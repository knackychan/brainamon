"""My Notes: the personal notebook (categories, notes, the autosave, Summarize, screenshot digest).

The file logic is my_notes.py (shared with the Qt My Notes window). Every write runs on the Writer
and is followed by db.reindex_notes() and an SSE notes_changed, so Knowledge and Wiskit see it.
Summarize and the screenshot digest are background jobs (`summarize`, `digest`).
"""
import asyncio
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request

from core import config, entitlements, note_format
from knowledge import knowledge
from knowledge import my_notes
from knowledge import voice
from server.jobs import Busy, JobError
from server.store import reader

router = APIRouter()
MAX_DIGEST_BYTES = 30 * 1024 * 1024
MAX_VOICE_BYTES = 100 * 1024 * 1024
_voice_busy = False             # one transcription at a time (the event loop is single threaded)


def _nd(request: Request):
    return request.app.state.data_dir / 'notes'


def _note(request: Request, file: str):
    p = knowledge.safe_note_path(_nd(request), file)
    if p is None:
        raise HTTPException(404, 'no such note')
    return p


def _out(p, meta: dict, body: str | None = None) -> dict:
    d = {'file': p.name, 'title': meta.get('topic') or p.stem, 'category': meta.get('category') or my_notes.DEFAULT_CATEGORY,
         'created': meta.get('created', ''), 'updated': meta.get('updated', '')}
    if body is not None:
        d['body'] = body
        d['stamps'] = note_format.parse_stamps(meta.get(note_format.KEY))
    return d


def _changed(request: Request, file: str) -> None:
    request.app.state.hub.publish('notes_changed', {'file': file, 'personal': True})


@router.get('/api/my-notes/categories')
def categories(request: Request):
    return {'categories': my_notes.all_categories(reader(request.app.state.db_path), _nd(request))}


@router.post('/api/my-notes/categories')
async def add_category(request: Request, body: dict = Body(...)):
    name = str(body.get('name') or '').strip()
    if not name:
        raise HTTPException(400, 'Enter a category name.')
    await request.app.state.writer.run(lambda db: my_notes.add_category(db, name))
    return categories(request)


@router.post('/api/my-notes/categories/rename')
async def rename_category(request: Request, body: dict = Body(...)):
    """Rename a category on every personal note in it (the phone connected to the PC, the desktop rail)."""
    old, new, nd = body.get('from'), body.get('to'), _nd(request)

    def run(db):
        paths = my_notes.rename_category(db, nd, old, new)
        if paths:
            db.reindex_notes()
        return paths
    try:
        paths = await request.app.state.writer.run(run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for p in paths:
        _changed(request, p.name)
    return categories(request)


@router.get('/api/my-notes')
def notes(request: Request, category: str = my_notes.ALL_CATEGORY):
    out = []
    for p, meta, body in my_notes.personal_notes(_nd(request)):
        cat = meta.get('category') or my_notes.DEFAULT_CATEGORY
        if category != my_notes.ALL_CATEGORY and cat != category:
            continue
        d = _out(p, meta)
        d['stamps'] = note_format.parse_stamps(meta.get(note_format.KEY))
        d['snippet'] = knowledge.note_snippet(body)
        d['head'] = note_format.head(body)          # the phone's note card (plans/08-note-cards.md)
        d['words'] = note_format.word_count(body)
        out.append(d)
    return out


@router.get('/api/my-notes/{file}')
def get_note(file: str, request: Request):
    p = _note(request, file)
    meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    return _out(p, meta, body.strip('\n'))


@router.post('/api/my-notes')
async def create(request: Request, body: dict = Body(...)):
    title = str(body.get('title') or '').strip() or 'Untitled'
    category = str(body.get('category') or '')

    def write(db):
        p = my_notes.create_note(db.notes_dir, title, category)
        db.reindex_notes()
        return p
    p = await request.app.state.writer.run(write)
    _changed(request, p.name)
    meta, b = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    return _out(p, meta, b)


@router.post('/api/my-notes/voice')
async def voice_note(request: Request, file: str = '', title: str = '', category: str = ''):
    """Raw audio body -> transcription -> text added to note `file`, or to a new note when `file` is empty."""
    global _voice_busy
    if not entitlements.feature_enabled('voice_notes'):
        raise HTTPException(403, 'Voice notes are not part of this plan.')
    if not config.openai_api_key():
        raise HTTPException(400, 'Voice notes need an OpenAI key. Open Settings > API keys to enter it.')
    target = _note(request, file) if file else None
    if int(request.headers.get('content-length') or 0) > MAX_VOICE_BYTES:
        raise HTTPException(413, 'That recording is too large (100 MB at most).')
    if _voice_busy:
        raise HTTPException(409, 'A voice note is already being transcribed.')
    _voice_busy = True
    work = Path(tempfile.mkdtemp(prefix='cm-voice-'))
    try:
        src = work / 'voice.audio'
        size = 0
        with open(src, 'wb') as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_VOICE_BYTES:
                    raise HTTPException(413, 'That recording is too large (100 MB at most).')
                f.write(chunk)
        if not size:
            raise HTTPException(400, 'No audio received.')
        try:
            text = await asyncio.to_thread(voice.transcribe_upload, src, work)
        except voice.VoiceError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f'Transcription failed: {e}')
        if not text:
            raise HTTPException(400, 'No speech was heard in that recording.')

        def write(db):
            p = target
            if p is None:
                name = title.strip() or f'Voice note {datetime.now():%Y-%m-%d %H:%M}'
                p = my_notes.create_note(db.notes_dir, name, category)
            meta = my_notes.add_voice(p, text)
            db.reindex_notes()
            return p, meta
        p, meta = await request.app.state.writer.run(write)
    finally:
        _voice_busy = False
        shutil.rmtree(work, ignore_errors=True)
    _changed(request, p.name)
    return {**_out(p, meta), 'text': text}


@router.put('/api/my-notes/{file}')
async def save(file: str, request: Request, body: dict = Body(...)):
    p = _note(request, file)

    def write(db):
        stamps = body.get('stamps') if isinstance(body.get('stamps'), list) else None   # absent: kept
        meta = my_notes.save_note(p, str(body.get('title') or ''), str(body.get('category') or ''), str(body.get('body') or ''), stamps)
        db.reindex_notes()
        return meta
    meta = await request.app.state.writer.run(write)
    _changed(request, p.name)
    return _out(p, meta)


@router.delete('/api/my-notes/{file}')
async def delete(file: str, request: Request):
    p = _note(request, file)

    def write(db):
        knowledge.delete_note(p)
        db.reindex_notes()
    await request.app.state.writer.run(write)
    _changed(request, p.name)
    return {'ok': True}


def _start(request: Request, kind: str, opts: dict):
    try:
        return request.app.state.jobs.start(kind, [0], True, opts)
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except JobError as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/my-notes/{file}/summarize')
def summarize(file: str, request: Request):
    _note(request, file)
    return _start(request, 'summarize', {'file': file})


@router.post('/api/my-notes/{file}/reformat')
def reformat(file: str, request: Request):
    _note(request, file)
    return _start(request, 'reformat', {'file': file})


@router.post('/api/my-notes/{file}/digest')
def digest(file: str, request: Request, body: dict = Body(...)):
    _note(request, file)
    images = [i for i in body.get('images') or [] if isinstance(i, dict) and i.get('data')]
    if not images:
        raise HTTPException(400, 'Pick one or more screenshots.')
    if sum(len(i['data']) for i in images) > MAX_DIGEST_BYTES:
        raise HTTPException(413, 'Those screenshots are too large together (30 MB at most).')
    return _start(request, 'digest', {'file': file, 'images': [
        {'name': str(i.get('name') or 'screenshot'), 'type': str(i.get('type') or 'image/png'), 'data': str(i['data'])}
        for i in images]})
