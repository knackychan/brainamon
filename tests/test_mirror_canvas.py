"""Canvas mirror index is derived from published snapshots, never legacy index.json."""
import json
import tempfile
import unittest
from pathlib import Path

from core.db import Database
from library import export, mirror
from library.canvas import CanvasStore, canvas_entries
from library.export_targets import DriveMirrorTarget
from tests.test_sync import FakeDrive, read_mirror


class MirrorCanvasTest(unittest.TestCase):
    def test_fresh_stale_and_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {'items': []}
            files = list(mirror.build_files(payload, root, mirror.Options(videos='off')))
            self.assertEqual(json.loads(next(f.data() for f in files if f.name == 'canvases/index.json')), [])
            cs = CanvasStore(root)
            first = cs.create_canvas('First')
            stale = cs.canvas_dir / 'index.json'
            stale.write_bytes(b'[{"id":"old","name":"Old"}]')
            second = cs.create_canvas('Second')
            cs.rename_canvas(first, 'Renamed')
            doc = cs.load_canvas(second)
            doc['items'].append({'id': 'one', 'type': 'note'})
            cs.save_canvas(doc)
            files = list(mirror.build_files(payload, root, mirror.Options(videos='off')))
            self.assertEqual([f.name for f in files].count('canvases/index.json'), 1)
            self.assertEqual(json.loads(next(f.data() for f in files if f.name == 'canvases/index.json')),
                             canvas_entries(cs.canvas_dir))
            self.assertEqual({f.name for f in files if f.name.startswith('canvases/')},
                             {'canvases/index.json', f'canvases/{first}.json', f'canvases/{second}.json'})
            self.assertEqual(stale.read_bytes(), b'[{"id":"old","name":"Old"}]')
            self.assertEqual([f.sig for f in files],
                             [f.sig for f in mirror.build_files(payload, root, mirror.Options(videos='off'))])
            self.assertFalse(any(f.name.startswith('canvases/') for f in
                                 mirror.build_files(payload, root, mirror.Options(videos='off', canvases=False))))

    def test_publish_refreshes_index_and_export_listing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = Database(root / 'content_manager.db')
            try:
                cs = CanvasStore(root)
                first = cs.create_canvas('First')
                payload = export.build_export_payload(db, cs, mirror=True)
                self.assertEqual([x['id'] for x in payload['canvases']], [first])
                drive, key, state = FakeDrive(), mirror.MirrorKey.generate(), {}

                def publish():
                    target = DriveMirrorTarget(drive, key, state, root, mirror.Options(videos='off'),
                                               save=lambda put, drop: state.update(put))
                    return target.export(export.build_export_payload(db, cs, mirror=True))

                self.assertFalse(publish().errors)
                _, files = read_mirror(drive, key)
                self.assertEqual(json.loads(files['canvases/index.json']), canvas_entries(cs.canvas_dir))
                old_sig = state['canvases/index.json']['sig']
                cs.rename_canvas(first, 'Renamed')
                second = cs.create_canvas('Second')
                self.assertEqual({x['name'] for x in export.build_export_payload(db, cs)['canvases']},
                                 {'Renamed', 'Second'})
                self.assertFalse(publish().errors)
                man, files = read_mirror(drive, key)
                self.assertNotEqual(state['canvases/index.json']['sig'], old_sig)
                self.assertEqual(json.loads(files['canvases/index.json']), canvas_entries(cs.canvas_dir))
                self.assertIn(f'canvases/{second}.json', man['files'])
                drive.calls.clear()
                self.assertFalse(publish().changed)
                self.assertEqual(drive.calls, ['list'])
            finally:
                db.close()
