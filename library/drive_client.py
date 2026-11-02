"""drive_client.py: Google sign-in and the Drive app data folder, for Upload to Google Drive.

No DB access and no app state: server/sync.py owns when this runs. Network only through urllib
(stdlib, as desktop/updater.py), so the installed build needs nothing new for it.

- Sign-in: OAuth 2.0 for installed apps. The system browser opens Google's consent page; Google
  redirects to a one-shot listener on http://127.0.0.1:<free port>/ (PKCE S256 + state). The
  token (with its refresh token) is saved as JSON in the local cloud folder, never in .env.
- Scope: drive.appdata only (Google lists it as non-sensitive): Brainamon sees its own hidden
  folder in the user's Drive and nothing else, and the user does not see the files in Drive.
- Files: list / download / upload (multipart up to 5 MB, resumable above, in 8 MiB chunks that resume from
  the server's Range after a dropped connection) / delete, all in the `appDataFolder` space.

The exact calls (projects/mobile-app/plans/03-drive-mirror.md) are written against Google's
documented REST endpoints; the live check needs Brainamon's sign-in app registered.
"""
import base64
import hashlib
import http.server
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.parser import BytesParser
from email.policy import default as email_policy
import random
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from core import private_storage

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
API = 'https://www.googleapis.com/drive/v3'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3'
SCOPE = 'https://www.googleapis.com/auth/drive.appdata'
SPACE = 'appDataFolder'

MULTIPART_MAX = 5 * 1024 * 1024        # Drive's limit for a multipart upload
CHUNK = 32 * 256 * 1024                # 8 MiB; resumable chunks must be multiples of 256 KiB
DELETE_BATCH_SIZE = 100
DELETE_WORKERS = 4
TIMEOUT = 60
RETRIES = 7                            # backoff 1, 2, 4 .. 32 s (Google's advice: cap near 32 to 64 s)
MAX_DELAY = 32
SIGN_IN_REQUIRED = 'Google Drive sign-in expired or was removed. Choose Sign in again and pick the same account. Your backup and settings stay as they are.'


class DriveError(Exception):
    """A Drive or sign-in call failed. `status` is the HTTP status when there was one; `reason` is Google's own
    reason string for it (`storageQuotaExceeded`, `rateLimitExceeded` ...), '' when there was none."""

    def __init__(self, msg: str, status: int = 0, reason: str = ''):
        super().__init__(msg)
        self.status = status
        self.reason = reason


def delete_files(client, ids, progress=None, stopped=None):
    """Use Drive batching when available; small alternate clients retain their delete interface."""
    try:
        if callable(getattr(client, 'delete_many', None)):
            return client.delete_many(ids, progress)
        for index, fid in enumerate(ids, 1):
            if client.stop.is_set():
                raise SignInCancelled('Google Drive work is stopping.')
            try:
                client.delete(fid)
            except DriveError as e:
                if e.status != 404:
                    raise
            if progress:
                progress(index, len(ids))
    except SignInCancelled:
        if stopped and client.stop.is_set():
            raise stopped() from None
        raise


class SignInCancelled(DriveError):
    pass


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _request(method: str, url: str, data: bytes | None = None, headers: dict | None = None,
             timeout: float = TIMEOUT, max_bytes: int | None = None):
    """(status, headers, body). HTTP errors come back as their status, not as exceptions;
    network errors raise OSError (URLError is one)."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read() if max_bytes is None else r.read(max_bytes + 1)
            if max_bytes is not None and len(body) > max_bytes:
                raise DriveError('Drive file exceeds the recovery download limit.')
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        body = e.read() if max_bytes is None else e.read(max_bytes + 1)
        if max_bytes is not None and len(body) > max_bytes:
            raise DriveError('Drive response exceeds the recovery download limit.')
        return e.code, dict(e.headers or {}), body or b''


def _form(url: str, fields: dict) -> dict:
    status, _, body = _request('POST', url, urllib.parse.urlencode(fields).encode(),
                               {'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        out = json.loads(body or b'{}')
    except ValueError:
        out = {}
    if status != 200:
        if url == TOKEN_URL and out.get('error') == 'invalid_grant':
            raise DriveError(SIGN_IN_REQUIRED, 401)
        raise DriveError(f"Google sign-in: {out.get('error_description') or out.get('error') or status}", status)
    return out


# ── Sign-in ──────────────────────────────────────────────────────────────────
class _Catch(http.server.BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(.25)
        def close():
            try:
                self.request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._deadline = threading.Timer(.25, close)
        self._deadline.daemon = True
        self._deadline.start()
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            self._deadline.cancel()

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if urllib.parse.urlparse(self.path).path != '/' or q.get('state') != [self.server.state] or not ('code' in q or 'error' in q):
            self.send_error(400, 'Invalid callback')
            return
        self.server.result = {k: v[0] for k, v in q.items()}
        ok = 'code' in self.server.result
        page = ('<h2>Brainamon is connected to Google Drive.</h2><p>You can close this tab.</p>' if ok else
                '<h2>Brainamon was not connected.</h2><p>You can close this tab and try again from Settings.</p>')
        body = f'<!doctype html><meta charset="utf-8"><title>Brainamon</title><body style="font:16px system-ui;padding:40px">{page}'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):      # no console noise
        pass


def sign_in(client_id: str, client_secret: str, open_url=webbrowser.open, timeout: float = 300,
            cancel: threading.Event | None = None, login_hint: str = '') -> dict:
    """Run the browser sign-in and return the token dict (see save_token). Blocks until Google
    redirects back, `timeout` seconds pass or `cancel` is set. `login_hint` (an email address) is Google's optional
    `login_hint` parameter: it pre-fills the account for a sign-in that renews the same one (S1); it constrains nothing,
    so the caller still checks which account answered."""
    if not client_id:
        raise DriveError('No Google sign-in app is configured for this build.')
    srv = http.server.HTTPServer(('127.0.0.1', 0), _Catch)
    srv.timeout = .1
    srv.result = None
    port = srv.server_address[1]
    redirect = f'http://127.0.0.1:{port}/'
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = srv.state = secrets.token_urlsafe(16)
    url = AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client_id, 'redirect_uri': redirect, 'response_type': 'code', 'scope': SCOPE,
        'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state,
        'access_type': 'offline', 'prompt': 'select_account consent',      # always Google's account chooser
        **({'login_hint': login_hint} if login_hint else {})})
    try:
        open_url(url)
        end = time.monotonic() + timeout
        while srv.result is None:
            if (cancel and cancel.is_set()) or time.monotonic() > end:
                raise SignInCancelled('Google sign-in was not finished.')
            srv.handle_request()
    finally:
        srv.server_close()
    if cancel and cancel.is_set():          # cancelled while the answer came in: no token exchange
        raise SignInCancelled('Google sign-in was cancelled.')
    got = srv.result
    if got.get('state') != state:
        raise DriveError('Google sign-in: the answer did not match the request.')
    if 'code' not in got:
        raise SignInCancelled(f"Google sign-in: {got.get('error') or 'cancelled'}")
    tok = _form(TOKEN_URL, {'client_id': client_id, 'client_secret': client_secret, 'code': got['code'],
                            'code_verifier': verifier, 'grant_type': 'authorization_code', 'redirect_uri': redirect})
    if cancel and cancel.is_set():
        raise SignInCancelled('Google sign-in was cancelled.')
    if not tok.get('refresh_token'):
        raise DriveError('Google sign-in returned no refresh token.')
    tok = _stamp(tok)
    tok['signed_in_at'] = time.time()       # when Google last asked the user: a Testing-mode app asks again 7 days later
    return tok


def _stamp(tok: dict) -> dict:
    tok = dict(tok)
    tok['expires_at'] = time.time() + float(tok.get('expires_in') or 3600) - 60
    return tok


def load_token(path: Path, *, readonly=False) -> dict | None:
    try:
        tok = json.loads(private_storage.read(path, readonly=readonly).decode('utf-8'))
        return tok if tok.get('refresh_token') else None
    except (FileNotFoundError, ValueError, AttributeError):
        return None


_SAVE_LOCK = threading.RLock()   # the mirror and the vault each hold a DriveClient on the same token file


def save_token(path: Path, tok: dict, expected=None) -> None:
    with _SAVE_LOCK:
        if expected is not None and load_token(path) != expected:
            raise SignInCancelled('The Google account session changed.')
        private_storage.write(path, json.dumps(tok).encode('utf-8'))


def revoke(tok: dict) -> None:
    """Best effort: tell Google to drop the grant (the local token is deleted by the caller)."""
    t = tok.get('refresh_token') or tok.get('access_token')
    if t:
        try:
            _request('POST', REVOKE_URL, urllib.parse.urlencode({'token': t}).encode(),
                     {'Content-Type': 'application/x-www-form-urlencoded'}, timeout=15)
        except OSError:
            pass


# ── Drive ────────────────────────────────────────────────────────────────────
class DriveClient:
    """The app data folder of one signed-in account. `token_path` is rewritten when the access
    token is refreshed. Calls may run from several threads at once (the vault's parallel uploads):
    the token refresh is behind a lock."""

    def __init__(self, client_id: str, client_secret: str, token: dict, token_path: Path | None = None):
        self.client_id, self.client_secret = client_id, client_secret
        self.tok = dict(token)
        self.token_path = token_path
        self._lock = threading.Lock()
        self._stored_token = dict(token)
        self.stop = threading.Event()
        self.request_timeout = TIMEOUT
        self.attempts = RETRIES

    # auth
    def _access(self) -> str:
        with self._lock:
            return self._access_locked()

    def _access_locked(self) -> str:
        with _SAVE_LOCK:
            current = self._check()
            if current is not None and current != self._stored_token:
                self.tok = dict(current)
                self._stored_token = dict(current)
        if not self.tok.get('access_token') or time.time() >= float(self.tok.get('expires_at') or 0):
            fresh = _form(TOKEN_URL, {'client_id': self.client_id, 'client_secret': self.client_secret,
                                      'refresh_token': self.tok['refresh_token'], 'grant_type': 'refresh_token'})
            with _SAVE_LOCK:
                current = self._check()
                # Another worker may have refreshed this session while the request was in flight.
                if current is not None and current != self._stored_token and current.get('access_token') and time.time() < float(current.get('expires_at') or 0):
                    self.tok = dict(current)
                else:
                    fresh.setdefault('refresh_token', self.tok['refresh_token'])
                    if self.tok.get('signed_in_at'):
                        fresh.setdefault('signed_in_at', self.tok['signed_in_at'])      # a refresh is not a sign-in
                    self.tok = _stamp(fresh)
                    if self.token_path:
                        save_token(self.token_path, self.tok, expected=current)
                self._stored_token = dict(self.tok)
        return self.tok['access_token']

    def _check(self):
        if self.stop.is_set():
            raise SignInCancelled('Google Drive work is stopping.')
        if self.token_path:
            with _SAVE_LOCK:
                current = load_token(self.token_path)
                if not current or current.get('refresh_token') != self._stored_token.get('refresh_token'):
                    raise SignInCancelled('The Google account session changed.')
                return current

    def _call(self, method: str, url: str, data: bytes | None = None, headers: dict | None = None,
              ok=(200,), timeout: float = TIMEOUT, max_bytes: int | None = None):
        """One API call with the bearer token, retried with backoff on 429 / 5xx / network errors, and on the 403
        Google gives a burst of calls (userRateLimitExceeded / rateLimitExceeded) when many upload at once."""
        delay = 1.0
        for attempt in range(self.attempts):
            self._check()
            access = self._access()
            h = dict(headers or {}, Authorization=f'Bearer {access}')
            try:
                status, rh, body = _request(method, url, data, h, min(timeout, self.request_timeout), **({'max_bytes': max_bytes} if max_bytes is not None else {}))
                self._check()
            except OSError as e:
                if attempt == self.attempts - 1:
                    raise DriveError(f'Google Drive is out of reach: {e}') from e
            else:
                if status in ok:
                    return status, rh, body
                if status == 401 and attempt == 0:
                    with self._lock:                       # expired early: refresh once (unless another call just did)
                        if self.tok.get('access_token') == access:
                            self.tok['access_token'] = ''
                    continue
                limited = status in (429, 500, 502, 503, 504) or (status == 403 and _rate_limited(body))
                if not limited or attempt == self.attempts - 1:
                    raise DriveError(f'Google Drive answered {status}: {_reason(body)}', status, _error_reason(body))
            self.stop.wait(delay + random.uniform(0, delay))        # jitter: parallel uploads do not retry in step
            delay = min(delay * 2, MAX_DELAY)
        raise DriveError('Google Drive did not answer.')

    def about(self) -> dict:
        """{'email', 'name', 'used', 'limit'} (bytes); fields Google leaves out come back empty."""
        _, _, body = self._call('GET', API + '/about?fields=user(emailAddress,displayName),storageQuota(limit,usage)')
        d = json.loads(body or b'{}')
        u, q = d.get('user') or {}, d.get('storageQuota') or {}
        return {'email': u.get('emailAddress', ''), 'name': u.get('displayName', ''),
                'used': int(q.get('usage') or 0), 'limit': int(q.get('limit') or 0)}

    def list(self, name: str | None = None, *, prefix: str | None = None) -> list[dict]:
        """Files in the app data folder, optionally matching a name or its prefix."""
        out, page = [], ''
        while True:
            q = {'spaces': SPACE, 'pageSize': '1000', 'fields': 'nextPageToken,files(id,name,size,version,modifiedTime)'}
            if name is not None or prefix is not None:
                escaped = (name if name is not None else prefix).replace('\\', '\\\\').replace("'", "\\'")
                q['q'] = f"name {'=' if name is not None else 'contains'} '{escaped}'"
            if page:
                q['pageToken'] = page
            _, _, body = self._call('GET', API + '/files?' + urllib.parse.urlencode(q))
            d = json.loads(body or b'{}')
            out += [{'id': f['id'], 'name': f['name'], 'size': int(f.get('size') or 0),
                     **{k: f[k] for k in ('version', 'modifiedTime') if k in f}} for f in d.get('files', [])]
            page = d.get('nextPageToken') or ''
            if not page:
                return out

    def download(self, file_id: str) -> bytes:
        """A file's content (the phone's change files are small; nothing big comes down here)."""
        _, _, body = self._call('GET', f'{API}/files/{file_id}?alt=media')
        return body

    def download_bounded(self, file_id: str, max_bytes: int) -> bytes:
        """Recovery reads authenticate untrusted files only after a bounded download."""
        if not file_id or len(file_id) > 256 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in file_id):
            raise DriveError('Invalid Drive file identity.')
        _, _, body = self._call('GET', f'{API}/files/{file_id}?alt=media', max_bytes=max_bytes)
        return body

    def delete(self, file_id: str) -> None:
        try:
            self._call('DELETE', f'{API}/files/{file_id}', ok=(200, 204))
        except DriveError as e:
            if e.status != 404:        # already gone is fine
                raise

    def delete_many(self, file_ids: list[str], progress=None) -> None:
        """Delete supplied IDs in four concurrent batches of up to 100; retry only failed parts."""
        ids = list(dict.fromkeys(file_ids))
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+', fid) for fid in ids):
            raise DriveError('Invalid Drive file identity.')
        done = 0
        window = DELETE_BATCH_SIZE * DELETE_WORKERS
        with ThreadPoolExecutor(DELETE_WORKERS, thread_name_prefix='cm-drive-delete') as pool:
            # Drain each window before retrying or starting more work; progress stays on the caller thread.
            for start in range(0, len(ids), window):
                self._check()
                batches = [ids[i:i + DELETE_BATCH_SIZE] for i in range(start, min(start + window, len(ids)), DELETE_BATCH_SIZE)]
                futures = {pool.submit(self._delete_batch, batch): batch for batch in batches}
                failed = []
                for future in as_completed(futures):
                    results = future.result()
                    self._check()
                    for i, fid in enumerate(futures[future]):
                        if results[i] in (200, 204, 404):
                            done += 1
                            if progress:
                                progress(done, len(ids))
                        else:
                            failed.append(fid)
                for fid in failed:
                    self._check()
                    self.delete(fid)
                    done += 1
                    if progress:
                        progress(done, len(ids))
            self._check()

    def _delete_batch(self, batch: list[str]) -> dict[int, int]:
        self._check()
        boundary = 'brainamon-' + secrets.token_hex(16)
        body = ''.join(f'--{boundary}\r\nContent-Type: application/http\r\nContent-ID: <delete-{i}>\r\n\r\nDELETE /drive/v3/files/{fid} HTTP/1.1\r\n\r\n'
                       for i, fid in enumerate(batch)) + f'--{boundary}--\r\n'
        _, headers, raw = self._call('POST', 'https://www.googleapis.com/batch/drive/v3', body.encode('ascii'),
                                    {'Content-Type': f'multipart/mixed; boundary={boundary}'}, max_bytes=2 * 1024 * 1024)
        content_type = _header(headers, 'Content-Type')
        message = BytesParser(policy=email_policy).parsebytes(f'Content-Type: {content_type}\r\n\r\n'.encode() + raw)
        results = {}
        if not message.is_multipart():
            raise DriveError('Invalid Drive batch response; retry to check remaining files.')
        for part in message.iter_parts():
            identity = re.fullmatch(r'<response-delete-(\d+)>', str(part.get('Content-ID', '')))
            payload = part.get_payload(decode=True)
            # application/http is normally an opaque MIME payload.
            status = re.match(rb'HTTP/\d(?:\.\d)? (\d{3})(?: |\r?\n)', payload or b'')
            if not identity or not status or int(identity[1]) >= len(batch) or int(identity[1]) in results:
                raise DriveError('Invalid Drive batch response; retry to check remaining files.')
            results[int(identity[1])] = int(status[1])
        if len(results) != len(batch):
            raise DriveError('Incomplete Drive batch response; retry to check remaining files.')
        return results

    def upload(self, name: str, data: bytes | None = None, path: Path | None = None,
               file_id: str = '', progress=None) -> str:
        """Create `name` in the app data folder (or replace the content of `file_id`) from `data`
        or the file at `path`; returns the Drive file id. `progress(sent_bytes)` is optional."""
        size = len(data) if data is not None else Path(path).stat().st_size
        if size <= MULTIPART_MAX:
            if data is None:
                data = Path(path).read_bytes()
            return self._multipart(name, data, file_id)
        return self._resumable(name, data, path, size, file_id, progress)

    def _multipart(self, name: str, data: bytes, file_id: str) -> str:
        meta = {'name': name} if file_id else {'name': name, 'parents': [SPACE]}
        b = secrets.token_hex(16)
        body = (f'--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n'
                f'--{b}\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{b}--'.encode()
        url = (f'{UPLOAD}/files/{file_id}' if file_id else f'{UPLOAD}/files') + '?uploadType=multipart&fields=id'
        _, _, out = self._call('PATCH' if file_id else 'POST', url, body,
                               {'Content-Type': f'multipart/related; boundary={b}'})
        return json.loads(out)['id']

    def _resumable(self, name: str, data, path, size: int, file_id: str, progress) -> str:
        meta = {'name': name} if file_id else {'name': name, 'parents': [SPACE]}
        url = (f'{UPLOAD}/files/{file_id}' if file_id else f'{UPLOAD}/files') + '?uploadType=resumable&fields=id'
        _, rh, _ = self._call('PATCH' if file_id else 'POST', url, json.dumps(meta).encode(),
                              {'Content-Type': 'application/json; charset=UTF-8',
                               'X-Upload-Content-Type': 'application/octet-stream',
                               'X-Upload-Content-Length': str(size)})
        session = _header(rh, 'Location')
        if not session:
            raise DriveError('Google Drive gave no upload session.')
        fh = open(path, 'rb') if data is None else None
        try:
            sent, fails = 0, 0
            while True:
                self._check()
                end = min(sent + CHUNK, size)
                if fh is not None:
                    fh.seek(sent)
                    chunk = fh.read(end - sent)
                else:
                    chunk = data[sent:end]
                try:
                    status, rh, body = _request('PUT', session, chunk, {
                        'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {sent}-{end - 1}/{size}'})
                except OSError:
                    status, rh, body = 0, {}, b''
                if status in (200, 201):
                    if progress:
                        progress(size)
                    return json.loads(body)['id']
                if status == 308:                    # this chunk landed (or part of it)
                    sent, fails = _resume_at(rh), 0
                elif status in (0, 500, 502, 503, 504):
                    fails += 1
                    if fails > RETRIES:
                        raise DriveError('The upload kept failing; it starts again on the next publish.')
                    self.stop.wait(min(30, 2 ** fails))
                    self._check()
                    sent = self._query(session, size)    # ask Google how much it has
                    if sent < 0:
                        continue
                else:
                    raise DriveError(f'Google Drive answered {status} during an upload: {_reason(body)}', status, _error_reason(body))
                if progress:
                    progress(sent)
        finally:
            if fh is not None:
                fh.close()

    def _query(self, session: str, size: int) -> int:
        self._check()
        try:
            status, rh, body = _request('PUT', session, b'', {'Content-Length': '0', 'Content-Range': f'bytes */{size}'})
        except OSError:
            return -1
        if status == 308:
            return _resume_at(rh)
        if status in (200, 201):
            return size
        return -1


def _header(h: dict, name: str) -> str:
    for k, v in h.items():
        if k.lower() == name.lower():
            return v
    return ''


def _resume_at(h: dict) -> int:
    """The next byte to send after a 308: one past the end of `Range: bytes=0-N` (0 without one)."""
    r = _header(h, 'Range')
    try:
        return int(r.split('-')[-1]) + 1 if r else 0
    except ValueError:
        return 0


def _rate_limited(body: bytes) -> bool:
    """A 403 that means slow down (try again), not a refusal."""
    try:
        e = json.loads(body).get('error') or {}
        reasons = [x.get('reason', '') for x in (e.get('errors') or []) if isinstance(x, dict)]
    except (ValueError, AttributeError):
        return False
    return any('ratelimit' in r.lower() for r in reasons)


def _reason(body: bytes) -> str:
    try:
        e = json.loads(body).get('error')
        return (e.get('message') if isinstance(e, dict) else str(e)) or 'error'
    except (ValueError, AttributeError):
        return (body or b'').decode('utf-8', 'replace')[:200] or 'error'


def _error_reason(body: bytes) -> str:
    """Google's reason string of an error answer (`error.errors[0].reason`, as `_rate_limited` reads it), else ''."""
    try:
        errors = (json.loads(body).get('error') or {}).get('errors') or []
        reason = errors[0].get('reason', '') if errors and isinstance(errors[0], dict) else ''
        return reason if isinstance(reason, str) else ''
    except (ValueError, AttributeError):
        return ''

