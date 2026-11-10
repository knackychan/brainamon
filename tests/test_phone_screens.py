"""The phone's screens show the one status model (docs/superpowers/plans/2026-10-31-phone-backup-phones.md, sub-plans 04
and 05): the facts a paired phone and a phone without a PC gather reach every state of tests/fixtures/phone_states.json
(web/src/mobile/mirror/phone-facts.ts), the change journal tells its watchers after every change (mirror/changes.ts), the
back routes and More's box openers know More > Backup & phones and Recover a library, and the screens are wired to it.
Runs under Node (type stripping), like tests/test_phone_js.py."""
import json
import re
import unittest
from pathlib import Path

from tests import test_phone_js
from tests.phone_catalog import english

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'web' / 'src' / 'mobile'


def source(rel: str) -> str:
    return (MOBILE / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


# what a paired phone holds in each fixture case (by its name), as the adapter's input; the clock is 15:30 local time
FACTS = r"""
    import fs from 'node:fs'
    import { pairedFacts, soloFacts, unpairEdits, unpairWarning } from './web/src/mobile/mirror/phone-facts.ts'
    import { phoneState } from './web/src/mobile/mirror/phone-state.ts'
    const fx = JSON.parse(fs.readFileSync('tests/fixtures/phone_states.json', 'utf8'))
    const at = (h, m) => new Date(2026, 9, 31, h, m).getTime()
    const why = cause => ({ cause, title: 'No library', message: 'Diagnosis words from diagnose.ts, naming the PC.', changeAccount: cause === 'account', pairAgain: cause === 'unknown' })
    const base = { app: true, online: true, paused: false, refreshing: false, tried: true, token: true, refused: false,
      account: 'a@example.com', pcAccount: 'a@example.com', mismatch: '', access: '', accessAt: 0, last: at(15, 5),
      noLibrary: null, reachable: true, tooOld: false, checked: '2 min ago', pend: { unsent: 0, waiting: 0, resending: 0 }, now: at(15, 30) }
    const pend = (unsent, waiting = 0, resending = 0) => ({ pend: { unsent, waiting, resending } })
    const APP = {
      'sync paused by user': { pause: 'Sync paused by you.' },
      'PH4 in sync, all sent': {},
      'PH4 in sync, edits not sent': pend(2, 1),
      'PH4 in sync, edits waiting for the PC': pend(0, 1),
      'PH4 syncing': { refreshing: true },
      'PH5 offline with edits': { online: false, paused: true, ...pend(2, 1) },
      'PH5 offline with one edit': { online: false, paused: true, ...pend(1) },
      'PH5 offline, nothing waiting': { online: false, paused: true },
      'Wi-Fi only on mobile data': { paused: true, ...pend(1) },
      'PC copy too new': { tooOld: true },
      'signed in to another account': { token: false, account: '', mismatch: 'b@example.com' },
      'PH9 Google asks to sign in again': { token: false, ...pend(3) },
      'PH2 connect Google Drive': { token: false, refused: true, account: '' },
      'PH12 PC restored or reinstalled': { access: 'replaced', reachable: false, ...pend(3) },
      'PH12 in a phone browser': { access: 'replaced', app: false, reachable: false },
      'PH7 access removed': { access: 'missing', reachable: false, ...pend(2, 1) },
      'PH7 in a phone browser': { access: 'missing', app: false, reachable: false, ...pend(3) },
      'first confirmation on its way': { access: 'missing', last: 0, reachable: false },
      'PH6 PC not renewing': { access: 'expired', accessAt: at(14, 2), reachable: false, ...pend(3) },
      'PH6 in a phone browser': { access: 'expired', app: false, accessAt: at(14, 2), reachable: false },
      'PC license inactive': { access: 'inactive', reachable: false },
      'access could not be checked': { access: 'invalid', reachable: false },
      'access could not be checked in a phone browser': { access: 'invalid', app: false, reachable: false },
      'WebView too old': { access: 'webview', reachable: false },
      'this browser too old': { access: 'webview', app: false, reachable: false },
      'PH3 first backup running': { noLibrary: why('uploading'), reachable: false },
      'pairing out of date': { noLibrary: why('key'), reachable: false },
      'pairing out of date in a phone browser': { noLibrary: why('key'), app: false, reachable: false },
      'PC not backing up the library': { noLibrary: why('mirror-off'), reachable: false },
      'no library, account unknown': { noLibrary: why('account'), reachable: false },
      'no library, folder not listed': { noLibrary: why('unknown'), reachable: false },
      'no library, empty folder': { noLibrary: why('empty'), reachable: false },
      'first read running': { tried: false, refreshing: true, reachable: false },
      'Drive out of reach': { reachable: false, ...pend(1) },
      'PH8 resending after pairing again': pend(3, 0, 3),
    }
    const id = over => phoneState(pairedFacts({ ...base, ...over })).id
    // what a phone without a PC holds: a token for its confirmed account, the last backup round (MirrorSource.round) and
    // its recovery setup (recovery-fact.ts recoveryFact)
    const solo = { app: true, online: true, paused: false, refreshing: false, started: true, token: true, account: 'a@example.com',
      round: { ok: true, ago: '2 min ago' }, recovery: 'none', unsent: 0 }
    const SOLO = {
      'solo: saved backup task': { backupTask: { busy: false, text: 'Backup task paused.', detail: 'Local content and queued edits stay here. Open the saved task to continue.' } },
      'solo: only on this phone': { token: false, account: '' },
      'solo: Google asks to sign in again': { token: false },
      'solo: no recovery yet': {},
      'solo: recovery file not checked': { recovery: 'saved' },
      'solo: passphrase set, no recovery file': { recovery: 'prepared' },
      'solo: backed up': { recovery: 'checked' },
      'solo: edits not backed up yet': { recovery: 'checked', unsent: 2 },
    }
    const soloId = over => phoneState(soloFacts({ ...solo, ...over })).id
    const want = c => phoneState({ ...fx.base, ...c.facts })
    const cases = fx.cases.filter(c => c.name in APP).map(c => ({ name: c.name, want: want(c),
      got: phoneState(pairedFacts({ ...base, ...APP[c.name] })) }))
    const soloCases = fx.cases.filter(c => c.name in SOLO).map(c => ({ name: c.name, want: want(c),
      got: phoneState(soloFacts({ ...solo, ...SOLO[c.name] })) }))
    const states = mode => [...new Set(fx.cases.filter(c => (c.facts.mode ?? fx.base.mode) === mode).map(c => want(c).id))]
    console.log(JSON.stringify({ cases, soloCases, unmapped: fx.cases.filter(c => !(c.name in APP) && !(c.name in SOLO)).map(c => c.name),
      pcStates: states('pc'), soloStates: states('solo'),
      solo: {
        beforeFirstRound: soloId({ round: null, refreshing: true }),
        expiredBeforeStart: soloId({ token: false, started: false, round: null }),
        failedRound: soloId({ round: { ok: false, ago: '1 min ago' } }),
        failedChecked: soloFacts({ ...solo, round: { ok: false, ago: '1 min ago' } }).checked,
        neverSignedIn: soloId({ token: false, account: '', started: false, round: null }),
        refusedAfterStart: soloId({ token: false }),
      },
      rules: {
        beforeFirstRead: id({ token: false, tried: false, refreshing: true, reachable: false }),
        refusedConfirmed: id({ refused: true }),
        refusedFresh: id({ token: false, refused: true, account: '' }),
        expiredToken: id({ token: false }),
        offlineAndPaused: id({ online: false, paused: true }),
        sinceExpired: pairedFacts({ ...base, access: 'expired', accessAt: at(14, 2) }).since,
        sinceRemoved: pairedFacts({ ...base, access: 'missing' }).since,
        sinceYesterday: pairedFacts({ ...base, access: 'missing', last: at(15, 5) - 86400000 }).since,
        neverHadAccess: pairedFacts({ ...base, access: 'missing', last: 0 }).hadAccess,
        words: [0, 1, 3].map(unpairWarning),
        edits: [unpairEdits({ unsent: 1, waiting: 2, held: 1 }, false), unpairEdits({ unsent: 1, waiting: 2, held: 1 }, true)],
      } }))
"""

# the journal in memory (store.ts without IndexedDB); every public change, then one after the watcher stopped
WATCH = r"""
    const { changes: db, kv } = await import('./web/src/mobile/store.ts')
    const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
    const mem = new Map()
    globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) }
    const rows = new Map(), store = new Map()
    let nextId = 1
    db.all = async () => structuredClone([...rows.values()].sort((a, b) => a.id - b.id))
    db.add = async e => { const id = nextId++; rows.set(id, structuredClone({ ...e, id })); return id }
    db.put = async e => { rows.set(e.id, structuredClone(e)); return e.id }
    db.del = async id => { rows.delete(id) }
    db.delConfirmed = async id => { rows.delete(id); return true }
    db.forChat = async () => structuredClone([...rows.values()])
    db.saveChat = async e => { const id = e.id ?? nextId++; rows.set(id, structuredClone({ ...e, id })); return id }
    kv.get = async k => structuredClone(store.get(k))
    kv.set = async (k, v) => { store.set(k, structuredClone(v)) }
    kv.del = async k => { store.delete(k) }
    const c = new Changes(), seen = []
    let step = ''
    const stop = c.watch(() => seen.push(step))
    c.watch(() => { throw new Error('a watcher that fails') })
    const run = async (name, f) => { step = name; try { await f() } catch { /* the canvas store needs IndexedDB */ } }
    await run('load', () => c.load())
    await run('add', () => c.add({ op: 'fav', uid: 'u1', on: true }))
    await run('add the same', () => c.add({ op: 'fav', uid: 'u1', on: false }))
    await run('saveChat', () => c.saveChat({ op: 'chat', slug: 's1', turns: [] }))
    await run('dropQueuedChat', () => c.dropQueuedChat('s1'))
    await run('add a note', () => c.add({ op: 'note', file: 'n.md', body: 'x' }))
    await run('dropQueuedNote', () => c.dropQueuedNote('n.md'))
    await run('add a link', () => c.add({ op: 'link', uid: 'l1', url: 'https://example.invalid/a', note: '' }))
    await run('amendLink', () => c.amendLink('l1', { note: 'n' }))
    await run('dropQueuedLink', () => c.dropQueuedLink('l1'))
    await run('flush', () => c.flush(async () => 'chg-1', 'dev1', true, true))
    const stream = c.list.find(e => e.stream)?.stream ?? ''
    await run('prune', () => c.prune(0, { delivery: 2, published: 1, receipts: { [stream]: { seq: 1 } } }))
    await run('add a canvas change', () => c.add({ op: 'canvas', canvas_id: 'c1', op_id: 'o1', canvasLocal: { status: 'pending' } }))
    const canvas = c.list.find(e => e.op === 'canvas')
    await run('canvasResult', () => c.canvasResult(canvas, 'refused', 'synthetic'))
    await run('pruneCanvas', () => c.pruneCanvas(canvas))
    await run('requeue', () => c.requeue())
    await run('merge', () => c.merge([]))
    stop()
    await run('after stop', () => c.add({ op: 'fav', uid: 'u3', on: true }))
    console.log(JSON.stringify({ seen: [...new Set(seen)], left: c.list.length }))
"""

# onboard.svelte.ts with Svelte, the store and the state module stubbed: which hash each opener sets from each screen
OPEN = r"""
    globalThis.$state = x => x
    const { registerHooks } = await import('node:module')
    const stub = { svelte: 'export const tick = async () => {}', './store': 'export const kv = {}',
      './state.svelte': 'export const phone = globalThis.__phone; export let solo = false; globalThis.__setSolo = v => { solo = v }' }
    registerHooks({ resolve: (s, c, n) => s in stub ? { url: 'data:text/javascript,' + encodeURIComponent(stub[s]), shortCircuit: true } : n(s, c) })
    const set = []
    globalThis.location = { get hash() { return '#/x' }, set hash(v) { set.push(v) } }
    globalThis.document = { getElementById: () => ({ scrollIntoView() {} }) }
    globalThis.requestAnimationFrame = f => setTimeout(f, 0)
    globalThis.__phone = { route: { tab: 'lib' } }
    const { openBackupBox, openMoreBox, openPairing } = await import('./web/src/mobile/onboard.svelte.ts')
    const from = async (route, f) => { globalThis.__phone.route = route; set.length = 0; await f(); return set.slice() }
    console.log(JSON.stringify({
      moreFromLibrary: await from({ tab: 'lib' }, () => openMoreBox('m-ai')),
      moreFromMore: await from({ tab: 'more' }, () => openMoreBox('m-ai')),
      moreFromImport: await from({ tab: 'cap', imp: true }, () => openMoreBox('m-ai')),
      moreFromBackup: await from({ tab: 'more', backup: true }, () => openMoreBox('m-ai')),
      backupFromMore: await from({ tab: 'more' }, () => openBackupBox('m-conn')),
      backupFromBackup: await from({ tab: 'more', backup: true }, () => openBackupBox('m-phone')),
      moreFromRecover: await from({ tab: 'more', recover: true }, () => openMoreBox('m-ai')),
      backupFromRecover: await from({ tab: 'more', recover: true }, () => openBackupBox('m-recovery')),
      pairingNotSolo: await from({ tab: 'lib' }, () => openPairing()),
      pairingSolo: await from({ tab: 'lib' }, () => { globalThis.__setSolo(true); return openPairing() }),
    }))
"""


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneScreensTest(unittest.TestCase):
    def test_the_facts_of_a_paired_phone_reach_every_pc_state(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + FACTS))
        for c in out['cases']:
            self.assertEqual(c['got'], c['want'], c['name'])
        self.assertEqual(sorted({c['want']['id'] for c in out['cases']}), sorted(out['pcStates']))
        # by design: a stored last access always has its time
        self.assertEqual(out['unmapped'], ['PH7 in a phone browser, last access unknown'])

    def test_the_facts_of_a_phone_without_a_pc_reach_every_solo_state(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + FACTS))
        for c in out['soloCases']:
            self.assertEqual(c['got'], c['want'], c['name'])
        self.assertEqual(sorted({c['want']['id'] for c in out['soloCases']}), sorted(out['soloStates']))
        s = out['solo']
        self.assertEqual(s['beforeFirstRound'], 'connecting')         # no state says Backed up before a round has ended
        self.assertEqual(s['expiredBeforeStart'], 'connecting')       # the start renews an expired token first
        self.assertEqual(s['failedRound'], 'unreachable')             # Backed up only after a round that worked
        self.assertEqual(s['failedChecked'], '')
        self.assertEqual(s['neverSignedIn'], 'solo-local')
        self.assertEqual(s['refusedAfterStart'], 'sign-in-again')

    def test_sign_in_access_times_and_unpair_words_follow_the_rules(self):
        r = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + FACTS))['rules']
        self.assertEqual(r['beforeFirstRead'], 'connecting')         # no sign-in asked before the first read finishes
        self.assertEqual(r['refusedConfirmed'], 'sign-in-again')     # Google refused the confirmed account's token
        self.assertEqual(r['refusedFresh'], 'connect')               # a new pairing never confirmed an account
        self.assertEqual(r['expiredToken'], 'sign-in-again')
        self.assertEqual(r['offlineAndPaused'], 'offline')           # Wi-Fi wait needs a network
        self.assertEqual((r['sinceExpired'], r['sinceRemoved'], r['sinceYesterday']), ('14:02', '15:05', '30 Oct 15:05'))
        self.assertFalse(r['neverHadAccess'])
        self.assertEqual(r['words'], ['', "1 edit hasn't reached your PC yet. If you unpair now, it never will.",
                                      "3 edits haven't reached your PC yet. If you unpair now, they never will."])
        self.assertEqual(r['edits'], [2, 4])                         # sent edits count only while the PC refuses access

    def test_the_journal_tells_its_watchers_after_every_change(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + WATCH))
        self.assertEqual(out['seen'], ['load', 'add', 'add the same', 'saveChat', 'dropQueuedChat', 'add a note',
                                       'dropQueuedNote', 'add a link', 'amendLink', 'dropQueuedLink', 'flush', 'prune',
                                       'add a canvas change', 'canvasResult', 'pruneCanvas', 'requeue', 'merge'])

    def test_back_and_the_box_openers_know_backup_and_phones(self):
        back = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            import { parentHash } from './web/src/mobile/back.ts'
            console.log(JSON.stringify([parentHash({ tab: 'more', backup: true }), parentHash({ tab: 'cap', imp: true }), parentHash({ tab: 'more' }),
              parentHash({ tab: 'more', recover: true })]))
        """))
        self.assertEqual(back, ['#/more', '#/cap', '#/lib', '#/backup'])      # Import goes back to Add; recovery to Backup & phones
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + OPEN))
        self.assertEqual(out, {'moreFromLibrary': ['#/more'], 'moreFromMore': [], 'moreFromImport': ['#/more'],
                               'moreFromBackup': ['#/more'], 'backupFromMore': ['#/backup'], 'backupFromBackup': [],
                               'moreFromRecover': ['#/more'], 'backupFromRecover': ['#/backup'],
                               'pairingNotSolo': ['#/more'], 'pairingSolo': ['#/backup']})

    def test_the_screens_show_the_one_status(self):
        state, shell, strip, more = source('state.svelte.ts'), source('Mobile.svelte'), source('OwnerLine.svelte'), source('screens/More.svelte')
        backup, card = source('screens/Backup.svelte'), source('StatusCard.svelte')
        self.assertIn("case 'backup': return backupHere ? { tab: 'more', backup: true } : { tab: 'more' }", state)
        self.assertIn('export const backupHere = !!mirrorSource\n', state)
        self.assertIn('mirrorSource.changes.watch(() => { void measurePend() })', state)
        self.assertEqual(state.count("location.replace(location.pathname + '#/backup')"), 2)    # pairFrom and useWithoutPc
        self.assertIn("location.pathname + '#/backup'", source('mirror/pairing.ts'))
        self.assertIn("const tag = $derived(r.backup ? t('shell.pageTag.backup') : r.recover ? t('shell.pageTag.recover') : t('shell.settings'))", source('PageKeys.svelte'))
        self.assertEqual([english('shell.pageTag.backup'), english('shell.pageTag.recover'), english('shell.settings')], ['Backup', 'Recover', 'Settings'])
        self.assertIn('{:else if r.backup}\n      <Backup scroller={main} />', shell)
        self.assertIn("if (st?.lamp) return t('shell.lamp.joined', { where: L, text: st.lamp })", shell)
        self.assertEqual(english('shell.lamp.joined'), '{where} · {text}')
        self.assertIn('if (st && ACCESS_STATES.includes(st.id)) return { lamp: phoneState(phoneFacts()!).lamp as DriveLamp, ok: false, why: st.text }', state)
        self.assertIn('return f && phoneState(f, phoneWords)', state)
        self.assertIn('const owner = $derived(!here && st?.strip ? st : null)', strip)
        self.assertIn('href="#/backup"', strip)
        self.assertIn('{#if m}\n    <StatusCard />', more)
        self.assertFalse((ROOT / 'web/src/mobile/SetupList.svelte').exists())     # its rows are the group rows now
        for gone in ('id="m-pair-setup"', '<h3>Google Drive<', 'id="m-recovery"', 'Retry access and library', 'let pend',
                     '<h3>Without a PC', '<PhoneRecovery', 'changesDb'):
            self.assertNotIn(gone, more)
        for kept in ('id="m-conn"', "kicker={t('settings.pair.pc')}", "title={t('settings.group.pc')}", "title={t('settings.sync.wifi')}", 'id="m-ai"', 'id="m-desktop"', 'href="#/recover"'):
            self.assertIn(kept, more)
        self.assertEqual([english('settings.pair.pc'), english('settings.group.pc'), english('settings.sync.wifi')], ['Pair with your PC', 'Your PC', 'Wi-Fi only'])
        self.assertIn('href="#/backup"', card)
        self.assertIn('look="hero"', card)
        self.assertNotIn('detail=', card)                                  # the card never shows the detail
        order = [backup.index(f'id="{i}"') for i in ('m-backup-status', 'm-pair-setup', 'm-conn', 'm-phone', 'm-pair', 'm-recovery')]
        self.assertEqual(order, sorted(order))
        unpair = backup[backup.index('async function unpair()'):]
        unpair = unpair[:unpair.index('\n  }\n')]
        self.assertLess(unpair.index('await stopCloudWork()'), unpair.index('await m?.dropPhoneRecord()'))
        self.assertLess(unpair.index('await m?.dropPhoneRecord()'), unpair.index('unpairPhone()'))
        self.assertNotIn('changesDb', unpair)                              # Unpair keeps the journal (plan P10)
        remove = backup[backup.index('async function removeSolo()'):]
        remove = remove[:remove.index('\n  }\n')]
        self.assertLess(remove.index('await stopCloudWork()'), remove.index('unpairPhone()'))
        self.assertIn('await Promise.all([wipe(), changesDb.clear()])', remove)   # Remove takes the phone's own library

    def test_the_phone_without_a_pc_has_backup_and_recover(self):
        state, shell, backup = source('state.svelte.ts'), source('Mobile.svelte'), source('screens/Backup.svelte')
        recovery, recover = source('PhoneRecovery.svelte'), source('screens/Recover.svelte')
        self.assertIn("case 'recover': return recoverHere ? { tab: 'more', recover: true } : { tab: 'more' }", state)
        self.assertIn('export const recoverHere = solo || (!mirrorSource && (isApp || devSolo))', state)
        self.assertIn('if (mirrorSource?.solo) phone.round = mirrorSource.round', state)
        self.assertIn('{:else if r.recover}\n      <Recover scroller={main} />', shell)
        solo = backup[backup.index('{:else if m}'):]
        order = [solo.index(f'id="{i}"') for i in ('m-backup-status', 'm-conn', 'm-phone', 'm-pair')]
        self.assertEqual(order, sorted(order))
        self.assertGreater(solo.index('<PhoneRecovery'), order[-1])
        self.assertIn('href="#/recover"', recovery)
        self.assertIn('recoveryFact(', recovery)
        self.assertNotIn('discoverPhoneRecovery', recovery)              # finding a backup is Recover's
        self.assertIn('discoverPhoneRecovery(', recover)
        self.assertIn('clock(setup.record.header.created * 1000, Date.now(), phoneLocale())', recover)   # setups by when they were made, no key shown
        self.assertIn("t('recovery.state.setupAt', { when: clock(", recover)
        self.assertEqual(english('recovery.state.setupAt'), 'Set up {when}')
        self.assertNotIn('.sort(', recover)                              # newest first, as discoverPhoneRecovery returns them
        self.assertIn("location.replace(location.pathname + '#/backup')", recover)


if __name__ == '__main__':
    unittest.main()
