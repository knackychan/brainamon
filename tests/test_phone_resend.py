"""Pairing again (S5) and numbered change files on the phone (web/src/mobile/mirror/changes.ts, pairing.ts, resend.ts),
checked under Node and, where a PC takes part, against the PC's own intake (server/delivery.py). Synthetic keys,
grants, journals and FakeDrive only. Plan: docs/superpowers/plans/2026-10-31-phone-backup-phones/
02-s5-resend-after-pairing-again.md."""
import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path

from core import license, sync_license
from library import mirror
from tests import test_phone_delivery_prerequisite as base
from tests import test_phone_js
from tests import test_sync

# the phone's journal and kv in memory (store.ts without IndexedDB), a send that records each change file
JOURNAL = """
    const { changes: db, kv } = await import('./web/src/mobile/store.ts')
    const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
    const R = await import('./web/src/mobile/mirror/resend.ts')
    const mem = new Map()
    globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) }
    const state = __STATE__ ?? { rows: [], kv: {} }
    const rows = new Map(state.rows.map(e => [e.id, e])), store = new Map(Object.entries(state.kv))
    let nextId = Math.max(0, ...rows.keys()) + 1, broken = 0
    const check = () => { if (broken > 0) { broken--; throw new Error('synthetic storage failure') } }
    db.all = async () => structuredClone([...rows.values()].sort((a, b) => a.id - b.id))
    db.add = async e => { check(); const id = nextId++; rows.set(id, structuredClone({ ...e, id })); return id }
    db.put = async e => { check(); rows.set(e.id, structuredClone(e)) }
    db.del = async id => { check(); rows.delete(id) }
    kv.get = async k => structuredClone(store.get(k))
    kv.set = async (k, v) => { check(); store.set(k, structuredClone(v)) }
    kv.del = async k => { store.delete(k) }
    const saved = () => ({ rows: [...rows.values()], kv: Object.fromEntries(store) })
    const sent = []
    const send = async doc => { sent.push(structuredClone(doc)); return 'chg-' + sent.length }
"""

PAIRING = """
    const mem = new Map(), session = new Map()
    globalThis.localStorage = { getItem: k => mem.get(k) ?? null, removeItem: k => mem.delete(k), setItem: (k, v) => {
      if (k === 'bp-resend' && globalThis.__failMarker) throw new DOMException('synthetic quota', 'QuotaExceededError')
      mem.set(k, String(v)) } }
    globalThis.sessionStorage = { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, String(v)), removeItem: k => session.delete(k) }
    const P = await import('./web/src/mobile/mirror/pairing.ts')
    const R = await import('./web/src/mobile/mirror/resend.ts')
    const { secrets } = await import('./web/src/mobile/native.ts')
    const link = p => '#pair=' + Buffer.from(JSON.stringify(p)).toString('base64url')
    const asked = []
    globalThis.confirm = q => { asked.push(q); return globalThis.__answer ?? true }
    const marker = () => { const m = JSON.parse(mem.get('bp-resend') ?? 'null'); return m && { f: m.f, l: m.l } }
    const start = async old => {
      secrets.set('bp-pair', JSON.stringify(old))
      secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
      await P.validateStoredPairing()
    }
    const K = __KEYS__, A = 'A'.repeat(122), B = 'B'.repeat(122)
    const old = { v: 2, k: K[0].k, f: K[0].f, l: A, c: 'client', e: 'Fred@Example.com', p: 'project', ai: {}, at: 1, g: 'fred@example.com' }
"""

KEPT = 'Paired again. Kept your Google sign-in (fred@example.com).'
REPLACE = 'Replace this phone’s paired PC and account?'


def run(script: str, **values) -> dict:
    for name, value in values.items():
        script = script.replace(f'__{name}__', json.dumps(value))
    return json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + script))


def keys(n=2):
    out = [mirror.MirrorKey.generate() for _ in range(n)]
    return [{'k': k.text(), 'f': k.fingerprint} for k in out]


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class PhoneToPc(base.Fixture):
    """The phone's own change files, applied by this PC's intake."""

    def phone(self, script, state=None, **values):
        return run(JOURNAL + """
            const append = tag => c.add({ op: 'note_append', file: __NOTE__, title: 'Delivery probe', name: 'Fixture',
              text: 'section-' + tag, when: '2026-10-31 15:05' })
        """ + script, STATE=state, NOTE=self.note.name, **values)

    def deliver(self, docs, key=None):
        for doc in docs:
            name, blob = (key or self.key).seal_change(doc)
            self.drive.put(name, blob)

    def order(self, *tags):
        text = self.note.read_text(encoding='utf-8')
        return sorted(tags, key=lambda t: text.index('section-' + t))

    def test_numbered_files_apply_once_in_order_after_a_lost_answer(self):
        out = self.phone("""
            let c = new Changes()
            await append('A'); await c.flush(send, 'probe-phone', true, true)
            await append('B')
            await c.flush(async doc => { sent.push(structuredClone(doc)); throw new Error('synthetic lost answer') }, 'probe-phone', true, true)
              .catch(() => {})                                                  // uploaded, but the answer never came
            c = new Changes()                                                   // and the app restarts
            await c.flush(send, 'probe-phone', true, true)
            await append('C'); await c.flush(send, 'probe-phone', true, true)
            console.log(JSON.stringify({ sent }))
        """)
        a, b, b2, c = out['sent']
        self.assertEqual([d['seq'] for d in out['sent']], [1, 2, 2, 3])
        self.assertEqual(b, b2)                                  # the same file again: number, time and changes
        self.assertTrue(a['at'] < b['at'] < c['at'])
        self.assertEqual({d['stream'] for d in out['sent']}, {a['stream']})
        self.assertEqual(set(a) - {'legacy'}, {'format', 'device', 'at', 'stream', 'seq', 'acked', 'changes'})
        self.assertEqual(a['changes'][0].keys() & {'id', 'state', 'sentAt', 'stream', 'seq', 'resend'}, set())
        self.deliver([c, b2, a, b])                              # listed in any order
        self.svc._intake()
        self.assertEqual(self.counts('A', 'B', 'C'), (1, 1, 1))
        self.assertEqual(self.order('C', 'A', 'B'), ['A', 'B', 'C'])
        self.assertEqual(self.receipt(a['stream']), {'seq': 3})
        self.assertEqual(self.changes_left(), [])

    def test_pairing_again_after_remove_all_phones_sends_only_what_the_pc_lacks(self):
        first = self.phone("""
            const c = new Changes()
            await append('A'); await c.flush(send, 'probe-phone', true, true)
            await append('B'); await c.flush(send, 'probe-phone', true, true)
            console.log(JSON.stringify({ sent, state: saved() }))
        """)
        a, b = first['sent']
        self.deliver([a])
        self.svc._intake()
        self.svc.unpair()                                        # Remove all phones: a new key
        self.deliver([b])                                        # late, under the old key: never read (I6)
        self.svc._intake()
        self.assertTrue(self.svc._publish(threading.Event()), self.svc.status())
        self.assertEqual(self.svc._rotation()['stage'], 'complete')
        new = mirror.MirrorKey.load(self.svc.key_path)
        man, _ = test_sync.read_mirror(self.drive, new)
        self.assertEqual((man['delivery'], man['receipts'][a['stream']]['seq']), (mirror.DELIVERY, 1))
        second = self.phone("""
            const pair = { f: __F__, l: 'L'.repeat(122) }
            R.markResend(pair)
            const c = new Changes()
            const man = __MAN__
            const resent = await c.prune(man.applied?.['probe-phone'] ?? 0, man, pair)
            const flagged = c.resending(true)
            await append('C')
            await c.flush(send, 'probe-phone', true, true)
            console.log(JSON.stringify({ resent, pending: R.resendPending(pair), flagged, sent }))
        """, first['state'], F=new.fingerprint, MAN=man)
        self.assertEqual((second['resent'], second['pending'], second['flagged']), (True, False, 1))
        b_again, c = second['sent']
        self.assertEqual({k: b_again[k] for k in ('stream', 'seq', 'at', 'changes')}, {k: b[k] for k in ('stream', 'seq', 'at', 'changes')})
        self.assertEqual((b_again['acked'], c['seq'], c['acked']), (1, 3, 1))
        self.deliver(second['sent'], new)
        self.svc._intake()
        self.assertEqual(self.counts('A', 'B', 'C'), (1, 1, 1))
        self.assertEqual(self.receipt(a['stream']), {'seq': 3})
        self.assertEqual(len(self.changes_left()), 1)            # the old-key copy stays for recovery

    def test_batches_an_older_build_sent_apply_once_after_the_upgrade(self):
        self.put('A', 100)
        self.put('B', 200)
        self.svc._intake()                                       # an older phone build, an older floor
        self.assertEqual(self.applied(), {'probe-phone': 200})
        old = [{'id': i + 1, 'op': 'note_append', 'file': self.note.name, 'title': 'Delivery probe', 'name': 'Fixture',
                'text': 'section-' + tag, 'when': '2026-10-31 15:05', 'at': at, 'state': state,
                **({'sentAt': at, 'chg': 'chg-old'} if state != 'queued' else {})}
               for i, (tag, at, state) in enumerate([('A', 100, 'sent'), ('B', 200, 'sent'), ('C', 300, 'sending'), ('D', 400, 'queued')])]
        out = self.phone("""
            const c = new Changes()
            await c.flush(send, 'probe-phone', true, true)
            console.log(JSON.stringify({ sent }))
        """, {'rows': old, 'kv': {}})
        self.assertEqual([(d['seq'], d['at'], d.get('legacy', False)) for d in out['sent'][:3]],
                         [(1, 100, True), (2, 200, True), (3, 300, True)])
        self.assertEqual((out['sent'][3]['seq'], 'legacy' in out['sent'][3], out['sent'][3]['at'] > 300), (4, False, True))
        self.deliver(out['sent'])
        self.svc._intake()
        self.assertEqual(self.counts('A', 'B', 'C', 'D'), (1, 1, 1, 1))
        self.assertEqual(self.applied(), {'probe-phone': 300})
        self.assertEqual(self.receipt(out['sent'][0]['stream']), {'seq': 4})
        self.assertEqual(self.changes_left(), [])


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Journal(unittest.TestCase):
    def test_receipts_prune_and_a_want_sends_the_missing_batch_once_per_manifest(self):
        out = run(JOURNAL + """
            const c = new Changes()
            for (const t of ['A', 'B', 'C']) { await c.add({ op: 'fav', uid: t, on: true }); await c.flush(send, 'phone', true, true) }
            const S = sent[0].stream
            const view = () => c.list.map(e => [e.uid, e.seq, e.state])
            const man = (seq, want, published) => ({ delivery: 2, published, receipts: { [S]: { device: 'phone', seq, ...(want ? { want } : {}) } } })
            await c.prune(0, man(1, 2, 10)); const one = view()
            await c.prune(0, man(1, 2, 10)); const again = view()
            await c.flush(send, 'phone', true, true); const resent = sent.slice(3).map(d => d.seq)
            await c.prune(0, man(1, 2, 10)); const same = view()
            await c.prune(0, man(1, 2, 11)); const next = view()
            await c.prune(0, man(3, 0, 12))
            const d = saved().kv.delivery
            console.log(JSON.stringify({ seqs: sent.slice(0, 3).map(d => d.seq), stream: /^[0-9a-f]{32}$/.test(S), one, again, resent,
              same, next, left: c.list.length, delivery: { ...d, stream: d.stream === S } }))
        """, STATE=None)
        self.assertEqual(out, {
            'seqs': [1, 2, 3], 'stream': True,
            'one': [['B', 2, 'sending'], ['C', 3, 'sent']], 'again': [['B', 2, 'sending'], ['C', 3, 'sent']], 'resent': [2],
            'same': [['B', 2, 'sent'], ['C', 3, 'sent']], 'next': [['B', 2, 'sending'], ['C', 3, 'sent']], 'left': 0,
            'delivery': {'stream': True, 'next': 4, 'acked': 3, 'wanted': '2:11'}})

    def test_an_older_pc_prunes_by_its_floor_and_missing_receipts_keep_the_batch(self):
        out = run(JOURNAL + """
            const c = new Changes()
            for (const t of ['A', 'B']) { await c.add({ op: 'fav', uid: t, on: true }); await c.flush(send, 'phone', true, true) }
            const at = sent.map(d => d.at)
            await c.prune(at[1] + 1, { delivery: 2, receipts: {} }); const sparse = c.list.length
            await c.prune(at[1] + 1, { delivery: 2, receipts: { ['f'.repeat(32)]: { device: 'other', seq: 9 } } }); const other = c.list.length
            await c.prune(at[0], {}); const floor = c.list.map(e => e.uid)            // a PC without delivery 2
            await c.add({ op: 'fav', uid: 'C', on: true }); await c.flush(send, 'phone', true, true)
            console.log(JSON.stringify({ sparse, other, floor, acked: sent[2].acked, seq: sent[2].seq }))
        """, STATE=None)
        self.assertEqual(out, {'sparse': 2, 'other': 2, 'floor': ['B'], 'acked': 1, 'seq': 3})

    def test_the_marker_waits_for_its_pairing_and_survives_a_failed_write_and_a_restart(self):
        out = run(JOURNAL + """
            const P1 = { f: 'a'.repeat(12), l: 'L1' }, P2 = { f: 'b'.repeat(12), l: 'L2' }
            let c = new Changes()
            await c.add({ op: 'fav', uid: 'A', on: true }); await c.flush(send, 'phone', true, true)
            await c.add({ op: 'fav', uid: 'B', on: true })                     // made while access was removed
            R.markResend(P2)
            const S = sent[0].stream, man = { delivery: 2, published: 5, receipts: {} }
            const other = await c.prune(0, man, P1)                            // read under another pairing
            const keptForOther = R.resendPending(P2)
            broken = 1
            let failed = ''
            try { await c.prune(0, man, P2) } catch (e) { failed = e.message }
            const view = l => l.map(e => [e.uid, e.state, !!e.resend])
            const afterFail = { pending: R.resendPending(P2), memory: view(c.list), stored: view([...rows.values()]) }
            c = new Changes(); await c.load()                                   // the app starts again
            const waiting = c.resending(true, R.resendPending(P2))
            const done = await c.prune(0, man, P2)
            const flagged = c.resending(true, R.resendPending(P2))
            const after = c.list.map(e => [e.uid, e.state, e.seq ?? null, !!e.resend])
            await c.flush(send, 'phone', true, true)
            const out = sent.slice(1).map(d => [d.seq, d.at === sent[0].at, d.changes.map(x => x.uid)])
            await c.prune(0, { delivery: 2, published: 6, receipts: { [S]: { device: 'phone', seq: 2 } } })
            console.log(JSON.stringify({ other, keptForOther, failed, afterFail, waiting, done, pending: R.resendPending(P2), flagged, after,
              out, left: c.resending(true) }))
        """, STATE=None)
        self.assertEqual(out, {
            'other': False, 'keptForOther': True, 'failed': 'synthetic storage failure',
            'afterFail': {'pending': True, 'memory': [['A', 'sent', False], ['B', 'queued', False]],
                          'stored': [['A', 'sent', False], ['B', 'queued', False]]},
            'waiting': 2, 'done': True, 'pending': False, 'flagged': 2,
            'after': [['A', 'sending', 1, True], ['B', 'queued', None, True]],
            'out': [[1, True, ['A']], [2, False, ['B']]], 'left': 0})

    def test_flush_prune_and_canvas_results_take_turns(self):
        out = run(JOURNAL + """
            const P = { f: 'c'.repeat(12), l: 'L' }
            const c = new Changes()
            const log = []
            await c.add({ op: 'fav', uid: 'A', on: true })
            const canvas = { id: 99, op: 'canvas', state: 'sent', at: 1, sentAt: 1,
              canvasLocal: { base: null, result: { id: 'x', name: '', items: [] }, assets: [], status: 'refused' } }
            c.list.push(canvas)
            let release
            const gate = new Promise(r => { release = r })
            const slow = async doc => { log.push('send ' + doc.seq); await gate; sent.push(doc); return 'chg-slow' }
            const flushing = c.flush(slow, 'phone', true, true)
            const twice = c.flush(slow, 'phone', true, true)                   // Send now while the online event's flush runs
            await new Promise(r => setTimeout(r, 20))
            R.markResend(P)
            const pruning = c.prune(0, { delivery: 2, published: 1, receipts: {} }, P).then(v => log.push('prune ' + v))
            const result = c.canvasResult(canvas, 'synced').then(() => log.push('canvas saved'), e => log.push('canvas: ' + e.message))
            await c.add({ op: 'fav', uid: 'B', on: true })
            log.push('added B')
            await new Promise(r => setTimeout(r, 20))
            log.push('release')
            release()
            const n = [await flushing, await twice]
            await Promise.all([pruning, result])
            console.log(JSON.stringify({ log, n, sent: sent.map(d => [d.seq, d.changes.map(x => x.uid)]),
              list: c.list.map(e => [e.uid ?? e.op, e.state, e.seq ?? null, !!e.resend]) }))
        """, STATE=None)
        log = out.pop('log')
        self.assertEqual(log[:3], ['send 1', 'added B', 'release'])          # nothing else ran during the upload
        self.assertEqual(sorted(log[3:]), sorted(['prune true', 'canvas: Phone storage is unavailable.', 'send 1', 'send 2']))
        self.assertLess(log.index('prune true'), log.index('send 2'))
        self.assertEqual(out, {                                              # A again: the prune ran before the next upload
            'n': [3, 3], 'sent': [[1, ['A']], [1, ['A']], [2, ['B']]],
            'list': [['A', 'sent', 1, True], ['canvas', 'sent', None, False], ['B', 'sent', 2, True]]})

    def test_clock_rollback_and_canvas_changes_keep_whole_batches_in_order(self):
        out = run(JOURNAL + """
            const c = new Changes()
            let now = 1000; Date.now = () => now
            const local = status => ({ base: null, result: { id: 'x', name: '', items: [] }, assets: [], status })
            await c.add({ op: 'fav', uid: 'A', on: true }); await c.flush(send, 'phone', true, true)
            now = 500                                                           // the phone's clock went back
            await c.add({ op: 'fav', uid: 'B', on: true }); await c.flush(send, 'phone', true, true)
            await c.add({ op: 'fav', uid: 'C', on: true })
            await c.add({ op: 'canvas', op_id: 'd'.repeat(32), canvas_id: 'e'.repeat(32), proposal: {}, refs: {}, sizes: {}, canvasLocal: local('pending') })
            await c.flush(send, 'phone', false, true)                          // a PC that takes no canvas changes
            const held = { list: c.list.map(e => [e.uid ?? e.op, e.state, e.seq ?? null]), resending: c.resending(false, true), all: c.resending(true, true) }
            await c.flush(send, 'phone', true, true)
            c.list.push({ id: 50, op: 'canvas', state: 'sent', at: 1, sentAt: 400, canvasLocal: local('refused') },
              { id: 51, op: 'canvas', state: 'sent', at: 1, sentAt: 400, canvasLocal: local('synced') })
            const before = sent.length
            await c.flush(send, 'phone', true, true)                           // settled: never numbered, never sent again
            const extra = sent.length - before
            c.list.find(e => e.seq === 4).state = 'sending'                     // its upload did not finish
            await c.add({ op: 'fav', uid: 'D', on: true })
            const blocked = [await c.flush(send, 'phone', false, true), c.list.find(e => e.uid === 'D').state]
            console.log(JSON.stringify({ at: sent.map(d => d.at), seqs: sent.map(d => d.seq), ops: sent.map(d => d.changes.map(x => x.uid ?? x.op)),
              held, extra, blocked }))
        """, STATE=None)
        self.assertEqual(out, {
            'at': [1000, 1001, 1002, 1003], 'seqs': [1, 2, 3, 4], 'ops': [['A'], ['B'], ['C'], ['canvas']],
            'held': {'list': [['A', 'sent', 1], ['B', 'sent', 2], ['C', 'sent', 3], ['canvas', 'queued', None]], 'resending': 3, 'all': 4},
            'extra': 0, 'blocked': [0, 'queued']})


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class PairingAgain(unittest.TestCase):
    def test_the_same_library_keeps_the_google_sign_in_without_asking(self):
        out = run(PAIRING + """
            await start(old)
            const token = secrets.get('bp-gtoken')
            const scan = { v: 2, k: K[1].k, f: K[1].f, l: A, c: 'client', e: 'fred@example.com', p: 'project' }
            const r1 = { note: await P.acceptLink(link(scan)), f: P.pairing()?.f === K[1].f, g: P.pairing()?.g, token: secrets.get('bp-gtoken') === token, marker: marker() }
            const at = JSON.parse(mem.get('bp-resend')).at
            const r2 = { note: await P.acceptLink(link(scan)), same: JSON.parse(mem.get('bp-resend')).at === at, token: secrets.get('bp-gtoken') === token }
            const signer = { ...scan, l: B }                                    // the same key, a new PC signing key
            const r3 = { note: await P.acceptLink(link(signer)), l: P.pairing()?.l === B, marker: marker(), token: secrets.get('bp-gtoken') === token }
            console.log(JSON.stringify({ r1, r2, r3, asked }))
        """, KEYS=keys())
        f1 = out['r1'].pop('marker')
        self.assertEqual(out['r1'], {'note': KEPT, 'f': True, 'g': 'fred@example.com', 'token': True})
        self.assertEqual(f1['l'], 'A' * 122)
        self.assertEqual(out['r2'], {'note': 'Paired again with the same PC.', 'same': True, 'token': True})
        self.assertEqual(out['r3'], {'note': KEPT, 'l': True, 'marker': {'f': f1['f'], 'l': 'B' * 122}, 'token': True})
        self.assertEqual(out['asked'], [])

    def test_another_library_or_account_still_asks_and_signs_in_again(self):
        out = run(PAIRING + """
            await start(old)
            const token = secrets.get('bp-gtoken')
            const other = { v: 2, k: K[1].k, f: K[1].f, l: B, c: 'client', e: 'fred@example.com', p: 'project' }
            globalThis.__answer = false
            const c1 = { note: await P.acceptLink(link(other)), asked: asked.splice(0), f: P.pairing()?.f === K[0].f, token: secrets.get('bp-gtoken') === token, marker: marker() }
            globalThis.__answer = true
            const c2 = { note: await P.acceptLink(link(other)), asked: asked.splice(0), f: P.pairing()?.f === K[1].f, g: P.pairing()?.g ?? null, token: secrets.get('bp-gtoken'), marker: marker() }
            await start(old)
            const account = { v: 2, k: K[0].k, f: K[0].f, l: A, c: 'client', e: 'someone@example.com', p: 'project' }
            const c3 = { note: await P.acceptLink(link(account)), asked: asked.splice(0), token: secrets.get('bp-gtoken') }
            console.log(JSON.stringify({ c1, c2, c3, f: K[1].f }))
        """, KEYS=keys())
        self.assertEqual(out['c1'], {'note': 'Pairing cancelled.', 'asked': [REPLACE], 'f': True, 'token': True, 'marker': None})
        self.assertEqual(out['c2'], {'note': 'Paired with your PC.', 'asked': [REPLACE], 'f': True, 'g': None, 'token': None,
                                     'marker': {'f': out['f'], 'l': 'B' * 122}})
        self.assertEqual(out['c3'], {'note': 'Paired with your PC.', 'asked': [REPLACE], 'token': None})

    def test_a_phone_used_without_a_pc_takes_only_the_requeue_path(self):
        out = run(PAIRING + """
            await P.startSolo(P.newKeyText())
            const scan = { v: 2, k: K[0].k, f: K[0].f, l: A, c: 'client', e: 'fred@example.com', p: 'project' }
            const note = await P.acceptLink(link(scan))
            console.log(JSON.stringify({ note, asked, requeue: P.takeRequeue(), marker: marker() }))
        """, KEYS=keys())
        self.assertEqual(out, {'note': 'Paired with your PC.', 'requeue': True, 'marker': None,
                               'asked': ['Send this phone’s library to this PC? Only continue if you trust this PC and its pairing code.']})

    def test_a_marker_that_cannot_be_saved_keeps_the_old_pairing(self):
        out = run(PAIRING + """
            await start(old)
            const token = secrets.get('bp-gtoken')
            const scan = { v: 2, k: K[1].k, f: K[1].f, l: A, c: 'client', e: 'fred@example.com', p: 'project' }
            globalThis.__failMarker = true
            const kept = { note: await P.acceptLink(link(scan)), f: P.pairing()?.f === K[0].f, token: secrets.get('bp-gtoken') === token, marker: marker() }
            globalThis.__failMarker = false
            const retried = await P.acceptLink(link(scan))
            const saved = marker()
            Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new DOMException('blocked', 'SecurityError') } })
            const x = { f: 'x'.repeat(12), l: 'L' }
            R.markResend(x)                                                     // blocked storage: kept while the page is open
            const blocked = [R.resendPending(x), R.resendPending({ ...x, l: 'M' })]
            R.clearResend(x)
            blocked.push(R.resendPending(x))
            console.log(JSON.stringify({ kept, retried, saved: saved?.f === K[1].f, blocked }))
        """, KEYS=keys())
        self.assertEqual(out, {'kept': {'note': 'That pairing code could not be read. Show the QR on the PC again.', 'f': True, 'token': True,
                                        'marker': None}, 'retried': KEPT, 'saved': True, 'blocked': [True, False, False]})

    def test_unpair_then_scan_again_resends_after_the_next_manifest(self):
        out = run(PAIRING + """
            await start(old)
            P.forget()                                                          // Unpair: the journal stays (P10)
            const scan = { v: 2, k: K[0].k, f: K[0].f, l: A, c: 'client', e: 'fred@example.com', p: 'project' }
            const note = await P.acceptLink(link(scan))
            console.log(JSON.stringify({ note, asked, pending: R.resendPending(P.pairing()), token: secrets.get('bp-gtoken') }))
        """, KEYS=keys())
        self.assertEqual(out, {'note': 'Paired with your PC.', 'asked': [], 'pending': True, 'token': None})

    def test_the_same_key_with_a_new_signer_still_refuses_the_old_signers_access(self):
        with tempfile.TemporaryDirectory() as folder:
            from tests.license_fixture import activate
            activate(self, Path(folder))
            key = mirror.MirrorKey.generate()
            first = sync_license.signer(Path(folder) / 'first.pem', create=True)
            second = sync_license.signer(Path(folder) / 'second.pem', create=True)
            sealed = lambda grant: base64.b64encode(key.seal(sync_license.LOGICAL, grant)).decode()
            pair = {'v': 2, 'k': key.text(), 'f': key.fingerprint, 'l': sync_license.public(first), 'c': '', 'e': '', 'ai': {}}
            out = run("""
                const mem = new Map(), session = new Map()
                globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) }
                globalThis.sessionStorage = { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, String(v)), removeItem: k => session.delete(k) }
                globalThis.window = new EventTarget(); globalThis.document = new EventTarget()
                Object.defineProperty(navigator, 'onLine', { value: true })
                Object.defineProperty(navigator, 'connection', { value: Object.assign(new EventTarget(), { type: 'wifi' }) })
                globalThis.__LICENSE_PUBLIC_KEYS__ = __ISSUERS__
                const P = await import('./web/src/mobile/mirror/pairing.ts')
                const { secrets } = await import('./web/src/mobile/native.ts')
                const { Drive } = await import('./web/src/mobile/mirror/drive.ts')
                const asked = []
                globalThis.confirm = q => { asked.push(q); return true }
                const pair = __PAIR__
                secrets.set('bp-pair', JSON.stringify({ ...pair, at: 1, g: 'fixture@example.com' }))
                secrets.set('bp-gtoken', JSON.stringify({ access: 'synthetic', exp: Date.now() + 3600000 }))
                await P.validateStoredPairing()
                const scan = { ...pair, l: __SECOND__ }; delete scan.ai
                const note = await P.acceptLink('#pair=' + Buffer.from(JSON.stringify(scan)).toString('base64url'))
                let control = ''
                globalThis.fetch = async url => {
                  if (url.includes('/files?') && new URL(url).searchParams.get('q').includes(__V2CONTROL__)) return Response.json({ files: [] })
                  if (url.includes('/files?')) return Response.json({ files: control ? [{ id: 'control', size: '10000' }] : [] })
                  if (url.includes('/files/control?')) return new Response(Buffer.from(control, 'base64'))
                  return new Response('local fixture content')
                }
                const drive = new Drive('https://www.googleapis.com', () => 'synthetic', () => {})
                const seen = []
                for (const grant of [__OLD__, __NEW__]) { control = grant; try { await drive.get('content'); seen.push('granted') } catch (e) { seen.push(e.kind) } }
                console.log(JSON.stringify({ note, asked, pinned: P.pairing()?.l === scan.l, seen }))
            """, ISSUERS=list(license.PUBLIC_KEYS), PAIR=pair, SECOND=sync_license.public(second),
                      V2CONTROL=key.name(sync_license.ACCESS_LOGICAL),
                      OLD=sealed(sync_license.record(key, first)), NEW=sealed(sync_license.record(key, second)))
        self.assertEqual(out, {'note': 'Paired again. Kept your Google sign-in (fixture@example.com).', 'asked': [], 'pinned': True,
                               'seen': ['replaced', 'granted']})


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class FreshManifestGate(unittest.TestCase):
    """source/mirror.ts pulls in the whole page: its flush and loadManifest run here from the source, with stubs."""

    def test_nothing_goes_before_a_fresh_manifest_from_the_new_pairing(self):
        out = run(JOURNAL + r"""
            const fs = await import('node:fs')
            const { stripTypeScriptTypes } = await import('node:module')
            const src = fs.readFileSync('web/src/mobile/source/mirror.ts', 'utf8').replace(/\r\n/g, '\n')   // a CRLF checkout too
            const pick = re => src.match(re)[0]
            const body = [pick(/  get solo\(\) .*\n/), pick(/  get canvasSync\(\) .*\n/), pick(/  get resendPending\(\) .*\n/),
              pick(/  async loadManifest\(\)[\s\S]*?\n  }\n/), pick(/  async flush\(\): Promise<number> \{[\s\S]*?\n  }\n/)].join('\n')
            const READER = Number(src.match(/export const READER = (\d+)/)[1])
            class PhoneTooOld extends Error {}
            class SyncPaused extends Error {}
            let online = true, signedIn = true, soon = 0, reads = 0
            const uploads = []
            Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online })
            const Source = new Function('READER', 'PhoneTooOld', 'tooOld', 'kv', 'deviceId', 'syncPaused', 'SyncPaused', 'token',
              'beginCloudChange', 'endCloudChange', 'recordPublish', 'resendPending', 'cloudStopped',
              stripTypeScriptTypes('class Source {\n' + body + '\n}') + ';return Source')(
              READER, PhoneTooOld, { fn: () => {} }, kv, () => 'phone', () => false, SyncPaused, () => signedIn ? 'synthetic' : null,
              () => {}, () => {}, async () => {}, R.resendPending, () => false)
            const s = new Source()
            let found = false, incoming = null
            Object.assign(s, { pair: { f: 'n'.repeat(12), l: 'L' }, changes: new Changes(), manifest: { reader: 1, files: {}, cached: true },
              mine: new Set(), lastError: '', cached: async () => '{}', flushSoon: () => { soon++ },
              noLibrary: async () => new Error('No library from this PC yet.'),
              key: { name: async n => n, openJSON: async () => { reads++; return incoming },
                     sealChange: async doc => { uploads.push(structuredClone(doc)); return ['chg-' + uploads.length, new Uint8Array()] } },
              drive: { checkpoint: () => {}, find: async () => found ? { id: 'manifest' } : null, get: async () => new Uint8Array(), create: async () => 'id' } })
            await s.changes.add({ op: 'fav', uid: 'A', on: true }); await s.changes.flush(async () => 'chg-old', 'phone', true, true)
            await s.changes.add({ op: 'fav', uid: 'B', on: true })
            R.markResend(s.pair)
            let early = ''
            try { await s.flush() } catch (e) { early = e.message }            // a valid grant, no manifest under the new key yet
            const first = { early, uploads: uploads.length, pending: R.resendPending(s.pair), reads }
            online = false
            const offline = [await s.flush(), reads]
            online = true
            signedIn = false                                                    // signed out of Google: the marker stays
            offline.push(await s.flush(), reads, R.resendPending(s.pair))
            signedIn = true
            found = true
            incoming = { reader: READER, files: {}, applied: {}, delivery: 2, published: 7, receipts: {} }
            const n = await s.flush()
            console.log(JSON.stringify({ first, offline, n, reads, soon, pending: R.resendPending(s.pair),
              uploads: uploads.map(d => [d.seq, d.changes.map(c => c.uid)]) }))
        """, STATE=None)
        self.assertEqual(out, {'first': {'early': 'No library from this PC yet.', 'uploads': 0, 'pending': True, 'reads': 0},
                               'offline': [0, 0, 0, 0, True], 'n': 2, 'reads': 1, 'soon': 1, 'pending': False,
                               'uploads': [[1, ['A']], [2, ['B']]]})


if __name__ == '__main__':
    unittest.main()
