"""Actual mobile recovery, tasks, disconnect and key forms in both themes, synthetic Drive only."""
import json
import os
from email.parser import BytesParser
from email.policy import default
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
from tests.check_phone_solo_browser import PAIR, ACCOUNT

ART = Path(tempfile.mkdtemp(prefix='brainamon-mobile-remediation-'))
OLD = 'solo-' + 'f' * 32 + '-'
OTHER = 'solo-' + 'b' * 32 + '-'


class Drive:
    def __init__(self):
        self.files = {'old': {'name': OLD + '1' * 32, 'body': b'lost-key copy'},
                      'other': {'name': OTHER + '2' * 32, 'body': b'independent phone'},
                      'desktop': {'name': 'c' * 32, 'body': b'PC backup'}}
        self.posts, self.deletes, self.held = [], [], []
        self.hold, self.refuse = False, False

    def route(self, route):
        req, path = route.request, urlparse(route.request.url).path
        if self.refuse:
            return route.fulfill(status=401, json={'error': {'message': 'synthetic expired authorization'}})
        if path == '/drive/v3/about':
            return route.fulfill(json={'user': {'emailAddress': ACCOUNT}})
        if req.method == 'POST':
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + req.headers['content-type'] + '\r\n\r\n').encode() + req.post_data_buffer)
            meta, data = list(message.iter_parts())
            name = json.loads(meta.get_payload(decode=True))['name']
            assert re.fullmatch(r'solo-[a-f0-9]{32}-[a-f0-9]{32}', name), name
            fid = 'new-' + str(len(self.posts) + 1)
            self.files[fid] = {'name': name, 'body': data.get_payload(decode=True)}
            self.posts.append(fid)
            if self.hold:
                self.held.append((route, fid))
                return
            return route.fulfill(json={'id': fid})
        if path == '/drive/v3/files':
            return route.fulfill(json={'files': [{'id': fid, 'name': f['name'], 'size': str(len(f['body']))}
                                                 for fid, f in self.files.items()]})
        fid = path.rsplit('/', 1)[-1]
        if req.method == 'DELETE':
            assert fid not in ('other', 'desktop'), fid
            self.deletes.append(fid)
            self.files.pop(fid, None)
            return route.fulfill(status=204)
        if fid in self.files:
            assert fid != 'desktop', 'Standalone phone read PC data'
            return route.fulfill(body=self.files[fid]['body'])
        return route.fulfill(status=404, json={'error': {'message': 'fixture missing'}})

    def release(self):
        self.hold = False
        for route, fid in self.held:
            route.fulfill(json={'id': fid})
        self.held.clear()


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with open(ART / 'vite.log', 'w') as log:
        proc = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port)],
                                cwd=ROOT / 'web', stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                try:
                    urlopen(base + '/src/mobile/main.ts', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('Vite startup failed')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel='msedge', args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                for theme, width in [('light', 360), ('dark', 320)]:
                    drive, errors = Drive(), []
                    ctx = browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
                    seed = {'bp-pair': json.dumps(dict(PAIR, g=ACCOUNT)), 'bp-gtoken': json.dumps({'access': 'synthetic', 'exp': 4e12}),
                            'bp-wifi': 'off', 'bp-theme': theme}
                    ctx.add_init_script("window.__bpDevSolo=true;if(!sessionStorage.getItem('fixture')){sessionStorage.setItem('fixture','1');for(const [k,v]of Object.entries(" + json.dumps(seed) + "))localStorage.setItem(k,v)}")
                    def other(route):
                        path = urlparse(route.request.url).path
                        if route.request.url.startswith(base + '/'):
                            if path.startswith('/cards/'):
                                return route.fulfill(path=ROOT / 'design/card-designs' / path.removeprefix('/cards/'))
                            public = (ROOT / 'web/public' / path.lstrip('/')).resolve()
                            if public.is_relative_to(ROOT / 'web/public') and public.is_file():
                                return route.fulfill(path=public)
                            if not path.startswith(('/api/', '/thumb/')):
                                return route.continue_()
                        return route.abort()
                    ctx.route('**/*', other)
                    ctx.route('https://www.googleapis.com/**', drive.route)
                    page = ctx.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/mobile.html#/recover')
                    page.wait_for_function("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried&&!phone.refreshing}")
                    def shot(name, selector='.m-main'):
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), name
                        page.locator(selector).screenshot(path=str(ART / f'{theme}-{width}-{name}.png'))
                    recover = page.locator('#m-recover')
                    recover.get_by_text('Forgot passphrase?', exact=True).click()
                    recover.get_by_text('I have none of these', exact=True).click()
                    recover.get_by_role('button', name='Choose phone backup options…').click()
                    choices = page.locator('#phone-backup-choices')
                    expect(choices.locator('select option')).to_have_count(3)
                    choices.locator('select').select_option(OLD)
                    choices.get_by_role('button', name='Replace with this phone’s content…').click()
                    expect(choices.get_by_role('button', name='Confirm replacement')).to_have_count(1)
                    shot('replace-confirm', '#phone-backup-choices')
                    choices.get_by_role('button', name='Cancel', exact=True).click()
                    assert not drive.posts and not drive.deletes
                    await_seed = """async()=>{const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                      await m.changes.add({op:'link',uid:'e'.repeat(32),url:'https://example.com/kept',note:'kept',category:''});
                      await m.changes.add({op:'note',file:'kept.md',title:'Kept',body:'before'})}"""
                    page.evaluate(await_seed)
                    drive.hold = True
                    choices.get_by_role('button', name='Replace with this phone’s content…').click()
                    choices.get_by_role('button', name='Confirm replacement').click()
                    expect(choices.get_by_role('button', name='Pause', exact=True)).to_be_visible()
                    page.wait_for_timeout(250)
                    assert drive.held
                    page.evaluate("async()=>{const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');await m.changes.add({op:'note',file:'kept.md',title:'Kept',body:'during upload'})}")
                    choices.get_by_role('button', name='Pause', exact=True).click()
                    drive.release()
                    expect(choices.get_by_role('button', name='Resume task')).to_be_visible()
                    shot('task-paused', '#phone-backup-choices')
                    page.evaluate("location.hash='#/more'")
                    expect(page.locator('#m-status')).to_contain_text('Backup task paused.')
                    page.reload()
                    expect(page.locator('#m-status')).to_contain_text('Backup task paused.')
                    page.get_by_role('button', name='View backup task', exact=True).click()
                    page.get_by_role('button', name='Resume task', exact=True).click()
                    page.wait_for_function("async()=>{const p=(await import('/src/mobile/mirror/pairing.ts')).pairing();return !p.backupTask&&p.k!==" + json.dumps(PAIR['k']) + "}")
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    page.wait_for_function("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried&&!phone.refreshing}")
                    assert drive.deletes == ['old']
                    assert 'other' in drive.files and 'desktop' in drive.files
                    assert len(drive.posts) <= 2  # replacement, then the edit queued during it
                    shot('replacement-complete')
                    drive.refuse = True
                    page.get_by_role('button', name='Manage phone backups…').click()
                    expect(page.locator('#phone-backup-choices').get_by_role('button', name='Connect Google Drive')).to_be_visible()
                    expect(page.locator('#phone-backup-choices').get_by_role('alert')).to_contain_text('sign in again')
                    shot('expired-authorization', '#phone-backup-choices')
                    drive.refuse = False
                    page.evaluate("""async()=>{(await import('/src/mobile/native.ts')).secrets.set('bp-gtoken',JSON.stringify({access:'synthetic-renewed',exp:4e12}));
                      (await import('/src/mobile/state.svelte.ts')).phone.tokenAt=Date.now()}""")
                    page.get_by_role('button', name='Refresh backup list').click()
                    expect(page.locator('#phone-backup-choices select option')).to_have_count(3)
                    page.get_by_role('button', name='Close', exact=True).click()
                    page.evaluate("location.hash='#/more'")
                    page.get_by_role('button', name='Pause sync', exact=True).click()
                    page.reload()
                    expect(page.locator('#m-status')).to_contain_text('Sync paused by you.')
                    shot('sync-paused')
                    page.locator('#m-status').get_by_role('button', name='Resume sync').click()
                    ai = page.locator('#m-ai')
                    ai.get_by_label('OpenAI API key', exact=True).fill('openai-synthetic')
                    ai.get_by_label('Anthropic API key', exact=True).fill('anthropic-draft')
                    ai.get_by_role('button', name='Save OpenAI key').click()
                    expect(ai.get_by_label('Anthropic API key')).to_have_value('anthropic-draft')
                    assert page.evaluate("async()=>(await import('/src/mobile/mirror/pairing.ts')).pairing().ai") == {'openai': 'openai-synthetic'}
                    ai.get_by_role('button', name='Save Anthropic key').click()
                    expect(ai.get_by_role('group', name='Provider').get_by_role('button', name='OpenAI')).to_have_attribute('aria-pressed', 'true')
                    shot('independent-keys', '#m-ai')
                    page.evaluate("location.hash='#/backup'")
                    drive.hold = True
                    page.evaluate("""async()=>{const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                      await m.changes.add({op:'fav',uid:'e'.repeat(32),on:true});window.__sending=m.flush().catch(()=>{})}""")
                    page.wait_for_timeout(250)
                    assert drive.held
                    page.get_by_role('button', name='Disconnect', exact=True).click()
                    page.get_by_role('button', name='Confirm disconnect', exact=True).click()
                    expect(page.get_by_role('button', name='Stopping cloud work…', exact=True)).to_be_visible()
                    drive.release()
                    page.wait_for_function("async()=>{const p=await import('/src/mobile/mirror/pairing.ts');return !p.token(p.pairing())}")
                    expect(page.locator('#m-backup-status')).to_contain_text('Your library is only on this phone.')
                    assert page.evaluate("async()=>{const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');await m.changes.load();return m.changes.unsent}") >= 1
                    shot('disconnected-local-content')
                    assert not errors, errors
                    ctx.close()
                browser.close()
            print(json.dumps({'screenshots': str(ART), 'themes': 2, 'widths': [360, 320], 'page_errors': []}))
        finally:
            proc.terminate()
            proc.wait(timeout=15)


if __name__ == '__main__':
    main()
