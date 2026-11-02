"""Production settings navigation with a throwaway library and mocked services.

Run after building web/: py tests/check_settings_navigation_browser.py
"""
import importlib.util
import tempfile
import re
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shots', ROOT / 'tests/helpers/shots.py')
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)

PAGES = {
    'overview': 'Overview', 'general': 'General', 'ai': 'Wiskit & AI',
    'imports': 'Imports & downloads', 'obsidian': 'Obsidian & map',
    'backup': 'Backup & phones',
}


class Review(shots.Run):
    def first_start(self, browser, theme):
        pass

    def phone(self, browser, theme):
        pass

    def desktop(self, browser, theme):
        ctx = self.context(browser, theme)
        saved = self.api('GET', '/api/settings')
        calls = []
        fail_key = False
        fail_link = False

        def settings_route(route):
            if route.request.method == 'PUT':
                payload = route.request.post_data_json
                calls.append(payload)
                if fail_key:
                    route.fulfill(status=409, json={'detail': 'Synthetic save failed.'})
                    return
                for provider in payload.get('keys', {}):
                    saved['keys'][provider] = True
                for provider in payload.get('clear_keys', []):
                    saved['keys'][provider] = False
                saved['plain'].update(payload.get('plain', {}))
                saved['downloads'].update(payload.get('downloads', {}))
                saved['models'].update(payload.get('models', {}))
                for provider in saved['models']['providers']:
                    provider['has_key'] = saved['keys'].get(provider['id'], False)
            route.fulfill(json=saved)

        def link_route(route):
            assert route.request.post_data_json == {'name': 'openai'}
            if fail_link:
                route.fulfill(status=409, json={'detail': 'Synthetic link failure.'})
            else:
                route.fulfill(json={'ok': True})

        ctx.route('**/api/settings', settings_route)
        ctx.route('**/api/app/setup/link', link_route)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        self.settle(page)
        pending_checks, full_checks = [], []
        ctx.route('**/api/settings/tools', lambda route: pending_checks.append(route))
        ctx.route('**/api/settings/scraper-runtime', lambda route: pending_checks.append(route))
        ctx.route('**/api/app/setup', lambda route: (full_checks.append(route.request.url), route.abort()))
        assert self.palette(page, 'Set up Brainamon')
        setup = page.get_by_role('dialog', name='Set up Brainamon', exact=True)
        nav = setup.get_by_role('navigation', name='Setup checklist')
        nav.get_by_role('button', name='Tools & environment', exact=False).click()
        nav.get_by_role('button', name='Your first content', exact=False).click()
        setup.get_by_role('button', name='Do this later', exact=True).click()
        expect(setup).to_have_count(0)
        page.keyboard.press('Control+Comma')
        win = page.locator('.cw.set-win')
        expect(win.locator('.set-heading h2')).to_have_text('Overview')

        def go(destination):
            if page.viewport_size['width'] < 700:
                win.locator('#set-section').select_option(destination)
            else:
                win.locator(f'#set-t{destination}').click()
            expect(win.locator('.set-heading h2')).to_have_text(PAGES[destination])

        def find(text, anchor):
            field = win.locator('#set-find-m' if page.viewport_size['width'] < 700 else '#set-find')
            field.fill(text)
            field.press('Enter')
            expect(win.locator(anchor)).to_be_focused()

        go('general')
        expect(win.locator('#a-tray')).to_be_enabled(timeout=2000)
        assert len(pending_checks) == 2, [r.request.url for r in pending_checks]
        assert not full_checks, full_checks
        for route in pending_checks:
            if route.request.url.endswith('/tools'):
                route.fulfill(json={'tools_dir': '', 'tools': [], 'all_found': False})
            else:
                route.fulfill(json={'state': 'missing', 'supported': True, 'workers': True, 'python': False, 'winget': False})
        ctx.unroute('**/api/settings/tools')
        ctx.unroute('**/api/settings/scraper-runtime')
        ctx.unroute('**/api/app/setup')

        for destination in PAGES:
            go(destination)
        go('overview')
        win.locator('#set-toverview').press('ArrowDown')
        expect(win.locator('#set-tgeneral')).to_be_focused()
        win.locator('#set-tgeneral').press('End')
        expect(win.locator('#set-tbackup')).to_be_focused()
        win.locator('#set-tbackup').press('Home')
        expect(win.locator('#set-toverview')).to_be_focused()

        go('general')
        win.get_by_text('Legacy receipt for an older phone app', exact=True).click()
        license_key = win.locator('#license-key')
        license_key.fill('synthetic-license-draft')
        go('backup')
        go('general')
        expect(license_key).to_have_value('synthetic-license-draft')

        find('cookies', '#set-s-dl-logins')
        expect(win.locator('.set-heading h2')).to_have_text(PAGES['imports'])
        find('ollama', '#set-s-local')
        expect(win.locator('#set-s-local').locator('xpath=ancestor::details[1]')).to_have_attribute('open', '')
        find('recovery', '#set-s-sync-recovery')
        expect(win.locator('.set-heading h2')).to_have_text(PAGES['backup'])

        go('ai')
        openai = win.locator('#k-openai')
        anthropic = win.locator('#k-anthropic')
        expect(openai).to_be_visible()
        expect(anthropic).to_be_visible()
        row = openai.locator('..')
        expect(row.get_by_role('button', name='Get an OpenAI API key', exact=True)).to_be_enabled()
        assert row.evaluate("e => Array.from(e.children).map(x => x.tagName === 'INPUT' ? 'input' : x.textContent.trim()).slice(0,3)") == ['input', 'Save OpenAI key', 'Get an API key']
        fail_link = True
        row.get_by_role('button', name='Get an OpenAI API key', exact=True).click()
        expect(win.get_by_role('alert').filter(has_text='Synthetic link failure.')).to_be_visible()
        fail_link = False
        openai.fill('synthetic-openai')
        anthropic.fill('synthetic-anthropic')
        go('general')
        go('ai')
        expect(openai).to_have_value('synthetic-openai')
        expect(anthropic).to_have_value('synthetic-anthropic')
        fail_key = True
        row.get_by_role('button', name='Save OpenAI key', exact=True).click()
        expect(win.get_by_role('alert').filter(has_text='Synthetic save failed.')).to_be_visible()
        expect(openai).to_have_value('synthetic-openai')
        fail_key = False
        row.get_by_role('button', name='Save OpenAI key', exact=True).click()
        expect(openai).to_have_value('')
        expect(anthropic).to_have_value('synthetic-anthropic')
        assert calls[-1] == {'keys': {'openai': 'synthetic-openai'}}
        expect(row.get_by_role('button', name='Get an OpenAI API key', exact=True)).to_be_enabled()
        win.locator('.cw-foot').get_by_role('button', name='Discard', exact=True).click()
        expect(anthropic).to_have_value('')

        for width, height in [(1440, 1000), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            for destination in PAGES:
                go(destination)
                assert win.locator('.cw-body').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), (theme, width, destination)
            go('ai')
            openai.scroll_into_view_if_needed()
            self.shot(page, f'{theme}-ai-{width}')
            if width == 390:
                find('cookies', '#set-s-dl-logins')
        assert not errors, errors
        ctx.close()
        print(f'{theme}: production navigation, keyboard, search/focus, drafts, key errors and layout passed')


if __name__ == '__main__':
    args = SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'), port=0,
                           out=tempfile.mkdtemp(prefix='brainamon-browser-shots-'), only=None,
                           root=None, themes='dark,light')
    Review(args).go()
