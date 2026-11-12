"""Update this folder (S9): a temporary PC took over with the same key; this PC takes the newer library back in place.
Synthetic libraries, secrets and an in-memory Drive only (A20 to A22)."""
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import private_storage
from core.db import Database
from library import drive_client, mirror, recovery as R, restore, update_folder
from server import intents, recovery as SR
from server.store import Writer
from server.sync import SyncService
from tests.test_sync import FakeDrive, Hub, Library

PASSWORD = 'a long synthetic recovery phrase'


class UpdateFolderTest(Library):
    def setUp(self):
        super().setUp()
        from tests.license_fixture import activate
        activate(self, self.root)
        self.db.close()
        self.drive = FakeDrive()
        self.cloud = self.root / 'cloud'
        self.writer, self.svc = self.open_pc(self.data, self.cloud)
        self.service = self.svc.recovery
        self.others = []
        self.kit = self.service.enroll(PASSWORD, PASSWORD)
        self.service.verify_kit(R.dump(self.kit).decode())
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.key = self.svc.mirror_key()

    def tearDown(self):
        for svc, writer in [(self.svc, self.writer), *self.others]:
            svc.recovery.shutdown()
            svc.shutdown()
            writer.stop()
        self.db = Database(self.data / 'content_manager.db')     # Library.tearDown closes it
        super().tearDown()

    def open_pc(self, data, cloud):
        writer = Writer(data / 'content_manager.db')
        writer.start()
        svc = SyncService(writer, Hub(), data, cloud, client_factory=lambda token: self.drive)
        svc.ensure_running = lambda: None       # the tests run the sync thread's steps themselves
        drive_client.save_token(svc.token_path, {'refresh_token': 'synthetic-' + cloud.name})
        return writer, svc

    def temporary_pc(self, publish=True):
        """Another PC restores the backup with the recovery file, becomes the backup PC and uploads: (its SyncService)."""
        empty, cloud, target = self.root / 'empty-pc', self.root / 'temp-cloud', self.root / 'temp-library'
        writer, new = self.open_pc(empty, cloud)
        try:
            new.recovery.preview(material=R.dump(self.kit).decode())
            new.recovery.start_restore(str(target))
            new.recovery.thread.join(15)
            self.assertEqual(new.recovery.job['state'], 'complete', new.recovery.job)
            with mock.patch('core.app_paths.set_data_dir'), mock.patch.dict('os.environ', {'CM_DATA_DIR': ''}):
                new.recovery.activate()
        finally:
            new.recovery.shutdown()
            new.shutdown()
            writer.stop()
        writer, temp = self.open_pc(target, cloud)
        self.others.append((temp, writer))
        kit = temp.recovery.take_over(PASSWORD, PASSWORD)
        temp.recovery.verify_kit(R.dump(kit).decode())
        if publish:
            self.assertTrue(temp._publish(), temp.status())
        return temp

    def temp_changes(self, temp, notes=12):
        """The temporary PC's work: two items edited, one removed, one added, `notes` new notes."""
        def edit(db):
            db.update_item(self.ids[2], {'description': 'Edited on the temporary PC'})
            db.update_item(self.ids[3], {'ai_desc': 'Re-described on the temporary PC'})
            db.delete_item(self.ids[5])
            return db.add_item({'url': 'https://www.instagram.com/reel/temp-new/', 'description': 'Saved on the temporary PC'})
        added = temp.writer.call(edit)
        for n in range(notes):
            (temp.data_dir / 'notes' / f'temp-{n}.md').write_text(f'---\ntopic: Temp {n}\n---\nWritten there {n}', encoding='utf-8')
        self.assertTrue(temp._publish(), temp.status())
        return added

    def phone_change(self, url, at):
        name, blob = self.key.seal_change({'format': 1, 'device': 'phone', 'at': at, 'changes': [
            {'op': 'link', 'uid': f'{at:032x}', 'url': url, 'at': at - 10}]})
        return self.drive.put(name, blob)

    def published(self):
        return self.writer.read(lambda db: db.get_sync_state())

    def download_update(self):
        """Update this folder up to Downloaded: the click, then the sync thread's step."""
        self.service.start_update()
        self.svc._run_intents(threading.Event())
        it = self.svc.intents.find(intents.UPDATE)
        self.assertEqual((it['stage'], it['error']), ('downloaded', ''), it)
        return it

    def restart(self):
        """Restart now, then the next start: the swap from the journal before anything opens the database."""
        self.assertTrue(self.service.update_activate()['restart'])
        self.service.shutdown()
        self.svc.shutdown()
        self.writer.stop()
        boot = SR.RecoveryService(SimpleNamespace(cloud_dir=self.cloud, key_path=self.cloud / 'mirror.key'))
        self.assertEqual(Path(boot.finish_activation()), self.data.resolve())
        self.writer, self.svc = self.open_pc(self.data, self.cloud)
        self.service = self.svc.recovery
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['stage'], 'claim')

    def uploaded(self, since):
        """Logical names this PC sent after `since` calls."""
        names = {self.key.name(n): n for n in self.read_manifest()['files']}
        names[self.key.name(mirror.MANIFEST)] = mirror.MANIFEST
        return [names.get(c.split(' ', 1)[1], c.split(' ', 1)[1]) for c in self.drive.calls[since:] if c.startswith('upload ')]

    def read_manifest(self):
        return json.loads(self.key.open(mirror.MANIFEST, self.drive.by_name(self.key.name(mirror.MANIFEST))))

    def owner_device(self):
        _, owner = self.service._owner(self.drive, self.key, self.kit['record']['header']['library'])
        return owner['device']

    # ── A20 ─────────────────────────────────────────────────────────────────
    def test_update_journal_remains_accepted_after_task_write_failure(self):
        stage = self.root / (update_folder.STAGE_PREFIX + 'synthetic')
        stage.mkdir()
        self.svc.intents.add(intents.UPDATE, {'stage': str(stage), 'hash': 'synthetic', 'manifest_id': 'manifest'})
        self.svc.intents.update(intents.UPDATE, stage='downloaded')
        with mock.patch('server.recovery.restore.preview', return_value={'hash': 'synthetic', 'manifest_id': 'manifest'}), \
             mock.patch.object(self.svc.intents, 'update', side_effect=OSError('synthetic task write failure')):
            result = self.service.update_activate()
        self.assertTrue(result['restart'])
        self.assertTrue(self.service._activation_pending())
        self.assertTrue(self.service.status()['restart_required'])
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['stage'], 'downloaded')

    def test_update_journal_remains_accepted_after_pause_clear_failure(self):
        stage = self.root / (update_folder.STAGE_PREFIX + 'synthetic')
        stage.mkdir()
        self.svc.intents.add(intents.UPDATE, {'stage': str(stage), 'hash': 'synthetic', 'manifest_id': 'manifest'})
        self.svc.intents.update(intents.UPDATE, stage='downloaded')
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        self.svc._set(on=True, state='idle')
        with mock.patch.object(type(self.svc), 'running', new_callable=mock.PropertyMock, return_value=True):
            token = self.svc.turn_off('recovery')
        self.svc.intents.add(intents.RESET)
        before = self.writer.read(lambda db: (db.get_setting('cloud_paused_at', ''), db.get_setting('cloud_pause_restore', '')))
        with mock.patch('server.recovery.restore.preview', return_value={'hash': 'synthetic', 'manifest_id': 'manifest'}), \
             mock.patch.object(self.svc, 'clear_pause', side_effect=OSError('synthetic Writer failure')):
            result = self.service.update_activate()
        self.assertTrue(result['restart'])
        self.assertTrue(self.service._activation_pending())
        self.assertTrue(self.service.status()['restart_required'])
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['stage'], 'swap')
        with mock.patch.object(self.svc.recovery, 'guard', side_effect=AssertionError('recovery gate bypassed')), \
             mock.patch.object(self.svc, 'ensure_running') as ensure:
            with self.assertRaises(drive_client.DriveError) as caught:
                self.svc.resume(token)
        self.assertEqual(self.svc.classified(caught.exception)['action'], 'none')
        ensure.assert_not_called()
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_paused_at', ''), db.get_setting('cloud_pause_restore', ''))), before)
        self.assertFalse(self.svc.status()['on'])

    def test_a20_only_the_difference_comes_down_one_restart_makes_this_pc_the_backup_pc_and_nothing_goes_up_twice(self):
        temp = self.temporary_pc()
        mine = self.published()
        added = self.temp_changes(temp)
        early = self.phone_change('https://example.com/from-the-phone', 5000)
        self.assertTrue(temp._intake())
        self.assertTrue(temp._publish(), temp.status())
        self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc.status()['error_code'], 'not_owner')

        before = dict(self.drive.files)
        view = self.service.update_preview()['update']
        self.assertTrue(view['eligible'], view)
        self.assertEqual(view['local_changes'], 0)
        self.assertFalse(view['nothing'])
        man = self.read_manifest()
        changed = {n for n, e in man['files'].items() if mine.get(n, {}).get('sig', '')[:16] != e['v']}
        get = set(self.service._update['diff']['get'])
        self.assertEqual(get, changed)
        self.assertEqual(view['files'], len(changed))
        self.assertGreaterEqual(len(changed), 15)
        self.assertLess(len(changed), len(man['files']))
        uid0, uid4 = self.writer.read(lambda db: [db.get_item(i)['uid'] for i in (self.ids[0], self.ids[4])])
        self.assertNotIn(f'items/{uid4}.json', get)         # unchanged there: never downloaded
        self.assertNotIn('notes/knees.md', get)
        self.assertNotIn(f'videos/{uid0}.bin', get)
        self.assertIn('notes/temp-11.md', get)

        calls = len(self.drive.calls)
        update = self.download_update()
        staged = Writer(Path(update['payload']['stage']) / 'content_manager.db')
        staged.start()
        try:
            staged.call(lambda db: (db.set_setting('cloud_paused_at', '123'), db.set_setting('cloud_pause_restore', 'old')))
        finally:
            staged.stop()
        self.writer.call(lambda db: (db.set_setting('cloud_paused_at', '123'), db.set_setting('cloud_pause_restore', 'old')))
        unchanged_ids = {e['id'] for n, e in man['files'].items() if n not in changed}
        downloaded = {c.split(' ', 1)[1] for c in self.drive.calls[calls:] if c.startswith('download ')}
        self.assertFalse(downloaded & unchanged_ids, 'an unchanged file was downloaded')
        self.assertEqual(self.drive.files, before)                         # Drive only read
        self.assertFalse(self.svc._publish())                              # nothing goes up before the restart
        self.assertEqual(self.drive.files, before)

        self.restart()
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_paused_at'), db.get_setting('cloud_pause_restore'))), ('', ''))
        self.assertEqual(self.drive.files, before)                         # the swap writes no cloud file
        self.svc._run_intents(threading.Event())                           # the claim, before any upload
        self.assertIsNone(self.svc.intents.find(intents.UPDATE))
        self.assertEqual(self.owner_device(), self.service._load()['device'])

        db = self.writer.read
        self.assertEqual(db(lambda d: d.get_item(self.ids[2])['description']), 'Edited on the temporary PC')
        self.assertEqual(db(lambda d: d.get_item(self.ids[3])['ai_desc']), 'Re-described on the temporary PC')
        self.assertIsNone(db(lambda d: d.get_item(self.ids[5])))
        self.assertTrue(db(lambda d: d.item_exists('https://www.instagram.com/reel/temp-new/')))
        self.assertTrue((self.data / 'notes' / 'temp-11.md').is_file())
        # the same video, not downloaded, under the name the newer library gives it
        self.assertEqual(mirror.video_of(self.data, self.ids[0]).read_bytes(), b'\x00video' * 300_000)
        updated = self.service.status()['updated']
        self.assertEqual((updated['published'], updated['kept']), (man['published'], 0))
        self.assertFalse(list(self.root.glob(update_folder.STAGE_PREFIX + '*')))      # staging removed

        calls = len(self.drive.calls)
        self.assertTrue(self.svc._publish(), self.svc.status())
        sent = self.uploaded(calls)
        # Nothing the other PC already sent goes up again. What may: the search vectors this PC holds and a restore does not
        # carry, and the item whose video stays only here (not a favourite, so never backed up: the other PC never had it).
        uid1 = db(lambda d: d.get_item(self.ids[1])['uid'])
        self.assertLessEqual(set(sent), {'vectors.bin', f'items/{uid1}.json', mirror.MANIFEST}, sent)
        self.assertFalse(self.svc._intake())                              # the phone's change was applied once, there
        self.assertEqual(db(lambda d: d.conn.execute('SELECT count(*) FROM items WHERE url = ?',
                                                     ('https://example.com/from-the-phone',)).fetchone()[0]), 1)
        self.assertNotEqual(early, '')
        self.assertFalse(temp._publish())                                  # the temporary PC stops
        self.assertEqual(temp.status()['error_code'], 'not_owner')
        self.assertTrue(added)

    def test_a20_nothing_changed_there_makes_this_pc_the_backup_pc_at_once_without_a_restart(self):
        # the other PC became the backup PC and never uploaded: its restore alone already differs in a few files (video
        # names, the thumbnail pack), so an upload there always makes an update with a restart
        self.temporary_pc(publish=False)
        self.writer.call(lambda db: db.update_item(self.ids[2], {'description': 'Edited here afterwards'}))
        view = self.service.update_preview()['update']
        self.assertTrue(view['eligible'] and view['nothing'], view)
        self.assertEqual(view['local_changes'], 1)
        self.service.start_update()
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['stage'], 'claim')
        self.svc._run_intents(threading.Event())
        self.assertIsNone(self.svc.intents.find(intents.UPDATE))
        self.assertEqual(self.owner_device(), self.service._load()['device'])
        self.assertTrue(self.svc._publish(), self.svc.status())             # its own later change goes up as usual
        self.assertEqual(self.writer.read(lambda db: db.get_item(self.ids[2])['description']), 'Edited here afterwards')

    # ── A21 ─────────────────────────────────────────────────────────────────
    def test_a21_local_changes_are_named_and_kept_only_in_the_dated_copy(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=2)
        self.writer.call(lambda db: db.update_item(self.ids[2], {'description': 'Local edit A'}))
        self.writer.call(lambda db: db.update_item(self.ids[4], {'description': 'Local edit B'}))
        (self.data / 'notes' / 'local-only.md').write_text('---\ntopic: Local\n---\nWritten here only', encoding='utf-8')
        view = self.service.update_preview()['update']
        self.assertEqual(view['local_changes'], 3)
        self.download_update()
        self.restart()
        self.svc._run_intents(threading.Event())

        folders = list(self.data.glob(update_folder.BEFORE_PREFIX + '*'))
        self.assertEqual(len(folders), 1)
        with closing(sqlite3.connect(folders[0] / 'content_manager.db')) as copy:
            self.assertEqual(copy.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            rows = dict(copy.execute('SELECT id, description FROM items'))
        self.assertEqual((rows[self.ids[2]], rows[self.ids[4]]), ('Local edit A', 'Local edit B'))
        self.assertIn(self.ids[5], rows)                                     # the old library entire, item removed there included
        live = self.writer.read(lambda db: {i: (db.get_item(i) or {}).get('description') for i in (self.ids[2], self.ids[4])})
        self.assertEqual(live[self.ids[2]], 'Edited on the temporary PC')    # not merged
        self.assertEqual(live[self.ids[4]], 'Secret knee drill 4')
        self.assertFalse((self.data / 'notes' / 'local-only.md').exists())
        self.assertEqual((folders[0] / 'notes' / 'local-only.md').read_text(encoding='utf-8'), '---\ntopic: Local\n---\nWritten here only')
        self.assertTrue((folders[0] / 'items' / str(self.ids[5]) / 'thumb.jpg').is_file())     # nothing deleted
        updated = self.service.status()['updated']
        self.assertEqual((updated['kept'], Path(updated['folder']).name), (3, folders[0].name))

    # ── A22 ─────────────────────────────────────────────────────────────────
    def test_a22_a_backup_made_there_during_the_download_is_fetched_before_the_swap(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=2)
        self.service.update_preview()
        real, rounds = update_folder.download, []

        def download(*args, **kw):
            real(*args, **kw)
            rounds.append(1)
            if len(rounds) == 1:
                (temp.data_dir / 'notes' / 'during.md').write_text('---\ntopic: During\n---\nWritten mid-download', encoding='utf-8')
                self.assertTrue(temp._publish(), temp.status())
        with mock.patch.object(update_folder, 'download', side_effect=download):
            self.download_update()
        self.assertEqual(len(rounds), 2)
        self.restart()
        self.svc._run_intents(threading.Event())
        self.assertEqual((self.data / 'notes' / 'during.md').read_text(encoding='utf-8'), '---\ntopic: During\n---\nWritten mid-download')
        self.assertEqual(self.owner_device(), self.service._load()['device'])

    def test_a22_a_backup_made_there_after_downloaded_is_fetched_at_restart_now(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=1)
        self.service.update_preview()
        self.download_update()
        (temp.data_dir / 'notes' / 'later.md').write_text('---\ntopic: Later\n---\nAfter Downloaded', encoding='utf-8')
        self.assertTrue(temp._publish(), temp.status())
        with self.assertRaisesRegex(R.RecoveryError, 'backed up again'):
            self.service.update_activate()
        self.assertFalse(self.service._optional(self.service.journal))
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['stage'], 'queued')
        self.svc._run_intents(threading.Event())
        self.restart()
        self.svc._run_intents(threading.Event())
        self.assertTrue((self.data / 'notes' / 'later.md').is_file())

    def test_a22_the_other_pc_backing_up_after_the_swap_is_not_claimed_over(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=1)
        self.service.update_preview()
        self.download_update()
        self.restart()
        (temp.data_dir / 'notes' / 'after-swap.md').write_text('---\ntopic: After\n---\nAfter the swap', encoding='utf-8')
        self.assertTrue(temp._publish(), temp.status())
        self.svc._run_intents(threading.Event())
        self.assertIsNone(self.svc.intents.find(intents.UPDATE))
        self.assertNotEqual(self.owner_device(), self.service._load()['device'])         # still the other PC's
        self.assertTrue(self.service.update_preview()['update']['eligible'])               # offered again (T14b)

    def test_a_claim_that_fails_stays_a_task_with_its_reason_and_try_again_claims(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=1)
        self.service.update_preview()
        self.download_update()
        self.restart()
        with mock.patch.object(self.service, '_write_owner', side_effect=drive_client.DriveError('synthetic: Drive refused the write', 503)):
            self.svc._run_intents(threading.Event())
        it = self.svc.intents.find(intents.UPDATE)
        self.assertEqual((it['stage'], it['error']), ('claim', 'synthetic: Drive refused the write'), it)    # not lost: the page offers Try again
        self.assertNotEqual(self.owner_device(), self.service._load()['device'])
        self.service.start_update()
        self.svc._run_intents(threading.Event())
        self.assertIsNone(self.svc.intents.find(intents.UPDATE))
        self.assertEqual(self.owner_device(), self.service._load()['device'])

    def test_a22_a_new_key_there_offers_only_copy_into_a_new_folder(self):
        temp = self.temporary_pc()
        temp.unpair(PASSWORD)
        self.assertTrue(temp._publish(), temp.status())
        before = dict(self.drive.files)
        view = self.service.update_preview()['update']
        self.assertEqual((view['eligible'], view['reason']), (False, 'other_key'), view)
        self.assertEqual(view['message'], SR.UPDATE_REFUSALS['other_key'])
        with self.assertRaisesRegex(R.RecoveryError, SR.UPDATE_REFUSALS['other_key'][:30]):
            self.service.start_update()
        self.assertEqual(self.drive.files, before)

    # ── refusals and Stop updating ─────────────────────────────────────────
    def test_this_pc_as_the_backup_pc_is_not_offered_an_update(self):
        view = self.service.update_preview()['update']
        self.assertEqual((view['eligible'], view['reason']), (False, 'is_owner'))

    def test_stop_updating_removes_the_staging_folder_and_changes_nothing(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=2)
        self.service.update_preview()
        self.service.start_update()
        stage = Path(self.svc.intents.find(intents.UPDATE)['payload']['stage'])
        self.service.cancel_update()
        self.assertIsNone(self.svc.intents.find(intents.UPDATE))
        self.assertFalse(stage.exists())
        self.service.update_preview()
        self.service.start_update()
        stage = Path(self.svc.intents.find(intents.UPDATE)['payload']['stage'])

        def cancel_midway(*args, **kw):
            self.service.update_cancel.set()
            args[5]()           # check(): the next file sees the stop
        with mock.patch.object(update_folder, 'download', side_effect=cancel_midway):
            self.svc._run_intents(threading.Event())
        self.assertIsNone(self.svc.intents.find(intents.UPDATE))
        self.assertFalse(stage.exists())
        self.assertEqual(self.writer.read(lambda db: db.get_item(self.ids[2])['description']), 'Secret knee drill 2')

    def test_a_pause_keeps_what_was_downloaded_and_the_next_pass_resumes(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=4)
        self.service.update_preview()
        self.service.start_update()
        stop = threading.Event()
        real = update_folder.download

        def pause(client, key, snap, names, stage, check, progress):
            def counted(done, *rest):
                progress(done, *rest)
                if done >= 2:
                    stop.set()      # a pause after two files: the next one sees it
            real(client, key, snap, names, stage, check, counted)
        with mock.patch.object(update_folder, 'download', side_effect=pause):
            with self.assertRaises(SR.ExportStopped):
                self.svc._run_intents(stop)
        it = self.svc.intents.find(intents.UPDATE)
        self.assertEqual(it['stage'], 'downloading')
        stage = Path(it['payload']['stage'])
        kept = sorted(p.name for p in (stage / 'files').iterdir())
        self.assertTrue(kept)
        calls = len(self.drive.calls)
        self.svc._run_intents(threading.Event())
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['stage'], 'downloaded')
        resumed = [c for c in self.drive.calls[calls:] if c.startswith('download ')]
        man = self.read_manifest()
        self.assertFalse({c.split(' ', 1)[1] for c in resumed} & {e['id'] for n, e in man['files'].items()
                                                                 if update_folder.staged(stage, n, e).name in kept})

    def test_a_crash_in_the_middle_of_the_swap_resumes_at_the_next_start(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=3)
        self.service.update_preview()
        self.download_update()
        self.assertEqual(self.svc.status()['task']['step'], 2)          # Switching at the restart
        self.assertTrue(self.service.update_activate()['restart'])
        self.service.shutdown()
        self.svc.shutdown()
        self.writer.stop()
        boot = SR.RecoveryService(SimpleNamespace(cloud_dir=self.cloud, key_path=self.cloud / 'mirror.key'))
        real, moved = update_folder._move, []

        def crash(src, dst):
            if len(moved) == 2:
                raise OSError('synthetic power cut')
            moved.append(dst)
            real(src, dst)
        with mock.patch.object(update_folder, '_move', side_effect=crash), self.assertRaises(OSError):
            boot.finish_activation()
        self.assertIn(boot._optional(boot.journal)['step'], ('copied', 'removed'))      # removals are done and recorded before the first placement
        self.assertEqual(Path(boot.finish_activation()), self.data.resolve())
        self.assertIsNone(boot._optional(boot.journal))
        self.writer, self.svc = self.open_pc(self.data, self.cloud)
        self.service = self.svc.recovery
        for n in range(3):
            self.assertTrue((self.data / 'notes' / f'temp-{n}.md').is_file())
        self.svc._run_intents(threading.Event())
        self.assertEqual(self.owner_device(), self.service._load()['device'])

    def test_a_swap_that_fails_before_anything_moved_keeps_this_library_and_starts(self):
        temp = self.temporary_pc()
        self.temp_changes(temp, notes=1)
        self.service.update_preview()
        self.download_update()
        self.service.update_activate()
        self.service.shutdown()
        self.svc.shutdown()
        self.writer.stop()
        boot = SR.RecoveryService(SimpleNamespace(cloud_dir=self.cloud, key_path=self.cloud / 'mirror.key'))
        with mock.patch.object(update_folder.sqlite3, 'connect', side_effect=sqlite3.OperationalError('synthetic')):
            self.assertEqual(Path(boot.finish_activation()), self.data.resolve())
        self.assertIsNone(boot._optional(boot.journal))
        self.writer, self.svc = self.open_pc(self.data, self.cloud)
        self.service = self.svc.recovery
        it = self.svc.intents.find(intents.UPDATE)
        self.assertEqual(it['stage'], 'downloaded')
        self.assertIn('did not start', it['error'])
        self.assertFalse((self.data / 'notes' / 'temp-0.md').exists())
        self.assertEqual(self.writer.read(lambda db: db.get_item(self.ids[2])['description']), 'Secret knee drill 2')
        self.service.start_update()                                     # Try again: Downloaded, Restart now once more
        self.assertEqual(self.svc.intents.find(intents.UPDATE)['error'], '')

    def test_a_damaged_journal_is_refused_without_touching_anything(self):
        boot = SR.RecoveryService(SimpleNamespace(cloud_dir=self.cloud, key_path=self.cloud / 'mirror.key'))
        for bad in ({'stage': str(self.data / 'elsewhere')}, {'before': str(self.root / 'before-update-x')}, {'step': 'nope'}):
            with self.subTest(bad=bad):
                j = {'kind': 'update', 'activation': 'a' * 32, 'target': str(self.data.resolve()),
                     'stage': str(self.data.resolve().parent / (update_folder.STAGE_PREFIX + 'b' * 32)),
                     'before': str(self.data.resolve() / 'before-update-2026-10-31'), 'step': 'prepared', **bad}
                private_storage.write(boot.journal, R.dump(j))
                with self.assertRaisesRegex(R.RecoveryError, 'damaged'):
                    boot.finish_activation()
        private_storage.remove(boot.journal)
        self.assertFalse(list(self.data.glob(update_folder.BEFORE_PREFIX + '*')))

    def test_a_restored_library_and_a_missing_recovery_setup_are_refused(self):
        with mock.patch.object(self.service, '_load', return_value=None):
            self.assertEqual(self.service.update_preview()['update']['reason'], 'no_recovery')
        state = dict(self.service._load(), restored=True)
        with mock.patch.object(self.service, '_load', return_value=state):
            self.assertEqual(self.service.update_preview()['update']['reason'], 'restored')


class SwapResumeTest(unittest.TestCase):
    """A swap that stops half way resumes from its last saved step and never takes back what it already placed."""

    def test_a_resumed_swap_keeps_the_files_the_first_run_placed_in_a_folder_it_also_removed(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        data = root / 'library'
        stage = root / (update_folder.STAGE_PREFIX + 'a' * 32)
        before = data / (update_folder.BEFORE_PREFIX + '2026-10-31')
        for folder in (data, stage):
            Database(folder / update_folder.DB_NAME).close()
        # this PC's own item 5 (made after its last backup) and the newer library's item 5 share an id: the folder goes, the newer files come
        (data / 'items' / '5').mkdir(parents=True)
        (data / 'items' / '5' / 'mine.txt').write_text('this PC only', encoding='utf-8')
        newer = {'thumb.jpg': 'newer thumbnail', 'report.md': 'newer report', 'transcript.txt': 'newer transcript'}
        (stage / 'out' / 'items' / '5').mkdir(parents=True)
        for name, text in newer.items():
            (stage / 'out' / 'items' / '5' / name).write_text(text, encoding='utf-8')
        moves = [{'path': 'items/5'}] + [{'path': f'items/5/{name}', 'from': f'out/items/5/{name}'} for name in newer]
        (stage / update_folder.PLAN).write_text(json.dumps({'moves': moves, 'state': {}, 'restamp_packs': {}, 'restamp_uploads': [],
                                                            'published': 1, 'local_changes': 0}), encoding='utf-8')
        journal = {'target': str(data), 'stage': str(stage), 'before': str(before), 'step': 'prepared'}
        real, calls, saved = update_folder._move, [], []

        def crash(src, dst):
            calls.append(dst)
            if len(calls) == 3:         # the folder goes, the thumbnail comes, then the power goes
                raise OSError('synthetic power cut')
            real(src, dst)
        with mock.patch.object(update_folder, '_move', side_effect=crash), self.assertRaises(OSError):
            update_folder.swap(journal, lambda value: saved.append(dict(value)))
        self.assertEqual((data / 'items' / '5' / 'thumb.jpg').read_text(encoding='utf-8'), 'newer thumbnail')
        update_folder.swap(dict(saved[-1]), lambda value: saved.append(dict(value)))        # the next start resumes from the last saved step
        for name, text in newer.items():
            self.assertEqual((data / 'items' / '5' / name).read_text(encoding='utf-8'), text, name)
        self.assertEqual((before / 'items' / '5' / 'mine.txt').read_text(encoding='utf-8'), 'this PC only')
        self.assertFalse((before / 'items' / '5.2').exists())
        self.assertEqual(saved[-1]['step'], 'done')
        self.assertFalse(stage.exists())


if __name__ == '__main__':
    unittest.main()
