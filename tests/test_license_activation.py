"""Gumroad key exchange (core/license_activation.py) against a local fake activation service,
and the service-key admin commands of packaging/license_keys.py. No real network."""
import base64
import importlib.util
import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import license
from core import license_activation as A
from tests.test_license import signed

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('license_keys', ROOT / 'packaging' / 'license_keys.py')
issuer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(issuer)

GUMROAD = '85DB562A-C11D4B06-A2335A6B-8C079166'


class Service(BaseHTTPRequestHandler):
    status, body, seen = 200, b'{}', []

    def _send(self, status, raw):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        type(self).seen.append((self.headers.get('Content-Type'), self.rfile.read(int(self.headers.get('Content-Length', 0)))))
        self._send(type(self).status, type(self).body)

    def do_GET(self):
        type(self).seen.append(('GET', self.path.encode()))
        self._send(type(self).status, type(self).body)

    def log_message(self, *args):
        pass


def serve(test, status=200, body=b'{}'):
    """A fake activation service answering every request with (status, body); returns (url, handler)."""
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    handler = type('Service', (Service,), {'status': status, 'body': body, 'seen': []})
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f'http://127.0.0.1:{server.server_port}/brainamon/activate.php', handler


class ExchangeTest(unittest.TestCase):
    def setUp(self):
        self.key = signed(Ed25519PrivateKey.generate())

    def test_recognizes_gumroad_keys_only(self):
        self.assertTrue(A.is_gumroad_key(GUMROAD))
        self.assertTrue(A.is_gumroad_key(' 85db562a-c11d4b06-\na2335a6b-8c079166 '))
        for text in (self.key, '', 'invalid', 'x' * 40, 'BRAINAMON1.abc.def', '85DB562A C11D4B06', None, 12):
            self.assertFalse(A.is_gumroad_key(text), text)

    def test_exchange_posts_the_key_and_returns_the_brainamon_key(self):
        url, service = serve(self, 200, {'key': self.key})
        self.assertEqual(A.exchange(' ' + GUMROAD + '\n', url), self.key)
        content_type, raw = service.seen[0]
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(json.loads(raw), {'key': GUMROAD})

    def test_service_refusal_reaches_the_user(self):
        url, _ = serve(self, 403, {'error': 'This purchase was refunded or disputed, so it cannot be activated.'})
        with self.assertRaises(A.ActivationError) as e:
            A.exchange(GUMROAD, url)
        self.assertEqual((str(e.exception), e.exception.status),
                         ('This purchase was refunded or disputed, so it cannot be activated.', 400))
        url, _ = serve(self, 400, {'error': 'x' * 1000})
        with self.assertRaises(A.ActivationError) as e:
            A.exchange(GUMROAD, url)
        self.assertEqual(len(str(e.exception)), A.MAX_MESSAGE)

    def test_unreachable_service(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        with self.assertRaises(A.ActivationError) as e:
            A.exchange(GUMROAD, f'http://127.0.0.1:{port}/brainamon/activate.php')
        self.assertEqual((str(e.exception), e.exception.status), (A.UNREACHABLE, 502))

    def test_unexpected_answers(self):
        for status, body in ((200, b'not json'), (200, b'{"key": "nope"}'), (500, b'<html>'), (200, b'[]'),
                             (200, json.dumps({'key': 'BRAINAMON1.' + 'A' * 20000}).encode())):
            url, _ = serve(self, status, body)
            with self.assertRaises(A.ActivationError) as e:
                A.exchange(GUMROAD, url)
            self.assertEqual((str(e.exception), e.exception.status), (A.UNEXPECTED, 502), body[:30])

    def test_only_https_or_loopback(self):
        with mock.patch.object(A.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            for url in ('http://fredtomas.com/brainamon/activate.php', 'ftp://127.0.0.1/x', 'file:///c:/x',
                        'http://127.0.0.1.example.com/x'):
                with self.assertRaises(A.ActivationError) as e:
                    A.exchange(GUMROAD, url)
                self.assertEqual(e.exception.status, 502)

    def test_default_address_is_the_https_service(self):
        self.assertEqual(A.ACTIVATION_URL, 'https://fredtomas.com/brainamon/activate.php')


class ServiceKeyToolsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)

    def test_keygen_service_writes_php_config_outside_the_repo(self):
        path = self.dir / 'brainamon-activation.php'
        public = issuer.generate_service(path, 'WJ3xqLN8aPbnaTRsSrU8oA==')
        text = path.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('<?php'))
        self.assertIn("'product_id' => 'WJ3xqLN8aPbnaTRsSrU8oA=='", text)
        seed = bytes.fromhex(text.split("'seed_hex' => '")[1][:64])
        self.assertEqual(Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex(), public)
        with self.assertRaises(FileExistsError):
            issuer.generate_service(path, 'WJ3xqLN8aPbnaTRsSrU8oA==')        # never replaces a service key
        with self.assertRaises(ValueError):
            issuer.generate_service(ROOT / 'build' / 'activation.php', 'WJ3xqLN8aPbnaTRsSrU8oA==')
        for bad in ('', "x'; echo 1; //", 'a' * 101):
            with self.assertRaises(ValueError):
                issuer.generate_service(self.dir / 'other.php', bad)

    def test_check_service_verifies_the_self_test(self):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes_raw().hex()
        sig = base64.urlsafe_b64encode(private.sign(b'BRAINAMON-SELFTEST')).rstrip(b'=').decode()
        good = {'php': '8.3.0', 'curl': True, 'public': public, 'sig': sig}
        url, service = serve(self, 200, good)
        with mock.patch.object(license, 'PUBLIC_KEYS', ('a' * 64, public)):
            self.assertTrue(issuer.check_service(url).startswith('Activation service OK: PHP 8.3.0'))
            self.assertEqual(service.seen[0], ('GET', b'/brainamon/activate.php?selftest=1'))
            for answer in ({**good, 'curl': False}, {**good, 'sig': sig[::-1]}, {'php': '8.3.0'}, []):
                url, _ = serve(self, 200, answer)
                with self.assertRaises(ValueError):
                    issuer.check_service(url)
        with mock.patch.object(license, 'PUBLIC_KEYS', ('a' * 64,)):
            url, _ = serve(self, 200, good)
            with self.assertRaisesRegex(ValueError, 'does not trust'):
                issuer.check_service(url)


if __name__ == '__main__':
    unittest.main()
