"""V6 plan 05 server pieces: favourites, the nd bits, smart search (embedding stubbed), tints.

Run from the project root:  py -m unittest tests.test_server_library -v
Uses a temporary data folder; never touches data/.
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from library import search
from core.db import Database
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def _jpeg(path: Path, rgb) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (40, 40), rgb).save(path, 'JPEG')


class LibraryTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://www.facebook.com/reel/1', 'description': 'Knee prehab hip',
                              'type': 'Reel', 'category': 'SPORT', 'tags': 'knee'})
        self.b = db.add_item({'url': 'https://youtu.be/x', 'description': 'Blender donut', 'type': 'Video',
                              'category': 'BLENDER', 'ai_desc': 'A donut tutorial.'})
        # item a is indexed with a unit vector on axis 0, item b on axis 1
        dim = 4
        db.upsert_embedding(self.a, ai_client.EMBEDDING_MODEL, dim, 'h1', search.vec_to_blob([1, 0, 0, 0]))
        db.upsert_embedding(self.b, ai_client.EMBEDDING_MODEL, dim, 'h2', search.vec_to_blob([0, 1, 0, 0]))
        db.close()
        _jpeg(self.data / 'items' / str(self.a) / 'thumb.jpg', (200, 20, 20))
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.app = app
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def rows(self):
        return {x['id']: x for x in self.c.get('/api/items').json()['items']}

    def test_favourite_round_trip(self):
        self.assertFalse(self.rows()[self.a]['fav'])
        r = self.c.post(f'/api/items/{self.a}/favourite', json={'on': True}, headers=W)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['fav'])
        self.assertTrue(self.rows()[self.a]['fav'])
        self.assertFalse(self.c.post(f'/api/items/{self.a}/favourite', json={'on': False}, headers=W).json()['fav'])
        self.assertEqual(self.c.post('/api/items/999/favourite', json={'on': True}, headers=W).status_code, 404)
        self.assertEqual(self.c.post(f'/api/items/{self.a}/favourite', json={'on': True}).status_code, 403)

    def test_items_cache_sees_writer_writes(self):
        # /api/items keeps its body until the Writer's next write (plan 10-footprint A4: the
        # Writer is the only connection that writes while the server runs)
        self.assertEqual(self.rows()[self.a]['creator'], '')
        self.rows()
        self.app.state.writer.call(lambda db: db.update_item(self.a, {'creator': 'writer'}))
        self.assertEqual(self.rows()[self.a]['creator'], 'writer')

    def test_items_cols_format(self):
        c = self.c.get('/api/items?fmt=cols').json()
        rows = [dict(zip(c['cols'], v)) for v in c['rows']]
        self.assertEqual(c['total'], 2)
        self.assertEqual({r['id'] for r in rows}, set(self.rows()))
        self.assertIn(rows[0]['fav'], (0, 1))
        one = self.c.get(f'/api/items?fmt=cols&ids={self.a}').json()
        self.assertEqual(dict(zip(one['cols'], one['rows'][0]))['id'], self.a)

    def test_thumb_cache_headers(self):
        tv = self.rows()[self.a]['tv']
        self.assertTrue(tv)
        self.assertIn('immutable', self.c.get(f'/thumb/{self.a}?v={tv}').headers['cache-control'])
        self.assertEqual(self.c.get(f'/thumb/{self.a}').headers['cache-control'], 'no-cache')

    def test_thumb_resized_for_the_grid(self):
        import io
        from PIL import Image
        tv = self.rows()[self.a]['tv']
        big = self.data / 'items' / str(self.b) / 'thumb.jpg'
        big.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (1080, 1920), (20, 200, 20)).save(big, 'JPEG')
        before = big.read_bytes()
        listing = sorted(x.name for x in (self.data / 'items' / str(self.b)).iterdir())
        r = self.c.get(f'/thumb/{self.b}?v=1&w=320')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['content-type'], 'image/jpeg')
        self.assertIn('immutable', r.headers['cache-control'])
        im = Image.open(io.BytesIO(r.content))
        self.assertEqual((im.format, im.size), ('JPEG', (320, 569)))
        self.assertLess(len(r.content), len(before))
        # nothing written next to the original, the original untouched
        self.assertEqual(sorted(x.name for x in big.parent.iterdir()), listing)
        self.assertEqual(big.read_bytes(), before)
        self.assertEqual(self.c.get(f'/thumb/{self.b}?w=320').headers['cache-control'], 'no-cache')
        # already narrower than w (item a is 40 px): the file as is
        small = self.c.get(f'/thumb/{self.a}?v={tv}&w=320')
        self.assertEqual(small.content, (self.data / 'items' / str(self.a) / 'thumb.jpg').read_bytes())
        # an unreadable file falls back to the file instead of a 500
        big.write_bytes(b'not a jpeg')
        self.assertEqual(self.c.get(f'/thumb/{self.b}?w=320').content, b'not a jpeg')

    def test_index_bit(self):
        c = self.data / 'content_manager.db'
        db = Database(c)
        n = db.add_item({'url': 'https://example.com/n', 'description': 'not indexed yet'})
        db.close()
        rows = self.rows()
        self.assertEqual(rows[self.a]['nd'] & 16, 0)
        self.assertEqual(rows[n]['nd'] & 16, 16)
        self.assertEqual(rows[n]['src'], 'web')

    def test_smart_ranks_by_meaning(self):
        with mock.patch('core.ai_defaults.embed_credentials', return_value=('k', None)), \
             mock.patch('core.ai_client.embed_texts', return_value=[[0, 1, 0, 0]]):
            r = self.c.post('/api/smart', json={'q': 'cake baking'}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['ids'][0], self.b)
        self.assertEqual(r.json()['mode'], 'hybrid')

    def test_smart_needs_key(self):
        with mock.patch('core.ai_defaults.embed_credentials', return_value=('', None)):
            r = self.c.post('/api/smart', json={'q': 'x'}, headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Index for search', r.json()['detail'])

    def test_index_job_drops_the_cached_index(self):
        with mock.patch('core.ai_defaults.embed_credentials', return_value=('k', None)), \
             mock.patch('core.ai_client.embed_texts', return_value=[[1, 0, 0, 0]]):
            self.c.post('/api/smart', json={'q': 'knee'}, headers=W)
        self.assertIsNotNone(self.app.state.embed_index)
        for fn in self.app.state.jobs.on_finish:
            fn('index', None)
        self.assertIsNone(self.app.state.embed_index)

    def test_tints(self):
        for _ in range(100):
            j = self.c.get('/api/tints').json()
            if j['ready']:
                break
            time.sleep(0.02)
        self.assertTrue(j['ready'])
        self.assertIn(str(self.a), j['tints'])
        r, g, b = (int(j['tints'][str(self.a)][i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(r, 150)
        self.assertLess(g, 80)
        self.assertNotIn(str(self.b), j['tints'])


if __name__ == '__main__':
    unittest.main()
