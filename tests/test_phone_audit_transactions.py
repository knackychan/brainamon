"""Audit regressions for file rollback. Temporary libraries only."""
from unittest import mock

from knowledge import knowledge
from server import delivery
from tests.test_phone_delivery_prerequisite import Fixture


class FileRollback(Fixture):
    def test_invalid_unicode_note_restores_the_last_successful_change(self):
        def apply(db):
            first = self.doc('A', 100, 1)
            meta, _ = knowledge.split_frontmatter(self.note.read_text(encoding='utf-8'))
            bad = {'op': 'note', 'file': self.note.name, 'title': 'Delivery probe',
                   'category': 'Inbox', 'body': '\ud800', 'was': meta['updated'], 'at': 4_000_000_000_000}
            # The append and the invalid overwrite touch the same file in one batch.
            first['changes'].append(bad)
            return delivery.intake_round(db, [({'id': 'fixture'}, first)])

        result = self.fx.writer.call(apply)
        self.assertEqual(self.counts('A'), (1,))
        self.assertIn('Seed', self.note.read_text(encoding='utf-8'))
        self.assertEqual(result.out.skipped, 1)
        self.assertEqual(self.receipt(), {'seq': 1})

    def test_failed_file_rollback_never_commits_a_receipt(self):
        doc = self.doc('A', 100, 1)
        doc['changes'].append({'op': 'note', 'file': self.note.name, 'body': '\ud800',
                               'at': 4_000_000_000_000})
        original = delivery._write
        failures = []

        def fail_once(path, data):
            if path == self.note and not failures:
                failures.append(True)
                raise OSError('synthetic failure restoring the skipped change')
            return original(path, data)

        with mock.patch.object(delivery, '_write', fail_once):
            result = self.fx.writer.call(lambda db: delivery.intake_round(db, [({'id': 'fixture'}, doc)]))
        self.assertEqual(result.done, [])
        self.assertEqual(self.receipt(), {})
        self.assertEqual(self.counts('A'), (0,))
        self.assertIn('Seed', self.note.read_text(encoding='utf-8'))

    def test_invalid_unicode_new_note_leaves_no_empty_note(self):
        before = sorted(self.note.parent.glob('*.md'))
        doc = self.doc('A', 100, 1)
        doc['changes'].insert(0, {'op': 'note', 'title': 'Broken Unicode', 'body': '\ud800', 'at': 100})
        self.fx.writer.call(lambda db: delivery.intake_round(db, [({'id': 'fixture'}, doc)]))
        self.assertEqual(sorted(self.note.parent.glob('*.md')), before)
        self.assertEqual(self.counts('A'), (1,))

