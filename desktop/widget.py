"""Wiskit on the desktop (projects/desktop-app plan 07): a tiny always-on-top sprite window.

    py -m desktop.widget         from source, against a running server (run.bat or py -m server)
    Brainamon.exe --widget  installed: the server and this widget in one process (server/desktop.py)

tkinter (stdlib): a borderless, topmost window whose key colour (#ff00ff) is transparent, one Label
whose image is swapped by one after() timer at the state's frame rate. Frames come from the sprite
sheet that wiskit_sprite.py renders (web/public/wiskit/sheet.png, copied into web/dist by Vite).

The widget never opens SQLite: its state comes from the server's event stream (GET /api/events,
read on a daemon thread) and every action is an HTTP call or a new process.
  - a job or a Wiskit answer running -> work; one just finished -> done for 3 s; then sleep
  - pointer over Wiskit -> idle (awake); the wheel open -> listen; something dragged over him -> receive
Left click: the action wheel (widget_wheel.py; plan 07b): Ask Wiskit, Drop panel, Write a note, Record a note, Open Brainamon, Quit Wiskit. Drag: move (saved to <app home>/widget.json).
Right click: menu. Dragging files, a link or text over him (plan 11) pops the drop ring: Inbox (filed
like the drop panel does, server/routes/inbox.py: images -> the screenshot digest on the Inbox note,
other files -> data/inbox, a link -> a library item, text -> the Inbox note), Add to library (a link),
Analyze video (one video file), Ask Wiskit (attached to a question in the drop panel; a video is
analyzed first). Dropping on Wiskit instead of a bubble asks which.

This process is also the keeper of sleep mode (desktop/sleep.py): it hosts the tray icon (desktop/tray.py)
and, with "Minimize to tray and show Wiskit" on, shows Wiskit and the icon only while the main window is
minimized, hidden or closed (polled once a second). Wiskit also follows his own setting (widget.json).

Activity while the window sleeps (projects/wiskit-activity): the `hello`, `job`, `cloud`, `ask_run` and
`ask_saved` events feed desktop/activity.py. A dot beside Wiskit (widget_wheel.Dot) pulses while a job, an
answer, the Drive upload or the vault sync runs and shows "!" while a request waits for a click (a click on it
opens Brainamon); hovering him or the dot shows the card (widget_wheel.Card) with a "Last:" line kept until the
window is opened; the tray tooltip names the card's first line.
"""
import base64
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from core import local_auth
from pathlib import Path

from core import app_paths
from desktop import activity
from desktop import autostart
from desktop import dropwin
from desktop import panel_ghost
from desktop import sleep
from desktop import tray
from desktop import widget_wheel

HOST = '127.0.0.1'
PORT = int(os.environ.get('CM_PORT', app_paths.DEFAULT_PORT))
DONE_S = 3.0
GONE_AFTER_S = 15    # a widget that does not own the server leaves once the server has been gone this long
DRAG_PX = 4          # a press that moves less than this is a click
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
MAX_FILE_BYTES = 200 * 1024 * 1024      # knowledge/inbox.py refuses bigger files
LEAVE_GRACE_MS = 250    # the drag left Wiskit and the ring: close the ring unless it comes back
CARD_DELAY_MS = 400     # the pointer rests on Wiskit or the dot this long before the activity card opens
PUMP_MS, PUMP_DRAG_MS = 60, 16      # how often the drop callbacks queued by dropwin run (idle / while dragging)
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}           # = server/routes/io.py VIDEO_EXTS
ATTACH_EXTS = {'.txt', '.md', '.csv', '.json', '.py', '.js', '.ts', '.html', '.css', '.xml', '.yaml', '.yml',
               '.log', '.ini', '.png', '.jpg', '.jpeg', '.webp', '.gif'}   # = knowledge/attachments.py (tests check)


_URL = re.compile(r'^https?://\S+$', re.I)
_FIND = re.compile(r'https?://[^\s<>"\']+', re.I)
_BARE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24})(:\d{1,5})?([/?#]\S*)?$', re.I)
_FILE_ENDINGS = {'md', 'txt', 'py', 'js', 'ts', 'json', 'csv', 'html', 'css', 'xml', 'yaml', 'yml', 'log', 'ini',
                 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'pdf', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'zip',
                 'exe', 'doc', 'docx'}
_TRACKING = re.compile(r'^(utm_\w+|igsh|igshid|si|mibextid|fbclid|rdid|share_id|feature)$', re.I)


def clean_link(url: str) -> str:
    """= knowledge/inbox.py clean_link(): no trailing punctuation, no share tracking parameters."""
    url = re.sub(r'[.,;:!?\'"]+$', '', url)
    if url.endswith(')') and '(' not in url:
        url = url.rstrip(')')
    base, hash_, frag = url.partition('#')
    path, q, query = base.partition('?')
    if q:
        keep = [p for p in query.split('&') if p and not _TRACKING.match(p.split('=', 1)[0])]
        base = path + ('?' + '&'.join(keep) if keep else '')
    return base + hash_ + frag


def _bare(t: str) -> str | None:
    m = _BARE.match(t)
    if not m or (m.group(1).lower() in _FILE_ENDINGS and not t.lower().startswith('www.') and not m.group(3)):
        return None
    return clean_link('https://' + t)


def link(text: str) -> str | None:
    """= knowledge/inbox.py link() (the widget imports only core; tests/fixtures/share_links.json
    checks they agree): the first http(s)://... in the text, cleaned; a bare address that is the
    whole text with https:// in front; else None."""
    t = (text or '').strip()
    m = _FIND.search(t)
    if m:
        return clean_link(m.group(0))
    return _bare(t)


def is_url(text: str) -> bool:
    """The whole text is one link (a dropped paragraph that only contains a link stays text)."""
    t = (text or '').strip()
    return bool(_URL.match(t)) or _bare(t) is not None


def api(path: str, body=None, raw: bytes | None = None, timeout: float = 60):
    """POST to the local server; returns the JSON answer, raises RuntimeError with the server's detail."""
    data = raw if raw is not None else json.dumps(body if body is not None else {}).encode('utf-8')
    ctype = 'application/octet-stream' if raw is not None else 'application/json'
    req = urllib.request.Request(f'http://{HOST}:{PORT}{path}', data=data, method='POST',
                                 headers=local_auth.headers(PORT, {'X-CM': '1', 'Content-Type': ctype}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get('detail')
        except ValueError:
            detail = None
        raise RuntimeError(detail or f'HTTP {e.code}') from None
    except OSError:
        raise RuntimeError('Brainamon is not answering. Is it running?') from None


TRIM_AFTER_S = 20       # asleep this long -> hand the startup / last-job pages back to Windows


def trim_memory() -> None:
    """Once per sleep: release this process's working set (EmptyWorkingSet). Pages an asleep Wiskit and
    an idle server do not touch stay out of RAM; anything needed later faults back in."""
    if sys.platform == 'win32':
        import ctypes
        try:
            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = ctypes.c_void_p          # a 64-bit pseudo handle, not an int
            psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
            psapi.EmptyWorkingSet(k32.GetCurrentProcess())
        except (OSError, AttributeError):
            pass


def on_screen(x: int, y: int, w: int, h: int, desk: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
    """Keep a saved position on the desktop as it is now (a second screen may be unplugged)."""
    if desk is None:
        if sys.platform != 'win32':
            return x, y
        import ctypes
        m = ctypes.windll.user32.GetSystemMetrics          # the virtual screen: every monitor
        desk = (m(76), m(77), m(76) + m(78), m(77) + m(79))
    left, top, right, bottom = desk
    return min(max(x, left), right - w), min(max(y, top), bottom - h)


def drop_actions(kind: str, payload) -> list[str]:
    """The drop bubbles for what is dragged, in ring order (spec 11, decision 2)."""
    acts = ['inbox']
    if kind == 'url' or (kind == 'text' and is_url(payload)):
        acts.append('library')
    if kind != 'files':
        return acts + ['ask']
    exts = [Path(p).suffix.lower() for p in payload]
    if len(exts) == 1 and exts[0] in VIDEO_EXTS:
        return acts + ['video', 'ask']
    if exts and all(e in ATTACH_EXTS for e in exts):
        acts.append('ask')
    return acts


def describe_drop(kind: str, payload) -> str:
    """One line for the choice bubble: what was dropped."""
    if kind == 'files':
        names = [Path(p).name for p in payload]
        head = ', '.join(names[:3]) + (f' and {len(names) - 3} more' if len(names) > 3 else '')
        return f'{len(names)} file{"s" * (len(names) > 1)}: {head}'
    if kind == 'url' or is_url(payload):
        return 'a link: ' + payload.strip()[:60]
    return 'some text: ' + ' '.join(payload.split())[:60]


def sort_files(paths: list[str]) -> tuple[list[Path], list[Path], list[str]]:
    """Dropped paths -> (images for the digest, other files for data/inbox, reasons skipped)."""
    images, others, skipped = [], [], []
    for s in paths:
        p = Path(s)
        if not p.is_file():
            skipped.append(f'{p.name}: folders are not filed')
        elif p.stat().st_size > MAX_FILE_BYTES:
            skipped.append(f'{p.name}: over 200 MB')
        else:
            (images if p.suffix.lower() in IMAGE_EXT else others).append(p)
    return images, others, skipped


def sheet_path() -> Path:
    for p in (app_paths.BUNDLE / 'web' / 'dist' / 'wiskit' / 'sheet.png',
              app_paths.BUNDLE / 'web' / 'public' / 'wiskit' / 'sheet.png'):
        if p.exists():
            return p
    from desktop import wiskit_sprite                                  # first run without a built sheet
    p = app_paths.HOME / 'wiskit' / 'sheet.png'
    legacy = app_paths.HOME / 'jarvis' / 'sheet.png'
    if not p.exists() and legacy.exists():
        return legacy
    if not p.exists():
        wiskit_sprite.render_sheet(p)
    return p


TITLE = sleep.WIDGET_TITLE     # the widget window's title: server/desktop.py looks for it (one widget only)
PANEL_TITLE = panel_ghost.PANEL_TITLE  # one definition, shared with server/desktop.py (tests check)
PREWARM_WAIT_S = 10            # a hidden panel started this recently is still coming up: wait for it


class Widget:
    """on_quit: stops this process's server (None: the server is another process's). off: Wiskit's own
    setting is off (he stays withdrawn; the process still keeps the server and the tray icon). grace:
    started by a window that is still opening: Wiskit and the icon wait for it (sleep.GRACE_S). owned:
    started by that window, so it ends the app when the window closes and nothing else shows."""

    def __init__(self, on_quit=None, off: bool = False, grace: bool = False, owned: bool = False):
        self.on_quit = on_quit
        self.root = tk.Tk()
        self.root.withdraw()
        idx = json.loads(sheet_path().with_suffix('.json').read_text(encoding='utf-8'))
        cw, ch = idx['cell']
        self.scale, key = idx['scale'], idx['key']
        sheet = tk.PhotoImage(file=str(sheet_path()))
        self.frames: dict[str, list[tk.PhotoImage]] = {}
        self.fps: dict[str, int] = {}
        for name, s in idx['states'].items():
            row = []
            for i in range(s['frames']):
                f = tk.PhotoImage()
                f.tk.call(f, 'copy', sheet, '-from', i * cw, s['row'] * ch, (i + 1) * cw, (s['row'] + 1) * ch, '-zoom', self.scale)
                row.append(f)
            self.frames[name], self.fps[name] = row, s['fps']
        self.w, self.h = cw * self.scale, ch * self.scale
        bounds = idx['states']['listen'].get('bounds', idx.get('bounds', [0, 0, cw, ch]))
        self.wheel_x, self.wheel_y, self.wheel_radius = widget_wheel.sprite_geometry(bounds, self.scale)

        r = self.root
        r.title(TITLE)
        r.overrideredirect(True)
        r.attributes('-topmost', True)
        r.configure(bg=key)
        r.wm_attributes('-transparentcolor', key)
        self.label = tk.Label(r, bd=0, bg=key, image=self.frames['sleep'][0], cursor='hand2')
        self.label.pack()
        st = autostart.widget_state()
        x = st.get('x', r.winfo_screenwidth() - self.w - 24)
        y = st.get('y', r.winfo_screenheight() - self.h - 72)
        x, y = on_screen(x, y, self.w, self.h)
        r.geometry(f'{self.w}x{self.h}+{x}+{y}')

        self.state, self.frame, self.hover, self.job, self.done_until = 'sleep', 0, False, False, 0.0
        self.press, self.off = None, off
        self.notice = False                                                 # the `tray_notice` setting: say where the window went
        self.first_note = False                                             # not told yet where the window goes: once, whatever `notice` says
        self.pref, self.warm = None, False                                  # GET /api/app, then `app` events
        self.grace_until = time.time() + sleep.GRACE_S if grace else 0.0
        self.owned = owned
        self.opening_until = 0.0                                            # open_app started a window: do not quit
        self.last_state = 'gone'                                            # the window's state on the last _watch
        self.tray = tray.Tray(f'http://{HOST}:{PORT}', on_open=self.open_app, on_quit=self.request_quit)
        self.tray_on, self.tray_lock = False, threading.Lock()
        self.panel_hidden_since = None
        self.wheel, self.wheel_closed_at, self.dragging, self.busy = None, 0.0, False, 0
        self.ring, self.close_job, self.pending_ask = None, None, None     # plan 11: drop ring, video then ask
        self.ghost = None                                                   # panel_ghost.Ghost while the panel starts
        self.prewarm_at = 0.0                                               # when _prewarm started the hidden panel
        self.exit_requested = False
        self.sleep_since, self.trimmed = time.time(), False
        anchor = lambda: (self.root.winfo_x() + self.w // 2, self.root.winfo_y())     # his centre x, top y
        self.bubble = widget_wheel.Bubble(r, anchor, on_open=lambda: self._hover_card(False))
        # projects/wiskit-activity: the latest snapshots (hello, job, cloud, ask_run), the "Last:" line, the tooltip
        self.jobs_snap, self.cloud, self.asks, self.last, self.tip = {}, {}, 0, '', activity.TIP
        self.card, self.card_job = widget_wheel.Card(r, anchor), None
        self.dot = widget_wheel.Dot(r, self._bg_open, self._hover_card)
        self.label.bind('<ButtonPress-1>', self._press)
        self.label.bind('<B1-Motion>', self._drag)
        self.label.bind('<ButtonRelease-1>', self._release)
        self.label.bind('<Button-3>', self._menu)
        self.label.bind('<Enter>', lambda e: self._set_hover(True))
        self.label.bind('<Leave>', lambda e: self._set_hover(False))
        self.menu = tk.Menu(r, tearoff=0)
        self.menu.add_command(label='Open Brainamon', command=self._bg_open)
        self.menu.add_command(label='Ask Wiskit...', command=lambda: self._open_panel(True))
        self.menu.add_separator()
        self.menu.add_command(label='Quit Brainamon', command=self.quit)

        threading.Thread(target=self._events, name='widget-events', daemon=True).start()
        hidden = self.off or grace
        if hidden:
            r.attributes('-alpha', 0.0)       # mapped once (the drop target needs its frame), never seen
        r.deiconify()
        r.update_idletasks()
        self.drop_target = dropwin.register([int(r.wm_frame(), 16), self.label.winfo_id()],
                                            self._drag_enter, self._drag_leave, self._dropped_at, self._drag_over)
        if hidden:
            r.withdraw()
            r.attributes('-alpha', 1.0)
        self._pump()
        self._tick()
        self._watch()

    # ── animation: one timer; a tick is one image swap ──
    def _want(self) -> str:
        if self.dragging:
            return 'receive' if 'receive' in self.frames else 'listen'
        if self.wheel:
            return 'listen'
        if self.job or self.busy or self.asks:
            return 'work'
        if time.time() < self.done_until:
            return 'done'
        return 'idle' if self.hover else 'sleep'

    def _tick(self):
        if self.exit_requested:                     # Quit from elsewhere (set on the server thread)
            self.root.destroy()
            return
        if self.root.state() == 'withdrawn':        # hidden (turned off, or the window is up): no frames at all
            self.root.after(1000, self._tick)
            return
        want = self._want()
        if want != self.state:
            self.state, self.frame = want, 0
            if want == 'sleep':
                self.sleep_since = time.time()
        if self.state == 'sleep' and not self.trimmed and time.time() - self.sleep_since > TRIM_AFTER_S:
            self.trimmed = True
            trim_memory()
        elif self.state != 'sleep':
            self.trimmed = False
        seq = self.frames[self.state]
        self.label.configure(image=seq[self.frame % len(seq)])
        self.frame += 1
        self.root.after(int(1000 / self.fps[self.state]), self._tick)

    def _set_hover(self, on: bool):
        self.hover = on
        if on and sleep.lazy_panel(self.pref, self.warm):
            self._prewarm()                 # asleep: the panel starts when he is about to be used
        self._hover_card(on)

    # ── sleep mode: Wiskit and the tray icon follow the main window (desktop/sleep.py) ──
    def _watch(self):
        if self.exit_requested:
            return
        now = time.time()
        state = sleep.window_state()
        if state == 'awake':
            self.grace_until = 0.0
            if self.last:                   # the window is up: its rail shows what ended, the "Last:" line goes
                self.last = ''
                self._show_activity()
        if state != 'gone':
            self.opening_until = 0.0        # the window open_app started is up: focus() finds it from now on
        in_grace = now < self.grace_until
        wiskit, icon = sleep.keeper_view(self.pref, not self.off, state, in_grace)
        self._show_wiskit(wiskit)
        if icon != self.tray_on:
            self.tray_on = icon
            first = self.first_note
            note = sleep.tray_note(not self.off, first) if sleep.announce(self.last_state, icon, self.notice, first) else None
            if note and first:
                self.first_note = False
                threading.Thread(target=self._note_seen, name='widget-note-seen', daemon=True).start()
            threading.Thread(target=self._sync_tray, args=(note,), name='widget-tray', daemon=True).start()
        closed = self.last_state != 'gone' and state == 'gone'
        self.last_state = state
        if now >= self.opening_until and sleep.owner_should_quit(self.owned, in_grace, state, self.pref, not self.off):
            self.quit()
            return
        self._close_idle_panel(now, closed)
        self.root.after(1000, self._watch)

    def _note_seen(self):
        try:
            tray.call(f'http://{HOST}:{PORT}', 'POST', '/api/app/tray/seen')
        except (OSError, ValueError):
            self.first_note = True          # the server did not take it: tell them next time too

    def _show_wiskit(self, on: bool):
        shown = self.root.state() != 'withdrawn'
        if on and not shown:
            self.root.deiconify()
            self._show_activity()           # the dot comes back with him
        elif not on and shown:
            if self.wheel:
                self.wheel.close()
            self.bubble.close()
            self.root.withdraw()
            self._show_activity()           # withdrawn: no dot, no card
            self.root.after(5000, lambda: trim_memory() if self.root.state() == 'withdrawn' else None)

    def _sync_tray(self, note: str | None = None):
        """A thread (HTTP + the icon): one at a time, applying whatever is wanted when it runs. note: the
        window just went to the tray: say so briefly from the icon."""
        with self.tray_lock:
            if self.tray_on:
                if self.tray.show() and note:
                    self.tray.notify(note)
            else:
                self.tray.hide()

    def _close_idle_panel(self, now: float, window_closed: bool = False):
        """Asleep (not warm): a drop panel hidden for PANEL_IDLE_S, or when the main window just closed, takes
        its WebView2 with it (sleep.close_hidden_panel)."""
        if not sleep.lazy_panel(self.pref, self.warm) or not sleep.find(PANEL_TITLE) or sleep.visible(PANEL_TITLE):
            self.panel_hidden_since = None
            return
        self.panel_hidden_since = self.panel_hidden_since or now
        if sleep.close_hidden_panel(now - self.panel_hidden_since, window_closed):
            sleep.close_window(PANEL_TITLE)
            self.panel_hidden_since = None

    def open_app(self):
        """Any thread: the main window to the front, or a new one (the window process is gone when asleep)."""
        if sleep.focus(sleep.WINDOW_TITLE) or time.time() < self.opening_until:
            return                      # shown, or one is still starting (a double click must not open two)
        self.opening_until = time.time() + sleep.GRACE_S
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)    # ASFW_ANY: the new window may come to the front
        autostart.spawn()

    def _bg_open(self):
        threading.Thread(target=self.open_app, name='widget-open', daemon=True).start()

    def _pump(self):
        """Run the drop callbacks that OLE queued (dropwin.py: never tkinter inside the OLE call)."""
        dropwin.pump()
        self.root.after(PUMP_DRAG_MS if self.dragging else PUMP_MS, self._pump)

    # ── server events (daemon thread -> tk via after) ──
    def _events(self):
        down_since = None
        while True:
            try:
                req = urllib.request.Request(f'http://{HOST}:{PORT}/api/events', headers=local_auth.headers(PORT, {'Accept': 'text/event-stream'}))
                with urllib.request.urlopen(req, timeout=120) as resp:
                    down_since = None
                    self._read_prefs()
                    if self.pref is not None and not sleep.lazy_panel(self.pref, self.warm):
                        self._prewarm()         # unread (server busy): hovering Wiskit starts the panel
                    event = ''
                    for raw in resp:
                        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                        if line.startswith('event:'):
                            event = line[6:].strip()
                        elif line.startswith('data:') and event == 'widget':
                            self.root.after(0, self._on if json.loads(line[5:]).get('enabled') else self._off)
                        elif line.startswith('data:') and event == 'app':
                            data = json.loads(line[5:])
                            self.pref, self.warm = bool(data.get('tray')), bool(data.get('warm'))
                            self.notice = bool(data.get('notice'))
                        elif line.startswith('data:') and event == 'video_tools':
                            self.root.after(0, self._analysis_done, json.loads(line[5:]))
                        elif line.startswith('data:') and event in ('hello', 'job'):
                            data = json.loads(line[5:])
                            snap = data.get('jobs', data) if event == 'hello' else data
                            if event == 'hello':
                                self.root.after(0, self._hello, data)
                            self.root.after(0, self._jobs, snap or {})
                        elif line.startswith('data:') and event == 'cloud':
                            self.root.after(0, self._cloud, json.loads(line[5:]))
                        elif line.startswith('data:') and event == 'ask_run':
                            self.root.after(0, self._asks, int(json.loads(line[5:]).get('running') or 0))
                        elif line.startswith('data:') and event == 'ask_saved':
                            self.root.after(0, self._ask_saved)
            except Exception:
                if down_since is None:          # once per outage: nothing is known to run until the next hello
                    try:
                        self.root.after(0, self._server_gone)
                    except Exception:
                        pass                    # tk is closing
                down_since = down_since or time.time()
                if not self.on_quit and time.time() - down_since > GONE_AFTER_S:
                    self.request_exit()      # not this process's server and it is gone: leave (the next tick closes)
                time.sleep(3)           # server not up yet, or restarted: reconnect

    def _read_prefs(self):
        """Events thread: the sleep preferences, once per connection (then `app` events keep them)."""
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://{HOST}:{PORT}/api/app', headers=local_auth.headers(PORT)), timeout=15) as r:
                view = json.loads(r.read() or b'{}')
            self.pref, self.warm = bool(view.get('tray')), bool(view.get('warm'))
            self.notice = bool(view.get('notice'))
            self.first_note = not view.get('notice_seen', True)
        except (OSError, ValueError):
            pass

    def _off(self):
        """Settings turned the widget off: Wiskit stays withdrawn; the process keeps serving until Quit."""
        self.off = True
        self._show_wiskit(False)

    def _on(self):
        """Settings or the tray menu turned the widget back on (_watch shows him when the window allows)."""
        self.off = False

    def _job(self, running: bool):
        if self.job and not running:
            self.done_until = time.time() + DONE_S
            if self.pending_ask:            # the video_tools finish event comes first; none came
                self.pending_ask = None
                self.bubble.say('The video analysis did not finish, so there is nothing to ask about.')
        self.job = running

    # ── activity while the window sleeps: the dot, the card, the tray tooltip (projects/wiskit-activity) ──
    def _hello(self, data: dict):
        """A new event stream: the answers and the Drive state as they are now (the jobs come next)."""
        self.asks = int(data.get('asks') or 0)
        self.cloud = data.get('cloud') or {}

    def _jobs(self, snap: dict):
        was = self.job
        self._job(bool(snap.get('current')))
        if was and not self.job:
            self.last = activity.last_job(snap.get('last'))
        self.jobs_snap = snap
        self._show_activity()

    def _cloud(self, data: dict):
        self.cloud = data
        self._show_activity()

    def _asks(self, running: int):
        self.asks = running
        self._show_activity()

    def _ask_saved(self):
        self.done_until = time.time() + DONE_S
        self.last = activity.LAST_ANSWER
        self._show_activity()

    def _server_gone(self):
        self.jobs_snap, self.cloud, self.asks = {}, {}, 0
        self._show_activity()

    def _show_activity(self):
        """Tk thread: the dot, an open card and the tray tooltip follow the latest snapshots."""
        card = activity.lines(self.jobs_snap, self.cloud, self.asks, self.last)
        shown = self.root.state() != 'withdrawn'
        mode = activity.dot(self.jobs_snap, self.cloud, self.asks) if shown else ''
        self.dot.set(mode, *widget_wheel.dot_xy(self.root.winfo_x(), self.root.winfo_y(), self.w, self.h))
        if self.card.win is not None:
            if card and shown:
                self.card.show(card)
            else:
                self.card.close()
        tip = activity.tooltip(card)
        if tip != self.tip:
            self.tip = tip
            self.tray.set_title(tip)

    def _hover_card(self, on: bool):
        """The pointer came onto Wiskit or the dot: the card after CARD_DELAY_MS. It left (or he is pressed,
        dragged, or a bubble opens): no card."""
        if self.card_job:
            self.root.after_cancel(self.card_job)
            self.card_job = None
        if on:
            self.card_job = self.root.after(CARD_DELAY_MS, self._open_card)
        else:
            self.card.close()

    def _open_card(self):
        self.card_job = None
        card = activity.lines(self.jobs_snap, self.cloud, self.asks, self.last)
        if card and not self.wheel and not self.dragging and not self.press and self.bubble.win is None \
                and self.root.state() != 'withdrawn':
            self.card.show(card)

    # ── input ──
    def _press(self, e):
        self._hover_card(False)
        self.press = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def _drag(self, e):
        if not self.press:
            return
        x0, y0, wx, wy, moved = self.press
        dx, dy = e.x_root - x0, e.y_root - y0
        if moved or abs(dx) > DRAG_PX or abs(dy) > DRAG_PX:
            self.press = (x0, y0, wx, wy, True)
            self.drag_to = (wx + dx, wy + dy)
            self.root.geometry(f'+{wx + dx}+{wy + dy}')
            self.dot.move(*widget_wheel.dot_xy(wx + dx, wy + dy, self.w, self.h))

    def _release(self, e):
        if self.press and self.press[4]:
            x, y = self.drag_to        # not winfo_x/y: the last geometry() may not be applied yet
            autostart.save_widget_state(x=x, y=y)
        elif self.press:
            self._toggle_wheel()
        self.press = None

    def _menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    # ── the action wheel ──
    def _toggle_wheel(self):
        if self.wheel:
            self.wheel.close()
            return
        if time.time() - self.wheel_closed_at < 0.3:     # this click took focus from the wheel and closed it
            return
        self.bubble.close()
        if sleep.lazy_panel(self.pref, self.warm):
            self._prewarm()
        self.wheel = widget_wheel.Wheel(self.root, self.root.winfo_x() + self.wheel_x, self.root.winfo_y() + self.wheel_y,
                                        self._pick, self._wheel_closed, radius=self.wheel_radius)

    def _note(self, mode: str):
        """Worker thread: the server hands the request to the main window and starts it if it is not there."""
        try:
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            api('/api/app/note', {'mode': mode}, timeout=5)
        except RuntimeError as e:
            self.root.after(0, lambda: self.bubble.say(f'Could not open a note: {e}'))

    def _wheel_closed(self):
        self.wheel, self.wheel_closed_at = None, time.time()

    def _pick(self, action: str):
        if action == 'ask':
            self._open_panel(True)
        elif action == 'drop':
            self._open_panel(False)
        elif action == 'open':
            self._bg_open()
        elif action in ('write', 'record'):
            threading.Thread(target=lambda: self._note(action), name='widget-note', daemon=True).start()
        elif action == 'quit':
            self.quit()

    # ── drag and drop onto Wiskit and the drop ring (desktop/dropwin.py, plan 11) ──
    def _drag_enter(self, kind: str, payload, x: int, y: int):
        self._cancel_close()
        self.dragging = True
        self._hover_card(False)
        if sleep.lazy_panel(self.pref, self.warm):
            self._prewarm()
        if self.wheel:
            self.wheel.close()
        if self.ring is None:
            acts = drop_actions(kind, payload)
            self.ring = widget_wheel.DropRing(self.root, self.root.winfo_x() + self.wheel_x, self.root.winfo_y() + self.wheel_y,
                                              [(a, widget_wheel.DROP_LABELS[a]) for a in acts], radius=self.wheel_radius)
            self.ring_target = dropwin.register(self.ring.hwnds, self._drag_enter, self._drag_leave,
                                                self._dropped_at, self._drag_over)
        self.ring.action_at(x, y)

    def _drag_over(self, x: int, y: int):
        if self.ring:
            self.ring.action_at(x, y)

    def _drag_leave(self):
        self._cancel_close()
        self.close_job = self.root.after(LEAVE_GRACE_MS, self._end_drag)

    def _cancel_close(self):
        if self.close_job:
            self.root.after_cancel(self.close_job)
            self.close_job = None

    def _end_drag(self):
        self._cancel_close()
        self.dragging = False
        if self.ring:
            dropwin.revoke(self.ring.hwnds)
            self.ring.close()
            self.ring = self.ring_target = None

    def _dropped_at(self, kind: str, payload, x: int, y: int):
        """A drop on a bubble runs it; a drop on Wiskit asks which. Runs from _pump, after the OLE call."""
        act = self.ring.action_at(x, y) if self.ring else None
        self._end_drag()
        if act:
            self._run_drop(act, kind, payload)
        else:
            self.bubble.choose('What do you want to do with this?', describe_drop(kind, payload),
                               [(widget_wheel.DROP_LABELS[a], lambda a=a: self._run_drop(a, kind, payload))
                                for a in drop_actions(kind, payload)])

    def _run_drop(self, action: str, kind: str, payload):
        if action == 'inbox':
            self._dropped(kind, payload)
        elif action == 'library':
            self._dropped('url', payload.strip())
        elif action == 'video':
            self._confirm_video(payload[0], ask=False)
        elif action == 'ask':
            self._ask_about(kind, payload)

    def _confirm_video(self, path: str, ask: bool):
        self.bubble.choose(f'Analyze {Path(path).name}?', 'It runs the Video Tools analysis with your AI keys.',
                           [('Yes', lambda: self._analyze(path, ask)), ('No', lambda: None)])

    def _analyze(self, path: str, ask: bool):
        def started(_d):
            if ask:
                self.pending_ask = Path(path).stem      # the output folder: data/video_tools/items/<stem>
            self.bubble.say('Analyzing the video. ' + ('I will open the panel when it is done.' if ask
                                                       else 'The report lands in data/video_tools.'), 4000)
        self._bg(lambda: api('/api/video-tools/analyze', {'path': path}), started, self.bubble.say)

    def _analysis_done(self, data: dict):
        folder = str(data.get('folder') or '')
        if not self.pending_ask or Path(folder).name != self.pending_ask:
            return
        self.pending_ask = None
        self._bg(lambda: api('/api/ask/attach', {'analysis': folder}), lambda d: self._open_ask([d['id']]), self.bubble.say)

    def _ask_about(self, kind: str, payload):
        if kind == 'files' and len(payload) == 1 and Path(payload[0]).suffix.lower() in VIDEO_EXTS:
            self._confirm_video(payload[0], ask=True)
            return

        def work():
            if kind == 'files':
                return [api(f'/api/ask/attach?name={urllib.parse.quote(Path(p).name)}', raw=Path(p).read_bytes(),
                            timeout=180)['id'] for p in payload]
            return [api('/api/ask/attach', {'text': payload})['id']]
        self.bubble.say('Reading it...')
        self._bg(work, self._open_ask, self.bubble.say)

    def _open_ask(self, ids: list[str]):
        self.bubble.say('Ask me about it in the panel.', 2500)
        self._open_panel(True, ids)

    def _open_panel(self, ask: bool, ids=()):
        """The drop panel. Normally it is there, hidden (_prewarm): POST /api/ask/panel shows it at once with the
        ids. Missing (closed by its server, or still starting): the dock ghost holds its place while it starts."""
        args = ['--panel', *(['--ask'] if ask else []), *(['--attach', '|'.join(ids)] if ids else [])]
        if not autostart.allow_foreground(PANEL_TITLE):
            if self.ghost:
                self.ghost.close()
            self.ghost = panel_ghost.Ghost(self.root)
            if time.time() - self.prewarm_at < PREWARM_WAIT_S:
                self._when_panel_up(args, ids, time.time() + PREWARM_WAIT_S)      # the prewarm is still starting
            else:
                autostart.spawn(*args)
            return

        def show():              # a thread: HTTP only, never tk
            try:
                api('/api/ask/panel', {'ids': list(ids)}, timeout=3)
            except RuntimeError:
                autostart.spawn(*args)
        threading.Thread(target=show, name='widget-panel', daemon=True).start()

    def _when_panel_up(self, args, ids, until: float):
        """A click while the prewarmed panel is still starting: open it once its window exists (a second
        process now would make two panels); it never came: start one cold."""
        if autostart.allow_foreground(PANEL_TITLE):
            threading.Thread(target=lambda: api('/api/ask/panel', {'ids': list(ids)}, timeout=3),
                             name='widget-panel', daemon=True).start()
        elif time.time() < until:
            self.root.after(50, self._when_panel_up, args, ids, until)
        else:
            autostart.spawn(*args)

    def _prewarm(self):
        """The server answered (events thread, no tk), or asleep: Wiskit was hovered or used. Start the drop
        panel hidden unless one is there or starting, so the open is instant (Fred: a cold open every time
        is too slow)."""
        if time.time() - self.prewarm_at < PREWARM_WAIT_S:
            return
        if not self.off and not autostart.allow_foreground(PANEL_TITLE):
            self.prewarm_at = time.time()
            autostart.spawn('--panel', '--hidden')

    def _dropped(self, kind: str, payload):
        if kind == 'url' or (kind == 'text' and is_url(payload)):
            self._bg(lambda: api('/api/inbox/link', {'url': payload.strip()}),
                     lambda d: self.bubble.say(('Added to the library' if d.get('new') else 'Already in the library') + f' (#{d.get("id")}).'),
                     self.bubble.say)
        elif kind == 'text':
            self._bg(lambda: api('/api/inbox/text', {'text': payload}),
                     lambda d: self.bubble.say('Saved to your Inbox note.'), self.bubble.say)
        elif kind == 'files':
            images, others, skipped = sort_files(payload)
            self._bg(lambda: self._file_all(images, others), lambda msg: self.bubble.say('\n'.join([msg, *skipped]), 5000),
                     self.bubble.say)
            if not images and not others:
                self.bubble.say('\n'.join(skipped) or 'Nothing to file.')

    @staticmethod
    def _file_all(images: list[Path], others: list[Path]) -> str:
        for p in others:
            api(f'/api/inbox/file?name={urllib.parse.quote(p.name)}', raw=p.read_bytes(), timeout=300)
        if images:
            api('/api/inbox/screenshot', {'images': [
                {'name': p.name, 'type': 'image/' + ('jpeg' if p.suffix.lower() in ('.jpg', '.jpeg') else p.suffix.lower()[1:]),
                 'data': base64.b64encode(p.read_bytes()).decode('ascii')} for p in images]})
        parts = []
        if others:
            parts.append(f'{len(others)} file{"s" * (len(others) > 1)} saved to data/inbox')
        if images:
            parts.append(f'{len(images)} picture{"s" * (len(images) > 1)} going into your Inbox note')
        msg = '; '.join(parts) + '.'
        return msg[0].upper() + msg[1:] if parts else 'Nothing to file.'

    def _bg(self, work, ok, err):
        """Run work() on a thread (HTTP only, never SQLite); ok(result) / err(message) back on tk."""
        self.busy += 1

        def run():
            try:
                res, fail = work(), None
            except Exception as e:
                res, fail = None, str(e) or e.__class__.__name__
            self.root.after(0, finish, res, fail)

        def finish(res, fail):
            self.busy -= 1
            if fail is None:
                self.done_until = time.time() + DONE_S
                ok(res)
            else:
                err(fail)
        threading.Thread(target=run, name='widget-drop', daemon=True).start()

    def request_exit(self):
        """Quit asked from another thread (POST /api/app/quit): close on the next tick, never touch tk here."""
        self.exit_requested = True

    def request_quit(self):
        """The tray's Quit (its worker thread): stop the app as quit() does, then close on the next tick."""
        if self.on_quit:
            self.on_quit()
        else:
            self._post_quit()
        self.exit_requested = True

    @staticmethod
    def _post_quit():
        try:
            req = urllib.request.Request(f'http://{HOST}:{PORT}/api/app/quit', data=b'', method='POST', headers=local_auth.headers(PORT, {'X-CM': '1'}))
            urllib.request.urlopen(req, timeout=3).close()
        except Exception:
            pass

    def quit(self):
        if self.on_quit:                # this process owns the server: stop it directly, no HTTP round trip
            self.on_quit()
        else:
            self._post_quit()
        self.exit_requested = True
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.tray.close()            # pystray's thread is not a daemon: the process would hang


if __name__ == '__main__':
    Widget().run()
