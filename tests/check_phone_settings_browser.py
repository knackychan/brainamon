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
from tests.phone_pages import group, open_group, row_line  # noqa: E402

ART = ROOT / 'local/phone-settings'
RAW = bytes([12]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
PAIR = dict(v=2, k=KEY, f=FP, c='', e='', ai={}, at=0, solo=True)
SETTLED = "async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }"
ROWS = ['Backup & phones', 'Sync', 'Wiskit on this phone', 'Obsidian', 'Storage', 'Look', 'About']


def fits(page):
    return page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')


def uncut(page):
    """The state lines that do not fit their row (one line, an ellipsis when cut)."""
    return page.evaluate("""() => [...document.querySelectorAll('.m-group-words > small')]
      .filter(s => s.offsetParent && s.scrollWidth > s.clientWidth + 0.5).map(s => s.textContent)""")


def small_targets(page):
    """Keys, links and disclosures in the page under 44 px (the round top keys are 36 px, outside .m-pad)."""
    return page.evaluate("""() => [...document.querySelectorAll('.m-pad button, .m-pad a, .m-pad summary, .m-pad input[type=range]')]
      .filter(e => e.offsetParent).map(e => [e.textContent.trim().slice(0, 30), e.getBoundingClientRect().height, e.getBoundingClientRect().width])
      .filter(t => t[1] < 43.5 || t[2] < 43.5)""")


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

                    def phone_page(width, paired=True, solo=True):
                        ctx = browser.new_context(viewport={'width': width, 'height': 780}, is_mobile=True, has_touch=True, locale='en-US')
                        ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                        ctx.route('https://**/*', lambda r: r.abort())
                        ctx.route('**/api/**', lambda r: r.abort())
                        ctx.route(base + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                        seed = {'bp-pair': json.dumps(dict(PAIR, solo=solo))} if paired else {}
                        ctx.add_init_script("localStorage.setItem('bp-wifi','off'); if (!sessionStorage.getItem('fixture')) {"
                                            "sessionStorage.setItem('fixture','1'); for (const [k, v] of Object.entries(" +
                                            json.dumps(seed) + ")) localStorage.setItem(k, v) }")
                        page = ctx.new_page()
                        page.set_default_timeout(15000)
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        return ctx, page

                    for width in (360, 320):
                        ctx, page = phone_page(width)
                        page.goto(base + '/mobile.html#/more')
                        page.wait_for_function(SETTLED)
                        expect(page.locator('.m-page-keys .m-ws')).to_have_text('Settings')
                        expect(page.get_by_role('button', name='Back', exact=True)).to_have_count(1)
                        assert page.locator('.m-group-words > b').all_inner_texts() == ROWS
                        expect(page.locator('#m-status')).to_contain_text('Status')
                        assert page.locator('.m-group-row[aria-expanded]').count() == 0
                        assert not small_targets(page), small_targets(page)
                        bottom = page.locator('a[href="#/more/about"]').bounding_box()
                        assert width != 360 or bottom['y'] + bottom['height'] <= 780, bottom
                        shoot(page, f'settings-{width}')

                        # Every hub row opens its own page, with its own Back and no cut words.
                        for title, route in [('Sync', 'sync'), ('Wiskit on this phone', 'wiskit'), ('Obsidian', 'obsidian'), ('Storage', 'storage'), ('Look', 'look'), ('About', 'about')]:
                            page.locator(f'a[href="#/more/{route}"]').click()
                            expect(page).to_have_url(base + '/mobile.html#/more/' + route)
                            expect(page.locator('.m-page:visible h1')).to_have_text(title)
                            assert fits(page), (width, route)
                            assert not small_targets(page), (route, small_targets(page))
                            shoot(page, f'{route}-{width}')
                            page.get_by_role('button', name='Back', exact=True).click()
                            expect(page).to_have_url(base + '/mobile.html#/more')

                        # Clear keeps its two taps and resets when the page is left.
                        page.locator('a[href="#/more/storage"]').click()
                        page.get_by_text('Show more', exact=True).click()
                        assert not small_targets(page), small_targets(page)
                        page.get_by_role('button', name='Clear', exact=True).click()
                        expect(page.get_by_role('button', name='Sure? Clear', exact=True)).to_be_visible()
                        page.get_by_role('button', name='Back', exact=True).click()
                        page.locator('a[href="#/more/storage"]').click()
                        page.get_by_text('Show more', exact=True).click()
                        expect(page.get_by_role('button', name='Clear', exact=True)).to_be_visible()

                        # Wiskit's Add a key lands on the keys card and returns to its sheet.
                        page.evaluate("location.hash = '#/jv'")
                        expect(page).to_have_url(base + '/mobile.html#/jv')
                        page.evaluate("async () => { const { openMoreBox } = await import('/src/mobile/onboard.svelte.ts'); await openMoreBox('m-ai') }")
                        expect(page).to_have_url(base + '/mobile.html#/more/wiskit')
                        expect(page.locator('#m-ai').get_by_label('OpenAI API key', exact=True)).to_be_visible()
                        assert page.evaluate("() => document.activeElement?.closest('#m-ai') !== null")
                        page.get_by_role('button', name='Back', exact=True).click()
                        expect(page).to_have_url(base + '/mobile.html#/jv')

                        page.evaluate("location.hash = '#/more'")
                        page.locator('a[href="#/backup"]').click()
                        expect(page.locator('.m-page:visible h1')).to_have_text('Backup & phones')
                        expect(page.locator('#m-phone')).to_contain_text('Backup off')
                        expect(page.locator('#m-recovery .m-steps li')).to_have_count(3)
                        assert not small_targets(page), small_targets(page)
                        shoot(page, f'backup-{width}')
                        page.locator('#m-phone').get_by_text('Show more', exact=True).click()
                        page.get_by_role('button', name='Remove', exact=True).click()
                        expect(page.get_by_role('button', name='Sure? Remove', exact=True)).to_be_visible()
                        page.locator('#m-recovery').get_by_role('link', name='Recover a library…', exact=True).click()
                        expect(page.locator('.m-page-keys .m-ws')).to_have_text('Recover')
                        expect(page.get_by_role('group', name='Unlock with')).to_be_visible()
                        assert not small_targets(page), small_targets(page)
                        shoot(page, f'recover-{width}')
                        page.get_by_role('button', name='Back', exact=True).click()
                        expect(page).to_have_url(base + '/mobile.html#/backup')

                        # Saved work disables conflicting controls and explains the gate on each page.
                        page.evaluate("""async () => {
                          const N = await import('/src/mobile/native.ts'), P = await import('/src/mobile/mirror/pairing.ts'), S = await import('/src/mobile/state.svelte.ts')
                          N.secrets.set('bp-gtoken', JSON.stringify({access:'synthetic',exp:Date.now()+3600000}))
                          P.confirmAccount(S.mirrorSource.pair,'sample@example.com'); await N.secretsSaved(); S.phone.tokenAt++
                          S.phone.pend = {...S.phone.pend,unsent:2}
                          const {rec} = await import('/src/mobile/recovery.svelte.ts'); rec.mode='setup'
                        }""")
                        expect(page.get_by_role('button', name='Generate passphrase', exact=True)).to_be_enabled()
                        page.evaluate("""async () => {
                          const {backup} = await import('/src/mobile/backup.svelte.ts')
                          backup.task = {kind:'delete',phase:'delete',account:'sample@example.com',prefix:'solo-synthetic',owner:'synthetic',files:[],removed:0,paused:true}
                        }""")
                        expect(page.get_by_role('button', name='Generate passphrase', exact=True)).to_be_disabled()
                        expect(page.locator('#m-phone').get_by_role('button', name='Send now', exact=True)).to_be_disabled()
                        expect(page.locator('#m-phone')).to_contain_text('Finish the saved backup task first.')
                        page.evaluate("location.hash = '#/more/sync'")
                        expect(page.get_by_role('button', name='Sync now', exact=True)).to_be_disabled()
                        expect(page.get_by_role('button', name='Pause sync', exact=True)).to_be_enabled()
                        page.evaluate("location.hash = '#/recover'")
                        expect(page.get_by_role('button', name='Find recovery setups', exact=True)).to_be_disabled()
                        expect(page.locator('#m-recover')).to_contain_text('Finish the saved backup task')
                        page.evaluate("location.hash = '#/backup/manage'")
                        expect(page.locator('.m-page:visible h1')).to_have_text('Saved backup task')
                        expect(page.locator('.m-steps li')).to_have_count(2)
                        shoot(page, f'manage-{width}')
                        ctx.close()

                    ctx, page = phone_page(360, solo=False)
                    page.goto(base + '/mobile.html#/backup')
                    page.wait_for_function(SETTLED)
                    for paused in (False, True):
                        page.evaluate("""async paused => {
                          const {network} = await import('/src/mobile/network.svelte.ts')
                          network.online=false; network.manualPause=paused
                        }""", paused)
                        expect(page.locator('#m-pair-setup')).to_have_count(0)
                    page.evaluate("async()=>{const {openBackupBox}=await import('/src/mobile/onboard.svelte.ts');await openBackupBox('m-pair')}")
                    expect(page.locator('#m-pair')).to_be_visible()
                    expect(page.locator('#m-phone details.m-more-foot')).to_have_attribute('open','')
                    page.get_by_role('button', name='Unpair this phone', exact=True).click()
                    expect(page.get_by_role('button', name='Sure? Unpair', exact=True)).to_be_visible()
                    page.evaluate("async()=>{const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');m.dropPhoneRecord=()=>new Promise((resolve,reject)=>window.__failUnpair=()=>reject(Error('synthetic failure')))}")
                    page.get_by_role('button', name='Sure? Unpair', exact=True).click()
                    expect(page.get_by_role('button', name='Stopping cloud work…', exact=True)).to_be_disabled()
                    page.wait_for_function('()=>!!window.__failUnpair')
                    page.evaluate('window.__failUnpair()')
                    expect(page.get_by_role('button', name='Sure? Unpair', exact=True)).to_be_enabled()
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

                    ctx, page = phone_page(360, paired=False)
                    page.goto(base + '/mobile.html#/more/sync')
                    expect(page).to_have_url(base + '/mobile.html#/more')
                    expect(page.locator('a[href="#/more/sync"]')).to_have_count(0)
                    ctx.close()

                    # 7. wider screens: no sideways scroll
                    for width in (320, 360, 375, 390, 568):
                        ctx, page = phone_page(width)
                        page.goto(base + '/mobile.html#/more')
                        page.wait_for_function(SETTLED)
                        for route in ('more', 'more/sync', 'more/wiskit', 'more/obsidian', 'more/storage', 'more/look', 'more/about', 'backup', 'backup/manage', 'recover'):
                            page.evaluate('(route) => location.hash = "#/" + route', route)
                            expect(page.locator('.m-page-keys')).to_be_visible()
                            assert fits(page), (width, route)
                        ctx.close()
                    browser.close()
                assert not errors, errors
                print(json.dumps({'screenshots': str(ART), 'page_errors': errors}))
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == '__main__':
    main()
