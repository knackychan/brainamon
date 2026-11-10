"""Local MCP server, job-start tools (projects/mcp-local/PLAN.md Part B).

Run from the project root:  py -m unittest tests.test_mcp_jobs -v
The app runs in-process (TestClient); the AI call is a stub; no network, no real key.
"""
import asyncio
import os
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core.db import Database
from mcp_local import jobs
from server.app import create_app
from server.jobs import KINDS

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def _fake_vision(provider, model, *, prompt, images, max_tokens=2000):
    return f'described by {provider}/{model}'


class JobToolsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.set_setting('ai_model_jarvis', json.dumps({'provider': 'anthropic', 'model': 'synthetic-model'}))
        self.ids = [db.add_item({'url': f'https://youtu.be/{i}', 'description': f'item {i}', 'type': 'Video'})
                    for i in range(4)]
        db.update_item(self.ids[0], {'ai_desc': 'already'})
        db.close()
        for p in (mock.patch.object(jobs, 'BASE', 'http://127.0.0.1:1'),   # never the running app
                  mock.patch.object(ai_client, 'complete_vision', _fake_vision),
                  mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}),
                  mock.patch.multiple(KINDS['describe'], gap=0.0, error_gap=0.0)):
            p.start()
            self.addCleanup(p.stop)
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        self.sent = []

        def transport(method, path, body=None):
            self.sent.append((method, path, body))
            r = self.c.request(method, path, json=body, headers=W)
            return r.status_code, r.json()

        p = mock.patch.object(jobs, 'transport', transport)
        p.start()
        self.addCleanup(p.stop)

    def _wait_idle(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.05)
        self.fail('job did not finish')

    def _approve(self):
        """Fred clicks Start in the app."""
        req = self.c.get('/api/jobs').json()['request']
        r = self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W)
        self.assertEqual(r.status_code, 200, r.text)

    def test_preview_counts_only_what_is_missing(self):
        p = jobs.preview('describe', self.ids)
        self.assertEqual((p['count'], p['asked'], p['provider']), (3, 4, 'anthropic'))

    def test_nothing_to_do(self):
        with self.assertRaises(jobs.JobToolError):
            jobs.start('describe', [self.ids[0]], 0)

    def test_only_the_four_kinds_and_bounded_ids(self):
        for kind in ('export_obsidian', 'export_csv', 'note', 'download', 'nope'):
            with self.assertRaises(jobs.JobToolError):
                jobs.preview(kind, self.ids)
        with self.assertRaises(jobs.JobToolError):
            jobs.preview('describe', [])
        with self.assertRaises(jobs.JobToolError):
            jobs.preview('describe', list(range(jobs.MAX_IDS + 1)))
        with self.assertRaises(jobs.JobToolError):
            jobs.control('delete')

    def test_start_needs_the_matching_count(self):
        with self.assertRaises(jobs.JobToolError):
            jobs.start('describe', self.ids, 99)
        self.assertFalse([s for s in self.sent if s[0] == 'POST' and s[1] in ('/api/jobs', '/api/jobs/request')])

    def test_start_only_asks_and_never_forces(self):
        out = jobs.start('describe', self.ids, 3)
        self.assertEqual((out['requested']['state'], out['preview']['count']), ('pending', 3))
        self.assertIsNone(jobs.status()['current'])                      # nothing started without the click
        self.assertFalse([s for s in self.sent if s[:2] == ('POST', '/api/jobs')])
        self._approve()
        last = self._wait_idle()
        self.assertEqual((last['state'], last['done']), ('finished', 3))
        self.assertEqual(jobs.status()['request']['state'], 'approved')
        rows = {x['id']: x for x in self.c.get('/api/items').json()['items']}
        self.assertEqual(rows[self.ids[0]]['desc'], 'already')          # finished item untouched
        self.assertTrue(rows[self.ids[1]]['desc'].startswith('described by'))
        self.assertTrue(all(not (b or {}).get('force') for _, _, b in self.sent))

    def test_declined_request_starts_nothing(self):
        req = jobs.start('describe', self.ids, 3)['requested']
        self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)
        s = jobs.status()
        self.assertEqual((s['request']['state'], s['current'], s['last']), ('declined', None, None))

    def test_save_note_only_asks(self):
        out = jobs.save_note('Knee plan', f'Body [id {self.ids[1]}].', [self.ids[1]])
        self.assertEqual((out['requested']['type'], out['requested']['state']), ('note', 'pending'))
        self.assertEqual(self.sent[-1][:2], ('POST', '/api/notes/request'))
        self.assertEqual(self.sent[-1][2]['source'], jobs.SOURCE)
        notes = self.data / 'notes'
        self.assertFalse(notes.exists() and any(notes.glob('*.md')))
        self._approve()
        self.assertEqual(len(list(notes.glob('*.md'))), 1)

    def test_set_category_only_asks_then_moves_on_click(self):
        self.c.app.state.writer.call(lambda db: db.add_category('NSFW', '#f00'))
        self.c.post('/api/items/bulk', json={'action': 'set_category', 'ids': [self.ids[0]], 'value': 'NSFW'}, headers=W)
        with self.assertRaises(jobs.JobToolError):
            jobs.set_category(self.ids, 'Nope')                                  # unknown category
        with self.assertRaises(jobs.JobToolError):
            jobs.set_category([self.ids[0]], 'NSFW')                            # already there
        out = jobs.set_category(self.ids, 'NSFW')
        self.assertEqual((out['requested']['type'], out['requested']['state']), ('category', 'pending'))
        self.assertEqual(out['requested']['ids'], self.ids[1:])                 # the item already in NSFW is left out
        cats = lambda: {x['id']: x['cat'] for x in self.c.get('/api/items').json()['items']}
        self.assertNotEqual(cats()[self.ids[1]], 'NSFW')                        # nothing moved without the click
        self._approve()
        self.assertTrue(all(cats()[i] == 'NSFW' for i in self.ids))

    def test_wiskit_claude_code_categories_wait_even_with_auto_approve(self):
        from knowledge import claude_code
        from server.jobs import AUTO_APPROVE_KEY
        self.c.app.state.writer.call(lambda db: (db.add_category('TARGET', '#123456'),
                                                db.set_setting(AUTO_APPROVE_KEY, '1')))
        with mock.patch.object(jobs, 'SOURCE', claude_code.SOURCE):
            out = jobs.set_category(self.ids, 'TARGET')
        self.assertEqual(out['requested']['state'], 'pending')
        self.assertTrue(out['requested']['require_approval'])
        rows = self.c.app.state.writer.call(lambda db: db.get_items_by_ids(self.ids))
        self.assertTrue(all(r['category'] != 'TARGET' for r in rows))

    def test_second_request_is_busy_and_stop_works(self):
        slow = mock.patch.object(ai_client, 'complete_vision', lambda *a, **k: (time.sleep(0.3), 'x')[1])
        slow.start()
        self.addCleanup(slow.stop)
        jobs.start('describe', self.ids, 3)
        with self.assertRaises(jobs.JobToolError) as ctx:
            jobs.start('describe', self.ids[3:], 1)      # the first request is still waiting
        self.assertIn('Busy', str(ctx.exception))
        self._approve()
        self.assertEqual(jobs.status()['current']['kind'], 'describe')
        jobs.control('stop')
        self._wait_idle()

    def test_status_keeps_item_failures_in_recent_errors(self):
        def bad_image(*a, **k):
            raise RuntimeError('not a valid image')
        with mock.patch.object(ai_client, 'complete_vision', bad_image):
            jobs.start('describe', self.ids, 3)
            self._approve()
            last = self._wait_idle()
        self.assertEqual((last['done'], last['err']), (0, 3))
        recent = jobs.status()['recent_errors']
        failed = {e['item_id'] for e in recent if 'item_id' in e}
        self.assertTrue(set(self.ids[1:]) <= failed, recent)
        self.assertTrue(all('not a valid image' in e['error'] for e in [e for e in recent if 'item_id' in e][-3:]))

    def test_app_not_running(self):
        with mock.patch.object(jobs, 'transport', jobs._http), \
                mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('refused')):
            with self.assertRaises(jobs.AppNotRunning):
                jobs.status()


class ToolSetTest(unittest.TestCase):
    def test_tool_names(self):
        from mcp_local import app
        names = {t.name for t in asyncio.run(app.mcp.list_tools())}
        self.assertEqual(names, {
            'library_stats', 'search_library', 'list_items', 'show_item', 'read_item_file', 'list_notes',
            'search_notes', 'read_note', 'list_personal_notes', 'note_categories', 'job_status', 'preview_job', 'start_job', 'control_job', 'save_note', 'set_category', 'set_categories',
            'list_canvases', 'read_canvas', 'list_frames', 'set_canvas', 'list_topics', 'read_topic'})
        for name in names:
            for verb in ('delete', 'remove', 'overwrite', 'erase', 'drop', 'wipe', 'force', 'write',
                         'update', 'edit', 'rename', 'move'):
                self.assertNotIn(verb, name)


if __name__ == '__main__':
    unittest.main()
