"""Manual production-page startup probe; isolated data, no user profile or running app.

Run: py tests/bench_startup.py
Requires the existing Playwright installation and a built web/dist. Times start at
browser navigation, not the desktop shortcut. Samples use a fresh browser context
then the same context's HTTP cache. Synthetic rows have no thumbnail files.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.db import Database
from playwright.sync_api import sync_playwright


def probe(browser, count):
    with tempfile.TemporaryDirectory(prefix='brainamon-startup-') as folder:
        data = Path(folder)
        db = Database(data / 'content_manager.db')
        for i in range(count):
            db.add_item({'url': f'https://example.com/{i}', 'description': f'Startup fixture {i}',
                         'category': 'Testing', 'type': 'Link'})
        db.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, CM_DATA_DIR=folder, CM_PORT=str(port))
        with (data / 'server.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'server'], cwd=ROOT,
                                       env=env, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        with urllib.request.urlopen(base + '/api/health', timeout=.3):
                            break
                    except OSError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError('Isolated server did not start')
                        time.sleep(.05)
                context = browser.new_context(viewport={'width': 1600, 'height': 1000})
                context.add_init_script("window.pywebview = {api: {ready: () => performance.mark('probe-ready')}}")
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for run in range(4):
                    page.goto(base, wait_until='domcontentloaded')
                    page.wait_for_function("performance.getEntriesByName('probe-ready').length > 0")
                    page.wait_for_timeout(500)
                    metrics = page.evaluate("""() => ({
                        ready_ms: Math.round(performance.getEntriesByName('probe-ready')[0].startTime),
                        cards_ms: Math.round(performance.getEntriesByName('cm-first-cards')[0]?.startTime || 0),
                        workspace_count: document.querySelectorAll('main.ws').length,
                        heap_mb: +(performance.memory.usedJSHeapSize / 1048576).toFixed(1)
                    })""")
                    assert not errors, errors
                    assert page.locator('#ws-lib').is_visible()
                    assert metrics['workspace_count'] == 1, metrics
                    assert page.evaluate("performance.getEntriesByName('cm-first-screen').length === 1")
                    print(json.dumps({'items': count, 'run': run, **metrics}), flush=True)
                page.wait_for_timeout(2200)
                assert page.locator('main.ws').count() == 1, 'Unused workspaces mounted at idle'
                assert context.request.post(base + '/api/app/setup/dismiss', headers={'X-CM': '1'}).ok
                page.keyboard.press('Escape')          # first-run Help on the empty fixture
                for ws in ('know', 'canvas', 'notes'):
                    page.locator('#tab-' + ws).click()
                    page.locator('#ws-' + ws).wait_for(state='visible')
                # Already visited workspaces remain mounted when another tab is active.
                assert page.locator('main.ws').count() == 4
                page.locator('#ws-notes').evaluate("el => el.dataset.probe = 'kept'")
                page.locator('#tab-lib').click()
                page.locator('#tab-notes').click()
                assert page.locator('#ws-notes').get_attribute('data-probe') == 'kept'
                for ws in ('know', 'canvas', 'notes', 'lib'):
                    page.evaluate('(ws) => localStorage.setItem("cm-v6-ws", ws)', ws)
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#ws-' + ws).wait_for(state='visible')
                    page.wait_for_function("performance.getEntriesByName('probe-ready').length > 0")
                    assert page.evaluate("performance.getEntriesByName('cm-first-screen').length === 1")
                page.evaluate("localStorage.setItem('cm-v5-view', 'list')")
                page.reload(wait_until='domcontentloaded')
                page.wait_for_function("performance.getEntriesByName('probe-ready').length > 0")
                assert page.evaluate("performance.getEntriesByName('cm-first-screen').length === 1")
                if count:
                    assert page.locator('.cell.lr').count() > 0
                assert not errors, errors
                print(f'PASS: {count} items; idle, workspace retention/restoration, list readiness', flush=True)
                context.close()
            finally:
                process.terminate()
                process.wait(timeout=10)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel='msedge')
        try:
            for count in (0, 3000):
                probe(browser, count)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
