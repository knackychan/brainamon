"""Canvas element dicts, Qt-free (shared by the Qt main window and the V6 server).

A canvas (canvas.CanvasStore, data/canvases/<id>.json) holds `items`: element dicts of type
'image' (source 'db' with item_id, or 'file' with file_path in data/canvases/uploads/) or
'note' (text, color). This module builds them with the same keys and default sizes the Qt
canvas window has always written, and places new ones on the board.
"""
import re
import uuid
from pathlib import Path

NOTE_COLOR = '#FFF9C4'
FRAME_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
FRAME_NAME = re.compile(r'^[A-Za-z0-9_.\-]+\.(jpg|jpeg|png|bmp|webp)$', re.I)


def element(kind: str, store=None, **kw):
    """Build an element dict for `kind`, or None when it can't be built.

    kinds: 'thumbnail' (item_id, label), 'frame' (path, label; copies the image into the
    canvas uploads folder through `store`), 'text' (text, optional color)."""
    if kind == 'thumbnail':
        return {
            'type': 'image', 'source': 'db', 'item_id': kw['item_id'],
            'w': 220, 'h': 165, 'label': kw.get('label', ''),
        }
    if kind == 'frame':
        fname = store.save_uploaded_image(str(kw['path'])) if store is not None else ''
        if not fname:
            return None
        return fit_height({
            'type': 'image', 'source': 'file', 'file_path': fname,
            'w': 200, 'h': 150, 'label': kw.get('label', ''),
        }, store.upload_path(fname))
    if kind == 'text':
        text = (kw.get('text') or '').strip()
        if not text:
            return None
        return {
            'type': 'note', 'text': text, 'color': kw.get('color', NOTE_COLOR),
            'w': 240, 'h': 160,
        }
    return None


def fit_height(el: dict, image_path) -> dict:
    """Set an image element's h from the image's real aspect at its width (the board draws images
    at their natural aspect, so rows of new elements do not overlap). Unreadable: unchanged."""
    try:
        from PIL import Image
        with Image.open(str(image_path)) as im:
            w, h = im.size
        if w:
            el['h'] = round(float(el.get('w', 200)) * h / w)
    except Exception:
        pass
    return el


def item_text(item: dict, kind: str, item_dir: Path) -> str:
    """The text an item contributes as a note: 'ai_desc'/'ai' = the AI summary, 'report' = the
    analysis report.md, anything else = the description (or the short note)."""
    if kind in ('ai_desc', 'ai'):
        return item.get('ai_desc') or ''
    if kind == 'report':
        rp = Path(item_dir) / 'report.md'
        return rp.read_text(encoding='utf-8') if rp.exists() else ''
    return item.get('description') or item.get('short_desc') or ''


def frame_paths(item_dir: Path) -> list:
    """The extracted frames of an item (data/items/<id>/frames), sorted."""
    fdir = Path(item_dir) / 'frames'
    if not fdir.exists():
        return []
    return sorted(p for p in fdir.iterdir() if p.suffix.lower() in FRAME_EXTS)


def frame_path(item_dir: Path, name: str):
    """One named frame of an item, or None (the name is checked, never a path)."""
    if not FRAME_NAME.match(name or '') or '..' in name:
        return None
    p = Path(item_dir) / 'frames' / name
    return p if p.is_file() else None


def place(existing: list, elements: list, at: dict | None = None) -> list:
    """Give new elements an id and a position: in a row from `at` (a drop point), else in a row
    to the right of everything already on the board (V6 placeEls)."""
    if at is not None:
        x, y = float(at.get('x', 0)), float(at.get('y', 0))
    else:
        right = max((float(e.get('x', 0)) + float(e.get('w', 150)) for e in existing), default=None)
        x, y = (40.0, 40.0) if right is None else (right + 44, 40.0)
        if existing:
            y = min(float(e.get('y', 0)) for e in existing)
    x0 = x
    for i, e in enumerate(elements):
        if i and i % ROW == 0:   # wrap long batches (all the frames of a source) into rows
            x, y = x0, y + max(float(p.get('h', 160)) for p in elements[i - ROW:i]) + 60
        e.setdefault('id', uuid.uuid4().hex[:8])
        e['x'], e['y'] = round(x), round(y)
        x += float(e.get('w', 150)) + 28
    return elements


ROW = 8
GAP = 28            # between elements of one line
LINE_GAP = 60       # between wrapped lines (rows) or sub-columns (columns)
SECTION_GAP = 80    # between sections, and between the explicit block and the sections
TITLE_H = 72        # a section title note
LABEL_TAB = 22      # the board draws an image's label tab above its box (v6-page.css .ce .lbl, top -21px)
IMAGE_CHROME = 34   # and its frame padding + caption strip below the image (.ce.img padding 6/24 + border)


def footprint(e: dict) -> tuple:
    """(top offset, height) of what the board draws for an element: an image card also takes its label tab
    above and its caption strip below; a note is its own box."""
    h = float(e.get('h', 160))
    return (LABEL_TAB, LABEL_TAB + max(40, h) + IMAGE_CHROME) if e.get('type') == 'image' else (0.0, h)


def origin(staying: list) -> tuple:
    """Where a new block starts: right of the elements that stay (+SECTION_GAP), at their top; 40,40 on
    an empty board."""
    if not staying:
        return 40.0, 40.0
    right = max(float(e.get('x', 0)) + float(e.get('w', 150)) for e in staying)
    return right + SECTION_GAP, min(float(e.get('y', 0)) for e in staying)


def arrange(sections: list, at: tuple, layout: str = 'rows', explicit: list | None = None) -> list:
    """Position grouped elements without overlaps (Wiskit canvas proposals, projects/wiskit-canvas).

    sections: [{'title': str or None, 'elements': [element dicts with w/h]}], in display order.
    at: the block origin (x, y). layout 'rows': one section per row, the title at its left, sections
    top to bottom; 'columns': one section per column, the title on top, sections left to right.
    explicit: elements carrying 'dx'/'dy' offsets from the origin, placed first; the sections start
    below them. A title becomes a note element. Spacing uses footprint() (what the board draws), so image
    cards with their label tab and caption never touch. Every element gets an id; returns all of them in order."""
    x0, y0 = float(at[0]), float(at[1])
    out, ex_bottom = [], y0
    for e in explicit or []:
        top, fh = footprint(e)
        bx, by = x0 + float(e.pop('dx')), y0 + float(e.pop('dy'))
        e['x'], e['y'] = round(bx), round(by + top)
        ex_bottom = max(ex_bottom, by + fh)
        out.append(e)
    if out:
        y0 = ex_bottom + SECTION_GAP
    x, y = x0, y0
    for sec in sections:
        els = list(sec['elements'])
        title = None
        if sec.get('title'):
            title = element('text', text=sec['title'])
            title['h'] = TITLE_H
            title['x'], title['y'] = round(x), round(y)
            out.append(title)
        if layout == 'columns':
            top = y + (TITLE_H + GAP if title else 0)
            cx, right = x, x + (float(title['w']) if title else 0)
            for i in range(0, len(els), ROW):
                cy, chunk = top, els[i:i + ROW]
                for e in chunk:
                    ft, fh = footprint(e)
                    e['x'], e['y'] = round(cx), round(cy + ft)
                    cy += fh + GAP
                    out.append(e)
                right = max(right, cx + max(float(e.get('w', 150)) for e in chunk))
                cx = right + LINE_GAP
            x = right + SECTION_GAP
        else:
            sx = x + (float(title['w']) + GAP if title else 0)
            bottom = y + (TITLE_H if title else 0)
            ly = y
            for i in range(0, len(els), ROW):
                lx, chunk = sx, els[i:i + ROW]
                for e in chunk:
                    e['x'], e['y'] = round(lx), round(ly + footprint(e)[0])
                    lx += float(e.get('w', 150)) + GAP
                    out.append(e)
                bottom = max(bottom, ly + max(footprint(e)[1] for e in chunk))
                ly = bottom + LINE_GAP
            y = bottom + SECTION_GAP
    for e in out:
        e.setdefault('id', uuid.uuid4().hex[:8])
    return out
