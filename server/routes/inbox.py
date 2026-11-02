"""Wiskit's drop panel (projects/desktop-app plan 07): file whatever was dropped or pasted.

POST /api/inbox/text        {"text"}                  -> {"file"}: a dated section in the Inbox note
POST /api/inbox/screenshot  {"images": [{name, type, data}]} -> the digest job on the Inbox note
POST /api/inbox/link        {"url"}                   -> {"id", "new"}: a library item + Fetch thumbnails
POST /api/inbox/file?name=  raw body                  -> {"path", "file"}: data/inbox/ + a line in the Inbox note
Questions go to POST /api/ask (Wiskit), unchanged.

Note writes and the new item run on the Writer (single SQLite writer); the file copy needs no DB.
"""
import sqlite3

from fastapi import APIRouter, Body, HTTPException, Request

from knowledge import inbox
from server.jobs import Busy, JobError
from server.routes import my_notes as my_notes_routes
from server.store import reader

router = APIRouter()


async def _inbox_note(request: Request, heading: str = '', text: str = ''):
    def write(db):
        p = inbox.note(db.notes_dir)
        if text:
            inbox.append(p, heading, text)
        db.reindex_notes()
        return p
    p = await request.app.state.writer.run(write)
    request.app.state.hub.publish('notes_changed', {'file': p.name, 'personal': True})
    return p


@router.post('/api/inbox/text')
async def drop_text(request: Request, body: dict = Body(...)):
    text = str(body.get('text') or '').strip()
    if not text:
        raise HTTPException(400, 'Type or drop some text first.')
    p = await _inbox_note(request, 'Note', text)
    request.app.state.notify('capture', 'Saved to your Inbox', text[:120])
    return {'file': p.name}


@router.post('/api/inbox/screenshot')
async def drop_screenshot(request: Request, body: dict = Body(...)):
    p = await _inbox_note(request)
    request.app.state.notify('capture', 'Screenshot received', 'Wiskit is reading it into your Inbox.')
    return my_notes_routes.digest(p.name, request, body)


@router.post('/api/inbox/link')
async def drop_link(request: Request, body: dict = Body(...)):
    url = inbox.link(str(body.get('url') or ''))
    if not url:
        raise HTTPException(400, 'That is not a web link.')
    row = reader(request.app.state.db_path).conn.execute('SELECT id FROM items WHERE url = ?', (url,)).fetchone()
    if row:
        return {'id': row[0], 'new': False}

    def write(db):
        return db.add_item({'url': url, 'description': url})
    try:
        new_id = await request.app.state.writer.run(write)
    except sqlite3.IntegrityError:
        row = reader(request.app.state.db_path).conn.execute('SELECT id FROM items WHERE url = ?', (url,)).fetchone()
        return {'id': row[0] if row else None, 'new': False}
    request.app.state.hub.publish('items_changed', {'ids': [new_id]})
    request.app.state.notify('capture', 'Link saved to your library', url)
    try:
        request.app.state.jobs.start('thumb', [new_id], True, {})
    except (Busy, JobError):
        pass        # another job is running: the thumbnail can be fetched later from the card
    return {'id': new_id, 'new': True}


@router.post('/api/inbox/file')
async def drop_file(request: Request, name: str = 'file'):
    raw = await request.body()
    if not raw:
        raise HTTPException(400, 'The file is empty.')
    try:
        path = inbox.save_file(request.app.state.data_dir, name, raw)
    except ValueError as e:
        raise HTTPException(413, str(e))
    p = await _inbox_note(request, 'File', f'Saved `{path.name}` to `data/inbox/` ({len(raw) // 1024} KB).')
    request.app.state.notify('capture', 'File saved to your Inbox', path.name)
    return {'path': str(path), 'file': p.name}
