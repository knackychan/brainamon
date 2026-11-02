"""Where the app's files live, from source or from the installed (frozen) build.

From source (run.bat, dev.bat, py -m server): everything stays in the repo, as before.
    bundle   = the repo (web/dist, design/card-designs)
    home     = the repo (.env); error_log.txt and widget.json live in <repo>/local
    data_dir = <repo>/data

Installed (PyInstaller, sys.frozen): nothing is written next to the exe.
    bundle   = sys._MEIPASS (read-only assets shipped with the app)
    home     = %LOCALAPPDATA%\\Brainamon (.env, error_log.txt, location.json, updates)
    data_dir = location.json {"data_dir": ...} if present, else <home>\\data

CM_DATA_DIR overrides data_dir in both cases. Stdlib only: config.py imports this module.

ffmpeg / ffprobe / yt-dlp are not bundled: they come from PATH, or from the folder the user picked in
Settings > Tools. That folder is saved in <LOCAL>/tools.json (set_tools_dir) and, when set, goes first on PATH
at import, so every shutil.which and subprocess call finds them; with none set PATH is left alone.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from core import build_channel

FROZEN = bool(getattr(sys, 'frozen', False))
_REPO = Path(__file__).resolve().parent.parent

BUNDLE = Path(getattr(sys, '_MEIPASS', _REPO)) if FROZEN else _REPO
BUILD_CHANNEL = build_channel.read(BUNDLE) if FROZEN else 'source'
CONTRIBUTOR = BUILD_CHANNEL in ('contributor', 'unverified')
APP_NAME = build_channel.DISPLAY_NAMES[BUILD_CHANNEL]
DEFAULT_PORT = 18767 if CONTRIBUTOR else 18765
_LOCAL = Path(os.environ.get('LOCALAPPDATA') or Path.home())


def _installed_home() -> Path:
    selected = os.environ.get('BRAINAMON_HOME')
    if selected:
        path = Path(selected).expanduser()
        try:
            if not stat.S_ISDIR(path.stat().st_mode):
                raise RuntimeError(f'Cannot use {path}: the selected app data location is not a folder.')
        except OSError as exc:
            raise RuntimeError(f'Cannot inspect the selected app data location {path}: {exc}') from exc
        return path
    fresh = _LOCAL / build_channel.HOME_NAMES[BUILD_CHANNEL]
    homes = (fresh,) if CONTRIBUTOR else (fresh, _LOCAL / 'Content Manager')
    populated = []
    for path in homes:
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimeError(f'Cannot inspect app data location {path}: {exc}') from exc
        if not stat.S_ISDIR(mode):
            raise RuntimeError(f'Cannot use {path}: the app data location is not a folder.')
        try:
            if next(path.iterdir(), None) is not None:
                populated.append(path)
        except OSError as exc:
            raise RuntimeError(f'Cannot inspect app data location {path}: {exc}') from exc
    if len(populated) > 1:
        choices = ', '.join(str(path) for path in populated)
        raise RuntimeError('Brainamon found more than one populated app data folder and left them untouched. '
                           f'Set BRAINAMON_HOME to the folder to use: {choices}')
    return populated[0] if populated else fresh


HOME = _installed_home() if FROZEN else Path(os.environ.get('BRAINAMON_HOME') or _REPO)
POINTER = HOME / 'location.json'
# creationflags for console programs (ffmpeg, yt-dlp): no console window flashes over the windowless app
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# Runtime files that are not source: from source <repo>/local (gitignored), installed the home folder.
LOCAL = (HOME / 'local') if not FROZEN else HOME
ERROR_LOG = LOCAL / 'error_log.txt'
TOOLS_POINTER = LOCAL / 'tools.json'
try:
    LOCAL.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
CACHE = LOCAL / 'cache'


def cache_dir(name: str) -> Path:
    """Regenerable browser state (WebView2 profile, Playwright profile). Not user data, so it lives
    beside the logs, not in data/. A copy left in data/<name> by older versions is moved over once."""
    dest = CACHE / name
    try:
        legacy = data_dir() / name
        if legacy.is_dir() and not dest.exists():
            CACHE.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(dest))
        dest.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            from core import private_storage
            private_storage._secure(dest)
    except OSError:
        pass            # in use or no access: the caller creates/uses dest as it can
    return dest


def tools_dir() -> str:
    """The folder the user picked for ffmpeg / ffprobe / yt-dlp ('' when none is saved)."""
    try:
        value = json.loads(TOOLS_POINTER.read_text(encoding='utf-8'))['tools_dir']
    except (OSError, ValueError, KeyError, TypeError):
        return ''
    return value if isinstance(value, str) else ''


def apply_tools_dir(folder: str) -> None:
    """Put `folder` first on PATH for this process (once; an empty folder does nothing)."""
    if not folder:
        return
    parts = os.environ.get('PATH', '').split(os.pathsep)
    if folder not in parts:
        os.environ['PATH'] = os.pathsep.join([folder] + [p for p in parts if p])


def set_tools_dir(folder: str) -> None:
    """Save the tools folder ('' clears it) and apply it now. Settings > Tools calls this. A cleared folder
    leaves this process's PATH as it is until the next start."""
    folder = str(Path(folder).resolve()) if folder else ''
    TOOLS_POINTER.write_text(json.dumps({'tools_dir': folder, 'tool_folders': tool_folders()}, indent=2), encoding='utf-8')
    apply_tools_dir(folder)


def tool_folders() -> dict:
    try:
        value = json.loads(TOOLS_POINTER.read_text(encoding='utf-8')).get('tool_folders', {})
        return {k: v for k, v in value.items() if k in ('ffmpeg', 'ffprobe', 'yt-dlp', 'deno') and isinstance(v, str)} if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def set_tool_folder(name: str, folder: str) -> None:
    folders = tool_folders()
    if folder:
        folders[name] = str(Path(folder).resolve())
    else:
        folders.pop(name, None)
    TOOLS_POINTER.write_text(json.dumps({'tools_dir': tools_dir(), 'tool_folders': folders}, indent=2), encoding='utf-8')
    apply_tools_dir(folder)


def find_tool(name: str):
    folder = tool_folders().get(name)
    return shutil.which(name, path=folder) if folder else shutil.which(name)


apply_tools_dir(tools_dir())
for _folder in tool_folders().values():
    apply_tools_dir(_folder)


def merge_registry_path() -> None:
    """Windows: add the folders of the user and machine PATH (as the registry has them now) that this process
    lacks, after its own. A tool installed after the app started (winget puts Deno's folder on the user PATH,
    not in a Links shortcut) is then found without a restart, and so are the subprocesses that look for it."""
    if sys.platform != 'win32':
        return
    try:
        import winreg
        found = []
        for root, sub in ((winreg.HKEY_CURRENT_USER, 'Environment'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
            try:
                with winreg.OpenKey(root, sub) as key:
                    found += os.path.expandvars(winreg.QueryValueEx(key, 'Path')[0]).split(os.pathsep)
            except OSError:
                pass
        parts = os.environ.get('PATH', '').split(os.pathsep)
        have = {os.path.normcase(os.path.normpath(p)) for p in parts if p}
        extra = []
        for p in found:
            key = os.path.normcase(os.path.normpath(p)) if p else ''
            if key and key not in have:
                have.add(key)
                extra.append(p)
        if extra:
            os.environ['PATH'] = os.pathsep.join([p for p in parts if p] + extra)
    except Exception:
        pass            # the PATH this process started with still works


merge_registry_path()


def data_dir() -> Path:
    env = os.environ.get('CM_DATA_DIR')
    if env:
        return Path(env)
    if not FROZEN:
        return HOME / 'data'
    try:
        return Path(json.loads(POINTER.read_text(encoding='utf-8'))['data_dir'])
    except (OSError, ValueError, KeyError, TypeError):
        return HOME / 'data'


def set_data_dir(path: Path) -> None:
    """Point the installed app at an existing data folder (nothing is moved or copied)."""
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = POINTER.with_name('location-' + str(os.getpid()) + '.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps({'data_dir': str(Path(path).resolve())}, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(POINTER)


def env_path() -> Path:
    """The .env file. Installed: <home>\\.env; on first use it is copied (not moved) from the data
    folder's parent when one exists there, which is the repo root for a library that started from source."""
    path = HOME / '.env'
    if FROZEN and not path.exists() and not (LOCAL / 'private' / 'api-keys.dpapi').exists():
        legacy = data_dir().parent / '.env'
        try:
            if legacy.is_file():
                HOME.mkdir(parents=True, exist_ok=True)
                from core import private_storage
                private_storage._check_path(legacy)
                private_storage.write(path, legacy.read_bytes())
        except OSError:
            pass
    return path
