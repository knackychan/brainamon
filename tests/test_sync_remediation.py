"""Recovery navigation regressions: real ownership guard, synthetic Drive, disposable library."""
import threading
import time
from unittest import mock

from core.db import Database
from library import drive_client, mirror
from library.export_targets import DriveMirrorTarget
from server import intents, sync
from server.store import Writer
from tests.test_sync import FakeDrive, Hub, Library


class RecoveryNavigationTest(Library):
    def setUp(self):
        super().setUp()
        self.payload_before = self.payload()
        self.db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.drive = FakeDrive()
        self.svc = sync.SyncService(self.writer, Hub(), self.data, self.root / 'cloud', client_factory=lambda tok: self.drive)
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        for patch in (mock.patch.object(self.svc, '_start_control'), mock.patch.object(drive_client, 'revoke'), mock.patch.object(sync, 'POLL', .02)):
            patch.start()
            self.addCleanup(patch.stop)
        self.releases = []

    def tearDown(self):
        for event in self.releases:
            event.set()
        self.svc.recovery.shutdown()
        self.svc.shutdown()
        self.writer.stop()
        self.db = Database(self.data / 'content_manager.db')
        super().tearDown()

    def wait(self, predicate):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(.02)
        self.fail(str(self.svc.status()))

    def foreign_backup(self):
        key = mirror.MirrorKey.generate()
        DriveMirrorTarget(self.drive, key, {}, self.data, mirror.Options()).export(self.payload_before)
        return set(self.drive.files)

    def test_replace_without_old_key_keeps_old_copy_until_complete(self):
        old = self.foreign_backup()
        solo = self.drive.put('solo-' + 'a' * 32 + '-' + 'b' * 32, b'standalone phone')
        self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc.status()['error_code'], 'foreign_backup')
        with mock.patch.object(self.svc, 'start'):
            self.svc.reset_backup(replace_existing=True)
        self.svc._run_intents(threading.Event())
        self.assertTrue(old.issubset(self.drive.files))
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        self.assertFalse(old & self.drive.files.keys())
        self.assertIn(solo, self.drive.files)
        self.assertIsNone(self.svc.intents.find(intents.RESET))
        self.assertEqual(self.writer.read(lambda db: db.count_items()), len(self.ids))
        tasks = [event['task'] for kind, event in self.svc.hub.events if kind == 'cloud' and event.get('task')]
        uploads = [task for task in tasks if task['stage'] == 'backing-up' and task['bytes_done']]
        self.assertTrue(uploads)
        self.assertTrue(all(task['step'] == 2 and task['total'] >= task['done'] > 0 for task in uploads))
        cleanup = [task for task in tasks if task['stage'] == 'cleanup' and task['total']]
        self.assertEqual([task['done'] for task in cleanup], list(range(len(old) + 1)))
        self.assertTrue(all(task['step'] == 3 and task['total'] == len(old) and task['bytes_total'] == 0 for task in cleanup))
        final = [event for kind, event in self.svc.hub.events if kind == 'cloud'][-1]
        self.assertIsNone(final['task'])
        self.assertEqual((final['done'], final['total'], final['upload_step']), (0, 0, ''))

    def test_reset_cleanup_retry_counts_only_remaining_files(self):
        old = [self.drive.put(str(n), b'old backup') for n in range(3)]
        self.svc.intents.add(intents.RESET, {'ids': old})
        self.svc.intents.update(intents.RESET, stage='cleanup')
        self.drive.delete(old[0])
        delete = self.drive.delete

        def fail_second(fid):
            if fid == old[2]:
                raise drive_client.DriveError('synthetic offline')
            delete(fid)

        with mock.patch.object(self.drive, 'delete', side_effect=fail_second):
            with self.assertRaises(drive_client.DriveError):
                self.svc._finish_reset(threading.Event())
        task = self.svc.status()['task']
        self.assertEqual((task['done'], task['total']), (1, 2))
        self.assertEqual(task['bytes_total'], 0)
        self.svc.hub.events.clear()
        self.svc._finish_reset(threading.Event())
        tasks = [event['task'] for kind, event in self.svc.hub.events if kind == 'cloud' and event.get('task') and event['task']['total']]
        self.assertEqual([(task['done'], task['total']) for task in tasks], [(0, 1), (1, 1)])
        self.assertFalse(self.drive.files)
        self.assertIsNone(self.svc.status()['task'])

    def test_reset_with_recovery_uses_real_guard_and_removes_old_records(self):
        self.assertTrue(self.svc._publish())
        old_key = self.svc._key()
        self.svc.recovery.enroll('synthetic passphrase only', 'synthetic passphrase only')
        old = set(self.drive.files)
        with mock.patch.object(self.svc, 'start'):
            self.svc.reset_backup()
        self.svc._run_intents(threading.Event())
        task = self.svc.intents.find(intents.RESET)
        archived = mirror.MirrorKey.load(self.svc.cloud_dir / f'mirror-before-reset-{task["id"]}.key')
        self.assertEqual(archived.master, old_key.master)
        self.assertTrue(old.issubset(self.drive.files))
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        self.assertFalse(old & self.drive.files.keys())

    def test_reset_cleanup_retry_reports_republishing_before_deletion(self):
        self.foreign_backup()
        with mock.patch.object(self.svc, 'start'):
            self.svc.reset_backup(True)
        self.svc._run_intents(threading.Event())
        with mock.patch.object(self.drive, 'delete', side_effect=drive_client.DriveError('synthetic offline')):
            self.assertTrue(self.svc._publish(threading.Event()))
        self.assertEqual(self.svc.status()['task']['stage'], 'cleanup')
        self.assertTrue(self.svc.status()['task']['error'])
        self.svc.hub.events.clear()
        self.assertTrue(self.svc._publish(threading.Event()))
        uploads = [event['task'] for kind, event in self.svc.hub.events
                   if kind == 'cloud' and event.get('task') and event.get('upload_step') == 'Uploading the encrypted library…']
        self.assertTrue(uploads)
        self.assertTrue(all(task['stage'] == 'backing-up' and not task['error'] for task in uploads))
        self.assertIsNone(self.svc.status()['task'])

    def test_delete_preempts_blocked_reset_and_drains_inflight_upload(self):
        old = self.foreign_backup()
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        self.svc.intents.add(intents.RESET, {'ids': []})
        self.svc.intents.update(intents.RESET, stage='backing-up')

        def blocked(stop):
            entered.set()
            release.wait(5)
            return False

        with mock.patch.object(self.svc, '_publish', blocked):
            self.svc.start()
            self.assertTrue(entered.wait(2))
            before = time.monotonic()
            self.svc.request_disconnect(True, delete_existing=True)
            self.assertLess(time.monotonic() - before, 1)
            self.assertEqual(self.svc.status()['task']['kind'], intents.DISCONNECT)
            self.assertTrue(old.issubset(self.drive.files))
            release.set()
            self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertEqual(self.drive.files, {})
        self.assertEqual(self.svc.intents.all(), [])
        self.assertEqual(self.svc.status()['state'], 'off')

    def test_pause_of_saved_task_survives_restart_even_when_upload_was_off(self):
        self.svc.intents.add(intents.RESET, {'ids': []})
        self.svc.intents.update(intents.RESET, stage='backing-up')
        self.svc.turn_off()
        self.assertGreater(self.svc.status()['paused_since'], 0)
        restarted = sync.SyncService(self.writer, Hub(), self.data, self.svc.cloud_dir, client_factory=lambda tok: self.drive)
        with mock.patch.object(restarted, '_start_control'), mock.patch.object(restarted, 'start') as start:
            restarted.boot()
            start.assert_not_called()
        self.assertIsNotNone(restarted.status()['task'])

    def test_manual_cloud_deletion_does_not_block_disconnect(self):
        self.foreign_backup()
        self.assertFalse(self.svc._publish())
        self.drive.files.clear()
        self.svc.request_disconnect(True, delete_existing=True)
        self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertEqual(self.svc.status()['error_code'], '')
        self.assertIsNone(self.svc.status()['task'])

    def test_rechecking_after_manual_cloud_deletion_clears_stale_conflict(self):
        self.foreign_backup()
        self.assertFalse(self.svc._publish())
        self.drive.files.clear()
        self.svc.publish_once()
        self.wait(lambda: not self.svc.running and self.svc.status()['last_publish'] > 0)
        self.assertEqual(self.svc.status()['error_code'], '')
        self.assertTrue(self.drive.files)

    def test_disconnect_interrupts_reset_cleanup_between_deletes(self):
        self.assertTrue(self.svc._publish())
        old = set(self.drive.files)
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = self.drive.delete
        def delete(fid):
            entered.set()
            release.wait(5)
            original(fid)
        with mock.patch.object(self.drive, 'delete', side_effect=delete):
            self.svc.reset_backup(True)
            self.assertTrue(entered.wait(2))
            self.svc.request_disconnect(False)
            release.set()
            self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertEqual(len(old & self.drive.files.keys()), len(old) - 1)
        self.assertEqual(self.svc.intents.all(), [])

    def test_failed_deletion_keeps_credentials_and_retry_finishes(self):
        self.foreign_backup()
        with mock.patch.object(self.drive, 'delete', side_effect=drive_client.DriveError('offline')):
            self.svc.request_disconnect(True, delete_existing=True)
            self.wait(lambda: bool((self.svc.intents.find(intents.DISCONNECT) or {}).get('error')))
            self.assertTrue(self.svc.signed_in())
        self.svc.publish_once()
        self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertFalse(self.drive.files)

    def test_new_foreign_files_after_replace_confirmation_are_not_ignored(self):
        self.foreign_backup()
        with mock.patch.object(self.svc, 'start'):
            self.svc.reset_backup(True)
        self.svc._run_intents(threading.Event())
        new_foreign = self.drive.put('c' * 32, b'new foreign data')
        self.assertFalse(self.svc._publish(threading.Event()))
        self.assertEqual(self.svc.status()['error_code'], 'foreign_backup')
        self.assertIn(new_foreign, self.drive.files)

    def test_delete_preserves_standalone_phone_and_unrecognized_files(self):
        self.foreign_backup()
        keep = {self.drive.put('solo-' + 'a' * 32 + '-' + 'b' * 32, b'solo'),
                self.drive.put('vi-phone-recovery-' + 'a' * 32 + '-' + 'b' * 32 + '.json', b'phone recovery'),
                self.drive.put('unrelated.json', b'unrelated')}
        self.svc.request_disconnect(True, delete_existing=True)
        self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertEqual(set(self.drive.files), keep)

    def test_stuck_legacy_reset_can_be_upgraded_to_replacement(self):
        old = self.foreign_backup()
        self.svc._key()
        self.svc.intents.add(intents.RESET, {'ids': []})
        self.svc.intents.update(intents.RESET, stage='backing-up')
        self.svc.turn_off()
        with mock.patch.object(self.svc, 'start'):
            self.svc.reset_backup(True)
        self.svc._run_intents(threading.Event())
        replacement = self.svc._key().fingerprint
        with mock.patch.object(self.svc, 'ensure_running'):
            self.svc.reset_backup(True)
        self.assertEqual(self.svc._key().fingerprint, replacement)
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        self.assertFalse(old & self.drive.files.keys())

    def test_disconnect_finishes_after_restart_if_token_was_already_removed(self):
        self.svc.intents.add(intents.DISCONNECT, {'delete_mirror': True, 'delete_existing': True})
        self.svc.intents.update(intents.DISCONNECT, stage='signing-out')
        drive_client.private_storage.remove(self.svc.token_path)
        self.svc.boot()
        self.wait(lambda: not self.svc.intents.all() and not self.svc.running)
        self.assertEqual(self.svc.status()['state'], 'off')

    def test_switch_supersedes_a_failed_reset_and_archives_old_recovery(self):
        self.assertTrue(self.svc._publish())
        self.svc.recovery.enroll('synthetic passphrase only', 'synthetic passphrase only')
        self.svc.intents.add(intents.RESET, {'ids': []})
        self.svc.intents.update(intents.RESET, stage='backing-up', error='stuck')
        with mock.patch('core.config.google_client', return_value=('synthetic', '')), mock.patch.object(self.svc, 'connect'), mock.patch.object(self.svc, 'start'):
            self.svc.switch(False)
            self.svc._run_intents(threading.Event())
        self.assertIsNone(self.svc.intents.find(intents.RESET))
        self.assertEqual(self.svc.intents.find(intents.SWITCH)['stage'], 'signing-in')
        from tests.test_sync import AccountDrive
        self.svc._read_account(AccountDrive('other@example.com'))
        self.assertFalse(self.svc.recovery.status()['configured'])

    def test_pause_during_reset_preparation_does_not_turn_uploads_on_again(self):
        self.foreign_backup()
        self.svc.intents.add(intents.RESET, {'replace_existing': True})
        stop = self.svc._stop
        real_list = self.drive.list
        def pause_while_listing(*args, **kwargs):
            self.svc.turn_off()
            return real_list(*args, **kwargs)
        with mock.patch.object(self.drive, 'list', side_effect=pause_while_listing):
            with self.assertRaises(sync.ExportStopped):
                self.svc._run_intents(stop)
        self.assertNotEqual(self.writer.read(lambda db: db.get_setting(sync.S_ON)), 'on')
        self.assertGreater(self.svc.status()['paused_since'], 0)

    def test_delete_requested_during_reset_key_save_is_not_lost(self):
        self.foreign_backup()
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = mirror.MirrorKey.save
        def save(key, path):
            entered.set()
            release.wait(5)
            original(key, path)
        with mock.patch.object(mirror.MirrorKey, 'save', save):
            self.svc.reset_backup(True)
            self.assertTrue(entered.wait(2))
            self.svc.request_disconnect(True, delete_existing=True)
            release.set()
            self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertEqual(self.svc.intents.all(), [])
        self.assertEqual(self.drive.files, {})

    def test_changing_to_disconnect_without_delete_keeps_remaining_files(self):
        old = self.foreign_backup()
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = self.drive.delete
        def delete(fid):
            entered.set()
            release.wait(5)
            original(fid)
        with mock.patch.object(self.drive, 'delete', side_effect=delete):
            self.svc.request_disconnect(True, delete_existing=True)
            self.assertTrue(entered.wait(2))
            self.svc.request_disconnect(False)
            release.set()
            self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertEqual(len(set(self.drive.files) & old), len(old) - 1)

    def test_renewed_signin_resumes_failed_deletion(self):
        self.foreign_backup()
        self.svc.intents.add(intents.DISCONNECT, {'delete_mirror': True, 'delete_existing': True})
        self.svc.intents.update(intents.DISCONNECT, error='expired', code='auth_expired')
        self.svc._resume_after_sign_in()
        self.wait(lambda: not self.svc.signed_in() and not self.svc.running)
        self.assertFalse(self.drive.files)
