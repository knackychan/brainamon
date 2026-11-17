"""System-bar and cutout geometry with real CSS env() values and disposable phone data."""
import importlib.util
import unittest

from tests.test_mobile_info_browser import ROOT, mobile_browser, synthetic_phone


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneInsetsBrowser(unittest.TestCase):
    def test_controls_clear_system_bars_and_landscape_cutouts(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base):
            for width, height, top, right, bottom, left in (
                (390, 844, 32, 0, 24, 0),     # portrait / gesture navigation
                (390, 844, 32, 0, 48, 0),     # portrait / three-button navigation
                (844, 390, 0, 24, 24, 44),    # landscape / left cutout
                (844, 390, 0, 44, 24, 24),    # landscape / right cutout
                (844, 280, 0, 44, 0, 0),     # keyboard-resized viewport
                (390, 844, 0, 0, 0, 0),      # older WebView: native padding, zero CSS insets
            ):
                with self.subTest(size=(width, height), insets=(top, right, bottom, left)), \
                        synthetic_phone(browser, base, width, height, 'light') as (page, errors):
                    cdp = page.context.new_cdp_session(page)
                    cdp.send('Emulation.setSafeAreaInsetsOverride', {
                        'insets': dict(top=top, right=right, bottom=bottom, left=left)})
                    page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                    expect(page.locator('#m-app')).to_be_visible()
                    page.wait_for_function("async () => {const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried&&!phone.refreshing}")
                    note = page.evaluate("""async () => {
                        const {saveOnb} = await import('/src/mobile/onboard.svelte.ts');
                        await saveOnb({answer:'phone',hidden:true,coach:true});
                        const {source,phone} = await import('/src/mobile/state.svelte.ts');
                        phone.motionOff=true;
                        document.documentElement.classList.add('motion-off');
                        source.notes=async()=>[];
                        return await source.createMyNote('Inset test', 'Other');
                    }""")

                    def safe(selector):
                        element = page.locator(selector)
                        expect(element).to_be_visible()
                        # Wait for sheet transitions/layout after hash navigation.
                        expect(element).to_have_css('transform', 'none')
                        box = element.bounding_box()
                        self.assertGreaterEqual(box['x'], left - 1, selector)
                        self.assertLessEqual(box['x'] + box['width'], width - right + 1, selector)
                        self.assertGreaterEqual(box['y'], top - 1, selector)
                        self.assertLessEqual(box['y'] + box['height'], height - bottom + 1, selector)

                    safe('.m-page-keys')
                    for route, selectors in (
                        ('#/lib', ('.m-top', '.m-dock')),
                        ('#/cap', ('.m-sheet-keys', '.m-cap-actions')),
                        ('#/notes', ('.m-sheet-keys',)),
                        ('#/mynotes/' + note['file'], ('.np-head', '.np-dock')),
                    ):
                        page.evaluate('(route) => {location.hash=route}', route)
                        for selector in selectors:
                            safe(selector)
                        if route == '#/cap':
                            page.get_by_role('button', name='Import & drafts', exact=True).click()
                            safe('.m-cap-pop[open]')
                            page.keyboard.press('Escape')
                            page.locator('.m-sheet-layer .m-info:visible').first.click()
                            safe('.m-info-dialog[open]')
                            page.keyboard.press('Escape')
                    page.get_by_role('button', name='Choose category: Other', exact=True).click()
                    safe('.m-picker-sheet')
                    page.keyboard.press('Escape')
                    if height == 280:
                        # The native keyboard watcher selects the editor's full-width toolbar.
                        page.evaluate("document.documentElement.classList.add('typing', 'kb')")
                        safe('.np-dock')
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    self.assertEqual(errors, [])
