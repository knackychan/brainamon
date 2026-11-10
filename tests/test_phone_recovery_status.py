"""Recovery progress names the operation and clears when it finishes or fails."""
import json
import unittest

from tests.test_phone_js import node


class PhoneRecoveryStatusTest(unittest.TestCase):
    def test_status_recovery_actions_wait_for_the_current_connection_or_sync(self):
        out = json.loads(node(r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            globalThis.__phone = { connecting: false, refreshing: false, sync: null }
            globalThis.__rec = { busy: false }
            const source = fs.readFileSync('web/src/mobile/actions.ts', 'utf8')
            const region = source.slice(source.indexOf('const GOOGLE'))
            const setup = 'const phone = globalThis.__phone, rec = globalThis.__rec;'
            const mod = await import('data:text/javascript,' + encodeURIComponent(stripTypeScriptTypes(setup + region)))
            const results = []
            for (const over of [{}, { connecting: true }, { refreshing: true }, { sync: { end: '' } }, { sync: { end: 'done' } }]) {
              Object.assign(__phone, { connecting: false, refreshing: false, sync: null }, over)
              results.push(['set-up-recovery', 'check-file'].map(mod.actionBusy))
            }
            __rec.busy = true
            results.push(['set-up-recovery', 'check-file'].map(mod.actionBusy))
            console.log(JSON.stringify(results))
        """))
        self.assertEqual(out, [[False, False], [True, True], [True, True], [True, True], [False, False], [True, True]])

    def test_activity_covers_success_failure_and_a_second_click(self):
        out = json.loads(node(r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            const source = fs.readFileSync('web/src/mobile/recovery.svelte.ts', 'utf8')
            const region = source.slice(source.indexOf('export const rec'), source.indexOf('// a recovery file'))
            const {t} = await import('./web/src/lib/i18n/index.ts')
            const {nativeError} = await import('./web/src/mobile/settings-words.ts')
            const {beginLanguageWork} = await import('./web/src/mobile/language-switch.ts')
            globalThis.__recoveryDeps = {t, nativeError, beginLanguageWork}
            const setup = 'const $state = x => x; const phone = { recoveryAt: 0 }; const {t,nativeError,beginLanguageWork}=globalThis.__recoveryDeps;'
            const mod = await import('data:text/javascript,' + encodeURIComponent(stripTypeScriptTypes(setup + region)))
            let finish, second = false
            const pending = mod.recoveryRun(() => new Promise(resolve => { finish = resolve }), 'Saving passphrase')
            const during = { ...mod.rec }
            await mod.recoveryRun(async () => { second = true }, 'Second operation')
            finish(); await pending
            const after = { ...mod.rec }
            await mod.recoveryRun(async () => { throw new Error('Synthetic failure') })
            console.log(JSON.stringify({ during, after, failed: mod.rec, second }))
        """))
        self.assertTrue(out['during']['busy'])
        self.assertEqual(out['during']['activity'], 'Saving passphrase')
        self.assertFalse(out['second'])
        for result in (out['after'], out['failed']):
            self.assertFalse(result['busy'])
            self.assertEqual(result['activity'], '')
        self.assertEqual(out['failed']['error'], 'Synthetic failure')
