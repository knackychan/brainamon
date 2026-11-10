"""The phone's Add page: one mixed draft, the Import & drafts panel and the recap (projects/phone-add-sheet, then
projects/phone-add-confirm).

Isolated: Vite only (web/), a synthetic solo pairing in localStorage, every https and /api request refused, no
Drive, no PC, no AI call, no data folder. source.notes() rejects as on a phone with no PC copy ("library/meta.json
is not in the mirror"). A bottom inset like Android's three buttons is simulated with a style tag. Checks the
draft (C1), the panel that drops from its key (C2), the recap for a new note (R2), a lone link to the Library
(R2a), a long note (R2b), a picture not read yet with its buttons over its thumbnail (R2c), an addition (R2d), the
Library's collection (INTERESTING, then the one used last; a new one needs its name) and Suggest with the phone's AI
key (R2e: it asks first, a refused call says so, a stubbed answer fills the collection and the tags, nothing is
queued), the saves, a share arriving on the recap, the keyboard rule, 360 x 780 and 320 x 568 with the inset cleared.
Screenshots (light and dark) go to local/phone-add/.

    py tests/check_phone_add_browser.py
"""
import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import expect  # noqa: E402

from tests.test_mobile_info_browser import PAIR, mobile_browser, synthetic_phone  # noqa: E402

ART = ROOT / 'local/phone-add'
INSET = 44
VIEW = (360, 780)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
# boot() (Mobile.svelte's onMount) adds the hashchange listener: a hash set before #m-app exists is never read,
# so the page counts as settled only once the app is mounted and its first refresh is over
SETTLED = ("async () => { const { phone } = await import('/src/mobile/state.svelte.ts');"
           " return phone.tried && !phone.refreshing && !!document.getElementById('m-app') }")
# a phone with no PC copy: source.notes() rejects (found on Fred's phone). The synthetic solo phone has no copy
# either; if a later build answers anyway, the call is made to reject the same way, never to answer.
NO_PC_COPY = """async () => {
  const { source } = await import('/src/mobile/state.svelte.ts')
  const rejects = () => source.notes().then(() => false, () => true)
  if (!(await rejects())) source.notes = async () => { throw new Error('library/meta.json is not in the mirror') }
  return rejects()
}"""
MAKE_NOTE = """async () => {
  const { source } = await import('/src/mobile/state.svelte.ts')
  const note = await source.createMyNote('Bookshop list', 'Reading')
  await source.saveMyNote(note.file, note.title, note.category, 'Ten books to read.')
  return note
}"""
# a second draft arrives without taking the screen (as a share kept by the service worker would)
KEEP_OTHER = """async () => {
  const { keepDraft } = await import('/src/mobile/capture.svelte.ts')
  const { newDraft } = await import('/src/lib/capture.ts')
  await keepDraft({ ...newDraft('share', 'https://www.youtube.com/watch?v=8Kf3nQ2'), at: Date.now() - 12 * 60000 })
}"""
SHARE_NOW = """async () => {
  const { shareIn } = await import('/src/mobile/capture.svelte.ts')
  await shareIn('https://example.com/shared-now')
}"""
DESCRIBE = 'AI describes what the photo shows and copies its visible text into your draft. Review the result before saving.'
SUGGEST_SAYS = ('Wiskit reads the link and what its page says, then picks one of your collections and a few tags. '
                'It uses the AI key on this phone.')
# no AI call in an isolated check: once the refused call is seen, Wiskit's answer is stubbed
STUB_SUGGEST = """async () => {
  const { source } = await import('/src/mobile/state.svelte.ts')
  source.suggestCategory = async () => ({ category: 'COOKING', tags: 'knives, technique' })
}"""
# the phone's queued changes and its outbox: Suggest adds to neither
QUEUED = """async () => {
  const { changes, outbox } = await import('/src/mobile/store.ts')
  return (await changes.all()).length + (await outbox.all()).length
}"""
LONG ='\n'.join(f'Line {n}: a step of the recipe that keeps going for a while.' for n in range(1, 25))


def fits(page):
    assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), 'the page is wider than the screen'


def shoot(page, name):
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        page.wait_for_timeout(150)
        fits(page)
        page.screenshot(path=str(ART / f'{name}-{theme}.png'))
    page.evaluate("document.documentElement.dataset.theme = 'light'")


def clear_of_inset(page, width, height):
    """The composer ends above the simulated inset (8 px of margin, then the inset) and 10 px from the sides."""
    box = page.locator('.m-cap-dock').bounding_box()
    assert box['y'] + box['height'] <= height - INSET - 8 + 0.5, box
    assert box['x'] >= 10 - 0.5 and box['x'] + box['width'] <= width - 10 + 0.5, box
    return box


def no_overflow(page, selector):
    for box in page.locator(selector).evaluate_all('xs => xs.map(e => ({ s: e.scrollWidth, c: e.clientWidth }))'):
        assert box['s'] <= box['c'], (selector, box)


def inside(page, outer, inner):
    """The inner element is drawn within the outer one (a stray global class once pulled the addition out)."""
    o, i = page.locator(outer).bounding_box(), page.locator(inner).bounding_box()
    assert (o['x'] - 0.5 <= i['x'] and i['x'] + i['width'] <= o['x'] + o['width'] + 0.5
            and o['y'] - 0.5 <= i['y'] and i['y'] + i['height'] <= o['y'] + o['height'] + 0.5), (outer, o, inner, i)


def settle(page, timeout=20):
    """Waits for SETTLED. page.wait_for_function takes an async predicate's Promise as truthy and returns at once,
    so the predicate is polled here with page.evaluate, which awaits it."""
    end = time.monotonic() + timeout
    while not page.evaluate(SETTLED):
        assert time.monotonic() < end, 'the phone page never settled'
        page.wait_for_timeout(100)


def open_add(page, base):
    if '/mobile.html' in page.url:
        page.evaluate("location.hash = '#/cap'")
    else:
        page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
    settle(page)
    page.locator('.m-sheet-layer.m-vt-cap').wait_for(state='visible')
    expect(page.locator('#cap-text')).to_be_visible()
    page.add_style_tag(content=f'.m-sheet-layer.m-bare{{padding-bottom:{INSET}px}}')


def to_recap(page):
    """Save on the draft opens the recap (#/cap/save) on the same screen; nothing is created."""
    page.locator('form button[type=submit]').click()
    page.wait_for_function("() => location.hash === '#/cap/save'")
    expect(page.locator('.m-cap-recap')).to_be_visible()
    expect(page.locator('#cap-pv')).to_be_focused()


def to_draft(page):
    page.get_by_role('button', name='Back', exact=True).click()
    page.wait_for_function("() => location.hash === '#/cap'")
    expect(page.locator('#cap-text')).to_be_visible()


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with mobile_browser() as (browser, base):
        # ── 360 x 780, a solo phone with no AI key and no PC copy ────────────────────────────────────────────────
        with synthetic_phone(browser, base, *VIEW, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            settle(page)
            assert page.evaluate(NO_PC_COPY), 'source.notes() rejects, as on a phone with no PC copy'
            made = page.evaluate(MAKE_NOTE)
            page.wait_for_timeout(800)                       # the note's own refresh settles before the route changes
            open_add(page, base)

            # C1: the empty draft: no destination, Save named Save
            assert page.locator('.m-sheet-head').count() == 0, 'the sheet head is gone'
            expect(page.locator('.m-sheet-layer.m-capturing')).to_have_count(1)
            expect(page.get_by_role('button', name='Close Add', exact=True)).to_be_visible()
            expect(page.locator('.m-ws')).to_have_text('Add')
            key = page.get_by_role('button', name='Import & drafts', exact=True)
            expect(key).to_be_visible()
            expect(key).to_have_attribute('aria-haspopup', 'dialog')
            expect(key).to_have_attribute('aria-expanded', 'false')
            expect(page.locator('.m-cap-badge')).to_have_count(0)
            keys = [page.get_by_role('button', name='Close Add', exact=True).bounding_box(), key.bounding_box()]
            assert abs(keys[0]['x'] - 12) < 1 and keys[0]['width'] == 36 and keys[0]['y'] == 8, keys[0]
            assert abs(keys[1]['x'] + keys[1]['width'] - (VIEW[0] - 12)) < 1 and keys[1]['width'] == 36, keys[1]
            expect(page.locator('.m-cap-hello b')).to_have_text('Add to Brainamon')
            hint = page.get_by_role('link', name='Import saved posts', exact=True)
            expect(hint).to_be_visible()
            box = hint.bounding_box()
            assert box['height'] >= 44 and abs(box['x'] - 16) < 1, box
            expect(page.locator('#cap-help')).to_have_text('Add a link, some text or a picture to save.')
            save = page.locator('form button[type=submit]')
            expect(save).to_be_disabled()
            expect(save).to_have_accessible_name('Save')
            expect(page.locator('input[name=cap-dest]')).to_have_count(0)
            expect(page.locator('#cap-comment')).to_have_count(0)
            expect(page.locator('#cap-title')).to_be_visible()
            dock = clear_of_inset(page, *VIEW)
            assert dock['height'] < 80, dock
            for name in ('Photo', 'File', 'Paste'):
                k = page.locator('.m-cap-actions').get_by_role('button', name=name, exact=True)
                assert k.inner_text().strip() == '' and k.locator('svg').count() == 1
                b = k.bounding_box()
                assert b['width'] == 44 and b['height'] == 44, (name, b)
            assert page.locator('#cap-text').bounding_box()['height'] > 100
            fits(page)
            shoot(page, 'c1-empty')
            page.locator('#cap-text').fill('Second thought for the list')
            expect(page.locator('.m-cap-hello')).to_have_count(0)
            expect(page.locator('#cap-help')).to_have_text('Nothing is saved yet. Save shows what goes where.')
            expect(save).to_be_enabled()
            shoot(page, 'c1-typed')

            # C2: the panel drops from its key: Import first, no comment, no outbox; Escape, a tap outside
            key.click()
            panel = page.get_by_role('dialog', name='Import & drafts', exact=True)
            expect(panel).to_be_visible()
            expect(key).to_have_attribute('aria-expanded', 'true')
            p, k = panel.bounding_box(), key.bounding_box()
            assert p['y'] > k['y'] + k['height'] - 1 and abs(p['x'] + p['width'] - (VIEW[0] - 12)) < 1.5, (p, k)
            imp = panel.get_by_role('link', name='Import saved posts', exact=True)
            expect(imp).to_be_visible()
            assert imp.bounding_box()['height'] >= 44
            go_box = imp.locator('.m-cap-go').bounding_box()
            assert abs(go_box['width'] - 30) < 1 and abs(go_box['height'] - 30) < 1, ('the arrow stays a 30 px circle', go_box)
            expect(panel.get_by_role('button', name='Discard this draft', exact=True)).to_be_visible()
            expect(panel.get_by_label('Comment', exact=False)).to_have_count(0)
            expect(panel).not_to_contain_text('Outbox')
            expect(panel.locator('.m-cap-drafts')).to_have_count(0)
            shoot(page, 'c2-panel')
            page.keyboard.press('Escape')
            expect(panel).not_to_be_visible()
            expect(key).to_be_focused()
            expect(key).to_have_attribute('aria-expanded', 'false')
            key.click()
            expect(panel).to_be_visible()
            page.mouse.click(30, VIEW[1] - 200)
            expect(panel).not_to_be_visible()
            expect(page.locator('#cap-text')).to_have_value('Second thought for the list')

            # R2: the recap of a new note: General, the preview, Library greyed with its reason
            to_recap(page)
            expect(page.locator('.m-ws')).to_have_text('Save')
            expect(page.get_by_role('button', name='Back', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='Import & drafts', exact=True)).to_have_count(0)
            pv = page.locator('.m-cap-pv')
            expect(pv.locator('.m-cap-cat')).to_have_text('General')
            expect(pv.locator('.m-cap-pv-kind')).to_have_text('New note')
            expect(pv.locator('.m-cap-pv-title')).to_have_text('Second thought for the list')
            expect(pv.locator('.m-cap-pv-body')).to_have_text('Second thought for the list')
            note_radio, lib_radio = page.locator('input[name=cap-dest][value=note]'), page.locator('input[name=cap-dest][value=library]')
            expect(note_radio).to_be_checked()
            expect(lib_radio).to_be_disabled()
            expect(page.locator('#cap-lib-hint')).to_have_text('Library items need a web link.')
            expect(page.get_by_role('button', name='Choose category: General', exact=True)).to_have_text('General')
            expect(page.locator('#cap-help')).to_have_text('Creates a note in General.')
            expect(save).to_have_accessible_name('Save to note')
            expect(page.locator('#cap-comment')).to_be_visible()
            clear_of_inset(page, *VIEW)
            page.locator('#cap-comment').fill('For the reading list')
            expect(pv.locator('.m-cap-pv-body')).to_contain_text('For the reading list')
            assert pv.locator('.m-cap-pv-body').inner_text() == 'Second thought for the list\n\nFor the reading list'
            shoot(page, 'r2-new-note')
            page.get_by_role('button', name='Choose category: General', exact=True).click()
            sheet = page.get_by_role('dialog', name='Choose category', exact=True)
            expect(sheet.get_by_role('button', name='Reading', exact=True)).to_be_visible()
            expect(sheet.get_by_role('button', name='Inbox', exact=True)).to_have_count(0)    # no note uses Inbox here
            sheet.get_by_role('button', name='Reading', exact=True).click()
            expect(pv.locator('.m-cap-cat')).to_have_text('Reading')
            expect(page.locator('#cap-help')).to_have_text('Creates a note in Reading.')

            # R2d: an addition: the note's last lines, then the section; its category stays as it is
            page.get_by_role('button', name='Note to add to', exact=True).click()
            menu = page.locator('.m-cap-dest.m-cap-on .m-cap-menu')
            expect(menu).to_be_visible()
            page.keyboard.press('Escape')
            expect(menu).to_have_count(0)
            page.get_by_role('button', name='Note to add to', exact=True).click()
            page.get_by_role('option').filter(has_text=made['title']).click()
            expect(menu).to_have_count(0)
            expect(page.get_by_role('button', name='Note to add to', exact=True)).to_have_text(made['title'])
            expect(pv.locator('.m-cap-pv-kind')).to_have_text('Adds to this note')
            expect(pv.locator('.m-cap-pv-title')).to_have_text(made['title'])
            expect(pv.locator('.m-cap-pv-old')).to_contain_text('Ten books to read.')
            assert pv.locator('.m-cap-pv-old').inner_text() == '…\nTen books to read.', pv.locator('.m-cap-pv-old').inner_text()
            expect(pv.locator('.m-cap-pv-new')).to_contain_text('## From Note - ')
            expect(pv.locator('.m-cap-pv-new')).to_contain_text('Second thought for the list')
            expect(page.locator('.m-cap-recap')).to_contain_text('Existing text stays untouched.')
            assert page.locator('.m-cap-category button').count() == 0, 'an existing note keeps its category as plain text'
            expect(page.locator('.m-cap-category')).to_contain_text('Reading')
            expect(page.locator('#cap-help')).to_have_text('Adds a section at the end of the note. Nothing already there changes.')
            expect(save).to_have_accessible_name('Add to note')
            inside(page, '.m-cap-pv', '.m-cap-pv-new')
            shoot(page, 'r2d-addition')
            page.get_by_role('button', name='Note to add to', exact=True).click()
            page.get_by_role('button', name='+ New note', exact=True).click()
            to_draft(page)
            expect(page.locator('#cap-text')).to_have_value('Second thought for the list')

            # R2b: a long note is cut, Show all opens it whole
            page.locator('#cap-text').fill(LONG)
            to_recap(page)
            more = page.get_by_role('button', name='Show all', exact=True)
            expect(more).to_be_visible()
            expect(pv.locator('.m-cap-pv-body')).to_have_class('m-cap-pv-body m-cap-cut')
            short_h = pv.locator('.m-cap-pv-body').bounding_box()['height']
            shoot(page, 'r2b-long')
            more.click()
            expect(page.get_by_role('button', name='Show less', exact=True)).to_have_attribute('aria-expanded', 'true')
            assert pv.locator('.m-cap-pv-body').bounding_box()['height'] > short_h * 2
            to_draft(page)

            # R2a: a lone link starts on Library; its preview, its fields, the reasons under Note
            page.locator('#cap-text').fill('https://example.com/read-later')
            to_recap(page)
            expect(lib_radio).to_be_checked()
            lib = page.locator('.m-cap-pv-lib')
            expect(lib).to_contain_text('New to your library')
            expect(lib.locator('.m-cap-pv-title')).to_have_text('example.com/read-later')
            expect(lib.locator('.m-cap-kv')).to_contain_text('INTERESTING')                 # the phone decides: nothing used yet
            expect(page.locator('.m-cap-says')).to_have_text("The card gets the page's picture and caption after saving.")
            expect(page.locator('#cap-note-hint')).to_have_text('The link is kept as text.')
            expect(page.locator('#cap-help')).to_have_text('Creates a Library card.')
            expect(save).to_have_accessible_name('Save to Library')
            chip = page.get_by_role('button', name='Choose collection: INTERESTING', exact=True)
            expect(chip).to_have_text('INTERESTING')
            expect(page.locator('.m-cap-suggest')).to_have_count(0)                         # no AI key on this phone: no Suggest
            page.get_by_role('textbox', name='Tags', exact=True).fill('cooking, knives')
            expect(lib.locator('.m-cap-kv')).to_contain_text('cooking, knives')
            expect(lib.locator('.m-cap-kv')).to_contain_text('For the reading list')        # the comment goes into its note
            shoot(page, 'r2a-library')
            # a new collection needs its name before Save
            chip.click()
            page.get_by_role('dialog', name='Choose collection', exact=True).get_by_role('button', name='+ New collection', exact=True).click()
            named = page.get_by_role('textbox', name='New collection name', exact=True)
            expect(named).to_be_visible()
            expect(save).to_be_disabled()
            expect(page.locator('#cap-help')).to_have_text('Name the new collection, or pick one.')
            named.fill('Knife skills')
            expect(save).to_be_enabled()
            expect(page.locator('#cap-help')).to_have_text('Creates a Library card.')
            expect(lib.locator('.m-cap-kv')).to_contain_text('Knife skills')
            note_radio.check()
            expect(page.locator('.m-cap-pv-lib')).to_have_count(0)
            expect(pv.locator('.m-cap-pv-title')).to_have_text('Link from example.com')
            lib_radio.check()

            # the keyboard: on the draft it folds the attach keys away; on the recap the comment stays above it
            page.locator('#cap-comment').focus()
            page.set_viewport_size({'width': VIEW[0], 'height': 520})
            page.wait_for_function("() => document.documentElement.classList.contains('kb')")
            expect(page.locator('#cap-comment')).to_be_in_viewport()
            expect(save).to_be_in_viewport()
            page.locator('#cap-comment').blur()
            page.set_viewport_size({'width': VIEW[0], 'height': VIEW[1]})
            page.wait_for_function("() => !document.documentElement.classList.contains('kb')")

            # a Library save: the result on the draft's page, one composer row
            save.click()
            expect(page.locator('#cap-done')).to_have_text('Saved as a Library item')
            page.wait_for_function("() => location.hash === '#/cap'")
            assert page.evaluate("document.activeElement && document.activeElement.id") == 'cap-done'
            expect(page.locator('.m-cap-done .m-badge')).to_have_text('Saved')
            expect(page.get_by_role('button', name='Back', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Open the card', exact=True)).to_have_count(0)
            add = page.get_by_role('button', name='Add another', exact=True)
            expect(add).to_be_visible()
            done_dock = clear_of_inset(page, *VIEW)
            ab = add.bounding_box()
            assert ab['width'] == 44 and abs(ab['x'] + ab['width'] - (done_dock['x'] + done_dock['width'] - 8 - 1)) < 1.5, (ab, done_dock)
            expect(page.locator('.m-cap-badge')).to_have_count(0)
            shoot(page, 'saved-library')
            key.click()
            expect(panel.get_by_role('link', name='Import saved posts', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='Discard this draft', exact=True)).to_have_count(0)
            page.keyboard.press('Escape')

            # a note save: Open the note beside the orange key
            add.click()
            page.locator('#cap-text').fill('Knife skills in 10 minutes')
            to_recap(page)
            save.click()
            expect(page.locator('#cap-done')).to_have_text('Saved to a new note')
            expect(page.get_by_role('button', name='Open the note', exact=True)).to_be_visible()
            ob = page.get_by_role('button', name='Open the note', exact=True).bounding_box()
            assert ob['height'] == 44 and ob['x'] > 18, ob
            shoot(page, 'saved-note')
            add.click()

            # another draft waits: the key's badge, the panel's list; the one left stays a draft
            page.locator('#cap-text').fill('A draft that stays')
            page.wait_for_timeout(500)
            page.evaluate(KEEP_OTHER)
            expect(page.locator('.m-cap-badge')).to_have_text('1')
            key.click()
            drafts = panel.locator('.m-cap-drafts')
            expect(drafts).to_contain_text('Other drafts (1)')
            expect(drafts.locator('.m-cap-draft')).to_contain_text('Shared · 12 min ago')
            shoot(page, 'c2-drafts')
            drafts.locator('.m-cap-draft').click()
            expect(panel).not_to_be_visible()
            expect(page.locator('#cap-text')).to_have_value('https://www.youtube.com/watch?v=8Kf3nQ2')
            expect(page.locator('.m-cap-badge')).to_have_text('1')
            key.click()
            expect(panel.locator('.m-cap-draft')).to_contain_text('A draft that stays')
            panel.locator('.m-cap-draft').click()
            expect(page.locator('#cap-text')).to_have_value('A draft that stays')

            # a share that arrives on the recap opens on the draft
            to_recap(page)
            page.evaluate(SHARE_NOW)
            page.wait_for_function("() => location.hash === '#/cap'")
            expect(page.locator('#cap-text')).to_have_value('https://example.com/shared-now')
            expect(page.locator('.m-cap-badge')).to_have_text('2')

            # Import saved posts from the panel, and back to the same draft
            key.click()
            panel.get_by_role('link', name='Import saved posts', exact=True).click()
            expect(page).to_have_url(base + '/mobile.html#/import')
            expect(page.locator('.m-sheet-layer.m-vt-cap')).to_be_visible()
            expect(page.locator('.m-ws')).to_have_text('Import')
            back = page.get_by_role('button', name='Back', exact=True)
            expect(back).to_be_visible()
            expect(page.get_by_role('button', name='Import & drafts', exact=True)).to_have_count(0)
            expect(page.get_by_role('heading', name='Import saved posts', exact=True)).to_be_visible()
            expect(page.get_by_text('Posts you saved on these sites become cards in your library.', exact=True)).to_be_visible()
            assert page.locator('.m-sheet-body').evaluate('e => getComputedStyle(e).overflowY') != 'hidden'
            body = page.locator('.m-sheet-body').bounding_box()
            assert body['y'] + body['height'] <= VIEW[1] - INSET + 0.5, body
            assert page.locator('.m-import-fold').evaluate_all('xs => xs.every(x => getComputedStyle(x).borderRadius === "12px")')
            assert page.locator('.m-import-expand').evaluate('x => getComputedStyle(x).gap') == '8px'
            fits(page)
            shoot(page, 'a6-import')
            back.click()
            expect(page).to_have_url(base + '/mobile.html#/cap')
            expect(page.locator('#cap-text')).to_have_value('https://example.com/shared-now')

            # the next Library item starts on the collection used last; a reload on the recap starts on the draft
            to_recap(page)
            expect(page.get_by_role('button', name='Choose collection: Knife skills', exact=True)).to_have_text('Knife skills')
            assert page.evaluate("localStorage.getItem('bp-cap-collection')") == 'Knife skills'
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function("() => location.hash === '#/cap'")
            expect(page.locator('#cap-text')).to_have_value('https://example.com/shared-now')
            assert errors == [], errors

        # ── a picture, with an AI key in the pairing so Read text and Describe are enabled ──────────────────────
        pair = dict(PAIR, ai={'openai': 'synthetic-openai-key'})
        with synthetic_phone(browser, base, *VIEW, 'light', pair=pair) as (page, errors):
            popups = []
            page.on('dialog', lambda dialog: (popups.append(dialog.message), dialog.dismiss()))
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            settle(page)
            page.evaluate(NO_PC_COPY)
            open_add(page, base)
            with page.expect_file_chooser() as chooser:
                page.get_by_role('button', name='Photo', exact=True).click()
            chooser.value.set_files({'name': 'IMG_0412.png', 'mimeType': 'image/png', 'buffer': PNG})

            # the draft's card: the thumbnail, all four actions, the confirm line inside the card
            card = page.locator('.m-cap-pic')
            expect(card).to_be_visible()
            expect(card.locator('img')).to_be_visible()
            expect(page.locator('.m-cap-pic > div > b')).to_have_text('IMG_0412.png')
            quick = page.locator('.m-cap-quick')
            names = [b.inner_text() or b.get_attribute('aria-label') for b in quick.get_by_role('button').all()]
            assert names == ['Read text', 'Describe', 'Ask Wiskit', 'Remove the attachment'], names
            for pill in ('Read text', 'Describe', 'Ask Wiskit'):
                b = quick.get_by_role('button', name=pill, exact=True).bounding_box()
                assert b['height'] == 40, (pill, b)
            describe = quick.get_by_role('button', name='Describe', exact=True)
            describe.click()
            ask = page.locator('.m-cap-ask')
            expect(ask).to_be_visible()
            expect(ask).to_contain_text(DESCRIBE)
            expect(describe).to_have_attribute('aria-expanded', 'true')
            expect(ask.get_by_role('button', name='Continue', exact=True)).to_be_focused()
            clear_of_inset(page, *VIEW)
            fits(page)
            shoot(page, 'c1-picture')
            ask.get_by_role('button', name='Cancel', exact=True).click()
            expect(ask).to_have_count(0)
            expect(describe).to_be_focused()
            assert popups == [] and page.locator('#cap-text').input_value() == '', 'Cancel reads nothing and opens no pop-up'
            quick.get_by_role('button', name='Ask Wiskit', exact=True).click()
            expect(ask).to_contain_text('Open chat with your draft text as context so you can ask questions about it.')
            page.keyboard.press('Escape')
            expect(ask).to_have_count(0)

            # R2c: the recap shows the thumbnail with its line and Read text / Describe over it
            expect(page.locator('form button[type=submit]')).to_be_enabled()
            to_recap(page)
            pv = page.locator('.m-cap-pv')
            expect(pv.locator('.m-cap-pv-wait')).to_have_text("The picture's text goes here once it is read.")
            shot = page.locator('.m-cap-att.m-cap-shot')
            expect(shot.locator('img')).to_be_visible()
            expect(shot).to_contain_text('IMG_0412.png')
            expect(shot).to_contain_text('1 picture, not read yet. Brainamon keeps the text, not the picture.')
            names = [b.inner_text() for b in shot.get_by_role('button').all()]
            assert names == ['Read text', 'Describe'], names
            s, i = shot.bounding_box(), shot.locator('img').bounding_box()
            assert abs(s['height'] - i['height']) < 1 and s['height'] >= 150, (s, i)
            band = shot.locator('.m-cap-quick').bounding_box()
            assert band['y'] > s['y'] and band['y'] + band['height'] <= s['y'] + s['height'], (band, s)
            expect(page.locator('#cap-help')).to_have_text("Read the picture's text, or type it. Brainamon keeps the text, not the picture.")
            expect(page.locator('form button[type=submit]')).to_be_disabled()
            expect(page.locator('input[name=cap-dest][value=library]')).to_be_disabled()
            shoot(page, 'r2c-picture')
            describe = shot.get_by_role('button', name='Describe', exact=True)
            describe.click()
            expect(shot.locator('.m-cap-ask')).to_contain_text(DESCRIBE)
            expect(shot.get_by_role('button', name='Continue', exact=True)).to_be_focused()
            grown = shot.bounding_box()
            assert grown['height'] > s['height'], (grown, s)
            shoot(page, 'r2c-confirm')
            page.keyboard.press('Escape')
            expect(shot.locator('.m-cap-ask')).to_have_count(0)
            expect(describe).to_be_focused()
            describe.click()
            shot.get_by_role('button', name='Continue', exact=True).click()
            expect(page.locator('.m-cap-say .m-err')).to_contain_text('Your capture has been kept')   # the synthetic key reaches no provider
            assert page.evaluate('location.hash') == '#/cap/save' and popups == [], popups

            # a picture with a lone link: the Library cannot take it on the phone
            to_draft(page)
            page.locator('#cap-text').fill('https://example.com/a')
            to_recap(page)
            expect(page.locator('input[name=cap-dest][value=note]')).to_be_checked()
            expect(page.locator('#cap-lib-hint')).to_have_text('A picture can only go into a Library item from the PC app. Choose Note, or remove the picture.')
            to_draft(page)
            quick.get_by_role('button', name='Remove the attachment', exact=True).click()
            expect(card).to_have_count(0)

            # Suggest, with the AI key on this phone: it asks first; the answer fills the collection and the tags and
            # writes nothing. No AI call in an isolated check: the network refuses the first one, then the answer is
            # stubbed (the prompt and its parser are checked by tests/test_phone_fixes.py)
            to_recap(page)
            expect(page.locator('input[name=cap-dest][value=library]')).to_be_checked()
            expect(page.get_by_role('button', name='Choose collection: INTERESTING', exact=True)).to_be_visible()
            queued = page.evaluate(QUEUED)
            suggest = page.get_by_role('button', name='Suggest', exact=True)
            expect(suggest).to_have_attribute('aria-expanded', 'false')
            suggest.click()
            line = page.get_by_role('group', name='Confirm: Suggest', exact=True)
            expect(line.locator('p')).to_have_text(f'Suggest. {SUGGEST_SAYS}')
            expect(line.get_by_role('button', name='Continue', exact=True)).to_be_focused()
            ink = suggest.evaluate("""e => { const t = document.createElement('i'); t.style.background = 'var(--ink)'
              e.parentElement.append(t); const c = getComputedStyle(t).backgroundColor; t.remove(); return c }""")
            expect(suggest).to_have_css('background-color', ink)                            # dark while its line is open, like the picture's pills
            fits(page)
            shoot(page, 'r2e-suggest')
            page.keyboard.press('Escape')
            expect(line).to_have_count(0)
            expect(suggest).to_be_focused()
            expect(suggest).not_to_have_css('background-color', ink)
            suggest.click()
            line.get_by_role('button', name='Continue', exact=True).click()
            failed = page.locator('.m-cap-say .m-err')
            expect(failed).to_contain_text('Wiskit could not suggest a collection: ')
            expect(failed).to_contain_text('. Pick one yourself.')
            expect(page.get_by_role('button', name='Choose collection: INTERESTING', exact=True)).to_be_visible()
            page.evaluate(STUB_SUGGEST)
            suggest.click()
            line.get_by_role('button', name='Continue', exact=True).click()
            expect(page.get_by_role('button', name='Choose collection: COOKING', exact=True)).to_be_visible()
            expect(page.get_by_role('textbox', name='Tags', exact=True)).to_have_value('knives, technique')
            expect(page.locator('.m-cap-dest').get_by_role('status')).to_have_text('Wiskit picked COOKING and the tags knives, technique. Change them if you like.')
            expect(page.locator('.m-cap-pv-lib .m-cap-kv')).to_contain_text('COOKING')
            expect(failed).to_have_count(0)
            assert page.evaluate(QUEUED) == queued, 'Suggest writes nothing'
            shoot(page, 'r2e-picked')
            assert errors == [], errors

        # ── 320 x 568: nothing is wider than the screen; the draft, the recap and both destinations fit ──────────
        with synthetic_phone(browser, base, 320, 568, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            settle(page)
            page.evaluate(NO_PC_COPY)
            open_add(page, base)
            page.locator('#cap-text').fill('A long enough draft to wrap onto more than one line at three hundred and twenty pixels wide')
            fits(page)
            clear_of_inset(page, 320, 568)
            no_overflow(page, '.m-cap-dock')
            assert page.locator('#cap-text').bounding_box()['height'] >= 36
            to_recap(page)
            fits(page)
            dock = clear_of_inset(page, 320, 568)
            no_overflow(page, '.m-cap-commit')
            for chip in page.locator('.m-cap-chip').all():
                assert chip.bounding_box()['width'] >= 90, chip.bounding_box()
            assert dock['height'] < 80, dock
            assert page.locator('.m-cap-recap').evaluate('e => getComputedStyle(e).overflowY') == 'auto'
            shoot(page, 'r2-320')
            to_draft(page)
            page.locator('#cap-text').fill('Keep this https://example.com/narrow for later')
            to_recap(page)
            page.locator('input[name=cap-dest][value=library]').check()
            fits(page)
            clear_of_inset(page, 320, 568)
            shoot(page, 'r2a-320')
            assert errors == [], errors
    print(f'PASS add draft, panel and recap at 360x780 with a {INSET} px simulated inset, and 320x568. Screenshots: {ART}')


if __name__ == '__main__':
    main()
