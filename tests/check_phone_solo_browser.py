"""Settings, Settings > Backup & phones and Recover a library… for the phone without a PC (docs/superpowers/plans/
2026-10-31-phone-backup-phones.md, sub-plan 05) in the phone page, at 360 px in light and dark. Each state is reached by
its cause: no Google sign-in, a Google token that ran out, the first backup round still waiting for Drive, Google Drive
out of reach, no recovery yet, a passphrase set, a recovery file downloaded but not checked, the file checked. A
synthetic solo key, synthetic Google tokens and an in-memory Google Drive (Playwright routes on googleapis.com); no
account, no real Drive, no data folder. The words come from tests/fixtures/phone_states.json.
Run: py tests/check_phone_solo_browser.py
"""
import base64
import copy
from email.parser import BytesParser
from email.policy import default
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
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library import mirror  # noqa: E402  (the phone's backup names come from the desktop's MirrorKey)
from tests.phone_groups import open_group, row_line  # noqa: E402  (the group rows, projects/phone-settings)

ART = ROOT / 'local/ui-blocks/shots/phone-solo'
RAW = bytes([11]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
PREFIX = 'solo-' + mirror.MirrorKey(RAW).name('phone-backup') + '-'
ACCOUNT = 'sample@example.com'
PAIR = dict(v=2, k=KEY, f=FP, c='', e='', ai={}, at=0, solo=True)
CASES = {c['name']: c['expect'] for c in json.loads((ROOT / 'tests/fixtures/phone_states.json').read_text(encoding='utf-8'))['cases']}
SETTLED = "async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }"
SET = re.compile(r'^Passphrase set \d{1,2} \w+$')


class Drive:
    """The phone's hidden Google Drive folder: uploads, listings and downloads in memory; `mode` holds the next listing
    open (the first round still running) or makes listings fail (Drive out of reach)."""

    def __init__(self):
        self.files, self.writes, self.methods, self.unexpected, self.held = {}, [], set(), [], []
        self.mode = 'ok'

    def route(self, route):
        req, url = route.request, urlparse(route.request.url)
        self.methods.add(req.method)
        if url.path == '/drive/v3/about':
            return route.fulfill(json={'user': {'emailAddress': ACCOUNT}})
        if req.method == 'POST' and url.path == '/upload/drive/v3/files':
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + req.headers['content-type'] + '\r\n\r\n').encode() + req.post_data_buffer)
            meta, body = list(message.iter_parts())
            name = json.loads(meta.get_payload(decode=True))['name']
            if not name.startswith(('vi-phone-recovery-', PREFIX)):
                self.unexpected.append('upload ' + name)
                return route.abort()
            fid = f'file-{len(self.files) + 1}'
            self.files[fid] = {'name': name, 'body': body.get_payload(decode=True)}
            self.writes.append(name)
            return route.fulfill(json={'id': fid})
        if req.method == 'GET' and url.path == '/drive/v3/files':
            if self.mode == 'abort':
                return route.abort()
            if self.mode == 'hold':
                self.mode = 'ok'
                self.held.append(route)
                return None
            q = parse_qs(url.query).get('q', [''])[0]
            return route.fulfill(json={'files': [{'id': fid, 'name': f['name'], 'size': str(len(f['body']))} for fid, f in self.files.items()
                                                 if 'vi-phone-recovery-' not in q or f['name'].startswith('vi-phone-recovery-')]})
        fid = url.path.removeprefix('/drive/v3/files/')
        if req.method == 'GET' and fid in self.files:
            return route.fulfill(body=self.files[fid]['body'], content_type='application/octet-stream')
        self.unexpected.append(f'{req.method} {url.path}')
        return route.abort()

    def release(self):
        for r in self.held:
            self.route(r)
        self.held.clear()


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
    """The whole screen in both themes: the page scrolls inside .m-main (a sheet inside .m-sheet-body), so the
    viewport grows to its content for the picture, then comes back to 360 x 800."""
    more = page.evaluate("() => { const m = document.querySelector('.m-sheet-body') || document.querySelector('.m-main'); return m ? m.scrollHeight - m.clientHeight : 0 }")
    page.set_viewport_size({'width': 360, 'height': 800 + max(0, more)})
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        assert fits(page), (name, theme)
        page.screenshot(path=str(ART / f'{name}-{theme}.png'))
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.set_viewport_size({'width': 360, 'height': 800})


def words(text):
    """A fixture sentence; its "checked 2 min ago" reads whatever the clock says when the check runs."""
    return re.compile('^' + re.escape(text).replace(re.escape('2 min ago'), r'(just now|\d+ min ago)') + '$')


def shows(page, scope, case, card=False):
    """The state of fixture case `case` in the status card (card=True: its sentence and key) or in the Status group of
    Backup & phones (also its detail)."""
    want = CASES[case]
    box = page.locator(scope)
    expect(box.locator('.m-status b')).to_have_text(words(want['text']))
    if not card:
        if want['detail']:
            expect(box.locator('.m-status small')).to_have_text(words(want['detail']))
        else:
            expect(box.locator('.m-status small')).to_have_count(0)
    keys = box.locator('.m-status').get_by_role('button')
    if want['action']:
        expect(keys).to_have_count(1)
        expect(keys).to_have_text(want['action']['label'])
        assert ('pri' in keys.get_attribute('class').split()) == want['action']['primary'], case
    else:
        expect(keys).to_have_count(0)
    return want


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-solo-') as folder:
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
                errors, drive, reached = [], Drive(), []

                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, channel='msedge')

                    def phone_page(signed_in: bool, token: bool):
                        ctx = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True, accept_downloads=True, locale='en-US')
                        ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                        ctx.route('https://**/*', lambda r: r.abort())
                        ctx.route('**/api/**', lambda r: r.abort())
                        ctx.route(base + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                        ctx.route('https://www.googleapis.com/**', drive.route)
                        seed = {'bp-pair': json.dumps(dict(PAIR, g=ACCOUNT) if signed_in else PAIR)}
                        if token:
                            seed['bp-gtoken'] = json.dumps({'access': 'synthetic', 'exp': int(time.time() * 1000) + 3600000})
                        ctx.add_init_script("localStorage.setItem('bp-wifi','off'); if (!sessionStorage.getItem('fixture')) {"
                                            "sessionStorage.setItem('fixture','1'); for (const [k, v] of Object.entries(" +
                                            json.dumps(seed) + ")) localStorage.setItem(k, v) }")
                        page = ctx.new_page()
                        page.set_default_timeout(15000)
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        return ctx, page

                    def on_more(page, case, name):
                        page.evaluate("location.hash = '#/more'")
                        shows(page, '#m-status', case, card=True)
                        assert page.locator('.m-pad > *').first.get_attribute('id') == 'm-status'
                        for moved in ('#m-conn', '#m-recovery', '#m-pair'):        # all on Backup & phones now
                            assert page.locator(moved).count() == 0, moved
                        tall(page, '#m-status')
                        shoot(page, f'more-{name}')

                    def on_backup(page, case, name):
                        page.evaluate("location.hash = '#/backup'")
                        want = shows(page, '#m-backup-status', case)
                        ids = page.evaluate("() => [...document.querySelectorAll('.m-pad > .m-box')].map(e => e.id)")
                        assert ids == ['m-backup-status', 'm-conn', 'm-phone', 'm-recovery'], ids
                        if want['action']:                                   # the Status's key, not a row's too
                            expect(page.get_by_role('button', name=want['action']['label'], exact=True)).to_have_count(1)
                        tall(page, '.m-pad')
                        shoot(page, f'backup-{name}')
                        reached.append(want['id'])

                    # 1. Only on this phone: no Google sign-in yet
                    ctx, page = phone_page(False, False)
                    page.goto(base + '/mobile.html#/more')
                    page.wait_for_function(SETTLED)
                    on_more(page, 'solo: only on this phone', 'solo-local')
                    page.locator('#m-status').get_by_role('link', name='Backup & phones').click()
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    on_backup(page, 'solo: only on this phone', 'solo-local')
                    expect(page.locator('#m-library')).to_contain_text('0 items on this phone')
                    expect(row_line(page, 'Recovery')).to_have_text('Not set up')       # the row says it, the group not again
                    recovery = open_group(page, 'Recovery')
                    expect(recovery.locator('.m-status')).to_have_count(0)
                    assert page.get_by_role('button', name='Set up recovery', exact=True).count() == 0
                    recovery.get_by_role('link', name='Recover a library…', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/recover')
                    expect(page.locator('.m-page-keys .m-ws')).to_have_text('Recover')
                    rbox = page.locator('#m-recover')
                    expect(rbox.get_by_text('Connect Google Drive on Backup & phones to use a passphrase or recovery file.', exact=True)).to_be_visible()
                    expect(rbox.get_by_role('button', name='Find recovery setups', exact=True)).to_be_disabled()
                    tall(page, '.m-pad')
                    shoot(page, 'recover-solo-local')
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    ctx.close()

                    # 2. Google asks to sign in again: a confirmed account whose token ran out before this start
                    ctx, page = phone_page(True, False)
                    page.goto(base + '/mobile.html#/notes')
                    page.wait_for_function(SETTLED)
                    strip = page.locator('.m-strip-owner')
                    expect(strip).to_have_text('Backup & phones · Google asks you to sign in again.')
                    assert strip.bounding_box()['height'] >= 43.5
                    shoot(page, 'notes-solo-sign-in')
                    on_more(page, 'solo: Google asks to sign in again', 'solo-sign-in')
                    on_backup(page, 'solo: Google asks to sign in again', 'solo-sign-in')
                    expect(strip).to_have_count(0)
                    assert page.get_by_role('button', name='Back up to Google Drive', exact=True).count() == 0
                    ctx.close()

                    # 3. Signed in: the first round waits for Drive, then it backs up; Drive out of reach; recovery
                    drive.mode = 'hold'
                    ctx, page = phone_page(True, True)
                    page.goto(base + '/mobile.html#/more')
                    for _ in range(100):
                        if drive.held:
                            break
                        page.wait_for_timeout(100)
                    assert drive.held, 'the first round never listed Drive'
                    on_more(page, 'first read running', 'solo-connecting')
                    on_backup(page, 'first read running', 'solo-connecting')
                    drive.release()
                    page.wait_for_function(SETTLED)
                    on_backup(page, 'solo: no recovery yet', 'solo-recovery')
                    expect(row_line(page, 'Recovery')).to_have_text('Not set up')
                    recovery = page.locator('#m-recovery')
                    on_more(page, 'solo: no recovery yet', 'solo-recovery')

                    drive.mode = 'abort'
                    sync = open_group(page, 'Sync')
                    sync.get_by_role('button', name='Sync now', exact=True).click()
                    card = page.locator('#m-status')
                    expect(card.locator('.m-status b')).to_have_text('Google Drive could not be reached.', timeout=30000)
                    expect(card.get_by_role('button', name='Retry', exact=True)).to_have_class('m-btn pill pri')
                    tall(page, '#m-status')
                    shoot(page, 'more-solo-unreachable')
                    page.evaluate("location.hash = '#/backup'")
                    status = page.locator('#m-backup-status')
                    expect(status.locator('.m-status small')).to_have_text('Saved content stays on this phone.')
                    expect(status.get_by_role('alert')).to_contain_text('Google Drive is out of reach')
                    tall(page, '.m-pad')
                    shoot(page, 'backup-solo-unreachable')
                    reached.append('unreachable')
                    drive.mode = 'ok'
                    status.get_by_role('button', name='Retry', exact=True).click()
                    page.wait_for_function(SETTLED)
                    shows(page, '#m-backup-status', 'solo: no recovery yet')

                    # Set up recovery: the Status key opens the form in the Recovery group
                    status.get_by_role('button', name='Set up recovery', exact=True).click()
                    recovery.get_by_role('button', name='Generate passphrase', exact=True).click()
                    passphrase = recovery.get_by_label('Recovery passphrase', exact=True).input_value()
                    assert len(passphrase) >= 12 and not drive.writes
                    tall(page, '.m-pad')
                    shoot(page, 'backup-solo-setup-form')
                    drive.mode = 'hold'
                    recovery.get_by_role('button', name='Save passphrase', exact=True).click()
                    expect(recovery.locator('#phone-recovery-wait')).to_have_text('Saving and checking your passphrase…')
                    deadline = time.monotonic() + 30
                    while not drive.held and time.monotonic() < deadline:
                        page.wait_for_timeout(50)
                    assert drive.held, 'Recovery setup never reached the held Drive check'
                    drive.release()
                    expect(recovery.locator('.m-status b')).to_have_text(SET, timeout=60000)
                    expect(recovery.get_by_text('Passphrase set and checked against your backup. Now save the recovery file.', exact=True)).to_be_visible()
                    assert len(drive.writes) == 1 and drive.writes[0].startswith('vi-phone-recovery-'), drive.writes
                    expect(recovery.get_by_role('button', name='Save recovery file…', exact=True)).to_have_class('m-btn sm pri')
                    on_backup(page, 'solo: passphrase set, no recovery file', 'solo-prepared')
                    on_more(page, 'solo: passphrase set, no recovery file', 'solo-prepared')

                    # Save recovery file…: a browser download, saved for this page's session
                    page.evaluate("location.hash = '#/backup'")
                    recovery = open_group(page, 'Recovery')
                    with page.expect_download() as download:
                        recovery.get_by_role('button', name='Save recovery file…', exact=True).click()
                    kit = Path(folder) / 'kit.json'
                    download.value.save_as(kit)
                    expect(recovery.locator('.m-status b')).to_have_text('Recovery file saved, not checked')
                    expect(recovery.get_by_text(re.compile(r'^Passphrase set \d{1,2} \w+\.$'))).to_be_visible()
                    expect(recovery.get_by_text('Download requested. A browser download is not confirmed until you open the file.', exact=True)).to_be_visible()
                    on_backup(page, 'solo: recovery file not checked', 'solo-check-file')
                    recovery = open_group(page, 'Recovery')
                    assert recovery.get_by_role('button', name='Check recovery file…', exact=True).count() == 0     # the Status has it
                    drive.mode = 'hold'
                    page.evaluate("async () => { const { refresh } = await import('/src/mobile/state.svelte.ts'); void refresh() }")
                    expect(recovery.locator('#phone-recovery-wait')).to_have_text('Syncing your backup. Recovery setup and file checks become available when the current sync finishes.')
                    expect(status.get_by_role('button', name='Check recovery file…', exact=True)).to_be_disabled()
                    expect(recovery.get_by_text(re.compile(r'^Passphrase set \d{1,2} \w+\.$'))).to_be_visible()
                    deadline = time.monotonic() + 10
                    while not drive.held and time.monotonic() < deadline:
                        page.wait_for_timeout(50)
                    assert drive.held, 'Sync never reached the held Drive read'
                    drive.release()
                    page.wait_for_function(SETTLED)
                    expect(status.get_by_role('button', name='Check recovery file…', exact=True)).to_be_enabled()
                    on_more(page, 'solo: recovery file not checked', 'solo-check-file')

                    # Check recovery file… from the card: the chooser opens in the tap, the outcome shows on Backup & phones
                    with page.expect_file_chooser() as chooser:
                        page.locator('#m-status').get_by_role('button', name='Check recovery file…', exact=True).click()
                    chooser.value.set_files(str(kit))
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    expect(recovery.locator('button.m-group-row')).to_have_attribute('aria-expanded', 'true')   # the link opened it
                    expect(recovery.get_by_text('Recovery file checked against your backup.', exact=True)).to_be_visible(timeout=30000)
                    expect(recovery.locator('.m-status b')).to_have_text(re.compile(r'^Passphrase set \d{1,2} \w+ · recovery file checked$'))
                    on_backup(page, 'solo: backed up', 'solo-ok')
                    on_more(page, 'solo: backed up', 'solo-ok')

                    # Recover a library…: an older setup of the same library in Drive too (put there by this check, not
                    # the page); setups by when they were made, the newest first and chosen, no key in the labels
                    real = next(fid for fid, f in drive.files.items() if f['name'].startswith('vi-phone-recovery-'))
                    older = copy.deepcopy(json.loads(drive.files[real]['body']))
                    older['header']['generation'] = 'e' * 32
                    older['header']['created'] -= 2 * 86400
                    drive.files['file-older'] = {'name': f"vi-phone-recovery-{older['header']['library']}-{'e' * 32}.json",
                                                 'body': json.dumps(older, separators=(',', ':')).encode()}
                    page.evaluate("location.hash = '#/backup'")
                    recovery = open_group(page, 'Recovery')
                    recovery.get_by_role('link', name='Recover a library…', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/recover')
                    rbox = page.locator('#m-recover')
                    tall(page, '.m-pad')
                    shoot(page, 'recover-solo-start')
                    rbox.get_by_role('button', name='Find recovery setups', exact=True).click()
                    setup = rbox.locator('select')          # its label's text includes the options, so it is found as the one select
                    expect(setup.locator('option')).to_have_count(2)
                    labels = setup.locator('option').all_inner_texts()
                    assert all(t.startswith('Set up ') and FP not in t for t in labels), labels
                    assert setup.input_value() == real, (setup.input_value(), real)
                    rbox.get_by_label('Recovery passphrase', exact=True).fill(passphrase)
                    tall(page, '.m-pad')
                    shoot(page, 'recover-solo-setups')
                    rbox.get_by_role('button', name='Find backup', exact=True).click()
                    keep = rbox.locator('#phone-recovery-keep')
                    expect(keep).to_contain_text('no record of a backup', timeout=60000)
                    expect(rbox.get_by_role('button', name='Restore on an empty phone', exact=True)).to_have_class('m-btn pill pri')
                    assert rbox.get_by_role('button', name='Reconnect this phone', exact=True).count() == 0
                    tall(page, '.m-pad')
                    shoot(page, 'recover-solo-found')
                    rbox.get_by_role('button', name='Cancel', exact=True).click()
                    expect(rbox.get_by_role('button', name='Find recovery setups', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    ctx.close()
                    browser.close()
                assert len(drive.writes) == 1, drive.writes                       # the recovery setup, nothing else
                assert not drive.unexpected, drive.unexpected
                assert not errors, errors
                print(json.dumps({'screenshots': str(ART), 'states': sorted(set(reached)), 'drive_methods': sorted(drive.methods),
                                  'writes': [w.split('-')[0] + '-…' for w in drive.writes], 'page_errors': errors}))
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == '__main__':
    main()
