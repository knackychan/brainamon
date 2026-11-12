"""D13: the phone's own record in the app data folder (web/src/mobile/mirror/phone-record.ts), read by the PC's Phones list
(library/mirror.py open_phone, server/sync.py _read_phones). Node runs the phone's code; Python checks the PC's side. Synthetic
keys, grants and Drives only (a fake in Node, server/dev_drive.py and tests/test_sync.FakeDrive in Python).
Plan: docs/superpowers/plans/2026-10-31-phone-backup-phones/03-d13-phone-record.md."""
import base64
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import license, sync_license
from library import mirror
from server import dev_drive
from tests import test_phone_js, test_sync

D = 'p0123456789'
T0 = 1_793_400_000_000
MIN = 60_000

# the phone's kv in memory, the record module, two keys and a Drive in memory that logs each call
RECORD = """
    const { kv } = await import('./web/src/mobile/store.ts')
    const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
    const { DriveError } = await import('./web/src/mobile/mirror/drive.ts')
    const R = await import('./web/src/mobile/mirror/phone-record.ts')
    const store = new Map()
    kv.get = async k => structuredClone(store.get(k))
    kv.set = async (k, v) => { store.set(k, structuredClone(v)) }
    kv.del = async k => { store.delete(k) }
    const key = await MirrorKey.fromText(__KEY__), other = await MirrorKey.fromText(__OTHER__)
    const pair = { f: key.fingerprint }, D = __D__, T0 = __T0__, MIN = 60000
    const files = new Map(), log = [], fail = {}
    let n = 0
    const drive = {
      async named(name, signal) { log.push('named'); signal?.throwIfAborted(); return [...files].filter(([, f]) => f.name === name).map(([id, f]) => ({ id, size: f.data.length })) },
      async get(id) { log.push('get ' + id); const f = files.get(id); if (!f) throw new DriveError('Google Drive answered 404', 404); return f.data },
      async create(name, data, signal) {
        log.push('create'); signal?.throwIfAborted()
        const id = 'r' + ++n
        files.set(id, { name, data })
        if (fail.lost) { fail.lost = false; throw new DriveError('Google Drive is out of reach (no answer in 20 s)') }
        return id
      },
      async update(id, data, signal) {
        log.push('update ' + id); signal?.throwIfAborted()
        if (fail.update) throw new DriveError('Google Drive answered ' + fail.update, fail.update)
        const f = files.get(id)
        if (!f) throw new DriveError('Google Drive answered 404', 404)
        f.data = data
      },
      async remove(id, signal) { log.push('remove ' + id); signal?.throwIfAborted(); files.delete(id) },
    }
    const open = async id => R.openPhoneRecord(key, files.get(id).name, files.get(id).data)
    const state = () => store.get('phone_record') ?? null
"""

# the phone page's storage and network for the real Drive class (tests/test_licensed_sync.py PhoneTransport)
PAGE = """
    const mem = new Map(), session = new Map()
    globalThis.localStorage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)), removeItem: k => mem.delete(k) }
    globalThis.sessionStorage = { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, String(v)), removeItem: k => session.delete(k) }
    globalThis.window = new EventTarget(); globalThis.document = new EventTarget()
    Object.defineProperty(navigator, 'onLine', { value: true })
    Object.defineProperty(navigator, 'connection', { value: Object.assign(new EventTarget(), { type: 'wifi' }) })
    globalThis.__LICENSE_PUBLIC_KEYS__ = __PUBLIC__
    const P = await import('./web/src/mobile/mirror/pairing.ts')
    const { secrets } = await import('./web/src/mobile/native.ts')
    const { Drive, DriveError } = await import('./web/src/mobile/mirror/drive.ts')
    const R = await import('./web/src/mobile/mirror/phone-record.ts')
    const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
    const pairWith = async p => { secrets.set('bp-pair', JSON.stringify(p)); await P.validateStoredPairing() }
    await pairWith(__PAIR__)
    const key = await MirrorKey.fromText(__PAIR__.k)
"""


def run(script: str, **values) -> dict:
    for name, value in values.items():
        script = script.replace(f'__{name}__', json.dumps(value))
    return json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + script))


def record(script: str, **values) -> dict:
    return run(RECORD + script, KEY=mirror.MirrorKey.generate().text(), OTHER=mirror.MirrorKey.generate().text(), D=D, T0=T0,
               **values)


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Sealing(unittest.TestCase):
    def test_a_record_sealed_on_the_phone_opens_on_the_pc_and_back(self):
        key, other = mirror.MirrorKey.generate(), mirror.MirrorKey.generate()
        names = ['Pixel 8', 'x' * 61, '\U0001F600' * 61, " Fred's\nPixel\t 8 ", '\x07\x08', 'Ünïcødé ' + 'é' * 70]
        pc_name, pc_blob = mirror.seal_phone(key, D, 'Galaxy A54', T0)
        _, foreign = mirror.seal_phone(other, D, 'Galaxy A54', T0)
        forged = key.seal(pc_name, mirror._json({'v': 1, 'device': 'pffffffffff', 'name': 'X', 'seen': 1}))
        out = run("""
            const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
            const R = await import('./web/src/mobile/mirror/phone-record.ts')
            const key = await MirrorKey.fromText(__KEY__)
            const b64 = a => Buffer.from(a).toString('base64'), bytes = s => new Uint8Array(Buffer.from(s, 'base64'))
            const sealed = []
            for (const [i, name] of __NAMES__.entries()) sealed.push(await R.sealPhoneRecord(key, __D__, name, __T0__ + i))
            const opened = await R.openPhoneRecord(key, __PC_NAME__, bytes(__PC_BLOB__))
            const refused = [await R.openPhoneRecord(key, __PC_NAME__, bytes(__FOREIGN__)),
              await R.openPhoneRecord(key, __PC_NAME__, bytes(__FORGED__)),
              await R.openPhoneRecord(key, __PC_NAME__, new Uint8Array(4097))]
            console.log(JSON.stringify({ sealed: sealed.map(([n, b]) => [n, b64(b)]), opened, refused,
              name: await R.phoneRecordName(key, __D__) }))
        """, KEY=key.text(), NAMES=names, D=D, T0=T0, PC_NAME=pc_name, PC_BLOB=base64.b64encode(pc_blob).decode(),
                  FOREIGN=base64.b64encode(foreign).decode(), FORGED=base64.b64encode(forged).decode())
        self.assertEqual(out['name'], mirror.phone_name(key, D))
        want = ['Pixel 8', 'x' * 60, '\U0001F600' * 60, "Fred's Pixel 8", 'Phone', 'Ünïcødé ' + 'é' * 52]
        for i, ((name, blob), expected) in enumerate(zip(out['sealed'], want)):
            self.assertEqual(name, mirror.phone_name(key, D))
            self.assertEqual(mirror.open_phone(key, name, base64.b64decode(blob)), {'device': D, 'name': expected, 'seen': T0 + i})
        self.assertEqual(out['opened'], {'device': D, 'name': 'Galaxy A54', 'seen': T0})
        self.assertEqual(out['refused'], [None, None, None])


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Writing(unittest.TestCase):
    def test_written_once_then_every_30_minutes_and_at_once_for_a_new_name(self):
        out = record("""
            const out = []
            for (const [name, t] of [['Pixel 8', T0], ['Pixel 8', T0 + 29 * MIN], ['Pixel 8', T0 + 30 * MIN], ['Fred phone', T0 + 31 * MIN]])
              out.push(await R.syncPhoneRecord(drive, key, pair, D, name, t))
            console.log(JSON.stringify({ out, log, files: files.size, record: await open('r1'), state: state() }))
        """)
        self.assertEqual(out['out'], ['written', 'fresh', 'written', 'written'])
        self.assertEqual(out['log'], ['named', 'create', 'update r1', 'update r1'])
        self.assertEqual((out['files'], out['record']), (1, {'device': D, 'name': 'Fred phone', 'seen': T0 + 31 * MIN}))
        self.assertEqual(out['state'], {'f': out['state']['f'], 'd': D, 'id': 'r1', 'name': 'Fred phone', 'at': T0 + 31 * MIN})

    def test_a_lost_answer_a_cleared_phone_and_a_removed_record_leave_one_record(self):
        out = record("""
            fail.lost = true
            const out = [await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0).catch(e => e.message)]   // made, the answer lost
            out.push(await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 + MIN))
            store.clear()                                                                       // the phone's storage cleared
            out.push(await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 + 2 * MIN))
            files.clear()                                                                       // the record removed meanwhile
            out.push(await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 + 40 * MIN))
            console.log(JSON.stringify({ out, log, ids: [...files.keys()], seen: (await open([...files.keys()][0])).seen }))
        """)
        self.assertEqual(out['out'], ['Google Drive is out of reach (no answer in 20 s)', 'written', 'written', 'written'])
        self.assertEqual(out['log'], ['named', 'create', 'named', 'get r1', 'update r1', 'named', 'get r1', 'update r1',
                                      'update r1', 'named', 'create'])
        self.assertEqual((out['ids'], out['seen']), (['r2'], T0 + 40 * MIN))

    def test_copies_of_its_record_go_and_files_that_do_not_open_stay(self):
        out = record("""
            const name = await R.phoneRecordName(key, D)
            files.set('x1', { name, data: (await R.sealPhoneRecord(key, D, 'Old', T0 - 100 * MIN))[1] })
            files.set('x2', { name, data: (await R.sealPhoneRecord(key, D, 'Old', T0 - 90 * MIN))[1] })
            files.set('x3', { name, data: new Uint8Array([1, 2, 3]) })
            files.set('x4', { name, data: await key.seal(name, new TextEncoder().encode(JSON.stringify({ device: 'pffffffffff', name: 'X', seen: 1, v: 1 }))) })
            const out = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0)
            console.log(JSON.stringify({ out, log, ids: [...files.keys()].sort(), name: (await open('x1')).name, id: state().id }))
        """)
        self.assertEqual(out, {'out': 'written', 'log': ['named', 'get x1', 'get x2', 'get x3', 'get x4', 'update x1', 'remove x2'],
                               'ids': ['x1', 'x3', 'x4'], 'name': 'Pixel 8', 'id': 'x1'})

    def test_overlapping_reads_write_once_a_failure_counts_for_nothing_and_a_clock_set_back_writes(self):
        out = record("""
            const both = await Promise.all([R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0), R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0)])
            fail.update = 500
            const failed = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 + 31 * MIN).catch(e => e.status)
            fail.update = 0
            const retried = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 + 32 * MIN)
            const back = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 - 24 * 60 * MIN)       // the clock set back a day
            const after = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 - 24 * 60 * MIN + MIN)
            console.log(JSON.stringify({ both, failed, retried, back, after, log, files: files.size, at: state().at }))
        """)
        self.assertEqual(out, {'both': ['written', 'fresh'], 'failed': 500, 'retried': 'written', 'back': 'written', 'after': 'fresh',
                               'log': ['named', 'create', 'update r1', 'update r1', 'update r1'], 'files': 1,
                               'at': T0 - 24 * 60 * MIN})

    def test_another_pairing_or_device_gets_its_own_record_and_a_solo_phone_writes_none(self):
        out = record("""
            await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0)
            const solo = await R.syncPhoneRecord(drive, key, { f: key.fingerprint, solo: true }, D, 'Pixel 8', T0 + 40 * MIN)
            const again = await R.syncPhoneRecord(drive, other, { f: other.fingerprint }, D, 'Pixel 8', T0 + MIN)    // paired with another PC
            const device = await R.syncPhoneRecord(drive, other, { f: other.fingerprint }, 'pabcdefabcd', 'Pixel 8', T0 + 2 * MIN)
            const names = [...files.values()].map(f => f.name)
            console.log(JSON.stringify({ solo, again, device, log, names: [names[0] === await R.phoneRecordName(key, D),
              names[1] === await R.phoneRecordName(other, D), names[2] === await R.phoneRecordName(other, 'pabcdefabcd')],
              state: [state().f === other.fingerprint, state().d, state().id] }))
        """)
        self.assertEqual(out, {'solo': 'solo', 'again': 'written', 'device': 'written',
                               'log': ['named', 'create', 'named', 'create', 'named', 'create'], 'names': [True, True, True],
                               'state': [True, 'pabcdefabcd', 'r3']})


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Dropping(unittest.TestCase):
    def test_unpair_removes_its_record_and_copies_and_nothing_is_written_after(self):
        out = record("""
            await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0)
            files.set('copy', { ...files.get('r1') })                                           // left by a lost answer
            files.set('t1', { name: await R.phoneRecordName(other, D), data: new Uint8Array([9]) })   // another pairing's
            const dropped = await R.dropPhoneRecord(drive, key, pair, D)
            const after = await R.syncPhoneRecord(drive, key, pair, D, 'Pixel 8', T0 + 40 * MIN)
            const again = await R.dropPhoneRecord(drive, key, pair, D)
            console.log(JSON.stringify({ dropped, after, again, log, ids: [...files.keys()], state: state() }))
        """)
        self.assertEqual(out, {'dropped': 'dropped', 'after': 'stopped', 'again': 'none',
                               'log': ['named', 'create', 'named', 'remove r1', 'remove copy', 'named'], 'ids': ['t1'],
                               'state': None})

    def test_a_hung_drive_gives_up_in_time_and_its_request_is_aborted(self):
        out = record("""
            let aborted = false
            const hung = { ...drive, named: (name, signal) => new Promise((_, no) => signal.addEventListener('abort', () => { aborted = true; no(signal.reason) })) }
            const t = Date.now()
            const out = await R.dropPhoneRecord(hung, key, pair, D, 300)
            const took = Date.now() - t
            console.log(JSON.stringify({ out, aborted, inTime: took >= 250 && took < 2500 }))
        """)
        self.assertEqual(out, {'out': 'stopped', 'aborted': True, 'inTime': True})

    def test_a_write_in_flight_stops_and_a_refused_drive_still_lets_unpair_go_on(self):
        out = record("""
            const slow = { ...drive, create: (name, data, signal) => { log.push('create'); return new Promise((_, no) => signal.addEventListener('abort', () => no(signal.reason))) } }
            const writing = R.syncPhoneRecord(slow, key, pair, D, 'Pixel 8', T0).catch(e => e.name)
            await new Promise(r => setTimeout(r, 50))
            const refused = { ...drive, named: async () => { throw new Error('This phone could not check its access.') } }
            const dropped = await R.dropPhoneRecord(refused, key, pair, D)
            console.log(JSON.stringify({ wrote: await writing, dropped, state: state(), log }))
        """)
        self.assertEqual(out, {'wrote': 'AbortError', 'dropped': 'failed', 'state': None, 'log': ['named', 'create']})


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class Transport(unittest.TestCase):
    """The real Drive class: against server/dev_drive.py (the PATCH Google's files.update takes), and a fetch that records."""

    def setUp(self):
        from tests.license_fixture import activate
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        activate(self, self.root)
        self.key = mirror.MirrorKey.generate()
        signer = sync_license.signer(self.root / 'control.pem', create=True)
        self.grant = self.key.seal(sync_license.LOGICAL, sync_license.record(self.key, signer))
        self.pair = {'v': 2, 'k': self.key.text(), 'f': self.key.fingerprint, 'l': sync_license.public(signer), 'c': '', 'e': '',
                     'ai': {}, 'at': 1}

    def page(self, script, **values):
        return run(PAGE + script, PUBLIC=list(license.PUBLIC_KEYS), PAIR=self.pair, **values)

    def test_update_replaces_the_bytes_in_place_on_the_dev_drive(self):
        dev_drive.FakeDrive(self.root / 'drive').put(self.key.name(sync_license.LOGICAL), self.grant)
        srv = dev_drive.serve(self.root / 'drive', port=0)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        out = self.page("""
            const real = globalThis.fetch, sent = []
            globalThis.fetch = async (url, init = {}) => {
              const u = new URL(url)
              sent.push({ method: init.method ?? 'GET', path: u.pathname + u.search, type: init.headers?.['Content-Type'] ?? '',
                body: init.body ? Buffer.from(init.body).toString('latin1') : '' })
              return real(__BASE__ + u.pathname + u.search, init)
            }
            const drive = new Drive('https://www.googleapis.com', () => 'synthetic', () => {})
            const [name, first] = await R.sealPhoneRecord(key, 'p0123456789', 'Pixel 8', 1793400000000)
            const id = await drive.create(name, first)
            const [, second] = await R.sealPhoneRecord(key, 'p0123456789', 'Fred phone', 1793400060000)
            await drive.update(id, second)
            const patch = sent.find(r => r.method === 'PATCH')
            const listed = await drive.named(name)
            const same = Buffer.from(await drive.get(id)).equals(Buffer.from(second))
            await drive.remove(id); await drive.remove(id)                                       // already gone is fine
            const missing = await drive.update(id, second).then(() => 0, e => e instanceof DriveError ? e.status : -1)
            console.log(JSON.stringify({ id, patch, second: Buffer.from(second).toString('latin1'), listed, same, missing,
              after: (await drive.named(name)).length }))
        """, BASE=f'http://127.0.0.1:{srv.server_address[1]}')
        self.assertEqual(out['patch']['path'], f"/upload/drive/v3/files/{out['id']}?uploadType=multipart&fields=id")
        b = re.fullmatch(r'multipart/related; boundary=(bp[0-9a-f]+)', out['patch']['type']).group(1)
        self.assertEqual(out['patch']['body'], f'--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{{}}\r\n'
                                               f'--{b}\r\nContent-Type: application/octet-stream\r\n\r\n' + out['second'] + f'\r\n--{b}--')
        self.assertEqual(out['listed'], [{'id': out['id'], 'size': len(out['second'].encode('latin1'))}])     # its name and id kept
        self.assertEqual((out['same'], out['missing'], out['after']), (True, 404, 0))

    def test_a_solo_phone_replaces_nothing_and_a_stopped_call_sends_nothing(self):
        out = self.page("""
            const control = __GRANT__, sent = []
            globalThis.fetch = async (url, init = {}) => {
              const u = new URL(url)
              if (u.pathname === '/drive/v3/files' && u.searchParams.get('q') === "name = '" + __V2CONTROL__ + "'")
                return Response.json({ files: [] })
              if (u.pathname === '/drive/v3/files' && u.searchParams.get('q') === "name = '" + __CONTROL__ + "'")
                return Response.json({ files: [{ id: 'control', size: '10000' }] })
              if (u.pathname === '/drive/v3/files/control') return new Response(Buffer.from(control, 'base64'))
              sent.push((init.method ?? 'GET') + ' ' + u.pathname + u.search)
              if (u.pathname.endsWith('/hang')) return new Promise((_, no) => init.signal.addEventListener('abort', () => no(init.signal.reason)))
              return Response.json({ id: 'a/b' })
            }
            const drive = new Drive('https://www.googleapis.com', () => 'synthetic', () => {})
            await drive.update('a/b', new Uint8Array([1, 2]))
            const before = new AbortController(); before.abort()
            const early = await drive.remove('rec', before.signal).catch(e => e.name)
            const during = new AbortController()
            setTimeout(() => during.abort(), 100)
            const t = Date.now()
            const late = await drive.remove('hang', during.signal).catch(e => e.name)
            const took = Date.now() - t
            await pairWith({ ...__PAIR__, solo: true })
            const solo = await new Drive('https://www.googleapis.com', () => 'synthetic', () => {}).update('rec', new Uint8Array([1]))
              .catch(e => e instanceof DriveError ? e.message : 'other')
            console.log(JSON.stringify({ sent, early, late, quick: took < 2000, solo }))
        """, GRANT=base64.b64encode(self.grant).decode(), CONTROL=self.key.name(sync_license.LOGICAL),
             V2CONTROL=self.key.name(sync_license.ACCESS_LOGICAL))
        self.assertEqual(out, {'sent': ['PATCH /upload/drive/v3/files/a%2Fb?uploadType=multipart&fields=id', 'DELETE /drive/v3/files/hang'],
                               'early': 'AbortError', 'late': 'AbortError', 'quick': True,
                               'solo': 'Standalone phones do not replace files in Google Drive.'})


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class PcList(unittest.TestCase):
    """The PC's Phones list reads what the phone sealed, and sees a record replaced in place (Drive gives it a new time)."""

    def setUp(self):
        self.fx = test_sync.ServiceTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.addCleanup(self.fx.tearDown)
        self.svc, self.drive = self.fx.svc, self.fx.drive
        self.svc.ensure_running = lambda: None
        self.key, _ = self.fx.access_ready()

    def sealed(self, name, seen):
        out = run("""
            const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
            const R = await import('./web/src/mobile/mirror/phone-record.ts')
            const [name, blob] = await R.sealPhoneRecord(await MirrorKey.fromText(__KEY__), __D__, __NAME__, __SEEN__)
            console.log(JSON.stringify({ name, blob: Buffer.from(blob).toString('base64') }))
        """, KEY=self.key.text(), D=D, NAME=name, SEEN=seen)
        return out['name'], base64.b64decode(out['blob'])

    def test_the_pc_lists_the_phone_by_name_and_last_sync(self):
        times = {}
        listing = self.drive.list
        with mock.patch.object(self.drive, 'list', lambda: [dict(f, modifiedTime=times.get(f['id'], '1')) for f in listing()]):
            rid = self.drive.put(*self.sealed("Fred's Pixel 8", T0))
            self.assertFalse(self.svc._intake())
            self.assertEqual(self.svc.status()['phones'], [{'device': D, 'name': "Fred's Pixel 8", 'seen': T0}])
            name, blob = self.sealed("Fred's Pixel 8", T0 + 31 * MIN)
            self.drive.files[rid] = (name, blob)                                    # Drive.update: same id, new bytes and time
            times[rid] = '2'
            self.assertFalse(self.svc._intake())
            self.assertEqual(self.svc.status()['phones'], [{'device': D, 'name': "Fred's Pixel 8", 'seen': T0 + 31 * MIN}])


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class SourceWiring(unittest.TestCase):
    """source/mirror.ts pulls in the whole page: its rows, watch and record calls run here from the source, with stubs."""

    def test_only_a_complete_read_or_a_look_at_the_same_upload_records(self):
        out = run(r"""
            const fs = await import('node:fs')
            const { stripTypeScriptTypes } = await import('node:module')
            const src = fs.readFileSync('web/src/mobile/source/mirror.ts', 'utf8').replace(/\r\n/g, '\n')   // a CRLF checkout too
            const pick = re => src.match(re)[0]
            const body = [pick(/  get solo\(\) .*\n/), pick(/  private full = .*\n/), pick(/  recorded: .*\n/),
              pick(/  private recordSoon\(\) \{[\s\S]*?\n  }\n/), pick(/  rows\([\s\S]*?\n  }\n/),
              pick(/  private async readRows\([\s\S]*?\n  }\n/),
              pick(/  watch\([\s\S]*?\n  }\n/)].join('\n')
            let look = null, fail = '', refused = '', parts = ''
            const calls = []
            globalThis.window = { setInterval: f => { look = f; return 1 } }
            globalThis.document = Object.assign(new EventTarget(), { hidden: false })
            Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
            const sync = async (drive, key, pair, device, name) => { calls.push([pair.f, device, name]); if (fail) throw new Error(fail); return 'written' }
            const Source = new Function('token', 'SOLO_MANIFEST', 'pool', 'syncPhoneRecord', 'deviceId', 'deviceName', 'syncPaused',
              'cloudRevision', 'cloudCheckpoint', 'cloudStopped', 'reconnecting', 'say', stripTypeScriptTypes('class Source {\n' + body + '\n}') + ';return Source')(
              () => 'synthetic', { published: 0, files: {} }, (list, n, f) => Promise.all(list.map(f)), sync, () => 'p0123456789',
              async () => 'Pixel 8', () => false, () => 0, () => {}, () => false, () => false, (_w, _k, _p, fallback) => fallback)
            const s = new Source()
            const part = 'library/part-0001.json'
            let manifest = { published: 5, files: { [part]: { v: '1' } } }
            Object.assign(s, { pair: { f: 'f'.repeat(12) }, drive: { checkpoint: () => {} }, key: Promise.resolve({}), manifest: null, base: [], rowsNow: [],
              byId: new Map(), looked: 0, lastError: '', ready: async () => {}, once: (_k, f) => f(), setRows() {}, cats: () => [],
              reconcileCanvas: async () => {}, background() {}, flushSoon() {}, names: () => [part],
              cached: async k => { if (k === part && parts) throw new Error(parts); return k === part ? '[]' : '{}' },
              loadManifest: async () => { if (refused) throw new Error(refused); s.manifest = manifest; return manifest } })
            const seen = []
            const step = async label => { await s.recorded; seen.push([label, calls.length]) }
            refused = 'This phone could not check its access.'
            await s.rows().catch(() => {}); await step('refused')
            refused = ''; parts = 'Google Drive is out of reach (no answer in 20 s)'
            await s.rows().catch(() => {}); await step('parts failed')
            parts = ''
            await s.rows(); await step('complete')
            fail = 'Google Drive answered 500'
            await s.rows(); await step('record failed')
            const lastError = s.lastError
            fail = ''
            s.watch(() => {}, () => {})
            s.looked = 0; await look(); await step('same upload')
            manifest = { published: 6, files: { [part]: { v: '2' } } }; parts = 'Google Drive is out of reach (no answer in 20 s)'
            s.looked = 0; await look(); await step('new upload, parts failed')
            s.looked = 0; await look(); await step('same upload, not read whole')
            s.pair.solo = true; s.recordSoon(); await step('solo')
            console.log(JSON.stringify({ seen, lastError, call: calls[0] }))
        """)
        self.assertEqual(out, {'seen': [['refused', 0], ['parts failed', 0], ['complete', 1], ['record failed', 2], ['same upload', 3],
                                        ['new upload, parts failed', 3], ['same upload, not read whole', 3], ['solo', 3]],
                               'lastError': '', 'call': ['f' * 12, D, 'Pixel 8']})


if __name__ == '__main__':
    unittest.main()
