"""Read-only payload gate. Errors contain filenames/counts, never matched values."""
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

OAUTH = {'BRAINAMON_GOOGLE_CLIENT_ID', 'BRAINAMON_GOOGLE_CLIENT_SECRET', 'BRAINAMON_GOOGLE_WEB_CLIENT_ID'}
PRIVATE_DIRS = {'cloud', 'private', 'site-sessions', 'auth', 'local', 'facebook-profile', 'instagram-profile',
                'reddit-profile', 'playwright', 'browser-state', 'user data'}
PRIVATE = re.compile(r'(?i)(^\.env($|\.)|google_token|mirror\.key|rotation.*\.json|vault_base|storage-state|'
                     r'^(private|issuer|signing)[-_.]|(^|[-_.])(private|issuer|signing)[-_.]?key|\.(pfx|p12|key|dpapi|jks|keystore)($|[.-])|pair-transfers\.json|cookies($|[-_.])|login data|web data)')
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|'
                    rb'"(?:refresh_token|access_token|private_key|api_key|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY|master_key|mirror_key)"\s*:\s*"[^"\s]+"|'
                    rb'(?:sk-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,})')


def forbidden(name, raw=None):
    path = PurePosixPath(name.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts or any(p.lower() in PRIVATE_DIRS for p in path.parts[:-1]):
        return True
    if PRIVATE.search(path.name):
        return True
    if path.name == 'google-oauth.json':
        try:
            value = json.loads(raw)
            if value == {}:
                return False              # contributor builds without an OAuth registration
            return not isinstance(value, dict) or set(value) != OAUTH or any(not isinstance(v, str) for v in value.values())
        except (ValueError, TypeError, UnicodeError):
            return True
    return raw is not None and bool(SECRET.search(raw))


def inspect_payload(path):
    """Inspect expanded files or a ZIP/APK without extraction; return relative filenames only."""
    path = Path(path)
    bad = []
    if path.is_dir():
        for item in path.rglob('*'):
            name = item.relative_to(path).as_posix()
            if item.is_symlink() or item.is_junction():
                bad.append(name)
            elif item.is_file() and forbidden(name, item.read_bytes()):
                bad.append(name)
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                if item.file_size > 512 * 1024 * 1024 or item.compress_size == 0 and item.file_size:
                    bad.append(item.filename)
                    continue
                if forbidden(item.filename, archive.read(item)):
                    bad.append(item.filename)
    else:
        raise ValueError('Final payload format cannot be inspected with the available gate.')
    return sorted(set(bad))


if __name__ == '__main__':
    import sys
    try:
        leaks = inspect_payload(sys.argv[1])
        if leaks:
            print(f'Private payload files ({len(leaks)}): ' + ', '.join(leaks), file=sys.stderr)
            raise SystemExit(1)
        print('Payload private-file gate passed.')
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(type(error).__name__ + ': payload inspection failed', file=sys.stderr)
        raise SystemExit(1)
