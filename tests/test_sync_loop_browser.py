"""Disposable, child-process browser gate for intake during a blocked Drive publish.

Run: py -m unittest tests.test_sync_loop_browser
The development build and synthetic issuer trust exist only below the temporary root.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SyncLoopBrowser(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires Playwright and Edge')
    def test_phone_edit_during_blocked_publish_is_acknowledged_on_refresh(self):
        with tempfile.TemporaryDirectory(prefix='sync-loop-browser-') as folder:
            root = Path(folder)
            for name in ('home', 'data', 'tmp', 'appdata', 'localappdata'):
                (root / name).mkdir()
            env = {**os.environ, 'BRAINAMON_HOME': str(root / 'home'), 'CM_DATA_DIR': str(root / 'data'),
                   'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
                   'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
                   'APPDATA': str(root / 'appdata'), 'LOCALAPPDATA': str(root / 'localappdata')}
            result = subprocess.run([sys.executable, '-m', 'tests.test_sync_loop_browser', '--fixture', str(root)],
                                    cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
            if result.returncode == 77:
                self.skipTest(result.stdout.strip())
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-6000:])
            self.assertIn('PASS: blocked intake, follow-up manifest, compatible phone prune', result.stdout)
            print(result.stdout.strip())


def fixture(root):
    # This function runs only in the child, after the runner sets the home and library.
    import socket
    import threading
    import time
    from unittest import mock
    import uvicorn
    from playwright.sync_api import sync_playwright, expect, Error
    from core import app_paths, license
    from core.db import Database
    from library import drive_client, mirror, recovery
    from library.export_targets import DriveMirrorTarget
    from server import sync as sync_mod
    from server.app import create_app
    from server.dev_drive import serve
    from tests.license_fixture import activate

    check = unittest.TestCase()
    check.assertTrue(app_paths.HOME.is_relative_to(root))
    check.assertTrue(app_paths.data_dir().is_relative_to(root))
    activate(check, root)
    # Build the existing app with an explicit test-only development transport and issuer.
    script = """import {build} from 'vite';
      await build({configFile:'vite.config.ts',logLevel:'error',
        define:{'import.meta.env.DEV':'true',__LICENSE_PUBLIC_KEYS__:process.argv[2]},
        build:{outDir:process.argv[1],emptyOutDir:true}})"""
    subprocess.run(['node', '--input-type=module', '-e', script, str(root / 'web'), json.dumps(license.PUBLIC_KEYS)],
                   cwd=ROOT / 'web', check=True, capture_output=True, text=True, timeout=90)
    data, cloud = root / 'data', root / 'cloud'
    db = Database(data / 'content_manager.db')
    item = db.add_item({'url': 'https://example.invalid/seed', 'description': 'Disposable browser seed'})
    uid = db.conn.execute('SELECT uid FROM items WHERE id=?', (item,)).fetchone()[0]
    db.set_setting('onboard_answer', 'skip')
    db.set_setting('automatic_updates', '0')
    db.close()
    drive = serve(root / 'fake-drive', port=0, account='fixture@example.com')
    base = f'http://127.0.0.1:{drive.server_port}'
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    app = create_app(data_dir=data, cloud_dir=cloud, port=port, web_dist=root / 'web')
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                          access_log=False, timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, daemon=True)
    release, entered = threading.Event(), threading.Event()
    page = None
    original_connect = socket.socket.connect
    def loopback_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise AssertionError('Fixture refused non-loopback connection')
        return original_connect(sock, address)
    def wait_for(predicate, label, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            if page is None:
                time.sleep(.02)
            else:
                page.wait_for_timeout(20)   # dispatch browser routes while polling the Writer
        if page is not None:
            print(page.locator('body').inner_text(), flush=True)
            print(app.state.sync.status(), flush=True)
        raise AssertionError(label)

    with mock.patch.object(drive_client, 'API', base + '/drive/v3'), \
            mock.patch.object(drive_client, 'UPLOAD', base + '/upload/drive/v3'), \
            mock.patch('core.config.google_client', return_value=('fixture', 'fixture')), \
            mock.patch.object(socket.socket, 'connect', loopback_only), \
            mock.patch.object(DriveMirrorTarget, 'TICK_EVERY', .05), \
            mock.patch.object(sync_mod, 'INTAKE', .05), mock.patch.object(sync_mod, 'INTAKE_MAX', .1), \
            mock.patch.object(sync_mod, 'POLL', .05):
        try:
            thread.start()
            wait_for(lambda: server.started, 'fixture server startup failed')
            svc = app.state.sync
            drive_client.save_token(svc.token_path, {'access_token': 'fixture', 'refresh_token': 'fixture', 'expires_at': 4e9})
            kit = svc.recovery.enroll('Disposable browser recovery passphrase', 'Disposable browser recovery passphrase')
            svc.recovery.verify_kit(recovery.dump(kit).decode())
            check.assertTrue(svc.recovery.status()['verified'])
            key = svc.mirror_key()
            svc._start_control()
            client = svc._client(drive_client.load_token(svc.token_path))
            from core import sync_license
            wait_for(lambda: any(f['name'] == key.name(sync_license.LOGICAL) for f in client.list()),
                     'fixture control grant was not published')
            check.assertTrue(svc._publish(), svc.status()['error'])
            origin = f'http://127.0.0.1:{port}'
            pair = {'v': 2, 'k': key.text(), 'f': key.fingerprint, 'l': svc.license_public_key(),
                    'c': '', 'e': 'fixture@example.com', 'g': 'fixture@example.com', 'd': base, 'ai': {}, 'at': 0}
            errors = []
            with sync_playwright() as pw:
                try:
                    ctx = pw.chromium.launch_persistent_context(str(root / 'browser-profile'), channel='msedge', headless=True,
                        viewport={'width': 390, 'height': 844},
                        args=['--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                except Error as e:
                    if 'Executable' in str(e) or 'not found' in str(e):
                        raise unittest.SkipTest('Edge unavailable: ' + str(e).splitlines()[0]) from e
                    raise
                try:
                    ctx.route('**/*', lambda route: route.continue_() if route.request.url.startswith((origin + '/', base + '/')) else route.abort())
                    ctx.add_init_script('if (!localStorage.getItem("fixture-seeded")) {' +
                        'localStorage.setItem("bp-pair",' + json.dumps(json.dumps(pair)) + ');' +
                        'localStorage.setItem("bp-wifi","off");localStorage.setItem("fixture-seeded","1");}')
                    page = ctx.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(origin + '/mobile.html#cm-auth=' + app.state.api_token)
                    page.locator('#m-app').wait_for()
                    page.evaluate("location.hash='/backup'")
                    try:
                        expect(page.locator('#m-library').get_by_text('1 items · the PC uploaded', exact=False)).to_be_visible(timeout=15000)
                    except AssertionError:
                        print(page.locator('body').inner_text(), flush=True)
                        raise
                    # Gate a real upload after a readable seed mirror exists. The loop owns all work.
                    original_upload = drive_client.DriveClient.upload
                    def blocked(client, name, *args, **kwargs):
                        if name == key.name(f'items/{uid}.json') and not release.is_set():
                            entered.set()
                            if not release.wait(30):
                                raise AssertionError('browser did not release fixture upload')
                        return original_upload(client, name, *args, **kwargs)
                    with mock.patch.object(drive_client.DriveClient, 'upload', blocked):
                        app.state.writer.call(lambda db: db.update_item(item, {'description': 'Trigger blocked upload'}))
                        # The optional thumbnail job is excluded; this test validates sync, not website fetching.
                        svc.on_new_links = lambda ids: True
                        svc.turn_on()
                        check.assertTrue(entered.wait(10), 'no upload entered the gate')
                        page.evaluate("location.hash='/cap'")
                        page.get_by_label('Your content', exact=True).fill('https://example.invalid/from-phone')
                        page.get_by_role('radio', name='Library item', exact=True).check()
                        page.get_by_role('button', name='Save to Library', exact=True).click()
                        expect(page.get_by_text('Saved as a Library item', exact=True)).to_be_visible()
                        page.evaluate("location.hash='/backup'")
                        send = page.get_by_role('button', name='Send now', exact=True)
                        if send.is_enabled():
                            send.click()
                        wait_for(lambda: app.state.writer.read(lambda db: db.conn.execute(
                            "SELECT COUNT(*) FROM items WHERE url='https://example.invalid/from-phone'").fetchone()[0]) == 1,
                            'phone edit did not land during blocked upload')
                        check.assertFalse(release.is_set())
                        check.assertTrue(svc.running)
                        check.assertEqual(svc.status()['state'], 'publishing')
                        wait_for(lambda: svc._force_manifest, 'intake did not request follow-up manifest')
                        device = page.evaluate('localStorage.getItem("bp-device")')
                        release.set()
                        client = svc._client(drive_client.load_token(svc.token_path))
                        def acknowledged():
                            found = next(f for f in client.list() if f['name'] == key.name(mirror.MANIFEST))
                            man = json.loads(key.open(mirror.MANIFEST, client.download(found['id'])))
                            # Delivery 2 (docs/superpowers/plans/2026-10-31-phone-backup-phones/02-s5-resend-after-pairing-again.md):
                            # a numbered change file is acknowledged by the manifest's receipts; only legacy files move `applied`
                            return man['items'] == 2 and any(r['device'] == device and r['seq'] >= 1 for r in man.get('receipts', {}).values())
                        wait_for(acknowledged, 'follow-up manifest did not contain item and acknowledgement')
                    page.evaluate("location.hash='/more'")
                    page.get_by_role('button', name='Sync now', exact=True).first.click()
                    page.evaluate("location.hash='/backup'")
                    expect(page.locator('#m-library').get_by_text('2 items · the PC uploaded', exact=False)).to_be_visible(timeout=15000)
                    page.wait_for_function("""async () => {
                      const db = await new Promise(ok => { const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result) })
                      const rows = await new Promise(ok => { const r=db.transaction('changes','readonly').objectStore('changes').getAll();r.onsuccess=()=>ok(r.result) })
                      db.close();return rows.length === 0
                    }""")
                    check.assertEqual(errors, [])
                    print('PASS: blocked intake, follow-up manifest, compatible phone prune', flush=True)
                finally:
                    release.set()
                    ctx.close()
        finally:
            release.set()
            server.should_exit = True
            thread.join(15)
            drive.shutdown()
            drive.server_close()
            check.doCleanups()
            check.assertFalse(thread.is_alive(), 'fixture server did not stop')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--fixture':
        try:
            fixture(Path(sys.argv[2]).resolve())
        except unittest.SkipTest as e:
            print(str(e))
            sys.exit(77)
    else:
        unittest.main()
