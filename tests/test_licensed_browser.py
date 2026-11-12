"""Real Settings/fake-Drive UI and browser cryptography in a disposable profile/library."""
import base64
import importlib.util
import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
from tests.phone_pages import open_group  # noqa: E402  (About is a group on the phone's Settings, projects/phone-settings)


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires installed Playwright and Edge')
class LicensedBrowser(unittest.TestCase):
    def test_free_sync_legacy_receipt_fake_drive_updates_and_phone_crypto(self):
        import uvicorn
        from playwright.sync_api import sync_playwright, expect
        from core import app_paths, license, sync_license
        from core.db import Database
        from desktop import updater, autostart
        from library import drive_client, ytdlp, mirror
        from server.app import create_app
        from server.dev_drive import serve
        from tests.license_fixture import activate

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            customer = activate(self, root)
            issuer_keys = list(license.PUBLIC_KEYS)
            key = mirror.MirrorKey.generate()
            signing = sync_license.signer(root / 'signer.pem', create=True)
            with mock.patch('core.sync_license.time.time', return_value=int(time.time())):
                grant = json.loads(sync_license.record(key, signing))
                access = json.loads(sync_license.access_record(key, signing))
                disabled = json.loads(sync_license.access_record(key, signing, False))
            license.remove()
            data = root / 'data'
            db = Database(data / 'content_manager.db')
            db.set_setting('onboard_answer', 'skip')
            db.add_item({'url': 'https://example.invalid/synthetic', 'description': 'Temporary sync fixture'})
            db.close()
            drive = serve(root / 'fake-drive', port=0, account='fixture@example.com')
            self.addCleanup(drive.server_close); self.addCleanup(drive.shutdown)
            base_drive = f'http://127.0.0.1:{drive.server_port}'
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
            app = create_app(data_dir=data, cloud_dir=root / 'cloud', port=port, web_dist=ROOT / 'web/dist')
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False, timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            # No actual sign-in, user settings, registry, production issuer or installer.
            with mock.patch.object(drive_client, 'API', base_drive + '/drive/v3'), \
                 mock.patch.object(drive_client, 'UPLOAD', base_drive + '/upload/drive/v3'), \
                 mock.patch.object(drive_client, 'BATCH', base_drive + '/batch/drive/v3'), \
                 mock.patch.object(drive_client, 'sign_in', return_value={'access_token':'fixture','refresh_token':'fixture','expires_at':4e9}), \
                 mock.patch('core.config.google_client', return_value=('fixture','fixture')), \
                 mock.patch.object(ytdlp, 'registry_get', return_value=''), \
                 mock.patch.object(autostart, 'is_on', return_value=False):
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                origin = f'http://127.0.0.1:{port}'
                (ROOT / 'build').mkdir(exist_ok=True)
                output = Path(tempfile.mkdtemp(prefix='support-review-', dir=ROOT / 'build'))
                output.mkdir(parents=True, exist_ok=True)
                try:
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(channel='msedge', headless=True,
                            args=['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                        try:
                            for theme in ('light','dark'):
                                app.state.writer.call(lambda db: db.set_setting('automatic_updates','1'))
                                ctx = browser.new_context(viewport={'width':1280,'height':900}, color_scheme=theme, locale='en-US')
                                ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                                ctx.route('**/*', lambda route: route.continue_() if route.request.url.startswith((origin+'/',base_drive+'/')) else route.abort())
                                page = ctx.new_page()
                                errors=[]; page.on('pageerror', lambda e: errors.append(str(e)))
                                page.goto(origin + '/#cm-auth=' + app.state.api_token)
                                page.get_by_role('button',name='Brainamon menu').wait_for()
                                page.keyboard.press('Control+Comma')
                                panel = page.locator('#set-panel')
                                page.locator('#set-tbackup').click()
                                # No receipt is needed for backup or paired phone access.
                                expect(panel.get_by_text('Needs a license',exact=True)).to_have_count(0)
                                expect(panel.get_by_role('button',name='Back up to Google Drive',exact=True)).to_be_enabled()
                                panel.get_by_role('button',name='Back up to Google Drive',exact=True).click()
                                board = panel.get_by_role('region', name='Is my library safe')
                                expect(board.get_by_text('fixture@example.com', exact=True)).to_be_visible(timeout=15000)
                                board.get_by_role('button', name='Show Recovery').click()
                                expect(panel.get_by_role('button',name='Recover a library…',exact=True).or_(page.locator('.set-win .cw-foot').get_by_role('button',name='Recover a library…',exact=True)).first).to_be_visible()
                                page.locator('#set-tobsidian').click()
                                self.assertTrue(app.state.sync.status()['licensed'])
                                expect(panel.get_by_text('Choose a vault above first.',exact=False)).to_be_visible()
                                page.locator('#set-tbackup').click()
                                board.get_by_role('button', name='Show Phones').click()
                                expect(panel.get_by_role('button',name='Add a phone',exact=True)).to_be_visible(timeout=15000)
                                panel.get_by_role('button',name='Add a phone',exact=True).click()
                                expect(panel.get_by_role('img',name='Phone pairing QR code')).to_be_visible()
                                page.screenshot(path=str(output / f'desktop-{theme}-free-pairing.png'))
                                fingerprint = mirror.MirrorKey.load(app.state.sync.key_path).fingerprint
                                page.locator('#set-tgeneral').click()
                                expect(page.get_by_text('All features available · support is optional',exact=True)).to_be_visible()
                                page.get_by_text('Legacy receipt for an older phone app',exact=True).click()
                                panel.get_by_label('Legacy receipt key',exact=True).fill(customer)
                                panel.get_by_role('button',name='Save legacy receipt',exact=True).click()
                                expect(panel.get_by_text('Legacy receipt stored',exact=True)).to_be_visible()
                                page.screenshot(path=str(output / f'desktop-{theme}-support.png'))
                                page.get_by_role('button',name='Remove legacy receipt…',exact=True).click()
                                page.get_by_role('alertdialog',name='Remove legacy receipt',exact=True).get_by_role('button',name='Remove receipt',exact=True).click()
                                expect(page.get_by_text('No legacy receipt stored',exact=True)).to_be_visible()
                                self.assertTrue(app.state.sync.status()['licensed'])
                                self.assertEqual(mirror.MirrorKey.load(app.state.sync.key_path).fingerprint, fingerprint)
                                page.locator('#set-tbackup').click()
                                if not panel.get_by_role('img',name='Phone pairing QR code').is_visible():
                                    if board.get_by_role('button', name='Show Phones').is_visible():
                                        board.get_by_role('button', name='Show Phones').click()
                                    panel.get_by_role('button',name='Add a phone',exact=True).click()
                                expect(panel.get_by_role('img',name='Phone pairing QR code')).to_be_visible()
                                # Status comes from the backend even after closing/reopening Settings.
                                app.state.updates.info={'current':'0.2.0','latest':'99.0.0','newer':True,'notes':'Synthetic release notes'}
                                with updater._dl_lock:
                                    updater._dl.update(state='ready',name='Brainamon-Setup-99.0.0.exe',version='99.0.0',done=1,total=1,error='')
                                with mock.patch.object(app_paths,'FROZEN',True):
                                    page.locator('#set-tgeneral').click()
                                    page.reload()
                                    page.get_by_role('button',name='Brainamon menu').wait_for()
                                    page.keyboard.press('Control+Comma')
                                    page.locator('#set-tgeneral').click()
                                    expect(page.get_by_role('button',name='Install and restart',exact=True)).to_be_visible()
                                    expect(page.locator('#set-auto-update')).to_be_checked()
                                    page.locator('#set-auto-update').uncheck()
                                    page.get_by_role('button',name='Later',exact=True).click()
                                    page.keyboard.press('Control+Comma'); page.locator('#set-tgeneral').click()
                                    expect(page.locator('#set-auto-update')).not_to_be_checked()
                                    expect(page.get_by_role('button',name='Install and restart',exact=True)).to_be_visible()
                                    page.locator('#set-s-app-updates').scroll_into_view_if_needed()
                                    page.screenshot(path=str(output / f'desktop-{theme}-updates.png'))
                                # Run the exact verifier in the real Edge crypto engine.
                                transpile = "import ts from './web/node_modules/typescript/lib/typescript.js';import fs from 'node:fs';process.stdout.write(ts.transpileModule(fs.readFileSync('web/src/mobile/mirror/license.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText)"
                                js = subprocess.run(['node','--input-type=module','-e',transpile],cwd=ROOT,capture_output=True,text=True,check=True).stdout
                                result = page.evaluate("""async ({module,grant,access,disabled,fp,pc,issuers}) => {
                                    const {verifyGrant,verifyAccess} = await import('data:text/javascript;base64,'+module)
                                    const now=JSON.parse(grant.body).issued
                                    const expires=await verifyGrant(grant,fp,pc,issuers,now)
                                    let expired=false
                                    try {await verifyGrant(grant,fp,pc,issuers,now+3600)} catch {expired=true}
                                    const v2life=(await verifyAccess(access,fp,pc,now))-now
                                    let disabledRefused=false
                                    try {await verifyAccess(disabled,fp,pc,now)} catch {disabledRefused=true}
                                    return {life:expires-now,expired,v2life,disabledRefused}
                                }""", {'module':base64.b64encode(js.encode()).decode(),'grant':grant,'access':access,'disabled':disabled,'fp':key.fingerprint,'pc':sync_license.public(signing),'issuers':issuer_keys})
                                self.assertEqual(result,{'life':3600,'expired':True,'v2life':3600,'disabledRefused':True})
                                page.set_viewport_size({'width':390,'height':844})
                                page.goto(origin + '/mobile.html#cm-auth=' + app.state.api_token)
                                page.goto(origin + '/mobile.html#/more')
                                page.locator('.m-page-keys').wait_for(timeout=15000)
                                open_group(page, 'About').get_by_role('heading', name='Privacy and licenses').wait_for(timeout=15000)
                                page.screenshot(path=str(output / f'phone-{theme}-local.png'))
                                self.assertEqual(page.evaluate('document.documentElement.scrollWidth > innerWidth'),False)
                                self.assertEqual(errors,[])
                                ctx.close()
                                # Next theme starts without a legacy receipt; current sync stays available.
                                drive_client.private_storage.remove(app.state.sync.token_path)
                                app.state.sync._set(account='')
                        finally:
                            browser.close()
                finally:
                    server.should_exit=True; thread.join(10)
