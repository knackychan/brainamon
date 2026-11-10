"""The phone note page (docs/superpowers/specs/2026-11-07-phone-note-page-design.md): floating keys, the
category tag whose dot is the save state, the formatting pill above Android's buttons and the canvas dots.
(Plan 08's Wiskit part was dropped: phone-wiskit-chat replaced that screen.) Synthetic standalone phone,
temporary browser data only.
Run:  py -m unittest tests.test_phone_note_page_browser -v
"""
import importlib.util
import unittest

from tests.test_mobile_info_browser import ROOT, mobile_browser, synthetic_phone

ART = ROOT / 'build/phone-note-page'


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneNotePageBrowser(unittest.TestCase):
    def open_note(self, page, base, expect, category='Health'):
        page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
        expect(page.locator('#m-status')).to_be_visible()
        page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
        note = page.evaluate("""async category => {
          const { source } = await import('/src/mobile/state.svelte.ts')
          source.notes = async () => []
          const note = await source.createMyNote('Knee prehab', category)
          await source.saveMyNote(note.file, note.title, category, 'Three short sessions beat one long one.')
          return note
        }""", category)
        page.evaluate("location.hash = '#/notes'")
        expect(page.locator('.m-sheet-keys')).to_have_count(1)
        page.evaluate('(file) => { location.hash = `#/mynotes/${encodeURIComponent(file)}` }', note['file'])
        expect(page.get_by_role('button', name=f'Choose category: {category}', exact=True)).to_be_visible()
        return note

    def test_note_page_keys_tag_pill_and_dots(self):
        from playwright.sync_api import expect
        ART.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width, height, theme in ((320, 720, 'light'), (390, 844, 'dark')):
                with self.subTest(width=width, theme=theme), synthetic_phone(browser, base, width, height, theme) as (page, errors):
                    self.open_note(page, base, expect)
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    head = page.locator('.np-head')
                    # an open note has no sheet head: its own Back key, no Close key
                    expect(page.locator('.m-sheet-head')).to_have_count(0)
                    expect(page.get_by_role('button', name='Close Notes', exact=True)).to_have_count(0)
                    expect(head.get_by_role('button', name='Back', exact=True)).to_be_visible()
                    # the tag's dot is the save state; no "Saved" words on the page
                    expect(page.locator('.np-tag')).to_have_attribute('data-s', 'saved')
                    expect(page.locator('.np-tag .np-led')).to_contain_text('Saved')
                    expect(page.locator('.np-tag .np-led .m-sr')).to_have_count(1)
                    for name in ('Undo', 'Redo', 'Note actions'):
                        box = head.get_by_role('button', name=name, exact=True).bounding_box()
                        self.assertLessEqual(box['x'] + box['width'], width)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    # the pill floats 14 px above the bottom and 10 px from the sides (Android's inset is 0 here)
                    dock = page.locator('.np-dock').bounding_box()
                    self.assertAlmostEqual(height - (dock['y'] + dock['height']), 14, delta=1)
                    self.assertAlmostEqual(dock['x'], 10, delta=1)
                    # the canvas's dots under the whole note
                    size = page.locator('.np').evaluate('e => getComputedStyle(e).backgroundSize.split(",")[0].trim()')
                    self.assertEqual(size, '16px 16px')
                    # the paper fills the sheet: no bare sheet colour under a short note
                    self.assertGreaterEqual(page.locator('.np').bounding_box()['height'], height - 2)
                    # the exact save state is in the note menu
                    head.get_by_role('button', name='Note actions', exact=True).click()
                    expect(page.locator('.np-sh-led')).to_contain_text('Saved')
                    page.locator('.np-more').get_by_role('button', name='Close', exact=True).click()
                    page.screenshot(path=str(ART / f'note-{width}-{theme}.png'))
                    # Back returns to the Notes list, whose floating keys are back
                    head.get_by_role('button', name='Back', exact=True).click()
                    expect(page.locator('.m-sheet-keys')).to_have_count(1)
                    self.assertEqual(errors, [])

    def test_new_and_rename_categories_queue_the_right_changes(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            note = self.open_note(page, base, expect)
            sheet = page.get_by_role('dialog', name='Choose category', exact=True)
            # New category moves this note; its next save carries the name (no new change type)
            page.get_by_role('button', name='Choose category: Health', exact=True).click()
            sheet.get_by_role('button', name='+ New category…', exact=True).click()
            dialog = page.get_by_role('dialog', name='New category', exact=True)
            dialog.get_by_role('textbox', name='Category name', exact=True).fill('  Training ')
            dialog.get_by_role('button', name='Add', exact=True).click()
            expect(page.get_by_role('button', name='Choose category: Training', exact=True)).to_be_visible()
            page.wait_for_function("""async file => { const {changes} = await import('/src/mobile/store.ts')
              return (await changes.all()).some(e => e.op === 'note' && e.file === file && e.category === 'Training') }""", arg=note['file'])
            expect(page.locator('.np-tag')).to_have_attribute('data-s', 'saved')
            # Rename: one note_category change, shown at once
            page.get_by_role('button', name='Choose category: Training', exact=True).click()
            sheet.get_by_role('button', name='Rename “Training”…', exact=True).click()
            dialog = page.get_by_role('dialog', name='Rename “Training”', exact=True)
            dialog.get_by_role('textbox', name='Category name', exact=True).fill('Gym')
            dialog.get_by_role('button', name='Rename', exact=True).click()
            expect(page.get_by_role('button', name='Choose category: Gym', exact=True)).to_be_visible()
            page.wait_for_function("""async () => { const {changes} = await import('/src/mobile/store.ts')
              return (await changes.all()).some(e => e.op === 'note_category' && e.from === 'Training' && e.to === 'Gym') }""")
            cats = page.evaluate("async () => (await import('/src/mobile/state.svelte.ts')).source.myNoteCategories()")
            self.assertIn('Gym', cats)
            self.assertNotIn('Training', cats)
            # a name another category has asks first; No goes back to the field
            page.get_by_role('button', name='Choose category: Gym', exact=True).click()
            sheet.get_by_role('button', name='Rename “Gym”…', exact=True).click()
            page.get_by_role('dialog', name='Rename “Gym”', exact=True).get_by_role('textbox', name='Category name', exact=True).fill('general')
            page.get_by_role('dialog', name='Rename “Gym”', exact=True).get_by_role('button', name='Rename', exact=True).click()
            question = page.get_by_role('dialog', name='Move notes?', exact=True)
            expect(question).to_contain_text('General already exists. Move 1 note into it?')
            question.get_by_role('button', name='No', exact=True).click()
            expect(page.get_by_role('dialog', name='Rename “Gym”', exact=True).get_by_role('textbox', name='Category name', exact=True)).to_be_visible()
            page.get_by_role('dialog', name='Rename “Gym”', exact=True).get_by_role('button', name='Cancel', exact=True).click()
            # General has New but no Rename
            page.get_by_role('button', name='Choose category: Gym', exact=True).click()
            sheet.get_by_role('button', name='General', exact=True).click()
            page.get_by_role('button', name='Choose category: General', exact=True).click()
            expect(sheet.locator('.m-picker-foot button')).to_have_count(1)
            sheet.get_by_role('button', name='Close', exact=True).click()
            # a paired PC that does not announce note_category refuses; one that does accepts
            blocked = page.evaluate("""async () => { const {source} = await import('/src/mobile/state.svelte.ts')
              source.pair.solo = false; const before = source.manifest; source.manifest = { ...(before || {}), note_category: undefined }
              const off = source.renameBlocked(); source.manifest = { ...(before || {}), note_category: 1 }
              const on = source.renameBlocked(); source.manifest = before; source.pair.solo = true; return [off, on] }""")
            self.assertEqual(blocked, ['Update Brainamon on the PC to rename.', ''])
            self.assertEqual(errors, [])

    def test_save_after_rename_preserves_order_and_storage_failure_keeps_the_queue(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            note = self.open_note(page, base, expect)
            result = page.evaluate("""async file => {
              const {source} = await import('/src/mobile/state.svelte.ts')
              const {changes} = await import('/src/mobile/store.ts')
              const {Changes} = await import('/src/mobile/mirror/changes.ts')
              await source.renameMyNoteCategory('Health', 'Gym')
              const before = await changes.all(), remove = IDBObjectStore.prototype.delete
              IDBObjectStore.prototype.delete = function(key) {
                if (this.name === 'changes') throw Error('test write failed')
                return remove.call(this, key)
              }
              let error = ''
              try { await source.saveMyNote(file, 'Knee plan', 'Health', 'Latest.') }
              catch (e) { error = e.message }
              finally { IDBObjectStore.prototype.delete = remove }
              const failed = await changes.all(), failedNote = await source.myNote(file)
              await source.saveMyNote(file, 'Knee plan', 'Health', 'Latest.')
              const fresh = new Changes(); await fresh.load()
              return {before, failed, failedNote, error, queue: fresh.list, note: await source.myNote(file)}
            }""", note['file'])
            self.assertEqual(result['error'], 'test write failed')
            self.assertEqual(result['failed'], result['before'])
            self.assertEqual(result['failedNote']['category'], 'Gym')
            queue = result['queue']
            self.assertEqual([e['op'] for e in queue], ['note_category', 'note'])
            self.assertGreater(queue[-1]['id'], queue[0]['id'])
            self.assertEqual(queue[-1]['was'], result['before'][0]['was'])
            self.assertEqual((result['note']['category'], result['note']['body']), ('Health', 'Latest.'))
            self.assertEqual(errors, [])

    def test_canvas_screens_share_the_dots(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/canvas/new', wait_until='domcontentloaded')
            board = page.locator('.m-cv').first
            expect(board).to_be_visible()
            size = board.evaluate('e => getComputedStyle(e).backgroundSize.split(",")[0].trim()')
            self.assertEqual(size, '16px 16px')
            self.assertEqual(errors, [])
