"""Recovery uses synthetic secrets, libraries and an in-memory Drive only."""
import copy
import json
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from core import private_storage
from core.db import Database
from library import drive_client, export, mirror, recovery as R, restore
from library.export_targets import DriveMirrorTarget
from server import cloud_errors, recovery as SR, sync as sync_mod
from server.store import Writer
from server.sync import SyncService
from tests.test_sync import FakeDrive, Hub, Library, read_mirror

PASSWORD = 'a long synthetic recovery phrase'


class EnvelopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = mirror.MirrorKey(bytes(range(32)))
        cls.record, cls.secret = R.create(cls.key, PASSWORD, 'test@example.com')

    def test_both_independent_secrets_unlock_and_legacy_codes_remain_supported(self):
        self.assertEqual(R.unlock(self.record, password=PASSWORD).master, self.key.master)
        kit = R.kit(self.record, R.encode(self.secret))
        self.assertEqual(R.import_key(R.dump(kit).decode())[0].master, self.key.master)
        self.assertEqual(R.import_key(self.key.text())[0].master, self.key.master)
        code = R.encode(R.dump({'v': 2, 'k': self.key.text(), 'ai': {'openai': 'must-not-be-imported'}}))
        self.assertEqual(R.import_key('https://example.com/#pair=' + code)[0].master, self.key.master)
        phone = {'format': R.PHONE_FORMAT, 'version': 1, 'key': self.key.text(), 'fingerprint': self.key.fingerprint}
        self.assertEqual(R.import_key(R.dump(phone).decode())[0].master, self.key.master)
        with self.assertRaisesRegex(R.RecoveryError, 'standalone phone backup'):
            R.import_key('{"format":"brainamon-phone-backup-kit","version":1}')

    def test_wrong_secret_tamper_and_unbounded_kdf_are_rejected(self):
        with self.assertRaises(R.RecoveryError):
            R.unlock(self.record, password='another incorrect recovery phrase')
        for field, value in (('fingerprint', 'a' * 12), ('generation', 'b' * 32), ('account', 'other@example.com')):
            record = copy.deepcopy(self.record)
            record['header'][field] = value
            with self.assertRaises(R.RecoveryError):
                R.unlock(record, secret=R.encode(self.secret))
        record = copy.deepcopy(self.record)
        record['password']['kdf']['n'] = 2 ** 40
        with mock.patch.object(R, '_derive', side_effect=AssertionError('KDF must not run')):
            with self.assertRaises(R.RecoveryError):
                R.unlock(record, password=PASSWORD)
        with self.assertRaises(R.RecoveryError):
            R.parse('{"version":1,"version":2}')
        with self.assertRaises(R.RecoveryError):
            R.import_key('x' * (R.MAX_RECORD + 1))

    def test_passphrase_is_not_trimmed_or_normalized(self):
        record, secret = R.create(self.key, '  a meaningful passphrase  ', 'test@example.com')
        with self.assertRaises(R.RecoveryError):
            R.unlock(record, password='a meaningful passphrase')
        self.assertEqual(R.unlock(record, secret=R.encode(secret)).master, self.key.master)


class RestoreTest(Library):
    def setUp(self):
        super().setUp()
        self.drive, self.key = FakeDrive(), mirror.MirrorKey.generate()
        self.payload = self.payload()
        DriveMirrorTarget(self.drive, self.key, {}, self.data, mirror.Options(videos='all')).export(self.payload)

    def restore(self, stage=None, cancel=None):
        snap = restore.preview(self.drive, self.key)
        stage = stage or self.root / 'recovered'
        before = dict(self.drive.files)
        restore.materialize(self.drive, self.key, snap, stage, cancel or threading.Event(), lambda d, t: None)
        self.assertEqual(self.drive.files, before)
        return stage

    def test_new_library_preserves_ids_uids_text_media_categories_and_notes(self):
        stage = self.restore()
        recovered = Database(stage / 'content_manager.db')
        try:
            self.assertEqual(recovered.count_items(), self.db.count_items())
            for original in self.payload['items']:
                row = recovered.get_item(original['id'])
                self.assertEqual(row['uid'], original['uid'])
                self.assertEqual(row['description'], original['description'])
                self.assertEqual(row['favourite'], original['favourite'])
                self.assertTrue((recovered.item_dir(row['id']) / 'thumb.jpg').is_file())
            self.assertEqual(recovered.get_setting('cloud_upload'), '')
            self.assertEqual(recovered.get_setting('cloud_vault'), 'off')
            self.assertTrue(recovered.fts_ids('knee'))
        finally:
            recovered.close()
        self.assertEqual((stage / 'notes/knees.md').read_bytes(), (self.data / 'notes/knees.md').read_bytes())
        self.assertEqual((stage / f'items/{self.ids[0]}/video/recovered.mp4').read_bytes(), (self.data / f'items/{self.ids[0]}/video/clip.mp4').read_bytes())
        self.assertTrue((stage / 'canvases/c1.json').is_file())

    def test_wiskit_deep_vectors_named_aux_do_not_block_restore(self):
        # search/aux.bin is a logical Drive label, never a file on disk, so AUX is not a device here.
        vector = bytes(4 * 4)
        self.payload['deep'] = {'model': 'm', 'aux': [{'key': 'note:knees.md#0', 'hash': 'h', 'dim': 4, 'blob': vector}]}
        self.drive = FakeDrive()
        DriveMirrorTarget(self.drive, self.key, {}, self.data, mirror.Options(videos='all')).export(self.payload)
        self.assertIn('search/aux.bin', restore.preview(self.drive, self.key)['manifest']['files'])
        self.assertTrue((self.restore() / 'content_manager.db').is_file())
        with self.assertRaisesRegex(R.RecoveryError, 'Windows filename'):
            restore.safe_rel('notes/aux.md')

    def test_pending_phone_changes_use_existing_deduplication_without_remote_deletes(self):
        uid = self.payload['items'][0]['uid']
        name, blob = self.key.seal_change({'format': 1, 'device': 'phone', 'at': 100, 'changes': [
            {'op': 'link', 'uid': 'a' * 32, 'url': 'https://example.com/recovered', 'at': 90}]})
        fid = self.drive.put(name, blob)
        stage = self.restore()
        recovered = Database(stage / 'content_manager.db')
        try:
            self.assertTrue(recovered.item_exists('https://example.com/recovered'))
            self.assertIn('phone', json.loads(recovered.get_setting('cloud_applied')))
            self.assertIn(fid, self.drive.files)
        finally:
            recovered.close()

    def test_cancel_corruption_missing_reference_and_snapshot_changes_leave_drive_unchanged(self):
        cancel = threading.Event()
        cancel.set()
        before = dict(self.drive.files)
        with self.assertRaisesRegex(R.RecoveryError, 'cancelled'):
            self.restore(cancel=cancel)
        self.assertEqual(self.drive.files, before)
        snap = restore.preview(self.drive, self.key)
        fid = snap['manifest_id']
        name, blob = self.drive.files[fid]
        changed = json.loads(self.key.open(mirror.MANIFEST, blob))
        changed['published'] += 1
        self.drive.files[fid] = name, self.key.seal(mirror.MANIFEST, R.dump(changed))
        with self.assertRaisesRegex(R.RecoveryError, 'changed since preview'):
            restore.unchanged(self.drive, self.key, snap)
        first = next(iter(snap['manifest']['files'].values()))['id']
        del self.drive.files[first]
        with self.assertRaisesRegex(R.RecoveryError, 'missing'):
            restore.preview(self.drive, self.key)

    def test_hostile_paths_and_existing_destinations_are_rejected(self):
        for path in ('../outside', '/absolute', 'notes/CON.md', 'notes/a:secret', 'notes/foo.', 'notes//x', 'notes/..\\x', 'NUL.txt'):
            with self.subTest(path=path), self.assertRaises(R.RecoveryError):
                restore.safe_rel(path)
        for path in (str(self.data), str(self.data / 'nested'), str(self.root)):
            with self.assertRaises(R.RecoveryError):
                restore.destination(path, (self.data,))
        self.assertEqual(restore.destination(str(self.root / 'new'), (self.data,)), self.root / 'new')

    def test_in_place_publication_is_rejected_even_before_the_manifest_changes(self):
        listing = self.drive.list
        versions, times = {}, {}
        manifest_id = next(f['id'] for f in listing() if f['name'] == self.key.name(mirror.MANIFEST))
        def metadata():
            return [{**f, 'version': versions.get(f['id'], '1'),
                     'modifiedTime': times.get(f['id'], '2026-10-27T00:00:10Z' if f['id'] == manifest_id else '2026-10-27T00:00:09Z')}
                    for f in listing()]
        with mock.patch.object(self.drive, 'list', side_effect=metadata):
            snap = restore.preview(self.drive, self.key)
            fid = next(iter(snap['manifest']['files'].values()))['id']
            versions[fid] = '2'
            with self.assertRaisesRegex(R.RecoveryError, 'referenced Drive file changed'):
                restore.unchanged(self.drive, self.key, snap)
            times[fid] = '2026-10-27T00:00:11Z'
            with self.assertRaisesRegex(R.RecoveryError, 'unfinished upload'):
                restore.preview(self.drive, self.key)

    def test_preview_signature_is_the_manifest_row_the_publisher_saved(self):
        saved, drive = {}, FakeDrive()
        DriveMirrorTarget(drive, self.key, {}, self.data, mirror.Options(videos='all'),
                          save=lambda put, drop: saved.update(put)).export(self.payload)
        snap = restore.preview(drive, self.key)
        self.assertEqual(saved[mirror.MANIFEST]['drive_id'], snap['manifest_id'])
        self.assertEqual(saved[mirror.MANIFEST]['sig'], snap['manifest_sig'])
        self.assertNotEqual(snap['manifest_sig'], snap['hash'])        # plaintext proof, not the ciphertext hash
        self.assertEqual(restore.unchanged(drive, self.key, snap)['manifest_sig'], snap['manifest_sig'])


class RecoveryServiceTest(Library):
    def setUp(self):
        super().setUp()
        from tests.license_fixture import activate
        activate(self, self.root)
        self.db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.drive = FakeDrive()
        self.svc = SyncService(self.writer, Hub(), self.data, self.root / 'cloud', client_factory=lambda token: self.drive)
        self.service = self.svc.recovery
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.addCleanup(self.service.shutdown)

    def tearDown(self):
        self.service.shutdown()
        self.svc.shutdown()
        self.writer.stop()
        self.db = Database(self.data / 'content_manager.db')
        super().tearDown()

    def test_a_queued_enrollment_blocked_by_recovery_can_be_retried_without_stalling_uploads(self):
        with mock.patch.object(SyncService, 'running', new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(self.svc, 'ensure_running'):
            self.service.enroll(PASSWORD, PASSWORD)
        with mock.patch.object(self.service, 'lock') as lock:
            lock.acquire.return_value = False
            self.svc._run_intents(threading.Event())
        task = self.svc.intents.find('enroll')
        self.assertEqual((task['stage'], task['code']), ('queued', 'busy'))
        self.assertFalse(self.svc.intents.preempting())
        self.service.enroll(PASSWORD, PASSWORD)
        self.assertIsNone(self.svc.intents.find('enroll'))
        self.assertTrue(self.service.status()['enrolled'])

    def setup_recovery(self):
        kit = self.service.enroll(PASSWORD, PASSWORD)
        self.service.verify_kit(R.dump(kit).decode())
        return kit

    def wait(self, cond, t=15):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def interrupted_removal(self, when, **kw):
        """Probe D after S3: a removal whose replacement record reached Drive but whose key switch never ran."""
        with mock.patch.object(R, 'time', mock.Mock(time=lambda: when)):
            self.svc.unpair(PASSWORD, **kw)
            with mock.patch.object(self.service, 'commit_rotation', side_effect=OSError('synthetic interruption')):
                self.assertFalse(self.svc._publish())

    def test_vault_workers_share_remote_checks_but_index_and_deletes_recheck(self):
        from concurrent.futures import ThreadPoolExecutor
        self.setup_recovery()
        client = self.svc._factory({})
        self.drive.calls.clear()
        with ThreadPoolExecutor(12) as pool:
            ids = list(pool.map(lambda i: client.upload(f'vb-{i:032x}', data=b'note'), range(48)))
        self.assertEqual(self.drive.calls.count('list'), 1)
        self.assertEqual(sum(c.startswith('download ') for c in self.drive.calls), 1)
        client.upload('vs-status', data=b'progress')
        self.assertEqual(self.drive.calls.count('list'), 1)
        client.upload('vi-index', data=b'index')
        client.delete(ids[0])
        self.assertEqual(self.drive.calls.count('list'), 3)
        client.upload('vb-existing', data=b'replacement', file_id=ids[1])
        self.assertEqual(self.drive.calls.count('list'), 4)

    def test_vault_without_recovery_reuses_listing_and_rejects_new_legacy_blocker(self):
        self.svc.mirror_key()
        client = self.svc._factory({})
        self.drive.calls.clear()
        client.upload('vs-status', data=b'progress')
        for i in range(48):
            client.upload(f'vb-{i:032x}', data=b'note')
        self.assertEqual(self.drive.calls.count('list'), 1)
        private_storage.write(self.svc.cloud_dir / 'recovery-legacy.json', R.dump({'pending': True}))
        with self.assertRaisesRegex(drive_client.DriveError, 'verified recovery'):
            client.upload('vb-blocked', data=b'note')

    def test_vault_cached_check_does_not_bypass_changed_google_session(self):
        key = self.svc.mirror_key()
        self.writer.call(lambda db: db.set_setting('cloud_epoch', key.fingerprint))
        token = {'refresh_token': 'synthetic', 'access_token': 'access', 'expires_at': 9999999999}
        drive_client.save_token(self.svc.token_path, token)
        raw = drive_client.DriveClient('public', 'public', token, self.svc.token_path)
        client = sync_mod._GuardedClient(self.svc, raw)
        with mock.patch.object(drive_client, '_request', return_value=(200, {}, b'{"files":[],"id":"blob"}')) as request:
            client.upload('vb-first', data=b'note')
            before = request.call_count
            drive_client.save_token(self.svc.token_path, dict(token, refresh_token='another-session'))
            with self.assertRaisesRegex(drive_client.SignInCancelled, 'session changed'):
                client.upload('vb-blocked', data=b'note')
            self.assertEqual(request.call_count, before)

    def test_vault_guard_expires_and_retries_failures_without_cached_success(self):
        self.setup_recovery()
        client = self.svc._factory({})
        self.drive.calls.clear()
        with mock.patch.object(SR.time, 'monotonic', return_value=100) as clock:
            client.upload('vb-first', data=b'note')
            clock.return_value = 129
            client.upload('vb-second', data=b'note')
            self.assertEqual(self.drive.calls.count('list'), 1)
            clock.return_value = 130
            with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('offline')):
                with self.assertRaisesRegex(drive_client.DriveError, 'offline'):
                    client.upload('vb-blocked', data=b'note')
            self.assertIsNone(client._guard_cache)
            client.upload('vb-third', data=b'note')
            self.assertEqual(self.drive.calls.count('list'), 2)
        self.assertNotIn('upload vb-blocked', self.drive.calls)

    def test_vault_guard_local_changes_invalidate_immediately(self):
        self.setup_recovery()
        client = self.svc._factory({})
        client.upload('vb-first', data=b'note')
        private_storage.write(self.service.journal, R.dump({'pending': True}))
        with self.assertRaisesRegex(drive_client.DriveError, 'activation is pending'):
            client.upload('vb-journal-blocked', data=b'note')
        private_storage.remove(self.service.journal)
        client.upload('vb-second', data=b'note')
        state = self.service._load()
        state['restored'] = True
        self.service._save(state)
        with self.assertRaisesRegex(drive_client.DriveError, 'Take over uploads'):
            client.upload('vb-restored-blocked', data=b'note')
        state['restored'] = False
        self.service._save(state)
        client.upload('vb-third', data=b'note')
        mirror.MirrorKey.generate().save(self.svc.key_path)
        with self.assertRaisesRegex(drive_client.DriveError, 'does not match'):
            client.upload('vb-key-blocked', data=b'note')

    def test_vault_guard_epoch_and_new_account_client_require_new_checks(self):
        self.setup_recovery()
        client = self.svc._factory({})
        client.upload('vb-first', data=b'note')
        self.drive.calls.clear()
        self.writer.call(lambda db: db.set_setting('cloud_epoch', 'changed'))
        client.upload('vb-second', data=b'note')
        self.assertEqual(self.drive.calls.count('list'), 1)
        with mock.patch.object(self.drive, 'about', return_value={'email': 'another@example.com'}):
            new_client = self.svc._factory({})
            with self.assertRaisesRegex(drive_client.DriveError, 'Reconnect the Google account'):
                new_client.upload('vb-account-blocked', data=b'note')

    def test_vault_guard_remote_takeover_blocks_index_and_expired_blob(self):
        self.setup_recovery()
        client = self.svc._factory({})
        client.upload('vb-first', data=b'note')
        state, key = self.service._load(), self.svc.mirror_key()
        found, owner = self.service._owner(self.drive, key, state['record']['header']['library'])
        fid = found['id']
        owner['device'] = 'another-pc'
        name, _ = self.drive.files[fid]
        self.drive.files[fid] = name, key.seal(SR.OWNER_LOGICAL, R.dump(owner))
        # Blobs may finish within the bounded window, but the index never publishes on stale ownership.
        client.upload('vb-in-flight', data=b'note')
        with self.assertRaisesRegex(drive_client.DriveError, 'Another PC'):
            client.upload('vi-index', data=b'index')
        with self.assertRaisesRegex(drive_client.DriveError, 'Another PC'):
            client.upload('vb-after-refusal', data=b'note')
        client._guard_until = 0
        with self.assertRaisesRegex(drive_client.DriveError, 'Another PC'):
            client.upload('vb-expired', data=b'note')
        self.assertNotIn('upload vi-index', self.drive.calls)

    def test_t3_an_account_that_holds_another_pcs_backup_is_classified_and_dated(self):
        """T3: the guard names the case (a code the page reads), with the newest time Drive stamped on that backup."""
        self.drive.put('0123456789abcdef0123456789abcdef', b'sealed by some other key')
        client = self.svc._factory({})
        with mock.patch.object(self.drive, 'list', return_value=[{'id': 'p1', 'name': '0123456789abcdef0123456789abcdef',
                                                                  'modifiedTime': '2026-10-28T14:02:00.000Z'}]):
            with self.assertRaises(cloud_errors.ForeignBackup) as caught:
                self.service.guard(client)
        self.assertEqual(caught.exception.at, 1793196120000)
        c = self.svc.classified(caught.exception)
        self.assertEqual((c['code'], c['action']), ('foreign_backup', 'recover'))
        self.assertIn('already holds a Brainamon backup from another PC', c['message'])
        self.assertNotIn('Restore', c['message'])
        self.assertFalse(self.svc._publish())
        st = self.svc.status()
        self.assertEqual((st['error_code'], st['error_action']), ('foreign_backup', 'recover'))

    def test_t14_the_uploader_that_took_over_is_dated(self):
        self.setup_recovery()
        client = self.svc._factory({})
        state, key = self.service._load(), self.svc.mirror_key()
        found, owner = self.service._owner(self.drive, key, state['record']['header']['library'])
        owner['device'], owner['changed'] = 'another-pc', 1793196120
        name, _ = self.drive.files[found['id']]
        self.drive.files[found['id']] = name, key.seal(SR.OWNER_LOGICAL, R.dump(owner))
        with self.assertRaises(cloud_errors.NotUploader) as caught:
            self.service.guard(client, cached=False)
        self.assertEqual(caught.exception.at, 1793196120000)
        self.assertEqual(self.svc.classified(caught.exception)['code'], 'not_owner')
        self.assertIn('Another PC became the backup PC', str(caught.exception))
        self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc.status()['error_at'], 1793196120000)

    def test_preflight_is_read_only_and_distinguishes_missing_key(self):
        def check(expected):
            before = dict(self.drive.files)
            local = {p: p.read_bytes() for p in self.svc.cloud_dir.rglob('*') if p.is_file()}
            with mock.patch('core.private_storage.write', side_effect=AssertionError('preflight wrote protected storage')), \
                 mock.patch.object(self.drive, 'upload', side_effect=AssertionError('preflight wrote Drive')), \
                 mock.patch.object(self.service, '_save', side_effect=AssertionError('preflight saved state')), \
                 mock.patch.object(self.svc, '_end_mirror', side_effect=AssertionError('preflight paused uploads')):
                result = self.service.preflight()
            self.assertEqual(result['state'], expected, result)
            self.assertEqual(self.drive.files, before)
            self.assertEqual({p: p.read_bytes() for p in self.svc.cloud_dir.rglob('*') if p.is_file()}, local)
            return result
        check('ready')
        self.assertFalse(self.svc.key_path.exists())
        self.drive.put('solo-' + 'a' * 32 + '-' + 'b' * 32, b'phone')
        self.drive.put('vi-phone-recovery-' + 'a' * 32 + '-' + 'b' * 32 + '.json', b'phone recovery')
        check('ready')
        self.drive.put('unknown-library', b'keep')
        check('restore_required')
        self.drive.files.clear()
        self.assertTrue(self.svc._publish())
        check('ready')
        from core import private_storage
        private_storage.remove(self.svc.key_path)
        check('restore_required')
        private_storage.remove(self.svc.token_path)
        check('sign_in_required')

    def test_completion_survives_reload_without_a_kit_and_failed_reenrollment(self):
        kit = self.service.enroll(PASSWORD, PASSWORD)
        self.assertTrue(self.service.status()['enrolled'])
        self.assertFalse(self.service.status()['verified'])
        previous = self.service._load()
        with mock.patch.object(self.drive, 'upload', side_effect=drive_client.DriveError('offline')):
            with self.assertRaises(drive_client.DriveError):
                self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.service._load(), previous)
        self.assertTrue(self.service.status()['enrolled'])
        for secret in (PASSWORD, kit['secret'], self.svc.mirror_key().text()):
            self.assertNotIn(secret, json.dumps(self.service.preflight()))

    def test_interrupted_and_old_enrollment_need_authenticated_evidence(self):
        with mock.patch.object(self.drive, 'upload', side_effect=drive_client.DriveError('offline')):
            with self.assertRaises(drive_client.DriveError):
                self.service.enroll(PASSWORD, PASSWORD)
        self.assertTrue(self.service.status()['configured'])
        self.assertFalse(self.service.status()['enrolled'])
        self.assertFalse(self.service.preflight()['enrolled'])
        self.service.enroll(PASSWORD, PASSWORD)
        state = self.service._load()
        state.pop('enrolled')
        self.service._save(state)
        self.assertFalse(self.service.status()['enrolled'])
        self.assertTrue(self.service.preflight()['enrolled'])
        with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('offline')):
            self.assertEqual(self.service.preflight()['state'], 'retry')
        record = next(f for f in self.drive.list() if f['name'] == R.name(state['record']))
        del self.drive.files[record['id']]
        self.assertFalse(self.service.preflight()['enrolled'])

    def test_explicit_account_switch_checks_new_data_and_preserves_prior_recovery_on_failure(self):
        self.service.enroll(PASSWORD, PASSWORD)
        previous = self.service._load()
        other = FakeDrive()
        self.svc._raw_factory = lambda token: other
        self.writer.call(lambda db: (db.set_setting('cloud_epoch', ''), db.set_setting('cloud_account', 'other@example.com')))
        with mock.patch.object(other, 'about', return_value={'email': 'other@example.com'}):
            self.assertEqual(self.service.preflight()['state'], 'ready')
            with mock.patch.object(other, 'upload', side_effect=drive_client.DriveError('offline')):
                with self.assertRaises(drive_client.DriveError):
                    self.service.enroll(PASSWORD, PASSWORD)
            self.assertEqual(self.service._optional(self.svc.cloud_dir / 'recovery-enrollment-previous.json'), previous)
            self.assertEqual(self.service._load()['account'], 'other@example.com')
            self.assertFalse(self.service.status()['enrolled'])
            with mock.patch.object(self.service, '_write_owner', side_effect=drive_client.DriveError('interrupted')):
                with self.assertRaises(drive_client.DriveError):
                    self.service.enroll(PASSWORD, PASSWORD)
            self.assertEqual(self.service.preflight()['state'], 'ready')
            self.assertEqual(self.service._optional(self.svc.cloud_dir / 'recovery-enrollment-previous.json'), previous)
            self.service.enroll(PASSWORD, PASSWORD)
            self.assertTrue(self.service.status()['enrolled'])
            # A later explicit fresh account still rejects unknown data.
            self.service.path = self.svc.cloud_dir / 'fresh-recovery.json'
            self.writer.call(lambda db: db.set_setting('cloud_epoch', ''))
            other.files.clear()
            other.put('unknown-library', b'keep')
            self.assertEqual(self.service.preflight()['state'], 'restore_required')

    def test_envelope_without_owner_remains_resumable_and_failed_final_save_keeps_previous(self):
        with mock.patch.object(self.service, '_write_owner', side_effect=drive_client.DriveError('interrupted')):
            with self.assertRaises(drive_client.DriveError):
                self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.service.preflight()['state'], 'ready')
        self.assertFalse(self.service.preflight()['enrolled'])
        self.service.enroll(PASSWORD, PASSWORD)
        previous = self.service._load()
        save = self.service._save
        def fail_completion(state):
            if state['record'] != previous['record'] and state.get('enrolled'):
                raise OSError('synthetic completion write failed')
            save(state)
        with mock.patch.object(self.service, '_save', side_effect=fail_completion):
            with self.assertRaises(OSError):
                self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.service._load(), previous)

    def test_reconcile_persists_only_authenticated_old_completion(self):
        with mock.patch.object(self.drive, 'upload', side_effect=drive_client.DriveError('offline')):
            with self.assertRaises(drive_client.DriveError):
                self.service.enroll(PASSWORD, PASSWORD)
        before = self.service._load()
        with self.assertRaises(R.RecoveryError):
            self.service.reconcile()
        self.assertEqual(self.service._load(), before)
        self.service.enroll(PASSWORD, PASSWORD)
        state = self.service._load()
        state.pop('enrolled')
        self.service._save(state)
        remote = dict(self.drive.files)
        self.assertTrue(self.service.reconcile()['enrolled'])
        self.assertTrue(self.service._load()['enrolled'])
        self.assertEqual(self.drive.files, remote)

    def test_preflight_rechecks_account_rotation_duplicates_and_concurrent_upload(self):
        self.service.enroll(PASSWORD, PASSWORD)
        with mock.patch.object(self.drive, 'about', side_effect=drive_client.DriveError('private-token-marker', 401)):
            result = self.service.preflight()
            self.assertEqual(result['state'], 'sign_in_required')
            self.assertNotIn('private-token-marker', json.dumps(result))
        with mock.patch.object(self.drive, 'about', return_value={'email': 'other@example.com'}):
            self.assertEqual(self.service.preflight()['state'], 'account_mismatch')
            with self.assertRaisesRegex(R.RecoveryError, 'Reconnect'):
                self.service.enroll(PASSWORD, PASSWORD)
        with mock.patch.object(self.svc, '_rotation', return_value={'stage': 'prepared'}):
            self.assertEqual(self.service.preflight()['state'], 'rotation_pending')
        with mock.patch.object(self.svc, '_publishing') as lock:
            lock.acquire.return_value = False
            self.assertEqual(self.service.preflight()['state'], 'retry')
            lock.release.assert_not_called()
        f = next(f for f in self.drive.list() if f['name'].startswith(R.PREFIX + 'owner-'))
        self.drive.put(f['name'], self.drive.files[f['id']][1])
        self.assertNotEqual(self.service.preflight()['state'], 'ready')

    def test_fresh_upload_does_not_delete_an_unknown_existing_drive_library(self):
        fid = self.drive.put('unknown-original-library', b'original')
        before = dict(self.drive.files)
        self.assertFalse(self.svc._publish())
        self.assertEqual(self.drive.files, before)
        self.assertFalse(self.svc.key_path.exists())
        with self.assertRaisesRegex(R.RecoveryError, 'already contains'):
            self.service.enroll(PASSWORD, PASSWORD)
        self.assertIn(fid, self.drive.files)

    def test_fresh_upload_works_without_recovery(self):
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = self.svc.mirror_key()
        self.assertFalse(self.service.status()['configured'])
        self.assertIn(key.name(mirror.MANIFEST), {n for n, _ in self.drive.files.values()})
        self.assertTrue(self.svc._publish(), self.svc.status())

    def test_desktop_backup_coexists_with_standalone_phone_backup(self):
        from core import license
        license.remove()
        name = 'solo-' + 'a' * 32 + '-' + 'b' * 32
        fid = self.drive.put(name, b'separate encrypted phone backup')
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertEqual(self.drive.files[fid], (name, b'separate encrypted phone backup'))
        # Neither licensed phone intake nor desktop publication owns the solo namespace.
        with mock.patch('core.entitlements.feature_enabled', return_value=True):
            self.assertFalse(self.svc._intake())
        self.assertTrue(self.svc._publish())
        self.assertEqual(self.drive.files[fid], (name, b'separate encrypted phone backup'))

    def test_recovery_added_after_upload_keeps_the_key_and_does_not_require_a_kit(self):
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = self.svc.mirror_key()
        kit = self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.svc.mirror_key().master, key.master)
        self.assertFalse(self.service.status()['verified'])
        self.assertEqual(R.unlock(kit['record'], password=PASSWORD).master, key.master)
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.service.verify_kit(R.dump(kit).decode())
        self.assertTrue(self.svc._publish())
        status = R.dump(self.service.status()).decode()
        for secret in (key.text(), kit['secret'], PASSWORD, 'refresh_token'):
            self.assertNotIn(secret, status)

    def test_recovery_added_during_an_upload_takes_the_next_slot_and_the_upload_goes_on(self):
        """S3: the click returns at once with the kit; the sync thread ends the export between two requests, saves the record,
        and the same thread publishes again. Back-to-back uploads cannot starve it."""
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        upload = self.drive.upload

        def blocked(*args, **kwargs):
            if not entered.is_set():
                entered.set()
                release.wait(10)
            return upload(*args, **kwargs)

        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.drive, 'upload', side_effect=blocked):
            self.svc.turn_on()
            self.assertTrue(entered.wait(5))
            thread = self.svc._thread
            key = self.svc.mirror_key()
            t0 = time.monotonic()
            kit = self.service.enroll(PASSWORD, PASSWORD)
            self.assertLess(time.monotonic() - t0, 5)                       # queued: nothing joined
            task = self.svc.status()['task']
            self.assertEqual((task['kind'], task['stage']), ('enroll', 'queued'))
            self.assertFalse(self.service.status()['configured'])           # nothing was set up yet
            release.set()
            self.assertTrue(self.wait(lambda: self.service.status()['enrolled']), self.svc.status())
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0 and not self.svc.status()['task']))
            self.assertTrue(thread.is_alive() and self.svc.running)         # the same thread: uploads never stopped
            self.assertEqual(self.svc.mirror_key().master, key.master)
            self.assertEqual(R.unlock(kit['record'], password=PASSWORD).master, key.master)
            self.assertFalse(self.service.status()['verified'])
            self.svc.turn_off()

    def test_optional_recovery_can_be_added_after_vault_only_sync(self):
        vault = self.root / 'vault'
        vault.mkdir()
        (vault / 'note.md').write_text('vault note')
        key = self.svc.mirror_key()
        client = self.svc._factory({'refresh_token': 'synthetic'}, phone=True)
        self.svc._vault_round(client, key, vault)
        kit = self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(R.unlock(kit['record'], password=PASSWORD).master, key.master)
        self.assertTrue(self.svc._publish(), self.svc.status())

    def test_recovery_setup_resumes_active_vault_sync(self):
        vault = self.root / 'vault'
        vault.mkdir()
        self.writer.call(lambda db: db.set_setting('obsidian_vault', str(vault)))
        entered = threading.Event()

        def round(client, key, root, **kwargs):
            entered.set()
            self.svc._vault_stop.wait(5)

        with mock.patch.object(self.svc, '_vault_round', side_effect=round):
            self.svc.turn_vault_on()
            self.assertTrue(entered.wait(5))
            thread = self.svc._vault_thread
            key = self.svc.mirror_key()
            self.service.enroll(PASSWORD, PASSWORD)        # S3: queued; the one-time sync thread ends the vault round, saves, resumes it
            self.assertTrue(self.wait(lambda: self.service.status()['enrolled']), self.svc.status())
            self.assertTrue(self.wait(lambda: self.svc.vault_running and self.svc._vault_thread is not thread))
            self.assertFalse(thread.is_alive())
            self.assertEqual(self.svc.mirror_key().master, key.master)

    def test_failed_recovery_setup_resumes_existing_uploads(self):
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = self.svc.mirror_key()
        self.svc.turn_on()
        with mock.patch.object(R, 'create', side_effect=R.RecoveryError('synthetic setup failure')):
            with self.assertRaisesRegex(R.RecoveryError, 'synthetic setup failure'):
                self.service.enroll(PASSWORD, PASSWORD)
        self.assertTrue(self.svc.running)
        self.assertEqual(self.svc.mirror_key().master, key.master)
        self.assertFalse(self.service.status()['configured'])
        self.assertTrue(self.svc._publish(), self.svc.status())

    def test_enrollment_does_not_replace_a_pending_rotation(self):
        self.setup_recovery()
        self.svc.unpair(PASSWORD)
        pending = self.svc._rotation()
        with self.assertRaisesRegex(R.RecoveryError, 'pending key rotation'):
            self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.svc._rotation(), pending)

    def test_pairing_control_created_before_enrollment_does_not_block_setup(self):
        key = self.svc.mirror_key()
        self.svc.publish_license_control()
        self.assertTrue(self.drive.files)
        self.setup_recovery()
        self.assertEqual(self.svc.mirror_key().master, key.master)
        self.assertTrue(self.svc._publish())

    def test_failed_enrollment_keeps_previous_verified_generation(self):
        self.setup_recovery()
        previous = self.service._load()
        with mock.patch.object(self.drive, 'download', side_effect=drive_client.DriveError('synthetic offline')):
            with self.assertRaises(drive_client.DriveError):
                self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.service._load(), previous)

    def test_interrupted_first_enrollment_keeps_candidate_and_can_retry(self):
        with mock.patch.object(self.drive, 'upload', side_effect=drive_client.DriveError('synthetic offline')):
            with self.assertRaises(drive_client.DriveError):
                self.service.enroll(PASSWORD, PASSWORD)
        key = self.svc.mirror_key().master
        self.assertFalse(self.service.status()['verified'])
        self.setup_recovery()
        self.assertEqual(self.svc.mirror_key().master, key)
        self.assertTrue(self.svc._publish())

    def test_saved_kit_never_overwrites_an_existing_file(self):
        kit = self.setup_recovery()
        path = self.root / 'saved-kit.json'
        self.service.save_kit(str(path))
        self.assertEqual(json.loads(path.read_bytes()), kit)
        with self.assertRaises(R.RecoveryError):
            self.service.save_kit(str(path))
        self.assertEqual(json.loads(path.read_bytes()), kit)

    def test_bounded_drive_read_rejects_oversized_response(self):
        from library.drive_client import DriveClient
        client = DriveClient('synthetic', '', {'access_token': 'synthetic', 'expires_at': 9999999999})
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status, response.headers = 200, {}
        response.read.return_value = b'x' * 11
        with mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(drive_client.DriveError, 'limit'):
                client.download_bounded('synthetic-file', 10)
        response.read.assert_called_once_with(11)

    def test_duplicate_discovery_is_not_silently_selected(self):
        kit = self.setup_recovery()
        self.drive.put(R.name(kit['record']), R.dump(kit['record']))
        with self.assertRaisesRegex(R.RecoveryError, 'Duplicate'):
            self.service.discover()

    def test_preflight_and_preview_each_use_one_fresh_listing(self):
        kit = self.setup_recovery()
        with mock.patch.object(self.drive, 'list', wraps=self.drive.list) as listing:
            self.assertEqual(self.service.preflight()['state'], 'ready')
            self.assertEqual(listing.call_count, 1)
        self.assertTrue(self.svc._publish())
        generation = self.service.discover()[0]
        with mock.patch.object(self.drive, 'list', wraps=self.drive.list) as listing:
            result = self.service.preview(file_id=generation['id'], password=PASSWORD)
            self.assertTrue(result['preview']['reconnect']['ok'])
            self.assertEqual(listing.call_count, 1)
        # A later operation must see new remote state, not a cached account listing.
        self.drive.put(R.name(kit['record']), R.dump(kit['record']))
        self.assertNotEqual(self.service.preflight()['state'], 'ready')

    def test_discovery_downloads_four_records_at_a_time_and_stops_on_failure(self):
        kit = self.service.enroll(PASSWORD, PASSWORD)
        for n in range(1, 8):
            record = copy.deepcopy(kit['record'])
            record['header']['generation'] = f'{n:032x}'
            record['header']['created'] += n
            self.drive.put(R.name(record), R.dump(record))
        # Discovery validates metadata; only the subsequent unlock authenticates its envelope.
        barrier = threading.Barrier(4)
        download = self.drive.download

        def overlap(file_id):
            barrier.wait(timeout=5)
            return download(file_id)

        with mock.patch.object(self.drive, 'download', side_effect=overlap):
            found = self.service.discover()
        self.assertEqual(len(found), 8)
        self.assertEqual([r['created'] for r in found], sorted((r['created'] for r in found), reverse=True))
        with mock.patch.object(self.drive, 'download', side_effect=drive_client.DriveError('offline')) as failed:
            with self.assertRaises(drive_client.DriveError):
                self.service.discover()
            self.assertLessEqual(failed.call_count, 4)

    def test_passphrase_restore_is_read_only_and_activation_requires_explicit_step(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish())
        generation = self.service.discover()[0]
        before = dict(self.drive.files)
        self.service.preview(file_id=generation['id'], password=PASSWORD)
        target = self.root / 'replacement'
        self.service.start_restore(str(target))
        self.service.thread.join(15)
        self.assertEqual(self.service.status()['job']['state'], 'complete', self.service.status())
        self.assertTrue((target / 'content_manager.db').is_file())
        self.assertEqual(self.drive.files, before)
        with mock.patch('core.app_paths.set_data_dir') as pointer, mock.patch.dict('os.environ', {'CM_DATA_DIR': ''}):
            result = self.service.activate()
            pointer.assert_called_once_with(target)
        self.assertTrue(result['restart'])
        self.assertEqual(self.drive.files, before)
        with self.assertRaises(drive_client.DriveError):
            self.service.guard(self.drive)

    def test_rotation_needs_the_passphrase_but_no_kit_before_the_key_switch(self):
        """D1: the replacement recovery file comes after the key switch, with a reminder until it is saved and read back."""
        oldkit = self.setup_recovery()
        self.assertTrue(self.svc._publish())
        oldkey = self.svc.mirror_key()
        with self.assertRaises(R.RecoveryError):
            self.svc.unpair('an incorrect recovery phrase')
        self.assertIsNone(self.svc._rotation())                      # a wrong passphrase starts nothing
        self.svc.unpair(PASSWORD)
        self.assertEqual(self.svc.mirror_key().master, self.svc._rotation_key(self.svc._rotation()['new']).master)   # D15: pairing gets the new key
        self.assertEqual(self.svc._key().master, oldkey.master)      # not switched yet
        newkit = self.service.export_kit()
        self.assertNotEqual(newkit['record']['header']['fingerprint'], oldkey.fingerprint)
        self.assertFalse(self.service.status()['enrolled'])
        self.assertTrue(self.svc._publish(), self.svc.status())      # no kit click in between
        self.assertTrue(self.service.status()['enrolled'])
        self.assertNotEqual(self.svc.mirror_key().master, oldkey.master)
        self.assertEqual(self.service._load()['record'], newkit['record'])
        self.assertEqual(R.import_key(R.dump(oldkit).decode())[0].master, oldkey.master)
        status = self.service.status()
        self.assertTrue(status['file_outdated'] and not status['verified'] and status['replaced_at'])
        self.service.verify_kit(R.dump(newkit).decode())             # the reminder ends when the new file is read back
        status = self.service.status()
        self.assertTrue(status['verified'] and not status['file_outdated'])

    def test_status_and_conflict_message_remain_available_during_kit_verification(self):
        kit = self.setup_recovery()
        entered, release = threading.Event(), threading.Event()
        original = self.drive.about
        errors = []

        def slow_account():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test timed out')
            return original()

        def verify():
            try:
                self.service.verify_kit(R.dump(kit).decode())
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(self.drive, 'about', side_effect=slow_account):
            thread = threading.Thread(target=verify, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                start = time.monotonic()
                status = self.service.status()
                self.assertLess(time.monotonic() - start, 1)
                self.assertEqual(status['activity']['action'], 'verify')
                self.assertIn('Google account', status['activity']['step'])
                self.assertNotIn(PASSWORD, json.dumps(status))
                with self.assertRaisesRegex(SR.Busy, 'Google account'):
                    self.svc.mirror_key()
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNone(self.service.status()['activity'])

    def test_unpair_stops_active_publisher_before_acquiring_its_lock(self):
        entered = threading.Event()

        def publishing():
            with self.svc._publishing:
                entered.set()
                self.svc._stop.wait(5)

        thread = self.svc._thread = threading.Thread(target=publishing, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(5))
        try:
            start = time.monotonic()
            self.svc.unpair()
            self.assertLess(time.monotonic() - start, 2)
            self.assertEqual(self.svc._rotation()['stage'], 'prepared')
        finally:
            self.svc._stop.set()
            thread.join(5)

    def test_unpair_is_accepted_while_a_publisher_runs_and_a_second_click_is_busy(self):
        """S3: a busy publisher delays the re-encrypting, never the click; one removal, one set of replacement records (A19)."""
        with self.svc._publishing:
            start = time.monotonic()
            self.svc.unpair()
            self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.svc._rotation()['stage'], 'prepared')
        self.assertIn('Phones locked out at', self.svc.status()['rotation_lock'])
        self.assertIsNone(self.service.status()['activity'])
        before = self.svc._rotation()
        with self.assertRaises(SR.Busy):
            self.svc.unpair()                                     # the second click: refused, nothing changed
        self.assertEqual(self.svc._rotation(), before)

    def expire(self):
        return mock.patch.object(self.drive, 'about', side_effect=drive_client.DriveError(drive_client.SIGN_IN_REQUIRED, 401))

    def test_a6_a_failed_step_keeps_its_code_and_sentence_after_settings_closes(self):
        """Closing Settings drops the page, not the activity: the saved failure is the classified one (A14, server half)."""
        with self.expire(), self.assertRaises(drive_client.DriveError):
            self.service.enroll(PASSWORD, PASSWORD)
        activity = self.service.status()['activity']                     # what a reopened page reads
        self.assertEqual((activity['action'], activity['state'], activity['code'], activity['next']),
                         ('enroll', 'error', 'auth_expired', 'sign_in_again'))
        self.assertIn('Choose Sign in again', activity['step'])
        self.assertNotIn('Change account', activity['step'])
        with self.assertRaises(R.RecoveryError) as caught:
            self.service.verify_kit('not a kit')
        activity = self.service.status()['activity']                     # a recovery sentence is kept as written
        self.assertEqual((activity['action'], activity['code'], activity['next']), ('verify', 'other', 'none'))
        self.assertEqual(activity['step'], str(caught.exception))
        self.setup_recovery()
        self.assertIsNone(self.service.status()['activity'])             # a step that finishes clears it

    def test_a6_the_recovery_check_asks_for_a_new_sign_in_in_the_same_words(self):
        with self.expire():
            out = self.service.preflight()
        self.assertEqual((out['state'], out['code'], out['action']), ('sign_in_required', 'auth_expired', 'sign_in_again'))
        self.assertIn('Choose Sign in again', out['message'])
        self.assertNotIn('Change account', out['message'])

    def test_a6_a_restore_that_loses_its_sign_in_says_so(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.service.preview(password=PASSWORD)
        with mock.patch.object(restore, 'materialize', side_effect=drive_client.DriveError(drive_client.SIGN_IN_REQUIRED, 401)):
            self.service.start_restore(str(self.root / 'recovered-after-401'))
            self.service.thread.join(15)
        job = self.service.status()['job']
        self.assertEqual((job['state'], job['code'], job['action']), ('error', 'auth_expired', 'sign_in_again'))
        self.assertIn('Choose Sign in again', job['error'])

    def test_i7_save_kit_is_remembered_across_reopening_settings(self):
        """R6: "saved, not checked" is the PC's record (`saved_at`), not component state."""
        self.assertEqual(self.service.status()['saved_at'], 0)
        kit = self.service.enroll(PASSWORD, PASSWORD)
        self.assertEqual(self.service.status()['saved_at'], 0)
        path = self.root / 'kit-saved.json'
        self.assertTrue(self.service.save_kit(str(path))['verified'])      # D11: saved and read back against Drive in one step
        saved = self.service.status()
        self.assertTrue(saved['saved_at'] and saved['verified'])
        self.assertEqual(self.service.status()['saved_at'], saved['saved_at'])
        self.svc.unpair(PASSWORD)                                         # a replacement kit starts unsaved
        self.assertEqual(self.service.status()['saved_at'], 0)
        self.service.save_kit(str(self.root / 'replacement-kit-saved.json'))
        self.assertTrue(self.service.status()['saved_at'])

    def test_rotation_reports_verification_and_cleanup_before_completion(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish())
        self.svc.unpair(PASSWORD)
        with mock.patch.object(self.svc, '_set', wraps=self.svc._set) as updates:
            self.assertTrue(self.svc._publish(), self.svc.status())
        stages = [call.kwargs.get('upload_step', '') for call in updates.call_args_list]
        self.assertTrue(any('Verifying the uploaded library' in stage for stage in stages))
        self.assertTrue(any('Removing the old encrypted copies' in stage for stage in stages))
        self.assertEqual(self.svc._rotation()['stage'], 'complete')

    def test_interrupted_activation_keeps_a_journal_and_retries_without_cloud_writes(self):
        kit = self.setup_recovery()
        self.assertTrue(self.svc._publish())
        self.service.preview(material=R.dump(kit).decode())
        target = self.root / 'activation-retry'
        self.service.start_restore(str(target))
        self.service.thread.join(15)
        self.assertEqual(self.service.job['state'], 'complete', self.service.job)
        before = dict(self.drive.files)
        with mock.patch.dict('os.environ', {'CM_DATA_DIR': ''}), mock.patch('core.app_paths.set_data_dir', side_effect=OSError('synthetic interruption')):
            with self.assertRaises(OSError):
                self.service.activate()
        journal = self.service._optional(self.service.journal)
        self.assertTrue(journal)
        backup = self.svc.cloud_dir / ('recovery-before-' + journal['activation'] + '.json')
        self.assertEqual(self.service._optional(backup)['key'], self.svc.mirror_key().text())
        with mock.patch('core.app_paths.set_data_dir') as pointer:
            self.assertEqual(self.service.finish_activation(), target)
            pointer.assert_called_once_with(target)
        self.assertIsNone(self.service._optional(self.service.journal))
        self.assertEqual(self.drive.files, before)

    def test_rotation_retries_interrupted_recovery_state_and_master_commits(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish())
        for point in ('state', 'master'):
            with self.subTest(point=point):
                self.svc.unpair(PASSWORD)
                kit = self.service.export_kit()
                patch = (mock.patch.object(self.service, '_save', side_effect=OSError('synthetic interruption'))
                         if point == 'state' else mock.patch.object(mirror.MirrorKey, 'save', side_effect=OSError('synthetic interruption')))
                with patch:
                    self.assertFalse(self.svc._publish())
                self.assertTrue(self.svc._publish(), self.svc.status())
                self.assertEqual(self.svc.mirror_key().fingerprint, kit['record']['header']['fingerprint'])
                self.assertEqual(self.svc._rotation()['stage'], 'complete')

    def test_replacement_pc_takes_over_without_duplicate_manifests_and_old_pc_pauses(self):
        from core import license
        license.remove()
        kit = self.setup_recovery()
        self.assertTrue(self.svc._publish())
        empty = self.root / 'empty-pc'
        new_writer = Writer(empty / 'content_manager.db')
        new_writer.start()
        new = SyncService(new_writer, Hub(), empty, self.root / 'new-cloud', client_factory=lambda token: self.drive)
        drive_client.save_token(new.token_path, {'refresh_token': 'replacement-synthetic'})
        target = self.root / 'replacement-library'
        try:
            new.recovery.preview(material=R.dump(kit).decode())
            new.recovery.start_restore(str(target))
            new.recovery.thread.join(15)
            self.assertEqual(new.recovery.job['state'], 'complete', new.recovery.job)
            with mock.patch('core.app_paths.set_data_dir'), mock.patch.dict('os.environ', {'CM_DATA_DIR': ''}):
                new.recovery.activate()
            with self.assertRaisesRegex(R.RecoveryError, 'Quit and reopen'):
                new.recovery.take_over(PASSWORD, PASSWORD)
        finally:
            new.recovery.shutdown()
            new.shutdown()
            new_writer.stop()
        writer = Writer(target / 'content_manager.db')
        writer.start()
        restarted = SyncService(writer, Hub(), target, self.root / 'new-cloud', client_factory=lambda token: self.drive)
        try:
            replacement_kit = restarted.recovery.take_over(PASSWORD, PASSWORD)
            restarted.recovery.verify_kit(R.dump(replacement_kit).decode())
            self.assertTrue(restarted._publish(), restarted.status())
            manifest_name = mirror.MirrorKey.load(restarted.key_path).name(mirror.MANIFEST)
            self.assertEqual(sum(n == manifest_name for n, _ in self.drive.files.values()), 1)
            before = dict(self.drive.files)
            self.assertFalse(self.svc._publish())
            self.assertIn('Another PC', self.svc.status()['error'])
            self.assertEqual((self.svc.status()['error_code'], self.svc.status()['error_action']), ('not_owner', 'recover'))
            self.assertEqual(self.drive.files, before)
        finally:
            restarted.shutdown()
            writer.stop()

    def test_a10_passphrase_restore_skips_a_setup_whose_removal_never_finished(self):
        """Probe D: after an unpair that never finished (replacement envelope uploaded, kit never checked, key
        switch never run) the newest recovery setup opens nothing. A passphrase restore must use the older one
        and say why, without the user picking from a list."""
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.interrupted_removal(time.time() + 3600)
        found = self.service.discover()                       # newest first
        self.assertEqual(len(found), 2)
        before = dict(self.drive.files)
        status = self.service.preview(password=PASSWORD)      # no file_id: Brainamon chooses the setup
        self.assertEqual(status['job']['state'], 'preview')
        self.assertEqual(status['preview']['generation'], {'created': found[1]['created'], 'fingerprint': found[1]['fingerprint']})
        self.assertIn('removing phones did not finish', status['preview']['notice'])
        self.assertEqual(self.drive.files, before)             # read-only

    def test_a10_the_notice_names_both_setups_by_day(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.interrupted_removal(time.time() + 3 * 86400)
        found = self.service.discover()
        notice = self.service.preview(password=PASSWORD)['preview']['notice']
        self.assertEqual(notice, f"Used the recovery setup from {SR._day(found[1]['created'])}. "
                                 f"The newer one from {SR._day(found[0]['created'])} has no backup because removing phones did not finish.")
        self.assertNotEqual(SR._day(found[0]['created']), SR._day(found[1]['created']))

    def test_a10_one_setup_needs_no_choice_and_no_notice(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        before = dict(self.drive.files)
        status = self.service.preview(password=PASSWORD)
        header = self.service.discover()[0]
        self.assertEqual((status['preview']['notice'], status['preview']['generation']),
                         ('', {'created': header['created'], 'fingerprint': header['fingerprint']}))
        self.assertEqual(self.drive.files, before)

    def test_a10_a_passphrase_that_opens_nothing_is_the_users_error_not_a_missing_backup(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        before = dict(self.drive.files)
        with self.assertRaisesRegex(R.RecoveryError, "doesn't unlock a backup in fred@example.com"):
            self.service.preview(password='another long synthetic phrase')
        self.assertIsNone(self.service.status()['preview'])
        self.assertEqual(self.drive.files, before)

    def test_a10_an_account_with_no_recovery_setup_says_the_passphrase_unlocks_nothing(self):
        self.assertTrue(self.svc._publish(), self.svc.status())            # a backup, but no passphrase was ever set up
        with self.assertRaisesRegex(R.RecoveryError, "doesn't unlock a backup"):
            self.service.preview(password=PASSWORD)

    def test_a10_a_setup_that_opens_but_has_no_backup_keeps_the_no_mirror_message(self):
        self.setup_recovery()                                               # recovery set up, nothing uploaded yet
        before = dict(self.drive.files)
        with self.assertRaises(restore.NoMirror):
            self.service.preview(password=PASSWORD)
        self.assertEqual(self.drive.files, before)

    def test_a10_another_refusal_of_a_real_backup_is_not_skipped_for_an_older_setup(self):
        """Only a missing backup falls back. A newest setup whose backup exists but cannot be used (here: a format
        this version cannot read) must say so instead of silently restoring an older, different copy."""
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        with mock.patch.object(restore, '_check_manifest', side_effect=R.RecoveryError('Update Brainamon to restore this library format.')):
            with self.assertRaisesRegex(R.RecoveryError, 'Update Brainamon'):
                self.service.preview(password=PASSWORD)

    def rotated(self):
        """A completed removal of phones a few days after the first setup: (old kit, old key, new kit, day it ran)."""
        old_kit = self.setup_recovery()
        old_key = self.svc.mirror_key()
        self.assertTrue(self.svc._publish(), self.svc.status())
        later = time.time() + 3 * 86400
        with mock.patch.object(R, 'time', mock.Mock(time=lambda: later)):
            self.svc.unpair(PASSWORD)
        new_kit = self.service.export_kit()
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.service.verify_kit(R.dump(new_kit).decode())
        self.assertNotEqual(self.svc.mirror_key().master, old_key.master)
        return old_kit, old_key, new_kit, int(later)

    def test_a11_an_outdated_kit_says_when_phones_were_removed(self):
        old_kit, _old_key, new_kit, later = self.rotated()
        before = dict(self.drive.files)
        with self.assertRaisesRegex(R.RecoveryError, f'This recovery file is from before phones were removed on {SR._day(later)}\\. '
                                                       'Use your passphrase or the newer recovery file\\.'):
            self.service.preview(material=R.dump(old_kit).decode())
        self.assertEqual(self.drive.files, before)
        status = self.service.preview(material=R.dump(new_kit).decode())          # the newer file opens the backup
        self.assertEqual(status['preview']['generation']['fingerprint'], new_kit['record']['header']['fingerprint'])
        self.assertEqual(status['preview']['notice'], '')
        self.assertEqual(self.drive.files, before)

    def test_a11_an_outdated_phone_code_says_so(self):
        _old_kit, old_key, _new_kit, _later = self.rotated()
        before = dict(self.drive.files)
        for code in (old_key.text(), R.dump({'format': R.PHONE_FORMAT, 'version': 1, 'key': R.encode(old_key.master),
                                             'fingerprint': old_key.fingerprint}).decode()):
            with self.subTest(code=code[:12]):
                with self.assertRaisesRegex(R.RecoveryError, 'That phone code is from before phones were removed\\. '
                                                               'Use a phone you added again, or your passphrase\\.'):
                    self.service.preview(material=code)
        self.assertEqual(self.drive.files, before)

    def test_a11_a_code_from_nowhere_keeps_the_plain_message(self):
        """With no recovery setup in the account nothing says a removal happened, so the plain message stands (after D5 the
        setups of a removed key are gone, so a setup in the account is the evidence for the 'before phones were removed' one)."""
        self.assertTrue(self.svc._publish(), self.svc.status())
        with self.assertRaisesRegex(restore.NoMirror, 'No library mirror matches this key'):
            self.service.preview(material=mirror.MirrorKey.generate().text())

    def test_a11_the_passphrase_restore_after_a_removal_uses_the_current_setup_without_a_notice(self):
        self.rotated()
        status = self.service.preview(password=PASSWORD)
        newest = self.service.discover()[0]
        self.assertEqual(status['preview']['generation'], {'created': newest['created'], 'fingerprint': newest['fingerprint']})
        self.assertEqual(status['preview']['notice'], '')

    def test_a4_restore_and_recovery_check_use_the_newest_valid_manifest_among_duplicates(self):
        """I3: two extra manifest copies under the same name, one older but valid, one newer but naming a file Drive
        does not hold. Preview picks the current one, read-only; the recovery check stays ready; the next upload
        heals the Drive."""
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = self.svc.mirror_key()
        name = key.name(mirror.MANIFEST)
        current = json.loads(key.open(mirror.MANIFEST, self.drive.by_name(name)))
        stale = dict(current, published=current['published'] - 60_000)
        self.drive.put(name, key.seal(mirror.MANIFEST, json.dumps(stale).encode()))
        broken = dict(current, published=current['published'] + 120_000,
                      files={**current['files'], 'notes/knees.md': {**current['files']['notes/knees.md'], 'id': 'gone'}})
        self.drive.put(name, key.seal(mirror.MANIFEST, json.dumps(broken).encode()))
        before = dict(self.drive.files)
        snap = restore.preview(self.drive, key)
        self.assertEqual((snap['published'], snap['duplicates'], snap['items']), (current['published'], 2, 6))
        self.assertEqual(self.drive.files, before)                                  # read-only
        self.assertEqual(self.service.preflight()['state'], 'ready')                # this key's copies never block setup
        generation = self.service.discover()[0]
        self.assertEqual(self.service.preview(file_id=generation['id'], password=PASSWORD)['preview']['duplicates'], 2)
        self.assertEqual(self.drive.files, before)
        self.assertTrue(self.svc._publish(), self.svc.status())                    # the uploader heals
        self.assertEqual(sum(n == name for n, _ in self.drive.files.values()), 1)
        self.assertEqual(restore.preview(self.drive, key)['duplicates'], 0)
        self.assertIn('2 duplicate copies', self.svc.status()['last_summary'])

    def test_a7_enroll_during_a_slow_request_is_queued_and_runs_when_the_request_ends(self):
        """S3 (was I4): setting up recovery while one upload request runs joins nothing: it is saved as a task, nothing is set
        up yet, and the same thread runs it after the request. Uploads never stop."""
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        release, entered = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow_publish(stop=None):
            with self.svc._publishing:
                entered.set()
                release.wait(30)
            return False
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', slow_publish):
            self.svc.start()
            try:
                self.assertTrue(entered.wait(5))
                old = self.svc._thread
                t0 = time.monotonic()
                self.service.enroll(PASSWORD, PASSWORD)
                self.assertLess(time.monotonic() - t0, 5)
                self.assertTrue(old.is_alive())
                self.assertEqual(self.svc.status()['task']['stage'], 'queued')
                self.assertFalse(self.service.status()['configured'])           # nothing was set up
                release.set()
                self.assertTrue(self.wait(lambda: self.service.status()['enrolled']), self.svc.status())
                self.assertTrue(old.is_alive() and self.svc.running)            # the same thread
            finally:
                release.set()
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), 'on')


    # ── S4 / S3 (sub-plan 08): the decisions in the backend ────────────────────────────────
    def test_enrolled_offline_removal_records_lockout(self):
        self.setup_recovery()
        old = self.svc._key()
        with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('offline')), \
                mock.patch.object(self.drive, 'download', side_effect=AssertionError('offline download')):
            self.svc.unpair(PASSWORD)
        rotation = self.svc._rotation()
        self.assertEqual(rotation['old'], old.text())
        self.assertTrue(rotation['lock_pending'])
        self.assertTrue(rotation['clicked'])
        self.assertNotEqual(self.svc.mirror_key().fingerprint, old.fingerprint)

    NEW_PASSWORD = 'a brand new synthetic passphrase'

    def recovery_names(self):
        return sorted(n for n, _ in self.drive.files.values() if n.startswith(R.PREFIX) and not n.startswith(R.PREFIX + 'owner-'))

    def restore_path_exists(self, password, label):
        """The passphrase opens a setup whose key opens a complete manifest, read only (A16)."""
        before = dict(self.drive.files)
        status = self.service.preview(password=password)
        self.assertEqual(status['job']['state'], 'preview', label)
        self.assertEqual(restore.preview(self.drive, self.service.session['key'])['items'], 6, label)
        self.assertEqual(self.drive.files, before, label)
        return status['preview']

    def test_a16_a_forgotten_passphrase_is_replaced_while_removing_phones_and_a_restore_path_exists_at_every_stage(self):
        """D2: the new passphrase also opens the old key until the old copy is deleted; F7: the current one is not needed."""
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        old_key = self.svc._key()
        later = time.time() + 3600
        with mock.patch.object(R, 'time', mock.Mock(time=lambda: later)):
            self.svc.unpair('', new_passphrase=self.NEW_PASSWORD)             # no current passphrase typed
        new_key = self.svc._rotation_key(self.svc._rotation()['new'])
        self.assertEqual(len(self.recovery_names()), 3)                         # old setup, new key's, old key's under the new passphrase
        # 1. the click (online: the records are already up): the new passphrase opens the old key's complete copy
        preview = self.restore_path_exists(self.NEW_PASSWORD, 'requested')
        self.assertEqual(preview['generation']['fingerprint'], old_key.fingerprint)
        self.assertIn('removing phones did not finish', preview['notice'])
        # 2. the key switched, nothing of the new copy yet
        with mock.patch.object(DriveMirrorTarget, 'export', side_effect=sync_mod.ExportStopped()):
            self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc._rotation()['stage'], 'publishing')
        self.assertEqual(self.restore_path_exists(self.NEW_PASSWORD, 'publishing')['generation']['fingerprint'], old_key.fingerprint)
        # 3. the new copy is complete but the old one is not deleted yet
        with mock.patch.object(self.drive, 'delete', side_effect=drive_client.DriveError('synthetic: offline')):
            self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc._rotation()['stage'], 'cleanup')
        self.assertEqual(self.restore_path_exists(self.NEW_PASSWORD, 'cleanup')['generation']['fingerprint'], new_key.fingerprint)
        # 4. done: only the new key's setup is left, and only the new passphrase opens it
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertEqual(self.svc._rotation()['stage'], 'complete')
        self.assertEqual([h['fingerprint'] for h in self.service.discover()], [new_key.fingerprint])
        self.assertEqual(self.restore_path_exists(self.NEW_PASSWORD, 'complete')['notice'], '')
        with self.assertRaises(R.RecoveryError):
            self.service.preview(password=PASSWORD)                             # the old passphrase opens nothing now (D5)
        status = self.service.status()
        self.assertTrue(status['file_outdated'])                                # the new recovery file is still to be saved (D1)
        self.assertIsNone(self.svc.status()['task'])

    def test_a16_a_wrong_current_passphrase_still_refuses_when_no_new_one_is_given(self):
        self.setup_recovery()
        with self.assertRaises(R.RecoveryError):
            self.svc.unpair('')
        self.assertIsNone(self.svc._rotation())
        self.assertIsNone(self.svc.intents.find('remove_phones'))

    def test_a19_a_double_click_on_remove_all_phones_makes_one_removal_and_one_envelope(self):
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        outcomes = []

        def click():
            try:
                self.svc.unpair(PASSWORD)
                outcomes.append('ok')
            except SR.Busy:
                outcomes.append('busy')
        clicks = [threading.Thread(target=click) for _ in range(2)]
        for t in clicks:
            t.start()
        for t in clicks:
            t.join(30)
        self.assertEqual(sorted(outcomes), ['busy', 'ok'])
        self.assertEqual(len(self.recovery_names()), 2)                         # the old setup and ONE replacement
        with self.assertRaises(SR.Busy):
            self.svc.unpair(PASSWORD)                                           # and a later click, once the first returned
        self.assertEqual(len(self.recovery_names()), 2)
        self.assertEqual(len([i for i in self.svc.intents.all() if i['kind'] == 'remove_phones']), 1)
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertEqual(len(self.recovery_names()), 1)                         # the old key's setup went with the old copy (D5)

    def test_d5_changing_the_passphrase_removes_the_setup_it_replaces(self):
        self.setup_recovery()
        self.assertEqual(len(self.recovery_names()), 1)
        kit = self.service.enroll(self.NEW_PASSWORD, self.NEW_PASSWORD)
        self.assertEqual(self.recovery_names(), [R.name(kit['record'])])
        with self.assertRaises(R.RecoveryError):
            self.service.preview(password=PASSWORD)
        self.assertEqual(R.unlock(kit['record'], password=self.NEW_PASSWORD).master, self.svc._key().master)

    def test_d4_a_one_time_backup_runs_on_its_own_thread_and_leaves_backup_off(self):
        self.setup_recovery()
        self.svc.publish_once()
        self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0), self.svc.status())
        self.assertTrue(self.wait(lambda: not self.svc.running and not self.svc.status()['task']), self.svc.status())
        self.assertEqual(self.svc.status()['state'], 'off')
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), '')

    def test_finding_2_a_copy_from_before_an_unfinished_removal_removes_phones_again_at_take_over(self):
        """The restored copy holds the key the lost phone also holds. Becoming the backup PC runs the removal again with the
        passphrase just used, so the phone stays out (D3 reuse across the restart, finding 2)."""
        from core import license
        self.setup_recovery()
        self.assertTrue(self.svc._publish(), self.svc.status())
        old_key = self.svc._key()
        license.remove()
        later = time.time() + 3600
        with mock.patch.object(R, 'time', mock.Mock(time=lambda: later)):
            self.svc.unpair(PASSWORD)
        with mock.patch.object(DriveMirrorTarget, 'export', side_effect=sync_mod.ExportStopped()):
            self.assertFalse(self.svc._publish())                               # the key switched; the PC is lost here
        self.assertEqual(self.svc._rotation()['stage'], 'publishing')
        empty = self.root / 'empty-pc'
        new_writer = Writer(empty / 'content_manager.db')
        new_writer.start()
        new = SyncService(new_writer, Hub(), empty, self.root / 'new-cloud', client_factory=lambda token: self.drive)
        drive_client.save_token(new.token_path, {'refresh_token': 'replacement-synthetic'})
        target = self.root / 'replacement-library'
        try:
            preview = new.recovery.preview(password=PASSWORD)['preview']
            self.assertIn('removing phones did not finish', preview['notice'])
            self.assertNotIn(PASSWORD, json.dumps(new.recovery.status()))       # the passphrase is in memory only
            new.recovery.start_restore(str(target))
            new.recovery.thread.join(30)
            self.assertEqual(new.recovery.job['state'], 'complete', new.recovery.job)
            with mock.patch('core.app_paths.set_data_dir'), mock.patch.dict('os.environ', {'CM_DATA_DIR': ''}):
                new.recovery.activate()
            state = new.recovery._load()
            self.assertTrue(state['takeover'] and state['removal'])             # sealed at activation, for after the restart
            self.assertNotIn(PASSWORD, json.dumps(state))                       # records only, never the passphrase
        finally:
            new.recovery.shutdown()
            new.shutdown()
            new_writer.stop()
        writer = Writer(target / 'content_manager.db')
        writer.start()
        restarted = SyncService(writer, Hub(), target, self.root / 'new-cloud', client_factory=lambda token: self.drive)
        try:
            with mock.patch.object(restarted, 'ensure_running'):                # the test runs the publish itself
                kit = restarted.recovery.take_over('', '')                      # D3: nothing typed again
            self.assertEqual(R.unlock(kit['record'], password=PASSWORD).master, old_key.master)
            self.assertEqual(restarted._rotation()['stage'], 'prepared')        # the removal runs again
            self.assertEqual(restarted.intents.find('remove_phones')['stage'], 'requested')
            self.assertTrue(restarted._publish(), restarted.status())
            self.assertEqual(restarted._rotation()['stage'], 'complete')
            self.assertNotEqual(restarted._key().master, old_key.master)
            self.assertEqual(R.unlock(restarted.recovery._load()['record'], password=PASSWORD).master, restarted._key().master)
        finally:
            restarted.shutdown()
            writer.stop()


class RecoveryRoutesTest(unittest.TestCase):
    def setUp(self):
        from tests.auth_client import TestClient
        from tests.license_fixture import activate
        from server.app import create_app
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        activate(self, self.root)
        from core import license
        license.remove()
        self.app = create_app(data_dir=self.root / 'data', cloud_dir=self.root / 'cloud', port=8765,
                              web_dist=self.root / 'no-web', cards_dir=self.root / 'no-cards')
        self.c = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        self.drive = FakeDrive()
        self.app.state.sync._raw_factory = lambda token: self.drive
        drive_client.save_token(self.app.state.sync.token_path, {'refresh_token': 'synthetic'})

    def test_signin_does_not_upload_and_status_uses_cloud_view_contract(self):
        result = self.c.post('/api/cloud/recovery/sign-in', headers={'X-CM': '1'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn('seq', result.json())
        self.assertTrue(result.json()['signed_in'])
        self.assertFalse(result.json()['running'])
        self.assertFalse(self.app.state.sync.key_path.exists())
        self.assertEqual(self.drive.calls, [])

    def test_guard_bounds_confirmation_and_validation(self):
        self.assertEqual(self.c.post('/api/cloud/recovery/enroll').status_code, 403)
        self.assertEqual(self.c.get('/api/cloud/recovery', headers={'Authorization': 'Bearer wrong'}).status_code, 403)
        for action, body in (('enroll', {'password': 1}), ('preview', {'material': []}), ('activate', {}), ('take-over', {})):
            result = self.c.post('/api/cloud/recovery/' + action, json=body, headers={'X-CM': '1'})
            self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.c.post('/api/cloud/recovery/preview', content=b'x' * 65537, headers={'X-CM': '1'}).status_code, 413)
        self.assertEqual(self.drive.files, {})

    def test_repaired_pointer_requires_fresh_imports_before_opening_restored_database(self):
        from server.app import create_app
        from server.recovery import RecoveryService
        with mock.patch.object(RecoveryService, 'finish_activation', return_value=self.root / 'restored'):
            with self.assertRaisesRegex(RuntimeError, 'Reopen Brainamon once more'):
                create_app(cloud_dir=self.root / 'cloud')

    def test_reconnect_route_needs_a_boolean_confirmation_and_stays_bounded(self):
        W = {'X-CM': '1'}
        service = self.app.state.sync.recovery
        secrets_ok = {'password': PASSWORD, 'confirmation': PASSWORD}
        with mock.patch.object(service, 'reconnect', return_value={'format': R.KIT_FORMAT}) as dispatch:
            for confirm in ({}, {'confirm': False}, {'confirm': 'true'}, {'confirm': 1}):
                with self.subTest(confirm=confirm):
                    result = self.c.post('/api/cloud/recovery/reconnect', json={**secrets_ok, **confirm}, headers=W)
                    self.assertEqual(result.status_code, 409, result.text)
            result = self.c.post('/api/cloud/recovery/reconnect', json={'confirm': True, 'password': 1, 'confirmation': PASSWORD}, headers=W)
            self.assertEqual(result.status_code, 409, result.text)
            self.assertEqual(self.c.post('/api/cloud/recovery/reconnect', content=b'x' * 65537, headers=W).status_code, 413)
            self.assertEqual(self.c.post('/api/cloud/recovery/reconnect', json={'confirm': True, **secrets_ok}).status_code, 403)
            self.assertEqual(self.c.post('/api/cloud/recovery/reconnect', json={'confirm': True, **secrets_ok},
                                         headers={**W, 'Authorization': 'Bearer wrong'}).status_code, 403)
            dispatch.assert_not_called()
            result = self.c.post('/api/cloud/recovery/reconnect', json={'confirm': True, **secrets_ok}, headers=W)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.headers['cache-control'], 'no-store')
            dispatch.assert_called_once_with(PASSWORD, PASSWORD)
        self.assertEqual(self.drive.files, {})

    def test_reconnect_blocks_conflicting_cloud_changes(self):
        from tests.license_fixture import activate
        activate(self, self.root)
        W = {'X-CM': '1'}
        service = self.app.state.sync.recovery
        held, release = threading.Event(), threading.Event()

        def hold():
            with service.mutation:
                held.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            self.assertTrue(held.wait(5))
            for method, path, body in (('post', '/api/cloud/connect', None), ('post', '/api/cloud/pair', {}),
                                       ('put', '/api/cloud/options', {'vault': True}), ('post', '/api/cloud/switch', None),
                                       ('post', '/api/cloud/sign-out', {}), ('post', '/api/cloud/unpair', {})):
                with self.subTest(path=path):
                    result = getattr(self.c, method)(path, json=body, headers=W)
                    self.assertEqual(result.status_code, 409, result.text)
                    self.assertEqual(result.json()['detail'], SR.BUSY)       # a busy refusal, never a failed write
        finally:
            release.set()
            holder.join(5)
        self.assertFalse(self.c.get('/api/cloud').json()['vault']['on'])
        self.assertIsNone(mirror.MirrorKey.load(self.app.state.sync.key_path))     # pairing made no key

    def test_enroll_verify_and_status_never_echo_recovery_secrets(self):
        W = {'X-CM': '1'}
        result = self.c.post('/api/cloud/recovery/enroll', json={'password': PASSWORD, 'confirmation': PASSWORD}, headers=W)
        self.assertEqual(result.status_code, 200, result.text)
        kit = result.json()
        self.assertNotIn(PASSWORD, result.text)
        result = self.c.post('/api/cloud/recovery/verify', json={'material': R.dump(kit).decode()}, headers=W)
        self.assertEqual(result.status_code, 200, result.text)
        status = self.c.get('/api/cloud/recovery')
        self.assertTrue(status.json()['verified'])
        self.assertNotIn(kit['secret'], status.text)

    def test_a6_a_401_answers_every_route_with_the_same_code_and_next_action(self):
        """Set up, verify, preview, restore, take over, keep this folder and unpair: an expired sign-in is `auth_expired`
        with the action Sign in again, and no sentence sends the user to Change account for a renewal."""
        W = {'X-CM': '1'}
        sync = self.app.state.sync
        service = sync.recovery
        expired = drive_client.DriveError(drive_client.SIGN_IN_REQUIRED, 401)
        both = {'password': PASSWORD, 'confirmation': PASSWORD}
        cases = (('/api/cloud/recovery/enroll', both, service, 'enroll'),
                 ('/api/cloud/recovery/verify', {'material': 'x'}, service, 'verify_kit'),
                 ('/api/cloud/recovery/preview', {'password': PASSWORD}, service, 'preview'),
                 ('/api/cloud/recovery/restore', {'destination': 'x'}, service, 'start_restore'),
                 ('/api/cloud/recovery/take-over', {'confirm': True, **both}, service, 'take_over'),
                 ('/api/cloud/recovery/reconnect', {'confirm': True, **both}, service, 'reconnect'),
                 ('/api/cloud/unpair', {}, sync, 'unpair'))
        for path, body, owner, method in cases:
            with self.subTest(path=path), mock.patch.object(owner, method, side_effect=expired):
                result = self.c.post(path, json=body, headers=W)
                self.assertEqual(result.status_code, 409, result.text)
                out = result.json()
                self.assertEqual((out['code'], out['action']), ('auth_expired', 'sign_in_again'))
                self.assertEqual(out['detail'], out['message'])
                self.assertIn('Choose Sign in again', out['message'])
                self.assertNotIn('Change account', result.text)

    def test_i7_other_failures_carry_their_own_code_and_a_license_refusal_stays_403(self):
        W = {'X-CM': '1'}
        sync = self.app.state.sync
        service = sync.recovery
        for exc, code, action in ((drive_client.DriveError('x', 403, 'storageQuotaExceeded'), 'drive_full', 'free_space'),
                                  (drive_client.DriveError('Google Drive is out of reach: x'), 'other', 'retry'),
                                  (SR.Busy(), 'busy', 'wait'), (R.RecoveryError('Select the recovery kit you just saved.'), 'other', 'none')):
            with self.subTest(code=code), mock.patch.object(service, 'verify_kit', side_effect=exc):
                result = self.c.post('/api/cloud/recovery/verify', json={'material': 'x'}, headers=W)
                self.assertEqual((result.status_code, result.json()['code'], result.json()['action']), (409, code, action), result.text)
        with mock.patch.object(service, 'verify_kit', side_effect=drive_client.DriveError('license_required')):
            result = self.c.post('/api/cloud/recovery/verify', json={'material': 'x'}, headers=W)
            self.assertEqual((result.status_code, result.json()), (403, {'detail': 'license_required'}))
        with mock.patch.object(service, 'verify_kit', side_effect=PermissionError(13, 'denied', r'C:\Users\someone\token.json')):
            result = self.c.post('/api/cloud/recovery/verify', json={'material': 'x'}, headers=W)
            self.assertEqual((result.status_code, result.json()['code']), (409, 'local_storage'))
            self.assertNotIn('someone', result.text)
        for exc in (OSError('disk'), drive_client.DriveError('x', 500)):          # unpair was a 500 for every failure
            with mock.patch.object(sync, 'unpair', side_effect=exc):
                result = self.c.post('/api/cloud/unpair', json={}, headers=W)
                self.assertEqual(result.status_code, 409, result.text)
                self.assertIn('code', result.json())

    def test_a_saved_removal_is_accepted_even_if_starting_its_worker_fails(self):
        sync = self.app.state.sync
        with mock.patch.object(sync, 'ensure_running', side_effect=OSError('synthetic worker failure')):
            result = self.c.post('/api/cloud/unpair', json={}, headers={'X-CM': '1'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['task']['kind'], 'remove_phones')
        self.assertEqual(result.json()['fingerprint'], sync.intents.find('remove_phones')['payload']['new'])
        self.assertEqual(sync._rotation()['stage'], 'prepared')
        self.assertIn('Restart Brainamon', result.json()['error'])
        with mock.patch.object(sync, 'start') as start, mock.patch.object(sync, '_start_control'):
            sync.boot()
        start.assert_called_once_with(oneshot=True)

    def test_s1_reauth_is_a_guarded_post_that_answers_with_the_cloud_view_or_a_classified_refusal(self):
        W = {'X-CM': '1'}
        sync = self.app.state.sync
        self.assertEqual(self.c.post('/api/cloud/reauth', json={}).status_code, 403)             # no X-CM: the guard refuses
        with mock.patch.object(sync, 'sign_in_again') as again:
            result = self.c.post('/api/cloud/reauth', json={}, headers=W)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIn('token_expired', result.json())
            again.assert_called_once_with()
        for exc, code in ((SR.Busy(), 'busy'), (drive_client.DriveError('No Google sign-in app is configured for this build.'), 'other')):
            with mock.patch.object(sync, 'sign_in_again', side_effect=exc):
                result = self.c.post('/api/cloud/reauth', json={}, headers=W)
                self.assertEqual((result.status_code, result.json()['code']), (409, code), result.text)


class ReconnectTest(Library):
    """Keep this folder after its app home lost the Drive key (plan 2026-10-29-reconnect-existing-library)."""

    def setUp(self):
        super().setUp()
        from tests.license_fixture import activate
        activate(self, self.root)
        self.db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.drive = FakeDrive()
        self.homes = []
        self.old = self.home('cloud')
        self.kit = self.old.recovery.enroll(PASSWORD, PASSWORD)
        self.old.recovery.verify_kit(R.dump(self.kit).decode())
        self.assertTrue(self.old._publish(), self.old.status())
        self.key = self.old.mirror_key()
        self.library = self.kit['record']['header']['library']
        self.svc = self.home('cloud-new')       # the recreated app home: same folder and DB, no key or recovery state
        self.service = self.svc.recovery

    def tearDown(self):
        for svc in self.homes:
            svc.recovery.shutdown()
            svc.shutdown()
        self.writer.stop()
        self.db = Database(self.data / 'content_manager.db')     # Library.tearDown closes it
        super().tearDown()

    def home(self, name):
        svc = SyncService(self.writer, Hub(), self.data, self.root / name, client_factory=lambda token: self.drive)
        drive_client.save_token(svc.token_path, {'refresh_token': 'synthetic-' + name})
        self.homes.append(svc)
        return svc

    def cloud_files(self):
        return {p: p.read_bytes() for p in self.svc.cloud_dir.rglob('*') if p.is_file()}

    def owners(self):
        return [f for f in self.drive.list() if f['name'].startswith(R.PREFIX + 'owner-')]

    def test_d3_keep_this_folder_reuses_the_passphrase_typed_to_find_the_backup(self):
        view = self.service.preview(password=PASSWORD)
        self.assertTrue(view['preview']['reconnect']['ok'])
        self.assertNotIn(PASSWORD, json.dumps(self.service.status()))
        kit = self.service.reconnect('', '')                                    # nothing typed again
        self.assertEqual(R.unlock(kit['record'], password=PASSWORD).master, self.key.master)

    def test_d3_a_backup_found_with_a_kit_has_no_passphrase_to_reuse(self):
        self.service.preview(material=R.dump(self.kit).decode())
        with self.assertRaises(R.RecoveryError):
            self.service.reconnect('', '')
        self.assertIsNotNone(self.service.session)                              # still a valid preview: type one and go on

    def eligibility(self, **material):
        return self.service.preview(**(material or {'material': R.dump(self.kit).decode()}))['preview']['reconnect']

    def test_preview_offers_reconnect_without_writing_anything(self):
        before, local = dict(self.drive.files), self.cloud_files()
        with mock.patch('core.private_storage.write', side_effect=AssertionError('preview wrote protected storage')), \
             mock.patch.object(drive_client, 'save_token', side_effect=AssertionError('preview saved a token')), \
             mock.patch.object(self.drive, 'upload', side_effect=AssertionError('preview wrote Drive')), \
             mock.patch.object(self.drive, 'delete', side_effect=AssertionError('preview deleted from Drive')):
            for material in ({'material': R.dump(self.kit).decode()}, {'material': self.key.text()},
                             {'file_id': self.service.discover()[0]['id'], 'password': PASSWORD}):
                with self.subTest(material=sorted(material)):
                    view = self.service.preview(**material)
                    self.assertEqual(view['preview']['reconnect'], {'ok': True, 'reason': 'eligible', 'message': SR.ELIGIBLE})
                    self.assertGreater(view['preview']['items'], 0)
                    self.service.status()
        self.assertEqual(self.drive.files, before)
        self.assertEqual(self.cloud_files(), local)
        status = json.dumps(self.service.status())
        for secret in (PASSWORD, self.kit['secret'], self.key.text()):
            self.assertNotIn(secret, status)

    def test_preview_explains_why_this_folder_cannot_be_kept(self):
        row = self.writer.read(lambda db: db.get_sync_state()[mirror.MANIFEST])
        fp = self.key.fingerprint
        cases = (
            ('not_latest', lambda db: db.save_sync_state({mirror.MANIFEST: {**row, 'sig': 'stale'}}),
             lambda db: db.save_sync_state({mirror.MANIFEST: row})),
            ('not_latest', lambda db: db.save_sync_state({}, [mirror.MANIFEST]),
             lambda db: db.save_sync_state({mirror.MANIFEST: row})),
            ('no_upload', lambda db: db.set_setting('cloud_epoch', ''), lambda db: db.set_setting('cloud_epoch', fp)),
            ('other_library', lambda db: db.set_setting('cloud_epoch', 'a' * 12), lambda db: db.set_setting('cloud_epoch', fp)),
            ('adoption_pending', lambda db: db.set_setting('cloud_epoch_next', 'b' * 12), lambda db: db.set_setting('cloud_epoch_next', '')),
            ('sync_on', lambda db: db.set_setting('cloud_upload', 'on'), lambda db: db.set_setting('cloud_upload', '')),
            ('sync_on', lambda db: db.set_setting('cloud_vault', 'on'), lambda db: db.set_setting('cloud_vault', 'off')),
        )
        for reason, apply, undo in cases:
            with self.subTest(reason=reason):
                self.writer.call(apply)
                try:
                    view = self.service.preview(material=R.dump(self.kit).decode())
                    self.assertEqual(view['preview']['reconnect']['reason'], reason)
                    self.assertFalse(view['preview']['reconnect']['ok'])
                    self.assertEqual(view['preview']['reconnect']['message'], SR.REFUSALS[reason])
                    self.assertGreater(view['preview']['items'], 0)     # restore into a new folder stays available
                finally:
                    self.writer.call(undo)
        self.assertTrue(self.eligibility()['ok'])

    def test_pending_local_recovery_work_refuses_reconnect(self):
        record, secret = R.create(self.key, PASSWORD, 'fred@example.com', library=self.library)
        restored = {'record': record, 'secret': R.encode(secret), 'device': 'c' * 32, 'account': 'fred@example.com',
                    'verified': False, 'verified_at': 0, 'restored': True, 'target': str(self.data)}
        cases = (
            ('rotation_pending', self.svc.cloud_dir / 'rotation.json', json.dumps({'stage': 'prepared'}).encode()),
            ('activation_pending', self.service.journal, R.dump({'stage': 'prepared'})),
            ('restored', self.svc.cloud_dir / 'recovery-legacy.json', R.dump({'restored': True, 'target': str(self.data)})),
            ('restored', self.service.path, R.dump(restored)),
        )
        for reason, path, raw in cases:
            with self.subTest(reason=reason, path=path.name):
                private_storage.write(path, raw)
                try:
                    reconnect = self.eligibility()
                    self.assertEqual(reconnect['reason'], reason)
                    self.assertFalse(reconnect['ok'])
                finally:
                    private_storage.remove(path)
        self.assertTrue(self.eligibility()['ok'])
        # Damaged protected state: status() already refuses it (route 409), so check the eligibility step itself.
        snap = restore.preview(self.service._client(readonly=True), self.key)
        private_storage.write(self.service.path, b'not a recovery state')
        try:
            with self.assertRaises(SR.ReconnectRefused) as refused:
                self.service._reconnect_check(self.key, snap)
            self.assertEqual(refused.exception.reason, 'local_damaged')
            self.assertEqual(private_storage.read(self.service.path, readonly=True), b'not a recovery state')
        finally:
            private_storage.remove(self.service.path)

    def test_unclear_uploader_identity_refuses_reconnect_but_keeps_restore(self):
        stray = 'e' * 32
        second = {'library': 'd' * 32, 'fingerprint': self.key.fingerprint, 'device': 'c' * 32,
                  'generation': 'b' * 32, 'changed': 1}
        cases = (
            ('owner_unknown', SR.RecoveryService.owner_name(stray),
             mirror.MirrorKey.generate().seal(SR.OWNER_LOGICAL, R.dump({'library': stray}))),
            ('owner_ambiguous', SR.RecoveryService.owner_name(second['library']), self.key.seal(SR.OWNER_LOGICAL, R.dump(second))),
            ('records_damaged', R.PREFIX + 'owner-not-a-library.json', b'{}'),
            ('records_damaged', R.name(self.kit['record']), R.dump(self.kit['record'])),       # a duplicate setup name
            ('records_damaged', R.PREFIX + 'f' * 32 + '-' + 'f' * 32 + '.json', b'not json'),
        )
        for reason, name, raw in cases:
            with self.subTest(reason=reason, name=name):
                fid = self.drive.put(name, raw)
                try:
                    view = self.service.preview(material=R.dump(self.kit).decode())
                    self.assertEqual(view['preview']['reconnect']['reason'], reason)
                    self.assertGreater(view['preview']['items'], 0)
                finally:
                    del self.drive.files[fid]
        mismatch, secret = R.create(self.key, PASSWORD, 'fred@example.com')        # a kit naming another uploader record
        material = R.dump(R.kit(mismatch, R.encode(secret))).decode()
        self.assertEqual(self.service.preview(material=material)['preview']['reconnect']['reason'], 'owner_mismatch')

    def test_every_recovery_method_resolves_the_existing_uploader_record(self):
        client = self.service._client(readonly=True)
        for record in (self.kit['record'], None):           # kit or passphrase; raw, pairing and phone codes
            with self.subTest(record=bool(record)):
                identity = self.service._reconnect_identity(client, self.key, 'fred@example.com', record, self.drive.list())
                self.assertEqual(identity['library'], self.library)
                self.assertEqual(identity['owner_id'], self.owners()[0]['id'])
                self.assertEqual(identity['owner']['library'], self.library)

    def test_without_an_uploader_record_the_namespace_comes_from_matching_setups(self):
        client, account = self.service._client(readonly=True), 'fred@example.com'
        for f in self.owners():
            del self.drive.files[f['id']]
        identity = self.service._reconnect_identity(client, self.key, account, None, self.drive.list())
        self.assertEqual((identity['library'], identity['owner_id'], identity['owner']), (self.library, '', None))
        self.assertEqual(self.service._reconnect_identity(client, self.key, account, self.kit['record'], self.drive.list())['library'],
                         self.library)
        other, _ = R.create(self.key, PASSWORD, account)
        self.drive.put(R.name(other), R.dump(other))
        for record in (None, self.kit['record']):
            with self.subTest(record=bool(record)):
                with self.assertRaises(SR.ReconnectRefused) as refused:
                    self.service._reconnect_identity(client, self.key, account, record, self.drive.list())
                self.assertEqual(refused.exception.reason, 'owner_ambiguous')
        for f in [f for f in self.drive.list() if f['name'].startswith(R.PREFIX)]:
            del self.drive.files[f['id']]
        self.assertIsNone(self.service._reconnect_identity(client, self.key, account, None, self.drive.list())['library'])
        unrelated, _ = R.create(mirror.MirrorKey.generate(), PASSWORD, account)     # another library's setup is ignored
        self.drive.put(R.name(unrelated), R.dump(unrelated))
        self.assertIsNone(self.service._reconnect_identity(client, self.key, account, None, self.drive.list())['library'])

    def test_a_started_restore_hides_the_reconnect_offer(self):
        self.assertTrue(self.eligibility()['ok'])
        self.service.session['stage'] = self.root / 'stage'
        self.assertEqual(self.service.status()['preview']['reconnect']['reason'], 'restore_started')

    def restart(self):
        """The same app home after a crash or restart: a new service, no preview in memory."""
        svc = SyncService(self.writer, Hub(), self.data, self.svc.cloud_dir, client_factory=lambda token: self.drive)
        self.homes.append(svc)
        self.svc, self.service = svc, svc.recovery

    def local_key(self):
        key = mirror.MirrorKey.load(self.svc.key_path, readonly=True)
        return key.master if key else None

    def local_snapshot(self):
        """Logical DB contents and library file bytes (WAL bookkeeping is not a meaningful byte comparison)."""
        def read(db):
            return ([tuple(r) for r in db.conn.execute('SELECT * FROM items ORDER BY id')],
                    dict(db.conn.execute('SELECT key, value FROM settings').fetchall()), db.get_sync_state())
        files = {str(p.relative_to(self.data)): p.read_bytes() for p in self.data.rglob('*')
                 if p.is_file() and not p.name.startswith('content_manager.db')}
        return self.writer.read(read), files

    def wait(self, cond, t=15):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def change(self, url):
        name, blob = self.key.seal_change({'format': 1, 'device': 'phone', 'at': 100, 'changes': [
            {'op': 'link', 'uid': 'a' * 32, 'url': url, 'at': 90}]})
        return self.drive.put(name, blob)

    def test_each_recovery_method_keeps_this_folder_and_pauses_the_old_pc(self):
        url = 'https://example.com/mobile.html#pair=' + R.encode(R.dump({'v': 2, 'k': self.key.text()}))
        phone = R.dump({'format': R.PHONE_FORMAT, 'version': 1, 'key': self.key.text(),
                        'fingerprint': self.key.fingerprint}).decode()
        methods = (('kit', {'material': R.dump(self.kit).decode()}), ('passphrase', None),
                   ('raw', {'material': self.key.text()}), ('pairing', {'material': url}), ('phone', {'material': phone}))
        previous = self.old
        for n, (name, material) in enumerate(methods):
            with self.subTest(method=name):
                if n:
                    self.svc = self.home('cloud-' + name)
                    self.service = self.svc.recovery
                if material is None:
                    material = {'file_id': self.service.discover()[0]['id'], 'password': PASSWORD}
                before = self.local_snapshot()
                self.assertTrue(self.eligibility(**material)['ok'])
                kit = self.service.reconnect(PASSWORD, PASSWORD)
                self.assertEqual(self.local_snapshot(), before)
                self.assertEqual(self.local_key(), self.key.master)
                state = self.service._load()
                self.assertEqual((state['enrolled'], state['verified'], state['verified_at']), (True, False, 0))
                self.assertNotIn('restored', state)
                self.assertEqual(state['record'], kit['record'])
                self.assertEqual(kit['record']['header']['library'], self.library)
                self.assertEqual([f['name'] for f in self.owners()], [SR.RecoveryService.owner_name(self.library)])
                _, owner = self.service._owner(self.drive, self.key, self.library)
                self.assertEqual(owner['device'], state['device'])
                status = self.service.status()
                self.assertIsNone(status['preview'])
                self.assertTrue(status['enrolled'])
                self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_upload', ''), db.get_setting('cloud_vault', '') == 'on')), ('', False))
                remote = dict(self.drive.files)
                self.assertFalse(previous._publish())
                self.assertIn('Another PC', previous.status()['error'])
                self.assertEqual(self.drive.files, remote)
                self.assertTrue(self.svc._publish(), self.svc.status())
                manifests = [f for f in self.drive.list() if f['name'] == self.key.name(mirror.MANIFEST)]
                self.assertEqual(len(manifests), 1)
                previous = self.svc

    def test_local_additions_edits_and_deletions_survive_and_upload_incrementally(self):
        self.writer.call(lambda db: db.add_item({'url': 'https://example.com/kept-local', 'description': 'local addition'}))
        self.writer.call(lambda db: db.update_item(self.ids[2], {'description': 'edited locally'}))
        self.writer.call(lambda db: db.delete_item(self.ids[3]))
        (self.data / 'notes' / 'local.md').write_text('---\ntopic: Local\n---\nkept here', encoding='utf-8')
        before = self.local_snapshot()
        published = before[0][2]
        self.assertTrue(self.eligibility()['ok'])
        self.service.reconnect(PASSWORD, PASSWORD)
        self.assertEqual(self.local_snapshot(), before)
        mark = len(self.drive.calls)
        self.assertTrue(self.svc._publish(), self.svc.status())
        after = self.writer.read(lambda db: db.get_sync_state())
        same = [k for k, v in published.items() if k != mirror.MANIFEST and after.get(k, {}).get('sig') == v['sig']]
        self.assertTrue(same)
        for logical in same:
            self.assertEqual(after[logical]['drive_id'], published[logical]['drive_id'])
        sent = {c.split(' ', 1)[1] for c in self.drive.calls[mark:] if c.startswith('upload ')}
        self.assertFalse(sent & {self.key.name(k) for k in same})
        self.assertEqual(sum(n == self.key.name(mirror.MANIFEST) for n, _ in self.drive.files.values()), 1)
        _, files = read_mirror(self.drive, self.key)
        items = {json.loads(v)['url']: json.loads(v) for k, v in files.items() if k.startswith('items/')}
        self.assertIn('https://example.com/kept-local', items)
        self.assertEqual(items['https://www.instagram.com/reel/r2/']['description'], 'edited locally')
        self.assertNotIn('https://www.instagram.com/reel/r3/', items)
        self.assertIn('notes/local.md', files)

    def test_a_mirror_without_recovery_gets_one_uploader_record(self):
        for f in [f for f in self.drive.list() if f['name'].startswith(R.PREFIX)]:
            del self.drive.files[f['id']]
        self.assertTrue(self.eligibility(material=self.key.text())['ok'])
        kit = self.service.reconnect(PASSWORD, PASSWORD)
        library = kit['record']['header']['library']
        self.assertNotEqual(library, self.library)
        self.assertEqual([f['name'] for f in self.owners()], [SR.RecoveryService.owner_name(library)])
        setups = [f for f in self.drive.list() if f['name'].startswith(R.PREFIX) and not f['name'].startswith(R.PREFIX + 'owner-')]
        self.assertEqual([f['name'] for f in setups], [R.name(kit['record'])])
        self.assertTrue(self.svc._publish(), self.svc.status())

    def test_an_unfinished_first_setup_lends_its_namespace(self):
        for f in self.owners():
            del self.drive.files[f['id']]
        self.assertTrue(self.eligibility(material=self.key.text())['ok'])
        kit = self.service.reconnect(PASSWORD, PASSWORD)
        self.assertEqual(kit['record']['header']['library'], self.library)
        self.assertEqual([f['name'] for f in self.owners()], [SR.RecoveryService.owner_name(self.library)])

    def test_reconnect_rechecks_everything_and_refuses_before_writing(self):
        row = self.writer.read(lambda db: db.get_sync_state()[mirror.MANIFEST])
        manifest = next(f for f in self.drive.list() if f['name'] == self.key.name(mirror.MANIFEST))
        sealed = self.drive.files[manifest['id']]
        changed = json.loads(self.key.open(mirror.MANIFEST, sealed[1]))
        changed['published'] += 1

        def setting(key, value, old):
            return (lambda: self.writer.call(lambda db: db.set_setting(key, value)),
                    lambda: self.writer.call(lambda db: db.set_setting(key, old)))

        def protected(path, raw):
            return (lambda: private_storage.write(path, raw)), (lambda: private_storage.remove(path))

        cases = {
            'stale row': (lambda: self.writer.call(lambda db: db.save_sync_state({mirror.MANIFEST: {**row, 'sig': 'stale'}})),
                          lambda: self.writer.call(lambda db: db.save_sync_state({mirror.MANIFEST: row}))),
            'other library': setting('cloud_epoch', 'a' * 12, self.key.fingerprint),
            'adoption': setting('cloud_epoch_next', 'b' * 12, ''),
            'uploads on': setting('cloud_upload', 'on', ''),
            'vault on': setting('cloud_vault', 'on', 'off'),
            'rotation': protected(self.svc.cloud_dir / 'rotation.json', json.dumps({'stage': 'prepared'}).encode()),
            'activation': protected(self.service.journal, R.dump({'stage': 'prepared'})),
            'legacy restore': protected(self.svc.cloud_dir / 'recovery-legacy.json', R.dump({'restored': True})),
            'staged restore': (lambda: self.service.session.update(stage=self.root / 'stage'), lambda: None),
            'drive changed': (lambda: self.drive.files.__setitem__(manifest['id'], (sealed[0], self.key.seal(mirror.MANIFEST, R.dump(changed)))),
                              lambda: self.drive.files.__setitem__(manifest['id'], sealed)),
        }
        for name, (apply, undo) in cases.items():
            with self.subTest(case=name):
                self.assertTrue(self.eligibility()['ok'])
                apply()
                try:
                    remote, local = dict(self.drive.files), self.cloud_files()
                    with self.assertRaises(R.RecoveryError):
                        self.service.reconnect(PASSWORD, PASSWORD)
                    self.assertEqual(self.drive.files, remote)
                    self.assertEqual(self.cloud_files(), local)
                finally:
                    undo()
        self.assertTrue(self.eligibility()['ok'])
        with mock.patch.object(self.drive, 'about', return_value={'email': 'other@example.com', 'used': 1, 'limit': 2}):
            with self.assertRaisesRegex(R.RecoveryError, 'account changed'):
                self.service.reconnect(PASSWORD, PASSWORD)
        for password, confirmation in (('short', 'short'), (PASSWORD, PASSWORD + 'x')):
            with self.assertRaises(R.RecoveryError):
                self.service.reconnect(password, confirmation)
        self.service.session = None
        with self.assertRaisesRegex(R.RecoveryError, 'Find your library'):
            self.service.reconnect(PASSWORD, PASSWORD)
        self.assertIsNone(self.local_key())
        self.assertIsNone(self.service._load(readonly=True))

    def test_a_competing_handover_stops_reconnect_before_this_pc_changes(self):
        self.assertTrue(self.eligibility()['ok'])
        owner = self.owners()[0]
        upload = self.drive.upload

        def competing(name, *args, **kwargs):
            fid = upload(name, *args, **kwargs)
            if name.startswith(R.PREFIX) and not name.startswith(R.PREFIX + 'owner-'):
                body = {'library': self.library, 'fingerprint': self.key.fingerprint, 'device': 'f' * 32,
                        'generation': 'e' * 32, 'changed': 1}
                self.drive.files[owner['id']] = (owner['name'], self.key.seal(SR.OWNER_LOGICAL, R.dump(body)))
            return fid

        with mock.patch.object(self.drive, 'upload', side_effect=competing):
            with self.assertRaises(R.RecoveryError) as refused:
                self.service.reconnect(PASSWORD, PASSWORD)
        self.assertEqual(str(refused.exception), SR.HANDOVER)
        self.assertIsNone(self.local_key())
        self.assertIsNone(self.service._load(readonly=True))
        self.assertEqual(self.service._owner(self.drive, self.key, self.library)[1]['device'], 'f' * 32)
        setups = [f for f in self.drive.list() if f['name'].startswith(R.PREFIX) and not f['name'].startswith(R.PREFIX + 'owner-')]
        self.assertEqual(len(setups), 2)        # the extra setup stays; nothing is deleted

    def test_interrupted_reconnect_fails_closed_and_retries_after_a_fresh_preview(self):
        write = private_storage.write

        def backup_fails(path, raw):
            if Path(path).name.startswith('recovery-before-reconnect-'):
                raise OSError('synthetic backup failure')
            return write(path, raw)

        points = (('backup', 'none'), ('envelope', 'none'), ('envelope', 'other'), ('owner', 'none'), ('owner', 'other'),
                  ('owner_written', 'none'), ('owner_written', 'same'),
                  ('key', 'none'), ('key', 'same'), ('key', 'other'), ('state', 'none'), ('state', 'same'), ('state', 'other'))
        uploader = self.old
        for n, (point, previous) in enumerate(points):
            with self.subTest(point=point, previous=previous):
                self.svc = self.home(f'cloud-failure-{n}')
                self.service = self.svc.recovery
                if previous == 'same':          # a copy of the current uploader's home
                    self.key.save(self.svc.key_path)
                    self.service._save(uploader.recovery._load())
                elif previous == 'other':       # recovery state for another key
                    other = mirror.MirrorKey.generate()
                    record, secret = R.create(other, PASSWORD, 'fred@example.com')
                    other.save(self.svc.key_path)
                    self.service._save({'record': record, 'secret': R.encode(secret), 'device': 'c' * 32,
                                        'account': 'fred@example.com', 'verified': False, 'verified_at': 0, 'enrolled': True})
                kept = (self.local_key(), self.service._load(readonly=True))
                self.assertTrue(self.eligibility()['ok'])
                upload = self.drive.upload

                def setup_upload_fails(name, *args, **kwargs):
                    if name.startswith(R.PREFIX) and not name.startswith(R.PREFIX + 'owner-'):
                        raise drive_client.DriveError('synthetic offline')
                    return upload(name, *args, **kwargs)

                write_owner = self.service._write_owner

                def owner_written_reply_lost(*args, **kwargs):
                    write_owner(*args, **kwargs)        # the uploader record changes in Drive, the reply is lost
                    raise drive_client.DriveError('synthetic lost response')

                patch = {'backup': mock.patch('core.private_storage.write', side_effect=backup_fails),
                         'owner_written': mock.patch.object(self.service, '_write_owner', side_effect=owner_written_reply_lost),
                         'envelope': mock.patch.object(self.drive, 'upload', side_effect=setup_upload_fails),
                         'owner': mock.patch.object(self.service, '_write_owner', side_effect=drive_client.DriveError('synthetic lost response')),
                         'key': mock.patch.object(mirror.MirrorKey, 'save', side_effect=OSError('synthetic key failure')),
                         'state': mock.patch.object(self.service, '_save', side_effect=OSError('synthetic state failure'))}[point]
                remote = dict(self.drive.files)
                with patch, self.assertRaises((OSError, R.RecoveryError)) as failed:
                    self.service.reconnect(PASSWORD, PASSWORD)
                for secret in (PASSWORD, self.key.text(), self.kit['secret']):
                    self.assertNotIn(secret, str(failed.exception))
                if point == 'backup':
                    self.assertEqual(self.drive.files, remote)
                if point in ('backup', 'envelope', 'owner', 'owner_written'):
                    self.assertEqual((self.local_key(), self.service._load(readonly=True)), kept)
                if point in ('envelope', 'owner', 'owner_written'):
                    self.assertEqual(str(failed.exception), SR.INTERRUPTED)
                if point in ('key', 'state'):
                    self.assertEqual(str(failed.exception), SR.INTERRUPTED_LOCAL)
                if point == 'owner_written':
                    self.assertNotEqual(self.drive.files, remote)       # the uploader record did change in Drive
                # Keep this library has an activity record (F14): the reason stays readable after Settings closes
                activity = self.service.status()['activity']
                self.assertEqual((activity['action'], activity['state']), ('reconnect', 'error'))
                self.assertEqual(activity['step'], {'envelope': SR.INTERRUPTED, 'owner': SR.INTERRUPTED, 'owner_written': SR.INTERRUPTED,
                                                    'key': SR.INTERRUPTED_LOCAL, 'state': SR.INTERRUPTED_LOCAL}.get(point, activity['step']))
                if point != 'backup':
                    # Once Drive may have changed, this preview is no proof: no retry without a fresh one.
                    self.assertEqual(self.service.status()['preview']['reconnect']['reason'], 'interrupted')
                    with self.assertRaisesRegex(R.RecoveryError, 'Find your library'):
                        self.service.reconnect(PASSWORD, PASSWORD)
                self.restart()
                self.assertFalse(self.svc._publish(), 'publication must stay blocked after an interrupted reconnect')
                self.assertTrue(self.eligibility()['ok'])
                self.service.reconnect(PASSWORD, PASSWORD)
                self.assertIsNone(self.service.status()['activity'])
                self.assertTrue(self.svc._publish(), self.svc.status())
                self.assertFalse(uploader._publish())
                uploader = self.svc

    def test_a_lost_response_shows_after_restart_and_nothing_starts(self):
        self.assertTrue(self.eligibility()['ok'])
        kit = self.service.reconnect(PASSWORD, PASSWORD)
        self.restart()
        status = self.service.status()
        self.assertTrue(status['enrolled'])
        self.assertIsNone(status['preview'])
        self.assertEqual(self.service.export_kit(), kit)
        with mock.patch.object(self.svc, 'start', side_effect=AssertionError('boot started uploads')), \
             mock.patch.object(self.svc, 'start_vault', side_effect=AssertionError('boot started vault sync')):
            self.svc.boot()
        self.assertFalse(self.svc.running or self.svc.vault_running)
        self.assertTrue(self.eligibility()['ok'])          # retrying after a lost response is safe
        self.service.reconnect(PASSWORD, PASSWORD)
        self.assertTrue(self.svc._publish(), self.svc.status())

    def test_conflicting_local_changes_refuse_while_reconnecting(self):
        self.assertTrue(self.eligibility()['ok'])
        results, create = {}, R.create

        def during(*args, **kwargs):
            def probe():
                for name, call in (('turn_on', self.svc.turn_on), ('vault', self.svc.turn_vault_on),
                                   ('connect', lambda: self.svc.connect('mirror')), ('switch', self.svc.switch),
                                   ('sign_out', self.svc.sign_out), ('unpair', lambda: self.svc.unpair(PASSWORD)),
                                   ('pair', self.svc.mirror_key), ('pair_public', self.svc.license_public_key)):
                    try:
                        call()
                        results[name] = 'ran'
                    except drive_client.DriveError as e:
                        results[name] = str(e)
                self.svc._start_control()
                results['control'] = bool(self.svc._control_thread and self.svc._control_thread.is_alive())
            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(10)
            return create(*args, **kwargs)

        with mock.patch.object(R, 'create', side_effect=during):
            self.service.reconnect(PASSWORD, PASSWORD)
        expected = ('turn_on', 'vault', 'connect', 'switch', 'sign_out', 'unpair', 'pair', 'pair_public')
        # reconnect has an activity record now (F14): the refusal names the step that is running instead of the generic text
        for name in expected:
            self.assertTrue(results.get(name, '').endswith('Wait for this step to finish, then retry.'), (name, results.get(name)))
            self.assertNotEqual(results[name], SR.BUSY)
        self.assertEqual(len({results[name] for name in expected}), 1)
        self.assertFalse(results['control'])
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_upload', ''), db.get_setting('cloud_vault', '') == 'on')), ('', False))
        self.assertIsNotNone(drive_client.load_token(self.svc.token_path))
        self.assertFalse(self.svc.running or self.svc.vault_running)
        with self.service.gate():   # free again afterwards
            pass

    def test_a_sign_in_that_finishes_during_reconnect_saves_nothing(self):
        private_storage.remove(self.svc.token_path)
        entered, answer = threading.Event(), threading.Event()

        def sign_in(cid, secret, cancel=None):
            entered.set()
            answer.wait(5)
            return {'refresh_token': 'another-account'}

        held, release = threading.Event(), threading.Event()

        def hold():
            with self.service.mutation:
                held.set()
                release.wait(5)

        self.svc._sign_in = sign_in
        with mock.patch.object(sync_mod.config, 'google_client', return_value=('synthetic-client', 'synthetic-secret')):
            self.svc.connect('mirror')
            self.assertTrue(entered.wait(5))
            holder = threading.Thread(target=hold)
            holder.start()
            self.assertTrue(held.wait(5))
            answer.set()
            self.svc._signin_thread.join(5)
            release.set()
            holder.join(5)
        self.assertIsNone(drive_client.load_token(self.svc.token_path))
        self.assertEqual(self.svc.status()['error'], SR.BUSY)
        self.assertFalse(self.svc.running)

    def test_reconnect_waits_for_google_sign_in_to_end(self):
        self.assertTrue(self.eligibility()['ok'])
        stop = threading.Event()
        self.svc._signin_thread = threading.Thread(target=stop.wait, args=(5,))
        self.svc._signin_thread.start()
        try:
            with self.assertRaisesRegex(R.RecoveryError, 'sign-in is still in progress'):
                self.service.reconnect(PASSWORD, PASSWORD)
        finally:
            stop.set()
            self.svc._signin_thread.join(5)
        self.service.reconnect(PASSWORD, PASSWORD)

    def test_changing_account_makes_the_reconnect_answer_stale(self):
        self.assertTrue(self.eligibility()['ok'])
        with mock.patch.object(drive_client, 'revoke'):
            self.svc.sign_out()
        self.assertEqual(self.service.status()['preview']['reconnect']['reason'], 'account_changed')
        with self.assertRaisesRegex(R.RecoveryError, 'Find your library'):
            self.service.reconnect(PASSWORD, PASSWORD)

    def test_receipt_free_reconnect_waits_for_explicit_publish_then_applies_phone_changes(self):
        from core import license
        fid = self.change('https://example.com/from-phone')
        license.remove()
        self.assertTrue(self.eligibility()['ok'])
        self.service.reconnect(PASSWORD, PASSWORD)
        self.assertFalse(self.writer.read(lambda db: db.item_exists('https://example.com/from-phone')))
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertNotIn(fid, set(self.drive.files))
        self.assertTrue(self.writer.read(lambda db: db.item_exists('https://example.com/from-phone')))

    def test_licensed_intake_applies_waiting_phone_changes_once_uploads_are_turned_on(self):
        self.change('https://example.com/from-phone')
        self.assertTrue(self.eligibility()['ok'])
        self.service.reconnect(PASSWORD, PASSWORD)
        self.assertFalse(self.writer.read(lambda db: db.item_exists('https://example.com/from-phone')))
        self.svc.turn_on()
        try:
            self.assertTrue(self.wait(lambda: self.writer.read(lambda db: db.item_exists('https://example.com/from-phone'))),
                            self.svc.status())
        finally:
            self.svc.turn_off()
            self.assertTrue(self.wait(lambda: not self.svc.running))

    def test_reconnect_deletes_nothing_and_keeps_the_data_pointer(self):
        self.old.license_public_key()
        self.old.publish_license_control()
        self.change('https://example.com/queued')
        self.drive.put('solo-' + 'a' * 32 + '-' + 'b' * 32, b'standalone phone backup')
        marker = self.svc.cloud_dir / 'unrelated.txt'
        marker.write_bytes(b'keep')
        before = dict(self.drive.files)
        self.assertTrue(self.eligibility()['ok'])
        with mock.patch('core.app_paths.set_data_dir', side_effect=AssertionError('reconnect moved the data pointer')), \
             mock.patch.object(self.drive, 'delete', side_effect=AssertionError('reconnect deleted from Drive')):
            self.service.reconnect(PASSWORD, PASSWORD)
        owner_id = self.owners()[0]['id']
        self.assertLessEqual(set(before), set(self.drive.files))
        self.assertEqual({k: v for k, v in before.items() if k != owner_id},
                         {k: self.drive.files[k] for k in before if k != owner_id})
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_missing_and_wrong_keys_point_to_reconnect(self):
        # A18: a key that is not this library's reads as the other copy's, before the recovery guard can say "restore it";
        # a key that is missing (a reinstall) still points at Unlock backup / Recover a library
        for word in ('Restore', 'Recover', 'Reconnect'):
            self.assertNotIn(word, sync_mod.KEY_CONFLICT)
        for case in ('missing key', 'wrong key'):
            with self.subTest(case=case):
                if case == 'wrong key':
                    self.svc.mirror_key()           # the recreated home made its own key
                self.assertFalse(self.svc._publish())
                if case == 'wrong key':
                    self.assertEqual(self.svc.status()['error'], sync_mod.KEY_CONFLICT)
                else:
                    self.assertIn(SR.RESTORE_HINT, self.svc.status()['error'])
                readiness = self.service.preflight()
                self.assertEqual(readiness['state'], 'restore_required')
                self.assertIn(SR.RESTORE_HINT, readiness['message'])
        for message in (SR.INTERRUPTED, SR.INTERRUPTED_LOCAL, SR.HANDOVER):
            self.assertIn('find your library again', message.lower())
            for claim in ('unchanged', 'rolled back', 'nothing changed', 'was preserved'):
                self.assertNotIn(claim, message.lower())
        self.assertIn('Uploads stay off', SR.INTERRUPTED)
        self.assertIn('Uploads stay off', SR.INTERRUPTED_LOCAL)
