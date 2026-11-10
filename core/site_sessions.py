"""Windows user-scoped credentials, outside library exports. Never fall back to plaintext."""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import contextmanager, ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from core import app_paths

ROOT = app_paths.LOCAL / 'site-sessions'
MAX_BYTES = 1024 * 1024
SITES = {'instagram': ('instagram.com',), 'facebook': ('facebook.com',),
         'reddit': ('reddit.com',), 'threads': ('threads.com', 'threads.net'), 'youtube': ('youtube.com', 'youtu.be')}
SLOTS = ('general', 'instagram', 'browser-facebook', 'browser-instagram', 'browser-reddit', 'browser-threads')
_lock = threading.RLock()
_active = set()
_cancelled = set()


class SessionError(RuntimeError):
    code = 'authentication'
    action = 'sessions'


def supported():
    return sys.platform == 'win32'


def host(url):
    try:
        parsed = urlsplit(url)
        return (parsed.hostname or '').lower().rstrip('.') if parsed.scheme in ('http', 'https') else ''
    except ValueError:
        return ''


def matches(domain, root):
    domain = domain.lower().lstrip('.').rstrip('.')
    return domain == root or domain.endswith('.' + root)


def site_for(url):
    return next((site for site, roots in SITES.items() if any(matches(host(url), r) for r in roots)), '')


def _domain(value):
    domain = value.lstrip('.')
    if value.startswith('..') or not domain or len(domain) > 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in domain.split('.')):
        raise ValueError('Invalid cookie domain.')
    return value.lower()


def parse_cookies(raw, site=''):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError('Cookie files must be no larger than 1 MiB.')
    try:
        lines = raw.decode('utf-8-sig').splitlines()
    except UnicodeError:
        raise ValueError('Use a UTF-8 Netscape cookies.txt file.') from None
    first = next((line for line in lines if line.strip()), '')
    if first not in ('# Netscape HTTP Cookie File', '# HTTP Cookie File'):
        raise ValueError('Invalid file: expected a Netscape cookie header and seven-column records.')
    if site and site not in SITES:
        raise ValueError('Choose a supported site.')
    rows, expired = [], 0
    for line in lines:
        if not line or line.startswith('#') and not line.startswith('#HttpOnly_'):
            continue
        http_only = line.startswith('#HttpOnly_')
        fields = (line[10:] if http_only else line).split('\t')
        if len(fields) != 7 or any(any(ord(c) < 32 or ord(c) == 127 for c in f) for f in fields):
            raise ValueError('Invalid file: each cookie needs seven tab-separated fields.')
        domain, flag, path, secure, expiry, name, value = fields
        domain = _domain(domain)
        if flag != ('TRUE' if domain.startswith('.') else 'FALSE') or secure not in ('TRUE', 'FALSE') or not path.startswith('/') or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) \
                or not re.fullmatch(r'[0-9]{1,12}', expiry):
            raise ValueError('Invalid file: check cookie flags, path, name and expiry.')
        if site and not any(matches(domain, r) for r in SITES[site]):
            continue
        if int(expiry) and int(expiry) <= time.time():
            expired += 1
            continue
        rows.append(('' if not http_only else '#HttpOnly_') + '\t'.join((domain, flag, path, secure, expiry, name, value)))
    if not rows:
        raise ValueError('Invalid file: no usable cookies for the selected site (session expiry 0 is allowed).')
    normalized = ('# Netscape HTTP Cookie File\n' + '\n'.join(rows) + '\n').encode()
    domains = sorted({r.removeprefix('#HttpOnly_').split('\t')[0] for r in rows})
    return normalized, {'domains': domains, 'usable': len(rows), 'expired': expired,
                        'digest': hashlib.sha256(raw).hexdigest()}


def _acl(path):
    """Replace the DACL with current-user full access; disable inherited grants."""
    if not supported():
        raise RuntimeError('Protected sessions require Windows current-user DPAPI.')
    from ctypes import wintypes as w
    adv, kernel = ctypes.WinDLL('advapi32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    token, size, sid_text, descriptor = w.HANDLE(), w.DWORD(), w.LPWSTR(), ctypes.c_void_p()
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        sddl = f'D:P(A;OICI;FA;;;{sid_text.value})'
        if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None) \
                or not adv.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def _crypt(raw, decrypt=False):
    if not supported():
        raise RuntimeError('Protected sessions require Windows current-user DPAPI.')
    from ctypes import wintypes as w
    class Blob(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, w.DWORD, ctypes.POINTER(Blob)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise RuntimeError('Cannot unlock on this PC. Re-import or sign in again.' if decrypt else 'Windows could not protect the session.')
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        kernel.LocalFree(dest.data)


def secure_dir(path):
    path = Path(path)
    if path.resolve() != ROOT.resolve() and ROOT.resolve() not in path.resolve().parents:
        raise RuntimeError('Session directory is outside app-owned storage.')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise RuntimeError('Session storage cannot use links or junctions.')
        if part == ROOT.parent:
            break
    path.mkdir(parents=True, exist_ok=True)
    _acl(path)
    return path


def _atomic(path, raw):
    secure_dir(path.parent)
    temp = path.parent / (uuid.uuid4().hex + '.new')
    try:
        with temp.open('xb') as f:
            _acl(temp)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _slot(slot):
    if slot not in SLOTS:
        raise ValueError('Unknown session slot.')
    return ROOT / (slot + '.bin')


def modes():
    try:
        value = json.loads((ROOT / 'modes.json').read_text(encoding='utf-8'))
        if not isinstance(value, dict) or any(value.get(s) not in (None, 'none', 'legacy', 'protected', 'disabled') for s in SLOTS):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise RuntimeError('Cannot read local session policy. Re-import saved access on this PC.') from None


def mode(slot, lookups=()):
    saved = modes().get(slot)
    if saved:
        return saved
    # Legacy use is an explicit migration choice. New libraries discover no credentials.
    return next((get('session_mode_' + slot) for get in lookups if get('session_mode_' + slot)), 'none')


def _set_mode(slot, value):
    try:
        metadata = modes()
    except RuntimeError:
        metadata = {s: 'disabled' for s in SLOTS}  # explicit save/Forget repairs policy fail-closed
    metadata[slot] = value
    metadata[slot + '-generation'] = uuid.uuid4().hex
    _atomic(ROOT / 'modes.json', json.dumps(metadata).encode())


def save(slot, raw):
    with _lock:
        path = _slot(slot)
        encrypted = b'BAS1' + _crypt(raw)
        previous = path.read_bytes() if path.exists() else None
        _atomic(path, encrypted)
        try:
            _set_mode(slot, 'protected')
        except BaseException:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                _atomic(path, previous)
            raise


def load(slot):
    raw = _slot(slot).read_bytes()
    if len(raw) > MAX_BYTES + 65536 or not raw.startswith(b'BAS1'):
        raise RuntimeError('Cannot unlock on this PC. Re-import or sign in again.')
    return _crypt(raw[4:], decrypt=True)


def forget(slots):
    with _lock:
        _cancelled.update(_active)
        for slot in slots:
            _slot(slot)
            _set_mode(slot, 'disabled')
            _slot(slot).unlink(missing_ok=True)


def summary(slot, lookups=()):
    try:
        current = mode(slot, lookups)
    except RuntimeError:
        return {'slot': slot, 'mode': 'unavailable', 'status': 'Cannot unlock on this PC', 'domains': [], 'usable': 0, 'expired': 0}
    out = {'slot': slot, 'mode': current, 'status': 'Not provided (optional)', 'domains': [], 'usable': 0, 'expired': 0}
    if current == 'disabled':
        out['status'] = 'Forgotten; legacy fallback disabled'
    elif current == 'legacy':
        out['status'] = 'Legacy file mode; import a protected copy or Disconnect' if legacy_path(slot, lookups) else 'Not provided (optional)'
    elif current == 'protected':
        try:
            if slot.startswith('browser-'):
                state = validate_state(load(slot), slot[8:])
                out['domains'] = sorted({c['domain'] for c in state['cookies']})
                out['usable'] = len(state['cookies'])
            else:
                _, info = parse_cookies(load(slot))
                out.update({k: info[k] for k in ('domains', 'usable', 'expired')})
            out['status'] = 'Saved; not tested'
        except ValueError:
            out['status'] = 'Sign-in may need refreshing'
        except (OSError, RuntimeError):
            out['status'] = 'Cannot unlock on this PC'
    return out


@contextmanager
def temporary(suffix):
    directory = secure_dir(ROOT / 'temp' / f'{os.getpid()}-{uuid.uuid4().hex}')
    path = directory / ('access' + suffix)
    with _lock:
        _active.add(directory)
    try:
        with path.open('xb'):
            _acl(path)
        yield path
    finally:
        try:
            shutil.rmtree(directory)
        finally:
            with _lock:
                _active.discard(directory)
                _cancelled.discard(directory)


def revoked(path):
    with _lock:
        return bool(path and Path(path).parent in _cancelled)


def busy():
    with _lock:
        return bool(_active)


def cleanup_stale():
    """Only this app's stopped process directories; never another live server/job."""
    if not supported() or not (ROOT / 'temp').exists():
        return
    for directory in (ROOT / 'temp').iterdir():
        with _lock:
            if directory in _active:
                continue
        if not re.fullmatch(r'[0-9]+-[0-9a-f]{32}', directory.name):
            continue
        pid = int(directory.name.split('-')[0])
        if pid != os.getpid():
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                kernel.CloseHandle(handle)
                continue
            if ctypes.get_last_error() != 87:  # access denied is not proof the owner exited
                continue
        secure_dir(directory)
        shutil.rmtree(directory)


def legacy_path(slot, lookups):
    if mode(slot, lookups) != 'legacy':
        return None
    key = 'instagram_cookies' if slot == 'instagram' else 'yt_dlp_cookies'
    candidates = [get(key) for get in lookups]
    candidates += [os.environ.get('YTDLP_COOKIES', '')] if slot == 'general' else []
    candidates += ['Instagram_cookies.txt' if slot == 'instagram' else 'cookies.txt']
    return next((Path(p) for p in candidates if p and Path(p).is_file()), None)


@contextmanager
def cookies(url, lookups=(), refresh=True):
    with ExitStack() as stack:
        # Register the temporary operation under the policy lock so Forget cannot miss it.
        with _lock:
            try:
                slot = 'instagram' if site_for(url) == 'instagram' else 'general'
                selected = mode(slot, lookups)
                if slot == 'instagram' and selected == 'none':
                    slot, selected = 'general', mode('general', lookups)
                path = None
                raw = None
                if selected == 'legacy':
                    legacy = legacy_path(slot, lookups)
                    if legacy:
                        with legacy.open('rb') as f:
                            raw = f.read(MAX_BYTES + 1)
                elif selected == 'protected':
                    raw = load(slot)
                generation = modes().get(slot + '-generation')
                if raw is not None:
                    # Keep a cookie jar: yt-dlp applies domain/path/secure checks on redirects.
                    _, original = parse_cookies(raw)
                    path = stack.enter_context(temporary('.txt'))
                    path.write_bytes(raw)
            except (OSError, RuntimeError, ValueError):
                raise SessionError('Saved login has expired or cannot be read on this PC. Replace saved login in Settings > Downloads, then test this link.') from None
        yield path
        if path and refresh and selected == 'protected':
            try:
                with path.open('rb') as f:
                    refreshed, info = parse_cookies(f.read(MAX_BYTES + 1))
                if any(not any(matches(d, root.lstrip('.')) for root in original['domains']) for d in info['domains']):
                    return
            except (OSError, ValueError):
                return  # invalid child output never replaces a good secret
            with _lock:
                if mode(slot) == 'protected' and modes().get(slot + '-generation') == generation:
                    save(slot, refreshed)


@contextmanager
def browser_state(site, remember=False):
    slot = 'browser-' + site
    with ExitStack() as stack:
        with _lock:
            generation = modes().get(slot + '-generation')
            path = stack.enter_context(temporary('.json'))
            if mode(slot) == 'protected':
                raw = load(slot)
                validate_state(raw, site)
                path.write_bytes(raw)
        yield path
        with _lock:
            if remember and modes().get(slot + '-generation') == generation:
                with path.open('rb') as f:
                    raw = f.read(MAX_BYTES + 1)
                validate_state(raw, site)
                save(slot, raw)


def validate_state(raw, site):
    if len(raw) > MAX_BYTES or site not in SITES:
        raise ValueError('Invalid or oversized browser state.')
    try:
        state = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Invalid browser state.') from None
    if not isinstance(state, dict) or set(state) - {'cookies', 'origins'} or not isinstance(state.get('cookies'), list) or not isinstance(state.get('origins'), list):
        raise ValueError('Invalid browser state.')
    for cookie in state['cookies']:
        if not isinstance(cookie, dict) or not isinstance(cookie.get('domain'), str) or not any(matches(_domain(cookie['domain']), root) for root in SITES[site]) \
                or not isinstance(cookie.get('name'), str) or not cookie['name'] or not isinstance(cookie.get('value'), str) \
                or not isinstance(cookie.get('path'), str) or not cookie['path'].startswith('/') \
                or not isinstance(cookie.get('expires'), (int, float)) or cookie['expires'] != cookie['expires'] \
                or cookie['expires'] < -1 or cookie['expires'] > 999999999999 \
                or type(cookie.get('httpOnly')) is not bool or type(cookie.get('secure')) is not bool \
                or cookie.get('sameSite') not in ('Strict', 'Lax', 'None'):
            raise ValueError('Invalid or unrelated browser cookie.')
    for origin in state['origins']:
        if not isinstance(origin, dict) or not isinstance(origin.get('origin'), str):
            raise ValueError('Invalid browser origin.')
        parsed = urlsplit(origin['origin'])
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment \
                or not any(matches(host(origin['origin']), root) for root in SITES[site]) \
                or not isinstance(origin.get('localStorage'), list) \
                or any(not isinstance(row, dict) or set(row) != {'name', 'value'} or any(not isinstance(v, str) for v in row.values()) for row in origin['localStorage']):
            raise ValueError('Invalid or unrelated browser origin.')
    return state


def reuse_browser(site, commit=False, digest=''):
    """An explicit review/commit exports cookies only; local storage never becomes download headers."""
    if site not in ('facebook', 'instagram', 'reddit', 'threads'):
        raise ValueError('Choose a supported remembered browser login.')
    with _lock:
        slot = 'browser-' + site
        if mode(slot) != 'protected':
            raise ValueError('Remember this browser login before reusing it.')
        state = validate_state(load(slot), site)
        lines = ['# Netscape HTTP Cookie File']
        for cookie in state['cookies']:
            fields = (cookie['domain'], 'TRUE' if cookie['domain'].startswith('.') else 'FALSE', cookie['path'],
                      'TRUE' if cookie['secure'] else 'FALSE', str(max(0, int(cookie['expires']))), cookie['name'], cookie['value'])
            lines.append(('#HttpOnly_' if cookie['httpOnly'] else '') + '\t'.join(fields))
        raw, info = parse_cookies(('\n'.join(lines) + '\n').encode(), site)
        target = 'instagram' if site == 'instagram' else 'general'
        if commit:
            if digest != info['digest']:
                raise ValueError('Browser state changed. Review the domains again.')
            save(target, raw)
        return {**info, 'target': target, 'status': 'Saved; not tested' if commit else 'Review before replacing download access'}
