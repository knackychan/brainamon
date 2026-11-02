"""Isolated mobile Wi-Fi policy, queue preservation and progress reminder. No real Drive/account.

Run: py -m tests.check_mobile_network_browser
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'local/ui-blocks/shots/mobile-wifi'

PROXIED = ('/api', '/thumb', '/cards', '/files', '/wiskit')
PUBLIC = (ROOT / 'web/public').resolve()
INIT = r"""
window.__connection = new EventTarget(); __connection.type = 'cellular';
Object.defineProperty(navigator, 'connection', {value: __connection});
window.__network = type => { __connection.type = type; __connection.dispatchEvent(new Event('change')); };
if (!localStorage.getItem('bp-pair')) localStorage.setItem('bp-pair', JSON.stringify({
  v:2,k:'A'.repeat(43),c:'',e:'',f:'4242b08871e4',ai:{},at:0,solo:true,d:location.origin+'/fake-drive'
}));
"""


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-wifi-') as temp:
        with open(Path(temp) / 'vite.log', 'w') as log:
            script = '''import {createServer} from 'vite';
              const proxy = Object.fromEntries(JSON.parse(process.argv[2]).map(p => [p, 'http://127.0.0.1:0']));
              const s = await createServer({configFile:'vite.config.ts', server:{host:'127.0.0.1',
                port:Number(process.argv[1]), strictPort:true, proxy}}); await s.listen();'''
            proc = subprocess.Popen(['node', '--input-type=module', '-e', script, str(port), json.dumps(PROXIED)],
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
                    context = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True,
                                                  service_workers='block')
                    context.add_init_script(INIT)
                    calls, errors, unexpected = [], [], []

                    def guarded(route):
                        path = urlparse(route.request.url).path
                        if route.request.url.startswith(base + '/') and not path.startswith(PROXIED):
                            return route.continue_()
                        if route.request.url.startswith(base + '/'):
                            public = (PUBLIC / path.lstrip('/')).resolve()
                            if public.is_relative_to(PUBLIC) and public.is_file():
                                return route.fulfill(path=public)
                            if path.startswith('/thumb/'):
                                return route.fulfill(status=503, body='')
                        unexpected.append(path)
                        return route.abort()

                    context.route('**/*', guarded)

                    def drive(route):
                        calls.append(route.request.method)
                        route.fulfill(json={'id': 'synthetic-change'} if route.request.method == 'POST' else {'files': []})

                    context.route(base + '/fake-drive/**', drive)
                    def cards(route):
                        path = (ROOT / 'design/card-designs' / route.request.url.split('/cards/', 1)[1].split('?', 1)[0]).resolve()
                        assert path.is_relative_to((ROOT / 'design/card-designs').resolve())
                        route.fulfill(path=path) if path.is_file() else route.abort()
                    context.route(base + '/cards/**', cards)
                    page = context.new_page()
                    page.set_default_timeout(10000)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/mobile.html#/more')
                    toggle = page.get_by_role('button', name='Wi-Fi only', exact=True)
                    toggle.wait_for()
                    assert toggle.get_attribute('aria-pressed') == 'true'
                    assert toggle.bounding_box()['height'] >= 44
                    assert calls == [], calls
                    assert page.get_by_role('button', name='Sync now', exact=True).is_disabled()
                    page.screenshot(path=ART / '360-more-light.png')
                    page.evaluate("document.documentElement.dataset.theme = 'dark'")
                    page.screenshot(path=ART / '360-more-dark.png')

                    # Save an edit locally, then reload while still on cellular.
                    page.evaluate("""async () => {
                      const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                      await m.changes.add({op:'link',uid:'synthetic-link',url:'https://example.com/queued',note:'Kept on phone',category:''});
                      m.flushSoon(0);
                    }""")
                    page.reload()
                    toggle.wait_for()
                    page.evaluate("location.hash = '#/lib'")
                    strip = page.locator('.m-strip')
                    strip.wait_for()
                    assert 'waiting for Wi-Fi' in strip.inner_text()
                    assert strip.bounding_box()['y'] + strip.bounding_box()['height'] <= page.locator('.m-main').bounding_box()['y'] + 1
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=ART / '360-strip-light.png')
                    assert calls == [], calls
                    page.wait_for_function("""async () => {
                      const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                      await m.changes.load(); return m.changes.unsent === 1;
                    }""")
                    page.evaluate("__network('wifi')")
                    page.wait_for_function("""async () => {
                      const {mirrorSource:m,phone}=await import('/src/mobile/state.svelte.ts');
                      return !phone.refreshing && m.changes.unsent === 0;
                    }""")
                    assert 'POST' in calls, calls
                    assert strip.count() == 0

                    page.evaluate("__network('cellular')")
                    strip.wait_for()
                    page.evaluate("location.hash = '#/more'")
                    toggle.click()
                    assert toggle.get_attribute('aria-pressed') == 'false'
                    page.reload()
                    toggle.wait_for()
                    assert toggle.get_attribute('aria-pressed') == 'false'
                    page.wait_for_function("""async () => !(await import('/src/mobile/state.svelte.ts')).phone.refreshing""")
                    assert page.get_by_role('button', name='Sync now', exact=True).is_enabled()

                    page.evaluate("__network('unknown')")
                    toggle.click()
                    page.get_by_text('Wi-Fi could not be confirmed.', exact=False).wait_for()
                    page.evaluate("location.hash = '#/lib'")
                    strip.wait_for()
                    assert 'cannot confirm Wi-Fi' in strip.inner_text()
                    page.set_viewport_size({'width': 800, 'height': 900})
                    page.screenshot(path=ART / '800-strip-light.png')
                    assert not unexpected, unexpected
                    assert not errors, errors
                    browser.close()
                    print(json.dumps({'drive_calls': calls, 'queued_edit_uploaded_after_wifi': True, 'page_errors': errors, 'screenshots': str(ART)}))
            finally:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == '__main__':
    main()
