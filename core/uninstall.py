"""Interactive installed-app cleanup, without importing runtime paths or credentials."""
import csv
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from core import build_channel


def _checked_path(value, protected):
    path = Path(value)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError(f'Cleanup needs an absolute local folder: {path}')
    for part in (path, *path.parents):
        try:
            attrs = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Cleanup will not follow links or junctions: {part}')
    path = path.resolve()
    if any(path == p or path in p.parents for p in protected):
        raise ValueError(f'Cleanup will not delete a shared or system folder: {path}')
    if (path / '.git').exists() or (path / 'launch.pyw').exists():
        raise ValueError(f'Cleanup will not delete a source folder: {path}')
    return path


def cleanup_targets(env, installation, channel='official'):
    local = Path(env['LOCALAPPDATA']).resolve()
    protected = [local, Path(installation).resolve(), Path(__file__).resolve().parents[1]]
    system_trees = [Path(installation).resolve()]
    for key in ('USERPROFILE', 'APPDATA', 'PROGRAMDATA', 'SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'TEMP', 'TMP'):
        if env.get(key):
            protected.append(Path(env[key]).resolve())
            if key in ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)'):
                system_trees.append(Path(env[key]).resolve())
    if env.get('USERPROFILE'):
        profile = Path(env['USERPROFILE'])
        protected += [profile / name for name in ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Videos', 'Music', 'OneDrive')]
    if channel not in build_channel.HOME_NAMES:
        raise ValueError('Unknown uninstall build identity')
    contributor = channel in ('contributor', 'unverified')
    homes = ([local / build_channel.HOME_NAMES[channel]] if contributor else
             [local / 'Brainamon', local / 'Content Manager'])
    if contributor:
        # A contributor's explicit pointer must never enlist an official settings home.
        system_trees += [local / 'Brainamon', local / 'Content Manager']
    if env.get('BRAINAMON_HOME'):
        custom = _checked_path(env['BRAINAMON_HOME'], protected)
        if custom.is_dir() and any(custom.iterdir()) and not any((custom / name).is_file() for name in
                ('location.json', 'private/api-keys.dpapi', 'data/content_manager.db')):
            raise ValueError(f'Cannot identify this custom settings home; remove it manually after review: {custom}')
        homes.append(custom)
    libraries = []
    for home in dict.fromkeys(homes):
        home = _checked_path(home, protected)
        if not home.exists():
            continue
        if not home.is_dir():
            raise ValueError(f'Expected a settings folder: {home}')
        libraries.append(home / 'data')
        pointer = home / 'location.json'
        if pointer.exists():
            _checked_path(pointer, protected)
            value = json.loads(pointer.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or not isinstance(value.get('data_dir'), str) or not value['data_dir']:
                raise ValueError(f'Cannot read the library location in {pointer}')
            libraries.append(Path(value['data_dir']))
    if env.get('CM_DATA_DIR'):
        libraries.append(Path(env['CM_DATA_DIR']))
    targets = []
    for folder in [*libraries, *homes]:
        path = _checked_path(folder, protected)
        if any(parent == path or parent in path.parents for parent in system_trees):
            raise ValueError(f'Cleanup will not delete installed programs or system files: {path}')
        if not path.exists():
            continue
        if not path.is_dir():
            raise ValueError(f'Expected a data folder: {path}')
        if folder in libraries and not any(path == home / 'data' for home in homes):
            if not (path / 'content_manager.db').is_file():
                raise ValueError(f'Cannot identify this custom library; remove it manually after review: {path}')
        if path not in targets:
            targets.append(path)
    # Libraries go first, so their pointers survive a failure removing a library.
    return targets


def _preflight(targets):
    def fail(exc):
        raise exc
    for target in targets:
        _checked_path(target, [])
        for root, dirs, files in os.walk(target, onerror=fail, followlinks=False):
            for name in [*dirs, *files]:
                _checked_path(Path(root) / name, [])


def _app_running(executable_name='Brainamon.exe'):
    result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/tasklist.exe'),
                             '/FI', f'IMAGENAME eq {executable_name}', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return any(len(row) > 1 and row[0].casefold() == executable_name.casefold() and row[1] != str(os.getpid())
               for row in csv.reader(result.stdout.splitlines()))


def _message(text, flags):
    import ctypes
    return ctypes.windll.user32.MessageBoxW(0, text, 'Uninstall Brainamon', flags)


def main():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        return 1
    try:
        if _app_running(Path(sys.executable).name):
            raise ValueError('Quit Brainamon from its tray menu, including background windows, then retry uninstall.')
        channel = build_channel.read(Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent / '_internal')))
        targets = cleanup_targets(os.environ, Path(sys.executable).parent, channel)
        _preflight(targets)
        if not targets:
            _message('No local Brainamon data folders were found.', 0x40)
            return 0
        answer = _message('Permanently delete these folders and EVERYTHING inside them?\n\n' +
                          '\n'.join(map(str, targets)) + '\n\nThis cannot be undone. Back up anything you need first.\n'
                          'Independent exports/backups, phone/browser data and cloud copies stay.\n\n'
                          'Select No to stop uninstall without deleting data.', 0x134)
        if answer != 6:
            return 2
        if _app_running(Path(sys.executable).name):
            raise ValueError('Brainamon is running. Quit it from the tray menu and retry uninstall.')
        _preflight(targets)
        for path in targets:
            if path.exists():
                shutil.rmtree(path)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _message(f'Local data cleanup could not finish. Uninstall will stop.\n\n{exc}\n\n'
                 'Some files may already have been removed. Review the folders before retrying.', 0x10)
        return 1
