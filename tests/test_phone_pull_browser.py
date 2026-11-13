"""Pull-to-refresh in a touch browser, with disposable storage and synthetic library rows."""
import unittest

from playwright.sync_api import expect
from tests.test_mobile_info_browser import mobile_browser, synthetic_phone
from tests.test_phone_settings_remediation_browser import NATIVE


class PhonePullBrowser(unittest.TestCase):
    def test_pull_retries_native_work_immediately_and_respects_sync_gates(self):
        native = NATIVE.replace("const methods=[", "const methods=['status','retry','configure','barrier',") \
            .replace("['Brainamon','App']", "['Brainamon','App','BrainamonSync']") \
            .replace("if(method==='secretGet')", """if(plugin==='BrainamonSync'){
              if(method==='retry'){window.__pullRetries=(window.__pullRetries||0)+1;return {id:'fresh'}};
              return {supported:!!window.__pullRetries,state:window.__pullRetries?'syncing':'',phase:'drive',retryable:false,nextAt:null};
            };if(method==='secretGet')""")
        with mobile_browser() as (browser, base):
            with synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
                page.add_init_script(native)
                # Keep synthetic in-flight reads held; test the native retry call independently of resume callbacks.
                page.add_init_script("window.addEventListener('brainamon-sync-resume',e=>e.stopImmediatePropagation())")
                page.goto(base + '/mobile.html#/lib')
                page.wait_for_function("async () => (await import('/src/mobile/state.svelte.ts')).phone.tried")
                page.evaluate("""async()=>{
                  const {source,mirrorSource}=await import('/src/mobile/state.svelte.ts');
                  await (await import('/src/mobile/onboard.svelte.ts')).saveOnb({answer:'phone',hidden:true,coach:true});
                  mirrorSource.pair.g='synthetic@example.test';
                  source.rows=async()=>({rows:[],cats:[]});
                }""")
                expect(page.locator('.m-main')).to_be_visible()
                retries = 0
                for state in ('retry', 'queued', 'reading', 'syncing', 'idle', 'paused', 'offline', 'wifi', 'stopped'):
                    with self.subTest(state=state):
                        page.evaluate("""async state=>{
                          const {phone}=await import('/src/mobile/state.svelte.ts');
                          const {network}=await import('/src/mobile/network.svelte.ts');
                          const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');
                          Object.assign(network,{manualPause:state==='paused',online:state!=='offline',wifiOnly:state==='wifi',type:'cellular',ready:true,background:false});
                          phone.refreshing=state==='reading';
                          phone.sync=['retry','queued','syncing'].includes(state)?{steps:[],end:'',msg:''}:null;
                          Object.assign(nativeSync,{supported:true,state:['reading','syncing'].includes(state)?'syncing':state,retryable:state==='retry',nextAt:state==='retry'?Date.now()+80*60000:null});
                          if(state==='stopped')await (await import('/src/mobile/mirror/gate.ts')).stopCloudWork();
                        }""", state)
                        page.locator('.m-main').evaluate("""el=>{
                          for(const [type,y] of [['touchstart',250],['touchmove',430],['touchend',null]]){
                            const touches=y===null?[]:[new Touch({identifier:0,target:el,clientX:100,clientY:y})];
                            el.dispatchEvent(new TouchEvent(type,{bubbles:true,cancelable:true,touches}));
                          }
                        }""")
                        expect(page.locator('#m-sync-panel')).to_be_visible()
                        if state not in ('paused', 'offline', 'wifi', 'stopped'):
                            retries += 1
                            page.wait_for_function('n=>window.__pullRetries===n', arg=retries)
                        page.wait_for_function("async()=>!(await import('/src/mobile/sync/native.svelte.ts')).nativeRetry.busy")
                        self.assertEqual(page.evaluate('window.__pullRetries||0'), retries)
                        expect(page.locator('[role=alert]')).to_have_count(0)
                        page.get_by_role('button', name='Close the sync panel', exact=True).click()
                self.assertEqual(errors, [])

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
                  window.__pullReads = 0;
                  source.rows = async () => { window.__pullReads++; return {rows, cats:[]}; };
                  phone.rows = rows;
                  phone.loaded = true;
                }""")
                expect(page.locator('.m-grid')).to_be_visible()
                page.wait_for_function("async () => !(await import('/src/mobile/state.svelte.ts')).phone.refreshing")
                main = page.locator('.m-main')
                reads_before = page.evaluate('window.__pullReads')

                def touch(kind, points):
                    return page.locator('.m-cell-a').first.evaluate("""(el, {kind, points}) => {
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

                # A long Android sync or a network pause must not make the gesture disappear.
                for state in ('reading', 'syncing', 'paused', 'offline', 'wifi'):
                    with self.subTest(state=state):
                        page.evaluate("""async state => {
                          const {phone} = await import('/src/mobile/state.svelte.ts');
                          const {network} = await import('/src/mobile/network.svelte.ts');
                          const {nativeSync} = await import('/src/mobile/sync/native.svelte.ts');
                          phone.refreshing = state === 'reading';
                          phone.sync = state === 'syncing' ? {steps:[], end:'', msg:''} : null;
                          network.manualPause = state === 'paused';
                          network.online = state !== 'offline';
                          network.wifiOnly = state === 'wifi';
                          network.type = 'cellular';
                          Object.assign(nativeSync, {supported:true, state:'syncing', phase:'vault', progress:.6});
                        }""", state)
                        touch('touchstart', [[100, 250]])
                        self.assertTrue(touch('touchmove', [[100, 290]]))
                        expect(page.locator('.m-main.m-pulling')).to_have_count(1)
                        expect(page.locator('.m-sync-key.pull')).to_be_visible()
                        expect(page.locator('.m-ring-g.spin')).to_have_count(0)
                        touch('touchmove', [[100, 430]])
                        touch('touchend', [])
                        expect(page.locator('#m-sync-panel')).to_be_visible()
                        self.assertEqual(page.evaluate("async () => (await import('/src/mobile/state.svelte.ts')).phone.sync"),
                                         dict(steps=[], end='', msg='') if state == 'syncing' else None)
                        expect(page.locator('.m-main.m-pulling')).to_have_count(0)
                        self.assertEqual(page.evaluate('window.__pullReads'), reads_before)
                        page.get_by_role('button', name='Close the sync panel', exact=True).click()

                page.evaluate("""async () => {
                  const {phone} = await import('/src/mobile/state.svelte.ts');
                  const {network} = await import('/src/mobile/network.svelte.ts');
                  const {nativeSync} = await import('/src/mobile/sync/native.svelte.ts');
                  phone.refreshing = false; phone.sync = null;
                  Object.assign(network, {manualPause:false, online:true, wifiOnly:false});
                  Object.assign(nativeSync, {supported:false, state:''});
                }""")

                # Browser-generated touches exercise native scrolling, unlike dispatchEvent.
                cdp = page.context.new_cdp_session(page)
                cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': 100, 'y': 300}]})
                for y in range(320, 481, 20):
                    cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': 100, 'y': y}]})
                expect(page.locator('.m-main.m-pulling')).to_have_count(1)
                cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                page.wait_for_function("async () => (await import('/src/mobile/state.svelte.ts')).phone.sync?.end === 'done'")
                self.assertEqual(page.evaluate('window.__pullReads'), reads_before + 1)
                expect(page.locator('.m-main.m-pulling')).to_have_count(0)
                self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
