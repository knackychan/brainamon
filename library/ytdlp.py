"""yt-dlp discovery, legacy-path compatibility and safe shared download recovery.

Active jobs use core.site_sessions.cookies for the full child-process lifetime.
Child output is classified locally; only numeric progress and safe hints reach logs/events.
"""
import re
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from core import app_console
from core import app_paths
from core.urls import http_url
from library.public_http import downloader

NOT_FOUND = ('Downloading videos and thumbnails needs yt-dlp, which was not found on this PC. Open '
             'Settings > Tools to install it or to pick the folder that holds it, then try again.')
_TAIL = 40  # how many trailing output lines to scan for error classification
FORBIDDEN = 'The site refused this request (403). Login, site restrictions, rate limits or tool support may be involved. Open the source and check tools; cookies are not a guaranteed fix.'


def find_ytdlp():
    """Return the yt-dlp executable path on PATH, or None."""
    if app_paths.tool_folders().get('yt-dlp'):
        return app_paths.find_tool('yt-dlp')
    return app_paths.find_tool('yt-dlp') or shutil.which('yt-dlp.exe') or shutil.which('yt_dlp')


def runtime_args():
    folder = app_paths.tool_folders().get('deno')
    if not folder:
        return []
    path = app_paths.find_tool('deno')
    return ['--js-runtimes', f'deno:{path}'] if path else []


def available() -> bool:
    """True if the yt-dlp executable is on PATH."""
    return find_ytdlp() is not None


def registry_get(name: str) -> str:
    """A value the Qt app saved with QSettings('ContentManager', 'Main'), read-only from the
    Windows registry (HKEY_CURRENT_USER\\Software\\ContentManager\\Main). '' elsewhere."""
    if sys.platform != 'win32':
        return ''
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\ContentManager\Main') as k:
            v, _ = winreg.QueryValueEx(k, name)
        return v if isinstance(v, str) else ''
    except OSError:
        return ''


def resolve_cookies(url: str = '', lookups=None):
    """Legacy-path compatibility only. Protected consumers must use site_sessions.cookies."""
    from core import site_sessions
    lookups = lookups if lookups is not None else []
    slot = 'instagram' if site_sessions.site_for(url) == 'instagram' else 'general'
    if slot == 'instagram' and site_sessions.mode(slot, lookups) == 'none':
        slot = 'general'
    return site_sessions.legacy_path(slot, lookups)


def validate_cookie_file(path: str) -> str:
    """'' if the file looks like a usable cookies.txt, else a short reason ('missing',
    'invalid format', 'unreadable'): the first non-blank line must be the Netscape cookie header
    or a tab-separated cookie row (the format yt-dlp expects)."""
    from core import site_sessions
    try:
        with Path(path).open('rb') as f:
            site_sessions.parse_cookies(f.read(site_sessions.MAX_BYTES + 1))
        return ''
    except FileNotFoundError:
        return 'missing'
    except ValueError:
        return 'invalid format'
    except OSError:
        return 'unreadable'


def failure(lines):
    """Shared, safe recovery hints. Never echo server output or assume every 403 is login."""
    blob = '\n'.join(lines).lower()
    code, action, text = 'unknown', 'retry', 'The request failed. Retry or open the source; cookies may not resolve this failure.'
    if blob.startswith('the site refused this request (403)'):
        return {'code': 'forbidden', 'action': 'source', 'error': FORBIDDEN}
    if any(s in blob for s in ('not found on this pc', 'ffmpeg not found', 'command not found', 'no such file')):
        code, action, text = 'missing_tool', 'tools', NOT_FOUND
    elif any(s in blob for s in ('429', 'too many requests', 'rate limit')):
        code, action, text = 'rate_limit', 'wait', 'The site is rate limiting requests. Wait before retrying.'
    elif any(s in blob for s in ('po token', 'po-token', 'po_token', 'javascript runtime', 'js runtime', 'js challenge', 'challenge solver', 'ejs', 'n challenge', 'nsig', 'signature solving')):
        code, action, text = 'youtube_setup', 'youtube', 'YouTube needs additional runtime, challenge or PO-token setup. Check Settings > Tools and the upstream YouTube guide; cookies alone may not fix it.'
    elif any(s in blob for s in ('sign in', 'sign-in', 'login required', 'log in', 'authentication required', 'http error 401', 'unauthorized', 'cookies have expired', 'private video', 'only available for registered', 'cannot unlock')):
        code, action, text = 'authentication', 'sessions', 'Sign-in may need refreshing, or this account may lack access. Replace saved login in Settings > Downloads, then test this link.'
    elif any(s in blob for s in ('unsupported url', 'unsupported, deleted', 'video unavailable', 'has been removed', 'has been deleted', 'not available', '404')):
        code, action, text = 'unavailable', 'source', 'This item may be unsupported, deleted or unavailable. Open the source to check it.'
    elif any(s in blob for s in ('timed out', 'timeout', 'connection', 'name resolution', 'network', 'certificate', 'unable to download')):
        code, action, text = 'network', 'retry', 'The network request failed. Check your connection and retry the selected link.'
    elif '403' in blob or 'forbidden' in blob:
        code, action, text = 'forbidden', 'source', FORBIDDEN
    return {'code': code, 'action': action, 'error': text}


class DownloadError(RuntimeError):
    def __init__(self, info):
        super().__init__(info['error'])
        self.code, self.action = info['code'], info['action']


def classify_error(lines: list) -> str:
    return failure(lines)['error']


def safe_url(url):
    try:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', ''))
    except ValueError:
        return '(selected link)'


def safe_output(line):
    # Child output may echo arbitrary cookie values. Only progress numbers cross the log/UI boundary.
    progress = re.search(r'^\[download\]\s+([0-9.]+%)', line)
    if progress:
        return '[download] ' + progress[1]
    if line.startswith('ERROR:'):
        return classify_error([line])
    return ''


@contextmanager
def monitor(proc, should_stop=None, timeout=1800):
    from library.scraper_runtime import kill_tree
    done = threading.Event()
    def watch():
        deadline = time.monotonic() + timeout
        while not done.wait(.15):
            if proc.poll() is not None:
                return
            if should_stop and should_stop() or time.monotonic() >= deadline:
                kill_tree(proc)
                return
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(16)
        kill_tree(proc)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


def largest_image(folder: Path):
    p = Path(folder)
    candidates = list(p.glob('**/*.jpg')) + list(p.glob('**/*.jpeg')) + list(p.glob('**/*.png'))
    # Prefer the highest-resolution thumbnail (largest file on disk)
    return max(candidates, key=lambda f: f.stat().st_size) if candidates else None


def fetch_thumbnail(item: dict, data_dir, cookies_path=None, on_proc=None, should_stop=None) -> dict:
    """One item of the batch thumbnail + caption pass: `yt-dlp --skip-download --write-thumbnail`
    into a throwaway folder, the largest image copied to data/items/<id>/thumb.jpg, the post
    caption captured from the same metadata pass. Returns {'filename', 'source', 'caption',
    'error'}; filename is '' when no thumbnail was produced (error says why). `on_proc` receives
    the running Popen (or None) so a caller can terminate it."""
    ytdlp_cmd = find_ytdlp()
    item_id = item.get('id')
    out = {'filename': '', 'source': '', 'caption': '', 'error': ''}
    url = (item.get('url') or '').strip()
    if not http_url(url):
        out['error'] = 'A valid HTTP(S) URL is required.'
        return out
    if not ytdlp_cmd:
        out['error'] = NOT_FOUND
        return out

    # Thumbnail-only run writes to a throwaway temp dir (no video, no reels clutter).
    out_dir = Path(tempfile.mkdtemp(prefix=f'cm_thumb_{item_id}_'))
    try:
        out_template = str(out_dir / '%(title).200s.%(ext)s')
        desc_file = out_dir / 'desc.txt'
        # Fold the post caption into the same metadata pass: --print-to-file writes the
        # description (multi-line safe) to a file; --no-simulate is required so the
        # thumbnail is still written, while --skip-download still avoids the video.
        args = [
            ytdlp_cmd, '--ignore-config', *runtime_args(), '--no-warnings', '--no-playlist', '--skip-download', '--no-simulate',
            '--write-thumbnail', '--convert-thumbnails', 'jpg',
            '--print-to-file', '%(description)s', str(desc_file),
            '-o', out_template,
        ]
        if cookies_path:
            args.extend(['--cookies', str(cookies_path)])
        args.extend(['--', url])

        proc = None
        network = None
        try:
            network = downloader(args, url)
            args = network.__enter__()
            proc = subprocess.Popen(
                args, cwd=str(Path.cwd()),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, creationflags=app_paths.NO_WINDOW,
            )
            if on_proc:
                on_proc(proc)
            from core import site_sessions
            with monitor(proc, lambda: (should_stop and should_stop()) or site_sessions.revoked(cookies_path), timeout=120):
                text, _ = proc.communicate(timeout=125)
                rc = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            out['error'] = 'yt-dlp timed out'
            return out
        except FileNotFoundError:
            out['error'] = NOT_FOUND
            return out
        except Exception as e:
            out['error'] = f'yt-dlp failed to start: {e}'
            return out
        finally:
            if network:
                network.__exit__(None, None, None)
            if on_proc:
                on_proc(None)

        # Caption from the same pass (kept regardless of thumbnail success).
        try:
            if desc_file.exists():
                desc_text = desc_file.read_text(encoding='utf-8', errors='replace').strip()
                if desc_text and desc_text != 'NA':  # yt-dlp writes "NA" for a missing field
                    out['caption'] = desc_text
        except Exception:
            pass

        # Copy the largest produced image to data/items/<id>/thumb.jpg
        thumb_file = largest_image(out_dir)
        if thumb_file:
            try:
                item_thumb_dir = Path(data_dir) / 'items' / str(item_id)
                item_thumb_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(thumb_file, item_thumb_dir / 'thumb.jpg')
                out['filename'], out['source'] = 'thumb.jpg', 'yt-dlp'
            except Exception as e:
                out['error'] = f'Could not save thumbnail: {e}'
        else:
            hint = classify_error((text or '').splitlines()) if rc != 0 else ''
            out['error'] = hint or 'No thumbnail produced'
            out.update({k: v for k, v in failure((text or '').splitlines()).items() if k != 'error'})
        return out
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def download_args(ytdlp_cmd: str, url: str, out_dir: Path, thumbnail_only: bool, cookies_path=None) -> list:
    """yt-dlp arguments for the per-item download. `--newline` emits each progress update on its
    own line so the caller can stream and parse them."""
    if not http_url(url):
        raise ValueError('A valid HTTP(S) URL is required.')
    out_template = str(Path(out_dir) / '%(title).200s.%(ext)s')
    args = [
        ytdlp_cmd, '--ignore-config', *runtime_args(), '--newline', '--no-warnings', '--no-playlist',
        '--write-thumbnail', '--convert-thumbnails', 'jpg',
        '-o', out_template,
    ]
    if thumbnail_only:
        args.append('--skip-download')
    if cookies_path:
        args.extend(['--cookies', str(cookies_path)])
    args.extend(['--', url])
    return args


def _run_streaming(args: list, url: str, out_dir, on_line, should_stop, on_proc=None):
    """Stream numeric progress; raw child output never reaches diagnostics or events."""
    tail = []
    try:
        proc = subprocess.Popen(args, cwd=str(Path.cwd()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                bufsize=1, text=True, encoding='utf-8', errors='replace', creationflags=app_paths.NO_WINDOW)
    except OSError as exc:
        return False, -1, NOT_FOUND if isinstance(exc, FileNotFoundError) else 'yt-dlp could not be launched. Check Settings > Tools.'
    if on_proc:
        on_proc(proc)
    app_console.emit('api', 'yt-dlp started', payload={'url': safe_url(url)})
    try:
        from core import site_sessions
        credential = args[args.index('--cookies') + 1] if '--cookies' in args else None
        with monitor(proc, lambda: should_stop() or site_sessions.revoked(credential)):
            for raw in proc.stdout:
                line = raw.rstrip('\n')
                tail.append(line)
                tail = tail[-_TAIL:]
                safe = safe_output(line)
                if safe:
                    on_line(safe)
            rc = proc.wait()
        hint = '' if rc == 0 else classify_error(tail)
        app_console.emit('api', 'yt-dlp completed', payload={'url': safe_url(url), 'returncode': rc, 'error_hint': hint})
        return rc == 0, rc, hint
    finally:
        if on_proc:
            on_proc(None)


def run_streaming(args, url, out_dir, on_line, should_stop, on_proc=None):
    with downloader(args, url) as confined:
        return _run_streaming(confined, url, out_dir, on_line, should_stop, on_proc)
