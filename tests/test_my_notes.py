"""my_notes.py (plan 10) and the My Notes endpoints: categories, create, autosave, delete, the
Summarize and screenshot-digest jobs (model calls stubbed).

Run from the project root:  py -m unittest tests.test_my_notes -v
"""
import base64
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client, note_format
from knowledge import knowledge
from knowledge import my_notes
from knowledge import tasks
from core.db import Database
from server.app import create_app
from server.jobs import Job, KINDS

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class MyNotesCoreTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)

    def test_categories(self):
        self.assertTrue(my_notes.add_category(self.db, 'Training'))
        self.assertFalse(my_notes.add_category(self.db, 'training'))
        p = my_notes.create_note(self.db.notes_dir, 'Ideas', 'Work')
        self.assertEqual(my_notes.all_categories(self.db, self.db.notes_dir), ['General', 'Training', 'Work'])
        self.assertEqual(p.name, 'ideas.md')

    def test_save_summary_digest(self):
        p = my_notes.create_note(self.db.notes_dir, 'Plan', my_notes.ALL_CATEGORY)
        meta = my_notes.save_note(p, 'Plan v2', 'Work', 'Body text\n\n')
        self.assertEqual((meta['topic'], meta['category'], meta['kind']), ('Plan v2', 'Work', 'personal'))
        b = my_notes.replace_summary('Body\n\n## AI summary\n\nold', '- new')
        self.assertEqual(b, 'Body\n\n## AI summary\n\n- new\n')
        self.assertIn('## Screenshot digest — 2026', my_notes.append_digest('x', 'shot text', '2026-10-09T10:00:00'))
        self.assertEqual(my_notes.combine_digest([('a.png', 'A'), ('b.png', 'B')]), '--- a.png ---\nA\n\n--- b.png ---\nB')


class ReformatTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.p = my_notes.create_note(self.db.notes_dir, 'Messy', 'General')
        my_notes.save_note(self.p, 'Messy', 'General', 'random bits\nmore bits')

    def test_parse_reformat(self):
        raw = '{"title": "Tidy", "category": "work", "topics": ["a", "b"], "body": "## A\\ntext"}'
        out = tasks.parse_reformat(raw, 'Messy', 'General', ['General', 'Work'])
        self.assertEqual((out['title'], out['category'], out['topics']), ('Tidy', 'Work', ['a', 'b']))
        self.assertEqual(out['body'], '## A\ntext')
        bad = tasks.parse_reformat('{"category": "INVENTED", "body": "x"}', 'Messy', 'General', ['General'])
        self.assertEqual((bad['category'], bad['title']), ('General', 'Messy'))   # fallbacks
        heads = tasks.parse_reformat('{"body": "## One\\nx\\n## Two\\ny"}', 'Messy', 'General', ['General'])
        self.assertEqual(heads['topics'], ['One', 'Two'])                          # derived from headings
        for junk in ('no json at all', '{"body": "  "}'):
            with self.assertRaises(ValueError):
                tasks.parse_reformat(junk, 'Messy', 'General', ['General'])

    def test_reformat_note_calls_complete_text(self):
        with mock.patch.object(ai_client, 'complete_text_info', return_value=('{"body": "## A\\nx"}', False)) as ct:
            out = tasks.reformat_note('Messy', 'random bits', 'General', ['General'], 'anthropic', 'm')
        self.assertEqual(out['category'], 'General')
        self.assertEqual(ct.call_args.kwargs['max_tokens'], 8000)

    def test_reformat_refuses_a_cut_off_answer(self):
        with mock.patch.object(ai_client, 'complete_text_info', return_value=('{"body": "## A\\nx', True)):
            with self.assertRaisesRegex(ValueError, 'cut off'):
                tasks.reformat_note('Messy', 'random bits', 'General', ['General'], 'anthropic', 'm')

    def test_ask_caps_hold_note_sized_answers(self):
        import json
        from pathlib import Path
        self.assertGreaterEqual(ai_client._ASK_MAX_TOKENS, 4000)
        ask = json.loads((Path(__file__).resolve().parent.parent / 'knowledge' / 'prompts' / 'ask_quick.json')
                         .read_text(encoding='utf-8'))
        self.assertGreaterEqual(ask['limits']['list_max_tokens'], 8192)
        self.assertEqual(ai_client._ask_cap(ai_client.ASK_PROVIDER_ANTHROPIC, 4000), 8000)
        self.assertEqual(ai_client._ask_cap(ai_client.ASK_PROVIDER_LOCAL_OPENAI, 4000), 4000)

    def test_reformat_kind_proposes_but_never_writes(self):
        job = Job(id=1, kind='reformat', label='Reformat & classify', ids=[0], force=True,
                  opts={'file': self.p.name})
        kind = KINDS['reformat']
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}), \
                mock.patch.object(ai_client, 'complete_text_info',
                                  return_value=('{"title": "Tidy", "category": "General", "body": "## A\\ntext"}', False)):
            items = kind.prepare(self.db, job)
            result = kind.run_item(job, items[0])
            kind.persist(self.db, items[0], result, job)
        ev, data = job.ctx['finish_events'][0]
        self.assertEqual(ev, 'reformat_preview')
        self.assertEqual((data['file'], data['title'], data['body']), (self.p.name, 'Tidy', '## A\ntext'))
        _meta, body = knowledge.split_frontmatter(self.p.read_text(encoding='utf-8'))
        self.assertIn('random bits', body)          # the note on disk is unchanged

    def test_reformat_kind_refuses_empty_and_long(self):
        my_notes.save_note(self.p, 'Messy', 'General', '   ')
        job = Job(id=1, kind='reformat', label='x', ids=[0], force=True, opts={'file': self.p.name})
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}):
            with self.assertRaises(Exception):
                KINDS['reformat'].prepare(self.db, job)
        my_notes.save_note(self.p, 'Messy', 'General', 'x' * 20001)
        job = Job(id=2, kind='reformat', label='x', ids=[0], force=True, opts={'file': self.p.name})
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}):
            with self.assertRaises(Exception):
                KINDS['reformat'].prepare(self.db, job)


class MyNotesServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        Database(self.data / 'content_manager.db').close()
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),):
            p.start()
            self.addCleanup(p.stop)
        for k in KINDS.values():
            p = mock.patch.multiple(k, gap=0.0, error_gap=0.0)
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def wait(self):
        end = time.time() + 10
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.03)
        self.fail('job did not finish')

    def test_crud_and_jobs(self):
        self.c.post('/api/my-notes/categories', json={'name': 'Training'}, headers=W)
        self.assertIn('Training', self.c.get('/api/my-notes/categories').json()['categories'])
        n = self.c.post('/api/my-notes', json={'title': 'Knee plan', 'category': 'Training'}, headers=W).json()
        self.assertEqual(n['file'], 'knee-plan.md')
        self.c.put('/api/my-notes/knee-plan.md', json={'title': 'Knee plan', 'category': 'Training', 'body': 'Hip airplanes daily.'}, headers=W)
        self.assertEqual(self.c.get('/api/my-notes/knee-plan.md').json()['body'], 'Hip airplanes daily.')
        self.assertEqual([x['file'] for x in self.c.get('/api/my-notes?category=Training').json()], ['knee-plan.md'])
        self.assertEqual(self.c.get('/api/my-notes?category=Work').json(), [])
        # it is a note of the shared pool: Knowledge search finds it
        self.assertEqual(self.c.get('/api/notes').json()[0]['kind'], 'Personal')
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '- daily airplanes'):
            self.assertEqual(self.c.post('/api/my-notes/knee-plan.md/summarize', headers=W).status_code, 200)
            self.wait()
        self.assertIn('## AI summary\n\n- daily airplanes', self.c.get('/api/my-notes/knee-plan.md').json()['body'])
        img = base64.b64encode(b'png').decode()
        with mock.patch.object(ai_client, 'complete_vision', lambda *a, **k: 'comment text'):
            r = self.c.post('/api/my-notes/knee-plan.md/digest', json={'images': [{'name': 's.png', 'type': 'image/png', 'data': img}]}, headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            self.wait()
        self.assertIn('comment text', self.c.get('/api/my-notes/knee-plan.md').json()['body'])
        self.assertEqual(self.c.delete('/api/my-notes/knee-plan.md', headers=W).json(), {'ok': True})
        self.assertEqual(self.c.get('/api/my-notes/knee-plan.md').status_code, 404)

    def test_list_gives_the_note_card_head_and_words(self):
        self.c.post('/api/my-notes', json={'title': 'Knee plan', 'category': 'General'}, headers=W)
        body = '## Plan\n- [x] Hip airplanes daily\n' + '\n'.join(f'line {i}' for i in range(20))
        self.c.put('/api/my-notes/knee-plan.md', json={'title': 'Knee plan', 'category': 'General', 'body': body}, headers=W)
        saved = self.c.get('/api/my-notes/knee-plan.md').json()['body']
        row = self.c.get('/api/my-notes').json()[0]
        self.assertEqual(row['head'], note_format.head(saved))
        self.assertTrue(row['head'].startswith('## Plan\n- [x] Hip airplanes daily\nline 0'))
        self.assertEqual(row['head'].count('\n'), note_format.HEAD_LINES - 1)
        self.assertEqual(row['words'], note_format.word_count(saved))

    def test_reformat_route(self):
        self.c.post('/api/my-notes', json={'title': 'Knee plan', 'category': 'General'}, headers=W)
        self.c.put('/api/my-notes/knee-plan.md', json={'title': 'Knee plan', 'category': 'General', 'body': 'Hip airplanes daily.'}, headers=W)
        with mock.patch.object(ai_client, 'complete_text_info', return_value=('{"title": "Knee plan", "category": "General", "body": "## Plan\\nHip airplanes daily."}', False)):
            self.assertEqual(self.c.post('/api/my-notes/knee-plan.md/reformat', headers=W).status_code, 200)
            last = self.wait()
        self.assertEqual((last['kind'], last['state'], last['done']), ('reformat', 'finished', 1))
        self.assertEqual(self.c.get('/api/my-notes/knee-plan.md').json()['body'], 'Hip airplanes daily.')  # unchanged
        self.assertEqual(self.c.post('/api/my-notes/nope.md/reformat', headers=W).status_code, 404)


if __name__ == '__main__':
    unittest.main()
