"""Upload to Google Drive (projects/mobile-app/PLAN.md Phase 3): the uid migration, the sealed
mirror format, DriveMirrorTarget's diff against a fake Drive, the sync service, and the Cloud
endpoints. No network: Drive is an in-memory fake, and with uploading off nothing may call out."""
import json
import shutil
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from core import ai_client, sync_license
from core.db import Database
from library import drive_client, export, mirror, vault_sync
from library.export_targets import DriveMirrorTarget, ExportStopped
from server import sync as sync_mod
from server.store import Writer
from tests import cloud_guard  # noqa: F401  (also when discovered from the tests folder: no test reaches local/cloud/)

class FakeDrive:
    def __init__(self):
        self.files: dict[str, tuple[str, bytes]] = {}
        self.calls: list[str] = []
        self._n = 0
        self._lock = threading.Lock()      # the vault round uploads from several threads

    def about(self):
        return {'email': 'fred@example.com', 'name': 'Fred', 'used': 1, 'limit': 2}

    def list(self):
        with self._lock:
            self.calls.append('list')
            return [{'id': i, 'name': n, 'size': len(b)} for i, (n, b) in self.files.items()]

    def upload(self, name, data=None, path=None, file_id='', progress=None):
        body = data if data is not None else Path(path).read_bytes()
        with self._lock:
            self.calls.append(f'upload {name}')
            if file_id:
                if file_id not in self.files:
                    raise drive_client.DriveError('gone', 404)
            else:
                self._n += 1
                file_id = f'f{self._n}'
            self.files[file_id] = (name, body)
        return file_id

    def delete(self, file_id):
        with self._lock:
            self.calls.append(f'delete {file_id}')
            self.files.pop(file_id, None)

    def download(self, file_id):
        with self._lock:
            self.calls.append(f'download {file_id}')
            if file_id not in self.files:
                raise drive_client.DriveError('gone', 404)
            return self.files[file_id][1]

    def put(self, name, data):
        """A file another device (the phone) uploaded."""
        with self._lock:
            self._n += 1
            self.files[f'p{self._n}'] = (name, data)
            return f'p{self._n}'

    def by_name(self, name):
        with self._lock:
            return next(b for n, b in self.files.values() if n == name)


class AccountDrive(FakeDrive):
    """A Drive that answers `about()` for a chosen Google account: the other side of a Sign in again."""

    def __init__(self, email):
        super().__init__()
        self.email = email

    def about(self):
        return {'email': self.email, 'name': 'x', 'used': 3, 'limit': 4}


def read_mirror(drive: FakeDrive, key: mirror.MirrorKey) -> tuple[dict, dict]:
    """(manifest, {logical: plaintext}) as the phone will read them."""
    man = json.loads(key.open(mirror.MANIFEST, drive.by_name(key.name(mirror.MANIFEST))))
    out = {}
    for logical, f in man['files'].items():
        blob = drive.by_name(f['n'])
        out[logical] = key.open_file(logical, blob, f) if logical.startswith('videos/') else key.open(logical, blob)
    return man, out


class Library(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.data = self.root / 'data'
        self.db = Database(self.data / 'content_manager.db')
        self.ids = []
        for n in range(6):
            i = self.db.add_item({'url': f'https://www.instagram.com/reel/r{n}/', 'description': f'Secret knee drill {n}',
                                  'ai_desc': f'AI says drill {n}', 'creator': 'coach', 'tags': 'knee, drill'})
            d = self.data / 'items' / str(i)
            d.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (16, 16), (n * 37, 255 - n * 31, n * 43)).save(d / 'thumb.jpg', 'JPEG')
            self.db.update_item(i, {'thumb_path': 'thumb.jpg', 'favourite': n == 0})
            self.ids.append(i)
        (self.data / 'items' / str(self.ids[1]) / 'report.md').write_text('# Report\nThe secret report text.', encoding='utf-8')
        for i in self.ids[:2]:
            (self.data / 'items' / str(i) / 'video').mkdir()
            (self.data / 'items' / str(i) / 'video' / 'clip.mp4').write_bytes(b'\x00video' * 300_000)   # 2.1 MB: 1 chunk
        (self.data / 'notes').mkdir()
        (self.data / 'notes' / 'knees.md').write_text('---\ntopic: Knees\n---\nSecret note body', encoding='utf-8')
        (self.data / 'canvases').mkdir()
        (self.data / 'canvases' / 'c1.json').write_text('{"id":"c1","name":"Board","items":[]}', encoding='utf-8')
        v = np.arange(8, dtype=np.float32) - 3.5
        self.db.upsert_embedding(self.ids[0], ai_client.EMBEDDING_MODEL, 8, 'h', v.tobytes())

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def payload(self):
        return export.build_export_payload(self.db, None, export.collect_thumb_sources(self.db), mirror=True,
                                           vectors_model=ai_client.EMBEDDING_MODEL)


class UidMigrationTest(Library):
    def test_backfill_unique_and_search_still_works(self):
        self.db.conn.execute("UPDATE items SET uid = NULL")
        self.db.conn.commit()
        self.db.close()
        self.db = Database(self.data / 'content_manager.db')
        uids = [r[0] for r in self.db.conn.execute('SELECT uid FROM items')]
        self.assertEqual(len(set(uids)), len(uids))
        self.assertTrue(all(len(u) == 32 for u in uids))
        new = self.db.add_item({'url': 'https://x/new', 'description': 'brand new'})
        self.assertEqual(len(self.db.conn.execute('SELECT uid FROM items WHERE id = ?', (new,)).fetchone()[0]), 32)
        self.assertIn(new, self.db.fts_ids('brand'))
        self.assertEqual(self.db.conn.execute("PRAGMA integrity_check").fetchone()[0], 'ok')


class SealTest(unittest.TestCase):
    def test_roundtrip_and_wrong_key(self):
        k, other = mirror.MirrorKey.generate(), mirror.MirrorKey.generate()
        blob = k.seal('items/a.json', b'{"title":"secret"}')
        self.assertNotIn(b'secret', blob)
        self.assertEqual(k.open('items/a.json', blob), b'{"title":"secret"}')
        with self.assertRaises(mirror.MirrorKeyError):
            other.open('items/a.json', blob)
        with self.assertRaises(mirror.MirrorKeyError):        # a file cannot be passed off as another
            k.open('items/b.json', blob)
        self.assertNotEqual(k.name('items/a.json'), other.name('items/a.json'))
        self.assertRegex(k.name('items/a.json'), r'^[0-9a-f]{32}$')

    def test_key_file(self):
        d = Path(tempfile.mkdtemp())
        k = mirror.MirrorKey.generate()
        k.save(d / 'mirror.key')
        self.assertEqual(mirror.MirrorKey.load(d / 'mirror.key').master, k.master)
        self.assertIsNone(mirror.MirrorKey.load(d / 'none.key'))
        shutil.rmtree(d)

    def test_video_chunks(self):
        d = Path(tempfile.mkdtemp())
        src = d / 'v.mp4'
        src.write_bytes(bytes(range(256)) * (mirror.VIDEO_CHUNK // 256 * 2 + 10))   # 2 chunks + a bit
        k = mirror.MirrorKey.generate()
        size = k.seal_file('videos/u.bin', src, d / 'v.bin')
        blob = (d / 'v.bin').read_bytes()
        self.assertEqual(size, len(blob))
        self.assertEqual(struct.unpack('>I', blob[4:8])[0], mirror.VIDEO_CHUNK)
        self.assertEqual(k.open_file('videos/u.bin', blob, {'integrity': 2, 'bytes': len(src.read_bytes()), 'sha256': __import__('hashlib').sha256(src.read_bytes()).hexdigest()}), src.read_bytes())
        shutil.rmtree(d)


class TargetTest(Library):
    def test_ticks_during_blocked_uploads_between_deletions_and_without_uploads(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {})
        for n in range(2):
            fid = drive.put('obsolete', b'x')
            state[f'obsolete/{n}'] = {'drive_id': fid, 'sig': 'old', 'size': 1}
        for name, st in state.items():
            if name != mirror.MANIFEST:
                st['sig'] = 'stale'
        drive.calls.clear()
        entered, release, twice = (threading.Event() for _ in range(3))
        trace, ticks, errors = [], [], []
        upload, delete = drive.upload, drive.delete
        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError('upload was not released')
            return upload(*args, **kwargs)
        def remove(fid):
            delete(fid)
            trace.append('delete')
        def tick():
            with drive._lock:
                sent = sum(c.startswith('upload') for c in drive.calls)
            ticks.append((threading.get_ident(), sent))
            trace.append('tick')
            if len(ticks) >= 2:
                twice.set()
        target = DriveMirrorTarget(drive, key, state, self.data, mirror.Options(), tick=tick)
        target.TICK_EVERY = .01
        payload = self.payload()
        def run():
            try:
                target.export(payload)
            except BaseException as e:
                errors.append(e)
        drive.upload, drive.delete = blocked, remove
        thread = threading.Thread(target=run)
        try:
            thread.start()
            self.assertTrue(entered.wait(5))
            self.assertTrue(twice.wait(5))
            self.assertEqual([sent for _, sent in ticks[:2]], [0, 0])
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(all(owner == thread.ident for owner, _ in ticks))
        deletes = [i for i, event in enumerate(trace) if event == 'delete']
        self.assertEqual(len(deletes), 2)
        self.assertTrue(all(trace[i + 1] == 'tick' for i in deletes))
        # Also exercise no changed uploads, and a deletion-only publish.
        for deletion in (False, True):
            trace.clear()
            if deletion:
                fid = drive.put('obsolete', b'x')
                target.state['obsolete/new'] = {'drive_id': fid, 'sig': 'old', 'size': 1}
            drive.calls.clear()
            target.export(payload)
            self.assertTrue(trace)
            self.assertFalse([c for c in drive.calls if c.startswith('upload') and c != f'upload {key.name(mirror.MANIFEST)}'])
            if deletion:
                self.assertEqual(trace[-2:], ['delete', 'tick'])

    def test_tick_abort_drains_successes_without_setting_external_stop(self):
        for error_type in (ExportStopped, ValueError):
            with self.subTest(error=error_type):
                drive, key, saved = FakeDrive(), mirror.MirrorKey.generate(), {}
                both, abort, release = (threading.Event() for _ in range(3))
                count, lock, errors = [0], threading.Lock(), []
                upload = drive.upload
                def blocked(*args, **kwargs):
                    with lock:
                        count[0] += 1
                        if count[0] >= 2:
                            both.set()
                    if not release.wait(10):
                        raise AssertionError('upload was not released')
                    return upload(*args, **kwargs)
                def tick():
                    if both.is_set():
                        abort.set()
                        raise error_type('fixture tick abort')
                drive.upload = blocked
                stop = threading.Event()
                target = DriveMirrorTarget(drive, key, {}, self.data, mirror.Options(), tick=tick, stop=stop,
                                          save=lambda put, drop: saved.update(put))
                target.TICK_EVERY = .01
                payload = self.payload()
                def run():
                    try:
                        target.export(payload)
                    except BaseException as e:
                        errors.append(e)
                thread = threading.Thread(target=run)
                try:
                    thread.start()
                    self.assertTrue(abort.wait(5))
                    self.assertTrue(thread.is_alive())
                finally:
                    release.set()
                    thread.join(10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], error_type)
                self.assertFalse(stop.is_set())
                self.assertEqual({v['drive_id'] for v in saved.values()}, set(drive.files))
                self.assertGreaterEqual(len(saved), 2)
                self.assertNotIn(f'upload {key.name(mirror.MANIFEST)}', drive.calls)
                drive.upload = upload
                _, resumed = self.publish(drive, key, saved)
                self.assertFalse((set(resumed) - {mirror.MANIFEST}) & set(saved))
                read_mirror(drive, key)

    def test_worker_abort_drains_running_successes_and_resumes(self):
        from types import SimpleNamespace
        from library import export_targets
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        saved, successful = {}, []
        entered, succeeded, release, cut = (threading.Event() for _ in range(4))
        target = DriveMirrorTarget(drive, key, {}, self.data, mirror.Options(),
                                  save=lambda put, drop: saved.update(put))
        target.UPLOAD_WORKERS = 3
        real = target._send
        count, lock, errors = [0], threading.Lock(), []
        def send(f, old=None):
            with lock:
                count[0] += 1
                n = count[0]
            if n == 1:
                entered.set()
                if not release.wait(10):
                    raise AssertionError('running worker was not released')
            elif n == 2:
                if not entered.wait(5) or not succeeded.wait(5):
                    raise AssertionError('workers did not enter')
                raise ExportStopped()
            got = real(f, old)
            successful.append(got[2])
            succeeded.set()
            return got
        def run():
            try:
                target.export(self.payload_snapshot)
            except BaseException as e:
                errors.append(e)
        self.payload_snapshot = self.payload()
        target._send = send
        thread = threading.Thread(target=run)
        with mock.patch.object(export_targets, 'threading', SimpleNamespace(Event=lambda: cut)):
            try:
                thread.start()
                self.assertTrue(cut.wait(5), 'abort was not observed by the owner')
                self.assertTrue(thread.is_alive())
            finally:
                release.set()
                thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ExportStopped)
        self.assertEqual({v['drive_id'] for v in saved.values()}, set(successful))
        self.assertGreaterEqual(len(successful), 2)
        self.assertNotIn(f'upload {key.name(mirror.MANIFEST)}', drive.calls)
        _, resumed = self.publish(drive, key, saved)
        self.assertFalse((set(resumed) - {mirror.MANIFEST}) & set(saved))
        read_mirror(drive, key)

    def test_manifest_abort_and_failed_save_are_not_lost(self):
        for failed_save in (False, True):
            with self.subTest(failed_save=failed_save):
                drive, key, saved = FakeDrive(), mirror.MirrorKey.generate(), {}
                def save(put, drop):
                    if failed_save:
                        raise OSError('fixture save failed')
                    saved.update(put)
                target = DriveMirrorTarget(drive, key, {}, self.data, mirror.Options(), save=save)
                real = target._send
                def send(f, old=None):
                    if f.name == mirror.MANIFEST:
                        raise ExportStopped()
                    return real(f, old)
                target._send = send
                with self.assertRaisesRegex(OSError, 'fixture save failed') if failed_save else self.assertRaises(ExportStopped):
                    target.export(self.payload())
                self.assertNotIn(f'upload {key.name(mirror.MANIFEST)}', drive.calls)
                if not failed_save:
                    self.assertEqual(len(saved), len(drive.files))

    def publish(self, drive, key, state, opts=None):
        saved = {}
        res = DriveMirrorTarget(drive, key, state, self.data, opts or mirror.Options(),
                                save=lambda put, drop: saved.update(put)).export(self.payload())
        return res, saved

    def test_first_publish_is_complete_and_unreadable_without_the_key(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        res, state = self.publish(drive, key, {})
        self.assertFalse(res.errors)
        man, files = read_mirror(drive, key)
        uid0 = self.db.conn.execute('SELECT uid FROM items WHERE id = ?', (self.ids[0],)).fetchone()[0]
        self.assertEqual(man['items'], 6)
        self.assertIn('library/part-000.json', files)
        rows = json.loads(files['library/part-000.json'])
        self.assertEqual([r['id'] for r in rows], self.ids)
        self.assertTrue(rows[0]['fav'] and rows[0]['thumb'] and rows[0]['uid'] == uid0)
        item1 = json.loads(files[f"items/{rows[1]['uid']}.json"])
        self.assertIn('secret report text', item1['report'])
        self.assertTrue(item1['files']['video'])
        pack = mirror.read_pack(files['thumbs/pack-0000.bin'])
        self.assertEqual(sorted(pack), self.ids)
        self.assertTrue(all(b[:2] == b'\xff\xd8' for b in pack.values()))
        self.assertIn('notes/knees.md', files)
        self.assertIn('canvases/c1.json', files)
        # videos: favourites only by default
        self.assertEqual([k for k in files if k.startswith('videos/')], [f'videos/{uid0}.bin'])
        self.assertEqual(files[f'videos/{uid0}.bin'], b'\x00video' * 300_000)
        vec = files['vectors.bin']
        n = struct.unpack('>I', vec[4:8])[0]
        head = json.loads(vec[8:8 + n])
        self.assertEqual((head['dim'], head['ids']), (8, [self.ids[0]]))
        q = np.frombuffer(vec[8 + n:], dtype=np.int8)
        self.assertEqual(int(q[-1]), 127)
        # Drive sees hashed names and scrambled bytes only
        for name, blob in drive.files.values():
            self.assertRegex(name, r'^[0-9a-f]{32}$')
            for secret in (b'Secret', b'secret', b'coach', b'instagram', b'Knees'):
                self.assertNotIn(secret, blob)
        other = mirror.MirrorKey.generate()
        with self.assertRaises(mirror.MirrorKeyError):
            other.open(mirror.MANIFEST, drive.by_name(key.name(mirror.MANIFEST)))
        self.assertEqual(set(state), set(man['files']) | {mirror.MANIFEST})

    def test_second_publish_sends_nothing_and_an_edit_sends_little(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {})
        drive.calls.clear()
        res, _ = self.publish(drive, key, state)
        self.assertEqual((res.uploaded, res.deleted, res.changed), (0, 0, False))
        self.assertEqual(drive.calls, ['list'])

        self.db.update_item(self.ids[3], {'tags': 'knee, drill, new'})
        drive.calls.clear()
        res, put = self.publish(drive, key, state)
        state.update(put)
        uid3 = self.db.conn.execute('SELECT uid FROM items WHERE id = ?', (self.ids[3],)).fetchone()[0]
        self.assertEqual(set(put), {f'items/{uid3}.json', 'library/part-000.json', 'search/text-000.json.gz', mirror.MANIFEST})
        _, files = read_mirror(drive, key)
        self.assertEqual(json.loads(files[f'items/{uid3}.json'])['tags'], 'knee, drill, new')

    def test_removed_item_and_stray_files_go(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {})
        uid5 = self.db.conn.execute('SELECT uid FROM items WHERE id = ?', (self.ids[5],)).fetchone()[0]
        drive.files['stray'] = ('0' * 32, b'left from a cut-off upload')
        self.db.conn.execute('DELETE FROM items WHERE id = ?', (self.ids[5],))
        self.db.conn.commit()
        res, put = self.publish(drive, key, state)
        self.assertIn('stray', set(drive.files))  # unknown namespace is retained
        man, files = read_mirror(drive, key)
        self.assertNotIn(f'items/{uid5}.json', files)
        self.assertEqual(len(drive.files), len(man['files']) + 2)      # manifest and unknown record

    def test_a_thumb_that_never_arrives_does_not_hold_the_upload(self):
        """Bug 6: rows that say they have a thumbnail whose file is missing or broken. The pack goes up
        without them, the next publish sends nothing (no endless resend), and the pack follows once
        the file arrives."""
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        gone = self.data / 'items' / str(self.ids[2]) / 'thumb.jpg'
        good = gone.read_bytes()
        gone.unlink()
        (self.data / 'items' / str(self.ids[3]) / 'thumb.jpg').write_bytes(b'not a jpeg')
        res, state = self.publish(drive, key, {})
        self.assertEqual(res.errors, [])
        _, files = read_mirror(drive, key)
        pack = mirror.read_pack(files['thumbs/pack-0000.bin'])
        self.assertEqual(sorted(pack), [i for i in self.ids if i != self.ids[2]])
        self.assertEqual(pack[self.ids[3]], b'not a jpeg')        # undecodable: sent as it is (export.downscale_jpeg)
        res, _ = self.publish(drive, key, state)
        self.assertEqual((res.uploaded, res.changed), (0, False))
        gone.write_bytes(good)
        res, put = self.publish(drive, key, state)
        self.assertIn('thumbs/pack-0000.bin', put)
        _, files = read_mirror(drive, key)
        self.assertIn(self.ids[2], mirror.read_pack(files['thumbs/pack-0000.bin']))

    def test_leftovers_are_deleted_after_the_manifest_and_counted(self):
        """The 2026-10-13 stall: thousands of stray files were deleted one call at a time BEFORE the
        manifest went up, with the bar at 13 of 13. The phone saw no library until the last delete."""
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {})
        for n in range(4):
            drive.files[f'stray{n}'] = ('0' * 32, b'x')
            state[f'obsolete/{n}'] = {'drive_id': f'stray{n}', 'sig': 'old', 'size': 1}
        self.db.conn.execute('DELETE FROM items WHERE id = ?', (self.ids[5],))
        self.db.conn.commit()
        drive.calls.clear()
        seen = []
        DriveMirrorTarget(drive, key, state, self.data, mirror.Options(), save=lambda put, drop: None
                          ).export(self.payload(), progress=lambda d, t: seen.append((d, t)))
        manifest_at = drive.calls.index(f'upload {key.name(mirror.MANIFEST)}')
        deletes = [i for i, c in enumerate(drive.calls) if c.startswith('delete')]
        self.assertGreaterEqual(len(deletes), 5)      # the removed item's file and the four strays
        self.assertGreater(min(deletes), manifest_at)
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertGreaterEqual(seen[-1][1], 5)       # the deletes are part of the bar
        man, _ = read_mirror(drive, key)
        self.assertEqual(man['items'], 5)

    def test_stop_ends_the_delete_pass_and_the_next_publish_finishes_it(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {})
        for n in range(6):
            drive.files[f'stray{n}'] = ('0' * 32, b'x')
            state[f'obsolete/{n}'] = {'drive_id': f'stray{n}', 'sig': 'old', 'size': 1}
        stop, real = threading.Event(), drive.delete

        def delete(fid):
            real(fid)
            if sum(c.startswith('delete') for c in drive.calls) >= 2:
                stop.set()
        drive.delete = delete
        with self.assertRaises(ExportStopped):
            DriveMirrorTarget(drive, key, state, self.data, mirror.Options(), save=lambda put, drop: None, stop=stop
                              ).export(self.payload())
        self.assertEqual(sum(c.startswith('delete') for c in drive.calls), 2)
        drive.delete = real
        self.publish(drive, key, state)
        self.assertFalse([f for f in drive.files if f.startswith('stray')])

    def test_files_go_up_several_at_a_time(self):
        """A full upload (first publish, Unpair, another account) took hours one request at a time."""
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        both = threading.Barrier(2, timeout=5)        # breaks unless two uploads are in flight together
        real, lock, seen = drive.upload, threading.Lock(), [0]

        def upload(name, **kw):
            with lock:
                seen[0] += 1
                first_two = seen[0] <= 2
            if first_two:
                both.wait()
            return real(name, **kw)
        drive.upload = upload
        res, _ = self.publish(drive, key, {})
        self.assertFalse(both.broken)
        self.assertFalse(res.errors)
        self.assertEqual(read_mirror(drive, key)[0]['items'], 6)

    def test_stop_mid_upload_records_what_went_up_and_the_next_publish_sends_the_rest(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        stop, real, saved = threading.Event(), drive.upload, {}

        def upload(name, **kw):
            out = real(name, **kw)
            if sum(c.startswith('upload') for c in drive.calls) >= 3:
                stop.set()
            return out
        drive.upload = upload
        with self.assertRaises(ExportStopped):
            DriveMirrorTarget(drive, key, {}, self.data, mirror.Options(), stop=stop,
                              save=lambda put, drop: saved.update(put)).export(self.payload())
        sent = sum(c.startswith('upload') for c in drive.calls)
        self.assertGreaterEqual(sent, 3)
        self.assertEqual(len(saved), sent)                         # every file that went up is recorded
        self.assertNotIn(mirror.MANIFEST, saved)                   # the manifest only after all the others
        drive.upload, drive.calls = real, []
        res, put = self.publish(drive, key, saved)
        self.assertEqual(res.deleted, 0)                           # nothing left over to delete
        self.assertFalse(set(put) - {mirror.MANIFEST} & set(saved))   # nothing sent twice
        self.assertEqual(read_mirror(drive, key)[0]['items'], 6)

    def test_a_refused_sign_in_stops_the_upload(self):
        drive, key, saved = FakeDrive(), mirror.MirrorKey.generate(), {}
        real, lock, seen = drive.upload, threading.Lock(), [0]

        def upload(name, **kw):
            with lock:
                seen[0] += 1
                refuse = seen[0] > 2
            if refuse:
                raise drive_client.DriveError('sign in again', 401)
            return real(name, **kw)
        drive.upload = upload
        with self.assertRaises(drive_client.DriveError):
            DriveMirrorTarget(drive, key, {}, self.data, mirror.Options(),
                              save=lambda put, drop: saved.update(put)).export(self.payload())
        self.assertEqual(len(saved), 2)
        self.assertNotIn(key.name(mirror.MANIFEST), {n for n, _ in drive.files.values()})

    def test_videos_all_and_off(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {}, mirror.Options(videos='all'))
        _, files = read_mirror(drive, key)
        self.assertEqual(len([k for k in files if k.startswith('videos/')]), 2)
        self.publish(drive, key, state, mirror.Options(videos='off', canvases=False))
        man, files = read_mirror(drive, key)
        self.assertFalse([k for k in files if k.startswith(('videos/', 'canvases/'))])
        self.assertEqual(len(drive.files), len(man['files']) + 1)

    def test_a_target_cannot_remove_an_unknown_key_namespace(self):
        drive = FakeDrive()
        self.publish(drive, mirror.MirrorKey.generate(), {})
        old_ids = set(drive.files)
        key2 = mirror.MirrorKey.generate()
        self.publish(drive, key2, {})
        man, _ = read_mirror(drive, key2)
        self.assertTrue(old_ids.issubset(drive.files))
        self.assertEqual(len(drive.files), len(old_ids) + len(man['files']) + 1)

    def test_a2_every_keyed_name_twice_heals_to_one_and_touches_nothing_else(self):
        """F1 healing (I2): a Drive seeded with a second copy of every mirror file ends with one of each after the
        next publish; recovery records, change files, solo and vault files and another key's files stay."""
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        _, state = self.publish(drive, key, {})
        for name, blob in list(drive.files.values()):
            drive.put(name, blob)                                   # a second copy of every mirror file
        others = {drive.put('vi-recovery-' + 'a' * 32 + '-' + 'b' * 32 + '.json', b'record'),
                  drive.put('chg-' + 'c' * 32, b'change'),
                  drive.put('solo-' + 'd' * 32 + '-' + 'e' * 32, b'phone backup'),
                  drive.put('vb-' + 'f' * 32, b'vault blob'),
                  drive.put('0' * 32, b'another key')}
        kept = {fid: drive.files[fid] for fid in others}
        res, _put = self.publish(drive, key, state)
        man, _ = read_mirror(drive, key)
        names = [n for n, _ in drive.files.values()]
        self.assertEqual(names.count(key.name(mirror.MANIFEST)), 1)
        for entry in man['files'].values():
            self.assertEqual(names.count(entry['n']), 1, entry['n'])
        self.assertEqual({fid: drive.files[fid] for fid in others}, kept)
        self.assertEqual((res.duplicates, res.deleted, res.uploaded), (len(man['files']) + 1, len(man['files']) + 1, 0))

    def test_a3_a_create_whose_answer_is_lost_leaves_one_file_after_the_retry(self):
        """A3: Drive stored the file but the answer never arrived. The next publish takes the orphan over (same
        name, no stored id) and updates it in place instead of creating a second copy."""
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        real, lost = drive.upload, []

        def upload(name, **kw):
            fid = real(name, **kw)                                  # Drive stored it...
            if not kw.get('file_id') and name == key.name('notes/knees.md') and not lost:
                lost.append(fid)
                raise drive_client.DriveError('connection reset', 0)      # ...but the answer never arrived
            return fid
        drive.upload = upload
        res, state = self.publish(drive, key, {})
        self.assertEqual([n for n, _ in res.errors], ['notes/knees.md'])
        self.assertNotIn('notes/knees.md', state)
        res, put = self.publish(drive, key, state)
        self.assertEqual(res.errors, [])
        self.assertEqual(put['notes/knees.md']['drive_id'], lost[0])            # taken over, not duplicated
        self.assertEqual(sum(n == key.name('notes/knees.md') for n, _ in drive.files.values()), 1)
        self.assertEqual(res.duplicates, 0)


class Hub:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


class ServiceTest(Library):
    def setUp(self):
        super().setUp()
        from tests.license_fixture import activate
        activate(self, self.root)
        self.db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.cloud = self.root / 'cloud'
        self.drive = FakeDrive()
        self.svc = sync_mod.SyncService(self.writer, Hub(), self.data, self.cloud,
                                        client_factory=lambda tok: self.drive)
        # Enrollment/ownership is covered in test_recovery; this fixture exercises the legacy sync protocol.
        policy = mock.patch.object(self.svc.recovery, 'guard')
        policy.start()
        self.addCleanup(policy.stop)
        self.to_release = []

    def tearDown(self):
        for event in self.to_release:
            event.set()                 # a failed assertion must not leave shutdown() waiting on a stuck worker
        self.svc.shutdown()
        self.writer.stop()
        self.db = Database(self.data / 'content_manager.db')     # Library.tearDown closes it
        super().tearDown()

    def wait(self, cond, t=15):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_off_means_no_thread_and_no_cloud_calls(self):
        def no_net(*a, **k):
            raise AssertionError('a cloud call with Upload to Google Drive off')
        with mock.patch.object(drive_client, '_request', no_net), mock.patch.object(drive_client.urllib.request, 'urlopen', no_net):
            drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
            self.svc.boot()
            self.svc.cancel_sign_in()       # nothing to cancel: no thread, no call, still off
            self.assertFalse(self.svc.running)
            self.assertNotIn('cm-sync', [t.name for t in threading.enumerate()])
            self.assertFalse(self.svc.vault_running)
            self.svc.vault_now()            # the vault sync off too: nothing
            self.assertEqual(self.svc.status()['state'], 'off')
        self.assertEqual(self.drive.calls, [])

    def cloud_events(self) -> list[dict]:
        return [d for k, d in self.svc.hub.events if k == 'cloud']

    def test_start_shows_starting_until_the_first_publish_ends(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        gate = threading.Event()

        def first_publish(stop=None):
            gate.wait(10)
            return False
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', first_publish):
            self.svc.turn_on()
            st = self.svc.status()
            self.assertEqual((st['state'], st['running']), ('starting', True))
            ev = self.cloud_events()[-1]
            self.assertEqual((ev['state'], ev['running'], ev['seq']), ('starting', True, st['seq']))
            gate.set()
        self.svc.turn_off()

    def test_seq_grows_with_every_change(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        s0 = self.svc.status()['seq']
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0))
        ev = self.cloud_events()
        states = [d['state'] for d in ev]
        self.assertEqual(states[0], 'starting')
        self.assertLess(states.index('starting'), states.index('publishing'))
        self.assertGreater(ev[states.index('publishing')]['seq'], ev[0]['seq'])
        self.assertGreater(ev[0]['seq'], s0)
        self.assertEqual(max(d['seq'] for d in ev), self.svc.status()['seq'])
        self.svc.turn_off()

    def test_stop_shows_stopping_while_the_threads_end(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        gate, entered = threading.Event(), threading.Event()

        def slow_publish(stop=None):
            entered.set()
            gate.wait(10)       # an upload that does not see the stop flag at once
            return False
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', slow_publish):
            self.svc.turn_on()
            self.assertTrue(entered.wait(5))
            self.svc.turn_off()
            self.assertEqual(self.svc.status()['state'], 'stopping')
            self.assertTrue(self.cloud_events()[-1]['running'])
            gate.set()
            self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'))
        self.assertEqual((self.svc.status()['state'], self.svc.running), ('off', False))
        tail = [d['state'] for d in self.cloud_events()]
        self.assertEqual(tail[-1], 'off')
        self.assertFalse(self.cloud_events()[-1]['running'])

    def test_one_stop_drains_both_workers_and_releases_the_controls(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        for first in ('mirror', 'vault'):
            with self.subTest(first=first):
                entered = {name: threading.Event() for name in ('mirror', 'vault')}
                release = {name: threading.Event() for name in entered}

                def publish(stop):
                    self.svc._set(state='publishing', done=2, total=10)
                    entered['mirror'].set()
                    release['mirror'].wait(10)
                    return False

                def vault():
                    self.svc._set(vault_state='syncing', vault_step='Sending to Drive', vault_done=438, vault_total=6349)
                    entered['vault'].set()
                    release['vault'].wait(10)

                with mock.patch.object(self.svc, '_publish', publish), mock.patch.object(self.svc, '_vault_tick', vault):
                    self.svc.turn_on()
                    self.svc.turn_vault_on()
                    threads = {'mirror': self.svc._thread, 'vault': self.svc._vault_thread}
                    try:
                        self.assertTrue(all(event.wait(5) for event in entered.values()))
                        self.svc.turn_off()
                        st = self.svc.status()
                        self.assertEqual((st['state'], st['vault_state']), ('stopping', 'stopping'))
                        self.assertEqual((st['done'], st['total'], st['vault_done'], st['vault_total']), (0, 0, 0, 0))
                        self.assertTrue(self.svc._stop.is_set() and self.svc._vault_stop.is_set())
                        self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_upload'), db.get_setting('cloud_vault'))), ('', 'off'))
                        with self.assertRaises(drive_client.DriveError):
                            self.svc.turn_on()
                        with self.assertRaises(drive_client.DriveError):
                            self.svc.turn_vault_on()
                        self.svc.upload_now()
                        self.svc.vault_now()
                        release[first].set()
                        threads[first].join(5)
                        self.assertFalse(threads[first].is_alive())
                        self.assertEqual(self.svc.status()['state'], 'stopping')
                    finally:
                        for event in release.values():
                            event.set()
                        for thread in threads.values():
                            thread.join(5)
                st = self.cloud_events()[-1]
                self.assertEqual((st['state'], st['vault_state'], st['running'], st['vault_running'], st['error']),
                                 ('off', 'off', False, False, ''))
                self.assertTrue(self.svc.signed_in())

    def test_upload_now_shows_publishing_at_once(self):
        self.svc.upload_now()           # off: nothing happens
        self.assertEqual(self.svc.status()['state'], 'off')
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch.object(sync_mod, 'POLL', 30):       # only the poke wakes the thread
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0 and self.svc.status()['state'] == 'idle'))
            first = self.svc.status()['last_publish']
            time.sleep(0.01)
            self.svc.upload_now()
            self.assertIn(self.svc.status()['state'], ('publishing', 'idle'))
            self.assertIn('publishing', [d['state'] for d in self.cloud_events()[-3:]])
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > first))
        self.svc.turn_off()

    def test_cancel_sign_in_is_at_once_and_connect_works_again(self):
        def waits(cid, secret, cancel=None):
            cancel.wait(10)
            raise drive_client.SignInCancelled('Google sign-in was not finished.')
        self.svc._sign_in = waits
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')), \
                mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', lambda stop=None: False):
            self.svc.connect()
            self.assertEqual(self.svc.status()['state'], 'signing-in')
            self.svc.cancel_sign_in()
            self.assertEqual((self.svc.status()['state'], self.svc.status()['error']), ('off', ''))
            self.assertTrue(self.wait(lambda: 'cm-signin' not in [t.name for t in threading.enumerate()]))
            self.assertEqual((self.svc.status()['state'], self.svc.status()['error']), ('off', ''))   # the cut-off wait says nothing
            self.svc._sign_in = lambda cid, secret, cancel=None: {'refresh_token': 'r', 'access_token': 'a', 'expires_at': 4e9}
            self.svc.connect()
            self.assertTrue(self.wait(lambda: self.svc.running))
        self.assertTrue(drive_client.private_storage.location(self.cloud / 'google_token.json').exists())

    def test_an_answer_that_lands_with_the_cancel_is_dropped(self):
        def answers_late(cid, secret, cancel=None):
            cancel.wait(10)         # Google's answer arrives just as Cancel sign-in is pressed
            return {'refresh_token': 'r', 'access_token': 'a', 'expires_at': 4e9}
        self.svc._sign_in = answers_late
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')):
            self.svc.connect()
            self.svc.cancel_sign_in()
            self.assertTrue(self.wait(lambda: 'cm-signin' not in [t.name for t in threading.enumerate()]))
        self.assertFalse(drive_client.private_storage.location(self.cloud / 'google_token.json').exists())
        self.assertFalse(self.svc.running)
        self.assertEqual(self.svc.status()['state'], 'off')

    def test_on_publishes_then_follows_an_edit(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(sync_mod, 'DEBOUNCE', 0.2):
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0))
            key = mirror.MirrorKey.load(self.cloud / 'mirror.key')
            man, _ = read_mirror(self.drive, key)
            self.assertEqual(man['items'], 6)
            self.assertEqual(self.svc.status()['account'], 'fred@example.com')
            first = self.svc.status()['last_publish']
            self.writer.call(lambda db: db.update_item(self.ids[2], {'ai_desc': 'edited on the desktop'}))
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > first))
            uid2 = self.writer.read(lambda db: db.conn.execute('SELECT uid FROM items WHERE id = ?', (self.ids[2],)).fetchone()[0])
            _, files = read_mirror(self.drive, key)
            self.assertEqual(json.loads(files[f'items/{uid2}.json'])['ai_desc'], 'edited on the desktop')
            self.svc.turn_off()
            self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'))
            self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), '')

    def test_a_long_vault_round_does_not_hold_the_mirror(self):
        # the vault round runs on its own thread: a round that never ends must not stop the phone mirror
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        release = threading.Event()
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(sync_mod, 'DEBOUNCE', 0.2), \
                mock.patch.object(self.svc, '_vault_tick', lambda: release.wait(20)):
            self.svc.turn_vault_on()
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0))
            self.assertTrue(self.svc.vault_running)
            release.set()
        self.svc.turn_off()
        self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'))
        self.assertFalse(self.svc.vault_running)

    def test_the_vault_sync_runs_on_its_own(self):
        """Sync my Obsidian vault has its own On / Off: no phone mirror thread, 'starting' at once,
        'stopping' then 'off' on Stop syncing; Sync now says 'starting' at once."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        rounds, release = [], threading.Event()

        def tick():
            rounds.append(1)
            release.wait(20)
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_vault_tick', tick):
            self.svc.vault_now()                        # off: nothing
            self.assertEqual(self.svc.status()['vault_state'], 'off')
            self.svc.turn_vault_on()
            st = self.svc.status()
            self.assertEqual((st['vault_state'], st['vault_running'], st['running']), ('starting', True, False))
            self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_vault', ''), db.get_setting('cloud_upload', ''))), ('on', ''))
            self.assertNotIn('cm-sync', [t.name for t in threading.enumerate()])
            self.assertTrue(self.wait(lambda: rounds))
            with self.svc._lock:
                self.svc.st['vault_state'] = 'idle'
            self.svc.vault_now()
            self.assertEqual(self.svc.status()['vault_state'], 'starting')
            n = len(self.cloud_events())
            release.set()
            self.svc.turn_vault_off()
        states = [d['vault_state'] for d in self.cloud_events()[n:]]
        self.assertEqual(states[0], 'stopping')
        self.assertEqual(states[-1], 'off')
        self.assertFalse(self.svc.vault_running)

        self.assertFalse(self.cloud_events()[-1]['vault_running'])
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_vault', '')), 'off')

    def test_vault_stop_timeout_clears_when_the_outstanding_work_ends(self):
        entered, release = threading.Event(), threading.Event()

        def tick():
            entered.set()
            release.wait(10)

        with mock.patch.object(self.svc, '_vault_tick', tick):
            self.svc.turn_vault_on()
            thread = self.svc._vault_thread
            try:
                self.assertTrue(entered.wait(5))
                with mock.patch.object(thread, 'join'):
                    with self.assertRaisesRegex(drive_client.DriveError, 'Vault sync is still stopping'):
                        self.svc.turn_vault_off()
                self.assertEqual(self.svc.status()['vault_state'], 'stopping')
                self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_vault', '')), 'off')
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.svc.status()['vault_state'], 'off')
        self.assertFalse(self.svc.vault_running)

    def test_stop_syncing_tells_the_phone_the_pc_is_off(self):
        """The phone reads the PC's vault status from Drive. A round's last words ('syncing') stayed there after Stop
        syncing, so the phone went on showing a round for a PC that had stopped. Now Stop seals an 'off' status."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        key = self.svc.mirror_key()
        name = vault_sync.status_name(key)

        def status():
            return json.loads(key.open(vault_sync.STATUS_LOGICAL, self.drive.by_name(name)))
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_vault_tick', lambda: None):
            self.svc.turn_vault_on()
            self.svc._vault_report(self.drive, key, push=True, vault_state='syncing', vault_step='Sending to Drive', vault_done=3, vault_total=9)
            self.assertEqual((status()['state'], status()['done']), ('syncing', 3))
            self.svc._vault_status_id = ''             # as after a restart: the file is found by its name, not made twice
            self.svc.turn_vault_off()
        st = status()
        self.assertEqual((st['state'], st['step'], st['done'], st['total']), ('off', '', 0, 0))
        self.assertEqual(sum(1 for n, _ in self.drive.files.values() if n == name), 1)

    def test_a_vault_error_before_a_round_reaches_the_phone(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        key = self.svc.mirror_key()
        self.writer.call(lambda db: db.set_setting('cloud_vault', 'on'))
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.start_vault()                    # no vault folder is set: the round cannot start
            self.assertTrue(self.wait(lambda: self.svc.status()['vault_state'] == 'error'))
            self.assertTrue(self.wait(lambda: any(n == vault_sync.status_name(key) for n, _ in self.drive.files.values())))
            self.svc.turn_vault_off()
        body = json.loads(key.open(vault_sync.STATUS_LOGICAL, self.drive.by_name(vault_sync.status_name(key))))
        self.assertEqual(body['state'], 'off')       # the last word is Stop's; the error was sent before it

    def test_the_account_is_read_for_the_pairing_link(self):
        self.assertEqual(self.svc.account(), '')                               # not signed in: no call
        self.assertEqual(self.drive.calls, [])
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertEqual(self.svc.account(), 'fred@example.com')               # signed in, not yet read this run

    def test_turning_vault_on_invalidates_old_phone_check_before_setting(self):
        self.svc.st['vault_devices'] = [{'device': 'stale', 'ok': True}]
        def checked(write):
            self.assertIsNone(self.svc.status()['vault_devices'])
        with mock.patch.object(self.svc, '_licensed_call', side_effect=checked), \
                mock.patch.object(self.svc, 'start_vault'):
            self.svc.turn_vault_on()

    def test_boot_starts_the_vault_sync_alone(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.writer.call(lambda db: db.set_setting('cloud_vault', 'on'))
        with mock.patch.object(self.svc, '_vault_tick', lambda: None):
            self.svc.boot()
            self.assertEqual((self.svc.vault_running, self.svc.running), (True, False))

    def test_connect_vault_signs_in_then_starts_only_the_vault(self):
        self.svc._sign_in = lambda cid, secret, cancel=None: {'refresh_token': 'r', 'access_token': 'a', 'expires_at': 4e9}
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')), \
                mock.patch.object(self.svc, '_vault_tick', lambda: None):
            self.svc.connect('vault')
            self.assertTrue(self.wait(lambda: self.svc.vault_running))
        self.assertFalse(self.svc.running)
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), '')

    def test_a_cancelled_sign_in_turns_the_waiting_vault_back_off(self):
        gate = threading.Event()

        def sign_in(cid, secret, cancel=None):
            cancel.wait(10)
            gate.set()
            raise drive_client.SignInCancelled('Google sign-in was not finished.')
        self.svc._sign_in = sign_in
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')):
            self.svc.connect('vault')
            st = self.svc.status()
            self.assertEqual((st['state'], st['vault_state']), ('signing-in', 'starting'))
            self.svc.cancel_sign_in()
            st = self.svc.status()
            self.assertEqual((st['state'], st['vault_state']), ('off', 'off'))
            self.assertTrue(gate.wait(10))
        self.assertFalse(self.svc.vault_running)

    def test_disconnect_stops_the_vault_sync_too(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch.object(self.svc, '_vault_tick', lambda: None), mock.patch.object(drive_client, 'revoke'):
            self.svc.turn_vault_on()
            self.svc.sign_out()
        self.assertFalse(self.svc.vault_running)
        self.assertEqual(self.svc.status()['vault_state'], 'off')
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_vault', '')), 'off')

    def test_off_then_on_again_never_leaves_two_publishers(self):
        """Off, then On while a publish was still deleting: the old thread had outlived shutdown() and
        start() cleared the shared stop flag, so two cm-sync threads published at once (seen live with
        py-spy). Each run now has its own stop flag, and publishes never overlap."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.turn_on()
            old = self.svc._stop
            self.svc.turn_off()
            self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'))
            self.svc.turn_on()
            self.assertTrue(old.is_set())
            self.assertFalse(self.svc._stop.is_set())
        self.svc.turn_off()
        active, peak, lock, real = [0], [0], threading.Lock(), self.drive.list

        def slow_list():
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.2)
            with lock:
                active[0] -= 1
            return real()
        self.drive.list = slow_list
        threads = [threading.Thread(target=self.svc._publish, args=(threading.Event(),)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(peak[0], 1)

    def test_a_stale_account_name_is_read_again(self):
        """The account name stored by an earlier run (another account, the development Drive) is
        replaced by the one Google reports on the first publish."""
        self.writer.call(lambda db: db.set_setting('cloud_account', 'dev@brainamon.local'))
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.boot()
            self.assertEqual(self.svc.status()['account'], 'dev@brainamon.local')
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0))
        self.assertEqual(self.svc.status()['account'], 'fred@example.com')
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_account', '')), 'fred@example.com')

    def test_sign_out_forgets_the_token_and_can_delete_the_mirror(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.turn_on()
            # State changes before its event is delivered; baseline the events only after delivery.
            self.assertTrue(self.wait(lambda: any(d['last_publish'] > 0 for d in self.cloud_events())))
        n = len(self.cloud_events())
        seen = []
        real_list = self.drive.list

        def listing():
            seen.append(self.svc.status()['state'])      # while the mirror is deleted
            return real_list()
        self.drive.list = listing
        with mock.patch.object(drive_client, 'revoke') as rv:
            self.svc.sign_out(delete_mirror=True)
            rv.assert_called_once()
        self.assertEqual(seen, ['disconnecting'])
        ev = self.cloud_events()[n:]
        states = [d['state'] for d in ev]
        self.assertEqual((states[0], states[-1]), ('disconnecting', 'off'))
        self.assertNotIn('off', states[:-1])        # no 'off' between: Disconnect shows until it is done
        counts = [(d['done'], d['total']) for d in ev if d['state'] == 'disconnecting' and d['total']]
        total = counts[0][1]
        self.assertEqual(counts, [(i, total) for i in range(total + 1)])     # the mirror delete counts up
        self.assertEqual((ev[-1]['done'], ev[-1]['total']), (0, 0))
        self.assertFalse(drive_client.private_storage.location(self.cloud / 'google_token.json').exists())
        self.assertEqual(self.drive.files, {})
        self.assertEqual(self.writer.read(lambda db: db.get_sync_state()), {})

    def test_a_failed_mirror_delete_does_not_stay_disconnecting(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})

        def broken():
            raise drive_client.DriveError('offline')
        self.drive.list = broken
        with self.assertRaises(drive_client.DriveError):
            self.svc.sign_out(delete_mirror=True)
        self.assertEqual(self.svc.status()['state'], 'off')
        self.assertTrue(drive_client.private_storage.location(self.cloud / 'google_token.json').exists())      # still signed in

    def test_connect_reads_the_account_right_after_sign_in(self):
        """The Cloud tab shows who signed in as soon as the sign-in ends, not only after an upload."""
        about = threading.Event()
        real = self.drive.about

        def first_about():
            about.set()
            return real()
        self.drive.about = first_about
        self.svc._sign_in = lambda cid, secret, cancel=None: {'refresh_token': 'r', 'access_token': 'a', 'expires_at': 4e9}
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')), \
                mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', lambda stop=None: False):
            self.svc.connect()
            self.assertTrue(self.wait(lambda: self.svc.status()['account'] == 'fred@example.com'))
        self.assertTrue(about.is_set())
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_account', '')), 'fred@example.com')
        self.assertTrue(drive_client.private_storage.location(self.cloud / 'google_token.json').exists())

    def test_switch_signs_out_keeps_the_mirror_then_signs_in_again(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'old'})
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.status()['last_publish'] > 0))
        fp = mirror.MirrorKey.load(self.cloud / 'mirror.key').fingerprint
        kept = dict(self.drive.files)
        old, new = self.drive, FakeDrive()          # another account: another Drive
        new.about = lambda: {'email': 'other@example.com', 'name': 'Other', 'used': 0, 'limit': 0}
        self.svc._raw_factory = lambda tok: new if tok.get('refresh_token') == 'new' else old
        signed = []

        def sign_in(cid, secret, cancel=None):
            signed.append(drive_client.load_token(self.cloud / 'google_token.json'))   # None: signed out first
            return {'refresh_token': 'new', 'access_token': 'a', 'expires_at': 4e9}
        self.svc._sign_in = sign_in
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')), \
                mock.patch.object(drive_client, 'revoke') as rv, mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.switch()
            self.assertTrue(self.wait(lambda: drive_client.load_token(self.cloud / 'google_token.json') is not None
                                      and self.svc.status()['state'] == 'off'))
            self.assertFalse(self.svc.running)
            self.assertFalse(self.svc.vault_running)
            self.assertNotEqual(self.writer.read(lambda db: db.get_setting('cloud_upload')), 'on')
            self.assertEqual(new.files, {})
            rv.assert_called_once()
            # another account: what was uploaded to the old one is forgotten, so the new one starts clean (I1)
            self.assertTrue(self.wait(lambda: self.writer.read(lambda db: db.get_setting('cloud_account', '')) == 'other@example.com'))
            self.assertEqual(self.writer.read(lambda db: (db.get_sync_state(), db.get_setting('cloud_epoch', ''))), ({}, ''))
        self.assertEqual(signed, [None])
        self.assertEqual(drive_client.load_token(self.cloud / 'google_token.json')['refresh_token'], 'new')
        self.assertEqual(mirror.MirrorKey.load(self.cloud / 'mirror.key').fingerprint, fp)
        self.assertEqual(old.files, kept)                         # the old account's mirror is not touched
        key = mirror.MirrorKey.load(self.cloud / 'mirror.key')
        with mock.patch.object(sync_mod, 'POLL', 0.1):                # uploading still needs an explicit action
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: any(n == key.name(mirror.MANIFEST) for n, _ in list(new.files.values()))))
        self.assertEqual(read_mirror(new, key)[0]['items'], 6)

    def test_another_copys_key_pauses_instead_of_deleting_its_mirror(self):
        """The installed app and the source copy share data/ but not the key: the second one must not
        wipe the first one's mirror (its phone then shows "Image unavailable") nor drop its phone's changes."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish())
        kept = dict(self.drive.files)
        mirror.MirrorKey.generate().save(self.cloud / 'mirror.key')       # the other copy's key
        self.assertFalse(self.svc._publish())
        self.assertEqual(self.svc.status()['error'], sync_mod.KEY_CONFLICT)
        self.assertEqual(self.drive.files, kept)
        self.assertFalse(self.svc._intake())
        self.assertEqual(self.drive.files, kept)

    def test_a_later_empty_intake_clears_the_old_failure(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish())
        self.svc._set(intake_summary=f'{sync_mod.INTAKE_FAILED}: [WinError 32]')
        self.assertFalse(self.svc._intake())
        self.assertEqual(self.svc.status()['intake_summary'], 'Nothing waiting')

    def test_save_token_retries_a_busy_file(self):
        path = self.cloud / 'google_token.json'
        real, calls = drive_client.private_storage.os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 1:
                raise PermissionError(32, 'busy')
            return real(src, dst)
        with mock.patch.object(drive_client.private_storage.os, 'replace', flaky):
            drive_client.save_token(path, {'refresh_token': 'r2'})
        self.assertEqual(len(calls), 2)
        self.assertEqual(drive_client.load_token(path)['refresh_token'], 'r2')

    def test_unpair_takes_the_mirror_over_with_the_new_key(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish())
        with mock.patch.object(self.svc, 'poke'):
            self.svc.unpair()
        self.assertTrue(self.svc._publish())
        key = mirror.MirrorKey.load(self.cloud / 'mirror.key')
        self.assertEqual(read_mirror(self.drive, key)[0]['items'], 6)
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('cloud_epoch', ''), db.get_setting('cloud_epoch_next', ''))),
                         (key.fingerprint, ''))

    def test_switch_without_a_sign_in_app_keeps_the_account(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch('core.config.google_client', return_value=('', '')), mock.patch.object(drive_client, 'revoke') as rv:
            with self.assertRaises(drive_client.DriveError):
                self.svc.switch()
            rv.assert_not_called()
        self.assertTrue(drive_client.private_storage.location(self.cloud / 'google_token.json').exists())

    def test_a1_sign_in_again_to_the_same_account_keeps_the_copy(self):
        """Probe A: Change account (or Disconnect, then Connect) choosing the SAME account must not make a second
        Drive copy: the state survives the sign-out, the next upload updates the same files, restore still works."""
        from library import restore
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'first'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = mirror.MirrorKey.load(self.cloud / 'mirror.key')
        files_before = dict(self.drive.files)
        state_before = self.writer.read(lambda db: db.get_sync_state())
        self.assertIn(mirror.MANIFEST, state_before)
        with mock.patch.object(drive_client, 'revoke'):
            self.svc.sign_out(delete_mirror=False)
        self.assertFalse(self.svc.signed_in())
        self.assertEqual(self.writer.read(lambda db: (db.get_sync_state(), db.get_setting('cloud_epoch', ''), db.get_setting('cloud_account', ''))),
                         (state_before, key.fingerprint, 'fred@example.com'))
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'again'})     # the same account
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())                  # sign_out set this run's stop event
        self.assertEqual(self.drive.files, files_before)                                           # same ids, same bytes: nothing re-sent
        self.assertEqual(sum(n == key.name(mirror.MANIFEST) for n, _ in self.drive.files.values()), 1)
        self.assertEqual(restore.preview(self.drive, key)['items'], 6)

    def slow_worker(self):
        """A publish whose one request outlasts the 10 s drain (probes B, C): (release, entered, publish)."""
        release, entered = threading.Event(), threading.Event()

        def slow_publish(stop=None):
            with self.svc._publishing:
                self.svc._set(state='publishing', upload_step='Uploading the encrypted library…', done=3, total=10)
                entered.set()
                release.wait(30)
            return False
        return release, entered, slow_publish

    def assert_state_has_a_worker(self):
        """I4 invariant: a state that means work in flight has a live worker behind it."""
        st = self.svc.status()
        if st['state'] in ('starting', 'publishing'):
            self.assertTrue(st['running'], st)
        if st['vault_state'] in ('syncing', 'starting'):
            self.assertTrue(st['vault_running'], st)

    def stop_and_restart(self):
        """A stop that puts the uploader back, the way the old handlers did: the I4 path (WorkerStopping, `_resume`)."""
        try:
            self.svc._end_mirror()
        finally:
            self.svc.start()

    def stop_vault_and_restart(self):
        try:
            self.svc._end_vault()
        finally:
            self.svc.start_vault()

    def test_a7_the_refusal_is_prompt_and_truthful_and_uploads_go_on_when_the_worker_exits(self):
        """Probe B, the stop half: 'stopping' at once, and once the old worker exits uploads go on."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        release, entered, slow_publish = self.slow_worker()
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', slow_publish):
            self.svc.start()
            try:
                self.assertTrue(entered.wait(5))
                old = self.svc._thread
                t0 = time.monotonic()
                with self.assertRaises(drive_client.DriveError):       # the request in flight cannot be cut: say so at once
                    self.stop_and_restart()
                self.assertLess(time.monotonic() - t0, 12)
                self.assertEqual(self.svc.status()['state'], 'stopping')
                release.set()
                self.assertTrue(self.wait(lambda: self.svc.running and self.svc._thread is not old))   # uploads were on: they continue
            finally:
                release.set()                                       # a failed assertion must not leave tearDown waiting on the worker
        st = self.svc.status()
        self.assertFalse(st['state'] in ('publishing', 'starting', 'disconnecting') and not st['running'], st)
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), 'on')

    def test_a7_unpair_during_a_slow_request_is_accepted_at_once(self):
        """S3: Remove all phones joins no worker. The click is recorded and locks the phones out while the request runs; the
        uploader is neither stopped nor stuck, and backup stays on."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        release, entered, slow_publish = self.slow_worker()
        self.to_release.append(release)
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', slow_publish):
            self.svc.start()
            self.assertTrue(entered.wait(5))
            old = self.svc._thread
            t0 = time.monotonic()
            self.svc.unpair()
            self.assertLess(time.monotonic() - t0, 5)
            self.assertTrue(old.is_alive())
            self.assertEqual(self.svc.status()['state'], 'publishing')
            self.assertEqual((self.svc.status()['task']['kind'], self.svc.status()['task']['stage']), ('remove_phones', 'requested'))
            self.assertEqual(self.svc._rotation()['stage'], 'prepared')
            self.assert_state_has_a_worker()
            release.set()
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), 'on')

    def test_a7_change_account_during_a_slow_request_settles_to_off(self):
        """Probe C: the halted sign-out never ran, so the token stays, the state settles to 'off' once the old
        worker exits, and Turn on uploads is accepted again."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        release, entered, slow_publish = self.slow_worker()

        def no_browser(cid, secret, cancel=None):
            raise drive_client.DriveError('synthetic: no browser')
        self.svc._sign_in = no_browser
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', slow_publish), \
                mock.patch.object(drive_client, 'revoke') as revoked, \
                mock.patch('core.config.google_client', return_value=('cid', 'sec')):
            self.svc.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(drive_client.DriveError):
                    self.svc.switch()
                self.assertIn(self.svc.status()['state'], ('stopping', 'disconnecting'))
                release.set()
                self.assertTrue(self.wait(lambda: not self.svc.running))
                self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'), self.svc.status())
                revoked.assert_not_called()
                self.assertTrue(self.svc.signed_in())
                self.svc.turn_on()                                   # accepted without a restart
                self.assertTrue(self.wait(lambda: self.svc.running))
            finally:
                release.set()

    def slow_stop(self, action, exc=None):
        """Run `action` against a mirror worker stuck in one request, with the 10 s wait skipped: (old thread,
        release, the refusal). The worker is released by the caller or by the cleanup."""
        old, release = self.slow_running()
        with mock.patch.object(old, 'join'):
            with self.assertRaises(exc or sync_mod.WorkerStopping) as caught:
                action()
        return old, release, caught.exception

    def slow_running(self):
        """A mirror worker stuck in one request: (its thread, the event that releases it)."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        release, entered, slow_publish = self.slow_worker()
        self.to_release.append(release)
        patches =[mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', slow_publish)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.svc.start()
        self.assertTrue(entered.wait(5))
        return self.svc._thread, release

    def test_a7_the_refusal_is_a_worker_stopping_error_and_says_what_happens_next(self):
        old, release, err = self.slow_stop(self.stop_and_restart)
        self.assertIsInstance(err, drive_client.DriveError)
        self.assertIn('Finishing one upload request first', str(err))
        st = self.svc.status()
        self.assertEqual((st['state'], st['running'], st['done'], st['total']), ('stopping', True, 0, 0))
        self.assert_state_has_a_worker()
        release.set()
        old.join(5)
        self.assertTrue(self.wait(lambda: self.svc.running and self.svc._thread is not old))

    def test_a7_two_refused_actions_leave_exactly_one_new_worker(self):
        old, release, _ = self.slow_stop(self.stop_and_restart)
        with mock.patch.object(old, 'join'):
            with self.assertRaises(sync_mod.WorkerStopping):
                self.stop_and_restart()                              # the same stop asked for again
        self.assertTrue(self.svc._resume)
        release.set()
        old.join(5)
        self.assertFalse(old.is_alive())
        self.assertTrue(self.wait(lambda: self.svc.running and self.svc._thread is not old))
        self.assertEqual(len([t for t in threading.enumerate() if t.name == 'cm-sync' and t.is_alive()]), 1)
        self.assert_state_has_a_worker()

    def test_a7_a_stop_while_the_old_worker_is_stopping_cancels_the_continuation(self):
        old, release, _ = self.slow_stop(self.stop_and_restart)
        self.assertTrue(self.svc._resume)
        self.svc.turn_off()                                          # the user's Stop wins over the pending restart
        self.assertFalse(self.svc._resume)
        release.set()
        old.join(5)
        self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'), self.svc.status())
        self.assertFalse(self.svc.running)
        self.assertEqual([t for t in threading.enumerate() if t.name == 'cm-sync' and t.is_alive()], [])
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), '')

    def test_a7_a_stopped_vault_round_resumes_the_vault_when_it_ends(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.writer.call(lambda db: db.set_setting('cloud_vault', 'on'))
        entered, release = threading.Event(), threading.Event()

        def tick():
            entered.set()
            release.wait(30)
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_vault_tick', tick):
            self.svc.start_vault()
            try:
                self.assertTrue(entered.wait(5))
                old = self.svc._vault_thread
                with mock.patch.object(old, 'join'):
                    with self.assertRaisesRegex(sync_mod.WorkerStopping, 'Vault sync is still stopping'):
                        self.stop_vault_and_restart()
                self.assertEqual(self.svc.status()['vault_state'], 'stopping')
                self.assert_state_has_a_worker()
                release.set()
                self.assertTrue(self.wait(lambda: self.svc.vault_running and self.svc._vault_thread is not old))
            finally:
                release.set()
        self.assert_state_has_a_worker()
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_vault', '')), 'on')

    def test_a7_a_closing_server_wins_over_the_continuation(self):
        old, release, _ = self.slow_stop(self.stop_and_restart)
        self.svc._closing = True
        release.set()
        old.join(5)
        self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'off'), self.svc.status())
        self.assertFalse(self.svc.running)
        self.svc._closing = False

    def test_a7_turn_on_settles_a_stop_whose_last_worker_has_exited(self):
        """A 'stopping' left behind with no worker (a missed settle) never refuses Turn on uploads."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.svc._set(state='stopping', vault_state='stopping')
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', lambda stop=None: False):
            self.svc.turn_on()
            self.assertTrue(self.wait(lambda: self.svc.running))
        self.assertEqual(self.svc.status()['vault_state'], 'off')

    # ── S1: Sign in again, with the account check (A5) ───────────────────────
    def expired_signin(self):
        """A published library whose Google sign-in Google then stopped accepting: the token file as it was."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r', 'access_token': 'old'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('x', 401)):
            self.assertFalse(self.svc._publish(threading.Event()))
        st = self.svc.status()
        self.assertEqual((st['token_expired'], st['error_code']), (True, 'auth_expired'))
        return drive_client.load_token(self.cloud / 'google_token.json')

    def kept(self):
        """What Sign in again must not touch: the uploaded state, the epoch, the account and every Drive file."""
        return (self.writer.read(lambda db: (db.get_sync_state(), db.get_setting('cloud_epoch', ''), db.get_setting('cloud_account', ''))),
                dict(self.drive.files))

    def again(self, token, email):
        """Sign in again with a browser that answers `token`, a sign-in of Google account `email`: (the hint the browser got,
        the revoke mock). Returns once the sign-in thread has ended."""
        hints = []

        def sign_in(cid, secret, cancel=None, login_hint=''):
            hints.append(login_hint)
            return token
        new_drive = self.drive if email == 'fred@example.com' else AccountDrive(email)
        raw = self.svc._raw_factory
        self.svc._sign_in = sign_in
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')), mock.patch.object(drive_client, 'revoke') as revoke, \
                mock.patch.object(self.svc, '_raw_factory', lambda tok: new_drive if tok.get('refresh_token') == token['refresh_token'] else raw(tok)), \
                mock.patch.object(self.svc, '_start_control') as start_control:
            self.svc.sign_in_again()
            self.assertTrue(self.wait(lambda: not (self.svc._signin_thread and self.svc._signin_thread.is_alive())))
        return hints, revoke

    def test_a5_another_accounts_sign_in_is_discarded_and_nothing_changes(self):
        before_token = self.expired_signin()
        before = self.kept()
        new = {'refresh_token': 'other', 'access_token': 'new'}
        hints, revoke = self.again(new, 'other@example.com')
        self.assertEqual(hints, ['fred@example.com'])                           # the browser is asked for the recorded account
        revoke.assert_called_once_with(new)                                     # the discarded token is revoked
        self.assertEqual(drive_client.load_token(self.cloud / 'google_token.json'), before_token)
        self.assertEqual(self.kept(), before)
        st = self.svc.status()
        self.assertEqual((st['error_code'], st['error_action'], st['token_expired'], st['state']), ('wrong_account', 'sign_in_again', True, 'off'))
        self.assertEqual(st['error'], 'You signed in as other@example.com, but this library backs up to fred@example.com. Nothing changed.')
        self.assertEqual(st['error_account'], 'other@example.com')     # the page offers "Switch this library to other@example.com…"
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_token_expired', '')), '1')

    def test_a5_the_same_account_replaces_only_the_token_file(self):
        self.expired_signin()
        before = self.kept()
        hints, revoke = self.again({'refresh_token': 'again', 'access_token': 'new', 'signed_in_at': 99.0}, 'Fred@Example.com')
        revoke.assert_not_called()
        tok = drive_client.load_token(self.cloud / 'google_token.json')
        self.assertEqual((tok['refresh_token'], tok['signed_in_at']), ('again', 99.0))
        self.assertEqual(self.kept(), before)                                   # same ids, same bytes, state and epoch untouched
        st = self.svc.status()
        self.assertEqual((st['token_expired'], st['error'], st['error_code'], st['state']), (False, '', '', 'off'))
        self.assertEqual(st['token_issued'], 99.0)
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_token_expired', '')), '')
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())    # and the next upload sends nothing
        self.assertEqual(self.kept(), before)

    def test_a5_what_was_on_starts_again_and_the_access_record_is_renewed_at_once(self):
        self.expired_signin()
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        key = self.svc.mirror_key()
        ran = []
        self.svc._control_wake.clear()
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', lambda stop=None: ran.append(1) or True):
            self.again({'refresh_token': 'again'}, 'fred@example.com')
            self.assertTrue(self.wait(lambda: self.svc.running and ran), self.svc.status())
        self.assertTrue(self.svc._control_wake.is_set())                        # the control thread renews the record without waiting a minute
        self.svc.publish_license_control()
        self.assertIn(key.name(sync_license.LOGICAL), self.drive_names())

    def test_a5_boot_after_an_expired_sign_in_shows_why_and_starts_nothing(self):
        self.expired_signin()
        self.writer.call(lambda db: (db.set_setting('cloud_upload', 'on'), db.set_setting('cloud_vault', 'on')))
        self.svc._set(token_expired=False, state='off', error='', error_code='', error_action='')       # a restart forgets memory, not the mark
        with mock.patch.object(self.svc, 'start') as start, mock.patch.object(self.svc, 'start_vault') as start_vault, \
                mock.patch.object(self.svc, '_start_control'):
            self.svc.boot()
        start.assert_not_called()
        start_vault.assert_not_called()
        st = self.svc.status()
        self.assertEqual((st['token_expired'], st['state'], st['error_code'], st['error_action']), (True, 'signed-out', 'auth_expired', 'sign_in_again'))
        self.assertIn('Choose Sign in again', st['error'])
        self.assertNotEqual(st['state'], 'off')

    def test_a5_an_expired_mark_needs_a_token_and_a_good_call_or_a_new_sign_in_clears_it(self):
        self.svc.classified(drive_client.DriveError('x', 401))
        self.assertFalse(self.svc.status()['token_expired'])                    # no token: nothing to be expired
        self.expired_signin()
        self.svc.mirror_key()
        self.svc.publish_license_control()                                      # a renewal that works
        self.assertFalse(self.svc.status()['token_expired'])
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_token_expired', '')), '')
        self.svc.classified(drive_client.DriveError('x', 401))
        self.assertTrue(self.svc.status()['token_expired'])
        with mock.patch.object(drive_client, 'revoke'):
            self.svc.sign_out()
        self.assertFalse(self.svc.status()['token_expired'])
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_token_expired', '')), '')

    def test_a_permission_refusal_does_not_disable_backup_after_restart(self):
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.writer.call(lambda db: db.set_setting('cloud_upload', 'on'))
        for reason in ('', 'appNotAuthorizedToFile', 'insufficientFilePermissions', 'domainPolicy', 'accessNotConfigured'):
            with self.subTest(reason=reason):
                failed = self.publish_fails(drive_client.DriveError('refused', 403, reason))
                self.assertEqual((failed['error_code'], failed['error_action']), ('other', 'retry'))
                self.assertFalse(self.svc.status()['token_expired'])
                self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_token_expired', '')), '')
                with mock.patch.object(self.svc, 'start') as start, mock.patch.object(self.svc, '_start_control'):
                    self.svc.boot()
                start.assert_called_once_with()

    def test_a5_sign_in_again_while_one_is_open_joins_it_and_a_cancel_changes_nothing(self):
        before_token = self.expired_signin()
        before = self.kept()
        calls, entered, release = [], threading.Event(), threading.Event()

        def sign_in(cid, secret, cancel=None, login_hint=''):
            calls.append(login_hint)
            entered.set()
            release.wait(10)
            raise drive_client.SignInCancelled('Google sign-in was not finished.')
        self.svc._sign_in = sign_in
        self.to_release.append(release)
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')):
            self.svc.sign_in_again()
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.svc.status()['state'], 'signing-in')
            self.svc.sign_in_again()
            release.set()
            self.assertTrue(self.wait(lambda: not self.svc._signin_thread.is_alive()))
        self.assertEqual(calls, ['fred@example.com'])
        st = self.svc.status()
        self.assertEqual((st['state'], st['error'], st['token_expired']), ('off', 'Google sign-in was not finished.', True))
        self.assertEqual(drive_client.load_token(self.cloud / 'google_token.json'), before_token)
        self.assertEqual(self.kept(), before)

    def test_a5_sign_in_again_needs_a_connected_account_and_a_sign_in_app(self):
        with self.assertRaisesRegex(drive_client.DriveError, 'not connected'):
            self.svc.sign_in_again()
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        with mock.patch('core.config.google_client', return_value=('', '')):
            with self.assertRaisesRegex(drive_client.DriveError, 'No Google sign-in app'):
                self.svc.sign_in_again()
        self.assertEqual(self.svc.status()['state'], 'off')

    def test_a5_an_account_nobody_recorded_is_accepted(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        hints, revoke = self.again({'refresh_token': 'first'}, 'new@example.com')       # no recorded account: nothing to check against
        self.assertEqual(hints, [''])
        revoke.assert_not_called()
        self.assertEqual(drive_client.load_token(self.cloud / 'google_token.json')['refresh_token'], 'first')

    def test_a5_the_recovery_setups_account_is_the_hint_and_the_check(self):
        from library import recovery as R
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        record, secret = R.create(mirror.MirrorKey.generate(), 'a long synthetic recovery phrase', 'recorded@example.com')
        self.svc.recovery._save({'record': record, 'secret': R.encode(secret), 'device': 'a' * 32, 'account': 'recorded@example.com',
                                 'verified': False, 'verified_at': 0, 'enrolled': True})
        hints, revoke = self.again({'refresh_token': 'other'}, 'fred@example.com')
        self.assertEqual(hints, ['recorded@example.com'])
        revoke.assert_called_once()
        self.assertEqual(drive_client.load_token(self.cloud / 'google_token.json')['refresh_token'], 'r')
        hints, revoke = self.again({'refresh_token': 'right'}, 'Recorded@Example.com')
        revoke.assert_not_called()
        self.assertEqual(drive_client.load_token(self.cloud / 'google_token.json')['refresh_token'], 'right')

    # ── I7: a failed upload says which kind of failure it was ───────────────
    def publish_fails(self, exc):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.svc._set(account='fred@example.com', used=int(14.5 * 2 ** 30), limit=15 * 2 ** 30)
        with mock.patch.object(self.drive, 'list', side_effect=exc):
            self.assertFalse(self.svc._publish(threading.Event()))
        return self.svc.status()

    def test_i7_a_full_drive_is_not_a_request_to_sign_in(self):
        st = self.publish_fails(drive_client.DriveError('Google Drive answered 403: quota', 403, 'storageQuotaExceeded'))
        self.assertEqual((st['state'], st['error_code'], st['error_action']), ('error', 'drive_full', 'free_space'))
        self.assertEqual(st['error'], 'Google Drive is full (14.5 of 15.0 GB). Free space in Google Drive, then choose Try again.')

    def test_i7_an_expired_sign_in_names_the_account_and_the_key_to_use(self):
        for exc in (drive_client.DriveError('x', 401), drive_client.DriveError(drive_client.SIGN_IN_REQUIRED)):
            st = self.publish_fails(exc)
            self.assertEqual((st['error_code'], st['error_action']), ('auth_expired', 'sign_in_again'))
            self.assertIn('Google Drive sign-in for fred@example.com expired or was removed. Choose Sign in again', st['error'])
            self.assertNotIn('Change account', st['error'])

    def test_i7_offline_and_rate_limits_wait_and_a_good_publish_clears_the_code(self):
        try:
            raise OSError('down')
        except OSError as cause:
            offline = drive_client.DriveError('Google Drive is out of reach: down')
            offline.__cause__ = cause
        st = self.publish_fails(offline)
        self.assertEqual((st['error_code'], st['error_action']), ('offline', 'none'))
        self.assertTrue(st['error'].startswith("Can't reach Google Drive. Nothing changed."))
        st = self.publish_fails(drive_client.DriveError('x', 429))
        self.assertEqual((st['error_code'], st['error_action']), ('rate_limited', 'wait'))
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        st = self.svc.status()
        self.assertEqual((st['error'], st['error_code'], st['error_action']), ('', '', ''))

    def test_i7_a_plain_message_has_no_code(self):
        self.svc._set(state='error', error='Something local', error_code='drive_full', error_action='free_space')
        self.svc._set(error='Something else')
        self.assertEqual((self.svc.status()['error_code'], self.svc.status()['error_action']), ('', ''))

    # ── I6: phones are locked out at the Remove click (A8) ─────────────────
    def phone_change(self, key, url, at):
        """A change file a phone sealed with `key` and put in Drive: (Drive id, the url it adds)."""
        name, blob = key.seal_change({'format': 1, 'device': 'phone', 'at': at, 'changes': [
            {'op': 'link', 'uid': f'{at:032x}', 'url': url, 'at': at - 10}]})
        return self.drive.put(name, blob)

    def drive_names(self):
        return [name for name, _ in self.drive.files.values()]

    def access_ready(self):
        """A published library and a renewed phone-access record under the library key: (key, the record's name)."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = self.svc.mirror_key()
        self.svc.publish_license_control()
        self.assertIn(key.name(sync_license.LOGICAL), self.drive_names())
        return key, key.name(sync_license.LOGICAL)

    def test_a8_the_click_deletes_the_old_access_record_and_a_late_change_is_not_applied(self):
        key, grant = self.access_ready()
        early = self.phone_change(key, 'https://example.com/before-click', 1000)
        self.svc.unpair()
        self.assertNotIn(grant, self.drive_names())                            # gone at the click, not at the end
        rotation = self.svc._rotation()
        self.assertEqual((rotation['old_changes'], rotation['lock_pending']), ([early], False))
        st = self.svc.status()
        self.assertTrue(st['rotation_clicked'] and st['rotation_locked_at'] >= st['rotation_clicked'])
        self.assertRegex(st['rotation_lock'], r'^Phones locked out at \d\d:\d\d\.$')
        late = self.phone_change(key, 'https://example.com/after-click', 2000)  # the lost phone, after the click
        self.assertTrue(self.svc._intake())
        self.assertTrue(self.writer.read(lambda db: db.item_exists('https://example.com/before-click')))
        self.assertFalse(self.writer.read(lambda db: db.item_exists('https://example.com/after-click')))
        self.assertNotIn(early, self.drive.files)                              # applied, then deleted as usual
        self.assertIn(late, self.drive.files)                                  # left in Drive, never read
        self.assertEqual(self.svc.status()['ignored_changes'], 1)
        for _ in range(3):                                                     # ten ticks cost no download and count once
            self.assertFalse(self.svc._intake())
        self.assertEqual(self.svc.status()['ignored_changes'], 1)
        self.assertNotIn(f'download {late}', self.drive.calls)

    def test_a8_the_control_thread_never_renews_the_old_key_during_a_removal(self):
        key, grant = self.access_ready()
        self.svc.unpair()
        rotation = self.svc._rotation()
        for _ in range(3):
            self.svc.publish_license_control()
            self.assertNotIn(grant, self.drive_names())
        new = self.svc._rotation_key(rotation['new'])
        self.assertEqual(self.drive_names().count(new.name(sync_license.LOGICAL)), 1)    # the new key's record is the one renewed
        body = json.loads(json.loads(new.open(sync_license.LOGICAL, self.drive.by_name(new.name(sync_license.LOGICAL))))['body'])
        self.assertEqual(body['fp'], new.fingerprint)
        self.assertEqual(self.svc.status()['rotation'], 'pending')

    def test_a8_an_offline_click_keeps_the_lock_pending_and_names_the_latest_time(self):
        key, grant = self.access_ready()
        expires = json.loads(json.loads(key.open(sync_license.LOGICAL, self.drive.by_name(grant)))['body'])['expires'] * 1000
        with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('offline')):
            self.svc.unpair()
        rotation = self.svc._rotation()
        self.assertEqual((rotation['lock_pending'], rotation['locked_at'], rotation['old_changes']), (True, 0, None))
        self.assertEqual(rotation['locked_by'], expires)                       # the grant the phone holds ends then, to the second
        self.assertLessEqual(rotation['locked_by'], rotation['clicked'] + sync_mod.GRANT_MS)
        st = self.svc.status()
        self.assertEqual((st['rotation_locked_at'], st['rotation_locked_by']), (0, expires))
        self.assertRegex(st['rotation_lock'], r'^Locked out by \d\d:\d\d at the latest: this PC stopped renewing their access$')
        self.assertIn(grant, self.drive_names())                               # nothing could be deleted yet
        self.svc.publish_license_control()                                     # the next contact
        self.assertNotIn(grant, self.drive_names())
        rotation = self.svc._rotation()
        self.assertEqual((rotation['lock_pending'], bool(rotation['locked_at'])), (False, True))
        self.assertRegex(self.svc.status()['rotation_lock'], r'^Phones locked out at \d\d:\d\d\.$')

    def test_a8_without_a_click_listing_old_change_files_are_judged_by_drive_time(self):
        from datetime import datetime, timezone
        key, grant = self.access_ready()
        stamps = {}
        original = self.drive.list

        def stamped():
            return [dict(f, **({'modifiedTime': stamps[f['id']]} if f['id'] in stamps else {})) for f in original()]

        def iso(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        before = self.phone_change(key, 'https://example.com/before', 1000)
        after = self.phone_change(key, 'https://example.com/after', 2000)
        unstamped = self.phone_change(key, 'https://example.com/unstamped', 3000)
        with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('offline')):
            self.svc.unpair()
        clicked = self.svc._rotation()['clicked']
        stamps[before], stamps[after] = iso(clicked - 5 * 60_000), iso(clicked + sync_mod.OLD_GRACE_MS + 60_000)
        with mock.patch.object(self.drive, 'list', stamped):
            self.assertTrue(self.svc._intake())
        done = lambda url: self.writer.read(lambda db: db.item_exists(url))
        self.assertEqual([done('https://example.com/before'), done('https://example.com/after'), done('https://example.com/unstamped')],
                         [True, False, False])                                 # no Drive time is no proof
        self.assertEqual((before in self.drive.files, after in self.drive.files, unstamped in self.drive.files), (False, True, True))
        self.assertEqual(self.svc.status()['ignored_changes'], 2)

    def test_a8_a_renewal_in_flight_at_the_click_cannot_undo_the_lock_out(self):
        key, grant = self.access_ready()
        entered, release = threading.Event(), threading.Event()
        upload = self.drive.upload

        def slow_upload(name, *args, **kwargs):
            entered.set()
            release.wait(10)
            return upload(name, *args, **kwargs)
        self.to_release.append(release)
        renewal = threading.Thread(target=self.svc.publish_license_control)
        with mock.patch.object(self.drive, 'upload', slow_upload), mock.patch.object(sync_mod, 'CONTROL_WAIT', 0.2):
            renewal.start()
            self.assertTrue(entered.wait(5))
            self.svc.unpair()                                                  # cannot take the pass: the lock stays pending
            self.assertTrue(self.svc._rotation()['lock_pending'])
            release.set()
            renewal.join(5)
        self.assertIn(grant, self.drive_names())                               # the renewal that began first landed
        self.svc.publish_license_control()                                     # the next pass sees the removal and deletes it
        self.assertNotIn(grant, self.drive_names())
        self.assertFalse(self.svc._rotation()['lock_pending'])

    def test_a8_a_busy_worker_delays_the_reencrypting_not_the_lock_out(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        key = self.svc.mirror_key()
        self.svc.publish_license_control()
        grant = key.name(sync_license.LOGICAL)
        old, release = self.slow_running()
        self.svc.unpair()                       # S3: accepted at once; the request in flight delays the re-encrypting only
        self.assertIn('Phones locked out at', self.svc.status()['rotation_lock'])
        self.assertNotIn(grant, self.drive_names())
        self.assertEqual(self.svc._rotation()['stage'], 'prepared')
        self.assertTrue(old.is_alive())
        release.set()
        old.join(5)

    def test_a8_a_stale_copy_cannot_take_back_what_the_click_learned(self):
        key, grant = self.access_ready()
        self.phone_change(key, 'https://example.com/before-click', 1000)
        self.svc.unpair()
        saved = self.svc._rotation()
        self.assertTrue(saved['locked_at'] and saved['old_changes'])
        stale = dict(saved, lock_pending=True, locked_at=0, old_changes=None, stage='publishing')   # a worker's older copy
        self.svc._save_rotation(stale)
        now = self.svc._rotation()
        self.assertEqual((now['stage'], now['lock_pending'], now['locked_at'], now['old_changes']),
                         ('publishing', False, saved['locked_at'], saved['old_changes']))

    def test_a8_a_removal_begun_before_the_lock_was_recorded_is_locked_by_the_next_renewal(self):
        key, grant = self.access_ready()
        self.svc.unpair()
        rotation = {k: v for k, v in self.svc._rotation().items() if k not in ('clicked', 'old_changes', 'lock_pending', 'locked_at', 'locked_by')}
        drive_client.private_storage.write(self.svc.cloud_dir / 'rotation.json', json.dumps(rotation).encode())
        self.drive.upload(grant, data=b'a renewal from an older version')
        self.assertIn(grant, self.drive_names())
        late = self.phone_change(key, 'https://example.com/legacy', 5000)
        self.svc.publish_license_control()
        self.assertNotIn(grant, self.drive_names())
        self.assertTrue(self.svc._intake())                                    # nothing to judge by: the old behaviour
        self.assertNotIn(late, self.drive.files)

    def test_a8_the_end_of_the_removal_deletes_an_old_access_record_the_click_never_reached(self):
        key, grant = self.access_ready()
        with mock.patch.object(self.drive, 'list', side_effect=drive_client.DriveError('offline')):
            self.svc.unpair()
        self.assertIn(grant, self.drive_names())
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertNotIn(grant, self.drive_names())
        rotation = self.svc._rotation()
        self.assertEqual((rotation['stage'], rotation['lock_pending'], bool(rotation['locked_at'])), ('complete', False, True))
        self.assertRegex(self.svc.status()['rotation_lock'], r'^Phones locked out at \d\d:\d\d\.$')

    def test_meta_carries_the_notes_prefix(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish())
        meta = json.loads(read_mirror(self.drive, self.svc.mirror_key())[1]['library/meta.json'])
        self.assertEqual(meta['obsidian_notes'], 'Content Manager/notes/')
        self.writer.call(lambda db: (db.set_setting('obsidian_vault', str(self.root / 'Brainamon Vault')), db.set_setting('obsidian_mode', 'owner')))
        self.assertTrue(self.svc._publish())
        meta = json.loads(read_mirror(self.drive, self.svc.mirror_key())[1]['library/meta.json'])
        self.assertEqual((meta['obsidian_notes'], meta['obsidian_vault']), ('Brainamon/Notes/', 'Brainamon Vault'))


    # ── S3 / S4 (sub-plan 08): saved tasks on the sync thread ────────────────────────────
    def restart(self):
        """The app closes and opens again on the same folders: a second service over the same Writer, cloud folder and Drive."""
        app = sync_mod.SyncService(self.writer, Hub(), self.data, self.cloud, client_factory=lambda tok: self.drive)
        policy = mock.patch.object(app.recovery, 'guard')
        policy.start()
        self.addCleanup(policy.stop)
        return app

    @staticmethod
    def card(task):
        return {k: task[k] for k in ('kind', 'stage', 'title', 'step', 'of', 'steps', 'since', 'error')}

    def test_a12_a_restart_at_each_removal_stage_resumes_it_and_shows_the_same_step(self):
        """Requested, prepared, publishing, cleanup: the task card reads the same after a restart, the removal then finishes by
        itself on a one-time thread, and backup stays off (A13)."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        stops = (('requested', None), ('prepared', lambda r: r['stage'] == 'prepared' and r.get('staged')),
                 ('publishing', lambda r: r['stage'] == 'publishing'), ('cleanup', lambda r: r['stage'] == 'cleanup'))
        for label, stop_at in stops:
            with self.subTest(stage=label):
                self.svc.unpair()
                if stop_at:
                    real = self.svc._save_rotation

                    def save(record, real=real, stop_at=stop_at):
                        real(record)
                        if stop_at(record):
                            raise OSError('synthetic: the app closed here')
                    with mock.patch.object(self.svc, '_save_rotation', save):
                        self.assertFalse(self.svc._publish())
                before = self.card(self.svc.status()['task'])
                self.assertEqual(before['stage'], label)
                app = self.restart()
                self.assertEqual(self.card(app._task_view()), before)           # the same step after the restart
                with mock.patch.object(sync_mod, 'POLL', 0.1):
                    app.boot()
                    self.assertTrue(self.wait(lambda: (app._rotation() or {}).get('stage') == 'complete'), app.status())
                    self.assertTrue(self.wait(lambda: not app.running and not app.status()['task']), app.status())
                self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), '')      # A13: backup stayed off
                self.assertEqual(app.status()['state'], 'off')
                old, self.svc = self.svc, app
                old.shutdown()
        self.assertEqual(read_mirror(self.drive, self.svc._key())[0]['items'], 6)

    def test_a13_removing_phones_with_backup_off_is_one_shot(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        old = self.svc._key()
        self.svc.unpair()
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.ensure_running()
            self.assertEqual(self.svc.status()['task']['kind'], 'remove_phones')
            self.assertTrue(self.wait(lambda: (self.svc._rotation() or {}).get('stage') == 'complete'), self.svc.status())
            self.assertTrue(self.wait(lambda: not self.svc.running), self.svc.status())
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), '')
        self.assertEqual((self.svc.status()['state'], self.svc.status()['task']), ('off', None))
        self.assertNotEqual(self.svc._key().master, old.master)

    def test_boot_never_drives_the_removal_of_another_library(self):
        """The cloud folder can be opened by another data folder (a second copy, a test run). Only the library whose database
        backed up with the removal's old or new key resumes it; the other makes no task and starts no thread."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.svc.unpair()
        other = self.root / 'other'
        other_db = Database(other / 'content_manager.db')
        other_db.close()
        writer = Writer(other / 'content_manager.db')
        writer.start()
        self.addCleanup(writer.stop)
        app = sync_mod.SyncService(writer, Hub(), other, self.cloud, client_factory=lambda tok: self.drive)
        self.addCleanup(app.shutdown)
        calls = len(self.drive.calls)
        app.boot()
        self.assertEqual((app.intents.all(), app.running, app.status()['rotation']), ([], False, 'pending'))
        self.assertEqual(self.svc.intents.find('remove_phones')['stage'], 'requested')      # its own library's task is untouched
        self.assertEqual(len(self.drive.calls), calls)                                      # and nothing reached Drive
        mine = self.restart()
        mine.boot()                                                                         # the library that made it resumes it
        self.assertTrue(mine.running)
        mine.shutdown()

    def test_d14_a_pause_lasts_until_resume(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.svc.turn_off()                                                      # not on: nothing to pause
        self.assertEqual(self.svc.status()['paused_since'], 0)
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.svc, '_publish', lambda stop=None: False):
            self.svc.turn_on()
            self.svc.turn_off()
            since = self.svc.status()['paused_since']
            self.assertGreater(since, 0)
            self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_paused_at', '')), str(since))
            self.svc.turn_off()                                                  # a second pause keeps the first time
            self.assertEqual(self.svc.status()['paused_since'], since)
            self.assertTrue(self.wait(lambda: not self.svc.running))
            app = self.restart()
            app.boot()
            self.assertEqual((app.status()['paused_since'], app.running), (since, False))   # nothing resumes by itself
            old, self.svc = self.svc, app
            old.shutdown()
            self.svc.turn_on()
            self.assertEqual((self.svc.status()['paused_since'], self.writer.read(lambda db: db.get_setting('cloud_paused_at', ''))), (0, ''))
            self.svc.turn_off()

    def test_d9_a_library_backed_up_before_with_no_key_is_not_backed_up_again(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        files = dict(self.drive.files)
        drive_client.private_storage.remove(self.svc.key_path)                  # reinstall: the app home's key is gone, the library stays
        app = self.restart()
        app.boot()
        self.assertTrue(app.status()['key_missing'])
        with self.assertRaisesRegex(drive_client.DriveError, 'no longer has the key'):
            app.turn_on()
        with self.assertRaisesRegex(drive_client.DriveError, 'no longer has the key'):
            app.publish_once()
        self.assertIsNone(mirror.MirrorKey.load(app.key_path))                  # no second key, no second backup
        self.assertEqual(self.drive.files, files)
        self.assertEqual(app.intents.all(), [])

    def has_manifest(self, drive):
        name = self.svc._key().name(mirror.MANIFEST)
        return any(n == name for n, _ in list(drive.files.values()))

    def switch_account(self, delete_old, fail_first_upload):
        """Switch from fred@example.com to bob@example.com: (old drive ids, bob's drive, revoked tokens, what to do next)."""
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'old'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        bob, revoked, seen = AccountDrive('bob@example.com'), [], {'fail': fail_first_upload}
        real_upload = bob.upload

        def upload(*args, **kwargs):
            if seen['fail']:
                seen['fail'] = False
                raise OSError('synthetic: one file did not go through')
            return real_upload(*args, **kwargs)
        self.svc._sign_in = lambda cid, secret, cancel=None, login_hint='': {'refresh_token': 'new', 'access_token': 'n'}
        patches = [mock.patch('core.config.google_client', return_value=('cid', 'sec')),
                   mock.patch.object(drive_client, 'revoke', side_effect=lambda tok: revoked.append(tok.get('refresh_token'))),
                   mock.patch.object(self.svc, '_raw_factory', lambda tok: bob if tok.get('refresh_token') == 'new' else self.drive),
                   mock.patch.object(bob, 'upload', side_effect=upload), mock.patch.object(sync_mod, 'POLL', 0.1)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        old_ids = set(self.drive.files)
        self.svc.switch(delete_old)
        return old_ids, bob, revoked

    def test_a_cancelled_switch_keeps_the_old_backup_and_connect_finishes_it(self):
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'old'})
        self.assertTrue(self.svc._publish())
        old_ids, bob = set(self.drive.files), AccountDrive('bob@example.com')

        def waits(cid, secret, cancel=None):
            cancel.wait(10)
            raise drive_client.SignInCancelled('Synthetic cancellation.')

        self.svc._sign_in = waits
        with mock.patch('core.config.google_client', return_value=('cid', 'sec')), \
                mock.patch.object(drive_client, 'revoke'), mock.patch.object(sync_mod, 'POLL', 0.1), \
                mock.patch.object(self.svc, '_raw_factory', side_effect=lambda tok: bob if tok.get('refresh_token') == 'new' else self.drive):
            self.svc.switch(True)
            self.svc.cancel_sign_in()
            self.assertTrue(self.wait(lambda: not self.svc._signin_thread.is_alive()))
            self.assertEqual(self.svc.intents.find('switch_account')['stage'], 'signing-in')
            self.assertEqual(set(self.drive.files), old_ids)
            self.assertIsNone(drive_client.load_token(self.svc.token_path))
            self.assertEqual(drive_client.load_token(self.svc.previous_token_path)['refresh_token'], 'old')
            self.svc._sign_in = lambda cid, secret, cancel=None: {'refresh_token': 'new'}
            self.svc.connect()
            self.assertTrue(self.wait(lambda: not self.svc.intents.all() and self.svc.status()['state'] == 'idle'))
            self.assertEqual(self.drive.files, {})
            self.assertEqual(read_mirror(bob, self.svc._key())[0]['items'], 6)
            self.svc.turn_off()

    def test_switch_account_deletes_the_old_copy_only_after_the_new_backup_is_complete(self):
        old_ids, bob, revoked = self.switch_account(True, fail_first_upload=True)
        self.assertEqual(self.svc.status()['task']['kind'], 'switch_account')
        self.assertTrue(self.wait(lambda: self.has_manifest(bob) and self.svc.status()['state'] == 'idle'), self.svc.status())
        self.assertTrue(old_ids <= set(self.drive.files))                     # the first backup in bob's account was partial: nothing deleted
        self.assertEqual(self.svc.intents.find('switch_account')['stage'], 'signing-in')
        self.assertTrue(drive_client.load_token(self.svc.previous_token_path))   # the old sign-in is kept until then
        self.assertEqual(revoked, [])
        self.svc.poke(force=True)
        self.assertTrue(self.wait(lambda: not self.svc.intents.all()), self.svc.status())
        self.assertEqual(self.drive.files, {})                                # the old copy went once the new one was complete
        self.assertEqual(read_mirror(bob, self.svc._key())[0]['items'], 6)
        self.assertEqual(revoked, ['old'])
        self.assertIsNone(drive_client.load_token(self.svc.previous_token_path))
        self.assertEqual(self.svc.status()['account'], 'bob@example.com')
        self.svc.turn_off()

    def test_switch_account_keeps_the_old_copy_when_not_asked_to_delete_it(self):
        old_ids, bob, revoked = self.switch_account(False, fail_first_upload=False)
        self.assertEqual(revoked, ['old'])                                    # the old sign-in is revoked at once
        self.assertTrue(self.wait(lambda: not self.svc.intents.all() and self.has_manifest(bob) and self.svc.status()['state'] == 'idle'),
                        self.svc.status())
        self.assertTrue(old_ids <= set(self.drive.files))
        self.assertEqual(read_mirror(bob, self.svc._key())[0]['items'], 6)
        self.svc.turn_off()

    def test_reset_backup_deletes_the_old_backup_only_after_the_new_one_is_complete(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        old_key, old_ids = self.svc._key(), set(self.drive.files)
        real_upload, seen = self.drive.upload, {'fail': True}

        def upload(*args, **kwargs):
            if seen['fail']:
                seen['fail'] = False
                raise OSError('synthetic: one file did not go through')
            return real_upload(*args, **kwargs)
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(self.drive, 'upload', side_effect=upload):
            self.svc.reset_backup()
            self.assertNotEqual(self.svc._key().master, old_key.master)
            self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_upload', '')), 'on')
            self.assertTrue(self.wait(lambda: self.svc.status()['state'] == 'idle'), self.svc.status())
            self.assertTrue(old_ids <= set(self.drive.files))                 # a partial new backup deletes nothing
            self.assertEqual(self.svc.intents.find('reset_backup')['stage'], 'backing-up')
            self.svc.poke(force=True)
            self.assertTrue(self.wait(lambda: not self.svc.intents.all()), self.svc.status())
        self.assertFalse(old_ids & set(self.drive.files))                     # then the old one is gone
        self.assertEqual(read_mirror(self.drive, self.svc._key())[0]['items'], 6)
        self.svc.turn_off()

    def failing_deletes(self, drive, count):
        """The next `count` deletes on `drive` fail like a busy Google: the cleanup of an old copy stops part way."""
        real, left = drive.delete, {'n': count}

        def delete(file_id):
            if left['n']:
                left['n'] -= 1
                raise drive_client.DriveError('synthetic: Google is busy', 503)
            return real(file_id)
        patch = mock.patch.object(drive, 'delete', side_effect=delete)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_switch_cleanup_that_failed_is_taken_up_again_by_the_next_complete_publish(self):
        self.failing_deletes(self.drive, 1)
        old_ids, bob, revoked = self.switch_account(True, fail_first_upload=False)
        self.assertTrue(self.wait(lambda: (self.svc.intents.find('switch_account') or {}).get('stage') == 'cleanup'
                                  and self.svc.status()['state'] == 'idle'), self.svc.status())
        self.assertTrue(old_ids <= set(self.drive.files))                     # the delete failed: the old copy and its sign-in are still here
        self.assertTrue(drive_client.load_token(self.svc.previous_token_path))
        self.assertEqual(revoked, [])
        self.svc.poke(force=True)
        self.assertTrue(self.wait(lambda: not self.svc.intents.all()), self.svc.status())
        self.assertEqual(self.drive.files, {})
        self.assertEqual(revoked, ['old'])
        self.assertIsNone(drive_client.load_token(self.svc.previous_token_path))
        self.svc.turn_off()

    def test_a_reset_cleanup_that_failed_is_taken_up_again_by_the_next_complete_publish(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        old_ids = set(self.drive.files)
        self.failing_deletes(self.drive, 1)
        with mock.patch.object(sync_mod, 'POLL', 0.1):
            self.svc.reset_backup()
            self.assertTrue(self.wait(lambda: (self.svc.intents.find('reset_backup') or {}).get('stage') == 'cleanup'
                                      and self.svc.status()['state'] == 'idle'), self.svc.status())
            self.assertTrue(old_ids <= set(self.drive.files))                 # the delete failed: nothing of the old backup is gone
            self.svc.poke(force=True)
            self.assertTrue(self.wait(lambda: not self.svc.intents.all()), self.svc.status())
        self.assertFalse(old_ids & set(self.drive.files))
        self.assertEqual(read_mirror(self.drive, self.svc._key())[0]['items'], 6)
        self.svc.turn_off()

    def test_a_task_that_wants_the_slot_ends_the_export_in_progress(self):
        """S3: `_tick` between upload requests raises ExportInterrupted for a waiting task, once; a one-time backup does not."""
        stop = threading.Event()
        self.svc._next_intake = time.monotonic() + 60
        self.svc._tick(stop)                                                  # nothing waiting: nothing happens
        self.svc.intents.add('one_shot_publish')
        self.svc._tick(stop)
        self.svc.intents.add('enroll', {})
        with self.assertRaises(sync_mod.ExportInterrupted):
            self.svc._tick(stop)
        self.assertTrue(self.svc._force)
        self.svc.intents.update('enroll', stage='uploading')
        self.svc._tick(stop)                                                  # running now: the export is not cut again

    # ── S7, S8 and the facts the Backup & phones page reads (sub-plan 09) ──
    def test_s7_the_upload_reports_files_and_bytes(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        counted = [e for e in self.cloud_events() if e.get('bytes_total')]
        self.assertTrue(counted)
        self.assertTrue(all(e['bytes_done'] <= e['bytes_total'] for e in counted))
        self.assertEqual(counted[-1]['bytes_done'], counted[-1]['bytes_total'])           # the last report is the whole pass
        self.assertGreater(counted[-1]['bytes_total'], 1_000_000)                         # the favourite video is in it
        st = self.svc.status()
        self.assertEqual((st['done'], st['total'], st['bytes_done'], st['bytes_total']), (0, 0, 0, 0))    # idle: no stale counts
        self.svc.intents.add('one_shot_publish')
        self.svc._set(done=3, total=9, bytes_done=5, bytes_total=50)
        self.assertEqual({k: self.svc.status()['task'][k] for k in ('done', 'total', 'bytes_done', 'bytes_total')},
                         {'done': 3, 'total': 9, 'bytes_done': 5, 'bytes_total': 50})
        self.svc._set(done=4, total=9)
        self.assertEqual(self.svc.status()['bytes_total'], 0)                             # files without bytes reset them

    def test_s7_the_removal_names_the_vault_blobs_it_owns_from_the_file_lists_and_reads_none_of_them(self):
        key, grant = self.access_ready()
        mine = [key.content_id(f'note {n}'.encode()) for n in range(5)]
        other = mirror.MirrorKey.generate()
        theirs = [other.content_id(f'other {n}'.encode()) for n in range(40)]
        owned_ids = []
        for cid in mine:
            owned_ids.append(self.drive.put(vault_sync.blob_name(cid), key.seal(vault_sync.blob_logical(cid), b'x')))
        foreign = [self.drive.put(vault_sync.blob_name(cid), other.seal(vault_sync.blob_logical(cid), b'y')) for cid in theirs]
        owned_ids.append(self.drive.put(vault_sync.index_name(key, 'pc'),
                                        key.seal(vault_sync.INDEX_LOGICAL, vault_sync.encode_index({f'n{n}.md': cid for n, cid in enumerate(mine)}, 'pc'))))
        owned_ids.append(self.drive.put(vault_sync.status_name(key), key.seal(vault_sync.STATUS_LOGICAL, b'{}')))
        name, blob = mirror.seal_phone(key, 'pixel', 'Pixel 8', 1_790_000_000_000)
        owned_ids.append(self.drive.put(name, blob))
        self.svc.unpair()
        calls = len(self.drive.calls)
        self.assertTrue(self.svc._publish(), self.svc.status())
        downloaded = {c.split()[1] for c in self.drive.calls[calls:] if c.startswith('download ')}
        self.assertFalse(downloaded & set(foreign))                                       # no blob of anyone is opened to find out whose it is
        self.assertFalse(downloaded & set(owned_ids[:5]))                                 # nor one this key owns: the file list names them
        self.assertEqual(self.svc.status()['rotation'], 'complete')
        for fid in owned_ids:
            self.assertNotIn(fid, self.drive.files)                                       # the old copy is deleted: blobs, list, status, phone record
        for fid in foreign:
            self.assertIn(fid, self.drive.files)                                          # another key's files are never ours to remove

    def test_a17_change_files_this_key_cannot_open_are_downloaded_once_per_session_and_counted(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        gone = mirror.MirrorKey.generate()                                                 # a removed phone's key
        old = self.phone_change(gone, 'https://example.com/from-a-removed-phone', 5000)
        for _ in range(10):
            self.assertFalse(self.svc._intake())
        self.assertEqual(self.drive.calls.count(f'download {old}'), 1)
        self.assertEqual(self.svc.status()['ignored_changes'], 1)
        self.assertFalse(self.writer.read(lambda db: db.item_exists('https://example.com/from-a-removed-phone')))
        self.assertIn(old, self.drive.files)                                               # kept in Drive for recovery, never deleted
        second = self.phone_change(gone, 'https://example.com/another', 6000)
        self.assertFalse(self.svc._intake())
        self.assertEqual((self.drive.calls.count(f'download {old}'), self.drive.calls.count(f'download {second}')), (1, 1))
        self.assertEqual(self.svc.status()['ignored_changes'], 2)
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'signed in again'})   # a new session
        for _ in range(5):
            self.assertFalse(self.svc._intake())
        self.assertEqual((self.drive.calls.count(f'download {old}'), self.drive.calls.count(f'download {second}')), (2, 2))
        self.drive.files.pop(old)                                                          # the user cleaned one up
        self.assertFalse(self.svc._intake())
        self.assertEqual(self.svc.status()['ignored_changes'], 1)

    def test_a17_a_readable_change_is_still_applied_beside_the_ignored_ones(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.phone_change(mirror.MirrorKey.generate(), 'https://example.com/ignored', 5000)
        self.phone_change(self.svc._key(), 'https://example.com/kept', 6000)
        self.assertTrue(self.svc._intake())
        self.assertTrue(self.writer.read(lambda db: db.item_exists('https://example.com/kept')))
        self.assertFalse(self.writer.read(lambda db: db.item_exists('https://example.com/ignored')))
        self.assertEqual(self.svc.status()['ignored_changes'], 1)

    def second_copy(self):
        """The other Brainamon on this data folder: its own cloud folder, key and sign-in, the same library database and Drive."""
        other = sync_mod.SyncService(self.writer, Hub(), self.data, self.root / 'cloud-other', client_factory=lambda tok: self.drive)
        self.addCleanup(other.shutdown)
        return other

    def test_a18_the_other_copy_is_named_and_nothing_suggests_a_restore(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        kept = dict(self.drive.files)
        other = self.second_copy()
        # the recovery guard would answer "restore it": the other copy's key is asked about first
        refuse = drive_client.DriveError('Recovery is configured for this library, but this PC does not hold its key. ' + 'Use Recover a library.')
        with mock.patch.object(other.recovery, 'guard', side_effect=refuse), mock.patch.object(drive_client, 'revoke'):
            drive_client.save_token(other.cloud_dir / 'google_token.json', {'refresh_token': 'r2'})
            mirror.MirrorKey.generate().save(other.key_path)
            for _ in range(2):                                                             # and again after signing out and in
                self.assertFalse(other._publish(threading.Event()))
                st = other.status()
                self.assertEqual((st['error'], st['error_code'], st['error_action']), (sync_mod.KEY_CONFLICT, 'other_copy', 'none'))
                self.assertIn('Another Brainamon on this PC (the installed app)', st['error'])
                for word in ('Restore', 'Recover', 'Reconnect', 'recovery'):
                    self.assertNotIn(word, st['error'])
                self.assertFalse(other._intake())
                other.sign_out()
                drive_client.save_token(other.cloud_dir / 'google_token.json', {'refresh_token': 'r3'})
        self.assertEqual(self.drive.files, kept)                                           # not one file written or deleted
        self.assertEqual(self.writer.read(lambda db: db.get_setting('cloud_epoch', '')), self.svc._key().fingerprint)

    def test_a18_the_frozen_app_names_the_source_copy(self):
        self.assertIn('(the copy run from source)', sync_mod.key_conflict_text(True))
        self.assertIn('(the installed app)', sync_mod.key_conflict_text(False))

    def test_d13_the_phones_own_records_are_read_not_written(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        key = self.svc._key()
        self.assertFalse(self.svc._intake())
        self.assertIsNone(self.svc.status()['phones'])                                     # no phone writes records yet: the page says "Phones read your backup"
        a = self.drive.put(*mirror.seal_phone(key, 'pixel', 'Pixel 8', 1_790_000_100_000))
        self.drive.put(*mirror.seal_phone(key, 'galaxy', ' Galaxy A54 ', 1_790_000_000_000))
        self.drive.put(*mirror.seal_phone(mirror.MirrorKey.generate(), 'old', 'Removed', 1_790_000_200_000))     # another key's: skipped
        name, blob = mirror.seal_phone(key, 'pixel', 'Spoof', 1_790_000_300_000)
        self.drive.put('ph-' + 'f' * 32, blob)                                             # a record under a name that is not its device's: skipped
        before = list(self.drive.files)
        self.assertFalse(self.svc._intake())
        self.assertEqual(self.svc.status()['phones'], [{'device': 'pixel', 'name': 'Pixel 8', 'seen': 1_790_000_100_000},
                                                      {'device': 'galaxy', 'name': 'Galaxy A54', 'seen': 1_790_000_000_000}])
        reads = self.drive.calls.count(f'download {a}')
        for _ in range(5):
            self.assertFalse(self.svc._intake())
        self.assertEqual(self.drive.calls.count(f'download {a}'), reads)                   # each record is read once
        self.assertEqual(list(self.drive.files), before)                                   # read only

    def test_s8_a_recovery_check_that_meets_an_upload_waits_for_a_slot_instead_of_refusing(self):
        recovery = self.svc.recovery
        ready = {'state': 'ready', 'message': 'ok', 'account': 'fred@example.com', 'enrolled': True}
        self.assertTrue(self.svc._publishing.acquire(blocking=False))                       # an upload is running
        try:
            with mock.patch.object(type(self.svc), 'running', new_callable=mock.PropertyMock, return_value=True), \
                    mock.patch.object(recovery, '_check', return_value=ready) as check:
                self.assertEqual(recovery.preflight()['state'], 'queued')
                self.assertEqual(recovery.status()['check']['state'], 'queued')
                check.assert_not_called()                                                    # not now, and the upload is not paused
                self.svc._next_intake = time.monotonic() + 60
                self.svc._tick(threading.Event())                                            # the next gap between upload requests
                check.assert_called_once_with(True)
                self.assertEqual(recovery.status()['check'], ready)
                self.assertFalse(recovery.check_wanted)
        finally:
            self.svc._publishing.release()

    def test_s8_without_an_upload_the_check_answers_at_once(self):
        recovery = self.svc.recovery
        with mock.patch.object(recovery, '_check', return_value={'state': 'ready'}) as check:
            self.assertEqual(recovery.preflight(), {'state': 'ready'})
        check.assert_called_once_with(True)
        self.assertFalse(recovery.check_wanted)

    def test_a_disconnect_that_deletes_the_copy_forgets_the_last_backup(self):
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertGreater(self.svc.status()['last_publish'], 0)
        with mock.patch.object(drive_client, 'revoke'):
            self.svc.sign_out(delete_mirror=False)
            self.assertGreater(self.svc.status()['last_publish'], 0)                         # the copy stays, so does its date
            drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
            self.svc.sign_out(delete_mirror=True)
        self.assertEqual(self.svc.status()['last_publish'], 0)
        self.assertEqual(self.writer.read(lambda db: int(db.get_setting('cloud_last_publish', '0') or 0)), 0)


class RoutesTest(unittest.TestCase):
    def setUp(self):
        from tests.auth_client import TestClient
        from server.app import create_app
        self.root = Path(tempfile.mkdtemp())
        from tests.license_fixture import activate
        activate(self, self.root)
        self.client = TestClient(create_app(data_dir=self.root / 'data', port=18765, web_dist=self.root / 'none',
                                            cards_dir=self.root / 'none', cloud_dir=self.root / 'cloud'),
                                 base_url='http://127.0.0.1:18765')
        self.c = self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cloud_endpoints(self):
        W = {'X-CM': '1'}
        v = self.c.get('/api/cloud').json()
        self.assertEqual((v['on'], v['running'], v['signed_in'], v['options']), (False, False, False, {'videos': 'fav', 'canvases': True}))
        # what the Backup & phones page and the rail read (sub-plan 09)
        for key, empty in (('task', None), ('phones', None), ('bytes_done', 0), ('bytes_total', 0), ('error_at', 0), ('paused_since', 0), ('key_missing', False),
                           ('ignored_changes', 0), ('error_code', ''), ('error_account', '')):
            self.assertEqual(v[key], empty, key)
        r = self.c.get('/api/cloud/recovery').json()
        for key in ('setup_at', 'takeover_ready', 'check', 'file_outdated'):
            self.assertIn(key, r)
        self.assertEqual(r['check'], None)
        self.assertEqual(self.c.put('/api/cloud/options', json={'videos': 'all'}, headers=W).json()['options']['videos'], 'all')
        self.assertEqual(self.c.put('/api/cloud/options', json={'videos': 'some'}, headers=W).status_code, 400)
        self.assertFalse(self.c.put('/api/cloud/options', json={'canvases': False}, headers=W).json()['options']['canvases'])
        self.assertEqual(self.c.post('/api/cloud/publish', headers=W).status_code, 409)
        with mock.patch('core.config.google_client', return_value=('', '')):
            self.assertEqual(self.c.post('/api/cloud/connect', headers=W).status_code, 409)
            self.assertEqual(self.c.post('/api/cloud/switch', headers=W).status_code, 409)
        self.assertEqual(self.c.post('/api/cloud/switch').status_code, 403)       # no X-CM: server/guard.py
        self.assertEqual(self.c.post('/api/cloud/cancel-sign-in', headers=W).json()['state'], 'off')
        self.assertEqual(self.c.post('/api/cloud/cancel-sign-in').status_code, 403)
        self.assertEqual(self.c.post('/api/cloud/vault/now', headers=W).status_code, 409)       # the vault sync is off
        with mock.patch('core.config.google_client', return_value=('', '')):
            self.assertEqual(self.c.post('/api/cloud/vault/connect', headers=W).status_code, 409)
        v = self.c.post('/api/cloud/vault/stop', headers=W).json()
        self.assertEqual((v['vault_running'], v['vault_state'], v['vault']['on']), (False, 'off', False))
        self.assertEqual(self.c.post('/api/cloud/vault/stop').status_code, 403)
        self.assertIsInstance(self.c.get('/api/cloud').json()['seq'], int)
        s = self.c.get('/api/cloud/sizes').json()
        self.assertEqual(s['videos_all'], 0)
        self.assertIn(self.c.post('/api/cloud/stop', headers=W).json()['state'], ('stopping', 'off'))


    def test_disabling_vault_resets_history_after_stop_but_keeps_membership_and_identity(self):
        sync = self.c.app.state.sync
        path = sync.cloud_dir / sync_mod.VAULT_STATE
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {'fp': 'synthetic', 'vault': 'owner-id', 'vault_ids': {'folder': 'owner-id'},
                 'devices': {'phone-1': True}, 'bases': {'phone-1': {'a.md': 'old'}},
                 'cache': {'a.md': [1, 1, 'old']}, 'orphans': {'vb-old': 1}, 'index_sig': 'old'}
        path.write_text(json.dumps(state), encoding='utf-8')
        def stop():
            state['devices']['phone-2'] = False
            path.write_text(json.dumps(state), encoding='utf-8')
        with mock.patch.object(type(sync), 'vault_running', new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(sync, 'turn_vault_off', side_effect=stop):
            r = self.c.put('/api/cloud/options', json={'vault': False}, headers={'X-CM': '1'})
        self.assertEqual(r.status_code, 200, r.text)
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved, {**state, 'bases': {}, 'cache': {}, 'orphans': {}, 'index_sig': ''})
        self.assertEqual(r.json()['vault_members'], ['phone-1', 'phone-2'])
        self.assertIsNone(r.json()['vault_devices'])
        self.assertEqual(self.c.put('/api/cloud/options', json={'vault': True}, headers={'X-CM': '1'}).status_code, 200)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), saved)

    def test_vault_option_allowed_in_owner_mode_and_drop_route(self):
        """Spec 1b decision 6: vault sync can be turned on for an owner vault (the per-round gate decides); Drop
        needs the Drive sign-in; the view carries vault_devices (None before a round)."""
        W = {'X-CM': '1'}
        state = self.c.app.state
        state.writer.call(lambda db: (db.set_setting('obsidian_vault', str(self.root / 'Vault')), db.set_setting('obsidian_mode', 'owner')))
        state.sync.st['vault_devices'] = [{'device': 'stale', 'ok': True}]
        r = self.c.put('/api/cloud/options', json={'vault': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(state.writer.read(lambda db: db.get_setting('cloud_vault', '')), 'on')
        self.assertIsNone(r.json()['vault_devices'])
        self.assertEqual(self.c.post('/api/cloud/vault/drop', json={'device': ''}, headers=W).status_code, 400)
        r = self.c.post('/api/cloud/vault/drop', json={'device': 'p1'}, headers=W)
        self.assertEqual((r.status_code, r.json()['detail']), (409, 'Sign in to Google Drive first.'))
        self.assertEqual(self.c.post('/api/cloud/vault/drop', json={'device': 'p1'}).status_code, 403)     # no X-CM
        self.assertEqual(self.c.put('/api/cloud/options', json={'vault': False}, headers=W).status_code, 200)

if __name__ == '__main__':
    unittest.main()


class DriveClientTest(unittest.TestCase):
    """The REST calls against a scripted fake of Google's endpoints (no network)."""

    def setUp(self):
        self.log = []
        self.store = {}
        self.session_got = bytearray()
        self.drop_once = True

    def test_revoked_refresh_token_requests_sign_in_without_retrying_or_replacing_token(self):
        token = {'refresh_token': 'synthetic-revoked'}
        client = drive_client.DriveClient('synthetic-client', 'synthetic-secret', token)
        response = (400, {}, b'{"error":"invalid_grant","error_description":"Token has been expired or revoked."}')
        with mock.patch.object(drive_client, '_request', return_value=response) as request:
            with self.assertRaises(drive_client.DriveError) as failure:
                client.about()
        self.assertEqual(failure.exception.status, 401)
        self.assertIn('Choose Sign in again', str(failure.exception))       # S1: renewing is Sign in again, never Change account
        self.assertNotIn('Change account', str(failure.exception))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(client.tok, token)

    def test_other_google_configuration_errors_are_not_reported_as_expired_sign_in(self):
        with mock.patch.object(drive_client, '_request', return_value=(400, {}, b'{"error":"invalid_client"}')):
            with self.assertRaises(drive_client.DriveError) as failure:
                drive_client._form(drive_client.TOKEN_URL, {})
        self.assertEqual(failure.exception.status, 400)

    def fake(self, method, url, data=None, headers=None, timeout=None):
        self.log.append((method, url.split('?')[0]))
        if url == drive_client.TOKEN_URL:
            return 200, {}, json.dumps({'access_token': 'A', 'expires_in': 3600}).encode()
        assert headers.get('Authorization') == 'Bearer A' or 'session' in url, headers
        if url.startswith(drive_client.UPLOAD) and 'uploadType=multipart' in url:
            self.assertIn(b'"parents": ["appDataFolder"]', data)
            return 200, {}, b'{"id": "m1"}'
        if url.startswith(drive_client.UPLOAD) and 'uploadType=resumable' in url:
            self.total = int(headers['X-Upload-Content-Length'])
            return 200, {'Location': 'https://upload.example/session'}, b''
        if url == 'https://upload.example/session':
            rng = headers['Content-Range']
            if rng.startswith('bytes */'):
                return 308, ({'Range': f'bytes=0-{len(self.session_got) - 1}'} if self.session_got else {}), b''
            start = int(rng.split(' ')[1].split('-')[0])
            if start == drive_client.CHUNK and self.drop_once:          # the second chunk is lost once
                self.drop_once = False
                raise OSError('connection reset')
            self.assertEqual(start, len(self.session_got))
            self.session_got += data
            if len(self.session_got) == self.total:
                return 200, {}, b'{"id": "r1"}'
            return 308, {'Range': f'bytes=0-{len(self.session_got) - 1}'}, b''
        if url.startswith(drive_client.API + '/files') and method == 'GET':
            self.assertIn('spaces=appDataFolder', url)
            return 200, {}, b'{"files": [{"id": "m1", "name": "x", "size": "3"}]}'
        return 404, {}, b'{"error": {"message": "nope"}}'

    def test_calls(self):
        c = drive_client.DriveClient('cid', 'sec', {'refresh_token': 'R'})
        with mock.patch.object(drive_client, '_request', self.fake), mock.patch.object(drive_client.time, 'sleep'):
            self.assertEqual(c.upload('a', data=b'small'), 'm1')
            big = bytes(range(256)) * (drive_client.CHUNK // 256 * 2 + 7)
            self.assertEqual(c.upload('b', data=big), 'r1')
            self.assertEqual(bytes(self.session_got), big)
            self.assertEqual(c.list(), [{'id': 'm1', 'name': 'x', 'size': 3}])
            with self.assertRaises(drive_client.DriveError) as e:
                c._call('GET', drive_client.API + '/nothing')
            self.assertEqual(e.exception.status, 404)
        self.assertEqual(sum(1 for m, u in self.log if u == drive_client.TOKEN_URL), 1)   # refreshed once, then reused

    def test_a_rate_limit_403_is_retried_and_a_refusal_is_not(self):
        # many uploads at once: Google answers a burst with 403 userRateLimitExceeded, which means try again later
        answers = {'slow': [403, 403, 200], 'no': [403]}
        tried = {'slow': 0, 'no': 0}

        def fake(method, url, data=None, headers=None, timeout=None):
            if url == drive_client.TOKEN_URL:
                return 200, {}, json.dumps({'access_token': 'A', 'expires_in': 3600}).encode()
            k = url.rsplit('/', 1)[1]
            status = answers[k][tried[k]]
            tried[k] += 1
            if status == 200:
                return 200, {}, b'{}'
            reason = 'userRateLimitExceeded' if k == 'slow' else 'insufficientPermissions'
            return 403, {}, json.dumps({'error': {'message': 'm', 'errors': [{'reason': reason}]}}).encode()
        c = drive_client.DriveClient('cid', 'sec', {'refresh_token': 'R'})
        with mock.patch.object(drive_client, '_request', fake), mock.patch.object(drive_client.time, 'sleep') as slept:
            self.assertEqual(c._call('GET', drive_client.API + '/slow')[0], 200)
            with self.assertRaises(drive_client.DriveError) as e:
                c._call('GET', drive_client.API + '/no')
        self.assertEqual((tried['slow'], tried['no'], e.exception.status), (3, 1, 403))
        self.assertTrue(all(0 < a.args[0] <= 2 * drive_client.MAX_DELAY for a in slept.call_args_list))

    def test_sign_in_loopback(self):
        import urllib.parse as up
        import urllib.request as ur

        def browser(url):
            q = dict(up.parse_qsl(up.urlparse(url).query))
            self.assertEqual((q['scope'], q['code_challenge_method']), (drive_client.SCOPE, 'S256'))
            self.assertEqual(q['prompt'], 'select_account consent')      # Connect and Switch both show the chooser
            self.assertTrue(q['redirect_uri'].startswith('http://127.0.0.1:'))
            back = q['redirect_uri'] + '?' + up.urlencode({'code': 'C', 'state': q['state']})
            threading.Thread(target=lambda: ur.urlopen(back, timeout=5).read(), daemon=True).start()

        sent = {}

        def form(url, fields):
            sent.update(fields)
            return {'access_token': 'A', 'refresh_token': 'R', 'expires_in': 3600}
        with mock.patch.object(drive_client, '_form', form):
            tok = drive_client.sign_in('cid', 'sec', open_url=browser, timeout=10)
        self.assertEqual(tok['refresh_token'], 'R')
        self.assertEqual((sent['code'], sent['grant_type']), ('C', 'authorization_code'))
        self.assertGreaterEqual(len(sent['code_verifier']), 43)
        self.assertAlmostEqual(tok['signed_in_at'], time.time(), delta=60)      # when Google last asked the user

    def test_s1_login_hint_is_sent_only_when_given(self):
        import urllib.parse as up
        seen = []
        for hint in ('', 'fred@example.com'):
            with self.assertRaises(drive_client.SignInCancelled):
                drive_client.sign_in('cid', 'sec', open_url=lambda url: seen.append(dict(up.parse_qsl(up.urlparse(url).query))),
                                     timeout=0.05, login_hint=hint)
        self.assertNotIn('login_hint', seen[0])
        self.assertEqual(seen[1]['login_hint'], 'fred@example.com')         # Google's optional parameter, a hint and no constraint
        self.assertEqual(seen[1]['prompt'], 'select_account consent')

    def test_s1_a_refresh_keeps_the_time_of_the_last_sign_in(self):
        tok = {'refresh_token': 'R', 'signed_in_at': 1234.0, 'expires_at': 0}
        client = drive_client.DriveClient('cid', 'sec', tok)
        with mock.patch.object(drive_client, '_form', return_value={'access_token': 'A2', 'expires_in': 3600}):
            self.assertEqual(client._access(), 'A2')
        self.assertEqual((client.tok['refresh_token'], client.tok['signed_in_at']), ('R', 1234.0))

    def test_sign_in_cancel_skips_the_token_exchange(self):
        class Late(threading.Event):
            # not set at the first look, set from then on: Cancel pressed as Google answers
            n = 0

            def is_set(self):
                self.n += 1
                return self.n > 1

        def browser(url):
            import urllib.parse as up
            import urllib.request as ur
            q = dict(up.parse_qsl(up.urlparse(url).query))
            back = q['redirect_uri'] + '?' + up.urlencode({'code': 'C', 'state': q['state']})
            threading.Thread(target=lambda: ur.urlopen(back, timeout=5).read(), daemon=True).start()
        with mock.patch.object(drive_client, '_form', side_effect=AssertionError('token exchange after cancel')):
            with self.assertRaises(drive_client.SignInCancelled):
                drive_client.sign_in('cid', 'sec', open_url=browser, timeout=10, cancel=Late())
