"""Updates from GitHub Releases, authenticated by the pinned Ed25519 update key.

The releases live in a public releases-only repo (BRAINSTORM D7: the source repo is private and
has user data in its history): github.com/knackychan/brainamon. Each release is tagged vX.Y.Z and
carries an installer, .sha256 checksum and signed .update.json manifest.

- check(): the latest release vs version.__version__ (unauthenticated GitHub API, 5 s timeout).
- download(): installer + .sha256 into <app home>/updates/, the SHA-256 verified before it is kept.
  start_download() runs it on a daemon thread and status() reports bytes done (GitHub's asset CDN
  can be slow, 30 KB/s was measured here, so the page polls instead of waiting on one request).
- launch(): queues the verified installer after all app processes exit (silent; replaces the
  files and restarts the app). Only ever called from an explicit click in Settings.
- backup_on_upgrade(): on the first start of a new version, a consistent copy of the DB goes to
  data/backups/ before the Writer opens it (and runs db._migrate()).
"""
import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

from core import app_paths, update_signing
from core.version import __version__

RELEASES_REPO = update_signing.REPOSITORY
API = f'https://api.github.com/repos/{RELEASES_REPO}/releases/latest'
ASSET_RE = re.compile(r'^Brainamon-Setup-(\d+\.\d+\.\d+)\.exe$')
UPDATES = app_paths.HOME / 'updates'
MAX_INSTALLER_SIZE = 1024 * 1024 * 1024
MAX_METADATA_SIZE = 2 * 1024 * 1024
INSTALL_EXIT_TIMEOUT = 120


def _allowed_url(url):
    u = urllib.parse.urlsplit(url)
    return (u.scheme == 'https' and not u.username and not u.password and u.port in (None, 443)
            and (url == API or u.hostname in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com')
                 or u.hostname == 'github.com' and u.path.startswith(f'/{RELEASES_REPO}/releases/download/')))


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl) or req.full_url == API and newurl != API:
            raise ValueError('Untrusted update redirect.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(req, timeout):
    if not _allowed_url(req.full_url):
        raise ValueError('Untrusted update origin.')
    return urllib.request.build_opener(_RedirectGuard()).open(req, timeout=timeout)


def parse_version(v: str) -> tuple:
    m = re.match(r'^v?(\d+)\.(\d+)\.(\d+)', (v or '').strip())
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _get(url: str, timeout: float = 5.0) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': f'Brainamon/{__version__}',
                                               'Accept': 'application/vnd.github+json'})
    with _open(req, timeout) as r:
        limit = MAX_METADATA_SIZE if url == API else 4096
        data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Update metadata is too large.')
        return data


def _get_chunks(url: str, timeout: float = 60.0):
    """(total bytes or 0, an iterator of chunks); the timeout is per read, not for the whole file."""
    def chunks():
        req = urllib.request.Request(url, headers={'User-Agent': f'Brainamon/{__version__}'})
        with _open(req, timeout) as r:
            total = int(r.headers.get('Content-Length') or 0)
            if total < 0 or total > MAX_INSTALLER_SIZE:
                raise ValueError('Installer is too large.')
            while block := r.read(256 * 1024):
                yield block
    return 0, chunks()


def check() -> dict:
    """{"current", "latest", "newer", "notes", "name", "url", "sha_url", "size", "digest"} or {"current", "error"}."""
    out = {'current': __version__}
    try:
        rel = json.loads(_get(API))
    except Exception as e:
        return {**out, 'error': f'Could not check for updates ({e.__class__.__name__}).'}
    latest = ''
    try:
        if not isinstance(rel, dict) or rel.get('draft') or rel.get('prerelease'):
            raise ValueError
        tag = rel.get('tag_name') or ''
        if not isinstance(tag, str) or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
            raise ValueError
        latest = tag[1:]
        assets = {a['name']: a for a in rel['assets'] if isinstance(a, dict) and isinstance(a.get('name'), str)}
        name = f'Brainamon-Setup-{latest}.exe'
        exe, sha, manifest = assets[name], assets[name + '.sha256'], assets[name + '.update.json']
        base = f'https://github.com/{RELEASES_REPO}/releases/download/{tag}/'
        if (exe.get('browser_download_url') != base + name or
                sha.get('browser_download_url') != base + name + '.sha256' or
                manifest.get('browser_download_url') != base + name + '.update.json' or
                type(manifest.get('size')) is not int or not 0 < manifest['size'] <= update_signing.MAX_MANIFEST_SIZE or
                type(exe.get('size')) is not int or not 0 < exe['size'] <= MAX_INSTALLER_SIZE or
                type(sha.get('size')) is not int or not 0 < sha['size'] <= 4096):
            raise ValueError
        notes = rel.get('body') or ''
        if not isinstance(notes, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return {**out, 'latest': latest, 'error': 'The latest release needs an installer, checksum and signed update manifest.'}
    return {**out, 'latest': latest, 'newer': parse_version(latest) > parse_version(__version__),
            'notes': notes, 'name': exe['name'], 'url': exe['browser_download_url'],
            'sha_url': sha['browser_download_url'], 'size': exe['size'],
            'manifest_url': manifest['browser_download_url'],
            'digest': exe.get('digest') or ''}


def expected_sha(sha_file_text: str) -> str:
    tok = (sha_file_text.strip().split() or [''])[0].lower()
    if not re.fullmatch(r'[0-9a-f]{64}', tok):
        raise ValueError('The .sha256 asset is not a SHA-256 checksum.')
    return tok


def download(info: dict, progress=None) -> Path:
    """The installer from check(), verified; raises ValueError when the checksum does not match.
    progress(done, total) is called after every chunk."""
    match = ASSET_RE.fullmatch(info.get('name', ''))
    if not match or match.group(1) != info.get('latest'):
        raise ValueError('Not a Brainamon installer.')
    base = f'https://github.com/{RELEASES_REPO}/releases/download/v{info["latest"]}/{info["name"]}'
    if (info.get('url') != base or info.get('sha_url') != base + '.sha256'
            or info.get('manifest_url') != base + '.update.json'):
        raise ValueError('Untrusted update origin.')
    raw = _get(info['manifest_url'], 30)
    signed = update_signing.verify(raw)
    want = expected_sha(_get(info['sha_url'], 30).decode('ascii', 'replace'))
    if (signed['version'] != info['latest'] or signed['name'] != info['name']
            or signed['size'] != info.get('size') or signed['sha256'] != want):
        raise ValueError('Release metadata does not match its update signature.')
    if info.get('digest', '').startswith('sha256:') and info['digest'][7:].lower() != want:
        raise ValueError('The release checksum and the GitHub asset digest disagree.')
    total, chunks = _get_chunks(info['url'])
    total = total or info.get('size', 0)
    UPDATES.mkdir(parents=True, exist_ok=True)
    path = UPDATES / info['name']
    tmp = None
    try:
        if total < 0 or total > MAX_INSTALLER_SIZE:
            raise ValueError('Installer is too large.')
        digest, done = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=UPDATES, prefix='.download-', suffix='.tmp', delete=False) as f:
            tmp = Path(f.name)
            for block in chunks:
                done += len(block)
                if done > MAX_INSTALLER_SIZE:
                    raise ValueError('Installer is too large.')
                f.write(block)
                digest.update(block)
                if progress:
                    progress(done, total)
        got = digest.hexdigest()
        if info.get('size') and done != info['size']:
            raise ValueError('Installer size does not match the release.')
        if got != want:
            raise ValueError(f'Checksum mismatch: expected {want[:12]}..., got {got[:12]}... The file was not kept.')
        tmp.replace(path)
        manifest_tmp = path.with_name(path.name + '.update.tmp')
        try:
            manifest_tmp.write_bytes(raw)
            manifest_tmp.replace(path.with_name(path.name + '.update.json'))
        finally:
            manifest_tmp.unlink(missing_ok=True)
    finally:
        if hasattr(chunks, 'close'):
            chunks.close()
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    with _dl_lock:
        _dl['sha256'] = want
    return path


_dl = {'state': 'idle', 'done': 0, 'total': 0, 'name': '', 'version': '', 'sha256': '', 'error': ''}
_dl_lock = threading.Lock()
_dl_cancel = threading.Event()
_dl_thread = None


def status() -> dict:
    """The background download: state idle | downloading | ready | error, bytes done / total."""
    with _dl_lock:
        return dict(_dl)


def start_download(info: dict) -> dict:
    """Start download(info) on a daemon thread (once at a time); returns status()."""
    global _dl_thread
    with _dl_lock:
        if _dl['state'] == 'downloading':
            return dict(_dl)
        _dl.update(state='downloading', done=0, total=info.get('size', 0), name=info.get('name', ''),
                   version=info.get('latest', ''), sha256='', error='')
        _dl_cancel.clear()

    def progress(done, total):
        if _dl_cancel.is_set():
            raise ValueError('Update download cancelled. Download it again when ready.')
        with _dl_lock:
            _dl.update(done=done, total=total)

    def run():
        try:
            path = download(info, progress)
            if _dl_cancel.is_set():
                raise ValueError('Update download cancelled. Download it again when ready.')
            if not _trusted_publisher(path, info['latest']):
                raise ValueError('The installer release signature or signed version does not match this update.')
            if _dl_cancel.is_set():
                raise ValueError('Update download cancelled. Download it again when ready.')
            saved = {**info, 'sha256': status()['sha256']}
            tmp = UPDATES / 'release.tmp'
            tmp.write_text(json.dumps(saved), encoding='utf-8')
            tmp.replace(UPDATES / 'release.json')
            with _dl_lock:
                _dl.update(state='ready', name=path.name)
        except Exception as e:
            with _dl_lock:
                _dl.update(state='error', error=str(e) if isinstance(e, ValueError) else f'Download failed: {e}')
        finally:
            (UPDATES / 'release.tmp').unlink(missing_ok=True)
    _dl_thread = threading.Thread(target=run, name='update-download', daemon=True)
    _dl_thread.start()
    return status()


def stop_download():
    _dl_cancel.set()
    if _dl_thread:
        _dl_thread.join(10)


def recover() -> dict:
    """A saved ready flag is never trusted, including when offline."""
    path = UPDATES / 'release.json'
    if not path.exists():
        return {}
    try:
        with path.open(encoding='utf-8') as f:
            info = json.loads(f.read(MAX_METADATA_SIZE + 1))
        name, version = info['name'], info['latest']
        if not ASSET_RE.fullmatch(name) or name != f'Brainamon-Setup-{version}.exe':
            raise ValueError('Invalid saved update.')
        # Completed upgrades leave their cached installer behind; it is no longer a pending update.
        if parse_version(version) <= parse_version(__version__):
            return {}
        installer = UPDATES / name
        base = f'https://github.com/{RELEASES_REPO}/releases/download/v{version}/{name}'
        if info.get('url') != base or info.get('sha_url') != base + '.sha256':
            raise ValueError('Invalid saved release origin.')
        if not 0 < installer.stat().st_size <= MAX_INSTALLER_SIZE:
            raise ValueError('Invalid saved installer size.')
        want = expected_sha(info['sha256'])
        if info.get('digest') and info['digest'] != 'sha256:' + want:
            raise ValueError('Invalid saved release digest.')
        if info.get('size') != installer.stat().st_size:
            raise ValueError('Invalid saved release size.')
        digest = hashlib.sha256()
        with installer.open('rb') as f:
            for block in iter(lambda: f.read(256 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != want or not _trusted_publisher(installer, version):
            raise ValueError('Saved update failed checksum or signature verification. Download it again.')
        with _dl_lock:
            _dl.update(state='ready', name=name, version=version, sha256=want, error='')
        return info
    except (OSError, ValueError, TypeError, KeyError):
        with _dl_lock:
            _dl.update(state='error', error='Saved update could not be verified. Check for updates and download it again.')
        return {}


def _trusted_publisher(path: Path, version: str) -> bool:
    """Require the pinned update signature binding this exact installer and version."""
    if sys.platform != 'win32' or not app_paths.FROZEN or app_paths.CONTRIBUTOR:
        return False
    try:
        release = update_signing.verify_file(path)
        return (release['version'] == version
                and parse_version(version) > parse_version(__version__))
    except (OSError, ValueError):
        return False


def _install_command(path: Path, checksum: str) -> list[str]:
    """A Windows-owned helper survives our exit without holding the installed bundle open."""
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    script = f"""
$ErrorActionPreference = 'Stop'
$appExe = {literal(Path(sys.executable).resolve())}
$installer = {literal(path.resolve())}
$log = {literal(path.with_suffix('.log').resolve())}
$handoffLog = {literal(path.with_suffix('.handoff.log').resolve())}
try {{
    'Waiting for Brainamon to exit.' | Set-Content -LiteralPath $handoffLog
    $deadline = [DateTime]::UtcNow.AddSeconds({INSTALL_EXIT_TIMEOUT})
    while (@(Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($appExe)) -ErrorAction SilentlyContinue |
             Where-Object {{ $_.Path -eq $appExe }}).Count -gt 0) {{
        if ([DateTime]::UtcNow -ge $deadline) {{
            throw 'Brainamon did not exit in time. Quit Brainamon and try the update again.'
        }}
        Start-Sleep -Milliseconds 250
    }}
    $stream = [IO.File]::OpenRead($installer)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{
        $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
    }} finally {{
        $stream.Dispose()
        $sha.Dispose()
    }}
    if ($digest -ne {literal(checksum)}) {{
        throw 'The downloaded installer changed. Download it again.'
    }}
    Start-Process -FilePath $installer -WorkingDirectory ([IO.Path]::GetDirectoryName($installer)) `
        -ArgumentList @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + $log + '"'))
    'Installer started.' | Add-Content -LiteralPath $handoffLog
}} catch {{
    $_.Exception.Message | Add-Content -LiteralPath $handoffLog
    exit 1
}}
"""
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return [str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
            '-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode('ascii')]


def launch(path: Path) -> None:
    """Verify and queue setup; the caller requests normal exit before the helper installs."""
    if app_paths.CONTRIBUTOR:
        raise ValueError('Official updates are disabled in this build.')
    path = Path(path)
    match = ASSET_RE.fullmatch(path.name)
    if path.parent.resolve() != UPDATES.resolve() or not match or not path.is_file():
        raise ValueError('Only a downloaded, verified installer can be run.')
    if parse_version(match.group(1)) <= parse_version(__version__):
        raise ValueError('Update rollback or same-version installer refused.')
    with _dl_lock:
        ready = dict(_dl)
    if (ready['state'] != 'ready' or ready['name'] != path.name or ready['version'] != match.group(1)
            or not ready['sha256']):
        raise ValueError('Download this update again before installing it.')
    digest = hashlib.sha256()
    with path.open('rb') as installer:
        for block in iter(lambda: installer.read(256 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != ready['sha256']:
        raise ValueError('The downloaded installer changed. Download it again.')
    if not _trusted_publisher(path, match.group(1)):
        raise ValueError('The installer release signature or signed version does not match this update.')
    # Window/keeper processes outlive the backend; Restart Manager can abort during that gap.
    subprocess.Popen(_install_command(path, ready['sha256']), cwd=str(UPDATES), close_fds=True,
                     creationflags=app_paths.NO_WINDOW)


def backup_on_upgrade(data_dir: Path, db_name: str = 'content_manager.db') -> Path | None:
    """First start of a newer version: copy the DB (SQLite backup API, consistent with the WAL) to
    data/backups/content_manager-<old>-to-<new>-<date>.db (never pruned: user DB backups are only
    deleted by Fred), then record the version. Returns the copy, or None when nothing changed or there is no DB yet."""
    data_dir = Path(data_dir)
    marker = data_dir / 'app_version.txt'
    old = marker.read_text(encoding='utf-8').strip() if marker.exists() else ''
    db = data_dir / db_name
    if old and parse_version(__version__) <= parse_version(old):
        return None     # same or older (a source run and the installed app share data/): no copy, marker kept
    copy = None
    if db.exists():
        backups = data_dir / 'backups'
        backups.mkdir(exist_ok=True)
        copy = backups / f'content_manager-{old or "unknown"}-to-{__version__}-{datetime.now():%Y%m%d-%H%M%S}.db'
        src = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
        dst = sqlite3.connect(copy)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    marker.write_text(__version__, encoding='utf-8')
    return copy
