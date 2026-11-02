"""Setup height, selection and inline actions; disposable library, mocked credentials/Drive."""
import copy
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shots', ROOT / 'tests/helpers/shots.py')
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)


class Review(shots.Run):
    def first_start(self, browser, theme):
        pass

    def phone(self, browser, theme):
        pass

    def desktop(self, browser, theme):
        self.api('PUT', '/api/onboarding', {'step': 'library', 'skipped': []})
        ctx = self.context(browser, theme)
        claude = self.api('GET', '/api/claude-code')
        claude['available'] = True
        ctx.route('**/api/claude-code', lambda route: route.fulfill(json=claude))
        settings = self.api('GET', '/api/settings')
        settings = copy.deepcopy(settings)
        settings['models']['jarvis'] = {'provider': 'anthropic', 'model': settings['models']['models']['anthropic'][0]['id']}
        key_calls = []
        fail_key = True

        def ai(route):
            if route.request.method == 'PUT':
                body = route.request.post_data_json
                key_calls.append(body)
                if fail_key:
                    route.fulfill(status=409, json={'detail': 'Synthetic save failure. Retry.'})
                    return
                if 'keys' in body:
                    for key in body['keys']:
                        settings['keys'][key] = True
                        next(p for p in settings['models']['providers'] if p['id'] == key)['has_key'] = True
                if 'models' in body:
                    settings['models']['jarvis'] = body['models']['jarvis']
            route.fulfill(json=settings)

        cloud = self.api('GET', '/api/cloud')
        cloud.update(configured=True, licensed=True, signed_in=False, state='off', rotation='complete', phone_keys=['openai'])
        recovery = dict(configured=False, enrolled=False, verified=False, account='', restored=False,
                        job={'state': 'idle'}, preview=None)
        calls = []
        preflight_calls = []
        fail_connect = True

        def drive(route):
            path = urlparse(route.request.url).path
            if path == '/api/cloud/recovery':
                route.fulfill(json=recovery)
                return
            if path == '/api/cloud/sizes':
                route.continue_()
                return
            if path == '/api/cloud/recovery/preflight':
                preflight_calls.append(path)
                route.fulfill(json={'state': 'ready', 'message': 'Ready for recovery setup.', 'enrolled': False, 'account': cloud['account']})
                return
            if path == '/api/cloud/recovery/discover':
                route.fulfill(json={'libraries': [{'id': 'synthetic-generation', 'fingerprint': 'test-key', 'created': 1790812800, 'account': cloud['account']}]})
                return
            if route.request.method == 'POST':
                calls.append((path, route.request.post_data_json))
                if path == '/api/cloud/recovery/sign-in':
                    if fail_connect:
                        route.fulfill(status=409, json={'detail': 'Synthetic sign-in failure. Retry.'})
                        return
                    cloud.update(signed_in=True, account='sample@example.com')
                elif path == '/api/cloud/connect':
                    cloud.update(running=True, state='idle')
                elif path == '/api/cloud/publish':
                    cloud.update(state='publishing', done=2, total=5)
                elif path == '/api/cloud/stop':
                    cloud.update(running=False, vault_running=False, state='off')
                elif path == '/api/cloud/pair':
                    route.fulfill(json={'url': 'https://example.invalid/#synthetic', 'svg': '<svg viewBox="0 0 100 100"><rect width="100" height="100" fill="black"/></svg>', 'fingerprint': 'test-check', 'keys': ['openai']})
                    return
                else:
                    raise AssertionError(f'Unexpected mutation: {path}')
                cloud['seq'] += 1
            route.fulfill(json=cloud)

        ctx.route('**/api/settings', ai)
        ctx.route('**/api/cloud', drive)
        ctx.route('**/api/cloud/**', drive)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw new Error('Denied')}}})")
        page.goto(self.url())
        page.get_by_role('button', name='Brainamon menu').wait_for()
        self.settle(page)
        assert self.palette(page, 'Set up Brainamon')
        setup = page.get_by_role('dialog', name='Set up Brainamon', exact=True)
        nav = setup.get_by_role('navigation', name='Setup checklist')
        titles = ['Your library', 'Tools & environment', 'Your first content', 'Wiskit AI', 'Drive & recovery', 'Connect your phone']

        def visit(title, wait_saved=True):
            nav.get_by_role('button', name=title, exact=False).click()
            expect(setup.locator('#setup-stage')).to_contain_text(title)
            expect(nav.get_by_role('button', name=title, exact=False)).to_be_enabled()
            if wait_saved:
                expect(setup.get_by_text('Saving setup position…', exact=True)).to_have_count(0)

        # Hold checks and the position save open: neither may lock navigation or source choices.
        self.settle(page)
        pending_saves, pending_checks = [], []

        def hold_save(route):
            if route.request.method == 'PUT':
                pending_saves.append(route)
            else:
                route.continue_()

        ctx.route('**/api/onboarding', hold_save)
        ctx.route('**/api/settings/tools', lambda route: pending_checks.append(route))
        ctx.route('**/api/settings/scraper-runtime', lambda route: pending_checks.append(route))
        visit('Tools & environment', wait_saved=False)
        expect(setup.get_by_role('progressbar', name='Looking for Python and checking Playwright with a local browser…', exact=True)).to_be_visible()
        visit('Your first content', wait_saved=False)
        setup.locator('[data-source="facebook"]').click(timeout=1000)
        setup.locator('[data-source="youtube"]').click(timeout=1000)
        expect(setup.locator('[data-source="youtube"]')).to_have_attribute('aria-pressed', 'true')
        expect(setup.get_by_role('button', name='Bring in a YouTube playlist', exact=True)).to_be_enabled()
        setup.get_by_role('button', name='Continue', exact=True).click(timeout=1000)
        expect(setup.locator('#setup-stage')).to_contain_text('Wiskit AI')
        assert pending_saves and len(pending_checks) >= 2, (len(pending_saves), len(pending_checks))
        ctx.unroute('**/api/onboarding', hold_save)
        for route in pending_saves:
            route.continue_()
        for route in pending_checks:
            if route.request.url.endswith('/tools'):
                route.fulfill(json={'tools_dir': '', 'tools': [], 'all_found': False})
            else:
                route.fulfill(json={'state': 'missing', 'supported': True, 'workers': True, 'python': False, 'winget': False})
        ctx.unroute('**/api/settings/tools')
        ctx.unroute('**/api/settings/scraper-runtime')
        expect(setup.get_by_text('Saving setup position…', exact=True)).to_have_count(0)
        expect(setup.locator('#setup-stage')).to_contain_text('Wiskit AI')
        visit('Your first content')
        expect(setup.locator('[data-source="youtube"]')).to_have_attribute('aria-pressed', 'true')

        for size in ({'width': 1280, 'height': 900}, {'width': 390, 'height': 844}):
            page.set_viewport_size(size)
            height = setup.bounding_box()['height']
            for title in titles:
                visit(title)
                assert abs(setup.bounding_box()['height'] - height) < 1, title
                assert setup.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), title
                current = nav.locator('[aria-current="step"]')
                assert current.count() == 1
                assert current.evaluate('e=>getComputedStyle(e).backgroundColor===getComputedStyle(e.parentElement).color')
                footer = setup.locator('.cw-foot').bounding_box()
                assert footer['y'] + footer['height'] <= size['height'] + 1
                if title == 'Your first content':
                    options = setup.locator('.source-options')
                    for source, color in [('instagram', 'rgb(214, 36, 159)'), ('facebook', 'rgb(24, 119, 242)'), ('reddit', 'rgb(255, 69, 0)'), ('youtube', 'rgb(255, 0, 0)')]:
                        button = options.locator(f'[data-source="{source}"]')
                        expect(button).to_have_css('background-color', color)
                        expect(button.locator('.source-logo')).to_have_attribute('aria-hidden', 'true')
                    assert options.locator('.source-logo').count() == 4
                    facebook = options.get_by_role('button', name='Facebook', exact=True)
                    facebook.focus(); page.keyboard.press('Enter')
                    expect(facebook).to_have_attribute('aria-pressed', 'true')
                    expect(facebook).to_be_enabled()
                    expect(options.locator('.source-selected')).to_have_count(1)
                    self.shot(page, f'setup-{theme}-{size["width"]}-sources')
            setup.get_by_role('button', name='Review setup', exact=True).click()
            expect(setup.locator('#setup-stage')).to_have_text('Your setup, at a glance')
            assert abs(setup.bounding_box()['height'] - height) < 1
            visit('Wiskit AI')
            actions = setup.locator('.key-actions')
            expect(actions.get_by_role('button', name='Save key', exact=True)).to_have_css('background-color', 'rgb(43, 209, 126)')
            save_box = actions.get_by_role('button', name='Save key', exact=True).bounding_box()
            get_box = actions.get_by_role('button', name='Get a provider key', exact=True).bounding_box()
            assert abs(save_box['y'] - get_box['y']) < 1
            assert get_box['x'] > save_box['x']
            actions.scroll_into_view_if_needed()
            self.shot(page, f'setup-{theme}-{size["width"]}-ai')

        page.set_viewport_size({'width': 1280, 'height': 900})
        expect(setup.get_by_text('OpenAI is recommended.', exact=True)).to_be_visible()
        expect(setup.get_by_role('option', name='OpenAI (recommended)', exact=True)).to_have_count(1)
        # Claude Code is set up inline: no Settings redirect, program field and Test right here.
        expect(setup.get_by_text('Claude Code (optional)', exact=True)).to_be_visible()
        expect(setup.get_by_label('Program', exact=True)).to_be_visible()
        expect(setup.get_by_role('button', name='Test', exact=True)).to_be_visible()
        assert page.locator('.set-win').count() == 0
        # Refresh models sits to the right of the Wiskit model list.
        refresh = setup.get_by_role('button', name='Refresh models', exact=True)
        model_box = setup.get_by_label('Wiskit model', exact=True).bounding_box()
        refresh_box = refresh.bounding_box()
        assert refresh_box['x'] > model_box['x'] + model_box['width'] - 1
        assert abs(refresh_box['y'] - model_box['y']) < model_box['height']
        provider = setup.get_by_label('AI provider', exact=True)
        provider.select_option('openai')
        key = setup.get_by_label('API key', exact=True)
        key.fill('synthetic-test-key')
        setup.get_by_role('button', name='Save key', exact=True).click()
        expect(setup.get_by_role('alert')).to_have_text('Synthetic save failure. Retry.')
        expect(key).to_have_value('synthetic-test-key')
        fail_key = False
        setup.get_by_role('button', name='Save key', exact=True).evaluate('e=>{e.click();e.click()}')
        expect(key).to_have_value('')
        assert key_calls == [{'keys': {'openai': 'synthetic-test-key'}}] * 2
        setup.get_by_role('button', name='Use this model', exact=True).click()
        expect(setup.get_by_text('Wiskit model saved.', exact=True)).to_be_visible()
        assert list(key_calls[-1]) == ['models']
        assert key_calls[-1]['models']['jarvis']['provider'] == 'openai'
        assert page.locator('.set-win').count() == 0

        visit('Drive & recovery')
        setup.get_by_role('button', name='Connect Google Drive', exact=True).click()
        expect(setup.get_by_role('alert')).to_have_text('Synthetic sign-in failure. Retry.')
        fail_connect = False
        setup.get_by_role('button', name='Connect Google Drive', exact=True).click()
        expect(setup.get_by_text('Google Drive connected: sample@example.com', exact=True)).to_be_visible()
        assert not cloud['running']
        # recovery is chosen and checked on the Backup & phones page: Setup shows where it stands and points there
        expect(setup.get_by_text('No recovery passphrase yet', exact=True)).to_be_visible()
        setup.get_by_role('button', name='Recovery in Backup & phones', exact=True).click()
        settings_window = page.get_by_role('dialog', name='Settings', exact=True)
        expect(settings_window.locator('.set-heading h2')).to_have_text('Backup & phones')
        expect(settings_window.locator('#set-s-sync-recovery')).to_be_focused()
        settings_window.get_by_role('button', name='Back to Setup', exact=True).click()
        setup.get_by_role('button', name='Turn on uploads', exact=True).click()
        expect(setup.get_by_role('button', name='Upload now', exact=True)).to_be_enabled()
        setup.get_by_role('button', name='Upload now', exact=True).click()
        expect(setup.get_by_role('progressbar', name='Google Drive upload', exact=True)).to_have_attribute('aria-valuenow', '40')
        setup.get_by_role('button', name='Pause uploads and vault sync', exact=True).click()
        expect(setup.get_by_text('Library uploads off', exact=True)).to_be_visible()
        self.shot(page, f'setup-{theme}-drive')
        setup.get_by_role('button', name='Advanced cloud settings', exact=True).click()
        expect(page.locator('#set-s-sync-recovery')).to_have_count(1)
        page.get_by_role('dialog', name='Settings', exact=True).get_by_role('button', name='Back to Setup', exact=True).click()

        visit('Connect your phone')
        setup.get_by_role('button', name='Show pairing QR', exact=True).click()
        expect(setup.get_by_role('img', name='Phone pairing QR code')).to_be_visible()
        assert calls[-1] == ('/api/cloud/pair', {'keys': ['openai']})
        setup.get_by_role('button', name='Copy pairing link', exact=True).click()
        expect(setup.get_by_text('Could not copy the pairing link. Scan the QR instead.', exact=True)).to_be_visible()
        self.shot(page, f'setup-{theme}-phone')
        visit('Wiskit AI')
        visit('Connect your phone')
        assert setup.get_by_role('img', name='Phone pairing QR code').count() == 0
        cloud.update(licensed=False, seq=cloud['seq'] + 1)
        visit('Your library'); visit('Connect your phone')
        expect(setup.get_by_role('button', name='Show pairing QR', exact=True)).to_be_disabled()
        claude['available'] = False
        visit('Wiskit AI')
        self.settle(page)
        expect(setup.get_by_text('Claude Code (optional)', exact=True)).to_have_count(0)
        # A library folder chosen for the next start: its content counts, and Restart is one click.
        chosen = {**self.api('GET', '/api/app/setup'), 'items': 0, 'data_dir_next': 'D:/Synthetic/Library',
                  'next_items': 1234, 'next_notes': 5, 'can_quit': True}
        restarts = []
        ctx.route('**/api/app/setup?include_tools=false', lambda route: route.fulfill(json=chosen))
        ctx.route('**/api/app/restart', lambda route: (restarts.append(1), route.fulfill(json={'ok': True})))
        visit('Wiskit AI'); visit('Your library')
        expect(setup.get_by_text('Opens after a restart: D:/Synthetic/Library', exact=True)).to_be_visible()
        expect(setup.get_by_text('It already holds 1,234 items and 5 notes.', exact=True)).to_be_visible()
        expect(nav.get_by_role('button', name='Your first content', exact=False)).to_contain_text('Ready')
        self.shot(page, f'setup-{theme}-library-restart')
        setup.get_by_role('button', name='Restart now to open it', exact=True).click()
        page.wait_for_timeout(300)
        assert restarts == [1], restarts
        assert not errors, errors
        ctx.close()
        print(f'{theme}: stable height, selected steps, inline key/model saves, recovery, uploads and pairing passed')


if __name__ == '__main__':
    args = SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'), port=0,
                           out=tempfile.mkdtemp(prefix='brainamon-browser-shots-'), only=None,
                           root=None, themes='dark,light')
    Review(args).go()
