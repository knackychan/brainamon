"""V6 jobs: the Describe job end to end, one-job-at-a-time, pause/stop, the SSE stream.

Run from the project root:  py -m unittest tests.test_server_jobs -v
The AI call is replaced by a stub; no network, no key needed beyond a fake env value.
"""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx
import uvicorn
from tests.auth_client import TestClient

from core import ai_client
from core.db import Database
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def _fake_vision(provider, model, *, prompt, images, max_tokens=2000):
    time.sleep(0.05)
    if 'FAIL' in prompt:
        raise RuntimeError('model refused')
    return f'described by {provider}/{model}'


class JobsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.set_setting('ai_model_jarvis', '{"provider":"anthropic","model":"claude-sonnet-4-6"}')
        self.ids = [db.add_item({'url': f'https://youtu.be/{i}', 'description': f'item {i}', 'type': 'Video'})
                    for i in range(4)]
        db.update_item(self.ids[0], {'ai_desc': 'already'})
        self.fail_id = db.add_item({'url': 'https://youtu.be/f', 'description': 'FAIL me'})
        db.close()
        patches = [mock.patch.object(ai_client, 'complete_vision', _fake_vision),
                   mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        for kind in ('describe',):          # speed the per-item pauses up for the tests
            from server.jobs import KINDS
            p = mock.patch.multiple(KINDS[kind], gap=0.0, error_gap=0.0)
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

    def test_preview_skips_described_unless_forced(self):
        p = self.c.post('/api/jobs/preview', json={'kind': 'describe', 'ids': self.ids}, headers=W).json()
        self.assertEqual((p['count'], p['asked'], p['provider'], p['key']), (3, 4, 'anthropic', True))
        p = self.c.post('/api/jobs/preview', json={'kind': 'describe', 'ids': self.ids, 'force': True}, headers=W).json()
        self.assertEqual(p['count'], 4)

    def test_describe_end_to_end(self):
        r = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': self.ids + [self.fail_id]}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['total'], 4)
        last = self._wait_idle()
        self.assertEqual((last['state'], last['done'], last['err']), ('finished', 3, 1))
        rows = {x['id']: x for x in self.c.get('/api/items').json()['items']}
        self.assertEqual(rows[self.ids[1]]['desc'], 'described by anthropic/claude-sonnet-4-6')
        self.assertEqual(rows[self.ids[0]]['desc'], 'already')          # skipped, not forced
        prog = self.c.get('/api/jobs/progress').json()
        states = {x['id']: x['state'] for x in prog['items']}
        self.assertEqual(states[self.fail_id], 'error')
        self.assertTrue(any(e['title'] == 'Describe item failed' for e in self.c.get('/api/console').json()))

    def test_describe_distinguishes_skipped_failed_and_described(self):
        def seed(db):
            bare = db.add_item({'url': 'https://youtu.be/bare', 'description': 'https://youtu.be/bare'})
            sentinel = db.add_item({'url': 'https://youtu.be/sentinel', 'description': 'Caption for sentinel'})
            db.update_item(sentinel, {'ai_desc': 'Keep existing', 'processed': True})
            return bare, sentinel
        bare, sentinel = self.c.app.state.writer.call(seed)
        def model(*args, **kwargs):
            if 'Caption for sentinel' in kwargs['prompt']:
                return 'NO_CONTENT'
            return _fake_vision(*args, **kwargs)
        with mock.patch.object(ai_client, 'complete_vision', side_effect=model) as ai:
            r = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': [bare, sentinel, self.ids[1], self.fail_id], 'force': True}, headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            last = self._wait_idle()
        self.assertEqual((last['done'], last['skipped'], last['err']), (1, 2, 1))
        self.assertEqual(ai.call_count, 3)
        rows = self.c.app.state.writer.call(lambda db: [db.get_item(bare), db.get_item(sentinel)])
        self.assertFalse(rows[0]['ai_desc'])
        self.assertEqual(rows[1]['ai_desc'], 'Keep existing')
        progress = self.c.get('/api/jobs/progress').json()['items']
        self.assertEqual({x['id']: x['state'] for x in progress}[bare], 'skipped')
        self.assertIn('Nothing to describe yet', next(x['step'] for x in progress if x['id'] == bare))

    def test_empty_item_skips_even_without_an_ai_key(self):
        bare = self.c.app.state.writer.call(lambda db: db.add_item({'url': 'https://youtu.be/empty', 'description': 'https://youtu.be/empty'}))
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch.object(ai_client, 'complete_vision') as ai:
            r = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': [bare]}, headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            last = self._wait_idle()
        self.assertEqual((last['done'], last['skipped'], last['err']), (0, 1, 0))
        ai.assert_not_called()

    def test_existing_sentinel_is_not_done_or_overwritten(self):
        def seed(db):
            item = db.add_item({'url': 'https://youtu.be/marker', 'description': 'https://youtu.be/marker'})
            db.update_item(item, {'ai_desc': ' NO_CONTENT ', 'processed': True})
            return item
        item = self.c.app.state.writer.call(seed)
        preview = self.c.post('/api/jobs/preview', json={'kind': 'describe', 'ids': [item]}, headers=W).json()
        self.assertEqual(preview['count'], 1)
        row = next(r for r in self.c.get('/api/items').json()['items'] if r['id'] == item)
        self.assertFalse(row['ai'])
        self.assertTrue(row['nd'] & 2)
        self.assertNotEqual(row['desc'], ' NO_CONTENT ')
        self.assertNotEqual(row['title'].strip().upper(), 'NO_CONTENT')
        self.c.post('/api/jobs', json={'kind': 'describe', 'ids': [item]}, headers=W)
        last = self._wait_idle()
        self.assertEqual((last['done'], last['skipped'], last['err']), (0, 1, 0))
        self.assertEqual(self.c.app.state.writer.call(lambda db: db.get_item(item)['ai_desc']), ' NO_CONTENT ')

    def test_describe_reads_saved_report_and_transcript_files(self):
        item = self.c.app.state.writer.call(lambda db: db.add_item({'url': 'https://youtu.be/files'}))
        folder = self.data / 'items' / str(item)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'report.md').write_text('Specific report', encoding='utf-8')
        (folder / 'transcript.txt').write_text('Specific transcript', encoding='utf-8')
        with mock.patch.object(ai_client, 'complete_vision', return_value='Real description') as ai:
            self.c.post('/api/jobs', json={'kind': 'describe', 'ids': [item]}, headers=W)
            last = self._wait_idle()
        self.assertEqual((last['done'], last['skipped'], last['err']), (1, 0, 0))
        self.assertIn('Specific report', ai.call_args.kwargs['prompt'])
        self.assertIn('Specific transcript', ai.call_args.kwargs['prompt'])

    def test_one_job_at_a_time_and_stop(self):
        slow = mock.patch.object(ai_client, 'complete_vision',
                                 lambda *a, **k: (time.sleep(0.3), 'x')[1])
        slow.start()
        self.addCleanup(slow.stop)
        self.assertEqual(self.c.post('/api/jobs', json={'kind': 'describe', 'ids': self.ids, 'force': True},
                                     headers=W).status_code, 200)
        busy = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': self.ids}, headers=W)
        self.assertEqual(busy.status_code, 409)
        self.assertIn('One job at a time', busy.json()['detail'])
        self.assertEqual(self.c.post('/api/jobs/pause', headers=W).json()['current']['state'], 'paused')
        self.assertEqual(self.c.post('/api/jobs/resume', headers=W).json()['current']['state'], 'running')
        self.c.post('/api/jobs/stop', headers=W)
        last = self._wait_idle()
        self.assertEqual(last['state'], 'stopped')
        self.assertLess(last['done'], 4)

    def test_errors_are_user_facing(self):
        nothing = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': [self.ids[0]]}, headers=W)
        self.assertEqual(nothing.status_code, 400)
        self.assertIn('already have a description', nothing.json()['detail'])
        self.assertEqual(self.c.post('/api/jobs', json={'kind': 'nope', 'ids': [1]}, headers=W).status_code, 400)
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            nokey = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': self.ids}, headers=W)
            self.assertEqual(nokey.status_code, 200)
            last = self._wait_idle()
        self.assertEqual(last['err'], 3)
        self.assertIn('API key', last['detail'])
        self.assertIn('API key', self.c.get('/api/jobs/progress').json()['items'][0]['error'])
        self.assertIsNone(self.c.get('/api/jobs').json()['current'])    # the line is free again


class EventStreamTest(unittest.TestCase):
    """A real uvicorn server on a free port: the SSE stream says hello, then streams job events."""

    def test_stream(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            data = Path(td)
            db = Database(data / 'content_manager.db')
            db.set_setting('ai_model_jarvis', '{"provider":"anthropic","model":"claude-sonnet-4-6"}')
            iid = db.add_item({'url': 'https://youtu.be/synthetic', 'description': 'd'})
            db.close()
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            app = create_app(data_dir=data, cloud_dir=data / 'test-cloud', port=port, web_dist=data / 'x', cards_dir=data / 'x')
            srv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
            t = threading.Thread(target=srv.run, daemon=True)
            t.start()
            while not srv.started:
                time.sleep(0.02)
            base = f'http://127.0.0.1:{port}'
            seen = []
            try:
                with mock.patch.object(ai_client, 'complete_vision', _fake_vision), \
                        mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}):
                    from core import local_auth
                    auth = local_auth.headers(port)
                    with httpx.Client(base_url=base, timeout=10, headers=auth) as c:
                        self.assertEqual(httpx.get(base + '/api/events', timeout=2).status_code, 403)
                        with c.stream('GET', '/api/events') as r:
                            self.assertEqual(r.headers['content-type'].split(';')[0], 'text/event-stream')
                            ev = None
                            for line in r.iter_lines():
                                if line.startswith('event: '):
                                    ev = line[7:]
                                elif line.startswith('data: ') and ev:
                                    seen.append((ev, json.loads(line[6:])))
                                    if ev == 'hello':
                                        c2 = httpx.Client(base_url=base, timeout=10, headers=auth)
                                        c2.post('/api/jobs', json={'kind': 'describe', 'ids': [iid]}, headers=W)
                                        c2.close()
                                    if ev == 'job' and seen[-1][1]['last'] and seen[-1][1]['current'] is None:
                                        break
            finally:
                srv.should_exit = True
                t.join(5)
            kinds = [k for k, _ in seen]
            self.assertEqual(kinds[0], 'hello')
            for k in ('job', 'job_item', 'items_changed', 'log'):
                self.assertIn(k, kinds)
            self.assertIn({'ids': [iid]}, [d for k, d in seen if k == 'items_changed'])


if __name__ == '__main__':
    unittest.main()
