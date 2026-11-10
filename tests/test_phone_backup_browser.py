"""Built phone UI: isolated Drive backup, recovery and protection of existing local content."""
import importlib.util
import json
import socket
import tempfile
import threading
import time
import unittest
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
from tests.phone_groups import open_group  # noqa: E402  (This phone is a group on Backup & phones, projects/phone-settings)


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires Playwright and Edge')
class PhoneBackupBrowser(unittest.TestCase):
    def test_separate_backup_and_restore_without_a_license(self):
        import uvicorn
        from playwright.sync_api import sync_playwright, expect
        from core import license
        from library import mirror
        from server.app import create_app
        from tests.test_sync import FakeDrive

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            with mock.patch.object(license, 'LICENSE_PATH', root / 'no-license'):
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
                app = create_app(data_dir=root / 'data', cloud_dir=root / 'cloud', port=port, web_dist=ROOT / 'web/dist')
                server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False, timeout_graceful_shutdown=1))
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 5
                    while not server.started and thread.is_alive() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(server.started)
                    origin = f'http://127.0.0.1:{port}'
                    drive = FakeDrive()
                    pc, phone_key = mirror.MirrorKey.generate(), mirror.MirrorKey.generate()
                    desktop = drive.put(pc.name(mirror.MANIFEST), pc.seal(mirror.MANIFEST, b'private desktop fixture'))
                    original = drive.files[desktop]
                    token = {'access': 'synthetic', 'exp': 4e12}
                    errors = []

                    def route_request(route):
                        request = route.request
                        if request.url.startswith(origin + '/'):
                            return route.continue_()
                        url = urlsplit(request.url)
                        if url.hostname != 'www.googleapis.com':
                            return route.abort()
                        if url.path == '/drive/v3/about':
                            return route.fulfill(json={'user': {'emailAddress': 'fixture@example.com'}})
                        if request.method == 'POST' and url.path == '/upload/drive/v3/files':
                            message = BytesParser(policy=default).parsebytes(
                                ('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode() + request.post_data_buffer)
                            meta, body = list(message.iter_parts())
                            name = json.loads(meta.get_payload(decode=True))['name']
                            self.assertRegex(name, r'^solo-[0-9a-f]{32}-[0-9a-f]{32}$')
                            return route.fulfill(json={'id': drive.upload(name, body.get_payload(decode=True))})
                        if url.path == '/drive/v3/files' and request.method == 'GET':
                            return route.fulfill(json={'files': drive.list()})
                        if url.path.startswith('/drive/v3/files/') and request.method == 'GET':
                            fid = url.path.rsplit('/', 1)[1]
                            self.assertNotEqual(fid, desktop, 'Standalone backup read the desktop mirror')
                            return route.fulfill(body=drive.download(fid), content_type='application/octet-stream')
                        raise AssertionError('Unexpected Drive operation: ' + request.method + ' ' + request.url)

                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(channel='msedge', headless=True,
                            args=['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                        try:
                            def context(key, connected, theme):
                                ctx = browser.new_context(viewport={'width':390,'height':844}, color_scheme=theme, locale='en-US')
                                ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                                pair = {'v':2,'k':key.text(),'f':key.fingerprint,'c':'','e':'','ai':{},'at':0,'solo':True}
                                if connected:
                                    pair['g'] = 'fixture@example.com'
                                seed = {'bp-pair':json.dumps(pair),'bp-wifi':'off'}
                                if connected:
                                    seed['bp-gtoken'] = json.dumps(token)
                                ctx.add_init_script(script="if (!sessionStorage.getItem('seeded')) { for (const [k,v] of Object.entries(" + json.dumps(seed) + ")) localStorage.setItem(k,v); sessionStorage.setItem('seeded','1'); }")
                                ctx.route('**/*', route_request)
                                page = ctx.new_page()
                                page.on('pageerror', lambda e: errors.append(str(e)))
                                page.goto(origin + '/mobile.html#/backup')
                                expect(page.get_by_role('heading', name='Google account', exact=False)).to_be_visible()
                                return ctx, page

                            source_ctx, page = context(phone_key, True, 'light')
                            page.evaluate("""async () => {
                              const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)})
                              await new Promise((ok,bad)=>{const t=db.transaction('changes','readwrite'),s=t.objectStore('changes');
                                s.add({op:'link',uid:'ab'.repeat(16),url:'https://example.invalid/phone',note:'Phone only',at:Date.now(),state:'queued'});
                                s.add({op:'note',file:'phone-only.md',title:'Phone note',body:'Keep this phone note',at:Date.now(),state:'queued'});
                                t.oncomplete=ok;t.onerror=()=>bad(t.error)})
                              db.close()
                            }""")
                            page.reload()
                            expect(page.get_by_text('1 item on this phone', exact=True)).to_be_visible(timeout=15000)
                            open_group(page, 'This phone')
                            expect(page.get_by_text('All backed up', exact=True)).to_be_visible()
                            expect(page.get_by_text('1 item on this phone', exact=True)).to_be_visible()
                            expect(page.get_by_text('This account also has a desktop library.', exact=False)).to_be_visible()
                            self.assertEqual(drive.files[desktop], original)
                            self.assertEqual(len(drive.files), 2)
                            output = ROOT / 'build/solo-backup-review'
                            output.mkdir(parents=True, exist_ok=True)
                            open_group(page, 'Google account')
                            page.locator('#m-conn').screenshot(path=str(output / 'backup-light.png'))
                            page.get_by_role('button', name='Disconnect', exact=True).click()
                            page.get_by_role('button', name='Confirm disconnect', exact=True).click()
                            expect(page.get_by_role('button', name='Back up to Google Drive', exact=True)).to_be_visible()
                            open_group(page, 'Recovery').get_by_role('link', name='Recover a library…', exact=True).click()
                            page.get_by_role('group', name='Unlock with').get_by_role('button', name='Code', exact=True).click()
                            page.get_by_role('textbox', name='Original recovery code').fill(phone_key.text())
                            page.get_by_role('button', name='Find backup', exact=True).click()
                            expect(page.locator('#phone-recovery-keep')).to_contain_text('not connected to Google Drive')   # not connected: only Restore on an empty phone
                            page.get_by_role('button', name='Restore on an empty phone', exact=True).click()
                            expect(page.get_by_role('alert')).to_contain_text('empty phone')
                            page.get_by_role('button', name='Back', exact=True).click()
                            expect(page.get_by_text('1 item on this phone', exact=True)).to_be_visible()
                            source_ctx.close()

                            restore_ctx, page = context(mirror.MirrorKey.generate(), False, 'dark')
                            open_group(page, 'Recovery').get_by_role('link', name='Recover a library…', exact=True).click()
                            page.get_by_role('group', name='Unlock with').get_by_role('button', name='Code', exact=True).click()
                            page.get_by_role('textbox', name='Original recovery code').fill(phone_key.text())
                            page.get_by_role('button', name='Find backup', exact=True).click()
                            expect(page.locator('#phone-recovery-keep')).to_contain_text('not connected to Google Drive')   # not connected: only Restore on an empty phone
                            page.get_by_role('button', name='Restore on an empty phone', exact=True).click()
                            expect(page.get_by_text('Recovery code accepted.', exact=False)).to_be_visible()
                            page.evaluate('(t)=>localStorage.setItem("bp-gtoken",JSON.stringify(t))', token)
                            page.reload()
                            expect(page.get_by_text('1 item on this phone', exact=True)).to_be_visible(timeout=15000)
                            open_group(page, 'This phone')
                            expect(page.get_by_text('All backed up', exact=True)).to_be_visible()
                            restored = page.evaluate("""async () => {
                              const db=await new Promise(ok=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result)})
                              const rows=await new Promise(ok=>{const r=db.transaction('changes','readonly').objectStore('changes').getAll();r.onsuccess=()=>ok(r.result)})
                              db.close();return rows
                            }""")
                            self.assertTrue(any(r.get('body') == 'Keep this phone note' for r in restored))
                            self.assertEqual(drive.files[desktop], original)
                            self.assertEqual(len(drive.files), 2, 'Restore must not re-upload or replace the other library')
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                            page.locator('#m-conn').screenshot(path=str(output / 'restored-dark.png'))
                            self.assertEqual(errors, [])
                            restore_ctx.close()
                        finally:
                            browser.close()
                finally:
                    server.should_exit = True
                    thread.join(10)
