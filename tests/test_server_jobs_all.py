"""V6 plan 07: every job kind with stubs (yt-dlp, the AI calls, embeddings, the video engine),
joining a running analyze job, the download job's streamed lines, the Analyze options settings.

Run from the project root:  py -m unittest tests.test_server_jobs_all -v
No network, no yt-dlp, no ffmpeg: every external call is replaced.
"""
import os
from contextlib import nullcontext
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core import ai_defaults
from library import linkinfo
from library import video_analyzer
from library import ytdlp
from core.db import Database
from server.app import create_app
from server.jobs import KINDS

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class JobsAllTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.add_category('SPORT', '#2E75B6')
        db.set_setting('ai_model_jarvis', '{"provider":"anthropic","model":"claude-sonnet-4-6"}')
        db.set_setting('session_mode_general', 'none')
        db.set_setting('session_mode_instagram', 'none')
        self.reel = db.add_item({'url': 'https://www.facebook.com/reel/1', 'description': 'Knee prehab reel',
                                 'type': 'Reel', 'category': 'INTERESTING'})
        self.vid = db.add_item({'url': 'https://youtu.be/v', 'description': 'Blender donut video',
                                'type': 'Video', 'category': 'BLENDER', 'tags': 'blender'})
        self.post = db.add_item({'url': 'https://example.com/p', 'description': '', 'type': 'Post',
                                 'category': 'INTERESTING'})
        db.close()
        patches = [mock.patch('core.site_sessions.ROOT', self.data / 'sessions'),
                   mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None)),
                   mock.patch.object(ytdlp, 'downloader', side_effect=lambda args, url: nullcontext(args)), mock.patch.object(ytdlp, 'registry_get', lambda name: ''), mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),
                   mock.patch('library.public_http.downloader', side_effect=lambda args, url: nullcontext(args)),
                   mock.patch.object(ytdlp, 'available', lambda: True),
                   mock.patch.object(ytdlp, 'find_ytdlp', lambda: 'yt-dlp'),
                   mock.patch.object(video_analyzer, 'preflight', lambda *a: '')]   # no ffmpeg / Whisper here
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for k in KINDS.values():
            p = mock.patch.multiple(k, gap=0.0, error_gap=0.0)
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def start(self, kind, ids, force=False, opts=None):
        r = self.c.post('/api/jobs', json={'kind': kind, 'ids': ids, 'force': force, 'opts': opts or {}}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def wait(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.03)
        self.fail('job did not finish')

    def item(self, i):
        return self.c.get(f'/api/items/{i}').json()

    def test_thumb_caption_rules(self):
        def fetch(item, data_dir, cookies=None, on_proc=None, should_stop=None):
            d = Path(data_dir) / 'items' / str(item['id'])
            d.mkdir(parents=True, exist_ok=True)
            (d / 'thumb.jpg').write_bytes(b'\xff\xd8\xff\xd9')
            return {'filename': 'thumb.jpg', 'source': 'yt-dlp', 'caption': f'caption {item["id"]}', 'error': ''}
        with mock.patch.object(ytdlp, 'fetch_thumbnail', fetch), \
                mock.patch.object(linkinfo, 'read', return_value={'desc': f'caption {self.post}', 'title': '', 'creator': '', 'image': 'https://example.com/thumb'}), \
                mock.patch.object(linkinfo, 'image', return_value=b'synthetic'), \
                mock.patch.object(linkinfo, 'to_jpeg', return_value=b'jpeg'):
            self.start('thumb', [self.reel, self.post])
            self.assertEqual(self.wait()['done'], 2, self.c.get('/api/console').json())
            self.assertEqual(self.item(self.reel)['description'], 'Knee prehab reel')   # kept: not forced
            self.assertEqual(self.item(self.post)['description'], f'caption {self.post}')  # was empty
            self.assertEqual(self.item(self.post)['thumb_path'], 'thumb.jpg')
            self.start('thumb', [self.reel], force=True)
            self.wait()
            self.assertEqual(self.item(self.reel)['description'], f'caption {self.reel}')   # forced
        self.assertIn(self.reel, self.app.state.jobs.dirty)

    def test_categorize(self):
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '{"category": "sport", "tags": "Knee, Prehab"}'):
            p = self.c.post('/api/jobs/preview', json={'kind': 'categorize', 'ids': [self.reel, self.vid]}, headers=W).json()
            self.assertEqual(p['count'], 1)                         # BLENDER is skipped unless forced
            self.start('categorize', [self.reel, self.vid])
            self.wait()
        it = self.item(self.reel)
        self.assertEqual((it['category'], it['tags']), ('SPORT', 'knee, prehab'))

    def test_analyze_and_join(self):
        gate = threading.Event()
        calls = []

        def fake_find(item_id, url, data_dir, cookies_resolver=None, **kw):
            return Path(data_dir) / 'x.mp4'

        def fake_engine(video, item_dir, *, item_id=None, step=None, **kw):
            calls.append((item_id, kw['analysis_provider'], kw['frame_interval']))
            step('Transcribing…')
            gate.wait(5)
            return str(Path(item_dir) / 'report.md'), 'the transcript', '### Summary\nA short summary.\n### Tags\nknee, mobility', 0

        with mock.patch.object(video_analyzer, 'find_or_download', fake_find), \
             mock.patch.object(video_analyzer, 'analyze_media', fake_engine):
            self.start('analyze', [self.reel], opts={'frame_interval': 0, 'analysis_provider': 'claude'})
            r = self.c.post('/api/jobs', json={'kind': 'analyze', 'ids': [self.vid, self.post]}, headers=W)
            self.assertEqual(r.status_code, 200, r.text)       # joined, not 409
            self.assertEqual(r.json()['total'], 2)              # the Post is not a video
            prog = self.c.get('/api/jobs/progress').json()
            self.assertEqual(prog['items'][0].get('step'), 'Transcribing…')
            gate.set()
            last = self.wait()
        self.assertEqual(last['done'], 2, self.c.get('/api/console').json())
        self.assertEqual(calls[0], (self.reel, 'claude', 0.0))
        it = self.item(self.vid)
        self.assertEqual(it['analysis_done'], 1)
        self.assertEqual(it['ai_desc'], 'A short summary.')
        self.assertEqual(it['tags'], 'blender, knee, mobility')
        # a describe while analyze runs would be refused; after it finished it is fine
        self.assertIsNone(self.c.get('/api/jobs').json()['current'])

    def test_analyze_stop_kills_the_running_step(self):
        # the real analyze_media: Stop during the first item's transcription kills its subprocess,
        # ends the job as stopped, skips the AI step and the report, never starts the second item
        transcribing = threading.Event()
        heard, toasts = [], []

        def fake_find(item_id, url, data_dir, cookies_resolver=None, should_stop=None, **kw):
            heard.append(should_stop)
            return Path(data_dir) / 'x.mp4'

        def slow_transcribe(video, should_stop=None, **kw):
            transcribing.set()      # stands in for ffmpeg: a process that would run for 60 s
            video_analyzer._run([sys.executable, '-c', 'import time; time.sleep(60)'], should_stop)
            return 'words', 'whisper_api'

        hub = self.app.state.jobs.hub
        publish = hub.publish

        def spy(kind, data):
            if kind == 'toast':
                toasts.append(data)
            publish(kind, data)

        ai = mock.Mock(return_value='ai')
        with mock.patch.object(video_analyzer, 'find_or_download', fake_find), \
             mock.patch.object(video_analyzer, 'transcribe_audio', slow_transcribe), \
             mock.patch.object(video_analyzer, '_analyze_with_ai', ai), \
             mock.patch.object(hub, 'publish', spy):
            self.start('analyze', [self.reel, self.vid], opts={'frame_interval': 0, 'transcribe': True,
                                                                'analysis_provider': 'claude'})
            self.assertTrue(transcribing.wait(5))
            self.c.post('/api/jobs/stop', headers=W)
            last = self.wait()                                  # 10 s timeout: the 60 s process was killed
        self.assertEqual((last['state'], last['done'], last['err'], last['total']), ('stopped', 0, 0, 2))
        self.assertEqual(len(heard), 1)                         # the second item never started
        self.assertTrue(callable(heard[0]))
        ai.assert_not_called()
        self.assertFalse((self.data / 'items' / str(self.reel) / 'report.md').exists())
        self.assertEqual(self.item(self.reel)['analysis_done'], 0)
        self.assertIn({'text': 'Stopped analyze videos after 0 of 2', 'level': 'w'}, toasts)

    def test_analyze_media_and_find_honour_should_stop(self):
        out = self.data / 'vt'
        with self.assertRaises(video_analyzer.AnalysisStopped):
            video_analyzer.analyze_media(self.data / 'x.mp4', out, frame_interval=0, transcribe=False,
                                         analysis_provider='none', should_stop=lambda: True)
        self.assertFalse((out / 'report.md').exists())
        with mock.patch('subprocess.Popen') as popen, self.assertRaises(video_analyzer.AnalysisStopped):
            video_analyzer.find_or_download(1, 'https://youtu.be/v', self.data, should_stop=lambda: True)
        popen.assert_not_called()

    def test_run_kills_on_stop(self):
        flag = threading.Event()
        threading.Timer(0.3, flag.set).start()
        t0 = time.time()
        with self.assertRaises(video_analyzer.AnalysisStopped):
            video_analyzer._run([sys.executable, '-c', 'import time; time.sleep(60)'], flag.is_set)
        self.assertLess(time.time() - t0, 10)
        r = video_analyzer._run([sys.executable, '-c', 'print(42)'], lambda: False,
                                stdout=subprocess.PIPE, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, '42'))

    def test_stopped_download_removes_partial_files(self):
        video_dir = self.data / 'items' / '7' / 'video'
        video_dir.mkdir(parents=True)
        (video_dir / 'notes.txt').write_text('mine')

        def killed(cmd, should_stop=None, **kw):
            self.assertEqual(cmd.count('--'), 1)
            self.assertEqual(cmd[-2:], ['--', 'https://youtu.be/v'])
            (video_dir / 'clip.f137.mp4').write_bytes(b'x')
            (video_dir / 'clip.f137.mp4.part').write_bytes(b'x')
            raise video_analyzer.AnalysisStopped('Stopped.')
        with mock.patch.object(video_analyzer, '_run', killed),              self.assertRaises(video_analyzer.AnalysisStopped):
            video_analyzer.find_or_download(7, 'https://youtu.be/v', self.data, should_stop=lambda: False)
        self.assertEqual([f.name for f in video_dir.iterdir()], ['notes.txt'])

    def test_index_batches_and_skips_unchanged(self):
        seen = []

        def embed(texts, api_key=None, base_url=None):
            seen.append(len(texts))
            return [[1.0, 0.0, 0.0] for _ in texts]
        with mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('k', None)), \
             mock.patch.object(ai_client, 'embed_texts', embed):
            self.start('index', [self.reel, self.vid])
            self.assertEqual(self.wait()['done'], 2)
            self.assertEqual(seen, [2])                         # one call for the batch
            r = self.c.post('/api/jobs', json={'kind': 'index', 'ids': [self.reel, self.vid]}, headers=W)
            self.assertEqual(r.status_code, 400)                # nothing changed: nothing to do
        rows = {x['id']: x for x in self.c.get('/api/items').json()['items']}
        self.assertEqual(rows[self.reel]['nd'] & 16, 0)

    def test_text_job_triggers_automatic_index(self):
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '{"category": "SPORT", "tags": ""}'), \
             mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('k', None)), \
             mock.patch.object(ai_client, 'embed_texts', lambda texts, **k: [[1.0, 0.0] for _ in texts]):
            self.start('categorize', [self.reel])
            end = time.time() + 10
            while time.time() < end:
                last = self.c.get('/api/jobs').json()['last']
                if last and last['kind'] == 'index' and last['state'] == 'finished':
                    break
                time.sleep(0.05)
            self.assertEqual(last['kind'], 'index')
            self.assertTrue(last['auto'])

    def test_note_writes_file(self):
        prompts = []

        def complete(provider, model, prompt, **kw):
            prompts.append(prompt)
            return '## Knee\nNotes from the sources.\n## Sources\n- ' + str(self.reel)
        with mock.patch.object(ai_client, 'complete_text', complete):
            r = self.c.post('/api/jobs', json={'kind': 'note', 'ids': [self.reel, self.vid]}, headers=W)
            self.assertEqual(r.status_code, 400)                # no topic
            self.start('note', [self.reel, self.vid, self.post], opts={'topic': 'Knee care'})
            last = self.wait()
        self.assertEqual(last['done'], 2)                       # the Post has no text
        f = self.data / 'notes' / 'knee-care.md'
        self.assertTrue(f.is_file())
        text = f.read_text(encoding='utf-8')
        self.assertIn('topic: Knee care', text)
        self.assertIn(f'sources: {self.reel},{self.vid}', text)
        self.assertIn('Synthesize the sources below', prompts[0])

    def test_download_streams_lines(self):
        def run(args, url, out_dir, on_line, should_stop, on_proc=None):
            on_line('[download]  50.0% of 1MiB ETA 00:01')
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            (Path(out_dir) / 'clip.jpg').write_bytes(b'\xff\xd8\xff\xd9' * 10)
            return True, 0, ''
        events = []
        hub = self.app.state.hub
        orig = hub.publish
        with mock.patch.object(ytdlp, 'run_streaming', run), \
             mock.patch.object(hub, 'publish', lambda k, d: (events.append((k, d)), orig(k, d))):
            r = self.c.post(f'/api/items/{self.vid}/download', json={'thumbnail_only': True}, headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            self.wait()
        self.assertIn(('ytdlp', {'job': r.json()['id'], 'id': self.vid, 'line': '[download]  50.0% of 1MiB ETA 00:01'}), events)
        self.assertEqual(self.item(self.vid)['thumb_path'], 'thumb.jpg')

    def test_download_needs_ytdlp(self):
        with mock.patch.object(ytdlp, 'available', lambda: False):
            r = self.c.post(f'/api/items/{self.vid}/download', json={}, headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], ytdlp.NOT_FOUND)

    def test_preview_is_not_video_success_and_failed_fragments_are_removed(self):
        def run(args, url, out_dir, **kw):
            (Path(out_dir) / 'preview.jpg').write_bytes(b'preview')
            return True, 0, ''
        with mock.patch.object(ytdlp, 'run_streaming', run):
            self.c.post(f'/api/items/{self.vid}/download', json={}, headers=W)
            job = self.wait()
        self.assertEqual(job['err'], 1)
        item = self.c.get('/api/jobs/progress').json()['items'][0]
        self.assertEqual(item['action'], 'source')
        self.assertIn('No complete video', item['error'])
        self.assertFalse((self.data / 'items' / str(self.vid) / 'video' / 'preview.jpg').exists())

    def test_analyze_settings_round_trip(self):
        g = self.c.get('/api/settings/analyze').json()
        self.assertEqual(g['options']['frame_interval'], 3.0)
        r = self.c.put('/api/settings/analyze', json={'frame_interval': 0, 'transcribe': False, 'analysis_provider': 'none'}, headers=W)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get('/api/settings/analyze').json()['options']['transcribe'], False)
        self.assertEqual(self.c.put('/api/settings/analyze', json={'analysis_provider': 'gpt9'}, headers=W).status_code, 400)


if __name__ == '__main__':
    unittest.main()
