"""Phone Import of Instagram saved posts (projects/milestone-2026-10-14/mobile-import/PLAN.md): the
mojibake fix, the saved_posts.json rules, the zip reader, the errors, the phone changes and their
overlay (web/src/mobile/imports.ts under Node), and the PC applying an imported link (server/intake.py).
Fixtures are small fakes built here from the layout in BRAINSTORM.md, never a real export."""
import io
import json
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from tests import test_phone_js
from tests.test_phone_mirror import ChangeIntakeTest


def moji(s: str) -> str:
    """What Meta writes: the UTF-8 bytes read back as Latin-1."""
    return s.encode('utf-8').decode('latin-1')


def post(url, ts=None, captions=(), owner=None, tags=(), href=None):
    lv = [{'label': 'URL', 'value': url, 'href': href or url}]
    lv += [{'label': 'Caption', 'value': moji(c)} for c in captions]
    lv.append({'label': 'Title', 'value': ''})
    lv.append({'title': 'Hashtags', 'dict': [{'dict': [{'label': 'Name', 'value': moji(t)}]} for t in tags]})
    if owner is not None:
        lv.append({'title': 'Owner', 'dict': [{'dict': [{'label': 'URL', 'value': 'https://linktr.ee/x'},
                                                        {'label': 'Name', 'value': moji(owner[0])},
                                                        {'label': 'Username', 'value': owner[1]}]}]})
    lv.append({'title': 'Brand partner', 'dict': []})
    e = {'media': [], 'label_values': lv, 'fbid': '1789'}
    if ts is not None:
        e['timestamp'] = ts
    return e


SAVED = [
    post('https://www.instagram.com/reel/DeZwNTwCCsj/', 1760400000, ['Café tips ’ here', 'Café tips ’ here'],
         ('Zoé Martin', 'zoe.m'), ['knees', '#Knees', 'prehab']),
    post('https://www.instagram.com/p/BjNUiURHGuHj4-xW10dDqupHGkllGg2jTPHWco0/', 1760300000, ['', 'Second caption'],
         ('Only Name', '')),
    post('https://www.instagram.com/p/NOCAP1/?igsh=abc', 1760200000),
    post('', 1760100000),                                   # no URL: skipped
    {'timestamp': 1760000000, 'media': []},                 # no label_values: skipped
]


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class ImportJsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_js(self, body: str):
        return json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            import fs from 'node:fs'
            const I = await import('./web/src/mobile/imports.ts')
            const bytes = p => new Uint8Array(fs.readFileSync(p))
            const err = async f => {{ try {{ await f(); return 'ok' }} catch (e) {{ return e.message === I.NOT_SAVED ? 'NOT_SAVED' : e.message === I.TOO_BIG ? 'TOO_BIG' : e.message }} }}
            {body}
        """))

    def put(self, name: str, data: bytes) -> str:
        p = self.tmp / name
        p.write_bytes(data)
        return p.as_posix()

    def test_fix_text(self):
        cases = [moji('It’s café'), 'plain ascii', 'already ok ’ here', 'café', '']
        out = self.run_js(f"console.log(JSON.stringify({json.dumps(cases)}.map(I.fixText)))")
        self.assertEqual(out, ['It’s café', 'plain ascii', 'already ok ’ here', 'café', ''])

    def test_saved_posts_rules(self):
        path = self.put('saved_posts.json', json.dumps(SAVED).encode('ascii'))
        out = self.run_js(f"console.log(JSON.stringify(await I.readExport(bytes({json.dumps(path)}))))")
        self.assertEqual(out['skipped'], 2)
        self.assertEqual(out['posts'], [
            {'url': 'https://www.instagram.com/reel/DeZwNTwCCsj/', 'at': 1760400000000, 'caption': 'Café tips ’ here',
             'creator': 'zoe.m', 'tags': 'knees, prehab'},
            {'url': 'https://www.instagram.com/p/BjNUiURHGuHj4-xW10dDqupHGkllGg2jTPHWco0/', 'at': 1760300000000,
             'caption': 'Second caption', 'creator': 'Only Name', 'tags': ''},
            {'url': 'https://www.instagram.com/p/NOCAP1/?igsh=abc', 'at': 1760200000000, 'caption': '', 'creator': '', 'tags': ''},
        ])

    def test_zip_stored_and_deflated(self):
        raw = ('﻿' + json.dumps(SAVED)).encode('utf-8')
        paths = []
        for i, method in enumerate((zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED)):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', method) as z:
                z.writestr('your_instagram_activity/likes/liked_posts.json', '[]')
                z.writestr('your_instagram_activity/saved/saved_posts.json', raw)
                z.writestr('your_instagram_activity/saved/saved_collections.json', '[]')
            paths.append(self.put(f'export{i}.zip', buf.getvalue()))
        out = self.run_js(f"""
            const got = []
            for (const p of {json.dumps(paths)}) {{ const r = await I.readExport(bytes(p)); got.push([r.posts.length, r.skipped, r.posts[0].caption]) }}
            console.log(JSON.stringify(got))""")
        self.assertEqual(out, [[3, 2, 'Café tips ’ here']] * 2)

    def test_errors(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('your_instagram_activity/likes/liked_posts.json', json.dumps(SAVED))
        files = [self.put('obj.json', b'{"saves_v2": []}'), self.put('other.json', b'[{"a": 1}, {"b": 2}]'),
                 self.put('nozip.zip', buf.getvalue()), self.put('junk.zip', b'PK\x03\x04 broken'),
                 self.put('text.json', b'not json'), self.put('empty.json', b'[]')]
        out = self.run_js(f"""
            const got = []
            for (const p of {json.dumps(files)}) got.push(await err(() => I.readExport(bytes(p))))
            got.push(await err(() => I.readExport(new Uint8Array(I.MAX_IMPORT_BYTES + 1))))
            got.push(await err(() => I.unzipEntry(new Uint8Array(64), {{ name: 'x', method: 8, packed: 1, size: I.MAX_IMPORT_BYTES + 1, at: 0 }})))
            console.log(JSON.stringify(got))""")
        self.assertEqual(out, ['NOT_SAVED'] * 5 + ['ok', 'TOO_BIG', 'TOO_BIG'])

    def test_import_changes_and_overlay(self):
        path = self.put('saved_posts.json', json.dumps(SAVED).encode('ascii'))
        out = self.run_js(f"""
            const {{ cleanLink }} = await import('./web/src/mobile/links.ts')
            const {{ Changes }} = await import('./web/src/mobile/mirror/changes.ts')
            const {{ posts }} = await I.readExport(bytes({json.dumps(path)}))
            const twice = [...posts, posts[0]]
            let n = 0
            const r = I.importChanges(twice, new Set(['https://www.instagram.com/p/NOCAP1/']), cleanLink, () => 'u' + (++n))
            const c = new Changes()
            let k = 0
            for (const ch of r.changes) {{ const e = await c.add(ch); if (e.op === 'link') e.id = ++k }}   // Node has no IndexedDB
            const rows = c.overlay([]).map(x => [x.url, x.title, x.creator, x.tags, x.created])
            console.log(JSON.stringify({{ dups: r.dups, changes: r.changes, rows }}))""")
        self.assertEqual(out['dups'], 2)
        self.assertEqual(out['changes'], [
            {'op': 'link', 'uid': 'u1', 'url': 'https://www.instagram.com/reel/DeZwNTwCCsj/', 'note': '', 'category': '',
             'tags': 'knees, prehab', 'at': 1760400000000},
            {'op': 'details', 'uid': 'u1', 'title': '', 'creator': 'zoe.m', 'desc': 'Café tips ’ here', 'thumb': ''},
            {'op': 'link', 'uid': 'u2', 'url': 'https://www.instagram.com/p/BjNUiURHGuHj4-xW10dDqupHGkllGg2jTPHWco0/',
             'note': '', 'category': '', 'tags': '', 'at': 1760300000000},
            {'op': 'details', 'uid': 'u2', 'title': '', 'creator': 'Only Name', 'desc': 'Second caption', 'thumb': ''},
        ])
        self.assertEqual(sorted(out['rows']), sorted([
            ['https://www.instagram.com/reel/DeZwNTwCCsj/', 'Café tips ’ here', 'zoe.m', 'knees, prehab', 1760400000000],
            ['https://www.instagram.com/p/BjNUiURHGuHj4-xW10dDqupHGkllGg2jTPHWco0/', 'Second caption', 'Only Name', '', 1760300000000],
        ]))


class ImportIntakeTest(ChangeIntakeTest):
    def test_intake_applies_an_import(self):
        uid, url, at = 'cd' * 16, 'https://www.instagram.com/reel/IMPORT1/', 1760400000000
        self.phone([
            {'op': 'link', 'uid': uid, 'url': url, 'note': '', 'category': '', 'tags': 'knees, prehab', 'at': at},
            {'op': 'details', 'uid': uid, 'title': '', 'creator': 'zoe.m', 'desc': 'Café tips', 'thumb': '', 'at': at + 1},
        ])
        self.assertTrue(self.svc._intake())
        row = self.writer.read(lambda db: dict(db.conn.execute('SELECT * FROM items WHERE uid = ?', (uid,)).fetchone()))
        self.assertEqual((row['url'], row['tags'], row['created'], row['description'], row['creator'], row['source']),
                         (url, 'knees, prehab', at, 'Café tips', 'zoe.m', 'phone'))
        self.phone([{'op': 'link', 'uid': 'ef' * 16, 'url': url, 'note': '', 'category': '', 'tags': 'other', 'at': at}],
                   at=int(time.time() * 1000) + 10_000)
        self.assertTrue(self.svc._intake())
        n = self.writer.read(lambda db: db.conn.execute('SELECT COUNT(*), MAX(tags) FROM items WHERE url = ?', (url,)).fetchone())
        self.assertEqual(tuple(n), (1, 'knees, prehab'))


def load_tests(loader, tests, pattern):
    # only this module's tests: ImportIntakeTest borrows ChangeIntakeTest's set-up, not its tests
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(ImportJsTest))
    suite.addTest(ImportIntakeTest('test_intake_applies_an_import'))
    return suite
