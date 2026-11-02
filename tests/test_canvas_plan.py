from tests.test_ask_tool_stream import agent_from_stream
"""Wiskit canvas proposals (projects/wiskit-canvas/PLAN.md): the layout, the proposal checks, the approval
request (never written before Fred's click, all or nothing, re-checked at Apply), the native and MCP tools.

Run from the project root:  py -m unittest tests.test_canvas_plan -v
"""
import io
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient
from PIL import Image

from core import ai_client
from core.db import Database, ReadOnlyDatabase
from knowledge import ask_core, librarian
from library import canvas_elements, canvas_plan, search
from library.canvas import CanvasStore
from mcp_local import jobs as mcp_jobs
from mcp_local import reads
from server.app import create_app
from server.jobs import AUTO_APPROVE_KEY, JobError
from server.routes import ask

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def jpeg(w=90, h=160) -> bytes:
    b = io.BytesIO()
    Image.new('RGB', (w, h), (40, 120, 200)).save(b, 'JPEG')
    return b.getvalue()


def boxes(els):
    """What the board draws: an image card includes its label tab above and caption strip below."""
    out = []
    for e in els:
        top, h = canvas_elements.footprint(e)
        out.append((float(e['x']), float(e['y']) - top, float(e['w']), h))
    return out


def overlaps(els) -> bool:
    return canvas_plan._overlap(boxes(els))


class ArrangeTest(unittest.TestCase):
    def els(self, n, w=200, h=150):
        return [{'type': 'image', 'w': w, 'h': h + 10 * (i % 3)} for i in range(n)]

    def test_rows_sections_wrap_without_overlap(self):
        a, b = self.els(11), self.els(3, 240, 160)
        out = canvas_elements.arrange([{'title': 'Warm-up', 'elements': a}, {'title': None, 'elements': b}], (40, 40))
        self.assertEqual(len(out), 1 + 11 + 3)
        self.assertFalse(overlaps(out))
        title = out[0]
        self.assertEqual((title['type'], title['text'], title['h']), ('note', 'Warm-up', canvas_elements.TITLE_H))
        self.assertTrue(all(e['x'] > title['x'] + title['w'] for e in a))     # items right of the title
        self.assertEqual(a[8]['x'], a[0]['x'])                                  # 9th wraps to a new line
        self.assertGreater(a[8]['y'], a[0]['y'])
        self.assertGreater(min(e['y'] for e in b), max(e['y'] + e['h'] for e in a))   # next section below
        self.assertEqual(len({e['id'] for e in out}), len(out))

    def test_columns_go_left_to_right(self):
        s1, s2 = self.els(10), self.els(2)
        out = canvas_elements.arrange([{'title': 'Wake up', 'elements': s1}, {'title': 'Breakfast', 'elements': s2}],
                                      (100, 50), 'columns')
        self.assertFalse(overlaps(out))
        self.assertGreater(min(e['x'] for e in s2), max(e['x'] + e['w'] for e in s1))
        self.assertGreater(s1[1]['y'], s1[0]['y'])                              # stacked downwards
        self.assertGreater(s1[8]['x'], s1[0]['x'])                              # a sub-column after ROW

    def test_explicit_block_first_and_origin(self):
        ex = [{'type': 'note', 'w': 240, 'h': 160, 'dx': 0, 'dy': 0}, {'type': 'note', 'w': 240, 'h': 160, 'dx': 300, 'dy': 0}]
        sec = self.els(2)
        out = canvas_elements.arrange([{'title': 'A', 'elements': sec}], (500, 20), 'rows', ex)
        self.assertEqual((ex[0]['x'], ex[0]['y'], ex[1]['x']), (500, 20, 800))
        self.assertNotIn('dx', ex[0])
        self.assertGreater(min(e['y'] for e in sec), 180)
        self.assertFalse(overlaps(out))
        self.assertEqual(canvas_elements.origin([]), (40.0, 40.0))
        self.assertEqual(canvas_elements.origin([{'x': 10, 'y': 5, 'w': 100}, {'x': 0, 'y': -3, 'w': 50}]),
                         (110 + canvas_elements.SECTION_GAP, -3))


class NormalizeTest(unittest.TestCase):
    def bad(self, payload, text, **kw):
        with self.assertRaises(canvas_plan.ProposalError) as cm:
            canvas_plan.normalize(payload, **kw)
        self.assertIn(text, str(cm.exception))

    def test_shapes(self):
        ok = canvas_plan.normalize({'new_name': '  Morning   routine ', 'elements': [
            {'kind': 'thumbnail', 'item_id': 1, 'group': 'Wake up', 'order': 2},
            {'kind': 'text', 'text': ' Drink water ', 'color': '#AABBCC'},
            {'kind': 'text', 'text': 'at', 'x': 0, 'y': 0}]})
        self.assertEqual(ok['new_name'], 'Morning routine')
        self.assertEqual(ok['layout'], 'rows')
        self.assertEqual(ok['elements'][1], {'kind': 'text', 'text': 'Drink water', 'color': '#AABBCC'})
        self.assertEqual((ok['elements'][2]['dx'], ok['elements'][2]['dy']), (0, 0))
        self.bad({'elements': [{'kind': 'text', 'text': 'x'}]}, 'exactly one of canvas_id')
        self.bad({'new_name': 'a', 'canvas_id': 'b', 'elements': [{'kind': 'text', 'text': 'x'}]}, 'exactly one')
        self.bad({'new_name': 'a', 'elements': []}, 'non-empty list')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': 'x'}] * 61}, 'at most 60')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': f'{i}'} for i in range(21)]}, 'at most 20 text')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'video', 'item_id': 1}]}, 'kind must be')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'thumbnail', 'item_id': True}]}, 'item_id must be')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'frame', 'item_id': 1, 'frame': '../x.jpg'}]}, 'frame must be')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': 'x' * 1001}]}, 'longer than')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': 'x', 'color': 'red'}]}, 'color')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'thumbnail', 'item_id': 1, 'text': 'x'}]}, 'not allowed')
        self.bad({'canvas_id': 'abc', 'elements': [{'kind': 'existing', 'id': 'e1'}]}, 'only with arrange')
        self.bad({'new_name': 'a', 'arrange': True, 'elements': [{'kind': 'text', 'text': 'x'}]}, 'existing canvas')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': 'x', 'x': 1}]}, 'x and y go together')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': 'x', 'x': 1, 'y': 1, 'group': 'g'}]}, 'not both')
        self.bad({'new_name': 'a', 'delete': True, 'elements': [{'kind': 'text', 'text': 'x'}]}, 'unknown field')
        self.bad({'new_name': 'a', 'elements': [{'kind': 'text', 'text': 'x', 'group': f'g{i}'} for i in range(13)]},
                 'at most 12 groups')
        self.assertEqual(canvas_plan.normalize({'new_name': 'a', 'elements': [{'kind': 'frame', 'item_id': 1, 'frame': 'f.jpg'}]})['elements'][0]['kind'], 'frame')


class CanvasRequestTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://x/a', 'description': 'Morning stretch', 'short_desc': 'stretch'})
        self.b = db.add_item({'url': 'https://x/b', 'description': 'Coffee ritual'})
        self.c_id = db.add_item({'url': 'https://x/c', 'description': 'No pictures'})
        for iid in (self.a, self.b):
            d = db.item_dir(iid)
            d.mkdir(parents=True, exist_ok=True)
            (d / 'thumb.jpg').write_bytes(jpeg())
        (db.item_dir(self.a) / 'frames').mkdir()
        for k in range(3):
            (db.item_dir(self.a) / 'frames' / f'frame_{k:03d}.jpg').write_bytes(jpeg(160, 90))
        db.close()
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def proposal(self, **kw):
        p = {'new_name': 'Morning routine', 'layout': 'columns', 'elements': [
            {'kind': 'text', 'text': 'Start slow', 'group': 'Wake up', 'order': 1},
            {'kind': 'thumbnail', 'item_id': self.a, 'group': 'Wake up', 'order': 2},
            {'kind': 'frame', 'item_id': self.a, 'frame': 'frame_001.jpg', 'group': 'Wake up', 'order': 3},
            {'kind': 'thumbnail', 'item_id': self.b, 'group': 'Coffee'}]}
        p.update(kw)
        return p

    def ask(self, proposal, source='Claude Code'):
        return self.c.post('/api/canvases/request', json={'proposal': proposal, 'source': source}, headers=W)

    def answer(self, rid, ok=True):
        return self.c.post(f"/api/jobs/request/{rid}/{'approve' if ok else 'decline'}", headers=W)

    def uploads(self):
        return sorted(p.name for p in (self.data / 'canvases' / 'uploads').iterdir()) \
            if (self.data / 'canvases' / 'uploads').exists() else []

    def canvases(self):
        return self.c.get('/api/canvases').json()

    def test_new_canvas_waits_then_applies_with_a_clean_layout(self):
        self.app.state.writer.call(lambda db: db.set_setting(AUTO_APPROVE_KEY, '1'))   # auto-approve does not apply it
        r = self.ask(self.proposal())
        self.assertEqual(r.status_code, 200, r.text)
        req = r.json()
        self.assertEqual((req['type'], req['state'], req['require_approval']), ('canvas_proposal', 'pending', True))
        self.assertNotIn('proposal', req)
        self.assertEqual(req['preview']['counts'], {'thumbnail': 2, 'frame': 1, 'text': 1, 'sections': 2, 'moves': 0})
        self.assertEqual([s['title'] for s in req['preview']['sections']], ['Wake up', 'Coffee'])
        self.assertNotIn('proposal', self.c.get('/api/jobs').json()['request'])
        self.assertEqual(self.canvases(), [])                  # nothing written before the click
        self.assertEqual(self.uploads(), [])
        self.assertEqual(self.ask(self.proposal(new_name='Other')).status_code, 409)   # one request at a time
        with mock.patch.object(self.app.state.hub, 'publish', wraps=self.app.state.hub.publish) as pub:
            res = self.answer(req['id']).json()
        self.assertIn('canvas_changed', [c.args[0] for c in pub.call_args_list])
        made = res['canvas']
        self.assertEqual((made['name'], made['added'], made['moved'], made['changed']), ('Morning routine', 6, 0, False))
        self.assertEqual(res['request']['state'], 'approved')
        self.assertEqual(res['request']['result']['canvas_id'], made['canvas_id'])
        doc = self.c.get(f"/api/canvases/{made['canvas_id']}").json()['canvas']
        self.assertEqual(len(doc['items']), 6)                 # 4 elements + 2 section titles
        self.assertFalse(overlaps(doc['items']))
        self.assertEqual(len(self.uploads()), 1)               # the frame was copied, the item's frames stay
        self.assertEqual(len(list((self.data / 'items' / str(self.a) / 'frames').iterdir())), 3)
        thumb = next(e for e in doc['items'] if e.get('item_id') == self.a)
        self.assertEqual((thumb['source'], thumb['w'], thumb['h']), ('db', 220, 391))   # fit_height, as a manual add
        self.assertIsNone(self.c.get('/api/canvas/active').json()['id'])   # nothing becomes active by itself

    def test_decline_changes_nothing(self):
        req = self.ask(self.proposal()).json()
        self.assertEqual(self.answer(req['id'], False).json()['request']['state'], 'declined')
        self.assertEqual(self.canvases(), [])
        self.assertEqual(self.uploads(), [])

    def test_bad_items_and_frames_are_refused_whole(self):
        bad = self.proposal(elements=[
            {'kind': 'thumbnail', 'item_id': 9999},
            {'kind': 'thumbnail', 'item_id': self.c_id},
            {'kind': 'frame', 'item_id': self.b, 'frame': 'frame_000.jpg'},
            {'kind': 'text', 'text': 'fine'}])
        r = self.ask(bad)
        self.assertEqual(r.status_code, 400)
        for text in ('no item with id 9999', f'item {self.c_id} has no thumbnail', f'item {self.b} has no frame named'):
            self.assertIn(text, r.json()['detail'])
        self.assertIsNone(self.c.get('/api/jobs').json()['request'])
        cid = self.c.post('/api/canvases', json={'name': 'Morning routine'}, headers=W).json()['id']
        r = self.ask(self.proposal())                          # the name is taken now
        self.assertEqual(r.status_code, 400)
        self.assertIn(cid, r.json()['detail'])
        self.assertIn('no canvas with id', self.ask(self.proposal(new_name=None, canvas_id='nope')).json()['detail'])

    def test_a_frame_gone_before_apply_rejects_everything(self):
        req = self.ask(self.proposal()).json()
        (self.data / 'items' / str(self.a) / 'frames' / 'frame_001.jpg').unlink()
        r = self.answer(req['id'])
        self.assertEqual(r.status_code, 400)
        self.assertIn('no frame named frame_001.jpg', r.json()['detail'])
        self.assertEqual(self.canvases(), [])                  # no canvas created
        self.assertEqual(self.uploads(), [])
        self.assertEqual(self.c.get('/api/jobs').json()['request']['state'], 'pending')   # still answerable
        self.assertEqual(self.answer(req['id'], False).status_code, 200)

    def test_a_failed_frame_copy_removes_its_own_copies(self):
        req = self.ask(self.proposal(elements=[
            {'kind': 'frame', 'item_id': self.a, 'frame': 'frame_000.jpg'},
            {'kind': 'frame', 'item_id': self.a, 'frame': 'frame_002.jpg'}])).json()
        real = CanvasStore.save_uploaded_image
        calls = []

        def flaky(store, src):
            calls.append(src)
            return real(store, src) if len(calls) == 1 else ''
        with mock.patch.object(CanvasStore, 'save_uploaded_image', flaky):
            r = self.answer(req['id'])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.uploads(), [])
        self.assertEqual(self.canvases(), [])

    def test_add_to_existing_keeps_it_and_rechecks_a_changed_canvas(self):
        cid = self.c.post('/api/canvases', json={'name': 'Workout'}, headers=W).json()['id']
        self.c.post(f'/api/canvases/{cid}/elements', json={'kind': 'text', 'text': 'Old note'}, headers=W)
        before = self.c.get(f'/api/canvases/{cid}').json()['canvas']['items']
        req = self.ask({'canvas_id': cid, 'elements': [
            {'kind': 'thumbnail', 'item_id': self.b, 'group': 'Moves'},
            {'kind': 'frame', 'item_id': self.a, 'frame': 'frame_002.jpg', 'group': 'Moves'}]}).json()
        self.assertEqual(req['preview']['target'], {'id': cid, 'name': 'Workout', 'new': False, 'count': 1})
        self.c.post(f'/api/canvases/{cid}/elements', json={'kind': 'text', 'text': 'Added meanwhile'}, headers=W)
        made = self.answer(req['id']).json()['canvas']
        self.assertTrue(made['changed'])
        items = self.c.get(f'/api/canvases/{cid}').json()['canvas']['items']
        self.assertEqual(len(items), 2 + 3)
        self.assertEqual(items[0], before[0])                  # untouched: same position and content
        self.assertIn('Added meanwhile', [e.get('text') for e in items])
        self.assertFalse(overlaps(items))

    def test_arrange_moves_only_listed_elements(self):
        cid = self.c.post('/api/canvases', json={'name': 'Board'}, headers=W).json()['id']
        for t in ('one', 'two'):
            self.c.post(f'/api/canvases/{cid}/elements', json={'kind': 'text', 'text': t}, headers=W)
        old = self.c.get(f'/api/canvases/{cid}').json()['canvas']['items']
        req = self.ask({'canvas_id': cid, 'arrange': True, 'layout': 'rows', 'elements': [
            {'kind': 'existing', 'id': old[1]['id'], 'group': 'Kept'},
            {'kind': 'thumbnail', 'item_id': self.b, 'group': 'Kept'}]}).json()
        self.assertEqual(req['preview']['counts']['moves'], 1)
        self.assertEqual(req['preview']['sections'][0]['elements'][0]['text'], 'two')
        made = self.answer(req['id']).json()['canvas']
        self.assertEqual((made['added'], made['moved']), (2, 1))
        items = {e['id']: e for e in self.c.get(f'/api/canvases/{cid}').json()['canvas']['items']}
        self.assertEqual(items[old[0]['id']], old[0])
        self.assertEqual(items[old[1]['id']]['text'], 'two')
        self.assertNotEqual((items[old[1]['id']]['x'], items[old[1]['id']]['y']), (old[1]['x'], old[1]['y']))
        self.assertFalse(overlaps(list(items.values())))
        r = self.ask({'canvas_id': cid, 'arrange': True, 'elements': [{'kind': 'existing', 'id': 'gone1'}]})
        self.assertIn('no element gone1', r.json()['detail'])

    def test_save_failures_leave_old_snapshot_and_retry_once(self):
        from library import canvas
        for existing in (False, True):
            for fault in ('serialize', 'stage', 'publish', 'save'):
                with self.subTest(existing=existing, fault=fault):
                    name = f'failure-{existing}-{fault}'
                    cid = None
                    if existing:
                        cid = self.c.post('/api/canvases', json={'name': name}, headers=W).json()['id']
                        self.c.post(f'/api/canvases/{cid}/elements', json={
                            'kind': 'frame', 'ids': [self.a], 'frame': 'frame_000.jpg'}, headers=W)
                    before_rows, before_uploads = self.canvases(), self.uploads()
                    path = self.data / 'canvases' / f'{cid}.json'
                    before = path.read_bytes() if existing else None
                    payload = self.proposal(elements=[{'kind': 'frame', 'item_id': self.a, 'frame': 'frame_001.jpg'}])
                    payload.update({'new_name': None, 'canvas_id': cid} if existing else {'new_name': name})
                    req = self.ask(payload).json()
                    if fault == 'serialize':
                        patch = mock.patch.object(canvas.json, 'dumps', side_effect=ValueError('serialize'))
                    elif fault == 'stage':
                        patch = mock.patch.object(canvas.os, 'fsync', side_effect=OSError('stage'))
                    elif fault == 'publish':
                        patch = mock.patch.object(canvas.os, 'replace', side_effect=OSError('publish'))
                    else:
                        patch = mock.patch.object(CanvasStore, 'save_canvas', side_effect=OSError('save'))
                    with patch, self.assertRaisesRegex(JobError, 'Canvas was not saved'):
                        self.app.state.jobs.answer(req['id'], True)
                    self.assertEqual(self.canvases(), before_rows)
                    self.assertEqual(self.uploads(), before_uploads)
                    if existing:
                        self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(list((self.data / 'canvases').glob('*.tmp')), [])
                    self.assertEqual(self.app.state.jobs.request['state'], 'pending')
                    out = self.answer(req['id']).json()['canvas']
                    self.assertEqual(out['count'], 2 if existing else 1)
                    self.assertEqual(len(self.uploads()), len(before_uploads) + 1)

    def test_revalidate_name_and_item_before_apply(self):
        req = self.ask(self.proposal()).json()
        self.c.post('/api/canvases', json={'name': 'Morning routine'}, headers=W)
        self.assertEqual(self.answer(req['id']).status_code, 400)
        self.assertEqual(self.uploads(), [])
        self.answer(req['id'], False)
        req = self.ask(self.proposal(new_name='Missing item', elements=[
            {'kind': 'thumbnail', 'item_id': self.a}])).json()
        self.app.state.writer.call(lambda db: db.conn.execute('DELETE FROM items WHERE id = ?', (self.a,)))
        self.assertEqual(self.answer(req['id']).status_code, 400)
        self.assertEqual(len(self.canvases()), 1)
        self.assertEqual(self.answer(req['id'], False).status_code, 200)

    def test_new_canvas_has_no_visible_empty_snapshot(self):
        from library import canvas
        req = self.ask(self.proposal()).json()
        reached, release = threading.Event(), threading.Event()
        real = canvas.os.replace
        def publish(src, dest):
            reached.set()
            if not release.wait(10):
                raise RuntimeError('reader did not release publication')
            real(src, dest)
        with ThreadPoolExecutor() as pool, mock.patch.object(canvas.os, 'replace', publish):
            future = pool.submit(self.app.state.jobs.answer, req['id'], True)
            try:
                self.assertTrue(reached.wait(10))
                self.assertEqual(self.canvases(), [])
                self.assertEqual(canvas_plan.canvas_rows(self.data / 'canvases'), [])
                self.assertEqual(len(list((self.data / 'canvases').glob('*.tmp'))), 1)
            finally:
                release.set()
            cid = future.result(10)['canvas']['canvas_id']
        self.assertEqual(len(canvas_plan.load(self.data / 'canvases', cid)['items']), 6)

    def test_index_is_not_a_second_commit_or_a_listing_dependency(self):
        # Even an unwritable legacy index path cannot affect publication or discovery.
        index = self.data / 'canvases' / 'index.json'
        index.parent.mkdir(exist_ok=True)
        index.mkdir()
        req = self.ask(self.proposal()).json()
        made = self.answer(req['id']).json()['canvas']
        cid = made['canvas_id']
        self.assertEqual(self.canvases()[0]['id'], cid)
        self.assertEqual(canvas_plan.canvas_rows(index.parent)[0]['id'], cid)
        self.assertEqual(self.ask(self.proposal()).status_code, 400)
        self.assertEqual(self.c.patch(f'/api/canvases/{cid}', json={'name': 'Renamed'}, headers=W).status_code, 200)
        self.assertEqual(canvas_plan.canvas_rows(index.parent)[0]['name'], 'Renamed')
        req = self.ask(self.proposal(new_name=None, canvas_id=cid)).json()
        self.assertEqual(self.answer(req['id']).json()['canvas']['count'], 12)
        self.assertEqual(len(self.uploads()), 2)
        self.assertEqual(self.c.delete(f'/api/canvases/{cid}', headers=W).status_code, 200)
        self.assertEqual(self.canvases(), [])

    def test_mirror_derives_index_from_exported_snapshots(self):
        from library import mirror
        req = self.ask(self.proposal()).json()
        cid = self.answer(req['id']).json()['canvas']['canvas_id']
        (self.data / 'canvases' / 'index.json').write_text('[{"id":"stale","name":"old"}]')
        files = {f.name: f for f in mirror.build_files({'items': []}, self.data, mirror.Options(videos='off'))}
        index = json.loads(files['canvases/index.json'].data())
        self.assertEqual([row['id'] for row in index], [cid])
        snapshot = json.loads(files[f'canvases/{cid}.json'].data())
        self.assertEqual(index[0]['item_count'], len(snapshot['items']))
        self.assertEqual(index[0]['name'], snapshot['name'])
        self.assertNotIn('canvases/stale.json', files)
        self.assertEqual(self.canvases()[0]['id'], cid)

    def test_partial_second_image_is_cleaned_and_old_upload_survives(self):
        cs = CanvasStore(self.data)
        old = cs.uploads_dir / 'old.jpg'
        old.write_bytes(jpeg())
        req = self.ask(self.proposal(elements=[
            {'kind': 'frame', 'item_id': self.a, 'frame': 'frame_000.jpg'},
            {'kind': 'frame', 'item_id': self.a, 'frame': 'frame_002.jpg'}])).json()
        real, calls = Image.Image.save, []
        def fail_second(image, dest, *args, **kw):
            calls.append(dest)
            if len(calls) == 2:
                Path(dest).write_bytes(b'partial image')
                raise OSError('conversion failed')
            return real(image, dest, *args, **kw)
        with mock.patch.object(Image.Image, 'save', fail_second):
            self.assertEqual(self.answer(req['id']).status_code, 400)
        self.assertEqual(self.uploads(), ['old.jpg'])
        self.assertEqual(old.read_bytes(), jpeg())
        self.assertEqual(self.answer(req['id'], False).json()['request']['state'], 'declined')

    def test_readers_see_complete_snapshots_and_approving_blocks_all_requests(self):
        from library import canvas
        cid = self.c.post('/api/canvases', json={'name': 'Concurrent'}, headers=W).json()['id']
        old = canvas_plan.load(self.data / 'canvases', cid)
        req = self.ask(self.proposal(new_name=None, canvas_id=cid)).json()
        reached, release = threading.Event(), threading.Event()
        real = canvas.os.replace
        def publish(src, dest):
            reached.set()
            if not release.wait(10):
                raise RuntimeError('reader did not release publication')
            real(src, dest)
        with ThreadPoolExecutor() as pool, mock.patch.object(canvas.os, 'replace', publish):
            future = pool.submit(self.app.state.jobs.answer, req['id'], True)
            try:
                self.assertTrue(reached.wait(10))
                for _ in range(20):
                    self.assertEqual(canvas_plan.load(self.data / 'canvases', cid), old)
                    self.assertEqual(self.c.get(f'/api/canvases/{cid}').json()['canvas'], old)
                for route, body in (
                    ('/api/canvases/request', {'proposal': self.proposal(new_name='Busy')}),
                    ('/api/notes/request', {'topic': 'Busy', 'body': 'body', 'sources': []}),
                    ('/api/items/category/request', {'ids': [self.a], 'category': 'INTERESTING'}),
                    ('/api/jobs/request', {'kind': 'describe', 'ids': [self.a]}),
                ):
                    r = self.c.post(route, json=body, headers=W)
                    self.assertEqual(r.status_code, 409, r.text)
            finally:
                release.set()
            self.assertEqual(future.result(10)['request']['state'], 'approved')
        self.assertEqual(len(canvas_plan.load(self.data / 'canvases', cid)['items']), 6)

    def test_notification_failure_does_not_make_commit_retryable(self):
        req = self.ask(self.proposal()).json()
        real = self.app.state.hub.publish
        def fail(event, data):
            if event == 'canvas_changed':
                raise RuntimeError('notification failed')
            return real(event, data)
        with mock.patch.object(self.app.state.hub, 'publish', fail), self.assertRaises(RuntimeError):
            self.app.state.jobs.answer(req['id'], True)
        self.assertEqual(self.app.state.jobs.request['state'], 'approved')
        self.assertEqual(self.answer(req['id']).status_code, 400)
        self.assertEqual(self.canvases()[0]['count'], 6)
        self.assertEqual(len(self.uploads()), 1)

    def test_full_review_text_and_bounded_model_read(self):
        text = ('Paragraph <b>literal</b>\n' * 42)[:970] + ' DISTINCTIVE END'
        req = self.ask(self.proposal(elements=[{'kind': 'text', 'text': text}])).json()
        self.assertEqual(req['preview']['sections'][0]['elements'][0]['text'], text)
        self.assertNotIn('proposal', req)
        cid = self.answer(req['id']).json()['canvas']['canvas_id']
        self.assertEqual(canvas_plan.load(self.data / 'canvases', cid)['items'][0]['text'], text)
        view = canvas_plan.canvas_view(self.data / 'canvases', cid)
        self.assertLessEqual(len(view['elements'][0]['text']), canvas_plan.TEXT_PREVIEW)

    def test_quick_malformed_shapes_return_tool_errors_and_finish(self):
        from core import ai_defaults
        from tests.test_server_ask import events
        rows = self.app.state.writer.read(lambda db: db.get_items_by_ids([self.a]))
        bad = [None, []]
        bad += [{'new_name': 'Q', 'elements': v} for v in (None, 4, True, {}, 'text', [None], [[]])]
        bad += [{'new_name': 'Q', 'elements': [{'kind': v}]} for v in ([], {}, None, 3)]
        bad += [{'new_name': 'Q', 'elements': [{'kind': 'thumbnail', 'item_id': v}]}
                for v in ([], {}, None, True, '1', 1.5, 2**63, -2**63-1, self.c_id)]
        bad += [{'new_name': {}, 'elements': [{'kind': 'text', 'text': 'x'}]},
                {'new_name': 'Q', 'elements': [{'kind': 'text', 'text': {'nested': 'x'}}]}]
        results = []
        def stream(messages, provider, model, **kw):
            for payload in bad:
                results.append(kw['run_tool']('propose_canvas', payload))
            yield 'Final answer after invalid tools.'
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', None)), \
                mock.patch.object(ask_core, 'fallback_rows', return_value=rows), \
                mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            with self.c.stream('POST', '/api/ask', json={'question': 'Canvas', 'provider': 'anthropic',
                    'model': 'm', 'mode': 'quick'}, headers=W) as resp:
                ev = events(resp)
        self.assertEqual(ev[-1][0], 'done', ev)
        self.assertEqual(ev[-1][1]['text'], 'Final answer after invalid tools.')
        self.assertTrue(all(r.startswith('Error:') for r in results), results)
        self.assertIsNone(self.app.state.jobs.request)
        for kind in ([], {}):
            with self.assertRaises(canvas_plan.ProposalError):
                canvas_plan.normalize({'new_name': 'Q', 'elements': [{'kind': kind}]})

    # ── the tools ────────────────────────────────────────────────────────────
    def test_native_proposal_text_and_quick_limits(self):
        out = ask._propose_canvas(self.app, self.proposal())
        self.assertIn('Canvas proposal #', out)
        self.assertIn('Nothing has been written', out)
        self.assertIn('Error: canvas proposal not queued', ask._propose_canvas(self.app, self.proposal(new_name='X')))
        req = self.c.get('/api/jobs').json()['request']
        self.assertEqual(req['source'], 'Wiskit')
        self.answer(req['id'], False)
        self.assertIn('Canvas proposal #', ask._propose_canvas(self.app, self.proposal()))

    def test_deep_tools_only_with_the_callback_and_reads(self):
        cid = self.c.post('/api/canvases', json={'name': 'Workout'}, headers=W).json()['id']
        self.c.post(f'/api/canvases/{cid}/elements', json={'kind': 'thumbnail', 'ids': [self.a]}, headers=W)
        seen = []

        def agent(messages, provider, model, *, system_prompt, tools, run_tool, on_tool=None, **kw):
            seen.append(([t['name'] for t in tools], system_prompt))
            if 'propose_canvas' in seen[-1][0]:
                rows = json.loads(run_tool('list_canvases', {}))
                self.assertEqual(rows[0]['id'], cid)
                view = json.loads(run_tool('read_canvas', {'canvas_id': cid}))
                self.assertEqual(view['elements'][0]['item_id'], self.a)
                self.assertIn('No canvas with id', run_tool('read_canvas', {'canvas_id': '../x'}))
                frames = json.loads(run_tool('list_frames', {'item_id': self.a}))
                self.assertEqual(frames['frames'], ['frame_000.jpg', 'frame_001.jpg', 'frame_002.jpg'])
                self.assertEqual(json.loads(run_tool('list_frames', {'item_id': self.b}))['count'], 0)
                self.assertIn('queued', run_tool('propose_canvas', {'new_name': 'A', 'elements': [{'kind': 'text', 'text': 'Hello'}]}))
            return 'ok'

        with mock.patch.object(ai_client, 'ask_agent', agent):
            for cb in (None, lambda proposal: 'queued'):
                ask_core.deep_answer(self.app.state.db_path, 'anthropic', 'm', 'SYSTEM', [], 'q',
                                     item_index=search.EmbeddingIndex([]), aux_rows=[], aux_jobs=[], embed_key='',
                                     embed_base=None, propose_canvas=cb)
        self.assertTrue(seen[0][1].startswith('SYSTEM\n\n'))
        self.assertIn('Deep mode:', seen[0][1])
        self.assertFalse({'propose_canvas', 'list_canvases'} & set(seen[0][0]))
        self.assertTrue({'list_canvases', 'read_canvas', 'list_frames', 'propose_canvas'} <= set(seen[1][0]))
        self.assertIn('"name": "Workout"', seen[1][1])
        self.assertIn('read_items on the candidates', seen[1][1])
        self.assertNotIn('canvas', ' '.join(t['name'] for t in librarian.TOOLS + librarian.PROPOSE_TOOLS))

    def test_quick_wires_propose_canvas_and_keeps_context_ids(self):
        def setup(db):
            return db.get_items_by_ids([self.a, self.b])
        rows = self.app.state.writer.call(setup)
        results = []

        def stream(messages, provider, model, **kw):
            self.assertIn('propose_canvas', [t['name'] for t in kw['tools']])
            self.assertIn('propose_canvas', kw['system_prompt'])
            run = kw['run_tool']
            results.append(run('propose_canvas', {'new_name': 'Q', 'elements': [{'kind': 'thumbnail', 'item_id': self.c_id}]}))
            results.append(run('propose_canvas', {'new_name': 'Q', 'elements': [{'kind': 'thumbnail', 'item_id': self.a, 'x': 0, 'y': 0}]}))
            yield 'Review waiting.'

        from core import ai_defaults
        from tests.test_server_ask import events
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', None)), \
                mock.patch.object(ask_core, 'fallback_rows', return_value=rows), \
                mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            with self.c.stream('POST', '/api/ask', json={'question': 'Make a morning canvas', 'provider': 'anthropic',
                                                         'model': 'm', 'mode': 'quick'}, headers=W) as resp:
                ev = events(resp)
        self.assertEqual(ev[-1][0], 'done', ev)
        self.assertIn('read item', results[0])
        self.assertIn('Canvas proposal #', results[1])

    def test_mcp_reads_and_set_canvas_over_http(self):
        cid = self.c.post('/api/canvases', json={'name': 'Workout'}, headers=W).json()['id']
        ro = ReadOnlyDatabase(self.data / 'content_manager.db')
        self.addCleanup(ro.close)
        self.assertEqual(reads.list_canvases(ro)['canvases'][0]['id'], cid)
        self.assertEqual(reads.read_canvas(ro, cid)['count'], 0)
        with self.assertRaises(ValueError):
            reads.read_canvas(ro, 'nope')
        self.assertEqual(reads.list_frames(ro, self.a)['count'], 3)
        self.assertEqual(reads.show_item(ro, self.a)['frame_count'], 3)
        with self.assertRaises(ValueError):
            reads.list_frames(ro, 9999)
        sent = []

        def transport(method, path, body=None):
            sent.append((method, path, body))
            r = self.c.request(method, path, json=body, headers=W)
            return r.status_code, r.json()
        with mock.patch.object(mcp_jobs, 'transport', transport):
            out = mcp_jobs.set_canvas({'canvas_id': cid, 'elements': [{'kind': 'thumbnail', 'item_id': self.b}]})
            self.assertEqual(out['requested']['state'], 'pending')
            with self.assertRaises(mcp_jobs.JobToolError):
                mcp_jobs.set_canvas({'canvas_id': cid, 'elements': [{'kind': 'thumbnail', 'item_id': self.b}]})
        self.assertEqual(sent[0][:2], ('POST', '/api/canvases/request'))
        self.assertEqual(self.c.get(f'/api/canvases/{cid}').json()['canvas']['items'], [])


if __name__ == '__main__':
    unittest.main()
