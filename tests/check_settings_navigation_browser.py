"""Production settings navigation with a throwaway library and mocked services.

Run after building web/: py tests/check_settings_navigation_browser.py
"""
import argparse
import importlib.util
import json
import tempfile
import re
from datetime import datetime, timezone
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

    def review_gaps(self, browser, theme):
        ctx = self.context(browser, theme)
        fixture = json.loads((ROOT / 'tests/fixtures/desktop_backup_states.json').read_text(encoding='utf-8'))
        ctx.route('**/api/cloud', lambda route: route.fulfill(json=fixture['cloud']))
        ctx.route('**/api/cloud/recovery', lambda route: route.fulfill(json=fixture['recovery']))
        ctx.add_init_script('window.EventSource = class extends EventTarget { close() {} }')
        update = {'state': 'idle', 'name': '', 'version': '', 'done': 0, 'total': 0, 'error': '', 'automatic': False}
        ctx.route('**/api/app/update/status', lambda route: route.fulfill(json=update))
        checks = []
        ctx.route('**/api/app/update', lambda route: (checks.append(route.request.url), route.abort()))
        page = ctx.new_page()
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        page.keyboard.press('Control+Comma')
        win = page.locator('.cw.set-win')
        expect(win.get_by_text('Updates have not been checked yet.', exact=True)).to_be_visible()
        update.update(current='1.0', latest='1.0', newer=False)
        expect(win.get_by_text('1.0 · up to date · from source', exact=True)).to_be_visible()
        del update['current'], update['latest']
        expect(win.get_by_text('Updates have not been checked yet.', exact=True)).to_be_visible()
        assert not checks, checks

        for query, target, action in (
            ('reset', 'backup', 'Reset backup…'),
            ('disconnect', 'account', 'Disconnect Google Drive…'),
            ('remove all phones', 'phones', 'Remove all phones…'),
            ('change passphrase', 'recovery', 'Change passphrase…'),
        ):
            field = win.locator('#set-find')
            field.fill(query)
            field.press('Enter')
            disclosure = win.locator(f'#set-s-sync-{target}-more')
            expect(disclosure).to_be_focused()
            expect(disclosure).to_have_attribute('open', '')
            expect(disclosure.get_by_role('button', name=action, exact=True)).to_be_visible()

        win.locator('#set-tai').click()
        field = win.locator('#k-openai')
        field.fill('synthetic-unsaved-key')
        for method in ('title', 'scrim', 'escape'):
            if method == 'title':
                win.locator('[data-wclose]').click()
            elif method == 'scrim':
                page.locator('#cw-scrim').click(position={'x': 2, 'y': 2})
            else:
                field.press('Escape')
            question = page.get_by_role('alertdialog', name='Close Settings', exact=True)
            expect(question).to_be_visible()
            expect(question.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
            question.get_by_role('button', name='Cancel', exact=True).click()
            expect(field).to_have_value('synthetic-unsaved-key')
        win.locator('[data-wclose]').click()
        page.get_by_role('alertdialog', name='Close Settings', exact=True).get_by_role('button', name='Discard and close').click()
        expect(win).to_have_count(0)
        page.keyboard.press('Control+Comma')
        win.locator('#set-tai').click()
        expect(win.locator('#k-openai')).to_have_value('')
        win.locator('[data-wclose]').click()
        expect(win).to_have_count(0)
        ctx.close()
        print(f'{theme}: idle update truth, backup disclosure search and all dirty-close paths passed', flush=True)

    def parity(self, browser, theme):
        fixture = json.loads((ROOT / 'tests/fixtures/desktop_backup_states.json').read_text(encoding='utf-8'))
        for scenario in ('safe', 'paused-task', 'recovery-unread', 'no-recovery'):
            ctx = self.context(browser, theme)
            ctx.clock.set_fixed_time(datetime.fromtimestamp(fixture['now'] / 1000, timezone.utc))
            cloud = dict(fixture['cloud'])
            rec = dict(fixture['recovery'])
            if scenario == 'paused-task':
                case = next(c for c in fixture['cases'] if c['id'] == 'remove-paused')
                cloud.update(case['cloud'])
                rec.update(case['rec'])
            if scenario == 'no-recovery':
                rec.update(configured=False, enrolled=False, verified=False, saved_at=0, verified_at=0, setup_at=0)
            ctx.route('**/api/cloud', lambda route: route.fulfill(json=cloud))
            if scenario == 'recovery-unread':
                ctx.route('**/api/cloud/recovery', lambda route: route.fulfill(status=409, json={'detail': 'Synthetic recovery read failure.'}))
            else:
                ctx.route('**/api/cloud/recovery', lambda route: route.fulfill(json=rec))
            ctx.add_init_script('''window.EventSource = class extends EventTarget {
                constructor() { super() } close() {}
            };''')
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.url())
            page.wait_for_selector('.cell[data-id]')
            self.settle(page)
            page.keyboard.press('Control+Comma')
            win = page.locator('.cw.set-win')
            expect(win.locator('.set-heading h2')).to_have_text('Overview')
            win.locator('#set-tbackup').click()
            expect(win.locator('.set-heading h2')).to_have_text('Backup & phones')
            if scenario == 'safe':
                expect(win.get_by_text('Your library is safe', exact=False).first).to_be_visible()
            elif scenario == 'paused-task':
                expect(win.get_by_text('Removing all phones is paused too.', exact=False).first).to_be_visible()
            elif scenario == 'recovery-unread':
                expect(win.get_by_text('Synthetic recovery read failure.', exact=False).first).to_be_visible()
            else:
                expect(win.get_by_role('button', name='Create recovery passphrase')).to_be_visible()
            page.evaluate('() => document.fonts.ready')
            for width, height in ((1440, 1000), (390, 844)):
                page.set_viewport_size({'width': width, 'height': height})
                win.locator('.cw-body').evaluate('(e) => e.scrollTop = 0')
                self.shot(page, f'parity-{theme}-{scenario}-{width}')
                if scenario == 'paused-task' and width == 390:
                    win.get_by_role('button', name='Resume backup').scroll_into_view_if_needed()
                    self.shot(page, f'parity-{theme}-{scenario}-task-390')
            assert not errors, errors
            ctx.close()
            print(f'{theme}: {scenario} captured at 1440 and 390', flush=True)


    def desktop(self, browser, theme):
        if self.args.only == 'review-gaps':
            return self.review_gaps(browser, theme)
        if self.args.only == 'parity':
            return self.parity(browser, theme)
        ctx = self.context(browser, theme)
        saved = self.api('GET', '/api/settings')
        if self.args.only == 'placement':
            saved['keys']['openai'] = True
            for provider in saved['models']['providers']:
                if provider['id'] == 'openai':
                    provider['has_key'] = True
            ctx.route('**/api/claude-code', lambda route: route.fulfill(json={'available': True, 'path': '', 'detected': '', 'enabled': False, 'model': 'default', 'models': [], 'auto_approve': False, 'winget': True}))
            obsidian = self.api('GET', '/api/obsidian')
            obsidian.update(vault='C:/synthetic/vault', mode='owner', exists=True, is_vault=True, legacy=False, first_open='')
            obsidian['status'].update(missing=False, other_library=False, error='', busy='', pending=False, adopted=['Synthetic.md'])
            ctx.route('**/api/obsidian', lambda route: route.fulfill(json=obsidian))
        if self.args.only == 'matrix':
            cloud = self.api('GET', '/api/cloud')
            cloud.update(signed_in=True, configured=True, licensed=True, on=True, running=True, state='publishing',
                         account='sample@example.com', last_publish=int(shots.FIXED_TIME.timestamp() * 1000) - 10000,
                         pair_ready=True, error='', error_code='', error_action='', paused_since=0,
                         task={'id': 'synthetic-reset', 'kind': 'reset_backup', 'stage': 'backing-up', 'title': 'Resetting the backup',
                               'step': 2, 'of': 3, 'steps': [{'label': 'New key ready', 'state': 'done'},
                                  {'label': 'Backing up again', 'state': 'active'}, {'label': 'Deleting the old backup', 'state': 'waiting'}],
                               'done': 40, 'total': 100, 'bytes_done': 0, 'bytes_total': 0,
                               'since': int(shots.FIXED_TIME.timestamp() * 1000) - 60000, 'error': '', 'code': '', 'lock': ''})
            recovery = self.api('GET', '/api/cloud/recovery')
            ctx.route('**/api/cloud', lambda route: route.fulfill(json=cloud))
            ctx.route('**/api/cloud/recovery', lambda route: route.fulfill(json=recovery))
            ctx.add_init_script('''window.__cloudStreams = [];
                window.EventSource = class extends EventSource {
                    constructor(...args) { super(...args); window.__cloudStreams.push(this) }
                };''')
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
        expect(win.get_by_text('Checking video tools…', exact=True)).to_be_visible()

        def go(destination):
            if page.viewport_size['width'] <= 600:
                win.locator('#set-section').select_option(destination)
            else:
                win.locator(f'#set-t{destination}').click()
            expect(win.locator('.set-heading h2')).to_have_text(PAGES[destination])

        def find(text, anchor):
            field = win.locator('#set-find-m' if page.viewport_size['width'] <= 600 else '#set-find')
            field.fill(text)
            field.press('Enter')
            expect(win.locator(anchor)).to_be_focused()

        go('general')
        expect(win.locator('#a-tray')).to_be_enabled(timeout=2000)
        page.wait_for_timeout(200)
        assert len(pending_checks) == 2, [r.request.url for r in pending_checks]
        assert not full_checks, full_checks
        for route in pending_checks:
            if route.request.url.endswith('/tools'):
                route.fulfill(json={'tools_dir': '', 'tools': [], 'all_found': False})
            else:
                if self.args.only == 'placement':
                    route.fulfill(json={'state': 'ready', 'version': '1.61.0', 'step': '', 'error': '', 'managed': True, 'supported': True, 'workers': True, 'python': True, 'winget': False})
                else:
                    route.fulfill(json={'state': 'missing', 'supported': True, 'workers': True, 'python': False, 'winget': False})
        ctx.unroute('**/api/settings/tools')
        ctx.unroute('**/api/settings/scraper-runtime')
        ctx.unroute('**/api/app/setup')

        if self.args.only == 'matrix':
            page.evaluate('() => document.fonts.ready')
            assert page.evaluate("document.fonts.status") == 'loaded'
            # Mount every lazy page before checking document-wide IDs and descriptions.
            for destination in PAGES:
                go(destination)
            for width, height in ((1440, 1000), (601, 844), (600, 844), (421, 844), (420, 844), (390, 844), (320, 844)):
                page.set_viewport_size({'width': width, 'height': height})
                expect(win.locator('.set-nav')).to_be_visible() if width > 600 else expect(win.locator('.set-nav')).to_be_hidden()
                expect(win.locator('.set-picker')).to_be_hidden() if width > 600 else expect(win.locator('.set-picker')).to_be_visible()
                if width <= 600:
                    cols = win.locator('.set-picker').evaluate("e => getComputedStyle(e).gridTemplateColumns.split(' ').length")
                    assert cols == (1 if width <= 420 else 2), (theme, width, cols)
                for destination in PAGES:
                    go(destination)
                    assert win.locator('.cw-body').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), (theme, width, destination, 'body overflow')
                    assert win.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), (theme, width, destination, 'window overflow')
                    result = page.evaluate('''() => {
                      const all = [...document.querySelectorAll('[id]')], seen = new Set(), duplicate = [];
                      for (const el of all) { if (seen.has(el.id)) duplicate.push(el.id); seen.add(el.id) }
                      const visible = el => !!el.getClientRects().length && !el.closest('[hidden]');
                      const broken = [...document.querySelectorAll('.set-win [aria-describedby]')].filter(visible).flatMap(el =>
                        el.getAttribute('aria-describedby').split(/\\s+/).filter(Boolean).filter(id => {
                          const target = document.getElementById(id);
                          return !target || (el.matches(':disabled') && (!visible(target) || !target.textContent.trim()));
                        }).map(id => `${el.tagName}#${el.id}: ${id}`));
                      return {duplicate, broken};
                    }''')
                    assert not result['duplicate'], (theme, width, destination, result['duplicate'])
                    assert not result['broken'], (theme, width, destination, result['broken'])
                    if width in (1440, 390):
                        self.shot(page, f'matrix-{theme}-{destination}-{width}')

            # The same task retains its real count without an animated lead after Pause.
            page.set_viewport_size({'width': 1440, 'height': 1000})
            go('backup')
            task = win.locator('#set-panel > div:not([hidden]) section[aria-label="Task"]')
            bar = task.get_by_role('progressbar', name='Resetting the backup')
            expect(bar).to_have_attribute('aria-valuenow', '40')
            page.emulate_media(reduced_motion='no-preference')
            page.evaluate("document.documentElement.classList.remove('motion-off')")
            lead = bar.locator('.lead')
            expect(lead).to_have_count(1)
            assert lead.evaluate("e => getComputedStyle(e).animationName") != 'none'
            page.emulate_media(reduced_motion='reduce')
            assert lead.evaluate("e => getComputedStyle(e).animationName") == 'none'
            cloud.update(seq=cloud['seq'] + 1, on=False, running=False, state='off',
                         paused_since=int(shots.FIXED_TIME.timestamp() * 1000), task={**cloud['task'], 'paused_snapshot': True})
            page.evaluate("data => window.__cloudStreams.forEach(s => s.dispatchEvent(new MessageEvent('cloud', {data: JSON.stringify(data)})))", cloud)
            expect(bar).to_have_attribute('aria-valuenow', '40')
            expect(bar.locator('.lead, .busy')).to_have_count(0)

            # A failed section read must stay visible on Overview while a key draft remains unsaved.
            go('ai')
            win.locator('#k-anthropic').fill('synthetic-unsaved-draft')
            go('imports')
            ctx.route('**/api/settings/scraper-runtime', lambda route: route.fulfill(status=409, json={'detail': 'Synthetic browser status failure.'}))
            win.get_by_role('button', name='Check browser tools again').click()
            expect(win.get_by_role('region', name='Browser tools').get_by_text('Synthetic browser status failure.', exact=True).first).to_be_visible()
            go('overview')
            expect(win.get_by_role('region', name='Your setup at a glance').get_by_text('Synthetic browser status failure.', exact=True)).to_be_visible()
            expect(win.get_by_text('Not saved yet', exact=True).first).to_be_visible()
            expect(win.locator('.cw-foot').get_by_role('button', name='Save', exact=True)).to_have_class(re.compile(r'\bpri\b'))
            go('ai')
            expect(win.locator('#k-anthropic')).to_have_value('synthetic-unsaved-draft')

            # Equivalent CSS viewport for a 1440 x 1000 window at 200% zoom.
            page.set_viewport_size({'width': 720, 'height': 500})
            for destination in PAGES:
                go(destination)
                assert win.locator('.cw-body').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), (theme, destination, '200% equivalent overflow')
                expect(win.locator('.cw-foot')).to_be_visible()
            self.shot(page, f'matrix-{theme}-zoom-equivalent-720')

            # Force Chromium's high contrast rendering and check the text and real progress remain available.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.emulate_media(forced_colors='active', reduced_motion='reduce')
            assert page.evaluate("matchMedia('(forced-colors: active)').matches")
            go('backup')
            expect(win.get_by_role('progressbar', name='Resetting the backup')).to_have_attribute('aria-valuenow', '40')
            self.shot(page, f'matrix-{theme}-forced-colors-390')
            page.emulate_media(forced_colors='none', reduced_motion='reduce')

            # Touch emulation exposes the actual coarse-pointer CSS at the same narrow desktop layout.
            cdp = ctx.new_cdp_session(page)
            cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 1})
            assert page.evaluate("matchMedia('(pointer: coarse)').matches")
            targets = win.locator('.group-box.summary .text-btn:visible').evaluate_all('''els => els.map(e => ({
              name: e.getAttribute('aria-label') || e.textContent.trim(), height: e.getBoundingClientRect().height
            }))''')
            assert targets, (theme, 'no coarse pointer summary targets')
            assert all(target['height'] >= 44 for target in targets), (theme, 'coarse pointer targets under 44px', targets)
            cdp.detach()
            assert not errors, errors
            ctx.close()
            print(f'{theme}: six pages at 1440/601/600/421/420/390/320, IDs, descriptions, motion and draft+failure passed', flush=True)
            return

        if self.args.only == 'placement':
            go('ai')
            expect(win.get_by_role('region', name='Claude Code')).to_be_visible()
            expect(win.locator('#k-openai')).to_have_count(0)
            win.locator('#replace-openai').click()
            openai = win.locator('#k-openai')
            expect(openai).to_be_focused()
            openai.fill('synthetic-replacement')
            fail_key = True
            win.get_by_role('button', name='Save OpenAI key').click()
            expect(win.get_by_role('alert').filter(has_text='Synthetic save failed.')).to_be_visible()
            expect(openai).to_have_value('synthetic-replacement')
            win.get_by_role('button', name='Cancel', exact=True).click()
            expect(win.locator('#replace-openai')).to_be_focused()
            expect(openai).to_have_count(0)
            win.locator('#replace-openai').click()
            openai.fill('discard this synthetic draft')
            openai.press('Escape')
            expect(openai).to_have_count(0)
            expect(win.locator('#replace-openai')).to_be_focused()
            fail_key = False
            win.locator('#replace-openai').click()
            openai.fill('synthetic-replacement')
            win.get_by_role('button', name='Save OpenAI key').click()
            expect(openai).to_have_count(0)
            assert calls[-1] == {'keys': {'openai': 'synthetic-replacement'}}
            key_row = win.locator('#replace-openai').locator('..')
            key_row.get_by_role('button', name='Remove key').click()
            win.get_by_role('button', name='Confirm removal').click()
            expect(win.locator('#k-openai')).to_be_visible()
            assert calls[-1] == {'clear_keys': ['openai']}
            find('refresh model lists', '#set-s-model-refresh')
            expect(win.locator('#set-s-model-refresh')).to_have_attribute('open', '')
            find('export diagnostics', '#set-s-app-diagnostics')
            expect(win.get_by_role('region', name='About').get_by_role('button', name='Export diagnostics', exact=True)).to_be_visible()
            find('quit completely', '#set-s-app-quit')
            expect(win.locator('#set-s-app-quit')).to_have_attribute('open', '')
            go('imports')
            expect(win.locator('#set-s-tools-more').get_by_role('button', name='Browse for ffmpeg')).to_be_hidden()
            expect(win.locator('#set-s-browser-more').get_by_role('button', name='Remove browser tools…')).to_be_hidden()
            find('tool folders', '#set-s-tools-more')
            expect(win.locator('#set-s-tools-more')).to_have_attribute('open', '')
            find('remove browser tools', '#set-s-browser-more')
            expect(win.locator('#set-s-browser-more')).to_have_attribute('open', '')
            win.get_by_role('button', name='Remove browser tools…').click()
            confirm = page.get_by_role('alertdialog', name='Remove browser tools', exact=True)
            expect(confirm).to_be_visible()
            confirm.get_by_role('button', name='Cancel', exact=True).click()
            find('change vault', '#set-s-obsidian-more')
            expect(win.locator('#set-s-obsidian-more')).to_have_attribute('open', '')
            win.get_by_role('list', name='Adopted pages').get_by_role('button', name='Reset to generated').click()
            confirm = page.get_by_role('alertdialog', name='Reset to generated', exact=True)
            expect(confirm).to_be_visible()
            confirm.get_by_role('button', name='Cancel', exact=True).click()
            resets = []
            def reset_vault(route):
                resets.append(route.request.post_data_json)
                route.fulfill(status=409, json={'detail': 'The selected vault changed. Review the current vault and confirm the action again.'})
            ctx.route('**/api/obsidian/reset', reset_vault)
            win.get_by_role('list', name='Adopted pages').get_by_role('button', name='Reset to generated').click()
            page.get_by_role('alertdialog', name='Reset to generated', exact=True).get_by_role('button', name='Reset to generated', exact=True).click()
            expect(win.get_by_role('alert').filter(has_text='The selected vault changed.').first).to_be_visible()
            assert resets == [{'path': 'Synthetic.md', 'expected_vault': 'C:/synthetic/vault'}], resets
            assert not errors, errors
            ctx.close()
            print(f'{theme}: saved key replacement/removal, More controls and search focus passed', flush=True)
            return

        if self.args.only == 'sections':
            requests = []
            def browser_read(route):
                requests.append(route.request.url)
                route.fulfill(status=409, json={'detail': 'Synthetic browser read failure.'})
            ctx.route('**/api/settings/scraper-runtime', browser_read)
            go('overview')
            overview = win.get_by_role('region', name='Your setup at a glance')
            for label in ('Updates', 'Wiskit & AI', 'Imports & downloads', 'Obsidian & map', 'Google account', 'Backup', 'Recovery', 'Phones'):
                expect(overview.get_by_text(label, exact=True)).to_be_visible()
            expect(win.get_by_text('Optional: FFmpeg, ffprobe, yt-dlp, Deno, YouTube EJS need setup.', exact=True)).to_be_visible()
            go('imports')
            expect(win.get_by_role('region', name='Browser tools').get_by_text('Missing: install browser tools, or keep working without them', exact=True)).to_be_visible()
            assert not requests, requests  # seeded child does not issue a duplicate initial read
            win.get_by_role('button', name='Check browser tools again').click()
            expect(win.get_by_role('region', name='Browser tools').get_by_text('Synthetic browser read failure.', exact=True).first).to_be_visible()
            go('overview')
            expect(overview.get_by_text('Synthetic browser read failure.', exact=True)).to_be_visible()
            overview.get_by_role('button', name='Open Imports & downloads').click()
            expect(win.locator('#set-s-tools-browser')).to_be_focused()
            assert len(requests) == 1, requests
            assert not errors, errors
            ctx.close()
            print(f'{theme}: lazy bootstrap, seeded mount and failed-refresh status passed', flush=True)
            return

        for destination in PAGES:
            go(destination)
        go('overview')
        win.locator('#set-panel').focus()
        page.keyboard.press('/')
        expect(win.locator('#set-find')).to_be_focused()
        win.locator('#set-find').fill('test')
        win.locator('#set-find').press('/')
        expect(win.locator('#set-find')).to_have_value('test/')
        win.locator('#set-find').fill('')
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
        expect(openai).to_have_count(0)
        expect(anthropic).to_have_value('synthetic-anthropic')
        assert calls[-1] == {'keys': {'openai': 'synthetic-openai'}}
        expect(win.locator('#replace-openai')).to_be_visible()
        win.locator('.cw-foot').get_by_role('button', name='Discard', exact=True).click()
        expect(anthropic).to_have_value('')

        for width, height in [(1440, 1000), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            for destination in PAGES:
                go(destination)
                assert win.locator('.cw-body').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), (theme, width, destination)
            go('ai')
            win.locator('#replace-openai').scroll_into_view_if_needed()
            self.shot(page, f'{theme}-ai-{width}')
            if width == 390:
                find('cookies', '#set-s-dl-logins')
        assert not errors, errors
        ctx.close()
        print(f'{theme}: production navigation, keyboard, search/focus, drafts, key errors and layout passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', default=str(ROOT / 'web/dist'))
    parser.add_argument('--out')
    parser.add_argument('--sections-only', action='store_true')
    parser.add_argument('--placement-only', action='store_true')
    parser.add_argument('--matrix-only', action='store_true')
    parser.add_argument('--parity-only', action='store_true')
    parser.add_argument('--review-gaps-only', action='store_true')
    options = parser.parse_args()
    args = SimpleNamespace(repo=str(ROOT), dist=options.dist, port=0,
                           out=options.out or tempfile.mkdtemp(prefix='brainamon-browser-shots-'), only='review-gaps' if options.review_gaps_only else 'sections' if options.sections_only else 'placement' if options.placement_only else 'matrix' if options.matrix_only else 'parity' if options.parity_only else None,
                           root=None, themes='dark,light')
    Review(args).go()
