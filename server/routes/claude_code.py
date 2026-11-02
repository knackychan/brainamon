"""Settings > Claude Code: Wiskit's third Ask mode (knowledge/claude_code.py,
projects/milestone-2026-10-14/claude-code-engine/PLAN.md). DB settings claude_code_path, claude_code_enabled,
claude_code_model; nothing in .env. The page applies each change at once (no Save). The installed build runs the
bundled MCP server (Brainamon.exe --mcp); a build without mcp_local answers 404 (claude_code.available)."""
import shutil

from fastapi import APIRouter, Body, HTTPException, Request

from core import ai_client
from knowledge import claude_code
from server.jobs import AUTO_APPROVE_KEY
from server.store import reader

router = APIRouter()
MODEL_IDS = {m for m, _ in ai_client.CLAUDE_CODE_MODELS}


def _view(get) -> dict:
    on = claude_code.available()
    return {'available': on, 'path': get(claude_code.PATH_KEY, ''), 'detected': claude_code.detect() if on else '',
            'enabled': get(claude_code.ENABLED_KEY, '') == '1', 'model': claude_code.model_setting(get),
            'auto_approve': get(AUTO_APPROVE_KEY, '0') == '1', 'winget': bool(shutil.which('winget')),
            'models': [{'id': m, 'label': label} for m, label in ai_client.CLAUDE_CODE_MODELS]}


def _need():
    if not claude_code.available():
        raise HTTPException(404, claude_code.NOT_IN_BUILD)


@router.get('/api/claude-code')
def get_claude_code(request: Request):
    return _view(reader(request.app.state.db_path).get_setting)


@router.post('/api/claude-code/test')
def test_claude_code(request: Request, body: dict = Body(...)):
    """{"path"}: claude --version and claude auth status (no model call). A path that passes is saved."""
    _need()
    path = str(body.get('path') or '').strip()
    result = claude_code.check(path)

    def write(db):
        if result['ok']:
            db.set_setting(claude_code.PATH_KEY, path)
        return _view(db.get_setting)
    return {**request.app.state.writer.call(write), 'test': result}


@router.post('/api/claude-code/login')
def login_claude_code(request: Request, body: dict = Body(...)):
    """{"path"}: open a console window with `claude auth login` (the CLI's own sign-in). Then press Test."""
    _need()
    path = str(body.get('path') or '').strip()
    try:
        claude_code.open_login(path)
    except (claude_code.Failed, OSError) as exc:
        raise HTTPException(400, str(exc) or 'Claude Code did not start.')
    return {'ok': True}


@router.put('/api/claude-code')
def put_claude_code(request: Request, body: dict = Body(...)):
    """{"enabled"?, "model"?, "auto_approve"?}. auto_approve: a note or job Claude Code asks for runs at once, with
    no click (DB setting `claude_auto_approve`, server/jobs.py). Turning it on tests the saved path again: it must be found and logged in."""
    _need()
    updates = {}
    if 'model' in body:
        model = str(body.get('model') or '')
        if model not in MODEL_IDS:
            raise HTTPException(400, 'Unknown Claude Code model.')
        updates[claude_code.MODEL_KEY] = model
    if 'enabled' in body:
        on = bool(body.get('enabled'))
        if on:
            result = claude_code.check(reader(request.app.state.db_path).get_setting(claude_code.PATH_KEY, ''))
            if not result['ok']:
                raise HTTPException(400, result['message'])
        updates[claude_code.ENABLED_KEY] = '1' if on else ''
    if 'auto_approve' in body:
        updates[AUTO_APPROVE_KEY] = '1' if body.get('auto_approve') else '0'

    def write(db):
        for k, v in updates.items():
            db.set_setting(k, v)
        return _view(db.get_setting)
    return request.app.state.writer.call(write)
