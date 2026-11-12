"""Loopback-only fake Drive for the debug Android SyncProbe. Never contacts Google.

Run from the repo: python -m tests.phone_sync_fixture
Then adb reverse tcp:18876 tcp:18876. Controls: POST /fixture with JSON fields
delay (seconds per media response), expired, failures, losePost (one lost response).
"""
import email
import email.policy
import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from cryptography.hazmat.primitives.asymmetric import ec
from core import sync_license
from library.mirror import MirrorKey

KEY = MirrorKey(bytes(range(32)))
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PAIR = dict(v=2, k=KEY.text(), f=KEY.fingerprint, l=sync_license.public(PRIVATE),
            g='fixture@example.test', e='fixture@example.test', ai={})
FILES, LOG, SESSIONS = {}, [], {}
CONTROL = dict(delay=0, expired=False, failures=0, losePost=False, loseChunk=False, loseGet=False, unauthorized=False)
LOCK = threading.RLock()


def add(logical, data, name=None):
    fid = str(len(FILES) + 1)
    FILES[fid] = dict(id=fid, name=name or KEY.name(logical), data=KEY.seal(logical, data))
    return fid


def reset():
    with LOCK:
        FILES.clear()
        add(sync_license.ACCESS_LOGICAL, sync_license.access_record(KEY, PRIVATE))
        parts = {}
        for i in range(12):
            logical = f'library/part-{i:03}.json.gz'
            import gzip
            raw = json.dumps([dict(uid=f'fixture-{i}-{j}', title='Synthetic item ' + str(j),
                                   text='Fixture content ' * 100) for j in range(250)]).encode()
            fid = add(logical, gzip.compress(raw))
            parts[logical] = dict(id=fid, n=KEY.name(logical), v=str(i))
        raw = b'{"categories":[],"count":3000}'
        fid = add('library/meta.json', raw)
        parts['library/meta.json'] = dict(id=fid, n=KEY.name('library/meta.json'), v='1')
        add('manifest.json', json.dumps(dict(format=1, reader=1, published=int(time.time()*1000), files=parts)).encode())
        vault = {}
        for i in range(30):
            raw = ('Fixture PC note ' + str(i) + '\n' + 'Synthetic content\n' * 100).encode()
            cid = KEY.content_id(raw)
            add('vault/blob/' + cid, raw, 'vb-' + cid)
            vault[f'pc-{i:02}.md'] = cid
        raw = b'Large synthetic vault note\n' * 160000
        cid = KEY.content_id(raw)
        add('vault/blob/' + cid, raw, 'vb-' + cid)
        vault['large.md'] = cid
        add('vault/index', json.dumps(dict(v=1, device='pc', files=vault, vault='fixture', generated=[])).encode(),
            'vi-' + KEY.name('vault/index/pc'))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, data, code=200, headers=None, lose=False):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data[:len(data)//2] if lose else data)
            if lose:
                self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/fixture':
            return self.reply(dict(pair=PAIR, control=CONTROL, requests=LOG, files=len(FILES)))
        if u.path == '/fixture/token':
            return self.reply(CONTROL)
        LOG.append(dict(time=time.time(), method='GET', path=self.path, range=self.headers.get('Range')))
        with LOCK:
            if CONTROL['unauthorized']:
                CONTROL['unauthorized'] = False
                return self.reply({}, 401)
            if CONTROL['failures']:
                CONTROL['failures'] -= 1
                return self.reply({}, 503)
            if u.path.endswith('/about'):
                return self.reply(dict(user=dict(emailAddress=PAIR['g'])))
            if u.path.endswith('/files'):
                q = parse_qs(u.query).get('q', [''])[0]
                match = re.search(r"name = '([^']+)'", q)
                return self.reply(dict(files=[dict(id=f['id'], name=f['name'], size=str(len(f['data'])))
                                             for f in FILES.values() if not match or f['name'] == match[1]]))
            f = FILES.get(u.path.rsplit('/', 1)[-1])
            data = f['data'] if f else None
        if CONTROL['delay']:
            time.sleep(CONTROL['delay'])
        if data is not None and self.headers.get('Range'):
            etag = '"' + hashlib.sha256(data).hexdigest() + '"'
            if self.headers.get('If-Range', etag) != etag:
                return self.reply(data, headers={'ETag': etag})
            start, end = map(int, self.headers['Range'][6:].split('-'))
            end = min(end + 1, len(data))
            if start >= len(data):
                return self.reply({}, 416)
            lose = CONTROL['loseGet'] and start >= 1024*1024
            if lose:
                CONTROL['loseGet'] = False
            return self.reply(data[start:end], 206, {'ETag': etag, 'Content-Range': f'bytes {start}-{end-1}/{len(data)}'}, lose)
        return self.reply(data if data is not None else {}, 200 if data is not None else 404)

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/fixture':
            patch = json.loads(data)
            if patch.pop('reset', False):
                reset()
            CONTROL.update(patch)
            return self.reply(CONTROL)
        if parse_qs(urlparse(self.path).query).get('uploadType') == ['resumable']:
            sid = str(len(SESSIONS) + 1)
            SESSIONS[sid] = dict(name=json.loads(data)['name'], data=bytearray(), size=int(self.headers['X-Upload-Content-Length']))
            LOG.append(dict(time=time.time(), method='SESSION', id=sid))
            return self.reply({}, headers={'Location': 'http://127.0.0.1:18876/upload/drive/v3/files?uploadType=resumable&upload_id=' + sid})
        message = email.message_from_bytes(('Content-Type: ' + self.headers['Content-Type'] + '\r\n\r\n').encode() + data,
                                          policy=email.policy.default)
        meta, body = list(message.iter_parts())
        name = json.loads(meta.get_payload(decode=True))['name']
        raw = body.get_payload(decode=True)
        with LOCK:
            fid = str(max(map(int, FILES), default=0) + 1)
            FILES[fid] = dict(id=fid, name=name, data=raw)
            LOG.append(dict(time=time.time(), method='POST', name=name, bytes=len(raw)))
        if CONTROL['losePost']:
            CONTROL['losePost'] = False
            self.close_connection = True
            return
        self.reply(dict(id=fid))

    def do_PUT(self):
        sid = parse_qs(urlparse(self.path).query)['upload_id'][0]
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        s = SESSIONS[sid]
        LOG.append(dict(time=time.time(), method='PUT', id=sid, range=self.headers['Content-Range']))
        if 'id' in s:
            return self.reply(dict(id=s['id']))
        if raw:
            start = int(self.headers['Content-Range'].split()[1].split('-')[0])
            if start != len(s['data']):
                return self.reply({}, 409)
            s['data'].extend(raw)
            if CONTROL['loseChunk']:
                CONTROL['loseChunk'] = False
                self.close_connection = True
                return
        if len(s['data']) < s['size']:
            return self.reply(b'', 308, {'Range': f"bytes=0-{len(s['data'])-1}"} if s['data'] else {})
        assert len(s['data']) == s['size']
        fid = str(max(map(int, FILES), default=0) + 1)
        FILES[fid] = dict(id=fid, name=s['name'], data=bytes(s['data']))
        s['id'] = fid
        LOG.append(dict(time=time.time(), method='POST', name=s['name'], bytes=len(s['data'])))
        self.reply(dict(id=fid))

    def do_PATCH(self):
        fid = urlparse(self.path).path.rsplit('/', 1)[-1]
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        with LOCK:
            if fid not in FILES:
                return self.reply({}, 404)
            FILES[fid]['data'] = raw
            LOG.append(dict(time=time.time(), method='PATCH', id=fid, bytes=len(raw)))
        self.reply(dict(id=fid))

    def do_DELETE(self):
        with LOCK:
            FILES.pop(urlparse(self.path).path.rsplit('/', 1)[-1], None)
        self.reply({})


if __name__ == '__main__':
    reset()
    print('Synthetic Drive listening on 127.0.0.1:18876', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 18876), Handler).serve_forever()
