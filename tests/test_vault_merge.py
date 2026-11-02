"""Vault sync core (projects/vault-sync/plans/01-export-and-merge.md): the merge cases, the scan, the exclusions,
the deletion brake, conflict copies and .trash/. The phone's port is checked against the same fixture in
tests/test_vault_merge_js.py.

Run from the project root:  py -m unittest tests.test_vault_merge -v
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from library import mirror, vault_sync as V

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'vault_cases.json').read_text(encoding='utf-8'))
WHEN = datetime(2026, 10, 12, 9, 30)


def got(plan: V.Plan) -> dict:
    return {'pull': plan.pull, 'trash': sorted(plan.trash), 'conflicts': plan.conflicts, 'lost': sorted(plan.lost),
            'legacy': sorted(plan.legacy), 'new_base': plan.new_base, 'brake': plan.brake}


def run_case(c: dict) -> V.Plan:
    """A fixture case: generated (a list, present only for a manifest vault), removed, mine_hash and fresh are optional."""
    return V.merge(c['base'], c['mine'], c['theirs'], c['role'], WHEN,
                   generated=set(c['generated']) if 'generated' in c else None,
                   removed=c.get('removed'), mine_hash=c.get('mine_hash'), fresh=c.get('fresh', False), kept=c.get('kept'))


class MergeTest(unittest.TestCase):
    def test_fixture_cases(self):
        self.assertEqual(len(CASES), 46)
        for c in CASES:
            with self.subTest(c['name']):
                self.assertEqual(got(run_case(c)), c['expect'])

    def test_classic_call_without_keywords_is_unchanged(self):
        # every existing caller (server/sync.py, the phone stand-in) passes no keywords and gets today's rules
        for c in CASES:
            if 'generated' not in c and not c.get('fresh'):
                with self.subTest(c['name']):
                    self.assertEqual(got(V.merge(c['base'], c['mine'], c['theirs'], c['role'], WHEN)), c['expect'])

    def test_brake_over_twenty_files(self):
        base = {f'f{i}.md': 'x' for i in range(500)}
        self.assertFalse(V.merge(base, base, {k: v for k, v in list(base.items())[20:]}, 'phone', WHEN).brake)
        self.assertTrue(V.merge(base, base, {k: v for k, v in list(base.items())[21:]}, 'phone', WHEN).brake)
        self.assertTrue(V.merge(base, {k: v for k, v in list(base.items())[21:]}, base, 'pc', WHEN).brake)

    def test_first_sync_is_a_union(self):
        p = V.merge({}, {'a.md': '1'}, {'b.md': '2'}, 'phone', WHEN)
        self.assertEqual((p.pull, p.trash, p.lost, p.brake), ({'b.md': '2'}, [], [], False))

    def test_conflict_name_keeps_folder_and_extension(self):
        self.assertEqual(V.conflict_name('Notes/Plan.v2.md', WHEN), 'Notes/Plan.v2 (phone conflict 2026-10-12 0930).md')


    def test_conflict_copies_never_replace_an_existing_file(self):
        rel = 'Brainamon/a.md'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / rel).parent.mkdir(parents=True)
            preferred = V.conflict_name(rel, WHEN)
            (root / preferred).write_bytes(b'older saved edit')
            for edit in (b'edit one', b'edit two'):
                (root / rel).write_bytes(edit)
                plan = V.merge({}, {rel: 'edit'}, {rel: 'pc'}, 'phone', WHEN, generated={rel})
                V.apply(root, plan, lambda cid: b'pc')
            saved = {(root / p).read_bytes() for p in ['Brainamon/' + f.name for f in (root / 'Brainamon').glob('*conflict*')]}
            self.assertEqual(saved, {b'older saved edit', b'edit one', b'edit two'})
            self.assertEqual((root / rel).read_bytes(), b'pc')

class FilesTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.key = mirror.MirrorKey(bytes(range(32)))

    def put(self, rel, text='x'):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def test_scan_skips_the_excluded(self):
        for rel in ('a.md', 'dir/b.md', '.obsidian/app.json', '.obsidian/plugins/p/main.js', '.obsidian/themes/t.css',
                    '.obsidian/workspace.json', '.obsidian/workspace-mobile.json', '.trash/old.md', '.git/HEAD', 'c.md.vsync-tmp',
                    '.brainamon/manifest.json'):
            self.put(rel)
        files, cache = V.scan(self.root, self.key)
        self.assertEqual(sorted(files), ['.obsidian/app.json', 'a.md', 'dir/b.md'])
        self.assertEqual(files['a.md'], self.key.content_id(b'x'))
        self.assertEqual(files, V.scan(self.root, self.key, cache)[0])

    def test_scan_skips_big_files(self):
        self.put('big.bin')
        old = V.MAX_FILE
        V.MAX_FILE = 0
        try:
            self.assertEqual(V.scan(self.root, self.key)[0], {})
        finally:
            V.MAX_FILE = old

    def test_scan_names_the_files_it_leaves_out_for_their_size(self):
        self.put('small.md', 'x')
        self.put('big.md', 'y' * 20)
        left = {}
        with mock.patch.object(V, 'MAX_FILE', 5):
            files, _ = V.scan(self.root, self.key, skipped=left)
            self.assertEqual(sorted(V.scan(self.root, self.key)[0]), ['small.md'])      # without the argument: as before
        self.assertEqual((sorted(files), left), (['small.md'], {'big.md': 20}))

    def test_the_note_counts_the_files_in_plain_words(self):
        self.assertEqual(V.skipped_note(0), '')
        self.assertEqual(V.skipped_note(1), '1 file over 50 MiB is not synced.')
        self.assertEqual(V.skipped_note(1234), '1,234 files over 50 MiB are not synced.')

    def test_content_id_depends_on_key_and_bytes(self):
        other = mirror.MirrorKey(bytes(range(1, 33)))
        self.assertNotEqual(self.key.content_id(b'x'), other.content_id(b'x'))
        self.assertNotEqual(self.key.content_id(b'x'), self.key.content_id(b'y'))
        self.assertRegex(self.key.content_id(b'x'), r'^[0-9a-f]{32}$')

    def test_valid_rel_and_index_filter(self):
        for bad in ('', '/a', '../a', 'a/../b', 'a\\b', 'C:x', 'a//b', './a'):
            self.assertFalse(V.valid_rel(bad), bad)
        good = 'a' * 32
        raw = V.encode_index({'ok.md': good, '../evil.md': good, 'bad.md': 'zz', '.trash/x.md': good}, 'phone-1')
        self.assertEqual(V.decode_index(raw), ('phone-1', {'ok.md': good}))
        self.assertEqual(json.loads(raw), {'v': 1, 'device': 'phone-1', 'files': {'ok.md': good, '../evil.md': good, 'bad.md': 'zz', '.trash/x.md': good}})

    def test_index_full_fields_and_the_old_reader(self):
        """Spec 1b: the PC's list carries vault, generated and removed; a phone's carries caps. Bad entries are
        dropped (a generated path must be listed, a removed path must not be, a record is a sha256). The old
        reader (decode_index, what a pre-1b phone does) sees only device and files."""
        a, b = 'a' * 32, 'b' * 32
        raw = V.encode_index({'a.md': a, 'Brainamon/Items/x-1.md': b}, 'pc', vault='v1',
                             generated=['Brainamon/Items/x-1.md', 'nope.md'],
                             removed={'gone.md': 'c' * 64, 'a.md': 'd' * 64, '../e.md': 'e' * 64, 'f.md': 'zz', '.brainamon/x': 'f' * 64})
        full = V.decode_index_full(raw)
        self.assertEqual((full['device'], full['vault'], full['caps']), ('pc', 'v1', set()))
        self.assertEqual(full['generated'], {'Brainamon/Items/x-1.md'})
        self.assertEqual(full['removed'], {'gone.md': 'c' * 64})
        self.assertEqual(V.decode_index(raw), ('pc', {'a.md': a, 'Brainamon/Items/x-1.md': b}))
        d = json.loads(raw)
        self.assertEqual((d['v'], d['vault'], d['generated']), (1, 'v1', ['Brainamon/Items/x-1.md', 'nope.md']))
        # a manifest vault with nothing generated still says so (an empty list), a classic vault says nothing
        self.assertEqual(V.decode_index_full(V.encode_index({}, 'pc', generated=[]))['generated'], set())
        self.assertNotIn('generated', json.loads(V.encode_index({}, 'pc')))
        self.assertIsNone(V.decode_index_full(V.encode_index({}, 'pc'))['generated'])
        phone = V.decode_index_full(V.encode_index({'n.md': a}, 'p1', caps=V.CAPS))
        self.assertEqual((phone['caps'], phone['generated'], phone['removed']), ({'generated', 'identity'}, None, {}))
        old = V.decode_index_full(V.encode_index({'n.md': a}, 'p1'))
        self.assertEqual(old['caps'], set())
        self.assertEqual(V.CAPS, ('generated', 'identity'))
        ack = V.decode_index_full(V.encode_index({'n.md': a}, 'p1', vault='v1', kept={'n.md': 'c' * 64, 'absent.md': 'd' * 64, 'bad.md': 'x'}))
        self.assertEqual((ack['vault'], ack['kept']), ('v1', {'n.md': 'c' * 64}))

    def test_path_identity_and_sha256(self):
        """A classic vault's identity is a hash of its resolved folder (case-insensitive, slashes folded)."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'Vault'
            p.mkdir()
            one = V.path_identity(p)
            self.assertTrue(one.startswith('path:') and len(one) == 37)
            self.assertEqual(one, V.path_identity(str(p).upper() + '\\'))
            self.assertNotEqual(one, V.path_identity(Path(td)))
        self.assertEqual(V.sha256_hex(b'x'), '2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881')
        self.assertTrue(V.excluded('.brainamon') and V.excluded('.brainamon/manifest.json'))

    def test_apply_conflict_trash_and_pull(self):
        self.put('a.md', 'phone version')
        self.put('gone.md', 'old')
        plan = V.Plan(pull={'a.md': 'idA', 'new/n.md': 'idN'}, trash=['gone.md'], conflicts={'a.md': 'a (phone conflict 2026-10-12 0930).md'})
        blobs = {'idA': b'pc version', 'idN': b'new'}
        V.apply(self.root, plan, blobs.__getitem__)
        self.assertEqual((self.root / 'a.md').read_text(), 'pc version')
        self.assertEqual((self.root / 'a (phone conflict 2026-10-12 0930).md').read_text(), 'phone version')
        self.assertEqual((self.root / 'new' / 'n.md').read_text(), 'new')
        self.assertFalse((self.root / 'gone.md').exists())
        self.assertEqual((self.root / '.trash' / 'gone.md').read_text(), 'old')
        self.assertEqual([p.name for p in self.root.rglob('*') if p.name.endswith(V.TMP_SUFFIX)], [])

    def test_trash_never_overwrites(self):
        self.put('.trash/x.md', 'first')
        self.put('x.md', 'second')
        V.to_trash(self.root, 'x.md')
        self.assertEqual((self.root / '.trash' / 'x.md').read_text(), 'first')
        self.assertEqual((self.root / '.trash' / 'x (2).md').read_text(), 'second')


if __name__ == '__main__':
    unittest.main()
