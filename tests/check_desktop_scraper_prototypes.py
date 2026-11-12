"""Offline scraper design checks; no backend, logins or library changes.

Run: python -X utf8 tests/check_desktop_scraper_prototypes.py
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/desktop-scraper-prototypes'
VARIANTS = ['Workspace', 'Expand', 'Guided']
SITES = ['facebook', 'instagram', 'threads', 'youtube', 'reddit']


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert page.locator('.ds-window:visible').evaluate('(x) => x.scrollWidth <= x.clientWidth + 1')


def check_context(page, out):
    page.set_viewport_size({'width': 1280, 'height': 980})
    page.get_by_label('Preview theme').select_option('light')
    for variant in VARIANTS:
        page.get_by_role('button', name=variant, exact=True).click()
        window = page.locator('.ds-window:visible')
        expect(window.locator('.wtitle')).to_have_text('Scrapers')
        expect(window.locator('.wcode')).to_have_text('SCR-08')
        expect(window.locator('.wdots i')).to_have_count(2)
        metrics = window.evaluate('''x => {
          const windowStyle = getComputedStyle(x);
          const bar = getComputedStyle(x.querySelector('.wbar'));
          return { width:x.getBoundingClientRect().width, titlebar:parseFloat(bar.height),
            border:parseFloat(windowStyle.borderTopWidth), shadow:windowStyle.boxShadow };
        }''')
        assert abs(metrics['width'] - 700) <= .5, metrics
        assert metrics['titlebar'] == 36, metrics
        assert 2 <= metrics['border'] <= 2.5, metrics
        assert '8px 8px 0px 0px' in metrics['shadow'], metrics
        section = choose_site(page, variant, 'instagram')
        work = choose_action(section, variant, 'scan')
        primary = work.locator('.ds-primary').evaluate('''x => {
          const style = getComputedStyle(x);
          return { font:style.fontFamily, background:style.backgroundColor };
        }''')
        assert 'IBM Plex Mono' in primary['font'], primary
        assert primary['background'] == 'rgb(43, 209, 126)', primary
    for width in [1280, 390]:
        page.set_viewport_size({'width': width, 'height': 980})
        for theme in ['light', 'dark']:
            page.get_by_label('Preview theme').select_option(theme)
            page.get_by_role('button', name='Expand', exact=True).click()
            section = choose_site(page, 'Expand', 'instagram')
            choose_action(section, 'Expand', 'scan')
            no_overflow(page)
            page.evaluate('document.fonts.ready')
            page.screenshot(path=str(out / f'context-expand-{theme}-{width}.png'), full_page=True)
    page.set_viewport_size({'width': 1280, 'height': 980})


def choose_site(page, variant, site):
    section = page.locator('[data-variant]:visible')
    if variant == 'Guided':
        while section.locator('[data-back]:visible').count():
            section.locator('[data-back]').click()
    button = section.locator(f'button[data-site="{site}"]')
    if variant != 'Expand' or button.get_attribute('aria-expanded') != 'true':
        button.click()
    if variant == 'Expand':
        expect(section.locator('[data-site][aria-expanded="true"]')).to_have_count(1)
    if variant == 'Guided':
        section.locator('[data-next]').click()
        expect(section.locator('[data-action][aria-pressed=true]')).to_be_focused()
    logo = section.locator(f'[data-brand="{site}"]:visible img').first
    expect(logo).to_be_visible()
    assert logo.get_attribute('src').startswith('data:image/svg+xml;base64,')
    logo.evaluate('(image) => image.decode()')
    assert logo.evaluate('(image) => image.naturalWidth > 0')
    return section


def choose_action(section, variant, action):
    if variant == 'Guided' and section.locator('.ds-work').count():
        section.locator('[data-back]').click()
    expect(section.locator(f'[data-action="{action}"]')).to_be_visible()
    section.locator(f'[data-action="{action}"]').click()
    if variant == 'Guided':
        section.locator('[data-next]').click()
        field = '[data-playlist]' if action == 'playlist' else '[data-remember]' if action == 'scan' else '[data-help]'
        expect(section.locator(field)).to_be_focused()
    work = section.locator('.ds-work')
    expect(work).to_be_visible()
    return work


def check_action(work, site, action):
    help_button = work.locator('[data-help]')
    expect(help_button).to_have_attribute('aria-expanded', 'false')
    expect(work.locator('.ds-help')).to_be_hidden()
    help_button.click()
    expect(help_button).to_have_attribute('aria-expanded', 'true')
    expect(work.locator('.ds-help')).to_be_visible()
    assert work.locator('.ds-help').inner_text().strip()
    help_button.click()
    expect(work.locator('.ds-help')).to_be_hidden()
    if action != 'file':
        advanced = work.locator('.ds-advanced')
        assert advanced.get_attribute('open') is None
        advanced.locator('summary').click()
        expect(advanced).to_have_attribute('open', '')
        if action != 'playlist':
            work.locator('[data-stop]').fill('Already imported title')
        if action != 'playlist':
            removal = work.get_by_label('Remove from saved posts after export', exact=True)
            if site == 'youtube':
                expect(work.locator('[data-unsave]')).to_have_count(0)
            else:
                expect(removal).not_to_be_checked()
                if site == 'threads' or (action == 'script' and site != 'facebook'):
                    expect(removal).to_be_disabled()
                else:
                    expect(removal).to_be_enabled()
    if action == 'file':
        with work.page.expect_file_chooser() as opened:
            work.locator('[data-run]').click()
        opened.value.set_files({'name': 'saved.csv', 'mimeType': 'text/csv', 'buffer': b'url,title\n'})
        expect(work.locator('[role=status]')).to_contain_text('saved.csv selected')
        work.locator('[data-csv]').set_input_files({'name': 'wrong.txt', 'mimeType': 'text/plain', 'buffer': b'bad'})
        expect(work.locator('[role=status]')).to_have_attribute('data-error', 'true')
    elif action == 'playlist':
        work.locator('[data-playlist]').fill('https://example.com/playlist?list=abc')
        work.locator('[data-run]').click()
        expect(work.locator('[role=status]')).to_have_attribute('data-error', 'true')
        work.locator('[data-playlist]').fill('https://www.youtube.com/playlist?list=PLexample')
        work.locator('[data-run]').click()
        expect(work.locator('[role=status]')).to_have_text('Preview: playlist link checked. No import started.')
        expect(work.locator('[role=status]')).to_have_attribute('data-error', 'false')
    else:
        work.locator('[data-run]').click()
        expect(work.locator('[role=status]')).to_contain_text('Preview:')
        expect(work.locator('[role=status]')).to_contain_text('No scan started.' if action == 'scan' else 'No browser opened.')


def check_removal(page, variant, out):
    section = choose_site(page, variant, 'facebook')
    work = choose_action(section, variant, 'script')
    work.locator('.ds-advanced summary').click()
    removal = work.get_by_label('Remove from saved posts after export', exact=True)
    expect(removal).to_be_enabled()
    expect(removal).not_to_be_checked()
    removal.check()
    expect(work.locator('.ds-safe')).to_have_text('Removes saves after export')
    if variant == 'Expand':
        page.screenshot(path=str(out / 'remove-option.png'), full_page=True)
    work.locator('[data-run]').click()
    dialog = page.get_by_role('dialog', name='Remove saved posts after export?', exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
    expect(dialog).to_contain_text('Facebook')
    expect(dialog).to_contain_text('changes your original account')
    if variant == 'Expand':
        page.screenshot(path=str(out / 'remove-confirmation.png'), full_page=True)
    dialog.get_by_role('button', name='Cancel', exact=True).click()
    expect(dialog).to_be_hidden()
    expect(work.locator('[role=status]')).to_have_text('Preview cancelled. No account changes.')
    work.locator('[data-run]').click()
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(work.locator('[role=status]')).to_have_text('Preview cancelled. No account changes.')
    work.locator('[data-run]').click()
    dialog.get_by_role('button', name='Continue', exact=True).click()
    expect(dialog).to_be_hidden()
    expect(work.locator('[role=status]')).to_have_text('Preview: removal after export confirmed. No scan started and no posts removed.')

    for site in ['instagram', 'reddit', 'threads']:
        section = choose_site(page, variant, site)
        work = choose_action(section, variant, 'scan')
        work.locator('.ds-advanced summary').click()
        other = work.get_by_label('Remove from saved posts after export', exact=True)
        expect(other).not_to_be_checked()
        if site == 'threads':
            expect(other).to_be_disabled()
            expect(work.get_by_text('Threads is read-only.', exact=True)).to_be_visible()
        else:
            expect(other).to_be_enabled()

    section = choose_site(page, variant, 'facebook')
    work = choose_action(section, variant, 'scan')
    work.locator('.ds-advanced summary').click()
    expect(work.locator('[data-unsave]')).not_to_be_checked()
    work = choose_action(section, variant, 'script')
    work.locator('.ds-advanced summary').click()
    expect(work.locator('[data-unsave]')).to_be_checked()
    expect(work.locator('.ds-safe')).to_have_text('Removes saves after export')
    work.locator('[data-unsave]').uncheck()
    expect(work.locator('.ds-safe')).to_have_text('Saves stay in your account')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url')
    parser.add_argument('--context', action='store_true', help='Check the previews inside the existing desktop frame')
    args = parser.parse_args()
    url = args.url or (ROOT / 'web/prototypes/desktop-scrapers' / ('context.html' if args.context else 'index.html')).as_uri()
    out = OUT / 'context' if args.context else OUT
    out.mkdir(parents=True, exist_ok=True)
    errors, requests, results = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 980})
        context.route('http://**', lambda route: (requests.append(route.request.url), route.abort()))
        context.route('https://**', lambda route: (requests.append(route.request.url), route.abort()))
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        if args.context:
            check_context(page, out)
            results.append('Existing desktop frame, dimensions, controls and theme fidelity PASS')
        for variant in VARIANTS:
            page.get_by_role('button', name=variant, exact=True).click()
            expect(page.locator('[data-variant]:visible')).to_have_attribute('data-variant', variant)
            for site in SITES:
                section = choose_site(page, variant, site)
                for action in ['playlist' if site == 'youtube' else 'scan', 'script', 'file']:
                    work = choose_action(section, variant, action)
                    check_action(work, site, action)
                    no_overflow(page)
            results.append(f'{variant}: five platforms, three methods, Help, advanced and preview actions PASS')
            check_removal(page, variant, out)
            results.append(f'{variant}: optional per-platform removal, confirmation, Cancel/Escape and isolation PASS')

        for width in [1280, 800, 390]:
            page.set_viewport_size({'width': width, 'height': 980})
            for theme in ['light', 'dark']:
                page.get_by_label('Preview theme').select_option(theme)
                for variant in VARIANTS:
                    page.get_by_role('button', name=variant, exact=True).click()
                    for site in ['instagram', 'threads']:
                        section = choose_site(page, variant, site)
                        if variant != 'Guided' or site == 'threads':
                            choose_action(section, variant, 'scan')
                        no_overflow(page)
                        page.evaluate('document.fonts.ready')
                        page.screenshot(path=str(out / f'{variant.lower()}-{site}-{theme}-{width}.png'))
                    results.append(f'{variant} at {width}px {theme}: no overflow PASS')

        page.locator('.wtitle:visible' if args.context else 'h1:visible').click()
        for key, variant in [('1', 'Workspace'), ('2', 'Expand'), ('3', 'Guided')]:
            page.keyboard.press(key)
            expect(page.locator('[data-variant]:visible')).to_have_attribute('data-variant', variant)
        section = choose_site(page, 'Guided', 'threads')
        work = choose_action(section, 'Guided', 'script')
        work.locator('.ds-advanced summary').click()
        work.locator('[data-stop]').fill('3')
        page.keyboard.press('1')
        expect(page.locator('[data-variant]:visible')).to_have_attribute('data-variant', 'Guided')
        page.reload()
        expect(page.locator('[data-variant]:visible')).to_have_attribute('data-variant', 'Guided')
        page.emulate_media(reduced_motion='reduce')
        page.get_by_role('button', name='Workspace', exact=True).click()
        assert page.locator('[data-variant="Workspace"] .ds-method').first.evaluate('(x) => getComputedStyle(x).transitionDuration') == '0s'
        results.append('Variant keyboard, input guard, URL persistence and reduced motion PASS')
        assert not requests, requests
        assert not errors, errors
        browser.close()
    (out / 'browser-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'PASS: {len(results)} groups; {42 if args.context else 38} screenshots; no network requests or JavaScript errors.')


if __name__ == '__main__':
    main()
