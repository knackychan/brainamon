"""Export diagnostics (server/diagnostics.py, POST /api/app/diagnostics): the zip holds the log, the
version and a settings summary, with keys, tokens, e-mail addresses and the home folder redacted.
Temp folders only: the real error log, .env and local/ are not read or written.

Run from the project root:  py -m unittest tests.test_diagnostics -v
"""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import config
from core.db import Database
from server import diagnostics
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
KEY = 'sk-ant-api03-SECRETSECRETSECRET'
OTHER = 'freellm-0123456789abcdef'          # a key with no known shape: removed because it is configured


class RedactTest(unittest.TestCase):
    def test_shapes(self):
        text = ('Error 401: Incorrect API key provided: sk-proj-abcdefghijklmnop. '
                'Authorization: Bearer abc.def-ghi  token=t0ps3cr3t  "api_key": "zzz"  '
                'AIzaSyA1234567890abcdefghijklmn ya29.a0AfH6SM-x  mail fred@example.com  max_tokens: 4096')
        out = diagnostics.redact(text)
        for leak in ('sk-proj-abcdefghijklmnop', 'abc.def-ghi', 't0ps3cr3t', 'zzz', 'AIzaSyA1234567890', 'ya29.a0AfH6SM',
                     'fred@example.com'):
            self.assertNotIn(leak, out)
        self.assertIn('max_tokens: 4096', out)                  # not every "token" is a secret
        self.assertIn('Incorrect API key provided', out)

    def test_known_values_and_home(self):
        out = diagnostics.redact(f'key {OTHER} in C:\\Users\\Fred\\data and c:/users/fred/x',
                                 known=[OTHER], home='C:\\Users\\Fred')
        self.assertNotIn(OTHER, out)
        self.assertNotIn('Fred', out)
        self.assertNotIn('fred', out)
        self.assertEqual(out.count('%USERPROFILE%'), 2)


class BuildTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        db = Database(self.data / 'content_manager.db')
        db.add_item({'url': 'https://x/a'})
        db.set_setting('minimize_to_tray', '1')
        db.set_setting('yt_dlp_cookies', str(Path.home() / 'cookies.txt'))
        db.set_setting('ask_active_chat', 'my-private-topic')
        db.close()
        self.log = self.root / 'error_log.txt'
        self.log.write_text('x' * (diagnostics.LOG_TAIL + 10) + f'\nTraceback: bad key {KEY} for {OTHER} in {Path.home()}\n',
                            encoding='utf-8')
        self.out = self.root / 'diag'
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': KEY, 'OPENAI_API_KEY': ''}),
                  mock.patch.object(config, 'read_env_file', lambda: {'FREELLMAPI_API_KEY': OTHER, 'FREELLMAPI_BASE_URL': 'http://x'}),
                  mock.patch.object(diagnostics, 'OUT_DIR', self.out),
                  mock.patch.object(diagnostics.app_paths, 'ERROR_LOG', self.log)):
            p.start()
            self.addCleanup(p.stop)

    def read(self, path):
        with zipfile.ZipFile(path) as z:
            self.assertEqual(sorted(z.namelist()), ['about.txt', 'error_log.txt', 'settings.json'])
            return {n: z.read(n).decode('utf-8') for n in z.namelist()}

    def check(self, files):
        blob = '\n'.join(files.values())
        for leak in (KEY, OTHER, str(Path.home()), 'my-private-topic'):
            self.assertNotIn(leak, blob)
        s = json.loads(files['settings.json'])
        self.assertEqual(s['db_settings']['minimize_to_tray'], '1')                  # a SAFE option
        self.assertTrue(s['db_settings']['yt_dlp_cookies'].endswith('characters]'))  # a path: length only
        self.assertEqual(s['api_keys'][config.ANTHROPIC], 'set')
        self.assertEqual(s['api_keys'][config.OPENAI], 'not set')
        self.assertIn('Items: 1', files['about.txt'])
        self.assertLessEqual(len(files['error_log.txt']), diagnostics.LOG_TAIL)
        self.assertIn('Traceback: bad key [key]', files['error_log.txt'])

    def test_build(self):
        rd = Database(self.data / 'content_manager.db')
        self.addCleanup(rd.close)
        path = diagnostics.build(rd, self.data)
        self.assertEqual(path.parent, self.out)
        self.check(self.read(path))

    def test_route(self):
        c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x'), base_url=BASE)
        with c:
            self.assertEqual(c.post('/api/app/diagnostics').status_code, 403)          # POSTs need X-CM
            r = c.post('/api/app/diagnostics', headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            path = Path(r.json()['path'])
            self.assertEqual(path.parent, self.out)
            self.check(self.read(path))
            self.assertIn(str(path), c.app.state.revealable)


if __name__ == '__main__':
    unittest.main()
