"""D3 tray through authenticated local SSE; synthetic jobs and imports only."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from core.db import Database
from server.app import create_app

ROOT = Path(__file__).resolve().parents[1]


class MotionScrapeBrowser(unittest.TestCase):
    def test_scrape_tray_and_library_handoff(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            old = db.add_item({'url': 'https://example.invalid/old', 'description': 'Old fixture'})
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
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge', headless=True)
                    try:
                        for motion in ('normal', 'off', 'reduced', 'rest'):
                            with self.subTest(motion=motion):
                                context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                                              reduced_motion='reduce' if motion == 'reduced' else 'no-preference')
                                page = context.new_page()
                                errors = []
                                page.on('pageerror', lambda error: errors.append(str(error)))
                                current = None
                                serial = 0
                                fail_start = False

                                def start(route):
                                    nonlocal current, serial
                                    if fail_start:
                                        route.fulfill(status=400, json={'detail': 'Synthetic start failure'})
                                        return
                                    serial += 1
                                    current = dict(id=7000 + serial, kind='scrape', label='Playwright scraper',
                                                   state='running', total=1, done=0, skipped=0, err=0,
                                                   current=-1, auto=False, t0=0, t1=0)
                                    app.state.hub.publish('job', {'current': current, 'last': None})
                                    route.fulfill(json={'ok': True})

                                def end(state='finished', errors=0):
                                    app.state.hub.publish('job', {'current': None, 'last': dict(
                                        current, state=state, err=errors, done=0 if errors else 1, current=None, t1=1)})

                                context.route('**/api/settings/scraper-runtime', lambda route: route.fulfill(json={
                                    'state': 'ready', 'workers': True, 'python': True, 'supported': True,
                                }))
                                context.route('**/api/scrapers', lambda route: route.fulfill(json={
                                    'platforms': [{'key': 'instagram', 'label': 'Instagram', 'target': ''}],
                                    'playwright': [{'key': 'instagram', 'label': 'Instagram'}],
                                    'watching': False, 'dir': str(root / 'downloads'),
                                }))
                                context.route('**/api/scrapers/watch', lambda route: route.fulfill(json={
                                    'watching': route.request.post_data_json.get('on', False), 'dir': str(root / 'downloads'),
                                }))
                                context.route('**/api/scrapers/playwright', start)
                                try:
                                    with page.expect_response(lambda r: r.url.endswith('/api/events') and r.status == 200):
                                        try:
                                            page.goto(f'http://127.0.0.1:{port}/?zoom=0#cm-auth=' + app.state.api_token)
                                        except Exception:
                                            raise AssertionError('Test bootstrap failed; credential URL omitted') from None
                                    expect(page.locator(f'#grid .cell[data-id="{old}"]')).to_have_count(1)
                                    if motion in ('off', 'rest'):
                                        page.evaluate('name => document.documentElement.classList.add(name)',
                                                      'motion-off' if motion == 'off' else 'cm-rest')
                                    if motion == 'normal':
                                        page.locator(f'#grid .cell[data-id="{old}"]').click(modifiers=['Control'])
                                        page.get_by_label('Search the library', exact=True).fill('Old fixture')
                                        expect(page.locator('#fchips .fchip')).to_have_count(1)
                                        page.get_by_role('radiogroup', name='Sort', exact=True).get_by_role('radio', name='Oldest', exact=True).click()
                                        page.locator('#tab-know').click()
                                    page.get_by_role('button', name='File', exact=True).click()
                                    page.get_by_role('menuitem', name='Scrapers').click()
                                    scraper = page.get_by_role('dialog', name='Scrapers', exact=True)
                                    tray = scraper.locator('.mo-scrape-tray')
                                    state = tray.locator('.mo-tray-state')
                                    count = tray.locator('.mo-tray-count')
                                    expect(tray).to_have_attribute('data-phase', 'ready')
                                    expect(state).to_have_text('Ready')
                                    expect(tray.locator('.mo-tray-row')).to_have_count(0)
                                    scraper.get_by_role('tab', name='Manual Scraping', exact=False).click()
                                    expect(tray).to_have_count(0)
                                    scraper.get_by_role('tab', name='Automatic', exact=False).click()
                                    launch = scraper.get_by_role('button', name='Open Instagram & scan', exact=True)
                                    expect(launch).to_be_enabled()
                                    launch.click()
                                    expect(tray).to_have_attribute('data-phase', 'scan')
                                    expect(state).to_have_text('Scanning in the browser window')
                                    app.state.hub.publish('scrape', {'read': 8})
                                    expect(count).to_have_text('8')
                                    app.state.hub.publish('scrape', {'read': 3})
                                    app.state.hub.publish('scrape', {'line': 'Synthetic scan status', 'c': 'd'})
                                    expect(scraper.locator('.tlog')).to_contain_text('Synthetic scan status')
                                    expect(count).to_have_text('8')
                                    self.assertNotIn('undefined', scraper.locator('.tlog').inner_text())

                                    if motion == 'normal':
                                        ids = app.state.writer.call(lambda db: [db.add_item({
                                            'url': f'https://example.invalid/import/{i}',
                                            'description': f'Imported fixture {i}',
                                        }) for i in range(16)])
                                        # The result can precede row refetch and the ending job snapshot.
                                        page.evaluate("""() => {
                                            window.traySeen = [];
                                            new MutationObserver(() => {
                                                document.querySelectorAll('.mo-tray-row[data-id]').forEach(e => {
                                                    const id = +e.dataset.id;
                                                    if (!window.traySeen.includes(id)) window.traySeen.push(id);
                                                });
                                            }).observe(document.querySelector('.mo-scrape-tray'), {subtree:true, childList:true});
                                        }""")
                                        app.state.hub.publish('scrape', {'imported': dict(added=16, duplicates=2, invalid=3, ids=ids)})
                                        expect(tray).to_have_attribute('data-phase', 'play')
                                        expect(tray.locator('.mo-tray-row')).to_have_count(0)
                                        with page.expect_response(lambda r: '/api/items?fmt=cols&ids=' in r.url and r.status == 200):
                                            app.state.hub.publish('items_changed', {'ids': ids, 'added': True})
                                        end()
                                        expect(tray).to_have_attribute('data-phase', 'done')
                                        expect(count).to_have_text('16')
                                        expect(state).to_contain_text('Saved posts imported')
                                        expect(tray).to_contain_text('2 were already in your library.')
                                        expect(tray).to_contain_text('3 rows had no link.')
                                        expect(tray.locator('.mo-tray-row')).to_have_count(5)
                                        self.assertEqual(page.evaluate('window.traySeen'), ids[:12])
                                        self.assertEqual(tray.locator('.mo-tray-row').evaluate_all('rows => rows.map(e => +e.dataset.id)'),
                                                         list(reversed(ids[7:12])))
                                        self.assertEqual(tray.locator('.mo-tray-row').first.evaluate('e => e.getBoundingClientRect().height'), 44)
                                        expect(tray.get_by_role('progressbar')).to_have_attribute('aria-valuenow', '100')
                                        # The finish does not expire on the common D1 hold timer.
                                        page.wait_for_timeout(2900)
                                        expect(tray).to_have_attribute('data-phase', 'done')
                                        tray.get_by_role('button', name='Show in Library', exact=True).click()
                                        expect(scraper).to_have_count(0)
                                        expect(page.locator('#tab-lib')).to_have_attribute('aria-selected', 'true')
                                        expect(page.locator('#q')).to_have_value('')
                                        expect(page.locator('#fchips .fchip')).to_have_count(0)
                                        expect(page.get_by_role('radiogroup', name='Sort', exact=True).get_by_role('radio', name='Newest', exact=True)).to_have_attribute('aria-checked', 'true')
                                        expect(page.locator('#tray-n')).to_contain_text('16 selected')
                                        expect(page.locator(f'#grid .cell[data-id="{old}"].sel')).to_have_count(0)
                                        expect(page.locator('#grid .cell.sel')).to_have_count(16)
                                        expect(page.get_by_text('Selected the 16 new items', exact=True)).to_be_visible()
                                        self.assertEqual(page.locator('#board').evaluate('e => e.scrollTop'), 0)
                                    else:
                                        end()
                                        expect(tray).to_have_attribute('data-phase', 'wait')
                                        expect(state).to_have_text("Reading the scan's file")
                                        # Missing item snapshots use the bounded 1.5-second fallback.
                                        app.state.hub.publish('scrape', {'imported': dict(added=1, duplicates=1, invalid=1, ids=[999999])})
                                        expect(tray).to_have_attribute('data-phase', 'play')
                                        expect(tray).to_have_attribute('data-phase', 'done', timeout=5000)
                                        expect(count).to_have_text('1')
                                        expect(tray).to_contain_text('1 was already in your library.')
                                        expect(tray).to_contain_text('1 row had no link.')
                                        expect(tray.locator('.mo-tray-row')).to_have_count(1)
                                        pop = tray.locator('.mo-pop').first
                                        style = pop.evaluate('e => {const s=getComputedStyle(e);return {name:s.animationName,play:s.animationPlayState}}')
                                        self.assertEqual(style['name'], 'none')
                                        launch.click()
                                        expect(tray).to_have_attribute('data-phase', 'scan')
                                        end('stopped')
                                        expect(tray).to_have_attribute('data-phase', 'off')
                                        expect(state).to_have_text('Scan stopped')
                                        # An exported file may arrive after Stop; importing must still finish.
                                        app.state.hub.publish('scrape', {'imported': dict(added=0, duplicates=0, invalid=0, ids=[])})
                                        expect(tray).to_have_attribute('data-phase', 'done')
                                        expect(tray).to_contain_text('None were already in your library.')
                                        expect(tray.get_by_role('button', name='Show in Library', exact=True)).to_have_count(0)
                                        launch.click()
                                        expect(tray).to_have_attribute('data-phase', 'scan')
                                        end(errors=1)
                                        expect(tray).to_have_attribute('data-phase', 'off')
                                        expect(state).to_have_text('Scan ended with an error')
                                        fail_start = True
                                        launch.click()
                                        expect(tray).to_have_attribute('data-phase', 'ready')
                                        expect(scraper.get_by_role('alert')).to_contain_text('Synthetic start failure')
                                        scraper.get_by_role('tab', name='Manual Scraping', exact=False).click()
                                        expect(tray).to_have_count(0)
                                        app.state.hub.publish('scrape', {'imported': dict(added=0, duplicates=2, invalid=0, ids=[])})
                                        expect(tray).to_have_attribute('data-phase', 'done')
                                        expect(state).to_contain_text('Saved posts imported')
                                    self.assertEqual(errors, [])
                                finally:
                                    context.close()
                    finally:
                        browser.close()
            finally:
                server.should_exit = True
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
