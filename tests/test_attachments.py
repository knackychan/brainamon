from tests.test_ask_tool_stream import agent_from_stream
"""Ask attachments (projects/desktop-app plan 11): knowledge/attachments.py, /api/ask/attach,
/api/ask/panel and the attachments field of /api/ask. Temp data only, model calls stubbed.
Run:  py -m unittest tests.test_attachments -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from knowledge import attachments as att
from tests.auth_client import TestClient

from core import ai_client
from core import ai_defaults
from core.db import Database
from knowledge import tasks
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def events(resp):
    out, ev = [], None
    for line in resp.iter_lines():
        if line.startswith('event:'):
            ev = line.split(':', 1)[1].strip()
        elif line.startswith('data:') and ev:
            out.append((ev, json.loads(line.split(':', 1)[1])))
            ev = None
    return out


class AttachmentsModuleTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)

    def test_kind_of(self):
        self.assertEqual(att.kind_of('a.MD'), 'text')
        self.assertEqual(att.kind_of('b.jpeg'), 'image')
        with self.assertRaises(att.Unsupported):
            att.kind_of('c.mp4')

    def test_text_file_is_copied_to_the_inbox(self):
        d = att.save(self.data, 'notes.md', b'# Plan\nlift heavy', describe=None)
        self.assertEqual(d['kind'], 'text')
        self.assertTrue((self.data / 'inbox' / d['id']).is_file())
        self.assertEqual(att.resolve(self.data, d['id']), (d['id'], '# Plan\nlift heavy'))

    def test_image_is_described_once_and_kept(self):
        calls = []

        def describe(media_type, raw):
            calls.append((media_type, raw))
            return 'A squat rack, text: "5x5"'
        d = att.save(self.data, 'rack.png', b'\x89PNG fake', describe=describe)
        self.assertEqual(calls, [('image/png', b'\x89PNG fake')])
        self.assertEqual(d['kind'], 'image')
        self.assertTrue((self.data / 'inbox' / d['id']).is_file())
        self.assertEqual(att.resolve(self.data, d['id'])[1], 'A squat rack, text: "5x5"')

    def test_failed_description_leaves_nothing(self):
        def describe(media_type, raw):
            raise RuntimeError('no key')
        with self.assertRaises(RuntimeError):
            att.save(self.data, 'rack.png', b'img', describe=describe)
        self.assertFalse((self.data / 'inbox').exists() and any((self.data / 'inbox').iterdir()))

    def test_empty_and_too_big(self):
        with self.assertRaises(ValueError):
            att.save(self.data, 'a.txt', b'', describe=None)
        with self.assertRaises(ValueError):
            att.save(self.data, 'a.png', b'x' * (att.MAX_IMAGE_BYTES + 1), describe=lambda m, r: 'x')

    def test_text_is_saved_as_pasted(self):
        d = att.save_text(self.data, '  https://example.com/a  ')
        self.assertTrue(d['id'].endswith('pasted.txt'))
        self.assertEqual(att.resolve(self.data, d['id'])[1], 'https://example.com/a')
        with self.assertRaises(ValueError):
            att.save_text(self.data, '   ')

    def test_video_analysis(self):
        folder = self.data / 'video_tools' / 'items' / 'clip, take 2'
        folder.mkdir(parents=True)
        (folder / 'report.md').write_text('Report body', encoding='utf-8')
        (folder / 'transcript.txt').write_text('hello there', encoding='utf-8')
        d = att.analysis(self.data, str(folder))
        self.assertEqual((d['id'], d['kind']), ('video:clip, take 2', 'video'))
        name, text = att.resolve(self.data, d['id'])
        self.assertEqual(name, 'clip, take 2 (video analysis)')
        self.assertIn('Report body', text)
        self.assertIn('hello there', text)
        outside = self.data / 'elsewhere'
        outside.mkdir()
        with self.assertRaises(att.Gone):
            att.analysis(self.data, str(outside))

    def test_unsafe_ids_are_gone(self):
        (self.data / 'inbox').mkdir()
        (self.data / 'secret.txt').write_text('no', encoding='utf-8')
        for bad in ('', '../secret.txt', 'a/b.txt', 'a\\b.txt', '..', 'video:..', 'video:a/b', 'video:', 'C:secret.txt'):
            with self.assertRaises(att.Gone, msg=bad):
                att.resolve(self.data, bad)

    def test_history_pair_caps(self):
        pair = att.history_pair([('a.md', 'x' * 50)], cap=10)
        self.assertEqual([m['role'] for m in pair], ['user', 'assistant'])
        self.assertIn('Attached file "a.md"', pair[0]['content'])
        self.assertIn('[cut: the first 10 of 50 characters]', pair[0]['content'])
        self.assertEqual(pair[1]['content'], att.ACK)
        self.assertEqual(att.history_pair([], cap=10), [])


class AttachRouteTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.add_item({'url': 'https://x/1', 'description': 'Knee prehab with hip airplanes', 'category': 'SPORT'})
        db.close()
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),
                  mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None))):
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def attach_file(self, name, raw):
        return self.c.post(f'/api/ask/attach?name={name}', content=raw, headers=W)

    def test_text_file(self):
        r = self.attach_file('plan.md', b'deadlift day')
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual((d['kind'], d['chars']), ('text', 12))
        self.assertTrue((self.data / 'inbox' / d['id']).is_file())

    def test_image_uses_the_describe_model(self):
        seen = {}

        def fake(media_type, b64, provider, model):
            seen.update(media_type=media_type, provider=provider, model=model)
            return 'a chart'
        with mock.patch.object(tasks, 'describe_attachment', fake):
            d = self.attach_file('chart.png', b'png-bytes').json()
        self.assertEqual(seen['media_type'], 'image/png')
        self.assertEqual((seen['provider'], seen['model']), ai_defaults._DEFAULT)
        self.assertEqual(d['chars'], len('a chart'))

    def test_image_failure_is_400_and_files_nothing(self):
        def boom(*a):
            raise RuntimeError('no key')
        with mock.patch.object(tasks, 'describe_attachment', boom):
            r = self.attach_file('chart.png', b'png-bytes')
        self.assertEqual(r.status_code, 400)
        self.assertIn('could not read the picture', r.json()['detail'])
        self.assertFalse((self.data / 'inbox').exists() and any((self.data / 'inbox').iterdir()))

    def test_unsupported_type_is_415(self):
        r = self.attach_file('clip.mp4', b'mp4')
        self.assertEqual(r.status_code, 415)
        self.assertEqual(r.json()['detail'], 'Wiskit cannot read .mp4 files yet.')

    def test_text_and_analysis_json(self):
        d = self.c.post('/api/ask/attach', json={'text': 'remember this'}, headers=W).json()
        self.assertTrue(d['id'].endswith('pasted.txt'))
        folder = self.data / 'video_tools' / 'items' / 'clip'
        folder.mkdir(parents=True)
        (folder / 'report.md').write_text('rep', encoding='utf-8')
        d = self.c.post('/api/ask/attach', json={'analysis': str(folder)}, headers=W).json()
        self.assertEqual(d['id'], 'video:clip')
        r = self.c.post('/api/ask/attach', json={'analysis': str(self.data)}, headers=W)
        self.assertEqual(r.status_code, 404)

    def test_panel_event(self):
        published = []
        with mock.patch.object(self.app.state.hub, 'publish', lambda k, d: published.append((k, d)) if k == 'panel_attach' else None):
            self.app.state.hub.publish('map', {})
            r = self.c.post('/api/ask/panel', json={'ids': ['a.md', '', 'video:x']}, headers=W)
        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(published, [('panel_attach', {'ids': ['a.md', 'video:x']})])

    def ask(self, **body):
        with self.c.stream('POST', '/api/ask', json=body, headers=W) as r:
            self.assertEqual(r.status_code, 200)
            return events(r)

    def test_ask_with_an_attachment_and_a_follow_up(self):
        aid = self.attach_file('plan.md', b'Squat 5x5 on Mondays' + b'.' * 9000).json()['id']
        seen = []

        def stream(messages, provider, model, **kw):
            seen.append(messages)
            yield 'Mondays.'
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            ev = self.ask(question='when do I squat?', attachments=[aid], provider='anthropic',
                          model='claude-sonnet-5-5', mode='quick')
            done = ev[-1][1]
            self.assertEqual(ev[-1][0], 'done', ev)
            self.ask(question='and how many sets?', chat=done['chat']['slug'], provider='anthropic',
                     model='claude-sonnet-5-5', mode='quick')
        first = seen[0]
        self.assertIn('Attached file "' + aid + '"', first[-3]['content'])
        self.assertNotIn('[cut:', first[-3]['content'])                 # full text in the turn
        self.assertEqual(first[-2]['content'], att.ACK)
        self.assertIn('when do I squat?', first[-1]['content'])
        self.assertEqual(done['chat']['name'], 'when do I squat?')
        self.assertTrue(any('Squat 5x5' in m['content'] for m in seen[1]))   # the follow-up still sees it
        chat = self.c.get(f"/api/chats/{done['chat']['slug']}").json()
        self.assertEqual([m['role'] for m in chat['history']][:4], ['user', 'assistant', 'user', 'assistant'])
        self.assertIn('[cut: the first 8000 of', chat['history'][0]['content'])   # capped when saved

    def test_ask_with_a_gone_attachment(self):
        ev = self.ask(question='what is this?', attachments=['2026-01-01-missing.md'])
        self.assertEqual(ev, [('error', {'message': att.GONE})])


if __name__ == '__main__':
    unittest.main()
