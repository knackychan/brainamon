"""Bundled legal documents in the built UI, using only a synthetic library and browser profile."""
import importlib.util
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
from tests.phone_groups import open_group  # noqa: E402  (About is a group on the phone's Settings, projects/phone-settings)
WEB_DIST = ROOT / 'web/dist'
DOCUMENTS = (
    ('Privacy policy', 'mobile-shell/store/privacy-policy.md'),
    ('Software license', 'LICENSE'),
    ('Third-party notices', 'THIRD_PARTY_NOTICES.md'),
)


@unittest.skipUnless(importlib.util.find_spec('playwright') and (WEB_DIST / 'index.html').is_file(),
                     'requires installed Playwright/Edge and the current production web build')
class LegalDocumentsBrowser(unittest.TestCase):
    def test_desktop_and_unpaired_phone_read_canonical_documents_offline(self):
        import uvicorn
        from playwright.sync_api import expect, sync_playwright
        from core.db import Database
        from library import ytdlp
        from server.app import create_app

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            data = Path(folder) / 'data'
            db = Database(data / 'content_manager.db')
            db.set_setting('onboard_answer', 'skip')
            db.close()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            app = create_app(data_dir=data, cloud_dir=Path(folder) / 'cloud', port=port, web_dist=WEB_DIST)
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                                   access_log=False, timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            with mock.patch.object(ytdlp, 'registry_get', return_value=''):
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                origin = f'http://127.0.0.1:{port}'
                screenshots = ROOT / 'build/marketplace-review'
                screenshots.mkdir(parents=True, exist_ok=True)
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(channel='msedge', headless=True,
                            args=['--disable-background-networking',
                                  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                        try:
                            for theme in ('light', 'dark'):
                                for surface, width in (('desktop', 1280), ('phone', 390)):
                                    with self.subTest(theme=theme, surface=surface):
                                        context = browser.new_context(viewport={'width': width, 'height': 900},
                                                                      color_scheme=theme, has_touch=surface == 'phone', locale='en-US')
                                        context.add_init_script("localStorage.setItem('bp-lang','en')")
                                        external = []

                                        def route(request):
                                            if request.request.url.startswith(origin + '/'):
                                                request.continue_()
                                            else:
                                                external.append(request.request.url.split('?')[0])
                                                request.abort()

                                        context.route('**/*', route)
                                        page = context.new_page()
                                        try:
                                            path = '/' if surface == 'desktop' else '/mobile.html#/more'
                                            if surface == 'desktop':
                                                path += '#cm-auth=' + app.state.api_token
                                            try:
                                                page.goto(origin + path, wait_until='domcontentloaded')
                                            except Exception:
                                                raise AssertionError('Synthetic UI bootstrap failed; credential URL omitted') from None
                                            if surface == 'desktop':
                                                page.get_by_role('button', name='Brainamon menu').click()
                                                page.get_by_role('menuitem', name='About Brainamon').click()
                                                dialog = page.get_by_role('dialog', name='About Brainamon')
                                                expect(dialog).to_be_visible()
                                                dialog.locator('[data-wclose]').focus()
                                                page.keyboard.press('Tab')
                                                expect(dialog.get_by_role('link', name='Get the Android app on Google Play')).to_be_focused()
                                                page.keyboard.press('Tab')
                                                expect(dialog.get_by_role('link', name='Support it on Ko-fi')).to_be_focused()
                                                page.keyboard.press('Tab')
                                                expect(dialog.get_by_role('link', name='me@fredtomas.com')).to_be_focused()
                                                page.keyboard.press('Tab')
                                                expect(dialog.locator('summary').first).to_be_focused()
                                            else:
                                                expect(open_group(page, 'About').get_by_role('heading', name='Privacy and licenses')).to_be_visible()
                                                self.assertEqual(page.evaluate("sessionStorage.getItem('cm-auth')"), None)
                                            legal = page.locator('.legal-documents')
                                            expect(legal).to_be_visible()
                                            expect(legal.get_by_role('link', name='me@fredtomas.com')).to_have_attribute('href', 'mailto:me@fredtomas.com')
                                            self.assertEqual(legal.locator('summary').all_text_contents(),
                                                             [label for label, _ in DOCUMENTS])
                                            context.set_offline(True)
                                            for i, (label, source) in enumerate(DOCUMENTS):
                                                summary = legal.locator('summary').nth(i)
                                                summary.focus()
                                                page.keyboard.press('Enter')
                                                text = legal.locator('pre').nth(i)
                                                expect(text).to_be_visible()
                                                expect(text).to_have_attribute('lang', 'en')
                                                self.assertEqual(text.text_content().replace('\r\n', '\n'),
                                                                 (ROOT / source).read_text(encoding='utf-8'))
                                                self.assertTrue(text.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
                                                self.assertEqual(text.evaluate('(e) => getComputedStyle(e).whiteSpace'), 'pre-wrap')
                                                page.keyboard.press('Space')
                                                expect(text).not_to_be_visible()
                                            legal.locator('summary').first.focus()
                                            if surface == 'phone':
                                                legal.locator('summary').first.tap()
                                            else:
                                                page.keyboard.press('Enter')
                                            expect(legal.locator('pre').first).to_be_visible()
                                            colors = legal.locator('pre').first.evaluate("""e => {
                                                const rgb = c => c.match(/[\\d.]+/g).map(Number);
                                                const foreground = rgb(getComputedStyle(e).color);
                                                for (let n = e; n; n = n.parentElement) {
                                                    const bg = rgb(getComputedStyle(n).backgroundColor);
                                                    if (bg.length === 3 || bg[3] === 1) return [foreground, bg];
                                                }
                                                throw new Error('No opaque reader background');
                                            }""")
                                            def luminance(rgb):
                                                linear = [v / 255 / 12.92 if v / 255 <= .04045 else
                                                          ((v / 255 + .055) / 1.055) ** 2.4 for v in rgb[:3]]
                                                return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
                                            values = sorted(luminance(color) for color in colors)
                                            contrast = (values[1] + .05) / (values[0] + .05)
                                            self.assertGreaterEqual(contrast, 4.5)
                                            print(f'{surface} {theme}: legal reader contrast {contrast:.2f}:1')
                                            legal.locator('summary').first.evaluate('(e) => e.scrollIntoView({block: "start"})')
                                            page.screenshot(path=str(screenshots / f'{surface}-{theme}-privacy.png'))
                                            page.set_viewport_size({'width': width // 2, 'height': 900})
                                            self.assertTrue(legal.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'),
                                                            'Legal documents overflow at 200% equivalent width')
                                            self.assertTrue(legal.locator('pre').first.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
                                            self.assertEqual(external, [])
                                            if surface == 'desktop' and theme == 'light':
                                                context.set_offline(False)
                                                page.set_viewport_size({'width': width, 'height': 900})
                                                dialog.locator('[data-wclose]').click()
                                                page.keyboard.press('Control+Comma')
                                                page.locator('#set-tai').click()
                                                page.locator('#set-panel').get_by_role('button', name='Turn on Wiskit', exact=True).click()
                                                key_form = page.get_by_role('dialog', name='Turn on Wiskit')
                                                expect(key_form).to_be_visible()
                                                page.screenshot(path=str(screenshots / 'desktop-light-ai-key.png'))
                                                key_form.locator('[data-wclose]').click()
                                                page.get_by_role('dialog', name='Settings', exact=True).locator('[data-wclose]').click()
                                                page.get_by_role('button', name='File', exact=True).click()
                                                page.get_by_role('menuitem', name='Add to Brainamon').click()
                                                capture = page.get_by_role('dialog', name='Add to Brainamon', exact=True)
                                                image_notice = capture.get_by_text('Reading a picture sends it', exact=False)
                                                expect(image_notice).to_be_visible()
                                                self.assertTrue(image_notice.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
                                                page.screenshot(path=str(screenshots / 'desktop-light-capture.png'))
                                                capture.locator('[data-wclose]').click()
                                            elif surface == 'phone' and theme == 'light':
                                                context.set_offline(False)
                                                page.set_viewport_size({'width': width, 'height': 900})
                                                page.evaluate("location.hash = '#/cap'")
                                                self.assertEqual(page.locator('.m-cap-dock').get_by_text('PDFs are read as soon as you add them', exact=False).count(), 0)
                                                page.get_by_role('button', name='More info: Adding content', exact=True).click()
                                                help_dialog = page.get_by_role('dialog', name='Adding content', exact=True)
                                                expect(help_dialog).to_be_visible()
                                                notice = help_dialog.get_by_text('PDFs are read as soon as you add them', exact=False)
                                                expect(notice).to_be_visible()
                                                self.assertTrue(notice.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
                                                page.screenshot(path=str(screenshots / 'phone-light-capture.png'))
                                        finally:
                                            context.close()
                        finally:
                            browser.close()
                finally:
                    server.should_exit = True
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
