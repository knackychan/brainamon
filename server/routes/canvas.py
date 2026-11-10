"""Canvases (moodboards): the list, one canvas, its elements, image uploads, the active canvas.

Canvas files stay data/canvases/<id>.json through canvas.CanvasStore (no DB). Every write runs on
the Writer thread anyway (one writer for all of data/), so two writes never interleave. A save
carries the `rev` (file mtime in microseconds) the client loaded; a stale one is refused with 409,
so the Qt canvas window and V6 never overwrite each other's newer file. The active canvas (where
every Add to canvas lands) is kept in the DB setting v6_active_canvas.
"""
import os
import re
import tempfile
import hashlib
import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from library import canvas_elements, canvas_plan
from library.canvas import CanvasStore
from server.store import reader

router = APIRouter()
ACTIVE_KEY = 'v6_active_canvas'
KINDS = ('thumbnail', 'desc', 'ai', 'report', 'frame', 'frames', 'text')
UPLOAD_NAME = re.compile(r'^[A-Za-z0-9_\-]+\.(jpg|jpeg|png|webp|gif|bmp)$', re.I)
UPLOAD_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
                '.gif': 'image/gif', '.bmp': 'image/bmp'}
MAX_IMAGE = 40 * 1024 * 1024
MAX_TEXT = 20000


class Stale(Exception):
    pass


def store(request: Request) -> CanvasStore:
    st = request.app.state
    if getattr(st, 'canvas_store', None) is None:
        st.canvas_store = CanvasStore(st.data_dir)
    return st.canvas_store


def _path(cs: CanvasStore, cid: str):
    if not re.fullmatch(r'[A-Za-z0-9_\-]{1,64}', cid or ''):
        raise HTTPException(404, 'no such canvas')
    return cs.canvas_dir / f'{cid}.json'


def rev_of(path) -> int:
    try:
        return os.stat(path).st_mtime_ns // 1000
    except OSError:
        return 0


def _row(e: dict) -> dict:
    return {'id': e['id'], 'name': e.get('name', ''), 'count': e.get('item_count', 0), 'updated': e.get('modified', 0)}


def _load(cs: CanvasStore, cid: str) -> dict:
    data = cs.load_canvas(cid) if _path(cs, cid).exists() else None
    if not isinstance(data, dict):
        raise HTTPException(404, 'no such canvas')
    data.setdefault('items', [])
    return data


def _changed(request: Request, cid: str, rev: int = 0, count: int | None = None) -> None:
    request.app.state.hub.publish('canvas_changed', {'id': cid, 'rev': rev, 'count': count})


def _name_taken(cs: CanvasStore, name: str, but: str | None = None) -> bool:
    return any(e['id'] != but and e.get('name', '').strip().lower() == name.lower() for e in cs.list_canvases())


def _clean_name(cs: CanvasStore, body: dict, but: str | None = None) -> str:
    name = str(body.get('name') or '').strip()
    if not name:
        raise HTTPException(400, 'Enter a name.')
    if _name_taken(cs, name, but):
        raise HTTPException(409, 'A canvas with that name exists.')
    return name


# ── the list ─────────────────────────────────────────────────────────────────
@router.get('/api/canvases')
def canvases(request: Request):
    return [_row(e) for e in store(request).list_canvases()]


@router.post('/api/canvases')
async def create(request: Request, body: dict = Body(...)):
    cs = store(request)

    def write(db):
        name = _clean_name(cs, body)
        cid = cs.create_canvas(name)
        db.set_setting(ACTIVE_KEY, cid)   # a new canvas becomes the active one (V6 newCanvas)
        return cid
    cid = await request.app.state.writer.run(write)
    request.app.state.canvas_active = cid
    _changed(request, cid, rev_of(_path(cs, cid)), 0)
    request.app.state.hub.publish('canvas_active', {'id': cid})
    return next(_row(e) for e in cs.list_canvases() if e['id'] == cid)


@router.patch('/api/canvases/{cid}')
async def rename(cid: str, request: Request, body: dict = Body(...)):
    cs = store(request)
    _load(cs, cid)

    def write(_db):
        cs.rename_canvas(cid, _clean_name(cs, body, but=cid))
    await request.app.state.writer.run(write)
    _changed(request, cid, rev_of(_path(cs, cid)))
    return next(_row(e) for e in cs.list_canvases() if e['id'] == cid)


@router.post('/api/canvases/draft')
async def draft(request: Request, body: dict = Body(...)):
    """One manual addition, including its retry marker, published by the existing canvas engine."""
    safe = lambda n: type(n) is int and 0 <= n <= 2 ** 53 - 1
    if set(body) != {'op_id', 'canvas_id', 'at', 'proposal', 'base_rev', 'sizes'}:
        raise HTTPException(400, 'Invalid canvas addition fields.')
    op, cid, raw, sizes = (body[k] for k in ('op_id', 'canvas_id', 'proposal', 'sizes'))
    if not isinstance(op, str) or not re.fullmatch('[0-9a-f]{32}', op) or not safe(body['at']):
        raise HTTPException(400, 'Invalid canvas addition identity.')
    if not isinstance(cid, str) or cid == 'index' or not re.fullmatch('[A-Za-z0-9_-]{1,64}', cid):
        raise HTTPException(400, 'Invalid canvas target.')
    if not isinstance(raw, dict) or set(raw) not in ({'canvas_id', 'layout', 'elements'}, {'new_name', 'layout', 'elements'}):
        raise HTTPException(400, 'Invalid canvas addition proposal.')
    if raw['layout'] not in ('rows', 'columns'):
        raise HTTPException(400, 'Invalid layout.')
    def unicode_ok(v):
        if isinstance(v, str):
            return not any(0xD800 <= ord(c) <= 0xDFFF for c in v)
        if isinstance(v, dict):
            return all(unicode_ok(k) and unicode_ok(x) for k, x in v.items())
        return all(unicode_ok(x) for x in v) if isinstance(v, list) else True
    if not unicode_ok(raw):
        raise HTTPException(400, 'Remove invalid characters from the name or note.')
    try:
        p = canvas_plan.normalize(raw)
    except canvas_plan.ProposalError as e:
        raise HTTPException(400, str(e)) from e
    existing = p['canvas_id'] is not None
    if (existing and (p['canvas_id'] != cid or not safe(body['base_rev']) or not body['base_rev'])) or (
            not existing and (body['base_rev'] is not None or not re.fullmatch('[0-9a-f]{32}', cid))):
        raise HTTPException(400, 'Invalid canvas revision or target.')
    ids, notes = [], 0
    for e in raw['elements']:
        if e.get('kind') == 'thumbnail' and set(e) == {'kind', 'item_id'}:
            iid = e['item_id']
            if not safe(iid) or not iid or iid in ids:
                raise HTTPException(400, 'Duplicate or invalid picked image.')
            ids.append(iid)
        elif e.get('kind') == 'text' and set(e) == {'kind', 'text', 'color'}:
            notes += 1
        else:
            raise HTTPException(400, 'Invalid canvas addition element.')
    if notes > 1 or not isinstance(sizes, dict) or set(sizes) != {str(i) for i in ids} or any(
            not isinstance(v, list) or len(v) != 2 or any(not safe(n) or not 0 < n <= 100000 for n in v)
            for v in sizes.values()):
        raise HTTPException(400, 'Invalid selected thumbnail dimensions or note count.')
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    cs = store(request)

    def write(db):
        deleted = canvas_plan.deleted_ops(db).get(op)
        if deleted:
            raise HTTPException(410 if deleted == [cid, digest] else 409,
                                'This canvas was deleted.' if deleted == [cid, digest] else 'Canvas operation ID was reused with different content.')
        # The ID is global, so a replay cannot redirect a previous operation to another board.
        for row in cs.list_canvases():
            doc = cs.load_canvas(row['id']) or {}
            marker = (doc.get('phone_ops') or {}).get(op)
            if marker:
                if row['id'] != cid or marker != digest:
                    raise HTTPException(409, 'Canvas operation ID was reused with different content.')
                return {'canvas_id': cid}, False
        path = _path(cs, cid)
        if existing:
            data = _load(cs, cid)
            if rev_of(path) != body['base_rev']:
                raise HTTPException(409, 'Canvas changed. Check the board and tap Add again.')
            if any(e.get('source') == 'db' and e.get('item_id') in ids for e in data['items']):
                raise HTTPException(400, 'A picked image is already on this canvas.')
        elif path.exists():
            raise HTTPException(409, 'The new canvas ID is occupied.')
        try:
            canvas_plan.check(db, cs.canvas_dir, p)
            from PIL import Image
            for iid in ids:
                try:
                    with Image.open(db.item_dir(iid) / 'thumb.jpg') as image:
                        image.load()
                        current = list(image.size)
                except (OSError, ValueError) as e:
                    raise HTTPException(400, f'Could not read thumbnail for item {iid}.') from e
                if current != sizes[str(iid)]:
                    raise HTTPException(409, 'Canvas changed. Check the board and tap Add again.')
            result = canvas_plan.apply(db, cs, p, body['base_rev'] or 0,
                                       phone={'op_id': op, 'canvas_id': cid, 'at': body['at'], 'hash': digest})
        except canvas_plan.ProposalError as e:
            raise HTTPException(404 if e.code == 'missing_canvas' else 400, str(e)) from e
        return {'canvas_id': result['canvas_id']}, True

    result, changed = await request.app.state.writer.run(write)
    if changed:
        _changed(request, cid, rev_of(_path(cs, cid)))
    return result


@router.delete('/api/canvases/{cid}')
async def delete(cid: str, request: Request):
    cs = store(request)
    _load(cs, cid)

    def write(db):
        canvas_plan.remember_deleted(db, cs.load_canvas(cid))
        cs.delete_canvas(cid)
        if db.get_setting(ACTIVE_KEY, '') == cid:
            rest = cs.list_canvases()
            db.set_setting(ACTIVE_KEY, rest[0]['id'] if rest else '')
        return db.get_setting(ACTIVE_KEY, '') or None
    request.app.state.canvas_active = await request.app.state.writer.run(write)
    _changed(request, cid)
    request.app.state.hub.publish('canvas_active', {'id': request.app.state.canvas_active})
    return {'ok': True}


# ── one canvas ───────────────────────────────────────────────────────────────
@router.get('/api/canvases/{cid}')
def get_canvas(cid: str, request: Request):
    cs = store(request)
    return {'canvas': _load(cs, cid), 'rev': rev_of(_path(cs, cid))}


@router.put('/api/canvases/{cid}')
async def save(cid: str, request: Request, body: dict = Body(...)):
    cs = store(request)
    data, rev = body.get('canvas'), body.get('rev')
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise HTTPException(400, 'canvas.items must be a list')
    path = _path(cs, cid)

    def write(_db):
        if not path.exists():
            raise HTTPException(404, 'no such canvas')
        if rev_of(path) != rev:
            raise Stale()
        cur = cs.load_canvas(cid) or {}
        data['id'] = cid
        data['name'] = str(data.get('name') or cur.get('name') or 'Untitled Canvas')
        data.setdefault('created', cur.get('created', 0))
        if 'phone_ops' in cur:
            data['phone_ops'] = cur['phone_ops']
        else:
            data.pop('phone_ops', None)
        cs.save_canvas(data)
        return rev_of(path)
    try:
        new = await request.app.state.writer.run(write)
    except Stale:
        raise HTTPException(409, 'This canvas was changed elsewhere since you opened it.')
    _changed(request, cid, new, len(data['items']))
    return {'rev': new}


@router.post('/api/canvases/{cid}/elements')
async def add_elements(cid: str, request: Request, body: dict = Body(...)):
    """Add from anywhere: build the elements of `kind` for `ids` (or `text`) and append them to
    the canvas file in one Writer step. Returns the new elements and the new rev."""
    cs = store(request)
    kind = body.get('kind')
    if kind not in KINDS:
        raise HTTPException(400, f'kind must be one of {", ".join(KINDS)}')
    ids = [int(i) for i in body.get('ids') or []]
    at = body.get('at') if isinstance(body.get('at'), dict) else None
    path = _path(cs, cid)

    def write(db):
        data = _load(cs, cid)
        els, why = [], ''
        if kind == 'text':
            el = canvas_elements.element('text', text=str(body.get('text') or '')[:MAX_TEXT])
            els, why = [el] if el else [], 'Nothing to attach (empty text)'
        for iid in ids:
            it = db.get_item(iid)
            if not it:
                continue
            d = db.item_dir(iid)
            if kind == 'thumbnail':
                if (d / 'thumb.jpg').is_file():
                    els.append(canvas_elements.fit_height(canvas_elements.element(
                        'thumbnail', item_id=iid), d / 'thumb.jpg'))
                why = 'This item has no thumbnail yet'
            elif kind in ('desc', 'ai', 'report'):
                el = canvas_elements.element('text', text=canvas_elements.item_text(it, kind, d))
                if el:
                    els.append(el)
                why = {'desc': 'This item has no description', 'ai': 'This item has no AI summary yet',
                       'report': 'This item has no analysis report'}[kind]
            elif kind == 'frame':
                fp = canvas_elements.frame_path(d, str(body.get('frame') or ''))
                el = canvas_elements.element('frame', cs, path=fp, label=fp.stem) if fp else None
                if el:
                    els.append(el)
                why = 'Could not add that frame'
            elif kind == 'frames':
                for fp in canvas_elements.frame_paths(d):
                    el = canvas_elements.element('frame', cs, path=fp, label=f'item {iid}')
                    if el:
                        els.append(el)
                why = 'None of these items has extracted frames. Analyze them first.'
        if not els:
            return {'added': 0, 'why': why or 'Nothing to add', 'rev': rev_of(path), 'elements': []}
        canvas_elements.place(data['items'], els, at)
        data['items'].extend(els)
        cs.save_canvas(data)
        return {'added': len(els), 'rev': rev_of(path), 'elements': els, 'count': len(data['items'])}
    out = await request.app.state.writer.run(write)
    if out['added']:
        _changed(request, cid, out['rev'], out['count'])
    return out


@router.put('/api/canvases/{cid}/image')
async def upload_image(cid: str, request: Request, name: str = 'image'):
    """An image from a file chooser: copied (as JPEG, at most 1200 px) into data/canvases/uploads.
    Returns the element; the client places it and saves the canvas."""
    cs = store(request)
    _load(cs, cid)
    raw = await request.body()
    if not raw:
        raise HTTPException(400, 'empty image')
    if len(raw) > MAX_IMAGE:
        raise HTTPException(413, 'That image is too large (40 MB at most).')
    fd, tmp = tempfile.mkstemp(suffix='.img')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        fname = await request.app.state.writer.run(lambda _db: cs.save_uploaded_image(tmp))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not fname:
        raise HTTPException(400, 'That file is not an image this app can read.')
    label = os.path.splitext(os.path.basename(name))[0][:80]
    return canvas_elements.fit_height({'type': 'image', 'source': 'file', 'file_path': fname,
                                       'w': 200, 'h': 150, 'label': label}, cs.upload_path(fname))


# ── the active canvas ────────────────────────────────────────────────────────
def _active(request: Request) -> str | None:
    st = request.app.state
    if not hasattr(st, 'canvas_active'):
        st.canvas_active = reader(st.db_path).get_setting(ACTIVE_KEY, '') or None
    cid = st.canvas_active
    if cid and not (re.fullmatch(r'[A-Za-z0-9_\-]{1,64}', cid) and (store(request).canvas_dir / f'{cid}.json').exists()):
        return None
    return cid


@router.get('/api/canvas/active')
def get_active(request: Request):
    return {'id': _active(request)}


@router.put('/api/canvas/active')
async def set_active(request: Request, body: dict = Body(...)):
    cid = body.get('id') or None
    if cid is not None:
        _load(store(request), str(cid))
    await request.app.state.writer.run(lambda db: db.set_setting(ACTIVE_KEY, cid or ''))
    request.app.state.canvas_active = cid
    request.app.state.hub.publish('canvas_active', {'id': cid})
    return {'id': cid}


# ── uploads, read-only ───────────────────────────────────────────────────────
@router.get('/files/canvas-uploads/{name}')
def upload_file(name: str, request: Request):
    if not UPLOAD_NAME.match(name):
        raise HTTPException(404, 'not found')
    p = store(request).upload_path(name)
    if not p.is_file():
        raise HTTPException(404, 'not found')
    return FileResponse(p, media_type=UPLOAD_TYPES[p.suffix.lower()], headers={'Cache-Control': 'max-age=86400'})
