from tests.test_ask_tool_stream import agent_from_stream
"""Mixed-category proposals: one review, atomic Writer apply, no live library or model calls."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client, ai_defaults
from core.db import Database
from knowledge import ask_core, claude_code
from mcp_local import jobs as mcp_jobs
from server.app import create_app
from server.jobs import AUTO_APPROVE_KEY
from server.routes import ask
from tests.test_server_ask import events

W = {'X-CM': '1'}


class CategoryBatchTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.add_category('AI  tools', '#123456')
        db.add_category('DESIGN', '#654321')
        self.ids = [db.add_item({'url': f'https://example.com/{i}', 'description': f'workflow {i}'})
                    for i in range(101)]
        db.close()
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(app, base_url='http://127.0.0.1:8765')
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        self.jm, self.writer = app.state.jobs, app.state.writer
        self.original = self.current()
        self.groups = [{'ids': self.ids[:2], 'category': 'AI  tools'},
                       {'ids': self.ids[2:3], 'category': 'DESIGN'}]

    def current(self):
        return self.writer.read(lambda db: {r['id']: r['category'] for r in db.get_items_by_ids(self.ids)})

    def propose(self, groups=None):
        return self.c.post('/api/items/categories/request', headers=W,
                           json={'groups': self.groups if groups is None else groups, 'source': 'Wiskit'})

    def answer(self, approve):
        req = self.jm.snapshot()['request']
        return self.c.post(f"/api/jobs/request/{req['id']}/{'approve' if approve else 'decline'}", headers=W)

    def test_all_groups_wait_then_apply_with_one_click_even_with_auto_approve(self):
        self.writer.call(lambda db: db.set_setting(AUTO_APPROVE_KEY, '1'))
        response = self.propose()
        self.assertEqual(response.status_code, 200, response.text)
        req = response.json()
        self.assertEqual((req['type'], req['state']), ('category_batch', 'pending'))
        self.assertTrue(req['require_approval'])
        self.assertEqual(len(req['entries']), 3)
        self.assertEqual(req['entries'][0]['title'], 'workflow 0')
        self.assertEqual(self.current(), self.original)
        published = []
        real = self.jm.hub.publish

        def publish(kind, data):
            if kind == 'items_changed':
                published.append((data['ids'], self.current()))
            real(kind, data)

        with mock.patch.object(self.jm.hub, 'publish', publish):
            result = self.answer(True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['moved'], 3)
        self.assertEqual(self.current()[self.ids[0]], 'AI  tools')
        self.assertEqual(self.current()[self.ids[2]], 'DESIGN')
        self.assertEqual(published, [(self.ids[:3], self.current())])

    def test_invalid_batch_never_reserves_or_partially_writes(self):
        invalid = [[], None, 'wrong', [{'ids': self.ids[:1], 'category': 'invented'}],
            [{'ids': [True], 'category': 'DESIGN'}], [{'ids': ['1'], 'category': 'DESIGN'}],
            [{'ids': [2 ** 64], 'category': 'DESIGN'}], [{'ids': [], 'category': 'DESIGN'}],
            [{'ids': self.ids, 'category': 'DESIGN'}], [{'ids': self.ids[:1], 'category': 'design'}],
            self.groups + [{'ids': self.ids[:1], 'category': 'DESIGN'}],
            self.groups + [{'ids': [999999], 'category': 'DESIGN'}],
            [{'ids': [self.ids[0], self.ids[0]], 'category': 'DESIGN'}]]
        for groups in invalid:
            with self.subTest(groups=groups):
                response = self.c.post('/api/items/categories/request', headers=W, json={'groups': groups})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIsNone(self.jm.snapshot()['request'])
                self.assertEqual(self.current(), self.original)

    def test_decline_defer_and_busy_do_not_apply(self):
        self.propose()
        self.assertEqual(self.propose().status_code, 409)
        note = self.c.post('/api/notes/request', headers=W, json={'topic': 'x', 'body': 'y'})
        self.assertEqual(note.status_code, 409)
        self.assertEqual(self.answer(False).json()['request']['state'], 'declined')
        self.propose()
        with self.jm._lock:
            self.jm.request['t0'] -= 24 * 60 * 60
        self.assertEqual(self.jm.snapshot()['request']['state'], 'pending')
        self.assertEqual(self.current(), self.original)
        self.assertEqual(self.answer(True).status_code, 200)

    def test_approval_revalidates_all_targets_before_any_update(self):
        self.propose()
        self.writer.call(lambda db: db.delete_category('DESIGN'))
        response = self.answer(True)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.jm.snapshot()['request']['state'], 'pending')
        self.assertEqual(self.current(), self.original)

    def test_missing_item_blocks_entire_approval(self):
        self.propose()
        def remove(db):
            db.conn.execute('DELETE FROM items WHERE id = ?', (self.ids[2],))
            db.conn.commit()
        self.writer.call(remove)
        before = self.current()
        self.assertEqual(self.answer(True).status_code, 400)
        self.assertEqual(self.current(), before)
        self.assertEqual(self.jm.snapshot()['request']['state'], 'pending')

    def test_write_failure_rolls_back_all_groups_and_preserves_request(self):
        self.propose()
        def trigger(db):
            db.conn.execute(f"CREATE TRIGGER fail_batch BEFORE UPDATE OF category ON items "
                            f"WHEN NEW.id = {self.ids[2]} BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
            db.conn.commit()
        self.writer.call(trigger)
        req = self.jm.snapshot()['request']
        with mock.patch.object(self.jm.hub, 'publish') as publish:
            with self.assertRaises(sqlite3.IntegrityError):
                self.jm.answer(req['id'], True)
            publish.assert_not_called()
        self.assertEqual(self.current(), self.original)
        self.assertEqual(self.jm.snapshot()['request']['state'], 'pending')
        self.writer.call(lambda db: db.conn.execute('DROP TRIGGER fail_batch'))
        self.assertEqual(self.answer(True).json()['moved'], 3)

    def test_skips_already_correct_items_and_reports_actual_changes(self):
        self.propose()
        self.writer.call(lambda db: db.set_field_bulk(self.ids[:1], 'category', 'AI  tools'))
        self.assertEqual(self.answer(True).json()['moved'], 2)
        self.assertEqual(self.propose().status_code, 400)  # now all three are already correct

    def test_quick_batches_25_items_and_rejects_ids_outside_context(self):
        rows = self.writer.read(lambda db: db.get_items_by_ids(self.ids[:26]))
        groups = [{'ids': self.ids[:12], 'category': 'AI  tools'},
                  {'ids': self.ids[12:25], 'category': 'DESIGN'}]

        def stream(*args, **kw):
            self.assertIn('propose_categories', [t['name'] for t in kw['tools']])
            bad = [{'ids': self.ids[26:27], 'category': 'DESIGN'}]
            self.assertTrue(kw['run_tool']('propose_categories', {'groups': bad}).startswith('Error:'))
            too_many = [{'ids': self.ids[:26], 'category': 'DESIGN'}]
            error = kw['run_tool']('propose_categories', {'groups': too_many})
            self.assertIn('evidence', error)
            kw['on_tool']('propose_categories', {'groups': groups})
            self.assertIn('25 item(s) across 2 categories', kw['run_tool']('propose_categories', {'groups': groups}))
            yield 'One batch is waiting for approval.'

        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)), \
                mock.patch.object(ask_core, 'fallback_rows', return_value=rows):
            result = self.run_mode('quick')
        self.assertEqual(result[-1][0], 'done', result)
        self.assertEqual(len(self.jm.snapshot()['request']['entries']), 25)
        self.assertEqual(self.current(), self.original)
        self.assertEqual(self.answer(True).json()['moved'], 25)

    def test_deep_batches_100_items_through_the_same_callback(self):
        groups = [{'ids': self.ids[:50], 'category': 'AI  tools'},
                  {'ids': self.ids[50:100], 'category': 'DESIGN'}]
        def agent(*args, tools, run_tool, on_tool, **kw):
            self.assertIn('propose_categories', [t['name'] for t in tools])
            for start in range(0, 100, 12):
                run_tool('read_items', {'ids': self.ids[start:min(start + 12, 100)]})
            self.assertIn('100 item(s) across 2 categories', run_tool('propose_categories', {'groups': groups}))
            return 'One batch is waiting.'
        with mock.patch.object(ai_client, 'ask_agent', agent), mock.patch.object(ask, '_refresh_resources'):
            result = self.run_mode('deep')
        self.assertEqual(result[-1][0], 'done', result)
        self.assertEqual(self.current(), self.original)
        self.assertEqual(self.answer(True).json()['moved'], 100)

    def run_mode(self, mode):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', None)):
            with self.c.stream('POST', '/api/ask', headers=W, json={'question': 'Categorize these workflows',
                              'mode': mode, 'provider': 'anthropic', 'model': 'm'}) as resp:
                return events(resp)

    def test_mcp_exposes_one_review_for_the_same_batch(self):
        groups = [{'ids': self.ids[:50], 'category': 'AI  tools'},
                  {'ids': self.ids[50:100], 'category': 'DESIGN'}]
        self.writer.call(lambda db: db.set_setting(AUTO_APPROVE_KEY, '1'))
        def transport(method, path, body=None):
            resp = self.c.request(method, path, headers=W, json=body)
            return resp.status_code, resp.json()
        with mock.patch.object(mcp_jobs, 'transport', transport), mock.patch.object(mcp_jobs, 'SOURCE', claude_code.SOURCE):
            out = mcp_jobs.set_categories(groups)
        self.assertIn('set_categories', claude_code.ASK_TOOLS)
        self.assertEqual(out['requested']['state'], 'pending')
        self.assertEqual(self.current(), self.original)
        self.assertEqual(self.answer(True).json()['moved'], 100)

    def test_batch_endpoint_is_guarded(self):
        self.assertEqual(self.c.post('/api/items/categories/request', json={'groups': self.groups}).status_code, 403)
        response = self.c.post('/api/items/categories/request', json={'groups': self.groups},
                               headers={**W, 'Host': 'attacker.example'})
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.jm.snapshot()['request'])
