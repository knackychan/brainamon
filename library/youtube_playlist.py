"""Read one YouTube playlist without downloading media or opening a browser."""
import json
import re
import subprocess
from collections import deque
from contextlib import ExitStack
from urllib.parse import parse_qs, urlsplit

from core import app_paths, site_sessions
from library import ytdlp

MAX_ENTRIES = 10000


def playlist_url(value):
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError
        u = urlsplit(value.strip())
        ids = parse_qs(u.query).get('list', [])
        if (u.scheme not in ('http', 'https') or u.hostname not in
                ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com')
                or u.username or u.password or u.port not in (None, 80, 443)
                or u.path not in ('/playlist', '/watch') or len(ids) != 1
                or not re.fullmatch(r'[A-Za-z0-9_-]{2,128}', ids[0])):
            raise ValueError
        return 'https://www.youtube.com/playlist?list=' + ids[0]
    except ValueError:
        raise ValueError('Paste a YouTube playlist link containing list=, not the playlists overview.') from None


def read(url, executable, lookups=(), should_stop=lambda: False, progress=lambda count: None):
    url = playlist_url(url)
    rows, seen, tail = [], set(), deque(maxlen=40)
    with ExitStack() as stack:
        cookies = stack.enter_context(site_sessions.cookies(url, lookups))
        stopped = lambda: should_stop() or site_sessions.revoked(cookies)
        if stopped():
            raise RuntimeError('Playlist import stopped. Nothing was imported.')
        args = [executable, '--ignore-config', *ytdlp.runtime_args(), '--flat-playlist',
                '--dump-json', '--skip-download', '--yes-playlist', '--no-mark-watched', '--abort-on-error',
                '--no-warnings', '--socket-timeout', '20', '--retries', '2',
                '--extractor-retries', '2', '--playlist-end', str(MAX_ENTRIES + 1)]
        if cookies:
            args += ['--cookies', str(cookies)]
        args += ['--', url]
        args = stack.enter_context(ytdlp.downloader(args, url))
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    creationflags=app_paths.NO_WINDOW)
        except OSError:
            raise RuntimeError('Could not start yt-dlp. Check Settings > Tools.') from None
        entries = total_bytes = 0
        with ytdlp.monitor(proc, stopped, timeout=600):
            while raw := proc.stdout.readline(1024 * 1024 + 1):
                total_bytes += len(raw)
                if len(raw) > 1024 * 1024 or total_bytes > 64 * 1024 * 1024:
                    raise RuntimeError('YouTube returned too much playlist data. Nothing was imported.')
                line = raw.decode('utf-8', errors='replace').strip()
                if not line.startswith('{'):
                    tail.append(line[:4096])
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    raise RuntimeError('YouTube returned unreadable playlist data. Nothing was imported.') from None
                if not isinstance(entry, dict):
                    raise RuntimeError('YouTube returned invalid playlist data. Nothing was imported.')
                entries += 1
                if entries > MAX_ENTRIES:
                    raise RuntimeError(f'Import one playlist with at most {MAX_ENTRIES:,} entries. Nothing was imported.')
                vid = entry.get('id')
                if not isinstance(vid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid) or vid in seen:
                    continue
                seen.add(vid)
                rows.append({'url': f'https://www.youtube.com/watch?v={vid}',
                             'description': str(entry.get('title') or ''),
                             'creator': str(entry.get('channel') or entry.get('uploader') or ''),
                             'type': 'Video', 'source': 'youtube_playlist'})
                progress(len(rows))
            rc = proc.wait()
        if stopped():
            raise RuntimeError('Playlist import stopped or saved login was disconnected. Nothing was imported.')
        if rc != 0:
            raise ytdlp.DownloadError(ytdlp.failure(list(tail)))
    if not rows:
        raise RuntimeError('No videos were returned. Check the playlist and its access, or try the Manual browser script.')
    return rows
