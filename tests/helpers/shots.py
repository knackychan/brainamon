"""Deterministic screenshots of a built UI against synthetic, disposable data.

Runs the backend of --repo against a throwaway library (the --root folder: never data/), serves the
web build in --dist, seeds the same items every time, then shoots the desktop and phone screens in
dark and light. Two runs on the same build give the same PNGs: the browser's clock, the server's clock,
the port, the library folder, randomness and the browser's storage estimate are pinned; card motion is
off (the app's own Motion switch); Chromium draws in software with no LCD text, so GPU rounding cannot
move a pixel; every shot waits until no request is in flight; canvases, toasts and console timestamps
are hidden. A before and an after build are compared with tools/pixdiff.py, and any pixel that differs
is a regression.

    py tests/helpers/shots.py --out <folder> [--repo <checkout>] [--dist <web build>]
        [--themes dark,light] [--only settings,phone-more] [--port 0] [--root <throwaway folder>]

--repo defaults to this checkout and --dist to <repo>/web/dist. --only keeps the shots whose name
contains one of the given words. A fresh root and ephemeral port are the defaults. For pixel comparisons,
pass the same explicit port and marked root to both runs (some screens display them). The
root folder is emptied at the start and removed at the end; the script refuses a folder it did not
make. Needs Python Playwright with Chromium (the guided import browser check uses the same).
"""
import argparse
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = Path(__file__).resolve().parents[2]
MARKER = '.ui-blocks-shots'

SERVER = r'''
import sys, time
from pathlib import Path
root = Path(sys.argv[1]); port = int(sys.argv[2]); dist = Path(sys.argv[3])
# the server's clock starts at the pinned time, so what it stamps (an item's saved day) is the same every run
_real = time.time; _shift = float(sys.argv[4]) - _real()
time.time = lambda: _real() + _shift
from core import app_paths, config
app_paths.LOCAL = root / 'local'; app_paths.LOCAL.mkdir(exist_ok=True)
app_paths.CACHE = app_paths.LOCAL / 'cache'; app_paths.ERROR_LOG = app_paths.LOCAL / 'error_log.txt'
config.ENV_PATH = root / 'absent.env'
from server.app import create_app
import uvicorn
uvicorn.run(create_app(data_dir=root / 'data', port=port, web_dist=dist, cloud_dir=root / 'cloud'),
            host='127.0.0.1', port=port, log_level='warning')
'''

# the per-run credential the trusted launcher hands the page (core/local_auth.py); absent on older trees
TOKEN = r'''
import sys
from pathlib import Path
from core import app_paths, local_auth
app_paths.LOCAL = Path(sys.argv[1]) / 'local'
print(local_auth.browser_url('http://127.0.0.1:%s/' % sys.argv[2], int(sys.argv[2])).split('#cm-auth=', 1)[1])
'''

ITEMS = [
    ('Reel', 'Three-minute knife skills for weeknight dinners', 'chefnora', 'https://example.com/reel/1001'),
    ('Reel', 'How to film a smooth handheld pan without a gimbal', 'framebyframe', 'https://example.com/reel/1002'),
    ('Post', 'A reading list for learning SQL window functions', 'datadesk', 'https://example.com/post/2001'),
    ('Post', 'Before and after: a balcony garden in one season', 'smallgreen', 'https://example.com/post/2002'),
    ('Video', 'Typography basics: measure, leading and rhythm', 'typeclass', 'https://example.com/video/3001'),
    ('Video', 'Fixing a dripping tap in ten minutes', 'fixitfast', 'https://example.com/video/3002'),
    ('Reel', 'Five stretches for long days at a desk', 'movewell', 'https://example.com/reel/1003'),
    ('Post', 'Notes from a week of slow travel by train', 'railnotes', 'https://example.com/post/2003'),
    ('Video', 'Sourdough starter from scratch, day by day', 'crumbshot', 'https://example.com/video/3003'),
    ('Reel', 'Color grading a sunset clip in three steps', 'gradelab', 'https://example.com/reel/1004'),
    ('Post', 'The checklist I use before every product launch', 'shipnotes', 'https://example.com/post/2004'),
    ('Video', 'Beginner watercolor: wet on wet skies', 'paperandwater', 'https://example.com/video/3004'),
]

# palette commands whose window the desktop pass shoots (labels from web/src/lib/command-table.ts)
WINDOWS = [
    ('setup', 'Set up Brainamon'), ('help', 'Help'), ('keys', 'Keyboard shortcuts'), ('about', 'About Brainamon'),
    ('add', 'Add to Brainamon'), ('import', 'Import CSV or JSON'), ('scrapers', 'Scrapers'),
    ('export-csv', 'Export item CSV'), ('export-obsidian', 'Export to Obsidian'), ('video-tools', 'Video Tools'),
    ('process', 'Process items'), ('new-collection', 'New collection'), ('progress', 'Show progress'),
    ('new-canvas', 'New canvas'), ('synthesize', 'Synthesize a note'),
]
SELECTION_WINDOWS = [('bulk', 'Bulk edit'), ('delete', 'Delete selected'), ('analyze', 'Analyze videos')]
PHONE_ROUTES = [('library', '#/'), ('more', '#/more'), ('capture', '#/cap'), ('wiskit', '#/jv'), ('notes', '#/notes'),
                ('import', '#/import'), ('canvas', '#/canvas')]

FIXED_TIME = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
# software rendering: the GPU path rounds blurs and edges differently from one run to the next
BROWSER_ARGS = ['--disable-gpu', '--disable-gpu-rasterization', '--disable-partial-raster', '--disable-lcd-text',
                '--disable-skia-runtime-opts', '--force-color-profile=srgb']
# hidden while shooting: canvases (drawn every frame: the field behind the app, Wiskit's sprite), the
# toasts (they leave after a few seconds) and the console's timestamps (the server's real time of day)
# The transient loading bar's off-screen glow can survive in Chromium's backdrop blur cache.
FREEZE = 'canvas, #toasts, .cl time, .loadbar { visibility: hidden !important }'
# before any page script: the theme, card motion off (the engine's and the phone's own switches), a
# seeded Math.random, and a count of the page's requests in flight (window.__busy) for Run.settle
INIT = '''(() => {
  try {
    localStorage.setItem('cm-os-theme', THEME)
    localStorage.setItem('cm-card-motion', 'off')
    localStorage.setItem('bp-motion', 'off')
  } catch (e) {}
  let s = 20261025
  Math.random = () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646 }
  if (navigator.storage) navigator.storage.estimate = async () => ({ usage: 0, quota: 8e9 })
  let busy = 0
  const fetch = window.fetch
  window.fetch = function (...args) { busy++; return fetch.apply(this, args).finally(() => setTimeout(() => busy--)) }
  Object.defineProperty(window, '__busy', { get: () => busy })
})()'''


def check_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is in use: pass --port with a free one, the same for the before and '
                             'after runs')


class Run:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.only = [w for w in (args.only or '').split(',') if w]
        self.taken = []

    def wanted(self, name):
        return not self.only or any(w in name for w in self.only)

    # ------------------------------------------------------------------ server

    def start(self, root):
        repo = Path(self.args.repo).resolve()
        dist = Path(self.args.dist).resolve() if self.args.dist else repo / 'web' / 'dist'
        self.port = self.args.port
        if not self.port:
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                self.port = reservation.getsockname()[1]
        check_port(self.port)
        self.base = f'http://127.0.0.1:{self.port}'
        env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in
               ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'BRAINAMON_', 'CM_DATA_DIR', 'YTDLP_COOKIES'))}
        for folder in ('temp', 'profile'):
            (root / folder).mkdir()
        env.update(BRAINAMON_HOME=str(root), CM_DATA_DIR=str(root / 'data'),
                   LOCALAPPDATA=str(root / 'profile'), APPDATA=str(root / 'profile'),
                   TEMP=str(root / 'temp'), TMP=str(root / 'temp'),
                   PYTHONIOENCODING='utf-8', PYTHON_DOTENV_DISABLED='1')
        self.env = env
        self.log = (root / 'server.log').open('w')
        self.server = subprocess.Popen([sys.executable, '-c', SERVER, str(root), str(self.port), str(dist),
                                        str(FIXED_TIME.timestamp())], cwd=repo,
                                       env=env, stdout=self.log, stderr=self.log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(300):
            try:
                with urlopen(self.base + '/api/health', timeout=2):
                    break
            except HTTPError:
                break                      # any answer means it is listening
            except URLError:
                if self.server.poll() is not None:
                    raise SystemExit((root / 'server.log').read_text(errors='replace'))
                time.sleep(.1)
        else:
            raise SystemExit('The throwaway server did not start')
        self.token = ''
        if (repo / 'core' / 'local_auth.py').exists():
            self.token = subprocess.run([sys.executable, '-c', TOKEN, str(root), str(self.port)], cwd=repo, env=env,
                                        capture_output=True, text=True, check=True).stdout.strip()

    def stop(self):
        self.server.terminate()
        try:
            self.server.wait(10)
        except subprocess.TimeoutExpired:
            self.server.kill()
        self.log.close()

    def api(self, method, path, body=None):
        headers = {'X-CM': '1', 'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        req = Request(self.base + path, method=method, headers=headers,
                      data=None if body is None else json.dumps(body).encode())
        with urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b'null')

    def seed(self):
        self.api('PUT', '/api/onboarding', {'answer': 'links'})
        # a description is given, so no Fetch link info job starts
        self.ids = [self.api('POST', '/api/items', {'url': url, 'description': text, 'short_desc': text,
                                                    'creator': creator, 'type': kind})['id']
                    for kind, text, creator, url in ITEMS]

    def url(self, page='/'):
        return self.base + page + (f'#cm-auth={self.token}' if self.token else '')

    # ------------------------------------------------------------------ browser

    def context(self, browser, theme, phone=False):
        size = {'width': 390, 'height': 844} if phone else {'width': 1440, 'height': 900}
        ctx = browser.new_context(viewport=size, device_scale_factor=1, is_mobile=phone, has_touch=phone,
                                  color_scheme=theme, reduced_motion='reduce', locale='en-US', timezone_id='UTC')
        ctx.add_init_script(INIT.replace('THEME', json.dumps(theme)))
        # Freeze before dialogs capture their backdrop, not temporarily during each screenshot.
        ctx.add_init_script('document.addEventListener("DOMContentLoaded", () => {'
                            'const style = document.createElement("style");'
                            f'style.textContent = {json.dumps(FREEZE)}; document.head.append(style);'
                            '})')
        ctx.clock.set_fixed_time(FIXED_TIME)
        # nothing outside the throwaway server: no fonts, previews or update checks from the network
        ctx.route(lambda u: not u.startswith(self.base), lambda route: route.abort())
        return ctx

    def settle(self, page):
        # no request in flight for 400 ms (at most 10 s): a status still loading would differ run to run
        quiet = 0
        for _ in range(100):
            quiet = quiet + 1 if not page.evaluate('window.__busy || 0') else 0
            if quiet >= 4:
                return
            page.wait_for_timeout(100)
        print('  requests still in flight after 10 s')

    def shot(self, page, name):
        if not self.wanted(name):
            return
        page.mouse.move(2, page.viewport_size['height'] - 2)
        self.settle(page)
        page.evaluate('document.fonts.ready')
        prev = None
        for _ in range(25):
            page.wait_for_timeout(150)
            png = page.screenshot(animations='disabled', caret='hide')
            if png == prev:
                break
            prev = png
        else:
            print(f'  {name}: still moving after 25 tries (kept the last frame)')
        (self.out / f'{name}.png').write_bytes(png)
        self.taken.append(name)

    # every page of a scrolling element: the window body, or the phone's main column
    def shot_pages(self, page, name, scroller):
        size, last = None, 'x'
        for _ in range(20):                 # the content may still be arriving: wait until its height holds
            size = page.evaluate('''s => { const all = document.querySelectorAll(s); const e = all[all.length - 1];
                                           return e ? [e.scrollHeight, e.clientHeight] : null }''', scroller)
            if size == last:
                break
            last = size
            page.wait_for_timeout(150)
        pages = 1 if not size or size[1] == 0 else max(1, math.ceil(size[0] / size[1]))
        for k in range(min(pages, 8)):
            page.evaluate('''([s, k]) => { const all = document.querySelectorAll(s); const e = all[all.length - 1];
                                           if (e) e.scrollTop = k * e.clientHeight }''', [scroller, k])
            self.shot(page, name if k == 0 else f'{name}-p{k + 1}')

    def close_windows(self, page):
        for _ in range(6):
            if not page.locator('.cw').count():
                return
            page.keyboard.press('Escape')
            page.wait_for_timeout(120)

    def palette(self, page, label):
        self.close_windows(page)
        page.keyboard.press('Control+k')
        page.locator('#pal-in').fill(label)
        # the row with this label (a window's label ends in an ellipsis); Enter would take whichever row the
        # filter happened to put first
        row = page.locator('.cw.pal .pal-i').filter(has=page.locator('span', has_text=re.compile(
            '^' + re.escape(label) + '…?$')))
        try:
            row.first.wait_for(timeout=3000)
        except Exception:
            return False
        row.first.click()
        try:
            page.wait_for_function("document.querySelectorAll('.cw:not(.pal)').length > 0", timeout=3000)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ the screens

    def first_start(self, browser, theme):
        ctx = self.context(browser, theme)
        page = ctx.new_page()
        page.goto(self.url())
        page.wait_for_selector('.cw')
        self.shot(page, f'desktop-{theme}-welcome')
        ctx.close()
        ctx = self.context(browser, theme, phone=True)
        page = ctx.new_page()
        page.goto(self.url('/mobile.html'))
        page.wait_for_selector('#m-app')
        self.shot(page, f'phone-{theme}-welcome')
        ctx.close()

    def desktop(self, browser, theme):
        ctx = self.context(browser, theme)
        page = ctx.new_page()
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        self.close_windows(page)
        self.shot(page, f'desktop-{theme}-library')

        page.keyboard.press('Control+Comma')
        page.wait_for_selector('.cw.set-win')
        self.settle(page)                   # some tabs appear only once a request answers (Claude Code)
        tabs = page.locator('.set-nav [id^="set-t"]')
        for i in range(tabs.count()):
            tab = tabs.nth(i)
            tid = tab.get_attribute('id')[len('set-t'):]
            tab.click()
            page.wait_for_timeout(300)
            self.shot_pages(page, f'desktop-{theme}-settings-{tid}', '.cw .cw-body')
        self.close_windows(page)

        page.keyboard.press('Control+k')
        page.wait_for_selector('.cw.pal')
        self.shot(page, f'desktop-{theme}-palette')
        for key, label in WINDOWS:
            if self.palette(page, label):
                page.wait_for_timeout(250)
                self.shot_pages(page, f'desktop-{theme}-win-{key}', '.cw .cw-body')
            else:
                print(f'  desktop {theme}: "{label}" opened no window')
        self.close_windows(page)

        for menu in ('cmos', 'file', 'edit', 'process', 'view'):
            button = page.locator(f'.menubar [data-menu="{menu}"]')
            if button.count() and button.first.is_visible():
                button.first.click()
                page.wait_for_timeout(200)
                self.shot(page, f'desktop-{theme}-menu-{menu}')
                page.keyboard.press('Escape')

        page.locator('.cell[data-id]').first.click()
        page.wait_for_timeout(300)
        if not page.locator('.cw').count():
            page.locator('.cell[data-id]').first.dblclick()
            page.wait_for_timeout(300)
        if page.locator('.cw').count():
            self.shot_pages(page, f'desktop-{theme}-item', '.cw .cw-body')
        else:
            print(f'  desktop {theme}: a card opened no item window')
        self.close_windows(page)

        page.keyboard.press('Control+a')
        page.wait_for_timeout(200)
        self.shot(page, f'desktop-{theme}-selection')
        for key, label in SELECTION_WINDOWS:
            if self.palette(page, label):
                page.wait_for_timeout(250)
                self.shot_pages(page, f'desktop-{theme}-win-{key}', '.cw .cw-body')
            self.close_windows(page)
        page.keyboard.press('Escape')

        for n, ws in ((2, 'knowledge'), (3, 'canvas'), (4, 'notes')):
            page.locator('body').press(str(n))
            page.wait_for_timeout(400)
            self.shot(page, f'desktop-{theme}-ws-{ws}')
        page.locator('body').press('1')
        page.keyboard.press('Control+Backquote')
        page.wait_for_timeout(300)
        self.shot(page, f'desktop-{theme}-console')
        ctx.close()

    def phone(self, browser, theme):
        ctx = self.context(browser, theme, phone=True)
        page = ctx.new_page()
        page.goto(self.url('/mobile.html'))
        page.wait_for_selector('#m-app')
        page.wait_for_timeout(500)
        for key, route in PHONE_ROUTES:
            page.evaluate('h => { location.hash = h }', route)
            page.wait_for_timeout(500)
            self.shot_pages(page, f'phone-{theme}-{key}', '.m-main')
        page.evaluate('h => { location.hash = h }', f'#/item/{self.ids[0]}')
        page.wait_for_timeout(500)
        self.shot_pages(page, f'phone-{theme}-item', '.m-main')
        ctx.close()

    def go(self):
        themes = [t for t in self.args.themes.split(',') if t]
        root = (Path(self.args.root).resolve() if self.args.root else
                Path(tempfile.mkdtemp(prefix='brainamon-browser-library-')).resolve())
        if not self.args.root:
            (root / MARKER).write_text('Disposable browser fixture\n')
        repo = Path(self.args.repo).resolve()
        # An explicit root can never delete a checkout, the real library, or another folder.
        if root == repo or root in repo.parents or repo in root.parents:
            raise SystemExit('The throwaway root must be outside the checkout')
        if root.exists():
            if root.is_symlink() or root.is_junction() or not (root / MARKER).is_file():
                raise SystemExit(f'{root} exists and was not made by this script: pass another --root')
            shutil.rmtree(root)
        root.mkdir(parents=True)
        (root / MARKER).write_text('Throwaway library of tests/helpers/shots.py\n')
        try:
            self.start(root)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=BROWSER_ARGS, env=self.env)
                for theme in themes:
                    self.first_start(browser, theme)
                self.seed()
                for theme in themes:
                    self.desktop(browser, theme)
                    self.phone(browser, theme)
                browser.close()
        finally:
            if hasattr(self, 'server'):
                self.stop()
            shutil.rmtree(root, ignore_errors=True)
        (self.out / 'shots.json').write_text(json.dumps(sorted(self.taken), indent=1))
        print(f'{len(self.taken)} shots in {self.out}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', required=True)
    p.add_argument('--repo', default=str(DEFAULT_REPO))
    p.add_argument('--dist')
    p.add_argument('--themes', default='dark,light')
    p.add_argument('--only')
    p.add_argument('--port', type=int, default=0)
    p.add_argument('--root')
    Run(p.parse_args()).go()


if __name__ == '__main__':
    main()
