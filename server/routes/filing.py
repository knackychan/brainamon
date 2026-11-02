"""Filing what was dropped on Wiskit (projects/wiskit-files): suggestions, filing into a note, the
screenshot digest as text, and reading a file without keeping it (the phone through the PC).

POST /api/filing/suggest {id}                                 -> {name, chars, options: [...], ai}
POST /api/filing/file    {id | name + text, action, file?, title?} -> {file, title, personal}
POST /api/filing/digest  {ids: [...]} | {images: [{name, type, data}]} -> {text, failed}
POST /api/filing/read?name=&how=digest|describe  raw bytes    -> {name, kind, text}

`id` is an Ask attachment id (POST /api/ask/attach: a data/inbox file name or video:<folder>).
AI calls and PDF reading run in the thread pool (reads through store.reader()); every note write
runs on the Writer, then an SSE notes_changed. Nothing here is a background job.
"""
import base64
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core import ai_client
from core import ai_defaults
from core import config
from knowledge import attachments
from knowledge import filing
from knowledge import knowledge
from knowledge import my_notes
from knowledge import tasks
from server.routes.knowledge import _topic_note_files
from server.store import reader

router = APIRouter()
MAX_DIGEST_BYTES = 30 * 1024 * 1024        # = server/routes/my_notes.py
# the vision providers that need a key in .env (Add to Brainamon shows the plain reason, plans/09-add-to-brainamon.md)
KEY_NAMES = {ai_client.ASK_PROVIDER_ANTHROPIC: 'Anthropic', ai_client.ASK_PROVIDER_OPENAI: 'OpenAI'}


def _notes(app):
    return app.state.data_dir / 'notes'


def _resolve(app, aid: str):
    try:
        return attachments.resolve(app.state.data_dir, aid)
    except attachments.Gone as e:
        raise HTTPException(404, str(e))


@router.post('/api/filing/suggest')
async def suggest(request: Request, body: dict = Body(...)):
    app = request.app
    name, text = _resolve(app, str(body.get('id') or ''))

    def work():
        rd = reader(app.state.db_path)
        cands = filing.candidates(rd, _notes(app), name, text, _topic_note_files(rd))
        provider, _model = ai_defaults.get(rd, ai_defaults.SUMMARIZE)
        sug = filing.suggest(name, text, cands, provider, ai_client.cheap_model(provider))
        return {'name': name, 'chars': len(text), 'options': filing.options(sug, cands), 'ai': sug['ai']}
    return await run_in_threadpool(work)


@router.post('/api/filing/file')
async def file_it(request: Request, body: dict = Body(...)):
    app = request.app
    action = str(body.get('action') or '')
    if action not in filing.ACTIONS:
        raise HTTPException(400, 'Pick what to do with it.')
    aid = str(body.get('id') or '')
    if aid:
        name, text = _resolve(app, aid)
        source = '' if aid.startswith(attachments.VIDEO_PREFIX) else f'\n\nSource file: `data/inbox/{aid}`'
    else:
        name, text, source = str(body.get('name') or 'Pasted text').strip()[:80], str(body.get('text') or ''), ''
    if not text.strip():
        raise HTTPException(400, 'Nothing to file.')
    file = str(body.get('file') or '')
    if action != 'new':
        p = knowledge.safe_note_path(_notes(app), file)
        if p is None:
            raise HTTPException(404, 'That note is gone.')
        if file in _topic_note_files(reader(app.state.db_path)):
            raise HTTPException(400, 'Refresh digest rewrites topic notes. Pick another note.')
        if action == 'extend':
            meta, note_body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))

            def work():
                provider, model = ai_defaults.get(reader(app.state.db_path), ai_defaults.SYNTHESIZE)
                return filing.extend_section(meta.get('topic') or p.stem, note_body, name, text, provider, model)
            try:
                text = await run_in_threadpool(work)
            except Exception as exc:
                raise HTTPException(400, f'Wiskit could not write the section: {str(exc)[:200]}')
    title = str(body.get('title') or '')
    try:
        p = await app.state.writer.run(lambda db: filing.file_text(db, action, name, text + source, file, title))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    meta, _body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    personal = meta.get('kind') == 'personal'
    app.state.hub.publish('notes_changed', {'file': p.name, 'personal': personal})
    return {'file': p.name, 'title': meta.get('topic') or p.stem, 'personal': personal}


@router.post('/api/filing/digest')
async def digest(request: Request, body: dict = Body(...)):
    """Pictures transcribed verbatim (tasks.DIGEST_PROMPT, the Describe model), one call each, in
    order. The text comes back for the user to place: a note, a new note, or the clipboard."""
    app = request.app
    images = []
    for aid in body.get('ids') or []:
        try:
            images.append(attachments.image_bytes(app.state.data_dir, str(aid)))
        except attachments.Gone as e:
            raise HTTPException(404, str(e))
        except attachments.Unsupported as e:
            raise HTTPException(415, str(e))
    for i in body.get('images') or []:
        if isinstance(i, dict) and i.get('data'):
            images.append((str(i.get('name') or 'screenshot'), str(i.get('type') or 'image/png'), str(i['data'])))
    if not images:
        raise HTTPException(400, 'Pick one or more screenshots.')
    if sum(len(d) for _n, _t, d in images) > MAX_DIGEST_BYTES:
        raise HTTPException(413, 'Those screenshots are too large together (30 MB at most).')

    def work():
        provider, model = ai_defaults.get(reader(app.state.db_path), ai_defaults.DESCRIBE)
        parts, failed = [], 0
        for name, media_type, data in images:
            try:
                parts.append((name, tasks.transcribe_screenshot(media_type, data, provider, model)))
            except Exception as exc:
                failed += 1
                parts.append((name, f'[transcription failed: {str(exc)[:200]}]'))
        return parts, failed
    parts, failed = await run_in_threadpool(work)
    if failed == len(parts):
        raise HTTPException(400, f'All {failed} screenshot(s) failed to transcribe. {parts[0][1]}')
    return {'text': my_notes.combine_digest(parts), 'failed': failed}


@router.post('/api/filing/read')
async def read(request: Request, name: str = '', how: str = 'digest'):
    """The phone's "Add a picture or file" through the PC: raw bytes in, text out, nothing kept.
    A picture is transcribed (how=digest) or described (how=describe); PDF and text files ignore `how`."""
    app = request.app
    try:
        kind = attachments.kind_of(name)
    except attachments.Unsupported as e:
        raise HTTPException(415, str(e))
    raw = await request.body()
    if not raw:
        raise HTTPException(400, 'The file is empty.')
    if kind == 'text':
        return {'name': name, 'kind': kind, 'text': raw.decode('utf-8', errors='replace')}
    if kind == 'pdf':
        if len(raw) > attachments.MAX_PDF_BYTES:
            raise HTTPException(413, 'That PDF is over 30 MB.')
        try:
            text = await run_in_threadpool(attachments.pdf_text, raw)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {'name': name, 'kind': kind, 'text': text}
    if len(raw) > attachments.MAX_IMAGE_BYTES:
        raise HTTPException(413, 'That picture is over 10 MB.')
    media, b64 = attachments.MEDIA[Path(name).suffix.lower()], base64.b64encode(raw).decode('ascii')
    provider, model = ai_defaults.get(reader(app.state.db_path), ai_defaults.DESCRIBE)
    if provider in KEY_NAMES and not config.key_for_provider(provider):
        raise HTTPException(400, f'Reading a picture needs an {KEY_NAMES[provider]} key on the PC (Settings > API keys). Type the text instead.')

    def work():
        fn = tasks.transcribe_screenshot if how == 'digest' else tasks.describe_attachment
        return fn(media, b64, provider, model)
    try:
        text = await run_in_threadpool(work)
    except Exception as exc:
        raise HTTPException(400, f'Wiskit could not read the picture: {str(exc)[:200]}')
    return {'name': name, 'kind': 'image', 'text': text}
