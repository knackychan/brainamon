"""`py -m server.dev_drive`: the backend with a stand-in for Google Drive, for trying the phone on
the mirror (projects/mobile-app/PLAN.md Phase 4) before Brainamon's Google sign-in app exists.
Development only; nothing in the app imports this.

- A fake Drive (the app data folder calls the PC and the phone make: list, find by name, download,
  multipart and resumable upload, delete) on 127.0.0.1:18766, kept in local/dev-drive/ so it
  survives a restart. It answers CORS, so the phone page can call it.
- The normal backend on 127.0.0.1:18765, with the Drive calls pointed at the fake, the sign-in
  skipped and its own cloud folder (local/dev-cloud/: mirror key and token), so the real Google
  sign-in and key are never touched. The pairing QR then carries the fake Drive's address (`d`),
  and the phone skips Google too.

With --fake-ai (Phase 5) the same server also stands in for the AI providers under /ai/anthropic and
/ai/openai (streamed answers that cite the items they were sent, a synthesized note, hashed
embeddings of --fake-dim numbers, and Wiskit Deep's tool rounds: search, read, then an answer citing
what the tools returned), and the pairing QR sends the phone there (`x`) with stand-in keys
for the ticked providers, so Wiskit, Smart search and Synthesize run with no key and no cost.

On a phone over USB: adb reverse tcp:18765 tcp:18765 and adb reverse tcp:18766 tcp:18766, then
Settings > Cloud > Upload to Google Drive, Show pairing QR, scan it.
"""
import argparse
import email.parser
import hashlib
import json
import re
import time
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 18766
FAKE_DIM = 1536         # text-embedding-3-small


# ── the stand-in AI providers (--fake-ai) ────────────────────────────────────
def fake_vec(text: str, dim: int) -> list:
    """Words hashed into `dim` buckets: texts that share words point the same way."""
    v = [0.0] * dim
    for w in re.findall(r'\w+', text.lower()):
        h = hashlib.sha256(w.encode('utf-8')).digest()
        v[(h[0] * 256 + h[1]) % dim] += 1.0
    return v


def fake_answer(prompt: str) -> str:
    """A Wiskit answer citing the first items and note of the context it was sent."""
    ids = list(dict.fromkeys(re.findall(r'\[id (\d+)\]', prompt)))[:3]
    notes = list(dict.fromkeys(re.findall(r'\[note: ([^\]]+)\]', prompt)))[:1]
    q = re.search(r'^Question: (.*)$', prompt, re.MULTILINE)
    out = f"Stand-in answer (development, no AI was called) to: {q.group(1) if q else 'your question'}.\n\n"
    out += ''.join(f'- Item {i} looks relevant [id {i}].\n' for i in ids) or 'Nothing relevant was sent.\n'
    if notes:
        out += f'\nYour note covers it too [note: {notes[0]}].\n'
    return out


def fake_note(prompt: str) -> str:
    topic = re.search(r'on(?: the topic)?: "([^"]*)"', prompt)
    ids = list(dict.fromkeys(re.findall(r'^### Source (\d+)', prompt, re.MULTILINE)))
    old = re.search(r'# Current note\n\n(.*?)\n\n# New sources', prompt, re.DOTALL)
    head = old.group(1).split('## Sources')[0].rstrip() if old else f"## {topic.group(1) if topic else 'Note'}\n\nStand-in synthesis (development, no AI was called)."
    prev = re.findall(r'^- (\d+)$', old.group(1), re.MULTILINE) if old else []
    return head + '\n\n## Sources\n' + ''.join(f'- {i}\n' for i in dict.fromkeys(prev + ids))


def fake_agent(provider: str, req: dict) -> dict:
    """Wiskit Deep's stand-in (plans/07-wiskit-deep.md): round 1 searches the library for the
    question, round 2 reads the first three items found, then (or whenever tools are forbidden) an
    answer citing what the tools returned. Anthropic Messages with tools, or the OpenAI Responses API
    (its reasoning item must come back on the next round, as store=false requires)."""
    texts = []
    if provider == 'anthropic':
        msgs = req.get('messages') or []
        rounds = sum(1 for m in msgs if m.get('role') == 'assistant' and not isinstance(m.get('content'), str))   # tool rounds, not earlier turns
        for m in msgs:
            c = m.get('content')
            texts += [c] if isinstance(c, str) else [str(b.get('content', '')) for b in c if b.get('type') == 'tool_result']
        last = (req.get('tool_choice') or {}).get('type') == 'none'
    else:
        items = req.get('input') or []
        rounds = sum(1 for i in items if i.get('type') == 'function_call')
        if rounds and sum(1 for i in items if i.get('type') == 'reasoning') != rounds:
            return {'error': {'message': 'reasoning items missing (store=false needs them back)'}}
        for i in items:
            texts.append(str(i['content']) if 'role' in i else str(i.get('output', '')))
        last = req.get('tool_choice') == 'none'
    prompt = '\n'.join(texts)
    call = None
    if not last and rounds == 0:
        q = re.search(r'^Question: (.*)$', prompt, re.MULTILINE)
        call = ('search_library', {'query': q.group(1) if q else 'library'})
    elif not last and rounds == 1:
        ids = [int(i) for i in dict.fromkeys(re.findall(r'\[id (\d+)\]', texts[-1]))][:3]
        if ids:
            call = ('read_items', {'ids': ids})
    if call is None:
        text = fake_answer(prompt)
        return ({'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]} if provider == 'anthropic'
                else {'status': 'completed', 'output': [{'type': 'message', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}]})
    if provider == 'anthropic':
        return {'stop_reason': 'tool_use', 'content': [{'type': 'text', 'text': 'Looking in the library.'},
                                                       {'type': 'tool_use', 'id': f'toolu_{rounds}', 'name': call[0], 'input': call[1]}]}
    return {'status': 'completed', 'output': [{'type': 'message', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Looking in the library.'}]},
                       {'type': 'reasoning', 'id': f'rs_{rounds}', 'summary': [], 'encrypted_content': 'stand-in'},
                       {'type': 'function_call', 'id': f'fc_{rounds}', 'call_id': f'call_{rounds}', 'name': call[0],
                        'arguments': json.dumps(call[1])}]}


def fake_agent_events(provider, out, model):
    """Independent wire fixtures, including explicit completion and replay items."""
    if provider == 'anthropic':
        yield {'type': 'message_start', 'message': {'id': 'msg_fake', 'type': 'message', 'role': 'assistant',
            'model': model, 'content': [], 'stop_reason': None, 'stop_sequence': None,
            'usage': {'input_tokens': 1, 'output_tokens': 0}}}
        for index, block in enumerate(out['content']):
            initial = dict(block)
            if block['type'] == 'text':
                initial['text'] = ''
            elif block['type'] == 'tool_use':
                initial['input'] = {}
            yield {'type': 'content_block_start', 'index': index, 'content_block': initial}
            if block['type'] == 'text':
                for text in re.findall(r'\S+\s*', block['text']):
                    yield {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'text_delta', 'text': text}}
            elif block['type'] == 'tool_use':
                arg = json.dumps(block['input'])
                for text in (arg[:len(arg)//2], arg[len(arg)//2:]):
                    yield {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'input_json_delta', 'partial_json': text}}
            yield {'type': 'content_block_stop', 'index': index}
        yield {'type': 'message_delta', 'delta': {'stop_reason': out['stop_reason'], 'stop_sequence': None}, 'usage': {'output_tokens': 1}}
        yield {'type': 'message_stop'}
    else:
        response = {'id': 'resp_fake', 'object': 'response', 'status': 'in_progress', 'output': [], 'model': model}
        yield {'type': 'response.created', 'response': dict(response)}
        for index, original in enumerate(out['output']):
            item = dict(original)
            item.setdefault('id', f'item_{index}')
            item['status'] = 'completed'
            yield {'type': 'response.output_item.added', 'output_index': index, 'item': dict(item, status='in_progress')}
            if item['type'] == 'message':
                for ci, content in enumerate(item['content']):
                    content.setdefault('annotations', [])
                    yield {'type': 'response.content_part.added', 'output_index': index, 'item_id': item['id'], 'content_index': ci, 'part': dict(content, text='')}
                    for text in re.findall(r'\S+\s*', content['text']):
                        yield {'type': 'response.output_text.delta', 'output_index': index, 'item_id': item['id'], 'content_index': ci, 'delta': text}
            yield {'type': 'response.output_item.done', 'output_index': index, 'item': item}
            response['output'].append(item)
        response['status'] = 'completed'
        yield {'type': 'response.completed', 'response': response}


class FakeDrive:
    """The app data folder, as files in `root` (an index of id -> name, the bytes per id)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / 'index.json'
        self.lock = threading.Lock()
        try:
            self.index = json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.index = {}
        self.n = max([int(k[1:]) for k in self.index if k[1:].isdigit()] or [0])
        self.sessions: dict[str, dict] = {}

    def _save(self):
        self.index_path.write_text(json.dumps(self.index), encoding='utf-8')

    def put(self, name: str, data: bytes, file_id: str = '') -> str:
        with self.lock:
            if not file_id:
                self.n += 1
                file_id = f'f{self.n}'
            elif file_id not in self.index:
                raise KeyError(file_id)
            (self.root / f'{file_id}.bin').write_bytes(data)
            self.index[file_id] = name
            self._save()
            return file_id

    def get(self, file_id: str) -> bytes:
        with self.lock:
            return (self.root / f'{file_id}.bin').read_bytes()

    def delete(self, file_id: str) -> bool:
        with self.lock:
            if self.index.pop(file_id, None) is None:
                return False
            (self.root / f'{file_id}.bin').unlink(missing_ok=True)
            self._save()
            return True

    def files(self, name: str = '') -> list[dict]:
        with self.lock:
            out = [{'id': i, 'name': n, 'size': str((self.root / f'{i}.bin').stat().st_size)}
                   for i, n in self.index.items() if not name or n == name]
        return out


def handler(drive: FakeDrive):
    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes = b'', ctype: str = 'application/json', extra: dict | None = None):
            self.send_response(code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Expose-Headers', 'Location, Range, Content-Length')
            self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, Content-Range, X-Upload-Content-Length, '
                             'x-api-key, anthropic-version, anthropic-dangerous-direct-browser-access')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode())

        def _body(self) -> bytes:
            n = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(n) if n else b''

        def _authed(self) -> bool:
            if not (self.headers.get('Authorization') or '').startswith('Bearer '):
                self._json(401, {'error': {'message': 'no token'}})
                return False
            return True

        def do_OPTIONS(self):
            self._send(204, extra={'Access-Control-Allow-Methods': 'GET, POST, PATCH, PUT, DELETE, OPTIONS',
                                   'Access-Control-Max-Age': '600'})

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if not self._authed():
                return
            if u.path == '/drive/v3/about':
                return self._json(200, {'user': {'emailAddress': self.server.account, 'displayName': self.server.account.split('@')[0]},
                                        'storageQuota': {'limit': str(15 * 2**30), 'usage': '0'}})
            if u.path == '/drive/v3/files':
                m = re.fullmatch(r"\s*name\s*(=|contains)\s*'((?:\\.|[^'\\])*)'\s*", q.get('q', ''))
                files = drive.files()
                if m:
                    name = re.sub(r"\\(.)", r"\1", m.group(2))
                    files = [f for f in files if (f['name'] == name if m.group(1) == '=' else f['name'].startswith(name))]
                return self._json(200, {'files': files})
            m = re.match(r'^/drive/v3/files/([\w-]+)$', u.path)
            if m and q.get('alt') == 'media':
                try:
                    return self._send(200, drive.get(m.group(1)), 'application/octet-stream')
                except OSError:
                    return self._json(404, {'error': {'message': 'not found'}})
            self._json(404, {'error': {'message': 'not here'}})

        def do_DELETE(self):
            if not self._authed():
                return
            m = re.match(r'^/drive/v3/files/([\w-]+)$', urllib.parse.urlparse(self.path).path)
            ok = bool(m) and drive.delete(m.group(1))
            self._send(204 if ok else 404)

        def _multipart(self, file_id: str = ''):
            raw = self._body()
            ctype = self.headers.get('Content-Type', '')
            msg = email.parser.BytesParser().parsebytes(b'Content-Type: ' + ctype.encode() + b'\r\n\r\n' + raw)
            parts = msg.get_payload()
            meta = json.loads(parts[0].get_payload(decode=True) or b'{}')
            data = parts[1].get_payload(decode=True) or b''
            try:
                fid = drive.put(meta.get('name') or drive.index.get(file_id, ''), data, file_id)
            except KeyError:
                return self._json(404, {'error': {'message': 'not found'}})
            self._json(200, {'id': fid, 'name': drive.index[fid]})

        def _ai(self, path: str):
            """The stand-in Anthropic Messages / OpenAI Chat Completions and embeddings, and Wiskit Deep's tool
            rounds (Anthropic Messages with tools, OpenAI Responses)."""
            req = json.loads(self._body() or b'{}')
            if path == '/ai/openai/v1/embeddings':
                return self._json(200, {'data': [{'index': i, 'embedding': fake_vec(t, self.server.fake_dim)}
                                                 for i, t in enumerate(req.get('input') or [])]})
            anthropic = path == '/ai/anthropic/v1/messages'
            if path == '/ai/openai/v1/responses' or (anthropic and req.get('tools')):
                out = fake_agent('anthropic' if anthropic else 'openai', req)
                if not req.get('stream') or 'error' in out:
                    return self._json(400 if 'error' in out else 200, out)
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.close_connection = True
                self.end_headers()
                for seq, event in enumerate(fake_agent_events('anthropic' if anthropic else 'openai', out, req.get('model', 'fake'))):
                    event.setdefault('sequence_number', seq)
                    if event['type'] in ('message_stop', 'response.completed'):
                        hold = getattr(self.server, 'ai_terminal_gate', None)
                        if hold is not None:
                            hold.wait(10)
                    try:
                        self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                        self.wfile.flush()
                    except ConnectionError:
                        break
                return
            msgs = req.get('messages') or []
            prompt = str(msgs[-1].get('content') if msgs else '')
            if not anthropic and path != '/ai/openai/v1/chat/completions':
                return self._json(404, {'error': {'message': 'not here'}})
            text = fake_answer(prompt) if 'Answer this question:' in prompt else fake_note(prompt)
            if not req.get('stream'):
                return self._json(200, {'content': [{'type': 'text', 'text': text}]} if anthropic
                                  else {'choices': [{'message': {'role': 'assistant', 'content': text}}]})
            parts = re.findall(r'\S+\s*', text)
            body = b''
            for w in parts:
                ev = ({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': w}} if anthropic
                      else {'choices': [{'index': 0, 'delta': {'content': w}}]})
                body += (b'event: content_block_delta\n' if anthropic else b'') + b'data: ' + json.dumps(ev).encode() + b'\n\n'
            body += b'event: message_stop\ndata: {"type":"message_stop"}\n\n' if anthropic else b'data: [DONE]\n\n'
            time.sleep(0.2)
            self._send(200, body, 'text/event-stream')

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if u.path.startswith('/ai/') and getattr(self.server, 'fake_ai', False):
                return self._ai(u.path)
            if not self._authed():
                return
            if u.path == '/batch/drive/v3':
                msg = email.parser.BytesParser().parsebytes(
                    b'Content-Type: ' + self.headers.get('Content-Type', '').encode() + b'\r\n\r\n' + self._body())
                if not msg.is_multipart():
                    return self._json(400, {'error': {'message': 'invalid batch'}})
                replies = []
                for part in msg.get_payload():
                    identity = re.fullmatch(r'<delete-(\d+)>', part.get('Content-ID', ''))
                    request = re.fullmatch(rb'DELETE /drive/v3/files/([\w-]+) HTTP/1\.1\r?\n', part.get_payload(decode=True) or b'')
                    if not identity or not request:
                        return self._json(400, {'error': {'message': 'invalid batch part'}})
                    status = 204 if drive.delete(request[1].decode()) else 404
                    replies.append(f'--fixture-batch\r\nContent-Type: application/http\r\nContent-ID: <response-delete-{identity[1]}>\r\n\r\nHTTP/1.1 {status} Result\r\n\r\n')
                return self._send(200, (''.join(replies) + '--fixture-batch--\r\n').encode(), 'multipart/mixed; boundary=fixture-batch')
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path == '/upload/drive/v3/files' and q.get('uploadType') == 'multipart':
                return self._multipart()
            if u.path == '/upload/drive/v3/files' and q.get('uploadType') == 'resumable':
                return self._start_resumable('')
            self._json(404, {'error': {'message': 'not here'}})

        def do_PATCH(self):
            if not self._authed():
                return
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            m = re.match(r'^/upload/drive/v3/files/([\w-]+)$', u.path)
            if m and q.get('uploadType') == 'multipart':
                return self._multipart(m.group(1))
            if m and q.get('uploadType') == 'resumable':
                return self._start_resumable(m.group(1))
            self._json(404, {'error': {'message': 'not here'}})

        def _start_resumable(self, file_id: str):
            meta = json.loads(self._body() or b'{}')
            sid = f's{len(drive.sessions) + 1}'
            drive.sessions[sid] = {'name': meta.get('name') or drive.index.get(file_id, ''), 'file_id': file_id,
                                   'size': int(self.headers.get('X-Upload-Content-Length') or 0), 'data': bytearray()}
            self._send(200, extra={'Location': f'http://127.0.0.1:{self.server.server_address[1]}/upload/session/{sid}'})

        def do_PUT(self):
            m = re.match(r'^/upload/session/(\w+)$', urllib.parse.urlparse(self.path).path)
            s = drive.sessions.get(m.group(1)) if m else None
            if s is None:
                return self._json(404, {'error': {'message': 'no session'}})
            s['data'] += self._body()
            if len(s['data']) < s['size']:
                return self._send(308, extra={'Range': f"bytes=0-{len(s['data']) - 1}"})
            fid = drive.put(s['name'], bytes(s['data']), s['file_id'])
            self._json(200, {'id': fid})
    return H


def signed_in_account(data_dir: Path) -> str:
    """The Google account the app last signed in with (DB setting `cloud_account`), read-only; '' if none."""
    from core.db import ReadOnlyDatabase
    from server import settings
    db_path = Path(data_dir) / settings.DB_NAME
    if not db_path.is_file():
        return ''
    try:
        return ReadOnlyDatabase(db_path).get_setting('cloud_account', '')
    except Exception:
        return ''


def serve(root: Path, port: int = PORT, fake_ai: bool = False, fake_dim: int = FAKE_DIM, account: str = '') -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(('127.0.0.1', port), handler(FakeDrive(root)))
    srv.fake_ai, srv.fake_dim, srv.account = fake_ai, fake_dim, account
    threading.Thread(target=srv.serve_forever, name='dev-drive', daemon=True).start()
    return srv


def main():
    import uvicorn
    from core import app_paths, config
    from library import drive_client
    from server import settings
    from server.app import create_app

    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--data', help='the data folder (default: the app\'s)')
    ap.add_argument('--fake-ai', action='store_true', help='stand in for Anthropic and OpenAI too (no key, no cost)')
    ap.add_argument('--fake-dim', type=int, default=FAKE_DIM, help='numbers in a stand-in embedding (the library\'s vector size)')
    a = ap.parse_args()
    config.load_env()
    local = Path(app_paths.LOCAL)
    serve(local / 'dev-drive', fake_ai=a.fake_ai, fake_dim=a.fake_dim,
          account=signed_in_account(Path(a.data) if a.data else settings.DATA_DIR))
    base = f'http://127.0.0.1:{PORT}'
    if a.fake_ai:
        from server.routes import cloud
        cloud.DEV_AI = base + '/ai'
    drive_client.API, drive_client.UPLOAD = base + '/drive/v3', base + '/upload/drive/v3'
    drive_client.BATCH = base + '/batch/drive/v3'
    drive_client.sign_in = lambda *a, **k: {'access_token': 'dev', 'refresh_token': 'dev', 'expires_at': 4e9}
    drive_client.revoke = lambda tok: None
    config.google_client = lambda: ('dev', 'dev')
    print(f'Fake Google Drive on {base} (files in {local / "dev-drive"}); backend on http://127.0.0.1:{settings.PORT}')
    app = create_app(data_dir=Path(a.data) if a.data else None, cloud_dir=local / 'dev-cloud')
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level='warning')


if __name__ == '__main__':
    main()
