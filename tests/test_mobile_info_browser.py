"""Mobile help uses synthetic phone storage and local Vite; no accounts or library data."""
import base64
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'build/mobile-info-review'
RAW = bytes([17]) * 32
PAIR = dict(v=2, k=base64.urlsafe_b64encode(RAW).decode().rstrip('='),
            f=hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12],
            c='', e='', ai={}, at=0, solo=True)


@contextmanager
def mobile_browser():
    from playwright.sync_api import sync_playwright

    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-mobile-ui-') as folder:
        with open(Path(folder) / 'vite.log', 'w') as log:
            proc = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port)],
                                    cwd=ROOT / 'web', stdout=log, stderr=log,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                base = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        urlopen(base + '/src/mobile/main.ts', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError('Vite did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge', headless=True)
                    try:
                        yield browser, base
                    finally:
                        browser.close()
            finally:
                proc.terminate()
                proc.wait(timeout=15)


@contextmanager
def synthetic_phone(browser, base, width, height, theme, *, pair=PAIR, language='en'):
    context = browser.new_context(viewport={'width': width, 'height': height},
                                  color_scheme=theme, is_mobile=True, has_touch=True, locale='en-US')
    errors = []

    def route(request):
        url = request.request.url
        if url == base + '/thumbs-proxy.js':
            request.fulfill(path=ROOT / 'web/public/thumbs-proxy.js')
        elif url.startswith(base + '/cards/'):
            path = ROOT / 'design/card-designs' / urlparse(url).path.removeprefix('/cards/')
            request.fulfill(path=path)
        elif url.startswith(base + '/'):
            request.continue_()
        else:
            request.abort()

    context.route('**/*', route)
    language_seed = "localStorage.setItem('bp-lang'," + json.dumps(language) + ");" if language is not None else ''
    context.add_init_script(language_seed + "localStorage.setItem('bp-wifi','off');localStorage.setItem('bp-pair'," +
                            json.dumps(json.dumps(pair)) + ');')
    page = context.new_page()
    page.set_default_timeout(10000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        yield page, errors
    finally:
        context.close()


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class MobileInfoBrowser(unittest.TestCase):
    def test_add_import_and_icon_actions(self):
        from playwright.sync_api import expect

        ART.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width, theme in ((320, 'light'), (320, 'dark'), (390, 'light'), (390, 'dark')):
                with self.subTest(width=width, theme=theme), synthetic_phone(browser, base, width, 844, theme) as (page, errors):
                    page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    content = page.locator('#cap-text')
                    expect(content).to_be_visible()
                    expect(page.get_by_role('link', name='Import saved posts', exact=True)).to_be_visible()     # the empty draft's one hint
                    content.fill('Synthetic draft retained when opening import')
                    content.blur()
                    page.screenshot(path=str(ART / f'add-import-{theme}-{width}.png'))
                    actions = page.locator('.m-cap-actions')
                    for name in ('Photo', 'File', 'Paste'):
                        button = actions.get_by_role('button', name=name, exact=True)
                        expect(button).to_be_visible()
                        self.assertEqual(button.inner_text().strip(), '')
                        expect(button.locator('svg')).to_have_count(1)
                        bounds = button.bounding_box()
                        self.assertGreaterEqual(bounds['width'], 44)
                        self.assertGreaterEqual(bounds['height'], 44)
                    expect(actions.get_by_role('button', name='More', exact=True)).to_have_count(0)
                    page.get_by_role('button', name='Import & drafts', exact=True).click()
                    tools = page.get_by_role('dialog', name='Import & drafts', exact=True)
                    expect(tools).to_be_visible()
                    expect(tools.get_by_label('Comment', exact=False)).to_have_count(0)     # the comment is on the recap (projects/phone-add-confirm)
                    expect(tools).not_to_contain_text('Outbox')
                    page.keyboard.press('Escape')
                    expect(tools).not_to_be_visible()
                    expect(page.get_by_role('link', name='Import saved posts', exact=True)).to_have_count(0)     # a draft is open: the hint is gone
                    page.get_by_role('button', name='Import & drafts', exact=True).click()
                    tools.get_by_role('link', name='Import saved posts', exact=True).click()                     # ... and the panel keeps the way in
                    expect(page).to_have_url(base + '/mobile.html#/import')
                    expect(page.locator('.m-ws')).to_have_text('Import')
                    expect(page.locator('.m-sheet-layer.m-vt-cap')).to_be_visible()     # Import opens inside the Add sheet
                    self.assertNotEqual(page.locator('.m-sheet-body').evaluate('e => getComputedStyle(e).overflowY'), 'hidden')
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/cap')
                    expect(page.locator('#cap-text')).to_have_value('Synthetic draft retained when opening import')
                    page.evaluate("location.hash = '#/more'")
                    expect(page.locator('.m-page-keys .m-ws')).to_have_text('Settings')
                    expect(page.get_by_role('link', name='Import saved posts', exact=True)).to_have_count(0)
                    expect(page.get_by_text('Saved posts from Instagram', exact=True)).to_have_count(0)
                    self.assertEqual(errors, [])

    def test_help_stays_compact_accessible_and_inside_the_viewport(self):
        from playwright.sync_api import expect

        ART.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width, height in ((320, 720), (360, 800), (390, 844), (320, 480), (568, 320)):
                for theme in ('light', 'dark'):
                    with self.subTest(width=width, height=height, theme=theme), synthetic_phone(browser, base, width, height, theme) as (page, errors):
                        page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        trigger = page.get_by_role('button', name='More info: Adding content', exact=True)
                        expect(trigger).to_be_visible()
                        expect(page.locator('.m-info-dialog[open]')).to_have_count(0)
                        expect(page.locator('.m-cap-dock')).not_to_contain_text('PDFs are read')
                        expect(page.locator('.m-cap-editor')).not_to_contain_text('AI provider charges')
                        self.assertGreaterEqual(page.locator('#cap-text').bounding_box()['height'], 36)
                        self.assertLess(page.locator('.m-cap-dock').bounding_box()['height'], 190)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        for selector in ('.m-cap-editor', '.m-cap-heading', '.m-cap-heading .m-info'):
                            bounds = page.locator(selector).bounding_box()
                            self.assertGreaterEqual(bounds['x'], 0, selector)
                            self.assertLessEqual(bounds['x'] + bounds['width'], width, selector)
                        if height <= 420:
                            save = page.get_by_role('button', name='Save', exact=True)
                            save.scroll_into_view_if_needed()
                            expect(save).to_be_in_viewport()
                        if (width, height, theme) == (390, 844, 'dark'):
                            page.screenshot(path=str(ART / 'capture-dark-390.png'))

                        trigger.click()
                        dialog = page.get_by_role('dialog', name='Adding content', exact=True)
                        expect(dialog).to_be_visible()
                        expect(dialog).to_contain_text('complete PDF to your AI provider')
                        expect(dialog).to_contain_text('direct-PC mode reads it on the PC')
                        expect(dialog).to_contain_text('AI provider charges apply separately')
                        self.assert_dialog_fits(page, dialog, width, height)
                        close = dialog.get_by_role('button', name='Close', exact=True)
                        expect(close).to_be_focused()
                        for key in ('Tab', 'Shift+Tab'):
                            page.keyboard.press(key)
                            # Native dialogs also let Tab reach browser chrome (reported as body).
                            self.assertTrue(dialog.evaluate('e => e.contains(document.activeElement) || document.activeElement === document.body'), key)
                        expect(close).to_be_focused()
                        page.locator('#cap-text').evaluate('e => e.focus()')
                        expect(close).to_be_focused()
                        page.keyboard.press('Escape')
                        expect(dialog).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        trigger.click()
                        close.click()
                        expect(dialog).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        trigger.click()
                        page.mouse.click(3, 3)
                        expect(dialog).not_to_be_visible()
                        expect(trigger).to_be_focused()

                        # These are real menu routes, including help portalled out of section headings.
                        menus = (('#/more', 'Sync'), ('#/backup', 'Google Drive backup'),
                                 ('#/recover', 'How recovery works'), ('#/import', 'Instagram: Export'))
                        for route_hash, title in menus:
                            page.evaluate('(hash) => { location.hash = hash }', route_hash)
                            if route_hash == '#/more':               # a group's (i) shows while the group is open (projects/phone-settings)
                                page.locator('a[href="#/more/sync"]').click()
                            menu_trigger = page.get_by_role('button', name=f'More info: {title}', exact=True)
                            expect(menu_trigger).to_be_visible()
                            expect(page.locator('.m-info-dialog[open]')).to_have_count(0)
                            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                            if (route_hash, width, height, theme) == ('#/more', 390, 844, 'dark'):
                                page.locator('.m-main').evaluate('e => { e.scrollTop = 0 }')
                                page.screenshot(path=str(ART / 'more-dark-390.png'))
                            menu_trigger.click()
                            menu_dialog = page.get_by_role('dialog', name=title, exact=True)
                            expect(menu_dialog).to_be_visible()
                            self.assert_dialog_fits(page, menu_dialog, width, height)
                            if route_hash == '#/recover':
                                body = menu_dialog.locator('.m-info-body')
                                if height <= 480:
                                    self.assertTrue(body.evaluate('e => e.scrollHeight > e.clientHeight'))
                                body.evaluate('e => { e.scrollTop = e.scrollHeight }')
                                expect(menu_dialog.get_by_role('button', name='Close', exact=True)).to_be_in_viewport()
                                if (width, height, theme) == (320, 480, 'light'):
                                    page.screenshot(path=str(ART / 'recovery-help-light-320.png'))
                            page.evaluate("location.hash = '#/cap'")
                            expect(menu_dialog).to_have_count(0)
                            expect(page.locator('.m-info-dialog[open]')).to_have_count(0)
                            expect(page.get_by_role('button', name='More info: Adding content', exact=True)).to_be_enabled()
                        self.assertEqual(errors, [])

    def assert_dialog_fits(self, page, dialog, width, height):
        bounds = dialog.bounding_box()
        self.assertGreaterEqual(bounds['x'], 15)
        self.assertGreaterEqual(bounds['y'], 15)
        self.assertLessEqual(bounds['x'] + bounds['width'], width - 15)
        self.assertLessEqual(bounds['y'] + bounds['height'], height - 15)
        self.assertTrue(dialog.evaluate('e => e.scrollWidth <= e.clientWidth'))
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))


if __name__ == '__main__':
    unittest.main()
