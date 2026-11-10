"""Synthesize's labelled source text on the PC (projects/phone-solo-synthesize): the job reads each
item's report file into the rows it folds, and a bare link (its description is only its url) is not
folded. The parts themselves, the caps and the trim are checked against the phone's twin in
tests/test_phone_ai.py."""
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from knowledge import synth
from server import job_kinds
from tests import phone_ai_fixture as F


class SynthPartsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brainamon-synth-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = F.build(self.tmp)
        self.addCleanup(self.db.close)

    def prepare(self, ids):
        job = SimpleNamespace(ids=ids, opts={'topic': 'Knee'}, ctx={})
        with mock.patch.object(job_kinds.ai_defaults, 'get', return_value=('openai', 'gpt-6-luna')), \
             mock.patch.object(job_kinds, '_key_ctx'):
            return job_kinds._note_prepare(self.db, job)

    def test_the_note_job_reads_each_report(self):
        with_report = [it['id'] for it in F.load()['items'] if it.get('report')]
        rows = self.prepare(with_report[:2] + [999999])
        self.assertEqual([r['id'] for r in rows], with_report[:2])
        for r in rows:
            self.assertTrue(r['report'])
            self.assertIn('Report:\n' + r['report'][:40], synth.source_block(r))

    def test_a_bare_link_is_not_folded(self):
        bare = self.db.add_item({'url': 'https://example.com/bare', 'description': 'https://example.com/bare', 'source': 'phone'})
        self.assertEqual(self.prepare([bare]), [])
        self.db.update_item(bare, {'notes': 'read this one'})
        rows = self.prepare([bare])
        self.assertEqual([r['id'] for r in rows], [bare])
        self.assertIn('My note:\nread this one', synth.source_block(rows[0]))
        self.assertNotIn('Caption:', synth.source_block(rows[0]))

    def test_a_sentinel_only_description_is_not_folded(self):
        bare = self.db.add_item({'url': 'https://example.com/sentinel', 'description': 'https://example.com/sentinel', 'source': 'phone'})
        self.db.update_item(bare, {'ai_desc': 'NO_CONTENT'})
        self.assertEqual(self.prepare([bare]), [])
        self.db.update_item(bare, {'description': 'example.com/sentinel/'})
        self.assertEqual(self.prepare([bare]), [])


if __name__ == '__main__':
    unittest.main()
