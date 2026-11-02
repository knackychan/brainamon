"""Backup must not upload what recovery refuses (release readiness plan B1; Fred's decision Q2).

A file over its recovery limit (a video over MAX_VIDEO, any other file over MAX_FILE) is not uploaded. It is counted,
named with its size in the manifest, shown in the Backup card's status and added to the recovery preview's omissions.
Synthetic libraries and an in-memory Drive only. The limits are shrunk, so no test writes 512 MiB.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from library import drive_client, mirror, recovery as R, restore
from library.export_targets import DriveMirrorTarget
from server import sync as sync_mod
from server.store import Writer
from tests.test_sync import FakeDrive, Hub, Library, read_mirror

VIDEO, FILE = 2_000_000, 1_000_000        # the shrunk limits (512 MiB and 64 MiB for real)
BIG_VIDEO, BIG_NOTE = 2_400_000, 1_200_000


def limits(video=VIDEO, file=FILE):
    """The recovery limits, patched where they are defined: the backup and the restore both read them from library/mirror.py."""
    return mock.patch.multiple(mirror, MAX_VIDEO=video, MAX_FILE=file)


def add_oversize(test):
    """The Library fixture has two videos of 1.8 MB. Make both items favourites and the second video 2.4 MB: the
    first fits the shrunk video limit, the second does not. A note of 1.2 MB sits beside the small one."""
    test.db.update_item(test.ids[1], {'favourite': True})
    (test.data / 'items' / str(test.ids[1]) / 'video' / 'clip.mp4').write_bytes(b'\x01' * BIG_VIDEO)
    (test.data / 'notes' / 'big.md').write_bytes(b'x' * BIG_NOTE)
    test.uid = {i: test.db.conn.execute('SELECT uid FROM items WHERE id = ?', (i,)).fetchone()[0] for i in test.ids}
    test.big_video, test.big_note = f'videos/{test.uid[test.ids[1]]}.bin', 'notes/big.md'


class OverLimitTest(Library):
    def setUp(self):
        super().setUp()
        add_oversize(self)
        shrunk = limits()
        shrunk.start()
        self.addCleanup(shrunk.stop)
        self.drive, self.key = FakeDrive(), mirror.MirrorKey.generate()

    def publish(self, opts=None):
        saved = {}
        res = DriveMirrorTarget(self.drive, self.key, {}, self.data, opts or mirror.Options(),
                                save=lambda put, drop: saved.update(put)).export(self.payload())
        return res, saved

    def test_a_video_and_a_file_over_their_limits_are_not_uploaded(self):
        res, saved = self.publish()
        self.assertEqual(res.errors, [])
        man, files = read_mirror(self.drive, self.key)
        sent = {name for name, _ in self.drive.files.values()}
        for logical in (self.big_video, self.big_note):
            self.assertNotIn(logical, man['files'])                 # not in the manifest...
            self.assertNotIn(self.key.name(logical), sent)          # ...nor in Drive...
            self.assertNotIn(logical, saved)                        # ...nor recorded as published
        # counted, with names and sizes, in the manifest and in the result
        self.assertEqual(man['skipped'], {self.big_video: BIG_VIDEO, self.big_note: BIG_NOTE})
        self.assertEqual(res.skipped, man['skipped'])
        # every other file went up: the video that fits, the small note, the library, its thumbnails, a canvas
        self.assertEqual(files[f'videos/{self.uid[self.ids[0]]}.bin'], b'\x00video' * 300_000)
        self.assertEqual(files['notes/knees.md'], (self.data / 'notes' / 'knees.md').read_bytes())
        for logical in ('library/meta.json', 'library/part-000.json', 'thumbs/pack-0000.bin', 'canvases/c1.json',
                        f'items/{self.uid[self.ids[1]]}.json'):
            self.assertIn(logical, man['files'])
        self.assertEqual(res.files, len(man['files']))

    def test_the_item_of_a_skipped_video_does_not_claim_a_video_the_backup_lacks(self):
        self.publish()
        _, files = read_mirror(self.drive, self.key)
        skipped = json.loads(files[f'items/{self.uid[self.ids[1]]}.json'])['files']
        kept = json.loads(files[f'items/{self.uid[self.ids[0]]}.json'])['files']
        self.assertEqual((skipped['video'], skipped['video_name']), (False, ''))
        self.assertEqual((kept['video'], kept['video_name']), (True, 'clip.mp4'))

    def test_the_videos_setting_not_the_limit_decides_what_is_not_uploaded_and_not_counted(self):
        res, _ = self.publish(mirror.Options(videos='off'))
        man, files = read_mirror(self.drive, self.key)
        self.assertEqual(man['skipped'], {self.big_note: BIG_NOTE})        # only the note: no video was going up
        self.assertEqual(res.skipped, {self.big_note: BIG_NOTE})
        item = json.loads(files[f'items/{self.uid[self.ids[1]]}.json'])['files']
        self.assertEqual((item['video'], item['video_name']), (True, 'clip.mp4'))    # as before the limit existed

    def test_a_library_within_the_limits_writes_no_skipped_entry(self):
        with limits(10 ** 9, 10 ** 9):
            res, _ = self.publish()
        man, files = read_mirror(self.drive, self.key)
        self.assertNotIn('skipped', man)
        self.assertEqual(res.skipped, {})
        self.assertIn(self.big_video, man['files'])
        self.assertIn(self.big_note, man['files'])

    def test_without_the_skip_recovery_refuses_the_whole_backup(self):
        """The effect B1 describes: one object over a limit and the preview of the entire backup stops."""
        with limits(10 ** 9, 10 ** 9):                  # a PC that uploads whatever it finds
            self.publish()
        with self.assertRaisesRegex(R.RecoveryError, 'too large for recovery'):
            restore.preview(self.drive, self.key)

    def test_recovery_accepts_the_backup_and_the_preview_says_what_is_not_in_it(self):
        self.publish()
        snap = restore.preview(self.drive, self.key)
        self.assertEqual(snap['omissions'][0], mirror.skipped_note(2))
        self.assertEqual(snap['omissions'][1:], restore.OMISSIONS)
        stage = self.root / 'recovered'
        result = restore.materialize(self.drive, self.key, snap, stage, threading.Event(), lambda done, total: None)
        self.assertEqual(result['omissions'][0], mirror.skipped_note(2))
        self.assertTrue((stage / 'notes' / 'knees.md').is_file())
        self.assertFalse((stage / 'notes' / 'big.md').exists())
        self.assertTrue((stage / 'items' / str(self.ids[0]) / 'video' / 'recovered.mp4').is_file())
        self.assertFalse((stage / 'items' / str(self.ids[1]) / 'video').exists())

    def test_a_library_within_the_limits_adds_nothing_to_the_omissions(self):
        with limits(10 ** 9, 10 ** 9):
            self.publish()
            self.assertEqual(restore.preview(self.drive, self.key)['omissions'], restore.OMISSIONS)

    def test_the_estimate_leaves_out_what_will_not_go_up(self):
        rows = [{'id': i, 'favourite': i in self.ids[:2]} for i in self.ids]
        est = mirror.estimate(self.data, rows)
        self.assertEqual((est['videos_fav'], est['videos_fav_count']), (1_800_000, 1))
        self.assertEqual((est['videos_all'], est['videos_all_count']), (1_800_000, 1))
        with limits(10 ** 9, 10 ** 9):
            whole = mirror.estimate(self.data, rows)
        self.assertEqual((whole['videos_fav'], whole['videos_fav_count']), (1_800_000 + BIG_VIDEO, 2))
        self.assertEqual(whole['base'] - est['base'], BIG_NOTE)

    def test_a_change_only_in_what_is_left_out_still_rewrites_the_manifest(self):
        """The preview reads the count from the manifest, so the manifest follows the list although no file changed."""
        state, before = {}, None

        def run():
            nonlocal before
            saved = {}
            res = DriveMirrorTarget(self.drive, self.key, state, self.data, mirror.Options(videos='off'),
                                    save=lambda put, drop: saved.update(put), skipped_before=before).export(self.payload())
            state.update(saved)
            before = dict(res.skipped)          # what the manifest now says (the service keeps it from one publish to the next)
            return res

        def listed():
            return read_mirror(self.drive, self.key)[0].get('skipped')

        run()
        self.assertEqual(listed(), {self.big_note: BIG_NOTE})
        (self.data / 'notes' / 'big2.md').write_bytes(b'y' * 1_100_000)                  # one more file over the limit, nothing else
        second = run()
        self.assertEqual((second.uploaded, second.changed), (0, True))
        self.assertEqual(listed(), {self.big_note: BIG_NOTE, 'notes/big2.md': 1_100_000})
        self.drive.calls.clear()
        third = run()                                                                     # nothing moved: no new manifest
        self.assertEqual((third.uploaded, third.changed, self.drive.calls), (0, False, ['list']))
        (self.data / 'notes' / 'big.md').unlink()
        (self.data / 'notes' / 'big2.md').unlink()
        fourth = run()
        self.assertEqual((fourth.uploaded, fourth.changed), (0, True))
        self.assertIsNone(listed())

    def test_sealed_size_is_what_the_sealing_code_makes(self):
        key = mirror.MirrorKey.generate()
        with tempfile.TemporaryDirectory() as td:
            for n in (0, 1, 1000):
                self.assertEqual(mirror.sealed_size('notes/a.md', n), len(key.seal('notes/a.md', b'x' * n)))
            for n in (0, 1, mirror.VIDEO_CHUNK - 1, mirror.VIDEO_CHUNK, mirror.VIDEO_CHUNK + 1, 2 * mirror.VIDEO_CHUNK + 5):
                src = Path(td) / 'v.mp4'
                src.write_bytes(b'v' * n)
                self.assertEqual(mirror.sealed_size('videos/u.bin', n), key.seal_file('videos/u.bin', src, Path(td) / 'v.bin'), n)

    def test_an_object_that_seals_to_exactly_the_limit_goes_up_and_one_byte_more_does_not(self):
        """Recovery compares the sealed object in Drive with the limit, so the check does too."""
        for logical, limit, overhead in (('notes/a.md', FILE, 32), ('chats/a.json', FILE, 32)):
            self.assertFalse(mirror.too_big(logical, limit - overhead), logical)
            self.assertTrue(mirror.too_big(logical, limit - overhead + 1), logical)
        with limits(video=64 * mirror.VIDEO_CHUNK):
            fits = 64 * mirror.VIDEO_CHUNK - 8 - 28 * 64          # 64 chunks of 28 bytes and the 8-byte header
            self.assertEqual(mirror.sealed_size('videos/u.bin', fits), 64 * mirror.VIDEO_CHUNK)
            self.assertFalse(mirror.too_big('videos/u.bin', fits))
            self.assertTrue(mirror.too_big('videos/u.bin', fits + 1))
        self.assertFalse(mirror.too_big('videos/u.bin', 0))

    def test_the_note_names_the_count_and_the_limits_in_plain_words(self):
        with limits(512 * 1024 * 1024, 64 * 1024 * 1024):
            one, many = mirror.skipped_note(1), mirror.skipped_note(1234)
        self.assertEqual(mirror.skipped_note(0), '')
        self.assertEqual(one, '1 file was not uploaded because it is too big to recover '
                              '(over 512 MiB for a video, over 64 MiB for anything else). It is not in the backup.')
        self.assertEqual(many, '1,234 files were not uploaded because they are too big to recover '
                               '(over 512 MiB for a video, over 64 MiB for anything else). They are not in the backup.')

    def test_a_malformed_skipped_entry_in_a_manifest_is_ignored(self):
        self.assertEqual(restore.omissions({}), restore.OMISSIONS)
        for junk in ('x', 3, None, ['videos/a.bin'], {'videos/a.bin': 'big'}, {'videos/a.bin': True}, {'videos/a.bin': -1}):
            self.assertEqual(restore.omissions({'skipped': junk}), restore.OMISSIONS, junk)
        self.assertEqual(restore.omissions({'skipped': {'videos/a.bin': 5, 'notes/b.md': 'big'}})[0], mirror.skipped_note(1))


class SkippedStatusTest(Library):
    """What the Backup card reads: the count and its sentence in the cloud status, set by the publish."""

    def setUp(self):
        super().setUp()
        add_oversize(self)
        from tests.license_fixture import activate
        activate(self, self.root)
        self.db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.cloud = self.root / 'cloud'
        self.drive = FakeDrive()
        self.svc = sync_mod.SyncService(self.writer, Hub(), self.data, self.cloud, client_factory=lambda tok: self.drive)
        for patch in (mock.patch.object(self.svc.recovery, 'guard'), limits()):
            patch.start()
            self.addCleanup(patch.stop)
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})

    def tearDown(self):
        self.svc.shutdown()
        self.writer.stop()
        from core.db import Database
        self.db = Database(self.data / 'content_manager.db')        # Library.tearDown closes it
        super().tearDown()

    def test_the_status_carries_the_count_after_a_publish_and_clears_it_when_nothing_is_left_out(self):
        st = self.svc.status()
        self.assertEqual((st['skipped'], st['skipped_note']), (0, ''))
        self.assertTrue(self.svc._publish(), self.svc.status())
        st = self.svc.status()
        self.assertEqual((st['skipped'], st['skipped_note']), (2, mirror.skipped_note(2)))
        self.assertIn('2 files were not uploaded', st['skipped_note'])
        live = [data for kind, data in self.svc.hub.events if kind == 'cloud'][-1]
        self.assertEqual(live['skipped'], 2)                         # the page gets it with the event, not only on a reload
        local, _ = self.svc.local_files()                            # Update this folder compares the same files
        self.assertFalse({self.big_video, self.big_note} & set(local))
        # the large note goes and the large video shrinks: the next publish has nothing to leave out
        (self.data / 'notes' / 'big.md').unlink()
        (self.data / 'items' / str(self.ids[1]) / 'video' / 'clip.mp4').write_bytes(b'\x01' * 1_000_000)
        self.assertTrue(self.svc._publish(), self.svc.status())
        st = self.svc.status()
        self.assertEqual((st['skipped'], st['skipped_note']), (0, ''))
        self.assertNotIn('skipped', read_mirror(self.drive, mirror.MirrorKey.load(self.cloud / 'mirror.key'))[0])

    def test_the_service_rewrites_the_manifest_when_only_the_left_out_files_change(self):
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = mirror.MirrorKey.load(self.cloud / 'mirror.key')
        self.assertEqual(sorted(read_mirror(self.drive, key)[0]['skipped']), sorted([self.big_video, self.big_note]))
        (self.data / 'notes' / 'big2.md').write_bytes(b'y' * 1_100_000)
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertEqual(sorted(read_mirror(self.drive, key)[0]['skipped']), sorted([self.big_video, self.big_note, 'notes/big2.md']))
        self.assertEqual(self.svc.status()['skipped'], 3)
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertTrue(self.svc.status()['last_summary'].startswith('Already up to date'), self.svc.status()['last_summary'])


if __name__ == '__main__':
    unittest.main()
