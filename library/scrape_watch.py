"""The one-click scrapers, Qt-free: the platforms, the script options, and a polling watcher of
the Downloads folder (shared by the Qt Scrapers window and the V6 server).

The scrapers are client-side JS (scrapers/*.js) run in the user's own logged-in browser: the
script is copied to the clipboard, the target page opens, the user pastes it in DevTools, the page
downloads a CSV, and the watcher imports it. The watcher only reports finished files; the import
itself is the caller's (`on_csv`), so SQLite writes stay where the caller allows them.
"""
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from core import app_paths

ROOT_DIR = Path(__file__).resolve().parent.parent
# Workers and JS assets ship; Playwright/Chromium are a separately installed runtime.
SCRAPERS_DIR = app_paths.BUNDLE / 'scrapers'
# key -> (label, script, persistent browser profile folder name); the key also picks the cookies URL
PLAYWRIGHT = {
    'facebook': ('Facebook', 'fb_saved_playwright.py', 'facebook-profile'),
    'instagram': ('Instagram', 'ig_saved_playwright.py', 'instagram-profile'),
    'reddit': ('Reddit', 'reddit_saved_playwright.py', 'reddit-profile'),
    'threads': ('Threads', 'threads_saved_playwright.py', 'threads-profile'),
}
PLAYWRIGHT_FB = SCRAPERS_DIR / PLAYWRIGHT['facebook'][1]
PLAYWRIGHT_PROFILE_DIR = app_paths.CACHE / 'playwright' / PLAYWRIGHT['facebook'][2]


def playwright_script(key: str) -> Path:
    return SCRAPERS_DIR / PLAYWRIGHT[key][1]


def playwright_profile(key: str) -> Path:
    return app_paths.CACHE / 'playwright' / PLAYWRIGHT[key][2]

# key -> (label, js filename, page to open, downloaded-CSV filename prefix)
PLATFORMS = {
    'facebook': (
        'Facebook (saved, manual)', 'facebook_scraper.js',
        'https://www.facebook.com/saved', 'fb_saved_',
    ),
    'instagram': (
        'Instagram (saved)', 'instagram_scraper.js',
        'https://www.instagram.com/', 'instagram_saved_',   # Saved is per user: <username>/saved/all-posts/
    ),
    'youtube': (
        'YouTube (playlist)', 'youtube_scraper.js',
        'https://www.youtube.com/feed/playlists', 'youtube_playlist_',
    ),
    'reddit': (
        'Reddit (saved)', 'reddit_scraper.js',
        'https://www.reddit.com/user/me/saved/', 'reddit_saved_',
    ),
}

CSV_PREFIXES = tuple(p[3] for p in PLATFORMS.values()) + ('threads_saved_',)


def default_downloads_dir() -> Path:
    """The browser's default Downloads folder (where the scraper CSV lands)."""
    if sys.platform == 'win32':
        return Path(os.environ.get('USERPROFILE', Path.home())) / 'Downloads'
    return Path.home() / 'Downloads'


def build_script(text: str, key: str, unsave: bool, stop_at: str) -> str:
    """Apply the window's options to a scraper script: the STOP_AT title and (Facebook) the
    UNSAVE_AFTER_SCRAPE switch."""
    if stop_at:
        safe = stop_at.replace('\\', '\\\\').replace("'", "\\'")
        text = re.sub(r"const STOP_AT\s*=\s*'[^']*';", lambda _m: f"const STOP_AT = '{safe}';", text, count=1)
    if key == 'facebook':
        text = re.sub(r"const UNSAVE_AFTER_SCRAPE\s*=\s*(?:true|false);",
                      f"const UNSAVE_AFTER_SCRAPE = {'true' if unsave else 'false'};", text, count=1)
    return text


def script_for(key: str, unsave: bool = False, stop_at: str = '') -> str:
    """The ready-to-paste script of a platform. KeyError for an unknown key; OSError if missing."""
    _label, js_name, _url, _prefix = PLATFORMS[key]
    return build_script((SCRAPERS_DIR / js_name).read_text(encoding='utf-8'), key, unsave, stop_at)


def playwright_args(watch_dir: Path, stop_at: str = '', unsave: bool = False, cookies: str = '',
                    key: str = 'facebook', username: str = '', python: str = '') -> list:
    """The command line of a Playwright scraper (PLAYWRIGHT key; it writes its CSV into watch_dir)."""
    if not python and app_paths.FROZEN:
        raise RuntimeError('Install browser tools from Help or Settings > Tools.')
    args = [python or sys.executable, str(playwright_script(key)), '--profile-dir', str(playwright_profile(key)),
            '--output-dir', str(watch_dir)]
    if stop_at:
        args += ['--stop-at', stop_at]
    if unsave:
        args.append('--unsave')
    if key == 'instagram' and username:
        args += ['--username', username]
    if cookies and Path(cookies).exists():
        args += ['--cookies', cookies]
    return args


def backup(path: Path, backup_dir: Path) -> None:
    """Keep a copy of an imported scrape CSV in data/scrapes/."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / path.name
    if path.resolve() != dest.resolve():
        shutil.copy2(str(path), str(dest))


class Watcher:
    """Polls `folder` for new scraper CSVs (names starting with CSV_PREFIXES, modified after the
    watcher started) and calls `on_csv(path)` once per file, when its size is stable across two
    polls (a browser download is complete). `on_csv` runs on the watcher thread."""

    def __init__(self, folder, on_csv, interval: float = 1.0):
        self.folder = Path(folder)
        self.on_csv = on_csv
        self.interval = interval
        self.since = time.time()
        self.seen: dict[str, tuple] = {}
        self._sizes: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='cm-scrape-watch', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def mark(self, path) -> None:
        """Remember a file imported by hand so the watcher does not import it again."""
        p = Path(path).resolve()
        try:
            st = p.stat()
            self.seen[str(p)] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.scan()

    def scan(self) -> list:
        """One poll; returns the files handed to on_csv."""
        out = []
        try:
            files = [p for p in self.folder.glob('*.csv') if p.name.startswith(CSV_PREFIXES)]
        except OSError:
            return out
        for p in files:
            rp = str(p.resolve())
            try:
                st = p.stat()
            except OSError:
                continue
            if self.seen.get(rp) == (st.st_mtime_ns, st.st_size) or st.st_mtime < self.since - 2:
                continue
            if self._sizes.get(rp) != st.st_size or st.st_size == 0:
                self._sizes[rp] = st.st_size        # still growing: look again next poll
                continue
            self._sizes.pop(rp, None)
            self.seen[rp] = (st.st_mtime_ns, st.st_size)
            out.append(p)
            try:
                self.on_csv(p)
            except Exception:
                pass
        return out
