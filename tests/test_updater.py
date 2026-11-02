"""updater.py: version compare, release parsing, checksum verification, DB backup on upgrade.
No network: updater._get is mocked. Run:  py -m unittest tests.test_updater -v
"""
import hashlib
import base64
import io
import json
import time
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from desktop import updater
from core import update_signing
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core.version import __version__

EXE = b'MZ fake installer bytes'
SHA = hashlib.sha256(EXE).hexdigest()
PRIVATE = Ed25519PrivateKey.generate()
PUBLIC = PRIVATE.public_key().public_bytes_raw().hex()


def manifest(version='99.0.0', private=PRIVATE, **changes):
    payload = {'v': 1, 'repo': updater.RELEASES_REPO, 'version': version,
               'name': f'Brainamon-Setup-{version}.exe', 'size': len(EXE), 'sha256': SHA, **changes}
    return json.dumps({'release': payload,
        'signature': base64.b64encode(private.sign(update_signing.message(payload))).decode('ascii')}).encode()


def release(tag='v99.0.0', sha=SHA, with_sha=True, digest=None, brand='Brainamon', with_manifest=True):
    name = f'{brand}-Setup-{tag[1:]}.exe'
    base = f'https://github.com/{updater.RELEASES_REPO}/releases/download/{tag}/'
    assets = [{'name': name, 'browser_download_url': base + name, 'size': len(EXE), **({'digest': digest} if digest else {})}]
    if with_sha:
        assets.append({'name': name + '.sha256', 'browser_download_url': base + name + '.sha256', 'size': 93})
    if with_manifest:
        assets.append({'name': name + '.update.json', 'browser_download_url': base + name + '.update.json', 'size': len(manifest(tag[1:]))})
    rel = {'tag_name': tag, 'body': 'Notes', 'assets': assets}
    urls = {updater.API: json.dumps(rel).encode(), base + name: EXE, base + name + '.sha256': f'{sha}  {name}\n'.encode(),
            base + name + '.update.json': manifest(tag[1:])}
    return lambda url, timeout=5.0: urls[url]


def chunks(url, timeout=60.0):
    return len(EXE), iter([EXE[:5], EXE[5:]])


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch.object(update_signing, 'PUBLIC_KEY', PUBLIC),
                      mock.patch.object(updater.app_paths, 'FROZEN', True),
                      mock.patch.object(updater.sys, 'platform', 'win32')):
            patch.start()
            self.addCleanup(patch.stop)

    def test_public_installer_feed(self):
        self.assertEqual(updater.RELEASES_REPO, 'knackychan/brainamon')
        self.assertEqual(updater.API, 'https://api.github.com/repos/knackychan/brainamon/releases/latest')

    def test_parse_version(self):
        self.assertEqual(updater.parse_version('v1.2.10'), (1, 2, 10))
        self.assertGreater(updater.parse_version('0.10.0'), updater.parse_version('0.9.9'))
        self.assertEqual(updater.parse_version('junk'), (0, 0, 0))

    def test_check_newer(self):
        with mock.patch.object(updater, '_get', release()):
            r = updater.check()
        self.assertTrue(r['newer'])
        self.assertEqual((r['current'], r['latest'], r['notes']), (__version__, '99.0.0', 'Notes'))

    def test_check_same_version_not_newer(self):
        with mock.patch.object(updater, '_get', release(tag='v' + __version__)):
            self.assertFalse(updater.check()['newer'])

    def test_check_without_sha_asset_is_an_error(self):
        with mock.patch.object(updater, '_get', release(with_sha=False)):
            self.assertIn('error', updater.check())

    def test_check_without_signed_manifest_is_an_error(self):
        with mock.patch.object(updater, '_get', release(with_manifest=False)):
            self.assertIn('error', updater.check())

    def test_check_requires_installer_version_to_match_release_tag(self):
        with mock.patch.object(updater, '_get', release(tag='v98.0.0')):
            rel = json.loads(updater._get(updater.API))
            rel['assets'].insert(0, {'name': 'Brainamon-Setup-99.0.0.exe', 'browser_download_url': 'https://x/wrong'})
            with mock.patch.object(updater, '_get', return_value=json.dumps(rel).encode()):
                self.assertEqual(updater.check()['name'], 'Brainamon-Setup-98.0.0.exe')

    def test_check_ignores_other_installer_names(self):
        with mock.patch.object(updater, '_get', release(brand='Other')):
            self.assertIn('error', updater.check())
        self.assertIsNone(updater.ASSET_RE.match('Other-Setup-99.0.0.exe'))

    def test_check_network_error(self):
        with mock.patch.object(updater, '_get', side_effect=OSError('offline')):
            self.assertIn('error', updater.check())

    def test_check_refuses_wrong_origin_and_unstable_release(self):
        rel = json.loads(release()(updater.API))
        for mutate in (lambda d: d['assets'][0].update(browser_download_url='https://elsewhere.invalid/setup.exe'),
                       lambda d: d.update(prerelease=True),
                       lambda d: d['assets'][0].update(size=updater.MAX_INSTALLER_SIZE + 1)):
            bad = json.loads(json.dumps(rel))
            mutate(bad)
            with mock.patch.object(updater, '_get', return_value=json.dumps(bad).encode()):
                self.assertIn('error', updater.check())

    def test_network_reads_are_bounded_and_closed(self):
        class Response(io.BytesIO):
            headers = {'Content-Length': str(updater.MAX_INSTALLER_SIZE + 1)}
        response = Response(b'')
        with mock.patch.object(updater, '_open', return_value=response):
            _, stream = updater._get_chunks('https://example.invalid/installer')
            with self.assertRaisesRegex(ValueError, 'too large'):
                next(stream)
        self.assertTrue(response.closed)
        response = Response(b'x' * 4097)
        with mock.patch.object(updater, '_open', return_value=response):
            with self.assertRaisesRegex(ValueError, 'too large'):
                updater._get('https://example.invalid/checksum')
        self.assertTrue(response.closed)

    def test_download_verifies_and_keeps(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_get', release()), mock.patch.object(updater, '_get_chunks', chunks):
            seen = []
            path = updater.download(updater.check(), lambda d, t: seen.append((d, t)))
            self.assertEqual(seen[-1], (len(EXE), len(EXE)))
            self.assertEqual(path.read_bytes(), EXE)

    def test_download_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_get', release(sha='0' * 64)), \
                mock.patch.object(updater, '_get_chunks', chunks):
            with self.assertRaises(ValueError):
                updater.download(updater.check())
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_download_digest_disagreement_is_refused(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_get', release(digest='sha256:' + '1' * 64)):
            with self.assertRaises(ValueError):
                updater.download(updater.check())

    def test_interrupted_download_keeps_existing_installer_and_cleans_partial(self):
        def interrupted(url, timeout=60.0):
            def blocks():
                yield EXE[:5]
                raise OSError('connection lost')
            return len(EXE), blocks()
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_get', release()), mock.patch.object(updater, '_get_chunks', interrupted):
            path = Path(td) / 'Brainamon-Setup-99.0.0.exe'
            path.write_bytes(b'previous')
            with self.assertRaises(OSError):
                updater.download(updater.check())
            self.assertEqual(path.read_bytes(), b'previous')
            self.assertEqual(list(Path(td).iterdir()), [path])

    def test_download_rejects_oversized_stream(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_get', release()), \
                mock.patch.object(updater, '_get_chunks', return_value=(0, iter([b'12345']))):
            info = updater.check()
            with mock.patch.object(updater, 'MAX_INSTALLER_SIZE', 4):
                with self.assertRaisesRegex(ValueError, 'too large'):
                    updater.download(info)
            self.assertEqual(list(Path(td).iterdir()), [])

    @mock.patch.object(updater, '_trusted_publisher', return_value=True)
    def test_background_download_status(self, _publisher):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)),                 mock.patch.object(updater, '_get', release()), mock.patch.object(updater, '_get_chunks', chunks):
            st = updater.start_download(updater.check())
            self.assertIn(st['state'], ('downloading', 'ready'))
            for _ in range(100):
                if updater.status()['state'] != 'downloading':
                    break
                time.sleep(0.02)
            st = updater.status()
            self.assertEqual((st['state'], st['done'], st['name']), ('ready', len(EXE), 'Brainamon-Setup-99.0.0.exe'))

    def test_launch_only_verified_downloads(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)):
            with self.assertRaises(ValueError):
                updater.launch(Path(td) / '..' / 'evil.exe')
            with self.assertRaises(ValueError):
                updater.launch(Path(td) / 'Brainamon-Setup-9.9.9.exe')   # not downloaded

    def test_launch_rechecks_digest_and_publisher(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_get', release()), mock.patch.object(updater, '_get_chunks', chunks), \
                mock.patch.object(updater, '_trusted_publisher', return_value=True) as publisher, \
                mock.patch.object(updater.subprocess, 'Popen') as popen:
            info = updater.check()
            path = updater.download(info)
            with mock.patch.object(updater, '_dl', {'state': 'ready', 'name': path.name,
                                                   'version': info['latest'], 'sha256': SHA}):
                updater.launch(path)
                publisher.assert_called_once_with(path, info['latest'])
                popen.assert_called_once()
                command = popen.call_args.args[0]
                self.assertEqual(Path(command[0]).name, 'powershell.exe')
                self.assertIn('-EncodedCommand', command)
                self.assertEqual(popen.call_args.kwargs['cwd'], str(Path(td)))
                path.write_bytes(b'MZ changed installer')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    updater.launch(path)
                self.assertEqual(popen.call_count, 1)

    def test_launch_rejects_untrusted_signature(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(updater, 'UPDATES', Path(td)), \
                mock.patch.object(updater, '_trusted_publisher', return_value=False), \
                mock.patch.object(updater.subprocess, 'Popen') as popen:
            path = Path(td) / 'Brainamon-Setup-99.0.0.exe'
            path.write_bytes(EXE)
            with mock.patch.object(updater, '_dl', {'state': 'ready', 'name': path.name,
                                                   'version': '99.0.0', 'sha256': SHA}):
                with self.assertRaisesRegex(ValueError, 'signature'):
                    updater.launch(path)
            popen.assert_not_called()

    def test_launch_requires_signed_version_to_match_release(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater, 'UPDATES', Path(folder)), \
                mock.patch.object(updater.subprocess, 'Popen') as launch:
            path = Path(folder) / 'Brainamon-Setup-99.0.0.exe'
            path.write_bytes(EXE)
            with mock.patch.object(updater, '_dl', {'state': 'ready', 'name': path.name, 'version': '99.0.0', 'sha256': SHA}):
                sidecar = path.with_name(path.name + '.update.json')
                for version in ('0.0.1', __version__, '98.0.0', '100.0.0', '99.0.0.1'):
                    with self.subTest(version=version):
                        sidecar.write_bytes(manifest(version))
                        with self.assertRaisesRegex(ValueError, 'signed version'):
                            updater.launch(path)
                        launch.assert_not_called()
                sidecar.write_bytes(manifest())
                updater.launch(path)
                launch.assert_called_once()

    def test_installer_embeds_the_release_version(self):
        script = Path(__file__).resolve().parents[1] / 'packaging' / 'installer.iss'
        self.assertIn('VersionInfoVersion={#AppVersion}', script.read_text())

    def test_backup_on_upgrade(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            data = Path(td)
            con = sqlite3.connect(data / 'content_manager.db')
            con.execute('create table t (x)')
            con.execute('insert into t values (42)')
            con.commit()
            con.close()
            copy = updater.backup_on_upgrade(data)
            self.assertIsNotNone(copy)
            self.assertEqual(sqlite3.connect(copy).execute('select x from t').fetchone(), (42,))
            self.assertEqual((data / 'app_version.txt').read_text(), __version__)
            self.assertIsNone(updater.backup_on_upgrade(data))    # same version: no second copy
            (data / 'app_version.txt').write_text('0.0.1')
            self.assertIn('0.0.1-to-', updater.backup_on_upgrade(data).name)
            self.assertEqual(len(list((data / 'backups').iterdir())), 2)   # never pruned
            (data / 'app_version.txt').write_text('99.0.0')                # a newer build used this data
            self.assertIsNone(updater.backup_on_upgrade(data))              # an older one: no copy
            self.assertEqual((data / 'app_version.txt').read_text(), '99.0.0')


if __name__ == '__main__':
    unittest.main()
