"""Sleep mode (projects/desktop-app plan 10, 2026-10-11): with "Minimize to tray and show Wiskit" on,
Brainamon shows its main window or, when that is minimized or closed, Wiskit and the tray icon.

The keeper (the --widget / --background process: server, Wiskit, tray icon) polls the main window's
state once a second with these helpers; no IPC. The window process decides on minimize / close:
asleep closes it (WebView2 and its processes are gone, plan 10: about 400 MB) unless the DB setting
`keep_window_warm` is on, which only hides it with the WebView2 suspended (instant to reopen).

Window helpers (ctypes, Windows only) and the pure decisions the tests check.
"""
import sys
import time

from core import app_paths

WINDOW_TITLE = app_paths.APP_NAME   # shared with server/desktop.py TITLE
WIDGET_TITLE = app_paths.APP_NAME + ' Wiskit'
GRACE_S = 20                       # a keeper started by a window hides Wiskit and the icon until it shows
PANEL_IDLE_S = 60                  # asleep and not warm: a drop panel hidden this long is closed


def _user32():
    import ctypes
    return ctypes.windll.user32


def find(title: str) -> int:
    """Our top-level window with this exact title and UI class, shown or hidden; 0 when none."""
    if sys.platform != 'win32':
        return 0
    import ctypes
    from ctypes import wintypes
    u = _user32()
    found = 0

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        nonlocal found
        if u.GetWindowTextLengthW(hwnd) == len(title):
            text = ctypes.create_unicode_buffer(len(title) + 1)
            u.GetWindowTextW(hwnd, text, len(text))
            if text.value == title:
                klass = ctypes.create_unicode_buffer(256)
                u.GetClassNameW(hwnd, klass, len(klass))
                if title == WIDGET_TITLE:
                    if klass.value != 'TkTopLevel':
                        return True
                elif not klass.value.startswith('WindowsForms10.Window.'):
                    return True
                found = hwnd
                return False
        return True

    # FindWindowW also matches Windows shell proxies, which can have the app's title.
    u.EnumWindows(visit, 0)
    return found


def window_state(title: str = WINDOW_TITLE) -> str:
    """'gone' (no window), 'asleep' (hidden or minimized) or 'awake' (on screen)."""
    hwnd = find(title)
    if not hwnd:
        return 'gone'
    u = _user32()
    return 'awake' if u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd) else 'asleep'


def visible(title: str) -> bool:
    hwnd = find(title)
    return bool(hwnd) and bool(_user32().IsWindowVisible(hwnd))


def close_window(title: str) -> bool:
    """Ask a window to close (WM_CLOSE, as its X button does). False when there is none."""
    hwnd = find(title)
    if hwnd:
        _user32().PostMessageW(hwnd, 0x0010, 0, 0)
    return bool(hwnd)


def focus(title: str = WINDOW_TITLE) -> bool:
    """Restore and bring an open window (the app, or the drop panel) to the front, also a hidden one
    (the warm tray). False when none. Called from a second launch (another process) and the keeper's
    Open (tray icon, Wiskit's menu and wheel).
    ShowWindowAsync, not ShowWindow: the owning UI thread does the work itself, and a new process's first
    ShowWindow can be replaced by its STARTUPINFO show command. SW_RESTORE on a hidden minimized window
    shows it restored; SW_SHOW covers a hidden window that is not minimized. The window's process gets
    the right to take the foreground (this process has it: the user just started or clicked it)."""
    if sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    u = _user32()
    hwnd = find(title)
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    u.AllowSetForegroundWindow(pid.value)
    if u.IsIconic(hwnd):
        u.ShowWindowAsync(hwnd, 9)     # SW_RESTORE
    elif not u.IsWindowVisible(hwnd):
        u.ShowWindowAsync(hwnd, 5)     # SW_SHOW
    for _ in range(20):                # up to 1 s for the owning thread to show it
        if u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
            break
        time.sleep(0.05)
    u.SetForegroundWindow(hwnd)
    return True


# ── pure decisions (tests/test_sleep.py) ──

def keeper_view(tray_pref: bool | None, wiskit_on: bool, state: str, in_grace: bool) -> tuple[bool, bool]:
    """(show Wiskit, show the tray icon). tray_pref None: not read yet (the server is starting).
    Preference off: Wiskit as his own setting says, no icon (as before sleep mode)."""
    if in_grace:
        return False, False
    if not tray_pref:
        return wiskit_on, False
    if state == 'awake':
        return False, False
    return wiskit_on, True


def owner_should_quit(owned: bool, in_grace: bool, state: str, tray_pref: bool | None, wiskit_on: bool) -> bool:
    """A keeper started by a window (--owned) ends the app when that window closes and nothing else
    shows: the preference and Wiskit both off. Startup grace also covers a window closed before
    the keeper could observe it; after grace, an absent window no longer keeps the server alive."""
    return owned and not in_grace and state == 'gone' and tray_pref is False and not wiskit_on


def on_minimize(tray_pref: bool, warm: bool) -> str:
    """The main window was minimized: 'normal' (stay on the taskbar), 'hide' (warm tray) or 'close'."""
    if not tray_pref:
        return 'normal'
    return 'hide' if warm else 'close'


def on_close(tray_pref: bool, warm: bool) -> str:
    """The X button: the same as minimize with the preference on (quit only from the tray or Wiskit)."""
    return 'hide' if tray_pref and warm else 'close'


def announce(last_state: str, icon_now: bool, notice: bool, first: bool = False) -> bool:
    """The icon just came up because the window left the screen (minimized or closed by the user): tell
    them where it went, when the `tray_notice` setting is on, or once ever (`first`: not told yet). Not
    when the keeper starts with no window (Start with Windows)."""
    return (notice or first) and icon_now and last_state == 'awake'


def tray_note(wiskit_on: bool, first: bool = False) -> str:
    return ('Brainamon is still running in the tray. Click the icon' + (' or Wiskit' if wiskit_on else '')
            + ' to bring it back, or use its menu to quit.'
            + (' You can change this in Settings > App.' if first else ''))


def lazy_panel(tray_pref: bool | None, warm: bool) -> bool:
    """Asleep means no WebView2: the drop panel starts when Wiskit is hovered or used, not with the server,
    and closes once hidden for PANEL_IDLE_S. Warm (or the preference off) keeps it prewarmed as before."""
    return bool(tray_pref) and not warm


def close_hidden_panel(hidden_s: float, window_closed: bool) -> bool:
    """Lazy mode, the panel hidden: close it after PANEL_IDLE_S, or at once when the main window just closed.
    Hovering Wiskit to click Open Brainamon prewarms the panel and the window shares its WebView2 (same
    user data folder), so without this its processes outlived the window's close by up to a minute."""
    return window_closed or hidden_s >= PANEL_IDLE_S
