"""The confirmed findings of the review of the applied sub-plans 01 to 03 (docs/superpowers/plans/
2026-10-31-phone-backup-phones-review-01-03.md), one test each: the phone's journal (web/src/mobile/mirror/changes.ts,
source/mirror.ts), the PC's intake (server/intake.py, server/delivery.py, server/sync.py) and the phone's record
(web/src/mobile/mirror/phone-record.ts, mirror/drive.ts). Synthetic keys, grants, journals and Drives only.
Plan: docs/superpowers/plans/2026-10-31-phone-backup-phones/03a-review-fixes.md."""
import base64
import io
import json
import sqlite3
import unittest
from unittest import mock

from PIL import Image

from core import sync_license
from core.db import Database
from library import mirror
from server import delivery, dev_drive
from tests import test_phone_delivery_prerequisite as base
from tests import test_phone_js, test_phone_record, test_phone_resend

S = 'a' * 32
D = 'p0123456789'
T0 = 1_793_400_000_000


def entry(i, tag, note, **kw):
    """A note_append the phone keeps in its journal (store.ts row)."""
    return {'id': i, 'op': 'note_append', 'file': note, 'title': 'Delivery probe', 'name': 'Fixture', 'text': 'section-' + tag,
            'when': '2026-10-31 15:05', 'at': 100 * i, **kw}


def paired_before(note):
    """Paired with a PC: batch 1 applied and pruned, batch 2 sent and never acknowledged, C queued; then Unpair, the
    app used without a PC, and a scan of a PC's code. kv `delivery` still says 3, acked 1 (finding 1)."""
    return {'rows': [entry(1, 'B', note, state='sent', sentAt=200, stream=S, seq=2, chg='chg-2'), entry(2, 'C', note, state='queued')],
            'kv': {'delivery': {'stream': S, 'next': 3, 'acked': 1}}}


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Requeue(base.Fixture):
    def test_a_phone_paired_after_use_without_a_pc_sends_its_journal_as_a_new_stream(self):
        out = test_phone_resend.run(test_phone_resend.JOURNAL + """
            const c = new Changes()
            await c.requeue()
            await c.flush(send, 'probe-phone', true, true)
            console.log(JSON.stringify({ sent, delivery: saved().kv.delivery }))
        """, STATE=paired_before(self.note.name))
        [doc] = out['sent']
        self.assertNotEqual(doc['stream'], S)
        self.assertEqual((doc['seq'], doc['acked'], [c['text'] for c in doc['changes']]), (1, 0, ['section-B', 'section-C']))
        self.assertEqual(out['delivery'], {'stream': doc['stream'], 'next': 2, 'acked': 0})
        for rec in ({S: {'seq': 1, 'digests': {}}}, {}):            # the PC it was paired with before, or another one
            self.assertEqual(delivery.take(rec, doc), 'apply')
        self.fx.writer.call(lambda db: db.set_setting(base.RECEIPTS, json.dumps({S: {'device': 'probe-phone', 'seq': 1, 'digests': {}}})))
        self.drive.put(*self.key.seal_change(doc))
        self.svc._intake()
        self.assertEqual(self.counts('B', 'C'), (1, 1))
        self.assertEqual(self.receipt(doc['stream']), {'seq': 1})


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Journal(unittest.TestCase):
    def test_a_requeue_the_phone_storage_refuses_leaves_the_journal_as_it_was(self):
        out = test_phone_resend.run(test_phone_resend.JOURNAL + """
            const c = new Changes()
            await c.load()
            broken = 1
            let failed = ''
            try { await c.requeue() } catch (e) { failed = e.message }
            const view = l => l.map(e => [e.text, e.state, e.stream === 'a'.repeat(32), e.seq ?? null])
            console.log(JSON.stringify({ failed, memory: view(c.list), stored: view(saved().rows), delivery: saved().kv.delivery }))
        """, STATE=paired_before('delivery-probe.md'))
        self.assertEqual(out, {'failed': 'synthetic storage failure',
                               'memory': [['section-B', 'sent', True, 2], ['section-C', 'queued', False, None]],
                               'stored': [['section-B', 'sent', True, 2], ['section-C', 'queued', False, None]],
                               'delivery': {'stream': S, 'next': 3, 'acked': 1}})

    def test_the_requeue_marker_goes_only_once_the_journal_is_saved(self):
        out = test_phone_resend.run(r"""
            const mem = new Map()
            globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) }
            globalThis.sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
            const P = await import('./web/src/mobile/mirror/pairing.ts')
            const fs = await import('node:fs')
            const { stripTypeScriptTypes } = await import('node:module')
            const src = fs.readFileSync('web/src/mobile/source/mirror.ts', 'utf8').replace(/\r\n/g, '\n')   // a CRLF checkout too
            const pick = re => src.match(re)[0]
            const body = [pick(/  get solo\(\) .*\n/), pick(/  private primed: .*\n/), pick(/  private ready\(\) \{[\s\S]*?\n  }\n/)].join('\n')
            const Source = new Function('requeueWaiting', 'takeRequeue', 'finishReconnect', 'kv', 'files',
              stripTypeScriptTypes('class Source {\n' + body + '\n}') + ';return Source')(P.requeueWaiting, P.takeRequeue, async () => false, {}, {})
            let fail = true, requeued = 0, soon = 0
            const start = () => Object.assign(new Source(), { pair: { f: 'f'.repeat(12) }, base: [{ id: 1 }], manifest: {}, meta: {},
              flushSoon: () => { soon++ },
              changes: { load: async () => {}, requeue: async () => { if (fail) throw new Error('synthetic storage failure'); requeued++ } } })
            mem.set('bp-requeue', '1')
            const first = await start().ready().then(() => 'opened', e => e.message)          // the library opens all the same
            const kept = mem.get('bp-requeue') ?? null
            fail = false
            const second = await start().ready().then(() => 'opened', e => e.message)         // the next start
            console.log(JSON.stringify({ first, kept, second, left: mem.get('bp-requeue') ?? null, requeued, soon }))
        """)
        self.assertEqual(out, {'first': 'opened', 'kept': '1', 'second': 'opened', 'left': None, 'requeued': 1, 'soon': 1})

    def canvas_after_its_receipt(self, lost, marker):
        return test_phone_resend.run(test_phone_resend.JOURNAL + """
            const local = status => ({ base: null, result: { id: 'x', name: '', items: [] }, assets: [], status })
            const P = { f: 'c'.repeat(12), l: 'L' }
            const c = new Changes()
            await c.add({ op: 'fav', uid: 'A', on: true })
            await c.add({ op: 'canvas', op_id: 'd'.repeat(32), canvas_id: 'e'.repeat(32), proposal: {}, refs: {}, sizes: {}, canvasLocal: local('pending') })
            const upload = async doc => { sent.push(structuredClone(doc)); if (__LOST__) throw new Error('synthetic lost answer'); return 'chg-' + sent.length }
            await c.flush(upload, 'phone', true, true).catch(() => {})
            if (__MARKER__) R.markResend(P)                                   // paired again before the PC's canvas result came
            await c.prune(0, { delivery: 2, published: 5, receipts: { [sent[0].stream]: { device: 'phone', seq: 1 } } }, P)   // batch 1 applied
            await c.flush(send, 'phone', true, true)
            console.log(JSON.stringify({ sent: sent.map(d => [d.seq, d.changes.map(x => x.uid ?? x.op)]),
              list: c.list.map(e => [e.op, e.state, e.seq ?? null, !!e.resend]), resending: c.resending(true) }))
        """, STATE=None, LOST=lost, MARKER=marker)

    def test_a_canvas_change_in_an_acknowledged_batch_is_never_sent_again(self):
        for lost, marker in ((True, False), (False, True)):         # its upload's answer lost; or paired again meanwhile
            with self.subTest(lost=lost, marker=marker):
                self.assertEqual(self.canvas_after_its_receipt(lost, marker),
                                 {'sent': [[1, ['A', 'canvas']]], 'list': [['canvas', 'sent', 1, False]], 'resending': 0})


class PcIntake(base.Fixture):
    def numbered(self, seq, changes, stream=S):
        doc = {'format': 1, 'device': 'probe-phone', 'at': 100 * seq, 'stream': stream, 'seq': seq, 'acked': 0, 'changes': changes}
        return self.drive.put(*self.key.seal_change(doc))

    def notes(self, slug):
        return sorted(p.name for p in self.note.parent.glob(slug + '*.md'))

    def test_a_thumbnail_the_pc_cannot_read_skips_only_its_change(self):
        buf = io.BytesIO()
        Image.new('RGB', (64, 64), (200, 30, 30)).save(buf, 'JPEG')
        cut = base64.b64encode(buf.getvalue()[:len(buf.getvalue()) // 2]).decode()      # a picture cut short
        odd = base64.b64encode(b'not a picture at all').decode()                         # base64, but not a picture
        uid = 'cd' * 16
        self.numbered(1, [{'op': 'link', 'uid': uid, 'url': 'https://example.com/odd-picture', 'note': '', 'category': '', 'at': 100}])
        for seq, thumb in ((2, odd), (3, cut)):
            self.numbered(seq, [{'op': 'details', 'uid': uid, 'title': 'Odd', 'creator': '', 'desc': '', 'thumb': thumb, 'at': 100 * seq}])
        self.put('A', 400, 4)
        self.svc._intake()
        row = self.fx.writer.read(lambda db: dict(db.conn.execute('SELECT thumb_path, short_desc FROM items WHERE uid = ?', (uid,)).fetchone()))
        self.assertEqual(row, {'thumb_path': '', 'short_desc': ''})       # each details change skipped whole
        self.assertEqual(self.counts('A'), (1,))
        self.assertEqual(self.receipt(), {'seq': 4})
        self.assertEqual(self.changes_left(), [])

    def test_a_note_a_failed_file_made_goes_with_it(self):
        self.numbered(1, [{'op': 'answer', 'md': '# Phone answer probe\n\nBody', 'ids': [], 'file': 'phone-answer.md', 'at': 100}])
        original, calls = Database.reindex_notes, []

        def disk_full_once(db):
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError('synthetic disk full while the notes reindex')
            return original(db)
        with mock.patch.object(Database, 'reindex_notes', disk_full_once):
            self.svc._intake()
            self.assertEqual(self.notes('phone-answer-probe'), [])       # undone with the file
            self.svc._intake()
        self.assertEqual(self.notes('phone-answer-probe'), ['phone-answer-probe.md'])
        self.assertEqual(self.receipt(), {'seq': 1})

    def test_files_that_only_wait_force_no_publish(self):
        self.put('A', 100, 1)
        self.assertTrue(self.svc._intake())
        self.put('C', 100, 1)                    # another file under an applied number: refused, retained
        self.put('B', 300, 3)                    # 2 has not arrived: held
        self.assertTrue(self.svc._intake())      # the manifest asks for 2
        self.assertEqual(self.receipt(), {'seq': 1, 'want': 2})
        self.assertFalse(self.svc._intake())     # nothing moved: no publish forced, the next look backs off
        self.assertEqual(len(self.changes_left()), 2)

    def test_a_numbered_file_without_acked_waits_and_the_rest_still_applies(self):
        early = '0' * 32                         # sorted before S, so the other files come after it
        doc = self.doc('B', 300, 3, stream=early)
        del doc['acked']
        held = self.drive.put(*self.key.seal_change(doc))
        self.put('A', 100, 1)
        self.svc._intake()
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual((self.receipt(), self.receipt(early)), ({'seq': 1}, {'seq': 0, 'want': 1}))
        self.assertEqual(self.changes_left(), [held])

    def test_a_phone_with_two_records_is_listed_once_by_its_newest(self):
        self.drive.put(*mirror.seal_phone(self.key, D, 'Pixel 8', T0))
        self.drive.put(*mirror.seal_phone(self.key, D, 'Pixel 8', T0 + 600_000))         # a copy a create answered twice left
        self.drive.put(*mirror.seal_phone(self.key, 'pabcdefabcd', 'Tablet', T0 + 300_000))
        self.svc._intake()
        self.assertEqual(self.svc.status()['phones'], [{'device': D, 'name': 'Pixel 8', 'seen': T0 + 600_000},
                                                       {'device': 'pabcdefabcd', 'name': 'Tablet', 'seen': T0 + 300_000}])


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Record(unittest.TestCase):
    setUp = test_phone_record.Transport.setUp
    page = test_phone_record.Transport.page

    def test_a_create_whose_answer_was_lost_is_made_once(self):
        dev_drive.FakeDrive(self.root / 'drive').put(self.key.name(sync_license.LOGICAL), self.grant)
        srv = dev_drive.serve(self.root / 'drive', port=0)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        out = self.page("""
            const { kv } = await import('./web/src/mobile/store.ts')
            const store = new Map()
            kv.get = async k => structuredClone(store.get(k)); kv.set = async (k, v) => { store.set(k, structuredClone(v)) }; kv.del = async k => { store.delete(k) }
            const real = globalThis.fetch
            let posts = 0
            globalThis.fetch = async (url, init = {}) => {
              const u = new URL(url), r = await real(__BASE__ + u.pathname + u.search, init)
              if ((init.method ?? 'GET') === 'POST' && ++posts === 1) throw new TypeError('synthetic lost answer')    // made, the answer lost
              return r
            }
            const drive = new Drive('https://www.googleapis.com', () => 'synthetic', () => {})
            const pair = { f: key.fingerprint }, D = 'p0123456789'
            const first = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', 1793400000000).catch(e => e.message)
            const second = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', 1793400060000)
            const name = await R.phoneRecordName(key, D), left = await drive.named(name)
            console.log(JSON.stringify({ first, second, posts, left: left.length,
              seen: (await R.openPhoneRecord(key, name, await drive.get(left[0].id))).seen }))
        """, BASE=f'http://127.0.0.1:{srv.server_address[1]}')
        self.assertEqual(out, {'first': 'Google Drive is out of reach (synthetic lost answer)', 'second': 'written', 'posts': 1,
                               'left': 1, 'seen': 1793400060000})

    def test_unpair_during_the_first_wait_of_a_write_leaves_no_record(self):
        out = test_phone_record.record("""
            const get = kv.get
            let slow = true
            kv.get = async k => { if (slow) { slow = false; await new Promise(r => setTimeout(r, 40)) } return get(k) }
            const writing = R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0)
            await new Promise(r => setTimeout(r, 10))                         // the write waits for its stored state
            const dropped = await R.dropPhoneRecord(drive, key, pair, D)
            console.log(JSON.stringify({ wrote: await writing, dropped, files: files.size, log, state: state() }))
        """)
        self.assertEqual(out, {'wrote': 'stopped', 'dropped': 'none', 'files': 0, 'log': ['named'], 'state': None})


if __name__ == '__main__':
    unittest.main()
