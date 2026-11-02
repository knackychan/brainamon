"""What the phone says about its backup and its PC (web/src/mobile/mirror/phone-state.ts; plan
docs/superpowers/plans/2026-10-31-phone-backup-phones.md). tests/fixtures/phone_states.json pins every state's words, tone,
key, strip and lamp; the rules below must hold for any facts. Runs under Node (type stripping), like tests/test_phone_js.py."""
import json
import re
import unittest
from pathlib import Path

from tests import test_phone_js

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'phone_states.json'
SOURCE = ROOT / 'web' / 'src' / 'mobile' / 'mirror' / 'phone-state.ts'

# facts drawn at random, 20,000 times, from a fixed seed: every combination the screens can meet, and more
RULES = r"""
    import { phoneState } from './web/src/mobile/mirror/phone-state.ts'
    let seed = 20261031
    const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
    const pick = a => a[Math.floor(rnd() * a.length)]
    const STRIP = ['removed', 'replaced', 'sign-in-again']
    const PC_ONLY = ['update-app', 'account-mismatch', 'connect', 'replaced', 'removed', 'confirming', 'waiting-pc', 'license',
      'access-invalid', 'webview', 'first-backup', 'key', 'backup-off', 'no-library', 'resending', 'in-sync']
    const COUNTED = ['offline', 'wifi', 'sign-in-again', 'replaced', 'removed', 'waiting-pc', 'unreachable']
    const bad = []
    let n = 0
    for (let i = 0; i < 20000; i++) {
      const f = { mode: pick(['pc', 'solo']), app: pick([true, false]), online: pick([true, true, false]), wifiWait: pick([false, false, true]),
        refreshing: pick([false, true]), tried: pick([true, true, false]), signedIn: pick([true, true, false]),
        account: pick(['a@example.com', '']), pcAccount: pick(['a@example.com', '']), mismatch: pick(['', '', 'b@example.com']),
        access: pick(['', '', 'missing', 'expired', 'replaced', 'inactive', 'invalid', 'webview']), hadAccess: pick([true, false]),
        since: pick(['15:05', '']), noLibrary: pick(['', '', 'uploading', 'key', 'mirror-off', 'project', 'account', 'empty', 'unknown']),
        noLibraryText: 'Diagnosis words from diagnose.ts, naming the PC.', reachable: pick([true, false]), tooOld: pick([false, false, true]),
        checked: pick(['2 min ago', '']), unsent: pick([0, 0, 1, 3]), waiting: pick([0, 0, 1, 2]), resending: pick([0, 0, 3]),
        recovery: pick(['none', 'prepared', 'saved', 'checked']) }
      if (f.mode === 'solo') { f.pcAccount = ''; f.mismatch = ''; f.access = ''; f.noLibrary = ''; f.tooOld = false; f.waiting = 0; f.resending = 0 }
      const s = phoneState(f), words = `${s.text} ${s.detail}`, pending = f.unsent + f.waiting, why = []
      if (Object.keys(s).sort().join() !== 'action,detail,id,lamp,strip,text,tone') why.push('shape')
      if (s.strip !== STRIP.includes(s.id)) why.push('strip')
      if (s.action?.primary && s.tone !== 'next') why.push('a primary key without a need')
      if (s.tone === 'next' && !s.action && !/PC|Settings|Android|browser|WebView|Play Store/.test(words)) why.push('dead end')
      if (!f.app && s.action?.id === 'scan') why.push('Scan in a browser')
      if (f.mode === 'solo' ? PC_ONLY.includes(s.id) : s.id.startsWith('solo-')) why.push('mode')
      if (/[–—]|  /.test(words) || !/[.…]$/.test(s.text) || (s.detail && !/[.…]$/.test(s.detail))) why.push('words')
      if (pending && COUNTED.includes(s.id) && !words.includes(pending === 1 ? '1 edit' : `${pending} edits`)) why.push('edits not counted')
      if (s.lamp.length > 16) why.push('lamp')
      if (why.length) { n++; if (bad.length < 3) bad.push({ f, s, why }) }
    }
    console.log(JSON.stringify({ n, bad }))
"""


class PhoneStateTest(unittest.TestCase):
    def test_every_state_reads_as_the_fixture_pins_it(self):
        fx = json.loads(FIXTURE.read_text(encoding='utf-8'))
        got = json.loads(test_phone_js.node("""
            import fs from 'node:fs'
            import { phoneState } from './web/src/mobile/mirror/phone-state.ts'
            const fx = JSON.parse(fs.readFileSync('tests/fixtures/phone_states.json', 'utf8'))
            console.log(JSON.stringify(fx.cases.map(c => phoneState({ ...fx.base, ...c.facts }))))
        """))
        self.assertEqual(len(got), len(fx['cases']))
        for case, state in zip(fx['cases'], got):
            with self.subTest(case['name']):
                self.assertEqual(state, case['expect'])

    def test_the_fixture_reaches_every_state(self):
        text = SOURCE.read_text(encoding='utf-8')
        block = re.search(r'export type StateId =(.*?)\nexport ', text, re.S).group(1)
        ids = set(re.findall(r"'([a-z-]+)'", block))
        reached = {c['expect']['id'] for c in json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']}
        self.assertEqual(len(ids), 27)
        self.assertEqual(ids - reached, set())

    def test_a_retry_shows_progress_until_the_current_read_finishes(self):
        out = json.loads(test_phone_js.node("""
            import fs from 'node:fs'
            import { phoneState } from './web/src/mobile/mirror/phone-state.ts'
            const { base } = JSON.parse(fs.readFileSync('tests/fixtures/phone_states.json', 'utf8'))
            console.log(JSON.stringify(['pc', 'solo'].map(mode => {
              const f = { ...base, mode, tried: true, reachable: false, recovery: 'checked' }
              return {
                failed: phoneState(f),
                retrying: phoneState({ ...f, refreshing: true }),
                failedAgain: phoneState({ ...f, refreshing: false }),
                succeeded: phoneState({ ...f, reachable: true }),
                offline: phoneState({ ...f, refreshing: true, online: false }),
                refused: phoneState({ ...f, refreshing: true, signedIn: false }),
              }
            })))
        """))
        for mode, states in zip(('pc', 'solo'), out):
            with self.subTest(mode=mode):
                self.assertEqual(states['failed']['id'], 'unreachable')
                self.assertEqual(states['retrying']['id'], 'connecting')
                self.assertEqual(states['retrying']['tone'], 'busy')
                self.assertEqual(states['retrying']['text'], 'Checking Google Drive…')
                self.assertIsNone(states['retrying']['action'])
                self.assertEqual(states['failedAgain']['id'], 'unreachable')
                self.assertEqual(states['succeeded']['id'], 'in-sync' if mode == 'pc' else 'solo-ok')
                self.assertEqual(states['offline']['id'], 'offline')
                self.assertEqual(states['refused']['id'], 'sign-in-again')

    def test_rules_hold_for_any_facts(self):
        out = json.loads(test_phone_js.node(RULES, timeout=120))
        self.assertEqual(out['n'], 0, out['bad'])

    def test_clock_reads_like_the_pc_page(self):
        out = json.loads(test_phone_js.node("""
            import { clock } from './web/src/mobile/mirror/phone-state.ts'
            const now = new Date(2026, 9, 31, 18, 0).getTime()
            console.log(JSON.stringify([clock(new Date(2026, 9, 31, 15, 5).getTime(), now), clock(new Date(2026, 9, 30, 9, 7).getTime(), now), clock(0, now)]))
        """))
        self.assertEqual(out, ['15:05', '30 Oct 09:07', ''])


if __name__ == '__main__':
    unittest.main()
