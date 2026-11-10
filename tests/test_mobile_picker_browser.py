"""Category/collection sheets use local synthetic notes and inspect real queued changes."""
import importlib.util
import re
import time
import unittest

from tests.test_mobile_info_browser import ROOT, mobile_browser, synthetic_phone


ART = ROOT / 'build/mobile-picker-review'
LONG = 'Research and reference material for upcoming writing projects and carefully collected reading notes'
NEEDLE = 'Needle category with a complete readable name and ' + 'unbroken' * 12
CATEGORIES = ['Inbox', LONG, NEEDLE, *[f'Category {n:02d} — saved research and reading' for n in range(70)]]


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class MobilePickerBrowser(unittest.TestCase):
    def test_category_and_collection_selection_preserves_drafts_and_autosaves_notes(self):
        from playwright.sync_api import expect

        ART.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width, height in ((320, 720), (390, 844), (568, 320)):
                for theme in ('light', 'dark'):
                    with self.subTest(width=width, height=height, theme=theme), synthetic_phone(browser, base, width, height, theme) as (page, errors):
                        page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                        expect(page.locator('#m-status')).to_be_visible()
                        self.poll(page, "async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        # a phone with no PC copy: source.notes() rejects (projects/phone-add-confirm); each list loads on its own
                        note = page.evaluate("""async categories => {
                          const { source, phone } = await import('/src/mobile/state.svelte.ts')
                          source.myNoteCategories = async () => categories
                          source.notes = async () => { throw new Error('library/meta.json is not in the mirror') }
                          phone.cats = categories.map(name => ({name, count: 1}))
                          const note = await source.createMyNote('Picker autosave note', categories[1])
                          await source.saveMyNote(note.file, note.title, note.category, 'Keep this body.')
                          return note
                        }""", CATEGORIES)
                        page.evaluate("location.hash = '#/cap'")
                        page.locator('#cap-text').fill('Keep this capture draft.')
                        self.to_recap(page)
                        # a new note starts in General; Inbox stays listed because a note uses it
                        trigger = page.get_by_role('button', name='Choose category: General', exact=True)
                        expect(trigger).to_be_visible()
                        trigger.click()
                        sheet = page.get_by_role('dialog', name='Choose category', exact=True)
                        expect(sheet).to_be_visible()
                        self.assert_sheet_fits(page, sheet, width, height)
                        options = sheet.locator('.m-picker-options')
                        self.assertTrue(options.evaluate('e => e.scrollHeight > e.clientHeight'))
                        expect(sheet.get_by_role('button', name='General', exact=True)).to_have_attribute('aria-pressed', 'true')
                        expect(sheet.get_by_role('button', name='Inbox', exact=True)).to_have_count(1)
                        long_option = sheet.get_by_role('button', name=LONG, exact=True)
                        long_option.scroll_into_view_if_needed()
                        self.assertGreater(long_option.bounding_box()['height'], 48)
                        expect(long_option).to_have_text(LONG)
                        sheet.get_by_role('searchbox', name='Search category', exact=True).fill('needle')
                        expect(options.get_by_role('button')).to_have_count(1)
                        expect(options.get_by_role('button', name=NEEDLE, exact=True)).to_have_text(NEEDLE)
                        self.assertTrue(options.evaluate('e => e.scrollWidth <= e.clientWidth'))
                        if (width, theme) == (320, 'dark'):
                            page.screenshot(path=str(ART / 'category-open-dark-320.png'))
                        page.keyboard.press('Escape')
                        expect(sheet).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        expect(trigger).to_have_text('General')
                        trigger.click()
                        expect(sheet.get_by_role('searchbox', name='Search category', exact=True)).to_have_value('')
                        sheet.get_by_role('button', name='Close', exact=True).click()
                        expect(sheet).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        trigger.click()
                        page.mouse.click(3, 3)
                        expect(sheet).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        trigger.click()
                        sheet.get_by_role('searchbox', name='Search category', exact=True).fill('needle')
                        sheet.get_by_role('button', name=NEEDLE, exact=True).click()
                        selected = page.get_by_role('button', name=f'Choose category: {NEEDLE}', exact=True)
                        expect(sheet).not_to_be_visible()
                        expect(selected).to_be_focused()
                        self.assert_trigger_fits(page, selected, width)
                        self.assertTrue(page.locator('#cap-help').evaluate('e => e.scrollWidth <= e.clientWidth'))
                        self.poll(page, """async category => {
                          const {drafts} = await import('/src/mobile/store.ts')
                          return (await drafts.all()).some(d => d.category === category && d.text === 'Keep this capture draft.')
                        }""", NEEDLE)
                        if (width, theme) == (390, 'light'):
                            page.screenshot(path=str(ART / 'capture-long-category-light-390.png'))

                        # Appending to an existing note keeps that note's category read-only.
                        page.get_by_role('button', name='Note to add to', exact=True).click()
                        page.get_by_role('option').filter(has_text=note['title']).click()
                        expect(page.locator('.m-cap-category')).to_contain_text(LONG)
                        expect(page.get_by_role('button', name=f'Choose category: {NEEDLE}', exact=True)).to_have_count(0)
                        page.get_by_role('button', name='Note to add to', exact=True).click()
                        page.get_by_role('button', name='+ New note', exact=True).click()

                        # The Library needs a web link. Its collection starts on INTERESTING (the phone decides, there is
                        # no "PC decides"), and '+ New collection' asks for the name right there.
                        page.get_by_role('button', name='Back', exact=True).click()
                        page.wait_for_function("() => location.hash === '#/cap'")
                        page.locator('#cap-text').fill('Keep this capture draft. https://example.com/picker')
                        self.to_recap(page)
                        page.locator('.m-cap-choice').filter(has_text='Library item').click()
                        collection = page.get_by_role('button', name='Choose collection: INTERESTING', exact=True)
                        expect(collection).to_be_visible()
                        collection.click()
                        collection_sheet = page.get_by_role('dialog', name='Choose collection', exact=True)
                        self.assert_sheet_fits(page, collection_sheet, width, height)
                        collection_sheet.get_by_role('searchbox', name='Search collection', exact=True).fill('needle')
                        collection_sheet.get_by_role('button', name=NEEDLE, exact=True).click()
                        picked_collection = page.get_by_role('button', name=f'Choose collection: {NEEDLE}', exact=True)
                        self.assert_trigger_fits(page, picked_collection, width)
                        picked_collection.click()
                        collection_sheet.get_by_role('button', name='INTERESTING', exact=True).click()
                        self.poll(page, """async () => {
                          const {drafts} = await import('/src/mobile/store.ts')
                          return (await drafts.all()).some(d => d.dest === 'library' && d.collection === 'INTERESTING')
                        }""")
                        collection.click()
                        collection_sheet.get_by_role('searchbox', name='Search collection', exact=True).fill('new collection')
                        collection_sheet.get_by_role('button', name='+ New collection', exact=True).click()
                        expect(collection_sheet).not_to_be_visible()
                        expect(page.get_by_role('textbox', name='New collection name', exact=True)).to_be_visible()
                        expect(page.locator('#cap-help')).to_have_text('Name the new collection, or pick one.')

                        # The editor must emit the selected category to the existing autosave journal.
                        page.evaluate('(file) => { location.hash = `#/mynotes/${encodeURIComponent(file)}` }', note['file'])
                        editor_trigger = page.get_by_role('button', name=f'Choose category: {LONG}', exact=True)
                        expect(editor_trigger).to_be_visible()
                        self.assert_trigger_fits(page, editor_trigger, width)
                        editor_trigger.click()
                        editor_sheet = page.get_by_role('dialog', name='Choose category', exact=True)
                        self.assert_sheet_fits(page, editor_sheet, width, height)
                        editor_sheet.get_by_role('searchbox', name='Search category', exact=True).fill('needle')
                        editor_sheet.get_by_role('button', name=NEEDLE, exact=True).click()
                        expect(page.get_by_role('button', name=f'Choose category: {NEEDLE}', exact=True)).to_be_visible()
                        self.poll(page, """async ({file,category}) => {
                          const {changes} = await import('/src/mobile/store.ts')
                          return (await changes.all()).some(e => e.op === 'note' && e.file === file && e.category === category && e.title === 'Picker autosave note' && e.body === 'Keep this body.')
                        }""", {'file': note['file'], 'category': NEEDLE})
                        expect(page.locator('.np-led')).to_contain_text('Saved')
                        self.assertEqual(errors, [])

    def poll(self, page, script, arg=None, timeout=10):
        """page.wait_for_function takes an async predicate's Promise as truthy and returns at once: poll it here."""
        end = time.monotonic() + timeout
        while not page.evaluate(script, arg):
            self.assertLess(time.monotonic(), end, script)
            page.wait_for_timeout(100)

    def to_recap(self, page):
        """The draft's Save opens the recap (#/cap/save), where the category and the collection are chosen."""
        page.locator('form button[type=submit]').click()
        page.wait_for_function("() => location.hash === '#/cap/save'")

    def assert_trigger_fits(self, page, trigger, width):
        bounds = trigger.bounding_box()
        self.assertGreaterEqual(bounds['x'], 0)
        self.assertLessEqual(bounds['x'] + bounds['width'], width)
        self.assertGreaterEqual(bounds['height'], 44)
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def assert_sheet_fits(self, page, sheet, width, height):
        bounds = sheet.bounding_box()
        self.assertGreaterEqual(bounds['x'], 15)
        self.assertGreaterEqual(bounds['y'], 15)
        self.assertLessEqual(bounds['x'] + bounds['width'], width - 15)
        self.assertLessEqual(bounds['y'] + bounds['height'], height - 15)
        expect_close = sheet.get_by_role('button', name='Close', exact=True).bounding_box()
        self.assertGreaterEqual(expect_close['y'], 0)
        self.assertTrue(sheet.evaluate('e => e.scrollWidth <= e.clientWidth'))
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        colors = sheet.evaluate('e => {const s=getComputedStyle(e); return [s.backgroundColor,s.color]}')
        background, foreground = [[float(n) for n in re.findall(r'[\d.]+', color)] for color in colors]
        self.assertTrue(len(background) == 3 or background[3] >= .99, colors)
        def luminance(rgb):
            channels = [n / 255 for n in rgb[:3]]
            linear = [n / 12.92 if n <= .04045 else ((n + .055) / 1.055) ** 2.4 for n in channels]
            return sum(n * weight for n, weight in zip(linear, (.2126, .7152, .0722)))
        darker, lighter = sorted((luminance(background), luminance(foreground)))
        self.assertGreaterEqual((lighter + .05) / (darker + .05), 4.5, colors)


if __name__ == '__main__':
    unittest.main()
