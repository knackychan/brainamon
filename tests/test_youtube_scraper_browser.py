"""Exercise the pasted script against synthetic YouTube layouts in a fresh browser."""
import csv
import importlib.util
import io
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'scrapers/youtube_scraper.js').read_text(encoding='utf-8')


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires Playwright and Edge')
class YoutubeScraperBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 900, 'height': 600})
        self.addCleanup(self.page.close)
        self.alerts = []
        self.page.on('dialog', lambda d: (self.alerts.append(d.message), d.dismiss()))
        self.page.route('**/*', lambda route: route.fulfill(content_type='text/html', body='<html><body></body></html>'))

    def prepare(self, url):
        self.page.goto(url)
        self.page.evaluate('''() => {
          window.csvText = ''; window.downloads = 0;
          const timer = window.setTimeout;
          window.setTimeout = (fn, ms) => timer(fn, Math.min(ms, 20));
          URL.createObjectURL = blob => { blob.text().then(text => window.csvText = text); return 'blob:fixture'; };
          HTMLAnchorElement.prototype.click = function () { window.downloads++; };
        }''')

    def run_script(self):
        self.page.evaluate(SCRIPT)
        self.page.wait_for_function('!window.brainamonYouTubeRunning')

    def test_overview_rejected_and_repeatable(self):
        self.prepare('https://www.youtube.com/feed/playlists')
        self.run_script()
        self.run_script()
        self.assertEqual(len(self.alerts), 2)
        self.assertIn('View full playlist', self.alerts[0])
        self.assertEqual(self.page.evaluate('downloads'), 0)

    def layout(self, nested):
        self.page.evaluate('''nested => {
          document.body.innerHTML = nested
            ? '<div style="height:1200px">Main page</div><ytd-playlist-panel-renderer style="position:fixed;top:0;right:0;display:block;width:350px"><div id="scroll" style="height:180px;overflow-y:auto"></div></ytd-playlist-panel-renderer>'
            : '<h1 class="title">My playlist</h1><ytd-playlist-video-list-renderer id="scroll" style="display:block"></ytd-playlist-video-list-renderer>';
          const list = document.querySelector('#scroll');
          function row(i) {
            const el = document.createElement(nested ? 'ytd-playlist-panel-video-renderer' : 'ytd-playlist-video-renderer');
            el.style.cssText = 'display:block;height:120px';
            el.innerHTML = `<a id="thumbnail" href="/watch?v=videoid000${i}&list=PLtest"></a><span id="video-title">Video ${i}</span><ytd-channel-name><a>Creator</a></ytd-channel-name>`;
            list.appendChild(el);
          }
          for (let i = 0; i < 8; i++) row(i);
          let loaded = false;
          const scroller = nested ? list : document.scrollingElement;
          (nested ? scroller : window).addEventListener('scroll', () => {
            if (!loaded && scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4) {
              loaded = true; row(8); row(9);
            }
          });
        }''', nested)

    def test_nested_scroller_loads_all_rows_without_scrolling_window(self):
        self.prepare('https://www.youtube.com/watch?v=videoid0000&list=PLtest')
        self.layout(True)
        self.run_script()
        rows = list(csv.DictReader(io.StringIO(self.page.evaluate('csvText'))))
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({r['url'] for r in rows}), 10)
        self.assertEqual(rows[-1]['description'], 'Video 9')
        self.assertEqual(self.page.evaluate('window.scrollY'), 0)
        self.run_script()
        self.assertEqual(self.page.evaluate('downloads'), 2)

    def test_full_page_and_stop_title(self):
        self.prepare('https://www.youtube.com/playlist?list=PLtest')
        self.layout(False)
        self.run_script()
        self.assertEqual(len(list(csv.DictReader(io.StringIO(self.page.evaluate('csvText'))))), 10)
        self.page.evaluate(SCRIPT.replace("const STOP_AT = '';", "const STOP_AT = 'Video 0';"))
        self.page.wait_for_function('!window.brainamonYouTubeRunning')
        self.assertIn('stop title', self.alerts[-1])
        self.assertEqual(self.page.evaluate('downloads'), 1)

    def test_empty_and_unknown_layout_do_not_export(self):
        self.prepare('https://www.youtube.com/playlist?list=PLtest')
        self.run_script()
        self.assertIn('No playlist video list', self.alerts[-1])
        self.page.set_content('<ytd-playlist-video-list-renderer style="display:block;height:20px">Empty</ytd-playlist-video-list-renderer>')
        self.run_script()
        self.assertIn('No videos could be read', self.alerts[-1])
        self.assertEqual(self.page.evaluate('downloads'), 0)

    def test_built_form_import_error_progress_and_stop(self):
        import uvicorn
        from playwright.sync_api import expect
        from core import config, site_sessions
        from core.db import Database
        from library import youtube_playlist, ytdlp
        from server.app import create_app
        from server.jobs import JobManager

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            db.set_setting('onboard_answer', 'skip')
            db.close()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            app = create_app(data_dir=root / 'data', cloud_dir=root / 'cloud', port=port, web_dist=ROOT / 'web/dist')
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False,
                                                   timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            with mock.patch.object(ytdlp, 'registry_get', return_value=''), \
                    mock.patch.object(ytdlp, 'find_ytdlp', return_value='yt-dlp'), \
                    mock.patch.object(site_sessions, 'ROOT', root / 'sessions'), \
                    mock.patch.object(config, 'ENV_PATH', root / '.env'), \
                    mock.patch.object(JobManager, '_follow_up'), \
                    mock.patch.object(youtube_playlist, 'read') as read:
                read.return_value = [{'url': 'https://www.youtube.com/watch?v=abcdefghijk',
                                      'description': 'Synthetic playlist video', 'creator': 'Fixture', 'type': 'Video'}]
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                origin = f'http://127.0.0.1:{port}'
                page = self.browser.new_page(viewport={'width': 1280, 'height': 960})
                page.set_default_timeout(8000)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                try:
                    page.goto(origin + '/#cm-auth=' + app.state.api_token)
                    page.get_by_role('button', name='File', exact=True).click()
                    page.get_by_role('menuitem', name='Scrapers', exact=False).click()
                    dialog = page.get_by_role('dialog', name='Scrapers', exact=True)
                    link = dialog.get_by_label('Playlist link', exact=True)
                    submit = dialog.get_by_role('button', name='Import playlist', exact=True)
                    expect(submit).to_be_disabled()
                    link.fill('https://example.com/playlist')
                    link.press('Enter')
                    expect(dialog.locator('.tlog')).to_contain_text('Paste a YouTube playlist link')
                    self.assertFalse(read.called)
                    link.fill('https://www.youtube.com/playlist?list=PLtest')
                    submit.click()
                    expect(dialog.locator('.tlog')).to_contain_text('imported 1 new videos')
                    submit.click()
                    expect(dialog.locator('.tlog')).to_contain_text('skipped 1 duplicates')

                    def slow(*args, should_stop, progress, **kwargs):
                        progress(3)
                        deadline = time.monotonic() + 10
                        while not should_stop() and time.monotonic() < deadline:
                            time.sleep(.02)
                        raise RuntimeError('Stopped')

                    read.side_effect = slow
                    submit.click()
                    expect(dialog.get_by_role('status').filter(has_text='Read 3 video links')).to_be_visible()
                    screenshots = ROOT / 'build/youtube-review'
                    screenshots.mkdir(parents=True, exist_ok=True)
                    dialog.screenshot(path=str(screenshots / 'playlist-import.png'))
                    page.set_viewport_size({'width': 720, 'height': 800})
                    self.assertTrue(dialog.evaluate('el => el.scrollWidth <= el.clientWidth + 1'))
                    dialog.get_by_role('button', name='Stop playlist import').click()
                    expect(submit).to_be_enabled()
                    self.assertEqual(app.state.jobs.last.state, 'stopped')
                    self.assertEqual(app.state.writer.call(lambda db: db.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]), 1)
                    self.assertEqual(errors, [])
                finally:
                    page.close()
                    server.should_exit = True
                    thread.join(6)
