"""Unreadable undo records must survive, and exports must wait for recovery."""
from pathlib import Path
from unittest import mock

from server import delivery
from tests.test_phone_delivery_prerequisite import Fixture


class UndoRecovery(Fixture):
    def test_unreadable_undo_journal_is_retained_for_retry(self):
        def interrupted(db):
            batch = delivery.Batch(db, db.conn)
            batch.before(self.note)
            self.note.write_text('interrupted write', encoding='utf-8')
        self.fx.writer.call(interrupted)
        root = self.fx.data / delivery.UNDO
        original = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == root / 'journal.json':
                raise PermissionError('synthetic sharing violation')
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, 'read_text', unreadable):
            with self.assertRaises(PermissionError):
                self.fx.writer.call(delivery.recover)
        self.assertTrue((root / 'journal.json').is_file())
        self.fx.writer.call(delivery.recover)
        self.assertIn('Seed', self.note.read_text(encoding='utf-8'))

    def test_damaged_undo_journal_is_retained_for_repair(self):
        root = self.fx.data / delivery.UNDO
        root.mkdir()
        journal = root / 'journal.json'
        journal.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.fx.writer.call(delivery.recover)
        self.assertEqual(journal.read_text(encoding='utf-8'), '{broken')

    def test_backup_refuses_to_publish_an_unrecovered_note(self):
        def interrupted(db):
            batch = delivery.Batch(db, db.conn)
            batch.before(self.note)
            self.note.write_text('uncommitted phone content', encoding='utf-8')
        self.fx.writer.call(interrupted)
        with mock.patch.object(delivery, 'recover', side_effect=PermissionError('synthetic recovery failure')):
            self.assertFalse(self.svc._publish())
        self.assertTrue((self.fx.data / delivery.UNDO / 'journal.json').is_file())
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertIn('Seed', self.note.read_text(encoding='utf-8'))

    def test_update_comparison_waits_for_undo_recovery(self):
        with mock.patch.object(delivery, 'recover', side_effect=PermissionError('synthetic recovery failure')):
            with self.assertRaises(PermissionError):
                self.svc.local_files()
