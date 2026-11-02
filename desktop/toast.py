"""A Windows notification (toast) from Brainamon, no extra package.

Windows shows a toast only for an app it knows by an AppUserModelID. Brainamon has no installer shortcut when
it runs from source, so `show` writes a per-user registration (HKCU\\Software\\Classes\\AppUserModelId\\Brainamon,
a display name) once, then lets Windows PowerShell raise the toast through the WinRT API under that id. The text
goes through environment variables, never into the script, so a title or a note excerpt cannot inject code.

Windows only: elsewhere `show` returns False. Never raises. Called off the request thread (server/notify.py).
"""
import base64
import os
import subprocess
import sys

from desktop import sleep

AUMID = 'Brainamon'
TIMEOUT_S = 15

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$t = [System.Security.SecurityElement]::Escape($env:CM_TOAST_TITLE)
$b = [System.Security.SecurityElement]::Escape($env:CM_TOAST_TEXT)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CM_TOAST_APP).Show($toast)
"""
_ENCODED = base64.b64encode(_SCRIPT.encode('utf-16-le')).decode('ascii')
_registered = False


def _register() -> None:
    global _registered
    if _registered:
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf'Software\Classes\AppUserModelId\{AUMID}') as k:
        winreg.SetValueEx(k, 'DisplayName', 0, winreg.REG_SZ, 'Brainamon')
    _registered = True


def app_focused() -> bool:
    """True when the Brainamon window is the one in front: its own toast would only repeat what is on screen."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        hwnd = sleep.find(sleep.WINDOW_TITLE)
        return bool(hwnd) and ctypes.windll.user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def show(title: str, text: str) -> bool:
    if sys.platform != 'win32':
        return False
    try:
        _register()
        env = {**os.environ, 'CM_TOAST_TITLE': title[:120], 'CM_TOAST_TEXT': text[:300], 'CM_TOAST_APP': AUMID}
        done = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', _ENCODED],
            env=env, capture_output=True, timeout=TIMEOUT_S, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return done.returncode == 0
    except Exception:
        return False
