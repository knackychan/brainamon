"""Built UI smoke test in a disposable library. Installs and site requests are mocked."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from unittest import mock

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SERVER = '''
import sys
from pathlib import Path
from core import app_paths, config, site_sessions
root=Path(sys.argv[1]); port=int(sys.argv[2])
app_paths.LOCAL=root/'local'; app_paths.LOCAL.mkdir()
app_paths.TOOLS_POINTER=app_paths.LOCAL/'tools.json'
app_paths.CACHE=app_paths.LOCAL/'cache'; app_paths.ERROR_LOG=app_paths.LOCAL/'error_log.txt'
site_sessions.ROOT=app_paths.LOCAL/'site-sessions'
config.ENV_PATH=root/'absent.env'
# Synthetic test credentials stay in this disposable folder; DPAPI is outside this UI check.
site_sessions._crypt = lambda raw, decrypt=False: raw
from server.app import create_app
import uvicorn
uvicorn.run(create_app(data_dir=root/'data', port=port, cloud_dir=root/'cloud'), host='127.0.0.1', port=port, log_level='warning')
'''


def check_scrapers(page, opened, runtime, out):
    """Exercise the live Expand UI without launching a site, watcher or import."""
    previous_runtime = dict(runtime)
    out = out / 'scraper-expand'
    out.mkdir(parents=True, exist_ok=True)
    launches, playlists, watches = [], [], []
    def start(route):
        launches.append(route.request.post_data_json)
        route.fulfill(json={'ok': True})
    def playlist(route):
        playlists.append(route.request.post_data_json)
        route.fulfill(json={'ok': True})
    def watch(route):
        watches.append(route.request.post_data_json)
        route.fulfill(json={'watching': watches[-1]['on'], 'dir': 'Synthetic Downloads'})
    page.context.route('**/api/scrapers/playwright', start)
    page.context.route('**/api/import/youtube-playlist', playlist)
    page.context.route('**/api/scrapers/watch', watch)
    page.get_by_role('button', name='File', exact=True).click()
    page.get_by_role('menuitem', name='Scrapers').click()
    scraper = page.get_by_role('dialog', name='Scrapers', exact=True)
    expect(scraper.locator('button[data-site]')).to_have_count(5)
    expect(scraper.locator('[data-site][aria-expanded=true]')).to_have_count(1)
    assert not scraper.locator('.scraper-help[open], .scraper-options[open]').count()
    assert not launches and not playlists and not opened
    for width in (1280, 390):
        page.set_viewport_size({'width': width, 'height': 960})
        assert scraper.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
        page.screenshot(path=str(out / f'instagram-default-{width}.png'))
    page.set_viewport_size({'width': 1280, 'height': 960})

    def site(key, method=None):
        button = scraper.locator(f'button[data-site="{key}"]')
        if button.get_attribute('aria-expanded') != 'true':
            button.click()
        expect(scraper.locator('[data-site][aria-expanded=true]')).to_have_count(1)
        if method:
            scraper.locator(f'button[data-method="{method}"]').click()
        return scraper

    def options():
        details = scraper.locator('.scraper-options')
        if details.get_attribute('open') is None:
            details.locator('summary').click()
        return scraper.get_by_label('Remove from saved posts after export', exact=False)

    # Category/method selection alone never copies, launches or imports anything.
    for key in ('facebook', 'instagram', 'threads', 'youtube', 'reddit'):
        site(key)
        expected = {'manual', 'file', 'playlist' if key == 'youtube' else 'automatic'}
        assert set(scraper.locator('[data-method]').evaluate_all('(xs) => xs.map(x => x.dataset.method)')) == expected
    assert not launches and not playlists and not opened
    assert page.evaluate('window.__copiedScript === undefined')

    # Manual scripts stay tied to the expanded category; unsupported unsave stays disabled.
    for key in ('facebook', 'instagram', 'threads', 'youtube', 'reddit'):
        site(key, 'manual')
        remove = options()
        if key == 'youtube':
            expect(remove).to_have_count(0)
        else:
            expect(remove).to_be_enabled() if key == 'facebook' else expect(remove).to_be_disabled()
            assert not remove.is_checked()
        with page.expect_response(f'**/api/scrapers/{key}.js?*') as response:
            scraper.get_by_role('button', name='Copy script', exact=True).click()
        assert 'unsave=false' in response.value.url
        page.wait_for_function('text => window.__copiedScript === text', arg=response.value.text())
        assert not opened
    site('facebook', 'manual')
    options()
    scraper.get_by_label('Stop at title', exact=True).fill("Tutorial's saved title")
    scraper.get_by_role('button', name='Copy script', exact=True).click()
    page.wait_for_function("window.__copiedScript.includes(\"Tutorial\\\\'s saved title\")")
    page.evaluate('window.__clipboardFail = true')
    scraper.get_by_role('button', name='Copy script', exact=True).click()
    scraper.get_by_role('status').filter(has_text='Clipboard access denied').first.wait_for()
    assert not opened
    page.evaluate('window.__clipboardFail = false')

    # Cancel preserves both clipboard and account. Confirmation alone enables removal.
    options().check()
    for width in (1280, 390):
        page.set_viewport_size({'width': width, 'height': 960})
        page.screenshot(path=str(out / f'facebook-removal-{width}.png'))
    for width, button in ((1280, scraper.get_by_role('button', name='Copy script', exact=True)), (390, scraper.locator('[data-run]'))):
        page.set_viewport_size({'width': width, 'height': 960})
        page.evaluate("window.__copiedScript = 'cancelled copy sentinel'")
        button.click()
        confirm = page.get_by_role('alertdialog', name='Unsave after export?')
        expect(confirm).to_be_visible()
        assert confirm.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
        page.screenshot(path=str(out / f'facebook-confirmation-{width}.png'))
        confirm.get_by_role('button', name='Cancel', exact=True).click()
        assert page.evaluate('window.__copiedScript') == 'cancelled copy sentinel'
        assert not opened and not launches
    page.set_viewport_size({'width': 1280, 'height': 960})
    scraper.get_by_role('button', name='Copy script', exact=True).click()
    page.get_by_role('alertdialog', name='Unsave after export?').get_by_role('button', name='Continue', exact=True).click()
    page.wait_for_function("window.__copiedScript.includes('const UNSAVE_AFTER_SCRAPE = true;')")

    # The shared browser readiness control still gates automatic collection.
    runtime.update(state='ready', version='1.61.0', error='', source='Synthetic environment', path='C:/test/python.exe', managed=False)
    for key in ('facebook', 'instagram', 'reddit'):
        site(key, 'automatic')
        options().check()
        scraper.get_by_label('Remember this login', exact=False).check()
        start_button = scraper.locator('[data-run]')
        if start_button.is_disabled():
            tools_panel = scraper.locator('.scraper-tools')
            if tools_panel.get_attribute('open') is None:
                tools_panel.locator('summary').click()
            check = scraper.get_by_role('button', name='Check browser tools again', exact=True)
            if check.count():
                check.click()
        expect(start_button).to_be_enabled()
        before = len(launches)
        start_button.click()
        page.get_by_role('alertdialog', name='Unsave after export?').get_by_role('button', name='Cancel', exact=True).click()
        assert len(launches) == before
        start_button.click()
        with page.expect_response('**/api/scrapers/playwright'):
            page.get_by_role('alertdialog', name='Unsave after export?').get_by_role('button', name='Continue', exact=True).click()
        assert launches[-1]['platform'] == key and len(launches) == before + 1
        assert launches[-1]['unsave'] is True and launches[-1]['unsave_confirmed'] is True
        assert launches[-1]['remember'] is True
    site('threads', 'automatic')
    expect(options()).to_be_disabled()
    assert not options().is_checked()
    before = len(launches)
    with page.expect_response('**/api/scrapers/playwright'):
        scraper.locator('[data-run]').click()
    assert len(launches) == before + 1
    assert launches[-1]['platform'] == 'threads' and launches[-1]['unsave'] is False
    assert launches[-1]['unsave_confirmed'] is False
    assert page.get_by_role('alertdialog', name='Unsave after export?').count() == 0

    site('youtube', 'playlist')
    scraper.get_by_role('textbox', name='Playlist link', exact=True).fill('https://www.youtube.com/playlist?list=PLsynthetic')
    with page.expect_response('**/api/import/youtube-playlist'):
        scraper.locator('[data-run]').click()
    assert playlists == [{'url': 'https://www.youtube.com/playlist?list=PLsynthetic'}]
    site('reddit', 'file')
    scraper.locator('[data-run]').click()
    importer = page.get_by_role('dialog', name='Import CSV or JSON', exact=True)
    expect(importer).to_be_visible()
    page.keyboard.press('Escape')
    importer.wait_for(state='detached')

    site('facebook', 'manual')
    scraper.locator('[data-method="manual"]').press('ArrowLeft')
    expect(scraper.locator('[data-method="automatic"]')).to_have_attribute('aria-selected', 'true')
    expect(scraper.locator('[data-method="automatic"]')).to_be_focused()
    scraper.locator('[data-method="automatic"]').press('ArrowRight')
    expect(scraper.locator('[data-method="manual"]')).to_have_attribute('aria-selected', 'true')
    expect(scraper.locator('[data-method="manual"]')).to_be_focused()
    help_panel = scraper.locator('.scraper-help')
    if help_panel.get_attribute('open') is None:
        help_panel.locator('summary').click()
    image = help_panel.get_by_role('img')
    if image.count():
        image.scroll_into_view_if_needed()
        image.evaluate('e => e.decode()')
        assert image.evaluate('e => e.naturalWidth') == 1536
    for width in (1280, 390):
        page.set_viewport_size({'width': width, 'height': 960})
        assert scraper.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
        page.screenshot(path=str(out / f'scraper-expand-{width}.png'))
    page.set_viewport_size({'width': 1280, 'height': 960})
    # Closing while a script is loading must not copy, open or restart its watcher later.
    pending = []
    page.context.route('**/api/scrapers/facebook.js?*', lambda route: pending.append(route))
    page.evaluate("window.__copiedScript = 'closed window sentinel'")
    before_watches = len(watches)
    scraper.locator('[data-run]').click()
    for _ in range(50):
        if pending:
            break
        page.wait_for_timeout(10)
    assert len(pending) == 1
    scraper.locator('.cw-foot').get_by_role('button', name='Close', exact=True).click()
    scraper.wait_for(state='detached')
    pending[0].fulfill(body='const delayedScript = true;', content_type='text/javascript')
    pending[0].request.response().finished()
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('window.__copiedScript') == 'closed window sentinel'
    assert not opened and not any(watch['on'] for watch in watches[before_watches:])
    page.context.unroute('**/api/scrapers/facebook.js?*')
    runtime.clear()
    runtime.update(previous_runtime)


def main():
    with tempfile.TemporaryDirectory(prefix='guided-import-browser-') as folder:
        root = Path(folder)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, ANTHROPIC_API_KEY='', OPENAI_API_KEY='', FREELLMAPI_API_KEY='', YTDLP_COOKIES='')
        with (root / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, '-c', SERVER, str(root), str(port)], cwd=ROOT, env=env,
                                      stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(100):
                    try:
                        with urlopen(base + '/api/health', timeout=2):
                            break
                    except OSError:
                        if server.poll() is not None:
                            raise AssertionError((root / 'server.log').read_text())
                        time.sleep(.1)
                else:
                    raise AssertionError('Isolated server did not start')
                sys.path.insert(0, str(ROOT))
                from core import app_paths, local_auth
                with mock.patch.object(app_paths, 'LOCAL', root / 'local'), mock.patch('core.site_sessions._crypt', side_effect=lambda raw, decrypt=False: raw):
                    headers = local_auth.headers(port)
                    entry = local_auth.browser_url(base, port)
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1280, 'height': 960})
                    page.add_init_script('''
                        Object.defineProperty(navigator, 'clipboard', { value: {
                          writeText: async text => {
                            if (window.__clipboardFail) throw new Error('Clipboard access denied');
                            window.__copiedScript = text;
                          }
                        }});
                    ''')
                    opened = []
                    page.context.route('**/api/scrapers/*/open', lambda route: (
                        opened.append(route.request.url), route.fulfill(json={'ok': True})))
                    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                    state = {'state': 'missing', 'step': '', 'error': '', 'workers': True,
                             'python': True, 'winget': True, 'supported': True}
                    calls = []
                    def runtime(route):
                        if route.request.method == 'POST':
                            action = route.request.post_data_json['action']; calls.append(action)
                            state.update(state='failed', error='Synthetic download failed. Retry browser tools.')
                        route.fulfill(json=state)
                    page.context.route('**/api/settings/scraper-runtime', runtime)
                    page.goto(entry)
                    # The first run uses the handed-off six-step flow, with real tools and no automatic installs.
                    welcome = page.get_by_role('dialog', name='Welcome to Brainamon')
                    welcome.get_by_role('button', name='Skip', exact=True).wait_for()
                    if '--scrapers-only' in sys.argv:
                        with page.expect_response(lambda response: '/api/onboarding' in response.url and response.request.method == 'PUT'):
                            welcome.get_by_role('button', name='Skip', exact=True).click()
                        welcome.wait_for(state='detached')
                        out = ROOT / 'local/ui-blocks/guided-setup'
                        out.mkdir(parents=True, exist_ok=True)
                        check_scrapers(page, opened, state, out)
                        assert not errors, errors
                        browser.close()
                        print('PASS: live scraper categories, manual scripts, removal confirmation/payloads, unsupported platforms, playlist, CSV dialog and narrow layout')
                        return
                    nav = welcome.get_by_role('navigation', name='Setup checklist')
                    assert nav.get_by_role('button').count() == 6
                    welcome.get_by_text('Step 1 of 6: Your library', exact=True).wait_for()
                    welcome.get_by_role('button', name='Continue', exact=True).click()
                    welcome.get_by_text('Step 2 of 6: Tools & environment', exact=True).wait_for()
                    welcome.get_by_role('button', name='Install browser tools', exact=True).wait_for()
                    welcome.get_by_role('button', name='Skip this step', exact=True).click()
                    welcome.get_by_text('Step 3 of 6: Your first content', exact=True).wait_for()
                    for answer in ('Instagram', 'Facebook', 'Reddit', 'YouTube', 'Links and notes'):
                        assert welcome.get_by_role('button', name=answer, exact=True).count() == 1, answer
                    nav.get_by_role('button', name='Wiskit AI', exact=False).click()
                    welcome.get_by_text('Step 4 of 6: Wiskit AI', exact=True).wait_for()
                    welcome.get_by_role('button', name='Continue', exact=True).click()
                    welcome.get_by_text('No successful library upload yet.', exact=True).wait_for()
                    welcome.get_by_role('button', name='Continue', exact=True).click()
                    welcome.get_by_text('Finish setup on your phone.', exact=False).wait_for()
                    welcome.get_by_role('button', name='Review setup', exact=True).click()
                    welcome.get_by_text('Your setup, at a glance', exact=True).wait_for()
                    assert welcome.get_by_role('button', name='Resume', exact=True).count() >= 4
                    out = ROOT / 'local/ui-blocks/guided-setup'
                    out.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(out / 'summary.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    assert welcome.evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
                    page.screenshot(path=str(out / 'narrow.png'))
                    page.set_viewport_size({'width':1280,'height':960})
                    expect(welcome.get_by_role('button', name='Do this later', exact=True)).to_be_enabled()
                    with urlopen(Request(base + '/api/onboarding', headers=headers), timeout=5) as r:
                        navigation = json.load(r)
                    assert navigation['step'] == 'summary' and 'tools' in navigation['skipped']
                    page.request.put(base + '/api/onboarding', headers={**headers,'X-CM':'1'},data={'step':'summary','skipped':['tools','content','ai','drive','phone']})
                    page.reload()
                    welcome = page.get_by_role('dialog', name='Welcome to Brainamon')
                    welcome.get_by_text('Your setup, at a glance', exact=True).wait_for()
                    expect(welcome.get_by_role('navigation', name='Setup checklist').get_by_role('button', name='Tools & environment', exact=False)).to_contain_text('Skipped')
                    assert welcome.locator('.setup-summary').get_by_text('Skipped',exact=True).count() == 5
                    assert not calls, 'Opening the welcome installed something'
                    # 2. Skip answers 'skip': no welcome after a reload, Get started at 1 of 3, one empty-library key
                    welcome.get_by_role('button', name='Skip', exact=True).click()
                    welcome.wait_for(state='detached')
                    for _ in range(50):
                        with urlopen(Request(base + '/api/onboarding', headers=headers), timeout=5) as r:
                            answer = json.load(r)['answer']
                        if answer == 'skip':
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError({'answer_after_skip': answer})
                    page.reload()
                    page.get_by_role('region', name='Get started').get_by_text('1 of 6', exact=True).wait_for()
                    assert page.get_by_role('dialog', name='Welcome to Brainamon').count() == 0
                    empty = page.get_by_role('region', name='Your library is empty')
                    empty.get_by_role('button', name='Add a link or note', exact=True).wait_for()
                    assert empty.get_by_role('button').count() == 1
                    # 3. browser tools and protected cookies live in Help
                    page.get_by_role('button', name='Brainamon menu').click()
                    page.get_by_role('menuitem', name='Help').click()
                    setup = page.get_by_role('dialog', name='Help', exact=True)
                    expect(setup.get_by_role('button',name='Resume setup',exact=True)).to_be_enabled()
                    try:
                        setup.get_by_role('button', name='Install browser tools', exact=True).wait_for(timeout=10000)
                    except Exception:
                        raise AssertionError({'errors': errors, 'help': setup.inner_text()})
                    assert not calls, 'Opening Help installed something'
                    install = setup.get_by_role('button', name='Install browser tools', exact=True)
                    install.focus(); assert install.evaluate('e => e === document.activeElement')
                    page.keyboard.press('Enter')
                    setup.get_by_role('button', name='Retry browser tools', exact=True).wait_for()
                    assert calls == ['install']
                    setup.get_by_role('button', name='Skip for now', exact=True).click()
                    assert setup.get_by_text('Skipped. Links, notes and file imports work now.').is_visible()
                    setup.get_by_role('button', name='Show browser setup').click()
                    setup.get_by_text('Connect a site only when needed', exact=True).click()
                    cookie = root / 'export.txt'
                    cookie.write_bytes(b'# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tlogin\tsynthetic-secret\n')
                    setup.get_by_role('button', name='Add a login…', exact=True).click()
                    with page.expect_file_chooser() as chooser:
                        setup.get_by_role('button', name='Choose cookies.txt').click()
                    chooser.value.set_files(cookie)
                    setup.get_by_role('button', name='Save protected copy').wait_for()
                    assert 'synthetic-secret' not in setup.inner_text()
                    setup.get_by_role('button', name='Save protected copy').click()
                    setup.get_by_text('Saved, not tested yet', exact=False).first.wait_for()
                    assert cookie.exists()
                    # One desktop and one narrow inspection; no personal session/site is touched.
                    for width in (1280, 390):
                        page.set_viewport_size({'width': width, 'height': 960})
                        assert setup.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                        page.screenshot(path=str(ROOT / 'build' / f'guided-import-{width}.png'))
                    page.set_viewport_size({'width': 1280, 'height': 960})
                    page.keyboard.press('Escape')
                    setup.wait_for(state='detached')
                    # 4. nested scraper categories, supported unsaving and confirmation.
                    check_scrapers(page, opened, state, out)
                    # 5. an answer picks the Get started task and the focused Scrapers guide
                    page.request.put(base + '/api/onboarding', headers={**headers, 'X-CM': '1'}, data={'answer': 'facebook'})
                    page.reload()
                    page.get_by_role('region', name='Get started').get_by_role('button', name='Bring in your Facebook saves').click()
                    setup = page.get_by_role('dialog', name='Set up Brainamon', exact=True)
                    setup.get_by_role('button', name='Open manual import guide', exact=True).click()
                    scraper = page.get_by_role('dialog', name='Scrapers', exact=True)
                    expect(scraper.locator('[data-site="facebook"]')).to_have_attribute('aria-expanded', 'true')
                    expect(scraper.locator('[data-method="manual"]')).to_have_attribute('aria-selected', 'true')
                    scraper.get_by_role('button', name='Copy script', exact=True).click()
                    scraper.get_by_text('Facebook script copied to clipboard.', exact=True).wait_for()
                    assert not opened
                    scraper.locator('[data-run]').click()
                    scraper.get_by_text('script copied and page opened.', exact=False).wait_for()
                    assert len(opened) == 1 and '/facebook/open' in opened[0]
                    scraper.locator('[data-method="automatic"]').click()
                    assert scraper.get_by_label('Instagram username').count() == 0
                    scraper.locator('[data-site="instagram"]').click()
                    scraper.locator('.scraper-options summary').click()
                    scraper.get_by_label('Instagram username').wait_for()
                    scraper.locator('[data-method="manual"]').focus()
                    page.keyboard.press('Enter')
                    expect(scraper.locator('[data-method="manual"]')).to_have_attribute('aria-selected', 'true')
                    assert scraper.get_by_label('Instagram username').count() == 0
                    assert not errors, errors
                    if '--desktop-only' not in sys.argv:
                        mobile = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en-US')
                        mobile.add_init_script("localStorage.setItem('bp-lang','en')")
                        from library.mirror import MirrorKey
                        solo_key = MirrorKey(bytes(range(32)))
                        solo_pair = {'v':2,'k':solo_key.text(),'f':solo_key.fingerprint,'c':'','e':'','ai':{},'at':0,'solo':True}
                        mobile.add_init_script("localStorage.setItem('bp-pair'," + json.dumps(json.dumps(solo_pair)) + ");")
                        mobile.context.route('https://**', lambda route: route.abort())
                        mobile.context.route('http://127.0.0.1:18766/**', lambda route: route.fulfill(status=503, json={'error': 'offline fixture'}))
                        mobile.goto(base + '/mobile.html#/more')
                        mobile.get_by_text('Backup & phones', exact=True).wait_for()
                        assert mobile.get_by_role('button', name='Install browser tools').count() == 0
                        assert mobile.get_by_role('button', name='Choose cookies.txt').count() == 0
                        assert mobile.get_by_text('Without a PC there are no thumbnails', exact=False).count() == 0
                        mobile.goto(base + '/mobile.html#/import')
                        export = root / 'saved_posts.json'
                        export.write_text(json.dumps([{'label_values': [{'label': 'URL', 'value': 'https://www.instagram.com/p/synthetic/'}]}]))
                        mobile.locator('input[type=file]').set_input_files(export)
                        mobile.get_by_text('Added 1 link', exact=False).wait_for()
                        mobile.locator('input[type=file]').set_input_files(export)
                        mobile.get_by_text('1 already in the library', exact=False).wait_for()
                        assert mobile.get_by_text('Links are saved', exact=False).count() == 0  # duplicate import reports no additions
                        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    # First-run checklist: rows exist while probes are pending, and match Setup/Settings.
                    page.request.put(base + '/api/onboarding', headers={**headers, 'X-CM': '1'}, data={'step':'library','skipped':[]})
                    fresh = browser.new_page(viewport={'width': 1280, 'height': 960})
                    fresh.add_init_script("localStorage.setItem('cm-os-theme', 'dark')")
                    fresh.on('pageerror', lambda e: errors.append(str(e)))
                    def first_run(route):
                        if route.request.method == 'GET':
                            response = route.fetch(); data = response.json(); data['answer'] = ''; data['welcome'] = True
                            route.fulfill(response=response, json=data)
                        else:
                            route.continue_()
                    fresh.context.route('**/api/onboarding', first_run)
                    installs = []
                    install_state = {'state': 'idle', 'step': '', 'error': '', 'winget': True,
                                     'command': 'winget install --id yt-dlp.yt-dlp -e --source winget --force'}
                    fail_install = True
                    def install_route(route):
                        if route.request.method == 'POST':
                            installs.append('install')
                            install_state.update(state='running', step='Checking video tools', error='')
                        elif install_state['state'] == 'running':
                            install_state.update(state='error' if fail_install else 'done', step='',
                                                 error='Synthetic permission failure' if fail_install else '')
                            tools['youtube']['ejs'] = 'not detected' if fail_install else 'detected'
                        route.fulfill(json=install_state)
                    fresh.context.route('**/api/settings/tools/install', install_route)
                    pending = []
                    fresh.context.route('**/api/settings/tools', lambda route: pending.append(route))
                    fresh.context.route('**/api/settings/scraper-runtime', lambda route: route.fulfill(json={**state, 'state': 'ready', 'version': '1.61.0', 'error': '', 'source': 'Selected project environment', 'path': 'C:/project/.venv/Scripts/python.exe', 'managed': False}))
                    fresh.goto(entry)
                    welcome = fresh.get_by_role('dialog', name='Welcome to Brainamon')
                    welcome.get_by_role('button', name='Continue', exact=True).click()
                    welcome.get_by_role('progressbar', name='Looking for tools and checking that they work…', exact=True).wait_for()
                    assert welcome.get_by_role('button', name='Check and set up', exact=True).is_disabled()
                    assert welcome.get_by_role('button', name='Browse for ffmpeg', exact=True).count() == 0
                    welcome.get_by_text('More: tool folders, install by hand', exact=True).click()
                    for name in ('ffmpeg', 'ffprobe', 'yt-dlp', 'deno'):
                        assert welcome.get_by_role('button', name=f'Browse for {name}', exact=True).count() == 1
                    assert welcome.locator('.tool-status.pending').count() >= 4
                    tools = {'tools_dir': '', 'tool_folders': {}, 'all_found': True, 'youtube': {'deno': True, 'ejs': 'detected', 'functional': True}, 'tools': [{'name': n, 'state': 'ready', 'found': True, 'path': f'C:/tools/{n}.exe', 'version': 'test'} for n in ('ffmpeg', 'ffprobe', 'yt-dlp', 'deno')]}
                    for route in pending: route.fulfill(json=tools)
                    fresh.context.unroute('**/api/settings/tools')
                    picked = []
                    def tools_route(route):
                        if route.request.method == 'PUT': picked.append(route.request.post_data_json)
                        route.fulfill(json=tools)
                    fresh.context.route('**/api/settings/tools', tools_route)
                    welcome.get_by_text('Video tools are ready.', exact=True).wait_for()
                    assert welcome.get_by_role('button', name='Install browser tools', exact=True).count() == 0
                    assert welcome.get_by_role('button', name='Remove browser tools…', exact=True).count() == 0
                    assert welcome.get_by_role('navigation', name='Setup checklist').get_by_role('button').count() == 6
                    welcome.get_by_role('button', name='Browse for ffmpeg', exact=True).click()
                    welcome.get_by_label('Folder containing ffmpeg', exact=True).fill('C:/chosen-tools')
                    welcome.get_by_role('button', name='Use folder', exact=True).click()
                    welcome.get_by_label('Folder containing ffmpeg', exact=True).wait_for(state='detached')
                    assert picked == [{'tool': 'ffmpeg', 'folder': 'C:/chosen-tools'}]
                    fresh.evaluate("window.pywebview = {api: {pick: async () => ['C:/native-tools']}}")
                    welcome.get_by_role('button', name='Browse for yt-dlp', exact=True).click()
                    welcome.get_by_label('Folder containing yt-dlp', exact=True).wait_for(state='detached')
                    assert picked[-1] == {'tool': 'yt-dlp', 'folder': 'C:/native-tools'}
                    welcome.get_by_role('navigation', name='Setup checklist').get_by_role('button', name='Drive & recovery', exact=False).click()
                    welcome.get_by_role('button', name='Advanced cloud settings', exact=True).click()
                    settings = fresh.get_by_role('dialog', name='Settings', exact=True)
                    expect(settings.locator('#set-s-sync-account')).to_be_focused()
                    settings.get_by_role('tab', name='Imports & downloads', exact=True).click()
                    primary = settings.get_by_role('button', name='Check and set up', exact=True)
                    expect(primary).to_be_enabled()
                    assert not installs, 'Opening setup installed video tools'
                    assert settings.get_by_role('button', name='Browse for ffmpeg', exact=True).count() == 0
                    assert settings.get_by_text('YouTube EJS scripts', exact=True).count() == 0 or settings.get_by_text('YouTube EJS scripts', exact=True).is_hidden()
                    primary.focus(); fresh.keyboard.press('Enter')
                    expect(settings.get_by_role('region', name='Video tools', exact=True).get_by_role('alert')).to_have_text('Synthetic permission failure')
                    assert installs == ['install']
                    terminals = []
                    def terminal_route(route):
                        terminals.append(route.request.method)
                        route.fulfill(status=409 if len(terminals) == 1 else 200,
                                      json={'detail': 'Synthetic elevation cancelled'} if len(terminals) == 1 else {'opened': True})
                    fresh.context.route('**/api/settings/tools/install/terminal', terminal_route)
                    terminal = settings.get_by_role('button', name='Open administrator terminal', exact=True)
                    terminal.click()
                    expect(settings.get_by_role('region', name='Video tools', exact=True).get_by_role('alert').filter(has_text='Synthetic elevation cancelled')).to_be_visible()
                    terminal.click()
                    settings.get_by_text('Terminal opened.', exact=False).wait_for()
                    assert terminal.is_disabled()
                    assert terminals == ['POST', 'POST']
                    for width in (1280, 390):
                        fresh.set_viewport_size({'width': width, 'height': 960})
                        assert settings.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                        fresh.screenshot(path=str(ROOT / 'build' / f'video-tools-recovery-{width}.png'))
                    fresh.set_viewport_size({'width': 1280, 'height': 960})
                    fail_install = False
                    primary.click()
                    fresh.get_by_text('Video tools are ready', exact=True).wait_for()
                    assert installs == ['install', 'install']
                    settings.get_by_text('More: tool folders, install by hand', exact=True).click()
                    settings.get_by_role('button', name='Browse for ffmpeg', exact=True).wait_for()
                    fresh.screenshot(path=str(ROOT / 'build' / 'setup-settings-tools-dark.png'))
                    settings.get_by_role('button', name='Back to Setup', exact=True).click()
                    settings.wait_for(state='detached')
                    assert fresh.get_by_role('dialog', name='Set up Brainamon', exact=True).count() == 0
                    assert welcome.is_visible()
                    for width in (1280, 390):
                        fresh.set_viewport_size({'width': width, 'height': 960})
                        assert welcome.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                        welcome.locator('.cw-body').evaluate('e => e.scrollTop = 0')
                        fresh.screenshot(path=str(ROOT / 'build' / f'setup-checklist-dark-{width}.png'))
                        welcome.get_by_role('navigation', name='Setup checklist').get_by_role('button', name='Wiskit AI', exact=False).click()
                        welcome.get_by_role('heading', name='Step 4 of 6: Wiskit AI', exact=True).scroll_into_view_if_needed()
                        fresh.screenshot(path=str(ROOT / 'build' / f'setup-checklist-details-dark-{width}.png'))
                    welcome.locator('.cw-body').evaluate('e => e.scrollTop = e.scrollHeight')
                    fresh.screenshot(path=str(ROOT / 'build' / 'setup-checklist-bottom-dark.png'))
                    fresh.set_viewport_size({'width':1280,'height':960})
                    welcome.get_by_role('navigation',name='Setup checklist').get_by_role('button',name='Your first content',exact=False).click()
                    welcome.get_by_role('button',name='CSV or Brainamon JSON',exact=True).click()
                    welcome.get_by_role('button',name='Choose a file',exact=True).click()
                    importer = fresh.get_by_role('dialog',name='Import CSV or JSON',exact=True)
                    expect(importer).to_be_visible()
                    fresh.keyboard.press('Escape')
                    expect(welcome.get_by_text('Step 3 of 6: Your first content',exact=True)).to_be_visible()
                    with urlopen(Request(base+'/api/onboarding',headers=headers),timeout=5) as r:
                        assert json.load(r)['answer'] == 'files'
                    assert not errors, errors
                    browser.close()
                print('PASS: welcome, shared setup checklist, tool loading/ready states, video setup/permission recovery/terminal retry, Help install/retry/skip, protected upload, desktop/narrow layout, nested scraper categories, method filtering and Unsave confirmation' + (' (mobile-only checks skipped)' if '--desktop-only' in sys.argv else ', mobile solo imports'))
            finally:
                server.terminate(); server.wait(timeout=15)


if __name__ == '__main__':
    main()
