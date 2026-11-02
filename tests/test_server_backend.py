"""V6 backend skeleton: read endpoints, the single writer, the localhost guard.

Run from the project root:  py -m unittest tests.test_server_backend -v
Uses a temporary data folder; never touches data/.
"""
import tempfile
import threading
import unittest
from pathlib import Path

from tests.auth_client import TestClient

from core.db import Database
from server.app import create_app
from server.store import Writer, reader

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class BackendTest(unittest.TestCase):
    def setUp(self):
        # reader connections stay open in the test client's pool threads; Windows then
        # refuses to delete the db file, so cleanup errors are ignored
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.add_category('SPORT', '#2E75B6')
        db.add_category('INTERESTING', '#4472C4')
        self.a = db.add_item({'url': 'https://www.facebook.com/reel/1', 'description': 'Knee prehab <b>hip</b>',
                              'creator': 'Pulse', 'type': 'Reel', 'category': 'SPORT', 'tags': 'knee, mobility'})
        self.b = db.add_item({'url': 'https://youtu.be/x', 'description': 'Blender donut', 'type': 'Video',
                              'category': 'INTERESTING', 'ai_desc': 'A donut tutorial.'})
        (self.data / 'items' / str(self.a)).mkdir(parents=True, exist_ok=True)
        (self.data / 'items' / str(self.a) / 'thumb.jpg').write_bytes(b'\xff\xd8\xff\xd9')
        db.update_item(self.a, {'thumb_path': 'thumb.jpg'})
        db.close()
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_items_compact_rows(self):
        r = self.c.get('/api/items')
        self.assertEqual(r.status_code, 200)
        rows = {x['id']: x for x in r.json()['items']}
        self.assertEqual(r.json()['total'], 2)
        a, b = rows[self.a], rows[self.b]
        self.assertEqual(a['title'], 'Knee prehab <b>hip</b>')      # raw; the front end escapes
        self.assertEqual(a['src'], 'facebook')
        self.assertTrue(a['thumb'])
        self.assertEqual(a['nd'] & 1, 0)                              # has a thumbnail
        self.assertEqual(b['nd'], 1 | 4 | 8 | 16)                     # needs thumb, analyze, categorize, index (plan 05)
        self.assertEqual(b['title'], 'A donut tutorial.')            # ai_desc before description

    def test_item_detail_and_404(self):
        r = self.c.get(f'/api/items/{self.a}')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['files']['thumb'])
        self.assertEqual(self.c.get('/api/items/999').status_code, 404)

    def test_categories_tags_search(self):
        cats = {c['name']: c['count'] for c in self.c.get('/api/categories').json()}
        self.assertEqual(cats['SPORT'], 1)
        self.assertIn({'tag': 'knee', 'n': 1}, self.c.get('/api/tags').json())
        self.assertEqual(self.c.get('/api/search', params={'q': 'knee hip'}).json()['ids'], [self.a])
        self.assertEqual(self.c.get('/api/search', params={'q': ''}).json()['ids'], [])
        # a whole number also finds the item with that id; a missing id adds nothing
        self.assertEqual(self.c.get('/api/search', params={'q': f' {self.b} '}).json()['ids'][0], self.b)
        self.assertEqual(self.c.get('/api/search', params={'q': '999'}).json()['ids'], [])

    def test_thumb(self):
        r = self.c.get(f'/thumb/{self.a}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['cache-control'], 'no-cache')
        self.assertEqual(self.c.get(f'/thumb/{self.b}').status_code, 404)

    def test_patch_goes_through_writer(self):
        r = self.c.patch(f'/api/items/{self.a}', json={'creator': 'New', 'ai_desc': 'ignored'}, headers=W)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['creator'], 'New')
        row = self.c.get(f'/api/items/{self.a}').json()
        self.assertEqual(row['creator'], 'New')
        self.assertEqual(row['ai_desc'], '')                          # not editable
        dup = self.c.patch(f'/api/items/{self.a}', json={'url': 'https://youtu.be/x'}, headers=W)
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(self.c.patch(f'/api/items/{self.a}', json={'description': ' '}, headers=W).status_code, 400)

    def test_guard(self):
        self.assertEqual(self.c.patch(f'/api/items/{self.a}', json={'creator': 'x'}).status_code, 403)
        bad = TestClient(self.c.app, base_url='http://evil.example:8765')
        self.assertEqual(bad.get('/api/items').status_code, 403)
        self.assertEqual(self.c.get('/api/health').json()['items'], 2)


class WriterTest(unittest.TestCase):
    def test_single_thread_and_ordering(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            path = Path(td) / 'content_manager.db'
            w = Writer(path)
            w.start()
            names = set()
            ids = [w.call(lambda db, i=i: (names.add(threading.current_thread().name),
                                           db.add_item({'url': f'u{i}', 'description': 'd'}))[1])
                   for i in range(5)]
            self.assertEqual(names, {'cm-writer'})
            self.assertEqual(ids, sorted(ids))
            self.assertEqual(reader(path).count_items(), 5)          # readers see committed writes
            with self.assertRaises(ZeroDivisionError):
                w.call(lambda db: 1 / 0)
            self.assertEqual(w.call(lambda db: db.count_items()), 5)  # writer survives an error
            w.stop()
            reader(path).close()


if __name__ == '__main__':
    unittest.main()
