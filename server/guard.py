"""Localhost guard: sensitive reads and mutations require the current-run bearer credential.

- Host header must be 127.0.0.1:<port> or localhost:<port> (blocks DNS rebinding).
- The trusted launcher/local tools provision the credential; HTTP never discovers it.
- Any method other than GET/HEAD must carry the header `X-CM: 1`. A web page on another
  origin cannot add a custom header without a CORS preflight, and this server answers no
  preflight, so other sites in Fred's browser cannot drive the API.
"""
import json
import secrets
import threading
from core import entitlements


class InstallGate:
    """Reserve shutdown before checking workers; reject new writes until exit."""
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.closing = False


class InstallGuard:
    def __init__(self, app, gate):
        self.app, self.gate = app, gate

    async def __call__(self, scope, receive, send):
        write = (scope['type'] == 'http' and scope['path'].startswith('/api/')
                 and scope['method'] not in ('GET', 'HEAD') and scope['path'] != '/api/app/update/install')
        if write:
            with self.gate.lock:
                denied = self.gate.closing
                if not denied:
                    self.gate.active += 1
            if denied:
                return await _deny(send, 'App is restarting for an update.')
        try:
            await self.app(scope, receive, send)
        finally:
            if write:
                with self.gate.lock:
                    self.gate.active -= 1


class LocalGuard:
    def __init__(self, app, hosts: set[str], token: str, dev_origins=()):
        self.app = app
        self.hosts = hosts
        self.token = ('Bearer ' + token).encode('ascii')
        self.origins = {'http://' + h for h in hosts} | set(dev_origins)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            headers = dict(scope.get('headers') or [])
            host = headers.get(b'host', b'').decode('latin-1').lower()
            if host not in self.hosts:
                return await _deny(send, 'host not allowed')
            origin = headers.get(b'origin', b'').decode('latin-1')
            if origin and origin not in self.origins:
                return await _deny(send, 'origin not allowed')
            protected = scope['path'].startswith(('/api/', '/thumb/', '/files/')) and scope['path'] != '/api/health'
            if protected and not secrets.compare_digest(headers.get(b'authorization', b''), self.token):
                return await _deny(send, 'local credential required')
            if protected and headers.get(b'x-brainamon-phone') == b'1' and not entitlements.feature_enabled('phone_sync'):
                return await _deny(send, 'license_required')
            if scope['method'] not in ('GET', 'HEAD') and headers.get(b'x-cm') != b'1':
                return await _deny(send, 'missing X-CM header')
        async def hardened(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [(b'x-frame-options', b'DENY'), (b'content-security-policy', b"frame-ancestors 'none'"), (b'referrer-policy', b'no-referrer')]
            await send(message)
        phone = entitlements.phone_request.set(scope['type'] == 'http' and dict(scope.get('headers') or []).get(b'x-brainamon-phone') == b'1')
        try:
            await self.app(scope, receive, hardened)
        finally:
            entitlements.phone_request.reset(phone)


async def _deny(send, why: str):
    body = json.dumps({'detail': why}).encode()
    await send({'type': 'http.response.start', 'status': 403,
                'headers': [(b'content-type', b'application/json'),
                            (b'content-length', str(len(body)).encode())]})
    await send({'type': 'http.response.body', 'body': body})


def allowed_hosts(port: int) -> set[str]:
    return {f'127.0.0.1:{port}', f'localhost:{port}'}
