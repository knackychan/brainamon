"""
Browser-driven Instagram Saved scraper using Playwright.

The automated alternative to pasting `instagram_scraper.js` into DevTools: it opens a persistent
Chromium profile, waits for you to log in the first time, opens <username>/saved/all-posts/, scrolls the grid, captures each
post link, its picture's alt text and the thumbnail (base64), and writes instagram_saved_<date>.csv
in the shape Brainamon's importer reads. Captions come later from Fetch link info (yt-dlp).

With --unsave, each scraped post is unsaved AFTER the CSV is written: the scraper opens the post
and clicks its bookmark ("Remove"), slowly, and stops after a few failures in a row (Instagram
answers fast unsaving with "Try again later").

    pip install playwright
    python -m playwright install chromium
    python scrapers/ig_saved_playwright.py [--unsave]
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from fb_saved_playwright import configure_stdio, import_cookies, save_scoped_state, session_ready

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = ROOT / "local" / "cache" / "playwright" / "instagram-profile"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "scrapes"
HOME_URL = "https://www.instagram.com/"
FIELDS = ["url", "description", "creator", "type", "thumb"]
MAX_UNSAVE_FAILS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Instagram Saved posts with Playwright and export instagram_saved_*.csv.")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cookies", type=Path, default=None, help="Optional Netscape cookies.txt to import first.")
    parser.add_argument("--username", default="", help="Your Instagram username (found from the page when empty).")
    parser.add_argument("--stop-at", default="", help="Stop when a post's text contains this substring.")
    parser.add_argument("--max-empty-scrolls", type=int, default=8)
    parser.add_argument("--scroll-pause-ms", type=int, default=1500)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--login-wait-seconds", type=int, default=0,
                        help="Login wait in seconds; 0 waits until you finish or stop (headless: 300 seconds).")
    parser.add_argument("--unsave", action="store_true", help="Unsave each scraped post after the CSV is written.")
    parser.add_argument("--unsave-delay-ms", type=int, default=4000)
    parser.add_argument("--no-thumbs", action="store_true")
    parser.add_argument('--isolated', action='store_true')
    parser.add_argument('--session-state', type=Path)
    parser.add_argument('--remember', action='store_true')
    return parser.parse_args()


def saved_url_for(username: str) -> str:
    return f"https://www.instagram.com/{username}/saved/all-posts/"


# The logged-in username from the side menu's link to your profile (/<username>/): its label ("Profile",
# "Profil", "Perfil") or, inside the navigation, the link whose picture's alt names that user. '' when not found.
FIND_USER_JS = r"""
() => {
  const notUsers = new Set(['explore', 'reels', 'direct', 'accounts', 'p', 'reel', 'stories', 'about', 'legal', 'saved']);
  const labels = new Set(['profile', 'profil', 'perfil', 'profilo']);
  const links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const m = (a.getAttribute('href') || '').match(/^\/([A-Za-z0-9._]+)\/$/);
    if (m && !notUsers.has(m[1])) links.push([a, m[1]]);
  }
  const saved = document.querySelector('a[href*="/saved/"]');
  const savedUser = saved && new URL(saved.href).pathname.match(/^\/([A-Za-z0-9._]+)\/saved\//);
  if (savedUser) return savedUser[1];
  for (const [a, user] of links) {
    if (labels.has((a.innerText || '').trim().toLowerCase())) return user;
  }
  for (const [a, user] of links) {
    const img = a.querySelector('img[alt]');
    if (a.closest('nav, [role="navigation"]') && img && img.alt.includes(user)) return user;
  }
  return '';
}
"""


def wait_for_saved_page(page, username: str, login_wait_seconds: int) -> None:
    """Keep observing delayed login/profile rendering; never reload a challenge."""
    username = username.strip().lstrip('@')
    if username and not re.fullmatch(r'[A-Za-z0-9._]+', username):
        raise ValueError('Enter an Instagram username, not a profile URL.')
    deadline = time.monotonic() + login_wait_seconds if login_wait_seconds > 0 else None
    page.goto(HOME_URL, wait_until="domcontentloaded")
    opened_saved = False
    explained_saved = False
    print('[status] login', flush=True)
    while True:
        if session_ready(page, 'instagram'):
            if re.fullmatch(r'/[^/]+/saved(?:/.*)?', urlsplit(page.url).path):
                print('[status] collecting', flush=True)
                page.wait_for_timeout(3000)
                return
            if not explained_saved:
                print('[status] instagram-saved', flush=True)
                explained_saved = True
            if not opened_saved:
                try:
                    user = username or page.evaluate(FIND_USER_JS)
                except PlaywrightError as exc:
                    if 'Execution context was destroyed' not in str(exc):
                        raise
                    user = ''  # Login redirects can replace the document between polls.
                if user:
                    opened_saved = True
                    page.goto(saved_url_for(user), wait_until="domcontentloaded")
        else:
            opened_saved = False
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError('Instagram login or Saved page did not complete before timeout.')
        page.wait_for_timeout(2000)


EXTRACT_VISIBLE_JS = r"""
async (args) => {
  const seen = new Set(args.seen || []);
  const out = [];
  async function b64(src) {
    if (!args.thumbs || !src) return '';
    try {
      const blob = await (await fetch(src)).blob();
      return await new Promise(resolve => {
        const r = new FileReader();
        r.onload = () => resolve((r.result || '').split(',')[1] || '');
        r.onerror = () => resolve('');
        r.readAsDataURL(blob);
      });
    } catch (e) { return ''; }
  }
  for (const a of document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]')) {
    let path;
    try { path = new URL(a.href).pathname; } catch (e) { continue; }
    const m = path.match(/\/(p|reel)\/([^/]+)/);
    if (!m) continue;
    const url = `https://www.instagram.com/${m[1]}/${m[2]}/`;
    if (seen.has(url)) continue;
    seen.add(url);
    const img = a.querySelector('img');
    out.push({
      url,
      description: img ? (img.alt || '') : '',
      creator: '',
      type: m[1] === 'reel' ? 'Reel' : 'Post',
      thumb: await b64(img ? img.src : ''),
    });
  }
  return out;
}
"""

# On a post page: click the bookmark when it shows "Remove" (saved), then wait for "Save"
UNSAVE_JS = r"""
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const scope = document.querySelector('main') || document;
  const icon = (label) => Array.from(scope.querySelectorAll('svg[aria-label]')).find(s => s.getAttribute('aria-label') === label);
  for (let i = 0; i < 20 && !icon('Remove') && !icon('Save'); i++) await sleep(500);
  const saved = icon('Remove');
  if (!saved) return icon('Save') ? 'already' : 'nobutton';
  (saved.closest('[role="button"], button') || saved).click();
  for (let i = 0; i < 20; i++) {
    await sleep(300);
    if (!icon('Remove') && icon('Save')) return 'ok';
  }
  return 'nochange';
}
"""


def scrape_grid(page, stop_at: str, thumbs: bool, max_empty_scrolls: int, scroll_pause_ms: int) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    empty = 0
    stop_lower = stop_at.lower().strip()
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(1000)
    while empty < max_empty_scrolls:
        batch = page.evaluate(EXTRACT_VISIBLE_JS, {"seen": list(seen), "thumbs": thumbs})
        if not batch:
            empty += 1
            print(f"[scroll] no new posts ({empty}/{max_empty_scrolls})")
        else:
            empty = 0
            for item in batch:
                seen.add(item["url"])
                if stop_lower and stop_lower in (item.get("description") or "").lower():
                    print(f'[stop] matched stop text "{stop_at}" on {item["url"]}')
                    return rows
                rows.append(item)
                print(f"[item {len(rows):04d}] {item['url']} {(item.get('description') or '')[:60]}")
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(scroll_pause_ms)
    return rows


def write_csv(rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"instagram_saved_{time.strftime('%Y-%m-%d')}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") or "" for field in FIELDS})
    return out_path


def unsave_all(page, rows: list[dict], delay_ms: int) -> int:
    done, fails = 0, 0
    for i, row in enumerate(rows, 1):
        page.goto(row["url"], wait_until="domcontentloaded")
        state = page.evaluate(UNSAVE_JS)
        if state in ("ok", "already"):
            done, fails = done + (state == "ok"), 0
            print(f"[unsave {i:04d}/{len(rows)}] {state} {row['url']}")
        else:
            fails += 1
            hint = " (no bookmark labelled 'Remove': is Instagram in English?)" if state == "nobutton" else ""
            print(f"[warn] Could not unsave {row['url']}: {state}{hint}")
            if fails >= MAX_UNSAVE_FAILS:
                print("[warn] Several failures in a row (Instagram may be limiting actions): stopping the unsave pass.")
                break
        page.wait_for_timeout(delay_ms + random.randint(0, 3000))
    return done


def main() -> int:
    configure_stdio()
    args = parse_args()
    if not args.isolated:
        args.profile_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = None
        if args.isolated:
            browser = p.chromium.launch(headless=args.headless)
            state = str(args.session_state) if args.session_state and args.session_state.stat().st_size else None
            context = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 1100})
        else:
            context = p.chromium.launch_persistent_context(user_data_dir=str(args.profile_dir), headless=args.headless, viewport={"width": 1280, "height": 1100})
        try:
            if args.cookies:
                try:
                    import_cookies(context, args.cookies)
                except Exception as exc:
                    print(f"[warn] Could not import cookies from {args.cookies}: {exc}")
            page = context.pages[0] if context.pages else context.new_page()
            wait_for_saved_page(page, args.username, args.login_wait_seconds or (300 if args.headless else 0))

            rows = scrape_grid(page, args.stop_at, not args.no_thumbs, args.max_empty_scrolls, args.scroll_pause_ms)
            out_path = write_csv(rows, args.output_dir)
            print(f"[done] Scraped {len(rows)} posts")
            print(f"[done] CSV written to {out_path}")

            if args.unsave and rows:
                n = unsave_all(page, rows, args.unsave_delay_ms)
                print(f"[done] Unsaved {n} of {len(rows)} posts")
            return 0
        finally:
            try:
                if args.isolated and args.remember and args.session_state:
                    save_scoped_state(context, args.session_state, 'instagram')
            finally:
                context.close()
                if browser:
                    browser.close()


if __name__ == "__main__":
    sys.exit(main())
