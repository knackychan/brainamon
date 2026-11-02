"""Add to Brainamon on the desktop (projects/note-organic-ui/plans/09-add-to-brainamon.md): the routes the
window and Wiskit's panel use, on temp data. Nothing new writes: a Library item is POST /api/items, a new
note is POST + PUT /api/my-notes, an addition is POST /api/filing/file (the old text stays), and the panel
hands text over with POST /api/app/capture. Run:  py -m unittest tests.test_capture_server -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core.db import Database
from knowledge import filing, tasks
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class CaptureServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        Database(self.data / 'content_manager.db').close()
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_the_panel_hands_text_to_the_main_window_once(self):
        with mock.patch('server.routes.app.autostart.spawn') as spawn, mock.patch.object(self.app.state.hub, 'publish') as pub:
            r = self.c.post('/api/app/capture', json={'text': '  Remember the bookshop  '}, headers=W)
        self.assertEqual(r.status_code, 200)
        spawn.assert_called_once()
        self.assertEqual([c for c in pub.call_args_list if c.args[0] == 'capture_open'], [mock.call('capture_open', {})])
        self.assertEqual(self.c.post('/api/app/capture/take', json={}, headers=W).json(), {'text': 'Remember the bookshop'})
        self.assertEqual(self.c.post('/api/app/capture/take', json={}, headers=W).json(), {'text': ''})

    def test_the_panel_refuses_empty_text_and_foreign_posts(self):
        self.assertEqual(self.c.post('/api/app/capture', json={'text': '   '}, headers=W).status_code, 400)
        self.assertEqual(self.c.post('/api/app/capture', json={'text': 'x'}).status_code, 403)    # no X-CM

    def test_a_library_item_keeps_its_comment_collection_type_and_tags_and_refuses_a_duplicate(self):
        body = {'url': 'https://example.com/read-later', 'notes': 'Why I kept it', 'category': 'INTERESTING', 'type': 'Link', 'tags': 'a, b'}
        with mock.patch.object(self.app.state.jobs, 'start'):
            row = self.c.post('/api/items', json=body, headers=W)
            again = self.c.post('/api/items', json=body, headers=W)
        self.assertEqual(row.status_code, 200)
        item = self.c.get(f"/api/items/{row.json()['id']}").json()
        self.assertEqual((item['notes'], item['category'], item['type'], item['tags']), ('Why I kept it', 'INTERESTING', 'Link', 'a, b'))
        self.assertEqual(again.status_code, 409)

    def test_a_new_note_lands_in_inbox_and_an_addition_leaves_the_old_text_alone(self):
        made = self.c.post('/api/my-notes', json={'title': 'A thought', 'category': 'Inbox'}, headers=W).json()
        saved = self.c.put(f"/api/my-notes/{made['file']}", json={'title': 'A thought', 'category': 'Inbox', 'body': 'First line.\n'}, headers=W).json()
        self.assertEqual(saved['category'], 'Inbox')
        self.assertEqual(self.c.get(f"/api/my-notes/{made['file']}").json()['body'].strip(), 'First line.')
        r = self.c.post('/api/filing/file', json={'action': 'append', 'file': made['file'], 'name': 'Note', 'text': 'Second, with a comment.'}, headers=W)
        self.assertEqual(r.status_code, 200)
        body = self.c.get(f"/api/my-notes/{made['file']}").json()['body']
        self.assertTrue(body.startswith('First line.\n\n## From Note - '), body)
        self.assertTrue(body.rstrip().endswith('Second, with a comment.'))
        self.assertEqual(body.count(filing.heading('append', 'Note', '')[:12]), 1)

    def test_reading_a_picture_without_a_key_says_so_plainly(self):
        def sdk(*_a):
            raise RuntimeError('Could not resolve authentication method')     # what the SDK says; never a real call
        with mock.patch('core.config.key_for_provider', lambda provider: ''), mock.patch.object(tasks, 'transcribe_screenshot', sdk):
            r = self.c.post('/api/filing/read?name=s.png&how=digest', content=b'png', headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertIn('key on the PC (Settings > API keys)', r.json()['detail'])


if __name__ == '__main__':
    unittest.main()
