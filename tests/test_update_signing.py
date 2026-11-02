"""Real release signatures and admin key custody, with disposable keys/files only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from core import update_signing
from desktop import updater
from tests.test_updater import EXE, PUBLIC, manifest, release, chunks
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_keys', ROOT / 'packaging/update_keys.py')
keys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keys)


class SignedUpdates(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch.object(update_signing, 'PUBLIC_KEY', PUBLIC),
                      mock.patch.object(updater.app_paths, 'FROZEN', True),
                      mock.patch.object(updater.sys, 'platform', 'win32')):
            patch.start(); self.addCleanup(patch.stop)

    def test_manifest_rejects_wrong_key_tamper_unconfigured_or_malformed(self):
        self.assertEqual(update_signing.verify(manifest())['version'], '99.0.0')
        tampered = json.loads(manifest()); tampered['release']['sha256'] = '0' * 64
        for raw in (manifest(private=Ed25519PrivateKey.generate()), json.dumps(tampered),
                    b'{}', b'null', b'[]', b'x' * 4097,
                    manifest(repo='attacker/repo'), manifest(size=True), manifest(version='99.0.0-beta')):
            with self.subTest(raw=str(raw)[:40]), self.assertRaises(ValueError):
                update_signing.verify(raw)
        with mock.patch.object(update_signing, 'PUBLIC_KEY', ''):
            with self.assertRaises(ValueError):
                update_signing.verify(manifest())

    def test_real_download_recovery_launch_and_cached_manifest_tampering(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater, 'UPDATES', Path(folder)), \
             mock.patch.object(updater, '_get', release()), mock.patch.object(updater, '_get_chunks', chunks), \
             mock.patch.object(updater.subprocess, 'Popen') as launch:
            updater.start_download(updater.check())
            updater._dl_thread.join(3)
            self.assertEqual(updater.status()['state'], 'ready')
            self.assertEqual(updater.recover()['latest'], '99.0.0')
            path = Path(folder) / 'Brainamon-Setup-99.0.0.exe'
            updater.launch(path); launch.assert_called_once()
            sidecar = path.with_name(path.name + '.update.json')
            sidecar.write_bytes(manifest(private=Ed25519PrivateKey.generate()))
            with self.assertRaisesRegex(ValueError, 'signature'):
                updater.launch(path)
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(updater.recover(), {})
            self.assertEqual(updater.status()['state'], 'error')

    def test_invalid_manifest_refuses_download_before_fetching_installer(self):
        fixture = release()
        def get(url, timeout=5):
            return manifest(private=Ed25519PrivateKey.generate()) if url.endswith('.update.json') else fixture(url, timeout)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater, 'UPDATES', Path(folder)), \
             mock.patch.object(updater, '_get', side_effect=get), mock.patch.object(updater, '_get_chunks') as stream:
            with self.assertRaises(ValueError):
                updater.download(updater.check())
            stream.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_saved_manifest_is_bound_to_hash_size_name_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Brainamon-Setup-99.0.0.exe'
            sidecar = path.with_name(path.name + '.update.json')
            path.write_bytes(EXE)
            for raw in (manifest(size=len(EXE) + 1), manifest(sha256='0' * 64), manifest(version='98.0.0')):
                sidecar.write_bytes(raw)
                self.assertFalse(updater._trusted_publisher(path, '99.0.0'))
            sidecar.write_bytes(manifest())
            self.assertTrue(updater._trusted_publisher(path, '99.0.0'))
            with mock.patch.object(updater, '__version__', '99.0.0'):
                self.assertFalse(updater._trusted_publisher(path, '99.0.0'))
            sidecar.unlink()
            self.assertFalse(updater._trusted_publisher(path, '99.0.0'))


class KeyCustody(unittest.TestCase):
    def test_initialize_reuses_key_signs_installer_and_never_replaces_trust(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            (root / 'core').mkdir(parents=True)
            config = root / 'core/update_signing.py'
            config.write_text("PUBLIC_KEY = ''\n")
            key = Path(folder) / 'admin/release.key'
            with mock.patch.object(keys, 'ROOT', root), mock.patch.object(update_signing, 'PUBLIC_KEY', ''):
                target = keys.initialize(key)
                public = update_signing.PUBLIC_KEY
                self.assertTrue(target.is_file())
                self.assertIn(public, config.read_text())
                self.assertEqual(keys.initialize(key), target)
                self.assertEqual(update_signing.PUBLIC_KEY, public)
                installer = Path(folder) / f'Brainamon-Setup-{keys.__version__}.exe'
                installer.write_bytes(EXE)
                keys.sign_installer(installer, key)
                self.assertEqual(update_signing.verify_file(installer)['version'], keys.__version__)
                original = target.read_bytes()
                with self.assertRaises(ValueError):
                    keys.initialize(Path(folder) / 'different.key')
                self.assertEqual(target.read_bytes(), original)
                with mock.patch.object(update_signing, 'PUBLIC_KEY', '0' * 64):
                    with self.assertRaises(ValueError):
                        keys.initialize(key)
                self.assertEqual(target.read_bytes(), original)
                with self.assertRaises(ValueError):
                    keys.initialize(root / 'private.key')


if __name__ == '__main__':
    unittest.main()
