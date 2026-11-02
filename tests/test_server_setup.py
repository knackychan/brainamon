"""First run (server/routes/app.py): the getting-started checklist, its dismissal, and the data
folder change of the installed app (location.json in a temp home; nothing real is touched).

Run from the project root:  py -m unittest tests.test_server_setup -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import app_paths
from core import config, ai_client, ai_defaults
from core import site_sessions
from core.db import Database
from library import ytdlp
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class SetupTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        Database(self.data / 'content_manager.db').close()
        env = {k: '' for k in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'FREELLMAPI_API_KEY')}
        for p in (mock.patch.object(config, 'ENV_PATH', self.root / '.env'),
                  mock.patch.object(ytdlp, 'registry_get', lambda name: ''),     # no Qt-era cookie paths
                  mock.patch.object(site_sessions, 'ROOT', self.root / 'sessions'),     # not this PC's saved sign-ins
                  mock.patch.dict(os.environ, env)):
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x', cloud_dir=self.root / 'cloud'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_checklist_and_dismiss(self):
        s = self.c.get('/api/app/setup').json()
        self.assertEqual((s['items'], s['has_key'], s['dismissed']), (0, False, False))
        self.assertEqual(set(s['tools']), {'ffmpeg', 'ffprobe', 'yt_dlp', 'deno'})
        self.assertFalse(s['cookies'])
        ck = self.root / 'my_cookies.txt'
        ck.write_text('# Netscape HTTP Cookie File')
        self.c.put('/api/settings', json={'downloads': {'yt_dlp_cookies': str(ck)}}, headers=W)
        self.assertTrue(self.c.get('/api/app/setup').json()['cookies'])
        self.assertEqual(self.c.post('/api/app/setup/dismiss').status_code, 403)      # no X-CM header
        self.assertTrue(self.c.post('/api/app/setup/dismiss', headers=W).json()['ok'])
        self.assertTrue(self.c.get('/api/app/setup').json()['dismissed'])

    def test_setup_navigation_skips_executable_checks(self):
        with mock.patch('server.routes.settings.tools_view', side_effect=AssertionError('tool probe')), \
                mock.patch('server.routes.settings.get_tools_install', side_effect=AssertionError('installer probe')):
            response = self.c.get('/api/app/setup?include_tools=false')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'], 0)
        self.assertIn('data_dir', response.json())
        self.assertNotIn('tool_status', response.json())

    def test_setup_is_read_only_and_redacted(self):
        state = self.c.app.state
        tools = {'tools_dir': '', 'tools': [{'name': n, 'found': n == 'ffprobe', 'path': ''}
                                          for n in ('ffmpeg', 'ffprobe', 'yt-dlp')], 'all_found': False}
        with mock.patch.object(state.writer, 'call', side_effect=AssertionError('GET wrote')), \
                mock.patch('server.routes.settings.tools_view', return_value=tools), \
                mock.patch('server.routes.io._obsidian_installed', return_value=False), \
                mock.patch.object(state.sync, 'status', return_value={'configured': True, 'signed_in': True, 'on': False}), \
                mock.patch.object(config, 'get', return_value='secret-should-not-leak'):
            response = self.c.get('/api/app/setup')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('secret-should-not-leak', response.text)
        s = response.json()
        self.assertTrue(s['keys']['openai'])
        self.assertEqual(s['tools'], {'ffmpeg': False, 'ffprobe': True, 'yt_dlp': False})
        self.assertFalse(s['obsidian']['installed'])
        self.assertFalse(s['obsidian']['is_vault'])
        self.assertTrue(s['cloud']['signed_in'])
        self.assertFalse(s['cloud']['on'])

    def test_vault_setup_moved_to_the_obsidian_routes(self):
        vault = self.root / 'Documents' / 'Brainamon Vault'
        with mock.patch('server.map_service.app_paths.HOME', self.root / 'home'):
            self.assertEqual(self.c.put('/api/obsidian/vault', json={'path': str(vault), 'create': True}).status_code, 403)
            self.assertFalse(vault.exists())
            self.assertEqual(self.c.put('/api/obsidian/vault', json={'path': str(self.data / 'notes'), 'create': True}, headers=W).status_code, 400)
            self.assertEqual(self.c.put('/api/obsidian/vault', json={'path': str(vault), 'create': True}, headers=W).status_code, 200)
        s = self.c.get('/api/app/setup').json()['obsidian']
        self.assertTrue(s['set'] and s['vault_ok'] and s['is_vault'])
        self.assertEqual(s['mode'], 'owner')

    def test_console_links_only_open_on_guarded_click(self):
        with mock.patch('server.routes.app.webbrowser.open', return_value=True) as opened:
            self.c.get('/api/app/setup')
            self.assertEqual(self.c.post('/api/app/setup/link', json={'name': 'openai'}).status_code, 403)
            self.assertEqual(self.c.post('/api/app/setup/link', json={'name': 'file:///bad'}, headers=W).status_code, 400)
            opened.assert_not_called()
            for name in ('anthropic', 'openai'):
                self.assertEqual(self.c.post('/api/app/setup/link', json={'name': name}, headers=W).status_code, 200)
            self.assertEqual(opened.call_count, 2)

    def test_wiskit_settings_validation_and_legacy_compatibility(self):
        provider = ai_client.ASK_PROVIDER_OPENAI
        model = ai_client.feature_models(provider)[0]['id']
        self.c.app.state.writer.call(lambda db: db.set_setting('ai_model_describe', json.dumps({'provider': provider, 'model': model})))
        s = self.c.get('/api/settings').json()['models']
        self.assertEqual(s['jarvis'], {'provider': provider, 'model': model})
        self.assertNotIn('features', s)
        for choice in (None, [], {}, {'provider': [], 'model': model}, {'provider': provider, 'model': []},
                       {'provider': provider, 'model': 'no-such-model'}):
            r = self.c.put('/api/settings', json={'keys': {'openai': 'must-not-save'}, 'models': {'jarvis': choice}}, headers=W)
            self.assertEqual(r.status_code, 400, r.text)
        self.assertFalse(config.openai_api_key())
        r = self.c.put('/api/settings', json={'models': {'jarvis': {'provider': provider, 'model': model}}}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.get('/api/settings/analyze').json()['options']['analysis_provider'], 'openai')
        self.assertTrue(self.c.get('/api/app/setup').json()['models']['saved'])

    def test_data_dir_needs_the_installed_app(self):
        self.assertEqual(self.c.put('/api/app/data-dir', json={'path': str(self.root)}, headers=W).status_code, 409)

    def test_data_dir_installed(self):
        home = self.root / 'home'
        full = self.root / 'full'
        full.mkdir()
        (full / 'notes.txt').write_text('mine')
        empty = self.root / 'empty'
        empty.mkdir()
        env = {k: v for k, v in os.environ.items() if k != 'CM_DATA_DIR'}
        with mock.patch.object(app_paths, 'FROZEN', True), mock.patch.object(app_paths, 'HOME', home), \
                mock.patch.object(app_paths, 'POINTER', home / 'location.json'), mock.patch.dict(os.environ, env, clear=True):
            put = lambda p: self.c.put('/api/app/data-dir', json={'path': p}, headers=W)   # noqa: E731
            self.assertEqual(put('').status_code, 400)
            self.assertEqual(put('relative/dir').status_code, 400)
            self.assertEqual(put(str(self.root / 'missing')).status_code, 400)
            self.assertEqual(put(str(full)).status_code, 400)              # not empty, no content_manager.db
            self.assertFalse((home / 'location.json').exists())
            r = put(str(empty))
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(Path(r.json()['data_dir_next']), empty.resolve())
            self.assertEqual(Path(r.json()['data_dir']), self.data)         # this run keeps its folder
            r = put(str(self.data))                                         # a data folder (holds the DB)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(json.loads((home / 'location.json').read_text())['data_dir'], str(self.data.resolve()))
        self.assertEqual((full / 'notes.txt').read_text(), 'mine')          # nothing moved

    def test_selected_library_content_counts_before_restart(self):
        other = self.root / 'other'
        db = Database(other / 'content_manager.db')
        db.conn.execute("INSERT INTO items (url) VALUES ('https://example.com/a'), ('https://example.com/b')")
        db.conn.commit()
        db.close()
        (other / 'notes').mkdir()
        (other / 'notes' / 'a.md').write_text('x')
        s = self.c.get('/api/app/setup').json()
        self.assertEqual((s['next_items'], s['next_notes'], s['data_dir_next']), (0, 0, str(self.data)))
        with mock.patch.object(app_paths, 'data_dir', return_value=other), mock.patch.object(app_paths, 'FROZEN', True):
            s = self.c.get('/api/app/setup').json()
        self.assertEqual((s['items'], s['next_items'], s['next_notes']), (0, 2, 1))
        self.assertEqual(Path(s['data_dir_next']), other)
        with mock.patch.object(app_paths, 'data_dir', return_value=self.root / 'missing'), mock.patch.object(app_paths, 'FROZEN', True):
            self.assertEqual(self.c.get('/api/app/setup').json()['next_items'], 0)


if __name__ == '__main__':
    unittest.main()
