"""Offline permanent licensing and admin issuance; all keys and files are temporary."""
import base64
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import entitlements, license

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('license_keys', ROOT / 'packaging' / 'license_keys.py')
issuer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(issuer)


def signed(private, **changes):
    payload = {'v': 1, 'id': 'test-license', 'ed': 'cloud', 'to': 'Test Buyer',
               'email': 'buyer@example.test', 'iss': '2026-10-22', 'exp': None, **changes}
    return signed_payload(private, payload)


def signed_payload(private, payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
    message = f'{license.PREFIX}.{body}'
    signature = base64.urlsafe_b64encode(private.sign(message.encode())).rstrip(b'=').decode()
    return f'{message}.{signature}'


class LicenseTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.path = Path(td.name) / 'local' / 'license.key'
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes_raw().hex()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(license, 'PUBLIC_KEYS', (public,)).start()
        mock.patch.object(license, 'LICENSE_PATH', self.path).start()
        self.key = signed(self.private)

    def test_permanent_license_and_whitespace(self):
        lic = license.parse(' \n' + self.key[:25] + '\n' + self.key[25:] + ' ')
        self.assertEqual((lic.status, lic.licensee, lic.key_id), ('valid', 'Test Buyer', 'test-license'))
        self.assertEqual(lic.issued, '2026-10-22')
        self.assertNotIn('key', lic.view())

    def test_no_license(self):
        self.assertEqual(license.load().status, 'none')
        self.assertEqual(license.parse(' \n ').status, 'none')
        self.assertFalse(entitlements.is_pro())

    def test_bad_input_never_grants_license(self):
        damaged = self.key.replace('BRAINAMON1.', 'BRAINAMON1.!', 1)
        for text in (None, 123, 'BRAINAMON1.a.a', 'x.y.z', 'x' * 8193, 'BRAINAMON1.é.abc', damaged):
            with self.subTest(text=repr(text)[:35]):
                self.assertEqual(license.parse(text).status, 'invalid')

    def test_signature_tampering_and_unknown_issuer(self):
        other = Ed25519PrivateKey.generate()
        for key in (signed(other), self.key[:-5] + 'AAAAA'):
            self.assertEqual(license.parse(key).status, 'invalid')
        with mock.patch.object(license, 'PUBLIC_KEYS', ()):
            self.assertIn('not configured', license.parse(self.key).error)
        with mock.patch.object(license, 'PUBLIC_KEYS', ('not-hex', self.private.public_key().public_bytes_raw().hex())):
            self.assertEqual(license.parse(self.key).status, 'valid')

    def test_signed_invalid_claims_are_rejected(self):
        for changes in ({'v': True}, {'v': 2}, {'ed': 'local'}, {'to': ''}, {'id': ''},
                        {'to': 12}, {'email': None}, {'iss': '20261022'}, {'iss': 'bad-date'},
                        {'email': 'x' * 321}, {'exp': '2030-01-01'}):
            with self.subTest(changes=changes):
                self.assertEqual(license.parse(signed(self.private, **changes)).status, 'invalid')
        self.assertEqual(license.parse(signed_payload(self.private, [])).status, 'invalid')

    def test_activate_reload_replace_and_remove(self):
        license.save(self.key)
        self.assertEqual(license.load(), license.parse(self.key))
        self.assertTrue(entitlements.is_pro())
        with self.assertRaises(ValueError):
            license.save('bad replacement')
        self.assertEqual(license.load().status, 'valid')
        license.remove()
        license.remove()
        self.assertFalse(self.path.exists())
        self.assertFalse(entitlements.is_pro())

    def test_atomic_write_failure_keeps_current_license(self):
        license.save(self.key)
        before = self.path.read_bytes()
        with mock.patch.object(license.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                license.save(signed(self.private, to='Replacement Buyer'))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_corrupt_saved_file_does_not_unlock(self):
        self.path.parent.mkdir()
        for data in (b'\xff', b'x' * 9000, b'bad license'):
            self.path.write_bytes(data)
            self.assertEqual(license.load().status, 'invalid')
            self.assertFalse(entitlements.is_pro())

    def test_all_features_are_available_with_or_without_a_legacy_receipt(self):
        for active in (False, True):
            if active:
                license.save(self.key)
            self.assertTrue(entitlements.feature_enabled('phone_sync'))
            self.assertEqual(entitlements.is_pro(), active)
            for feature in ('cloud', 'mobile', 'sync', 'ai', 'voice_notes', 'export'):
                self.assertTrue(entitlements.feature_enabled(feature))

    def test_issuer_generates_encrypted_key_and_issues_valid_license(self):
        secret = self.path.parent.parent / 'issuer.pem'
        public = issuer.generate(secret, b'test password')
        self.assertIn(b'ENCRYPTED PRIVATE KEY', secret.read_bytes())
        with self.assertRaises(TypeError):
            serialization.load_pem_private_key(secret.read_bytes(), password=None)
        with self.assertRaises(FileExistsError):
            issuer.generate(secret, b'test password')
        with mock.patch.object(license, 'PUBLIC_KEYS', (public,)):
            key = issuer.issue(secret, b'test password', 'Buyer')
            lic = license.parse(key)
            self.assertEqual((lic.status, lic.licensee), ('valid', 'Buyer'))
            self.assertTrue(lic.key_id)
            with self.assertRaises(ValueError):
                issuer.issue(secret, b'wrong password', 'Buyer')
            with self.assertRaises(ValueError):
                issuer.issue(secret, b'test password', '')
        with self.assertRaisesRegex(ValueError, 'Pin'):
            issuer.issue(secret, b'test password', 'Buyer')

    def test_issuer_rejects_secrets_in_repo_and_empty_passwords(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            issuer.generate(ROOT / 'local' / 'issuer-test.pem', b'test password')
        with self.assertRaisesRegex(ValueError, 'password'):
            issuer.generate(self.path.parent.parent / 'issuer.pem', b'')

    def test_interactive_issuer_setup_and_reuse(self):
        root = self.path.parent.parent / 'checkout'
        source = root / 'core' / 'license.py'
        source.parent.mkdir(parents=True)
        source.write_text('PUBLIC_KEYS: tuple[str, ...] = ()\n', encoding='utf-8')
        secret = self.path.parent.parent / 'issuer.pem'
        with mock.patch.object(issuer, 'ROOT', root), mock.patch.object(license, 'PUBLIC_KEYS', ()), \
                mock.patch('builtins.input', return_value='Trial Buyer'), \
                mock.patch.object(issuer.getpass, 'getpass', return_value='test password'), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            issuer.interactive(secret)
            first_private = secret.read_bytes()
            first_source = source.read_bytes()
            self.assertIn(b'ENCRYPTED PRIVATE KEY', first_private)
            self.assertIn(license.PUBLIC_KEYS[0], source.read_text())
            issuer.interactive(secret)
            self.assertEqual(secret.read_bytes(), first_private)
            self.assertEqual(source.read_bytes(), first_source)
            keys = [line for line in output.getvalue().splitlines() if line.startswith(license.PREFIX + '.')]
            self.assertEqual(len(keys), 2)
            self.assertNotEqual(keys[0], keys[1])
            for key in keys:
                self.assertEqual(license.parse(key).licensee, 'Trial Buyer')
            with mock.patch.object(issuer.getpass, 'getpass', return_value='wrong password'):
                with self.assertRaises(ValueError):
                    issuer.interactive(secret)
            self.assertEqual(source.read_bytes(), first_source)

    def test_interactive_never_replaces_existing_issuer(self):
        secret = self.path.parent.parent / 'new-issuer.pem'
        with mock.patch('builtins.input', return_value='Trial Buyer'):
            with self.assertRaisesRegex(ValueError, 'already configured'):
                issuer.interactive(secret)
        self.assertFalse(secret.exists())
        with self.assertRaisesRegex(ValueError, 'different issuer'):
            issuer.configure_public_key('another issuer')

    def test_issuer_configuration_failure_keeps_source_and_trust(self):
        root = self.path.parent.parent / 'checkout'
        source = root / 'core' / 'license.py'
        source.parent.mkdir(parents=True)
        original = 'PUBLIC_KEYS: tuple[str, ...] = ()\n'
        source.write_text(original, encoding='utf-8')
        with mock.patch.object(issuer, 'ROOT', root), mock.patch.object(license, 'PUBLIC_KEYS', ()), \
                mock.patch.object(issuer.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                issuer.configure_public_key(self.private.public_key().public_bytes_raw().hex())
            self.assertEqual(license.PUBLIC_KEYS, ())
        self.assertEqual(source.read_text(), original)
        self.assertEqual(list(source.parent.iterdir()), [source])


if __name__ == '__main__':
    unittest.main()
