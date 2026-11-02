"""Vault sync, phone side (projects/vault-sync/plans/03-phone-side.md): the TypeScript merge gives the same plans as
library/vault_sync.py on tests/fixtures/vault_cases.json, the content id and sealing agree with Python, and a whole
phone round works against a PC-sealed Drive. Node 22.6+ (skips without it)."""
import base64
import json
import unittest
from datetime import datetime
from pathlib import Path

from library import mirror, vault_sync as V
from tests.test_phone_js import TS_RESOLVE, _node_ok, node

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'vault_cases.json').read_text(encoding='utf-8'))
KEY = mirror.MirrorKey(bytes(range(32)))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class VaultJsTest(unittest.TestCase):
    def test_progress_waits_for_more_than_the_first_parallel_batch(self):
        node("""
            import assert from 'node:assert/strict'
            import { progress } from './web/src/lib/progress.ts'
            assert.equal(progress(10, 2827, 1000, 213000).left, '')
            assert.equal(progress(30, 2827, 1000, 5000).left, '')
            assert.deepEqual(progress(30, 60, 1000, 61000), { pct: 50, left: 'about 1 min left' })
            assert.deepEqual(progress(60, 60, 1000, 121000), { pct: 100, left: '' })
        """)

    def test_merge_matches_the_fixture(self):
        self.assertEqual(len(CASES), 46)
        out = json.loads(node(f"""
            import {{ mergeVault }} from './web/src/mobile/vault/merge.ts'
            const cases = {json.dumps(CASES)}
            const when = new Date(2026, 9, 12, 9, 30)
            console.log(JSON.stringify(cases.map(c => {{
              const p = mergeVault(c.base, c.mine, c.theirs, c.role, when, {{ generated: c.generated ? new Set(c.generated) : null, removed: c.removed, mineHash: c.mine_hash, fresh: c.fresh, kept: c.kept }})
              return {{ pull: p.pull, trash: [...p.trash].sort(), conflicts: p.conflicts, lost: [...p.lost].sort(), legacy: [...p.legacy].sort(), new_base: p.new_base, brake: p.brake }} }})))
        """))
        for c, got in zip(CASES, out):
            self.assertEqual(got, c['expect'], c['name'])

    def test_brake_and_exclusions_match(self):
        base = {f'f{i}.md': 'x' for i in range(500)}
        out = json.loads(node(f"""
            import {{ mergeVault, excluded, validRel }} from './web/src/mobile/vault/merge.ts'
            const base = {json.dumps(base)}
            const keep = n => Object.fromEntries(Object.entries(base).slice(n))
            const when = new Date(2026, 9, 12, 9, 30)
            const paths = {json.dumps(['a.md', '.obsidian/app.json', '.obsidian/plugins/p/x.js', '.obsidian/themes/t.css', '.obsidian/workspace.json', '.trash/a.md', '.git/HEAD', 'a.md.vsync-tmp', '.nomedia', 'x/.nomedia', '.brainamon/manifest.json', '.brainamon'])}
            const bad = {json.dumps(['', '/a', '../a', 'a/../b', 'a\\\\b', 'C:x', 'a//b', './a'])}
            console.log(JSON.stringify([mergeVault(base, base, keep(20), 'phone', when).brake, mergeVault(base, base, keep(21), 'phone', when).brake,
              paths.map(excluded), bad.map(validRel)]))
        """))
        self.assertEqual(out[:2], [False, True])
        self.assertEqual(out[2], [V.excluded(p) for p in ['a.md', '.obsidian/app.json', '.obsidian/plugins/p/x.js', '.obsidian/themes/t.css',
                                                          '.obsidian/workspace.json', '.trash/a.md', '.git/HEAD', 'a.md.vsync-tmp', '.nomedia', 'x/.nomedia',
                                                          '.brainamon/manifest.json', '.brainamon']])
        self.assertEqual(out[2][-2:], [True, True])
        self.assertEqual(out[3], [False] * 8)

    def test_index_codec_matches_python(self):
        """The phone reads what the PC writes (vault, generated, removed) and the PC reads what the phone writes
        (caps); both drop the same bad entries; the old reader sees files and device only."""
        a, b = 'a' * 32, 'b' * 32
        pc = V.encode_index({'a.md': a, 'Brainamon/Items/x-1.md': b}, 'pc', vault='v1',
                            generated=['Brainamon/Items/x-1.md', 'nope.md'],
                            removed={'gone.md': 'c' * 64, 'a.md': 'd' * 64, '../e.md': 'e' * 64, 'f.md': 'zz'})
        out = json.loads(node(f"""
            import {{ decodeIndexFull, decodeIndex, encodeIndex, CAPS }} from './web/src/mobile/vault/merge.ts'
            const f = decodeIndexFull({json.dumps(pc.decode())})
            const phone = new TextDecoder().decode(encodeIndex({{ 'n.md': {json.dumps(a)} }}, 'p1', {{ caps: CAPS, vault: 'v1', kept: {{ 'n.md': 'c'.repeat(64), 'absent.md': 'd'.repeat(64) }} }}))
            const empty = new TextDecoder().decode(encodeIndex({{}}, 'pc', {{ generated: [] }}))
            const classic = new TextDecoder().decode(encodeIndex({{}}, 'pc'))
            console.log(JSON.stringify({{ device: f.device, vault: f.vault, generated: [...f.generated].sort(), removed: f.removed, caps: [...f.caps],
              old: decodeIndex({json.dumps(pc.decode())}), phone, empty, classic, emptyGen: [...decodeIndexFull(empty).generated], classicGen: decodeIndexFull(classic).generated }}))
        """))
        self.assertEqual((out['device'], out['vault'], out['generated'], out['removed'], out['caps']),
                         ('pc', 'v1', ['Brainamon/Items/x-1.md'], {'gone.md': 'c' * 64}, []))
        self.assertEqual(out['old'], {'device': 'pc', 'files': {'a.md': a, 'Brainamon/Items/x-1.md': b}})
        full = V.decode_index_full(out['phone'].encode())
        self.assertEqual((full['device'], full['files'], full['caps'], full['generated']), ('p1', {'n.md': a}, {'generated', 'identity'}, None))
        self.assertEqual(json.loads(out['phone'])['caps'], ['generated', 'identity'])
        self.assertEqual((full['vault'], full['kept']), ('v1', {'n.md': 'c' * 64}))
        self.assertEqual((out['emptyGen'], out['classicGen']), ([], None))
        self.assertEqual(V.decode_index_full(out['empty'].encode())['generated'], set())
        self.assertIsNone(V.decode_index_full(out['classic'].encode())['generated'])

    def test_whole_round_against_a_pc_sealed_drive(self):
        data = {'Ideas/a.md': 'from the pc', 'b.md': 'second'}
        drive = {}
        index = {}
        for rel, text in data.items():
            cid = KEY.content_id(text.encode())
            index[rel] = cid
            drive[V.blob_name(cid)] = base64.b64encode(KEY.seal(V.blob_logical(cid), text.encode())).decode()
        drive[V.index_name(KEY, 'pc')] = base64.b64encode(KEY.seal(V.INDEX_LOGICAL, V.encode_index(index, 'pc'))).decode()
        status = {'state': 'syncing', 'step': 'Sending to Drive', 'done': 4, 'total': 9, 'since': 3, 'reason': '', 'summary': '', 'last': 1, 'at': 2}
        drive[V.status_name(KEY)] = base64.b64encode(KEY.seal(V.STATUS_LOGICAL, json.dumps(status).encode())).decode()
        out = json.loads(node(f"""{TS_RESOLVE}
            const {{ MirrorKey }} = await import('./web/src/mobile/mirror/crypto.ts')
            const {{ pcStatus, vaultRound }} = await import('./web/src/mobile/vault/sync.ts')
            const key = await MirrorKey.fromText({json.dumps(KEY.text())})
            const files = new Map(Object.entries({json.dumps(drive)}).map(([n, b]) => [n, {{ id: n, name: n, data: Buffer.from(b, 'base64') }}]))
            const drive = {{ list: async () => [...files.values()].map(f => ({{ id: f.id, name: f.name, size: f.data.length }})),
              get: async id => new Uint8Array(files.get(id).data), remove: async id => {{ files.delete(id) }},
              create: async (name, data) => {{ files.set(name, {{ id: name, name, data: Buffer.from(data) }}); return name }} }}
            const mem = new Map([['phone-only.md', new TextEncoder().encode('from the phone')]])
            const fs = {{ list: async () => [...mem].map(([path, b]) => ({{ path, size: b.length, mtime: 1 }})), read: async p => mem.get(p),
              write: async (p, b) => {{ mem.set(p, b) }}, remove: async p => {{ mem.delete(p) }}, has: async p => mem.has(p) }}
            let st
            const pc = await pcStatus(drive, key), steps = [], overall = []
            const r = await vaultRound({{ drive, key, fs, device: 'phone-1', force: false, load: async () => st, save: async s => {{ st = s }},
              progress: (step, done, total, o) => {{ steps.push([step, done, total]); overall.push(o) }} }})
            console.log(JSON.stringify({{ r, pc, steps, overall, fs: Object.fromEntries([...mem].map(([p, b]) => [p, new TextDecoder().decode(b)])),
              drive: Object.fromEntries([...files].map(([n, f]) => [n, f.data.toString('base64')])) }}))
        """))
        self.assertEqual(out['r']['state'], 'idle', out['r'])
        self.assertEqual(out['pc'], status)
        taking = [x for x in out['steps'] if x[0] in ("Taking the PC's changes", 'Sending to Drive')]
        self.assertEqual(taking, [["Taking the PC's changes", 0, 2], ["Taking the PC's changes", 1, 2], ['Sending to Drive', 0, 1]])
        # the round reports from its first step on (listing, scanning), and the bar only moves forward
        self.assertEqual([x[0] for x in out['steps']][:3], ['Reading the Drive list', "Reading the PC's file list", 'Listing the vault folder'])
        self.assertEqual(out['overall'], sorted(out['overall']))
        self.assertTrue(0 <= out['overall'][0] and out['overall'][-1] < 1)
        self.assertEqual(out['fs'], {'.nomedia': '', 'Ideas/a.md': 'from the pc', 'b.md': 'second', 'phone-only.md': 'from the phone'})
        name = V.index_name(KEY, 'phone-1')
        device, listed = V.decode_index(KEY.open(V.INDEX_LOGICAL, base64.b64decode(out['drive'][name])))
        self.assertEqual((device, sorted(listed)), ('phone-1', ['Ideas/a.md', 'b.md', 'phone-only.md']))
        cid = KEY.content_id(b'from the phone')
        self.assertEqual(KEY.open(V.blob_logical(cid), base64.b64decode(out['drive'][V.blob_name(cid)])), b'from the phone')

    def _round(self, files_pc, phone, state=None, stop_at=None, drive=None, *, vault='', generated=None, removed=None, extra=''):
        """Run vaultRound over memory stand-ins. `stop_at`: [step, done]: Stop is pressed when the round reports that
        step at that count (the file it is on still finishes). `vault`, `generated`, `removed`: what the PC's list
        carries (spec 1b; a classic list carries only `vault`). `extra`: JavaScript run after the round, with `fs`,
        `mem`, `drive`, `removeLegacy` in scope. Returns the result, whether it saved, the saved state, the phone's
        files and the Drive's files. Pass `drive` (an earlier return) to run a second round on that Drive."""
        if drive is None:
            drive, index = {}, {}
            for rel, text in files_pc.items():
                cid = KEY.content_id(text.encode())
                index[rel] = cid
                drive[V.blob_name(cid)] = base64.b64encode(KEY.seal(V.blob_logical(cid), text.encode())).decode()
            drive[V.index_name(KEY, 'pc')] = base64.b64encode(KEY.seal(V.INDEX_LOGICAL, V.encode_index(
                index, 'pc', vault=vault, generated=generated, removed=removed))).decode()
        return json.loads(node(f"""{TS_RESOLVE}
            const {{ MirrorKey }} = await import('./web/src/mobile/mirror/crypto.ts')
            const {{ vaultRound, removeLegacy }} = await import('./web/src/mobile/vault/sync.ts')
            const key = await MirrorKey.fromText({json.dumps(KEY.text())})
            const files = new Map(Object.entries({json.dumps(drive)}).map(([n, b]) => [n, {{ id: n, name: n, data: Buffer.from(b, 'base64') }}]))
            const drive = {{ list: async () => [...files.values()].map(f => ({{ id: f.id, name: f.name, size: f.data.length }})),
              get: async id => new Uint8Array(files.get(id).data), remove: async id => {{ files.delete(id) }},
              create: async (name, data) => {{ files.set(name, {{ id: name, name, data: Buffer.from(data) }}); return name }} }}
            const mem = new Map(Object.entries({json.dumps(phone)}).map(([p, t]) => [p, new TextEncoder().encode(t)]))
            const fs = {{ list: async () => [...mem].map(([path, b]) => ({{ path, size: b.length, mtime: 1 }})), read: async p => mem.get(p),
              write: async (p, b) => {{ mem.set(p, b) }}, remove: async p => {{ mem.delete(p) }}, has: async p => mem.has(p) }}
            let st = {json.dumps(state)}, saved = false
            const signal = {{ aborted: false }}, stop = {json.dumps(stop_at)}, steps = []
            const r = await vaultRound({{ drive, key, fs, device: 'phone-1', force: false, now: new Date(2026, 9, 12, 9, 30), signal,
              load: async () => st, save: async s => {{ st = s; saved = true }},
              progress: (step, done) => {{ steps.push(step); if (stop && step === stop[0] && done === stop[1]) signal.aborted = true }} }})
            {extra}
            const marker = mem.has('.nomedia'); mem.delete('.nomedia')        // the gallery marker, written by every round
            console.log(JSON.stringify({{ r, saved, st, steps, marker, fs: Object.fromEntries([...mem].map(([p, b]) => [p, new TextDecoder().decode(b)])),
              drive: Object.fromEntries([...files].map(([n, f]) => [n, f.data.toString('base64')])) }}))
        """))

    def _phone_index(self, out) -> dict:
        """The list this phone published, in full (device, files, caps)."""
        return V.decode_index_full(KEY.open(V.INDEX_LOGICAL, base64.b64decode(out['drive'][V.index_name(KEY, 'phone-1')])))

    def test_stop_while_scanning_changes_nothing_and_saves_nothing(self):
        phone = {'m1.md': 'one', 'm2.md': 'two', 'm3.md': 'three'}
        out = self._round({'a.md': 'pc a'}, phone, stop_at=['Checking files', 0])
        self.assertEqual(out['r']['state'], 'stopped')
        self.assertNotIn('Comparing with the PC', out['steps'])    # stopped inside the scan, between two files
        self.assertFalse(out['saved'])
        self.assertEqual(out['fs'], phone)

    def test_stop_between_pulls_finishes_the_file_and_the_next_round_completes(self):
        pc = {'a.md': 'one', 'b.md': 'two', 'c.md': 'three'}
        first = self._round(pc, {}, stop_at=["Taking the PC's changes", 0])
        self.assertEqual(first['r']['state'], 'stopped')
        self.assertEqual(first['fs'], {'a.md': 'one'})            # the file in progress was finished, not cut
        self.assertFalse(first['saved'])                          # the base stays as it was: the round is not half-recorded
        second = self._round(pc, first['fs'], drive=first['drive'])
        self.assertEqual(second['r']['state'], 'idle', second['r'])
        self.assertEqual(second['fs'], pc)
        self.assertIn('2 pulled', second['r']['summary'])          # a.md was already equal on both sides

    def test_stop_never_repeats_a_conflict_copy(self):
        # x.md changed on both sides, y.md is new from the PC. Stop after x.md: its conflict copy exists once,
        # and the round that follows (base unchanged) must not make a second one.
        base = {'x.md': KEY.content_id(b'old')}
        pc = {'x.md': 'pc edit', 'y.md': 'new from pc'}
        first = self._round(pc, {'x.md': 'phone edit'}, state={'base': base, 'cache': {}, 'fp': KEY.fingerprint}, stop_at=["Taking the PC's changes", 0])
        self.assertEqual(first['r']['state'], 'stopped')
        self.assertEqual(first['fs']['x.md'], 'pc edit')
        copies = [p for p in first['fs'] if 'phone conflict' in p]
        self.assertEqual(len(copies), 1)
        self.assertEqual(first['fs'][copies[0]], 'phone edit')
        second = self._round(pc, first['fs'], state={'base': base, 'cache': {}, 'fp': KEY.fingerprint}, drive=first['drive'])
        self.assertEqual(second['r']['state'], 'idle', second['r'])
        self.assertEqual(len([p for p in second['fs'] if 'phone conflict' in p]), 1)
        self.assertEqual(second['fs']['y.md'], 'new from pc')

    def test_a_state_from_another_key_is_dropped(self):
        # paired again with a new key: the old base and cache hold ids of the old key. Kept, the stale cached ids
        # would equal the old base, so both files would look deleted on the PC and go to .trash.
        other = mirror.MirrorKey.generate()
        stale = {'base': {'gone.md': other.content_id(b'gone'), 'mine.md': other.content_id(b'mine')},
                 'cache': {'gone.md': [4, 1, other.content_id(b'gone')], 'mine.md': [4, 1, other.content_id(b'mine')]},
                 'fp': other.fingerprint}
        out = self._round({'a.md': 'pc a'}, {'gone.md': 'gone', 'mine.md': 'mine'}, state=stale)
        self.assertEqual(out['r']['state'], 'idle', out['r'])
        self.assertEqual(out['fs'], {'a.md': 'pc a', 'gone.md': 'gone', 'mine.md': 'mine'})     # a first sync: no deletions
        self.assertEqual(out['st']['fp'], KEY.fingerprint)
        self.assertEqual(out['st']['cache']['mine.md'][2], KEY.content_id(b'mine'))
        self.assertIn(V.blob_name(KEY.content_id(b'mine')), out['drive'])

    def test_stop_while_sending_saves_the_base_and_sends_the_rest_next_round(self):
        phone = {'p1.md': 'first', 'p2.md': 'second'}
        first = self._round({'a.md': 'pc a'}, phone, stop_at=['Sending to Drive', 0])
        self.assertEqual(first['r']['state'], 'stopped')
        self.assertTrue(first['saved'])                           # the PC's changes are in: the base is true
        self.assertEqual(first['fs']['a.md'], 'pc a')
        names = set(first['drive'])
        self.assertNotIn(V.index_name(KEY, 'phone-1'), names)     # the phone's own list waits for a whole round
        self.assertEqual(sum(1 for n in names if n.startswith(V.BLOB_PREFIX)), 2)   # a.md + one phone file
        second = self._round({'a.md': 'pc a'}, first['fs'], state=first['st'], drive=first['drive'])
        self.assertEqual(second['r']['state'], 'idle', second['r'])
        self.assertIn(V.index_name(KEY, 'phone-1'), second['drive'])
        self.assertEqual(sum(1 for n in second['drive'] if n.startswith(V.BLOB_PREFIX)), 3)

    def test_many_files_go_several_at_a_time_and_all_land(self):
        pc = {f'n/{i:02}.md': f'pc {i}' for i in range(30)}
        phone = {f'p/{i:02}.md': f'phone {i}' for i in range(30)}
        out = self._round(pc, phone)
        self.assertEqual(out['r']['state'], 'idle', out['r'])
        self.assertEqual(out['fs'], {**pc, **phone})
        self.assertIn('30 pulled', out['r']['summary'])
        self.assertIn('30 sent', out['r']['summary'])

    def test_waits_when_the_pc_has_no_list(self):
        out = json.loads(node(f"""{TS_RESOLVE}
            const {{ MirrorKey }} = await import('./web/src/mobile/mirror/crypto.ts')
            const {{ vaultRound }} = await import('./web/src/mobile/vault/sync.ts')
            const key = await MirrorKey.fromText({json.dumps(KEY.text())})
            const drive = {{ list: async () => [], get: async () => new Uint8Array(), remove: async () => {{}}, create: async () => '' }}
            const fs = {{ list: async () => [], read: async () => new Uint8Array(), write: async () => {{}}, remove: async () => {{}}, has: async () => false }}
            console.log(JSON.stringify(await vaultRound({{ drive, key, fs, device: 'p', force: false, load: async () => undefined, save: async () => {{}} }})))
        """))
        self.assertEqual(out['state'], 'waiting')


    # ── spec 1b: an owner vault on the phone ───────────────────────────────────
    G, K, R, R2, CM = 'Brainamon/Items/a-1.md', 'Brainamon/Knowledge Map.md', 'Brainamon/Items/gone-2.md', 'Brainamon/Items/gone-3.md', 'Content Manager/items/x.md'

    def test_generated_pages_one_way_phone_files_two_way_caps_declared(self):
        """Decision 3: a differing copy of a generated page with no base becomes a conflict copy, then the PC's
        version; a phone file under Brainamon/ is sent and listed; the list declares caps; the state records the
        identity and that the vault has a manifest."""
        out = self._round({self.G: 'page a', self.K: 'map'}, {self.G: 'phone edit', 'Brainamon/Notes/mine.md': 'mine'}, vault='v1', generated=[self.G, self.K])
        self.assertEqual(out['r']['state'], 'idle', out['r'])
        copy = 'Brainamon/Items/a-1 (phone conflict 2026-10-12 0930).md'
        self.assertEqual(out['fs'], {self.G: 'page a', self.K: 'map', copy: 'phone edit', 'Brainamon/Notes/mine.md': 'mine'})
        idx = self._phone_index(out)
        self.assertEqual(idx['caps'], {'generated', 'identity'})
        self.assertEqual(sorted(idx['files']), sorted([self.G, self.K, copy, 'Brainamon/Notes/mine.md']))
        self.assertEqual((out['st']['vault'], out['st']['manifest'], out['st']['legacy']), ('v1', True, 0))
        self.assertEqual(out['r']['legacy'], 0)
        for part in ('2 pulled', '1 conflict', '2 sent'):
            self.assertIn(part, out['r']['summary'])
        # equal to the base: a PC version, taken directly, no copy
        again = self._round({self.G: 'page a2', self.K: 'map'}, out['fs'], state=out['st'], vault='v1', generated=[self.G, self.K])
        self.assertEqual(again['fs'][self.G], 'page a2')
        self.assertEqual(len([p for p in again['fs'] if 'conflict' in p]), 1)

    def test_removed_path_trashed_only_when_unedited(self):
        """Decision 3: a copy equal to the recorded hash goes to .trash (no base needed); an edited one stays, is
        listed and sent as the user's file."""
        removed = {self.R: V.sha256_hex(b'page gone'), self.R2: V.sha256_hex(b'page gone 2')}
        out = self._round({self.K: 'map'}, {self.K: 'map', self.R: 'page gone', self.R2: 'my version'}, vault='v1', generated=[self.K], removed=removed)
        self.assertEqual(out['r']['state'], 'idle', out['r'])
        self.assertEqual(out['fs'], {self.K: 'map', '.trash/' + self.R: 'page gone', self.R2: 'my version'})
        idx = self._phone_index(out)
        self.assertEqual(sorted(idx['files']), [self.R2, self.K])
        self.assertNotIn(self.R2, out['st']['base'])
        self.assertEqual((idx['vault'], idx['kept']), ('v1', {self.R2: removed[self.R2]}))
        self.assertIn(self.K, out['st']['base'])
        self.assertIn('1 moved to .trash', out['r']['summary'])

    def test_identity_change_is_non_destructive_then_legacy_is_trashed(self):
        """Decision 4 on the phone: another identity than the state's drops the base (the leftover Content Manager/
        entries excepted): nothing is trashed, differences become conflict copies, a file the PC lacks is kept and
        listed. Legacy copies are never listed; the next round trashes the unedited one."""
        state = {'base': {'a.md': KEY.content_id(b'pc note'), self.CM: KEY.content_id(b'x'), 'c.md': KEY.content_id(b'c')},
                 'cache': {}, 'fp': KEY.fingerprint, 'vault': 'old'}
        out = self._round({'a.md': 'pc edit', self.K: 'map'}, {'a.md': 'phone edit', self.CM: 'x', 'b.md': 'mine', 'c.md': 'c'},
                          state=state, vault='new', generated=[self.K])
        self.assertEqual(out['r']['state'], 'idle', out['r'])
        copy = 'a (phone conflict 2026-10-12 0930).md'
        self.assertEqual(out['fs'], {'a.md': 'pc edit', copy: 'phone edit', self.CM: 'x', 'b.md': 'mine', 'c.md': 'c', self.K: 'map'})
        self.assertEqual((out['st']['vault'], out['st']['legacy'], out['r']['legacy']), ('new', 1, 1))
        idx = self._phone_index(out)
        self.assertNotIn(self.CM, idx['files'])
        self.assertIn('c.md', idx['files'])
        second = self._round({'a.md': 'pc edit', self.K: 'map'}, out['fs'], state=out['st'], drive=out['drive'])
        self.assertEqual(second['fs'].get('.trash/' + self.CM), 'x')
        self.assertNotIn(self.CM, second['fs'])
        self.assertEqual((second['st']['legacy'], second['r']['legacy']), (0, 0))

    def test_classic_list_keeps_the_old_rules_and_still_declares_caps(self):
        """Decision 5, last bullet: a PC list without `generated` (a classic vault) gets today's one-way rule for
        Content Manager/ (taken back, no conflict copy); the phone still declares caps and records the identity."""
        state = {'base': {self.CM: KEY.content_id(b'export')}, 'cache': {}, 'fp': KEY.fingerprint}
        out = self._round({self.CM: 'export', 'n.md': 'note'}, {self.CM: 'phone change'}, state=state, vault='path:abc')
        self.assertEqual(out['fs'], {self.CM: 'export', 'n.md': 'note'})
        idx = self._phone_index(out)
        self.assertEqual(idx['caps'], {'generated', 'identity'})
        self.assertIn(self.CM, idx['files'])
        self.assertEqual((out['st']['manifest'], out['st']['vault']), (False, 'path:abc'))

    def test_remove_old_brainamon_pages_moves_the_folder_to_trash(self):
        """Decision 3: Remove old Brainamon pages moves what is left of Content Manager/ to .trash, on click."""
        out = self._round({self.K: 'map'}, {self.CM: 'x', 'Content Manager/items/y.md': 'y', 'mine.md': 'm'}, vault='v1', generated=[self.K],
                          extra="const n = await removeLegacy({ fs }); mem.set('n.txt', new TextEncoder().encode(String(n)))")
        self.assertEqual(out['fs']['n.txt'], '2')
        self.assertEqual(out['fs'].get('.trash/' + self.CM), 'x')
        self.assertEqual(out['fs'].get('.trash/Content Manager/items/y.md'), 'y')
        self.assertNotIn('Content Manager/items/y.md', out['fs'])
        self.assertEqual(out['fs']['mine.md'], 'm')

    def test_repeated_generated_conflicts_keep_every_edit(self):
        preferred = 'Brainamon/Items/a-1 (phone conflict 2026-10-12 0930).md'
        out = self._round({self.G: 'pc'}, {self.G: 'first', preferred: 'older'}, vault='v1', generated=[self.G])
        phone = dict(out['fs'])
        phone[self.G] = 'second'
        again = self._round({}, phone, state=out['st'], drive=out['drive'])
        self.assertEqual({v for k, v in again['fs'].items() if 'conflict' in k}, {'older', 'first', 'second'})
        self.assertEqual(again['fs'][self.G], 'pc')

    def test_classic_identity_changes_keep_files_for_one_round(self):
        for previous in ('path:old', 'owner-old'):
            with self.subTest(previous):
                st = {'fp': KEY.fingerprint, 'vault': previous, 'base': {self.CM: KEY.content_id(b'old')}, 'cache': {}}
                out = self._round({}, {self.CM: 'old'}, state=st, vault='path:new')
                self.assertEqual(out['fs'], {self.CM: 'old'})
                self.assertEqual(out['r']['state'], 'idle')
                again = self._round({}, out['fs'], state=out['st'], drive=out['drive'])
                self.assertEqual(again['fs'], {'.trash/' + self.CM: 'old'})

    def test_fresh_round_does_not_acknowledge_an_unprocessed_removal(self):
        st = {'fp': KEY.fingerprint, 'vault': 'old', 'base': {}, 'cache': {}}
        removed = {self.R: V.sha256_hex(b'generated')}
        out = self._round({}, {self.R: 'my edit'}, state=st, vault='new', generated=[], removed=removed)
        self.assertEqual(self._phone_index(out)['kept'], {})
        again = self._round({}, out['fs'], state=out['st'], drive=out['drive'])
        self.assertEqual(self._phone_index(again)['kept'], removed)
        self.assertEqual(again['fs'][self.R], 'my edit')


if __name__ == '__main__':
    unittest.main()
