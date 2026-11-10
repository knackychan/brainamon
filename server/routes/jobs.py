"""Job endpoints: snapshot, preview (for the confirm window), start, pause, resume, stop,
per-item progress (the Analysis progress window) and the console backlog."""
from fastapi import APIRouter, Body, HTTPException, Request

from core import app_console
from server.jobs import Busy, JobError

router = APIRouter()


def _jm(request: Request):
    return request.app.state.jobs


def _args(body: dict):
    kind = str(body.get('kind') or '')
    ids = [int(i) for i in body.get('ids') or []]
    return kind, ids, bool(body.get('force')), dict(body.get('opts') or {})


@router.get('/api/jobs')
def jobs(request: Request):
    return _jm(request).snapshot()


@router.get('/api/jobs/progress')
def progress(request: Request):
    return _jm(request).progress()


@router.post('/api/jobs/preview')
def preview(request: Request, body: dict = Body(...)):
    kind, ids, force, opts = _args(body)
    try:
        return _jm(request).preview(kind, ids, force, opts)
    except JobError as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/jobs')
def start(request: Request, body: dict = Body(...)):
    kind, ids, force, opts = _args(body)
    try:
        return _jm(request).start(kind, ids, force, opts)
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except JobError as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/jobs/request')
def ask(request: Request, body: dict = Body(...)):
    """A job asked for from outside the app (the local MCP): waits for a click in the app."""
    try:
        return _jm(request).ask(str(body.get('kind') or ''), [int(i) for i in body.get('ids') or []],
                                str(body.get('source') or 'Claude Code'))
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except (JobError, ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/jobs/request/{req_id}/{answer}')
def answer_request(req_id: int, answer: str, request: Request):
    if answer not in ('approve', 'decline'):
        raise HTTPException(404, 'answer is approve or decline')
    try:
        return _jm(request).answer(req_id, answer == 'approve')
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except JobError as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/notes/request')
def ask_note(request: Request, body: dict = Body(...)):
    """A note asked for from outside the app (the local MCP save_note): written only on a click in the app.
    Answered by /api/jobs/request/{id}/{approve|decline}, the same slot as a job request."""
    try:
        return _jm(request).ask_note(str(body.get('topic') or ''), str(body.get('body') or ''),
                                     [int(i) for i in body.get('sources') or []],
                                     str(body.get('source') or 'Claude Code'),
                                     file=str(body.get('file') or ''), category=str(body.get('category') or ''),
                                     stamps=body.get('stamps') if isinstance(body.get('stamps'), list) else None)
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except (JobError, ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/items/category/request')
def ask_category(request: Request, body: dict = Body(...)):
    """A re-categorize asked for from outside the app (the local MCP set_category): applied only on a click in the
    app. Answered by /api/jobs/request/{id}/{approve|decline}, the same slot as a job request."""
    try:
        return _jm(request).ask_category([int(i) for i in body.get('ids') or []], str(body.get('category') or ''),
                                         str(body.get('source') or 'Claude Code'))
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except (JobError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/items/categories/request')
def ask_categories(request: Request, body: dict = Body(...)):
    """A multi-category batch, applied atomically only after one approval in the app."""
    try:
        return _jm(request).ask_categories(body.get('groups'), str(body.get('source') or 'Claude Code'))
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except (JobError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/canvases/request')
def ask_canvas(request: Request, body: dict = Body(...)):
    """A canvas proposal (the local MCP set_canvas, projects/wiskit-canvas/PLAN.md): written only on a click in
    the app, never by auto-approve. Answered by /api/jobs/request/{id}/{approve|decline}."""
    try:
        return _jm(request).ask_canvas(body.get('proposal'), str(body.get('source') or 'Claude Code'))
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except (JobError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/jobs/pause')
def pause(request: Request):
    return _jm(request).pause()


@router.post('/api/jobs/resume')
def resume(request: Request):
    return _jm(request).resume()


@router.post('/api/jobs/stop')
def stop(request: Request, body: dict = Body(default={})):
    """Stop the running job. Optional {id}: stop only that job (a refused id changes nothing); no body as before."""
    job_id = body.get('id') if isinstance(body, dict) else None
    if job_id is not None and (type(job_id) is not int or job_id < 1):
        raise HTTPException(400, 'id must be a positive whole number.')
    try:
        return _jm(request).stop(job_id)
    except JobError as exc:
        raise HTTPException(400, str(exc))


@router.post('/api/items/{item_id}/download')
def download(item_id: int, request: Request, body: dict = Body(default={})):
    """One item's yt-dlp run (video, or the thumbnail only) as a one-item job: it respects the
    one-job rule and streams its lines as SSE `ytdlp` events."""
    try:
        return _jm(request).start('download', [item_id], True, {'thumbnail_only': bool(body.get('thumbnail_only'))})
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except JobError as exc:
        raise HTTPException(400, str(exc))


@router.get('/api/console')
def console():
    return app_console.entries()
