"""Pull-to-refresh in a touch browser, with disposable storage and synthetic library rows."""
import unittest

from playwright.sync_api import expect
from tests.test_mobile_info_browser import mobile_browser, synthetic_phone


class PhonePullBrowser(unittest.TestCase):
    def test_pull_claims_touch_without_stealing_scroll_or_pinch(self):
        with mobile_browser() as (browser, base):
            with synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
                page.goto(base + '/mobile.html#/lib')
                page.wait_for_function("async () => (await import('/src/mobile/state.svelte.ts')).phone.tried")
                page.evaluate("""async () => {
                  const {phone, source} = await import('/src/mobile/state.svelte.ts');
                  const {saveOnb} = await import('/src/mobile/onboard.svelte.ts');
                  await saveOnb({answer:'phone', hidden:true, coach:true});
                  const rows = Array.from({length:30}, (_, i) => ({id:i+1, title:`Item ${i+1}`,
                    creator:'Example', type:'Post', cat:'Art', tags:'', desc:'', url:'https://example.com',
                    src:'web', thumb:false, ai:false, an:false, nd:0, fav:false, created:i, tv:0}));
                  source.rows = async () => ({rows, cats:[]});
                  phone.rows = rows;
                  phone.loaded = true;
                }""")
                expect(page.locator('.m-grid')).to_be_visible()
                page.wait_for_function("async () => !(await import('/src/mobile/state.svelte.ts')).phone.refreshing")
                main = page.locator('.m-main')

                def touch(kind, points):
                    return main.evaluate("""(el, {kind, points}) => {
                      const touches = points.map(([clientX, clientY], identifier) =>
                        new Touch({identifier, target:el, clientX, clientY}));
                      const event = new TouchEvent(kind, {bubbles:true, cancelable:true, touches});
                      el.dispatchEvent(event);
                      return event.defaultPrevented;
                    }""", dict(kind=kind, points=points))

                def no_sync():
                    self.assertTrue(page.evaluate("async () => !(await import('/src/mobile/state.svelte.ts')).phone.sync"))

                # A short pull gives feedback but never refreshes on release.
                touch('touchstart', [[100, 250]])
                self.assertTrue(touch('touchmove', [[100, 290]]))
                expect(page.locator('.m-main.m-pulling')).to_have_count(1)
                touch('touchend', [])
                no_sync()

                # Upward scroll, sideways swipe and a second finger stay native.
                for points in ([[100, 220]], [[150, 260]], [[100, 290], [180, 290]]):
                    touch('touchstart', [[100, 250]])
                    self.assertFalse(touch('touchmove', points))
                    touch('touchend', [])
                    no_sync()

                main.evaluate('el => el.scrollTop = 200')
                touch('touchstart', [[100, 250]])
                self.assertFalse(touch('touchmove', [[100, 430]]))
                touch('touchend', [])
                no_sync()
                main.evaluate('el => el.scrollTop = 0')

                touch('touchstart', [[100, 250]])
                self.assertTrue(touch('touchmove', [[100, 430]]))
                touch('touchcancel', [])
                expect(page.locator('.m-main.m-pulling')).to_have_count(0)
                no_sync()

                # Browser-generated touches exercise native scrolling, unlike dispatchEvent.
                cdp = page.context.new_cdp_session(page)
                cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': 100, 'y': 300}]})
                for y in range(320, 481, 20):
                    cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': 100, 'y': y}]})
                expect(page.locator('.m-main.m-pulling')).to_have_count(1)
                cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                page.wait_for_function("async () => !!(await import('/src/mobile/state.svelte.ts')).phone.sync")
                expect(page.locator('.m-main.m-pulling')).to_have_count(0)
                self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
