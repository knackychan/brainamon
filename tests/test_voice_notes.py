"""Voice notes, PC side (projects/voice-notes/plans/01-pc.md): the transcription call is stubbed.

Run from the project root:  py -m unittest tests.test_voice_notes -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from knowledge import my_notes
from server.app import create_app
from server.routes import my_notes as routes

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class VoiceCoreTest(unittest.TestCase):
    def test_append_voice(self):
        self.assertEqual(my_notes.append_voice('', ' hello ', '2026-10-12 09:30'), '## Voice note - 2026-10-12 09:30\n\nhello\n')
        self.assertEqual(my_notes.append_voice('Intro\n', 'hi', '2026-10-12 09:30'),
                         'Intro\n\n## Voice note - 2026-10-12 09:30\n\nhi\n')

    def test_model_id_comes_from_ai_client(self):
        self.assertEqual(ai_client.phone_settings('anthropic', ai_client.CLAUDE_MODEL)['transcription_model'], ai_client.WHISPER_MODEL)


class VoiceRouteTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()          # runs the lifespan: the Writer and the SSE hub
        self.addCleanup(self.c.__exit__, None, None, None)
        for p in (mock.patch('server.routes.my_notes.config.openai_api_key', return_value='sk-test'),
                  mock.patch('knowledge.voice.transcribe_upload', return_value='buy milk')):
            p.start()
            self.addCleanup(p.stop)

    def test_new_note_then_append(self):
        r = self.c.post('/api/my-notes/voice', content=b'audio', headers={**W, 'Content-Type': 'audio/webm'})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertTrue(j['title'].startswith('Voice note '))
        self.assertEqual(j['text'], 'buy milk')
        body = self.c.get(f"/api/my-notes/{j['file']}").json()['body']
        self.assertIn('## Voice note - ', body)
        r2 = self.c.post('/api/my-notes/voice', params={'file': j['file']}, content=b'audio', headers=W)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(self.c.get(f"/api/my-notes/{j['file']}").json()['body'].count('## Voice note - '), 2)

    def test_refusals(self):
        with mock.patch('server.routes.my_notes.config.openai_api_key', return_value=''):
            self.assertEqual(self.c.post('/api/my-notes/voice', content=b'a', headers=W).status_code, 400)
        self.assertEqual(self.c.post('/api/my-notes/voice', content=b'', headers=W).status_code, 400)
        self.assertEqual(self.c.post('/api/my-notes/voice', params={'file': 'nope.md'}, content=b'a', headers=W).status_code, 404)
        with mock.patch.object(routes, 'MAX_VOICE_BYTES', 3):
            self.assertEqual(self.c.post('/api/my-notes/voice', content=b'abcd', headers=W).status_code, 413)
        with mock.patch.object(routes, '_voice_busy', True):
            self.assertEqual(self.c.post('/api/my-notes/voice', content=b'a', headers=W).status_code, 409)
        with mock.patch('server.routes.my_notes.entitlements.feature_enabled', return_value=False):
            self.assertEqual(self.c.post('/api/my-notes/voice', content=b'a', headers=W).status_code, 403)

    def test_no_speech(self):
        with mock.patch('knowledge.voice.transcribe_upload', return_value=''):
            self.assertEqual(self.c.post('/api/my-notes/voice', content=b'a', headers=W).status_code, 400)


if __name__ == '__main__':
    unittest.main()
