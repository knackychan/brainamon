"""Render the supplied Wiskit v4 art for the widget, web UI and phone.

Regenerate art: node web/scripts/export_wiskit.mjs
Render assets: py -m desktop.wiskit_sprite [out.png]
"""
import json
import sys
from pathlib import Path

from desktop.wiskit_art import PALETTE as INK, STATES

CELL_W, CELL_H = 96, 56
SCALE = 3
KEY = (255, 0, 255)
# Existing widget/UI states keep their behavior while sharing the reference rows.
ALIASES = {'sleep': 'idle', 'listen': 'hover', 'receive': 'hover', 'work': 'processing',
           'think': 'processing', 'talk': 'hover', 'point': 'searching', 'happy': 'done', 'sad': 'hover'}


def _hex(c: str) -> tuple:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def state_frames() -> dict[str, list[list[str]]]:
    return {name: state['frames'] for name, state in STATES.items()}


def render_sheet(path: Path) -> dict:
    """Write a keyed PNG and index; aliases reference rows without duplicating pixels."""
    from PIL import Image
    cols = max(len(s['frames']) for s in STATES.values())
    img = Image.new('RGB', (CELL_W * cols, CELL_H * len(STATES)), KEY)
    index = {'cell': [CELL_W, CELL_H], 'scale': SCALE, 'key': '#ff00ff', 'states': {}}
    bounds = [CELL_W, CELL_H, 0, 0]
    palette = {k: _hex(v) for k, v in INK.items()}
    px = img.load()
    for row, (name, state) in enumerate(STATES.items()):
        state_bounds = [CELL_W, CELL_H, 0, 0]
        for col, frame in enumerate(state['frames']):
            for y, line in enumerate(frame):
                for x, color in enumerate(line):
                    if color != '.':
                        px[col * CELL_W + x, row * CELL_H + y] = palette[color]
                        bounds = [min(bounds[0], x), min(bounds[1], y), max(bounds[2], x + 1), max(bounds[3], y + 1)]
                        state_bounds = [min(state_bounds[0], x), min(state_bounds[1], y), max(state_bounds[2], x + 1), max(state_bounds[3], y + 1)]
        index['states'][name] = {'row': row, 'frames': len(state['frames']), 'fps': 1000 / state['ms'], 'bounds': state_bounds}
        if state['move']:
            index['states'][name]['move'] = state['move']
    for alias, name in ALIASES.items():
        index['states'][alias] = dict(index['states'][name])
    index['bounds'] = bounds
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    path.with_suffix('.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')
    return index


if __name__ == '__main__':
    # the app icons are the logo now (projects/brainamon-logo/build.py), not Wiskit
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'web/public/wiskit/sheet.png'
    print(json.dumps(render_sheet(out)['states']))
