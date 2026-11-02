"""Wiskit: Ask my library (Quick and Deep), the saved chats, Save as note.

POST /api/ask answers with an SSE stream read by fetch (EventSource is GET-only). Events:
  start    {run}              the answer's id, for POST /api/ask/stop
  context  {line, ids}        the retrieval line ("Sent N items + notes · mode") and the sent ids
  progress {line}             Deep-mode tool calls and notices
  chunk    {text}             a visible answer-text delta
  done     {text, cited, notes, sources, chat}
  stopped  {}                 the client pressed Stop (nothing saved)
  error    {message}
  reset    {}                 clear the text so far (it led into a tool call)

A page that goes away (the main window closed by sleep mode, desktop/sleep.py) does not stop the answer:
it finishes, is saved to its chat, and an `ask_saved` {run, slug, name, detached} event on /api/events
tells a reopened page. Only POST /api/ask/stop {run} (the Stop button) ends it early. An `ask_run` {running}
event on /api/events counts the running answers when one starts and ends (Wiskit's dot, desktop/activity.py).

Ask is not a background job (the Qt app lets Ask run during a batch). The answer runs on its own
thread: retrieval reads through a ReadOnlyDatabase opened and closed by that thread; the Deep
agent opens its own (ask_core.deep_answer, the documented exception); every write (chat files,
aux vectors, notes, the resources index) goes through the Writer. The prompts and retrieval are
ask_core.py, shared with the Qt app.

Claude Code mode (mode 'claude_code', knowledge/claude_code.py) runs the Claude Code CLI with only the Brainamon
MCP tools; it needs no API key, reads in the MCP server, and writes nothing itself (save_note / start_job are
requests Fred approves in the app).
"""
import asyncio
import base64
import json
import time
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from starlette.concurrency import run_in_threadpool

from core import ai_client
from core import ai_defaults
from core import app_console
from knowledge import ask_core
from knowledge import attachments
from knowledge import claude_code
from knowledge import tasks
from knowledge import weekly_review
from core import config
from knowledge import knowledge
from knowledge import librarian
from knowledge.ask_chats import AskChatStore, valid_slug
from server.jobs import Busy, JobError, category_groups
from core.db import ReadOnlyDatabase
from server.library import compact
from server.routes.library import embedded
from server.routes.smart import embed_index
from server.store import reader

router = APIRouter()

# A Stop received after the Writer has begun committing cannot undo the saved turn; this sentinel
# marks the commit-boundary cancellation decided inside the Writer closure.
_CANCELLED = object()


def _store(request_or_app) -> AskChatStore:
    app = getattr(request_or_app, 'app', request_or_app)
    st = getattr(app.state, 'chat_store', None)
    if st is None:
        st = app.state.chat_store = AskChatStore(app.state.data_dir)
    return st


# ── options ──────────────────────────────────────────────────────────────────
@router.get('/api/ask/options')
def options(request: Request):
    rd = reader(request.app.state.db_path)
    providers = ai_client.ask_provider_options()
    local = []
    if ai_client.ask_local_available():
        local = ai_client.ask_discover_local_models(config.local_openai_base_url(), config.local_openai_api_key())
    found = ai_defaults.found_models(rd)
    models = {p['id']: ai_client.ask_models(p['id'], local if p['id'] == ai_client.ASK_PROVIDER_LOCAL_OPENAI
                                            else found.get(p['id']))
              for p in providers}
    provider, model = ai_defaults.get(rd, ai_defaults.DESCRIBE)
    return {
        'providers': providers, 'models': models,
        'default_provider': provider,
        'default_models': {p['id']: model if p['id'] == provider else ai_client.ask_default_model(p['id']) for p in providers},
        'problems': {p['id']: ask_core.provider_problem(p['id']) for p in providers},
        'agent_providers': list(ai_client.ASK_AGENT_PROVIDERS),
        'depths': [10, 25, 50],
        'scopes': [c['name'] for c in rd.get_categories()],
        'claude_code': claude_code.ready(rd.get_setting),
    }


# ── attachments (projects/desktop-app plan 11) ───────────────────────────────
@router.post('/api/ask/attach')
async def attach(request: Request, name: str = ''):
    """?name=<file> with the raw bytes: a file copied to data/inbox (an image is described once).
    JSON {"text"}: text saved as data/inbox/<date>-pasted.txt. JSON {"analysis": <folder>}: a
    finished Video Tools analysis. -> {id, name, kind, chars}; the id goes in /api/ask attachments."""
    data_dir = request.app.state.data_dir
    raw = await request.body()

    def describe(media_type, img):
        try:
            provider, model = ai_defaults.get(reader(request.app.state.db_path), ai_defaults.DESCRIBE)
            return tasks.describe_attachment(media_type, base64.b64encode(img).decode('ascii'), provider, model)
        except Exception as exc:
            raise ValueError(f'Wiskit could not read the picture: {str(exc)[:200]}') from None

    try:
        if name:
            return await run_in_threadpool(attachments.save, data_dir, name, raw, describe)
        body = json.loads(raw or b'{}')
        if body.get('analysis'):
            return attachments.analysis(data_dir, str(body['analysis']))
        return attachments.save_text(data_dir, str(body.get('text') or ''))
    except attachments.Unsupported as e:
        raise HTTPException(415, str(e))
    except attachments.Gone as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post('/api/ask/panel')
def panel_attach(request: Request, body: dict = Body(...)):
    """An open drop panel picks up these attachment ids (server/desktop.py --panel --attach)."""
    ids = [str(i) for i in body.get('ids') or [] if i]
    request.app.state.hub.publish('panel_attach', {'ids': ids})
    return {'ok': True}


# ── the answer stream ────────────────────────────────────────────────────────
class _Run(threading.Event):
    """Stop owns only this run's response, independently of browser detachment."""
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.closer = None
        self.committing = False

    def register(self, closer):
        with self.lock:
            close_now = self.is_set()
            self.closer = None if close_now else closer
        if close_now and closer:
            closer()

    def set(self):
        with self.lock:
            super().set()
            closer, self.closer = self.closer, None
        if closer:
            try:
                closer()
            except Exception:
                pass  # the worker reports its provider outcome


def _runs(app) -> dict:
    """run id -> its stop Event, while the answer runs."""
    runs = getattr(app.state, 'ask_runs', None)
    if runs is None:
        runs = app.state.ask_runs = {}
    return runs


_runs_lock = threading.Lock()


def _track(app, run: str, stop=None) -> None:
    """Add a running answer (stop given) or drop it, then publish `ask_run` {running}: how many answers run
    now (Wiskit's dot while the window sleeps, desktop/activity.py). One lock keeps the counts in order."""
    with _runs_lock:
        runs = _runs(app)
        if stop is None:
            runs.pop(run, None)
        else:
            runs[run] = stop
        app.state.hub.publish('ask_run', {'running': len(runs)})


@router.post('/api/ask/stop')
def stop_ask(request: Request, body: dict = Body(...)):
    ev = _runs(request.app).get(str(body.get('run') or ''))
    if ev is not None:
        ev.set()            # the answer loop ends at its next step and sends `stopped` (nothing saved)
    return {'ok': ev is not None}


@router.post('/api/ask', response_class=EventSourceResponse)
async def ask(request: Request, body: dict = Body(...)):
    question = str(body.get('question') or '').strip()
    if not question:
        yield ServerSentEvent(data={'message': 'Type a question first.'}, event='error')
        return
    app = request.app
    task = body.get('task')
    review = None
    if task not in (None, '', 'weekly_review'):
        yield ServerSentEvent(data={'message': 'Unknown task.'}, event='error')
        return
    if task == 'weekly_review':
        try:
            review = weekly_review.validate_request(body, now=datetime.now(timezone.utc))
        except ValueError as exc:
            yield ServerSentEvent(data={'message': str(exc)}, event='error')
            return
    try:
        resolved = [attachments.resolve(app.state.data_dir, a) for a in body.get('attachments') or []]
    except attachments.Gone as e:
        yield ServerSentEvent(data={'message': str(e)}, event='error')
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop, gone = _Run(), threading.Event()
    run = uuid.uuid4().hex[:12]
    _track(app, run, stop)

    def put(kind, data):
        if gone.is_set():
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, data))
        except RuntimeError:            # the server is shutting down
            pass

    def work():
        try:
            _answer(app, body, question, put, stop, resolved, run, gone, review=review)
        except Exception as exc:
            if stop.is_set() and not stop.committing:
                put('stopped', {})
            else:
                app_console.emit('error', 'Ask failed', level='error', error=exc)
                put('error', {'message': str(exc)[:300]})
        finally:
            _track(app, run)
            put(None, None)

    threading.Thread(target=work, name='cm-ask', daemon=True).start()
    yield ServerSentEvent(data={'run': run}, event='start')
    try:
        while True:
            kind, data = await queue.get()
            if kind is None:
                break
            yield ServerSentEvent(data=data, event=kind)
    finally:
        gone.set()          # the page went away: the answer still finishes and is saved (Stop is POST /api/ask/stop)


def _answer(app, body, question, put, stop, resolved=(), run='', gone=None, review=None):
    writer = app.state.writer
    store = _store(app)
    slug = str(body.get('chat') or '')
    chat = store.load(slug) if slug else None
    if chat is None:
        slug, chat = writer.call(lambda db: _new_chat(db, store, 'New chat'))
    history = list(chat.get('history') or [])
    # Persisted assistant turns may carry review metadata; never leak it into provider messages.
    provider_history = [{'role': t.get('role'), 'content': t.get('content')} for t in history]
    turn_history = provider_history + attachments.history_pair(resolved, attachments.MAX_CHARS)
    default_provider, default_model = writer.read(lambda db: ai_defaults.get(db, ai_defaults.DESCRIBE))
    saved = chat.get('options') or {}
    provider = str(body.get('provider') or saved.get('provider') or default_provider)
    saved_model = saved.get('model_id') if provider == saved.get('provider') else None
    model_id = ai_client.current_model(str(body.get('model') or saved_model or
                                         (default_model if provider == default_provider else ai_client.ask_default_model(provider))))
    depth = int(body.get('depth') or ask_core.DEPTH_DEFAULT)
    scope = str(body.get('scope') or '')
    deep = body.get('mode') == 'deep'
    cc = body.get('mode') == 'claude_code'      # Claude Code mode needs no API key (knowledge/claude_code.py)
    cc_session = ''

    if review is not None and cc:
        put('error', {'message': 'Choose an API model to review this week.'})
        return
    err, local_base_url, local_api_key = (None, None, None) if cc else ask_core.provider_ready(provider, model_id)
    if err:
        put('error', {'message': err})
        return

    rd = ReadOnlyDatabase(app.state.db_path)
    try:
        if review is not None:
            text, rows, list_mode = _weekly(rd, review, provider, model_id, local_base_url, local_api_key, put, stop)
        elif cc:
            err = claude_code.problem(rd.get_setting)
            if err:
                put('error', {'message': err})
                return
            text, rows, list_mode, cc_session = _claude(app, rd, chat, provider_history, question, resolved, put, stop)
        else:
            embed_key, embed_base = ai_defaults.embed_credentials(rd)
            if deep and provider not in ai_client.ASK_AGENT_PROVIDERS:
                put('progress', {'line': 'Deep mode needs the Anthropic or OpenAI provider; answering in fast mode.'})
                deep = False
            if deep:
                text, rows, list_mode = _deep(app, rd, provider, model_id, turn_history, question,
                                              embed_key, embed_base, put, stop)
            else:
                text, rows, list_mode = _quick(app, rd, provider, model_id, turn_history, question, depth, scope,
                                               embed_key, embed_base, local_base_url, local_api_key, put, stop)
        if text is None:
            put('stopped', {})
            return
        rows = ask_core.answer_sources(rows, text, list_mode)
        emb = embedded(rd)
        sources = [compact(r, emb) for r in rows]
    finally:
        rd.close()

    if stop.is_set():
        put('stopped', {})
        return

    # persist the turn (the Qt _ask_on_answer + _ask_save_current_chat + _ask_auto_name_if_needed)
    def save(db):
        if stop.is_set():
            return _CANCELLED
        stop.committing = True
        current = store.load(slug) or {}
        data = dict(current)
        assistant_turn = {'role': 'assistant', 'content': text}
        if review is not None:
            assistant_turn['review'] = review
        data['history'] = (history + attachments.history_pair(resolved, attachments.HISTORY_CHARS)
                           + [{'role': 'user', 'content': question}, assistant_turn])
        data['source_ids'] = [r['id'] for r in rows]
        if cc:
            data['claude_session'] = cc_session
        data['options'] = {'provider': provider, 'model_id': model_id,
                           'model_label': ai_client.ask_model_label(provider, model_id),
                           'depth': depth, 'scope': scope}
        store.save(slug, data)
        new_slug, name = slug, data.get('name') or 'New chat'
        if not history and name == 'New chat':
            nm = ask_core.auto_name(question)
            if nm:
                new_slug, _ = store.rename(slug, nm)
                name = nm
        db.set_setting('ask_active_chat', new_slug)
        return new_slug, name

    result = writer.call(save)
    if result is _CANCELLED:
        put('stopped', {})
        return
    new_slug, name = result
    detached = gone is not None and gone.is_set()
    if detached:
        app_console.emit('log', f'Wiskit finished an answer after its window closed: saved to "{name}"')
    app.state.hub.publish('ask_saved', {'run': run, 'slug': new_slug, 'name': name, 'detached': detached})
    source_ids = {r['id'] for r in rows}
    note_sources = getattr(stop, 'note_sources', None)
    done = {'text': text, 'cited': [i for i in ask_core.cited_ids(text) if i in source_ids],
            'notes': [f for f in ask_core.cited_notes(text) if note_sources is None or f in note_sources],
            'sources': sources, 'chat': {'slug': new_slug, 'name': name}}
    if review is not None:
        done['review'] = review
    put('done', done)


def _quick(app, rd, provider, model_id, history, question, depth, scope, embed_key, embed_base,
           local_base_url, local_api_key, put, stop):
    budget = librarian.PROMPTS['agent_budgets']['quick']
    deadline = time.monotonic() + budget['research_seconds']
    depth = ask_core.effective_depth(question, depth)
    index = embed_index(app, rd) if embed_key else None
    if embed_key and index is not None and len(index):
        try:
            vec = ai_client.embed_texts([question], api_key=embed_key, base_url=embed_base)[0]
            rows, retrieval = ask_core.rank_rows(rd, question, depth, scope, index, vec), 'keyword + semantic search'
        except Exception as exc:
            rows = ask_core.fallback_rows(rd, question, depth, scope)
            retrieval = ask_core.fallback_label(f'embedding failed: {str(exc)[:120]}')
    else:
        reason = 'no embeddings API key' if not embed_key else 'no items indexed - run "Index for search"'
        rows, retrieval = ask_core.fallback_rows(rd, question, depth, scope), ask_core.fallback_label(reason)
    turn = ask_core.build_turn(rd, question, rows, history, retrieval,
                               budget=budget if provider in ai_client.ASK_AGENT_PROVIDERS else None)
    put('context', {'line': turn['info'], 'ids': [r['id'] for r in turn['sources']], 'list': turn['list_mode']})
    if provider in ai_client.ASK_AGENT_PROVIDERS:
        return _deep(app, rd, provider, model_id, history, question, embed_key, embed_base,
                     put, stop, mode='quick', starting_turn=turn, research_deadline=deadline)
    parts = []
    system = ask_core.SYSTEM + '\n\n' + ask_core.P['category_unavailable'] + '\n\n' + ask_core.P['canvas_unavailable']
    tool_opts = {}
    gen = ai_client.ask_chat_stream(
        turn['messages'], provider, model_id, system_prompt=system,
        local_base_url=local_base_url, local_api_key=local_api_key, max_tokens=turn['max_tokens'], **tool_opts)
    try:
        for delta in gen:
            if stop.is_set():
                return None, [], False
            parts.append(delta)
            put('chunk', {'text': delta})
    except RuntimeError:
        if stop.is_set():
            return None, [], False
        raise
    finally:
        close = getattr(gen, 'close', None)
        if close:
            close()
    if stop.is_set():
        return None, [], False
    return ''.join(parts).strip(), turn['sources'], turn['list_mode']


def _weekly(rd, review, provider, model_id, local_base_url, local_api_key, put, stop):
    """The on-demand weekly review: deterministic date selection, one bounded stream, then output
    validation and the deterministic title/Coverage. Returns (text, rows, False); text None on Stop."""
    if stop.is_set():
        return None, [], False
    bundle = weekly_review.collect(rd, rd.notes_dir, review, should_stop=stop.is_set)
    if bundle is None:
        return None, [], False
    items_incl = bundle['coverage']['items']['included']
    notes_incl = bundle['coverage']['notes']['included']
    omitted = bundle['coverage']['items']['omitted'] + bundle['coverage']['notes']['omitted']
    line = (f"Weekly review · {review['start']}–{review['end']} · {items_incl} items + "
            f"{notes_incl} notes · {omitted} omitted")
    put('context', {'line': line, 'ids': [it['id'] for it in bundle['items']], 'list': False})
    if not items_incl and not notes_incl:
        if stop.is_set():
            return None, [], False
        return weekly_review.compose_answer('', bundle), [], False

    turn = weekly_review.build_turn(bundle)
    parts = []
    total = 0
    gen = ai_client.ask_chat_stream(
        turn['messages'], provider, model_id, system_prompt=turn['system'],
        local_base_url=local_base_url, local_api_key=local_api_key, max_tokens=turn['max_tokens'])
    try:
        for delta in gen:
            if stop.is_set():
                return None, [], False
            parts.append(delta)
            total += len(delta)
            if total > weekly_review.L['max_output_chars']:
                raise ValueError('The review is too long.')
            put('chunk', {'text': delta})
    finally:
        close = getattr(gen, 'close', None)
        if close:
            close()
    if stop.is_set():
        return None, [], False
    body = weekly_review.validate_output(''.join(parts), bundle)
    text = weekly_review.compose_answer(body, bundle)
    return text, bundle['rows'], False


def _propose_reformat(app, file, instruction=''):
    """Deep tool propose_reformat: queue the reformat job for one personal note, with what the user asked
    for (`instruction`, plans/04-agents.md). Nothing is written: the job's persist only sends the preview,
    and the note changes when Fred clicks Apply."""
    p = knowledge.safe_note_path(app.state.data_dir / 'notes', file)
    if p is None:
        return f'Not queued: no note named {file!r}.'
    meta, _body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    if (meta.get('kind') or '') != 'personal':
        return f'Not queued: {p.name} is not one of the user\'s personal notes.'
    try:
        asked = ' '.join(str(instruction or '').split())[:500]
        app.state.jobs.start('reformat', [0], True, {'file': p.name, **({'instruction': asked} if asked else {})})
    except (Busy, JobError) as exc:
        return f'Not queued: {exc}'
    return (f'Queued a reformat proposal for {p.name}. Nothing is changed yet: the user sees it in '
            'My Notes and clicks Apply to save it.')


def _propose_category(app, ids, category):
    """Deep proposes through the existing CAT-02 request; only the user's click writes."""
    try:
        if not isinstance(ids, list) or any(type(i) is not int for i in ids):
            raise JobError('Give a list of integer item ids.')
        if not isinstance(category, str):
            raise JobError('Give an existing category name.')
        req = app.state.jobs.ask_category(ids, category, source='Wiskit', require_approval=True)
    except (Busy, JobError, ValueError, TypeError, OverflowError) as exc:
        return f'Error: category proposal not queued: {exc}'
    if req['state'] != 'pending':
        return (f"Category proposal #{req['id']} is {req['state']}: {req['category']}. "
                'The user has already resolved it. Re-read the items to verify their current categories.')
    return (f"Category proposal #{req['id']} is {req['state']}: {len(req['ids'])} item(s) to {req['category']}. "
            'Nothing has changed. Review and approve or decline it in Brainamon. '
            'Only one request can wait at a time; stop queuing and offer the next group on a later turn.')


def _propose_categories(app, groups):
    """One mixed-category proposal, sharing the same approval system across all Wiskit modes."""
    try:
        req = app.state.jobs.ask_categories(groups, source='Wiskit')
    except (Busy, JobError, ValueError, TypeError, OverflowError) as exc:
        return f'Error: category batch not queued: {exc}'
    n = len(req['ids'])
    return (f"Category batch #{req['id']} is {req['state']}: {n} item(s) across "
            f"{len({e['category'] for e in req['entries']})} categories. "
            'If pending, nothing has changed: review all assignments and click Apply batch in Brainamon once. '
            'The whole batch is queued; no separate approval per category is needed. '
            'Wait for this batch to be resolved before preparing another.')


def _propose_canvas(app, proposal):
    """A canvas proposal through the shared request slot (projects/wiskit-canvas/PLAN.md); only Fred's click writes."""
    try:
        req = app.state.jobs.ask_canvas(proposal, source='Wiskit')
    except (Busy, JobError, ValueError, TypeError, OverflowError) as exc:
        return f'Error: canvas proposal not queued: {exc}'
    t, c = req['preview']['target'], req['preview']['counts']
    made = (f"{c['thumbnail']} thumbnail(s), {c['frame']} frame(s), {c['text']} note(s) in {c['sections']} section(s)"
            + (f", moving {c['moves']} existing element(s)" if c['moves'] else ''))
    return (f"Canvas proposal #{req['id']} is {req['state']}: "
            f"{'a new canvas' if t['new'] else 'additions to the canvas'} \"{t['name']}\" with {made}. "
            'Nothing has been written: the user reviews it in Brainamon and clicks Apply or Decline. '
            'Only one request can wait at a time: do not queue another (a note, a category batch) in this answer; '
            'offer it for after the user answers.')


def _deep(app, rd, provider, model_id, history, question, embed_key, embed_base, put, stop, *,
          mode='deep', starting_turn=None, research_deadline=None):
    writer = app.state.writer
    if research_deadline is None:
        research_deadline = time.monotonic() + librarian.PROMPTS['agent_budgets'][mode]['research_seconds']
    if mode == 'deep' and not stop.is_set() and time.monotonic() < research_deadline:
        _refresh_resources(app, rd, put, stop=stop, deadline=research_deadline)
    setup = ask_core.deep_setup(rd, embed_key, embed_index(app, rd) if embed_key else None, mode=mode, should_stop=stop.is_set, research_deadline=research_deadline)
    if setup['obsolete']:
        writer.call(lambda db: db.delete_aux_embeddings(setup['obsolete']))
    for line in setup['infos']:
        put('progress', {'line': line})
    if not setup['profile']:
        put('progress', {'line': 'Tip: create a note titled "About me" in My Notes (goals, equipment, level, '
                                 'constraints) and Wiskit will tailor its answers to it.'})
    if not starting_turn:
        put('context', {'line': f'Deep mode · {ai_client.ask_model_label(provider, model_id)} is researching your library...',
                    'ids': [], 'list': False})
    hist = history[-(ask_core.HISTORY_TURNS * 2):]

    def save_aux(rows):
        if rows:
            writer.call(lambda db: db.upsert_aux_embeddings(ai_client.EMBEDDING_MODEL, rows))

    evidence = {}
    try:
        text, consulted = ask_core.deep_answer(
            app.state.db_path, provider, model_id, setup['system'], hist, question,
            item_index=setup['index'], aux_rows=setup['aux_rows'], aux_jobs=setup['jobs'],
            embed_key=embed_key, embed_base=embed_base,
            on_progress=lambda m: put('progress', {'line': m}), on_aux=save_aux, should_stop=stop.is_set,
            propose=lambda file, instruction='': _propose_reformat(app, file, instruction),
            propose_category=lambda ids, category: _propose_category(app, ids, category),
            propose_categories=lambda groups: _propose_categories(app, groups),
            propose_canvas=lambda proposal: _propose_canvas(app, proposal),
            mode=mode, starting_turn=starting_turn, research_deadline=research_deadline, evidence=evidence,
            on_text=lambda text: put('chunk', {'text': text}), on_reset=lambda: put('reset', {}),
            on_stream=getattr(stop, 'register', None))
    except RuntimeError:
        if stop.is_set():
            return None, [], False
        raise
    if stop.is_set():
        return None, [], False
    stop.note_sources = evidence.get('notes', set())
    text = text or ask_core.EMPTY_DEEP
    return text, ask_core.deep_sources(rd, text, consulted, validated=True), False


def _claude(app, rd, chat, history, question, resolved, put, stop):
    """Claude Code mode (knowledge/claude_code.py): the CLI answers through the Brainamon MCP tools. Reads happen
    in the MCP server; a note or a job is a request Fred approves in the app. -> (text, rows, list_mode, session);
    text None after Stop. claude_code.Failed reaches work(), which sends its message as the `error` event."""
    put('context', {'line': 'Claude Code · researching your library through the Brainamon tools...',
                    'ids': [], 'list': False})
    attached = attachments.history_pair(resolved, attachments.MAX_CHARS)
    text, session = claude_code.answer(
        rd.get_setting(claude_code.PATH_KEY, ''), question,
        session=str(chat.get('claude_session') or ''), history=history,
        attached=attached[0]['content'] if attached else '',
        model=claude_code.model_setting(rd.get_setting), system_text=claude_code.system_prompt(rd),
        data_dir=app.state.data_dir, port=app.state.port, on_event=put, should_stop=stop.is_set)
    if text is None:
        return None, [], False, ''
    return text, ask_core.deep_sources(rd, text, []), False, session


_resources_busy = threading.Lock()


def _refresh_resources(app, rd, put, *, stop=None, deadline=None):
    """Rebuild the websites/tools index in the background when items changed (Qt
    _ask_refresh_resources): file reads on a thread, rows persisted on the Writer."""
    sig = rd.items_signature()
    if rd.get_setting('resources_sig', '') == sig or not _resources_busy.acquire(blocking=False):
        return
    items, items_dir = rd.items_for_resources(), rd.items_dir

    def run():
        try:
            rows = librarian.resource_rows(items, items_dir,
                lambda: not (stop and stop.is_set()) and (deadline is None or time.monotonic() < deadline))

            def save(db):
                db.replace_resources([tuple(r) for r in rows])
                db.set_setting('resources_sig', sig)
            app.state.writer.call(save)
        except Exception as exc:
            app_console.emit('error', 'Resources index failed', level='error', error=exc)
        finally:
            _resources_busy.release()

    threading.Thread(target=run, name='cm-resources', daemon=True).start()
    put('progress', {'line': 'Indexing websites and tools mentioned in your library '
                             '(background; website answers improve once done).'})


# ── chats ────────────────────────────────────────────────────────────────────
@router.get('/api/chats')
def chats(request: Request):
    return {'chats': _store(request).list_chats(),
            'active': reader(request.app.state.db_path).get_setting('ask_active_chat', '')}


def _new_chat(db, store, name):
    provider, model = ai_defaults.get(db, ai_defaults.DESCRIBE)
    return store.create(name, options={'provider': provider, 'model_id': model})


@router.post('/api/chats')
async def create_chat(request: Request, body: dict = Body(default={})):
    store = _store(request)
    name = str(body.get('name') or 'New chat').strip() or 'New chat'

    def make(db):
        slug, data = _new_chat(db, store, name)
        db.set_setting('ask_active_chat', slug)
        return slug, data
    slug, data = await request.app.state.writer.run(make)
    return {'slug': slug, **data, 'sources': []}


@router.put('/api/chats/active')
async def set_active(request: Request, body: dict = Body(...)):
    slug = str(body.get('slug') or '')
    if slug and not valid_slug(slug):
        raise HTTPException(400, 'Not a chat name.')
    await request.app.state.writer.run(lambda db: db.set_setting('ask_active_chat', slug))
    return {'active': slug}


@router.get('/api/chats/{slug}')
def get_chat(slug: str, request: Request):
    data = _store(request).load(slug)
    if data is None:
        raise HTTPException(404, 'no such chat')
    rd = reader(request.app.state.db_path)
    emb = embedded(rd)
    return {'slug': slug, **data, 'sources': [compact(r, emb) for r in rd.get_items_by_ids(data.get('source_ids') or [])]}


@router.put('/api/chats/{slug}')
async def save_chat_options(slug: str, request: Request, body: dict = Body(...)):
    store = _store(request)

    def save(db):
        data = store.load(slug)
        if data is None:
            return None
        opts = dict(data.get('options') or {})
        for k in ('provider', 'model_id', 'depth', 'scope'):
            if k in (body.get('options') or {}):
                opts[k] = body['options'][k]
        if opts.get('provider') and opts.get('model_id'):
            opts['model_label'] = ai_client.ask_model_label(opts['provider'], opts['model_id'])
        data['options'] = opts
        store.save(slug, data)
        return store.load(slug)
    data = await request.app.state.writer.run(save)
    if data is None:
        raise HTTPException(404, 'no such chat')
    return {'slug': slug, **data}


@router.post('/api/chats/{slug}/rename')
async def rename_chat(slug: str, request: Request, body: dict = Body(...)):
    name = str(body.get('name') or '').strip()
    if not name:
        raise HTTPException(400, 'Enter a name.')
    store = _store(request)
    if store.load(slug) is None:
        raise HTTPException(404, 'no such chat')

    def ren(db):
        new_slug, data = store.rename(slug, name)
        db.set_setting('ask_active_chat', new_slug)
        return new_slug, data
    new_slug, data = await request.app.state.writer.run(ren)
    return {'slug': new_slug, **(data or {})}


@router.post('/api/chats/{slug}/clear')
async def clear_chat(slug: str, request: Request):
    store = _store(request)

    def clear(db):
        data = store.load(slug)
        if data is None:
            return None
        data['history'], data['source_ids'], data['claude_session'] = [], [], ''
        store.save(slug, data)
        return True
    if await request.app.state.writer.run(clear) is None:
        raise HTTPException(404, 'no such chat')
    return {'ok': True}


@router.delete('/api/chats/{slug}')
async def delete_chat(slug: str, request: Request):
    store = _store(request)
    await request.app.state.writer.run(lambda db: store.delete(slug))
    return {'chats': store.list_chats()}


# ── Save as note ─────────────────────────────────────────────────────────────
@router.post('/api/ask/save-note')
async def save_note(request: Request, body: dict = Body(...)):
    md = str(body.get('answer_md') or '').strip()
    if not md:
        raise HTTPException(400, 'Nothing to save.')
    ids = [int(i) for i in body.get('source_ids') or []]
    review = None
    if body.get('review') is not None:
        try:
            review = weekly_review.validate_metadata(body.get('review'))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    path = await request.app.state.writer.run(lambda db: ask_core.save_note(db, md, ids, review=review))
    request.app.state.hub.publish('notes_changed', {'file': path.name})
    return {'file': path.name}
