"""Isolated UI preview checks. No backend, personal storage, site login or library writes.

Run with the existing Vite server: py -X utf8 tests/check_phone_import_prototypes.py
Evidence: local/phone-import-prototypes/. The browser uses a fresh disposable context.
"""
import argparse
import io
import json
import re
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local' / 'phone-import-prototypes'
NAMES = ['Instagram', 'Facebook', 'Threads', 'TikTok']
LABELS = ['Request export', 'Read saved posts', 'Import file']
URLS = [
    'https://accountscenter.instagram.com/info_and_permissions/dyi/',
    'https://accountscenter.facebook.com/info_and_permissions/dyi/',
    'https://www.threads.com/settings/privacy',
    'https://support.tiktok.com/en/account-and-privacy/personalized-ads-and-data/requesting-your-data',
]


def choose(page, variant, name):
    if variant == 2:
        page.get_by_role('group', name='Platform', exact=True).get_by_role('button', name=name, exact=True).click()
    elif variant == 3:
        toggle = page.locator('.m-import-toggle').filter(has=page.get_by_text(name, exact=True))
        if toggle.get_attribute('aria-expanded') != 'true':
            toggle.click()
        assert page.locator('.m-import-toggle[aria-expanded="true"]').count() == 1
    return page.locator('section').filter(has=page.get_by_role('group', name=f'{name} actions', exact=True)).last


def close_help(page):
    dialog = page.get_by_role('dialog')
    assert 'Contributor' not in dialog.inner_text()
    assert 'stays on this phone' not in dialog.inner_text()
    dialog.evaluate("x => { delete x.dataset.closed; x.addEventListener('close', () => x.dataset.closed='true', {once:true}) }")
    dialog_id = dialog.get_attribute('id')
    dialog.get_by_role('button', name='Close', exact=True).click()
    expect(page.locator(f'dialog[id="{dialog_id}"]')).to_have_attribute('data-closed', 'true')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5176/prototypes/phone-import/')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    errors, api_calls = [], []
    payload = json.dumps([{'label_values': [{'label': 'URL', 'value': 'https://www.instagram.com/p/Preview1/'}]}]).encode()
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('saved/saved_posts.json', payload)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=1)
        context.on('page', lambda p: p.on('pageerror', lambda error: errors.append(str(error))))
        context.route(re.compile(r'^https://'), lambda route: route.fulfill(body='<title>Official page target checked</title>'))
        context.route('**/api/**', lambda route: (api_calls.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on('console', lambda msg: errors.append(f'{msg.type}: {msg.text} {msg.location}') if msg.type in ['error', 'warning'] else None)

        for width in [320, 390]:
            page.set_viewport_size({'width': width, 'height': 844})
            for theme in ['light', 'dark']:
                for variant in [1, 2, 3]:
                    page.goto(f'{args.url}?v={variant}')
                    expect(page.locator('[data-variant]')).to_have_attribute('data-variant', str(variant))
                    page.get_by_label('Preview theme').select_option(theme)
                    expect(page.locator('html')).to_have_attribute('data-theme', theme)
                    expect(page.get_by_role('heading', name='Import saved posts', exact=True)).to_be_visible()
                    assert 'I sent it' not in page.locator('.m-import-preview').inner_text()
                    assert 'Requested just now' not in page.locator('.m-import-preview').inner_text()
                    expect(page.locator('.proto-picker-item[aria-current="true"]')).to_have_count(1)
                    page.evaluate('document.fonts.ready')
                    page.screenshot(path=str(OUT / f'{variant}-{theme}-{width}.png'))
                    if variant == 1:
                        assert page.locator('.m-import-name h3').all_text_contents() == NAMES
                        assert page.get_by_role('group', name='Instagram actions', exact=True).count() == 1
                    elif variant == 2:
                        assert page.get_by_role('group', name='Platform', exact=True).get_by_role('button').all_text_contents() == NAMES
                    else:
                        assert page.locator('.m-import-toggle>span:first-child').all_text_contents() == NAMES
                        assert [text.strip() for text in page.locator('.m-import-toggle').all_text_contents()] == NAMES

                    for i, name in enumerate(NAMES):
                        block = choose(page, variant, name)
                        actions = block.get_by_role('group', name=f'{name} actions', exact=True)
                        if variant == 3:
                            assert actions.locator('.m-import-action>.m-btn').evaluate_all('(xs) => xs.map(x => x.getAttribute("aria-label"))') == ['Request export', 'Scan saved posts', 'Import file']
                            assert actions.locator('.m-import-action-caption .m-info span').all_text_contents() == ['Export', 'Scan', 'File']
                            assert actions.locator('.m-import-action-icon svg').count() == 3
                            assert actions.locator('.m-import-action-caption .m-info').count() == 3
                            assert actions.locator('.m-import-action-caption .m-info').evaluate_all('(xs) => xs.every(x => getComputedStyle(x).fontSize === "10px")')
                            assert actions.locator('.m-import-action-caption .m-info svg').evaluate_all('(xs) => xs.every(x => x.getBoundingClientRect().width === 14)')
                            assert actions.locator('button button,a button,button a').count() == 0
                            file_hint = block.locator(f'[id="{actions.get_by_role("button", name="Import file", exact=True).get_attribute("aria-describedby")}"]')
                            expect(file_hint).to_have_class(re.compile('m-sr'))
                            assert block.locator('.m-import-identity').count() == 0
                            expect(block.get_by_role('button', name='Sign in', exact=True)).to_have_count(0)
                            assert actions.locator('.m-import-action').evaluate_all('''xs => xs.every(x => {
                              const action = x.querySelector('.m-btn').getBoundingClientRect();
                              const info = x.querySelector('.m-info').getBoundingClientRect();
                              return action.bottom <= info.top + 0.5;
                            })''')
                        else:
                            assert actions.locator('a,button').all_text_contents() == LABELS
                        expect(actions.get_by_role('button', name='Scan saved posts' if variant == 3 else 'Read saved posts', exact=True)).to_be_disabled()
                        expect(actions.get_by_role('button', name='Import file', exact=True)).to_be_enabled() if i == 0 else expect(actions.get_by_role('button', name='Import file', exact=True)).to_be_disabled()
                        if variant != 3:
                            expect(block.get_by_role('button', name='Sign in', exact=True)).to_be_disabled()
                        link = actions.get_by_role('link', name='Request export', exact=True)
                        assert link.get_attribute('href') == URLS[i]
                        assert link.get_attribute('target') == '_blank'
                        assert 'noopener' in link.get_attribute('rel')
                        assert 'File import unavailable' in block.inner_text() if i else 'Saved ZIP / JSON' in block.inner_text()
                        dims = actions.locator('a,button').evaluate_all('(xs) => xs.map(x => ({w:x.getBoundingClientRect().width,h:x.getBoundingClientRect().height}))')
                        assert all(d['w'] >= 44 and d['h'] >= 44 for d in dims), dims
                        with page.expect_popup() as opened:
                            link.click()
                        popup = opened.value
                        popup.wait_for_url(URLS[i])
                        assert popup.url == URLS[i]
                        popup.close()
                        expect(block.get_by_role('status')).to_have_text(f'Export page opened. Complete your request on {name}.')
                        connection_help = f'More info: {name}: Scan' if variant == 3 else f'More info: {name} export & sign-in'
                        block.get_by_role('button', name=connection_help, exact=True).click()
                        dialog = page.get_by_role('dialog')
                        expect(dialog).to_be_visible()
                        if variant != 3:
                            assert 'opening it does not submit a request' in dialog.inner_text()
                            assert 'Read saved posts is unavailable' in dialog.inner_text()
                        else:
                            assert 'Scanning saved posts is not available yet' in dialog.inner_text()
                            assert 'The site browser is unavailable here' in dialog.inner_text()
                        expect(dialog.get_by_role('button', name='Close', exact=True)).to_be_visible()
                        assert dialog.evaluate('(x) => x.scrollWidth <= x.clientWidth + 1')
                        close_help(page)
                        expect(block.get_by_role('button', name=connection_help, exact=True)).to_be_focused()
                        if variant == 3:
                            for caption in ['Export', 'Scan', 'File']:
                                info = actions.get_by_role('button', name=f'More info: {name}: {caption}', exact=True)
                                expect(info).to_be_enabled()
                                info.click()
                                dialog = page.get_by_role('dialog')
                                expect(dialog).to_be_visible()
                                text = dialog.inner_text()
                                if caption == 'Export':
                                    assert 'opening it does not submit a request' in text
                                    assert dialog.locator('ol li').count() > 0
                                elif caption == 'Scan':
                                    assert 'Scanning saved posts is not available yet' in text
                                    assert f'Opens {name} in the site browser. Sign in there if asked.' in text
                                elif name == 'Instagram':
                                    assert 'Saved ZIP or saved_posts.json, up to 60 MiB' in text
                                    assert 'without saving links' in text
                                else:
                                    assert f'{name} export files are not supported yet' in text
                                assert dialog.evaluate('(x) => x.scrollWidth <= x.clientWidth + 1')
                                close_help(page)
                                expect(info).to_be_focused()

                    choose(page, variant, 'Instagram')
                    page.locator('.m-sheet-body').evaluate('(x) => x.scrollTop=0')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert page.locator('.m-sheet-body').evaluate('(x) => x.scrollWidth <= x.clientWidth + 1')
                    targets = page.locator('.m-import-preview').locator('button:visible,a:visible,summary:visible').evaluate_all('(xs) => xs.map(x => ({text:x.textContent,h:x.getBoundingClientRect().height,w:x.getBoundingClientRect().width}))')
                    assert all(x['h'] >= 44 and x['w'] >= 44 for x in targets), targets
                    results.append(f'{variant}/{theme}/{width}: layout, actions, links, help, focus, touch targets PASS')

        # Exercise state changes and real parser/picker behavior in every direction.
        for variant in [1, 2, 3]:
            page.goto(f'{args.url}?v={variant}')
            block = choose(page, variant, 'Instagram')
            with page.expect_file_chooser() as picked:
                block.get_by_role('button', name='Import file', exact=True).click()
            picked.value.set_files({'name': 'saved_posts.json', 'mimeType': 'application/json', 'buffer': payload})
            expect(block.get_by_role('status')).to_have_text('Preview: 1 link found. Nothing added to your library.')
            for file in [
                {'name': 'saved.zip', 'mimeType': 'application/zip', 'buffer': packed.getvalue()},
                {'name': 'saved_posts.json', 'mimeType': 'application/json', 'buffer': payload},
            ]:
                block.locator('input[type=file]').set_input_files(file)
                expect(block.get_by_role('status')).to_have_text('Preview: 1 link found. Nothing added to your library.')
            block.locator('input[type=file]').set_input_files({'name': 'wrong.json', 'mimeType': 'application/json', 'buffer': b'{}'})
            expect(block.get_by_role('alert')).to_contain_text('This is not Instagram')
            block.locator('input[type=file]').evaluate("x => { const file = new File(['x'], 'large.json', {type:'application/json'}); Object.defineProperty(file, 'size', {value:60*1024*1024+1}); const data = new DataTransfer(); data.items.add(file); x.files=data.files; x.dispatchEvent(new Event('change', {bubbles:true})); }")
            expect(block.get_by_role('alert')).to_contain_text('over 60 MB')

            for scenario in ['signed-out', 'signed-in', 'error', 'busy', 'unavailable']:
                page.get_by_label('Preview reader state').select_option(scenario)
                for name in NAMES:
                    block = choose(page, variant, name)
                    if scenario == 'signed-out':
                        if variant == 3:
                            expect(block.get_by_text('Scan', exact=True)).to_be_visible()
                            block.get_by_role('button', name='Scan saved posts', exact=True).click()
                            expect(block.get_by_role('button', name='Scan saved posts', exact=True)).to_be_enabled()
                            block.get_by_role('button', name=f'More info: {name}: Scan', exact=True).click()
                            expect(page.get_by_role('dialog').get_by_text('Signed in.', exact=True)).to_be_visible()
                            close_help(page)
                        else:
                            expect(block.get_by_text('Not signed in', exact=True)).to_be_visible()
                            block.get_by_role('button', name='Sign in', exact=True).click()
                            expect(block.get_by_text('Signed in', exact=True)).to_be_visible()
                            expect(block.get_by_role('button', name='Read saved posts', exact=True)).to_be_disabled()
                    elif scenario == 'signed-in':
                        expect(block.get_by_text('Scan' if variant == 3 else 'Signed in', exact=True)).to_be_visible()
                        block.get_by_role('button', name=f'More info: {name}: Scan' if variant == 3 else f'More info: {name} export & sign-in').click()
                        dialog = page.get_by_role('dialog')
                        if variant == 3:
                            expect(dialog.get_by_text('Signed in.', exact=True)).to_be_visible()
                        dialog.get_by_role('button', name='Forget login', exact=True).click()
                        expect(dialog.get_by_role('button', name='Tap again to forget login', exact=True)).to_be_visible()
                        dialog.get_by_role('button', name='Cancel', exact=True).click()
                        dialog.get_by_role('button', name='Forget login', exact=True).click()
                        dialog.get_by_role('button', name='Tap again to forget login', exact=True).click()
                        expect(dialog.get_by_role('button', name='Forget login', exact=True)).to_have_count(0)
                        close_help(page)
                        expect(block.get_by_text('Scan' if variant == 3 else 'Not signed in', exact=True)).to_be_visible()
                    elif scenario == 'error':
                        block.get_by_role('button', name='Scan saved posts' if variant == 3 else 'Sign in', exact=True).click()
                        expect(block.get_by_role('alert')).to_have_text('Could not open sign-in. Try again.')
                    elif scenario == 'busy':
                        expect(block.get_by_role('button', name='Scan saved posts' if variant == 3 else 'Opening…', exact=True)).to_be_disabled()
                        if variant == 3:
                            expect(block.get_by_role('button', name='Scan saved posts', exact=True)).to_have_attribute('aria-busy', 'true')
                            expect(block.get_by_text('Opening…', exact=True)).to_be_visible()
                    else:
                        expect(block.get_by_role('button', name='Scan saved posts' if variant == 3 else 'Sign in', exact=True)).to_be_disabled()
                results.append(f'{variant}/{scenario}: all four platforms PASS')
            page.get_by_label('Preview reader state').select_option('actual')
            page.get_by_text('How importing works', exact=True).click()
            expect(page.get_by_text('This prototype checks a selected file on this device and shows the result. It does not add links or sync anything.', exact=True)).to_be_visible()
            assert 'Contributor' not in page.locator('body').inner_text()

        # The refined accordion uses separate rounded boxes and reversible real height transitions.
        page.goto(f'{args.url}?v=3')
        expect(page.locator('.m-import-reveal.open')).to_have_count(1)
        assert page.locator('.m-import-fold.m-box').count() == 4
        assert page.locator('.m-import-fold').evaluate_all('(xs) => xs.every(x => getComputedStyle(x).borderRadius === "12px")')
        assert page.locator('.m-import-expand').evaluate('(x) => getComputedStyle(x).gap') == '8px'
        assert page.locator('.m-import-reveal:not(.open)').evaluate_all('(xs) => xs.every(x => x.inert && x.getAttribute("aria-hidden") === "true")')
        assert page.get_by_role('group', name=re.compile(' actions$')).count() == 1
        assert page.locator('.m-import-reveal').evaluate_all('(xs) => xs.every(x => x.getAnimations().length === 0)')
        sample = page.evaluate('''async () => {
          const panel = document.querySelectorAll('.m-import-reveal')[1];
          const toggle = document.querySelectorAll('.m-import-toggle')[1];
          const frame = () => new Promise(requestAnimationFrame);
          toggle.click(); await frame(); await frame();
          const animations = panel.getAnimations();
          const track = animations.find(x => x.transitionProperty === 'grid-template-rows');
          if (!track) throw new Error('Missing expand transition');
          track.pause(); track.currentTime = 100; await frame();
          const middle = panel.getBoundingClientRect().height;
          const full = panel.querySelector('.m-import-expanded').getBoundingClientRect().height;
          toggle.click(); await frame(); await frame();
          const reversing = panel.getBoundingClientRect().height;
          const closing = panel.getAnimations();
          closing.forEach(x => x.finish()); await frame();
          return {middle, full, reversing, closed:panel.getBoundingClientRect().height,
            duration:track.effect.getTiming().duration};
        }''')
        assert 0 < sample['middle'] < sample['full'], sample
        assert 0 < sample['reversing'] <= sample['middle'] + 1, sample
        assert sample['closed'] == 0 and sample['duration'] == 220, sample
        expect(page.locator('.m-import-toggle[aria-expanded="true"]')).to_have_count(0)
        fb = page.locator('.m-import-toggle').filter(has=page.get_by_text('Facebook', exact=True))
        fb.focus()
        page.keyboard.press('Enter')
        expect(fb).to_have_attribute('aria-expanded', 'true')
        page.keyboard.press('Space')
        expect(fb).to_have_attribute('aria-expanded', 'false')
        page.get_by_label('Preview reader state').select_option('signed-out')
        instagram = choose(page, 3, 'Instagram')
        instagram.get_by_role('button', name='Scan saved posts', exact=True).click()
        choose(page, 3, 'Facebook')
        instagram = choose(page, 3, 'Instagram')
        instagram.get_by_role('button', name='More info: Instagram: Scan', exact=True).click()
        expect(page.get_by_role('dialog').get_by_text('Signed in.', exact=True)).to_be_visible()
        close_help(page)
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.m-import-reveal').first.evaluate('(x) => getComputedStyle(x).transitionDuration') == '0s'
        assert page.locator('.m-import-chevron svg').first.evaluate('(x) => getComputedStyle(x).transitionDuration') == '0s'
        page.emulate_media(reduced_motion='no-preference')
        page.evaluate("async () => { (await import('/src/mobile/state.svelte.ts')).phone.motionOff = true }")
        expect(page.locator('.m-import-expand')).to_have_class(re.compile('m-import-still'))
        assert page.locator('.m-import-reveal').first.evaluate('(x) => getComputedStyle(x).transitionDuration') == '0s'
        page.evaluate("async () => { (await import('/src/mobile/state.svelte.ts')).phone.motionOff = false }")
        results.append('Expand: separate rounded cards, short captions, reversible animation, keyboard, inert panels, retained sign-in and both motion settings PASS')

        # Picker contract, including URL bounds, keyboard guards, reload and reduced motion.
        page.goto(f'{args.url}?v=99')
        expect(page.locator('[data-variant]')).to_have_attribute('data-variant', '1')
        for key, selected in [('2', '2'), ('ArrowRight', '3'), ('ArrowRight', '1'), ('ArrowLeft', '3')]:
            page.locator('h1').click()
            page.keyboard.press(key)
            expect(page.locator('[data-variant]')).to_have_attribute('data-variant', selected)
            assert f'v={selected}' in page.url
        page.reload()
        expect(page.locator('[data-variant]')).to_have_attribute('data-variant', '3')
        page.get_by_label('Preview reader state').focus()
        page.keyboard.press('1')
        expect(page.locator('[data-variant]')).to_have_attribute('data-variant', '3')
        page.locator('h1').click()
        page.keyboard.press('Alt+1')
        expect(page.locator('[data-variant]')).to_have_attribute('data-variant', '3')
        page.keyboard.press('r')
        expect(page.locator('[data-variant]')).to_have_attribute('data-variant', '3')
        page.get_by_role('button', name='Panel', exact=True).click()
        expect(page.locator('[data-variant]')).to_have_attribute('data-variant', '2')
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.proto-picker-highlight').evaluate('(x) => getComputedStyle(x).transitionDuration') == '0s'
        page.get_by_role('button', name='Close Import', exact=True).click()
        expect(page.get_by_role('navigation', name='Actions', exact=True)).to_be_visible()
        page.get_by_role('button', name='Add', exact=True).click()
        expect(page.locator('[data-variant]')).to_be_visible()
        assert not api_calls, api_calls
        assert not errors, errors
        results.append('Picker, real shell reopen, reduced motion, no API calls or console errors PASS')
        browser.close()

    (OUT / 'browser-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'PASS: {len(results)} groups; 12 screenshots; no API calls or console errors.')


if __name__ == '__main__':
    main()
