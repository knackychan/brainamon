"""Windowless launcher: start Brainamon (the V6 window, server.desktop) with no console window.

    pyw launch.pyw        (a trailing "v6" argument from older shortcuts is ignored)

Runs under pythonw, so there is no console: stdout/stderr go to error_log.txt (appended), console
child processes (yt-dlp, ffmpeg) are started with CREATE_NO_WINDOW so they do not flash a window,
and a crash shows a message box instead of a paused console. For a console, run
py -m server.desktop from the repo root. It is also the entry script of the installed build
(packaging/brainamon.spec).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if '--uninstall-data' in sys.argv:
    from core.uninstall import main as uninstall_data
    raise SystemExit(uninstall_data())
if sys.argv[1:2] == ['--mcp']:
    # The local MCP server (mcp_local) for Wiskit's Claude Code mode: stdin/stdout are the protocol channel,
    # so this runs before anything below redirects them. Logs go to stderr.
    sys.argv = sys.argv[:1]
    if sys.stderr is None:                       # windowed exe started without a stderr pipe
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    from mcp_local.app import main as mcp_main
    raise SystemExit(mcp_main())

from desktop import sleep  # noqa: E402
if all(arg == 'v6' for arg in sys.argv[1:]) and sleep.focus():
    sys.exit(0)
from desktop import early_splash  # noqa: E402
early_splash.start(sys.argv[1:])

import runpy  # noqa: E402
import subprocess  # noqa: E402
import traceback  # noqa: E402
from datetime import datetime  # noqa: E402

try:
    from core import app_paths  # noqa: E402
except RuntimeError as exc:
    early_splash.close()
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(exc), 'Brainamon', 0x10)
    raise SystemExit(1) from exc

# From source both are the repo. Installed (the PyInstaller entry point): assets from the bundle,
# and the working folder + log in %LOCALAPPDATA%\Brainamon, never next to the exe.
ROOT = app_paths.BUNDLE
app_paths.HOME.mkdir(parents=True, exist_ok=True)
app_paths.LOCAL.mkdir(parents=True, exist_ok=True)
LOG = app_paths.ERROR_LOG
os.chdir(app_paths.HOME)

_log = open(LOG, 'a', encoding='utf-8', errors='replace', buffering=1)
sys.stdout = sys.stderr = _log

if os.name == 'nt':
    class _NoWindowPopen(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen


def _alert(text: str) -> None:
    early_splash.close()
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, 'Brainamon', 0x10)


def main() -> None:
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != 'v6']
    print(f'\n===== {datetime.now():%Y-%m-%d %H:%M:%S} launch.pyw (V6) =====')
    if not (ROOT / 'web' / 'dist' / 'index.html').exists():
        _alert('The V6 front end is not built.\nRun: cd web && npm install && npm run build')
        return
    try:
        runpy.run_module('server.desktop', run_name='__main__', alter_sys=True)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            _alert(f'Brainamon exited with an error.\nDetails: {LOG}')
    except BaseException:
        traceback.print_exc()
        _alert(f'Brainamon crashed.\nDetails: {LOG}')


try:
    main()
finally:
    early_splash.close()
