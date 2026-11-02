"""Synthetic account/rotation/callback failure regressions; no real Drive or browser."""
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from unittest import mock
from pathlib import Path

from library import drive_client, mirror
from tests import test_sync as fixtures


class Rotation(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ServiceTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.svc, self.drive = self.fixture.svc, self.fixture.drive
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})

    def test_off_queues_rotation_with_one_listing_and_without_changing_master(self):
        old = self.svc.mirror_key().master
        self.drive.calls.clear()
        candidate = self.svc.unpair()
        self.assertNotEqual(candidate, self.svc._key().fingerprint)             # not switched yet (mirror_key() answers the new key: D15)
        self.assertEqual(self.svc._key().master, old)
        self.assertEqual(self.svc.mirror_key().master, self.svc._rotation_key(self.svc._rotation()['new']).master)      # D15
        self.assertEqual(self.svc.status()['rotation'], 'pending')
        self.assertEqual(self.drive.calls, ['list'])        # the click's lock-out looks once and changes nothing in Drive
        self.assertTrue(self.svc.status()['rotation_locked_at'])

    def test_cleanup_failure_retries_same_key_and_preserves_unknown_records(self):
        self.assertTrue(self.svc._publish())
        old = self.svc.mirror_key()
        unknown = self.drive.put('recovery-unknown', b'not our namespace')
        self.svc.unpair()
        with mock.patch.object(self.drive, 'delete', side_effect=drive_client.DriveError('synthetic cleanup failure')):
            self.assertFalse(self.svc._publish())
        new = self.svc.mirror_key()
        self.assertNotEqual(new.master, old.master)
        self.assertEqual(self.svc._rotation()['stage'], 'cleanup')
        # An offline phone's pending edit remains discoverable after rotation; never dropped unread.
        name, blob = old.seal_change({'format': 1, 'device': 'old-phone', 'at': 1, 'changes': []})
        pending = self.drive.put(name, blob)
        self.assertTrue(self.svc._publish())
        self.assertEqual(self.svc.mirror_key().master, new.master)
        self.assertEqual(self.svc._rotation()['stage'], 'complete')
        self.assertIn(unknown, self.drive.files)
        self.svc._intake()
        self.assertIn(pending, self.drive.files)
        fixtures.read_mirror(self.drive, new)
        self.assertFalse(any(n == old.name(mirror.MANIFEST) for n, _ in self.drive.files.values()))

    def test_partial_publication_retains_old_generation_and_candidate(self):
        self.assertTrue(self.svc._publish())
        old = self.svc.mirror_key()
        candidate = self.svc.unpair()
        with mock.patch.object(self.drive, 'upload', side_effect=drive_client.DriveError('synthetic offline', 503)):
            self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc.mirror_key().fingerprint, candidate)
        self.assertTrue(any(n == old.name(mirror.MANIFEST) for n, _ in self.drive.files.values()))
        self.assertEqual(self.svc._rotation()['stage'], 'publishing')
        self.assertTrue(self.svc._publish())
        self.assertEqual(self.svc.mirror_key().fingerprint, candidate)

    def test_rotation_rejects_account_replacement_and_keeps_master(self):
        old = self.svc.mirror_key().master
        self.svc.unpair()
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'different-synthetic-account'})
        self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc._key().master, old)
        self.assertEqual(self.svc._rotation()['stage'], 'prepared')

    def test_disconnect_deletes_only_authenticated_mirror_records(self):
        self.assertTrue(self.svc._publish())
        key = self.svc.mirror_key()
        name, blob = key.seal_change({'format': 1, 'changes': []})
        pending = self.drive.put(name, blob)
        unknown = self.drive.put('synthetic-unknown', b'preserve')
        vault = self.drive.put('vb-' + '0' * 32, b'unknown vault')
        with mock.patch.object(drive_client, 'revoke'):
            self.svc.sign_out(delete_mirror=True)
        self.assertEqual(set(self.drive.files), {pending, unknown, vault})

    def test_rotation_drains_pending_edits_and_verifies_vault_before_cleanup(self):
        from library import vault_sync
        root = self.fixture.root / 'vault'
        root.mkdir()
        (root / 'a.md').write_text('synthetic vault')
        self.svc.writer.call(lambda db: db.set_setting('obsidian_vault', str(root)))
        self.assertTrue(self.svc._publish())
        old = self.svc.mirror_key()
        name, blob = old.seal_change({'format': 1, 'device': 'synthetic', 'at': int(time.time() * 1000),
                                    'changes': [{'op': 'fav', 'uid': self.svc.writer.read(lambda db: db.get_item(self.fixture.ids[1])['uid']), 'on': True, 'at': int(time.time() * 1000)}]})
        pending = self.drive.put(name, blob)
        self.svc.unpair()
        with mock.patch.object(self.svc, '_vault_send', side_effect=drive_client.DriveError('synthetic interrupted vault')):
            self.assertFalse(self.svc._publish())
        self.assertNotIn(pending, self.drive.files)
        self.assertTrue(self.svc.writer.read(lambda db: db.get_item(self.fixture.ids[1])['favourite']))
        self.assertTrue(any(n == old.name(mirror.MANIFEST) for n, _ in self.drive.files.values()))
        self.assertTrue(self.svc._publish())
        key = self.svc.mirror_key()
        index = next(b for n, b in self.drive.files.values() if n == vault_sync.index_name(key, 'pc'))
        _, files = vault_sync.decode_index(key.open(vault_sync.INDEX_LOGICAL, index))
        self.assertIn('a.md', files)


    def test_owner_rotation_ignores_only_authenticated_old_files_and_retries_cleanup(self):
        from library import owner_vault, vault_sync as V
        from tests.test_vault_sync_pc import Phone
        root = self.fixture.root / 'vault'
        root.mkdir()
        man = owner_vault.new_manifest('synthetic')
        owner_vault.apply_render(root, man, {'Brainamon/a.md': {'data': b'page', 'source': 'item', 'key': 'a'}})
        self.svc.writer.call(lambda db: (db.set_setting('obsidian_vault', str(root)),
                                        db.set_setting('obsidian_mode', 'owner')))
        self.assertTrue(self.svc._publish())
        old = self.svc.mirror_key()
        self.svc._rotation_vault_round(self.drive, old, root)
        phone_root = self.fixture.root / 'phone'
        phone_root.mkdir()
        (phone_root / 'lost.md').write_text('pending lost-phone vault edit')
        Phone(self.drive, old, phone_root).round()
        self.svc.unpair()
        finish = self.svc._rotation_finish
        unknown = []

        def unexpected_index(*args):
            unknown.append(self.drive.put('vi-' + '0' * 32, b'not authenticated'))
            return finish(*args)

        with mock.patch.object(self.svc, '_rotation_finish', side_effect=unexpected_index):
            self.assertFalse(self.svc._publish())
        record = self.svc._rotation()
        self.assertEqual(record['stage'], 'publishing')
        self.assertTrue(set(record['owned']).issubset(self.drive.files))
        self.assertIn(unknown[0], self.drive.files)
        self.drive.delete(unknown[0])
        with mock.patch.object(self.drive, 'delete', side_effect=drive_client.DriveError('interrupted cleanup')):
            self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc._rotation()['stage'], 'cleanup')
        new = self.svc.mirror_key()
        self.assertNotEqual(new.fingerprint, old.fingerprint)
        idx = V.decode_index_full(new.open(V.INDEX_LOGICAL, self.drive.by_name(V.index_name(new, 'pc'))))
        self.assertEqual(idx['generated'], {'Brainamon/a.md'})
        self.assertEqual(idx['vault'], man['vault_id'])
        self.assertNotIn('lost.md', idx['files'])
        self.assertFalse((root / 'lost.md').exists())
        self.assertTrue(self.svc._publish())
        self.assertEqual(self.svc._rotation()['stage'], 'complete')
        self.assertTrue(set(record['owned']).isdisjoint(self.drive.files))


class AccountOwnership(unittest.TestCase):
    def test_key_transfer_accepts_its_own_token_refresh(self):
        from server.sync import SyncService
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            from tests.license_fixture import activate
            activate(self, root)
            svc = SyncService(mock.Mock(), mock.Mock(), root / 'data', root / 'cloud')
            drive_client.save_token(svc.token_path, {'refresh_token': 'synthetic-session', 'expires_at': 0})
            svc._raw_factory = lambda tok: drive_client.DriveClient('public', 'public', tok, svc.token_path)
            policy = mock.patch.object(svc.recovery, 'guard')
            policy.start()
            self.addCleanup(policy.stop)
            with mock.patch.object(drive_client, '_form', return_value={'access_token': 'synthetic-fresh', 'expires_in': 3600}), \
                    mock.patch.object(drive_client, '_request', return_value=(200, {}, b'{"id":"synthetic-file"}')):
                self.assertIn('t', svc.send_keys({'openai': 'synthetic'}))
            self.assertEqual([r['id'] for r in svc._transfers()], ['synthetic-file'])

    def test_stopped_successful_response_is_not_delivered(self):
        client = drive_client.DriveClient('public', 'public', {'refresh_token': 'synthetic', 'access_token': 'synthetic', 'expires_at': 9999999999})
        def blocked(*args):
            client.stop.set()
            return 200, {}, b'late response'
        with mock.patch.object(drive_client, '_request', side_effect=blocked):
            with self.assertRaises(drive_client.SignInCancelled):
                client.about()

    def test_delayed_account_read_and_cancelled_signin_cannot_commit(self):
        fixture = fixtures.ServiceTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        svc = fixture.svc
        def delayed():
            svc._generation += 1
            return fixture.drive.about()
        client = mock.Mock()
        client.about.side_effect = delayed
        svc._read_account(client)
        self.assertEqual(svc.st['account'], '')
        svc._read_account(client, generation=svc._generation - 1)
        self.assertEqual(client.about.call_count, 1)

    def test_stopped_prepare_does_not_reference_uninitialized_manifest(self):
        fixture = fixtures.ServiceTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        svc = fixture.svc
        drive_client.save_token(svc.token_path, {'refresh_token': 'synthetic'})
        from library.export_targets import ExportStopped
        with mock.patch.object(svc, '_rotation_prepare', side_effect=ExportStopped()):
            self.assertFalse(svc._publish())


class Callback(unittest.TestCase):
    def test_timeout_denial_and_late_exchange_cancellation(self):
        with mock.patch.object(drive_client, '_form') as exchange:
            with self.assertRaises(drive_client.SignInCancelled):
                drive_client.sign_in('public', 'public', lambda url: None, timeout=.05)
            exchange.assert_not_called()
        for denied in (True, False):
            cancel = threading.Event()
            def browser(url):
                params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                callback = params['redirect_uri'][0] + '?state=' + params['state'][0] + ('&error=access_denied' if denied else '&code=synthetic')
                def request():
                    with urllib.request.urlopen(callback, timeout=2) as response:
                        response.read()
                threading.Thread(target=request, daemon=True).start()
            def late(*args):
                cancel.set()
                return {'refresh_token': 'synthetic'}
            with mock.patch.object(drive_client, '_form', side_effect=late) as exchange:
                with self.assertRaises(drive_client.SignInCancelled):
                    drive_client.sign_in('public', 'public', browser, cancel=cancel, timeout=2)
                self.assertEqual(exchange.call_count, 0 if denied else 1)

    def test_incomplete_headers_and_slow_drip_cannot_hold_cancel(self):
        clients = []
        stop = threading.Event()
        def browser(url):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            callback = urllib.parse.urlsplit(params['redirect_uri'][0])
            client = socket.create_connection(('127.0.0.1', callback.port), timeout=1)
            clients.append(client)
            client.sendall(b'GET / HTTP/1.1\r\nHost: ')
            threading.Timer(.05, stop.set).start()
        start = time.monotonic()
        with mock.patch.object(drive_client, '_form') as exchange:
            try:
                with self.assertRaises(drive_client.SignInCancelled):
                    drive_client.sign_in('public-id', 'public-registration', browser, timeout=.4, cancel=stop)
            finally:
                for client in clients:
                    client.close()
            exchange.assert_not_called()
        self.assertLess(time.monotonic() - start, .8)

    def test_wrong_path_and_state_do_not_consume_single_valid_callback(self):
        failures = []
        def browser(url):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            base, state = params['redirect_uri'][0], params['state'][0]
            def requests():
                for suffix in ('wrong?state=' + state + '&code=x', '?state=wrong&code=x', '?state=' + state + '&code=valid'):
                    try:
                        urllib.request.urlopen(base + suffix, timeout=2).close()
                    except OSError:
                        failures.append('refused')
            threading.Thread(target=requests, daemon=True).start()
        with mock.patch.object(drive_client, '_form', return_value={'refresh_token': 'synthetic', 'access_token': 'synthetic'}) as exchange:
            drive_client.sign_in('public-id', 'public-registration', browser, timeout=2)
        self.assertEqual(len(failures), 2)
        exchange.assert_called_once()
        self.assertEqual(exchange.call_args.args[1]['code'], 'valid')
