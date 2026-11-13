"""The drop panel's Inbox (projects/desktop-app plan 07): inbox.py + /api/inbox/*. Temp data only.
Run:  py -m unittest tests.test_server_inbox -v
"""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from knowledge import inbox
from knowledge import knowledge
from core.db import Database
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
SHARE_LINKS = json.loads((Path(__file__).parent / 'fixtures' / 'share_links.json').read_text(encoding='utf-8'))['cases']
LINK_MISSES = ('a thought', 'notes.md', 'app.py', 'look at text.com', 'localhost', '1.2', 'ftp://x.y', 'x.c',
               'C:\a\b.mp4', '')


class InboxTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        Database(self.data / 'content_manager.db').close()
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def _inbox_body(self, file):
        return knowledge.split_frontmatter((self.data / 'notes' / file).read_text(encoding='utf-8'))

    def test_is_url(self):
        self.assertTrue(inbox.is_url(' https://www.instagram.com/reel/abc/ '))
        self.assertFalse(inbox.is_url('look at https://x.com'))

    def test_link_without_scheme(self):
        for raw, url in (('text.com', 'https://text.com'), ('www.example.org/a?b=1', 'https://www.example.org/a?b=1'),
                         ('HTTPS://x.y/z', 'HTTPS://x.y/z'), ('instagram.com/reel/abc/', 'https://instagram.com/reel/abc/'),
                         ('sub.domain.co.uk:8080/p', 'https://sub.domain.co.uk:8080/p'), ('www.notes.md', 'https://www.notes.md')):
            self.assertEqual(inbox.link(f' {raw} '), url)
        for raw in LINK_MISSES:
            self.assertIsNone(inbox.link(raw), raw)

    def test_link_from_shared_text(self):
        # apps share "Check this out https://...?igsh=..."; the link is pulled out and cleaned the
        # same way on the phone (web/src/mobile/links.ts) and in the widget (tests share the cases)
        for raw, url in SHARE_LINKS:
            self.assertEqual(inbox.link(raw), url, raw)
        self.assertFalse(inbox.is_url('look at https://x.com'))

    def test_shared_link_dedupes_against_the_clean_one(self):
        with mock.patch.object(self.app.state.jobs, 'start'):
            r = self.c.post('/api/inbox/link', json={'url': 'https://www.instagram.com/reel/C9/'}, headers=W).json()
            again = self.c.post('/api/inbox/link', json={'url': 'Look https://www.instagram.com/reel/C9/?igsh=abc'}, headers=W).json()
        self.assertEqual((again['id'], again['new']), (r['id'], False))

    def test_facebook_watch_and_reel_are_one_item(self):
        with mock.patch.object(self.app.state.jobs, 'start') as start:
            first = self.c.post('/api/inbox/link', json={'url': 'https://www.facebook.com/watch/?v=1234567890'}, headers=W).json()
            again = self.c.post('/api/inbox/link', json={'url': 'https://m.facebook.com/reel/1234567890/'}, headers=W).json()
            self.assertEqual(again, {'id': first['id'], 'new': False})
            self.assertEqual(start.call_count, 1)
            manual = self.c.post('/api/items', json={'url': 'https://www.facebook.com/Example/videos/1234567890/',
                                                    'description': 'Different title'}, headers=W)
            self.assertEqual(manual.status_code, 409)

    def test_text_goes_to_one_inbox_note(self):
        a = self.c.post('/api/inbox/text', json={'text': 'first thought'}, headers=W).json()
        b = self.c.post('/api/inbox/text', json={'text': 'second thought'}, headers=W).json()
        self.assertEqual(a['file'], b['file'])
        meta, body = self._inbox_body(a['file'])
        self.assertEqual((meta['topic'], meta['category'], meta['kind']), ('Inbox', 'Inbox', 'personal'))
        self.assertLess(body.index('first thought'), body.index('second thought'))

    def test_link_creates_item_once(self):
        with mock.patch.object(self.app.state.jobs, 'start') as start:
            r = self.c.post('/api/inbox/link', json={'url': 'https://youtu.be/abc'}, headers=W).json()
            self.assertTrue(r['new'])
            start.assert_called_once_with('thumb', [r['id']], True, {})
            again = self.c.post('/api/inbox/link', json={'url': 'https://youtu.be/abc'}, headers=W).json()
        self.assertEqual((again['id'], again['new']), (r['id'], False))
        self.assertEqual(self.c.post('/api/inbox/link', json={'url': 'not a link'}, headers=W).status_code, 400)

    def test_link_route_adds_https(self):
        with mock.patch.object(self.app.state.jobs, 'start'):
            r = self.c.post('/api/inbox/link', json={'url': 'www.text.com/a'}, headers=W).json()
            again = self.c.post('/api/inbox/link', json={'url': 'https://www.text.com/a'}, headers=W).json()
        self.assertEqual((again['id'], again['new']), (r['id'], False))

    def test_file_is_copied_and_listed(self):
        r = self.c.post('/api/inbox/file?name=report%20q3.pdf', content=b'%PDF-1.4 x', headers=W).json()
        path = Path(r['path'])
        self.assertEqual(path.parent, self.data / 'inbox')
        self.assertTrue(path.name.endswith('report q3.pdf'))
        self.assertIn(path.name, self._inbox_body(r['file'])[1])
        r2 = self.c.post('/api/inbox/file?name=report%20q3.pdf', content=b'other', headers=W).json()
        self.assertNotEqual(r2['path'], r['path'])          # never overwrites

    def test_screenshot_starts_digest_on_inbox(self):
        img = base64.b64encode(b'\x89PNG fake').decode()
        with mock.patch.object(self.app.state.jobs, 'start', return_value={'ok': True}) as start:
            self.c.post('/api/inbox/screenshot', json={'images': [{'name': 's.png', 'type': 'image/png', 'data': img}]}, headers=W)
        kind, ids, force, opts = start.call_args.args
        self.assertEqual(kind, 'digest')
        self.assertEqual(self._inbox_body(opts['file'])[0]['topic'], 'Inbox')


if __name__ == '__main__':
    unittest.main()
