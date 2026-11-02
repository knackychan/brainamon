"""The pull widget and failed send step use the current access state's recovery words."""
import json
import unittest

from tests.test_phone_js import node


class SyncAccessErrors(unittest.TestCase):
    def test_removed_access_uses_the_model_for_refresh_and_failed_send(self):
        got = json.loads(node(r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            const src = fs.readFileSync('web/src/mobile/state.svelte.ts', 'utf8')
            const region = src.slice(src.indexOf('const PARTS_AT'), src.indexOf('// after an items_changed'))
            const setup = `
              class LicenseRequired extends Error {}
              class SyncPaused extends Error {}
              class PhoneTooOld extends Error {}
              class NoMirror extends Error {}
              class NeedsSignIn extends Error {}
              const error = new LicenseRequired('Waiting for your PC to confirm this phone.')
              const source = { kind: 'mirror', rows: async () => { throw error } }
              const mirrorSource = { changes: { load: async () => {}, counts: () => ({ unsent: 1 }) },
                flush: async () => { throw error } }
              const phone = { refreshing: false, rows: [], loaded: true, sync: null }
              const phoneStatus = () => ({ id: 'removed', text: "This phone's access was removed on your PC.",
                detail: 'Still your phone? Open the new pairing link from your PC.' })
              const ACCESS_STATES = ['removed'], network = { licenseLocked: true }
              const reconnecting = () => false, syncPaused = () => false, answered = () => true
              const renewSignIn = async () => true, measurePend = async () => {}, isApp = false, solo = false, navigator = { onLine: true }
              const fmtAgo = () => 'just now', window = { setTimeout: () => 0 }
            `
            const mod = await import('data:text/javascript,' + encodeURIComponent(stripTypeScriptTypes(setup + region +
              '\nexport function result() { return { error: phone.error, run: phone.sync } }')))
            try { await mod.syncNow() } catch (e) { console.error(e.message); process.exit(1) }
            console.log(JSON.stringify(mod.result()))
        """))
        expected = "This phone's access was removed on your PC. Still your phone? Open the new pairing link from your PC."
        self.assertEqual(got['error'], expected)
        self.assertEqual(got['run']['msg'], expected)
        self.assertEqual(got['run']['steps'][0]['note'], 'kept for later: ' + expected)
