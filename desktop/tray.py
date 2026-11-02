"""The notification-area icon for "Minimize to tray and show Wiskit" (sleep mode, desktop/sleep.py).

Hosted by the keeper (the --widget / --background process, desktop/widget.py), which shows it while the
main window is minimized, hidden or closed, and hides it while the window is on screen.
The preference lives in the DB settings table (key `minimize_to_tray`); this module never opens SQLite.
It reads and changes it through the local API (GET /api/app, PUT /api/app/tray, PUT /api/app/widget), so
Settings, the tray menu and the keeper always agree. The icon is created the first time it shows
(pystray; a thread running its own message loop), then only shown and hidden.

Menu: Open Brainamon (also a left click), Ask Wiskit..., the preference as a checkbox, Wiskit on the
desktop as a checkbox, Quit Brainamon.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from core import local_auth

from core import app_console, app_paths
from desktop import autostart


def call(base: str, method: str, path: str, body: dict | None = None, timeout: float = 2.0) -> dict:
    """One request to the local server; raises OSError / ValueError on failure."""
    data = None if method == 'GET' else json.dumps(body or {}).encode('utf-8')
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=local_auth.headers(__import__('urllib.parse', fromlist=['urlsplit']).urlsplit(base).port, {'X-CM': '1', 'Content-Type': 'application/json'}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def _image():
    """The app icon: brand/icon-32.png, the tile hinted to the pixel grid (projects/brainamon-logo/build.py),
    from the built front end or, from source before a build, web/public. A plain navy square when missing."""
    from PIL import Image
    from core import app_paths
    for path in (app_paths.BUNDLE / 'web' / 'dist' / 'brand' / 'icon-32.png',
                 app_paths.BUNDLE / 'web' / 'public' / 'brand' / 'icon-32.png'):
        try:
            return Image.open(path).convert('RGBA')
        except OSError:
            continue
    return Image.new('RGBA', (32, 32), '#123456')


TITLE = app_paths.APP_NAME
NOTIFY_S = 4.0          # how long the "minimized to the tray" notification stays
NOTIFY_SETTINGS = r'Control Panel\NotifyIconSettings'


def _same_exe(entry: str, exe: str) -> bool:
    """A NotifyIconSettings ExecutablePath is a plain path or starts with a known-folder GUID
    ({6D80...}\\Brainamon\\Brainamon.exe for Program Files): compare the tail for those."""
    entry, exe = os.path.normcase(entry), os.path.normcase(exe)
    if entry.startswith('{') and '\\' in entry:
        return exe.endswith('\\' + entry.split('\\', 1)[1])
    return entry == exe


def promote(exe: str, title: str = TITLE, base: str = NOTIFY_SETTINGS, tries: int = 20, wait: float = 0.5) -> bool:
    """Windows 11 files a new notification-area icon in the overflow flyout until its entry under
    HKCU\\Control Panel\\NotifyIconSettings has IsPromoted=1 (the switch in Settings > Personalization >
    Taskbar > Other system tray icons), so a first-time icon looks missing. Explorer writes that entry a
    moment after the icon is added: poll for it, set the flag once, and leave a value the user already
    chose (promoted or not) alone. Entries are matched by executable and tooltip. True when one was set."""
    import winreg
    for attempt in range(tries):
        if attempt:
            time.sleep(wait)
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)
        except OSError:
            continue
        done = False
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, name, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                        entry = winreg.QueryValueEx(k, 'ExecutablePath')[0]
                        tip = winreg.QueryValueEx(k, 'InitialTooltip')[0]
                        if not _same_exe(entry, exe) or tip.casefold() != title.casefold():
                            continue
                        try:
                            winreg.QueryValueEx(k, 'IsPromoted')
                            continue                      # the user (or an earlier run) already decided
                        except FileNotFoundError:
                            pass
                        winreg.SetValueEx(k, 'IsPromoted', 0, winreg.REG_DWORD, 1)
                        done = True
                except OSError:
                    continue
        if done:
            return True
    return False


class Tray:
    """on_open: bring the main window back (or start it); on_quit: stop the app. Both may be called on any
    thread (the menu runs them on a worker thread)."""

    def __init__(self, base: str, on_open, on_quit):
        self.base, self.on_open, self.on_quit = base, on_open, on_quit
        self.icon = None
        self.state = {'tray': True, 'widget': False, 'notice': False}       # what the menu checkboxes show; refreshed in show()
        self.title = TITLE                     # the tooltip: what runs while the window sleeps (set_title)

    def show(self) -> bool:
        """The app went to sleep: tray icon on. False when the icon could not be shown."""
        try:
            view = call(self.base, 'GET', '/api/app')
            self.state = {'tray': bool(view.get('tray')), 'widget': bool(view.get('widget')),
                          'notice': bool(view.get('notice'))}
        except (OSError, ValueError):
            pass                               # the menu keeps its last checkboxes
        try:
            if self.icon is None:
                import pystray
                self.icon = pystray.Icon(TITLE, _image(), TITLE, self._menu(pystray))
                self.icon.run_detached()                 # default setup: the icon becomes visible
                self._bg(lambda: promote(sys.executable))     # out of the overflow flyout, first run only
            else:
                self.icon.update_menu()
                self.icon.title = TITLE                  # added as TITLE again; _apply_title() names the activity after
                self.icon.visible = True
        except Exception as exc:
            app_console.emit('error', 'Tray: could not show the icon', level='error', error=exc)
            self.icon = None
            return False
        self._apply_title()
        return True

    def set_title(self, text: str) -> None:
        """The tooltip names what runs (desktop/activity.py tooltip(), already short enough for Windows). It
        changes now only while the icon is up: Windows keeps the tooltip an icon is added with as its
        InitialTooltip, which promote() matches against TITLE, so show() adds the icon as TITLE first."""
        self.title = text
        icon = self.icon
        if icon is not None and icon.visible:
            try:
                icon.title = text
            except Exception as exc:
                app_console.emit('error', 'Tray: could not change the tooltip', level='warning', error=exc)

    def _apply_title(self) -> None:
        """show(), on its thread: once the icon is up (a new one comes up a moment after run_detached), the
        tooltip becomes self.title. Waits up to 2 s, as notify() does."""
        icon = self.icon
        if icon is None:
            return
        for _ in range(40):
            if icon.visible:
                break
            time.sleep(0.05)
        self.set_title(self.title)

    def hide(self) -> None:
        if self.icon is not None and self.icon.visible:
            self.icon.visible = False

    def notify(self, message: str, seconds: float = NOTIFY_S) -> None:
        """A brief notification from the icon (a toast on Windows 11), taken back after `seconds` so it does
        not stay in the notification centre. Waits up to 2 s for a new icon to be added first."""
        icon = self.icon
        if icon is None:
            return
        for _ in range(40):
            if icon.visible:
                break
            time.sleep(0.05)
        try:
            icon.notify(message, TITLE)
        except Exception as exc:
            app_console.emit('error', 'Tray: could not show the notification', level='warning', error=exc)
            return
        t = threading.Timer(seconds, self._unnotify, args=(icon,))
        t.daemon = True
        t.start()

    def _unnotify(self, icon) -> None:
        if self.icon is icon and icon.visible:
            try:
                icon.remove_notification()
            except Exception:
                pass

    def close(self) -> None:
        """The process is ending: take the icon out of the notification area (it would linger as a ghost)."""
        if self.icon is not None:
            self.icon.visible = False
            self.icon.stop()
            self.icon = None

    def _menu(self, pystray):
        item, menu = pystray.MenuItem, pystray.Menu
        return menu(
            item('Open Brainamon', lambda icon, i: self._bg(self.on_open), default=True),
            item('Ask Wiskit...', lambda icon, i: autostart.spawn('--panel', '--ask')),
            menu.SEPARATOR,
            item('Minimize to tray and show Wiskit', lambda icon, i: self._bg(self._toggle_pref),
                 checked=lambda i: self.state['tray']),
            item('Show Wiskit on the desktop', lambda icon, i: self._bg(self._toggle_widget),
                 checked=lambda i: self.state['widget']),
            item('Notify when Brainamon goes to the tray', lambda icon, i: self._bg(self._toggle_notice),
                 checked=lambda i: self.state.get('notice', False)),
            menu.SEPARATOR,
            item('Quit Brainamon', lambda icon, i: self._bg(self.on_quit)),
        )

    @staticmethod
    def _bg(fn) -> None:
        """Menu callbacks run inside the tray's message loop: HTTP and window work go to a thread."""
        threading.Thread(target=fn, name='tray-action', daemon=True).start()

    def _toggle_pref(self) -> None:
        try:
            on = not self.state['tray']
            self.state['tray'] = bool(call(self.base, 'PUT', '/api/app/tray', {'on': on}).get('tray'))
        except (OSError, ValueError) as exc:
            app_console.emit('error', 'Tray: could not change the preference', level='warning', error=exc)
            return
        app_console.emit('log', f'Minimize to tray and show Wiskit: {"on" if self.state["tray"] else "off"} (tray menu)')
        if not self.state['tray']:
            self.on_open()                  # off: no icon from now on, so bring the window back (or start it)
            self.hide()
        elif self.icon is not None:
            self.icon.update_menu()

    def _toggle_widget(self) -> None:
        try:
            on = not self.state['widget']
            self.state['widget'] = bool(call(self.base, 'PUT', '/api/app/widget', {'on': on}, timeout=5).get('widget'))
        except (OSError, ValueError) as exc:
            app_console.emit('error', 'Tray: could not change Wiskit', level='warning', error=exc)
            return
        app_console.emit('log', f'Wiskit on the desktop: {"on" if self.state["widget"] else "off"} (tray menu)')
        if self.icon is not None:
            self.icon.update_menu()

    def _toggle_notice(self) -> None:
        try:
            on = not self.state.get('notice', False)
            self.state['notice'] = bool(call(self.base, 'PUT', '/api/app/notice', {'on': on}, timeout=5).get('notice'))
        except (OSError, ValueError) as exc:
            app_console.emit('error', 'Tray: could not change the notice', level='warning', error=exc)
            return
        app_console.emit('log', f'Notice when going to the tray: {"on" if self.state["notice"] else "off"} (tray menu)')
        if self.icon is not None:
            self.icon.update_menu()
