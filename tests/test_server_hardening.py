"""Audit fixes B2 and A1: a Wiskit chat slug is validated before it becomes a file name
(knowledge/ask_chats.py, server/routes/ask.py), and an item's video upload has a size cap
(server/routes/items.py, 413 like Video Tools).

Run from the project root:  py -m unittest tests.test_server_hardening -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core.db import Database
from knowledge import ask_chats
from knowledge.ask_chats import AskChatStore
from server.app import create_app
from server.routes import items as items_routes

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
BAD = ['', '..', '../x', '..\\..\\x', 'a/b', 'a\\b', 'C:x', 'Chat', '-a', 'a.json', 'a\n', 'a' * 82, None, 3]


class ChatSlugTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.store = AskChatStore(self.root / 'data')
        (self.root / 'data' / 'secret.json').write_text('{"name": "outside"}', encoding='utf-8')

    def test_valid_slugs(self):
        for slug in ('chat', 'kettlebell', 'new-chat-2', 'a' * 81):
            self.assertTrue(ask_chats.valid_slug(slug), slug)
        for slug in BAD:
            self.assertFalse(ask_chats.valid_slug(slug), slug)

    def test_store_refuses_bad_slugs(self):
        self.assertIsNone(self.store.load('../secret'))
        self.assertIsNone(self.store.load('..\\secret'))
        self.store.delete('../secret')
        self.assertTrue((self.root / 'data' / 'secret.json').exists())
        with self.assertRaises(ValueError):
            self.store.save('../secret', {'name': 'x'})
        with self.assertRaises(ValueError):
            self.store.rename('../secret', 'x')

    def test_created_slugs_stay_valid(self):
        for name in ('New chat', 'Été ✨ 2026', 'x' * 300, '!!!'):
            slug, _ = self.store.create(name)
            self.assertTrue(ask_chats.valid_slug(slug), slug)
        slug, _ = self.store.create('x' * 300)          # the second one gets a -2 suffix
        self.assertTrue(ask_chats.valid_slug(slug), slug)


class RoutesTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name) / 'data'
        db = Database(self.data / 'content_manager.db')
        self.item = db.add_item({'url': 'https://x/v', 'type': 'Video'})
        db.close()
        (self.data / 'secret.json').write_text('{"name": "outside"}', encoding='utf-8')
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_chat_routes(self):
        for slug in ('..%5Csecret', '%2E%2E%5Csecret', 'Secret'):
            with self.subTest(slug=slug):
                self.assertEqual(self.c.get(f'/api/chats/{slug}').status_code, 404)
                self.assertEqual(self.c.put(f'/api/chats/{slug}', json={'options': {}}, headers=W).status_code, 404)
                self.assertEqual(self.c.post(f'/api/chats/{slug}/rename', json={'name': 'x'}, headers=W).status_code, 404)
                self.assertEqual(self.c.post(f'/api/chats/{slug}/clear', headers=W).status_code, 404)
                self.assertEqual(self.c.delete(f'/api/chats/{slug}', headers=W).status_code, 200)
        self.assertTrue((self.data / 'secret.json').exists())
        self.assertEqual(self.c.put('/api/chats/active', json={'slug': '..\\secret'}, headers=W).status_code, 400)
        made = self.c.post('/api/chats', json={'name': 'Hips'}, headers=W).json()['slug']
        self.assertEqual(self.c.get(f'/api/chats/{made}').status_code, 200)
        self.assertEqual(self.c.put('/api/chats/active', json={'slug': made}, headers=W).status_code, 200)

    def test_video_upload_cap(self):
        url = f'/api/items/{self.item}/video'
        vdir = self.data / 'items' / str(self.item) / 'video'
        with mock.patch.object(items_routes, 'MAX_VIDEO', 10):
            r = self.c.put(url, params={'name': 'big.mp4'}, content=b'x' * 11, headers=W)
            self.assertEqual(r.status_code, 413)
            self.assertFalse(vdir.exists() and any(vdir.iterdir()))       # no .part, no file left

            def body():                                                   # streamed: no Content-Length
                yield b'x' * 6
                yield b'x' * 6
            r = self.c.put(url, params={'name': 'big.mp4'}, content=body(), headers=W)
            self.assertEqual(r.status_code, 413)
            self.assertFalse(vdir.exists() and any(vdir.iterdir()))
            r = self.c.put(url, params={'name': 'ok.mp4'}, content=b'x' * 10, headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['bytes'], 10)


if __name__ == '__main__':
    unittest.main()
