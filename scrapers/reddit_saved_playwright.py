"""
Browser-driven Reddit Saved scraper using Playwright.

The automated alternative to pasting `reddit_scraper.js` into DevTools: it opens a persistent
Chromium profile on old.reddit.com, waits for you to log in the first time, then runs the same
collect() as the console script (loaded from reddit_scraper.js, so the row rules live in one place)
and writes reddit_saved_<date>.csv in the shape Brainamon's importer reads.

With --unsave, each scraped item is unsaved AFTER the CSV is written (what the "unsave" button does:
POST /api/unsave with the session's modhash). Reddit lists only the newest ~1000 saves, so unsaving
lets a later run reach older ones.

    pip install playwright
    python -m playwright install chromium
    python scrapers/reddit_saved_playwright.py [--unsave]
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from fb_saved_playwright import configure_stdio, import_cookies, save_scoped_state

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = ROOT / "local" / "cache" / "playwright" / "reddit-profile"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "scrapes"
SCRAPER_JS = Path(__file__).resolve().parent / "reddit_scraper.js"
HOME_URL = "https://old.reddit.com/"
LOGIN_URL = "https://old.reddit.com/login"
FIELDS = ["url", "description", "creator", "type", "thumb"]
MAX_UNSAVE_FAILS = 3          # unsave refusals in a row before giving up


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Reddit Saved items with Playwright and export reddit_saved_*.csv.")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cookies", type=Path, default=None, help="Optional Netscape cookies.txt to import first.")
    parser.add_argument("--stop-at", default="", help="Stop when a title contains this substring.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--login-wait-seconds", type=int, default=300)
    parser.add_argument("--unsave", action="store_true", help="Unsave each scraped item after the CSV is written.")
    parser.add_argument("--unsave-delay-ms", type=int, default=1500)
    parser.add_argument('--isolated', action='store_true')
    parser.add_argument('--session-state', type=Path)
    parser.add_argument('--remember', action='store_true')
    return parser.parse_args()


def logged_in_user(page) -> str:
    return page.evaluate(
        """async () => {
          try {
            const r = await fetch('/api/me.json', { credentials: 'include' });
            const j = await r.json();
            return (j && j.data && j.data.name) || '';
          } catch (e) { return ''; }
        }"""
    )


def wait_for_login(page, login_wait_seconds: int) -> str:
    page.goto(HOME_URL, wait_until="domcontentloaded")
    user = logged_in_user(page)
    if user:
        return user
    print("[action] Reddit needs a login in the opened browser. Log in there normally.")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    deadline = time.time() + max(5, login_wait_seconds)
    while time.time() < deadline:
        page.wait_for_timeout(5000)
        if "reddit.com" in page.url and "/login" not in page.url:
            user = logged_in_user(page)
            if user:
                return user
        print(f"[action] Waiting for the Reddit login ({int(deadline - time.time())}s left)...")
    raise RuntimeError("Reddit login did not complete before timeout. Re-run and log in in the opened browser.")


def write_csv(rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"reddit_saved_{time.strftime('%Y-%m-%d')}_{time.time_ns()}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") or "" for field in FIELDS})
    return out_path


def unsave_all(page, rows: list[dict], modhash: str, delay_ms: int) -> int:
    if not modhash:
        print("[warn] Reddit gave no modhash for this session: nothing unsaved.")
        return 0
    done, fails = 0, 0
    for i, row in enumerate(rows, 1):
        name = row.get("name") or ""
        if not name:
            continue
        ok = page.evaluate("([n, m]) => window.__cm.unsave(n, m)", [name, modhash])
        if ok:
            done, fails = done + 1, 0
            print(f"[unsave {i:04d}/{len(rows)}] {row.get('url', '')}")
        else:
            fails += 1
            print(f"[warn] Reddit refused to unsave {row.get('url', '')}")
            if fails >= MAX_UNSAVE_FAILS:
                print("[warn] Several refusals in a row: stopping the unsave pass.")
                break
        page.wait_for_timeout(delay_ms + random.randint(0, 500))
    return done


def main() -> int:
    configure_stdio()
    args = parse_args()
    if not args.isolated:
        args.profile_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    script = SCRAPER_JS.read_text(encoding="utf-8")

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
            page.on("console", lambda m: print(f"[page] {m.text}") if m.type in ("log", "error", "warning") else None)

            user = wait_for_login(page, args.login_wait_seconds)
            print(f"[info] Logged in as u/{user}")
            page.goto(f"https://old.reddit.com/user/{user}/saved/", wait_until="domcontentloaded")
            # the console script's functions, without running it (window.__cm)
            page.evaluate("window.__CM_NO_RUN = true")
            page.evaluate(script)

            result = page.evaluate("(stopAt) => window.__cm.collect(stopAt)", args.stop_at)
            rows = result.get("rows") or []
            out_path = write_csv(rows, args.output_dir)
            print(f"[done] Scraped {len(rows)} items ({result.get('thumbs', 0)} with a thumbnail)")
            print(f"[done] CSV written to {out_path}")

            if args.unsave and rows:
                n = unsave_all(page, rows, result.get("modhash") or "", args.unsave_delay_ms)
                print(f"[done] Unsaved {n} of {len(rows)} items")
            return 0
        finally:
            try:
                if args.isolated and args.remember and args.session_state:
                    save_scoped_state(context, args.session_state, 'reddit')
            finally:
                context.close()
                if browser:
                    browser.close()


if __name__ == "__main__":
    sys.exit(main())
