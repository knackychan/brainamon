"""The V6 desktop window: start the server on 127.0.0.1 in a thread, then a pywebview (WebView2)
window on it. Run from the repo root:  py -m server.desktop   (run.bat / launch.pyw do this).

Single instance: when the app window is already open, a second launch restores and focuses it and
exits. When a V6 server answers on 127.0.0.1:<port> but no window is open (background mode), this
process only opens a window on it (no second writer).

--widget / --background (Start with Windows, autostart.py): the keeper. The server, the tray icon and
Wiskit (widget.py; withdrawn while his own setting is off) in one process, no main window, until Quit
(POST /api/app/quit, the tray or Wiskit). A plain launch that finds no server starts a keeper first
(--widget --grace --owned), so the server outlives the window: the window process is disposable.
--owned: that keeper ends the app when the window closes while sleep mode and Wiskit are both off.
--panel [--ask] [--attach <id|id>]: Wiskit's drop panel (web/panel.html), a small frameless window
near the widget; one at a time (a second one only brings the first to the front and hands it the
attachments over POST /api/ask/panel). Always there: the widget starts it hidden (--panel --hidden)
and closing hides it again with its WebView2 at rest (PanelApi), so every open is instant. The widget's
dock ghost (desktop/panel_ghost.py) covers a panel that still has to start cold.
--smoke: open the window, wait 3 s, close (planning / CI check).
--restart-after <pid>: POST /api/app/restart; waits for the previous app to close, then a plain launch.

Sleep mode, "Minimize to tray and show Wiskit" (Settings > App, or the tray menu; on by default; DB
setting `minimize_to_tray`, read over the API): minimizing or closing the main window ends this process,
so WebView2 and its processes are gone, and the keeper shows its tray icon and Wiskit (desktop/sleep.py).
The tray icon or Wiskit starts a new window. With "Keep the window warm" (`keep_window_warm`) the window is
only hidden with its WebView2 suspended, and the same clicks show it again at once.
"""
import json
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from core import local_auth
from pathlib import Path

import webview

from core import app_console
from core import app_paths
from desktop import autostart
from desktop import panel_ghost
from desktop import sleep
from desktop import early_splash
from desktop import tray
from core import config
from server import settings

TITLE = sleep.WINDOW_TITLE   # shared with the window lookup used by a second launch
MOBILE_TITLE, MOBILE_W, MOBILE_H = app_paths.APP_NAME + ' (phone)', 412, 915
LEAVING = threading.Event()  # set before this process closes its own window: the close is not a sleep


def _loading_html(t0: int, error: str = '') -> str:
    """The window's first page, before the backend answers: the startup bar of web/public/boot.js
    (inlined: no server to load it from yet), started at t0 (ms since the epoch), or stopped on `error`."""
    for path in (settings.WEB_DIST / 'boot.js', settings.REPO / 'web' / 'public' / 'boot.js'):
        if path.is_file():
            js = path.read_text(encoding='utf-8')
            break
    else:
        js = "document.body.textContent = 'Starting Brainamon…'"
    cfg = json.dumps({'t0': t0, 'error': error}).replace('<', '\\u003c')
    return ('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;'
            'background:#17181b;color:#e8e8e1;font:14px Segoe UI,sans-serif}</style></head><body>'
            f'<script>window.CM_BOOT={cfg}</script><script>{js}</script></body></html>')


# Native file dialogs for the page (plan 12): window.pywebview.api.pick(kind) -> [paths] | null
PICK_TYPES = {
    'csv': ('CSV files (*.csv)',),
    'json': ('JSON files (*.json)',),
    'import': ('Data files (*.csv;*.json)',),
    'image': ('Images (*.png;*.jpg;*.jpeg;*.webp;*.gif)',),
    'video': ('Video files (*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v)', 'All files (*.*)'),
    'cookies': ('Cookies file (*.txt)', 'All files (*.*)'),
    'claude': ('Claude Code (*.exe;*.cmd)', 'All files (*.*)'),
}


class Api:
    """Exposed to the page as window.pywebview.api (pywebview js_api)."""

    def close(self):
        """Close the window (after Settings > App > Quit stopped the server)."""
        _destroy_all()

    def ready(self):
        """The page rendered its first screen."""

    def pick(self, kind: str):
        w = webview.windows[0] if webview.windows else None
        if w is None:
            return None
        if kind == 'folder':
            res = w.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            res = w.create_file_dialog(webview.FileDialog.OPEN, file_types=PICK_TYPES.get(kind, ()))
        return list(res) if res else None


def _running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f'http://{settings.HOST}:{port}/api/health', timeout=0.5) as r:
            return json.loads(r.read()).get('ok') is True
    except Exception:
        return False


def _focus_existing(title: str = TITLE) -> bool:
    """A second launch: restore and bring the open window to the front (sleep.focus)."""
    return sleep.focus(title)


def _wait_for_previous(port: int, timeout: float = 60) -> bool:
    """--restart-after <pid> (POST /api/app/restart): wait until the old server, window and keeper are
    gone, so this launch starts fresh instead of focusing them. False when they are still there."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _running(port) and not sleep.find(TITLE) and not sleep.find(sleep.WIDGET_TITLE):
            return True
        time.sleep(0.25)
    return False


def _destroy_all() -> None:
    LEAVING.set()
    for w in list(webview.windows):
        w.destroy()


def _start_server(port: int):
    """The server in a daemon thread; returns it once it answers, or None if it failed to start."""
    # imported here: a window-only process (the widget owns the server) and the drop panel never
    # start a server and skip about 30 MB of FastAPI + uvicorn + the routes
    import uvicorn
    from server.app import create_app
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=settings.HOST, port=port, log_level='warning'))
    def request_exit():
        # Quit / install an update: stop the server and close this process's window too, so the
        # process ends and the installer can replace its files.
        server.should_exit = True
        _destroy_all()
    app.state.request_exit = request_exit
    t = threading.Thread(target=server.run, name='cm-server', daemon=True)
    t.start()
    deadline = time.time() + 20
    while not server.started:
        if not t.is_alive() or time.time() > deadline:
            print(f'The V6 server did not start on {settings.HOST}:{port}. See error_log.txt.', file=sys.stderr)
            return None
        time.sleep(0.05)
    server.thread = t
    server.app = app
    return server


def _suspend_when_minimized(window) -> None:
    """Main window only: minimized hides the WebView2 control and suspends it (the renderer and GPU
    stop drawing: 0.3 -> 0.0 CPU-s / 10 s, plan 10-footprint A1); restored or maximized shows it again,
    which resumes it. pywebview fires these events on a worker thread and CoreWebView2 may only be
    touched on the UI thread, so the work is Invoked on the form, as pywebview's winforms.py does.
    Each event re-reads the window state on the UI thread, so a quick minimize + restore cannot leave
    the page hidden."""
    def sync():
        form = getattr(window, 'native', None)
        ctl = getattr(getattr(form, 'browser', None), 'webview', None)
        if ctl is None:
            return
        from System import Func, Type
        from System.Windows.Forms import FormWindowState

        def apply():
            if form.WindowState == FormWindowState.Minimized:
                if ctl.Visible:
                    ctl.Visible = False                 # the page turns document.hidden: rest mode
                    core = ctl.CoreWebView2
                    if core is not None:
                        core.TrySuspendAsync()          # needs Visible = False first
            elif not ctl.Visible:
                ctl.Visible = True                      # resumes a suspended WebView2

        try:
            form.Invoke(Func[Type](apply))
        except Exception as exc:
            app_console.emit('error', 'WebView2 suspend / resume failed', level='warning', error=exc)

    if sys.platform != 'win32':
        return
    window.events.minimized += sync
    window.events.restored += sync
    window.events.maximized += sync


def _reload_app(window, app_url: str) -> None:
    """Navigate through the native shell without relying on the page's controls."""
    try:
        # A fresh URL forces navigation even when WebView2 already displays the app URL.
        target = local_auth.browser_url(f'{app_url}?reload={time.time_ns()}')
        # shortcut: a hung renderer needs the window reopened; recreate it if reload must cover renderer hangs.
        window.load_url(target)
    except Exception as exc:
        _log_crash(exc)
        window.create_confirmation_dialog('Could not reload app',
                                          'Please close and reopen Brainamon. Details are in the error log.')


def _configure_webview(window, *, block_history: bool = False, app_url: str | None = None) -> None:
    """Paste (navigator.clipboard.readText) is allowed without WebView2's per-run "see text and images
    copied to the clipboard" prompt: this is the app's own window on its own 127.0.0.1 page, not a site.
    Only the clipboard-read permission, only for that origin; every other permission keeps WebView2's
    default. The handlers are added once, when the first page has loaded (CoreWebView2 exists by then), on
    the UI thread, and stay for every later navigation. The desktop shell can also block browser history:
    its startup page cannot resume the app, and its workspaces are not browser history entries.
    With app_url, an unexpected return to that page gets one native recovery attempt per window."""
    if sys.platform != 'win32':
        return
    done = []
    app_seen = False
    recovered = False

    def hook(*_):
        form = getattr(window, 'native', None)
        ctl = getattr(getattr(form, 'browser', None), 'webview', None)
        if ctl is None or done:
            return
        from System import Func, Type

        def apply():
            core = ctl.CoreWebView2
            if core is None or done:
                return
            from Microsoft.Web.WebView2.Core import (CoreWebView2NavigationKind,
                                                    CoreWebView2PermissionKind, CoreWebView2PermissionState)

            def on_permission(sender, args):
                if args.PermissionKind == CoreWebView2PermissionKind.ClipboardRead                         and str(args.Uri).startswith(f'http://{settings.HOST}:'):
                    args.State = CoreWebView2PermissionState.Allow
            core.PermissionRequested += on_permission
            done.append(on_permission)               # keeps the handler alive
            if block_history:
                def on_navigation(sender, args):
                    if args.NavigationKind == CoreWebView2NavigationKind.BackOrForward:
                        args.Cancel = True
                core.NavigationStarting += on_navigation
                done.append(on_navigation)
            if app_url:
                def on_completed(sender, args):
                    nonlocal app_seen, recovered
                    if not args.IsSuccess:
                        return
                    source = str(sender.Source)
                    if source.split('#', 1)[0].split('?', 1)[0] == app_url:
                        app_seen = True
                    elif app_seen and not recovered and (source == 'about:blank' or source.startswith('data:text/html')):
                        recovered = True
                        # Defer navigation until WebView2 has finished dispatching this event.
                        form.BeginInvoke(Func[Type](lambda: _reload_app(window, app_url)))
                core.NavigationCompleted += on_completed
                done.append(on_completed)

        try:
            form.Invoke(Func[Type](apply))
        except Exception as exc:
            app_console.emit('error', 'WebView2 configuration failed', level='warning', error=exc)

    window.events.loaded += hook


def _sleep(window, base: str) -> None:
    """Main window only, after _suspend_when_minimized (an event runs its handlers in order, so the WebView2
    is already hidden and suspended). With "Minimize to tray and show Wiskit" on, minimize and the X button
    put the app to sleep (desktop/sleep.py): this process closes, or with "Keep the window warm" the form
    is only hidden. The keeper (another process) shows the tray icon and Wiskit meanwhile and brings the
    window back (sleep.focus, which finds hidden windows) or starts a new one. Preferences are read fresh
    over the API each time (Settings may have changed them a second ago)."""
    hidden = []                       # [True] while the form is hidden by us (warm)
    # The loading window may have been shown and minimized before these handlers attach.
    shown = [True] if window.events.shown.is_set() or sleep.window_state(TITLE) == 'awake' else []

    def prefs():
        try:
            view = tray.call(base, 'GET', '/api/app')
            return bool(view.get('tray')), bool(view.get('warm'))
        except (OSError, ValueError):
            return None               # no server: nothing to sleep into

    def keeper():
        if not sleep.find(sleep.WIDGET_TITLE):
            autostart.spawn('--widget')     # a server started elsewhere (py -m server): someone must host the icon

    def hide():
        """Worker thread (the minimized event): the form out of sight, WebView2 still suspended."""
        from System import Func, Type
        from System.Windows.Forms import FormWindowState
        form = window.native

        def apply():
            if form.WindowState == FormWindowState.Minimized and not hidden:   # not restored meanwhile
                form.Hide()
                hidden.append(True)
        try:
            form.Invoke(Func[Type](apply))
        except Exception as exc:
            app_console.emit('error', 'Minimize to tray failed', level='warning', error=exc)

    def minimized():
        if not shown:                   # Windows opened it minimized (the keeper had the foreground), not the user
            _raise(window)
            return
        if hidden or LEAVING.is_set():  # a minimize fired while hidden would show it again
            return
        p = prefs()
        act = sleep.on_minimize(*p) if p else 'normal'
        if act == 'normal' or sleep.window_state(TITLE) != 'asleep':      # restored while we asked
            return
        keeper()
        if act == 'hide':
            hide()
        else:
            app_console.emit('log', 'Brainamon is asleep: the window closed, the tray icon brings it back')
            _destroy_all()

    def closing():
        """UI thread (FormClosing, also for our own destroy). False keeps the window (warm: hidden)."""
        if LEAVING.is_set():
            return None
        p = prefs()
        if p is None or sleep.on_close(*p) == 'close':
            if p and p[0]:
                keeper()
            return None
        keeper()
        from System.Windows.Forms import FormWindowState
        window.native.WindowState = FormWindowState.Minimized       # the minimized event hides it
        return False

    def on_screen():
        if not shown and sleep.window_state(TITLE) == 'awake':
            shown.append(True)

    def back():
        on_screen()
        # sleep.focus shows the window with ShowWindow, which leaves WinForms thinking the form is still
        # hidden (Form.Visible False, so the WebView2 child reads as hidden too): tell it.
        if hidden:
            hidden.clear()
            try:
                from System import Func, Type
                window.native.Invoke(Func[Type](lambda: window.native.Show()))
            except Exception as exc:
                app_console.emit('error', 'Restore from the tray failed', level='warning', error=exc)

    window.events.shown += on_screen          # after _show_front's handler; restored / maximized count too
    window.events.minimized += minimized
    window.events.closing += closing
    window.events.restored += back
    window.events.maximized += back
    if sleep.window_state(TITLE) == 'asleep':
        minimized()


def _close_when_server_gone(port: int) -> None:
    """A window-only process (the widget owns the server) is never told about Quit: the widget's menu
    stops the server and the widget, not this window, and the tray icon would stay up on a dead app.
    So watch the server and close the windows once it has been gone for about 6 s."""
    def watch():
        misses = 0
        while True:
            time.sleep(2)
            misses = 0 if _running(port) else misses + 1
            if misses >= 3:
                _destroy_all()
                return
    threading.Thread(target=watch, name='server-watch', daemon=True).start()


def _raise(window) -> None:
    """Restore the main window if it is minimized and bring it to the front (any thread)."""
    form = getattr(window, 'native', None)
    if form is None:
        return
    from System import Func, Type
    from System.Windows.Forms import FormWindowState

    def apply():
        if form.WindowState == FormWindowState.Minimized:
            form.WindowState = FormWindowState.Maximized
        form.TopMost = True            # the topmost flip raises it without needing foreground rights
        form.TopMost = False
        form.Activate()

    try:
        form.Invoke(Func[Type](apply))
    except Exception as exc:
        app_console.emit('error', 'Bring the window to the front failed', level='warning', error=exc)


def _show_front(window) -> None:
    """First show of the main window: when the keeper was spawned a moment earlier it holds the
    foreground, so Windows opens this window behind everything (a taskbar button, nothing on screen).
    Restore it if it came up minimized, and bring it to the front. That minimize can also arrive after
    this handler ran: _sleep then raises the window again instead of putting it to sleep."""
    if sys.platform == 'win32':
        window.events.shown += lambda: _raise(window)


PANEL_TITLE, PANEL_W, PANEL_H = panel_ghost.PANEL_TITLE, panel_ghost.PANEL_W, panel_ghost.PANEL_H


def _front(title: str) -> None:
    """Bring a shown window to the front (the clicked process allowed it: autostart.allow_foreground)."""
    if sys.platform == 'win32':
        import ctypes
        hwnd = sleep.find(title)
        if hwnd:
            ctypes.windll.user32.SetForegroundWindow(hwnd)


def _webview_rest(window, rest: bool) -> None:
    """The hidden panel's WebView2 at rest, as _suspend_when_minimized does for the main window: control
    hidden (the page reads document.hidden), memory target low, suspended; awake again before it shows.
    CoreWebView2 may only be touched on the UI thread, so the work is Invoked on the form."""
    form = getattr(window, 'native', None)
    ctl = getattr(getattr(form, 'browser', None), 'webview', None)
    if ctl is None:
        return
    from System import Func, Type

    def apply():
        core = ctl.CoreWebView2
        from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel as Level
        if rest:
            ctl.Visible = False
            if core is not None:
                core.MemoryUsageTargetLevel = Level.Low
                core.TrySuspendAsync()              # needs Visible = False first
        else:
            ctl.Visible = True                      # resumes a suspended WebView2
            if core is not None:
                core.MemoryUsageTargetLevel = Level.Normal
    try:
        form.Invoke(Func[Type](apply))
    except Exception as exc:
        app_console.emit('error', 'Panel WebView2 rest / wake failed', level='warning', error=exc)


class PanelApi(Api):
    """The drop panel's js_api. Always there (Fred: a cold open every time is too slow and looks heavy):
    the widget starts it hidden (--panel --hidden) and closing hides it again with its WebView2 at rest,
    so every open (a panel_attach event, read by _panel_events) is instant. It lives as long as its
    server. Its state is private: pywebview hands the page every public attribute."""
    def __init__(self, hidden: bool = False):
        self._window, self._hidden = None, hidden

    def close(self):
        self._hidden = True
        self._window.hide()
        _webview_rest(self._window, True)

    def reopen(self, ids=()):
        if self._hidden:
            _webview_rest(self._window, False)
        self._hidden = False
        self._window.show()
        _front(PANEL_TITLE)
        # the page was suspended and may have missed panel_attach: hand it the ids (it skips ones it has)
        self._window.evaluate_js(f'window.panelAttach?.({json.dumps(list(ids))})')

    def _loaded(self):
        if self._hidden:                            # started hidden: rest once the page is in
            _webview_rest(self._window, True)


def _panel_watch(lines, on_attach) -> None:
    """Read a server event stream (bytes lines); on_attach(ids) for every panel_attach event."""
    event = ''
    for raw in lines:
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        if not line:
            event = ''                 # a blank line ends the event
        elif line.startswith('event:'):
            event = line[6:].strip()
        elif line.startswith('data:') and event == 'panel_attach':
            try:
                ids = json.loads(line[5:]).get('ids') or []
            except ValueError:
                ids = []
            on_attach([str(i) for i in ids])


def _panel_events(port: int, api: PanelApi) -> None:
    """The panel process's own event reader (a daemon thread): panel_attach wakes and shows the window
    with the ids. A panel whose server is gone exits."""
    while True:
        try:
            req = urllib.request.Request(f'http://{settings.HOST}:{port}/api/events', headers=local_auth.headers(port, {'Accept': 'text/event-stream'}))
            with urllib.request.urlopen(req, timeout=120) as resp:
                _panel_watch(resp, api.reopen)
        except Exception:
            pass
        if not _running(port):
            api._window.destroy()
            return
        time.sleep(2)


def _panel(port: int, ask: bool, attach: str = '', hidden: bool = False) -> int:
    """The drop panel: bottom right, above the widget; the server is the widget's (or started here).
    attach: Ask attachment ids joined with '|' (plan 11), shown as chips in the panel. hidden: start it
    hidden and at rest (the widget's prewarm), the first open then only shows it."""
    if autostart.allow_foreground(PANEL_TITLE):     # open, or hidden: it shows itself on panel_attach
        if hidden:
            return 0                                # a prewarm with a panel already there: nothing to do
        try:
            req = urllib.request.Request(f'http://{settings.HOST}:{port}/api/ask/panel', method='POST',
                                         data=json.dumps({'ids': attach.split('|') if attach else []}).encode('utf-8'),
                                         headers=local_auth.headers(port, {'X-CM': '1', 'Content-Type': 'application/json'}))
            urllib.request.urlopen(req, timeout=3).close()
        except Exception:
            pass
        return 0
    server = None if _running(port) else _start_server(port)
    if server is None and not _running(port):
        return 1
    x = y = None
    if sys.platform == 'win32':
        import ctypes
        sw, sh = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        x, y, _, _ = panel_ghost.panel_rect(sw, sh)      # the widget's dock ghost uses the same spot
    storage = app_paths.cache_dir('webview')
    query = urllib.parse.urlencode({**({'ask': '1'} if ask else {}), **({'attach': attach} if attach else {})})
    api = PanelApi(hidden)
    api._window = webview.create_window(PANEL_TITLE, local_auth.browser_url(f'http://{settings.HOST}:{port}/panel.html' + (f'?{query}' if query else '')),
                                       width=PANEL_W, height=PANEL_H, x=x, y=y, frameless=True, on_top=True,
                                       resizable=False, hidden=hidden, background_color='#131417', js_api=api)
    api._window.events.loaded += api._loaded
    _configure_webview(api._window)
    threading.Thread(target=_panel_events, args=(port, api), name='panel-events', daemon=True).start()
    try:
        webview.start(private_mode=False, storage_path=str(storage))
    finally:
        if server is not None:
            server.should_exit = True
    return 0


def _keeper(port: int, grace: bool, owned: bool) -> int:
    """--widget / --background: the server (unless one answers already), the tray icon and Wiskit."""
    if sleep.find(sleep.WIDGET_TITLE):
        return 0
    server = None if _running(port) else _start_server(port)
    if server is None and not _running(port):
        return 1
    from desktop import widget
    w = widget.Widget(on_quit=(lambda: setattr(server, 'should_exit', True)) if server else None,
                      off=not autostart.widget_on(), grace=grace, owned=owned)
    if server is not None:
        # runs on a server thread: only flags; the widget closes itself on its next tick
        server.app.state.request_exit = lambda: (setattr(server, 'should_exit', True), w.request_exit())
    app_console.emit('log', 'Brainamon keeper started (server, tray icon, Wiskit)')
    w.run()
    if server is not None:
        server.should_exit = True
        time.sleep(0.5)                 # no longer listening: the window's close check finds no server and closes
        sleep.close_window(TITLE)       # Quit: the window and the panel now, not after their 6 s server watch
        sleep.close_window(PANEL_TITLE)
        server.thread.join(5)
    return 0


def _log_crash(exc: BaseException) -> None:
    try:
        with open(app_paths.ERROR_LOG, 'a', encoding='utf-8') as fh:
            fh.write('\n----- V6 unhandled exception -----\n')
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    except Exception:
        pass


def main() -> int:
    if '--dependency-report' in sys.argv:
        from PIL import __version__ as pillow_version, features
        import pypdf
        print(json.dumps({'Pillow': pillow_version, 'pypdf': pypdf.__version__, 'OpenJPEG': features.version_codec('jpg_2000')}))
        return 0
    config.load_env()
    port = settings.PORT
    url = f'http://{settings.HOST}:{port}/'
    smoke = '--smoke' in sys.argv     # planning / CI check: open, wait 3 s, close
    if '--background' in sys.argv and sys.platform != 'win32':
        if _running(port):
            return 0
        server = _start_server(port)
        if server is None:
            return 1
        server.thread.join()          # until Quit (POST /api/app/quit)
        return 0
    if '--restart-after' in sys.argv and not _wait_for_previous(port):
        print('Restart: the previous Brainamon did not close within 60 s.', file=sys.stderr)
        return 1
    if '--widget' in sys.argv or '--background' in sys.argv:
        return _keeper(port, grace='--grace' in sys.argv, owned='--owned' in sys.argv)
    if '--panel' in sys.argv:
        attach = sys.argv[sys.argv.index('--attach') + 1] if '--attach' in sys.argv[:-1] else ''
        return _panel(port, '--ask' in sys.argv, attach, '--hidden' in sys.argv)
    # --mobile (run-mobile.bat): the phone page (/mobile.html) in a phone-sized window beside the main
    # window, to check the phone UI without building the APK. Same WebView2 engine as the Android
    # WebView; mouse instead of touch, no native plugin, no share target. Not a second main window:
    # no sleep mode and no focus of an existing window.
    mobile = '--mobile' in sys.argv
    if not smoke and not mobile and _focus_existing():
        return 0
    server = None
    storage = app_paths.cache_dir('webview')
    t0 = early_splash.started_at()   # one clock from the first splash through the app page (?boot=)
    if mobile:
        window = webview.create_window(MOBILE_TITLE, html=_loading_html(t0), width=MOBILE_W, height=MOBILE_H,
                                       min_size=(320, 480), background_color='#17181b', js_api=Api(), text_select=True)
    else:
        window = webview.create_window(TITLE, html=_loading_html(t0), width=1600, height=1000, min_size=(360, 560), maximized=True,
                                       background_color='#17181b', js_api=Api(), text_select=True)
    early_splash.handoff(window)
    _suspend_when_minimized(window)
    _configure_webview(window, block_history=not mobile, app_url=None if mobile else url)
    if not smoke:
        _show_front(window)

    def boot():
        nonlocal server
        if not smoke and not _running(port) and sys.platform == 'win32':
            autostart.spawn('--widget', '--grace', '--owned')   # the keeper owns the server
            deadline = time.time() + 20
            while not _running(port) and time.time() < deadline and window in webview.windows:
                time.sleep(0.2)
        if window not in webview.windows:
            return
        if not _running(port):
            try:
                server = _start_server(port)
            except Exception as exc:  # create_app failed: say so instead of a bar that never ends
                _log_crash(exc)
            if server is None:
                if window in webview.windows:
                    window.load_html(_loading_html(t0, f'Could not start the backend. Details are in {app_paths.ERROR_LOG}'))
                return
        if not smoke and server is None:  # a fallback server in this process cannot sleep
            _close_when_server_gone(port)
            if sys.platform == 'win32' and not mobile:
                _sleep(window, f'http://{settings.HOST}:{port}')
        if window in webview.windows:
            if mobile:
                window.load_url(local_auth.browser_url(f'{url}mobile.html'))
            else:
                window.load_url(local_auth.browser_url(f'{url}?boot={t0}-{int(time.time() * 1000)}'))
        if smoke:
            time.sleep(3)
            _destroy_all()

    try:
        webview.start(boot, private_mode=False, storage_path=str(storage))
    finally:
        if server is not None:
            app_console.emit('log', 'V6 window closed: stopping the server')
            server.should_exit = True
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        _log_crash(exc)
        raise
