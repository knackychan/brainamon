"""Wiskit reference fidelity, shipped assets and legacy widget state compatibility."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops
from desktop import wiskit_sprite as sprite

ROOT = Path(__file__).resolve().parents[1]


class SpriteTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Reference exporter requires Node')
    def test_frozen_art_matches_reference(self):
        subprocess.run(['node', 'web/scripts/export_wiskit.mjs', '--check'], cwd=ROOT, check=True, capture_output=True)

    def test_sheet_pixels_timing_and_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sheet.png'
            index = sprite.render_sheet(path)
            with Image.open(path) as img:
                self.assertEqual(img.size, (96 * 7, 56 * 7))
                self.assertNotIn('waiting', index['states'])
                for alias in ('listen', 'receive', 'sad'):
                    self.assertEqual(index['states'][alias], index['states']['hover'])
                self.assertEqual(json.loads(path.with_suffix('.json').read_text()), index)
                self.assertNotIn(sprite.KEY, [sprite._hex(c) for c in sprite.INK.values()])
                for name, frames in sprite.state_frames().items():
                    state = index['states'][name]
                    self.assertAlmostEqual(1000 / state['fps'], sprite.STATES[name]['ms'])
                    for col, frame in enumerate(frames):
                        actual = img.crop((col * 96, state['row'] * 56, (col + 1) * 96, (state['row'] + 1) * 56))
                        expected = [sprite._hex(sprite.INK[c]) if c != '.' else sprite.KEY for line in frame for c in line]
                        self.assertEqual(actual.tobytes(), bytes(v for pixel in expected for v in pixel), (name, col))
                for alias, name in sprite.ALIASES.items():
                    self.assertEqual(index['states'][alias], index['states'][name])
                self.assertEqual(index['states']['slither']['move'], [1] * 6)
                self.assertGreater(sum(index['states']['inch']['move']), 0)
                shipped = ROOT / 'web/public/wiskit'
                with Image.open(shipped / 'sheet.png') as actual:
                    self.assertIsNone(ImageChops.difference(img, actual).getbbox())
                self.assertEqual(index, json.loads((shipped / 'sheet.json').read_text()))


if __name__ == '__main__':
    unittest.main()
