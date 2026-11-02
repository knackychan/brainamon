"""Keep this phone's library after its Drive key was lost (docs/superpowers/plans/2026-10-29-phone-reconnect.md).
The names, formats and batch sealing the phone shares with Python are pinned by tests/fixtures/phone_reconnect.json
and checked from both sides; the phone's read-only eligibility check, its commit and its gates run under Node
(type stripping) with the same shims as tests/test_phone_solo.py."""
import base64
import hashlib
import json
import unittest
from pathlib import Path

from tests import test_phone_js

ROOT = Path(__file__).resolve().parents[1]
FX = json.loads((ROOT / 'tests' / 'fixtures' / 'phone_reconnect.json').read_text(encoding='utf-8'))

# the browser shims of tests/test_phone_solo.py plus an in-memory IndexedDB (store.ts) and the phone modules
PRELUDE = test_phone_js.TS_RESOLVE + r"""
    import fs from 'node:fs'
    const mem = new Map(), session = new Map()
    globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v), removeItem: k => mem.delete(k) }
    globalThis.sessionStorage = { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, v), removeItem: k => session.delete(k) }
    globalThis.window = new EventTarget(); globalThis.document = new EventTarget()
    Object.defineProperty(navigator, 'onLine', { value: true })
    Object.defineProperty(navigator, 'connection', { value: Object.assign(new EventTarget(), { type: 'wifi' }) })
    const S = await import('./web/src/mobile/store.ts')
    const rows = new Map(), store = new Map()
    let nextId = 1
    S.changes.all = async () => structuredClone([...rows.values()])
    S.changes.add = async e => { const id = nextId++; rows.set(id, structuredClone({ ...e, id })); return id }
    S.changes.put = async e => { rows.set(e.id, structuredClone(e)) }
    S.changes.del = async id => { rows.delete(id) }
    S.kv.get = async k => structuredClone(store.get(k))
    S.kv.set = async (k, v) => { store.set(k, structuredClone(v)) }
    S.kv.del = async k => { store.delete(k) }
    const P = await import('./web/src/mobile/mirror/pairing.ts')
    const { secrets } = await import('./web/src/mobile/native.ts')
    const { MirrorKey, CHANGE_PREFIX } = await import('./web/src/mobile/mirror/crypto.ts')
    const { CHANGE_FORMAT, Changes } = await import('./web/src/mobile/mirror/changes.ts')
    const R = await import('./web/src/mobile/mirror/phone-reconnect.ts')
    const fx = JSON.parse(fs.readFileSync('tests/fixtures/phone_reconnect.json', 'utf8'))
    const enc = new TextEncoder()
    const blob = Uint8Array.from(Buffer.from(fx.batch.blob, 'base64'))
    // a journal with the fixture batch sent under the fixture key, and one queued edit
    async function journalOf(prefixName = fx.batch.name) {
      rows.clear()
      const j = new Changes()
      await j.add({ op: 'link', uid: 'ef'.repeat(16), url: 'https://www.youtube.com/watch?v=reconnect1', note: 'kept on the phone', category: '' })
      await j.add({ op: 'fav', uid: 'ef'.repeat(16), on: true })
      for (const e of j.list) { e.state = 'sent'; e.sentAt = fx.batch.at; e.chg = prefixName; await S.changes.put(e) }
      await j.add({ op: 'edit', uid: 'ef'.repeat(16), fields: { tags: 'queued' }, was: {} })
      return j
    }
    // a stand-in Drive for the read-only check (the real Drive boundary has its own test)
    function driveOf(files) {
      return { list: async () => [...files].map(([id, f]) => ({ id, name: f.name, size: f.data.length })),
               getRecovered: async id => { if (!files.has(id)) throw new Error('unlisted'); return Uint8Array.from(files.get(id).data) } }
    }
"""


def node(script: str, timeout: float = 120) -> dict:
    return json.loads(test_phone_js.node(PRELUDE + script, timeout))


class ParityTest(unittest.TestCase):
    def test_python_sees_the_phone_names_and_formats_the_fixture_pins(self):
        from library import mirror, recovery as R
        from server import recovery as SR
        k = mirror.MirrorKey(base64.urlsafe_b64decode(FX['key'] + '='))
        self.assertEqual((k.text(), k.fingerprint), (FX['key'], FX['fingerprint']))
        self.assertEqual((k.name('phone-backup'), k.name('phone-recovery')), (FX['backup_library'], FX['recovery_library']))
        self.assertEqual('solo-' + FX['backup_library'] + '-', FX['solo_prefix'])
        plain = k.open(FX['batch']['name'], base64.b64decode(FX['batch']['blob']))
        self.assertEqual(plain.decode('utf-8'), FX['batch']['plain'])
        self.assertEqual(hashlib.sha256(plain).hexdigest(), FX['batch']['sig'])
        doc = json.loads(plain)
        self.assertEqual((doc['format'], doc['at'], len(doc['changes'])), (mirror.CHANGE_FORMAT, FX['batch']['at'], FX['batch']['n']))
        self.assertEqual(FX['change_format'], mirror.CHANGE_FORMAT)
        with self.assertRaises(mirror.MirrorKeyError):
            mirror.MirrorKey.generate().open(FX['batch']['name'], base64.b64decode(FX['batch']['blob']))
        # every material the phone's code field takes opens the same key on the PC
        for name, material in FX['materials'].items():
            with self.subTest(material=name):
                self.assertEqual(R.import_key(material)[0].master, k.master)
        self.assertEqual(R.PHONE_FORMAT, FX['formats']['phone_export'])
        with self.assertRaisesRegex(R.RecoveryError, 'standalone phone backup'):
            R.import_key(json.dumps({'format': FX['formats']['phone_kit'], 'version': 1}))
        # the PC never takes a solo file into its intake, and its listings skip the phone's names
        self.assertFalse(mirror.is_change(FX['batch']['name']))
        self.assertRegex(FX['batch']['name'], FX['names']['solo'])
        self.assertRegex('vi-phone-recovery-' + FX['recovery_library'] + '-' + 'b' * 32 + '.json', FX['names']['phone_recovery'])
        self.assertRegex('chg-' + 'c' * 32, FX['names']['legacy_change'])
        src = (ROOT / 'server' / 'recovery.py').read_text(encoding='utf-8')
        self.assertIn(r"re.fullmatch(r'solo-[0-9a-f]{32}-[0-9a-f]{32}', f['name'])", src)
        self.assertIn(r"re.fullmatch(r'vi-phone-recovery-[0-9a-f]{32}-[0-9a-f]{32}\.json', f['name'])", src)
        listing = [{'id': '1', 'name': FX['batch']['name'], 'size': 1},
                   {'id': '2', 'name': 'vi-phone-recovery-' + FX['recovery_library'] + '-' + 'b' * 32 + '.json', 'size': 1}]
        self.assertFalse(any(f['name'].startswith(R.PREFIX) for f in listing))
        identity = SR.RecoveryService._reconnect_identity(None, None, k, 'sample@example.com', None, listing)
        self.assertEqual(identity, {'library': None, 'owner_id': '', 'owner': None})


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneSideTest(unittest.TestCase):
    def test_the_phone_derives_the_same_names_and_opens_the_same_batch(self):
        out = node(r"""
            const key = await MirrorKey.fromText(fx.key)
            const plain = await key.open(fx.batch.name, blob)
            const materials = {}
            for (const [k, v] of Object.entries(fx.materials)) materials[k] = await R.keyFromMaterial(v)
            let kitRefused = '', wrong = ''
            try { await R.keyFromMaterial(JSON.stringify({ format: fx.formats.phone_kit, version: 1 })) } catch (e) { kitRefused = e.message }
            try { await R.keyFromMaterial(JSON.stringify({ format: fx.formats.phone_export, version: 1, key: fx.key, fingerprint: 'ffffffffffff' })) } catch (e) { wrong = e.message }
            console.log(JSON.stringify({ fingerprint: key.fingerprint, backup: await key.name('phone-backup'), recovery: await key.name('phone-recovery'),
              prefix: await key.soloPrefix(), plain: Buffer.from(plain).toString(), sig: await R.sha256hex(plain), solo: R.SOLO_NAME.source,
              materials, kitRefused, wrong, format: CHANGE_FORMAT }))
        """)
        self.assertEqual((out['fingerprint'], out['backup'], out['recovery'], out['prefix']),
                         (FX['fingerprint'], FX['backup_library'], FX['recovery_library'], FX['solo_prefix']))
        self.assertEqual((out['plain'], out['sig'], out['solo'], out['format']), (FX['batch']['plain'], FX['batch']['sig'], FX['names']['solo'], FX['change_format']))
        self.assertEqual(out['materials'], {name: FX['key'] for name in FX['materials']})
        self.assertIn('File under Unlock with', out['kitRefused'])
        self.assertIn('fingerprint', out['wrong'])

    def test_eligibility_reads_only_and_names_every_refusal(self):
        out = node(r"""
            const key = await MirrorKey.fromText(fx.key)
            const other = P.newKeyText()                    // the key this phone made after it lost the backup's key
            await P.startSolo(other)
            const otherPrefix = await (await MirrorKey.fromText(other)).soloPrefix()
            const files = new Map([['f1', { name: fx.batch.name, data: blob }]])
            const drive = driveOf(files)
            const journal = await journalOf()
            const reason = async () => (await R.reconnectCheck(key, drive, journal)).reason
            const out = {}
            out.journal = await R.reconnectCheck(key, drive, journal)           // no record yet: the journal proves it
            const rec = { fingerprint: key.fingerprint, name: fx.batch.name, id: 'f1', at: fx.batch.at, n: 2, sig: fx.batch.sig }
            await S.kv.set(R.PUBLISH_KEY, { [key.fingerprint]: rec })
            out.record = await R.reconnectCheck(key, drive, journal)
            for (const [name, patch] of [['sig', { sig: 'f'.repeat(64) }], ['id', { id: 'f9' }], ['at', { at: rec.at + 1 }], ['n', { n: 3 }]]) {
              await S.kv.set(R.PUBLISH_KEY, { [key.fingerprint]: { ...rec, ...patch } })
              out[name] = await reason()
            }
            await S.kv.set(R.PUBLISH_KEY, { [other.slice(0, 12)]: { ...rec, fingerprint: 'other' } })   // another key's record is ignored
            out.otherRecord = await reason()
            await S.kv.set(R.PUBLISH_KEY, {})
            files.delete('f1'); out.missing = await reason(); files.set('f1', { name: fx.batch.name, data: blob })
            const stranger = await MirrorKey.fromText(P.newKeyText())
            files.set('f1', { name: fx.batch.name, data: await stranger.seal(fx.batch.name, enc.encode(fx.batch.plain)) })
            out.wrongKey = await reason(); files.set('f1', { name: fx.batch.name, data: blob })
            files.set('f1', { name: fx.batch.name, data: await key.seal(fx.batch.name, enc.encode(JSON.stringify({ format: 1, at: fx.batch.at + 5, changes: [] }))) })
            out.wrongAt = await reason(); files.set('f1', { name: fx.batch.name, data: blob })
            // legacy chg- batch: eligible when it opens with the key
            const legacy = 'chg-' + 'c'.repeat(32)
            files.set('l1', { name: legacy, data: await key.seal(legacy, enc.encode(fx.batch.plain)) })
            const legacyJournal = await journalOf(legacy)
            out.legacy = (await R.reconnectCheck(key, drive, legacyJournal)).reason
            // the journal only knows batches under another key: other_library; nothing sent at all: no_upload
            const strayJournal = await journalOf(otherPrefix + 'b'.repeat(32))
            out.other = (await R.reconnectCheck(key, drive, strayJournal)).reason
            rows.clear()
            const fresh = new Changes(); await fresh.add({ op: 'fav', uid: 'ef'.repeat(16), on: true })
            out.none = (await R.reconnectCheck(key, drive, fresh)).reason
            // paired with a PC
            secrets.set('bp-pair', JSON.stringify({ v: 2, k: fx.key, f: fx.fingerprint, c: '', e: 'pc@example.com', ai: {}, at: 1, l: 'A'.repeat(122) }))
            await P.validateStoredPairing()
            out.paired = await reason()
            secrets.set('bp-pair', null)
            out.unpaired = await reason()
            out.journalIntact = journal.list.map(e => [e.op, e.state, e.chg ?? null])
            out.strays = R.strays(strayJournal.list, otherPrefix).length
            out.latest = R.latestBatch(journal.list, await key.soloPrefix())
            console.log(JSON.stringify(out))
        """)
        self.assertEqual(out['journal'], {'ok': True, 'reason': 'eligible', 'message': out['journal']['message'], 'batch': {'name': FX['batch']['name'], 'at': FX['batch']['at'], 'n': 2, 'id': 'f1'}})
        self.assertIn('matches its latest backup', out['journal']['message'])
        self.assertEqual(out['record']['batch'], {'fingerprint': FX['fingerprint'], 'name': FX['batch']['name'], 'id': 'f1', 'at': FX['batch']['at'], 'n': 2, 'sig': FX['batch']['sig']})
        self.assertEqual({k: out[k] for k in ('sig', 'id', 'at', 'n', 'missing', 'wrongKey', 'wrongAt')}, dict.fromkeys(('sig', 'id', 'at', 'n', 'missing', 'wrongKey', 'wrongAt'), 'not_latest'))
        self.assertEqual((out['otherRecord'], out['legacy'], out['other'], out['none'], out['paired'], out['unpaired']),
                         ('eligible', 'eligible', 'other_library', 'no_upload', 'paired_pc', 'not_connected'))
        self.assertEqual(out['journalIntact'], [['link', 'sent', FX['batch']['name']], ['fav', 'sent', FX['batch']['name']], ['edit', 'queued', None]])
        self.assertEqual((out['strays'], out['latest']), (2, {'name': FX['batch']['name'], 'at': FX['batch']['at'], 'n': 2}))

    def test_the_drive_reads_one_recovered_backup_file_and_nothing_else(self):
        out = node(r"""
            const { Drive } = await import('./web/src/mobile/mirror/drive.ts')
            const key = await MirrorKey.fromText(fx.key), stranger = await MirrorKey.fromText(P.newKeyText())
            await P.startSolo(P.newKeyText())
            const files = new Map([['f1', { name: fx.batch.name, data: blob }],
              ['s1', { name: (await stranger.soloPrefix()) + 'd'.repeat(32), data: await stranger.seal((await stranger.soloPrefix()) + 'd'.repeat(32), enc.encode('{}')) }],
              ['v1', { name: 'vi-phone-recovery-' + fx.recovery_library + '-' + 'b'.repeat(32) + '.json', data: enc.encode('{}') }]])
            let writes = 0
            globalThis.fetch = async (url, init = {}) => {
              if (init.method === 'POST' || init.method === 'DELETE') { writes++; return new Response('', { status: 500 }) }
              if (url.includes('/files?')) return Response.json({ files: [...files].map(([id, f]) => ({ id, name: f.name, size: f.data.length })) })
              const id = decodeURIComponent(new URL(url).pathname.split('/').pop())
              return new Response(files.get(id).data)
            }
            const drive = new Drive(P.GOOGLE_DRIVE, () => 'synthetic', () => {})
            const out = { refused: {} }
            try { await drive.getRecovered('f1', key); out.refused.unlisted = 'read' } catch (e) { out.refused.unlisted = e.message }
            await drive.list()
            out.read = Buffer.from(await drive.getRecovered('f1', key)).toString('base64') === fx.batch.blob
            for (const [name, call] of [['stranger', () => drive.getRecovered('s1', key)], ['recovery', () => drive.getRecovered('v1', key)],
                                        ['plainGet', () => drive.get('f1')], ['unknownId', () => drive.getRecovered('f9', key)]]) {
              try { await call(); out.refused[name] = 'read' } catch (e) { out.refused[name] = e.message }
            }
            secrets.set('bp-pair', JSON.stringify({ v: 2, k: fx.key, f: fx.fingerprint, c: '', e: 'pc@example.com', ai: {}, at: 1, l: 'A'.repeat(122) }))
            await P.validateStoredPairing()
            try { await drive.getRecovered('f1', key); out.refused.paired = 'read' } catch (e) { out.refused.paired = e.message }
            out.writes = writes
            console.log(JSON.stringify(out))
        """)
        self.assertTrue(out['read'])
        self.assertEqual(out['writes'], 0)
        for name in ('unlisted', 'stranger', 'recovery', 'unknownId', 'paired'):
            self.assertNotEqual(out['refused'][name], 'read', name)
        self.assertNotEqual(out['refused']['plainGet'], 'read')          # the existing boundary: another key's file never through get()

    def test_each_material_keeps_the_phone_and_writes_nothing_to_drive(self):
        out = node(r"""
            const { Drive } = await import('./web/src/mobile/mirror/drive.ts')
            const E = await import('./web/src/mobile/mirror/recovery-envelope.ts')
            const key = await MirrorKey.fromText(fx.key)
            const account = 'sample@example.com'
            const kit = await E.createPhoneKit(fx.key, 'synthetic reconnect passphrase', account)
            const files = new Map([['f1', { name: fx.batch.name, data: blob }]])
            let writes = 0
            globalThis.fetch = async (url, init = {}) => {
              if (init.method === 'POST' || init.method === 'DELETE') { writes++; return new Response('', { status: 500 }) }
              if (url.includes('/files?')) return Response.json({ files: [...files].map(([id, f]) => ({ id, name: f.name, size: f.data.length })) })
              return new Response(files.get(decodeURIComponent(new URL(url).pathname.split('/').pop())).data)
            }
            const methods = [['raw', await R.keyFromMaterial(fx.materials.raw), undefined], ['pairing', await R.keyFromMaterial(fx.materials.pairing_url), undefined],
              ['export', await R.keyFromMaterial(fx.materials.phone_export), undefined],
              ['kit', await E.unlockPhoneEnvelope(kit.record, account, { secret: kit.secret }), kit],
              ['passphrase', await E.unlockPhoneEnvelope(kit.record, account, { password: 'synthetic reconnect passphrase' }), undefined]]
            const out = {}
            for (const [name, keyText, usedKit] of methods) {
              // the phone after the loss: a new solo key, the AI key typed on the phone, Drive connected to the account
              const lost = P.newKeyText()
              await P.startSolo(lost)
              const p = P.pairing(); P.setAiKeys(p, { anthropic: 'sk-ant-synthetic' }); P.confirmAccount(p, account)
              secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
              const lostPrefix = await (await MirrorKey.fromText(lost)).soloPrefix()
              rows.clear(); store.clear()
              const journal = await journalOf()
              // one change already backed up under the lost key: a stray that must go again
              await journal.add({ op: 'fav', uid: 'ab'.repeat(16), on: true })
              const stray = journal.list[journal.list.length - 1]; stray.state = 'sent'; stray.sentAt = fx.batch.at + 1000; stray.chg = lostPrefix + 'b'.repeat(32); await S.changes.put(stray)
              await S.kv.set(R.PUBLISH_KEY, { lost: { fingerprint: 'lost', name: stray.chg, id: 'x', at: stray.sentAt, n: 1, sig: 'f'.repeat(64) } })
              await S.kv.set('rows', [{ id: -1, url: 'https://www.youtube.com/watch?v=reconnect1' }])
              const drive = new Drive(P.GOOGLE_DRIVE, () => 'synthetic', () => {})
              await R.reconnectPhone(P.pairing(), drive, journal, keyText, account, usedKit)
              const after = P.pairing()
              const backups = [...mem.keys()].filter(k => k.startsWith('bp-pair-before-reconnect-'))
              out[name] = { k: after.k, f: after.f, g: after.g, e: after.e, solo: !!after.solo, ai: after.ai, recovery: after.recovery ? [after.recovery.verified, after.recovery.kit.record.header.library] : null,
                token: P.token(after) !== null, backups: backups.length, backedUp: JSON.parse(mem.get(backups[0])).k === lost,
                journal: journal.list.map(e => [e.op, e.state, e.chg ?? null]), rows: (await S.kv.get('rows')).length,
                publish: Object.keys(await S.kv.get(R.PUBLISH_KEY)), marker: (await S.kv.get(R.STRAYS_KEY)) ?? null,
                oldDrive: await drive.list().then(() => 'read', e => e.constructor.name) }
              mem.delete(backups[0])
            }
            out.writes = writes
            console.log(JSON.stringify(out))
        """)
        self.assertEqual(out.pop('writes'), 0)
        for name, got in out.items():
            with self.subTest(method=name):
                self.assertEqual((got['k'], got['f'], got['g'], got['e'], got['solo'], got['ai'], got['token']),
                                 (FX['key'], FX['fingerprint'], 'sample@example.com', 'sample@example.com', True, {'anthropic': 'sk-ant-synthetic'}, True))
                self.assertEqual(got['recovery'], [False, FX['recovery_library']] if name == 'kit' else None)
                self.assertEqual((got['backups'], got['backedUp'], got['rows']), (1, True, 1))
                self.assertEqual(got['journal'], [['link', 'sent', FX['batch']['name']], ['fav', 'sent', FX['batch']['name']], ['edit', 'queued', None], ['fav', 'queued', None]])
                self.assertEqual(got['publish'], ['lost'])                      # the lost key's record is kept, untouched
                self.assertIsNone(got['marker'])                                 # the strays marker is gone after success
                self.assertEqual(got['oldDrive'], 'LicenseRequired')           # the old Drive instance refuses: its pairing identity changed

    def test_reconnect_refuses_before_writing_and_fails_closed_after(self):
        out = node(r"""
            const { Drive } = await import('./web/src/mobile/mirror/drive.ts')
            const key = await MirrorKey.fromText(fx.key), account = 'sample@example.com'
            const files = new Map([['f1', { name: fx.batch.name, data: blob }]])
            globalThis.fetch = async (url, init = {}) => {
              if (init.method) throw new Error('reconnect wrote Drive')
              if (url.includes('/files?')) return Response.json({ files: [...files].map(([id, f]) => ({ id, name: f.name, size: f.data.length })) })
              return new Response(files.get(decodeURIComponent(new URL(url).pathname.split('/').pop())).data)
            }
            const set = secrets.set.bind(secrets), put = S.changes.put
            async function phone() {
              for (const k of [...mem.keys()].filter(k => k.startsWith('bp-pair-before-reconnect-'))) secrets.set(k, null)
              const lost = P.newKeyText()
              await P.startSolo(lost); P.confirmAccount(P.pairing(), account)
              secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
              rows.clear(); store.clear()
              const journal = await journalOf()
              const stray = journal.list[2]; stray.state = 'sent'; stray.sentAt = fx.batch.at + 1000; stray.chg = (await (await MirrorKey.fromText(lost)).soloPrefix()) + 'b'.repeat(32); await S.changes.put(stray)
              return { lost, journal, drive: new Drive(P.GOOGLE_DRIVE, () => 'synthetic', () => {}) }
            }
            const state = () => ({ k: P.pairing()?.k ?? null, backups: [...mem.keys()].filter(k => k.startsWith('bp-pair-before-reconnect-')).length })
            const out = {}
            // refusals before the first write
            let { lost, journal, drive } = await phone()
            for (const [name, call] of [
              ['mismatch', () => R.reconnectPhone(P.pairing(), drive, journal, key.fingerprint.repeat(4).slice(0, 43), account)],
              ['account', () => R.reconnectPhone(P.pairing(), drive, journal, fx.key, 'other@example.com')],
              ['shortKey', () => R.reconnectPhone(P.pairing(), drive, journal, 'AAAA', account)]]) {
              try { await call(); out[name] = 'ran' } catch (e) { out[name] = e.message }
            }
            files.delete('f1')
            try { await R.reconnectPhone(P.pairing(), drive, journal, fx.key, account); out.notLatest = 'ran' } catch (e) { out.notLatest = e.message }
            files.set('f1', { name: fx.batch.name, data: blob })
            out.untouched = { ...state(), lost: P.pairing().k === lost, stray: journal.list[2].state }
            // the pairing changes during the check (another tap won): refuse before writing
            const swap = { ...driveOf(files), list: async () => { P.confirmAccount(P.pairing(), 'other@example.com'); return driveOf(files).list() } }
            ;({ lost, journal, drive } = await phone())
            try { await R.reconnectPhone(P.pairing(), swap, journal, fx.key, account); out.swapped = 'ran' } catch (e) { out.swapped = e.message }
            out.afterSwap = state().backups
            // injected failures: backup write, pairing write, journal write
            const failures = {}
            for (const point of ['backup', 'pairing', 'journal']) {
              ;({ lost, journal, drive } = await phone())
              secrets.set = (k, v) => { if ((point === 'backup' && k.startsWith('bp-pair-before-reconnect-')) || (point === 'pairing' && k === 'bp-pair')) throw new Error('synthetic storage failure'); return set(k, v) }
              S.changes.put = async e => { if (point === 'journal') throw new Error('synthetic journal failure'); return put(e) }
              let message = 'ran'
              try { await R.reconnectPhone(P.pairing(), drive, journal, fx.key, account) } catch (e) { message = e.message }
              secrets.set = set; S.changes.put = put
              const s = state()
              // restart: a new journal and what MirrorSource.ready does on a solo start (finishReconnect with the key in use)
              const again = new Changes()
              const requeued = await R.finishReconnect(again, await MirrorKey.fromText(P.pairing().k))
              failures[point] = { message, k: s.k === fx.key ? 'recovered' : s.k === lost ? 'lost' : 'other', backups: s.backups, requeued,
                                  marker: (await S.kv.get(R.STRAYS_KEY)) ?? null, states: again.list.map(e => e.state),
                                  retry: s.k === lost ? await R.reconnectPhone(P.pairing(), new Drive(P.GOOGLE_DRIVE, () => 'synthetic', () => {}), again, fx.key, account).then(() => 'ok', e => e.message) : 'n/a',
                                  afterRetry: (await S.kv.get(R.STRAYS_KEY)) ?? null, retryStates: again.list.map(e => e.state) }
            }
            out.failures = failures
            out.busyAfter = (await import('./web/src/mobile/mirror/gate.ts')).reconnecting()
            console.log(JSON.stringify(out))
        """)
        self.assertIn('different key', out['mismatch'])            # a valid key that never backed this phone up
        self.assertIn('changed', out['account'])
        self.assertIn('32 bytes', out['shortKey'])
        self.assertIn('missing from Drive', out['notLatest'])
        self.assertEqual((out['untouched']['backups'], out['untouched']['lost'], out['untouched']['stray']), (0, True, 'sent'))
        self.assertIn('changed', out['swapped'])
        self.assertEqual(out['afterSwap'], 0)
        f = out['failures']
        self.assertEqual((f['backup']['k'], f['backup']['backups'], f['backup']['requeued'], f['backup']['marker'], f['backup']['retry']), ('lost', 0, 0, None, 'ok'))
        self.assertIn('synthetic storage failure', f['backup']['message'])
        self.assertEqual((f['pairing']['k'], f['pairing']['backups'], f['pairing']['requeued'], f['pairing']['retry']), ('lost', 1, 0, 'ok'))
        self.assertEqual(f['pairing']['marker']['to'], FX['solo_prefix'])      # left for the retry, which rewrites and clears it
        self.assertIsNone(f['pairing']['afterRetry'])
        self.assertEqual(f['pairing']['retryStates'], ['sent', 'sent', 'queued'])
        self.assertIn('interrupted', f['pairing']['message'].lower())
        self.assertEqual((f['journal']['k'], f['journal']['backups'], f['journal']['requeued'], f['journal']['marker'], f['journal']['retry']), ('recovered', 1, 1, None, 'n/a'))
        self.assertEqual(f['journal']['states'], ['sent', 'sent', 'queued'])
        self.assertIn('interrupted', f['journal']['message'].lower())
        self.assertFalse(out['busyAfter'])

    def test_reconnect_refuses_an_existing_background_cloud_change(self):
        out = node(r"""
            const G = await import('./web/src/mobile/mirror/gate.ts')
            const account = 'sample@example.com'
            await P.startSolo(P.newKeyText()); P.confirmAccount(P.pairing(), account)
            secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
            const journal = await journalOf(), before = secrets.get('bp-pair')
            const drive = driveOf(new Map([['f1', { name: fx.batch.name, data: blob }]]))
            G.beginCloudChange(); G.beginCloudChange()
            let check, message
            try {
              check = (await R.reconnectCheck(await MirrorKey.fromText(fx.key), drive, journal)).reason
              try { await R.reconnectPhone(P.pairing(), drive, journal, fx.key, account) } catch (e) { message = e.message }
            } finally { G.endCloudChange() }
            const nested = G.cloudChanging(), untouched = secrets.get('bp-pair') === before
            G.endCloudChange()
            await R.reconnectPhone(P.pairing(), drive, journal, fx.key, account)
            console.log(JSON.stringify({ check, message, nested, untouched, after: G.cloudChanging(), key: P.pairing().k }))
        """)
        self.assertEqual(out['check'], 'busy')
        self.assertIn('current sync', out['message'])
        self.assertTrue(out['nested'])
        self.assertTrue(out['untouched'])
        self.assertFalse(out['after'])
        self.assertEqual(out['key'], FX['key'])

    def test_retry_after_a_journal_failure_keeps_the_original_repair_marker(self):
        out = node(r"""
            const account = 'sample@example.com'
            const lost = P.newKeyText()
            await P.startSolo(lost); P.confirmAccount(P.pairing(), account)
            secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
            const journal = await journalOf()
            const stray = journal.list[2]
            stray.state = 'sent'; stray.sentAt = fx.batch.at + 1
            stray.chg = (await (await MirrorKey.fromText(lost)).soloPrefix()) + 'b'.repeat(32)
            await S.changes.put(stray)
            const files = new Map([['f1', { name: fx.batch.name, data: blob }]])
            const put = S.changes.put
            S.changes.put = async () => { throw new Error('synthetic journal failure') }
            let message = ''
            try { await R.reconnectPhone(P.pairing(), driveOf(files), journal, fx.key, account) } catch (e) { message = e.message }
            S.changes.put = put
            const failed = { memory: stray.state, disk: (await S.changes.all())[2].state }
            await R.reconnectPhone(P.pairing(), driveOf(files), journal, fx.key, account)
            const after = (await S.changes.all()).map(e => [e.op, e.state, e.chg ?? null])
            await R.reconnectPhone(P.pairing(), driveOf(files), journal, fx.key, account)
            console.log(JSON.stringify({ message, failed, after, repeat: (await S.changes.all()).map(e => [e.op, e.state, e.chg ?? null]), marker: (await S.kv.get(R.STRAYS_KEY)) ?? null }))
        """)
        self.assertIn('interrupted', out['message'].lower())
        self.assertEqual(out['failed'], {'memory': 'sent', 'disk': 'sent'})
        self.assertEqual(out['after'], [['link', 'sent', FX['batch']['name']], ['fav', 'sent', FX['batch']['name']], ['edit', 'queued', None]])
        self.assertEqual(out['repeat'], out['after'])
        self.assertIsNone(out['marker'])

    def test_conflicting_local_changes_refuse_while_reconnecting(self):
        out = node(r"""
            const G = await import('./web/src/mobile/mirror/gate.ts')
            const PR = await import('./web/src/mobile/mirror/phone-recovery.ts')
            const key = await MirrorKey.fromText(fx.key), account = 'sample@example.com'
            await P.startSolo(P.newKeyText()); P.confirmAccount(P.pairing(), account)
            secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
            const journal = await journalOf()
            let release
            const held = new Promise(r => { release = r })
            const slow = { list: async () => { await held; return [{ id: 'f1', name: fx.batch.name, size: blob.length }] }, getRecovered: async () => blob }
            const running = R.reconnectPhone(P.pairing(), slow, journal, fx.key, account)
            await new Promise(r => setTimeout(r, 20))
            const results = {}
            for (const [name, call] of [['gate', () => G.reconnectGate()], ['forget', () => P.forget()], ['disconnect', () => P.disconnectDrive(P.pairing())],
                                        ['startSolo', () => P.startSolo(P.newKeyText())], ['prepare', () => PR.preparePhoneRecovery(P.pairing(), slow, 'x'.repeat(12), 'x'.repeat(12))],
                                        ['verify', () => PR.verifyPhoneRecovery(P.pairing(), slow, '{}')], ['again', () => R.reconnectPhone(P.pairing(), slow, journal, fx.key, account)]]) {
              try { await call(); results[name] = 'ran' } catch (e) { results[name] = e.message }
            }
            results.during = G.reconnecting()
            release()
            await running
            results.after = G.reconnecting()
            results.k = P.pairing().k
            try { G.reconnectGate(); results.free = 'free' } catch (e) { results.free = e.message }
            console.log(JSON.stringify({ results, busy: G.RECONNECT_BUSY }))
        """)
        r, busy = out['results'], out['busy']
        for name in ('gate', 'forget', 'disconnect', 'startSolo', 'prepare', 'verify', 'again'):
            self.assertEqual(r[name], busy, name)
        self.assertEqual((r['during'], r['after'], r['k'], r['free']), (True, False, FX['key'], 'free'))

    def test_the_screens_and_the_mirror_check_the_gate(self):
        """state.svelte.ts and source/mirror.ts pull in the whole page; their gates are read from the source."""
        state = (ROOT / 'web/src/mobile/state.svelte.ts').read_text(encoding='utf-8')
        mirror = (ROOT / 'web/src/mobile/source/mirror.ts').read_text(encoding='utf-8')
        # the phone without a PC is removed on Backup & phones (sub-plan 05), behind the same gate
        backup = (ROOT / 'web/src/mobile/screens/Backup.svelte').read_text(encoding='utf-8')
        self.assertIn("reconnecting, RECONNECT_BUSY, stopCloudWork } from './mirror/gate'", state)
        self.assertEqual(state.count('if (reconnecting()) { phone.note = RECONNECT_BUSY; return }'), 1)       # pairFrom; Connect drains work before switching accounts
        self.assertIn('if (reconnecting()) { phone.note = RECONNECT_BUSY; return false }', state)              # useWithoutPc
        self.assertIn('if (reconnecting()) return RECONNECT_BUSY', state)                                      # refresh
        self.assertIn('if (reconnecting() || cloudStopped()) return\n', state[state.index('export async function syncNow'):])     # syncNow
        self.assertIn("endCloudChange, reconnecting, stopCloudWork } from '../mirror/gate'", mirror)
        self.assertIn('    beginCloudChange()\n    try {\n      const n = await this.changes.flush(', mirror)
        self.assertIn('private async readBack(): Promise<number> {\n    beginCloudChange()\n    try {', mirror)
        self.assertEqual(mirror.count('      endCloudChange()'), 2)
        self.assertIn('|| syncPaused() || reconnecting() || cloudStopped() || Date.now() - this.looked < 60_000) return', mirror)
        self.assertIn('if (this.solo && await finishReconnect(this.changes, await this.key)) this.flushSoon()', mirror)
        self.assertIn('RECONNECT_BUSY', backup)
