"""Item edits beyond the PATCH of plan 02: create, thumbnail upload, local video, related items,
delete, bulk edit, and opening things on the desktop (the server runs on the same machine).

Every SQLite write goes through the Writer. File writes (thumb.jpg, the video copy) happen in the
request thread: only SQLite has the single-writer rule.
"""
import os
import re
import sqlite3
import webbrowser
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from core.urls import http_url

from knowledge import inbox
from library.linkinfo import to_jpeg as _to_jpeg
from server.jobs import Busy, JobError
from server.library import compact
from server.routes.io import MAX_VIDEO
from server.routes.library import embedded
from server.routes.smart import embed_index
from server.store import reader

router = APIRouter()

FIELDS = ('description', 'short_desc', 'creator', 'type', 'category', 'url', 'tags', 'notes')
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}   # Qt item_detail_window.VIDEO_EXTS
MAX_IMAGE = 40 * 1024 * 1024
BULK = {'set_category': 'category', 'set_type': 'type', 'set_creator': 'creator'}


def _items_dir(request: Request) -> Path:
    return request.app.state.data_dir / 'items'


def _changed(request: Request, ids: list, text: bool = True) -> None:
    """Tell the pages to refetch these rows; mark them for the automatic re-embed pass."""
    request.app.state.hub.publish('items_changed', {'ids': list(ids)})
    if text:
        request.app.state.jobs.dirty.update(int(i) for i in ids)


# ── create ───────────────────────────────────────────────────────────────────
@router.post('/api/items')
async def create(request: Request, data: dict = Body(...)):
    clean = {k: str(data.get(k) or '').strip() for k in FIELDS if data.get(k) is not None}
    if not clean.get('url'):
        raise HTTPException(400, 'URL is required.')
    clean = {k: v for k, v in clean.items() if v or k in ('description', 'url')}
    clean['url'] = inbox.link(clean['url']) or clean['url']        # text.com -> https://text.com
    if not http_url(clean['url']):
        raise HTTPException(400, 'A valid HTTP(S) URL is required.')
    # no description: the link stands in, and the widget's follow-up (Fetch thumbnails, forced)
    # replaces it with the post caption (routes/inbox.drop_link)
    fetch = not clean.get('description')
    if fetch:
        clean['description'] = clean['url']

    def write(db):
        new_id = db.add_item(clean)
        if clean.get('notes'):
            db.update_item(new_id, {'notes': clean['notes']})   # add_item has no notes column
        return compact(db.get_item(new_id), embedded(db))

    try:
        row = await request.app.state.writer.run(write)
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'This URL is already in the library.')
    _changed(request, [row['id']])
    if fetch:
        try:
            request.app.state.jobs.start('thumb', [row['id']], True, {})
        except (Busy, JobError):
            fetch = False   # another job is running: the thumbnail can be fetched later from the card
    return {**row, 'fetching': fetch}


# ── thumbnail upload (Qt _upload_thumb: RGB, 600 px box, JPEG 82; library/linkinfo.to_jpeg) ──


@router.put('/api/items/{item_id}/thumb')
async def upload_thumb(item_id: int, request: Request):
    raw = await request.body()
    if not raw:
        raise HTTPException(400, 'No image received.')
    if len(raw) > MAX_IMAGE:
        raise HTTPException(413, 'That image is too large (40 MB at most).')
    if not reader(request.app.state.db_path).get_item(item_id):
        raise HTTPException(404, 'no such item')
    try:
        jpg = await run_in_threadpool(_to_jpeg, raw)
    except Exception as exc:
        raise HTTPException(400, f'Failed to load image: {exc}')
    d = _items_dir(request) / str(item_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / 'thumb.jpg').write_bytes(jpg)

    def write(db):
        db.update_item(item_id, {'thumb_path': 'thumb.jpg'})
        return compact(db.get_item(item_id), embedded(db))

    row = await request.app.state.writer.run(write)
    request.app.state.tints.refresh(item_id)
    _changed(request, [item_id], text=False)
    return row


# ── local video (Qt _link_local_video: copied into data/items/<id>/video/) ───
@router.put('/api/items/{item_id}/video')
async def upload_video(item_id: int, request: Request, name: str = ''):
    base = Path(name.replace('\\', '/')).name
    if not base or Path(base).suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(400, 'Pick a video file (.mp4 .mov .mkv .webm .avi .m4v).')
    if not reader(request.app.state.db_path).get_item(item_id):
        raise HTTPException(404, 'no such item')
    if int(request.headers.get('content-length') or 0) > MAX_VIDEO:
        raise HTTPException(413, 'That video is too large (4 GB at most).')
    vdir = _items_dir(request) / str(item_id) / 'video'
    vdir.mkdir(parents=True, exist_ok=True)
    dest = vdir / base
    tmp = dest.with_name(dest.name + '.part')
    size = 0
    try:
        with open(tmp, 'wb') as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_VIDEO:          # a missing or wrong Content-Length still stops here
                    raise HTTPException(413, 'That video is too large (4 GB at most).')
                f.write(chunk)
        if not size:
            raise HTTPException(400, 'No video received.')
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {'path': f'video/{base}', 'bytes': size}


# ── related by meaning ───────────────────────────────────────────────────────
@router.get('/api/items/{item_id}/related')
def related(item_id: int, request: Request):
    db = reader(request.app.state.db_path)
    idx = embed_index(request.app, db)
    if not idx.has(item_id):
        return {'needs_index': True}
    hits = idx.similar_to(item_id, 8)
    score = dict(hits)
    emb = embedded(db)
    return [{**compact(r, emb), 'score': round(score[r['id']], 4)} for r in db.get_items_by_ids([i for i, _ in hits])]


# ── delete + bulk ────────────────────────────────────────────────────────────
@router.post('/api/items/delete')
async def delete(request: Request, data: dict = Body(...)):
    ids = [int(i) for i in data.get('ids') or []]
    if not ids:
        raise HTTPException(400, 'Nothing to delete.')
    n = await request.app.state.writer.run(lambda db: db.delete_items_bulk(ids))
    _changed(request, ids, text=False)
    return {'deleted': n}


@router.post('/api/items/bulk')
async def bulk(request: Request, data: dict = Body(...)):
    ids = [int(i) for i in data.get('ids') or []]
    action = str(data.get('action') or '')
    value = str(data.get('value') or '').strip()
    if not ids:
        raise HTTPException(400, 'Tick at least one item.')
    if action == 'delete':
        n = await request.app.state.writer.run(lambda db: db.delete_items_bulk(ids))
        _changed(request, ids, text=False)
        return {'changed': n}
    if action not in BULK and action not in ('add_tags', 'remove_tags'):
        raise HTTPException(400, f'Unknown bulk action: {action}')
    if not value:
        raise HTTPException(400, 'Enter a value.')
    if action in BULK:
        n = await request.app.state.writer.run(lambda db: db.set_field_bulk(ids, BULK[action], value))
    else:
        mode = 'add' if action == 'add_tags' else 'remove'
        n = await request.app.state.writer.run(lambda db: db.modify_tags_bulk(ids, mode, value))
    _changed(request, ids)
    return {'changed': n}


# ── open on the desktop ──────────────────────────────────────────────────────
def _startfile(path: Path) -> None:
    os.startfile(str(path))      # Windows; the V6 window runs on Fred's machine


def _largest_video(d: Path) -> Path | None:
    vdir = d / 'video'
    vids = [f for f in vdir.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS] if vdir.is_dir() else []
    return max(vids, key=lambda f: f.stat().st_size) if vids else None


@router.post('/api/open')
def open_(request: Request, data: dict = Body(...)):
    what = str(data.get('what') or '')
    try:
        item_id = int(data.get('id'))
    except (TypeError, ValueError):
        raise HTTPException(400, 'Which item?')
    row = reader(request.app.state.db_path).get_item(item_id)
    if not row:
        raise HTTPException(404, 'no such item')
    d = _items_dir(request) / str(item_id)
    if what == 'url':
        url = (row.get('url') or '').strip()
        if not re.match(r'^https?://', url, re.I):
            raise HTTPException(400, 'This item has no web address.')
        webbrowser.open(url)
    elif what == 'folder':
        d.mkdir(parents=True, exist_ok=True)
        _startfile(d)
    elif what == 'video':
        v = _largest_video(d)
        if not v:
            raise HTTPException(400, 'No local video for this item yet.')
        _startfile(v)
    elif what == 'report':
        rp = d / 'report.md'
        if not rp.is_file():
            raise HTTPException(400, 'No analysis report has been generated yet.')
        _startfile(rp)
    else:
        raise HTTPException(400, f'Cannot open: {what}')
    return {'ok': True}
