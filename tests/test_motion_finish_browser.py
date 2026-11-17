"""D1 finish feedback through the real authenticated SSE stream; no site or AI calls."""
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

ROOT = Path(__file__).resolve().parents[1]


class MotionFinishBrowser(unittest.TestCase):
    def test_manual_finish_hold_and_follow_up(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            iid = db.add_item({'url': 'https://example.invalid/finish', 'description': 'Finish fixture'})
            db.set_setting('onboarding_hidden', '1')
            db.close()
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
                                    app.state.writer.call(lambda db: db.update_item(iid, {'thumb_path': ''}))
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
                                        expect(page.locator('.cell[data-id]')).to_have_count(1)
                                        expect(page.locator('.rjobs .n')).to_have_text('Idle')
                                        expect(page.locator('.rj-ok')).to_have_count(0)
                                        status = page.locator('#status-g button').filter(has_text='Missing thumbnail')
                                        expect(status.locator('.c')).to_have_text('1')
                                        if mode == 'off':
                                            page.evaluate("document.documentElement.classList.add('motion-off')")
                                        gate.clear()
                                        app.state.jobs.start('thumb', [iid], force=True)
                                        expect(page.locator('.rjobs .n')).to_have_text('Running')
                                        expect(page.locator('.rjobs .c')).to_have_text('0/1')
                                        expect(page.locator('#mb-job .lamp.mo-pulse')).to_have_count(1)
                                        if mode in ('off', 'reduced'):
                                            self.assertEqual(page.locator('#mb-job .lamp').evaluate('e => getComputedStyle(e).animationName'), 'none')
                                        if mode == 'rest':
                                            page.evaluate("document.documentElement.classList.add('cm-rest')")
                                        gate.set()
                                        expect(page.locator('.rjobs .n')).to_have_text('Done')
                                        expect(page.locator('.rjobs .rj-ok')).to_have_text('✓ 1/1')
                                        if mode != 'normal':
                                            self.assertEqual(page.locator('.rj-ok').evaluate('e => getComputedStyle(e).opacity'), '1')
                                            self.assertEqual(page.locator('.rj-ok').evaluate('e => getComputedStyle(e).animationName'), 'none')
                                        expect(page.locator('#mb-w')).to_have_text('THUMB DONE')
                                        expect(page.locator('#mb-job .lamp.g')).to_have_count(1)
                                        expect(page.locator('.rjobs .prog.mo-done')).to_have_attribute('aria-valuenow', '100')
                                        expect(page.locator('.rjobs .prog.mo-done i.lit')).to_have_count(12)
                                        expect(page.locator('.rjobs .rj-fin .l')).to_have_text('1 done')
                                        expect(page.locator('.rjobs').get_by_role('button', name='Progress', exact=True)).to_have_count(1)
                                        expect(page.locator('.rjobs .c')).to_have_count(0)
                                        expect(status.locator('.c.mo-okc')).to_have_count(1)
                                        expect(status.locator('.mo-delta')).to_have_count(0)
                                        # Row refresh deliberately lands after the finish snapshot.
                                        app.state.writer.call(lambda db: db.update_item(iid, {'thumb_path': 'thumb.jpg'}))
                                        app.state.hub.publish('items_changed', {'ids': [iid]})
                                        expect(status.locator('.mo-delta')).to_have_text('−1')
                                        if mode != 'normal':
                                            self.assertEqual(status.locator('.mo-delta').evaluate('e => getComputedStyle(e).opacity'), '1')
                                            self.assertEqual(status.locator('.mo-delta').evaluate('e => getComputedStyle(e).animationName'), 'none')
                                        expect(status.locator('.c')).to_have_text('0')
                                        app.state.hub.publish('job', app.state.jobs.snapshot())
                                        page.wait_for_timeout(120)
                                        expect(page.locator('.rjobs .n')).to_have_text('Done')
                                        expect(status.locator('.mo-delta')).to_have_count(0, timeout=2500)
                                        expect(status.locator('.c.mo-okc')).to_have_count(0)
                                        expect(page.locator('.rjobs .n')).to_have_text('Idle', timeout=5000)
                                        expect(page.locator('.rj-ok')).to_have_count(0)
                                        expect(page.locator('#mb-w')).to_have_text('idle')
                                        expect(page.locator('#mb-job .lamp.off')).to_have_count(1)
                                        with page.expect_response(lambda r: r.url.endswith('/api/events') and r.status == 200):
                                            page.reload()
                                        expect(page.locator('.rjobs .n')).to_have_text('Idle')
                                        expect(page.locator('.rj-ok')).to_have_count(0)

                                        if mode == 'normal':
                                            gate.clear()
                                            app.state.jobs.start('thumb', [iid], force=True)
                                            expect(page.locator('.rjobs .n')).to_have_text('Running')
                                            gate.set()
                                            expect(page.locator('.rjobs .n')).to_have_text('Done')
                                            finished = app.state.jobs.snapshot()['last']
                                            auto = dict(finished, id=finished['id'] + 100, kind='index', label='Index search',
                                                        state='running', done=0, current=iid, auto=True, t1=0)
                                            app.state.hub.publish('job', {'current': auto, 'last': finished})
                                            expect(page.locator('.rjobs .n')).to_have_text('Running')
                                            expect(page.locator('.rj-ok')).to_have_text('✓ 1/1')
                                            expect(page.locator('.rjobs .c')).to_have_text('0/1')
                                            expect(page.locator('.rjobs').get_by_role('button', name='Progress', exact=True)).to_have_count(1)
                                            auto_done = dict(auto, state='finished', done=1, current=None)
                                            app.state.hub.publish('job', {'current': None, 'last': auto_done})
                                            expect(page.locator('.rjobs .n')).to_have_text('Done')
                                            expect(page.locator('#mb-w')).to_have_text('THUMB DONE')
                                            manual = dict(auto, id=auto['id'] + 1, auto=False, kind='thumb', label=finished['label'])
                                            app.state.hub.publish('job', {'current': manual, 'last': auto_done})
                                            expect(page.locator('.rjobs .n')).to_have_text('Running')
                                            expect(page.locator('.rj-ok')).to_have_count(0)
                                            stopped = dict(manual, state='stopped', current=None)
                                            app.state.hub.publish('job', {'current': None, 'last': stopped})
                                            expect(page.locator('.rjobs .n')).to_have_text('Idle')
                                            expect(page.locator('.rj-ok')).to_have_count(0)
                                        self.assertEqual(errors, [])
                                    finally:
                                        context.close()
                        finally:
                            browser.close()
            finally:
                gate.set()
                server.should_exit = True
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
