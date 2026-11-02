"""Wiskit canvas proposals (projects/wiskit-canvas/PLAN.md), Qt-free.

Read views for the model (list_canvases, read_canvas, list_frames), the shape check of a proposal
(normalize), the check against the library and the canvas file (check: reads only), and apply, which
builds the elements exactly as a manual Add to canvas does (canvas_elements.element) and saves the
canvas in one step. apply runs on the server Writer, inside the JobManager's approval of a
`canvas_proposal` request; nothing here opens SQLite (the db object is passed in). Nothing deletes a
canvas or an element, and an existing element only ever gets a new x/y (arrange).
"""
import json
import os
import re
import time
import uuid

from library.canvas import canvas_entries

from library import canvas_elements

MAX_ELEMENTS = 60      # new elements plus moved existing ones, per request
MAX_NOTES = 20         # text elements plus section titles
MAX_NOTE_TEXT = 1000
MAX_LABEL = 80
MAX_SECTIONS = 12
NAME_MAX = 80
READ_MAX = 150         # elements read_canvas returns
TEXT_PREVIEW = 300     # chars of a note shown to the model by read_canvas
FRAMES_MAX = 200
OFFSET_MAX = 20000
PROBLEMS_MAX = 10
DELETED_OPS = 'canvas_deleted_phone_ops'   # DB setting: {op_id: [canvas_id, hash]} of canvases deleted on the PC
DELETED_MAX = 5000

CID = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')
COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')
LAYOUTS = ('rows', 'columns')
TOP_KEYS = {'canvas_id', 'new_name', 'layout', 'arrange', 'elements'}
KIND_KEYS = {
    'thumbnail': {'item_id', 'label', 'group', 'order', 'x', 'y'},
    'frame': {'item_id', 'frame', 'label', 'group', 'order', 'x', 'y'},
    'text': {'text', 'color', 'group', 'order', 'x', 'y'},
    'existing': {'id', 'group', 'order'},
}


class ProposalError(Exception):
    """The proposal is refused as a whole. The message is for the model and for Fred; `code` names the
    (first) problem for a phone receipt (server/intake.py), so nothing matches on message text."""

    def __init__(self, message='', code='invalid'):
        super().__init__(message)
        self.code = code


def _line(text, limit):
    return ' '.join(str(text or '').split())[:limit]


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def rev_of(path) -> int:
    """The canvas file's mtime in microseconds (server/routes/canvas.rev_of)."""
    try:
        return os.stat(path).st_mtime_ns // 1000
    except OSError:
        return 0


def _int(v) -> bool:
    return type(v) is int and -(2 ** 63) <= v < 2 ** 63


def _join(problems) -> str:
    more = len(problems) - PROBLEMS_MAX
    return 'Canvas proposal refused, nothing was changed:\n- ' + '\n- '.join(problems[:PROBLEMS_MAX]) + (
        f'\n- and {more} more' if more > 0 else '')


def deleted_ops(db) -> dict:
    """The phone operations of canvases Fred deleted on the PC, so a resent creation never brings one back."""
    try:
        got = json.loads(db.get_setting(DELETED_OPS, '') or '{}')
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def remember_deleted(db, data) -> None:
    """On the Writer, before a canvas file is deleted: keep its phone markers (newest last, capped)."""
    ops = (data or {}).get('phone_ops')
    if not isinstance(ops, dict) or not ops:
        return
    keep = deleted_ops(db)
    for op_id, digest in ops.items():
        keep.pop(op_id, None)
        keep[op_id] = [data.get('id', ''), digest]
    db.set_setting(DELETED_OPS, json.dumps(dict(list(keep.items())[-DELETED_MAX:])))


# ── read views ───────────────────────────────────────────────────────────────
def canvas_rows(canvas_dir) -> list:
    """Every canvas, newest first: id, name, element count, modified (ms)."""
    rows = canvas_entries(canvas_dir)
    return [{'id': r['id'], 'name': r.get('name', ''), 'elements': r.get('item_count', 0),
             'modified': r.get('modified', 0)} for r in rows]


def load(canvas_dir, cid):
    """One canvas dict, or None (bad id, missing or unreadable file)."""
    if not CID.match(str(cid or '')):
        return None
    data = _read_json(os.path.join(canvas_dir, f'{cid}.json'))
    if not isinstance(data, dict):
        return None
    data.setdefault('items', [])
    return data


def canvas_view(canvas_dir, cid, limit=READ_MAX) -> dict:
    data = load(canvas_dir, cid)
    if data is None:
        raise ProposalError(f'No canvas with id {cid!r}. list_canvases gives the ids.')
    els = [e for e in data['items'] if isinstance(e, dict)]
    out = []
    for e in els[:limit]:
        row = {'id': e.get('id'), 'type': e.get('type')}
        if e.get('type') == 'image':
            if e.get('source') == 'db':
                row['item_id'] = e.get('item_id')
            else:
                row['file_path'] = e.get('file_path')
        if e.get('label'):
            row['label'] = _line(e['label'], MAX_LABEL)
        if e.get('type') == 'note':
            row['text'] = _line(e.get('text'), TEXT_PREVIEW)
        for k in ('x', 'y', 'w', 'h'):
            try:
                row[k] = round(float(e.get(k, 0)))
            except (TypeError, ValueError):
                row[k] = 0
        out.append(row)
    return {'id': data.get('id', cid), 'name': data.get('name', ''), 'count': len(els), 'shown': len(out),
            'truncated': len(els) > limit, 'elements': out}


def frames_view(item_dir, item_id) -> dict:
    names = [p.name for p in canvas_elements.frame_paths(item_dir)]
    return {'item_id': item_id, 'count': len(names), 'frames': names[:FRAMES_MAX],
            'truncated': len(names) > FRAMES_MAX}


# ── the proposal ─────────────────────────────────────────────────────────────
def normalize(payload) -> dict:
    """Check the shape of a model's proposal (no file or DB access). Returns the clean proposal or raises
    ProposalError listing every problem."""
    if not isinstance(payload, dict):
        raise ProposalError('Give a canvas proposal object.')
    problems = []
    extra = set(payload) - TOP_KEYS
    if extra:
        problems.append(f"unknown field(s): {', '.join(sorted(map(str, extra)))}")
    for key in ('canvas_id', 'new_name'):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            problems.append(f'{key} must be a string')
    cid = str(payload.get('canvas_id') or '').strip()
    name = _line(payload.get('new_name'), 10_000)
    if bool(cid) == bool(name):
        problems.append('give exactly one of canvas_id (an existing canvas) or new_name (a new canvas)')
    if cid and not CID.match(cid):
        problems.append(f'canvas_id {cid[:70]!r} is not a canvas id (list_canvases gives the ids)')
    if len(name) > NAME_MAX:
        problems.append(f'new_name is longer than {NAME_MAX} characters')
    layout = payload.get('layout') or 'rows'
    if layout not in LAYOUTS:
        problems.append(f"layout must be one of {', '.join(LAYOUTS)}")
    arrange = payload.get('arrange', False)
    if not isinstance(arrange, bool):
        problems.append('arrange must be true or false')
        arrange = False
    elif arrange and not cid:
        problems.append('arrange works only on an existing canvas (canvas_id)')
    els = payload.get('elements')
    if not isinstance(els, list) or not els:
        problems.append('elements must be a non-empty list')
        els = []
    if len(els) > MAX_ELEMENTS:
        problems.append(f'at most {MAX_ELEMENTS} elements per proposal (got {len(els)})')
        els = els[:MAX_ELEMENTS]
    out, seen, groups, notes = [], set(), [], 0
    for n, e in enumerate(els, 1):
        at = f'element {n}'
        if not isinstance(e, dict):
            problems.append(f'{at}: not an object')
            continue
        kind = e.get('kind')
        if not isinstance(kind, str) or kind not in KIND_KEYS:
            problems.append(f"{at}: kind must be one of {', '.join(KIND_KEYS)}")
            continue
        bad = set(e) - KIND_KEYS[kind] - {'kind'}
        if bad:
            problems.append(f"{at}: field(s) not allowed for {kind}: {', '.join(sorted(map(str, bad)))}")
        for key in ('frame', 'text', 'color', 'id', 'label', 'group'):
            if e.get(key) is not None and not isinstance(e[key], str):
                problems.append(f'{at}: {key} must be a string')
        el = {'kind': kind}
        if kind in ('thumbnail', 'frame'):
            if not _int(e.get('item_id')):
                problems.append(f'{at}: item_id must be an integer item id')
            else:
                el['item_id'] = e['item_id']
        if kind == 'frame':
            frame = str(e.get('frame') or '')
            if not canvas_elements.FRAME_NAME.match(frame) or '..' in frame:
                problems.append(f'{at}: frame must be a frame file name from list_frames (e.g. frame_001.jpg)')
            else:
                el['frame'] = frame
        if kind == 'text':
            text = str(e.get('text') or '').strip()
            if not text:
                problems.append(f'{at}: text is empty')
            elif len(text) > MAX_NOTE_TEXT:
                problems.append(f'{at}: text is longer than {MAX_NOTE_TEXT} characters')
            el['text'] = text
            if e.get('color') is not None:
                if not COLOR.match(str(e['color'])):
                    problems.append(f'{at}: color must look like #FFF9C4')
                else:
                    el['color'] = str(e['color'])
            notes += 1
        if kind == 'existing':
            eid = str(e.get('id') or '')
            if not arrange:
                problems.append(f'{at}: existing elements move only with arrange: true')
            if not CID.match(eid):
                problems.append(f'{at}: id must be an element id from read_canvas')
            elif eid in seen:
                problems.append(f'{at}: element {eid} appears twice')
            seen.add(eid)
            el['id'] = eid
        if e.get('label') is not None and kind in ('thumbnail', 'frame'):
            el['label'] = _line(e['label'], MAX_LABEL)
        if e.get('group') is not None:
            group = _line(e['group'], MAX_LABEL)
            if not group:
                problems.append(f'{at}: group is empty')
            else:
                el['group'] = group
                if group not in groups:
                    groups.append(group)
        if e.get('order') is not None:
            if not _int(e['order']):
                problems.append(f'{at}: order must be an integer')
            else:
                el['order'] = e['order']
        has_x, has_y = 'x' in e, 'y' in e
        if has_x or has_y:
            if not (has_x and has_y) or not all(_int(e[k]) and 0 <= e[k] <= OFFSET_MAX for k in ('x', 'y')):
                problems.append(f'{at}: x and y go together, integers from 0 to {OFFSET_MAX}')
            elif 'group' in el:
                problems.append(f'{at}: give either a group or x/y, not both')
            else:
                el['dx'], el['dy'] = e['x'], e['y']
        out.append(el)
    if len(groups) > MAX_SECTIONS:
        problems.append(f'at most {MAX_SECTIONS} groups (sections) per proposal')
    if notes + len(groups) > MAX_NOTES:
        problems.append(f'at most {MAX_NOTES} text notes per proposal, section titles included')
    if problems:
        raise ProposalError(_join(problems))
    return {'canvas_id': cid or None, 'new_name': name or None, 'layout': layout, 'arrange': arrange,
            'elements': out}


def sections(elements: list) -> tuple:
    """(sections, explicit) in display order: groups by first appearance, ungrouped last (untitled);
    inside a section by order, then input order. Works on any list parallel to the proposal's
    elements: pass pairs (proposal element, payload) and get the payloads back."""
    order, by, explicit = [], {}, []
    for i, (p, v) in enumerate(elements):
        if 'dx' in p:
            explicit.append(v)
            continue
        key = p.get('group')
        if key not in by:
            by[key] = []
            order.append(key)
        by[key].append((p.get('order', 10 ** 9), i, v))
    if None in by:
        order.remove(None)
        order.append(None)
    return [{'title': k, 'elements': [v for _o, _i, v in sorted(by[k], key=lambda t: t[:2])]} for k in order], explicit


def _thumb(db, iid):
    p = db.items_dir / str(iid) / 'thumb.jpg'
    return p if p.is_file() else None


def _frame(db, iid, name):
    return canvas_elements.frame_path(db.items_dir / str(iid), name)


def _overlap(boxes) -> bool:
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                return True
    return False


def _size(db, p) -> tuple:
    """The (w, drawn h) the element will take on the board (images at their real aspect, with their card)."""
    if p['kind'] == 'thumbnail':
        el = canvas_elements.fit_height(canvas_elements.element('thumbnail', item_id=p['item_id']), _thumb(db, p['item_id']))
    elif p['kind'] == 'frame':
        el = canvas_elements.fit_height({'type': 'image', 'w': 200, 'h': 150}, _frame(db, p['item_id'], p['frame']))
    else:
        el = {'type': 'note', 'w': 240, 'h': 160}
    return float(el['w']), canvas_elements.footprint(el)[1]


def _box(el) -> tuple:
    return (el['dx'], el['dy'], float(el['w']), canvas_elements.footprint(el)[1])


def check(db, canvas_dir, p) -> dict:
    """Check a normalized proposal against the library and the canvas file (reads only; at proposal time
    and again at Apply). Raises ProposalError listing every problem. Returns the canvas (None for a new
    one), its rev, the item rows and the review preview."""
    data, rev = None, 0
    if p['canvas_id']:
        data = load(canvas_dir, p['canvas_id'])
        if data is None:
            raise ProposalError(_join([f"no canvas with id {p['canvas_id']} (list_canvases gives the ids)"]),
                                'missing_canvas')
        rev = rev_of(os.path.join(canvas_dir, f"{p['canvas_id']}.json"))
    else:
        for r in canvas_rows(canvas_dir):
            if r['name'].strip().lower() == p['new_name'].lower():
                raise ProposalError(_join([f"a canvas named {r['name']!r} exists: add to it with canvas_id "
                                           f"{r['id']}, or choose another new_name"]), 'name_taken')
    ids = sorted({e['item_id'] for e in p['elements'] if 'item_id' in e})
    rows = {r['id']: r for r in db.get_items_by_ids(ids)} if ids else {}
    have = {str(e.get('id')): e for e in (data or {}).get('items', []) if isinstance(e, dict)}
    problems, codes = [], []
    for n, e in enumerate(p['elements'], 1):
        at = f'element {n}'
        if 'item_id' in e and e['item_id'] not in rows:
            problems.append(f"{at}: no item with id {e['item_id']}")
            codes.append('missing_item')
        elif e['kind'] == 'thumbnail' and _thumb(db, e['item_id']) is None:
            problems.append(f"{at}: item {e['item_id']} has no thumbnail yet (Fetch link info makes one)")
            codes.append('no_thumbnail')
        elif e['kind'] == 'frame' and _frame(db, e['item_id'], e['frame']) is None:
            problems.append(f"{at}: item {e['item_id']} has no frame named {e['frame']} "
                            '(list_frames gives the names; no frames means Analyze has not run on it)')
            codes.append('no_frame')
        elif e['kind'] == 'existing' and e['id'] not in have:
            problems.append(f"{at}: no element {e['id']} on this canvas")
            codes.append('missing_element')
    if problems:
        raise ProposalError(_join(problems), codes[0])
    explicit = [e for e in p['elements'] if 'dx' in e]
    if _overlap([(e['dx'], e['dy'], *_size(db, e)) for e in explicit]):
        raise ProposalError(_join(['elements placed with x/y overlap each other: space them out or use groups']),
                            'overlap')

    def view(e):
        v = {'kind': e['kind']}
        if 'item_id' in e:
            r = rows[e['item_id']]
            v['item_id'] = e['item_id']
            v['title'] = _line(r.get('short_desc') or r.get('ai_desc') or r.get('description') or r.get('url'), 80)
        for k in ('frame', 'label', 'color'):
            if k in e:
                v[k] = e[k]
        if e['kind'] == 'text':
            v['text'] = e['text']
        if e['kind'] == 'existing':
            old = have[e['id']]
            v['id'] = e['id']
            v['type'] = old.get('type')
            v['text'] = _line(old.get('text') or old.get('label'), TEXT_PREVIEW)
            if old.get('source') == 'db':
                v['item_id'] = old.get('item_id')
            elif old.get('file_path'):
                v['file_path'] = old['file_path']
        return v
    secs, expl = sections([(e, view(e)) for e in p['elements']])
    kinds = [e['kind'] for e in p['elements']]
    preview = {
        'target': {'id': p['canvas_id'], 'name': data.get('name', '') if data else p['new_name'],
                   'new': data is None, 'count': len(have)},
        'layout': p['layout'], 'arrange': p['arrange'],
        'counts': {'thumbnail': kinds.count('thumbnail'), 'frame': kinds.count('frame'),
                   'text': kinds.count('text'), 'sections': sum(1 for s in secs if s['title']),
                   'moves': kinds.count('existing')},
        'sections': secs, 'explicit': expl,
    }
    return {'data': data, 'rev': rev, 'rows': rows, 'preview': preview}


def apply(db, cs, p, rev=0, *, phone=None) -> dict:
    """Apply an approved proposal, on the Writer: re-check against the CURRENT canvas file (a canvas changed
    since the proposal is re-validated, never overwritten from a stale copy), build every element, then
    publish the complete canvas once. All or nothing: on any failure the frame copies made
    here are removed and no canvas is created or saved."""
    if phone:
        old = load(cs.canvas_dir, phone['canvas_id'])
        markers = (old or {}).get('phone_ops') or {}
        marker = markers.get(phone['op_id']) if isinstance(markers, dict) else None
        if marker:
            if marker != phone['hash']:
                raise ProposalError('Canvas operation ID was reused with different content.', 'reused')
            return {'canvas_id': old['id'], 'name': old.get('name', ''), 'added': 0, 'moved': 0,
                    'count': len(old.get('items', [])), 'rev': rev_of(cs.canvas_dir / f"{old['id']}.json"),
                    'changed': False}
        if (p['canvas_id'] and p['canvas_id'] != phone['canvas_id']) or (not p['canvas_id'] and old):
            raise ProposalError('Canvas target changed or the new canvas ID is occupied.', 'target')
    chk = check(db, cs.canvas_dir, p)
    data = chk['data']
    changed = bool(p['canvas_id']) and chk['rev'] != rev
    copied, built = [], []
    try:
        for e in p['elements']:
            k = e['kind']
            if k == 'thumbnail':
                el = canvas_elements.fit_height(canvas_elements.element(
                    'thumbnail', item_id=e['item_id'], label=e.get('label', '')), _thumb(db, e['item_id']))
            elif k == 'frame':
                fp = _frame(db, e['item_id'], e['frame'])
                el = canvas_elements.element('frame', cs, path=fp, label=e.get('label', fp.stem))
                if el is None:
                    raise ProposalError(_join([f"could not copy frame {e['frame']} of item {e['item_id']}"]), 'no_frame')
                copied.append(el['file_path'])
            elif k == 'text':
                el = canvas_elements.element('text', text=e['text'], **({'color': e['color']} if 'color' in e else {}))
            else:
                el = next(x for x in data['items'] if isinstance(x, dict) and str(x.get('id')) == e['id'])
            built.append(el)
        moved = {id(el) for e, el in zip(p['elements'], built) if e['kind'] == 'existing'}
        for e, el in zip(p['elements'], built):
            if 'dx' in e:
                el['dx'], el['dy'] = e['dx'], e['dy']
        if _overlap([_box(el) for el in built if 'dx' in el]):
            raise ProposalError(_join(['elements placed with x/y overlap each other: space them out or use groups']),
                                'overlap')
        secs, explicit = sections(list(zip(p['elements'], built)))
        staying = [x for x in (data or {}).get('items', []) if isinstance(x, dict) and id(x) not in moved]
        placed = canvas_elements.arrange(secs, canvas_elements.origin(staying), p['layout'], explicit)
        new = [el for el in placed if id(el) not in moved]
        if data is None:
            data = {'id': phone['canvas_id'] if phone else uuid.uuid4().hex[:12], 'name': p['new_name'],
                    'created': phone['at'] if phone else int(time.time() * 1000), 'items': []}
        if phone:
            for n, el in enumerate(x for x in placed if id(x) not in moved):
                el['id'] = f"{phone['op_id']}_{n}"
            data.setdefault('phone_ops', {})[phone['op_id']] = phone['hash']
        data.setdefault('items', []).extend(new)
        cs.save_canvas(data)
    except Exception:
        for name in copied:
            try:
                cs.upload_path(name).unlink()
            except OSError:
                pass
        raise
    return {'canvas_id': data['id'], 'name': data.get('name', ''), 'added': len(new), 'moved': len(moved),
            'count': len(data['items']), 'rev': rev_of(cs.canvas_dir / f"{data['id']}.json"), 'changed': changed}
