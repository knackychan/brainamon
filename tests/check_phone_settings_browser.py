"""The phone's Settings, Backup & phones and Recover a library after projects/phone-settings (spec
docs/superpowers/specs/2026-11-07-phone-settings-design.md, Checks): the top keys, the group rows, one open at a time,
the row that stays under the finger, a link into a group, Clear's two taps, and the round Back. Vite only, a synthetic
phone used without a PC and not signed in to Google (every https request is refused), no Drive, no AI call, no data
folder. Photographs at 360 x 780 and 320 x 780 in light and dark into local/phone-settings/.
Run: py tests/check_phone_settings_browser.py
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.phone_groups import group, open_group, row_line  # noqa: E402

ART = ROOT / 'local/phone-settings'
RAW = bytes([12]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
PAIR = dict(v=2, k=KEY, f=FP, c='', e='', ai={}, at=0, solo=True)
SETTLED = "async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }"
ROWS = ['Sync', 'Your phone', 'Wiskit on this phone', 'Obsidian', 'Storage', 'Look', 'About']


def fits(page):
    return page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')


def uncut(page):
    """The state lines that do not fit their row (one line, an ellipsis when cut)."""
    return page.evaluate("""() => [...document.querySelectorAll('.m-group-words > small')]
      .filter(s => s.offsetParent && s.scrollWidth > s.clientWidth + 0.5).map(s => s.textContent)""")


def small_targets(page):
    """Keys, links and disclosures in the page under 44 px (the round top keys are 36 px, outside .m-pad)."""
    return page.evaluate("""() => [...document.querySelectorAll('.m-pad button, .m-pad a, .m-pad summary')]
      .filter(e => e.offsetParent).map(e => [e.textContent.trim().slice(0, 30), e.getBoundingClientRect().height])
      .filter(t => t[1] < 43.5)""")


def shoot(page, name):
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        assert fits(page), (name, theme)
        page.screenshot(path=str(ART / f'{name}-{theme}.png'))
    page.evaluate("document.documentElement.dataset.theme = 'light'")


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-settings-') as folder:
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
                cards = {name: ROOT / 'design/card-designs' / name for name in
                         ('cards.css', 'engine.js', 'full-art-v2/fa2.css', 'full-art-v2/fa2.js')}
                errors, passed = [], []
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, channel='msedge')

                    def phone_page(width, paired=True):
                        ctx = browser.new_context(viewport={'width': width, 'height': 780}, is_mobile=True, has_touch=True, locale='en-US')
                        ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                        ctx.route('https://**/*', lambda r: r.abort())
                        ctx.route('**/api/**', lambda r: r.abort())
                        ctx.route(base + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                        seed = {'bp-pair': json.dumps(PAIR)} if paired else {}
                        ctx.add_init_script("localStorage.setItem('bp-wifi','off'); if (!sessionStorage.getItem('fixture')) {"
                                            "sessionStorage.setItem('fixture','1'); for (const [k, v] of Object.entries(" +
                                            json.dumps(seed) + ")) localStorage.setItem(k, v) }")
                        page = ctx.new_page()
                        page.set_default_timeout(15000)
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        return ctx, page

                    for width in (360, 320):
                        # 1. the first screen: the keys, the hero, every row in one screen, no line cut
                        ctx, page = phone_page(width)
                        page.goto(base + '/mobile.html#/more')
                        page.wait_for_function(SETTLED)
                        expect(page.locator('.m-page-keys .m-ws')).to_have_text('Settings')
                        expect(page.get_by_role('button', name='Back', exact=True)).to_have_count(1)
                        assert page.locator('.m-pad > *').first.get_attribute('id') == 'm-status'
                        expect(page.locator('#m-status').get_by_role('link', name='Backup & phones')).to_be_visible()
                        titles = page.locator('.m-group-words > b').all_inner_texts()
                        assert titles == ROWS, titles
                        bottom = page.evaluate("() => Math.max(...[...document.querySelectorAll('.m-group-row')].map(r => r.getBoundingClientRect().bottom))")
                        assert bottom <= 780, (width, bottom)
                        assert not uncut(page), (width, uncut(page))
                        assert not small_targets(page), small_targets(page)
                        assert page.locator('.m-group-row[aria-expanded="true"]').count() == 0
                        shoot(page, f'settings-{width}')

                        # 2. one group at a time; the tapped row stays where it was when the group above closes
                        storage = open_group(page, 'Storage')
                        expect(storage.get_by_text('Keep automatically', exact=True)).to_be_visible()
                        expect(group(page, 'Wiskit on this phone').get_by_role('button', name='More info: Wiskit on this phone')).to_have_count(0)
                        shoot(page, f'settings-{width}-storage')
                        look_row = group(page, 'Look').locator('button.m-group-row')
                        before = look_row.bounding_box()['y']
                        look_row.click()
                        expect(look_row).to_have_attribute('aria-expanded', 'true')
                        expect(storage.locator('button.m-group-row')).to_have_attribute('aria-expanded', 'false')
                        page.wait_for_timeout(400)                  # a smooth scroll that brings the panel up has ended
                        after = look_row.bounding_box()['y']
                        assert after <= before + 1 and after >= 56 - 1, (width, before, after)
                        expect(group(page, 'Look').get_by_role('button', name='More info: Appearance')).to_be_visible()

                        # 3. Clear asks twice, and forgets the first tap when Storage closes
                        storage = open_group(page, 'Storage')
                        clear = storage.get_by_role('button', name='Clear', exact=True)
                        clear.click()
                        expect(storage.get_by_role('button', name='Sure? Clear', exact=True)).to_be_visible()
                        storage.locator('button.m-group-row').click()
                        storage = open_group(page, 'Storage')
                        expect(storage.get_by_role('button', name='Clear', exact=True)).to_be_visible()

                        # 4. a link into a group: Wiskit's Add a key (openMoreBox('m-ai')) from the Wiskit sheet opens
                        # Wiskit on this phone, brings it under the keys, and Back returns to the sheet
                        page.evaluate("location.hash = '#/jv'")
                        expect(page).to_have_url(base + '/mobile.html#/jv')
                        page.evaluate("async () => { const { openMoreBox } = await import('/src/mobile/onboard.svelte.ts'); await openMoreBox('m-ai') }")
                        expect(page).to_have_url(base + '/mobile.html#/more')
                        ai = page.locator('#m-ai')
                        expect(ai.locator('button.m-group-row')).to_have_attribute('aria-expanded', 'true')
                        expect(ai.get_by_label('OpenAI API key', exact=True)).to_be_visible()
                        page.wait_for_timeout(600)
                        top = ai.bounding_box()['y']
                        assert 0 <= top <= 780 - 52, (width, top)
                        assert page.evaluate("() => document.activeElement?.closest('#m-ai') !== null")
                        page.get_by_role('button', name='Back', exact=True).click()
                        expect(page).to_have_url(base + '/mobile.html#/jv')

                        # 5. Backup & phones and Recover: their keys, (i) and Back one page at a time
                        page.evaluate("location.hash = '#/more'")
                        page.locator('#m-status').get_by_role('link', name='Backup & phones').click()
                        expect(page).to_have_url(base + '/mobile.html#/backup')
                        expect(page.locator('.m-page-keys .m-ws')).to_have_text('Backup')
                        expect(page.locator('.m-page-keys').get_by_role('button', name='More info: Google Drive backup')).to_be_visible()
                        ids = page.evaluate("() => [...document.querySelectorAll('.m-pad > .m-box')].map(e => e.id)")
                        assert ids == ['m-backup-status', 'm-conn', 'm-phone', 'm-recovery'], ids
                        expect(row_line(page, 'Google account')).to_have_text('Sign in')
                        expect(row_line(page, 'This phone')).to_have_text('All backed up · no PC paired')
                        expect(row_line(page, 'Recovery')).to_have_text('Not set up')
                        assert not uncut(page), uncut(page)
                        assert not small_targets(page), small_targets(page)
                        shoot(page, f'backup-{width}')
                        recovery = open_group(page, 'Recovery')
                        expect(recovery.locator('.m-status')).to_have_count(0)          # the row says Not set up; not again
                        shoot(page, f'backup-{width}-recovery')
                        recovery.get_by_role('link', name='Recover a library…', exact=True).click()
                        expect(page).to_have_url(base + '/mobile.html#/recover')
                        expect(page.locator('.m-page-keys .m-ws')).to_have_text('Recover')
                        expect(page.locator('.m-page-keys').get_by_role('button', name='More info: How recovery works')).to_be_visible()
                        expect(page.get_by_role('group', name='Unlock with')).to_be_visible()
                        assert not small_targets(page), small_targets(page)
                        shoot(page, f'recover-{width}')
                        page.get_by_role('button', name='Back', exact=True).click()
                        expect(page).to_have_url(base + '/mobile.html#/backup')
                        page.get_by_role('button', name='Back', exact=True).click()
                        expect(page).to_have_url(base + '/mobile.html#/more')
                        ctx.close()

                    # 6. a cold start has nothing behind: Back takes the parent
                    ctx, page = phone_page(360)
                    page.goto(base + '/mobile.html#/more')
                    page.wait_for_function(SETTLED)
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/lib')
                    ctx.close()
                    # Parent fallbacks replace the entry, so successive Back taps never return to the child.
                    for start in ('#/backup', '#/recover'):
                        for reloaded, no_navigation in ((False, False), (True, False), (False, True)):
                            ctx, page = phone_page(360)
                            if no_navigation:
                                page.add_init_script("Object.defineProperty(window, 'navigation', { value: undefined })")
                            page.goto(base + '/mobile.html' + ('#/more' if reloaded else start))
                            page.wait_for_function(SETTLED)
                            expect(page.locator('.m-page-keys')).to_be_visible()
                            if reloaded:
                                page.evaluate('(hash) => { location.hash = hash }', start)
                                expect(page.locator('.m-page-keys .m-ws')).to_have_text('Backup' if start == '#/backup' else 'Recover')
                                page.reload()
                                page.wait_for_function(SETTLED)
                            parents = ('#/backup', '#/more', '#/lib') if start == '#/recover' else ('#/more', '#/lib')
                            for parent in parents:
                                page.locator('.m-page-keys').get_by_role('button', name='Back', exact=True).click()
                                expect(page).to_have_url(base + '/mobile.html' + parent)
                            ctx.close()
                    # a browser with no pairing has no Recover a library: #/recover is Settings itself
                    ctx, page = phone_page(360, paired=False)
                    page.goto(base + '/mobile.html#/recover')
                    page.wait_for_function(SETTLED)
                    expect(page.locator('.m-page-keys .m-ws')).to_have_text('Settings')
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/lib')
                    ctx.close()

                    # 7. wider screens: no sideways scroll
                    for width in (390, 568):
                        ctx, page = phone_page(width)
                        page.goto(base + '/mobile.html#/more')
                        page.wait_for_function(SETTLED)
                        assert fits(page), width
                        ctx.close()
                    browser.close()
                assert not errors, errors
                print(json.dumps({'screenshots': str(ART), 'page_errors': errors}))
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == '__main__':
    main()
