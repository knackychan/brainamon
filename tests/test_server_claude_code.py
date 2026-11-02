"""Wiskit's Claude Code mode through the server: the Ask stream, chats, Stop, Settings > Claude Code, with a
fake CLI (tests/fake_claude.py). No network, no login, no API key used.

Run from the project root:  py -m unittest tests.test_server_claude_code -v
"""
import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core.db import Database
from knowledge import ask_core
from knowledge import claude_code
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
FAKE = str(Path(__file__).with_name('fake_claude.py'))


def events(resp):
    out, ev = [], None
    for line in resp.iter_lines():
        if line.startswith('event:'):
            ev = line.split(':', 1)[1].strip()
        elif line.startswith('data:') and ev:
            out.append((ev, json.loads(line.split(':', 1)[1])))
            ev = None
    return out


class ClaudeCodeServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://x/1', 'description': 'Knee prehab with hip airplanes', 'category': 'SPORT'})
        db.set_setting(claude_code.PATH_KEY, FAKE)
        db.set_setting(claude_code.ENABLED_KEY, '1')
        db.close()
        self.log = self.data / 'calls.jsonl'

        def no_key_check(*a, **k):
            raise AssertionError('Claude Code mode must not check API keys')
        for p in (mock.patch.object(claude_code, 'launcher', lambda path: [sys.executable, FAKE]),
                  mock.patch.object(claude_code, 'WORK_DIR', self.data / 'work'),
                  mock.patch.object(claude_code.app_paths, 'ERROR_LOG', self.data / 'error_log.txt'),
                  mock.patch.object(claude_code, 'available', lambda: True),
                  mock.patch.object(ask_core, 'provider_ready', no_key_check),
                  mock.patch.dict(os.environ, {'FAKE_CLAUDE_LOG': str(self.log), 'FAKE_CLAUDE_MODE': 'ok'})):
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text(encoding='utf-8').splitlines()] if self.log.exists() else []

    def ask(self, **body):
        body = {'question': 'knee prehab', 'mode': 'claude_code', 'provider': 'anthropic', 'model': 'm', **body}
        with self.c.stream('POST', '/api/ask', json=body, headers=W) as r:
            self.assertEqual(r.status_code, 200)
            return events(r)

    def test_options_flag(self):
        with mock.patch.object(ask_core, 'provider_ready', lambda p, m: (None, None, None)):
            self.assertTrue(self.c.get('/api/ask/options').json()['claude_code'])
            self.c.put('/api/claude-code', json={'enabled': False}, headers=W)
            self.assertFalse(self.c.get('/api/ask/options').json()['claude_code'])

    def test_answer_streams_and_keeps_the_session(self):
        ev = self.ask()
        kinds = [k for k, _ in ev]
        self.assertEqual(kinds[:2], ['start', 'context'])
        self.assertIn('reset', kinds)
        self.assertIn(('progress', {'line': 'Claude Code · search_library: knee prehab'}), ev)
        done = ev[-1][1]
        self.assertEqual(kinds[-1], 'done')
        self.assertEqual(done['text'], 'Do the hip airplanes [id 1].')
        self.assertEqual(done['cited'], [self.a])
        self.assertEqual([s['id'] for s in done['sources']], [self.a])
        slug = done['chat']['slug']
        chat = self.c.get(f'/api/chats/{slug}').json()
        first = self.calls()[0]['argv']
        sid = first[first.index('--session-id') + 1]
        self.assertEqual(chat['claude_session'], sid)
        self.assertEqual(len(chat['history']), 2)
        self.ask(chat=slug, question='and the second one?')
        second = self.calls()[1]['argv']
        self.assertEqual(second[second.index('--resume') + 1], sid)
        self.c.post(f'/api/chats/{slug}/clear', headers=W)
        self.assertEqual(self.c.get(f'/api/chats/{slug}').json()['claude_session'], '')

    def test_model_setting_reaches_the_command(self):
        self.assertEqual(self.c.put('/api/claude-code', json={'model': 'sonnet'}, headers=W).json()['model'], 'sonnet')
        self.ask()
        argv = self.calls()[0]['argv']
        self.assertEqual(argv[argv.index('--model') + 1], 'sonnet')

    def test_off_missing_or_failing_is_an_error_event(self):
        self.c.put('/api/claude-code', json={'enabled': False}, headers=W)
        ev = self.ask()
        self.assertEqual(ev[-1][0], 'error')
        self.assertIn('Turn on Claude Code', ev[-1][1]['message'])
        self.assertEqual(self.calls(), [])
        self.c.put('/api/claude-code', json={'enabled': True}, headers=W)
        os.environ['FAKE_CLAUDE_MODE'] = 'logged_out'
        ev = self.ask()
        self.assertEqual(ev[-1][0], 'error')
        self.assertIn('not logged in', ev[-1][1]['message'])
        self.assertIn('not logged in', (self.data / 'error_log.txt').read_text(encoding='utf-8'))
        self.assertTrue(all(not c.get('message_count') for c in self.c.get('/api/chats').json()['chats']))

    def test_stop_saves_nothing(self):
        os.environ['FAKE_CLAUDE_MODE'] = 'slow'
        from server.routes import ask as ask_route
        req = types.SimpleNamespace(app=self.app)
        body = {'question': 'knee prehab', 'mode': 'claude_code', 'provider': 'anthropic', 'model': 'm'}

        async def main():
            agen = ask_route.ask(req, body)
            try:
                run = (await agen.__anext__()).data['run']
                async for ev in agen:
                    if ev.event == 'chunk':
                        break
                await asyncio.to_thread(lambda: self.c.post('/api/ask/stop', json={'run': run}, headers=W))
                return [ev.event async for ev in agen]
            finally:
                await agen.aclose()
        kinds = asyncio.run(main())
        self.assertEqual(kinds[-1], 'stopped')
        self.assertTrue(all(not c.get('message_count') for c in self.c.get('/api/chats').json()['chats']))

    def test_settings_endpoints(self):
        v = self.c.get('/api/claude-code').json()
        self.assertEqual((v['available'], v['path'], v['enabled']), (True, FAKE, True))
        self.assertEqual([m['id'] for m in v['models']], ['', 'sonnet', 'opus', 'fable'])
        bad = self.c.post('/api/claude-code/test', json={'path': str(self.data / 'none.exe')}, headers=W).json()
        self.assertEqual((bad['test']['state'], bad['path']), ('missing', FAKE))       # a failing path is not saved
        ok = self.c.post('/api/claude-code/test', json={'path': FAKE}, headers=W).json()
        self.assertEqual((ok['test']['ok'], ok['test']['version']), (True, '2.1.296 (Claude Code)'))
        self.assertEqual(self.c.put('/api/claude-code', json={'model': 'gpt-6-luna'}, headers=W).status_code, 400)
        os.environ['FAKE_CLAUDE_MODE'] = 'logged_out'
        self.c.put('/api/claude-code', json={'enabled': False}, headers=W)
        r = self.c.put('/api/claude-code', json={'enabled': True}, headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertIn('not logged in', r.json()['detail'])
        self.assertFalse(self.c.get('/api/claude-code').json()['enabled'])
        self.assertEqual(self.c.post('/api/claude-code/test', json={'path': FAKE}).status_code, 403)   # no X-CM
        with mock.patch.object(claude_code, 'available', lambda: False):
            self.assertFalse(self.c.get('/api/claude-code').json()['available'])
            self.assertEqual(self.c.post('/api/claude-code/test', json={'path': FAKE}, headers=W).status_code, 404)


if __name__ == '__main__':
    unittest.main()
