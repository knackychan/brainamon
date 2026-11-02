"""Playlist extraction and job integration; no real accounts or network."""
import io
import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest import mock

from core import site_sessions
from library import youtube_playlist as yt
from library import ytdlp
from server.app import create_app
from server.jobs import JobManager
from tests.auth_client import TestClient

URL = 'https://www.youtube.com/playlist?list=PLtest'
VIDEO = {'id': 'abcdefghijk', 'title': 'A title', 'channel': 'Creator'}
ROW = {'url': 'https://www.youtube.com/watch?v=abcdefghijk', 'description': 'A title',
       'creator': 'Creator', 'type': 'Video', 'source': 'youtube_playlist'}


class PlaylistReaderTest(unittest.TestCase):
    def test_url_allowlist_and_canonicalization(self):
        self.assertEqual(yt.playlist_url('https://m.youtube.com/watch?v=abcdefghijk&list=PLtest&index=2'), URL)
        for bad in (None, {}, 'file:///playlist?list=PLtest', 'https://youtube.com.evil/playlist?list=PLtest',
                    'https://localhost/playlist?list=PLtest', 'https://www.youtube.com/feed/playlists',
                    'https://user:pass@youtube.com/playlist?list=PLtest',
                    'https://youtube.com:444/playlist?list=PLtest', URL + '&list=other',
                    'https://youtube.com/playlist?list=../../bad'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                yt.playlist_url(bad)

    def read(self, lines, rc=0, stop=lambda: False, revoked=False):
        proc = mock.Mock(stdout=io.BytesIO(('\n'.join(lines) + '\n').encode()), stderr=None)
        proc.wait.return_value = rc
        active = []

        @contextmanager
        def cookies(*args):
            active.append(True)
            try:
                yield Path('isolated-session.txt')
            finally:
                active.pop()

        def spawn(args, **kwargs):
            self.assertTrue(active)
            self.args = args
            return proc

        with mock.patch.object(site_sessions, 'cookies', cookies), \
                mock.patch.object(site_sessions, 'revoked', return_value=revoked), \
                mock.patch.object(ytdlp, 'runtime_args', return_value=[]), \
                mock.patch.object(ytdlp, 'downloader', side_effect=lambda args, url: nullcontext(args)), \
                mock.patch.object(ytdlp, 'monitor', return_value=nullcontext()), \
                mock.patch.object(yt.subprocess, 'Popen', side_effect=spawn):
            return yt.read(URL, 'yt-dlp', should_stop=stop)

    def test_entries_deduplicated_and_safe_arguments(self):
        self.assertEqual(self.read([json.dumps(VIDEO), json.dumps(VIDEO), '{"id":"../bad"}']), [ROW])
        for flag in ('--ignore-config', '--skip-download', '--flat-playlist', '--no-mark-watched', '--yes-playlist'):
            self.assertIn(flag, self.args)
        self.assertEqual(self.args[-2:], ['--', URL])
        self.assertEqual(self.args[self.args.index('--cookies') + 1], 'isolated-session.txt')
        self.assertNotIn('--cookies-from-browser', self.args)

    def test_failure_never_returns_partial_rows_or_raw_secrets(self):
        with self.assertRaises(ytdlp.DownloadError) as error:
            self.read([json.dumps(VIDEO), 'ERROR: sign in; secret-cookie=123'], rc=1)
        self.assertNotIn('secret-cookie', str(error.exception))
        for lines in ([], ['{broken'], ['x' * (1024 * 1024 + 1)]):
            with self.subTest(lines=len(lines)), self.assertRaises(RuntimeError):
                self.read(lines)
        with mock.patch.object(yt, 'MAX_ENTRIES', 1), self.assertRaisesRegex(RuntimeError, 'at most'):
            self.read([json.dumps(VIDEO)] * 2)

    def test_stop_and_revocation(self):
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            self.read([], stop=lambda: True)
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            self.read([], revoked=True)
        calls = iter([False, True])
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            self.read([json.dumps(VIDEO)], stop=lambda: next(calls))


class PlaylistApiTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / 'data'
        for p in (mock.patch.object(ytdlp, 'registry_get', return_value=''),
                  mock.patch.object(site_sessions, 'ROOT', self.root / 'sessions'),
                  mock.patch.object(ytdlp, 'find_ytdlp', return_value='yt-dlp'),
                  mock.patch.object(JobManager, '_follow_up')):
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.root / 'cloud', port=8765,
                              web_dist=self.root / 'web')
        self.c = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def start(self, url=URL):
        return self.c.post('/api/import/youtube-playlist', json={'url': url}, headers={'X-CM': '1'})

    def wait(self):
        deadline = time.monotonic() + 6
        while self.app.state.jobs.current and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertIsNone(self.app.state.jobs.current)

    def count(self):
        return self.app.state.writer.call(lambda db: db.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0])

    def test_import_duplicates_and_index_queue(self):
        with mock.patch.object(yt, 'read', return_value=[ROW]):
            self.assertEqual(self.start().status_code, 200)
            self.wait()
            self.assertEqual(self.count(), 1)
            self.assertEqual(len(self.app.state.jobs.dirty), 1)
            self.assertEqual(self.start().status_code, 200)
            self.wait()
        self.assertEqual(self.count(), 1)
        self.assertIn('skipped 1 duplicates', self.app.state.jobs.last.ctx['finish_toast'])
        self.assertEqual(len(list((self.data / 'scrapes').glob('youtube_playlist_*.csv'))), 2)

    def test_bad_input_missing_tool_and_extraction_failure(self):
        self.assertEqual(self.start('https://evil.example/').status_code, 400)
        with mock.patch.object(ytdlp, 'find_ytdlp', return_value=None):
            self.assertEqual(self.start().status_code, 400)
        with mock.patch.object(yt, 'read', side_effect=RuntimeError('Access failed')):
            self.assertEqual(self.start().status_code, 200)
            self.wait()
        self.assertEqual(self.app.state.jobs.last.err, 1)
        self.assertEqual(self.count(), 0)
        self.assertFalse((self.data / 'scrapes').exists())

    def test_busy_and_cancel_import_nothing(self):
        entered = threading.Event()

        def read(*args, should_stop, **kwargs):
            entered.set()
            deadline = time.monotonic() + 5
            while not should_stop() and time.monotonic() < deadline:
                time.sleep(.01)
            raise RuntimeError('Stopped')

        with mock.patch.object(yt, 'read', side_effect=read):
            self.assertEqual(self.start().status_code, 200)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.start().status_code, 409)
            self.c.post('/api/jobs/stop', headers={'X-CM': '1'})
            self.wait()
        self.assertEqual(self.app.state.jobs.last.state, 'stopped')
        self.assertEqual(self.app.state.jobs.last.err, 0)
        self.assertEqual(self.count(), 0)
        self.assertFalse((self.data / 'scrapes').exists())
