"""Library endpoints: items, one item, categories, tags, text search, thumbnails, item edits."""
import json
import sqlite3
from core.urls import http_url

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, Response

from core import ai_client
from server.library import compact
from server.store import reader

router = APIRouter()

# Fields the item window may change (the Qt EditDialog's fields). ai_desc, thumb_path,
# analysis_* and transcript are written only by jobs.
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}

EDITABLE = {'description', 'short_desc', 'creator', 'type', 'category', 'url', 'tags', 'notes'}


def _rd(request: Request):
    return reader(request.app.state.db_path)


def embedded(db) -> set:
    """Ids that have a vector for the current embedding model (nd bit 16 is set for the rest)."""
    return set(db.get_embedding_hashes(ai_client.EMBEDDING_MODEL))


@router.get('/api/health')
def health(request: Request):
    import secrets
    if not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + request.app.state.api_token):
        return {'ok': True}
    from core import entitlements
    return {'ok': True, 'items': _rd(request).count_items(), 'licensed': entitlements.feature_enabled('phone_sync')}


# The full list, one body per format for the whole server (app.state.items_cache, plan
# 10-footprint A4), kept until the Writer's next write: {fmt: (Writer.generation, body)}. The
# generation is read before the rows, so a write that lands while a body is built leaves it stale
# and the next request rebuilds. The Writer is the only connection that writes while the server runs.


@router.get('/api/items')
def items(request: Request, ids: str = '', fmt: str = ''):
    """Every item as a compact row, newest first; or only `ids` (comma-separated), the
    refetch after an items_changed event. Unknown ids are left out.
    fmt=cols (the front end): {"cols": [key, ...], "rows": [[value, ...], ...], "total": n},
    booleans as 0 / 1; about 30 % smaller than the default list of objects."""
    cols = fmt == 'cols'
    db = _rd(request)
    if ids:
        rows = db.get_items_by_ids([int(x) for x in ids.split(',') if x.strip().isdigit()])
        return Response(_rows_json(db, rows, cols), media_type='application/json')
    cache = request.app.state.items_cache
    gen = request.app.state.writer.generation
    hit = cache.get(fmt)
    if hit and hit[0] == gen:
        return Response(hit[1], media_type='application/json')
    body = _rows_json(db, db.search_items(sort='new'), cols)
    hit = cache.get(fmt)
    if not hit or hit[0] <= gen:
        cache[fmt] = (gen, body)
    return Response(body, media_type='application/json')


def _rows_json(db, rows, cols: bool = False) -> str:
    # Serialized here: FastAPI's default path walks all 3,000+ rows through jsonable_encoder first,
    # which cost about as much as building them (PLAN.md budget: /api/items <= 120 ms).
    emb = embedded(db)
    out = [compact(r, emb) for r in rows]
    if cols:
        keys = list(out[0]) if out else []
        data = {'cols': keys, 'rows': [[int(v) if isinstance(v, bool) else v for v in o.values()] for o in out],
                'total': len(out)}
    else:
        data = {'items': out, 'total': len(out)}
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


@router.get('/api/items/{item_id}')
def item(item_id: int, request: Request):
    row = _rd(request).get_item(item_id)
    if not row:
        raise HTTPException(404, 'no such item')
    d = request.app.state.data_dir / 'items' / str(item_id)
    frames = d / 'frames'
    names = sorted(f.name for f in frames.glob('*.jpg')) if frames.is_dir() else []
    vdir = d / 'video'
    row['files'] = {
        'thumb': (d / 'thumb.jpg').is_file(),
        'report': (d / 'report.md').is_file(),
        'transcript': (d / 'transcript.txt').is_file(),
        'frames': len(names),
        'frame_names': names,                          # plan 06: the Frames & Analysis tab
        'video': vdir.is_dir() and any(f.suffix.lower() in VIDEO_EXTS for f in vdir.iterdir()),
    }
    return row


@router.patch('/api/items/{item_id}')
async def edit_item(item_id: int, request: Request, data: dict = Body(...)):
    clean = {k: (v if isinstance(v, str) else str(v)) for k, v in data.items() if k in EDITABLE}
    if not clean:
        raise HTTPException(400, 'no editable fields')
    if 'description' in clean and not clean['description'].strip():
        raise HTTPException(400, 'description is required')
    if 'url' in clean and not clean['url'].strip():
        raise HTTPException(400, 'url is required')

    if 'url' in clean and not http_url(clean['url']):
        raise HTTPException(400, 'A valid HTTP(S) URL is required.')

    def write(db):
        if not db.get_item(item_id):
            return None
        db.update_item(item_id, clean)
        return compact(db.get_item(item_id), embedded(db))

    try:
        row = await request.app.state.writer.run(write)
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'another item already has this url')
    if row is None:
        raise HTTPException(404, 'no such item')
    request.app.state.hub.publish('items_changed', {'ids': [item_id]})
    request.app.state.jobs.dirty.add(item_id)          # re-embedded by the next automatic index pass
    return row


@router.post('/api/items/{item_id}/favourite')
async def favourite(item_id: int, request: Request, data: dict = Body(...)):
    """Star or unstar an item (a holo card). Body {"on": bool}; returns the compact row."""
    on = bool(data.get('on'))

    def write(db):
        if not db.get_item(item_id):
            return None
        db.update_item(item_id, {'favourite': on})
        return compact(db.get_item(item_id), embedded(db))

    row = await request.app.state.writer.run(write)
    if row is None:
        raise HTTPException(404, 'no such item')
    request.app.state.hub.publish('items_changed', {'ids': [item_id]})
    return row


@router.get('/api/categories')
def categories(request: Request):
    db = _rd(request)
    counts = db.count_by_category()
    return [{**c, 'count': counts.get(c['name'], 0)} for c in db.get_categories()]


@router.get('/api/tags')
def tags(request: Request):
    return [{'tag': t, 'n': n} for t, n in _rd(request).get_all_tags()]


@router.get('/api/search')
def search(request: Request, q: str = ''):
    """Ids matching the Library search box, with the app's semantics (every word, FTS5,
    LIKE fallback). Empty q returns no ids: the client shows everything then. A q that is one
    whole number also finds the item with that id, listed first (never a partial id)."""
    q = q.strip()
    if not q:
        return {'ids': []}
    db = _rd(request)
    ids = [r['id'] for r in db.search_items(query=q)]
    if q.isascii() and q.isdigit() and int(q) > 0 and db.get_item(int(q)):
        n = int(q)
        ids = [n] + [i for i in ids if i != n]
    return {'ids': ids}


def _scaled_jpeg(p, w: int):
    """The thumbnail at w px wide as JPEG bytes, or None when it is already that narrow or unreadable.
    draft() lets the JPEG decoder skip to the nearest 1/2, 1/4 or 1/8 scale before the resize."""
    import io
    from PIL import Image
    try:
        with Image.open(p) as im:
            if im.width <= w:
                return None
            h = max(1, round(im.height * w / im.width))
            im.draft('RGB', (w, h))
            out = im.convert('RGB').resize((w, h), Image.LANCZOS)
        b = io.BytesIO()
        out.save(b, 'JPEG', quality=85)
        return b.getvalue()
    except Exception:
        return None


@router.get('/thumb/{item_id}')
def thumb(item_id: int, request: Request, v: int = 0, w: int = 0):
    p = request.app.state.data_dir / 'items' / str(item_id) / 'thumb.jpg'
    if not p.is_file():
        raise HTTPException(404, 'no thumbnail')
    # ?v=<row tv> (the front end's thumbSrc) names one version of the image: the browser keeps it
    # and never asks again; a new thumbnail comes with a new tv, so a new URL. Without v:
    # no-cache = revalidate with the ETag every time.
    cache = 'public, max-age=31536000, immutable' if v else 'no-cache'
    # ?w=<px> (the Library grid asks for 320): resized in memory, nothing written to data/
    if w > 0:
        body = _scaled_jpeg(p, w)
        if body is not None:
            return Response(body, media_type='image/jpeg', headers={'Cache-Control': cache})
    return FileResponse(p, media_type='image/jpeg', headers={'Cache-Control': cache})
