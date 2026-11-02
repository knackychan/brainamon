"""Approved phone canvas intent: Writer-side validation, atomic marker and retry."""
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import io
from pathlib import Path

from PIL import Image
from core.db import Database
from library.canvas import CanvasStore
from library import canvas_plan, mirror
from server import intake
from tests import test_phone_js


class PhoneCanvasIntakeTest(unittest.TestCase):
    def test_solo_merge_requeue_deduplicates_and_keeps_canvas_identity(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
          const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
          const op = 'b'.repeat(32), cid = 'a'.repeat(32)
          const create = {op:'canvas',op_id:op,canvas_id:cid,at:123,
            proposal:{new_name:'A',elements:[{kind:'text',text:'One'}]},refs:{},sizes:{}}
          const append = {op:'canvas',op_id:'c'.repeat(32),canvas_id:cid,at:124,
            proposal:{canvas_id:cid,elements:[{kind:'text',text:'Two'}]},refs:{},sizes:{}}
          const b = new Changes()
          const n = await b.merge([{name:'chg-z',doc:{at:10,changes:[append]}},
            {name:'chg-a',doc:{at:10,changes:[create,create,{...create,proposal:{new_name:'Other',elements:[]}}]}}])
          await b.requeue()
          const sent = []
          await b.flush(async d => {sent.push(d);return 'chg-new'},'phone')
          console.log(JSON.stringify({n,errors:b.mergeErrors.length,ids:b.list.map(x=>x.op_id),
            wire:sent[0].changes,local:JSON.stringify(sent[0]).includes('canvasLocal')}))
        """))
        self.assertEqual(out['n'], 2)
        self.assertEqual(out['errors'], 1)
        self.assertEqual(out['ids'], ['b' * 32, 'c' * 32])
        self.assertEqual([c['op_id'] for c in out['wire']], out['ids'])
        self.assertFalse(out['local'])

    def test_uid_alias_and_missing_thumbnail_are_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                iid = db.add_item({'url': 'https://example.com/a', 'description': 'A'})
                uid = db.conn.execute('SELECT uid FROM items WHERE id = ?', (iid,)).fetchone()[0]
                phone_uid = 'f' * 32
                cid = 'a' * 32
                ch = {'op': 'canvas', 'op_id': 'b' * 32, 'canvas_id': cid, 'at': 123,
                      'proposal': {'new_name': 'A', 'elements': [{'kind': 'thumbnail', 'item_id': -7}]},
                      'refs': {'-7': phone_uid}, 'sizes': {phone_uid: [90, 160]}}
                out = intake.apply(db, {'device': 'phone', 'at': 123, 'changes': [ch]},
                                   intake.Applied(alias={phone_uid: uid}))
                self.assertEqual(out.canvas_results[ch['op_id']]['state'], 'refused')
                self.assertFalse((Path(td) / 'canvases' / f'{cid}.json').exists())
                thumb = db.item_dir(iid) / 'thumb.jpg'
                thumb.parent.mkdir(parents=True, exist_ok=True)
                image = io.BytesIO(); Image.new('RGB', (90, 160)).save(image, 'JPEG'); thumb.write_bytes(image.getvalue())
                ch['op_id'] = 'c' * 32
                out = intake.apply(db, {'device': 'phone', 'at': 124, 'changes': [ch]},
                                   intake.Applied(alias={phone_uid: uid}))
                self.assertEqual(out.canvas_results[ch['op_id']]['state'], 'applied', out.canvas_results[ch['op_id']])
                self.assertEqual(CanvasStore(Path(td)).load_canvas(cid)['items'][0]['item_id'], iid)
            finally:
                db.close()

    def test_typescript_normalizer_and_layout_match_python(self):
        root = Path(__file__).resolve().parent.parent
        raw = json.loads((root / 'tests' / 'fixtures' / 'canvas_proposals.json').read_text(encoding='utf-8'))
        env = dict(os.environ, PYTHONUTF8='1')
        js = json.loads(subprocess.check_output(['node', 'tests/check_phone_canvas.mjs'], cwd=root, env=env))
        for i, (case, got) in enumerate(zip(raw, js['out'])):
            try:
                p = canvas_plan.normalize(case)
            except canvas_plan.ProposalError as e:
                self.assertIn('error', got, f'fixture {i}')
                self.assertEqual(str(e), got['error'], f'fixture {i}')
            else:
                if i == 9:  # phone transport rejects this signed-64-bit desktop value
                    self.assertIn('error', got)
                else:
                    self.assertEqual(p, got['ok'], f'fixture {i}')
        self.assertEqual(js['round'], [0, 2, 2, 0, -2])
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                p = canvas_plan.normalize({'new_name': 'A', 'elements': [
                    {'kind': 'text', 'text': 'A', 'group': 'First'}, {'kind': 'text', 'text': 'B', 'group': 'First'},
                    {'kind': 'text', 'text': 'C', 'x': 0, 'y': 0}]})
                result = canvas_plan.apply(db, CanvasStore(Path(td)), p,
                                           phone={'op_id': 'b' * 32, 'canvas_id': 'a' * 32, 'at': 123, 'hash': 'h'})
                py = CanvasStore(Path(td)).load_canvas(result['canvas_id'])
                self.assertEqual(py['items'], js['layout']['items'])
            finally:
                db.close()

    def test_create_append_replay_and_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                cs = CanvasStore(Path(td))
                cid, op = 'a' * 32, 'b' * 32
                ch = {'op': 'canvas', 'op_id': op, 'canvas_id': cid, 'at': 123,
                      'proposal': {'new_name': 'Phone', 'elements': [{'kind': 'text', 'text': 'First'}]},
                      'refs': {}, 'sizes': {}}
                out = intake.apply(db, {'device': 'phone', 'at': 123, 'changes': [ch]})
                first = cs.load_canvas(cid)
                self.assertEqual(first['items'][0]['id'], f'{op}_0')
                self.assertEqual(first['phone_ops'][op], out.canvas_results[op]['hash'])
                raw = (cs.canvas_dir / f'{cid}.json').read_bytes()
                again = intake.apply(db, {'device': 'phone', 'at': 124, 'changes': [ch]})
                self.assertEqual(again.canvas_results[op]['state'], 'applied')
                self.assertEqual((cs.canvas_dir / f'{cid}.json').read_bytes(), raw)
                altered = copy.deepcopy(ch)
                altered['proposal']['elements'][0]['text'] = 'Tampered'
                bad = intake.apply(db, {'device': 'phone', 'at': 125, 'changes': [altered]})
                self.assertEqual(bad.canvas_results[op]['state'], 'refused')
                self.assertEqual((cs.canvas_dir / f'{cid}.json').read_bytes(), raw)
                append = {'op': 'canvas', 'op_id': 'c' * 32, 'canvas_id': cid, 'at': 126,
                          'proposal': {'canvas_id': cid, 'elements': [{'kind': 'text', 'text': 'Second'}]},
                          'refs': {}, 'sizes': {}}
                intake.apply(db, {'device': 'phone', 'at': 126, 'changes': [append]})
                self.assertEqual([e['text'] for e in cs.load_canvas(cid)['items']], ['First', 'Second'])
                self.assertEqual(len(cs.load_canvas(cid)['phone_ops']), 2)
            finally:
                db.close()

    def test_missing_target_refuses_without_file(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                ch = {'op': 'canvas', 'op_id': 'b' * 32, 'canvas_id': 'gone', 'at': 123,
                      'proposal': {'canvas_id': 'gone', 'elements': [{'kind': 'text', 'text': 'Safe'}]},
                      'refs': {}, 'sizes': {}}
                out = intake.apply(db, {'device': 'phone', 'at': 123, 'changes': [ch]})
                self.assertEqual(out.canvas_results[ch['op_id']]['state'], 'refused')
                self.assertEqual(out.canvas_results[ch['op_id']]['reason'], 'The target canvas is missing on the PC.')
                self.assertFalse((Path(td) / 'canvases' / 'gone.json').exists())
            finally:
                db.close()

    def test_phone_and_pc_hash_the_same_bytes(self):
        """Number-like refs keys sort as text on both sides; a lone surrogate hashes as its escape."""
        def change(refs, text='One'):
            return {'op': 'canvas', 'op_id': 'b' * 32, 'canvas_id': 'a' * 32, 'at': 123,
                    'proposal': {'new_name': 'A', 'elements': [{'kind': 'text', 'text': text}] + [
                        {'kind': 'thumbnail', 'item_id': int(k)} for k in refs]},
                    'refs': refs, 'sizes': {u: [90, 160] for u in refs.values()}}
        cases = [change({'3': 'c' * 32, '12': 'd' * 32}), change({'-3': 'c' * 32, '5': 'd' * 32}),
                 change({}, 'é 😀 "q" \\ \n\t\x01'), change({}, 'bad \ud800 end')]
        js = json.loads(test_phone_js.node(f"""
          const {{ canvasHash }} = await import('./web/src/mobile/ai/canvas.ts')
          const cases = {json.dumps(cases)}
          console.log(JSON.stringify(await Promise.all(cases.map(canvasHash))))
        """))
        self.assertEqual(js, [intake._digest(ch) for ch in cases])
        for ch in cases[:3]:     # the bytes mirror._json writes
            self.assertEqual(intake._digest(ch), hashlib.sha256(mirror._json(ch)).hexdigest())

    def test_refusal_reasons_come_from_codes(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                cs = CanvasStore(Path(td))
                cs.save_canvas({'id': 'old', 'name': 'Taken', 'items': []})
                taken = {'op': 'canvas', 'op_id': 'b' * 32, 'canvas_id': 'a' * 32, 'at': 123,
                         'proposal': {'new_name': 'Taken', 'elements': [{'kind': 'text', 'text': 'x'}]},
                         'refs': {}, 'sizes': {}}
                # "new_name" and "item references" once matched the name and the item reasons
                extra = dict(taken, op_id='c' * 32, proposal={'new_name': 'Fresh', 'elements': [{'kind': 'text', 'text': 'x'}]},
                             refs={'7': 'f' * 32}, sizes={'f' * 32: [1, 1]})
                bad = dict(taken, op_id='d' * 32, proposal={'new_name': 'Odd \ud800', 'elements': [{'kind': 'text', 'text': 'x'}]})
                link = {'op': 'link', 'uid': 'e' * 32, 'url': 'https://example.com/after', 'at': 124}
                out = intake.apply(db, {'device': 'phone', 'at': 124, 'changes': [taken, extra, bad, link]})
                reasons = {k: v['reason'] for k, v in out.canvas_results.items()}
                self.assertEqual(reasons['b' * 32], 'A canvas with that name already exists on the PC.')
                self.assertEqual(reasons['c' * 32], 'The PC could not apply this canvas change.')
                self.assertEqual(reasons['d' * 32], 'The canvas change has text the PC cannot store.')
                self.assertEqual(out.links, 1)     # the change after the surrogate still applied
            finally:
                db.close()

    def test_deleted_canvas_is_not_recreated_by_a_resend(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'content_manager.db')
            try:
                cs = CanvasStore(Path(td))
                cid, op = 'a' * 32, 'b' * 32
                ch = {'op': 'canvas', 'op_id': op, 'canvas_id': cid, 'at': 123,
                      'proposal': {'new_name': 'Phone', 'elements': [{'kind': 'text', 'text': 'First'}]},
                      'refs': {}, 'sizes': {}}
                first = intake.apply(db, {'device': 'phone', 'at': 123, 'changes': [ch]})
                canvas_plan.remember_deleted(db, cs.load_canvas(cid))     # routes/canvas.py delete
                cs.delete_canvas(cid)
                again = intake.apply(db, {'device': 'phone', 'at': 200, 'changes': [ch]})
                self.assertEqual(again.canvas_results[op], first.canvas_results[op])
                self.assertFalse((cs.canvas_dir / f'{cid}.json').exists())
                altered = copy.deepcopy(ch)
                altered['proposal']['elements'][0]['text'] = 'Other'
                bad = intake.apply(db, {'device': 'phone', 'at': 201, 'changes': [altered]})
                self.assertEqual(bad.canvas_results[op]['state'], 'refused')
                self.assertFalse((cs.canvas_dir / f'{cid}.json').exists())
            finally:
                db.close()

    def test_more_counts_settled_and_held_canvas_changes(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
          const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
          const c = new Changes()
          c.loaded = Promise.resolve()
          const local = status => ({ base: null, result: { id: 'x', name: '', items: [] }, assets: [], status })
          c.list = [{ op: 'fav', state: 'queued', at: 1 }, { op: 'fav', state: 'sent', at: 1 },
            { op: 'canvas', state: 'queued', at: 1, canvasLocal: local('pending') },
            { op: 'canvas', state: 'sent', at: 1, canvasLocal: local('refused') },
            { op: 'canvas', state: 'sent', at: 1, canvasLocal: local('synced') }]
          console.log(JSON.stringify({ old: c.counts(false), now: c.counts(true) }))
        """))
        self.assertEqual(out['old'], {'unsent': 1, 'waiting': 1, 'held': 1})
        self.assertEqual(out['now'], {'unsent': 2, 'waiting': 1, 'held': 0})
