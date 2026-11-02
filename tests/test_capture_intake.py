"""What Add to Brainamon on the phone sends the PC, through the one intake (server/intake.py apply, on the
Writer in the app): a saved link keeps its comment, collection and tags and never doubles (items.url is
UNIQUE); a new note arrives as a `note` change; an addition arrives as a `note_append` change that adds one
section at the end of the PC's CURRENT note, so whatever the PC wrote since the phone read the note stays;
an addition to a note gone on the PC keeps its text in a new note; additions queued offline are never
folded into one another (projects/note-organic-ui/plans/09-add-to-brainamon.md).
Temp data only. Run:  py -m unittest tests.test_capture_intake -v
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from core.db import Database
from knowledge import knowledge, my_notes
from server import intake
from tests import test_phone_js

UID = 'a' * 32
FILE = 'a-thought-1a2b3c.md'
HOUR = 3600_000


class CaptureIntakeTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        self.db = Database(self.data / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.t = int(time.time() * 1000)

    def doc(self, changes, device='phone-1', later=0):
        return {'format': 1, 'device': device, 'at': self.t + later, 'changes': changes}

    def note(self, file=FILE):
        return knowledge.split_frontmatter((Path(self.db.notes_dir) / file).read_text(encoding='utf-8'))

    def made(self, body='First line.\n'):
        # createMyNote then saveMyNote on the phone: the queue folds both into one `note` change (changes.ts add)
        intake.apply(self.db, self.doc([{'op': 'note', 'file': FILE, 'title': 'A thought', 'category': 'Inbox', 'body': body, 'was': '', 'at': self.t}]))

    def append(self, later, file=FILE, text='Second.'):
        return intake.apply(self.db, self.doc([{'op': 'note_append', 'file': file, 'title': 'A thought', 'name': 'Note', 'text': text,
                                                'when': '2026-10-18 10:01', 'at': self.t + later}], later=later))

    def test_a_saved_link_keeps_comment_collection_and_tags_and_never_doubles(self):
        link = {'op': 'link', 'uid': UID, 'url': 'https://example.com/read-later?igsh=zz', 'note': 'Why I kept it',
                'category': 'Reading', 'tags': 'a, b', 'at': self.t}
        out = intake.apply(self.db, self.doc([link]))
        again = intake.apply(self.db, self.doc([{**link, 'uid': 'b' * 32}], device='phone-2'))
        row = self.db.conn.execute('SELECT url, notes, category, tags, source FROM items').fetchall()
        self.assertEqual(len(row), 1)
        self.assertEqual(tuple(row[0]), ('https://example.com/read-later', 'Why I kept it', 'Reading', 'a, b', 'phone'))
        self.assertEqual((out.links, out.dups, again.links, again.dups), (1, 0, 0, 1))
        self.assertEqual(len(out.new_ids), 1)

    def test_a_tag_edit_after_the_link_lands_on_the_same_item(self):
        intake.apply(self.db, self.doc([{'op': 'link', 'uid': UID, 'url': 'https://example.com/a', 'note': '', 'category': '', 'at': self.t}]))
        out = intake.apply(self.db, self.doc([{'op': 'edit', 'uid': UID, 'fields': {'tags': 'x, y', 'notes': 'late comment'}, 'was': {'tags': '', 'notes': ''}, 'at': self.t + 5}], later=5))
        tags, notes = self.db.conn.execute('SELECT tags, notes FROM items').fetchone()
        self.assertEqual((tags, notes, out.edits), ('x, y', 'late comment', 1))

    def test_a_new_note_then_an_addition_keeps_the_old_text_first(self):
        self.made()
        meta, body = self.note()
        self.assertEqual((meta['kind'], meta['category'], meta['topic'], body.strip()), ('personal', 'Inbox', 'A thought', 'First line.'))
        out = self.append(90_000)
        self.assertEqual(out.notes, [FILE])
        meta2, after = self.note()
        self.assertEqual(after, 'First line.\n\n## From Note - 2026-10-18 10:01\n\nSecond.\n')
        self.assertEqual((meta2['kind'], meta2['category'], meta2['topic']), ('personal', 'Inbox', 'A thought'))

    def test_an_addition_keeps_what_the_pc_wrote_since_the_phone_read_it(self):
        self.made()
        my_notes.save_note(Path(self.db.notes_dir) / FILE, 'A thought', 'Inbox', 'First line.\n\nThe PC wrote this later.\n')
        out = self.append(HOUR)                                   # an hour later, far past intake.SKEW
        self.assertEqual((out.notes, out.kept_pc), ([FILE], 0))
        self.assertEqual(self.note()[1], 'First line.\n\nThe PC wrote this later.\n\n## From Note - 2026-10-18 10:01\n\nSecond.\n')

    def test_an_addition_to_a_note_gone_on_the_pc_keeps_its_text(self):
        out = self.append(HOUR, file='gone-aaaaaa.md')
        self.assertEqual(out.kept_pc, 1)
        kept = [(m, b) for _p, m, b in my_notes.personal_notes(self.db.notes_dir) if m.get('topic') == 'A thought (from phone)']
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0][1].strip(), '## From Note - 2026-10-18 10:01\n\nSecond.')
        self.assertEqual(self.append(HOUR, text='   ').notes, [], 'an empty addition is nothing')

    @unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
    def test_two_additions_queued_offline_stay_two_changes_and_a_delete_drops_them(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            // an in-memory IndexedDB, just what web/src/mobile/store.ts uses (as in tests/test_phone_mirror.py)
            const stores = {}
            const req = v => { const r = { result: v }; setTimeout(() => r.onsuccess?.()); return r }
            const keyOf = (s, v, k) => (s.opts?.autoIncrement && v[s.opts.keyPath] === undefined ? ++s.n : s.opts?.keyPath ? v[s.opts.keyPath] : k)
            globalThis.indexedDB = { open() {
              const d = {
                objectStoreNames: { contains: n => n in stores },
                createObjectStore(n, opts) { stores[n] = { opts, m: new Map(), n: 0 } },
                transaction(n) {
                  const s = stores[n], t = { objectStore: () => ({
                    get: k => req(structuredClone(s.m.get(k))),
                    getAll: () => req([...s.m.values()].map(v => structuredClone(v))),
                    getAllKeys: () => req([...s.m.keys()]),
                    add(v, k) { k = keyOf(s, v, k); s.m.set(k, structuredClone(s.opts?.keyPath ? { ...v, [s.opts.keyPath]: k } : v)); return req(k) },
                    put(v, k) { k = keyOf(s, v, k); s.m.set(k, structuredClone(v)); return req(k) },
                    delete(k) { s.m.delete(k); return req(undefined) },
                    clear() { s.m.clear(); return req(undefined) },
                  }) }
                  setTimeout(() => setTimeout(() => t.oncomplete?.()))
                  return t
                },
              }
              const r = { result: d }
              setTimeout(() => { r.onupgradeneeded?.(); r.onsuccess?.() })
              return r
            } }
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes()
            await c.add({ op: 'note_append', file: 'a-thought-1a2b3c.md', title: 'A thought', name: 'Note', text: 'one', when: '2026-10-18 10:01' })
            await c.add({ op: 'note_append', file: 'a-thought-1a2b3c.md', title: 'A thought', name: 'Note', text: 'two', when: '2026-10-18 10:02' })
            const queued = c.list.map(e => e.text)
            await c.dropQueuedNote('a-thought-1a2b3c.md')            // the note was deleted on the phone: its additions never go
            console.log(JSON.stringify({ queued, after: c.list.length }))
        """))
        self.assertEqual(out, {'queued': ['one', 'two'], 'after': 0})


if __name__ == '__main__':
    unittest.main()
