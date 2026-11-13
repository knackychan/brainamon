"""Background jobs for the V6 server. Replaces the QThread workers of ai.py for the web UI.

Rules (the root CLAUDE.md threading invariant, restated for the server):
- A job thread never opens a SQLite connection. Its items are plain dicts loaded on the
  Writer when the job starts; each result is persisted with `writer.call(fn)` on the Writer.
- One job at a time, as in the Qt app (`self.worker`). Starting a second one raises Busy (409).
- With ids given by the client (a selection) a job force-reprocesses them when `force` is
  true; otherwise each kind's `select` skips items that already have the step done.
- After a job that changed item text, an automatic `index` job re-embeds the changed items
  (the Qt app's `_dirty_embed_ids`), once the `index` kind is registered (plan 07).

A kind is registered with `register(JobKind(...))`. Plan 03 registers `describe`; plan 07
adds thumb, categorize, analyze, index, note and download, and three optional hooks: `batch` +
`run_batch` (several items per call, results persisted one by one), `finish` (on the Writer after
a job that was not stopped) and `join` (a second start of the same kind adds its items to the
running job, as the Qt VideoAnalysisWorker.add_items).
"""
import secrets
import threading
import time
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any, Callable

from core import app_console
from core import entitlements

SNAPSHOT_KEYS = ('id', 'kind', 'label', 'state', 'total', 'done', 'skipped', 'err', 'detail', 'current', 'auto', 't0', 't1')

# Jobs asked for from outside the app (the local MCP, projects/mcp-local/plans/01-confirm-in-app.md): they wait
# for Fred's click in the app. Only the kinds that fill what is missing; never force.
REQUEST_KINDS = ('describe', 'categorize', 'thumb', 'analyze')
REQUEST_MAX_IDS = 500
CATEGORY_BATCH_MAX = 100


def category_groups(groups: list, max_items: int = CATEGORY_BATCH_MAX) -> list[dict]:
    """Validate a model-supplied category batch before it reaches SQLite."""
    if not isinstance(groups, list) or not groups or len(groups) > max_items:
        raise JobError(f'Give 1 to {max_items} category groups.')
    seen, out = set(), []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {'ids', 'category'}:
            raise JobError('Each group needs ids and category.')
        ids, name = group['ids'], group['category']
        if not isinstance(name, str) or not name.strip():
            raise JobError('Give an existing category name for each group.')
        if not isinstance(ids, list) or not ids:
            raise JobError('Each category group needs integer item ids.')
        for item_id in ids:
            if type(item_id) is not int or not -(2 ** 63) <= item_id < 2 ** 63:
                raise JobError('Item ids must be signed 64-bit integers.')
            if item_id in seen:
                raise JobError(f'Item {item_id} appears more than once in the batch.')
            seen.add(item_id)
            if len(seen) > max_items:
                raise JobError(f'At most {max_items} items per category batch.')
        out.append({'ids': list(ids), 'category': name.strip()})
    return out

# Notes asked for from outside the app (the local MCP save_note; projects/milestone-2026-10-14/claude-code-engine):
# the same one request slot, written only on Fred's click. Never replaces a note (ask_core.save_note picks a new name).
NOTE_TOPIC_MAX = 120
NOTE_BODY_MAX = 20000
NOTE_MAX_SOURCES = 200
NOTE_EXCERPT = 600             # what the confirm window shows of the body

# DB setting '1' / '0' (Settings > Claude Code, off by default): a request from outside is answered "approve"
# the moment it arrives, so no click is needed. Whatever cannot run right then (a job is busy) still waits.
AUTO_APPROVE_KEY = 'claude_auto_approve'


class Busy(Exception):
    """Another job is running."""


class JobError(Exception):
    """The job cannot start (no key, nothing to do, unknown kind). Message is user-facing."""


class Stopped(Exception):
    """Raised by a run_item that quit for Stop: the item goes back to queued, not failed."""


class Skipped(Exception):
    """An item has no work to perform and was not changed."""


@dataclass
class JobKind:
    key: str                                   # 'describe'
    label: str                                 # 'Describe' (menus, lamp, toasts)
    verb: str                                  # 'Described' (finish toast)
    ai: bool                                   # gated by entitlements.feature_enabled('ai')
    text: bool                                 # changes item text: re-embed afterwards
    prepare: Callable[[Any, 'Job'], list]      # on the Writer: (db, job) -> item dicts to run
    run_item: Callable[['Job', dict], Any]     # on the job thread: the network/file work
    persist: Callable[[Any, dict, Any, 'Job'], None]   # on the Writer: (db, item, result, job)
    gap: float = 0.3                           # pause after each item (the Qt workers' sleep)
    error_gap: float = 1.5                     # pause after a failed item
    batch: int = 1                             # > 1: run_batch gets that many items per call
    run_batch: Callable[['Job', list], list] | None = None
    finish: Callable[[Any, 'Job'], None] | None = None   # on the Writer, after a job not stopped
    join: bool = False                         # a second start of this kind joins the running job


@dataclass
class Job:
    id: int
    kind: str
    label: str
    ids: list
    force: bool
    opts: dict
    auto: bool = False
    state: str = 'running'                     # running | paused | finished | stopped
    total: int = 0
    done: int = 0
    skipped: int = 0
    err: int = 0
    detail: str = ''
    current: int | None = None
    t0: float = 0.0
    t1: float = 0.0
    ctx: dict = field(default_factory=dict)    # per-run settings resolved in prepare (provider, model, ...)
    items: list = field(default_factory=list)
    status: dict = field(default_factory=dict)  # item id -> {'state', 'title', 'error'?}
    ok_ids: list = field(default_factory=list)
    stopping: bool = False
    emit: Callable[[str, Any], None] = lambda kind, data: None   # set by JobManager: publish an SSE event

    def step(self, item_id: int, text: str) -> None:
        """Report a step of the current item (the Qt step_update), for the progress window."""
        if item_id in self.status:
            self.status[item_id]['step'] = text
        self.emit('job_item', {'job': self.id, 'id': item_id, 'state': 'working', 'step': text})

    def snapshot(self) -> dict:
        out = {k: getattr(self, k) for k in SNAPSHOT_KEYS}
        if self.kind == 'analyze' and 'opts' in self.ctx:
            from server.job_kinds import ANALYZE_DEFAULTS
            # A joining phone keeps the actual options for Retry; never publish provider credentials or arbitrary opts.
            out['options'] = {k: self.ctx['opts'][k] for k in ANALYZE_DEFAULTS if k in self.ctx['opts']}
        return out


KINDS: dict[str, JobKind] = {}


def register(kind: JobKind) -> None:
    KINDS[kind.key] = kind


class JobManager:
    def __init__(self, writer, hub, data_dir):
        self.writer = writer
        self.hub = hub
        self.data_dir = data_dir
        self.current: Job | None = None
        self.last: Job | None = None
        self.dirty: set[int] = set()
        # shortcut: pending fetches live in memory; persist them if they must survive app exit.
        self._fetch_ids: set[int] = set()
        self._fetch_lock = threading.Lock()
        self._lock = threading.Lock()
        self._closing = False
        self._seq = 0
        self._thread: threading.Thread | None = None
        self.on_prepare: list = []         # fn(kind_key) after Writer prepare completes
        self.on_finish: list = []          # fn(kind_key, job) after every job (e.g. drop the smart-search index)
        self.request: dict | None = None   # the one job asked for from outside, waiting for Fred (ask / answer)
        self._req_seq = secrets.randbelow(2 ** 31)   # a fresh start per process: a card from before a restart never matches
        self.notify: Callable[..., Any] = lambda category, title, text: False   # server/notify.Notifier, set by the app

    # ── state ────────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {'current': self.current.snapshot() if self.current else None,
                'last': self.last.snapshot() if self.last else None,
                'request': self._request_view()}

    def progress(self) -> dict:
        job = self.current or self.last
        if not job:
            return {'job': None, 'items': []}
        return {'job': job.snapshot(),
                'items': [{'id': i, **job.status[i]} for i in job.ids if i in job.status]}

    def _emit_job(self, job: Job) -> None:
        self.hub.publish('job', self.snapshot())

    # ── preview + start ──────────────────────────────────────────────────────
    def preview(self, kind_key: str, ids: list, force: bool, opts: dict | None = None) -> dict:
        """What a start would do, without starting: the confirm window's numbers."""
        kind = self._kind(kind_key)
        probe = Job(id=0, kind=kind.key, label=kind.label, ids=list(ids), force=force, opts=opts or {})
        items = self.writer.call(lambda db: kind.prepare(db, probe))
        for fn in self.on_prepare:
            fn(kind.key)
        return {'kind': kind.key, 'label': kind.label, 'count': len(items), 'asked': len(ids),
                'force': force, **{k: v for k, v in probe.ctx.items() if k in ('provider', 'model', 'key', 'plan')}}

    def start(self, kind_key: str, ids: list, force: bool = False, opts: dict | None = None,
              auto: bool = False) -> dict:
        kind = self._kind(kind_key)
        if kind.ai and not entitlements.feature_enabled('ai'):
            raise JobError('AI features are not available on your current plan.')
        with self._lock:
            if self._closing:
                raise Busy('App is restarting for an update.')
            cur = self.current
            if cur is not None and not (kind.join and cur.kind == kind.key and not cur.stopping):
                raise Busy(f'One job at a time: {cur.label} is running')
        if cur is not None:
            return self.extend(cur, kind, ids, force)
        with self._lock:
            if self._closing:
                raise Busy('App is restarting for an update.')
            if self.current is not None:
                raise Busy(f'One job at a time: {self.current.label} is running')
            self._seq += 1
            job = Job(id=self._seq, kind=kind.key, label=kind.label, ids=[int(i) for i in ids],
                      force=force, opts=opts or {}, auto=auto)
            self.current = job            # reserve the line before the slow prepare
        try:
            job.items = self.writer.call(lambda db: kind.prepare(db, job))
            for fn in self.on_prepare:
                fn(kind.key)
        except Exception:
            with self._lock:
                self.current = None
            raise
        if kind.ai and kind.key != 'describe' and not job.ctx.get('key', True):
            with self._lock:
                self.current = None
            raise JobError(job.ctx.get('key_msg') or 'API key required: open Settings > API keys.')
        if not job.items:
            with self._lock:
                self.current = None
            raise JobError(job.ctx.get('empty_msg') or f'Nothing to do for {kind.label}.')
        job.emit = self.hub.publish
        job.ids = [it['id'] for it in job.items]
        job.total = len(job.items)
        job.status = {it['id']: {'state': 'queued', 'title': _title(it)} for it in job.items}
        job.t0 = time.time()
        app_console.emit('log', f'{"Auto " if auto else ""}{kind.label}: {job.total} item(s)'
                         + (' (selection, forced)' if force else ''))
        self._thread = threading.Thread(target=copy_context().run, args=(self._run, kind, job), name='cm-job', daemon=True)
        self._thread.start()
        self._emit_job(job)
        return job.snapshot()

    def extend(self, job: 'Job', kind: JobKind, ids: list, force: bool) -> dict:
        """Add items to the running job of the same kind (its options stay as they were)."""
        probe = Job(id=0, kind=kind.key, label=kind.label, ids=[int(i) for i in ids], force=force, opts=job.opts)
        items = self.writer.call(lambda db: kind.prepare(db, probe))
        for fn in self.on_prepare:
            fn(kind.key)
        with self._lock:
            new = [it for it in items if it['id'] not in job.status]
            for it in new:
                job.status[it['id']] = {'state': 'queued', 'title': _title(it)}
                job.ids.append(it['id'])
            job.items.extend(new)          # the running loop picks them up
            job.total = len(job.items)
        if new:
            text = f'Added {len(new)} item(s) to the running {kind.label.lower()} job'
            app_console.emit('log', text)
            self.hub.publish('toast', {'text': text, 'level': ''})
        self._emit_job(job)
        return job.snapshot()

    # ── requests from outside the app: wait for a click in the app ────────────
    def _request_view(self) -> dict | None:
        r = self.request
        if not r:
            return None
        view = dict(r)
        view.pop('body', None)          # a note's full text stays here; the page gets its excerpt
        view.pop('proposal', None)      # a canvas proposal's payload too; the page gets its preview
        return view

    def _check_free(self) -> None:
        cur = self._request_view()
        if cur and cur['state'] in ('pending', 'approving'):
            raise Busy(f"A request is already waiting for an answer in the app (#{cur['id']})")

    def ask(self, kind_key: str, ids: list, source: str = 'Claude Code') -> dict:
        """Store a job someone outside the app wants. Nothing starts: the page shows a confirm window and
        answer() starts it (force=False) only on Fred's click."""
        if kind_key not in REQUEST_KINDS:
            raise JobError(f"Only {', '.join(REQUEST_KINDS)} can be requested")
        ids = sorted({int(i) for i in ids})
        if not ids or len(ids) > REQUEST_MAX_IDS:
            raise JobError(f'Give between 1 and {REQUEST_MAX_IDS} item ids')
        self._check_free()
        p = self.preview(kind_key, ids, False)
        if not p['count']:
            raise JobError('Nothing to do: every one of these items already has this step done.')
        with self._lock:
            self._check_free()
            self._req_seq += 1
            self.request = {'id': self._req_seq, 'type': 'job', 'kind': kind_key, 'ids': ids,
                            'source': str(source)[:40], 'preview': p, 'state': 'pending', 't0': time.time()}
            view = dict(self.request)
        app_console.emit('log', f"{view['source']} asks: {p['label']} {p['count']} item(s); waiting for a click in the app")
        self.hub.publish('job', self.snapshot())
        return self._settle(view, f"{p['label']} {p['count']} item(s)")

    def ask_note(self, topic: str, body: str, sources: list, source: str = 'Claude Code',
                 file: str = '', category: str = '', stamps: list | None = None) -> dict:
        """Store a note someone outside the app wants saved. Nothing is written: the page shows a confirm
        window and answer() writes it only on Fred's click. With `file`, the request replaces that
        existing personal note (a reformat): validated now, re-validated on the Writer at the click."""
        topic = ' '.join(str(topic or '').split())[:NOTE_TOPIC_MAX]
        body = str(body or '').strip()
        if not topic or not body:
            raise JobError('A note needs a topic and a body.')
        if len(body) > NOTE_BODY_MAX:
            raise JobError(f'The note is too long ({len(body)} characters, at most {NOTE_BODY_MAX}).')
        ids = sorted({int(i) for i in sources or []})
        if len(ids) > NOTE_MAX_SOURCES:
            raise JobError(f'At most {NOTE_MAX_SOURCES} source ids.')
        file = str(file or '').strip()
        category = ' '.join(str(category or '').split())[:60]
        if stamps is not None and not file:
            raise JobError('Stamps belong to a personal note: name it with file.')
        self._check_free()
        if file:
            from knowledge import knowledge as _kn    # here, not at the top: server/jobs.py stays light

            def check(db):
                p = _kn.safe_note_path(db.notes_dir, file)
                if p is None:
                    raise JobError(f'No note named {file}')
                meta, _b = _kn.split_frontmatter(p.read_text(encoding='utf-8'))
                if meta.get('kind') != 'personal':
                    raise JobError('Only a personal note (My Notes) can be replaced.')
            self.writer.call(check)
        self._check_free()
        with self._lock:
            self._check_free()
            self._req_seq += 1
            self.request = {'id': self._req_seq, 'type': 'note', 'topic': topic, 'body': body,
                            'excerpt': body[:NOTE_EXCERPT], 'chars': len(body), 'sources': ids,
                            'source': str(source)[:40], 'state': 'pending', 't0': time.time()}
            if file:
                self.request['file'] = file
                self.request['category'] = category
                if stamps is not None:
                    from core import note_format as _nf
                    self.request['stamps'] = _nf.clean_stamps(stamps)
            view = self._request_view()
        app_console.emit('log', f'{view["source"]} asks to save the note "{topic}"; waiting for a click in the app')
        self.hub.publish('job', self.snapshot())
        return self._settle(view, f'Save the note "{topic}"')

    def ask_category(self, ids: list, category: str, source: str = 'Claude Code', *,
                     require_approval: bool = False) -> dict:
        """Store a re-categorize someone outside the app wants. Nothing changes: the page shows a confirm
        window (items per current category, a few titles) and answer() sets the category on the Writer only on
        Fred's click, or at once with auto-approve unless require_approval is set (Wiskit Deep).
        Unlike the categorize job this overwrites an existing category."""
        ids = sorted({int(i) for i in ids or []})
        if not ids or len(ids) > REQUEST_MAX_IDS:
            raise JobError(f'Give between 1 and {REQUEST_MAX_IDS} item ids')
        if any(i < -(2 ** 63) or i >= 2 ** 63 for i in ids):
            raise JobError('Item ids must be signed 64-bit integers.')
        category = str(category or '').strip()
        self._check_free()

        def look(db):
            names = {c['name'] for c in db.get_categories()}
            if category not in names:
                raise JobError(f"No category named {category or '(empty)'}. Existing: {', '.join(sorted(names))}")
            marks = ','.join('?' * len(ids))
            return db.conn.execute(
                f'SELECT id, category, COALESCE(NULLIF(short_desc, ""), NULLIF(description, ""), url) AS title '
                f'FROM items WHERE id IN ({marks}) ORDER BY id', ids).fetchall()
        rows = self.writer.call(look)
        found = {r['id'] for r in rows}
        missing = [i for i in ids if i not in found]
        if missing:
            raise JobError(f"No such item id: {', '.join(map(str, missing[:10]))}")
        todo = [r for r in rows if r['category'] != category]
        if not todo:
            raise JobError(f'Nothing to do: every one of these items is already in {category}.')
        counts: dict = {}
        for r in todo:
            counts[r['category']] = counts.get(r['category'], 0) + 1
        self._check_free()
        with self._lock:
            self._check_free()
            self._req_seq += 1
            self.request = {'id': self._req_seq, 'type': 'category', 'category': category,
                            'ids': [r['id'] for r in todo], 'from': counts,
                            'sample': [{'id': r['id'], 'title': str(r['title'] or '')[:80]} for r in todo[:8]],
                            'source': str(source)[:40], 'state': 'pending', 't0': time.time()}
            if require_approval or source in ('Wiskit', 'Wiskit (Claude Code)'):
                self.request['require_approval'] = True
            view = dict(self.request)
        app_console.emit('log', f'{view["source"]} asks: move {len(todo)} item(s) to {category}; waiting for a click in the app')
        self.hub.publish('job', self.snapshot())
        return self._settle(view, f'Move {len(todo)} item(s) to {category}')

    def ask_categories(self, groups: list, source: str = 'Claude Code') -> dict:
        """One reviewed batch across categories. Always requires a click, even with auto-approve."""
        groups = category_groups(groups)
        targets = {i: g['category'] for g in groups for i in g['ids']}
        self._check_free()

        def look(db):
            names = {c['name'] for c in db.get_categories()}
            for category in targets.values():
                if category not in names:
                    raise JobError(f'No category named {category}.')
            rows = {r['id']: r for r in db.get_items_by_ids(list(targets))}
            missing = targets.keys() - rows.keys()
            if missing:
                raise JobError(f"No such item id: {', '.join(map(str, sorted(missing)))}")
            return [{'id': i, 'title': str(rows[i].get('short_desc') or rows[i].get('description')
                        or rows[i].get('url') or '')[:160],
                     'from': rows[i]['category'], 'category': category}
                    for i, category in targets.items() if rows[i]['category'] != category]
        entries = self.writer.read(look)
        if not entries:
            raise JobError('Nothing to do: every item is already in its proposed category.')
        with self._lock:
            self._check_free()
            self._req_seq += 1
            self.request = {'id': self._req_seq, 'type': 'category_batch', 'entries': entries,
                            'ids': [e['id'] for e in entries], 'source': str(source)[:40],
                            'state': 'pending', 't0': time.time(), 'require_approval': True}
            view = dict(self.request)
        what = f'Review category changes for {len(entries)} item(s)'
        app_console.emit('log', f"{view['source']} asks: {what}; waiting for a click in the app")
        self.hub.publish('job', self.snapshot())
        return self._settle(view, what)

    def ask_canvas(self, payload: dict, source: str = 'Claude Code') -> dict:
        """A canvas proposal (projects/wiskit-canvas/PLAN.md): a new themed canvas or additions to one. Nothing is
        written: the page shows the review window (CANVAS-02) and answer() applies it on the Writer only on Fred's
        click. Always requires that click, whatever the source and the auto-approve setting."""
        from library import canvas_plan       # here, not at the top: server/jobs.py stays light to import
        try:
            proposal = canvas_plan.normalize(payload)
            self._check_free()
            chk = self.writer.read(lambda db: canvas_plan.check(db, self._canvas_dir(), proposal))
        except canvas_plan.ProposalError as exc:
            raise JobError(str(exc))
        with self._lock:
            self._check_free()
            self._req_seq += 1
            self.request = {'id': self._req_seq, 'type': 'canvas_proposal', 'proposal': proposal,
                            'preview': chk['preview'], 'rev': chk['rev'], 'ids': sorted(chk['rows']),
                            'source': str(source)[:40], 'state': 'pending', 't0': time.time(),
                            'require_approval': True}
            view = self._request_view()
        t, c = chk['preview']['target'], chk['preview']['counts']
        what = (f"{'Create the canvas' if t['new'] else 'Add to the canvas'} {t['name']}: "
                f"{c['thumbnail'] + c['frame'] + c['text']} element(s)" + (f", move {c['moves']}" if c['moves'] else ''))
        app_console.emit('log', f"{view['source']} asks: {what}; waiting for a click in the app")
        self.hub.publish('job', self.snapshot())
        return self._settle(view, what)

    def _canvas_dir(self):
        from pathlib import Path
        return Path(self.data_dir) / 'canvases'

    def _apply_canvas(self, req: dict) -> dict:
        from library import canvas_plan
        from library.canvas import CanvasStore

        def write(db):
            try:
                return canvas_plan.apply(db, CanvasStore(self.data_dir), req['proposal'], req.get('rev', 0))
            except canvas_plan.ProposalError as exc:
                raise JobError(str(exc))
            except (OSError, ValueError) as exc:
                raise JobError(f'Canvas was not saved: {exc}. Retry or decline this request.') from exc
        out = self.writer.call(write, timeout=None)
        return out

    def _set_categories(self, req: dict) -> int:
        def write(db):
            with db.conn:
                names = {c['name'] for c in db.get_categories()}
                for entry in req['entries']:
                    if entry['category'] not in names:
                        raise JobError(f"No category named {entry['category']}.")
                rows = {r['id']: r for r in db.get_items_by_ids(req['ids'])}
                missing = set(req['ids']) - rows.keys()
                if missing:
                    raise JobError(f"No such item id: {', '.join(map(str, sorted(missing)))}")
                changed = [e for e in req['entries'] if rows[e['id']]['category'] != e['category']]
                if not changed:
                    raise JobError('Nothing to do: every item is already in its proposed category.')
                now = int(time.time() * 1000)
                db.conn.executemany('UPDATE items SET category = ?, modified = ? WHERE id = ?',
                                    [(e['category'], now, e['id']) for e in changed])
            return [e['id'] for e in changed]
        changed = self.writer.call(write)
        self.hub.publish('items_changed', {'ids': changed})
        return len(changed)

    def _set_category(self, req: dict) -> int:
        def write(db):
            category, ids = req['category'], req['ids']
            if category not in {c['name'] for c in db.get_categories()}:
                raise JobError(f'No category named {category}.')
            marks = ','.join('?' * len(ids))
            rows = db.conn.execute(f'SELECT id, category FROM items WHERE id IN ({marks}) ORDER BY id', ids).fetchall()
            found = {r['id'] for r in rows}
            missing = [i for i in ids if i not in found]
            if missing:
                raise JobError(f"No such item id: {', '.join(map(str, missing[:10]))}")
            changed = [r['id'] for r in rows if r['category'] != category]
            if not changed:
                raise JobError(f'Nothing to do: every one of these items is already in {category}.')
            db.set_field_bulk(changed, 'category', category)
            return changed
        changed = self.writer.call(write)
        self.hub.publish('items_changed', {'ids': changed})
        return len(changed)

    def _settle(self, view: dict, what: str) -> dict:
        """Auto-approve eligible requests; manual-only requests always wait for the user's click."""
        if not view.get('require_approval') and self.writer.call(lambda db: db.get_setting(AUTO_APPROVE_KEY, '0')) == '1':
            try:
                return self.answer(view['id'], True, auto=True)['request']
            except (Busy, JobError) as exc:
                app_console.emit('log', f"Auto-approve could not run request #{view['id']}: {exc}; "
                                        'it waits for a click in the app', level='warning')
        self.notify('approval', f"{view['source']} is waiting for your OK", what)
        current = self._request_view()
        return current if current and current['id'] == view['id'] else view

    def answer(self, req_id: int, approve: bool, auto: bool = False) -> dict:
        """Fred's click on the request's confirm window: the job starts (force=False) or the note is written.
        Busy / JobError on approve leave it pending. auto: the call came from auto-approve, not a click."""
        with self._lock:
            r = self._request_view()
            if not r or r['id'] != int(req_id) or r['state'] != 'pending':
                raise JobError('This request is no longer waiting (answered or replaced).')
            self.request['state'] = 'approving' if approve else 'declined'
            req = dict(self.request)                 # with a note's body
        started = saved = moved = canvas = None
        if approve:
            try:
                if req.get('type') == 'note':
                    saved = self._write_note(req)
                elif req.get('type') == 'canvas_proposal':
                    canvas = self._apply_canvas(req)
                elif req.get('type') == 'category':
                    moved = self._set_category(req)
                elif req.get('type') == 'category_batch':
                    moved = self._set_categories(req)
                else:
                    started = self.start(req['kind'], req['ids'], force=False)
            except Exception:
                with self._lock:
                    self.request['state'] = 'pending'
                raise
            with self._lock:
                self.request['state'] = 'approved'
                if canvas is not None:
                    self.request['result'] = canvas    # job_status shows what was made
        app_console.emit('log', f"{r['source']} request #{r['id']}: {'approved' if approve else 'declined'} "
                                f"{'automatically (Settings > Claude Code)' if auto else 'in the app'}")
        if canvas is not None:
            self.hub.publish('canvas_changed', {'id': canvas['canvas_id'], 'rev': canvas['rev'], 'count': canvas['count']})
        self.hub.publish('job', self.snapshot())
        if auto and approve:
            if moved is not None:
                done = f"Moved {moved} item(s) to {req['category']}"
            else:
                done = f'Saved the note {saved}' if saved else f"Started {started['label']}: {started['total']} item(s)"
            self.hub.publish('toast', {'text': f"{r['source']}: {done[0].lower()}{done[1:]}", 'level': ''})
            self.notify('claude', f"{r['source']} did something", done)
        return {'request': self._request_view(), 'started': started, 'saved': saved, 'moved': moved, 'canvas': canvas}

    def _write_note(self, req: dict) -> str:
        """The approved note, on the Writer; the notes are reindexed. A new data/notes/<slug>.md, or —
        when the request names a `file` — that personal note replaced (the reformat path)."""
        from knowledge import ask_core        # here, not at the top: server/jobs.py stays light to import
        if req.get('file'):
            from knowledge import knowledge as _kn
            from knowledge import my_notes as _mn

            def write(db):
                p = _kn.safe_note_path(db.notes_dir, req['file'])
                if p is None:
                    raise JobError('That note is gone.')
                meta, _old = _kn.split_frontmatter(p.read_text(encoding='utf-8'))
                if meta.get('kind') != 'personal':
                    raise JobError('Only a personal note (My Notes) can be replaced.')
                _mn.save_note(p, req['topic'], req.get('category') or meta.get('category') or '', req['body'], req.get('stamps'))
                db.reindex_notes()
                return p.name
            name = self.writer.call(write)
            self.hub.publish('notes_changed', {'file': name, 'personal': True})
            return name
        md = f"# {req['topic']}\n\n{req['body']}"
        path = self.writer.call(lambda db: ask_core.save_note(db, md, req['sources']))
        self.hub.publish('notes_changed', {'file': path.name})
        return path.name

    def _kind(self, key: str) -> JobKind:
        kind = KINDS.get(key)
        if kind is None:
            raise JobError(f'Unknown job: {key}')
        return kind

    # ── controls ─────────────────────────────────────────────────────────────
    def pause(self) -> dict:
        job = self.current
        if job and job.state == 'running':
            job.state = 'paused'
            app_console.emit('log', f'{job.label} paused')
            self._emit_job(job)
        return self.snapshot()

    def resume(self) -> dict:
        job = self.current
        if job and job.state == 'paused':
            job.state = 'running'
            app_console.emit('log', f'{job.label} resumed')
            self._emit_job(job)
        return self.snapshot()

    def stop(self, job_id: int | None = None) -> dict:
        """Ask the running job to stop. With `job_id` (the phone's Tools panel sends it), only that job: an id that is
        not the running one is refused under the same lock that reads `current`, so a Stop meant for a job that has
        ended cannot stop the job that replaced it. Without an id it is what it always was."""
        with self._lock:
            job = self.current
            if job_id is not None and (job is None or job.id != job_id):
                raise JobError('That job is not running any more; nothing was stopped.')
            if job:
                job.stopping = True
                if job.state == 'paused':
                    job.state = 'running'
        return self.snapshot()

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
        self.stop()
        t = self._thread
        if t is not None:
            t.join(5)

    # ── the job thread ───────────────────────────────────────────────────────
    def _run(self, kind: JobKind, job: Job) -> None:
        if kind.batch > 1 and kind.run_batch is not None:
            self._run_batches(kind, job)
        else:
            self._run_items(kind, job)
        self._finish(kind, job)

    def _ok(self, kind: JobKind, job: Job, iid: int) -> None:
        self.dirty.update(job.ctx.pop('added_ids', []))
        job.done += 1
        job.ok_ids.append(iid)
        st = job.status[iid]
        st.update(state='done', ms=_took(st))
        if kind.text:
            self.dirty.add(iid)
        self.hub.publish('job_item', {'job': job.id, 'id': iid, 'state': 'done', 'ms': st['ms']})
        self.hub.publish('items_changed', {'ids': [iid]})

    def _fail(self, kind: JobKind, job: Job, iid: int, exc: Exception) -> None:
        job.err += 1
        msg = str(exc)[:300]
        if not job.detail:
            job.detail = msg
        recovery = {k: getattr(exc, k) for k in ('code', 'action') if hasattr(exc, k)}
        st = job.status[iid]
        st.update(state='error', error=msg, ms=_took(st), **recovery)
        self.hub.publish('job_item', {'job': job.id, 'id': iid, 'state': 'error', 'error': msg, 'ms': st['ms'], **recovery})
        app_console.emit('error', f'{kind.label} item failed', level='error',
                         payload={'item_id': iid, 'worker': kind.label}, error=exc)

    def _wait_paused(self, job: Job) -> bool:
        """Block while paused; False when the job is stopping."""
        if entitlements.phone_request.get() and not entitlements.feature_enabled('phone_sync'):
            job.stopping = True
        while job.state == 'paused' and not job.stopping:
            time.sleep(0.2)
        return not job.stopping

    def _run_batches(self, kind: JobKind, job: Job) -> None:
        i = 0
        while i < len(job.items):
            if not self._wait_paused(job):
                break
            chunk = job.items[i:i + kind.batch]
            i += len(chunk)
            t = time.time()
            for it in chunk:
                job.status[it['id']].update(state='working', t=t)
                self.hub.publish('job_item', {'job': job.id, 'id': it['id'], 'state': 'working', 't': t})
            job.current = chunk[0]['id']
            self._emit_job(job)
            try:
                results = kind.run_batch(job, chunk)
            except Exception as exc:
                for it in chunk:
                    self._fail(kind, job, it['id'], exc)
                time.sleep(kind.error_gap)
                continue
            for it, result in zip(chunk, results):
                try:
                    self.writer.call(lambda db, it=it, result=result: kind.persist(db, it, result, job))
                except Exception as exc:
                    self._fail(kind, job, it['id'], exc)
                    continue
                self._ok(kind, job, it['id'])
            time.sleep(kind.gap)

    def _run_items(self, kind: JobKind, job: Job) -> None:
        for item in job.items:          # a joined job appends to job.items while this runs
            if not self._wait_paused(job):
                break
            iid = item['id']
            job.current = iid
            t = time.time()
            job.status[iid].update(state='working', t=t)
            self.hub.publish('job_item', {'job': job.id, 'id': iid, 'state': 'working', 't': t})
            self._emit_job(job)
            try:
                result = kind.run_item(job, item)
                self.writer.call(lambda db: kind.persist(db, item, result, job))
            except Skipped as exc:
                job.skipped += 1
                st = job.status[iid]
                st.update(state='skipped', step=str(exc), ms=_took(st))
                self.hub.publish('job_item', {'job': job.id, 'id': iid, 'state': 'skipped', 'step': st['step'], 'ms': st['ms']})
                continue
            except Stopped:
                job.status[iid]['state'] = 'queued'
                self.hub.publish('job_item', {'job': job.id, 'id': iid, 'state': 'queued'})
                break
            except Exception as exc:
                self._fail(kind, job, iid, exc)
                time.sleep(kind.error_gap)
                continue
            self._ok(kind, job, iid)
            time.sleep(kind.gap)

    def _finish(self, kind: JobKind, job: Job) -> None:
        if kind.finish is not None and not job.stopping:
            try:
                self.writer.call(lambda db: kind.finish(db, job))
            except Exception as exc:
                job.ctx['finish_toast'] = f'{kind.label} could not finish: {str(exc)[:200]}'
                app_console.emit('error', f'{kind.label} finish failed', level='error', error=exc)
        job.state = 'stopped' if job.stopping else 'finished'
        job.current = None
        job.t1 = time.time()
        stopped = job.state == 'stopped'
        with self._lock:
            self.last, self.current = job, None
        app_console.emit('error' if job.err else 'log',
                         f'{"Auto " if job.auto else ""}{kind.label} finished: {job.done} done, '
                         f'{job.skipped} skipped, {job.err} failed' + (' (stopped)' if stopped else ''),
                         level='error' if job.err else 'info')
        if stopped:
            text = f'Stopped {kind.label.lower()} after {job.done + job.skipped + job.err} of {job.total}'
        else:
            text = f'{kind.verb} {job.done} item(s)' + (f' · {job.skipped} skipped' if job.skipped else '') + (f' · {job.err} failed' if job.err else '')
            if job.skipped and kind.key == 'describe':
                text += '. Nothing to describe yet: open it online once or add a note.'
        if job.ctx.get('finish_toast') and not stopped:
            text = job.ctx['finish_toast']
        if not job.auto or job.err:
            self.hub.publish('toast', {'text': text, 'level': 'w' if job.err or stopped else ''})
            self.notify('jobs', f'{kind.label}: ' + ('finished with errors' if job.err else 'stopped' if stopped else 'done'), text)
        for ev, data in job.ctx.get('finish_events', []):
            self.hub.publish(ev, data)
        self._emit_job(job)
        for fn in list(self.on_finish):
            try:
                fn(kind.key, job)
            except Exception as exc:
                app_console.emit('error', 'Job finish hook failed', level='error', error=exc)
        self.queue_fetch(())
        self._follow_up(kind, job)

    def queue_fetch(self, ids) -> None:
        """Fetch missing previews after a scrape, waiting for the running job to finish."""
        with self._fetch_lock:
            self._fetch_ids.update(int(i) for i in ids)
            if self.current is not None or self._closing or not self._fetch_ids:
                return
            pending = sorted(self._fetch_ids)
            self._fetch_ids.clear()
            try:
                self.start('thumb', pending, force=False, auto=True)
            except Busy:
                self._fetch_ids.update(pending)
            except JobError as exc:
                app_console.emit('log', f'Automatic fetch pass skipped: {exc}')

    def reindex(self, ids) -> None:
        """Items added or changed outside a job (an import): embed them now, or after the running
        job (the dirty set is drained by _follow_up). Not from the Writer thread."""
        self.dirty.update(int(i) for i in ids)
        if self.current is not None or 'index' not in KINDS or not self.dirty:
            return
        dirty = sorted(self.dirty)
        self.dirty.clear()
        try:
            self.start('index', dirty, force=False, auto=True)
        except (Busy, JobError) as exc:
            self.dirty.update(dirty)
            app_console.emit('log', f'Automatic index pass skipped: {exc}')

    def _follow_up(self, kind: JobKind, job: Job) -> None:
        """Re-embed items whose text changed (the Qt app's silent index pass)."""
        if kind.key == 'index' or job.state == 'stopped' or 'index' not in KINDS:
            return
        dirty = sorted(self.dirty)
        if not dirty:
            return
        self.dirty.clear()
        app_console.emit('log', f'Re-embedding {len(dirty)} changed item(s) (automatic index pass)')
        try:
            self.start('index', dirty, force=False, auto=True)
        except (Busy, JobError) as exc:
            self.dirty.update(dirty)       # keep them for the next pass
            app_console.emit('log', f'Automatic index pass skipped: {exc}')


def _took(st: dict) -> int:
    """How long an item took, in ms, from its 'working' start (0 when it never started)."""
    return round((time.time() - st['t']) * 1000) if 't' in st else 0


def _title(item: dict) -> str:
    text = (item.get('short_desc') or item.get('ai_desc') or item.get('description') or '').strip()
    return (text.splitlines()[0] if text else item.get('url', ''))[:90]
