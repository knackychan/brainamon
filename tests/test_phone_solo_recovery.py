"""What protects the key of the phone without a PC (docs/superpowers/plans/2026-10-31-phone-backup-phones.md, sub-plan
05): web/src/mobile/mirror/recovery-fact.ts recoveryFact says none, prepared, saved or checked for the setup this phone
remembers for its own key and its confirmed Google account; Save recovery file… in the app records its receipt only
after the file was written and while the library and its setup are still the same, a browser download counts for its
session only, and a file that is not this setup's never changes it. Runs under Node with a stand-in Android plugin and a
stand-in Drive (synthetic keys and passphrase, no network), like tests/test_phone_reconnect.py."""
import json
import unittest

from tests import test_phone_js

# native.ts asks Capacitor whether it runs in the app and for the Brainamon plugin: here a flag and a stand-in that
# records what the page asked it (a folder, the file's chunks, the protected secrets)
PRELUDE = test_phone_js.TS_RESOLVE + r"""
    const { registerHooks } = await import('node:module')
    registerHooks({ load(url, context, next) {
      const r = next(url, context)
      if (!url.endsWith('/web/src/mobile/native.ts')) return r
      const text = typeof r.source === 'string' ? r.source : new TextDecoder().decode(r.source)     // bytes after register()
      const src = text.replace('export const isApp = Capacitor.isNativePlatform()', 'export const isApp = globalThis.__app === true')
        .replace(/const B = registerPlugin\s*(<BrainamonPlugin>)?\s*\('Brainamon'\)/, 'const B = globalThis.__plugin')
      if (!src.includes('globalThis.__app') || !src.includes('globalThis.__plugin')) throw new Error('native.ts changed: update the stand-in')
      return { ...r, source: src }
    } })
    const mem = new Map(), session = new Map()
    globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) }
    globalThis.sessionStorage = { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, String(v)), removeItem: k => session.delete(k) }
    globalThis.window = new EventTarget()
    const downloads = []
    globalThis.document = Object.assign(new EventTarget(), {
      createElement: () => ({ click() { downloads.push(this.download) }, remove() {} }), body: { append() {} } })
    Object.defineProperty(navigator, 'onLine', { value: true })
    const calls = [], secretsHeld = new Map(), folder = new Map()
    const fail = { pick: '', write: '', finish: null }
    globalThis.__plugin = {
      vaultPick: async () => { calls.push('pick'); if (fail.pick) throw new Error(fail.pick); return { uri: 'content://synthetic', name: 'Synthetic folder' } },
      vaultDelete: async o => { calls.push('delete ' + o.path); folder.delete(o.path) },
      vaultWrite: async o => {
        calls.push('write ' + o.path)
        if (fail.write) throw new Error(fail.write)
        folder.set(o.path, (o.append ? folder.get(o.path) ?? '' : '') + Buffer.from(o.data, 'base64').toString('utf8'))
      },
      vaultFinish: async o => { calls.push('finish ' + o.path); folder.set(o.path, folder.get(o.tmp)); folder.delete(o.tmp); fail.finish?.() },
      secretSet: async o => { secretsHeld.set(o.key, o.value) },
      secretGet: async o => ({ value: secretsHeld.get(o.key) ?? null }),
    }
    const P = await import('./web/src/mobile/mirror/pairing.ts')
    const N = await import('./web/src/mobile/native.ts')
    const PR = await import('./web/src/mobile/mirror/phone-recovery.ts')
    const RF = await import('./web/src/mobile/mirror/recovery-fact.ts')
    const E = await import('./web/src/mobile/mirror/recovery-envelope.ts')
    // the phone's own Drive folder: the account it signs in to and the recovery setups uploaded there
    const files = new Map()
    let who = 'a@example.com'
    const drive = {
      about: async () => who,
      create: async (name, data) => { const id = 'f' + (files.size + 1); files.set(id, { name, text: new TextDecoder().decode(data) }); return id },
      listPhoneRecovery: async () => [...files].filter(([, f]) => f.name.startsWith(E.PHONE_RECOVERY_PREFIX)).map(([id, f]) => ({ id, name: f.name, size: f.text.length })),
      getPhoneRecovery: async id => files.get(id).text,
    }
    const PASS = 'synthetic recovery passphrase'
    const fact = (over = {}) => RF.recoveryFact({ ...structuredClone(pair), ...over })
    const attempt = async f => { try { return { ok: await f() } } catch (e) { return { error: e.message } } }
    await P.startSolo('A'.repeat(43))
    const pair = P.pairing()
    P.confirmAccount(pair, 'a@example.com')
    N.secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
    await N.secretsSaved()
    const out = { none: fact() }
    await PR.preparePhoneRecovery(pair, drive, PASS, PASS)
    const kit = pair.recovery.kit, setup = pair.recovery
"""

# the app: a folder chosen, cancelled or refused, the setup changed while the file was written, then checked
APP = PRELUDE.replace("const { registerHooks }", "globalThis.__app = true\n    const { registerHooks }", 1) + r"""
    const stored = () => JSON.parse(secretsHeld.get('bp-pair')).recovery
    Object.assign(out, {
      prepared: fact(), upperCase: fact({ g: 'A@EXAMPLE.COM' }), noAccount: fact({ g: undefined }), otherAccount: fact({ g: 'b@example.com' }),
      otherKey: fact({ f: 'b'.repeat(12) }), damaged: fact({ recovery: { kit: { format: 'synthetic' }, verified: false } }),
      receipt: fact({ recovery: { ...setup, saved: 1 } }), verified: fact({ recovery: { ...setup, verified: true } }),
      verifiedAndSaved: fact({ recovery: { ...setup, verified: true, saved: 1 } }),
    })
    fail.pick = 'cancelled'
    out.cancelled = { got: await attempt(() => PR.savePhoneKit(pair)), saved: pair.recovery.saved ?? null }
    fail.pick = 'The folder could not be opened.'
    out.refused = { got: await attempt(() => PR.savePhoneKit(pair)), saved: pair.recovery.saved ?? null }
    fail.pick = ''; fail.write = 'Synthetic write failure.'
    out.writeFailed = { got: await attempt(() => PR.savePhoneKit(pair)), saved: pair.recovery.saved ?? null }
    fail.write = ''
    // another library opened while the file was written (the stored pairing no longer holds this key)
    fail.finish = () => { N.secrets.set('bp-pair', JSON.stringify({ ...pair, k: 'B'.repeat(43) })) }
    out.libraryChanged = { got: await attempt(() => PR.savePhoneKit(pair)), saved: pair.recovery.saved ?? null }
    N.secrets.set('bp-pair', JSON.stringify(pair))
    // the setup made again while the file was written
    fail.finish = () => { pair.recovery = { ...setup } }
    out.setupChanged = { got: await attempt(() => PR.savePhoneKit(pair)), saved: pair.recovery.saved ?? null }
    pair.recovery = setup; N.secrets.set('bp-pair', JSON.stringify(pair))
    fail.finish = null
    calls.length = 0
    out.saved = { got: await attempt(() => PR.savePhoneKit(pair)), fact: RF.recoveryFact(pair), receipt: typeof pair.recovery.saved,
      stored: typeof stored().saved, calls: [...calls] }
    await N.secretsSaved()
    out.stored = typeof stored().saved
    const name = `Brainamon-phone-recovery-kit-${kit.record.header.generation}.json`
    const text = folder.get(name)
    out.file = text === E.recoveryJSON(kit)
    const other = E.recoveryJSON({ ...kit, secret: Buffer.alloc(32, 7).toString('base64url') })
    out.wrongFile = { got: await attempt(() => PR.verifyPhoneRecovery(pair, drive, other)), fact: RF.recoveryFact(pair) }
    out.rightFile = { got: await attempt(() => PR.verifyPhoneRecovery(pair, drive, text)), fact: RF.recoveryFact(pair), stored: stored().verified }
    out.wrongAfter = { got: await attempt(() => PR.verifyPhoneRecovery(pair, drive, other)), fact: RF.recoveryFact(pair) }
    P.confirmAccount(pair, 'b@example.com')
    out.accountChanged = RF.recoveryFact(pair)
    console.log(JSON.stringify(out))
"""

# a phone browser: a download asked for counts as saved for this page's session only, and only for its setup
BROWSER = PRELUDE + r"""
    out.prepared = fact()
    out.download = { got: await attempt(() => PR.savePhoneKit(pair)), fact: RF.recoveryFact(pair), receipt: pair.recovery.saved ?? null,
      stored: JSON.parse(localStorage.getItem('bp-pair')).recovery.saved ?? null, downloads: [...downloads], pick: calls.includes('pick') }
    const again = structuredClone(setup)
    again.kit.record.header.generation = 'c'.repeat(32)
    out.newSetup = fact({ recovery: again })
    // the setups found in Drive, newest first (Recover a library… shows them in this order)
    const record = (n, created) => ({ ...structuredClone(kit.record), header: { ...kit.record.header, generation: n.repeat(32), created } })
    files.clear()
    for (const r of [record('1', 100), record('3', 300), record('2', 200)]) await drive.create(E.phoneRecoveryName(r), new TextEncoder().encode(E.recoveryJSON(r)))
    out.discovered = (await PR.discoverPhoneRecovery(drive)).map(s => s.record.header.created)
    console.log(JSON.stringify(out))
"""


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneSoloRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = json.loads(test_phone_js.node(APP, timeout=180))
        cls.browser = json.loads(test_phone_js.node(BROWSER, timeout=180))

    def test_the_recovery_fact_belongs_to_this_key_and_account(self):
        a = self.app
        self.assertEqual((a['none'], a['prepared'], a['upperCase']), ('none', 'prepared', 'prepared'))
        for name in ('noAccount', 'otherAccount', 'otherKey', 'damaged', 'accountChanged'):
            self.assertEqual(a[name], 'none', name)
        self.assertEqual((a['receipt'], a['verified'], a['verifiedAndSaved']), ('saved', 'checked', 'checked'))

    def test_the_app_records_a_saved_file_only_after_it_was_written(self):
        a = self.app
        self.assertEqual(a['cancelled'], {'got': {'ok': 'cancelled'}, 'saved': None})
        self.assertEqual(a['refused'], {'got': {'error': 'The folder could not be opened.'}, 'saved': None})
        self.assertEqual(a['writeFailed'], {'got': {'error': 'Synthetic write failure.'}, 'saved': None})
        changed = 'The phone library or its recovery changed while saving. Save the recovery file again.'
        self.assertEqual(a['libraryChanged'], {'got': {'error': changed}, 'saved': None})
        self.assertEqual(a['setupChanged'], {'got': {'error': changed}, 'saved': None})
        self.assertEqual(a['saved']['got'], {'ok': 'saved'})
        self.assertEqual((a['saved']['fact'], a['saved']['receipt'], a['stored']), ('saved', 'number', 'number'))
        name = a['saved']['calls'][-1].removeprefix('finish ')
        self.assertRegex(name, r'^Brainamon-phone-recovery-kit-[0-9a-f]{32}\.json$')
        self.assertEqual(a['saved']['calls'], ['pick', f'delete {name}.vsync-tmp', f'write {name}.vsync-tmp', f'finish {name}'])
        self.assertTrue(a['file'])                      # the folder holds this setup's recovery file, as recoveryJSON writes it

    def test_only_this_setups_file_checks_it(self):
        a = self.app
        self.assertEqual(a['wrongFile'], {'got': {'error': 'Select the recovery file saved for this setup.'}, 'fact': 'saved'})
        self.assertEqual(a['rightFile'], {'got': {}, 'fact': 'checked', 'stored': True})
        self.assertEqual(a['wrongAfter'], {'got': {'error': 'Select the recovery file saved for this setup.'}, 'fact': 'checked'})

    def test_a_browser_download_counts_for_its_session_only(self):
        b = self.browser
        self.assertEqual(b['prepared'], 'prepared')
        d = b['download']
        self.assertEqual((d['got'], d['fact'], d['receipt'], d['stored'], d['pick']), ({'ok': 'downloaded'}, 'saved', None, None, False))
        self.assertRegex(d['downloads'][0], r'^Brainamon-phone-recovery-kit-[0-9a-f]{32}\.json$')
        self.assertEqual(b['newSetup'], 'prepared')         # a new setup's file is not saved yet
        self.assertEqual(b['discovered'], [300, 200, 100])


if __name__ == '__main__':
    unittest.main()
