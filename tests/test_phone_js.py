"""The phone's TypeScript against the desktop's Python (projects/mobile-app/PLAN.md Phase 4), run
under Node (type stripping, no build): the share-link rule in web/src/mobile/links.ts and its copy
in web/public/sw.js agree with knowledge/inbox.py on tests/fixtures/share_links.json, and
web/src/mobile/mirror/crypto.ts opens files sealed by library/mirror.py (manifest, a thumbnail
pack, a video, the vectors) while Python opens the change file it seals. Skips without Node 22.6+."""
import base64
import json
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from library import mirror

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'web'
CASES = json.loads((ROOT / 'tests' / 'fixtures' / 'share_links.json').read_text(encoding='utf-8'))['cases']


def node(script: str, timeout: float = 60, *, development: bool = False) -> str:
    if development:
        # Explicit fixture transform; production modules retain their endpoint restrictions.
        script = r"""
        import { registerHooks } from 'node:module'
        registerHooks({ resolve(specifier, context, next) {
          return next(specifier.startsWith('./web/') ? new URL(specifier, import.meta.url).href : specifier, context)
        }, load(url, context, next) {
          const result = next(url, context)
          if (/\/mobile\/(ai\/providers|mirror\/(pairing|drive|status))\.ts$/.test(url))
            return { ...result, source: result.source.toString().replaceAll('import.meta.env?.DEV === true', 'true') }
          return result
        } })
        """ + "await import('data:text/javascript,' + encodeURIComponent(" + json.dumps(script) + "))"
    r = subprocess.run(['node', '--experimental-strip-types', '--no-warnings', '--input-type=module', '-e', script],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return r.stdout


# lets a script import phone modules whose imports leave out ".ts" (Vite resolves them)
TS_RESOLVE = """
    globalThis.$state = x => x
    import { register } from 'node:module'
    register('data:text/javascript,' + encodeURIComponent('export async function resolve(s, c, n) { try { return await n(s, c) } catch (e) { if (s.startsWith(".") && !/\\.\\w+$/.test(s)) return n(s + ".ts", c); throw e } }'), import.meta.url)
"""


def _node_ok() -> bool:
    if not shutil.which('node'):
        return False
    try:
        node("import { cleanLink } from './web/src/mobile/links.ts'; console.log(cleanLink('x'))")
        return True
    except Exception:
        return False


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneJsTest(unittest.TestCase):
    def test_share_links_agree_everywhere(self):
        from knowledge import inbox
        out = json.loads(node(f"""
            import {{ cleanLink }} from './web/src/mobile/links.ts'
            import fs from 'node:fs'
            import vm from 'node:vm'
            const ctx = {{ self: {{ addEventListener() {{}} }}, location: {{ origin: 'x' }} }}
            vm.createContext(ctx)
            vm.runInContext(fs.readFileSync('web/public/sw.js', 'utf8') + ';globalThis.swClean = cleanLink', ctx)
            const cases = {json.dumps([c[0] for c in CASES])}
            console.log(JSON.stringify(cases.map(t => [cleanLink(t) || null, ctx.swClean(t) || null])))
        """))
        for (text, want), (phone, sw) in zip(CASES, out):
            self.assertEqual(inbox.link(text), want, text)
            self.assertEqual(phone, want, f'links.ts: {text!r}')
            if want is None or text.strip().lower().startswith('http') or '://' in text:
                self.assertEqual(sw, want, f'sw.js: {text!r}')      # the share sheet always sends http(s) links

    def test_open_in_obsidian_targets_the_exported_note(self):
        """Phase 6: obsidian://new at <vault>/<notes prefix><file>, the prefix from the mirror's library/meta.json
        (Content Manager/notes/ for the classic export, Brainamon/Notes/ for an owner vault; the classic default
        when absent), every value encoded as Obsidian asks ("/" as %2F, spaces as %20), the note's frontmatter kept."""
        from urllib.parse import parse_qsl, urlsplit
        from library import obsidian_export
        out = json.loads(node("""
            import { obsidianUrl, noteText } from './web/src/mobile/obsidian.ts'
            const text = noteText({ topic: 'Knee prehab', sources: '102,104', empty: '' }, '## Knee & co\\n\\nA + B = 100%')
            console.log(JSON.stringify({ text, url: obsidianUrl('My Vault', 'knee-prehab.md', text), bare: obsidianUrl('', 'a.md', 'x'),
              owner: obsidianUrl('My Vault', 'knee-prehab.md', text, 'Brainamon/Notes/'), blank: obsidianUrl('V', 'a.md', 'x', '') }))
        """))
        self.assertEqual(out['text'], '---\ntopic: Knee prehab\nsources: 102,104\n---\n\n## Knee & co\n\nA + B = 100%')
        u = urlsplit(out['url'])
        self.assertEqual((u.scheme, u.netloc), ('obsidian', 'new'))
        self.assertNotIn('+', u.query)
        self.assertIn('file=Content%20Manager%2Fnotes%2Fknee-prehab&', u.query)
        q = dict(parse_qsl(u.query))
        self.assertEqual(q, {'vault': 'My Vault', 'file': 'Content Manager/notes/knee-prehab', 'content': out['text'], 'overwrite': 'true'})
        self.assertIn('notes', obsidian_export.MANAGED_SUBDIRS)
        self.assertFalse(out['bare'].startswith('obsidian://new?vault'))
        self.assertEqual(dict(parse_qsl(urlsplit(out['owner']).query))['file'], 'Brainamon/Notes/knee-prehab')
        self.assertEqual(dict(parse_qsl(urlsplit(out['blank']).query))['file'], 'Content Manager/notes/a')

    def test_phone_opens_what_the_pc_seals_and_the_pc_opens_its_change(self):
        k = mirror.MirrorKey.generate()
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        man = k.seal(mirror.MANIFEST, json.dumps({'format': 1, 'items': 2, 'files': {}}).encode())
        pack = b'BTP1'
        idx = json.dumps({'7': [0, 3], '9': [3, 2]}).encode()
        pack += struct.pack('>I', len(idx)) + idx + b'abcde'
        (d / 'v.mp4').write_bytes(bytes(range(256)) * 40)
        k.seal_file('videos/u1.bin', d / 'v.mp4', d / 'v.bin')
        rows = [(7, 4, np.array([1, 0, 0, 0], np.float32).tobytes()), (9, 4, np.array([0.9, 0.1, 0, 0], np.float32).tobytes()),
                (11, 4, np.array([0, 0, 1, 0], np.float32).tobytes())]
        vec = mirror._vectors('m', rows, {7: 'a', 9: 'b', 11: 'c'})
        fx = {'key': k.text(), 'fp': k.fingerprint, 'man_name': k.name(mirror.MANIFEST),
              'man': base64.b64encode(man).decode(), 'pack': base64.b64encode(k.seal('thumbs/pack-0000.bin', pack)).decode(),
              'video': base64.b64encode((d / 'v.bin').read_bytes()).decode(),
              'vec': base64.b64encode(k.seal('vectors.bin', vec)).decode()}
        (d / 'fx.json').write_text(json.dumps(fx))
        out = json.loads(node(f"""
            import {{ MirrorKey, readPack, readVectors, nearest }} from './web/src/mobile/mirror/crypto.ts'
            import fs from 'node:fs'
            const fx = JSON.parse(fs.readFileSync({json.dumps(str(d / 'fx.json'))}, 'utf8'))
            const b = s => Uint8Array.from(Buffer.from(s, 'base64'))
            const k = await MirrorKey.fromText(fx.key)
            const pack = readPack(await k.open('thumbs/pack-0000.bin', b(fx.pack)))
            const vid = Buffer.concat(await k.openVideo('videos/u1.bin', b(fx.video), {json.dumps({'integrity': 2, 'bytes': 10240, 'sha256': __import__('hashlib').sha256(bytes(range(256)) * 40).hexdigest()})}))
            const v = readVectors(await k.open('vectors.bin', b(fx.vec)))
            let wrong = ''
            try {{ await k.open('items/x.json', b(fx.man)) }} catch (e) {{ wrong = e.constructor.name }}
            const [name, sealed] = await k.sealChange({{ format: 1, device: 'p1', at: 5, changes: [{{ op: 'fav', uid: 'u', on: true }}] }})
            console.log(JSON.stringify({{
              fp: k.fingerprint, name: await k.name('manifest.json'), man: await k.openJSON('manifest.json', b(fx.man)),
              pack: Object.fromEntries([...pack].map(([i, j]) => [i, Buffer.from(j).toString()])),
              vid: vid.toString('base64'), near: nearest(v, 0, 2), dim: v.dim, uids: v.uids, wrong,
              change: [name, Buffer.from(sealed).toString('base64')],
            }}))
        """))
        self.assertEqual((out['fp'], out['name']), (k.fingerprint, k.name(mirror.MANIFEST)))
        self.assertEqual(out['man']['items'], 2)
        self.assertEqual(out['pack'], {'7': 'abc', '9': 'de'})
        self.assertEqual(base64.b64decode(out['vid']), (d / 'v.mp4').read_bytes())
        self.assertEqual((out['near'], out['dim'], out['uids']), ([9, 11], 4, ['a', 'b', 'c']))
        self.assertEqual(out['wrong'], 'MirrorKeyError')                       # a file cannot pass as another
        name, blob = out['change']
        self.assertTrue(mirror.is_change(name))
        self.assertEqual(k.open_change(name, base64.b64decode(blob))['changes'], [{'op': 'fav', 'uid': 'u', 'on': True}])
        with self.assertRaises(mirror.MirrorKeyError):
            mirror.MirrorKey.generate().open_change(name, base64.b64decode(blob))

    def test_plain_search_finds_an_item_by_its_whole_number(self):
        """A query that is one whole number also finds the item with that id; partial ids, phone-only
        links (id < 0) and the word rule for text are unchanged."""
        out = json.loads(node(TS_RESOLVE + """
            const { findIds } = await import('./web/src/mobile/source/find.ts')
            const { idFirst, inSearch } = await import('./web/src/lib/whole-id.ts')
            const row = (id, title = '') => ({ id, title, creator: '', tags: '', desc: '', cat: '', url: '' })
            const rows = [row(7, '100 tips'), row(100), row(10), row(1000), row(-100), row(5, 'red apple pie'), row(6, 'apple tart')]
            // the list (sorted, or ranked by Smart search) shows the exact id first
            const ranked = idFirst([{ id: 7 }, { id: 3 }, { id: 100 }], '100').map(r => r.id)
            // search ids / Smart rank that exclude the id still keep it for the whole number
            const kept = [inSearch(100, '100', new Set([7]), null), inSearch(100, '100', null, new Map([[7, 1]])),
              inSearch(100, '10', new Set([7]), null), inSearch(-100, '-100', new Set([7]), null)]
            console.log(JSON.stringify({ kept, n100: findIds(rows, '100'), n10: findIds(rows, ' 10 '), ranked,
              words: findIds(rows, 'apple pie'), mixed: findIds(rows, '100 apple'), neg: findIds(rows, '-100') }))
        """))
        self.assertEqual(out['n100'], [100, 7])                        # the id first, then the text matches
        self.assertEqual(out['ranked'], [100, 7, 3])
        self.assertEqual(out['kept'], [True, True, False, False])
        self.assertEqual(out['n10'], [10, 7])                          # id 10 only, never 100 or 1000 by id
        self.assertEqual(out['words'], [5])
        self.assertEqual(out['mixed'], [])
        self.assertEqual(out['neg'], [])

    def test_phone_collects_the_ai_keys_the_pc_left_for_a_pairing(self):
        """Audit H3: the pairing link carries a one-time key, not the API keys. The phone works out
        the Drive name of the sealed keys file (library/mirror.py pair_drop), opens it, keeps the
        keys, deletes the file and forgets the one-time key; a file gone past its expiry gives up."""
        one, exp, name, blob = mirror.pair_drop({'openai': 'sk-o', 'anthropic': 'sk-a', 'odd': 5})
        _, old_exp, _, _ = mirror.pair_drop({}, now=time.time() - mirror.PAIR_TTL - 5)
        out = json.loads(node(TS_RESOLVE + f"""
            const mem = new Map()
            globalThis.localStorage = {{ getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v), removeItem: k => mem.delete(k) }}
            const {{ takeKeys }} = await import('./web/src/mobile/mirror/pairing.ts')
            const files = new Map([['d1', [{json.dumps(name)}, Buffer.from({json.dumps(base64.b64encode(blob).decode())}, 'base64')]]])
            const removed = []
            const drive = {{
              find: async n => {{ for (const [id, [fn]] of files) if (fn === n) return {{ id, size: 0 }}; return null }},
              get: async id => Uint8Array.from(files.get(id)[1]),
              remove: async id => {{ removed.push(id); files.delete(id) }},
            }}
            const p = {{ v: 2, k: 'x', c: '', e: '', f: 'f', ai: {{}}, t: {json.dumps(one.text())}, tx: {exp}, at: 1 }}
            const note = await takeKeys(p, drive)
            const again = await takeKeys(p, drive)
            const stored = JSON.parse(mem.get('bp-pair'))
            const late = {{ v: 2, k: 'x', c: '', e: '', f: 'f', ai: {{}}, t: {json.dumps(one.text())}, tx: {old_exp}, at: 1 }}
            const lateNote = await takeKeys(late, drive)
            const early = {{ v: 2, k: 'x', c: '', e: '', f: 'f', ai: {{}}, t: {json.dumps(one.text())}, tx: {exp + 7}, at: 1 }}
            const earlyNote = await takeKeys(early, drive)
            console.log(JSON.stringify({{ ai: p.ai, t: p.t ?? null, note, again, removed, stored,
                                          late: [lateNote, late.t ?? null], early: [earlyNote, early.t ?? null] }}))
        """))
        self.assertEqual(out['ai'], {'openai': 'sk-o', 'anthropic': 'sk-a'})
        self.assertEqual((out['t'], out['note'], out['again'], out['removed']), (None, 'AI keys received.', '', ['d1']))
        self.assertEqual(out['stored']['ai'], {'openai': 'sk-o', 'anthropic': 'sk-a'})
        self.assertNotIn('t', out['stored'])
        self.assertIn('expired', out['late'][0])
        self.assertIsNone(out['late'][1])
        self.assertEqual(out['early'], ['', one.text()])          # not there yet, not expired: tried again later

    def test_a_phone_only_delete_outlasts_prune(self):
        """An item deleted "only on this phone" stays hidden after the PC applied the change and prune
        dropped it (the PC keeps the row); one deleted on the PC too is left to the PC's next rows."""
        out = json.loads(node(f"""{TS_RESOLVE}
            const {{ Changes }} = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes()
            const rows = ['a', 'b', 'c'].map((uid, i) => ({{ id: i + 1, uid, url: 'https://x/' + uid }}))
            const uids = l => l.map(r => r.uid)
            await c.add({{ op: 'delete', uid: 'a', pc: false }})
            await c.add({{ op: 'delete', uid: 'b', pc: true }})
            const before = uids(c.overlay(rows))
            for (const e of c.list) {{ e.state = 'sent'; e.sentAt = 5 }}
            await c.prune(10)
            console.log(JSON.stringify({{ before, after: uids(c.overlay(rows)), left: c.list.length }}))
        """))
        self.assertEqual(out, {'before': ['c'], 'after': ['b', 'c'], 'left': 0})

    def test_old_reader_keeps_persisted_overlays_and_only_flushes_queued_edits(self):
        out = json.loads(node(TS_RESOLVE + r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            const { changes: db, kv } = await import('./web/src/mobile/store.ts')
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const persisted = new Map([
              [1, { id: 1, op: 'fav', uid: 'old', on: true, state: 'sent', sentAt: 5, at: 1 }],
              [2, { id: 2, op: 'link', uid: 'new', url: 'https://example.invalid/new', state: 'sent', sentAt: 6, at: 2 }],
              [3, { id: 3, op: 'edit', uid: 'old', fields: { tags: 'queued' }, state: 'queued', at: 3 }],
            ])
            db.all = async () => structuredClone([...persisted.values()])
            db.put = async e => { persisted.set(e.id, structuredClone(e)) }
            db.del = async id => { persisted.delete(id) }
            const old = { reader: 1, files: {}, marker: 'cached' }
            const cache = new Map([['manifest', structuredClone(old)]])
            kv.get = async k => structuredClone(cache.get(k))
            kv.set = async (k, v) => { cache.set(k, structuredClone(v)) }
            const src = fs.readFileSync('web/src/mobile/source/mirror.ts', 'utf8')
            const method = src.match(/  private async readManifest\(\)[\s\S]*?\n  }/)[0]
            const READER = Number(src.match(/export const READER = (\d+)/)[1])
            let warnings = 0, receipts = 0, prunes = 0
            class PhoneTooOld extends Error {}
            const Loader = new Function('READER', 'PhoneTooOld', 'tooOld', 'kv', 'deviceId',
              stripTypeScriptTypes('class Loader {\n' + method + '\n}') + ';return Loader')(
                READER, PhoneTooOld, { fn: () => warnings++ }, kv, () => 'phone')
            const loader = new Loader()
            loader.nativeReady = async () => false
            loader.loadManifest = () => loader.readManifest()
            let incoming = { reader: READER + 1, files: { 'canvas-results.json': {} }, applied: { phone: 10 } }
            loader.manifest = structuredClone(old)
            loader.changes = new Changes()
            const prune = loader.changes.prune.bind(loader.changes)
            loader.changes.prune = async at => { prunes++; await prune(at) }
            loader.key = { name: async n => n, openJSON: async () => incoming }
            loader.drive = { checkpoint: () => {}, find: async () => ({ id: 'fixture' }), get: async () => new Uint8Array() }
            loader.cached = async () => { receipts++; return '{}' }
            let refused = false
            try { await loader.loadManifest() } catch(e) { refused = e instanceof PhoneTooOld }
            await loader.changes.load()
            const rows = [{ id: 7, uid: 'old', url: 'https://example.invalid/old', fav: false, tags: '' }]
            const visible = c => c.overlay(rows).map(r => [r.uid, r.fav, r.tags])
            const before = visible(loader.changes)
            const reloaded = new Changes(); await reloaded.load()
            const after = visible(reloaded)
            const retained = { refused, warnings, receipts, prunes, manifest: loader.manifest,
              cache: cache.get('manifest'), count: reloaded.list.length, before, after }
            const sent = []
            await reloaded.flush(async doc => { sent.push(doc); return 'fixture-change' }, 'phone')
            incoming = { ...incoming, reader: READER }
            await loader.loadManifest()
            console.log(JSON.stringify({ retained, ops: sent.flatMap(d => d.changes.map(c => c.op)),
              format: sent[0].format, prunes, receipts, left: [...persisted.values()].map(e => e.op) }))
        """))
        keep = out['retained']
        self.assertTrue(keep['refused'])
        self.assertEqual((keep['warnings'], keep['receipts'], keep['prunes'], keep['count']), (1, 0, 0, 3))
        self.assertEqual(keep['manifest'], keep['cache'])
        self.assertEqual(keep['manifest']['marker'], 'cached')
        self.assertEqual(keep['before'], keep['after'])
        self.assertEqual(keep['after'], [['new', False, ''], ['old', True, 'queued']])
        self.assertEqual((out['ops'], out['format'], out['prunes'], out['receipts'], out['left']),
                         (['edit'], mirror.CHANGE_FORMAT, 1, 1, ['edit']))


if __name__ == '__main__':
    unittest.main()
