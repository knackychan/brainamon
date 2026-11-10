"""My Notes categories (docs/superpowers/specs/2026-11-07-phone-note-page-design.md, sections 3-4): the name
rules and the rename in Python (knowledge/my_notes.py) and TypeScript (web/src/lib/note-category.ts) against one
fixture; the phone's `note_category` change on the PC (server/intake.py); the direct rename route.
Temp data only. Run:  py -m unittest tests.test_note_category -v
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.auth_client import TestClient
from tests.test_phone_js import TS_RESOLVE, _node_ok, node

from core.db import Database
from knowledge import knowledge, my_notes
from server import intake
from server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
FX = json.loads((ROOT / 'tests/fixtures/note_category.json').read_text(encoding='utf-8'))
UPDATED = '2026-11-07T10:00:00'
BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def write(notes_dir: Path, file: str, category: str, kind: str = 'personal') -> Path:
    notes_dir.mkdir(parents=True, exist_ok=True)
    meta = {'topic': file[:-3], 'created': UPDATED, 'updated': UPDATED, 'kind': kind}
    if category:
        meta['category'] = category
    path = notes_dir / file
    my_notes._write(path, meta, 'Body line.\n')
    return path


def category_of(notes_dir: Path, file: str) -> str:
    meta, _ = knowledge.split_frontmatter((notes_dir / file).read_text(encoding='utf-8'))
    return meta.get('category') or 'General'


class NoteCategoryPythonTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.notes = Path(self.db.notes_dir)

    def test_names_follow_the_fixture(self):
        for case in FX['names']:
            with self.subTest(case=case):
                if 'error' in case:
                    with self.assertRaises(ValueError) as e:
                        my_notes.clean_category(case['in'])
                    self.assertEqual(str(e.exception), FX['errors'][case['error']])
                else:
                    self.assertEqual(my_notes.clean_category(case['in']), case['out'])
        self.assertEqual(my_notes.clean_category('x' * FX['max']), 'x' * FX['max'])
        with self.assertRaises(ValueError) as e:
            my_notes.clean_category('x' * (FX['max'] + 1))
        self.assertEqual(str(e.exception), FX['errors']['long'])

    def test_renames_follow_the_fixture(self):
        for case in FX['renames']:
            with self.subTest(case=case['name']):
                for p in self.notes.glob('*.md'):
                    p.unlink()
                for file, category in case['notes'].items():
                    write(self.notes, file, category)
                try:
                    for old, new in case['steps']:
                        my_notes.rename_category(self.db, self.notes, old, new)
                except ValueError as e:
                    self.assertEqual(str(e), FX['errors'][case['error']])
                    continue
                self.assertNotIn('error', case)
                self.assertEqual({f: category_of(self.notes, f) for f in case['notes']}, case['after'])

    def test_rename_keeps_updated_body_and_other_kinds_and_renames_the_stored_list(self):
        my_notes.add_category(self.db, 'Health')
        my_notes.add_category(self.db, 'fitness')
        a = write(self.notes, 'a.md', 'Health')
        write(self.notes, 'topic.md', 'Health', kind='topic')
        before = a.read_text(encoding='utf-8')
        paths = my_notes.rename_category(self.db, self.notes, 'Health', 'Fitness')
        self.assertEqual([p.name for p in paths], ['a.md'])
        self.assertEqual(a.read_text(encoding='utf-8'), before.replace('category: Health', 'category: Fitness'))
        self.assertEqual(category_of(self.notes, 'topic.md'), 'Health')
        self.assertEqual(my_notes.stored_categories(self.db), ['Fitness'])

    def test_intake_renames_and_a_later_phone_edit_still_lands_in_place(self):
        write(self.notes, 'a.md', 'Health')
        t = int(time.time() * 1000)
        doc = lambda changes, at: {'format': 1, 'device': 'phone-1', 'at': at, 'changes': changes}
        out = intake.apply(self.db, doc([{'op': 'note_category', 'from': 'Health', 'to': 'Fitness', 'at': t}], t))
        self.assertEqual(out.notes, ['a.md'])
        meta, _ = knowledge.split_frontmatter((self.notes / 'a.md').read_text(encoding='utf-8'))
        self.assertEqual((meta['category'], meta['updated']), ('Fitness', UPDATED))
        intake.apply(self.db, doc([{'op': 'note', 'file': 'a.md', 'title': 'a', 'category': 'Fitness', 'body': 'New text.',
                                    'was': UPDATED, 'at': t + 1}], t + 1))
        self.assertEqual(sorted(p.name for p in self.notes.glob('*.md')), ['a.md'])
        self.assertIn('New text.', (self.notes / 'a.md').read_text(encoding='utf-8'))

    def test_intake_skips_a_refused_rename_and_applies_the_rest(self):
        write(self.notes, 'a.md', 'Health')
        t = int(time.time() * 1000)
        out = intake.apply(self.db, {'format': 1, 'device': 'phone-1', 'at': t, 'changes': [
            {'op': 'note_category', 'from': 'General', 'to': 'Other', 'at': t},
            {'op': 'note_category', 'from': 'Health', 'to': 7, 'at': t},
            {'op': 'note_category', 'from': 'Health', 'to': 'Gym', 'at': t}]})
        self.assertEqual(out.skipped, 2)
        self.assertEqual(category_of(self.notes, 'a.md'), 'Gym')

    @unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
    def test_later_note_save_stays_after_a_queued_rename_without_a_conflict_copy(self):
        queue = json.loads(node(TS_RESOLVE + 'const updated = ' + json.dumps(UPDATED) + """
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes()
            const note = { op: 'note', file: 'a.md', title: 'a', category: 'Health', body: 'First.', was: updated }
            await c.add(note)
            await c.add({ op: 'note_category', from: 'Health', to: 'Gym' })
            await c.add({ ...note, body: 'Second.', was: 'local edit' })
            await c.add({ ...note, body: 'Latest.', was: 'another local edit' })
            console.log(JSON.stringify(c.list))
        """))
        self.assertEqual([e['op'] for e in queue], ['note_category', 'note'])
        self.assertEqual(queue[-1]['was'], UPDATED)
        write(self.notes, 'a.md', 'Health')
        out = intake.apply(self.db, {'format': 1, 'device': 'phone-1', 'at': max(e['at'] for e in queue), 'changes': queue})
        self.assertEqual((out.kept_pc, out.skipped), (0, 0))
        self.assertEqual(sorted(p.name for p in self.notes.glob('*.md')), ['a.md'])
        self.assertEqual(category_of(self.notes, 'a.md'), 'Health')
        self.assertIn('Latest.', (self.notes / 'a.md').read_text(encoding='utf-8'))


class RenameRouteTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        Database(self.data / 'content_manager.db').close()
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765,
                                       web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_rename_route(self):
        self.c.post('/api/my-notes/categories', json={'name': 'Health'}, headers=W)
        self.c.post('/api/my-notes', json={'title': 'Knee plan', 'category': 'Health'}, headers=W)
        r = self.c.post('/api/my-notes/categories/rename', json={'from': 'Health', 'to': 'Fitness'}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('Fitness', r.json()['categories'])
        self.assertNotIn('Health', r.json()['categories'])
        self.assertEqual(self.c.get('/api/my-notes/knee-plan.md').json()['category'], 'Fitness')
        bad = self.c.post('/api/my-notes/categories/rename', json={'from': 'General', 'to': 'Other'}, headers=W)
        self.assertEqual((bad.status_code, bad.json()['detail']), (400, FX['errors']['general']))

    def test_rename_route_rejects_non_string_names_without_changing_notes(self):
        self.c.post('/api/my-notes', json={'title': 'Knee plan', 'category': 'Health'}, headers=W)
        for field in ('from', 'to'):
            for value in (7, True, [], {}, None):
                with self.subTest(field=field, value=value):
                    body = {'from': 'Health', 'to': 'Fitness', field: value}
                    r = self.c.post('/api/my-notes/categories/rename', json=body, headers=W)
                    self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.c.get('/api/my-notes/knee-plan.md').json()['category'], 'Health')


JS = """
const M = await import('./web/src/lib/note-category.ts')
const run = f => { try { return { out: f() } } catch (e) { return { error: e.message } } }
const names = FX.names.map(c => run(() => M.cleanCategory(c.in)))
const long = [run(() => M.cleanCategory('x'.repeat(FX.max))), run(() => M.cleanCategory('x'.repeat(FX.max + 1)))]
const renames = FX.renames.map(c => {
  let notes = Object.entries(c.notes).map(([file, category]) => ({ file, meta: category ? { kind: 'personal', category } : { kind: 'personal' } }))
  try {
    for (const [f, t] of c.steps) { const r = M.checkRename(f, t); notes = M.renameNotes(notes, r.from, r.to) }
    return { after: Object.fromEntries(notes.map(n => [n.file, n.meta.category || 'General'])) }
  } catch (e) { return { error: e.message } }
})
const other = [M.otherNamed(['General', 'Health', 'Work'], 'health', 'Gym') ?? null, M.otherNamed(['Health'], 'health', 'Health') ?? null,
  M.otherNamed(['Health'], 'Fitness', '') ?? null]
const topic = M.renameNotes([{ file: 't.md', meta: { kind: 'topic', category: 'Health' } }], 'Health', 'X')[0].meta.category
console.log(JSON.stringify({ names, long, renames, other, topic, needsPc: M.RENAME_NEEDS_PC }))
"""


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class NoteCategoryTsTest(unittest.TestCase):
    def test_the_phone_rules_match_the_fixture(self):
        out = json.loads(node(TS_RESOLVE + 'const FX = ' + json.dumps(FX) + '\n' + JS))
        self.assertEqual(out['names'], [{'error': FX['errors'][c['error']]} if 'error' in c else {'out': c['out']} for c in FX['names']])
        self.assertEqual(out['long'], [{'out': 'x' * FX['max']}, {'error': FX['errors']['long']}])
        self.assertEqual(out['renames'], [{'error': FX['errors'][c['error']]} if 'error' in c else {'after': c['after']} for c in FX['renames']])
        self.assertEqual(out['other'], ['Health', None, None])
        self.assertEqual(out['topic'], 'Health')
        self.assertEqual(out['needsPc'], 'Update Brainamon on the PC to rename.')
