"""Recovery codes, metadata-only probes and session/API boundaries, without account actions."""
import http.cookiejar
import json
import os
import subprocess
import sys
import threading
import time
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.request import Request

from core import site_sessions as ss
from core import app_console
from library import ytdlp, video_analyzer
from server.routes import settings
from tests.test_server_tools import _Base, W
from tests.test_site_sessions import JAR, MIXED


class FailureTest(unittest.TestCase):
    def setUp(self):
        # These children are synthetic Python programs, not network downloaders.
        patch = mock.patch('library.public_http.downloader', side_effect=lambda args, url: nullcontext(args))
        patch.start()
        self.addCleanup(patch.stop)
        streaming = mock.patch.object(ytdlp, 'downloader', side_effect=lambda args, url: nullcontext(args))
        streaming.start()
        self.addCleanup(streaming.stop)

    def test_raw_child_credentials_do_not_reach_lines_or_console_events(self):
        events, lines = [], []
        listener = events.append
        app_console.add_listener(listener)
        try:
            ok, rc, hint = ytdlp.run_streaming([sys.executable, '-c',
                "print('arbitrary synthetic-secret'); print('ERROR: HTTP Error 403 Cookie: synthetic-secret'); raise SystemExit(1)"],
                'https://instagram.com/p/selected?token=synthetic-secret', '.', lines.append, lambda: False)
        finally:
            app_console.remove_listener(listener)
        self.assertFalse(ok)
        self.assertEqual(ytdlp.failure([hint])['code'], 'forbidden')
        self.assertNotIn('synthetic-secret', json.dumps(events) + '\n'.join(lines))

    def test_stop_terminates_silent_child_before_cookie_cleanup(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ss, 'ROOT', Path(td) / 'sessions'), \
                mock.patch.object(ss, '_acl'), mock.patch.object(ss, '_crypt', side_effect=lambda raw, decrypt=False: raw[::-1]):
            ss.save('general', JAR)
            stop = threading.Event()
            timer = threading.Timer(.3, stop.set); timer.start()
            started = time.monotonic()
            try:
                with self.assertRaises(ytdlp.DownloadError):
                    with ss.cookies('https://instagram.com') as path:
                        ok, rc, hint = ytdlp.run_streaming([sys.executable, '-c', 'import time; time.sleep(60)', '--cookies', str(path)],
                                                          'https://instagram.com', td, lambda line: None, stop.is_set)
                        if not ok:
                            raise ytdlp.DownloadError(ytdlp.failure([hint]))
                self.assertLess(time.monotonic() - started, 10)
                self.assertEqual(list((ss.ROOT / 'temp').iterdir()), [])
                self.assertEqual(ss.load('general'), JAR)
            finally:
                timer.cancel()

    def test_classifier_and_safe_output(self):
        for line, code, action in [('Login required', 'authentication', 'sessions'), ('HTTP Error 401', 'authentication', 'sessions'), ('HTTP Error 429', 'rate_limit', 'wait'),
                                   ('Unsupported URL', 'unavailable', 'source'), ('PO Token required', 'youtube_setup', 'youtube'),
                                   ('Connection timed out', 'network', 'retry'), ('HTTP Error 403', 'forbidden', 'source')]:
            with self.subTest(line=line):
                result = ytdlp.failure([line + ' Cookie: synthetic-secret'])
                self.assertEqual((result['code'], result['action']), (code, action))
                self.assertNotIn('synthetic-secret', json.dumps(result))
                self.assertEqual(ytdlp.failure([result['error']])['code'], code)
        self.assertEqual(ytdlp.safe_output('[debug] Cookie: synthetic-secret'), '')
        self.assertEqual(ytdlp.safe_output('[download] 50.0% secret text'), '[download] 50.0%')
        self.assertNotIn('secret', ytdlp.safe_url('https://user:secret@youtube.com/watch?token=secret'))
        args = ytdlp.download_args('yt-dlp', 'https://instagram.com/p/1', Path('.'), False)
        self.assertIn('--ignore-config', args)  # external configs cannot resurrect browser extraction after Forget
        self.assertIn('--no-playlist', args)

    def test_cookiejar_domain_secure_path_and_cross_site_redirect(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'cookies.txt'; path.write_bytes(MIXED)
            from yt_dlp.cookies import YoutubeDLCookieJar
            jar = YoutubeDLCookieJar(str(path)); jar.load(ignore_discard=True, ignore_expires=True)
            for url, expected in [('https://www.instagram.com/post/1', 'synthetic-secret'),
                                  ('http://www.instagram.com/post/1', ''), ('https://instagram.com.evil/post/1', ''),
                                  ('https://www.facebook.com/post/1', 'other-secret')]:
                request = Request(url); jar.add_cookie_header(request)
                header = request.get_header('Cookie', '')
                self.assertEqual(expected in header if expected else not header, True)
                if 'facebook.com' in url:
                    self.assertNotIn('synthetic-secret', header)

    def test_analysis_cookie_lifetime_and_child_failure(self):
        from contextlib import contextmanager
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'cookie.txt'
            @contextmanager
            def cookies(url):
                path.write_bytes(JAR)
                try:
                    yield path
                finally:
                    path.unlink()
            def run(args, *a, **kw):
                self.assertTrue(path.exists())
                self.assertIn(str(path), args)
                return subprocess.CompletedProcess(args, 1, '', 'HTTP Error 403 Cookie: synthetic-secret')
            with mock.patch.object(video_analyzer, '_run', run):
                with self.assertRaises(ytdlp.DownloadError) as error:
                    video_analyzer.find_or_download(1, 'https://instagram.com/p/1', td, cookies_resolver=cookies)
            self.assertFalse(path.exists())
            self.assertEqual(error.exception.code, 'forbidden')
            self.assertNotIn('synthetic-secret', str(error.exception))

    def test_analysis_download_timeout_removes_fragments(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(video_analyzer.time, 'monotonic', return_value=0) as clock:
            def run(args, should_stop, **kw):
                out = Path(td) / 'items/1/video'; (out / 'partial.mp4').write_bytes(b'incomplete')
                clock.return_value = 1801
                self.assertTrue(should_stop())
                raise video_analyzer.AnalysisStopped('Stopped.')
            with mock.patch.object(video_analyzer, '_run', run), self.assertRaises(ytdlp.DownloadError) as error:
                video_analyzer.find_or_download(1, 'https://instagram.com/p/selected', td)
            self.assertEqual(error.exception.code, 'network')
            self.assertFalse((Path(td) / 'items/1/video/partial.mp4').exists())

    def test_youtube_checks_selected_executable_not_app_python(self):
        def run(args, **kw):
            if args[0] == 'deno-selected':
                return subprocess.CompletedProcess(args, 0, 'deno 2.3.0', '')
            self.assertEqual(args[0], 'ytdlp-selected')
            self.assertIn('--simulate', args)
            self.assertIn('--load-info-json', args)
            self.assertNotIn('https://youtube.com', args)
            return subprocess.CompletedProcess(args, 0, '', '[debug] Optional libraries: yt_dlp_ejs-1.0.0')
        with mock.patch.object(settings.shutil, 'which', return_value='deno-selected'), \
                mock.patch.object(ytdlp, 'find_ytdlp', return_value='ytdlp-selected'), mock.patch.object(settings.subprocess, 'run', run):
            self.assertEqual(settings.youtube_tools(), {'deno': True, 'ejs': 'detected', 'functional': True})


class SessionApiTest(_Base):
    def setUp(self):
        super().setUp()
        for patch in (mock.patch.object(ss, 'ROOT', self.root / 'sessions'), mock.patch.object(ss, '_acl'),
                      mock.patch.object(ss, 'supported', return_value=True),
                      mock.patch.object(ss, '_crypt', side_effect=lambda raw, decrypt=False: raw[::-1])):
            patch.start(); self.addCleanup(patch.stop)

    def test_unrelated_cookie_seed_does_not_block_remembered_scraper(self):
        from library import scraper_runtime
        from server import job_kinds
        state = b'{"cookies": [], "origins": []}'
        ss.save('browser-reddit', state)
        job = SimpleNamespace(ctx={'platform': 'reddit', 'label': 'Reddit', 'lookups': [], 'watch': str(self.root)},
                              opts={}, stopping=False, emit=lambda *args: None)
        for jar, seeded in ((MIXED, False), (MIXED + JAR.replace(b'instagram.com', b'reddit.com'), True)):
            with self.subTest(seeded=seeded):
                ss.save('general', jar)
                def process(job, args, env, say, name):
                    self.assertEqual(Path(args[args.index('--session-state') + 1]).read_bytes(), state)
                    self.assertEqual('--cookies' in args, seeded)
                    if seeded:
                        raw = Path(args[args.index('--cookies') + 1]).read_bytes()
                        self.assertEqual(ss.parse_cookies(raw)[1]['domains'], ['.reddit.com'])
                    return 'launched'
                with mock.patch.object(scraper_runtime, 'use', return_value=nullcontext(('python', {}))), \
                        mock.patch.object(job_kinds, '_scrape_process', side_effect=process):
                    self.assertEqual(job_kinds._scrape_run(job, {}), 'launched')
                self.assertEqual(ss.load('general'), jar)
                self.assertFalse(ss.busy())
                self.assertEqual(list((ss.ROOT / 'temp').iterdir()), [])

    def test_invalid_saved_access_offers_recovery_in_download_and_analysis(self):
        from server import job_kinds
        job = SimpleNamespace(ctx={'data_dir': str(self.data), 'lookups': [], 'thumbnail_only': False},
                              stopping=False, step=lambda *args: None)
        item = {'id': 1, 'url': 'https://instagram.com/p/selected'}
        for jar in (JAR.replace(b'\t0\t', b'\t1\t'), b'invalid'):
            ss.save('instagram', jar)
            for run in (job_kinds._download_run, job_kinds._analyze_run):
                with self.subTest(run=run.__name__, jar=jar), \
                        mock.patch.object(ytdlp, 'run_streaming') as download, \
                        mock.patch.object(video_analyzer, '_run') as analyze:
                    with self.assertRaises(ss.SessionError) as error:
                        run(job, item)
                    self.assertEqual((error.exception.code, error.exception.action), ('authentication', 'sessions'))
                    self.assertIn('Replace saved login', str(error.exception))
                    download.assert_not_called()
                    analyze.assert_not_called()
                    self.assertEqual(ss.load('instagram'), jar)

    def test_upload_guard_limit_review_and_scoped_save(self):
        url = '/api/settings/site-sessions/import?slot=instagram&site=instagram'
        self.assertEqual(self.c.post(url, content=JAR).status_code, 403)
        response = self.c.post(url, content=MIXED, headers=W)
        self.assertEqual(response.status_code, 200, response.text)
        review = response.json()
        self.assertNotIn('synthetic-secret', response.text)
        self.assertEqual(review['domains'], ['.instagram.com'])
        self.assertFalse((ss.ROOT / 'instagram.bin').exists())
        self.assertEqual(self.c.post(url + '&save=true&digest=wrong', content=MIXED, headers=W).status_code, 400)
        self.assertEqual(self.c.post(url + '&save=true&digest=' + review['digest'], content=MIXED, headers=W).status_code, 200)
        self.assertNotIn(b'other-secret', ss.load('instagram'))
        previous = ss.load('instagram')
        self.assertEqual(self.c.post(url + '&save=true', content=b'invalid', headers=W).status_code, 400)
        self.assertEqual(ss.load('instagram'), previous)
        self.assertEqual(self.c.post(url, content=iter([b'x' * 600000, b'y' * 600000]), headers=W).status_code, 413)
        status = self.c.get('/api/settings/site-sessions')
        self.assertNotIn('synthetic-secret', status.text)
        self.assertIn('Saved; not tested', status.text)
        self.assertNotIn(b'synthetic-secret', (self.data / 'content_manager.db').read_bytes())

    def test_native_picker_path_and_forget(self):
        file = self.root / 'export.txt'; file.write_bytes(JAR)
        url = '/api/settings/site-sessions/import?slot=instagram&site=instagram'
        review = self.c.post(url, json={'path': str(file)}, headers=W).json()
        response = self.c.post(url + '&save=true&digest=' + review['digest'], json={'path': str(file)}, headers=W)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.c.post('/api/settings/site-sessions/forget', json={'slot': 'instagram'}, headers=W).status_code, 200)
        self.assertEqual(ss.mode('instagram'), 'disabled')
        self.assertEqual(ss.mode('browser-instagram'), 'disabled')
        self.assertEqual(file.read_bytes(), JAR)

    def test_test_link_is_scoped_and_metadata_only(self):
        endpoint = '/api/settings/site-sessions/test'
        for url in ('http://127.0.0.1', 'https://instagram.com@evil/x', 'https://instagram.com.evil/x', 'https://instagram.com:123/x'):
            self.assertEqual(self.c.post(endpoint, json={'url': url}, headers=W).status_code, 400)
        proc = mock.Mock(returncode=0, stdout=None, stderr=None)
        proc.poll.return_value = 0
        proc.communicate.return_value = ('{}', '')
        with mock.patch.object(ytdlp, 'find_ytdlp', return_value='selected-ytdlp'), mock.patch.object(subprocess, 'Popen', return_value=proc) as popen:
            response = self.c.post(endpoint, json={'url': 'https://instagram.com/p/chosen?token=secret'}, headers=W)
        self.assertEqual(response.status_code, 200, response.text)
        args = popen.call_args.args[0]
        self.assertIn('--no-playlist', args); self.assertIn('--simulate', args); self.assertIn('--skip-download', args)
        self.assertNotIn('token=secret', response.text)
        self.assertIn('Last test succeeded for this link', response.text)

    def test_new_library_does_not_discover_registry(self):
        from core.db import Database
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                with mock.patch.object(ytdlp, 'registry_get', side_effect=AssertionError('implicit discovery')):
                    settings.migrate_registry(db)
                self.assertEqual(db.get_setting('session_mode_general'), 'none')
            finally:
                db.close()
