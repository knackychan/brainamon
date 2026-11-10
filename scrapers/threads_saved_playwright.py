"""Read Threads Saved with the same card adapter used by the phone site reader."""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from fb_saved_playwright import configure_stdio, import_cookies, save_scoped_state, session_ready

ROOT = Path(__file__).resolve().parents[1]
SAVED_URL = 'https://www.threads.com/saved'
SITE_JS = (ROOT / 'scrapers' / 'sites' / 'threads.js').read_text(encoding='utf-8')
FIELDS = ['url', 'description', 'creator', 'type', 'thumb']


def parse_args():
    parser = argparse.ArgumentParser(description='Read Threads Saved posts.')
    parser.add_argument('--profile-dir', type=Path, default=ROOT / 'local/cache/playwright/threads-profile')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/scrapes')
    parser.add_argument('--cookies', type=Path)
    parser.add_argument('--stop-at', default='')
    parser.add_argument('--max-empty-scrolls', type=int, default=10)
    parser.add_argument('--scroll-pause-ms', type=int, default=1500)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--login-wait-seconds', type=int, default=0)
    parser.add_argument('--no-thumbs', action='store_true')
    parser.add_argument('--isolated', action='store_true')
    parser.add_argument('--session-state', type=Path)
    parser.add_argument('--remember', action='store_true')
    return parser.parse_args()


def wait_for_saved_page(page, login_wait_seconds):
    deadline = time.monotonic() + login_wait_seconds if login_wait_seconds > 0 else None
    page.goto(SAVED_URL, wait_until='domcontentloaded')
    opened_saved = False
    print('[status] login', flush=True)
    while True:
        if session_ready(page, 'threads'):
            if urlsplit(page.url).path.rstrip('/') == '/saved':
                print('[status] collecting', flush=True)
                page.wait_for_timeout(4000)
                return
            if not opened_saved:
                opened_saved = True
                print('[status] saved', flush=True)
                page.goto(SAVED_URL, wait_until='domcontentloaded')
        else:
            opened_saved = False
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError('Threads login or Saved page did not complete before timeout.')
        page.wait_for_timeout(2000)


EXTRACT_JS = '''async ({seen, thumbs}) => {
''' + SITE_JS + r'''
  const known = new Set(seen), out = [];
  for (const card of SITE.read(document)) {
    const key = SITE.key(card.url);
    if (!key || known.has(key)) continue;
    known.add(key);
    let thumb = '';
    if (thumbs && card.pic && card.pic.length <= 2000) {
      try {
        const u = new URL(card.pic);
        if (u.protocol !== 'https:' || u.username || u.password || u.port ||
            !/(^|\.)(cdninstagram\.com|fbcdn\.net)$/i.test(u.hostname)) throw new Error('Invalid picture');
        const response = await fetch(u.href, {redirect: 'error'});
        if (response.ok) {
          const blob = await response.blob();
          thumb = await new Promise(resolve => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
            reader.onerror = () => resolve('');
            reader.readAsDataURL(blob);
          });
        }
      } catch (e) { /* Text and link remain usable if a picture cannot be fetched. */ }
    }
    out.push({key, url: card.url, description: card.caption, creator: card.creator, type: card.kind, thumb});
  }
  return out;
}'''


def scrape_saved(page, stop_at, thumbs, max_empty_scrolls, scroll_pause_ms):
    rows, seen, empty = [], set(), 0
    stop_lower = stop_at.strip().lower()
    page.evaluate('window.scrollTo(0, 0)')
    while empty < max_empty_scrolls:
        if not session_ready(page, 'threads') or urlsplit(page.url).path.rstrip('/') != '/saved':
            raise RuntimeError('Threads Saved became unavailable during the scan.')
        batch = page.evaluate(EXTRACT_JS, {'seen': list(seen), 'thumbs': thumbs})
        if batch:
            empty = 0
            for row in batch:
                key = row.pop('key')
                if key in seen:
                    continue
                seen.add(key)
                if stop_lower and stop_lower in row['description'].lower():
                    return rows
                rows.append(row)
        else:
            empty += 1
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(scroll_pause_ms)
    if not seen:
        raise RuntimeError('No Threads posts could be read; Saved may be empty or unavailable.')
    return rows


def write_csv(rows, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"threads_saved_{time.strftime('%Y-%m-%d')}.csv"
    temp = path.with_suffix('.tmp')
    try:
        with temp.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def main():
    configure_stdio()
    args = parse_args()
    if not args.isolated:
        args.profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        if args.isolated:
            browser = p.chromium.launch(headless=args.headless)
            state = str(args.session_state) if args.session_state and args.session_state.stat().st_size else None
            context = browser.new_context(storage_state=state, viewport={'width': 1280, 'height': 1100})
        else:
            context = p.chromium.launch_persistent_context(user_data_dir=str(args.profile_dir), headless=args.headless,
                                                           viewport={'width': 1280, 'height': 1100})
        try:
            if args.cookies:
                try:
                    import_cookies(context, args.cookies)
                except Exception as exc:
                    print(f'[warn] Could not import cookies: {exc}')
            page = context.pages[0] if context.pages else context.new_page()
            wait_for_saved_page(page, args.login_wait_seconds or (300 if args.headless else 0))
            rows = scrape_saved(page, args.stop_at, not args.no_thumbs, args.max_empty_scrolls, args.scroll_pause_ms)
            path = write_csv(rows, args.output_dir)
            print(f'[done] Scraped {len(rows)} posts', flush=True)
            print(f'[done] CSV written to {path}', flush=True)
            return 0
        finally:
            try:
                if args.isolated and args.remember and args.session_state:
                    save_scoped_state(context, args.session_state, 'threads')
            finally:
                context.close()
                if browser:
                    browser.close()


if __name__ == '__main__':
    sys.exit(main())
