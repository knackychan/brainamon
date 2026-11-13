"""V6 plan 12 endpoints: import, scrapers (script, watcher), exports (CSV, Obsidian),
reveal, Video Tools (analyze_media stubbed), and the Settings window (keys never returned,
the registry read stubbed, the CK lamp).

Run from the project root:  py -m unittest tests.test_server_io -v
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_defaults, app_paths, config
from core import site_sessions
from library import owner_vault
from library import video_analyzer
from library import ytdlp
from core.db import Database
from server.app import create_app
from server.jobs import KINDS
from server.routes import io as io_routes

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class IoServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://x/a', 'description': 'Hip airplane', 'tags': 'hips'})
        db.close()
        self.env = self.root / '.env'
        for p in (mock.patch.object(app_paths, 'LOCAL', self.root / 'local'),
                  mock.patch.object(ytdlp, 'registry_get', lambda name: ''),
                  mock.patch.object(site_sessions, 'ROOT', self.root / 'sessions'),     # not this PC's saved sign-ins
                  mock.patch.object(config, 'ENV_PATH', self.env),
                  mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-secret', 'OPENAI_API_KEY': ''})):
            p.start()
            self.addCleanup(p.stop)
        for k in KINDS.values():
            p = mock.patch.multiple(k, gap=0.0, error_gap=0.0)
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def wait(self):
        end = time.time() + 15
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.03)
        self.fail('job did not finish')

    def test_import(self):
        csv = 'url,description\nhttps://x/new,New one\nhttps://x/a,Duplicate\n'
        r = self.c.post('/api/import?name=fb_saved_x.csv', content=csv.encode(), headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()['added'], r.json()['skipped']), (1, 1))
        self.assertEqual((r.json()['duplicates'], r.json()['invalid']), (1, 0))
        self.assertEqual([f['name'] for f in self.c.get('/api/import/files').json()], ['fb_saved_x.csv'])
        again = self.c.post('/api/import', json={'scrape': 'fb_saved_x.csv'}, headers=W).json()
        self.assertEqual((again['added'], again['skipped']), (0, 2))
        self.assertEqual(self.c.post('/api/import?name=x.txt', content=b'x', headers=W).status_code, 400)
        self.assertEqual(self.c.post('/api/import', json={'path': str(self.root / 'none.csv')}, headers=W).status_code, 404)

    def test_meta_export_explains_phone_route(self):
        for raw in (b'{"saved_saved_media": []}', b'[{"label_values": []}]'):
            response = self.c.post('/api/import?name=meta.json', content=raw, headers=W)
            self.assertEqual(response.status_code, 400)
            self.assertIn('Add > Import saved posts', response.json()['detail'])
        self.assertEqual(self.c.get('/api/items').json()['total'], 1)

    def test_scrapers(self):
        r = self.c.get('/api/scrapers').json()
        self.assertEqual({p['key'] for p in r['platforms']}, {'facebook', 'instagram', 'youtube', 'reddit', 'threads'})
        self.assertEqual([p['key'] for p in r['playwright']], ['facebook', 'instagram', 'reddit', 'threads'])
        self.assertEqual(self.c.post('/api/scrapers/playwright', json={'platform': 'nope'}, headers=W).status_code, 404)
        self.assertFalse(r['watching'])
        js = self.c.get('/api/scrapers/facebook.js?stop_at=Last%20one&unsave=true').text
        self.assertIn("const STOP_AT = 'Last one';", js)
        js = self.c.get('/api/scrapers/threads.js?stop_at=Last%20thread').text
        self.assertIn("const STOP_AT = 'Last thread';", js)
        self.assertIn("id: 'threads'", js)
        self.assertNotIn('// THREADS_SITE', js)
        with mock.patch.object(io_routes.webbrowser, 'open') as opened:
            self.assertEqual(self.c.post('/api/scrapers/threads/open', headers=W).status_code, 200)
            opened.assert_called_once_with('https://www.threads.com/saved')
        self.assertEqual(self.c.get('/api/scrapers/nope.js').status_code, 404)
        downloads = self.root / 'Downloads'
        downloads.mkdir()
        fetched = []

        def fetch(job, item):
            fetched.append(item['id'])
            return {'filename': 'thumb.jpg', 'source': 'web', 'caption': 'Fetched caption',
                    'title': 'Fetched title', 'creator': '', 'error': ''}

        for p in (mock.patch.object(KINDS['thumb'], 'run_item', fetch),
                  mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', None))):
            p.start()
            self.addCleanup(p.stop)
        self.c.put('/api/settings', json={'downloads': {'scrape_watch_dir': str(downloads)}}, headers=W)
        w = self.c.post('/api/scrapers/watch', json={'on': True}, headers=W).json()
        self.assertEqual(w, {'watching': True, 'dir': str(downloads)})
        (downloads / 'fb_saved_new.csv').write_text('url,description\nhttps://x/w,Watched\n', encoding='utf-8')
        end = time.time() + 8
        while time.time() < end and not (self.data / 'scrapes' / 'fb_saved_new.csv').exists():
            time.sleep(0.1)
        time.sleep(0.3)
        self.assertTrue((self.data / 'scrapes' / 'fb_saved_new.csv').exists())
        self.assertIn('https://x/w', [r['url'] for r in self.c.get('/api/items').json()['items']])
        end = time.monotonic() + 5
        while time.monotonic() < end:
            rows = self.c.get('/api/items').json()['items']
            imported = next(r for r in rows if r['url'] == 'https://x/w')
            if imported['thumb']:
                break
            time.sleep(.03)
        self.assertEqual(fetched, [imported['id']])
        item = self.c.get(f'/api/items/{imported["id"]}').json()
        self.assertEqual(item['thumb_path'], 'thumb.jpg')
        self.assertEqual(item['description'], 'Watched')
        self.assertFalse(self.c.post('/api/scrapers/watch', json={'on': False}, headers=W).json()['watching'])

    def test_obsidian_graph(self):
        vault = self.data / 'Fredorama'
        opened = []
        with mock.patch.object(io_routes, '_open_uri', opened.append), \
                mock.patch.object(io_routes, '_obsidian_installed', lambda: True), \
                mock.patch.object(owner_vault, 'obsidian_vaults', lambda path=None: [{'path': str(vault), 'open': True, 'ts': 0}]):
            r = self.c.post('/api/obsidian/graph', headers=W)
            self.assertEqual(r.status_code, 400)                     # no vault yet: say so, open nothing
            self.assertIn('Export to Obsidian', r.json()['detail'])
            (vault / '.obsidian').mkdir(parents=True)
            (vault / 'Content Manager').mkdir()
            (vault / 'Content Manager' / 'README.md').write_text('x', encoding='utf-8')
            r = self.c.post('/api/obsidian/graph', headers=W)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(opened, [r.json()['uri']])
            self.assertTrue(opened[0].startswith('obsidian://open?path='))
            self.assertIn('README.md', opened[0])
            self.assertNotIn('/', opened[0][len('obsidian://open?path='):])   # the whole path URI-encoded
        with mock.patch.object(io_routes, '_open_uri', opened.append), \
                mock.patch.object(io_routes, '_obsidian_installed', lambda: False):
            r = self.c.post('/api/obsidian/graph', headers=W)
            self.assertEqual(r.status_code, 400)
            self.assertIn('not installed', r.json()['detail'])
        self.assertEqual(len(opened), 1)

    def test_exports(self):
        out = self.root / 'out'
        out.mkdir()
        # Export for phone retired with the Google Drive mirror (plan Phase 3)
        self.assertIn(self.c.post('/api/export/phone', json={'folder': str(out), 'name': 'p'}, headers=W).status_code, (404, 405))
        self.assertEqual(self.c.post('/api/reveal', json={'path': str(self.root)}, headers=W).status_code, 404)
        self.assertEqual(self.c.post('/api/export/csv', json={'path': str(self.data / 'b.csv')}, headers=W).status_code, 400)
        self.assertEqual(self.c.post('/api/export/csv', json={'path': str(out / 'backup')}, headers=W).status_code, 200)
        self.wait()
        self.assertIn('https://x/a', (out / 'backup.csv').read_text(encoding='utf-8-sig'))
        vault = self.root / 'vault'
        vault.mkdir()
        self.assertEqual(self.c.get('/api/export/obsidian/coverage').json(), {'indexed': 0, 'total': 1, 'low': True})
        self.assertEqual(self.c.post('/api/export/obsidian', json={'vault': str(self.root / 'nope')}, headers=W).status_code, 400)
        self.assertEqual(self.c.post('/api/export/obsidian', json={'vault': str(vault)}, headers=W).status_code, 200)
        self.assertEqual(self.c.app.state.sync.status()['vault']['folder'], str(vault))
        last = self.wait()
        self.assertEqual(last['err'], 0, last)
        self.assertTrue((vault / 'Content Manager').is_dir())
        self.assertEqual(self.c.get('/api/export/defaults').json()['vault'], str(vault))

    def test_video_tools(self):
        vid = self.root / 'clip.mp4'
        vid.write_bytes(b'video')
        seen = {}

        def fake(video, item_dir, **kw):
            seen.update(video=str(video), item_dir=str(item_dir), item_id=kw['item_id'])
            Path(item_dir).mkdir(parents=True, exist_ok=True)
            (Path(item_dir) / 'report.md').write_text('# r')
            return str(Path(item_dir) / 'report.md'), 'words', 'analysis', 0
        with mock.patch.object(video_analyzer, 'analyze_media', fake), \
                mock.patch.object(video_analyzer, 'preflight', lambda *a: ''):
            r = self.c.post('/api/video-tools/analyze', json={'path': str(vid), 'opts': {'analysis_provider': 'none'}}, headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.wait()['done'], 1)
        self.assertEqual(seen['item_id'], 'clip')
        self.assertEqual(Path(seen['item_dir']), self.data / 'video_tools' / 'items' / 'clip')
        self.assertEqual(self.c.post('/api/video-tools/analyze', json={'path': str(self.root / 'x.mp4')}, headers=W).status_code, 400)
        up = self.c.put('/api/video-tools/upload?name=my%20clip.mp4', content=b'abc', headers=W).json()
        self.assertEqual(Path(up['path']).read_bytes(), b'abc')
        self.assertEqual(self.c.put('/api/video-tools/upload?name=x.exe', content=b'abc', headers=W).status_code, 400)

    def test_settings_never_return_keys(self):
        s = self.c.get('/api/settings')
        self.assertNotIn('sk-ant-secret', s.text)
        self.assertEqual(s.json()['keys']['anthropic'], True)
        self.assertEqual(s.json()['keys']['openai'], False)
        r = self.c.put('/api/settings', json={'keys': {'openai': 'sk-new'}, 'plain': {'local_base': 'http://localhost:11434/v1'},
                                              'models': {'jarvis': {'provider': 'openai', 'model': 'gpt-6-luna'},
                                                         'embed_provider': 'openai'}}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn('sk-new', r.text)
        from core import private_storage
        self.assertIn('OPENAI_API_KEY=sk-new', private_storage.read(self.env).decode())
        v = r.json()
        self.assertEqual(v['plain']['local_base'], 'http://localhost:11434/v1')
        self.assertEqual(v['models']['jarvis']['model'], 'gpt-6-luna')
        self.assertEqual(v['models']['embed_provider'], 'openai')
        bad = {'models': {'jarvis': {'provider': 'openai', 'model': 'nope'}}}
        self.assertEqual(self.c.put('/api/settings', json=bad, headers=W).status_code, 400)
        self.c.put('/api/settings', json={'clear_keys': ['openai']}, headers=W)
        self.assertFalse(self.c.get('/api/settings').json()['keys']['openai'])

    def test_single_key_update_keeps_other_saved_settings(self):
        before = self.c.get('/api/settings').json()
        result = self.c.put('/api/settings', json={'keys': {'openai': 'synthetic-key'}}, headers=W)
        self.assertEqual(result.status_code, 200)
        after = result.json()
        self.assertTrue(after['keys']['anthropic'])
        self.assertTrue(after['keys']['openai'])
        for field in ('plain', 'downloads'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after['models']['jarvis'], before['models']['jarvis'])
        self.assertNotIn('synthetic-key', result.text)
        removed = self.c.put('/api/settings', json={'clear_keys': ['openai']}, headers=W).json()
        self.assertFalse(removed['keys']['openai'])
        self.assertTrue(removed['keys']['anthropic'])

    def test_cookies_lamp(self):
        here = os.getcwd()
        os.chdir(self.root)              # no cookies.txt fallback in the project folder
        self.addCleanup(os.chdir, here)
        self.assertEqual(self.c.get('/api/settings/cookies-state').json()['lamp'], 'off')
        ck = self.root / 'cookies.fb.txt'
        ck.write_text('not cookies')
        self.c.put('/api/settings', json={'downloads': {'yt_dlp_cookies': str(ck)}}, headers=W)
        self.assertEqual(self.c.get('/api/settings/cookies-state').json()['lamp'], 'a')
        ck.write_text('# Netscape HTTP Cookie File\n')
        self.assertEqual(self.c.get('/api/settings/cookies-state').json()['lamp'], 'a')


class RegistryMigrationTest(unittest.TestCase):
    def test_copied_once(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            data = Path(td)
            db = Database(data / 'content_manager.db')
            db.set_setting('setup_dismissed', '1')  # existing installation opts into legacy migration
            db.close()
            reg = {'yt_dlp_cookies': r'C:\c.txt', 'scrape_watch_dir': r'C:\Downloads'}
            with mock.patch.object(app_paths, 'LOCAL', data / 'local'), \
                    mock.patch.object(ytdlp, 'registry_get', lambda n: reg.get(n, '')):
                with TestClient(create_app(data_dir=data, cloud_dir=data / 'test-cloud', port=8765, web_dist=data / 'x', cards_dir=data / 'x'), base_url=BASE) as c:
                    self.assertEqual(c.get('/api/settings').json()['downloads']['yt_dlp_cookies'], r'C:\c.txt')
                    c.put('/api/settings', json={'downloads': {'yt_dlp_cookies': ''}}, headers=W)
                with TestClient(create_app(data_dir=data, cloud_dir=data / 'test-cloud', port=8765, web_dist=data / 'x', cards_dir=data / 'x'), base_url=BASE) as c:
                    self.assertEqual(c.get('/api/settings').json()['downloads']['yt_dlp_cookies'], '')   # not re-copied


if __name__ == '__main__':
    unittest.main()
