"""
Browser-driven Facebook Saved scraper using Playwright.

This is the automated alternative to pasting `facebook_scraper.js` into DevTools.
It opens a real Chromium profile, reuses the logged-in session, scrolls through the
Saved page, extracts visible reel/video cards, captures thumbnails as base64, and
writes the same CSV shape consumed by Brainamon's existing importer.

Typical usage:

    pip install playwright
    python -m playwright install chromium
    python scrapers/fb_saved_playwright.py

First run is expected to be headful so Facebook can be logged into normally.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = ROOT / "local" / "cache" / "playwright" / "facebook-profile"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "scrapes"
DEFAULT_COOKIES = ROOT / "cookies.txt"
SAVED_URL = "https://www.facebook.com/saved"


def configure_stdio() -> None:
    """Force UTF-8 child-process output so QProcess logs don't die on Windows codepages."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass


def save_scoped_state(context, path, site):
    import json
    from urllib.parse import urlsplit
    state = context.storage_state()
    root = site + '.com'
    def included(domain):
        domain = domain.lower().lstrip('.')
        return domain == root or domain.endswith('.' + root)
    state['cookies'] = [c for c in state['cookies'] if included(c['domain'])]
    state['origins'] = [o for o in state['origins'] if included(urlsplit(o['origin']).hostname or '')]
    path.write_text(json.dumps(state), encoding='utf-8')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Facebook Saved items with Playwright and export fb_saved_*.csv."
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help=f"Persistent Chromium profile directory (default: {DEFAULT_PROFILE_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for the generated CSV (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        default=None,
        help="Optional Netscape cookies.txt to import before loading the page.",
    )
    parser.add_argument(
        "--stop-at",
        default="",
        help="Stop when a card's text contains this substring.",
    )
    parser.add_argument(
        "--max-empty-scrolls",
        type=int,
        default=10,
        help="How many scrolls without new items before stopping.",
    )
    parser.add_argument(
        "--scroll-pause-ms",
        type=int,
        default=1500,
        help="Wait after each scroll, in milliseconds.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless. Headful is recommended for Facebook session reuse.",
    )
    parser.add_argument(
        "--login-wait-seconds",
        type=int,
        default=0,
        help="Login wait in seconds; 0 waits until you finish or stop (headless: 300 seconds).",
    )
    parser.add_argument(
        "--unsave",
        action="store_true",
        help="Attempt to unsave each collected item after its CSV checkpoint is written.",
    )
    parser.add_argument(
        "--no-thumbs",
        action="store_true",
        help="Do not fetch thumbnail images as base64.",
    )
    parser.add_argument('--isolated', action='store_true')
    parser.add_argument('--session-state', type=Path)
    parser.add_argument('--remember', action='store_true')
    return parser.parse_args()


def parse_netscape_cookies(path: Path) -> list[dict]:
    cookies: list[dict] = []
    if not path.exists():
        raise FileNotFoundError(f"Cookies file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue

        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_") :]

        parts = line.split("\t")
        if len(parts) != 7:
            continue

        domain, _flag, cookie_path, secure, expires, name, value = parts
        if not domain or not name:
            continue

        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie_path or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": http_only,
        }
        try:
            expiry = int(expires)
        except ValueError:
            expiry = None
        if expiry and expiry > 0:
            cookie["expires"] = expiry
        cookies.append(cookie)

    return cookies


def import_cookies(context, cookie_path: Path) -> None:
    cookies = parse_netscape_cookies(cookie_path)
    if not cookies:
        print(f"[warn] No usable cookies parsed from {cookie_path}")
        return
    context.add_cookies(cookies)
    print(f"[info] Imported {len(cookies)} cookies from {cookie_path}")


def session_ready(page, site: str) -> bool:
    """Observe login without navigating away from passwords, 2FA or challenges."""
    url = urlsplit(page.url)
    root = site + '.com'
    if url.hostname != root and not (url.hostname or '').endswith('.' + root):
        return False
    if any(part in url.path.lower() for part in ('login', 'accounts', 'checkpoint', 'challenge',
                                                'two_factor', 'two_step', 'captcha', 'auth_platform')):
        return False
    try:
        if page.locator('input[type="password"]:visible, input[autocomplete="one-time-code"]:visible, iframe[src*="captcha"]:visible').count():
            return False
    except PlaywrightError as exc:
        if 'Execution context was destroyed' not in str(exc):
            raise
        return False
    cookie_name = 'c_user' if site == 'facebook' else 'sessionid'
    return any(c['name'] == cookie_name and c['value'] for c in page.context.cookies('https://www.' + root + '/'))


def wait_for_saved_page(page, login_wait_seconds: int) -> None:
    deadline = time.monotonic() + login_wait_seconds if login_wait_seconds > 0 else None
    page.goto(SAVED_URL, wait_until="domcontentloaded")
    opened_saved = False
    print('[status] login', flush=True)
    while True:
        if session_ready(page, 'facebook'):
            if urlsplit(page.url).path.rstrip('/') == '/saved':
                print('[status] collecting', flush=True)
                page.wait_for_timeout(2500)
                return
            if not opened_saved:
                opened_saved = True
                page.goto(SAVED_URL, wait_until="domcontentloaded")
                print('[status] saved', flush=True)
        else:
            opened_saved = False  # A new challenge must finish before we can try Saved again.
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError('Facebook login or Saved page did not complete before timeout.')
        page.wait_for_timeout(2000)


EXTRACT_VISIBLE_JS = r"""
(args) => {
  const seenIds = new Set(args.seenIds || []);
  const captureThumbs = !!args.captureThumbs;

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  function getReelId(a) {
    try {
      const m = new URL(a.href).pathname.match(/\/(reel|watch|videos)\/(\d+)/);
      return m ? m[2] : null;
    } catch (e) {
      return null;
    }
  }

  function extractDescription(a, row, creator) {
    const cl = (creator || '').toLowerCase().trim();
    const isMeta = (raw) => {
      const t = (raw || '').toLowerCase().trim();
      if (t.length <= 5) return true;
      if (t.includes('saved from')) return true;
      if (t.includes('add to collection')) return true;
      if (t.includes('see more') || t.includes('see less')) return true;
      if (t === 'view story' || t === 'more options' || (cl && t === cl + ', view story')) return true;
      if (/^(reels?|videos?)\s*[•·]/i.test(t)) return true;
      if (cl && t === cl) return true;
      if (/^\d+(\.\d+)?[kmb]?\s*(views?|likes?|comments?|shares?|plays?)/i.test(t)) return true;
      if (/^\d+\s*(s|m|h|d|w|y|hr|hrs|min|mins)\b/i.test(t)) return true;
      if (/'s (video|reel|post)$/i.test(t)) return true;
      return false;
    };

    const candidates = [];
    const push = (s) => {
      if (!s) return;
      s.split('\n').forEach(line => candidates.push((line || '').trim()));
    };

    push(row.innerText);
    if (a.getAttribute('aria-label')) candidates.push(a.getAttribute('aria-label').trim());
    row.querySelectorAll('[aria-label]').forEach(el => {
      const v = el.getAttribute('aria-label');
      if (v) candidates.push(v.trim());
    });
    row.querySelectorAll('img[alt]').forEach(el => {
      const v = el.getAttribute('alt');
      if (v) candidates.push(v.trim());
    });

    const good = candidates.filter(s => s && !isMeta(s));
    return good.length ? good[0] : '';
  }

  function getVisibleRows() {
    const rows = [];
    document.querySelectorAll('a[href]').forEach(a => {
      const id = getReelId(a);
      if (!id || seenIds.has(id)) return;
      let el = a.parentElement;
      for (let i = 0; i < 20; i++) {
        if (!el) break;
        if ((el.innerText || '').includes('Add to collection')) {
          rows.push({ id, a, row: el });
          return;
        }
        el = el.parentElement;
      }
    });
    return rows;
  }

  async function getThumb(row) {
    if (!captureThumbs) return '';
    const img = row.querySelector('img[src*="fbcdn"], img[src*="scontent"]');
    if (!img || !img.src) return '';
    try {
      const blob = await (await fetch(img.src)).blob();
      return await new Promise(resolve => {
        const r = new FileReader();
        r.onload = () => resolve((r.result || '').split(',')[1] || '');
        r.onerror = () => resolve('');
        r.readAsDataURL(blob);
      });
    } catch (e) {
      return '';
    }
  }

  async function unsave(row) {
    try {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(600);
      const btn = Array.from(row.querySelectorAll('[role="button"]'))
        .find(b => (b.getAttribute('aria-label') || '').includes('More options'));
      if (!btn) return false;
      btn.click();
      await sleep(800);
      const item = Array.from(document.querySelectorAll('[role="menuitem"]'))
        .find(m => (m.innerText || '').toLowerCase().includes('unsave'));
      if (!item) {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        return false;
      }
      item.click();
      await sleep(1000);
      return true;
    } catch (e) {
      return false;
    }
  }

  return (async () => {
    const out = [];
    for (const { id, a, row } of getVisibleRows()) {
      const fullText = row.innerText || '';
      const creatorMatch = fullText.match(/(?:Reels?|Videos?)\s*[•·]\s*([^\n]+)/i);
      const creator = creatorMatch ? creatorMatch[1].trim() : '';
      const description = extractDescription(a, row, creator);
      const type = /\/(watch|videos)\//.test(a.href) ? 'Video' : 'Reel';
      const url = 'https://www.facebook.com' + new URL(a.href).pathname;
      const thumb = await getThumb(row);
      const unsaved = false;
      out.push({ id, url, description, creator, type, thumb, fullText, unsaved });
    }
    return out;
  })();
}
"""


UNSAVE_VISIBLE_JS = r"""
(targetIds) => {
  const ids = new Set(targetIds || []);
  const visible = el => el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const moreButton = row => {
    const buttons = Array.from(row.querySelectorAll('[role="button"], button')).filter(b => {
      const label = b.getAttribute('aria-label') || '';
      return visible(b) && (label.includes('More options') ||
        (b.getAttribute('aria-haspopup') === 'dialog' && /^more(?:\s|,|$)/i.test(label)));
    });
    return buttons.length === 1 && buttons[0];
  };

  function getReelId(a) {
    try {
      const m = new URL(a.href).pathname.match(/\/(reel|watch|videos)\/(\d+)/);
      return m ? m[2] : null;
    } catch (e) {
      return null;
    }
  }

  function getVisibleRows() {
    const rows = new Map();
    document.querySelectorAll('a[href]').forEach(a => {
      const id = getReelId(a);
      if (!id || !ids.has(id) || rows.has(id) || !visible(a)) return;
      let el = a.parentElement;
      for (let i = 0; i < 20; i++) {
        if (!el) break;
        const collections = (el.innerText || '').split('Add to collection').length - 1;
        if (collections > 1) break;
        // The menu button can be a sibling of the caption and collection control.
        if (collections === 1 && moreButton(el)) {
          rows.set(id, el);
          return;
        }
        el = el.parentElement;
      }
    });
    return rows;
  }

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  async function unsave(id, row) {
    try {
      row.scrollIntoView({ behavior: 'instant', block: 'center' });
      await sleep(600);
      if (getVisibleRows().get(id) !== row) return false;
      const btn = moreButton(row);
      if (!btn) return false;
      const previous = new Set(Array.from(document.querySelectorAll('[role="menuitem"]')).filter(visible));
      btn.click();
      await sleep(800);
      // Facebook can portal menu items without a role="menu" wrapper.
      const items = Array.from(document.querySelectorAll('[role="menuitem"]'))
        .filter(m => !previous.has(m) && visible(m) && /^(unsave|remove from saved)(\s|$)/i.test((m.innerText || '').trim()));
      const item = items.length === 1 && items[0];
      if (!item) {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        return false;
      }
      if (getVisibleRows().get(id) !== row || !visible(item)) return false;
      item.click();
      for (let i = 0; i < 20; i++) {
        await sleep(300);
        if (!visible(row) && !getVisibleRows().has(id)) return true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  return (async () => {
    const result = {};
    for (const id of ids) {
      const row = getVisibleRows().get(id);
      if (row) result[id] = await unsave(id, row);
    }
    return result;
  })();
}
"""


def scrape_saved_items(page, stop_at: str, capture_thumbs: bool, unsave: bool,
                       max_empty_scrolls: int, scroll_pause_ms: int, out_dir: Path | None = None) -> list[dict]:
    if unsave and out_dir is None:
        raise ValueError('A CSV output directory is required before unsaving.')
    scraped: list[dict] = []
    seen_ids: set[str] = set()
    empty_scrolls = 0
    stop_lower = stop_at.lower().strip()

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(1500)

    while empty_scrolls < max_empty_scrolls:
        batch = page.evaluate(
            EXTRACT_VISIBLE_JS,
            {"seenIds": list(seen_ids), "captureThumbs": capture_thumbs},
        )

        if not batch:
            empty_scrolls += 1
            print(f"[scroll] no new items ({empty_scrolls}/{max_empty_scrolls})")
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(scroll_pause_ms)
            continue

        empty_scrolls = 0
        batch_ids: list[str] = []
        for item in batch:
            item_id = item["id"]
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            batch_ids.append(item_id)

            full_text = item.pop("fullText", "") or ""
            if stop_lower and stop_lower in full_text.lower():
                print(f'[stop] matched stop text "{stop_at}" on {item_id}')
                scraped.append(item)
                return scraped

            scraped.append(item)
            desc = (item.get("description") or "")[:70]
            print(f"[item {len(scraped):04d}] {item_id} {desc}")

        if unsave and batch_ids:
            checkpoint = write_csv(scraped, out_dir)
            print(f"[checkpoint] CSV written to {checkpoint}")
            unsaved = page.evaluate(UNSAVE_VISIBLE_JS, batch_ids)
            for item in scraped[-len(batch_ids):]:
                item["unsaved"] = bool(unsaved.get(item["id"]))
                if not item["unsaved"]:
                    print('[status] unsave-failed', flush=True)

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(scroll_pause_ms)

    return scraped


def write_csv(rows: list[dict], out_dir: Path, filename: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (filename or f"fb_saved_{time.strftime('%Y-%m-%d')}.csv")
    fields = ["id", "url", "description", "creator", "type", "thumb"]
    temporary = out_path.with_suffix('.csv.tmp')
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, out_path)
    finally:
        temporary.unlink(missing_ok=True)
    return out_path


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
            context = browser.new_context(storage_state=state, viewport={"width": 1440, "height": 1200})
        else:
            context = p.chromium.launch_persistent_context(user_data_dir=str(args.profile_dir), headless=args.headless, viewport={"width": 1440, "height": 1200})
        try:
            if args.cookies:
                try:
                    import_cookies(context, args.cookies)
                except Exception as exc:
                    print(f"[warn] Could not import cookies from {args.cookies}: {exc}")

            page = context.pages[0] if context.pages else context.new_page()
            wait_for_saved_page(page, args.login_wait_seconds or (300 if args.headless else 0))
            checkpoint_dir = args.output_dir / 'pending' / f'facebook-{time.time_ns()}' if args.unsave else None

            rows = scrape_saved_items(
                page=page,
                stop_at=args.stop_at,
                capture_thumbs=not args.no_thumbs,
                unsave=args.unsave,
                max_empty_scrolls=args.max_empty_scrolls,
                scroll_pause_ms=args.scroll_pause_ms,
                out_dir=checkpoint_dir,
            )

            out_path = write_csv(rows, args.output_dir, f"fb_saved_{time.strftime('%Y-%m-%d')}_{time.time_ns()}.csv")
            if checkpoint_dir and checkpoint_dir.exists():
                try:
                    for checkpoint in checkpoint_dir.glob('fb_saved_*.csv'):
                        checkpoint.unlink()
                    checkpoint_dir.rmdir()
                except OSError as exc:
                    print(f"[warn] Could not clean up the published CSV checkpoint: {exc}")
            print(f"[done] Scraped {len(rows)} items")
            if args.unsave:
                print(f"[done] Unsaved {sum(bool(row.get('unsaved')) for row in rows)} of {len(rows)} posts")
            print(f"[done] CSV written to {out_path}")
            return 0
        finally:
            try:
                if args.isolated and args.remember and args.session_state:
                    save_scoped_state(context, args.session_state, 'facebook')
            finally:
                context.close()
                if browser:
                    browser.close()


if __name__ == "__main__":
    sys.exit(main())
