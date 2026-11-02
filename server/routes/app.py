"""The app itself (projects/desktop-app): version, data folder, Start with Windows, Quit.

GET /api/app            -> {"version", "frozen", "data_dir", "autostart", "widget", "tray", "warm", "notice", "can_quit"}
PUT /api/app/widget     {"on": bool}: Wiskit on the desktop (starts it now, or shows / hides it), and
                        which mode Start with Windows uses
PUT /api/app/tray       {"on": bool}: "Minimize to tray and show Wiskit" (DB setting `minimize_to_tray`;
                        the window and its tray icon, desktop/tray.py, read it through GET /api/app)
PUT /api/app/warm       {"on": bool}: keep the main window warm (hidden, WebView2 suspended) when it is
                        minimized or closed, instead of closing it (DB setting `keep_window_warm`)
                        All three publish an `app` event {"tray", "warm", "notice"} for the keeper (desktop/sleep.py)
PUT /api/app/notice     {"on": bool}: show a notification when the window goes to the tray (DB setting
                        `tray_notice`; off by default; the first time it goes to the tray there is one notice anyway)
POST /api/app/tray/seen     the keeper showed that first notice (DB setting `tray_notice_seen`); it is not shown again
PUT /api/app/toasts     {"on"?, "jobs"?, "approval"?, "claude"?, "capture"?}: Windows notifications (server/notify.py;
                        DB settings `os_notify`, `os_notify_<category>`; off by default); the view's `toasts`
POST /api/app/toasts/test   one notification now
PUT /api/app/autostart  {"on": bool} -> same as GET
POST /api/app/capture   {"text"}: the drop panel's "Choose where...": opens the main window on Add to Brainamon with that text
                        (kept until the window takes it with POST /api/app/capture/take, so a window that was closed gets it too)
POST /api/app/note      {"mode": "write"|"record"}: Wiskit's wheel; opens the main window on My Notes (taken with POST /api/app/note/take)
POST /api/app/quit      stops the server process (and with it a background-mode instance)
POST /api/app/restart   the same, after starting a launch that waits for this one to close (a new data folder loads)
GET  /api/app/update            -> updater.check() (latest GitHub release vs this version)
POST /api/app/update/download   -> starts the download (installer + .sha256, checksum verified) in the background
GET  /api/app/update/status     -> {"state": idle|downloading|ready|error, "done", "total", "name", "version", "error"}
POST /api/app/update/install    {"name"}: runs that verified installer, then stops the server
GET  /api/app/setup             -> the first-run checklist: data folder, AI key, library size, tools, and
                                   the item/note counts of a folder chosen for the next start
POST /api/app/setup/dismiss     the checklist no longer opens at start (DB setting `setup_dismissed`)
PUT  /api/app/data-dir          {"path"}: installed app only, point location.json at another data folder
                                (an empty folder or one holding content_manager.db; nothing is moved; used
                                from the next start)
POST /api/app/diagnostics       -> {"path", "name"}: a redacted diagnostics zip on this PC (server/diagnostics.py);
                                its folder can then be opened with POST /api/reveal

Only the tray preference touches SQLite (reader / Writer); autostart is a registry value
(autostart.py), the widget flag a file, quit asks uvicorn to exit.
Installing is always an explicit click (Settings > App); nothing installs on its own.
"""
import os
import sqlite3
import sys
import webbrowser
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request

from core import app_paths
from core import config
from core.db import ReadOnlyDatabase
from server import diagnostics
from server.notify import CATEGORIES
from desktop import autostart
from desktop import updater
from core.version import __version__
from server.store import reader

router = APIRouter()

TRAY_KEY = 'minimize_to_tray'      # DB settings value '1' / '0'; ON until the user turns it off (a desktop app lives in the tray)
WARM_KEY = 'keep_window_warm'      # '1' / '0'; off: asleep closes the window process
NOTICE_KEY = 'tray_notice'         # '1' / '0'; off: no notification when the window goes to the tray (bar the first time)
SEEN_KEY = 'tray_notice_seen'      # '1' once the first-time tray notice was shown
SETUP_KEY = 'setup_dismissed'      # '1': the first-run checklist does not open at start


def _sessions_saved(db):
    from core import site_sessions
    return any(s['mode'] == 'protected' or s['status'].startswith('Legacy file mode') for s in (site_sessions.summary(slot, [db.get_setting]) for slot in ('general', 'instagram')))


def _view(request: Request) -> dict:
    return {
        'version': __version__,
        'frozen': app_paths.FROZEN,
        'automatic_updates': request.app.state.updates.enabled(),
        'data_dir': str(request.app.state.data_dir),
        # the installed app's location.json target: differs from data_dir after a change, until the restart
        'data_dir_next': str(app_paths.data_dir() if app_paths.FROZEN else request.app.state.data_dir),
        'autostart': autostart.is_on(),
        'widget': autostart.widget_on(),
        'tray': reader(request.app.state.db_path).get_setting(TRAY_KEY, '1') == '1',
        'warm': reader(request.app.state.db_path).get_setting(WARM_KEY, '0') == '1',
        'notice': reader(request.app.state.db_path).get_setting(NOTICE_KEY, '0') == '1',
        'notice_seen': reader(request.app.state.db_path).get_setting(SEEN_KEY, '0') == '1',
        'toasts': request.app.state.notify.view(),
        'can_quit': getattr(request.app.state, 'request_exit', None) is not None,
    }


@router.get('/api/app')
def get_app(request: Request):
    return _view(request)


@router.get('/api/app/setup')
def get_setup(request: Request, include_tools: bool = True):
    from server.routes.settings import settings_view, tools_view, get_tools_install
    from server.routes.io import _vault, _obsidian_installed
    from server.sync import _applied
    db = reader(request.app.state.db_path)
    settings = settings_view(db)
    # Setup navigation polls library facts without launching executable probes.
    tools = tools_view() if include_tools else None
    vault = Path(_vault(request))
    cloud = request.app.state.sync.status()
    return {
        'frozen': app_paths.FROZEN,
        'data_dir': str(request.app.state.data_dir),
        'has_key': any(config.get(k) for k in (config.ANTHROPIC, config.OPENAI, config.FREELLMAPI)),
        'items': db.count_items(),
        'phone_seen': bool(_applied(db)),
        # the user's own browser cookies (Settings > Downloads); the installer never ships any
        'cookies': _sessions_saved(db),
        **({'tools': {t['name'].replace('-', '_'): t['found'] for t in tools['tools']},
            'tool_status': tools, 'tool_install': get_tools_install()} if tools is not None else {}),
        'keys': settings['keys'],
        'models': settings['models'],
        'obsidian': {'installed': _obsidian_installed(), 'vault': str(vault),
                     'set': bool(db.get_setting('obsidian_vault', '')), 'mode': db.get_setting('obsidian_mode', '') or '',
                     'vault_ok': vault.is_dir(), 'is_vault': (vault / '.obsidian').is_dir()},
        'cloud': {'configured': cloud['configured'], 'signed_in': cloud['signed_in'],
                  'on': db.get_setting('cloud_upload', '') == 'on'},
        'dismissed': db.get_setting(SETUP_KEY, '0') == '1',
        'can_quit': getattr(request.app.state, 'request_exit', None) is not None,
        **_next_library(request),
    }


def _next_library(request: Request) -> dict:
    """The folder chosen for the next start and what it already holds (read-only), so setup can count
    content that loads after the restart."""
    current = Path(request.app.state.data_dir)
    target = Path(app_paths.data_dir()) if app_paths.FROZEN else current
    items = notes = 0
    if target.resolve() != current.resolve():
        try:
            db = ReadOnlyDatabase(target / 'content_manager.db') if (target / 'content_manager.db').is_file() else None
            if db:
                try:
                    items = db.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]
                finally:
                    db.close()
            notes = sum(1 for _ in (target / 'notes').glob('*.md')) if (target / 'notes').is_dir() else 0
        except (OSError, sqlite3.Error):
            items = notes = 0
    return {'data_dir_next': str(target), 'next_items': items, 'next_notes': notes}


SETUP_LINKS = {
    'anthropic': 'https://console.anthropic.com/settings/keys',
    'openai': 'https://platform.openai.com/api-keys',
    'obsidian': 'https://obsidian.md/download',
}


@router.post('/api/app/setup/link')
def open_setup_link(body: dict = Body(...)):
    name = body.get('name')
    if not isinstance(name, str) or name not in SETUP_LINKS:
        raise HTTPException(400, 'Unknown setup link.')
    if not webbrowser.open(SETUP_LINKS[name]):
        raise HTTPException(500, 'Could not open the system browser.')
    return {'ok': True}


@router.post('/api/app/setup/dismiss')
def dismiss_setup(request: Request):
    request.app.state.writer.call(lambda db: db.set_setting(SETUP_KEY, '1'))
    return {'ok': True}


@router.put('/api/app/data-dir')
def put_data_dir(request: Request, body: dict = Body(...)):
    if not app_paths.FROZEN:
        raise HTTPException(409, "Running from source: the data folder is the repo's data/ (or CM_DATA_DIR).")
    if os.environ.get('CM_DATA_DIR'):
        raise HTTPException(409, 'CM_DATA_DIR is set, so it decides the data folder.')
    raw = str(body.get('path') or '').strip()
    target = Path(raw) if raw else None
    if target is None or not target.is_absolute() or not target.is_dir():
        raise HTTPException(400, 'Pick an existing folder.')
    app_dir = Path(sys.executable).resolve().parent      # the install folder: uninstall removes it
    if target.resolve() == app_dir or app_dir in target.resolve().parents:
        raise HTTPException(400, "Pick a folder outside the app's own folder.")
    if not (target / 'content_manager.db').is_file() and any(target.iterdir()):
        raise HTTPException(400, 'Pick an empty folder, or a Brainamon data folder (it holds content_manager.db).')
    app_paths.set_data_dir(target)
    return _view(request)


@router.post('/api/app/diagnostics')
def export_diagnostics(request: Request):
    """Opt-in: only on the user's click; the zip stays on this PC until they send it themselves."""
    try:
        path = diagnostics.build(reader(request.app.state.db_path), request.app.state.data_dir)
    except OSError as e:
        raise HTTPException(500, f'Could not write the diagnostics file: {e}')
    request.app.state.revealable.add(str(path))
    return {'path': str(path), 'name': path.name}


@router.put('/api/app/autostart')
def put_autostart(request: Request, body: dict = Body(...)):
    try:
        autostart.set_on(bool(body.get('on')))
    except OSError as e:
        raise HTTPException(500, f'Could not change Start with Windows: {e}')
    return _view(request)


@router.put('/api/app/widget')
def put_widget(request: Request, body: dict = Body(...)):
    on = bool(body.get('on'))
    autostart.save_widget_state(enabled=on)
    if on:
        autostart.spawn('--widget')                 # exits at once when a widget is already up
    request.app.state.hub.publish('widget', {'enabled': on})     # a lingering widget hides or shows itself
    if autostart.is_on():
        autostart.set_on(True)                      # Start with Windows follows: --widget or --background
    return _view(request)


def _put_setting(request: Request, key: str, on: bool) -> dict:
    value = '1' if on else '0'
    request.app.state.writer.call(lambda db: db.set_setting(key, value))
    view = _view(request)
    request.app.state.hub.publish('app', {'tray': view['tray'], 'warm': view['warm'], 'notice': view['notice']})
    return view


@router.put('/api/app/tray')
def put_tray(request: Request, body: dict = Body(...)):
    return _put_setting(request, TRAY_KEY, bool(body.get('on')))


@router.post('/api/app/tray/seen')
def post_tray_seen(request: Request):
    request.app.state.writer.call(lambda db: db.set_setting(SEEN_KEY, '1'))
    return {'ok': True}


@router.put('/api/app/warm')
def put_warm(request: Request, body: dict = Body(...)):
    return _put_setting(request, WARM_KEY, bool(body.get('on')))


@router.put('/api/app/notice')
def put_notice(request: Request, body: dict = Body(...)):
    return _put_setting(request, NOTICE_KEY, bool(body.get('on')))


@router.put('/api/app/toasts')
def put_toasts(request: Request, body: dict = Body(...)):
    changes = {k: bool(body[k]) for k in ('on', *CATEGORIES) if k in body}
    request.app.state.writer.call(lambda db: request.app.state.notify.save(db, changes))
    return _view(request)


@router.post('/api/app/toasts/test')
def test_toast(request: Request):
    """The Settings test button: one notification now, whatever the switches say."""
    request.app.state.notify('jobs', 'Brainamon', 'Windows notifications work.', force=True)
    return {'ok': True}


@router.post('/api/app/open')
def open_window():
    """Open (or bring to the front) the main window: from the drop panel and the widget."""
    autostart.spawn()
    return {'ok': True}


@router.post('/api/app/capture')
def capture(request: Request, body: dict = Body(...)):
    """Wiskit's drop panel: "Choose where..." hands what was typed to the main window's Add to Brainamon."""
    text = str(body.get('text') or '').strip()[:200_000]
    if not text:
        raise HTTPException(400, 'Type or drop some text first.')
    request.app.state.pending_capture = text
    request.app.state.hub.publish('capture_open', {})
    autostart.spawn()
    return {'ok': True}


@router.post('/api/app/capture/take')
def take_capture(request: Request):
    """The main window collects the text the panel left (once)."""
    text = getattr(request.app.state, 'pending_capture', '')
    request.app.state.pending_capture = ''
    return {'text': text}


@router.post('/api/app/note')
def note_request(request: Request, body: dict = Body(...)):
    """Wiskit's wheel: Write a note / Record a note. Opens the main window on My Notes (kept until it takes it)."""
    mode = str(body.get('mode') or '')
    if mode not in ('write', 'record'):
        raise HTTPException(400, 'mode must be write or record.')
    request.app.state.pending_note = mode
    request.app.state.hub.publish('note_open', {})
    autostart.spawn()
    return {'ok': True}


@router.post('/api/app/note/take')
def take_note(request: Request):
    """The main window collects the note request the wheel left (once)."""
    mode = getattr(request.app.state, 'pending_note', '')
    request.app.state.pending_note = ''
    return {'mode': mode}


@router.post('/api/app/quit')
def quit_app(request: Request):
    stop = getattr(request.app.state, 'request_exit', None)
    if stop is None:
        raise HTTPException(409, 'This server was not started by the app (py -m server or tests): stop it where it runs.')
    stop()
    return {'ok': True}


@router.post('/api/app/restart')
def restart_app(request: Request):
    """Quit, then start again: a new launch waits for this one to close (server/desktop.py --restart-after)."""
    stop = getattr(request.app.state, 'request_exit', None)
    if stop is None:
        raise HTTPException(409, 'This server was not started by the app (py -m server or tests): restart it where it runs.')
    try:
        autostart.spawn('--restart-after', str(os.getpid()))
    except OSError as e:
        raise HTTPException(500, f'Could not start Brainamon again: {e}')
    stop()
    return {'ok': True}


@router.get('/api/app/update')
def check_update(request: Request):
    return request.app.state.updates.check()


@router.put('/api/app/update/automatic')
def automatic_update(request: Request, body: dict = Body(...)):
    if app_paths.CONTRIBUTOR and body.get('on') is True:
        raise HTTPException(409, 'Official automatic updates are disabled in this build.')
    if type(body.get('on')) is not bool:
        raise HTTPException(422, 'on must be a boolean.')
    from server.updates import AUTO
    request.app.state.writer.call(lambda db: db.set_setting(AUTO, '1' if body['on'] else '0'))
    request.app.state.updates.emit()
    return _view(request)


@router.post('/api/app/update/download')
def download_update(request: Request):
    if app_paths.CONTRIBUTOR:
        raise HTTPException(409, 'Official updates are disabled in this build. Rebuild from source.')
    if not app_paths.FROZEN:
        raise HTTPException(409, 'Running from source: update with git, not the installer.')
    info = request.app.state.updates.check(download=True)
    if info.get('state') in ('checking', 'downloading'):
        return info
    if info.get('error') or not info.get('newer'):
        raise HTTPException(409, info.get('error') or 'Already up to date.')
    return request.app.state.updates.status()


@router.get('/api/app/update/status')
def update_status(request: Request):
    return request.app.state.updates.status()


@router.post('/api/app/update/install')
def install_update(request: Request, body: dict = Body(...)):
    if app_paths.CONTRIBUTOR:
        raise HTTPException(409, 'Official updates are disabled in this build. Rebuild from source.')
    if not app_paths.FROZEN:
        raise HTTPException(409, 'Running from source: update with git, not the installer.')
    stop = getattr(request.app.state, 'request_exit', None)
    if stop is None:
        raise HTTPException(409, 'This server cannot restart. Start the installed app to install updates.')
    state = request.app.state
    gate = state.install_gate
    with gate.lock:
        if gate.closing or gate.active:
            raise HTTPException(409, 'Wait for active requests to finish before installing.')
        gate.closing = True
    updates_reserved = False
    try:
        updates_reserved = state.updates.lock.acquire(blocking=False)
        if not updates_reserved:
            raise HTTPException(409, 'Wait for the update check to finish before installing.')
        from server.routes import settings as settings_routes
        from library import scraper_runtime
        with state.jobs._lock:
            if (state.jobs.current or getattr(state, 'ask_runs', None) or state.scrape_watcher
                    or updater.status()['state'] == 'downloading' or settings_routes.get_tools_install()['state'] == 'running'
                    or scraper_runtime._state and scraper_runtime._state.get('state') == 'installing'):
                raise HTTPException(409, 'Wait for active work to finish before installing.')
            state.jobs._closing = True
        if (state.sync._publishing.locked() or state.sync.st['vault_state'] == 'syncing' or state.sync.st['state'] == 'signing-in'
                or state.sync.recovery.thread and state.sync.recovery.thread.is_alive()):
            raise HTTPException(409, 'Wait for sync to finish before installing.')
        state.sync._closing = True
        state.sync.shutdown()
        state.writer.call(lambda db: None)
        updater.launch(updater.UPDATES / str(body.get('name', '')))
        stop()
    except Exception as e:
        if updates_reserved:
            state.updates.lock.release()
        gate.closing = False
        state.jobs._closing = False
        state.sync._closing = False
        state.sync.boot()
        if isinstance(e, ValueError):
            raise HTTPException(422, str(e))
        from library.drive_client import DriveError
        if isinstance(e, (OSError, DriveError)):
            raise HTTPException(409, 'Update could not start. Outstanding work must stop before retrying.')
        raise
    return {'ok': True}
