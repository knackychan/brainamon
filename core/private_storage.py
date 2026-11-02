"""Current-user secret files; verified, recoverable migration from legacy plaintext."""
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from core import app_paths, site_sessions

LOCK = threading.RLock()
SENTINEL = b'Brainamon protected storage; do not downgrade.\n'


def _check_path(path):
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise RuntimeError('Private storage cannot use links or junctions.')


def _secure(path):
    _check_path(path)
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'win32':
        site_sessions._acl(path)
    else:
        path.chmod(0o700)


def location(path):
    path = Path(path)
    if sys.platform != 'win32':
        return path
    if path == app_paths.HOME / '.env':
        return app_paths.LOCAL / 'private' / 'api-keys.dpapi'
    return path.parent / 'private' / (path.name + '.dpapi')


def write(path, raw):
    path = Path(path)
    target = location(path)
    with LOCK:
        _secure(target.parent)
        _check_path(target)
        _check_path(path)
        previous = target.with_name(target.name + '.previous')
        _check_path(previous)
        sealed = site_sessions._crypt(raw) if sys.platform == 'win32' else raw
        temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.new')
        try:
            with temp.open('xb') as stream:
                if sys.platform == 'win32':
                    site_sessions._acl(temp)
                else:
                    temp.chmod(0o600)
                stream.write(sealed)
                stream.flush()
                os.fsync(stream.fileno())
            check = temp.read_bytes()
            if (site_sessions._crypt(check, decrypt=True) if sys.platform == 'win32' else check) != raw:
                raise RuntimeError('Protected write verification failed; previous secret retained.')
            if target.exists():
                # Ciphertext only; retain the last verified value until final read-back succeeds.
                old = target.read_bytes()
                if sys.platform == 'win32':
                    site_sessions._crypt(old, decrypt=True)
                with previous.open('wb') as backup:
                    if sys.platform == 'win32':
                        site_sessions._acl(previous)
                    else:
                        previous.chmod(0o600)
                    backup.write(old)
                    backup.flush()
                    os.fsync(backup.fileno())
            for attempt in range(5):
                try:
                    os.replace(temp, target)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(.1 * (attempt + 1))
            if sys.platform == 'win32' and site_sessions._crypt(target.read_bytes(), decrypt=True) != raw:
                if previous.exists():
                    os.replace(previous, target)
                raise RuntimeError('Protected read-back failed; previous secret retained.')
            previous.unlink(missing_ok=True)
            _retire(path, target)
        finally:
            temp.unlink(missing_ok=True)


def _retire(path, target):
    if target == path:
        return
    _check_path(path)
    if path.name == 'mirror.key':
        # Older desktop builds must fail closed instead of generating a replacement key.
        if not path.exists() or path.read_bytes() != SENTINEL:
            marker = target.with_name(target.name + '.marker')
            _check_path(marker)
            try:
                marker.write_bytes(SENTINEL)
                site_sessions._acl(marker)
                os.replace(marker, path)
            finally:
                marker.unlink(missing_ok=True)
    else:
        path.unlink(missing_ok=True)
    legacy_temp = path.with_suffix('.tmp')
    _check_path(legacy_temp)
    if legacy_temp.exists() and legacy_temp != path:
        write(legacy_temp, legacy_temp.read_bytes())


def read(path, *, readonly=False):
    path = Path(path)
    target = location(path)
    with LOCK:
        _check_path(target)
        _check_path(path)
        previous = target.with_name(target.name + '.previous')
        _check_path(previous)
        if not target.exists() and previous.exists():
            data = previous.read_bytes()
            if sys.platform == 'win32':
                site_sessions._crypt(data, decrypt=True)
            if not readonly:
                os.replace(previous, target)
        if target.exists() or (readonly and previous.exists()):
            if not readonly:
                _secure(target.parent)
                if sys.platform == 'win32':
                    site_sessions._acl(target)
                else:
                    target.chmod(0o600)
            data = (target if target.exists() else previous).read_bytes()
            try:
                raw = site_sessions._crypt(data, decrypt=True) if sys.platform == 'win32' else data
            except RuntimeError:
                if not previous.exists():
                    raise
                raw = site_sessions._crypt(previous.read_bytes(), decrypt=True)
                if not readonly:
                    os.replace(previous, target)
            # Windows text tools can change the marker's newline; never normalize actual secrets.
            if target != path and path.exists() and path.read_bytes() not in (raw, SENTINEL, SENTINEL.replace(b'\n', b'\r\n')):
                raise RuntimeError('Legacy and protected secrets differ; both retained for recovery.')
            if not readonly:
                _retire(path, target)
            return raw
        if target != path and path.exists():
            if path.is_symlink() or path.is_junction():
                raise RuntimeError('Legacy private storage cannot use links or junctions.')
            data = path.read_bytes()
            if not readonly:
                write(path, data)
            return data
        if path.with_suffix('.tmp').exists():
            raise RuntimeError('A legacy temporary secret needs recovery; refusing to replace it.')
        raise FileNotFoundError(path.name)


def remove(path):
    with LOCK:
        target = location(path)
        _check_path(target)
        _check_path(Path(path))
        _check_path(target.with_name(target.name + '.previous'))
        target.unlink(missing_ok=True)
        target.with_name(target.name + '.previous').unlink(missing_ok=True)
        Path(path).unlink(missing_ok=True)
