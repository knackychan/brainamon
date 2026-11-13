"""Live sync progress and narrow panel layout, with disposable storage and no Google calls."""
import unittest

from tests.test_mobile_info_browser import ART, PAIR, mobile_browser, synthetic_phone
from tests.test_phone_settings_remediation_browser import NATIVE
from tests import test_phone_i18n_browser as scenes


class PhoneSyncProgress(unittest.TestCase):
    def test_native_progress_replaces_read_placeholder_and_vault_details_wrap(self):
        from playwright.sync_api import expect

        ART.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width in (320, 390, 900):
                with self.subTest(width=width), synthetic_phone(browser, base, width, 844, 'dark', pair={**PAIR, 'solo': False}) as (page, errors):
                    page.add_init_script(NATIVE)
                    scenes.PhoneSettingsBackupRecoveryScenes().boot(page, base)
                    page.evaluate("""async()=>{
                      const {phone}=await import('/src/mobile/state.svelte.ts');
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');
                      const {network}=await import('/src/mobile/network.svelte.ts');
                      const {vault}=await import('/src/mobile/vault/auto.svelte.ts');
                      network.manualPause=false;network.foreground=true;network.online=true;
                      vault.opts={on:true,uri:'synthetic',name:'Synthetic'};
                      phone.refreshing=false;phone.reachable=true;phone.synced=Date.now()-60000;
                      phone.read={text:'Reading Google Drive',frac:.15};
                      Object.assign(nativeSync,{supported:true,state:'syncing',phase:'drive',progress:0,driveStep:{key:'shell.sync.checkingAccess'}});
                    }""")
                    bar = page.locator('#m-status [role=progressbar]')
                    expect(bar).to_be_visible()
                    expect(page.locator('#m-status [role=progressbar][aria-valuenow]')).to_have_count(0)
                    expect(page.locator('#m-status')).to_contain_text('Checking sync access')
                    self.assertTrue(page.evaluate("""async()=>{
                      const {phoneFacts}=await import('/src/mobile/state.svelte.ts');return phoneFacts().refreshing;
                    }"""), 'native background work must keep the status heading busy')
                    page.evaluate("""async()=>{
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');
                      nativeSync.driveStep={key:'shell.sync.readingIndex'};
                    }""")
                    expect(page.locator('#m-status')).to_contain_text('Reading the Google Drive file list')
                    page.evaluate("""async()=>{
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');
                      Object.assign(nativeSync,{progress:.2,driveStep:{key:'shell.sync.readingFiles',done:2,total:4}});
                    }""")
                    expect(bar).to_have_attribute('aria-valuenow', '50')
                    expect(page.locator('#m-status')).to_contain_text('2/4 files checked')
                    page.evaluate("""async()=>{
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');nativeSync.progress=.3;
                    }""")
                    expect(bar).to_have_attribute('aria-valuenow', '75')
                    page.evaluate("location.hash='#/lib'")
                    expect(page.locator('.m-sync-key')).to_be_visible()
                    page.locator('.m-sync-key').click()
                    panel = page.locator('#m-sync-panel')
                    expect(panel.locator('[role=progressbar]').first).to_have_attribute('aria-valuenow', '75')
                    page.evaluate("""async()=>{
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');
                      Object.assign(nativeSync,{phase:'vault',progress:.695,vaultStep:{key:'backup.vault.step.taking',done:25,total:50},vaultFiles:{done:4555,total:4934}});
                    }""")
                    lane = panel.locator('.m-syncp-lane').filter(has_text='Obsidian vault')
                    expect(lane.locator('[role=progressbar]')).to_have_attribute('aria-valuenow', '50')
                    expect(lane).to_contain_text('25/50')
                    expect(lane).to_contain_text('4555/4934')
                    self.assertTrue(lane.evaluate("el=>{const p=el.querySelector('p'),bar=el.querySelector('.m-runbar');return p.getBoundingClientRect().top>=bar.getBoundingClientRect().bottom}"))
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.screenshot(path=str(ART / f'sync-progress-{width}.png'))
                    page.evaluate("""async()=>{
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');nativeSync.progress=undefined;
                    }""")
                    expect(lane.locator('[role=progressbar][aria-valuenow]')).to_have_count(0)
                    page.evaluate("""async()=>{
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');nativeSync.state='retry';
                    }""")
                    expect(lane).to_contain_text('Waiting')
                    expect(panel.locator('[role=progressbar]')).to_have_count(0)
                    self.assertEqual(errors, [])

    def test_delayed_sync_explains_wait_and_retry_stays_available(self):
        from playwright.sync_api import expect

        native = NATIVE.replace("const methods=[", "const methods=['status','retry',") \
            .replace("['Brainamon','App']", "['Brainamon','App','BrainamonSync']") \
            .replace("if(method==='secretGet')", """if(plugin==='BrainamonSync'){
              if(method==='retry'){window.__retried=(window.__retried||0)+1;return {id:'fresh'}};
              return {supported:!!window.__retried,state:window.__retried?'syncing':'',phase:'drive',retryable:false,nextAt:null};
            };if(method==='secretGet')""")
        with mobile_browser() as (browser, base):
            for width, language in ((320, 'en'), (390, 'fr'), (390, 'zh-Hant')):
                with self.subTest(language=language), synthetic_phone(browser, base, width, 844, 'dark', pair={**PAIR, 'solo': False}, language=language) as (page, errors):
                    page.add_init_script(native)
                    scenes.PhoneSettingsBackupRecoveryScenes().boot(page, base)
                    page.evaluate("""async()=>{
                      const {phone}=await import('/src/mobile/state.svelte.ts');
                      const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');
                      const {network}=await import('/src/mobile/network.svelte.ts');
                      network.manualPause=false;network.foreground=true;network.online=true;
                      phone.refreshing=true;phone.pend.unsent=37;
                      const {vault}=await import('/src/mobile/vault/auto.svelte.ts');
                      vault.opts={on:true,uri:'synthetic',name:'Synthetic'};
                      phone.sync={end:'',msg:'',steps:[{key:'send',label:"Send this phone's changes",state:'run',note:''}]};
                      Object.assign(nativeSync,{supported:true,state:'retry',retryable:true,nextAt:Date.now()+80*60000,vaultFiles:{done:4555,total:4934}});
                      location.hash='#/lib';
                    }""")
                    page.locator('.m-sync-key').click()
                    panel = page.locator('#m-sync-panel')
                    expect(panel.locator('.m-syncp-steps')).to_have_count(0)
                    expect(panel.locator('[role=progressbar]')).to_have_count(0)
                    expect(page.locator('.m-sync-key .spin')).to_have_count(0)
                    expect(panel.locator('.m-syncp-lane').first).to_contain_text('Android')
                    expect(panel.locator('.m-syncp-why')).to_contain_text('37')
                    retry = panel.locator('.m-syncp-btns button').first
                    expect(retry).to_be_enabled()
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.screenshot(path=str(ART / f'sync-delay-{language}.png'))
                    retry.click()
                    page.wait_for_function('window.__retried===1')
                    expect(page.locator('.m-sync-key .spin')).to_have_count(1)
                    expect(panel.locator('[role=alert]')).to_have_count(0)
                    page.evaluate("location.hash='#/more/sync'")
                    page.evaluate("""async()=>{const {nativeSync}=await import('/src/mobile/sync/native.svelte.ts');Object.assign(nativeSync,{state:'retry',retryable:true,nextAt:Date.now()+60000})}""")
                    retry = page.locator('.m-settings-chips button').first
                    expect(retry).to_be_enabled()
                    retry.click()
                    page.wait_for_function('window.__retried===2')
                    self.assertEqual(errors, [])
