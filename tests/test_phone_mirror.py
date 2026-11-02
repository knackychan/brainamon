"""The phone on the mirror (projects/mobile-app/PLAN.md Phase 4), desktop side: change files from
the phone applied on the Writer (server/intake.py through server/sync.py), the manifest's Drive
ids and `applied`, change files never deleted as strays, the pairing link and Unpair. Drive is the
in-memory fake from test_sync; nothing calls out."""
import base64
import json
import time
import threading
import unittest
from pathlib import Path
from unittest import mock

from library import drive_client, mirror
from library.export_targets import DriveMirrorTarget
from server import intake, sync as sync_mod
from server.store import Writer
from tests import test_phone_js, test_sync
from tests.test_sync import FakeDrive, Hub, Library, read_mirror
from core.db import Database


class ChangeIntakeTest(Library):
    def setUp(self):
        super().setUp()
        from tests.license_fixture import activate
        activate(self, self.root)
        self.db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.cloud = self.root / 'cloud'
        self.drive = FakeDrive()
        self.links = []
        self.hub = Hub()
        self.svc = sync_mod.SyncService(self.writer, self.hub, self.data, self.cloud,
                                        client_factory=lambda tok: self.drive,
                                        on_new_links=lambda ids: self.links.append(ids) or True)
        policy = mock.patch.object(self.svc.recovery, 'guard')
        policy.start()
        self.guard_patch = policy
        self.addCleanup(policy.stop)
        drive_client.save_token(self.cloud / 'google_token.json', {'refresh_token': 'r'})
        self.key = self.svc.mirror_key()
        self.uid = {i: self.writer.read(lambda db, i=i: db.conn.execute('SELECT uid FROM items WHERE id = ?', (i,)).fetchone()[0])
                    for i in self.ids}

    def tearDown(self):
        self.svc.shutdown()
        self.writer.stop()
        self.db = Database(self.data / 'content_manager.db')
        super().tearDown()

    def phone(self, changes, at=None, device='pA', key=None):
        at = at or int(time.time() * 1000)
        name, blob = (key or self.key).seal_change({'format': 1, 'device': device, 'at': at, 'changes': changes})
        self.drive.put(name, blob)
        return name, at

    def item(self, i):
        return self.writer.read(lambda db: dict(db.conn.execute('SELECT * FROM items WHERE id = ?', (i,)).fetchone()))

    def verified_recovery(self):
        from library import recovery
        self.guard_patch.stop()
        kit = self.svc.recovery.enroll('Disposable sync fixture passphrase', 'Disposable sync fixture passphrase')
        self.svc.recovery.verify_kit(recovery.dump(kit).decode())

    def test_intake_during_blocked_upload_and_followup_manifest(self):
        self.verified_recovery()
        entered, release, landed = (threading.Event() for _ in range(3))
        upload, tick = self.drive.upload, self.svc._tick_intake
        results, errors = [], []
        def blocked(name, **kw):
            if name == self.key.name('library/meta.json'):
                entered.set()
                if not release.wait(15):
                    raise AssertionError('upload was not released')
            return upload(name, **kw)
        def observe(stop):
            tick(stop)
            if self.svc._force_manifest:
                landed.set()
        self.drive.upload, self.svc._tick_intake = blocked, observe
        def run():
            try:
                results.append(self.svc._publish())
            except BaseException as e:
                errors.append(e)
        thread = threading.Thread(target=run)
        with mock.patch.object(DriveMirrorTarget, 'TICK_EVERY', .01), mock.patch.object(sync_mod, 'INTAKE', .01), \
                mock.patch.object(sync_mod, 'INTAKE_MAX', .02):
            try:
                thread.start()
                self.assertTrue(entered.wait(5))
                _, at = self.phone([{'op': 'link', 'uid': 'ab' * 16, 'url': 'https://example.invalid/during-upload'}])
                self.svc._look_now = True
                self.assertTrue(landed.wait(8))
                self.assertTrue(thread.is_alive())
                self.assertFalse(release.is_set())
                self.assertTrue(self.svc._force)
                self.assertTrue(self.svc._force_manifest)
            finally:
                release.set()
                thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [True])
        first, first_files = read_mirror(self.drive, self.key)
        self.assertEqual(first['items'], 6)
        self.assertNotIn('pA', first['applied'])
        self.assertNotIn('items/' + 'ab' * 16 + '.json', first_files)
        self.drive.upload = upload
        self.assertTrue(self.svc._publish())
        followup, files = read_mirror(self.drive, self.key)
        self.assertEqual(followup['items'], 7)
        self.assertEqual(followup['applied']['pA'], at)
        self.assertEqual(json.loads(files['items/' + 'ab' * 16 + '.json'])['url'], 'https://example.invalid/during-upload')

    def test_tick_stop_is_enforced_and_receipt_removal_does_not_revoke_intake(self):
        from core import license
        from library.export_targets import ExportStopped
        self.verified_recovery()
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ExportStopped):
            self.svc._tick_intake(stop)
        self.phone([{'op': 'fav', 'uid': self.uid[self.ids[1]], 'on': True}])
        download = self.drive.download
        stop = threading.Event()
        def stop_during_download(fid):
            value = download(fid)
            if mirror.is_change(self.drive.files[fid][0]):
                stop.set()
            return value
        with mock.patch.object(self.drive, 'download', side_effect=stop_during_download):
            with self.assertRaises(ExportStopped):
                self.svc._tick_intake(stop)
        self.assertFalse(self.item(self.ids[1])['favourite'])
        self.assertEqual(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED, '')), '')
        # Receipt removal after download is not an authentication revocation.
        def revoke(fid):
            value = download(fid)
            if mirror.is_change(self.drive.files[fid][0]):
                license.remove()
            return value
        with mock.patch.object(self.drive, 'download', side_effect=revoke):
            self.svc._tick_intake(threading.Event())
        self.assertTrue(self.item(self.ids[1])['favourite'])
        self.assertTrue(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED, '')))
        self.assertFalse(any(mirror.is_change(n) for n, _ in self.drive.files.values()))
        self.assertNotIn('license_required', self.svc.status()['intake_summary'])

    def test_canvas_receipt_survives_publish_and_duplicate_file(self):
        cid, op = 'a' * 32, 'b' * 32
        ch = {'op': 'canvas', 'op_id': op, 'canvas_id': cid, 'at': int(time.time() * 1000),
              'proposal': {'new_name': 'Phone', 'elements': [{'kind': 'text', 'text': 'Keep this'}]},
              'refs': {}, 'sizes': {}}
        self.phone([ch], at=ch['at'])
        self.assertTrue(self.svc._intake())
        receipt = self.writer.read(lambda db: json.loads(db.get_setting(sync_mod.S_CANVAS_RESULTS, '{}'))[op])
        self.assertEqual(receipt['state'], 'applied')
        self.assertIn(('canvas_changed', {'id': cid}), self.hub.events)
        first = (self.data / 'canvases' / f'{cid}.json').read_bytes()
        self.phone([ch], at=ch['at'] + 1)
        self.assertTrue(self.svc._intake())
        self.assertEqual((self.data / 'canvases' / f'{cid}.json').read_bytes(), first)
        self.assertTrue(self.svc._publish())
        man, files = read_mirror(self.drive, self.key)
        self.assertEqual(man['canvas_change'], 1)
        self.assertEqual(man['reader'], mirror.READER)
        self.assertEqual(json.loads(files['canvas-results.json'])[op], receipt)

    def test_phone_reads_the_mirror_reader_the_pc_writes(self):
        # raising READER on the PC without a phone release would leave every phone asking for an update
        src = (Path(__file__).resolve().parents[1] / 'web/src/mobile/source/mirror.ts').read_text(encoding='utf-8')
        self.assertIn(f'export const READER = {mirror.READER}\n', src)

    def test_change_format_matches_and_legacy_files_apply(self):
        src = (Path(__file__).resolve().parents[1] / 'web/src/mobile/mirror/changes.ts').read_text(encoding='utf-8')
        self.assertIn(f'export const CHANGE_FORMAT = {mirror.CHANGE_FORMAT}\n', src)
        for n, fmt in enumerate([None, mirror.CHANGE_FORMAT]):
            doc = {'device': 'legacy', 'at': n + 1, 'changes': []}
            if fmt is not None:
                doc['format'] = fmt
            name, blob = self.key.seal_change(doc)
            self.drive.put(name, blob)
        self.assertTrue(self.svc._intake())
        self.assertEqual(json.loads(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED))), {'legacy': 2})

    def test_held_timestamp_blocks_same_and_later_passes_until_upgrade(self):
        t = int(time.time() * 1000)
        def put(at, fmt, device='pA'):
            doc = {'format': fmt, 'device': device, 'at': at, 'changes': [
                {'op': 'note_append', 'file': 'barrier.md', 'title': 'Barrier', 'name': str(at), 'text': str(at), 'at': at}]}
            name, blob = self.key.seal_change(doc)
            return self.drive.put(name, blob)
        held = put(t, 2)
        equal, later = put(t, 1), put(t + 1, 1)
        put(t - 1, 1)
        put(t, 1, 'pB')
        self.assertTrue(self.svc._intake())
        applied = lambda: json.loads(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED)))
        self.assertEqual(applied(), {'pA': t - 1, 'pB': t})
        self.assertEqual(set(self.drive.files), {held, equal, later})
        last = put(t + 2, 1)
        self.assertFalse(self.svc._intake())
        self.assertEqual(self.drive.calls.count(f'download {held}'), 1)
        self.assertIn('Brainamon update', self.svc.status()['intake_summary'])
        self.assertIn('behind', self.svc.status()['intake_summary'])
        # A fresh service reconstructs the barrier; the upgraded binary can then read it.
        fresh = sync_mod.SyncService(self.writer, self.hub, self.data, self.cloud, client_factory=lambda tok: self.drive)
        try:
            with mock.patch.object(fresh.recovery, 'guard'):
                self.assertFalse(fresh._intake())
                seen, real = [], intake.apply
                def apply(db, doc, out):
                    seen.append(doc['at'])
                    return real(db, doc, out)
                # Restart/upgrade invalidates the memory-only cache.
                fresh._held.clear()
                with mock.patch.object(mirror, 'CHANGE_FORMAT', 2), mock.patch.object(intake, 'apply', side_effect=apply), \
                        mock.patch.object(self.drive, 'delete', side_effect=drive_client.DriveError('retry', 500)):
                    self.assertTrue(fresh._intake())
                    self.assertEqual(seen, [t, t + 1, t + 2])
                    self.assertEqual(applied()['pA'], t + 2)
                    self.assertTrue(fresh._intake())
                    self.assertEqual(seen, [t, t + 1, t + 2])
                with mock.patch.object(mirror, 'CHANGE_FORMAT', 2):
                    fresh._intake()
                self.assertEqual(self.drive.files, {})
        finally:
            fresh.shutdown()

    def test_invalid_envelopes_are_retained_and_cache_tracks_listing_and_context(self):
        for fmt in [True, False, 0, -1, 1.5, '2', None]:
            with self.subTest(format=fmt):
                name, blob = self.key.seal_change({'format': fmt, 'device': 'pA', 'at': 10, 'changes': []})
                fid = self.drive.put(name, blob)
                self.phone([], at=11)
                self.assertFalse(self.svc._intake())
                self.assertIn('invalid', self.svc.status()['intake_summary'])
                self.assertIn(fid, self.drive.files)
                self.assertEqual(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED, '')), '')
                self.drive.delete(fid)
                self.assertTrue(self.svc._intake())
                self.writer.call(lambda db: db.set_setting(sync_mod.S_APPLIED, ''))
        for device, at in [('', 10), (3, 10), ('pA', True), ('pA', 0), ('pA', 1.5)]:
            name, blob = self.key.seal_change({'format': 2, 'device': device, 'at': at, 'changes': []})
            fid = self.drive.put(name, blob)
            self.phone([], at=9, device='pB')
            self.assertFalse(self.svc._intake())
            self.assertEqual(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED, '')), '')
            self.drive.delete(fid)
            self.assertTrue(self.svc._intake())
            self.writer.call(lambda db: db.set_setting(sync_mod.S_APPLIED, ''))
        name, blob = self.key.seal_change({'format': 2, 'device': 'pA', 'at': 10, 'changes': []})
        fid = self.drive.put(name, blob)
        self.svc._intake()
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'other'})
        self.svc._intake()
        self.assertEqual(self.drive.calls.count(f'download {fid}'), 2)
        new = mirror.MirrorKey.generate()
        new.save(self.svc.key_path)
        self.svc._intake()
        self.assertEqual(self.drive.calls.count(f'download {fid}'), 3)
        self.assertEqual(self.svc._held, {})
        self.drive.delete(fid)
        self.svc._intake()
        self.assertNotIn('update', self.svc.status()['intake_summary'])

    def test_blocked_device_without_timestamp_and_normalized_device_are_deferred(self):
        device = 'p' * 45
        name, blob = self.key.seal_change({'format': 2, 'device': device, 'at': 10, 'changes': []})
        held = self.drive.put(name, blob)
        for at in (None, 0, True, '9'):
            name, blob = self.key.seal_change({'format': 1, 'device': device[:40], 'at': at, 'changes': []})
            self.drive.put(name, blob)
        self.phone([], at=11, device='pB')
        self.assertTrue(self.svc._intake())
        self.assertEqual(json.loads(self.writer.read(lambda db: db.get_setting(sync_mod.S_APPLIED))), {'pB': 11})
        self.assertEqual(len(self.drive.files), 5)
        self.drive.delete(held)
        self.svc._intake()
        self.assertEqual(self.svc._held, {})
        self.assertNotIn('behind', self.svc.status()['intake_summary'])

    def test_refused_canvas_receipt_survives_with_unrelated_change(self):
        cid, op = 'a' * 32, 'b' * 32
        at = int(time.time() * 1000)
        ch = {'op': 'canvas', 'op_id': op, 'canvas_id': cid, 'at': at,
              'proposal': {'canvas_id': cid, 'elements': [{'kind': 'text', 'text': 'Never applied'}]},
              'refs': {}, 'sizes': {}}
        fav = {'op': 'fav', 'uid': self.uid[self.ids[0]], 'on': True, 'at': at}
        self.phone([ch, fav], at=at)
        self.assertTrue(self.svc._intake())
        self.assertFalse((self.data / 'canvases' / f'{cid}.json').exists())
        self.assertTrue(self.item(self.ids[0])['favourite'])
        self.assertTrue(self.svc._publish())
        man, files = read_mirror(self.drive, self.key)
        receipt = json.loads(files['canvas-results.json'])[op]
        self.assertEqual((receipt['state'], receipt['canvas_id']), ('refused', cid))
        self.assertIn('missing', receipt['reason'])
        self.assertEqual(man['applied']['pA'], at)

    def test_approved_category_batch_is_atomic(self):
        a, b = self.ids[:2]
        self.writer.call(lambda db: (db.add_category('FITNESS', '#ff0000'), db.add_category('WORK', '#0000ff')))
        old_a, old_b = self.item(a)['category'], self.item(b)['category']
        good = {'op': 'category_batch', 'entries': [
            {'uid': self.uid[a], 'from': old_a, 'category': 'FITNESS'},
            {'uid': self.uid[b], 'from': old_b, 'category': 'WORK'},
        ]}
        bad = {'op': 'category_batch', 'entries': [
            {'uid': self.uid[a], 'from': old_a, 'category': 'FITNESS'},
            {'uid': self.uid[b], 'from': 'stale category', 'category': 'WORK'},
        ]}
        result = self.writer.call(lambda db: intake.apply(db, {'device': 'test', 'changes': [bad]}))
        self.assertEqual(result.skipped, 1)
        self.assertEqual((self.item(a)['category'], self.item(b)['category']), (old_a, old_b))
        result = self.writer.call(lambda db: intake.apply(db, {'device': 'test', 'changes': [good]}))
        self.assertEqual(result.edits, 2)
        self.assertEqual((self.item(a)['category'], self.item(b)['category']), ('FITNESS', 'WORK'))

    def test_links_favourites_edits_apply_and_files_go(self):
        now = int(time.time() * 1000) + 5000
        new_uid = 'ab' * 16
        name, at = self.phone([
            {'op': 'link', 'uid': new_uid, 'url': 'Look https://www.instagram.com/reel/NEW1/?igsh=zz', 'note': 'for knees', 'category': 'FITNESS', 'at': now},
            {'op': 'link', 'uid': 'cd' * 16, 'url': 'https://www.instagram.com/reel/r1/?igsh=dup', 'at': now},
            {'op': 'fav', 'uid': self.uid[self.ids[2]], 'on': True, 'at': now},
            {'op': 'edit', 'uid': self.uid[self.ids[3]], 'fields': {'tags': 'knee, phone'}, 'was': {'tags': 'knee, drill'}, 'at': now},
            {'op': 'edit', 'uid': new_uid, 'fields': {'tags': 'later'}, 'at': now},
        ], at=now)
        self.assertTrue(self.svc._intake())
        self.assertEqual([n for n, _ in self.drive.files.values() if mirror.is_change(n)], [])     # applied, deleted
        new = self.writer.read(lambda db: dict(db.conn.execute('SELECT * FROM items WHERE uid = ?', (new_uid,)).fetchone()))
        self.assertEqual((new['url'], new['notes'], new['category'], new['tags'], new['source']),
                         ('https://www.instagram.com/reel/NEW1/', 'for knees', 'FITNESS', 'later', 'phone'))
        self.assertEqual(new['created'], now)
        self.assertEqual(self.links, [[new['id']]])                      # Fetch thumbnails on the new link
        self.assertEqual(self.writer.read(lambda db: db.conn.execute("SELECT COUNT(*) FROM items WHERE url LIKE '%reel/r1/%'").fetchone()[0]), 1)
        self.assertTrue(self.item(self.ids[2])['favourite'])
        self.assertEqual(self.item(self.ids[3])['tags'], 'knee, phone')
        self.assertEqual(json.loads(self.writer.read(lambda db: db.get_setting('cloud_applied', ''))), {'pA': at})
        self.assertEqual(self.svc.status()['intake_summary'], '1 link(s) saved, 1 duplicate link(s), 1 favourite(s), 2 edit(s)')
        kinds = [k for k, _ in self.hub.events]
        self.assertIn('items_changed', kinds)

    def test_an_edit_to_a_duplicate_link_in_a_later_file_finds_the_item(self):
        """The phone saved a link the PC already had (its copy did not show it yet), sent it, then
        favourited the card: the favourite reaches the library's item."""
        t = int(time.time() * 1000) + 5000
        phone_uid = 'ef' * 16
        self.phone([{'op': 'link', 'uid': phone_uid, 'url': 'https://www.instagram.com/reel/r1/?igsh=x', 'at': t}], at=t)
        self.svc._intake()
        self.phone([{'op': 'fav', 'uid': phone_uid, 'on': True, 'at': t + 1}], at=t + 1)
        self.svc._intake()
        fav = self.writer.read(lambda db: db.conn.execute("SELECT favourite FROM items WHERE url LIKE '%reel/r1/%'").fetchone()[0])
        self.assertTrue(fav)

    def test_newest_wins_per_field(self):
        i = self.ids[4]
        old = int(time.time() * 1000) - 60_000
        self.writer.call(lambda db: db.update_item(i, {'tags': 'pc edit'}))       # the PC changed it after the phone read it
        self.phone([{'op': 'edit', 'uid': self.uid[i], 'fields': {'tags': 'phone edit', 'category': 'FITNESS'},
                     'was': {'tags': 'knee, drill', 'category': 'INTERESTING'}, 'at': old}], at=old)
        self.svc._intake()
        it = self.item(i)
        self.assertEqual(it['tags'], 'pc edit')            # the PC's newer value stays
        self.assertEqual(it['category'], 'FITNESS')        # the PC left this one alone: the phone's goes in
        later = int(time.time() * 1000) + 60_000
        self.phone([{'op': 'edit', 'uid': self.uid[i], 'fields': {'tags': 'phone again'}, 'was': {'tags': 'stale'}, 'at': later}], at=later)
        self.svc._intake()
        self.assertEqual(self.item(i)['tags'], 'phone again')     # newer than the PC's write: wins

    def test_notes_written_and_a_newer_pc_note_is_kept(self):
        t = int(time.time() * 1000) + 1000
        self.phone([{'op': 'note', 'file': 'gym-ideas-a1b2c3.md', 'title': 'Gym ideas', 'category': 'Fitness', 'body': 'Squat day', 'was': '', 'at': t}], at=t)
        self.svc._intake()
        p = self.data / 'notes' / 'gym-ideas-a1b2c3.md'
        text = p.read_text(encoding='utf-8')
        self.assertIn('kind: personal', text)
        self.assertIn('Squat day', text)
        self.assertTrue(self.writer.read(lambda db: db.conn.execute("SELECT COUNT(*) FROM notes_fts WHERE notes_fts MATCH 'squat'").fetchone()[0]))
        # the PC edits it; a phone edit made before that, from the old version, lands beside it
        from knowledge import my_notes
        my_notes.save_note(p, 'Gym ideas', 'Fitness', 'PC version')
        self.phone([{'op': 'note', 'file': 'gym-ideas-a1b2c3.md', 'title': 'Gym ideas', 'category': 'Fitness', 'body': 'Phone version',
                     'was': 'old-stamp', 'at': t - 120_000}], device='pB')
        self.svc._intake()
        self.assertIn('PC version', p.read_text(encoding='utf-8'))
        copies = [q for q in (self.data / 'notes').glob('*.md') if 'Phone version' in q.read_text(encoding='utf-8')]
        self.assertEqual(len(copies), 1)
        self.assertIn('(from phone)', copies[0].read_text(encoding='utf-8'))
        # a Knowledge note (not a My Note) is never overwritten from the phone
        self.phone([{'op': 'note', 'file': 'knees.md', 'title': 'Knees', 'body': 'phone text', 'at': t + 10}], at=t + 10)
        self.svc._intake()
        self.assertIn('Secret note body', (self.data / 'notes' / 'knees.md').read_text(encoding='utf-8'))

    def test_note_stamps_carry_and_a_body_edit_keeps_them(self):
        """The phone's `note` change carries the plan 01 stamps, intake applies them; a later
        body-only change (no `stamps`) keeps the stamps line byte-identical, and `note_delete`
        removes a personal note."""
        from core import note_format
        from knowledge import knowledge
        stamps = [{'k': 'sun', 'at': 'top', 'x': -4, 'y': 0, 's': 3, 'c': 'indigo', 'r': 0}]
        t = int(time.time() * 1000) + 60_000
        self.phone([{'op': 'note', 'file': 'stamped-aaaaaa.md', 'title': 'Stamped', 'category': 'General',
                     'body': '# Hi\n\ntext', 'was': '', 'stamps': stamps, 'at': t}], at=t)
        self.svc._intake()
        p = self.data / 'notes' / 'stamped-aaaaaa.md'
        meta, _ = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        self.assertEqual(note_format.parse_stamps(meta.get(note_format.KEY)), stamps)
        line = meta.get(note_format.KEY)
        self.phone([{'op': 'note', 'file': 'stamped-aaaaaa.md', 'title': 'Stamped', 'category': 'General',
                     'body': 'new body', 'was': '', 'at': t + 1}], at=t + 1, device='pB')
        self.svc._intake()
        meta2, _ = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        self.assertEqual(meta2.get(note_format.KEY), line)
        self.phone([{'op': 'note_delete', 'file': 'stamped-aaaaaa.md', 'at': t + 2}], at=t + 2, device='pC')
        self.svc._intake()
        self.assertFalse(p.exists())

    def test_phone_chats_answers_and_syntheses(self):
        """Phase 5: a chat asked on the phone, Save as note on its answer, a synthesized note, a
        synthesis queued for the PC (started when no job runs), and a chat the PC went on with."""
        from knowledge.ask_chats import AskChatStore
        started = []
        self.svc.on_synth = lambda topic, ids: started.append((topic, ids)) or len(started) > 1   # busy once
        t = int(time.time() * 1000)
        hist = [{'role': 'user', 'content': 'knee?'}, {'role': 'assistant', 'content': f'Try [id {self.ids[0]}].'}]
        self.phone([
            {'op': 'chat', 'slug': 'knee-a1b2', 'name': 'knee?', 'created': '2026-10-11T09:00:00', 'history': hist,
             'source_ids': [self.ids[0]], 'options': {'provider': 'openai', 'model_id': 'gpt-6-luna'}, 'was': '', 'at': t},
            {'op': 'answer', 'md': f'# Knee plan\n\nTry [id {self.ids[0]}].', 'ids': [self.ids[0]], 'at': t},
            {'op': 'synth', 'topic': 'Knee prehab', 'sources': [self.ids[0], self.ids[1]], 'body': '## Knee\n\nText', 'at': t},
            {'op': 'synth_queue', 'topic': 'Everything knees', 'ids': list(self.ids), 'at': t},
        ], at=t)
        self.svc._intake()
        store = AskChatStore(self.data)
        chat = store.load('knee-a1b2')
        self.assertEqual(chat['history'], hist)
        self.assertEqual(chat['options']['model_id'], 'gpt-6-luna')
        notes = {q.name: q.read_text(encoding='utf-8') for q in (self.data / 'notes').glob('*.md')}
        self.assertIn('topic: Knee plan', notes['knee-plan.md'])
        self.assertIn(f'sources: {self.ids[0]},{self.ids[1]}', notes['knee-prehab.md'])
        self.assertTrue(self.writer.read(lambda db: db.conn.execute("SELECT COUNT(*) FROM notes_fts WHERE notes_fts MATCH 'prehab'").fetchone()[0]))
        self.assertEqual(started, [])
        self.svc._retry_synth()                       # a job is running: stays queued
        self.svc._retry_synth()
        self.assertEqual(started, [('Everything knees', list(self.ids))] * 2)
        self.assertEqual(self.writer.read(sync_mod._synth_queue), [])
        # the PC went on with the chat after the phone read it: the phone's copy lands beside it
        store.save('knee-a1b2', dict(chat, history=hist + [{'role': 'user', 'content': 'pc turn'}]))
        f = self.data / 'ask_chats' / 'knee-a1b2.json'
        f.write_text(json.dumps(dict(json.loads(f.read_text(encoding='utf-8')), updated='2099-01-01T00:00:00')), encoding='utf-8')
        self.phone([{'op': 'chat', 'slug': 'knee-a1b2', 'name': 'knee?', 'history': hist[:1], 'was': chat['updated'],
                     'at': t - 60_000}], device='pB')
        self.svc._intake()
        self.assertEqual(len(store.load('knee-a1b2')['history']), 3)
        self.assertEqual([c['name'] for c in store.list_chats() if 'phone' in c['name']], ['knee? (from phone)'])

    def test_phone_item_delete(self):
        """An item deleted on the phone with `pc` goes from the PC library with its folder; "only on
        this phone" (pc false or missing) and an unknown uid leave the library alone."""
        gone, kept, kept2 = self.ids[0], self.ids[1], self.ids[2]
        folder = self.data / 'items' / str(gone)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'thumb.jpg').write_bytes(b'x')
        t = int(time.time() * 1000)
        self.phone([
            {'op': 'delete', 'uid': self.uid[gone], 'pc': True, 'at': t},
            {'op': 'delete', 'uid': self.uid[kept], 'pc': False, 'at': t},
            {'op': 'delete', 'uid': self.uid[kept2], 'at': t},
            {'op': 'delete', 'uid': 'ef' * 16, 'pc': True, 'at': t},
        ], at=t)
        self.assertTrue(self.svc._intake())
        ids = self.writer.read(lambda db: [r[0] for r in db.conn.execute('SELECT id FROM items')])
        self.assertNotIn(gone, ids)
        self.assertIn(kept, ids)
        self.assertIn(kept2, ids)
        self.assertFalse(folder.exists())
        self.assertEqual(self.svc.status()['intake_summary'], '1 item(s) deleted')

    def test_phone_chat_delete(self):
        """A chat deleted on the phone goes on the PC; one the PC went on with (more turns than the
        phone saw) stays; an unknown or malformed slug deletes nothing; the page hears which went."""
        from knowledge.ask_chats import AskChatStore
        store = AskChatStore(self.data)
        hist = [{'role': 'user', 'content': 'knee?'}, {'role': 'assistant', 'content': 'Rest.'}]
        for slug in ('knee-a1b2', 'hip-c3d4', 'back-e5f6'):
            store.save(slug, {'name': slug, 'history': hist})
        store.save('hip-c3d4', {'name': 'hip-c3d4', 'history': hist + [{'role': 'user', 'content': 'pc turn'}]})
        t = int(time.time() * 1000)
        self.phone([
            {'op': 'chat_delete', 'slug': 'knee-a1b2', 'turns': 2, 'at': t},
            {'op': 'chat_delete', 'slug': 'hip-c3d4', 'turns': 2, 'at': t},      # the PC asked again since
            {'op': 'chat_delete', 'slug': 'gone-0000', 'turns': 0, 'at': t},
            {'op': 'chat_delete', 'slug': '../back-e5f6', 'turns': 0, 'at': t},
        ], at=t)
        self.svc._intake()
        self.assertEqual(sorted(c['slug'] for c in store.list_chats()), ['back-e5f6', 'hip-c3d4'])
        self.assertIn(('chats_changed', {'deleted': ['knee-a1b2']}), self.hub.events)
        self.assertIn('1 chat(s) deleted', self.svc.status()['intake_summary'])
        self.assertIn('1 newer PC value(s) kept', self.svc.status()['intake_summary'])
        # a chat asked on the phone and deleted there before it was sent: both in one file
        self.phone([{'op': 'chat', 'slug': 'neck-0a0b', 'name': 'neck?', 'history': hist, 'was': '', 'at': t + 1},
                    {'op': 'chat_delete', 'slug': 'neck-0a0b', 'turns': 2, 'at': t + 2}], at=t + 2)
        self.svc._intake()
        self.assertIsNone(store.load('neck-0a0b'))

    def test_a_file_applied_twice_or_sealed_with_an_old_key_is_dropped(self):
        t = int(time.time() * 1000)
        doc = {'format': 1, 'device': 'pB', 'at': t, 'changes': [{'op': 'note', 'file': 'once-aaaaaa.md', 'title': 'Once', 'body': 'x', 'at': t}]}
        n1, b1 = self.key.seal_change(doc)
        self.drive.put(n1, b1)
        self.svc._intake()
        self.drive.put(n1, b1)                                 # its delete did not go through
        self.svc._intake()
        self.assertEqual(len(list((self.data / 'notes').glob('once*.md'))), 1)
        self.phone([{'op': 'fav', 'uid': self.uid[self.ids[5]], 'on': True, 'at': t}], key=mirror.MirrorKey.generate())
        self.svc._intake()
        self.assertFalse(self.item(self.ids[5])['favourite'])
        self.assertEqual(len([n for n, _ in self.drive.files.values() if mirror.is_change(n)]), 1)  # unknown keys retained

    def test_unreadable_changes_are_skipped_and_the_rest_land(self):
        """A phone on another version sends fields the PC cannot read: those changes are skipped,
        the others land, the file is recorded and deleted, and a second look applies nothing again."""
        t = int(time.time() * 1000) + 5000
        name, at = self.phone([
            {'op': 'edit', 'uid': self.uid[self.ids[1]], 'fields': ['tags', 'x'], 'at': t},
            {'op': 'link', 'uid': 'ab' * 16, 'url': 'https://www.instagram.com/reel/BAD1/', 'at': 'soon'},
            {'op': 'note', 'file': 'bad-aaaaaa.md', 'title': {'a': 1}, 'body': ['x'], 'at': t},
            {'op': 'chat', 'slug': 'odd-chat', 'history': 'not a list', 'options': 7, 'at': t},
            {'op': 'answer', 'md': '# Kept once\n\nText', 'ids': 'nope', 'at': t},
            'not a change',
            {'op': 'fav', 'uid': self.uid[self.ids[2]], 'on': True, 'at': t},
        ], at=t)
        with mock.patch.object(intake, '_note', side_effect=RuntimeError('boom')):
            self.assertTrue(self.svc._intake())
        self.assertTrue(self.item(self.ids[2])['favourite'])                     # after the bad ones
        self.assertEqual(self.writer.read(lambda db: db.conn.execute("SELECT COUNT(*) FROM items WHERE url LIKE '%BAD1%'").fetchone()[0]), 1)
        self.assertEqual(json.loads(self.writer.read(lambda db: db.get_setting('cloud_applied', ''))), {'pA': at})
        self.assertEqual([n for n, _ in self.drive.files.values() if mirror.is_change(n)], [])
        self.assertIn('2 unreadable change(s) skipped', self.svc.status()['intake_summary'])
        self.drive.put(name, self.key.seal_change({'format': 1, 'device': 'pA', 'at': at, 'changes': []})[1])
        self.svc._intake()
        self.assertEqual(len(list((self.data / 'notes').glob('kept-once*.md'))), 1)

    def test_the_intake_sweeps_ai_keys_no_phone_collected(self):
        _, _, live, blob = mirror.pair_drop({'openai': 'sk-x'})
        _, _, old, _ = mirror.pair_drop({'openai': 'sk-y'}, now=time.time() - mirror.PAIR_TTL - 5)
        self.drive.put(live, blob)
        self.drive.put(old, b'old')
        with mock.patch.object(mirror.time, 'time', return_value=time.time() - mirror.PAIR_TTL - 5):
            self.svc.send_keys({'openai': 'synthetic-owned'})
        self.assertFalse(self.svc._intake())
        self.assertEqual([n for n, _ in self.drive.files.values() if mirror.is_pair_drop(n)], [live, old])

    def test_a_file_that_fails_does_not_stop_the_next(self):
        t = int(time.time() * 1000)
        self.phone([{'op': 'fav', 'uid': self.uid[self.ids[1]], 'on': True, 'at': t}], at=t, device='pA')
        self.phone([{'op': 'fav', 'uid': self.uid[self.ids[2]], 'on': True, 'at': t + 1}], at=t + 1, device='pB')
        real = intake.apply

        def first_fails(db, doc, out=None):
            if doc['device'] == 'pA':
                raise RuntimeError('boom')
            return real(db, doc, out)
        with mock.patch.object(intake, 'apply', side_effect=first_fails):
            self.svc._intake()
        self.assertFalse(self.item(self.ids[1])['favourite'])
        self.assertTrue(self.item(self.ids[2])['favourite'])
        self.assertEqual(json.loads(self.writer.read(lambda db: db.get_setting('cloud_applied', ''))), {'pA': t, 'pB': t + 1})
        self.assertEqual([n for n, _ in self.drive.files.values() if mirror.is_change(n)], [])

    def test_the_sync_thread_outlives_a_failing_intake(self):
        calls = []

        def broken(stop=None):
            calls.append(1)
            raise ValueError('a phone from the future')
        self.svc._intake = broken
        with mock.patch.object(sync_mod, 'POLL', 0.05), mock.patch.object(sync_mod, 'INTAKE', 0):
            self.svc.turn_on()
            end = time.time() + 10
            while time.time() < end and len(calls) < 3:
                time.sleep(0.05)
            self.assertGreaterEqual(len(calls), 3)
            self.assertTrue(self.svc.running)
            self.assertIn('a phone from the future', self.svc.status()['intake_summary'])

    def test_quiet_phones_are_looked_for_less_often_until_publish_now(self):
        from types import SimpleNamespace
        looks, now, poked = [], [0.0], []
        stop = threading.Event()

        def look(stop=None):
            looks.append(now[0])
            if poked:
                stop.set()
            return False

        def wait(seconds):
            now[0] += seconds
            if len(looks) == 4 and not poked:
                poked.append(now[0])
                self.svc.poke(force=True)
            if now[0] > 2:
                stop.set()
        wake = SimpleNamespace(wait=wait, clear=lambda: None, set=lambda: None)
        clock = SimpleNamespace(monotonic=lambda: now[0], time=time.time)
        self.svc._intake = look
        # Run the real scheduling loop on a virtual clock; disk/signing speed is irrelevant.
        with mock.patch.object(sync_mod, 'POLL', .02), mock.patch.object(sync_mod, 'INTAKE', .1), \
                mock.patch.object(sync_mod, 'INTAKE_MAX', .4), mock.patch.object(sync_mod, 'time', clock), \
                mock.patch.object(self.svc, '_wake', wake), mock.patch.object(self.svc, '_publish', return_value=True), \
                mock.patch.object(type(self.svc), 'running', new_callable=mock.PropertyMock, return_value=True):
            self.svc._loop(stop)
        gaps = [b - a for a, b in zip(looks, looks[1:4])]
        self.assertEqual(len(looks), 5)
        self.assertAlmostEqual(gaps[0], .2, delta=.021)
        self.assertAlmostEqual(gaps[1], .4, delta=.021)
        self.assertLessEqual(max(gaps), .421)
        self.assertLessEqual(looks[-1] - poked[0], .021)

    @unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
    def test_offline_note_deletes_keep_one_per_file(self):
        """plans/07-phone-editor-review.md #2: deletes of two personal notes queued offline are two
        changes (keyed by file), kept in storage and both in the upload; a second delete of the same
        file is folded into the first. Intake then removes both notes."""
        t = int(time.time() * 1000) + 60_000
        for i, f in enumerate(('first-aaaaaa.md', 'second-bbbbbb.md')):
            self.phone([{'op': 'note', 'file': f, 'title': f, 'category': 'General', 'body': 'text', 'was': '', 'at': t + i}],
                       at=t + i, device=f'pN{i}')
        self.svc._intake()
        paths = [self.data / 'notes' / f for f in ('first-aaaaaa.md', 'second-bbbbbb.md')]
        self.assertTrue(all(p.exists() for p in paths))
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            // an in-memory IndexedDB, just what web/src/mobile/store.ts uses
            const stores = {}
            const req = v => { const r = { result: v }; setTimeout(() => r.onsuccess?.()); return r }
            const keyOf = (s, v, k) => (s.opts?.autoIncrement && v[s.opts.keyPath] === undefined ? ++s.n : s.opts?.keyPath ? v[s.opts.keyPath] : k)
            globalThis.indexedDB = { open() {
              const d = {
                objectStoreNames: { contains: n => n in stores },
                createObjectStore(n, opts) { stores[n] = { opts, m: new Map(), n: 0 } },
                transaction(n) {
                  const s = stores[n], t = { objectStore: () => ({
                    get: k => req(structuredClone(s.m.get(k))),
                    getAll: () => req([...s.m.values()].map(v => structuredClone(v))),
                    getAllKeys: () => req([...s.m.keys()]),
                    add(v, k) { k = keyOf(s, v, k); s.m.set(k, structuredClone(s.opts?.keyPath ? { ...v, [s.opts.keyPath]: k } : v)); return req(k) },
                    put(v, k) { k = keyOf(s, v, k); s.m.set(k, structuredClone(v)); return req(k) },
                    delete(k) { s.m.delete(k); return req(undefined) },
                    clear() { s.m.clear(); return req(undefined) },
                  }) }
                  setTimeout(() => setTimeout(() => t.oncomplete?.()))
                  return t
                },
              }
              const r = { result: d }
              setTimeout(() => { r.onupgradeneeded?.(); r.onsuccess?.() })
              return r
            } }
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes()
            await c.add({ op: 'note_delete', file: 'first-aaaaaa.md' })
            await c.add({ op: 'note_delete', file: 'second-bbbbbb.md' })
            await c.add({ op: 'note_delete', file: 'first-aaaaaa.md' })
            const again = new Changes()                  // a fresh start reads the stored queue
            await again.load()
            const stored = again.list.map(e => e.file)
            const sent = []
            const n = await again.flush(async doc => { sent.push(JSON.parse(JSON.stringify(doc))); return 'chg-d' }, 'pD')
            console.log(JSON.stringify({ stored, n, sent }))
        """))
        self.assertEqual(out['stored'], ['first-aaaaaa.md', 'second-bbbbbb.md'])
        self.assertEqual(out['n'], 2)
        doc = out['sent'][0]
        self.assertEqual([(c['op'], c['file']) for c in doc['changes']],
                         [('note_delete', 'first-aaaaaa.md'), ('note_delete', 'second-bbbbbb.md')])
        doc['at'] = max(doc['at'], t + 10)
        name, blob = self.key.seal_change(doc)
        self.drive.put(name, blob)
        self.svc._intake()
        self.assertFalse(any(p.exists() for p in paths))

    @unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
    def test_a_retried_upload_never_applies_twice(self):
        """The phone's upload goes through but its answer is lost: the retry sends the same batch
        with the same time (web/src/mobile/mirror/changes.ts), so the saved answer is one note, and
        what was queued meanwhile goes in the next file."""
        docs = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes(), sent = []
            await c.add({ op: 'answer', md: '# Once only\\n\\nText', ids: [], file: 'once-only.md' })
            let lost = true
            const send = async doc => { sent.push(JSON.parse(JSON.stringify(doc))); if (lost) { lost = false; throw new TypeError('Failed to fetch') } return 'chg-x' }
            await c.flush(send, 'pR').catch(() => {})
            await c.add({ op: 'answer', md: '# Second\\n\\nText', ids: [], file: 'second.md' })
            const n = await c.flush(send, 'pR')
            console.log(JSON.stringify({ sent, n, unsent: c.unsent }))
        """))
        sent = docs['sent']
        self.assertEqual((docs['n'], docs['unsent'], len(sent)), (2, 0, 3))
        self.assertEqual(sent[0], sent[1])
        self.assertGreater(sent[2]['at'], sent[1]['at'])
        for d in sent:
            name, blob = self.key.seal_change(d)
            self.drive.put(name, blob)
        self.svc._intake()
        notes = sorted(q.name for q in (self.data / 'notes').glob('*.md'))
        self.assertEqual([n for n in notes if n.startswith(('once', 'second'))], ['once-only.md', 'second.md'])

    def test_publish_lists_ids_and_applied_and_keeps_change_files(self):
        with mock.patch.object(sync_mod, 'POLL', 0.1), mock.patch.object(sync_mod, 'INTAKE', 0.1), \
                mock.patch.object(sync_mod, 'INTAKE_MAX', 0.1):
            self.svc.turn_on()
            end = time.time() + 15
            while time.time() < end and not self.svc.status()['last_publish']:
                time.sleep(0.05)
            man, files = read_mirror(self.drive, self.key)
            for logical, f in man['files'].items():
                self.assertEqual(self.drive.files[f['id']][0], f['n'])          # the phone downloads by id
            self.assertEqual(man['applied'], {})
            published = man['published']
            self.phone([{'op': 'fav', 'uid': self.uid[self.ids[1]], 'on': True}], device='pC')
            end = time.time() + 15
            while time.time() < end:
                man, _ = read_mirror(self.drive, self.key)
                if man['applied'].get('pC'):
                    break
                time.sleep(0.05)
            self.assertIn('pC', man['applied'])
            self.assertGreater(man['published'], published)
            self.assertIn('library/meta.json', man['files'])
        meta = json.loads(read_mirror(self.drive, self.key)[1]['library/meta.json'])
        self.assertEqual(meta['topic_notes'], [])

    def test_stray_delete_spares_change_files(self):
        state = {}
        payload = self.writer.read(lambda db: __import__('library.export', fromlist=['x']).build_export_payload(db, None, mirror=True))
        self.drive.put(mirror.CHANGE_PREFIX + 'ab' * 16, b'pending')
        self.drive.put('0' * 32, b'stray')
        DriveMirrorTarget(self.drive, self.key, state, self.data, mirror.Options()).export(payload)
        names = [n for n, _ in self.drive.files.values()]
        self.assertIn(mirror.CHANGE_PREFIX + 'ab' * 16, names)
        self.assertIn('0' * 32, names)  # unknown namespace is not owned

    def test_unpair_makes_a_new_key(self):
        old = self.key.fingerprint
        new = self.svc.unpair()
        self.assertNotEqual(old, new)
        self.assertEqual(mirror.MirrorKey.load(self.cloud / 'mirror.key').fingerprint, old)
        self.assertEqual(self.svc.status()['rotation'], 'pending')


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class DriveLampTest(unittest.TestCase):
    def test_signed_in_and_answering_never_reads_offline(self):
        """The phone said "offline" with Google Drive connected: the lamp followed "the last refresh
        worked", so a refresh still running, one that found no library (the PC's first upload was not
        finished) or met a file Drive no longer has all read as offline. Only no signal, a refused
        sign-in or a call that got no reply may (web/src/mobile/mirror/status.ts)."""
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            const { driveLamp, answered } = await import('./web/src/mobile/mirror/status.ts')
            const { DriveError, NeedsSignIn } = await import('./web/src/mobile/mirror/drive.ts')
            const base = { online: true, refreshing: false, tried: true, signedIn: true, signIn: false, answered: true, noLibrary: false }
            const lamp = o => driveLamp({ ...base, ...o })
            console.log(JSON.stringify({
              ok: lamp({}),
              starting: lamp({ tried: false, answered: false }),
              busy: lamp({ refreshing: true, answered: false }),
              noLibrary: lamp({ noLibrary: true }),
              refused: lamp({ signIn: true }),
              noToken: lamp({ signedIn: false }),
              noSignal: lamp({ online: false }),
              noReply: lamp({ answered: false }),
              file404: answered(new DriveError('Google Drive answered 404', 404)),
              noNet: answered(new DriveError('Google Drive is out of reach (Failed to fetch)')),
              signInErr: answered(new NeedsSignIn('sign in', 401)),
              other: answered(new TypeError('x')),
            }))
        """))
        self.assertEqual(out, {
            'ok': 'connected', 'starting': 'connecting', 'busy': 'syncing', 'noLibrary': 'no library yet',
            'refused': 'sign in', 'noToken': 'sign in', 'noSignal': 'offline', 'noReply': 'not reachable',
            'file404': True, 'noNet': False, 'signInErr': False, 'other': False})


class AccountTest(unittest.TestCase):
    def test_drive_waits_for_a_confirmed_account(self):
        """After a reset the app took the Google account Google remembered, without asking. A token is
        now used only once its account is confirmed on this phone (`g`); a paired phone signed in to
        another account than the PC's is told so; re-pairing the same PC keeps the confirmed account
        (web/src/mobile/mirror/status.ts accountCheck, mirror/pairing.ts token)."""
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            globalThis.window = new EventTarget()
            globalThis.document = new EventTarget()
            Object.defineProperty(navigator, 'onLine', { value: true })
            Object.defineProperty(navigator, 'connection', { value: Object.assign(new EventTarget(), { type: 'wifi' }) })
            const { accountCheck, accountConfirmed } = await import('./web/src/mobile/mirror/status.ts')
            const P = await import('./web/src/mobile/mirror/pairing.ts')
            const { secrets } = await import('./web/src/mobile/native.ts')
            const calls = []
            globalThis.fetch = async (url, init) => {
              calls.push([url, init.headers.Authorization])
              return new Response(JSON.stringify({ user: { emailAddress: 'fred@example.com' } }), { status: 200 })
            }
            const code = o => Buffer.from(JSON.stringify(o)).toString('base64url')
            const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
            const k = P.newKeyText(), key = await MirrorKey.fromText(k)
            const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify'])
            const l = Buffer.from(await crypto.subtle.exportKey('spki', signing.publicKey)).toString('base64url')
            const pc = { v: 2, k, l, c: '', e: 'fred@example.com', f: key.fingerprint }
            globalThis.confirm = () => true
            await P.acceptLink('https://x/mobile.html#pair=' + code({ ...pc, g: 'evil@example.com' }))
            const p = P.pairing()
            secrets.set('bp-gtoken', JSON.stringify({ access: 'TOK', exp: Date.now() + 3600e3 }))
            const before = [p.g ?? null, P.token(p), P.unconfirmedToken(p)]
            const got = await P.whoSignedIn(p)
            P.confirmAccount(p, got)
            const after = [P.token(p), P.unconfirmedToken(p)]
            await P.acceptLink('https://x/mobile.html#pair=' + code(pc))          // the same PC again
            const kept = P.pairing().g ?? null
            await P.acceptLink('https://x/mobile.html#pair=' + code({ ...pc, c: 'different-project-client' }))
            if (P.pairing().g || P.token(P.pairing())) throw Error('Reused account/token across OAuth clients')
            await P.acceptLink('https://x/mobile.html#pair=' + code(pc))
            await P.acceptLink('https://x/mobile.html#pair=' + code({ ...pc, e: 'other@example.com' }))
            const dropped = P.pairing().g ?? null
            const q = P.pairing()
            P.confirmAccount(q, 'other@example.com')
            secrets.set('bp-gtoken', JSON.stringify({ access: 'TOK2', exp: Date.now() + 3600e3 }))
            P.disconnectDrive(q)
            console.log(JSON.stringify({
              before, got, after, kept, dropped, call: calls[0],
              disconnected: [P.token(q), P.pairing().g ?? null],
              dev: P.token({ ...q, d: 'http://127.0.0.1:18766' }),
              checks: [accountCheck('fred@example.com', undefined, 'fred@example.com'),
                       accountCheck('fred@example.com', undefined, 'other@example.com'),
                       accountCheck('fred@example.com', 'fred@example.com', 'Fred@Example.com '),
                       accountCheck('', undefined, 'a@example.com'),
                       accountCheck('', 'a@example.com', 'b@example.com')],
              confirmed: [accountConfirmed({}), accountConfirmed({ g: 'a' }), accountConfirmed({ d: 'x' })],
            }))
        """))
        self.assertEqual(out['before'], [None, None, True])       # a code cannot carry `g`; the token waits
        self.assertEqual(out['got'], 'fred@example.com')
        self.assertEqual(out['call'], ['https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)', 'Bearer TOK'])
        self.assertEqual(out['after'], ['TOK', False])
        self.assertEqual((out['kept'], out['dropped']), ('fred@example.com', None))
        self.assertEqual(out['disconnected'], [None, None])
        self.assertIsNone(out['dev'])
        self.assertEqual(out['checks'], ['confirm', 'mismatch', 'ok', 'confirm', 'confirm'])
        self.assertEqual(out['confirmed'], [False, True, False])


class ApplyTest(unittest.TestCase):
    def test_summary_and_unknown_ops(self):
        a = intake.Applied(links=1, favs=2)
        self.assertEqual(a.summary(), '1 link(s) saved, 2 favourite(s)')
        self.assertEqual(intake.Applied().summary(), 'nothing new')


class PairRoutesTest(test_sync.RoutesTest):
    def test_disconnect_forgets_the_token_and_keeps_the_account_unless_the_copy_is_deleted(self):
        """Disconnect Google Drive (POST /api/cloud/sign-out): the token goes; the account name and what was uploaded
        stay while the copy stays, so a sign-in to the same account updates it instead of making a second one (I1).
        Deleting the copy forgets the account too, so Connect starts clean. The guard still wants X-CM."""
        tok = self.root / 'cloud' / 'google_token.json'
        writer = self.client.app.state.writer
        drive_client.save_token(tok, {'refresh_token': 'r'})
        writer.call(lambda db: db.set_setting('cloud_account', 'dev@brainamon.local'))
        self.assertEqual(self.c.post('/api/cloud/sign-out', json={}).status_code, 403)
        with mock.patch.object(drive_client, 'revoke') as rv:
            v = self.c.post('/api/cloud/sign-out', json={}, headers={'X-CM': '1'}).json()
            rv.assert_called_once()
        self.assertFalse(tok.exists())
        self.assertFalse(v['signed_in'])
        self.assertEqual(writer.read(lambda db: db.get_setting('cloud_account', '')), 'dev@brainamon.local')
        v = self.c.post('/api/cloud/sign-out', json={'delete_mirror': True}, headers={'X-CM': '1'}).json()
        self.assertEqual((v['account'], v['signed_in']), ('', False))
        self.assertEqual(writer.read(lambda db: db.get_setting('cloud_account', '')), '')

    def test_pair_link_and_unpair(self):
        W = {'X-CM': '1'}
        drive = FakeDrive()
        sync = self.client.app.state.sync
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test-openai', 'ANTHROPIC_API_KEY': '',
                                            'BRAINAMON_GOOGLE_WEB_CLIENT_ID': 'web-123.apps.googleusercontent.com',
                                            'BRAINAMON_GOOGLE_CLIENT_ID': '123456789-abc.apps.googleusercontent.com'}):
            self.assertEqual(self.c.get('/api/cloud/pair').status_code, 405)          # never a GET: it carries the key
            self.assertEqual(self.c.post('/api/cloud/pair', json={}).status_code, 403)  # the guard wants X-CM
            # AI keys go through Drive: not signed in, they cannot be sent (the plain pairing still can)
            self.assertEqual(self.c.post('/api/cloud/pair', json={'keys': ['openai']}, headers=W).status_code, 409)
            self.assertNotIn('t', self._code(self.c.post('/api/cloud/pair', json={}, headers=W).json()))
            drive_client.save_token(self.root / 'cloud' / 'google_token.json', {'refresh_token': 'r'})
            sync._raw_factory = lambda tok: drive
            policy = mock.patch.object(sync.recovery, 'guard')
            policy.start()
            self.addCleanup(policy.stop)
            r = self.c.post('/api/cloud/pair', json={'keys': ['openai', 'anthropic', 'evil']}, headers=W).json()
            v = self.c.get('/api/cloud').json()
        self.assertTrue(r['url'].startswith('http://localhost:18765/mobile.html#pair='))
        self.assertNotIn('sk-test-openai', r['url'])
        data = self._code(r)
        key = mirror.MirrorKey.load(self.root / 'cloud' / 'mirror.key')
        self.assertEqual(data['k'], key.text())
        self.assertEqual((data['v'], data['c'], data['f']), (2, 'web-123.apps.googleusercontent.com', key.fingerprint))
        self.assertNotIn('ai', data)                      # the link never carries an API key
        self.assertEqual((data['e'], data['p']), ('fred@example.com', '123456789'))     # the PC's account (read from Google) and Cloud project
        self.assertEqual(r['keys'], ['openai'])
        # the keys wait in Drive, sealed with the link's one-time key, under a name the phone can work out
        one = mirror.MirrorKey(base64.urlsafe_b64decode(data['t'] + '=' * (-len(data['t']) % 4)))
        drops = [(n, b) for n, b in drive.files.values() if mirror.is_pair_drop(n)]
        self.assertEqual([n for n, _ in drops], [mirror.pair_drop_name(one, data['tx'])])
        self.assertNotIn(b'sk-test-openai', drops[0][1])
        self.assertEqual(json.loads(one.open(mirror.PAIR_LOGICAL, drops[0][1])), {'ai': {'openai': 'sk-test-openai'}})
        self.assertNotEqual(one.fingerprint, key.fingerprint)
        self.assertAlmostEqual(data['tx'], time.time() + mirror.PAIR_TTL, delta=60)
        self.assertNotIn('d', data)                       # Google's Drive: no development base
        self.assertIn('<svg', r['svg'])
        self.assertEqual((v['web_client'], v['phone_keys']), (True, ['openai']))
        u = self.c.post('/api/cloud/unpair', headers=W).json()
        self.assertNotEqual(u['fingerprint'], key.fingerprint)
        self.assertEqual(self.c.put('/api/cloud/options', json={'phone_url': 'http://evil.example/m'}, headers=W).status_code, 400)
        self.assertEqual(self.c.put('/api/cloud/options', json={'phone_url': 'https://brainamon.app/mobile.html'}, headers=W).json()['phone_url'],
                         'https://brainamon.app/mobile.html')

    @staticmethod
    def _code(r: dict) -> dict:
        code = r['url'].split('#pair=')[1]
        return json.loads(base64.urlsafe_b64decode(code + '=' * (-len(code) % 4)))

    def test_cloud_endpoints(self):          # covered by test_sync
        pass


class PairDropTest(unittest.TestCase):
    def test_kept_from_strays_until_it_expires_then_swept(self):
        key, drive = mirror.MirrorKey.generate(), FakeDrive()
        one, exp, name, blob = mirror.pair_drop({'openai': 'sk-x'})
        self.assertFalse(mirror.pair_drop_expired(name))
        self.assertTrue(mirror.pair_drop_expired(name, now=exp + 1))
        self.assertTrue(mirror.pair_drop_expired(mirror.PAIR_PREFIX + 'junk'))
        _, _, old_name, _ = mirror.pair_drop({'openai': 'sk-old'}, now=time.time() - mirror.PAIR_TTL - 5)
        drive.put(name, blob)
        drive.put(old_name, b'old')
        tmp = Path(__import__('tempfile').mkdtemp())
        payload = {'items': [], 'categories': [], 'canvases': [], 'notes': [], 'chats': [], 'vectors': None}
        with mock.patch.object(mirror, 'build_files', return_value=iter([])):
            DriveMirrorTarget(drive, key, {}, tmp, mirror.Options()).export(payload)
        self.assertEqual([n for n, _ in drive.files.values() if mirror.is_pair_drop(n)], [name, old_name])  # exporter owns neither transfer; intake sweeps expiry


if __name__ == '__main__':
    unittest.main()
