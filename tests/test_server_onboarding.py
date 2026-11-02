"""First run (server/routes/onboarding.py): the welcome answer, the Get started view and its Hide, on a
temp library (nothing real is touched; keys come from a patched environment and are never written).

Run from the project root:  py -m unittest tests.test_server_onboarding -v
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import config
from core.db import Database
from library import ytdlp
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
NO_KEYS = {k: '' for k in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'FREELLMAPI_API_KEY', 'LOCAL_OPENAI_BASE_URL')}


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        Database(self.data / 'content_manager.db').close()
        for p in (mock.patch.object(config, 'ENV_PATH', self.root / '.env'),
                  mock.patch.object(ytdlp, 'registry_get', lambda name: ''),     # no Qt-era cookie paths
                  mock.patch.dict(os.environ, NO_KEYS)):
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x', cloud_dir=self.root / 'cloud'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def view(self):
        r = self.c.get('/api/onboarding')
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_a_new_library_gets_the_welcome(self):
        self.assertEqual(self.view(), {'answer': '', 'hidden': False, 'welcome': True, 'items': 0, 'notes': 0, 'wiskit': False, 'step': 'library', 'skipped': []})
        self.assertEqual(self.c.get('/api/categories').json(), [])

    def test_first_collection_can_be_created_and_deleted_without_losing_items(self):
        created = self.c.post('/api/categories', json={'name': 'Ideas', 'color': '#123456'}, headers=W)
        self.assertEqual(created.status_code, 200)
        self.assertEqual([c['name'] for c in created.json()], ['IDEAS'])
        item = self.c.post('/api/items', json={
            'url': 'https://example.com/idea', 'description': 'Saved idea', 'category': 'IDEAS'}, headers=W)
        self.assertEqual(item.status_code, 200)
        deleted = self.c.delete('/api/categories/IDEAS', headers=W)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), [])
        rows = self.c.get('/api/items').json()['items']
        self.assertEqual([r['id'] for r in rows], [item.json()['id']])

    def test_the_answer_is_saved_and_ends_the_welcome(self):
        v = self.c.put('/api/onboarding', json={'answer': 'instagram'}, headers=W).json()
        self.assertEqual((v['answer'], v['welcome']), ('instagram', False))
        self.assertEqual(self.view()['answer'], 'instagram')
        self.c.put('/api/onboarding', json={'answer': 'skip'}, headers=W)
        v = self.view()
        self.assertEqual((v['answer'], v['welcome']), ('skip', False))

    def test_bad_requests_change_nothing(self):
        self.assertEqual(self.c.put('/api/onboarding', json={'answer': 'tiktok'}, headers=W).status_code, 400)
        self.assertEqual(self.c.put('/api/onboarding', json={'hidden': 'yes'}, headers=W).status_code, 400)
        self.assertEqual(self.c.put('/api/onboarding', json={'answer': 'reddit'}).status_code, 403)     # no X-CM header
        v = self.view()
        self.assertEqual((v['answer'], v['hidden']), ('', False))

    def test_setup_navigation_is_validated_partial_and_persistent(self):
        patch = {'answer': 'files', 'step': 'ai', 'skipped': ['tools', 'content']}
        result = self.c.put('/api/onboarding', json=patch, headers=W)
        self.assertEqual(result.status_code, 200)
        for key, value in patch.items():
            self.assertEqual(self.view()[key], value)
        self.c.put('/api/onboarding', json={'hidden': True}, headers=W)
        self.assertEqual(self.view()['step'], 'ai')
        self.assertEqual(self.view()['skipped'], ['tools', 'content'])
        before = self.view()
        for bad in ({'step': None}, {'step': 'secrets'}, {'step': 2}, {'skipped': None},
                    {'skipped': ['tools'] * 7}, {'skipped': ['tools', 'tools']},
                    {'skipped': [['tools']]}, {'skipped': ['summary']}, {'skipped': [True]}):
            self.assertEqual(self.c.put('/api/onboarding', json=bad, headers=W).status_code, 400, bad)
            self.assertEqual(self.view(), before)
        self.c.app.state.writer.call(lambda db: (db.set_setting('onboard_step', 'obsolete'), db.set_setting('onboard_skipped', '{invalid')))
        self.assertEqual((self.view()['step'], self.view()['skipped']), ('library', []))

    def test_hide_persists(self):
        self.assertTrue(self.c.put('/api/onboarding', json={'hidden': True}, headers=W).json()['hidden'])
        self.assertTrue(self.view()['hidden'])
        self.assertFalse(self.c.put('/api/onboarding', json={'hidden': False}, headers=W).json()['hidden'])

    def test_a_library_from_before_never_gets_the_welcome(self):
        self.assertTrue(self.c.post('/api/app/setup/dismiss', headers=W).json()['ok'])
        self.assertFalse(self.view()['welcome'])
        self.assertTrue(self.view()['hidden'])

    def test_hidden_unanswered_welcome_stays_hidden(self):
        self.c.put('/api/onboarding', json={'hidden': True}, headers=W)
        self.assertFalse(self.view()['welcome'])

    def test_an_item_ends_the_welcome_and_a_note_counts_while_there_is_none(self):
        notes = self.data / 'notes'
        notes.mkdir(exist_ok=True)
        (notes / 'a-topic.md').write_text('---\ntopic: A topic\n---\nSynthesized, not personal.\n', encoding='utf-8')
        self.assertEqual(self.view()['notes'], 0)              # Knowledge notes do not count
        made = self.c.post('/api/my-notes', json={'title': 'A thought', 'category': 'Inbox'}, headers=W)
        self.assertEqual(made.status_code, 200)
        v = self.view()
        self.assertEqual((v['notes'], v['welcome']), (1, True))
        self.c.app.state.writer.call(lambda db: db.add_item({'url': 'https://example.com/first'}))
        v = self.view()
        self.assertEqual((v['items'], v['notes'], v['welcome']), (1, 0, False))

    def test_wiskit_follows_the_wiskit_providers_key(self):
        # Wiskit runs on OpenAI until a model is chosen (core/ai_defaults.py): an Anthropic key alone is not enough
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            self.assertFalse(self.view()['wiskit'])
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}):
            self.assertTrue(self.view()['wiskit'])
        self.assertFalse(self.view()['wiskit'])

    def test_reading_never_writes(self):
        with mock.patch.object(self.c.app.state.writer, 'submit', side_effect=AssertionError('GET used the Writer')):
            self.view()


if __name__ == '__main__':
    unittest.main()
