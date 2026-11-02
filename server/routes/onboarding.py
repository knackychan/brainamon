"""First run, desktop side (docs/superpowers/specs/2026-10-25-newstart-ui-redo-design.md): the one
welcome question and the rail's Get started checklist. The phone keeps its own copy (kv 'onboard').

GET /api/onboarding  -> answer, hidden, welcome, items, notes, wiskit, step, skipped
PUT /api/onboarding  {"answer"?, "hidden"?, "step"?, "skipped"?}: the welcome's answer (one of ANSWERS) and the checklist's
                     Hide (DB settings `onboard_answer`, `onboard_hidden`); answers with the same view

`welcome` is true only for a new library: no answer yet, no item, and the first-run checklist of
earlier versions not dismissed; an older library with items, or one whose checklist was finished,
never sees it. `notes` counts personal notes only while there is no item (the checklist's second
task is done either way).
`wiskit`: the Wiskit provider has its key (ask_core.provider_problem says nothing).
"""
import json

from fastapi import APIRouter, Body, HTTPException, Request

from core import ai_defaults
from knowledge import ask_core, my_notes
from server.store import reader

router = APIRouter()

# the welcome's answers; web/src/lib/onboarding.ts ANSWERS lists the same ids, without 'skip'
ANSWERS = ('instagram', 'facebook', 'reddit', 'youtube', 'links', 'files', 'skip')
STEPS = ('library', 'tools', 'content', 'ai', 'drive', 'phone')
ANSWER_KEY = 'onboard_answer'
HIDDEN_KEY = 'onboard_hidden'
SETUP_KEY = 'setup_dismissed'          # server/routes/app.py: the first-run checklist of earlier versions


def view(db) -> dict:
    answer = db.get_setting(ANSWER_KEY, '')
    answer = answer if answer in ANSWERS else ''
    items = db.count_items()
    hidden = db.get_setting(HIDDEN_KEY, '0') == '1' or db.get_setting(SETUP_KEY, '0') == '1'
    provider, _model = ai_defaults.get(db, ai_defaults.DESCRIBE)
    step = db.get_setting('onboard_step', 'library')
    try:
        skipped = json.loads(db.get_setting('onboard_skipped', '[]'))
    except ValueError:
        skipped = []
    if not isinstance(skipped, list) or len(skipped) > len(STEPS) or any(not isinstance(s, str) or s not in STEPS for s in skipped):
        skipped = []
    return {
        'answer': answer,
        'hidden': hidden,
        'welcome': not answer and not items and not hidden,
        'items': items,
        'notes': 0 if items else len(my_notes.personal_notes(db.notes_dir)),
        'wiskit': ask_core.provider_problem(provider) == '',
        'step': step if step in (*STEPS, 'summary') else 'library',
        'skipped': list(dict.fromkeys(skipped)),
    }


@router.get('/api/onboarding')
def get_onboarding(request: Request):
    return view(reader(request.app.state.db_path))


@router.put('/api/onboarding')
async def put_onboarding(request: Request, body: dict = Body(...)):
    answer, hidden = body.get('answer'), body.get('hidden')
    if answer is not None and answer not in ANSWERS:
        raise HTTPException(400, 'Unknown answer.')
    if hidden is not None and not isinstance(hidden, bool):
        raise HTTPException(400, 'Hidden must be true or false.')
    if 'step' in body and (not isinstance(body['step'], str) or body['step'] not in (*STEPS, 'summary')):
        raise HTTPException(400, 'Unknown setup step.')
    if 'skipped' in body:
        skipped = body['skipped']
        if (not isinstance(skipped, list) or len(skipped) > len(STEPS)
                or any(not isinstance(s, str) or s not in STEPS for s in skipped) or len(set(skipped)) != len(skipped)):
            raise HTTPException(400, 'Skipped steps must be a unique list of setup step IDs.')

    def write(db):
        if answer is not None:
            db.set_setting(ANSWER_KEY, answer)
        if hidden is not None:
            db.set_setting(HIDDEN_KEY, '1' if hidden else '0')
        if 'step' in body:
            db.set_setting('onboard_step', body['step'])
        if 'skipped' in body:
            db.set_setting('onboard_skipped', json.dumps(body['skipped']))
        return view(db)
    return await request.app.state.writer.run(write)
