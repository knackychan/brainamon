"""Desktop fetch feedback through the real authenticated SSE stream; no site or AI calls."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import uvicorn
from playwright.sync_api import expect, sync_playwright

from core.db import Database
from server.app import create_app
from server.jobs import KINDS
from starlette.responses import Response

ROOT = Path(__file__).resolve().parents[1]


class DesktopJobProgressBrowser(unittest.TestCase):
    def test_tools_fetch_progress_and_cards(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            ids = [db.add_item({'url': f'https://example.invalid/{i}', 'description': f'Fetch fixture {i}'}) for i in range(3)]
            db.set_setting('onboarding_hidden', '1')
            db.close()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            app = create_app(data_dir=root / 'data', cloud_dir=root / 'cloud', port=port,
                             web_dist=ROOT / 'web/dist')
            # EventSource closes permanently on a failed HTTP response; the UI must reconnect.
            attempts = []
            @app.middleware('http')
            async def interrupted_stream(request, call_next):
                if request.url.path == '/api/events':
                    attempts.append(True)
                    if len(attempts) == 1:
                        return Response(status_code=503)
                return await call_next(request)
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                                   timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            gates = [threading.Event() for _ in ids]

            def fetch(job, item):
                job.step(item['id'], 'Reading synthetic preview')
                gates[ids.index(item['id'])].wait(20)

            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                with mock.patch.multiple(KINDS['thumb'], run_item=fetch, persist=lambda *args: None, text=False, gap=0):
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(channel='msedge', headless=True)
                        try:
                            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                            page = context.new_page()
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            try:
                                page.goto(f'http://127.0.0.1:{port}/#cm-auth=' + app.state.api_token)
                            except Exception:
                                raise AssertionError('Test bootstrap failed; credential URL omitted') from None
                            expect(page.locator('.cell[data-id]')).to_have_count(3)
                            page.get_by_role('button', name='Processing tools', exact=True).click()
                            page.get_by_role('button', name='Review fetch link info', exact=False).click()
                            page.get_by_role('alertdialog').get_by_role('button', name='Fetch 3', exact=True).click()
                            queue = page.get_by_role('dialog', name='Processing progress', exact=True)
                            expect(queue).to_be_visible()
                            expect(page.locator('.rjobs .n')).to_have_text('Running')
                            first = app.state.jobs.current.current
                            _, second, third = app.state.jobs.current.ids
                            expect(page.locator(f'.cell[data-id="{first}"].worked .job-scan')).to_be_visible()
                            expect(page.locator('.rjobs .c')).to_have_text('0/3')
                            expect(queue.locator(f'[data-item-id="{first}"] b')).to_have_text('Processing')
                            expect(queue.locator(f'[data-item-id="{second}"] b')).to_have_text('Queued')
                            expect(queue.get_by_role('progressbar')).to_have_attribute('aria-valuenow', '0')
                            queue.get_by_role('button', name='Pause', exact=True).click()
                            expect(queue.locator(f'[data-item-id="{first}"] b')).to_have_text('Paused')
                            expect(queue.get_by_role('button', name='Resume', exact=True)).to_be_enabled()
                            queue.get_by_role('button', name='Resume', exact=True).click()
                            expect(queue.locator(f'[data-item-id="{first}"] b')).to_have_text('Processing')
                            gates[ids.index(first)].set()
                            expect(page.locator(f'.cell[data-id="{first}"].done')).to_be_visible()
                            expect(page.locator(f'.cell[data-id="{second}"].worked .job-scan')).to_be_visible()
                            expect(page.locator('.rjobs .c')).to_have_text('1/3')
                            expect(queue.locator(f'[data-item-id="{first}"] b')).to_have_text('Done')
                            expect(queue.locator(f'[data-item-id="{second}"] b')).to_have_text('Processing')
                            self.assertAlmostEqual(float(queue.get_by_role('progressbar').get_attribute('aria-valuenow')), 100 / 3)
                            out = ROOT / 'build/fetch-progress-review'
                            out.mkdir(parents=True, exist_ok=True)
                            for width in (1440, 390):
                                page.set_viewport_size({'width': width, 'height': 1000})
                                page.screenshot(path=str(out / f'queue-{width}.png'))
                                self.assertTrue(queue.evaluate('e => e.scrollWidth <= e.clientWidth + 1'))
                            page.set_viewport_size({'width': 1440, 'height': 1000})
                            page.keyboard.press('Escape')
                            page.context.route('**/api/settings/scraper-runtime', lambda route: route.fulfill(json={
                                'state': 'ready', 'workers': True, 'python': True, 'supported': True,
                            }))
                            page.get_by_role('button', name='File', exact=True).click()
                            page.get_by_role('menuitem', name='Scrapers').click()
                            scraper = page.get_by_role('dialog', name='Scrapers', exact=True)
                            scraper.locator('[data-site="facebook"]').click()
                            start = scraper.get_by_role('button', name='Open Facebook & scan', exact=True)
                            expect(start).to_be_disabled()
                            expect(scraper.get_by_role('status').filter(has_text='One job at a time')).to_contain_text('Fetch link info')
                            scraper.get_by_role('button', name='Show progress', exact=True).click()
                            expect(queue).to_be_visible()
                            queue.get_by_role('button', name='Stop', exact=True).click()
                            gates[ids.index(second)].set()
                            expect(page.locator('.rjobs .n')).to_have_text('Idle')
                            expect(queue.locator(f'[data-item-id="{third}"] b')).to_have_text('Not processed')
                            expect(queue.locator('.cw-foot small')).to_contain_text('Stopped')
                            expect(queue.get_by_role('button', name='Stop', exact=True)).to_be_disabled()
                            expect(start).to_be_enabled()
                            expect(scraper.get_by_role('button', name='Show progress', exact=True)).to_have_count(0)
                            self.assertEqual(errors, [])
                        finally:
                            browser.close()
            finally:
                for gate in gates:
                    gate.set()
                server.should_exit = True
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
