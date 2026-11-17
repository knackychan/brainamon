"""D2 card scan and thumbnail landing through authenticated SSE; no external calls."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import uvicorn
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from core.db import Database
from server.app import create_app
from server.jobs import KINDS

ROOT = Path(__file__).resolve().parents[1]


class MotionCardsBrowser(unittest.TestCase):
    def test_scan_and_thumbnail_landing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            iid = db.add_item({'url': 'https://example.invalid/cards', 'description': 'Card fixture'})
            db.update_item(iid, {'thumb_path': 'thumb.jpg'})
            db.set_setting('onboarding_hidden', '1')
            db.close()
            thumb = root / 'data/items' / str(iid) / 'thumb.jpg'
            thumb.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (96, 128), '#446688').save(thumb)
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            app = create_app(data_dir=root / 'data', cloud_dir=root / 'cloud', port=port,
                             web_dist=ROOT / 'web/dist')
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                                   timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            gate = threading.Event()

            def fetch(job, item):
                job.step(item['id'], 'Reading synthetic preview')
                gate.wait(20)

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
                            for mode in ('normal', 'off', 'reduced', 'rest'):
                                with self.subTest(motion=mode):
                                    app.state.writer.call(lambda db: db.update_item(iid, {'thumb_path': 'thumb.jpg'}))
                                    context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                                                  reduced_motion='reduce' if mode == 'reduced' else 'no-preference')
                                    page = context.new_page()
                                    errors = []
                                    page.on('pageerror', lambda error: errors.append(str(error)))
                                    try:
                                        with page.expect_response(lambda r: r.url.endswith('/api/events') and r.status == 200):
                                            try:
                                                page.goto(f'http://127.0.0.1:{port}/#cm-auth=' + app.state.api_token)
                                            except Exception:
                                                raise AssertionError('Test bootstrap failed; credential URL omitted') from None
                                        cell = page.locator(f'#grid .cell[data-id="{iid}"]')
                                        image = cell.locator('img.art.ld')
                                        landed = page.locator(f'#grid .cell[data-id="{iid}"].mo-land')
                                        expect(cell).to_have_count(1)
                                        expect(image).to_have_count(1)
                                        expect(landed).to_have_count(0)
                                        if mode in ('off', 'rest'):
                                            page.evaluate("name => document.documentElement.classList.add(name)",
                                                          'motion-off' if mode == 'off' else 'cm-rest')
                                        gate.clear()
                                        app.state.jobs.start('thumb', [iid], force=True)
                                        scan = cell.locator('.job-scan.mo-scan')
                                        expect(scan).to_be_visible()
                                        expect(scan).to_have_attribute('aria-hidden', 'true')
                                        style = scan.evaluate("e => { const s = getComputedStyle(e), p = getComputedStyle(e, '::after'); return {top:s.top, pointer:s.pointerEvents, width:e.clientWidth, height:e.clientHeight, animation:p.animationName, display:p.display, play:p.animationPlayState} }")
                                        self.assertEqual(style['top'], '14px')
                                        self.assertEqual(style['pointer'], 'none')
                                        self.assertAlmostEqual(style['height'] / style['width'], 88 / 63, delta=.02)
                                        if mode in ('off', 'reduced', 'rest'):
                                            self.assertEqual(style['animation'], 'none')
                                            self.assertEqual(style['display'], 'none')
                                        else:
                                            self.assertEqual(style['animation'], 'mo-sweep')
                                            self.assertEqual(style['play'], 'running')
                                        gate.set()
                                        expect(cell.locator('.drn-tag')).to_have_text('DONE ✓')
                                        expect(scan).to_have_count(0)

                                        def refresh(change=None):
                                            if change is not None:
                                                app.state.writer.call(lambda db: db.update_item(iid, change))
                                            with page.expect_response(lambda r: '/api/items?fmt=cols&ids=' in r.url and r.status == 200):
                                                app.state.hub.publish('items_changed', {'ids': [iid]})

                                        before = image.get_attribute('src')
                                        refresh({'thumb_path': 'thumb.jpg'})
                                        expect(image).not_to_have_attribute('src', before)
                                        if mode == 'normal':
                                            expect(landed).to_have_count(1)
                                            self.assertEqual(image.evaluate('e => getComputedStyle(e).animationName'), 'mo-land')
                                            # A repeated row snapshot must not cancel the active hold.
                                            page.wait_for_timeout(700)
                                            refresh()
                                            page.wait_for_timeout(200)
                                            expect(landed).to_have_count(1)
                                            expect(landed).to_have_count(0, timeout=1000)
                                            old_image = image.element_handle()
                                            before = image.get_attribute('src')
                                            refresh({'thumb_path': 'thumb.jpg'})
                                            expect(image).not_to_have_attribute('src', before)
                                            expect(landed).to_have_count(1)
                                            self.assertFalse(old_image.evaluate('e => e.isConnected'))
                                            page.evaluate("document.documentElement.classList.add('motion-off')")
                                            self.assertEqual(image.evaluate('e => getComputedStyle(e).animationName'), 'none')
                                            expect(landed).to_have_count(0, timeout=2300)
                                            page.evaluate("document.documentElement.classList.remove('motion-off')")
                                        else:
                                            expect(landed).to_have_count(0)
                                            self.assertEqual(image.evaluate('e => getComputedStyle(e).animationName'), 'none')
                                        before = image.get_attribute('src')
                                        refresh({'thumb_path': ''})
                                        expect(image).not_to_have_attribute('src', before)
                                        expect(landed).to_have_count(0)
                                        self.assertEqual(errors, [])
                                    finally:
                                        gate.set()
                                        context.close()
                        finally:
                            browser.close()
            finally:
                gate.set()
                server.should_exit = True
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
