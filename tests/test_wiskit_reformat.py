"""Wiskit Deep tool propose_reformat: queues the reformat job, writes nothing, refuses non-personal notes.

Run from the project root:  py -m unittest tests.test_wiskit_reformat -v
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from knowledge import librarian
from server.jobs import Busy
from server.routes import ask


class ProposeReformatTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        (self.data / 'notes').mkdir()
        (self.data / 'notes' / 'knee-plan.md').write_text(
            '---\ntopic: Knee plan\nkind: personal\n---\nmessy bits\n', encoding='utf-8')
        (self.data / 'notes' / 'wiki.md').write_text(
            '---\ntopic: Wiki\nkind: wiki\n---\nsynth\n', encoding='utf-8')
        self.started = []
        self.jobs = SimpleNamespace(start=self.start)
        self.app = SimpleNamespace(state=SimpleNamespace(data_dir=self.data, jobs=self.jobs))

    def start(self, kind, ids, force=False, opts=None, auto=False):
        self.started.append((kind, ids, force, opts))
        return {'id': 1}

    def test_queues_the_reformat_job_for_a_personal_note(self):
        out = ask._propose_reformat(self.app, 'knee-plan.md')
        self.assertEqual(self.started, [('reformat', [0], True, {'file': 'knee-plan.md'})])
        self.assertIn('Nothing is changed yet', out)
        self.assertEqual((self.data / 'notes' / 'knee-plan.md').read_text(encoding='utf-8').count('messy bits'), 1)

    def test_refuses_a_wiki_note_and_a_missing_one(self):
        self.assertIn('not one of the user', ask._propose_reformat(self.app, 'wiki.md'))
        self.assertIn('no note named', ask._propose_reformat(self.app, 'nope.md'))
        self.assertEqual(self.started, [])

    def test_busy_job_comes_back_as_text(self):
        def busy(*a, **k):
            raise Busy('One job at a time: Describe is running')
        self.jobs.start = busy
        self.assertIn('Not queued: One job at a time', ask._propose_reformat(self.app, 'knee-plan.md'))

    def test_tool_is_desktop_only_and_dispatches(self):
        names = [t['name'] for t in librarian.PROPOSE_TOOLS]
        self.assertEqual(names, ['read_note', 'propose_reformat'])
        self.assertNotIn('propose_reformat', [t['name'] for t in librarian.TOOLS])
        self.assertNotIn('read_note', [t['name'] for t in librarian.TOOLS])
        lib = librarian.Librarian.__new__(librarian.Librarian)
        lib.should_stop = None
        lib.deadline = None
        lib.budget = None
        lib._propose_fn = lambda f, i='': f'queued {f}' + (f' ({i})' if i else '')
        self.assertEqual(lib.run_tool('propose_reformat', {'file': 'a.md'}), 'queued a.md')
        self.assertEqual(lib.run_tool('propose_reformat', {'file': 'a.md', 'instruction': ' make  a checklist '}),
                         'queued a.md (make a checklist)')
        lib._propose_fn = None
        self.assertIn('not available', lib.run_tool('propose_reformat', {'file': 'a.md'}))

    def test_phone_port_tool_list_is_unchanged(self):
        prompts = json.loads((Path(__file__).resolve().parent.parent / 'knowledge' / 'prompts' / 'ask_deep.json')
                             .read_text(encoding='utf-8'))
        self.assertNotIn('propose_reformat', [t['name'] for t in prompts['tools']])


if __name__ == '__main__':
    unittest.main()
