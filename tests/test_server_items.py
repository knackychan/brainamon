"""V6 plan 06 server pieces: create, thumbnail upload, local video, related, delete, bulk edit,
open on the desktop, collections and the item-file allow-list.

Run from the project root:  py -m unittest tests.test_server_items -v
Uses a temporary data folder; never touches data/. os.startfile and webbrowser.open are stubbed.
"""
import io
import tempfile
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


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (1200, 800), (10, 200, 30)).save(buf, 'PNG')
    return buf.getvalue()


class ItemsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        for name, color in (('SPORT', '#2E75B6'), ('BLENDER', '#E46C0A'), ('INTERESTING', '#4472C4')):
            db.add_category(name, color)
        self.a = db.add_item({'url': 'https://www.facebook.com/reel/1', 'description': 'Knee prehab',
                              'type': 'Reel', 'category': 'SPORT', 'tags': 'knee, mobility'})
        self.b = db.add_item({'url': 'https://youtu.be/x', 'description': 'Blender donut', 'type': 'Video',
                              'category': 'BLENDER', 'tags': 'blender'})
        self.c = db.add_item({'url': 'file:///nope', 'description': 'No web address'})
        db.upsert_embedding(self.a, ai_client.EMBEDDING_MODEL, 4, 'h1', search.vec_to_blob([1, 0, 0, 0]))
        db.upsert_embedding(self.b, ai_client.EMBEDDING_MODEL, 4, 'h2', search.vec_to_blob([0.9, 0.1, 0, 0]))
        db.close()
        d = self.data / 'items' / str(self.a)
        (d / 'frames').mkdir(parents=True)
        (d / 'frames' / 'f_0001.jpg').write_bytes(b'\xff\xd8\xff\xd9')
        (d / 'report.md').write_text('# Report', encoding='utf-8')
        (d / 'secret.txt').write_text('no', encoding='utf-8')
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.app = app
        self.cl = TestClient(app, base_url=BASE)
        self.cl.__enter__()
        self.addCleanup(self.cl.__exit__, None, None, None)

    def row(self, i):
        return self.cl.get(f'/api/items/{i}').json()

    def test_create_validation(self):
        p = lambda body: self.cl.post('/api/items', json=body, headers=W)
        self.assertEqual(p({'description': 'x', 'url': ''}).status_code, 400)
        self.assertEqual(p({'description': '', 'url': ''}).status_code, 400)
        r = p({'description': 'dup', 'url': 'https://youtu.be/x'})
        self.assertEqual(r.status_code, 409)
        self.assertIn('already in the library', r.json()['detail'])
        r = p({'description': 'New one', 'url': 'https://example.com/n', 'notes': 'mine', 'tags': 'a, b'})
        self.assertEqual(r.status_code, 200, r.text)
        new = r.json()
        self.assertEqual(new['cat'], 'INTERESTING')
        self.assertEqual(self.row(new['id'])['notes'], 'mine')
        self.assertIn(new['id'], self.app.state.jobs.dirty)
        r = p({'description': 'Bare', 'url': 'www.example.com/bare'})
        self.assertEqual(self.row(r.json()['id'])['url'], 'https://www.example.com/bare')

    def test_create_without_description_fetches_like_the_widget(self):
        p = lambda body: self.cl.post('/api/items', json=body, headers=W)
        with mock.patch.object(self.app.state.jobs, 'start') as start:
            r = p({'description': '  ', 'url': 'www.example.com/reel', 'creator': 'me'})
            self.assertEqual(r.status_code, 200, r.text)
            new = r.json()
            self.assertTrue(new['fetching'])
            row = self.row(new['id'])
            self.assertEqual(row['description'], 'https://www.example.com/reel')   # the link stands in
            self.assertEqual(row['creator'], 'me')
            start.assert_called_once_with('thumb', [new['id']], True, {})
            start.reset_mock()
            r = p({'description': 'Mine', 'url': 'https://example.com/described'})
            self.assertFalse(r.json()['fetching'])
            start.assert_not_called()
            r = p({'url': 'https://youtu.be/x'})                 # duplicate: 409, no job
            self.assertEqual(r.status_code, 409)
            self.assertIn('already in the library', r.json()['detail'])
            start.assert_not_called()

    def test_create_without_description_while_a_job_runs(self):
        from server.jobs import Busy
        with mock.patch.object(self.app.state.jobs, 'start', side_effect=Busy('busy')):
            r = self.cl.post('/api/items', json={'url': 'https://example.com/busy'}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()['fetching'])
        self.assertEqual(self.row(r.json()['id'])['description'], 'https://example.com/busy')

    def test_thumb_upload(self):
        r = self.cl.put(f'/api/items/{self.b}/thumb', content=_png(), headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['thumb'])
        from PIL import Image
        with Image.open(self.data / 'items' / str(self.b) / 'thumb.jpg') as im:
            self.assertEqual(im.format, 'JPEG')
            self.assertLessEqual(max(im.size), 600)
        self.assertEqual(self.cl.put(f'/api/items/{self.b}/thumb', content=b'not an image', headers=W).status_code, 400)
        self.assertEqual(self.cl.put('/api/items/999/thumb', content=_png(), headers=W).status_code, 404)

    def test_video_upload_names(self):
        r = self.cl.put(f'/api/items/{self.b}/video', params={'name': r'C:\x\..\clip.MP4'}, content=b'1234', headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['path'], 'video/clip.MP4')
        self.assertTrue((self.data / 'items' / str(self.b) / 'video' / 'clip.MP4').is_file())
        self.assertEqual(self.cl.put(f'/api/items/{self.b}/video', params={'name': 'x.exe'}, content=b'1', headers=W).status_code, 400)

    def test_related(self):
        r = self.cl.get(f'/api/items/{self.a}/related').json()
        self.assertEqual(r[0]['id'], self.b)
        self.assertIn('score', r[0])
        self.assertEqual(self.cl.get(f'/api/items/{self.c}/related').json(), {'needs_index': True})

    def test_delete(self):
        r = self.cl.post('/api/items/delete', json={'ids': [self.a]}, headers=W)
        self.assertEqual(r.json(), {'deleted': 1})
        self.assertEqual(self.cl.get(f'/api/items/{self.a}').status_code, 404)
        self.assertFalse((self.data / 'items' / str(self.a)).exists())

    def test_bulk(self):
        b = lambda body: self.cl.post('/api/items/bulk', json=body, headers=W)
        self.assertEqual(b({'ids': [self.a, self.b], 'action': 'set_type', 'value': 'Post'}).json(), {'changed': 2})
        self.assertEqual(self.row(self.b)['type'], 'Post')
        b({'ids': [self.a, self.b], 'action': 'add_tags', 'value': 'new, Knee'})
        self.assertEqual(self.row(self.a)['tags'], 'knee, mobility, new')
        b({'ids': [self.a], 'action': 'remove_tags', 'value': 'MOBILITY'})
        self.assertEqual(self.row(self.a)['tags'], 'knee, new')
        b({'ids': [self.a], 'action': 'set_category', 'value': 'AI'})
        self.assertEqual(self.row(self.a)['category'], 'AI')
        self.assertEqual(b({'ids': [self.a], 'action': 'set_creator', 'value': ''}).status_code, 400)
        self.assertEqual(b({'ids': [self.a], 'action': 'drop_table', 'value': 'x'}).status_code, 400)
        self.assertEqual(b({'ids': [self.b], 'action': 'delete'}).json(), {'changed': 1})
        self.assertEqual(self.cl.get(f'/api/items/{self.b}').status_code, 404)

    def test_open_is_limited(self):
        with mock.patch('webbrowser.open') as wb, mock.patch('server.routes.items._startfile') as sf:
            o = lambda what, i: self.cl.post('/api/open', json={'what': what, 'id': i}, headers=W)
            self.assertEqual(o('url', self.a).status_code, 200)
            wb.assert_called_once_with('https://www.facebook.com/reel/1')
            self.assertEqual(o('url', self.c).status_code, 400)          # file:// is refused
            self.assertEqual(o('folder', self.a).status_code, 200)
            self.assertEqual(o('report', self.a).status_code, 200)
            self.assertEqual(o('report', self.b).status_code, 400)
            self.assertEqual(o('video', self.a).status_code, 400)
            self.assertEqual(o('exe', self.a).status_code, 400)
            opened = [Path(c.args[0]) for c in sf.call_args_list]
            base = (self.data / 'items' / str(self.a)).resolve()
            self.assertTrue(all(p.resolve() == base or base in p.resolve().parents for p in opened))

    def test_files_allow_list(self):
        g = lambda p: self.cl.get(f'/files/items/{self.a}/{p}')
        self.assertEqual(g('frames/f_0001.jpg').status_code, 200)
        self.assertEqual(g('report.md').text, '# Report')
        self.assertEqual(g('secret.txt').status_code, 404)
        self.assertEqual(g('../../content_manager.db').status_code, 404)
        self.assertEqual(g('frames/../secret.txt').status_code, 404)

    def test_collections(self):
        c = lambda m, url, body=None: getattr(self.cl, m)(url, headers=W, **({'json': body} if body is not None else {}))
        r = c('post', '/api/categories', {'name': 'garden', 'color': '#2bb0a8'})
        self.assertIn('GARDEN', [x['name'] for x in r.json()])
        self.assertEqual(c('post', '/api/categories', {'name': 'Garden', 'color': '#2bb0a8'}).status_code, 409)
        self.assertEqual(c('post', '/api/categories', {'name': 'x', 'color': 'red'}).status_code, 400)
        r = c('patch', '/api/categories/SPORT', {'name': 'fitness', 'color': '#58b35a'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.row(self.a)['category'], 'FITNESS')
        self.assertEqual(c('patch', '/api/categories/INTERESTING', {'name': 'OTHER', 'color': '#4472C4'}).status_code, 400)
        self.assertEqual(c('patch', '/api/categories/INTERESTING', {'name': 'INTERESTING', 'color': '#000000'}).status_code, 200)
        self.assertEqual(c('delete', '/api/categories/INTERESTING').status_code, 400)
        r = c('delete', '/api/categories/FITNESS')
        self.assertNotIn('FITNESS', [x['name'] for x in r.json()])
        self.assertEqual(self.row(self.a)['category'], 'INTERESTING')

    def test_hidden_collection(self):
        c = lambda m, url, body=None: getattr(self.cl, m)(url, headers=W, **({'json': body} if body is not None else {}))
        hid = lambda r, n: next(x['hidden'] for x in r.json() if x['name'] == n)
        self.assertEqual(hid(c('post', '/api/categories', {'name': 'nsfw', 'color': '#c00000', 'hidden': True}), 'NSFW'), 1)
        self.assertEqual(hid(c('patch', '/api/categories/NSFW', {'name': 'NSFW', 'color': '#c00000'}), 'NSFW'), 0)
        self.assertEqual(hid(c('patch', '/api/categories/NSFW', {'name': 'adult', 'color': '#c00000', 'hidden': True}), 'ADULT'), 1)


if __name__ == '__main__':
    unittest.main()
