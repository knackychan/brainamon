"""Manual canvas contracts: real pure TS helpers, no personal library or browser storage."""
import unittest
import json
import tempfile
from pathlib import Path
from PIL import Image
from core.db import Database
from library import canvas_plan
from library.canvas import CanvasStore
from server import intake
from tests.test_phone_js import node, TS_RESOLVE


class ComposeTest(unittest.TestCase):
    def test_pure_contracts(self):
        self.assertIn('compose contracts passed', node(TS_RESOLVE + "await import('./tests/check_phone_compose.mjs')"))

    def test_manual_port_intake_and_original_image_geometry(self):
        proposals = json.loads(node(TS_RESOLVE + """
          const {COLOURS,proposal,manual,preview}=await import('./web/src/mobile/canvas/compose.ts');
          console.log(JSON.stringify(COLOURS.map((color,i)=>{
            const raw=proposal('Manual '+i,null,[-7],'Line one\\nLine two',color,'columns');
            return {raw,normalized:manual(raw),local:preview(null,[-7],'Line one\\nLine two',color,'columns',new Map([[-7,[90,160]]]))};
          })));
        """))
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'content_manager.db')
            try:
                iid = db.add_item({'url': 'https://example.test/manual', 'description': 'Synthetic image'})
                uid = db.get_item(iid)['uid']
                directory = db.item_dir(iid); directory.mkdir(parents=True, exist_ok=True)
                Image.new('RGB', (100, 200)).save(directory / 'thumb.jpg')
                cs = CanvasStore(Path(folder))
                for i, p in enumerate(proposals):
                    self.assertEqual(canvas_plan.normalize(p['raw']), p['normalized'])
                    cid, op = f'{i + 1:032x}', f'{i + 20:032x}'
                    wire = {'op': 'canvas', 'op_id': op, 'canvas_id': cid, 'at': 100 + i,
                            'proposal': p['raw'], 'refs': {'-7': uid}, 'sizes': {uid: [90, 160]}}
                    result = intake.apply(db, {'device': 'fixture', 'at': 100 + i, 'changes': [wire]})
                    self.assertEqual(result.canvas_results[op]['state'], 'applied')
                    items = cs.load_canvas(cid)['items']
                    self.assertEqual(items[1]['color'], p['raw']['elements'][1]['color'])
                    self.assertEqual(items[1]['text'], 'Line one\nLine two')
                    self.assertEqual(items[0]['item_id'], iid)
                    self.assertEqual(items[0]['h'], 440)  # PC uses its original, not the downscaled phone sizes.
                    self.assertEqual(p['local']['items'][0]['h'], round(220 * 160 / 90))
                    self.assertEqual(set(wire), {'op', 'op_id', 'canvas_id', 'at', 'proposal', 'refs', 'sizes'})
            finally:
                db.close()
