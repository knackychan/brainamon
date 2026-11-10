"""Phone recovery UI and Drive boundary checks with synthetic keys and mocked Drive.

Run: py tests/check_phone_recovery_browser.py
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
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library import mirror  # noqa: E402  (the fixture's batch file is sealed by the desktop's MirrorKey)
from tests.phone_groups import open_group  # noqa: E402  (the Recovery group, projects/phone-settings)

ART = Path(tempfile.mkdtemp(prefix='brainamon-phone-recovery-shots-'))
RAW = bytes([7]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
MKEY = mirror.MirrorKey(RAW)
PREFIX = 'solo-' + MKEY.name('phone-backup') + '-'


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-recovery-') as folder:
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
                    browser = pw.chromium.launch(headless=True, channel='msedge')
                    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, locale='en-US')
                    ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                    # This fixture starts only Vite, so serve the card engine without its backend proxy.
                    cards = {name: ROOT / 'design/card-designs' / name for name in
                             ('cards.css', 'engine.js', 'full-art-v2/fa2.css', 'full-art-v2/fa2.js')}
                    def card(route):
                        route.fulfill(path=cards[urlparse(route.request.url).path.removeprefix('/cards/')])
                    ctx.route(base + '/cards/**', card)
                    pair = dict(v=2, k=KEY, f=FP, c='', e='', g='sample@example.com', ai={}, at=0, solo=True, d=base + '/fake-drive')
                    ctx.add_init_script("window.__bpDevSolo=true; localStorage.setItem('bp-wifi','off'); if(!sessionStorage.getItem('fixture')) {sessionStorage.setItem('fixture','1');localStorage.setItem('bp-pair'," + json.dumps(json.dumps(pair)) + ");}")
                    ctx.route('https://**/*', lambda r: r.abort())
                    ctx.route('**/api/**', lambda r: r.abort())
                    records, writes, errors = {}, [], []
                    account = ['sample@example.com']

                    def drive(route):
                        req = route.request
                        path = urlparse(req.url).path
                        query = parse_qs(urlparse(req.url).query)
                        if path.endswith('/about'):
                            route.fulfill(json={'user': {'emailAddress': account[0]}})
                        elif req.method == 'POST':
                            parts = req.post_data_buffer.split(b'\r\n\r\n')
                            metadata = json.loads(parts[1].split(b'\r\n--')[0])
                            body = parts[2].rsplit(b'\r\n--', 1)[0]
                            assert metadata['name'].startswith(('vi-phone-recovery-', PREFIX)), metadata['name']
                            file_id = 'recovery-' + str(len(records))
                            records[file_id] = dict(id=file_id, name=metadata['name'], size=str(len(body)), body=body)
                            writes.append(metadata['name'])
                            route.fulfill(json={'id': file_id})
                        elif path.endswith('/files'):
                            q = query.get('q', [''])[0]
                            found = [f for f in records.values() if 'vi-phone-recovery-' not in q or f['name'].startswith('vi-phone-recovery-')]
                            route.fulfill(json={'files': [{k: f[k] for k in ('id', 'name', 'size')} for f in found]})
                        elif path.rsplit('/', 1)[-1] in records:
                            route.fulfill(body=records[path.rsplit('/', 1)[-1]]['body'], content_type='application/json')
                        else:
                            raise AssertionError(f'Unexpected Drive operation: {req.method} {path}')

                    ctx.route(base + '/fake-drive/**', drive)
                    ctx.route('http://127.0.0.1:18766/**', drive)
                    page = ctx.new_page()
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/mobile.html#/backup')
                    box = page.locator('#m-recovery')
                    status = page.locator('#m-backup-status')
                    button = lambda name: box.get_by_role('button', name=name, exact=True)
                    page.wait_for_function("async()=> !(await import('/src/mobile/state.svelte.ts')).phone.refreshing")
                    open_group(page, 'Recovery')
                    guide = box.locator('details').first
                    guide.locator('summary').first.focus()
                    page.keyboard.press('Enter')
                    for situation in ('I can still open my library', 'I have a recovery file', 'I have a recovery code or a paired phone', 'I have none of these'):
                        guide.get_by_text(situation, exact=True).click()
                    expect(guide.get_by_text('Earlier phone passphrases remain valid.', exact=False)).to_be_visible()
                    expect(guide.get_by_text('Google sign-in alone cannot unlock', exact=False)).to_be_visible()
                    for width in (320, 390):
                        page.set_viewport_size({'width': width, 'height': 844})
                        for theme in ('light', 'dark'):
                            page.evaluate('(v)=>document.documentElement.dataset.theme=v', theme)
                            guide.scroll_into_view_if_needed()
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                            page.screenshot(path=ART / f'forgot-{width}-{theme}.png')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    guide.get_by_role('button', name='Create another passphrase…', exact=True).click()
                    expect(box.get_by_label('Recovery passphrase', exact=True)).to_be_visible()
                    button('Cancel').click()
                    assert not writes
                    guide.get_by_role('button', name='Use recovery code', exact=True).click()
                    expect(box.locator('#phone-original-code')).to_contain_text(KEY)
                    assert page.evaluate("async()=> (await import('/src/mobile/mirror/pairing.ts')).pairing().k") == KEY
                    page.evaluate("async()=>{(await import('/src/mobile/state.svelte.ts')).phone.refreshing=true}")
                    expect(guide.get_by_role('button', name='Create another passphrase…', exact=True)).to_be_disabled()
                    expect(guide.get_by_text('Syncing your backup.', exact=False)).to_be_visible()
                    page.evaluate("async()=>{(await import('/src/mobile/state.svelte.ts')).phone.refreshing=false}")
                    page.evaluate("async()=>{(await import('/src/mobile/state.svelte.ts')).phone.connecting=true}")
                    expect(guide.get_by_role('button', name='Create another passphrase…', exact=True)).to_be_disabled()
                    expect(guide.get_by_text('Connecting Google Drive.', exact=False)).to_be_visible()
                    page.evaluate("async()=>{(await import('/src/mobile/state.svelte.ts')).phone.connecting=false}")
                    guide.get_by_role('button', name='Use recovery file', exact=True).click()
                    recover = page.locator('#m-recover')
                    expect(recover.get_by_role('button', name='File', exact=True)).to_have_attribute('aria-pressed', 'true')
                    recover.get_by_text('Forgot passphrase?', exact=True).click()
                    recover.get_by_text('I have a recovery code or a paired phone', exact=True).click()
                    recover.get_by_role('button', name='Use recovery code', exact=True).click()
                    recover.get_by_label('Original recovery code', exact=True).fill('synthetic-unsent-code')
                    recover.get_by_role('button', name='File', exact=True).click()
                    recover.get_by_role('button', name='Code', exact=True).click()
                    expect(recover.get_by_label('Original recovery code', exact=True)).to_have_value('')
                    recover.get_by_label('Original recovery code', exact=True).fill(KEY)
                    recover.get_by_role('button', name='Find backup', exact=True).click()
                    expect(recover.locator('#phone-recovery-keep')).to_be_visible()
                    recover.get_by_role('button', name='Cancel', exact=True).click()
                    expect(recover.get_by_label('Original recovery code', exact=True)).to_have_value('')
                    recover.get_by_role('button', name='File', exact=True).click()
                    with page.expect_file_chooser() as cancelled_file:
                        recover.get_by_role('button', name='Open recovery file…', exact=True).click()
                    cancelled_file.value.set_files([])
                    expect(recover.locator('#phone-recovery-keep')).not_to_be_visible()
                    assert not writes
                    page.evaluate("location.hash='#/backup'")
                    # the Status offers the one next step; the Recovery group leaves that key out
                    expect(status.get_by_text('Backed up, but if this phone is lost nothing can unlock the backup.', exact=True)).to_be_visible()
                    expect(status.get_by_role('button', name='Set up recovery', exact=True)).to_be_enabled()
                    assert button('Set up recovery').count() == 0
                    status.get_by_role('button', name='Set up recovery', exact=True).click()
                    button('Generate passphrase').click()
                    password = box.get_by_label('Recovery passphrase', exact=True)
                    generated = password.input_value()
                    expect(box.get_by_label('Confirm passphrase', exact=True)).to_have_value(generated)
                    expect(password).to_have_attribute('type', 'text')
                    assert not writes
                    button('Hide passphrase').click()
                    expect(password).to_have_attribute('type', 'password')
                    for theme in ('light', 'dark'):
                        page.evaluate('(v) => document.documentElement.dataset.theme=v', theme)
                        password.scroll_into_view_if_needed()
                        page.screenshot(path=ART / f'390-{theme}-generate.png')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    # Passphrase derivation must allow UI timers to run while the worker is busy.
                    responsiveness = page.evaluate("""async () => {
                      const {recoveryKey}=await import('/src/mobile/mirror/recovery-kdf.ts');
                      let ticks=0;
                      const timer=setInterval(()=>ticks++, 10);
                      try {
                        const key=await recoveryKey(new TextEncoder().encode('synthetic worker passphrase'),new Uint8Array(16));
                        key.fill(0);
                        return ticks;
                      } finally {clearInterval(timer)}
                    }""")
                    assert responsiveness >= 2, f'Passphrase processing blocked UI timers: {responsiveness}'
                    button('Save passphrase').click()
                    expect(box.get_by_text(re.compile(r'^Passphrase set \d{1,2} \w+$'))).to_be_visible()
                    expect(box.get_by_text('Passphrase set and checked against your backup. Now save the recovery file.', exact=True)).to_be_visible()
                    expect(status.get_by_text(re.compile(r'^Backed up · checked '))).to_be_visible()
                    assert len(writes) == 1
                    with page.expect_download() as download:
                        button('Save recovery file…').click()
                    kit_path = Path(folder) / 'kit.json'
                    download.value.save_as(kit_path)
                    kit = json.loads(kit_path.read_text())
                    expect(box.get_by_text('Recovery file saved, not checked', exact=True)).to_be_visible()
                    expect(box.get_by_text('Download requested. A browser download is not confirmed until you open the file.', exact=True)).to_be_visible()
                    expect(status.get_by_text('Recovery file saved, not checked yet.', exact=True)).to_be_visible()
                    discovery = page.evaluate("""async kit => {
                      const r=await import('/src/mobile/mirror/phone-recovery.ts');
                      const e=await import('/src/mobile/mirror/recovery-envelope.ts');
                      const records=Array.from({length:9},(_,i)=>{
                        const record=structuredClone(kit.record);
                        record.header.generation=i.toString(16).padStart(32,'0');
                        record.header.created+=i;
                        return record;
                      });
                      let active=0,peak=0;
                      const drive={
                        listPhoneRecovery:async()=>records.map((record,i)=>({id:String(i),name:e.phoneRecoveryName(record)})),
                        getPhoneRecovery:async id=>{
                          active++; peak=Math.max(peak,active);
                          await new Promise(resolve=>setTimeout(resolve,20));
                          active--; return JSON.stringify(records[Number(id)]);
                        }
                      };
                      const found=await r.discoverPhoneRecovery(drive);
                      return {peak, ids:found.map(f=>f.id)};
                    }""", kit)
                    assert discovery == {'peak': 4, 'ids': [str(i) for i in reversed(range(9))]}, discovery
                    assert button('Check recovery file…').count() == 0              # the Status offers it
                    with page.expect_file_chooser() as chooser:
                        status.get_by_role('button', name='Check recovery file…', exact=True).click()
                    chooser.value.set_files(str(kit_path))
                    checked = re.compile(r'^Passphrase set \d{1,2} \w+ · recovery file checked$')
                    expect(box.get_by_text(checked)).to_be_visible()
                    expect(box.get_by_text('Recovery file checked against your backup.', exact=True)).to_be_visible()
                    page.reload()
                    open_group(page, 'Recovery')
                    expect(box.get_by_text(checked)).to_be_visible()

                    # Recover a library… (#/recover): from here on `box`, and button() with it, is that screen's box
                    box.get_by_role('link', name='Recover a library…', exact=True).click()
                    box = page.locator('#m-recover')
                    button('Find recovery setups').click()
                    password = box.get_by_label('Recovery passphrase', exact=True)
                    expect(password).to_be_visible()
                    password.fill('incorrect synthetic phrase')
                    button('Find backup').click()
                    expect(box.get_by_role('alert')).to_contain_text('incorrect')
                    assert len(writes) == 1
                    # Authenticating a key is read-only and checks the current account again.
                    recovered = page.evaluate("""async password => {
                      const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                      const r=await import('/src/mobile/mirror/phone-recovery.ts');
                      const setups=await r.discoverPhoneRecovery(m.drive);
                      return (await r.restorePhonePassphrase(m.pair,m.drive,setups[0].id,password)).key;
                    }""", generated)
                    assert recovered == KEY
                    account[0] = 'other@example.com'
                    button('Find recovery setups').click()
                    expect(box.get_by_role('alert')).to_contain_text('account changed')
                    account[0] = 'sample@example.com'

                    # The old code path remains visible; a phone that never backed up gets no Reconnect, and
                    # Restore on an empty phone still refuses a phone with content.
                    box.get_by_role('group', name='Unlock with').get_by_role('button', name='Code', exact=True).click()
                    expect(box.get_by_label('Original recovery code', exact=True)).to_be_visible()
                    # a recovery file pasted in the code field: refused with help, and Use recovery file switches the method
                    box.get_by_label('Original recovery code', exact=True).fill(kit_path.read_text())
                    button('Find backup').click()
                    expect(box.get_by_role('alert')).to_contain_text('This is a recovery file')
                    button('Use recovery file').click()
                    expect(button('Open recovery file…')).to_be_visible()
                    page.evaluate("""async () => {
                      const {changes}=await import('/src/mobile/store.ts');
                      await changes.add({op:'link',uid:'local-kept',url:'https://example.com/kept',note:'keep',category:''});
                    }""")
                    with page.expect_file_chooser() as chooser:
                        button('Open recovery file…').click()
                    chooser.value.set_files(str(kit_path))
                    keep = box.locator('#phone-recovery-keep')
                    expect(keep).to_contain_text('no record of a backup')
                    assert box.get_by_role('button', name='Reconnect this phone', exact=True).count() == 0
                    button('Restore on an empty phone').click()
                    expect(box.get_by_role('alert')).to_contain_text('empty phone')
                    expect(keep).to_be_visible()                      # the found key stays: Reconnect is one tap away after a refusal
                    assert page.evaluate("async()=> (await import('/src/mobile/mirror/pairing.ts')).pairing().k") == KEY
                    assert page.evaluate("async()=> (await (await import('/src/mobile/store.ts')).changes.forChat()).length") == 1
                    assert len(writes) == 1
                    # A fresh, empty phone can import the saved kit while keeping the confirmed account.
                    page.evaluate("""async () => {
                      const {changes,wipe}=await import('/src/mobile/store.ts');
                      await changes.clear(); await wipe();
                      const p=await import('/src/mobile/mirror/pairing.ts');
                      await p.startSolo('A'.repeat(43), {d:location.origin+'/fake-drive',x:{},ai:{}});
                      p.confirmAccount(p.pairing(),'sample@example.com');
                      await (await import('/src/mobile/native.ts')).secretsSaved();
                    }""")
                    page.reload()
                    expect(box.get_by_role('group', name='Unlock with')).to_be_visible()      # the reload stays on Recover a library
                    box.get_by_role('group', name='Unlock with').get_by_role('button', name='File', exact=True).click()
                    with page.expect_file_chooser() as chooser:
                        button('Open recovery file…').click()
                    chooser.value.set_files(str(kit_path))
                    expect(box.locator('#phone-recovery-keep')).to_contain_text('no record of a backup')
                    with page.expect_navigation():
                        button('Restore on an empty phone').click()
                    # restored, it opens on Backup & phones, where the Status asks for recovery on this phone
                    expect(page).to_have_url(base + '/mobile.html#/backup')
                    expect(status.get_by_role('button', name='Set up recovery', exact=True)).to_be_enabled()
                    restored = page.evaluate("async()=> (await import('/src/mobile/mirror/pairing.ts')).pairing()")
                    assert restored['k'] == KEY and restored['g'] == 'sample@example.com'
                    assert len(writes) == 1  # Restore does not publish or claim a desktop library.

                    # Reconnect: the phone backed up under KEY, then lost it (a new solo key, the journal kept).
                    # Stop the previous page's background reads before installing a new synthetic journal.
                    page.evaluate("async()=> (await import('/src/mobile/network.svelte.ts')).setWifiOnly(true)")
                    page.wait_for_function("async()=> !(await import('/src/mobile/state.svelte.ts')).phone.refreshing")
                    batch = {'format': 1, 'device': 'p0102030405', 'at': 1761750000000, 'changes': [
                        {'op': 'link', 'uid': 'ef' * 16, 'url': 'https://www.youtube.com/watch?v=reconnect1', 'note': 'kept on the phone', 'category': '', 'at': 1761749990000}]}
                    plain = json.dumps(batch, separators=(',', ':')).encode()
                    name = PREFIX + 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
                    records['batch-1'] = dict(id='batch-1', name=name, size=str(len(plain) + 32), body=MKEY.seal(name, plain))
                    lost_key = mirror.MirrorKey(base64.urlsafe_b64decode('B' * 43 + '='))
                    stray_name = 'solo-' + lost_key.name('phone-backup') + '-' + 'b' * 32
                    stray = {'op': 'fav', 'uid': 'ef' * 16, 'on': True, 'at': batch['at'] + 1}
                    stray_body = lost_key.seal(stray_name, json.dumps({'format': 1, 'device': batch['device'], 'at': batch['at'] + 2, 'changes': [stray]}).encode())
                    records['stray-1'] = dict(id='stray-1', name=stray_name, size=str(len(stray_body)), body=stray_body)
                    page.evaluate("""async ([name, at, sig, fp, strayName]) => {
                      const {changes, kv}=await import('/src/mobile/store.ts');
                      await changes.clear();
                      const id=await changes.add({op:'link',uid:'ef'.repeat(16),url:'https://www.youtube.com/watch?v=reconnect1',note:'kept on the phone',category:'',at:1761749990000});
                      await changes.put({id,op:'link',uid:'ef'.repeat(16),url:'https://www.youtube.com/watch?v=reconnect1',note:'kept on the phone',category:'',at:1761749990000,state:'sent',sentAt:at,chg:name});
                      await changes.add({op:'fav',uid:'ef'.repeat(16),on:true,at:at+1,state:'sent',sentAt:at+2,chg:strayName});
                      await kv.set('solo_publish',{[fp]:{fingerprint:fp,name,id:'batch-1',at,n:1,sig}});
                      await kv.set('rows',[{id:-1,url:'https://www.youtube.com/watch?v=reconnect1'}]);
                      const p=await import('/src/mobile/mirror/pairing.ts');
                      await p.startSolo('B'.repeat(43), {d:location.origin+'/fake-drive',x:{},ai:{}});
                      p.confirmAccount(p.pairing(),'sample@example.com');
                      await (await import('/src/mobile/native.ts')).secretsSaved();
                    }""", [name, batch['at'], hashlib.sha256(plain).hexdigest(), FP, stray_name])
                    page.reload()
                    page.wait_for_function("async()=> (await import('/src/mobile/mirror/pairing.ts')).pairing()?.k === 'B'.repeat(43)")
                    open_group(page, 'Recovery').get_by_role('link', name='Recover a library…', exact=True).click()
                    box.get_by_role('group', name='Unlock with').get_by_role('button', name='File', exact=True).click()
                    with page.expect_file_chooser() as chooser:
                        button('Open recovery file…').click()
                    chooser.value.set_files(str(kit_path))
                    expect(box.locator('#phone-recovery-keep')).to_contain_text('matches its latest backup')
                    before_reconnect = len(writes)
                    button('Reconnect this phone').click()
                    expect(button('Confirm reconnect')).to_be_visible()
                    expect(box.get_by_text("Your phone's content will be kept", exact=False).first).to_be_visible()
                    for theme in ('light', 'dark'):
                        page.evaluate('(v) => document.documentElement.dataset.theme=v', theme)
                        box.scroll_into_view_if_needed()
                        page.screenshot(path=ART / f'390-{theme}-reconnect.png')
                    # Inspect the committed state before the next automatic sync on reload.
                    page.add_init_script("if(sessionStorage.getItem('reconnect-offline')) Object.defineProperty(navigator,'onLine',{value:false});")
                    page.evaluate("sessionStorage.setItem('reconnect-offline','1')")
                    with page.expect_navigation():
                        button('Confirm reconnect').click()
                    assert len(writes) == before_reconnect, 'reconnect wrote Drive'
                    box = open_group(page, 'Recovery')                     # back on Backup & phones: the Recovery group
                    expect(box.get_by_role('button', name='Create another passphrase…', exact=True)).to_be_enabled()      # the recovery file was remembered: a passphrase set, the file not saved from here yet
                    expect(box.get_by_text(re.compile(r'^Passphrase set \d{1,2} \w+$'))).to_be_visible()
                    state = page.evaluate("""async()=>{
                      const p=await import('/src/mobile/mirror/pairing.ts');
                      const {changes, kv}=await import('/src/mobile/store.ts');
                      const vault=await new Promise((ok,bad)=>{const r=indexedDB.open('bp-secrets');r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                      const keys=await new Promise((ok,bad)=>{const r=vault.transaction('kv','readonly').objectStore('kv').getAllKeys();r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                      vault.close();
                      return {pair:p.pairing(), journal:(await changes.all()).map(e=>[e.op,e.state]), rows:(await kv.get('rows')).length,
                        backups:keys.filter(k=>k.startsWith('bp-pair-before-reconnect-')).length, marker:(await kv.get('solo_strays'))??null};
                    }""")
                    assert state['pair']['k'] == KEY and state['pair']['g'] == 'sample@example.com' and state['pair']['solo'] is True
                    assert state['pair']['recovery']['verified'] is False
                    assert state['journal'] == [['link', 'sent'], ['fav', 'queued']] and state['rows'] == 1, (state['journal'], state['rows'])
                    assert state['backups'] == 1 and state['marker'] is None
                    assert all(w.startswith(('vi-phone-recovery-', PREFIX)) for w in writes), writes
                    page.evaluate("sessionStorage.removeItem('reconnect-offline')")
                    page.reload()
                    open_group(page, 'Recovery')
                    expect(box.get_by_role('button', name='Create another passphrase…', exact=True)).to_be_enabled()
                    page.wait_for_function("async()=> {const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried && !phone.refreshing}")
                    page.wait_for_function("async()=> (await (await import('/src/mobile/store.ts')).changes.all()).every(e=>e.state==='sent')")
                    assert len(writes) == before_reconnect + 1, (before_reconnect, len(writes), [w.split('-')[0] for w in writes])
                    assert writes[-1].startswith(PREFIX)
                    assert records['stray-1']['body'] == stray_body
                    page.evaluate("""async () => {
                      const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                      try { await m.drive.getPhoneRecovery('unlisted-secret'); throw Error('accepted arbitrary file'); }
                      catch(e) { if(!e.message.includes('Find the available')) throw e; }
                      try { await m.drive.create('desktop-manifest',new Uint8Array([1])); throw Error('accepted desktop write'); }
                      catch(e) { if(!e.message.includes('only upload their own')) throw e; }
                    }""")
                    assert not errors, errors
                    # Paired phone UI: actual missing-grant handling keeps Google connection visible.
                    paired_ctx = browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True, locale='en-US')
                    paired_ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                    paired_ctx.route(base + '/cards/**', card)
                    paired = dict(v=2,k=KEY,f=FP,c='',e='sample@example.com',ai={},at=0,l='A'*122)
                    paired_ctx.add_init_script("localStorage.setItem('bp-wifi','off'); if(!sessionStorage.getItem('fixture')) {sessionStorage.setItem('fixture','1');sessionStorage.setItem('bp-pair-setup','1');localStorage.setItem('bp-pair'," + json.dumps(json.dumps(paired)) + ");}")
                    def paired_drive(route):
                        if '/about?' in route.request.url:
                            route.fulfill(json={'user':{'emailAddress':'sample@example.com'}})
                        else:
                            assert route.request.method == 'GET', 'Pairing guidance wrote Drive'
                            route.fulfill(json={'files':[]})
                    paired_ctx.route('https://www.googleapis.com/**',paired_drive)
                    paired_page = paired_ctx.new_page()
                    paired_page.on('pageerror',lambda e:errors.append(str(e)))
                    paired_page.goto(base+'/mobile.html#/more')
                    # Settings shows the status card; its kicker opens Settings > Backup & phones, which holds the guide
                    card=paired_page.locator('#m-status')
                    expect(card.get_by_text('Connect Google Drive.',exact=True)).to_be_visible()
                    expect(card.get_by_role('button',name='Connect',exact=True)).to_be_enabled()
                    assert paired_page.locator('#m-desktop').count()==0
                    assert paired_page.locator('#m-pair-setup').count()==0
                    card.get_by_role('link',name='Backup & phones').click()
                    expect(paired_page).to_have_url(base+'/mobile.html#/backup')
                    recovery_guide = open_group(paired_page, 'Recovery').locator('details').first
                    recovery_guide.locator('summary').first.click()
                    recovery_guide.get_by_text('I can still open my library', exact=True).click()
                    expect(recovery_guide.get_by_text('The desktop passphrase is managed on the PC.', exact=False)).to_be_visible()
                    recovery_guide.get_by_text('I have a recovery code or a paired phone', exact=True).click()
                    recovery_guide.get_by_role('button', name='Show recovery code', exact=True).click()
                    expect(paired_page.get_by_label('Recovery code', exact=True)).to_have_value(KEY)
                    guide=paired_page.locator('#m-pair-setup')
                    status=paired_page.locator('#m-backup-status')
                    expect(guide.get_by_text('Finish connecting your PC',exact=True)).to_be_visible()
                    expect(status.get_by_role('button',name='Connect',exact=True)).to_be_enabled()
                    # Synthetic OAuth completion; the real account-confirmation/storage and refresh APIs run.
                    paired_page.evaluate("""async()=>{
                      const P=await import('/src/mobile/mirror/pairing.ts');
                      const N=await import('/src/mobile/native.ts');
                      N.secrets.set('bp-gtoken',JSON.stringify({access:'synthetic',exp:Date.now()+3600000}));
                      const S=await import('/src/mobile/state.svelte.ts');
                      P.confirmAccount(S.mirrorSource.pair,'sample@example.com');await N.secretsSaved();
                      S.phone.tokenAt++;await S.refresh();
                    }""")
                    expect(guide.get_by_text('Google Drive connected: sample@example.com.',exact=True)).to_be_visible()
                    # the access words come from the status model (mirror/phone-state.ts), never the raw refusal text
                    expect(status.get_by_text('Waiting for your PC to confirm this phone.',exact=True)).to_be_visible()
                    expect(guide.get_by_text('Waiting for your PC to confirm this phone.',exact=True)).to_be_visible()
                    expect(status.get_by_role('button',name='Retry',exact=True)).to_be_enabled()
                    assert guide.get_by_role('button').count()==0          # the Status holds the one Retry
                    assert paired_page.get_by_text('to confirm this phone: keep Brainamon open',exact=False).count()==0
                    prev = paired_page.evaluate('location.hash')                 # the lamp is the sync key's name: on the Library
                    paired_page.evaluate("location.hash = '#/lib'")
                    expect(paired_page.locator('.m-sync-key')).to_have_attribute('aria-label', 'Drive · access pending')
                    paired_page.evaluate('h => { location.hash = h }', prev)
                    expect(status.get_by_role('button', name='Retry', exact=True)).to_be_visible()
                    assert paired_page.locator('.m-pad').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                    paired_page.screenshot(path=str(ART/'paired-access-pending.png'))
                    paired_page.reload()
                    expect(guide.get_by_text('Google Drive connected: sample@example.com.',exact=True)).to_be_visible()
                    paired_page.wait_for_function("async()=> {const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried && !phone.refreshing}")
                    # Ready is a UI state fixture, not evidence that missing grants authorize reads.
                    paired_page.evaluate("""async()=>{
                      const S=await import('/src/mobile/state.svelte.ts');
                      const {network,setWifiOnly}=await import('/src/mobile/network.svelte.ts');
                      setWifiOnly(true);
                      network.licenseLocked=false;S.phone.reachable=true;S.phone.tried=true;
                    }""")
                    expect(status.get_by_text('Waiting for Wi-Fi.',exact=True)).to_be_visible()
                    expect(guide.get_by_role('button',name='Done, open library',exact=True)).to_be_enabled()
                    guide.get_by_role('button',name='Done, open library',exact=True).click()
                    assert paired_page.evaluate("sessionStorage.getItem('bp-pair-setup')") is None
                    expect(paired_page).to_have_url(base+'/mobile.html#/lib')
                    paired_ctx.close()
                    assert not errors, errors
                    browser.close()
                    print('Phone recovery UI: generation, enrollment, kit save/verify/reload, discovery, account/password rejection, local-data protection and reconnect passed.')
            finally:
                proc.terminate()
                proc.wait(timeout=15)


if __name__ == '__main__':
    main()
