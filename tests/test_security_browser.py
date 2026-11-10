"""Built desktop/panel/phone transports in an isolated headless Edge profile."""
import importlib.util
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / 'web/dist'


@unittest.skipUnless(importlib.util.find_spec('playwright') and (WEB_DIST / 'index.html').is_file(),
                     'requires installed Playwright/Edge and the isolated production web build')
class BrowserTransports(unittest.TestCase):
    def test_fetch_sse_images_video_and_unrelated_browser_context(self):
        import uvicorn
        from PIL import Image
        from playwright.sync_api import sync_playwright
        from core.db import Database
        from server.app import create_app
        from library import ytdlp
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            from tests.license_fixture import activate
            activate(self, Path(folder))
            data = Path(folder) / 'data'
            db = Database(data / 'content_manager.db')
            item = db.add_item({'url': 'https://example.invalid/synthetic', 'description': 'Synthetic transport fixture'})
            Image.new('RGB', (2, 2)).save(db.item_dir(item) / 'thumb.jpg')
            db.update_item(item, {'thumb_path': 'thumb.jpg'})
            (db.item_dir(item) / 'video').mkdir()
            (db.item_dir(item) / 'video/synthetic.mp4').write_bytes(b'synthetic-video-for-range-request')
            db.close()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            app = create_app(data_dir=data, cloud_dir=Path(folder) / 'cloud', port=port,
                             web_dist=WEB_DIST)
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False, timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            with mock.patch.object(ytdlp, 'registry_get', return_value=''):
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                origin = f'http://127.0.0.1:{port}'
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(channel='msedge', headless=True,
                            args=['--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                        try:
                            context = browser.new_context(locale='en-US')
                            context.add_init_script("localStorage.setItem('bp-lang','en')")
                            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                            page = context.new_page()
                            replies = []
                            page.on('response', lambda response: replies.append((__import__('urllib.parse', fromlist=['urlsplit']).urlsplit(response.url).path, response.status)))
                            for path in ('/', '/panel.html', '/mobile.html'):
                                try:
                                    page.goto(origin + path + '#cm-auth=' + app.state.api_token, wait_until='domcontentloaded')
                                except Exception:
                                    raise AssertionError('Synthetic browser bootstrap failed; credential URL omitted') from None
                                page.wait_for_function("() => !location.hash.startsWith('#cm-auth=') && !!navigator.serviceWorker.controller", timeout=15000)
                                self.assertEqual(page.evaluate("async()=> (await fetch('/api/items')).status"), 200)
                                self.assertTrue(page.evaluate(f"""()=>new Promise(resolve=>{{const img=new Image();img.onload=()=>resolve(true);img.onerror=()=>resolve(false);img.src='/thumb/{item}'}})"""), str([(p, status) for p, status in replies if p.startswith(('/api/', '/thumb/'))][-12:]))
                                self.assertEqual(page.evaluate(f"async()=> (await fetch('/files/items/{item}/thumb.jpg',{{headers:{{Range:'bytes=0-8'}}}})).status"), 206)
                                self.assertTrue(page.evaluate("""()=>new Promise(resolve=>{const es=new EventSource('/api/events');const timer=setTimeout(()=>{es.close();resolve(false)},3000);es.addEventListener('hello',()=>{clearTimeout(timer);es.close();resolve(true)})})"""))
                            # Stop worker memory, then exercise browser media requests that cannot set headers.
                            cdp = context.new_cdp_session(page)
                            cdp.send('ServiceWorker.enable')
                            cdp.send('ServiceWorker.stopAllWorkers')
                            self.assertTrue(page.evaluate(f"""()=>new Promise(resolve=>{{const img=new Image();img.onload=()=>resolve(true);img.onerror=()=>resolve(false);img.src='/thumb/{item}?restart=1'}})"""))
                            cdp.detach()
                            import base64, json
                            from library import mirror
                            key = mirror.MirrorKey.generate()
                            code = base64.urlsafe_b64encode(json.dumps({'v': 2, 'k': key.text(), 'f': key.fingerprint, 'c': '', 'e': '', 'd': 'http://127.0.0.1:18766'}).encode()).rstrip(b'=').decode()
                            page.goto(origin + '/panel.html', wait_until='domcontentloaded')
                            page.goto(origin + '/mobile.html#pair=' + code, wait_until='domcontentloaded')
                            page.wait_for_function("() => document.body.textContent.includes('That pairing code could not be read')", timeout=10000)
                            unauthenticated = context.new_page()
                            try:
                                unauthenticated.goto(origin + '/panel.html', wait_until='domcontentloaded')
                                self.assertEqual(unauthenticated.evaluate("async()=> (await fetch('/api/items')).status"), 403)
                            finally:
                                unauthenticated.close()
                            # Another browser profile has no bootstrap, including SSE and file routes.
                            unrelated = browser.new_context()
                            try:
                                for path in ('/api/items', '/api/events', '/thumb/1', '/api/items/1/video'):
                                    response = unrelated.request.get(origin + path)
                                    self.assertEqual(response.status, 403)
                            finally:
                                unrelated.close()
                            context.close()
                        finally:
                            browser.close()
                finally:
                    server.should_exit = True
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
