"""Actual phone entry + native adapter; fresh storage, synthetic secrets, no backend/device.

Run: py -m tests.check_mobile_startup_browser
"""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

BRIDGE = r"""
window.androidBridge = {};
window.__reads = []; window.__writes = []; window.__deadlines = new Map();
const later = window.setTimeout.bind(window), clear = window.clearTimeout.bind(window);
let timerId = -1;
window.setTimeout = (fn, ms, ...args) => {
  if(ms !== 10000) return later(fn, ms, ...args);
  __deadlines.set(--timerId, fn); return timerId;
};
window.clearTimeout = id => { if(!__deadlines.delete(id)) clear(id); };
window.__expire = () => { const [id, fn] = __deadlines.entries().next().value; __deadlines.delete(id); fn(); };
window.__pair = JSON.stringify({v:1,k:'A'.repeat(43),c:'',e:'',f:'synthetic-startup',ai:{openai:'synthetic-ai-key'},at:0,solo:true});
window.__token = JSON.stringify({access:'synthetic-token',exp:1});
if(!sessionStorage.getItem('synthetic-secrets')) sessionStorage.setItem('synthetic-secrets', JSON.stringify({'bp-pair':__pair,'bp-gtoken':__token}));
localStorage.setItem('startup-sentinel','synthetic-kept');
window.__mode = sessionStorage.getItem('bridge-mode') || 'hold';
window.Capacitor = {
  PluginHeaders: ['Brainamon','App'].map(name => ({name, methods: [
    {name:'secretGet',rtype:'promise'}, {name:'secretSet',rtype:'promise'},
    {name:'addListener',rtype:'callback'}, {name:'removeListener',rtype:'promise'}
  ]})),
  nativeCallback() { return 'synthetic-listener'; },
  nativePromise(plugin, method, options) {
    if(method === 'secretGet') {
      return new Promise((resolve,reject) => {
        __reads.push({key:options.key,resolve,reject});
        if(__mode === 'reject-'+options.key) reject(Error('synthetic secret failure'));
        else if(__mode === 'ready') resolve({value:JSON.parse(sessionStorage.getItem('synthetic-secrets'))[options.key]});
      });
    }
    if(method === 'secretSet') {
      __writes.push(options);
      const values = JSON.parse(sessionStorage.getItem('synthetic-secrets'));
      values[options.key] = options.value;
      sessionStorage.setItem('synthetic-secrets',JSON.stringify(values));
    }
    return Promise.resolve({});
  }
};
"""


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-startup-') as folder:
        with open(Path(folder) / 'vite.log', 'w') as log:
            proc = subprocess.Popen(
                ['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port)],
                cwd=ROOT/'web', stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for _ in range(100):
                    try:
                        urlopen(f'http://127.0.0.1:{port}/src/mobile/main.ts', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError('isolated Vite did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, channel='msedge')
                    # Android packaging removes CSP for its inline bridge; model that environment.
                    context = browser.new_context(bypass_csp=True, viewport={'width':390, 'height':844})
                    context.route('https://**/*', lambda r: r.abort())
                    context.route('**/api/**', lambda r: r.abort())

                    def cards(route):
                        rel = route.request.url.split('/cards/', 1)[1].split('?', 1)[0]
                        path = (ROOT/'design/card-designs'/rel).resolve()
                        assert path.is_relative_to((ROOT/'design/card-designs').resolve())
                        route.fulfill(path=path) if path.is_file() else route.abort()

                    context.route(f'http://127.0.0.1:{port}/cards/**', cards)
                    page = context.new_page()
                    page.add_init_script(BRIDGE)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{port}/mobile.html#/jv')
                    page.wait_for_function('__reads.length === 2 && __deadlines.size === 1')
                    assert page.locator('#m-startup').is_visible()
                    assert page.get_by_role('status').inner_text() == 'Loading your saved sign-in...'
                    assert page.locator('#m-app').count() == 0
                    assert not page.get_by_role('button', name='Retry', exact=True).is_visible()
                    page.evaluate("""async () => {
                      const {kv} = await import('/src/mobile/store.ts');
                      await kv.set('startup-sentinel',{note:'synthetic-note',draft:'synthetic-draft'});
                    }""")
                    before = page.evaluate("sessionStorage.getItem('synthetic-secrets')")

                    def failure():
                        page.get_by_role('button', name='Retry', exact=True).wait_for(state='visible')
                        assert 'could not start' in page.locator('#m-startup-title').inner_text()
                        assert page.locator('#m-app').count() == 0
                        assert page.evaluate('__writes.length') == 0, 'failure wrote pairing / started solo'
                        assert page.evaluate("sessionStorage.getItem('synthetic-secrets')") == before

                    def mounted():
                        page.locator('#m-app').wait_for()
                        assert page.locator('nav[aria-label="Sections"]').count() == 1
                        assert page.locator('#m-startup').count() == 0
                        assert page.evaluate('__writes.length') == 0, 'startup replaced saved credentials'
                        assert page.evaluate("sessionStorage.getItem('synthetic-secrets')") == before
                        assert page.evaluate("localStorage.getItem('startup-sentinel')") == 'synthetic-kept'
                        assert page.evaluate("async () => (await import('/src/mobile/store.ts')).kv.get('startup-sentinel')") == {'note':'synthetic-note','draft':'synthetic-draft'}

                    # Timeout, then obsolete callbacks arrive before/during a held retry.
                    page.evaluate('__expire()')
                    failure()
                    page.evaluate('__reads[0].resolve({value:null})')
                    page.get_by_role('button', name='Retry', exact=True).click()
                    page.wait_for_function('__reads.length === 4')
                    assert not page.get_by_role('button', name='Retry', exact=True).is_visible()
                    page.evaluate('__reads[1].resolve({value:null})')
                    assert page.locator('#m-app').count() == 0
                    page.evaluate("__reads.slice(2).forEach(r => r.resolve({value:r.key==='bp-pair'?__pair:__token}))")
                    mounted()

                    # After a successful retry, old callbacks cannot replace its cache either.
                    page.reload()
                    page.wait_for_function('__reads.length === 2 && __deadlines.size === 1')
                    page.evaluate('__expire()')
                    failure()
                    page.evaluate("__mode='ready'")
                    page.get_by_role('button', name='Retry', exact=True).click()
                    mounted()
                    page.evaluate('__reads.slice(0,2).forEach(r => r.resolve({value:null}))')
                    assert page.evaluate("async () => (await import('/src/mobile/native.ts')).secrets.get('bp-pair') === __pair")
                    assert page.evaluate("async () => (await import('/src/mobile/native.ts')).secrets.get('bp-gtoken') === __token")

                    # Each rejected secret blocks boot; explicit keyboard Retry recovers in place.
                    for key in ('bp-pair', 'bp-gtoken'):
                        page.evaluate('(mode) => sessionStorage.setItem("bridge-mode",mode)', 'reject-'+key)
                        page.reload()
                        failure()
                        assert page.evaluate('__reads.length') == 2
                        page.evaluate("__mode='ready'")
                        page.get_by_role('button', name='Retry', exact=True).press('Enter')
                        mounted()
                    page.evaluate("sessionStorage.setItem('bridge-mode','ready')")
                    for _ in range(3):
                        page.reload()
                        mounted()
                    # Failed imports are cached by ESM; this Retry must reload the page.
                    page.route('**/src/mobile/Mobile.svelte*', lambda r: r.abort())
                    page.reload()
                    failure()
                    page.unroute('**/src/mobile/Mobile.svelte*')
                    with page.expect_navigation():
                        page.get_by_role('button', name='Retry', exact=True).click()
                    mounted()
                    # A held module also expires; its eventual completion must not mount the app.
                    held = []
                    page.route('**/src/mobile/Mobile.svelte*', lambda r: held.append(r))
                    page.reload(wait_until='domcontentloaded')
                    page.wait_for_function('__deadlines.size === 1 && __reads.length === 2')
                    assert len(held) == 1
                    page.evaluate('__expire()')
                    failure()
                    held.pop().continue_()
                    page.evaluate("async () => { await import('/src/mobile/Mobile.svelte') }")
                    assert page.locator('#m-app').count() == 0
                    page.unroute('**/src/mobile/Mobile.svelte*')
                    with page.expect_navigation():
                        page.get_by_role('button', name='Retry', exact=True).click()
                    mounted()
                    assert not errors, errors
                    # Browser startup still migrates synthetic legacy pairing to the sealed vault.
                    pwa = context.new_page()
                    pwa.on('pageerror', lambda error: errors.append(str(error)))
                    pwa.add_init_script("""if(!sessionStorage.getItem('pwa-seeded')) {
                      localStorage.setItem('bp-pair',JSON.stringify({v:1,k:'A'.repeat(43),c:'',e:'',f:'synthetic-pwa',ai:{},at:0,solo:true}));
                      sessionStorage.setItem('pwa-seeded','yes');
                    }""")
                    pwa.goto(f'http://127.0.0.1:{port}/mobile.html#/jv')
                    pwa.locator('#m-app').wait_for()
                    assert pwa.evaluate("localStorage.getItem('bp-pair')") is None
                    assert pwa.evaluate("async () => JSON.parse((await import('/src/mobile/native.ts')).secrets.get('bp-pair')).f") == 'synthetic-pwa'
                    pwa.reload()
                    pwa.locator('#m-app').wait_for()
                    assert pwa.evaluate("async () => JSON.parse((await import('/src/mobile/native.ts')).secrets.get('bp-pair')).f") == 'synthetic-pwa'
                    assert not errors, errors
                    print('PASS: visible loading; held/rejected reads; explicit Retry; stale callbacks; credentials/storage preserved; 3 healthy reloads; failed/held module recovery; browser vault startup/reload; zero page errors')
                    browser.close()
            finally:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                else:
                    proc.terminate()
                proc.wait(timeout=10)


if __name__ == '__main__':
    main()
