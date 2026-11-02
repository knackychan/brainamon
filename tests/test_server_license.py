"""Local license endpoints and the existing, still-unrestricted Cloud route."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import license
from core import license_activation
from tests.test_license_activation import GUMROAD, serve
from server.app import create_app
from tests.test_license import signed
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

W = {'X-CM': '1'}


class LicenseRoutesTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        private = Ed25519PrivateKey.generate()
        self.key = signed(private)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(license, 'PUBLIC_KEYS', (private.public_key().public_bytes_raw().hex(),)).start()
        mock.patch.object(license, 'LICENSE_PATH', self.root / 'local' / 'license.key').start()
        app = create_app(data_dir=self.root / 'data', port=8765, cloud_dir=self.root / 'cloud',
                         web_dist=self.root / 'no-web', cards_dir=self.root / 'no-cards')
        self.c = TestClient(app, base_url='http://127.0.0.1:8765')
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_status_activation_removal(self):
        self.assertEqual(self.c.get('/api/license').json()['status'], 'none')
        r = self.c.put('/api/license', json={'key': self.key}, headers=W)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'valid')
        self.assertNotIn(self.key, r.text)
        self.assertEqual(self.c.get('/api/license').json()['licensee'], 'Test Buyer')
        self.assertFalse((self.root / 'data' / 'license.key').exists())
        self.assertEqual(self.c.delete('/api/license', headers=W).json()['status'], 'none')

    def test_mutations_require_guard(self):
        self.assertEqual(self.c.put('/api/license', json={'key': self.key}).status_code, 403)
        self.assertEqual(self.c.delete('/api/license').status_code, 403)
        self.assertEqual(license.load().status, 'none')

    def test_invalid_replacement_preserves_license(self):
        self.c.put('/api/license', json={'key': self.key}, headers=W)
        self.assertEqual(self.c.put('/api/license', json={'key': 'invalid'}, headers=W).status_code, 400)
        for body in ({}, {'key': ['invalid']}, {'key': 'x' * 8193}, {'key': 123}):
            self.assertEqual(self.c.put('/api/license', json=body, headers=W).status_code, 422)
        self.assertEqual(self.c.get('/api/license').json()['status'], 'valid')

    def test_gumroad_key_is_exchanged_once_then_saved(self):
        url, service = serve(self, 200, {'key': self.key})
        with mock.patch.object(license_activation, 'ACTIVATION_URL', url):
            r = self.c.put('/api/license', json={'key': GUMROAD}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['licensee'], 'Test Buyer')
        self.assertEqual(json.loads(service.seen[0][1]), {'key': GUMROAD})
        self.assertEqual(license.load().status, 'valid')

    def test_gumroad_refusal_or_outage_keeps_current_license(self):
        self.c.put('/api/license', json={'key': self.key}, headers=W)
        url, _ = serve(self, 403, {'error': 'This purchase was refunded or disputed, so it cannot be activated.'})
        with mock.patch.object(license_activation, 'ACTIVATION_URL', url):
            r = self.c.put('/api/license', json={'key': GUMROAD}, headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertIn('refunded', r.json()['detail'])
        url, _ = serve(self, 500, b'<html>')
        with mock.patch.object(license_activation, 'ACTIVATION_URL', url):
            self.assertEqual(self.c.put('/api/license', json={'key': GUMROAD}, headers=W).status_code, 502)
        self.assertEqual(license.load().status, 'valid')

    def test_disk_errors_are_reported(self):
        with mock.patch.object(license, 'save', side_effect=OSError('private filesystem details')):
            r = self.c.put('/api/license', json={'key': self.key}, headers=W)
            self.assertEqual(r.status_code, 500)
            self.assertNotIn('private filesystem', r.text)
        with mock.patch.object(license, 'remove', side_effect=OSError):
            self.assertEqual(self.c.delete('/api/license', headers=W).status_code, 500)

    def test_cloud_status_and_cleanup_stay_available_while_sync_is_locked(self):
        self.assertEqual(license.load().status, 'none')
        self.assertEqual(self.c.get('/api/cloud').status_code, 200)
        with mock.patch.object(self.c.app.state.sync, 'connect') as connect:
            self.assertEqual(self.c.post('/api/cloud/connect', headers=W).status_code, 200)
            connect.assert_called_once()

    def test_backup_actions_without_license_keep_local_auth(self):
        svc = self.c.app.state.sync
        for endpoint, method in (('connect', 'connect'), ('switch', 'switch')):
            with mock.patch.object(svc, method) as action:
                self.assertEqual(self.c.post('/api/cloud/' + endpoint).status_code, 403)
                action.assert_not_called()
                self.assertEqual(self.c.post('/api/cloud/' + endpoint, headers=W).status_code, 200)
                action.assert_called_once()
        with mock.patch.object(type(svc), 'running', new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(svc, 'upload_now') as upload:
            self.assertEqual(self.c.post('/api/cloud/publish', headers=W).status_code, 200)
            upload.assert_called_once()
        self.assertEqual(self.c.post('/api/cloud/pair', headers=W).status_code, 200)
        with mock.patch.object(svc, 'connect') as connect:
            self.assertEqual(self.c.post('/api/cloud/vault/connect', headers=W).status_code, 200)
            connect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
