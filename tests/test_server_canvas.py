"""V6 plan 09: canvas_elements.py and the canvas endpoints: CRUD, the active canvas, elements of
every kind, a stale save refused with 409, image uploads and the uploads allow-list.

Run from the project root:  py -m unittest tests.test_server_canvas -v
"""
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.auth_client import TestClient
from PIL import Image

from library import canvas_elements
from library.canvas import CanvasStore
from core.db import Database
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def jpeg(w=90, h=160) -> bytes:
    b = io.BytesIO()
    Image.new('RGB', (w, h), (200, 40, 40)).save(b, 'JPEG')
    return b.getvalue()


class CanvasElementsTest(unittest.TestCase):
    def test_direct_draft_replay_survives_server_restart(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            body = {'op_id': '1' * 32, 'canvas_id': '2' * 32, 'at': 42, 'base_rev': None, 'sizes': {},
                    'proposal': {'new_name': 'Durable', 'layout': 'rows',
                                 'elements': [{'kind': 'text', 'text': 'Restart', 'color': '#FFE0CC'}]}}
            revisions = []
            for _ in range(2):
                app = create_app(data_dir=root, cloud_dir=root / 'cloud', port=8765, web_dist=root / 'x', cards_dir=root / 'x')
                with TestClient(app, base_url=BASE) as client:
                    self.assertEqual(client.post('/api/canvases/draft', json=body, headers=W).status_code, 200)
                    got = client.get('/api/canvases/' + '2' * 32).json()
                    revisions.append(got['rev'])
                    self.assertEqual(len(got['canvas']['items']), 1)
            self.assertEqual(*revisions)

    def test_elements_and_place(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            cs = CanvasStore(Path(td))
            self.assertEqual(canvas_elements.element('thumbnail', item_id=3, label='x'),
                             {'type': 'image', 'source': 'db', 'item_id': 3, 'w': 220, 'h': 165, 'label': 'x'})
            self.assertIsNone(canvas_elements.element('text', text='  '))
            self.assertEqual(canvas_elements.element('text', text='hi')['color'], '#FFF9C4')
            src = Path(td) / 'f.jpg'
            src.write_bytes(jpeg(100, 200))
            fr = canvas_elements.element('frame', cs, path=src, label='f')
            self.assertEqual((fr['source'], fr['w'], fr['h']), ('file', 200, 400))
            self.assertTrue(cs.upload_path(fr['file_path']).is_file())
            els = canvas_elements.place([{'x': 10, 'y': -50, 'w': 100}], [{'w': 50}, {'w': 50}])
            self.assertEqual([(e['x'], e['y']) for e in els], [(154, -50), (232, -50)])
            many = canvas_elements.place([], [{'w': 10, 'h': 20} for _ in range(9)])
            self.assertEqual((many[8]['x'], many[8]['y']), (40, 120))
            self.assertIsNone(canvas_elements.frame_path(Path(td), '../f.jpg'))


class CanvasServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://x/a', 'description': 'Hip airplane', 'short_desc': 'hips'})
        self.b = db.add_item({'url': 'https://x/b', 'description': 'Knee lift'})
        db.update_item(self.a, {'ai_desc': 'A balance drill.'})
        d = db.item_dir(self.a)
        d.mkdir(parents=True, exist_ok=True)
        (d / 'thumb.jpg').write_bytes(jpeg())
        (d / 'report.md').write_text('# Report\nKey information', encoding='utf-8')
        (d / 'frames').mkdir()
        for k in range(3):
            (d / 'frames' / f'frame_{k:03d}.jpg').write_bytes(jpeg(160, 90))
        db.close()
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def new(self, name='Knees'):
        r = self.c.post('/api/canvases', json={'name': name}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['id']

    def draft_body(self, name='Manual', elements=None, cid=None, op='a', layout='rows'):
        return {'op_id': op * 32, 'canvas_id': cid or 'b' * 32, 'at': 123,
                'proposal': {**({'canvas_id': cid} if cid else {'new_name': name}), 'layout': layout,
                             'elements': elements or [{'kind': 'text', 'text': 'Note', 'color': '#D9F2E3'}]},
                'base_rev': self.c.get(f'/api/canvases/{cid}').json()['rev'] if cid else None,
                'sizes': {str(e['item_id']): [90, 160] for e in elements or [] if e['kind'] == 'thumbnail'}}

    def post_draft(self, body):
        return self.c.post('/api/canvases/draft', json=body, headers=W)

    def test_draft_atomic_replay_layout_colour_and_active(self):
        active = self.new('Active stays')
        body = self.draft_body(elements=[{'kind': 'thumbnail', 'item_id': self.a},
                                       {'kind': 'text', 'text': 'Full\ntext', 'color': '#E6DDF5'}], layout='columns')
        self.assertEqual(self.post_draft(body).json(), {'canvas_id': 'b' * 32})
        opened = self.c.get('/api/canvases/' + 'b' * 32).json()
        items = opened['canvas']['items']
        self.assertEqual(items[1]['color'], '#E6DDF5')
        self.assertGreater(items[1]['y'], items[0]['y'])
        self.assertEqual(self.c.get('/api/canvas/active').json(), {'id': active})
        self.assertEqual(self.post_draft(body).status_code, 200)
        self.assertEqual(self.c.get('/api/canvases/' + 'b' * 32).json()['rev'], opened['rev'])
        append = self.draft_body(cid='b' * 32, op='c')
        self.assertEqual(self.post_draft(append).status_code, 200)
        self.assertEqual(self.post_draft(append).status_code, 200)  # replay precedes stale-base validation
        current = self.c.get('/api/canvases/' + 'b' * 32).json()
        self.assertEqual(current['canvas']['items'][:2], items)
        self.assertEqual(len(current['canvas']['items']), 3)
        append['op_id'] = 'd' * 32
        self.assertEqual(self.post_draft(append).status_code, 409)
        body['proposal']['new_name'] = 'Changed replay'
        self.assertEqual(self.post_draft(body).status_code, 409)

    def test_draft_missing_and_changed_thumbnails_never_create_partial_board(self):
        for elements in ([{'kind': 'thumbnail', 'item_id': self.b}],
                         [{'kind': 'thumbnail', 'item_id': self.a}, {'kind': 'thumbnail', 'item_id': self.b}]):
            body = self.draft_body(elements=elements)
            self.assertEqual(self.post_draft(body).status_code, 400)
            self.assertEqual(self.c.get('/api/canvases').json(), [])
        body = self.draft_body(elements=[{'kind': 'thumbnail', 'item_id': self.a}])
        body['sizes'][str(self.a)] = [10, 10]
        self.assertEqual(self.post_draft(body).status_code, 409)
        (self.data / 'items' / str(self.a) / 'thumb.jpg').write_bytes(b'corrupt')
        self.assertEqual(self.post_draft(body).status_code, 400)
        self.assertEqual(self.c.get('/api/canvases').json(), [])

    def test_draft_shape_limits_duplicate_and_unicode(self):
        import copy
        body = self.draft_body()
        variations = [dict(body, extra=1), dict(body, at=True), dict(body, at=2 ** 53), dict(body, op_id='X' * 32),
                      dict(body, canvas_id='index'), dict(body, base_rev=1), dict(body, sizes={'1': [1, 2]})]
        for name in ('😀' * 81, '\ud800', ' \u001c\u0085'):
            b = copy.deepcopy(body); b['proposal']['new_name'] = name; variations.append(b)
        for text in ('😀' * 1001, '\udfff'):
            b = copy.deepcopy(body); b['proposal']['elements'][0]['text'] = text; variations.append(b)
        for extra in ({'arrange': False}, {'layout': None}):
            b = copy.deepcopy(body); b['proposal'].update(extra); variations.append(b)
        for b in variations:
            # httpx cannot encode lone surrogate request bodies; JSON escaping is valid HTTP input.
            import json
            r = self.c.post('/api/canvases/draft', content=json.dumps(b), headers={**W, 'Content-Type': 'application/json'})
            self.assertEqual(r.status_code, 400, r.text)
        duplicate = self.draft_body(elements=[{'kind': 'thumbnail', 'item_id': self.a}] * 2)
        self.assertEqual(self.post_draft(duplicate).status_code, 400)
        valid = self.draft_body(name='😀' * 80, elements=[{'kind': 'text', 'text': '😀' * 1000, 'color': '#D6E8FA'}])
        self.assertEqual(self.post_draft(valid).status_code, 200)

    def test_draft_deleted_replay_foreign_operation_and_write_failure(self):
        from unittest.mock import patch
        body = self.draft_body()
        with patch.object(CanvasStore, '_write_canvas', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.post_draft(body)
        self.assertEqual(self.c.get('/api/canvases').json(), [])
        self.assertEqual(self.post_draft(body).status_code, 200)
        foreign = self.draft_body(name='Foreign')
        foreign['canvas_id'] = 'c' * 32
        self.assertEqual(self.post_draft(foreign).status_code, 409)
        self.c.delete('/api/canvases/' + 'b' * 32, headers=W)
        self.assertEqual(self.post_draft(body).status_code, 410)
        self.assertEqual(self.c.get('/api/canvases').json(), [])

    def test_draft_already_present_image_and_missing_target(self):
        body = self.draft_body(elements=[{'kind': 'thumbnail', 'item_id': self.a}])
        self.assertEqual(self.post_draft(body).status_code, 200)
        append = self.draft_body(cid='b' * 32, op='c', elements=[{'kind': 'thumbnail', 'item_id': self.a}])
        self.assertEqual(self.post_draft(append).status_code, 400)
        append['canvas_id'] = append['proposal']['canvas_id'] = 'missing'
        self.assertEqual(self.post_draft(append).status_code, 404)

    def test_draft_keeps_local_origin_and_mutation_guards(self):
        from fastapi.testclient import TestClient as RawClient
        body = self.draft_body()
        raw = RawClient(self.c.app, base_url=BASE)
        try:
            self.assertEqual(raw.post('/api/canvases/draft', json=body, headers=W).status_code, 403)
        finally:
            raw.close()
        self.assertEqual(self.c.post('/api/canvases/draft', json=body).status_code, 403)
        self.assertEqual(self.c.post('/api/canvases/draft', json=body, headers={**W, 'Origin': 'https://foreign.test'}).status_code, 403)
        self.assertEqual(self.c.get('/api/canvases').json(), [])

    def test_manual_save_preserves_server_phone_markers(self):
        cid = self.new()
        cs = CanvasStore(self.data)
        doc = cs.load_canvas(cid)
        doc['phone_ops'] = {'a' * 32: 'b' * 64}
        cs.save_canvas(doc)
        opened = self.c.get(f'/api/canvases/{cid}').json()
        forged = dict(opened['canvas'], phone_ops={'c' * 32: 'd' * 64})
        r = self.c.put(f'/api/canvases/{cid}', json={'canvas': forged, 'rev': opened['rev']}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(cs.load_canvas(cid)['phone_ops'], doc['phone_ops'])
        other = self.new('No markers')
        opened = self.c.get(f'/api/canvases/{other}').json()
        forged = dict(opened['canvas'], phone_ops={'c' * 32: 'd' * 64})
        r = self.c.put(f'/api/canvases/{other}', json={'canvas': forged, 'rev': opened['rev']}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn('phone_ops', cs.load_canvas(other))

    def test_crud_and_active(self):
        self.assertEqual(self.c.get('/api/canvas/active').json(), {'id': None})
        cid = self.new()
        self.assertEqual(self.c.get('/api/canvas/active').json(), {'id': cid})   # new = active
        self.assertEqual(self.c.post('/api/canvases', json={'name': 'knees'}, headers=W).status_code, 409)
        self.assertEqual(self.c.post('/api/canvases', json={'name': ' '}, headers=W).status_code, 400)
        other = self.new('Hips')
        self.assertEqual(self.c.patch(f'/api/canvases/{cid}', json={'name': 'Hips'}, headers=W).status_code, 409)
        self.assertEqual(self.c.patch(f'/api/canvases/{cid}', json={'name': 'Knee care'}, headers=W).json()['name'], 'Knee care')
        self.assertEqual({r['name'] for r in self.c.get('/api/canvases').json()}, {'Knee care', 'Hips'})
        self.assertEqual(self.c.put('/api/canvas/active', json={'id': cid}, headers=W).json(), {'id': cid})
        self.assertEqual(self.c.put('/api/canvas/active', json={'id': 'nope'}, headers=W).status_code, 404)
        self.assertEqual(self.c.delete(f'/api/canvases/{cid}', headers=W).json(), {'ok': True})
        self.assertEqual(self.c.get('/api/canvas/active').json(), {'id': other})
        self.assertEqual(self.c.get(f'/api/canvases/{cid}').status_code, 404)
        self.assertEqual(self.c.get('/api/canvases/..%2Fx').status_code, 404)

    def test_elements(self):
        cid = self.new()
        add = lambda **b: self.c.post(f'/api/canvases/{cid}/elements', json=b, headers=W).json()
        r = add(kind='thumbnail', ids=[self.a, self.b])
        self.assertEqual(r['added'], 1)   # b has no thumbnail
        el = r['elements'][0]
        self.assertEqual((el['source'], el['item_id'], el['label'], el['h']), ('db', self.a, '', round(220 * 160 / 90)))
        self.assertEqual(add(kind='thumbnail', ids=[self.b]), {'added': 0, 'why': 'This item has no thumbnail yet', 'rev': r['rev'], 'elements': []})
        self.assertEqual(add(kind='desc', ids=[self.a])['elements'][0]['text'], 'Hip airplane')
        self.assertEqual(add(kind='ai', ids=[self.a])['elements'][0]['text'], 'A balance drill.')
        self.assertIn('Key information', add(kind='report', ids=[self.a])['elements'][0]['text'])
        self.assertEqual(add(kind='ai', ids=[self.b])['added'], 0)
        self.assertEqual(add(kind='frame', ids=[self.a], frame='frame_001.jpg')['elements'][0]['label'], 'frame_001')
        self.assertEqual(add(kind='frame', ids=[self.a], frame='../thumb.jpg')['added'], 0)
        fr = add(kind='frames', ids=[self.a, self.b])
        self.assertEqual(fr['added'], 3)
        name = fr['elements'][0]['file_path']
        self.assertEqual(self.c.get(f'/files/canvas-uploads/{name}').headers['content-type'], 'image/jpeg')
        t = add(kind='text', text='From Wiskit', at={'x': 500, 'y': 600})
        self.assertEqual((t['elements'][0]['x'], t['elements'][0]['y']), (500, 600))
        self.assertEqual(add(kind='text', text='')['added'], 0)
        self.assertEqual(self.c.post(f'/api/canvases/{cid}/elements', json={'kind': 'bogus'}, headers=W).status_code, 400)
        got = self.c.get(f'/api/canvases/{cid}').json()
        self.assertEqual(len(got['canvas']['items']), 9)
        self.assertEqual(got['rev'], t['rev'])
        self.assertEqual(self.c.get('/api/canvases').json()[0]['count'], 9)

    def test_stale_save_refused(self):
        cid = self.new()
        got = self.c.get(f'/api/canvases/{cid}').json()
        cv, rev = got['canvas'], got['rev']
        cv['items'] = [{'id': 'n1', 'type': 'note', 'text': 'mine', 'x': 0, 'y': 0, 'w': 240, 'h': 160}]
        time.sleep(0.01)
        r = self.c.put(f'/api/canvases/{cid}', json={'canvas': cv, 'rev': rev}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        rev2 = r.json()['rev']
        self.assertNotEqual(rev2, rev)
        # someone else (the Qt canvas window) writes the file after our load
        time.sleep(0.01)
        cs = CanvasStore(self.data)
        theirs = cs.load_canvas(cid)
        theirs['items'].append({'id': 'q1', 'type': 'note', 'text': 'theirs', 'x': 9, 'y': 9, 'w': 240, 'h': 160})
        cs.save_canvas(theirs)
        cv['items'].append({'id': 'n2', 'type': 'note', 'text': 'mine 2', 'x': 1, 'y': 1, 'w': 240, 'h': 160})
        r = self.c.put(f'/api/canvases/{cid}', json={'canvas': cv, 'rev': rev2}, headers=W)
        self.assertEqual(r.status_code, 409)
        self.assertEqual([e['id'] for e in cs.load_canvas(cid)['items']], ['n1', 'q1'])   # theirs kept
        self.assertEqual(self.c.put(f'/api/canvases/{cid}', json={'canvas': {'items': 3}, 'rev': rev2}, headers=W).status_code, 400)

    def test_upload_and_allow_list(self):
        cid = self.new()
        r = self.c.put(f'/api/canvases/{cid}/image?name=shot.png', content=jpeg(50, 100), headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        el = r.json()
        self.assertEqual((el['source'], el['label'], el['h']), ('file', 'shot', 400))
        self.assertEqual(self.c.get(f'/files/canvas-uploads/{el["file_path"]}').status_code, 200)
        self.assertEqual(self.c.put(f'/api/canvases/{cid}/image', content=b'not an image', headers=W).status_code, 400)
        (self.data / 'canvases' / 'uploads' / 'notes.txt').write_text('x')
        self.assertEqual(self.c.get('/files/canvas-uploads/notes.txt').status_code, 404)
        self.assertEqual(self.c.get('/files/canvas-uploads/..%2Findex.json').status_code, 404)
        self.assertEqual(self.c.put(f'/api/canvases/{cid}/image', content=jpeg()).status_code, 403)   # no X-CM


if __name__ == '__main__':
    unittest.main()
