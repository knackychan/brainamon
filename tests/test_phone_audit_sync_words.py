"""A finished sync must not override the current access refusal with stale words."""
import json
import unittest

from tests.test_phone_js import node


class SyncWords(unittest.TestCase):
    def test_current_access_reason_wins_over_the_previous_sync_message(self):
        rows = json.loads(node(r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            import { t } from './web/src/lib/i18n/index.ts'
            globalThis.__syncWordsT = t
            let src = fs.readFileSync('web/src/mobile/lanes.ts', 'utf8')
              .replace(/^import .*$/gm, '')
            const setup = `
              const t = globalThis.__syncWordsT
              const backup = {task:null,busy:false}; const isApp = false, mirrorSource = {}, solo = false, source = {}, pics = { state: 'idle' }
              const phone = { sync: { end: 'error', msg: 'Waiting for your PC to confirm this phone.' } }
              const driveWork = () => null, syncPaused = () => false, fmtAgo = () => 'just now'
              const nativeSync = { supported: false }
              let current = { ok: false, lamp: 'access removed', why: "This phone's access was removed on your PC." }
              const driveStatus = () => current
            `
            src = stripTypeScriptTypes(setup + src + `
              export function cases() {
                const removed = syncLanes()[0]
                current = { ok: false, lamp: 'PC changed', why: 'Your PC has changed.' }
                const replaced = syncLanes()[0]
                current = { ok: true, lamp: 'connected', why: '' }
                phone.sync = { end: 'done', msg: 'Your changes were sent.' }
                return [removed, replaced, syncLanes()[0]]
              }
            `)
            const { cases } = await import('data:text/javascript,' + encodeURIComponent(src))
            console.log(JSON.stringify(cases()))
        """))
        self.assertEqual(rows[0]['text'], "This phone's access was removed on your PC.")
        self.assertEqual(rows[1]['text'], 'Your PC has changed.')
        self.assertEqual(rows[2]['text'], 'Your changes were sent.')
