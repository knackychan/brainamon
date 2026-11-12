"""Review regressions: disposable browser storage, synthetic native bridge, no real APIs."""
import unittest

from tests.test_mobile_info_browser import mobile_browser, synthetic_phone, PAIR
from tests import test_phone_i18n_browser as scenes

NATIVE = """(()=>{window.androidBridge={};
const methods=['secretGet','secretSet','networkStatus','deviceName','vaultPick','vaultDelete','vaultWrite','vaultFinish','siteState','getInfo','addListener','removeListener'];
window.Capacitor={PluginHeaders:['Brainamon','App'].map(name=>({name,methods:methods.map(name=>({name,rtype:'promise'}))})),
nativePromise:async(plugin,method,o)=>{
if(method==='secretGet')return {value:localStorage.getItem(o.key)};
if(method==='secretSet'){if(window.__failSecret)throw Error('synthetic write failure');if(o.value===null)localStorage.removeItem(o.key);else localStorage.setItem(o.key,o.value);return {}};
if(method==='networkStatus')return {connected:true,type:'wifi'};
if(method==='deviceName')return {name:'Synthetic'};
if(method==='getInfo')return {version:'test',build:'test'};
if(method==='siteState')return {supported:false};
if(method==='vaultPick'){if(window.__pickMode)return new Promise(resolve=>window.__pick=resolve);throw Error('synthetic picker denied')};
if(method==='vaultWrite'){window.__writes=(window.__writes||0)+1;if(window.__holdWrite)return new Promise(resolve=>window.__finishWrite=resolve)};
return {}}}})()"""


class PhoneSettingsRemediation(unittest.TestCase):
    def test_native_export_checks_identity_and_drains_started_write(self):
        with mobile_browser() as (browser, base):
            with synthetic_phone(browser, base, 360, 780, 'light') as (p, errors):
                p.add_init_script(NATIVE)
                scenes.PhoneSettingsBackupRecoveryScenes().boot(p, base)
                p.evaluate("""async()=>{
                  const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                  const {savePhoneKit}=await import('/src/mobile/mirror/phone-recovery.ts');
                  m.pair.recovery={kit:{record:{header:{generation:'synthetic'}}}};
                  window.__pickMode=true;
                  window.__save=savePhoneKit(m.pair).catch(e=>e.message);
                }""")
                p.wait_for_function('!!window.__pick')
                p.evaluate("""async()=>{const g=await import('/src/mobile/mirror/gate.ts');await g.stopCloudWork();g.allowCloudWork();window.__pick({uri:'synthetic',name:'Synthetic'})}""")
                self.assertIn('Previous cloud work stopped', p.evaluate('window.__save'))
                self.assertEqual(p.evaluate('window.__writes||0'), 0)
                p.evaluate("""async()=>{
                  const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');
                  const {savePhoneKit}=await import('/src/mobile/mirror/phone-recovery.ts');
                  window.__holdWrite=true;window.__pick=null;window.__save=savePhoneKit(m.pair).catch(e=>e.message);
                }""")
                p.wait_for_function('!!window.__pick')
                p.evaluate("()=>{window.__pick({uri:'synthetic',name:'Synthetic'})}")
                p.wait_for_function('() => !!window.__finishWrite')
                p.evaluate("""async()=>{const g=await import('/src/mobile/mirror/gate.ts');window.__stop=g.stopCloudWork().then(()=>{window.__stopped=true});}""")
                self.assertFalse(p.evaluate('!!window.__stopped'))
                p.evaluate('()=>{window.__finishWrite()}')
                self.assertIn('Previous cloud work stopped', p.evaluate('window.__save'))
                p.wait_for_function('window.__stopped')
                self.assertEqual(p.evaluate('window.__writes'), 1)
                self.assertFalse(p.evaluate("async()=>{const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts');return !!m.pair.recovery.saved}"))
                self.assertEqual(errors, [])

    def test_shared_offline_assets_model_failures_and_keyboard(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base):
            for theme in ('light', 'dark'):
                with synthetic_phone(browser, base, 320, 780, theme, pair=dict(PAIR, ai={'openai': 'synthetic-key'})) as (p, errors):
                    scenes.PhoneSettingsBackupRecoveryScenes().boot(p, base)
                    result = p.evaluate("""async()=>{
                      const s=await import('/src/mobile/store.ts'), o=await import('/src/mobile/offline.svelte.ts'),state=await import('/src/mobile/state.svelte.ts');
                      const a={id:'a',name:'A',at:1,doc:{items:[]},images:['shared.png','only-a.png']};
                      const b={...a,id:'b',name:'B',images:['shared.png']};
                      await s.kv.setOfflineRequired('saved-canvases',[a,b]);
                      const c=await caches.open(o.OFFLINE),url=n=>state.source.canvasImageUrl(n);
                      for(const n of a.images)await c.put(url(n),new Response(n));
                      await o.removeCanvas('a');
                      return {kept:(await s.kv.get('saved-canvases')).map(x=>x.id),shared:!!await c.match(url('shared.png')),removed:!!await c.match(url('only-a.png'))};
                    }""")
                    self.assertEqual(result, dict(kept=['b'], shared=True, removed=False))
                    p.locator('a[href="#/more/wiskit"]').click()
                    picker = p.get_by_role('button', name='Choose model:')
                    picker.focus()
                    p.keyboard.press('Enter')
                    expect(p.locator('dialog[open]')).to_be_visible()
                    p.keyboard.press('Escape')
                    expect(picker).to_be_focused()
                    # An actual provider response, intercepted before it can leave the browser.
                    p.route('**/v1/models*', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":{"message":"synthetic provider unavailable"}}'))
                    p.get_by_role('button', name='Refresh', exact=True).click()
                    expect(p.get_by_text('synthetic provider unavailable', exact=False)).to_be_visible()
                    expect(p.get_by_role('button', name='Refresh', exact=True)).to_be_enabled()
                    p.evaluate("""()=>{const original=window.fetch;window.fetch=(url,init)=>String(url).includes('/v1/models')?new Promise((resolve,reject)=>{
                      window.__modelsStarted=true;init.signal.addEventListener('abort',()=>{window.__modelsAborted=true;reject(init.signal.reason)},{once:true});
                    }):original(url,init)}""")
                    p.get_by_role('button', name='Refresh', exact=True).click()
                    p.wait_for_function('window.__modelsStarted')
                    p.get_by_role('button', name='Back', exact=True).click()
                    p.wait_for_function('window.__modelsAborted')
                    p.locator('a[href="#/more/wiskit"]').click()
                    expect(p.get_by_role('button', name='Refresh', exact=True)).to_be_enabled()
                    sizes = p.locator('.m-page-keys button').evaluate_all('(els)=>els.map(e=>{const r=e.getBoundingClientRect();return [r.width,r.height]})')
                    self.assertTrue(all(w >= 44 and h >= 44 for w, h in sizes), sizes)
                    # OS reduced motion governs deep-link reveal, independently of the app setting.
                    p.emulate_media(reduced_motion='reduce')
                    p.evaluate("""async()=>{(await import('/src/mobile/state.svelte.ts')).phone.motionOff=false;
                      HTMLElement.prototype.scrollIntoView=function(options){window.__revealBehavior=options.behavior};
                      await(await import('/src/mobile/onboard.svelte.ts')).openMoreBox('m-ai');}""")
                    self.assertEqual(p.evaluate('window.__revealBehavior'), 'instant')
                    p.evaluate("location.hash='#/recover'")
                    p.get_by_role('button', name='Code', exact=True).click()
                    p.locator('input[type=password]').fill('synthetic')
                    colors = p.locator('.m-btn.pill.pri').first.evaluate('e=>{const s=getComputedStyle(e);return [s.color,s.backgroundColor]}')
                    import re
                    def luminance(css):
                        rgb = [int(v)/255 for v in re.findall(r'\d+', css)[:3]]
                        return sum(weight*(v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4) for weight, v in zip((.2126,.7152,.0722), rgb))
                    a, b = sorted(map(luminance, colors))
                    self.assertGreaterEqual((b+.05)/(a+.05), 4.5, colors)
                    self.assertEqual(errors, [])

    def test_persistence_navigation_errors_and_progress(self):
        from playwright.sync_api import expect

        boot = scenes.PhoneSettingsBackupRecoveryScenes().boot
        with mobile_browser() as (browser, base):
            with synthetic_phone(browser, base, 320, 780, 'dark', pair=dict(PAIR, ai={'openai': 'synthetic-key'})) as (p, errors):
                boot(p, base)
                p.locator('a[href="#/more/wiskit"]').click()
                p.get_by_role('button', name='Choose model:').click()
                expect(p.locator('dialog[open]')).to_be_visible()
                p.go_back()
                expect(p).to_have_url(base + '/mobile.html#/more')
                expect(p.locator('dialog[open]')).to_have_count(0)
                p.locator('a[href="#/more/storage"]').click()
                p.evaluate("""async()=>{const s=await import('/src/mobile/store.ts');
                  await s.items.putRequired({id:991,at:1,item:{title:'Opened'}});
                  await s.items.putRequired({id:992,at:1,saved:true,item:{title:'Saved'}});
                  await s.changes.addBatch([{at:1,state:'queued',op:'note',body:'keep me'}]);
                  window.__delete=IDBObjectStore.prototype.delete;
                  IDBObjectStore.prototype.delete=function(k){if(this.name==='items')throw Error('synthetic deletion refused');return window.__delete.call(this,k)};
                }""")
                p.locator('.m-page:visible').get_by_text('Show more', exact=True).click()
                p.get_by_role('button', name='Clear', exact=True).click()
                p.get_by_role('button', name='Sure? Clear', exact=True).click()
                expect(p.get_by_text('Storage could not be cleared completely.', exact=False)).to_be_visible()
                expect(p.get_by_role('button', name='Clear', exact=True)).to_be_enabled()
                self.assertTrue(p.evaluate("async()=>!!await(await import('/src/mobile/store.ts')).items.get(991)"))
                p.evaluate('()=>{IDBObjectStore.prototype.delete=window.__delete}')
                p.get_by_role('button', name='Clear', exact=True).click()
                p.get_by_role('button', name='Sure? Clear', exact=True).click()
                expect(p.get_by_text('Cleared.', exact=False)).to_be_visible()
                self.assertEqual(p.evaluate("async()=>{const s=await import('/src/mobile/store.ts');return [(await s.items.all()).map(x=>x.id),(await s.changes.all()).length]}"), [[992], 1])
                self.assertEqual(errors, [])

            with synthetic_phone(browser, base, 360, 780, 'light') as (p, errors):
                boot(p, base, '#/backup')
                p.evaluate("""async()=>{const s=await import('/src/mobile/store.ts');
                  await s.items.putRequired({id:991,at:1,saved:true,item:{title:'Saved'}});
                  await s.kv.setOfflineRequired('saved-canvases',[{id:'saved',doc:{items:[]}}]);
                  await s.kv.setOfflineRequired('drafts',[{text:'draft'}]);
                  await s.changes.addBatch([{at:1,state:'queued',op:'note',body:'remove me'}]);
                  await s.outbox.add({url:'https://example.invalid',state:'waiting',added:1});
                  for(const name of ['bp-offline-v1','bp-mirror-v1','bp-thumbs-v1'])await(await caches.open(name)).put('/synthetic',new Response('bytes'));
                }""")
                p.locator('#m-phone').get_by_text('Show more', exact=True).click()
                p.get_by_role('button', name='Remove', exact=True).click()
                with p.expect_navigation(wait_until='domcontentloaded'):
                    p.get_by_role('button', name='Sure? Remove', exact=True).click()
                expect(p.locator('#m-status')).to_be_visible()
                result = p.evaluate("""async()=>{const s=await import('/src/mobile/store.ts');return {
                  items:await s.items.all(),changes:await s.changes.all(),outbox:await s.outbox.all(),
                  drafts:await s.drafts.all(),canvases:await s.kv.get('saved-canvases')??[],
                  caches:await Promise.all(['bp-offline-v1','bp-mirror-v1','bp-thumbs-v1'].map(async n=>!!await(await caches.open(n)).match('/synthetic')))}}""")
                self.assertEqual(result, dict(items=[], changes=[], outbox=[], drafts=[], canvases=[], caches=[False]*3))
                self.assertEqual(errors, [])

            with synthetic_phone(browser, base, 360, 780, 'light', pair=dict(PAIR, ai={'openai': 'synthetic-key'})) as (p, errors):
                p.add_init_script(NATIVE)
                boot(p, base)
                p.locator('a[href="#/more/wiskit"]').click()
                p.locator('.m-page:visible').get_by_text('Show more', exact=True).click()
                p.evaluate('window.__failSecret=true')
                p.get_by_role('button', name='Forget', exact=True).click()
                p.get_by_role('button', name='Sure? Forget', exact=True).click()
                expect(p.get_by_text('Keys could not be removed securely.', exact=False)).to_be_visible()
                self.assertTrue(p.evaluate("!!JSON.parse(localStorage.getItem('bp-pair')).ai.openai"))
                self.assertTrue(p.evaluate("async()=>!!(await import('/src/mobile/state.svelte.ts')).mirrorSource.ai()"))
                expect(p.get_by_role('button', name='Retry', exact=True)).to_be_enabled()
                p.evaluate('window.__failSecret=false')
                p.get_by_role('button', name='Retry', exact=True).click()
                p.wait_for_function("!JSON.parse(localStorage.getItem('bp-pair')).ai.openai")
                expect(p.get_by_role('button', name='Retry', exact=True)).to_have_count(0)
                self.assertEqual(errors, [])

            with synthetic_phone(browser, base, 360, 780, 'light', pair=dict(PAIR, solo=False, l='A'*122)) as (p, errors):
                p.add_init_script(NATIVE)
                boot(p, base)
                p.locator('a[href="#/more/obsidian"]').click()
                p.get_by_role('button', name='Choose', exact=True).click()
                expect(p.locator('.m-page:visible').get_by_text('synthetic picker denied', exact=False)).to_be_visible()
                expect(p.get_by_role('button', name='Choose', exact=True)).to_be_enabled()
                self.assertEqual(errors, [])

            with synthetic_phone(browser, base, 360, 780, 'light', pair=dict(PAIR, g='synthetic@example.test', d=base)) as (p, errors):
                boot(p, base)
                p.evaluate("""async()=>{const s=await import('/src/mobile/state.svelte.ts');const n=await import('/src/mobile/network.svelte.ts');n.setSyncPaused(false);
                  s.mirrorSource.drive.listPhoneRecovery=()=>new Promise(resolve=>window.__finishDiscovery=resolve);location.hash='#/recover'}""")
                p.get_by_role('button', name='Find recovery setups', exact=True).click()
                p.wait_for_function('!!window.__finishDiscovery')
                expect(p.get_by_role('progressbar')).to_have_attribute('aria-valuenow', '0')
                expect(p.get_by_text('Step 1 of 3', exact=True)).to_be_visible()
                p.evaluate('window.__finishDiscovery([])')
                expect(p.get_by_role('button', name='Find recovery setups', exact=True)).to_be_enabled()
                self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
