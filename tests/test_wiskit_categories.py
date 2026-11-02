from tests.test_ask_tool_stream import agent_from_stream
"""Desktop Deep category proposals use CAT-02 and always wait for a click. No live data or API calls."""
import json
import os
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client, ai_defaults
from core.db import Database, ReadOnlyDatabase
from knowledge import ask_core, claude_code, librarian
from library import search
from server.app import create_app
from server.jobs import AUTO_APPROVE_KEY
from server.routes import ask
from tests.test_server_ask import events

W = {'X-CM': '1'}
TARGET = 'AI  workflows'


class WiskitCategoriesTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.add_category(TARGET, '#123456')
        self.ids = [db.add_item({'url': f'https://example.com/{i}', 'description': f'AI workflow {i}'})
                    for i in range(2)]
        self.original = [r['category'] for r in db.get_items_by_ids(self.ids)]
        db.close()
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def categories(self):
        return self.app.state.writer.call(lambda db: [r['category'] for r in db.get_items_by_ids(self.ids)])

    def proposal(self):
        return ask._propose_category(self.app, self.ids, TARGET)

    def answer(self, approve):
        req = self.app.state.jobs.snapshot()['request']
        return self.c.post(f"/api/jobs/request/{req['id']}/{'approve' if approve else 'decline'}", headers=W)

    def test_deep_route_queues_without_writing_even_with_auto_approve_then_click_applies(self):
        self.app.state.writer.call(lambda db: db.set_setting(AUTO_APPROVE_KEY, '1'))

        def agent(messages, provider, model, *, system_prompt, tools, run_tool, on_tool, **kw):
            self.assertIn('propose_category', [t['name'] for t in tools])
            self.assertIn(json.dumps(TARGET), system_prompt)  # exact, empty category included
            self.assertIn('suggestions', system_prompt)
            self.assertIsInstance(run_tool.__self__.db, ReadOnlyDatabase)
            self.assertIn(f'[id {self.ids[0]}]', run_tool('read_items', {'ids': self.ids}))
            args = {'ids': self.ids, 'category': TARGET}
            on_tool('propose_category', args)
            out = run_tool('propose_category', args)
            self.assertIn('Nothing has changed', out)
            return f'Approval is waiting in Brainamon for [id {self.ids[0]}].'

        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', None)), \
                mock.patch.object(ai_client, 'ask_agent', agent), \
                mock.patch.object(ask, '_refresh_resources'):
            with self.c.stream('POST', '/api/ask', json={
                    'question': 'Categorize these AI workflows for approval', 'provider': 'anthropic',
                    'model': 'm', 'mode': 'deep'}, headers=W) as resp:
                self.assertEqual(resp.status_code, 200)
                ev = events(resp)
        self.assertEqual(ev[-1][0], 'done', ev)
        self.assertTrue(any(k == 'progress' and 'approval' in v['line'] for k, v in ev))
        req = self.app.state.jobs.snapshot()['request']
        self.assertEqual((req['type'], req['source'], req['state']), ('category', 'Wiskit', 'pending'))
        self.assertTrue(req['require_approval'])
        self.assertEqual(self.categories(), self.original)
        result = self.answer(True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['moved'], 2)
        self.assertEqual(self.categories(), [TARGET, TARGET])

    def test_decline_and_defer_never_write(self):
        self.assertIn('Nothing has changed', self.proposal())
        self.assertEqual(self.answer(False).json()['request']['state'], 'declined')
        self.assertEqual(self.categories(), self.original)
        self.proposal()
        jm = self.app.state.jobs
        with jm._lock:
            jm.request['t0'] -= 24 * 60 * 60
        self.assertEqual(jm.snapshot()['request']['state'], 'pending')
        self.assertEqual(self.categories(), self.original)
        self.assertEqual(self.answer(True).status_code, 200)
        self.assertEqual(self.categories(), [TARGET, TARGET])

    def test_invalid_model_arguments_do_not_queue_or_write(self):
        for ids, category in [([], TARGET), ([999999], TARGET), (self.ids, 'invented'),
                              (self.ids, TARGET.lower()), ('12', TARGET), ([True], TARGET),
                              ([1.5], TARGET), ([str(self.ids[0])], TARGET), ([2 ** 64], TARGET),
                              (self.ids, None)]:
            with self.subTest(ids=ids, category=category):
                self.assertTrue(ask._propose_category(self.app, ids, category).startswith('Error:'))
                self.assertIsNone(self.app.state.jobs.snapshot()['request'])
                self.assertEqual(self.categories(), self.original)

    def test_busy_keeps_the_first_proposal(self):
        self.proposal()
        first = self.app.state.jobs.snapshot()['request']
        self.assertTrue(self.proposal().startswith('Error:'))
        self.assertEqual(self.app.state.jobs.snapshot()['request'], first)
        self.assertEqual(self.categories(), self.original)

    def test_deleted_target_at_approval_rejects_without_writing(self):
        self.proposal()
        self.app.state.writer.call(lambda db: db.delete_category(TARGET))
        response = self.answer(True)
        self.assertEqual(response.status_code, 400)
        self.assertIn('No category named', response.text)
        self.assertEqual(self.app.state.jobs.snapshot()['request']['state'], 'pending')
        self.assertEqual(self.categories(), self.original)

    def test_tool_is_only_advertised_when_category_callback_exists(self):
        seen = []

        def agent(messages, provider, model, *, system_prompt, tools, run_tool, on_tool, **kw):
            seen.append(([t['name'] for t in tools], system_prompt))
            if 'propose_category' not in seen[-1][0]:
                self.assertIn('not available', run_tool('propose_category', {'ids': self.ids, 'category': TARGET}))
            return 'ok'

        with mock.patch.object(ai_client, 'ask_agent', agent):
            for callback in (None, lambda ids, category: 'queued'):
                ask_core.deep_answer(self.app.state.db_path, 'anthropic', 'm', 'SYSTEM', [], 'q',
                    item_index=search.EmbeddingIndex([]), aux_rows=[], aux_jobs=[], embed_key='',
                    embed_base=None, propose_category=callback)
        self.assertTrue(seen[0][1].startswith('SYSTEM\n\n'))
        self.assertIn('Deep mode:', seen[0][1])
        self.assertNotIn('propose_category', seen[0][0])
        self.assertIn('propose_category', seen[1][0])
        self.assertNotIn('read_note', seen[1][0])
        self.assertNotIn('propose_category', [t['name'] for t in librarian.TOOLS])
        self.assertNotIn('propose_category', [t['name'] for t in librarian.PROPOSE_TOOLS])

    def test_quick_25_item_batch_uses_the_shared_approval_and_checks_context_ids(self):
        def setup(db):
            db.set_setting(AUTO_APPROVE_KEY, '1')
            ids = [db.add_item({'url': f'https://example.com/quick/{i}', 'description': f'AI workflow {i}'})
                   for i in range(25)]
            return db.get_items_by_ids(ids)
        rows = self.app.state.writer.call(setup)
        ids = [r['id'] for r in rows]

        def stream(messages, provider, model, **kw):
            self.assertEqual(kw['tools'], librarian.TOOLS + librarian.PROPOSE_TOOLS + librarian.CATEGORY_TOOLS + librarian.CANVAS_TOOLS)
            self.assertIn(json.dumps(TARGET), kw['system_prompt'])
            self.assertIn('research', kw['system_prompt'].lower())
            for bad in ([self.ids[0]], ids + ids[:1], [True]):
                self.assertTrue(kw['run_tool']('propose_category', {'ids': bad, 'category': TARGET}).startswith('Error:'))
            yield 'Preparing a proposal'
            kw['on_reset']()
            kw['on_tool']('propose_category', {'ids': ids, 'category': TARGET})
            self.assertIn('Nothing has changed', kw['run_tool']('propose_category', {'ids': ids, 'category': TARGET}))
            yield 'Approval is waiting.'

        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', None)), \
                mock.patch.object(ask_core, 'fallback_rows', return_value=rows), \
                mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            with self.c.stream('POST', '/api/ask', json={'question': 'Categorize these workflows',
                    'provider': 'anthropic', 'model': 'm', 'mode': 'quick'}, headers=W) as resp:
                ev = events(resp)
        self.assertEqual(ev[-1][0], 'done', ev)
        self.assertEqual(ev[-1][1]['text'], 'Approval is waiting.')
        self.assertIn('reset', [kind for kind, _ in ev])
        req = self.app.state.jobs.snapshot()['request']
        self.assertEqual(req['ids'], ids)
        self.assertEqual(req['state'], 'pending')
        read = lambda: self.app.state.writer.call(lambda db: db.get_items_by_ids(ids))
        self.assertTrue(all(r['category'] != TARGET for r in read()))
        self.assertEqual(self.answer(True).json()['moved'], 25)
        self.assertTrue(all(r['category'] == TARGET for r in read()))

    def test_quick_followup_keeps_25_cited_items(self):
        ids = self.app.state.writer.call(lambda db: [db.add_item({
            'url': f'https://example.com/carry/{i}', 'description': 'workflow'}) for i in range(25)])
        with closing(ReadOnlyDatabase(self.app.state.db_path)) as rd:
            history = [{'role': 'assistant', 'content': ' '.join(f'[id {i}]' for i in ids)}]
            turn = ask_core.build_turn(rd, 'Apply these category assignments', [], history)
        self.assertEqual([r['id'] for r in turn['sources']], ids)

    def test_quick_stop_prevents_category_tool_execution_and_closes_stream(self):
        stop, closed = threading.Event(), []

        def stream(*args, **kw):
            try:
                stop.set()
                kw['on_tool']('propose_category', {'ids': self.ids, 'category': TARGET})
                kw['run_tool']('propose_category', {'ids': self.ids, 'category': TARGET})
                yield 'should not happen'
            finally:
                closed.append(True)

        with closing(ReadOnlyDatabase(self.app.state.db_path)) as rd, \
                mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            out = ask._quick(self.app, rd, 'anthropic', 'm', [], 'categorize workflows', 25, '',
                             '', None, None, None, lambda *a: None, stop)
        self.assertIsNone(out[0])
        self.assertEqual(closed, [True])
        self.assertIsNone(self.app.state.jobs.snapshot()['request'])

    def test_claude_code_uses_shared_category_policy_and_always_waits(self):
        self.app.state.writer.call(lambda db: db.set_setting(AUTO_APPROVE_KEY, '1'))
        with closing(ReadOnlyDatabase(self.app.state.db_path)) as rd:
            prompt = claude_code.system_prompt(rd)
            self.assertIn(librarian.category_instructions(rd, 'set_category'), prompt)
        req = self.app.state.jobs.ask_category(self.ids, TARGET, source=claude_code.SOURCE)
        self.assertEqual(req['state'], 'pending')
        self.assertTrue(req['require_approval'])
        self.assertEqual(self.categories(), self.original)


if __name__ == '__main__':
    unittest.main()
