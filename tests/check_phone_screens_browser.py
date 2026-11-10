"""The status card, Settings > Backup & phones, the owner line under the app bar and the lamp (docs/superpowers/plans/
2026-10-31-phone-backup-phones.md, sub-plan 04) in the phone page, at 360 px in light and dark: a synthetic pairing, a
mocked Google Drive that holds no access confirmation, synthetic Google tokens. No account, no real Drive, no data folder.
Run: py tests/check_phone_screens_browser.py
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
from tests.phone_groups import open_group, row_line  # noqa: E402  (the group rows, projects/phone-settings)
ART = ROOT / 'local/ui-blocks/shots/phone-screens'
RAW = bytes([9]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
PAIR = dict(v=2, k=KEY, f=FP, c='', e='sample@example.com', ai={}, at=0, l='A' * 122)
# a synthetic Google sign-in for the PC's account, the way the app keeps one (mirror/pairing.ts, native.ts secrets)
SIGN_IN = """async () => {
  const P = await import('/src/mobile/mirror/pairing.ts'), N = await import('/src/mobile/native.ts'), S = await import('/src/mobile/state.svelte.ts')
  N.secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
  P.confirmAccount(S.mirrorSource.pair, 'sample@example.com'); await N.secretsSaved()
  S.phone.tokenAt++; await S.refresh()
}"""
SETTLED = "async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }"


def targets(page, scope):
    """Every visible key, link and disclosure in `scope`, with its height (calm rule: 44 px)."""
    return page.evaluate("""(scope) => [...document.querySelectorAll(scope)].flatMap(s => [...s.querySelectorAll('button, a, summary')])
      .filter(e => e.offsetParent).map(e => [e.textContent.trim(), e.getBoundingClientRect().height])""", scope)


def tall(page, scope):
    small = [t for t in targets(page, scope) if t[1] < 43.5]
    assert not small, small


def fits(page):
    return page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')


def shoot(page, name):
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        assert fits(page), (name, theme)
        page.screenshot(path=str(ART / f'{name}-{theme}.png'), full_page=True)
    page.evaluate("document.documentElement.dataset.theme = 'light'")


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-screens-') as folder:
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
                errors, methods = [], []

                def drive(route):
                    methods.append(route.request.method)
                    if '/about?' in route.request.url:
                        route.fulfill(json={'user': {'emailAddress': 'sample@example.com'}})
                    else:
                        route.fulfill(json={'files': []})        # no access confirmation, no library

                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, channel='msedge')

                    def phone_page(init: str):
                        ctx = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True, locale='en-US')
                        ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                        ctx.route(base + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                        ctx.route('https://www.googleapis.com/**', drive)
                        ctx.add_init_script("localStorage.setItem('bp-wifi','off'); if (!sessionStorage.getItem('fixture')) {"
                                            "sessionStorage.setItem('fixture','1'); localStorage.setItem('bp-pair'," +
                                            json.dumps(json.dumps(PAIR)) + ');' + init + '}')
                        page = ctx.new_page()
                        page.set_default_timeout(10000)
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        return ctx, page

                    # 1. A new pairing, not connected to Google yet: the card, its heading, Backup & phones, Back
                    ctx, page = phone_page("sessionStorage.setItem('bp-pair-setup','1');")
                    page.goto(base + '/mobile.html#/more')
                    card = page.locator('#m-status')
                    expect(card.get_by_text('Connect Google Drive.', exact=True)).to_be_visible()
                    expect(card.get_by_role('button', name='Connect', exact=True)).to_have_class('m-btn pill pri')
                    assert card.get_by_text('Choose sample@example.com', exact=False).count() == 0   # the card never shows the detail
                    assert page.locator('.m-pad > *').first.get_attribute('id') == 'm-status'
                    for moved in ('#m-pair-setup', '#m-conn', '#m-recovery'):             # all on Backup & phones now
                        assert page.locator(moved).count() == 0, moved
                    tall(page, '#m-status')
                    shoot(page, 'more-connect')
                    card.get_by_role('link', name='Backup & phones').click()
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    expect(page.locator('.m-page-keys .m-ws')).to_have_text('Backup')
                    status = page.locator('#m-backup-status')
                    expect(status.get_by_text('Connect Google Drive.', exact=True)).to_be_visible()
                    expect(status.get_by_text('Choose sample@example.com, the account your PC backs up to.', exact=True)).to_be_visible()
                    assert page.get_by_role('button', name='Connect', exact=True).count() == 1     # the Status's key, not the row's too
                    expect(page.locator('#m-pair-setup').get_by_text('Finish connecting your PC', exact=True)).to_be_visible()
                    ids = page.evaluate("() => [...document.querySelectorAll('.m-pad > .m-box')].map(e => e.id)")
                    assert ids == ['m-backup-status', 'm-pair-setup', 'm-conn', 'm-phone', 'm-recovery'], ids
                    expect(row_line(page, 'This phone')).to_have_text('Phone browser · all sent')
                    expect(open_group(page, 'This phone').get_by_text('Phone browser', exact=True)).to_be_visible()
                    assert page.locator('#m-pair').get_by_role('button', name='Scan').count() == 0        # a browser pastes the link
                    assert page.locator('.m-strip').count() == 0
                    tall(page, '.m-pad')
                    shoot(page, 'backup-connect')
                    open_group(page, 'Recovery').get_by_role('button', name='Show', exact=True).click()
                    assert page.get_by_label('Recovery code', exact=True).input_value() == KEY
                    page.locator('#m-recovery').get_by_role('button', name='Hide', exact=True).click()
                    expect(page.get_by_label('Recovery code', exact=True)).to_have_count(0)
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/more')
                    ctx.close()

                    # 2. Access removed on the PC (this pairing had access an hour ago), signed in: the owner line, the lamp,
                    #    the Status, Unpair's first tap with unsent edits
                    seen = json.dumps(json.dumps({'f': FP, 'at': int(time.time() * 1000) - 3600000}))
                    ctx, page = phone_page(f"localStorage.setItem('bp-access',{seen});")
                    page.goto(base + '/mobile.html#/lib')
                    page.wait_for_function(SETTLED)
                    page.evaluate(SIGN_IN)
                    strip = page.locator('.m-strip-owner')
                    expect(strip).to_have_text("Backup & phones · This phone's access was removed on your PC.")
                    expect(page.locator('.m-sync-key')).to_have_attribute('aria-label', 'Drive · access removed')
                    assert strip.bounding_box()['height'] >= 43.5
                    shoot(page, 'library-access-removed')
                    for tab in ('#/canvas', '#/notes', '#/jv'):
                        page.evaluate(f"location.hash = '{tab}'")
                        expect(strip).to_be_visible()
                    strip.locator('a').click()
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    expect(strip).to_have_count(0)
                    status = page.locator('#m-backup-status')
                    expect(status.get_by_text("This phone's access was removed on your PC.", exact=True)).to_be_visible()
                    expect(status.get_by_text('Still your phone? Open the new pairing link from your PC.', exact=False)).to_be_visible()
                    assert status.get_by_role('button').count() == 0                     # Scan is the app's; the link is below
                    expect(row_line(page, 'Google account')).to_have_text('Access removed')    # driveStatus speaks the model
                    page.evaluate("""async () => {
                      const { mirrorSource: m } = await import('/src/mobile/state.svelte.ts')
                      await m.changes.add({ op: 'fav', uid: 'synthetic-1', on: true })
                      await m.changes.add({ op: 'fav', uid: 'synthetic-2', on: true })
                    }""")
                    expect(status.get_by_text('2 edits wait on this phone.', exact=False)).to_be_visible()
                    expect(row_line(page, 'This phone')).to_have_text('Phone browser · 2 not sent')
                    shoot(page, 'backup-access-removed')
                    phone = open_group(page, 'This phone')
                    expect(phone.get_by_text('2 not sent yet', exact=False)).to_be_visible()
                    phone.get_by_role('button', name='Unpair this phone', exact=True).click()
                    expect(page.get_by_role('button', name='Sure? Unpair', exact=True)).to_be_visible()
                    expect(page.get_by_role('alert')).to_have_text("2 edits haven't reached your PC yet. If you unpair now, they never will.")
                    main = page.locator('.m-main')
                    assert main.evaluate('e => e.scrollTop') > 0                                 # Unpair sits low on the screen
                    shoot(page, 'backup-unpair')
                    page.evaluate("location.hash = '#/more'")
                    expect(page.locator('#m-status').get_by_text("This phone's access was removed on your PC.", exact=True)).to_be_visible()
                    expect(main).to_have_js_property('scrollTop', 0)                           # More opens at its card
                    expect(strip).to_have_count(0)
                    # the Sync row says the lamp, not the access check's message
                    expect(row_line(page, 'Sync')).to_have_text('access removed')
                    tall(page, '#m-status')
                    shoot(page, 'more-access-removed')
                    main.evaluate('e => { e.scrollTop = 400 }')
                    page.evaluate("location.hash = '#/backup'")
                    expect(status).to_be_visible()
                    expect(main).to_have_js_property('scrollTop', 0)                           # and Backup & phones at its Status
                    ctx.close()
                    browser.close()
                assert set(methods) == {'GET'}, methods                                  # nothing here writes Drive
                assert not errors, errors
                print(json.dumps({'screenshots': str(ART), 'drive_methods': sorted(set(methods)), 'page_errors': errors}))
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == '__main__':
    main()
