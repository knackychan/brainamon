"""A phone change file applies as one transaction (server/delivery.py): an error of the PC undoes it, a quit in the
middle is finished or undone at the next start, and a change that is wrong in itself is still skipped alone.
All libraries and Drive files are synthetic (test_sync fixtures)."""
import json
import unittest
from unittest import mock

from core.db import Database
from knowledge import filing, my_notes
from server import delivery, intake
from server import sync as sync_mod
from tests import test_phone_delivery_prerequisite as base


class Crash(BaseException):
    """The process ends here: nothing after it runs, not even the undo."""


class InterruptedFile(base.Fixture):
    def numbered(self, seq, changes, at=None):
        at = at or 100 * seq
        name, blob = self.key.seal_change({'format': 1, 'device': 'probe-phone', 'at': at, 'stream': base.STREAM,
                                           'seq': seq, 'acked': 0, 'changes': changes})
        return self.drive.put(name, blob)

    def append(self, tag, at=100):
        return {'op': 'note_append', 'file': self.note.name, 'title': 'Delivery probe', 'name': 'Fixture',
                'text': 'section-' + tag, 'when': '2026-10-31 15:05', 'at': at}

    def started(self):
        app = self.fx.restart()
        self.addCleanup(app.shutdown)
        app.ensure_running = lambda: None
        app.boot()
        return app

    def undo_dir(self):
        return self.fx.data / delivery.UNDO

    def item_with_folder(self):
        def make(db):
            item = db.add_item({'url': 'https://example.com/delete-me', 'description': 'x'})
            folder = db.item_dir(item)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'report.md').write_text('kept until the commit', encoding='utf-8')
            return item, db.get_item(item)['uid'], folder
        return self.fx.writer.call(make)

    def test_a_quit_before_the_commit_is_undone_at_the_next_start(self):
        self.numbered(1, [self.append('A')])
        real = Database.set_setting

        def quit_at_commit(db, name, value):
            if name == delivery.COMMIT:
                raise Crash()
            return real(db, name, value)
        with mock.patch.object(Database, 'set_setting', quit_at_commit), mock.patch.object(delivery, '_undo'), \
                mock.patch.object(delivery.shutil, 'rmtree'):
            with self.assertRaises(Crash):
                self.svc._intake()
        self.assertEqual(self.counts(), (1, 0))             # what the quit left: the section, and its journal
        self.assertTrue((self.undo_dir() / 'journal.json').is_file())
        app = self.started()
        self.assertEqual(self.counts(), (0, 0))
        self.assertFalse(self.undo_dir().exists())
        app._intake()
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(self.receipt(), {'seq': 1})

    def test_a_quit_after_the_commit_keeps_the_file_and_removes_the_folder_at_the_next_start(self):
        item, uid, folder = self.item_with_folder()
        self.numbered(1, [{'op': 'delete', 'uid': uid, 'pc': True, 'at': 100}, self.append('A')])
        with mock.patch.object(delivery, '_remove_folders', side_effect=Crash()):
            with self.assertRaises(Crash):
                self.svc._intake()
        self.assertIsNone(self.fx.writer.read(lambda db: db.get_item(item)))
        self.assertTrue(folder.is_dir())                    # deleted from the database, folder not yet
        app = self.started()
        self.assertFalse(folder.exists())
        self.assertFalse(self.undo_dir().exists())
        app._intake()                                       # the file is still in Drive: seen before, deleted
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(self.changes_left(), [])

    def test_an_error_of_the_pc_undoes_the_whole_file_and_keeps_a_deleted_items_folder(self):
        item, uid, folder = self.item_with_folder()
        self.numbered(1, [{'op': 'delete', 'uid': uid, 'pc': True, 'at': 100},
                          {'op': 'note', 'file': 'from-the-phone.md', 'title': 'From the phone', 'category': 'Inbox',
                           'body': 'new', 'was': '', 'at': 100},
                          {'op': 'chat', 'slug': 'phone-chat', 'name': 'Phone chat', 'created': '', 'history': [],
                           'source_ids': [], 'options': {}, 'was': '', 'at': 100},
                          self.append('A'),
                          {'op': 'synth_queue', 'topic': 'Later', 'ids': [1], 'at': 100}])
        real = filing.add_section

        def disk_full(*a, **k):
            real(*a, **k)
            raise OSError('synthetic disk full after the section was written')
        notes = sorted(p.name for p in self.fx.data.joinpath('notes').iterdir())
        with mock.patch.object(filing, 'add_section', disk_full):
            self.svc._intake()
        self.assertEqual(self.counts(), (0, 0))
        self.assertTrue(folder.is_dir())
        self.assertIsNotNone(self.fx.writer.read(lambda db: db.get_item(item)))
        self.assertEqual(sorted(p.name for p in self.fx.data.joinpath('notes').iterdir()), notes)
        self.assertFalse((self.fx.data / 'ask_chats' / 'phone-chat.json').exists())
        self.assertEqual(self.fx.writer.read(lambda db: db.get_setting(intake.SYNTH_QUEUE, '')), '')
        self.assertEqual(self.receipt(), {})
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 0))
        self.assertFalse(folder.exists())
        self.assertTrue((self.fx.data / 'notes' / 'from-the-phone.md').is_file())
        self.assertTrue((self.fx.data / 'ask_chats' / 'phone-chat.json').is_file())
        self.assertEqual(len(json.loads(self.fx.writer.read(lambda db: db.get_setting(intake.SYNTH_QUEUE)))), 1)
        self.assertEqual(self.receipt(), {'seq': 1})

    def test_a_change_wrong_in_itself_is_skipped_alone_and_its_writes_are_rolled_back(self):
        item, uid, _folder = self.item_with_folder()
        real = intake._edit

        def half_then_wrong(db, ch, at, alias, out):
            db.update_item(item, {'tags': 'half-written'})
            raise ValueError('a change this PC cannot read')
        self.numbered(1, [{'op': 'edit', 'uid': uid, 'fields': {'tags': 'x'}, 'was': {}, 'at': 100}, self.append('A')])
        with mock.patch.object(intake, '_edit', half_then_wrong):
            self.svc._intake()
        self.assertEqual(self.fx.writer.read(lambda db: db.get_item(item)['tags']), '')
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(self.receipt(), {'seq': 1})
        self.assertIn('unreadable change(s) skipped', self.svc.status()['intake_summary'])
        self.assertIs(real, intake._edit)

    def test_an_unexpected_error_never_acknowledges_a_numbered_file(self):
        self.numbered(1, [self.append('A')])
        with mock.patch.object(intake, 'apply', side_effect=RuntimeError('boom')):
            self.svc._intake()
        self.assertEqual((self.counts(), self.receipt()), ((0, 0), {}))
        self.assertEqual(len(self.changes_left()), 1)
        self.svc._intake()
        self.assertEqual((self.counts(), self.receipt()), ((1, 0), {'seq': 1}))

    def test_the_setting_names_match_the_sync_service(self):
        self.assertEqual((delivery.APPLIED, delivery.ALIAS, delivery.CANVAS_RESULTS, delivery.ALIAS_KEEP),
                         (sync_mod.S_APPLIED, sync_mod.S_ALIAS, sync_mod.S_CANVAS_RESULTS, sync_mod.ALIAS_KEEP))


if __name__ == '__main__':
    unittest.main()
