"""Synthetic trust-boundary regressions. Run through scripts/security_tests.py."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.db import Database
from core.urls import http_url
from library import importers, public_http, ytdlp


class InputBoundaries(unittest.TestCase):
    def test_option_values_never_reach_downloader(self):
        for url in ('--config-locations=evil', 'file:///secret', 'https://u:p@host/', 'https://host/\n--exec=x'):
            self.assertFalse(http_url(url))
            with self.assertRaises(ValueError):
                ytdlp.download_args('yt-dlp', url, Path('synthetic'), False)
            with mock.patch.object(ytdlp.subprocess, 'Popen') as run:
                self.assertTrue(ytdlp.fetch_thumbnail({'url': url}, 'synthetic')['error'])
                run.assert_not_called()
        args = ytdlp.download_args('yt-dlp', 'https://example.com/v', Path('synthetic'), False)
        self.assertEqual(args[-2:], ['--', 'https://example.com/v'])

    def test_import_rejects_options_and_external_thumb_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / 'outside.jpg'
            outside.write_bytes(b'private synthetic bytes')
            data = root / 'data'
            db = Database(data / 'content_manager.db')
            (data / 'thumbs').mkdir(exist_ok=True)
            incoming = root / 'in.json'
            incoming.write_text(json.dumps({'items': [
                {'url': '--config-locations=evil'},
                {'url': 'https://example.com/v', 'thumb_path': str(outside)}]}))
            counts = {}
            self.assertEqual(importers.import_file(db, incoming, counts)[:2], (1, 1))
            self.assertEqual(counts, {'invalid': 1})
            db.close()
            for _ in range(2):
                db = Database(data / 'content_manager.db')
                self.assertEqual(db.get_item(1)['thumb_path'], '')
                db.close()
                self.assertEqual(outside.read_bytes(), b'private synthetic bytes')

    def test_legacy_thumbnail_migration_keeps_valid_image(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = Database(root / 'content_manager.db')
            item = db.add_item({'url': 'https://example.com/v', 'thumb_path': '1.jpg'})
            (root / 'thumbs').mkdir(exist_ok=True)
            Image.new('RGB', (2, 2)).save(root / 'thumbs' / '1.jpg')
            db.close()
            db = Database(root / 'content_manager.db')
            self.assertEqual(db.get_item(item)['thumb_path'], 'thumb.jpg')
            self.assertTrue((db.item_dir(item) / 'thumb.jpg').is_file())
            db.close()

    def test_thumbnail_migration_refuses_source_and_destination_reparse_points(self):
        from PIL import Image
        for blocked in ('source', 'directory', 'destination'):
            with self.subTest(blocked=blocked), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                db = Database(root / 'content_manager.db')
                item = db.add_item({'url': 'https://example.com/v', 'thumb_path': '1.jpg'})
                (root / 'thumbs').mkdir(exist_ok=True)
                src = root / 'thumbs' / '1.jpg'
                Image.new('RGB', (2, 2)).save(src)
                before = src.read_bytes()
                directory = db.item_dir(item)
                db.close()
                target = {'source': src, 'directory': directory, 'destination': directory / 'thumb.jpg'}[blocked]
                with mock.patch.object(Path, 'is_junction', lambda path: path == target):
                    for _ in range(2):
                        db = Database(root / 'content_manager.db')
                        self.assertEqual(db.get_item(item)['thumb_path'], '1.jpg')
                        db.close()
                self.assertEqual(src.read_bytes(), before)

    def test_dns_pinning_refuses_mixed_private_addresses(self):
        for forbidden in ('127.0.0.1', '224.0.0.1', 'ff02::1', '::ffff:127.0.0.1'):
            infos = [(2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', (forbidden, 443))]
            with mock.patch.object(public_http.socket, 'getaddrinfo', return_value=infos), mock.patch.object(public_http.socket, 'socket') as sock:
                with self.assertRaises(public_http.SecurityRefusal):
                    public_http.connect(('synthetic.invalid', 443))
                sock.assert_not_called()

    def test_reader_security_refusal_is_terminal(self):
        from library import linkinfo
        from server import job_kinds
        with mock.patch.object(linkinfo, 'public', return_value=False), mock.patch.object(job_kinds, '_ytdlp_info') as tool:
            with self.assertRaises(public_http.SecurityRefusal):
                job_kinds._thumb_run(mock.Mock(), {'id': 1, 'url': 'http://127.0.0.1/private'})
            tool.assert_not_called()

    def test_retired_html_export_is_removed(self):
        from library import export
        self.assertFalse(hasattr(export, 'generate_html'))
        self.assertFalse(hasattr(export, 'export_to_file'))


class PrivateStorage(unittest.TestCase):
    def setUp(self):
        from core import private_storage
        from types import SimpleNamespace
        patch = mock.patch.object(private_storage, 'sys', SimpleNamespace(platform='win32'))
        patch.start()
        self.addCleanup(patch.stop)

    def test_migration_preserves_exact_key_and_wrong_user_fails_closed(self):
        from core import private_storage as storage
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mirror.key'
            path.write_bytes(b'unchanged synthetic master key')
            with mock.patch.object(storage.site_sessions, '_acl'), mock.patch.object(storage.site_sessions, '_crypt', side_effect=lambda b, decrypt=False: b[4:] if decrypt else b'fake' + b):
                self.assertEqual(storage.read(path), b'unchanged synthetic master key')
                self.assertNotIn(b'unchanged synthetic master key', path.read_bytes())
                with mock.patch.object(storage.site_sessions, '_crypt', side_effect=RuntimeError('wrong user')):
                    with self.assertRaises(RuntimeError):
                        storage.read(path)
                self.assertTrue(storage.location(path).exists())

    def test_readonly_does_not_migrate_repair_or_change_permissions(self):
        from core import private_storage as storage
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mirror.key'
            path.write_bytes(b'synthetic')
            with mock.patch.object(storage.site_sessions, '_acl', side_effect=AssertionError('changed permissions')), \
                 mock.patch.object(storage.site_sessions, '_crypt', side_effect=lambda b, decrypt=False: b[4:] if decrypt else b'fake' + b), \
                 mock.patch.object(storage, 'write', side_effect=AssertionError('migrated')), \
                 mock.patch.object(storage.os, 'replace', side_effect=AssertionError('repaired')):
                self.assertEqual(storage.read(path, readonly=True), b'synthetic')
                target = storage.location(path)
                target.parent.mkdir()
                previous = target.with_name(target.name + '.previous')
                previous.write_bytes(b'fakesynthetic')
                self.assertEqual(storage.read(path, readonly=True), b'synthetic')
                self.assertTrue(previous.exists())
                self.assertFalse(target.exists())
                target.write_bytes(b'fakesynthetic')
                self.assertEqual(storage.read(path, readonly=True), b'synthetic')
                path.write_bytes(b'conflict')
                with self.assertRaises(RuntimeError):
                    storage.read(path, readonly=True)

    def test_failed_verified_write_preserves_legacy_and_retry(self):
        from core import private_storage as storage
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mirror.key'
            path.write_bytes(b'unchanged')
            with mock.patch.object(storage.site_sessions, '_acl'), mock.patch.object(storage.site_sessions, '_crypt', side_effect=lambda b, decrypt=False: b'bad' if decrypt else b):
                with self.assertRaises(RuntimeError):
                    storage.read(path)
                self.assertEqual(path.read_bytes(), b'unchanged')
            with mock.patch.object(storage.site_sessions, '_acl'), mock.patch.object(storage.site_sessions, '_crypt', side_effect=lambda b, decrypt=False: b):
                self.assertEqual(storage.read(path), b'unchanged')


if __name__ == '__main__':
    unittest.main()


class Authentication(unittest.TestCase):
    def test_all_private_transports_require_current_run_credential(self):
        import asyncio
        from server.guard import LocalGuard
        async def request(path, token='', origin='', method='GET'):
            messages = []
            async def app(scope, receive, send):
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'ok'})
            guard = LocalGuard(app, {'127.0.0.1:8765'}, 'synthetic-current')
            headers = [(b'host', b'127.0.0.1:8765'), (b'x-cm', b'1')]
            if token:
                headers.append((b'authorization', ('Bearer ' + token).encode()))
            if origin:
                headers.append((b'origin', origin.encode()))
            async def send(message):
                messages.append(message)
            await guard({'type': 'http', 'method': method, 'path': path, 'headers': headers}, None, send)
            return messages[0]['status']
        for path in ('/api/items', '/api/cloud/pair', '/api/events', '/thumb/1', '/files/items/1/video.mp4'):
            for token in ('', 'wrong', 'synthetic-stale'):
                self.assertEqual(asyncio.run(request(path, token)), 403)
            self.assertEqual(asyncio.run(request(path, 'synthetic-current')), 200)
            self.assertEqual(asyncio.run(request(path, 'synthetic-current', 'http://evil.invalid')), 403)
        self.assertEqual(asyncio.run(request('/index.html')), 200)


class WorkerIsolation(unittest.TestCase):
    def test_same_session_clients_reuse_refreshed_token(self):
        from library import drive_client as dc
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'google_token.json'
            original = {'refresh_token': 'synthetic-session', 'access_token': '', 'expires_at': 0}
            dc.save_token(path, original)
            clients = [dc.DriveClient('public', 'public', original, path) for _ in range(2)]
            with mock.patch.object(dc, '_form', return_value={'access_token': 'synthetic-fresh', 'expires_in': 3600}) as refresh:
                self.assertEqual([c._access() for c in clients], ['synthetic-fresh'] * 2)
                refresh.assert_called_once()
            # An early 401 must still force refresh when the stored token has not changed.
            clients[1].tok['access_token'] = ''
            with mock.patch.object(dc, '_form', return_value={'access_token': 'synthetic-renewed', 'expires_in': 3600}) as refresh:
                self.assertEqual(clients[1]._access(), 'synthetic-renewed')
                refresh.assert_called_once()

    def test_overlapping_refreshes_keep_the_first_committed_token(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from library import drive_client as dc
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'google_token.json'
            original = {'refresh_token': 'synthetic-session', 'expires_at': 0}
            dc.save_token(path, original)
            clients = [dc.DriveClient(str(i), 'public', original, path) for i in range(2)]
            barrier = threading.Barrier(2)
            def refresh(url, fields):
                barrier.wait(timeout=3)
                return {'access_token': 'synthetic-' + fields['client_id'], 'expires_in': 3600}
            with mock.patch.object(dc, '_form', side_effect=refresh), ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda c: c._access(), clients))
            self.assertEqual(results, [dc.load_token(path)['access_token']] * 2)

    def test_cancelled_refresh_does_not_persist(self):
        from library import drive_client as dc
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'google_token.json'
            original = {'refresh_token': 'synthetic-session', 'expires_at': 0}
            dc.save_token(path, original)
            client = dc.DriveClient('public', 'public', original, path)
            def refresh(*args):
                client.stop.set()
                return {'access_token': 'synthetic-late', 'expires_in': 3600}
            with mock.patch.object(dc, '_form', side_effect=refresh):
                with self.assertRaises(dc.SignInCancelled):
                    client._access()
            self.assertEqual(dc.load_token(path), original)

    def test_delayed_refresh_cannot_replace_new_account(self):
        import threading
        from library import drive_client
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'google_token.json'
            a = {'refresh_token': 'synthetic-account-A', 'access_token': '', 'expires_at': 0}
            b = {'refresh_token': 'synthetic-account-B', 'access_token': 'synthetic-B', 'expires_at': 9999999999}
            drive_client.save_token(path, a)
            client = drive_client.DriveClient('public-client', 'public-registration', a, path)
            started, release = threading.Event(), threading.Event()
            def refresh(*args):
                started.set()
                self.assertTrue(release.wait(3))
                return {'access_token': 'synthetic-A', 'expires_in': 3600}
            failures = []
            def work():
                try:
                    client._access()
                except drive_client.SignInCancelled:
                    failures.append('obsolete')
            with mock.patch.object(drive_client, '_form', side_effect=refresh):
                thread = threading.Thread(target=work)
                thread.start()
                self.assertTrue(started.wait(3))
                drive_client.save_token(path, b)
                release.set()
                thread.join(3)
            self.assertEqual(failures, ['obsolete'])
            self.assertEqual(drive_client.load_token(path), b)

    def test_live_thread_stays_owned_and_stop_is_not_acknowledged(self):
        from server.sync import SyncService
        from library.drive_client import DriveError
        service = SyncService(mock.Mock(), mock.Mock(), Path('synthetic'), Path('synthetic'))
        thread = service._thread = mock.Mock()
        thread.is_alive.return_value = True
        with self.assertRaises(DriveError):
            service._end_mirror()
        self.assertIs(service._thread, thread)
        self.assertTrue(service._stop.is_set())


class VideoIntegrity(unittest.TestCase):
    def test_complete_file_rejects_truncation_splice_and_legacy(self):
        import hashlib
        from library import mirror
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mirror, 'VIDEO_CHUNK', 8):
            root = Path(folder)
            src, sealed = root / 'v.mp4', root / 'v.bin'
            key = mirror.MirrorKey.generate()
            for data in (b'', b'12345678', b'12345678abcdefgh', b'12345678abcdefghXYZ'):
                src.write_bytes(data)
                integrity = {'integrity': 2, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                key.seal_file('videos/u.bin', src, sealed, integrity)
                blob = sealed.read_bytes()
                self.assertEqual(key.open_file('videos/u.bin', blob, integrity), data)
                with self.assertRaises(mirror.MirrorKeyError):
                    key.open_file('videos/u.bin', blob, {})
                if len(data) > 8:
                    with self.assertRaises(mirror.MirrorKeyError):
                        key.open_file('videos/u.bin', blob[:44], integrity)
                    src.write_bytes(b'87654321' + data[8:])
                    key.seal_file('videos/u.bin', src, root / 'other.bin')
                    changed = (root / 'other.bin').read_bytes()
                    with self.assertRaises(mirror.MirrorKeyError):
                        key.open_file('videos/u.bin', changed[:44] + blob[44:], integrity)
                with self.assertRaises(mirror.MirrorKeyError):
                    key.open_file('videos/u.bin', blob[:4] + bytes(4) + blob[8:], integrity)


class PackagingGate(unittest.TestCase):
    def test_private_names_content_oauth_and_archives(self):
        import importlib.util
        import zipfile
        spec = importlib.util.spec_from_file_location('payload_guard', Path(__file__).resolve().parents[1] / 'packaging/payload_guard.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bad = ['google_token.json', 'mirror.key.tmp', '.env.backup', 'cloud/random', 'private/random', 'keys/signing.pem', 'secret.dpapi', 'auth/8765.token', 'customer.pfx.bak', 'pair-transfers.json']
            for name in bad:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic')
            (root / 'arbitrary.json').write_text('{"refresh_token":"synthetic"}')
            (root / 'google-oauth.json').write_text(json.dumps({key: 'public' for key in guard.OAUTH}))
            expected = sorted(bad + ['arbitrary.json'])
            self.assertEqual(guard.inspect_payload(root), expected)
            archive = root.parent / (root.name + '.zip')
            try:
                with zipfile.ZipFile(archive, 'w') as z:
                    for file in root.rglob('*'):
                        if file.is_file():
                            z.write(file, file.relative_to(root).as_posix())
                self.assertEqual(guard.inspect_payload(archive), expected)
            finally:
                archive.unlink(missing_ok=True)
            self.assertTrue(guard.forbidden('google-oauth.json', b'{"unexpected":"x"}'))
            self.assertTrue(guard.forbidden('google-oauth.json', json.dumps({key: 3 for key in guard.OAUTH}).encode()))
