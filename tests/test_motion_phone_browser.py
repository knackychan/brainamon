"""The phone's motion language in a real browser (projects/motion-language plans 07 and 08), on synthetic rows and
disposable storage, never a real library: the import run (ImportRun.svelte) from ready to Open in Library, and the
Library after an import (cards slide in 90 ms apart, the All chip counts up from the number held before, a toast names
the site), with motion on and off. The sheet over the Library, the Android tray and the WebView are the phone's: Fred's."""
import importlib.util
import unittest

from tests.test_mobile_info_browser import mobile_browser, synthetic_phone
from tests.test_phone_gallery_browser import seed

NEW = [3001, 3002, 3003]

ADD = """async ({ ids, motion }) => {
  const { phone } = await import('/src/mobile/state.svelte.ts')
  const { recordArrival } = await import('/src/mobile/arrival.svelte.ts')
  phone.motionOff = !motion
  document.documentElement.classList.toggle('motion-off', !motion)
  phone.cat = 'all'; phone.fav = false; phone.src = 'all'; phone.sort = 'new'
  location.hash = '#/cap'                                     // a sheet over the Library, as the Import screen is
  await new Promise(r => setTimeout(r, 120))
  const added = ids.map((id, i) => ({ id, title: 'New post ' + id, creator: 'Example creator', type: 'Post', cat: 'Art', tags: '', desc: '',
    url: 'https://example.com/post/' + id, src: 'instagram', thumb: false, ai: false, an: false, nd: 0, fav: false, created: 4000 - i, tv: 0 }))
  phone.rows = [...added, ...phone.rows]
  recordArrival('instagram', 'Instagram', ids, phone.rows.length)
  location.hash = '#/lib'
}"""

ALL_CHIP = lambda page: page.locator('.m-chips .m-chip').filter(has_text='All').locator('small')


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires installed Playwright/Edge')
class PhoneArrivalBrowser(unittest.TestCase):
    def test_cards_slide_in_chip_counts_up_and_a_toast_names_the_site(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            seed(page)
            expect(ALL_CHIP(page)).to_have_text('3000', timeout=5000)      # the seeded rows counted up to their number
            page.evaluate(ADD, dict(ids=NEW, motion=True))
            page.wait_for_selector('.m-cell[data-mo="arrive"]')
            # the hold: the chip still shows the number from before the import, the toast is not there yet
            self.assertEqual(ALL_CHIP(page).inner_text(), '3000')
            self.assertEqual(page.locator('.m-lib-sum').inner_text().split(' · ')[0], '3,000 items')
            delays = page.evaluate("""() => [...document.querySelectorAll('.m-cell[data-mo="arrive"]')].map(e => ({ id: +e.querySelector('a').dataset.id, d: parseInt(e.style.getPropertyValue('--mo-d')) }))""")
            self.assertEqual([x['id'] for x in delays], NEW)
            # each card reads the clock on its own: 90 ms apart, give or take the rounding of its own read
            for i in range(2):
                self.assertAlmostEqual(delays[i + 1]['d'] - delays[i]['d'], 90, delta=2)
            self.assertTrue(180 <= delays[0]['d'] <= 280, delays)
            expect(page.locator('.m-toast')).to_have_count(0)
            expect(ALL_CHIP(page)).to_have_text('3003', timeout=5000)
            expect(page.locator('.m-lib-sum')).to_contain_text('3,003 items', timeout=3000)
            expect(page.locator('.m-toast')).to_have_text('✓ 3 new from Instagram')
            # nothing keeps replaying: the cards settle, the toast goes after 3.6 s
            expect(page.locator('.m-cell[data-mo="arrive"]')).to_have_count(0, timeout=6000)
            expect(page.locator('.m-toast')).to_have_count(0, timeout=6000)
            self.assertEqual(errors, [])

    def test_a_card_scrolled_in_after_its_turn_is_simply_there(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            seed(page)
            page.evaluate(ADD, dict(ids=NEW, motion=True))
            page.wait_for_selector('.m-cell[data-mo="arrive"]')
            page.wait_for_function("() => !document.querySelector('.m-cell[data-mo=\"arrive\"]')", timeout=6000)
            # the record is spent: the Library shown again (an item opened and closed) plays nothing
            page.evaluate("async () => { location.hash = '#/item/9'; await new Promise(r => setTimeout(r, 150)); location.hash = '#/lib' }")
            page.wait_for_timeout(400)
            self.assertEqual(page.locator('.m-cell[data-mo="arrive"]').count(), 0)
            self.assertEqual(errors, [])

    def test_with_motion_off_the_numbers_are_there_at_once_and_nothing_slides(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            seed(page)
            page.evaluate(ADD, dict(ids=NEW, motion=False))
            expect(ALL_CHIP(page)).to_have_text('3003', timeout=2000)
            expect(page.locator('.m-toast')).to_have_text('✓ 3 new from Instagram')
            self.assertEqual(page.locator('.m-cell[data-mo="arrive"]').count(), 0)
            self.assertEqual(errors, [])


MOUNT = """async ({ ids, motion }) => {
  const { phone, pics } = await import('/src/mobile/state.svelte.ts')
  const { mount } = await import('/@id/svelte')
  const { default: ImportRun } = await import('/src/mobile/ImportRun.svelte')
  phone.motionOff = !motion
  document.documentElement.classList.toggle('motion-off', !motion)
  const host = document.createElement('div')
  host.id = 'ir-host'
  host.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99;padding:12px;background:var(--wg-paper,#f4efe4)'
  document.querySelector('#m-app').append(host)
  window.__ir = { later: 0, done: 0 }
  mount(ImportRun, { target: host, props: { site: 'instagram', name: 'Instagram', posts: 3, reason: 'read to the end of the list', known: 2, refused: 1,
    disabled: false, onlater() { window.__ir.later++ }, ondone() { window.__ir.done++ },
    onimport: async () => {
      const added = ids.map((id, i) => ({ id, title: 'New post ' + id, creator: 'C', type: 'Post', cat: 'Art', tags: '', desc: '',
        url: 'https://example.com/post/' + id, src: 'instagram', thumb: false, ai: false, an: false, nd: 0, fav: false, created: 4000 - i, tv: 0 }))
      phone.rows = [...added, ...phone.rows]
      pics.state = 'run'                       // the picture queue was started
      return { ids, dups: 2 }
    } } })
}"""


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires installed Playwright/Edge')
class PhoneImportRunBrowser(unittest.TestCase):
    def run_flow(self, motion):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            seed(page)
            page.evaluate(MOUNT, dict(ids=NEW, motion=motion))
            host = page.locator('#ir-host')
            expect(host.locator('.m-ir-t')).to_have_text('3 posts ready to import')
            expect(host).to_contain_text('Read to the end of the list · 2 already there · 1 refused')
            host.get_by_role('button', name='Import 3 posts').click()
            # the pictures: a grid of three squares, all waiting until the queue works on them
            expect(host.locator('.m-ir-t')).to_have_text('Fetching pictures', timeout=4000)
            squares = host.locator('.m-ir-sq')
            expect(squares).to_have_count(3)
            self.assertEqual(squares.evaluate_all('els => els.map(e => e.dataset.s)'), ['wait', 'wait', 'wait'])
            expect(host).to_contain_text('0 of 3 pictures')
            # one is scanned while its picture is fetched, one has landed
            page.evaluate("""async () => {
              const { startWork } = await import('/src/mobile/work.svelte.ts')
              const { phone } = await import('/src/mobile/state.svelte.ts')
              startWork('pics', 'FETCH', 3002)
              phone.rows = phone.rows.map(r => r.id === 3001 ? { ...r, thumb: true, tv: 1 } : r)
            }""")
            expect(squares.nth(0)).to_have_attribute('data-s', 'done')
            expect(squares.nth(1)).to_have_attribute('data-s', 'run')
            expect(squares.nth(1).locator('.mo-scan')).to_have_count(1)
            expect(squares.nth(0).locator('img.m-ir-img')).to_have_count(1)
            expect(host).to_contain_text('1 of 3 pictures')
            page.evaluate("""async () => {
              const { phone } = await import('/src/mobile/state.svelte.ts')
              phone.rows = phone.rows.map(r => [3002, 3003].includes(r.id) ? { ...r, thumb: true, tv: 1 } : r)
            }""")
            # the finish: green, how many, whether the pictures came, and the way to the Library
            expect(host.locator('.m-ir-t')).to_have_text('3 posts in your library', timeout=4000)
            expect(host).to_contain_text('Pictures ready · 2 were already there')
            host.get_by_role('button', name='Open in Library').click()
            self.assertEqual(page.evaluate('window.__ir.done'), 1)
            state = page.evaluate("""async () => {
              const { phone } = await import('/src/mobile/state.svelte.ts')
              const { arrival } = await import('/src/mobile/arrival.svelte.ts')
              return { cat: phone.cat, fav: phone.fav, sort: phone.sort, scroll: phone.scroll.lib, ids: [...arrival.cur.ids], base: arrival.cur.base, site: arrival.cur.name }
            }""")
            self.assertEqual(state, dict(cat='all', fav=False, sort='new', scroll=0, ids=NEW, base=3000, site='Instagram'))
            self.assertEqual(errors, [])

    def test_ready_to_finish_with_motion(self):
        self.run_flow(True)

    def test_ready_to_finish_with_motion_off(self):
        self.run_flow(False)

    def test_later_hands_back_without_importing(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            seed(page)
            page.evaluate(MOUNT, dict(ids=NEW, motion=False))
            host = page.locator('#ir-host')
            host.get_by_role('button', name='Later').click()
            self.assertEqual(page.evaluate('window.__ir.later'), 1)
            expect(host.locator('.m-ir-t')).to_have_text('3 posts ready to import')
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
