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
                      phone.refreshing=true;phone.read={text:'Reading Google Drive',frac:.15};
                      Object.assign(nativeSync,{supported:true,state:'syncing',phase:'drive',progress:.2});
                    }""")
                    bar = page.locator('#m-status [role=progressbar]')
                    expect(bar).to_have_attribute('aria-valuenow', '50')
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
