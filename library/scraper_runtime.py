"""User-installed browser tools. The frozen executable is never a Python worker."""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core import app_paths

PIN = '1.61.0'
ROOT = app_paths.LOCAL / 'tools' / 'scraper'
REQS = app_paths.BUNDLE / 'packaging' / 'requirements-scraper.txt'
PROBE = ("from importlib.metadata import version; assert version('playwright') == '" + PIN + "'; "
         "from playwright.sync_api import sync_playwright; "
         "p=sync_playwright().start(); b=p.chromium.launch(headless=True, channel='chromium'); "
         "page=b.new_page(); page.goto('about:blank'); b.close(); p.stop()")
_lock = threading.RLock()
_cancel = threading.Event()
_state = None
_users = 0
_checked = None


def supported():
    # Windows 10 2004 (build 19041) or later; the browser check still has to pass before use.
    return sys.platform == 'win32' and sys.getwindowsversion().build >= 19041 and platform.machine().lower() in ('amd64', 'arm64')


def _json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.new')
    temp.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temp, path)


def _owned(path):
    """Reject links/junctions before deleting or executing app-owned runtime entries."""
    root, target = ROOT.resolve(), Path(path)
    if ROOT.is_symlink() or ROOT.is_junction() or target.resolve() == root or root not in target.resolve().parents:
        raise RuntimeError('Browser tools path is outside the app-owned runtime.')
    for part in (target, *target.parents):
        if part.is_symlink() or part.is_junction():
            raise RuntimeError('Browser tools directory contains a link or junction.')
    return target


def interpreter(folder):
    return Path(folder) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def environment(folder):
    return {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(Path(folder) / 'browsers')}


def kill_tree(proc):
    if proc.poll() is None:
        if os.name == 'nt':
            try:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                               timeout=15, creationflags=app_paths.NO_WINDOW)
            finally:
                if proc.poll() is None:
                    proc.kill()
        elif proc.poll() is None:
            proc.kill()
        proc.wait(timeout=15)


def _run(args, env=None, timeout=900, cancellable=True):
    proc = subprocess.Popen([str(a) for a in args], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, creationflags=app_paths.NO_WINDOW)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancellable and _cancel.is_set():
                raise RuntimeError('Installation cancelled. Retry when ready.')
            if time.monotonic() >= deadline:
                raise RuntimeError('Browser tools timed out. Check your connection and retry.')
            try:
                output, _ = proc.communicate(timeout=.3)
                if proc.returncode:
                    raise RuntimeError('Browser tools command failed. Check free disk space, network access and Python; then retry.')
                return output.decode('utf-8', errors='replace').strip()
            except subprocess.TimeoutExpired:
                pass
    finally:
        kill_tree(proc)


def discover_python():
    probe_env = {**os.environ, 'PYTHON_MANAGER_AUTOMATIC_INSTALL': 'false'}
    selected = _json(ROOT / 'selected.json').get('python', '')
    candidates = ([selected] if selected else []) + ([] if app_paths.FROZEN else [sys.executable])
    for name in ('python3.14', 'python'):
        if found := shutil.which(name):
            if 'windowsapps' not in found.lower():
                candidates.append(found)
    if launcher := shutil.which('py'):
        try:
            # Listing works with both Windows launchers and cannot auto-install a missing runtime.
            listing = _run([launcher, '-0p'], env=probe_env, timeout=10, cancellable=False)
            candidates.extend(re.findall(r'([A-Za-z]:\\.*?python[0-9.]*\.exe)\s*$', listing, re.MULTILINE | re.IGNORECASE))
        except (OSError, RuntimeError):
            pass
    for candidate in dict.fromkeys(candidates):
        try:
            _run([candidate, '-c', 'import sys,struct; assert sys.version_info[:2] == (3,14) and struct.calcsize("P") == 8'], env=probe_env, timeout=10, cancellable=False)
            return candidate
        except (OSError, RuntimeError):
            pass
    return ''


def _active():
    name = _json(ROOT / 'active.json').get('name', '')
    if not isinstance(name, str) or not name.startswith('runtime-') or Path(name).name != name:
        return None
    return _owned(ROOT / name)


def runtime_location():
    selected = _json(ROOT / 'selected.json').get('environment', '')
    if selected:
        folder = Path(selected)
        return folder, str(interpreter(folder)), 'Selected project environment'
    folder = _active()
    return folder, str(interpreter(folder)) if folder else (sys.executable if not app_paths.FROZEN else ''), 'Managed by Brainamon' if folder else 'Current project environment'


def runtime_env(folder):
    return environment(folder) if folder and (folder == _active() or (Path(folder) / 'browsers').is_dir()) else os.environ.copy()


def select_location(kind, raw):
    global _checked
    if kind not in ('environment', 'python') or not isinstance(raw, str):
        raise ValueError('Choose a browser environment or Python folder.')
    with _lock:
        if _users or (_state and _state.get('state') == 'installing'):
            raise RuntimeError('Stop the scraper or installer before changing its location.')
        selected = _json(ROOT / 'selected.json')
        if raw.strip():
            folder = Path(raw.strip())
            if not folder.is_absolute() or not folder.is_dir():
                raise ValueError('Choose an existing absolute folder path.')
            folder = folder.resolve()
            if kind == 'environment':
                if not interpreter(folder).is_file():
                    raise ValueError('Choose the environment folder containing Scripts/python.exe (or bin/python).')
                probe(folder)
                selected[kind] = str(folder)
            else:
                py = folder / ('python.exe' if os.name == 'nt' else 'python')
                if not py.is_file():
                    raise ValueError('Choose the folder containing Python.')
                _run([py, '-c', 'import sys,struct; assert sys.version_info[:2] == (3,14) and struct.calcsize("P") == 8'], timeout=10, cancellable=False)
                selected[kind] = str(py)
        else:
            selected.pop(kind, None)
        _write(ROOT / 'selected.json', selected)
        _checked = None
        return status(recheck=True)


def probe(folder, python=None):
    _run([python or interpreter(folder), '-c', PROBE], runtime_env(folder), timeout=35, cancellable=False)


def status(recheck=False):
    global _checked
    from library import scrape_watch
    with _lock:
        state = dict(_state or _json(ROOT / 'install.json'))
        if state.get('state') == 'installing' and _state is None:
            state = {'state': 'failed', 'error': 'Installation was interrupted. Retry browser tools.'}
        selected = _json(ROOT / 'selected.json')
        common = {'environment': selected.get('environment', ''), 'python_path': selected.get('python', ''), 'managed': False, 'supported': supported(), 'workers': all(scrape_watch.playwright_script(k).is_file() for k in scrape_watch.PLAYWRIGHT),
                  'python': bool(discover_python()) if state.get('state') != 'installing' else False,
                  'winget': bool(shutil.which('winget')), 'step': '', 'error': ''}
        if state.get('state') == 'installing':
            return {**common, **state}
        version = ''
        py = ''
        try:
            folder, py, source = runtime_location()
            common.update(path=py, source=source, managed=source == 'Managed by Brainamon')
            key = (str(folder), py)
            if py and (recheck or _checked != key):
                probe(folder, py)
                _checked = key
            if py and _checked == key and common['workers']:
                return {**common, 'state': 'ready', 'version': PIN, 'error': state.get('error', '')}
        except (OSError, RuntimeError):
            _checked = None
            if py:
                try:
                    version = _run([py, '-c', "from importlib.metadata import version; print(version('playwright'))"], timeout=10, cancellable=False)
                except (OSError, RuntimeError):
                    pass
        if re.fullmatch(r'\d+\.\d+\.\d+', version) and tuple(map(int, version.split('.'))) < tuple(map(int, PIN.split('.'))):
            return {**common, 'state': 'older', 'version': version}
        failed = state.get('state') in ('ready', 'failed')
        return {**common, 'state': 'failed' if failed or version else 'missing', 'version': version,
                'error': state.get('error', '') or ('Browser tools failed the local probe. Retry or reinstall them.' if failed else '')}


@contextmanager
def use():
    global _users
    with _lock:
        if status()['state'] != 'ready':
            raise RuntimeError('Browser tools are not ready. Open Help or Settings > Tools to install/check them.')
        folder, py, _ = runtime_location()
        env = runtime_env(folder)
        _users += 1
    try:
        yield py, env
    finally:
        with _lock:
            _users -= 1


def _install(python_only=False):
    global _checked
    folder = None
    cleanup_error = ''
    try:
        if python_only:
            winget = shutil.which('winget')
            if not winget:
                raise RuntimeError('Install Python 3.14 from python.org, then Check again.')
            _run([winget, 'install', '--id', 'Python.Python.3.14', '-e', '--scope', 'user',
                  '--accept-package-agreements', '--accept-source-agreements'])
            app_paths.apply_tools_dir(str(Path(os.environ['LOCALAPPDATA']) / 'Microsoft/WinGet/Links'))
        else:
            py = discover_python()
            if not py:
                raise RuntimeError('Install Python 3.14, then Check again.')
            if shutil.disk_usage(ROOT.parent).free < 2 * 1024**3:
                raise RuntimeError('Keep at least 2 GiB free for installation and retry.')
            folder = _owned(ROOT / ('runtime-' + uuid.uuid4().hex))
            _state.update(step='Creating isolated Python environment')
            _run([py, '-m', 'venv', folder], env={**os.environ, 'PYTHON_MANAGER_AUTOMATIC_INSTALL': 'false'})
            _state.update(step='Installing Playwright ' + PIN)
            _run([interpreter(folder), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', REQS])
            _state.update(step='Downloading Chromium')
            _run([interpreter(folder), '-m', 'playwright', 'install', 'chromium', '--no-shell'], environment(folder))
            _state.update(step='Checking local browser')
            probe(folder)
            if _cancel.is_set():
                raise RuntimeError('Installation cancelled. Retry when ready.')
            selected = _json(ROOT / 'selected.json')
            selected.pop('environment', None)
            _write(ROOT / 'selected.json', selected)
            _write(ROOT / 'active.json', {'name': folder.name})
            _checked = (str(folder), str(interpreter(folder)))
            active = folder
            folder = None
            for entry in ROOT.glob('runtime-*'):
                if entry != active:
                    try:
                        shutil.rmtree(_owned(entry))
                    except (OSError, RuntimeError):
                        cleanup_error = 'Browser tools are ready, but old runtime cleanup failed. Close browser tools and retry installation or removal.'
        _state.update(state='ready' if not python_only else 'missing', step='', error=cleanup_error)
    except Exception as exc:
        _state.update(state='failed', step='', error=str(exc) if isinstance(exc, RuntimeError) else 'Installation failed. Check disk access and retry.')
    finally:
        if folder and folder.exists():
            try:
                shutil.rmtree(_owned(folder))
            except OSError:
                _state.update(state='failed', error='Installation failed; temporary runtime cleanup failed. Close browser tools and retry removal.')
        _write(ROOT / 'install.json', _state)


def action(name):
    global _state, _checked
    with _lock:
        if name == 'cancel':
            _cancel.set()
            return status()
        if _users or (_state and _state['state'] == 'installing'):
            raise RuntimeError('Browser tools are in use. Stop the scraper or installer and wait before changing them.')
        if name == 'remove':
            # Never follow a pointer supplied by a settings file to remove anything outside ROOT.
            for entry in ROOT.glob('runtime-*'):
                shutil.rmtree(_owned(entry))
            for name_ in ('active.json', 'install.json'):
                (ROOT / name_).unlink(missing_ok=True)
            _state, _checked = None, None
            return status()
        if name not in ('install', 'python'):
            raise ValueError('Unknown browser tools action.')
        if not supported():
            raise RuntimeError('The optional installer requires Windows 10 (version 2004 or later) or Windows 11, x64 or ARM64.')
        _owned(ROOT / 'install.json')
        ROOT.mkdir(parents=True, exist_ok=True)
        _cancel.clear()
        _state = {'state': 'installing', 'step': 'Preparing browser tools', 'error': ''}
        _write(ROOT / 'install.json', _state)
        threading.Thread(target=_install, args=(name == 'python',), name='cm-scraper-install', daemon=True).start()
        return status()
