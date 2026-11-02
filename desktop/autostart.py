"""Start with Windows: one per-user value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.

The registry value is the only state (no DB setting), so what Settings shows is what Windows will do.
The command starts the app without a window: --widget (server + Wiskit on the desktop) when the
widget is on, else --background (server only), see server/desktop.py. Off by default.

Also the one place that knows how to start the app as a new process (app_args / spawn): the installed
exe, or pythonw + launch.pyw when running from source.
"""
import json
import subprocess
import sys
from pathlib import Path

from core import app_paths
from desktop import sleep

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE = app_paths.APP_NAME
OLD_VALUES = () if app_paths.CONTRIBUTOR else ('Content Manager',)


WIDGET_FILE = app_paths.LOCAL / 'widget.json'      # {"enabled": bool, "x": int, "y": int}


def app_args(*args: str) -> list[str]:
    """The command line that starts the app with these flags."""
    if app_paths.FROZEN:
        return [sys.executable, *args]
    exe = Path(sys.executable)
    pyw = exe.with_name('pythonw.exe')
    return [str(pyw if pyw.exists() else exe), str(app_paths.BUNDLE / 'launch.pyw'), *args]


def spawn(*args: str) -> None:
    """Start the app as a new, independent process (no console window)."""
    subprocess.Popen(app_args(*args), cwd=str(app_paths.HOME), close_fds=True,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def allow_foreground(title: str) -> bool:
    """True when a window with this title exists, shown or hidden (the drop panel). Lets its process
    take the foreground: Windows gives that only to the process the user clicked, which is this one."""
    if sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = sleep.find(title)
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    user32.AllowSetForegroundWindow(pid.value)
    return True


def widget_state() -> dict:
    try:
        return json.loads(WIDGET_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_widget_state(**kw) -> None:
    try:
        WIDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        WIDGET_FILE.write_text(json.dumps({**widget_state(), **kw}), encoding='utf-8')
    except OSError:
        pass


def widget_on() -> bool:
    return bool(widget_state().get('enabled'))


def command() -> str:
    *exe, flag = app_args('--widget' if widget_on() else '--background')
    return ' '.join(f'"{a}"' for a in exe) + ' ' + flag


def is_on() -> bool:
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            present = {name for name in (VALUE, *OLD_VALUES) if _has_value(winreg, k, name)}
    except OSError:
        return False
    if present - {VALUE}:
        set_on(True)
        return True
    return VALUE in present


def _has_value(winreg, key, name: str) -> bool:
    try:
        winreg.QueryValueEx(key, name)
        return True
    except FileNotFoundError:
        return False


def set_on(on: bool) -> bool:
    """Write the new Run value before removing old names so a failed write keeps autostart working."""
    if sys.platform != 'win32':
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
            names = OLD_VALUES
        else:
            names = (VALUE, *OLD_VALUES)
        for name in names:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
    return bool(on)
