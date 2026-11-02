"""Claude, Wiskit and the MCP read, edit and format the notes (projects/note-organic-ui/plans/04-agents.md):
Deep's read_note shows the note as written, propose_reformat carries the user's instruction into the
reformat job, Reformat reads the format and may return stamps, an MCP replace can set stamps (only with
a file) and keeps them otherwise, and every model-facing text carries the format contract."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core import note_format
from core.db import Database
from knowledge import claude_code
from knowledge import knowledge
from knowledge import librarian
from knowledge import my_notes
from knowledge import tasks
from server.app import create_app
from server.jobs import Job, KINDS
from server.routes import ask

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
LINE = '[{"k":"kettlebell","at":"The sequence","x":-4,"y":1,"s":3,"c":"indigo","r":0}]'
BODY = 'Ten minutes. <span data-ink="ember">16 kg</span>.\n\n## The sequence\n\n- [x] cat-cow\n- [ ] hang\n'


def _note(folder: Path, name='morning.md', kind='personal', stamps=LINE):
    folder.mkdir(parents=True, exist_ok=True)
    extra = f'stamps: {stamps}\n' if stamps else ''
    (folder / name).write_text(f'---\ntopic: Morning\nkind: {kind}\ncategory: General\n{extra}---\n\n{BODY}', encoding='utf-8')
    return folder / name


class DeepNoteToolsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        _note(self.data / 'notes')

    def test_read_note_shows_the_note_as_written(self):
        lib = librarian.Librarian.__new__(librarian.Librarian)
        lib.db = SimpleNamespace(notes_dir=self.data / 'notes')
        lib.budget = None
        lib.should_stop = None
        lib.deadline = None
        out = lib.run_tool('read_note', {'file': 'morning.md'})
        self.assertIn('[note: morning.md] Morning', out)
        self.assertIn(f'stamps: {LINE}', out)
        self.assertIn('<span data-ink="ember">16 kg</span>', out)
        self.assertIn('- [x] cat-cow', out)
        self.assertIn('No note named', lib.run_tool('read_note', {'file': 'nope.md'}))
        self.assertEqual(librarian.describe_call('read_note', {'file': 'morning.md'}), 'Reading the note morning.md')

    def test_propose_carries_the_instruction(self):
        started = []
        app = SimpleNamespace(state=SimpleNamespace(data_dir=self.data, jobs=SimpleNamespace(
            start=lambda kind, ids, force=False, opts=None: started.append(opts) or {'id': 1})))
        ask._propose_reformat(app, 'morning.md', '  make the steps   a checklist ')
        ask._propose_reformat(app, 'morning.md')
        self.assertEqual(started, [{'file': 'morning.md', 'instruction': 'make the steps a checklist'}, {'file': 'morning.md'}])

    def test_deep_system_prompt_gets_the_format_only_with_the_note_tools(self):
        seen = {}

        def agent(messages, provider, model_id, system_prompt, tools, run_tool, on_tool, **kw):
            seen[bool(tools and any(t['name'] == 'read_note' for t in tools))] = system_prompt
            return 'ok'
        db = Database(self.data / 'content_manager.db')
        db.close()
        from knowledge import ask_core
        from library import search
        with mock.patch.object(ai_client, 'ask_agent', agent):
            for propose in (None, lambda f, i='': 'queued'):
                ask_core.deep_answer(self.data / 'content_manager.db', 'anthropic', 'm', 'SYSTEM', [], 'q',
                                     item_index=search.EmbeddingIndex([]), aux_rows=[], aux_jobs=[], embed_key='',
                                     embed_base=None, propose=propose)
        self.assertTrue(seen[False].startswith('SYSTEM\n\n'))
        self.assertIn('Deep mode:', seen[False])
        self.assertTrue(seen[True].startswith('SYSTEM\n\n') and seen[True].endswith(note_format.contract()))


class ReformatFormatTest(unittest.TestCase):
    def test_prompt_has_the_format_instruction_and_stamps(self):
        with mock.patch.object(ai_client, 'complete_text_info', return_value=('{"body": "## A\\nx"}', False)) as m:
            out = tasks.reformat_note('Morning', BODY, 'General', ['General'], 'anthropic', 'm',
                                      instruction='highlight the weights', stamps=LINE)
        prompt = m.call_args.kwargs['prompt']
        self.assertIn('do it first: highlight the weights', prompt)
        self.assertIn(f'stamps: {LINE}', prompt)
        self.assertIn(note_format.contract(), prompt)
        self.assertIsNone(out['stamps'])                         # left out: the note keeps its stamps

    def test_parse_returns_clean_stamps(self):
        raw = json.dumps({'body': 'x', 'stamps': [{'k': 'sun', 'at': 'top', 'x': 99}, {'k': 'unicorn'}]})
        self.assertEqual(tasks.parse_reformat(raw, 'T', 'General', ['General'])['stamps'],
                         [{'k': 'sun', 'at': 'top', 'x': 40, 'y': 0, 's': 2, 'c': 'indigo', 'r': 0}])
        self.assertEqual(tasks.parse_reformat(json.dumps({'body': 'x', 'stamps': []}), 'T', 'General', ['General'])['stamps'], [])

    def test_job_passes_instruction_and_stamps_to_the_preview(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(db.close)
        p = _note(db.notes_dir)
        job = Job(id=1, kind='reformat', label='Reformat & classify', ids=[0], force=True,
                  opts={'file': p.name, 'instruction': 'make a checklist'})
        kind = KINDS['reformat']
        answer = json.dumps({'title': 'Morning', 'category': 'General', 'body': '## Steps\n- [ ] a',
                             'stamps': [{'k': 'kettlebell', 'at': 'Steps'}]})
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}), \
                mock.patch.object(ai_client, 'complete_text_info', return_value=(answer, False)) as m:
            items = kind.prepare(db, job)
            kind.persist(db, items[0], kind.run_item(job, items[0]), job)
        self.assertIn('make a checklist', m.call_args.kwargs['prompt'])
        _ev, data = job.ctx['finish_events'][0]
        self.assertEqual(data['instruction'], 'make a checklist')
        self.assertEqual(data['stamps'][0]['at'], 'Steps')
        self.assertIn(f'stamps: {LINE}', p.read_text(encoding='utf-8'))   # nothing written before Apply


class McpReplaceStampsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        Database(self.data / 'content_manager.db').close()
        self.path = _note(self.data / 'notes')
        p = mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'})
        p.start()
        self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def ask(self, **kw):
        return self.c.post('/api/notes/request', json={'topic': 'Morning', 'body': BODY + '\nmore', **kw}, headers=W)

    def approve(self, r):
        self.assertEqual(r.status_code, 200, r.text)
        return self.c.post(f"/api/jobs/request/{r.json()['id']}/approve", headers=W).json()

    def stamps(self):
        return knowledge.split_frontmatter(self.path.read_text(encoding='utf-8'))[0].get('stamps')

    def test_replace_keeps_or_sets_stamps(self):
        self.assertEqual(self.ask(stamps=[{'k': 'sun'}]).status_code, 400)        # stamps need a file
        self.approve(self.ask(file='morning.md'))
        self.assertEqual(self.stamps(), LINE)                                     # kept
        r = self.ask(file='morning.md', stamps=[{'k': 'sun', 'at': 'top', 'c': 'sun'}, {'k': 'nope'}])
        self.assertEqual(len(r.json()['stamps']), 1)                              # the confirm window can count them
        self.approve(r)
        self.assertEqual(note_format.parse_stamps(self.stamps()), [{'k': 'sun', 'at': 'top', 'x': -4, 'y': 0, 's': 2, 'c': 'sun', 'r': 0}])
        self.approve(self.ask(file='morning.md', stamps=[]))
        self.assertIsNone(self.stamps())                                          # [] removes them


class ContractEverywhereTest(unittest.TestCase):
    def test_mcp_tools_describe_the_format(self):
        from mcp_local import app
        tools = {t.name: t for t in asyncio.run(app.mcp.list_tools())}
        for name in ('read_note', 'save_note'):
            self.assertIn(note_format.contract(), tools[name].description)
        self.assertIn('stamps', tools['save_note'].inputSchema['properties'])

    def test_claude_code_mode_reads_the_format_and_lists_personal_notes(self):
        with tempfile.TemporaryDirectory() as td:
            db = SimpleNamespace(count_by_category=lambda: {'AI': 1}, count_items=lambda: 1,
                                 get_categories=lambda: [{'name': 'AI'}], notes_dir=Path(td), data_dir=Path(td))
            text = claude_code.system_prompt(db)
        self.assertTrue(text.endswith(note_format.contract()))
        self.assertIn('read_note it, then call save_note with file', text)
        self.assertIn('mcp__brainamon__list_personal_notes', claude_code.ALLOWED)


if __name__ == '__main__':
    unittest.main()
