"""Phone change files applied exactly once (server/delivery.py, delivery 2). All libraries and Drive files are synthetic.

Plan: docs/superpowers/plans/2026-10-31-phone-backup-phones/02-s5-resend-after-pairing-again.md. The first five tests
are the review probes, moved to numbered files: on the reviewed baseline three of them lost or doubled a batch.
"""
import json
import threading
import unittest
from unittest import mock

from core.db import Database
from knowledge import my_notes
from library import drive_client, mirror
from server import sync as sync_mod
from tests import test_sync, test_update_folder

STREAM = 'a' * 32
RECEIPTS = 'cloud_receipts'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.fx = test_sync.ServiceTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.addCleanup(self.fx.tearDown)
        self.svc, self.drive = self.fx.svc, self.fx.drive
        self.svc.ensure_running = lambda: None
        self.key, _ = self.fx.access_ready()

        def create(db):
            path = my_notes.create_note(db.notes_dir, 'Delivery probe', 'Inbox')
            my_notes.save_note(path, 'Delivery probe', 'Inbox', 'Seed')
            return path
        self.note = self.fx.writer.call(create)

    def doc(self, tag, at, seq=None, stream=STREAM, acked=0, legacy=False, device='probe-phone'):
        doc = {'format': 1, 'device': device, 'at': at, 'changes': [
            {'op': 'note_append', 'file': self.note.name, 'title': 'Delivery probe',
             'name': 'Fixture', 'text': 'section-' + tag, 'when': '2026-10-31 15:05', 'at': at}]}
        if seq is not None:
            doc.update(stream=stream, seq=seq, acked=acked)
            if legacy:
                doc['legacy'] = True
        return doc

    def put(self, tag, at, seq=None, key=None, **kw):
        name, blob = (key or self.key).seal_change(self.doc(tag, at, seq, **kw))
        return self.drive.put(name, blob)

    def setting(self, name):
        return self.fx.writer.read(lambda db: json.loads(db.get_setting(name, '') or '{}'))

    def applied(self):
        return self.setting(sync_mod.S_APPLIED)

    def receipt(self, stream=STREAM):
        r = self.setting(RECEIPTS).get(stream) or {}
        return {k: r[k] for k in ('seq', 'want') if k in r}

    def counts(self, *tags):
        text = self.note.read_text(encoding='utf-8')
        return tuple(text.count('section-' + t) for t in (tags or ('A', 'B')))

    def changes_left(self):
        return [fid for fid, (n, _) in self.drive.files.items() if mirror.is_change(n)]


class DeliveryPrerequisite(Fixture):
    def test_download_failure_does_not_acknowledge_an_unread_earlier_batch(self):
        early, _late = self.put('A', 100, 1), self.put('B', 200, 2)
        download = self.drive.download

        def fail_early(fid):
            if fid == early:
                raise drive_client.DriveError('synthetic temporary download failure', 503)
            return download(fid)
        with mock.patch.object(self.drive, 'download', side_effect=fail_early):
            self.svc._intake()
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.receipt(), {'seq': 0, 'want': 1})
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1), {'receipts': self.setting(RECEIPTS), 'counts': self.counts()})
        self.assertEqual(self.receipt(), {'seq': 2})
        self.assertEqual(self.changes_left(), [])

    def test_omitted_earlier_file_can_arrive_after_a_later_batch(self):
        early, late = self.put('A', 100, 1), self.put('B', 200, 2)
        listing = self.drive.list
        with mock.patch.object(self.drive, 'list', side_effect=lambda: [f for f in listing() if f['id'] != early]):
            self.svc._intake()
        self.assertEqual(self.counts(), (0, 0))
        self.assertIn(late, self.drive.files)
        self.assertIn('wait for an earlier one', self.svc.status()['intake_summary'])
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1), {'receipts': self.setting(RECEIPTS), 'counts': self.counts()})

    def test_complete_listing_is_sorted_and_duplicate_batches_are_skipped(self):
        self.put('B', 200, 2)
        self.put('A', 100, 1)
        self.put('A', 100, 1)
        self.svc._intake()
        self.put('B', 200, 2)
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.receipt(), {'seq': 2})
        self.assertEqual(self.changes_left(), [])

    def test_retry_after_receipt_write_failure_does_not_append_twice(self):
        self.put('A', 100, 1)
        original = Database.set_setting

        def fail_receipt(db, name, value):
            if name == sync_mod.S_APPLIED:
                raise OSError('synthetic receipt write failure after note append')
            return original(db, name, value)
        with mock.patch.object(Database, 'set_setting', fail_receipt):
            self.svc._intake()
        self.assertEqual(self.counts(), (0, 0))        # the note append was undone with its receipt
        self.assertEqual(len(self.changes_left()), 1)
        self.assertIn('wait for the next look', self.svc.status()['intake_summary'])
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 0), {'receipts': self.setting(RECEIPTS), 'counts': self.counts()})

    def test_rotation_retains_late_old_file_and_resend_keeps_batch_identity(self):
        early = self.put('A', 100, 1)
        self.svc.unpair()
        self.assertIn(early, self.svc._rotation()['old_changes'])
        late = self.put('B', 200, 2)
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(self.receipt(), {'seq': 1})
        self.assertIn(late, self.drive.files)
        self.assertNotIn('download ' + late, self.drive.calls)
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        self.assertEqual(self.svc._rotation()['stage'], 'complete')
        self.assertIn(late, self.drive.files)
        new = mirror.MirrorKey.load(self.svc.key_path)
        self.put('B', 200, 2, new, acked=0)     # paired again: everything not acknowledged goes again, oldest first
        self.put('A', 100, 1, new, acked=0)
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.receipt(), {'seq': 2})
        self.assertIn(late, self.drive.files)   # the old-key file stays for recovery (I6)

    def test_equal_times_and_two_uploads_of_one_file_do_not_collide(self):
        self.put('A', 100, 1)
        self.put('B', 100, 2)
        self.put('B', 100, 2)                   # an upload whose answer was lost, sent again
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.changes_left(), [])

    def test_other_content_under_an_applied_number_is_refused_and_retained(self):
        self.put('A', 100, 1)
        self.svc._intake()
        other = self.put('C', 100, 1)
        self.svc._intake()
        self.assertEqual(self.counts('A', 'C'), (1, 0))
        self.assertEqual(self.changes_left(), [other])
        self.assertIn('refused', self.svc.status()['intake_summary'])
        self.assertEqual(self.receipt(), {'seq': 1})

    def test_a_stream_this_pc_does_not_know_starts_after_what_the_phone_saw_acknowledged(self):
        # a library restored from an older backup: the phone already dropped 1 to 4, acknowledged elsewhere
        self.put('A', 500, 5, acked=4)
        self.put('B', 700, 7, acked=4)
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(self.receipt(), {'seq': 5, 'want': 6})

    def test_the_manifest_says_delivery_and_carries_the_receipts(self):
        self.put('A', 100, 1)
        self.put('B', 300, 3)
        self.svc._intake()
        self.svc._force_manifest = True
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        man, _ = test_sync.read_mirror(self.drive, self.key)
        self.assertEqual(man['delivery'], mirror.DELIVERY)
        self.assertEqual({k: man['receipts'][STREAM][k] for k in ('device', 'seq', 'want')},
                         {'device': 'probe-phone', 'seq': 1, 'want': 2})
        self.assertEqual(len(man['receipts'][STREAM]['digests']), 1)

    def test_an_invalid_numbered_envelope_is_retained(self):
        doc = self.doc('A', 100, 1)
        doc['stream'] = 'not-a-stream'
        name, blob = self.key.seal_change(doc)
        bad = self.drive.put(name, blob)
        self.svc._intake()
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.changes_left(), [bad])
        self.assertIn('invalid phone change envelope', self.svc.status()['intake_summary'])


class LegacyCompatibility(Fixture):
    """Files without numbers come from a phone build before delivery 2: the `applied` floor rules stay (no new guarantee)."""

    def test_unnumbered_files_keep_the_floor_rules(self):
        self.put('B', 200)
        self.svc._intake()
        self.put('A', 100)                      # an older file seen after a later one: skipped, as before
        self.svc._intake()
        self.assertEqual(self.counts(), (0, 1))
        self.assertEqual(self.applied(), {'probe-phone': 200})

    def test_unnumbered_files_wait_after_a_failed_download(self):
        early, _late = self.put('A', 100), self.put('B', 200)
        download = self.drive.download

        def fail_early(fid):
            if fid == early:
                raise drive_client.DriveError('synthetic temporary download failure', 503)
            return download(fid)
        with mock.patch.object(self.drive, 'download', side_effect=fail_early):
            self.svc._intake()
        self.assertEqual((self.counts(), self.applied()), ((0, 0), {}))
        self.svc._intake()
        self.assertEqual((self.counts(), self.applied()), ((1, 1), {'probe-phone': 200}))

    def test_a_legacy_batch_sent_again_with_a_number_applies_once(self):
        self.put('A', 100)
        self.svc._intake()
        self.put('A', 100, 1, legacy=True)      # its numbered copy: applied before, only the receipt moves
        self.put('B', 200, 2, legacy=True)
        self.put('B', 200)                      # and an unnumbered copy of the next one, still readable
        self.svc._intake()
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual((self.applied(), self.receipt()), ({'probe-phone': 200}, {'seq': 2}))
        self.assertEqual(self.changes_left(), [])

    def test_unnumbered_copies_wait_for_the_numbered_ones(self):
        self.put('A', 100, 1, legacy=True)
        self.svc._intake()
        old = self.put('B', 300)                # the unnumbered copy of a batch the phone renumbered
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(self.changes_left(), [old])
        self.assertIn('wait for their numbered copies', self.svc.status()['intake_summary'])
        self.put('B', 300, 2, legacy=True)
        self.svc._intake()
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.changes_left(), [])


class AcknowledgementCopy(unittest.TestCase):
    def test_restore_takeover_and_update_preserve_receipts_and_apply_pending_numbered_files(self):
        fx = test_update_folder.UpdateFolderTest()
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        self.addCleanup(fx.tearDown)
        want = {'probe-phone': 123456789}
        rec = {STREAM: {'device': 'probe-phone', 'seq': 4, 'digests': {}}}
        fx.writer.call(lambda db: (db.set_setting(sync_mod.S_APPLIED, json.dumps(want)),
                                   db.set_setting(RECEIPTS, json.dumps(rec))))
        fx.svc._force_manifest = True  # mirror the follow-up publish requested by _tick_intake
        self.assertTrue(fx.svc._publish(), fx.svc.status())

        def numbered(seq, url):
            name, blob = fx.key.seal_change({'format': 1, 'device': 'probe-phone', 'at': 1000 + seq, 'stream': STREAM,
                                             'seq': seq, 'acked': 4, 'changes': [
                                                 {'op': 'link', 'uid': f'{seq:032x}', 'url': url, 'at': 1000 + seq}]})
            return fx.drive.put(name, blob)
        numbered(5, 'https://example.com/pending-five')
        numbered(7, 'https://example.com/pending-seven')
        temp = fx.temporary_pc()
        urls = temp.writer.read(lambda db: {r[0] for r in db.conn.execute('SELECT url FROM items')})
        self.assertIn('https://example.com/pending-five', urls)
        self.assertNotIn('https://example.com/pending-seven', urls)
        got = temp.writer.read(lambda db: json.loads(db.get_setting(RECEIPTS)))[STREAM]
        self.assertEqual((got['seq'], got['want']), (5, 6))
        self.assertEqual(temp.writer.read(lambda db: json.loads(db.get_setting(sync_mod.S_APPLIED))), want)
        fx.temp_changes(temp, notes=1)
        fx.download_update()
        fx.restart()
        self.assertEqual(fx.writer.read(lambda db: json.loads(db.get_setting(sync_mod.S_APPLIED))), want)
        back = fx.writer.read(lambda db: json.loads(db.get_setting(RECEIPTS)))[STREAM]
        self.assertEqual((back['seq'], back['want']), (5, 6))


if __name__ == '__main__':
    unittest.main()
