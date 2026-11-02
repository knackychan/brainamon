"""Local MCP server, read tools (projects/mcp-local/PLAN.md Step 1).

Run from the project root:  py -m unittest tests.test_mcp_reads -v
No network, no key, no running app: a temp library opened read-only.
"""
import io
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core.db import Database
from mcp_local import reads
from server import store

try:
    from mcp_local import app as mcp_app
except ImportError:                      # lean remote sessions without the MCP SDK
    mcp_app = None

ROOT = Path(__file__).resolve().parent.parent


class ReadsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.pasta = db.add_item({'url': 'https://youtu.be/a', 'description': 'pasta carbonara recipe',
                                  'creator': 'chef', 'type': 'Video'})
        self.bike = db.add_item({'url': 'https://youtu.be/b', 'description': 'bike repair basics'})
        self.done = db.add_item({'url': 'https://youtu.be/c', 'description': 'garden tips'})
        db.update_item(self.done, {'ai_desc': 'Tips for a small garden', 'category': 'GARDEN'})
        item_dir = db.item_dir(self.pasta)
        (item_dir / 'report.md').write_text('# Report\nboil water', encoding='utf-8')
        (item_dir / 'secret.txt').write_text('not served', encoding='utf-8')
        db.notes_dir.mkdir(exist_ok=True)
        (db.notes_dir / 'cooking.md').write_text('---\ntopic: Cooking\n---\n\nsalt the water', encoding='utf-8')
        (db.notes_dir / 'diary.md').write_text('---\ntopic: Diary\nkind: personal\ncategory: General\n---\n\nmessy bits', encoding='utf-8')
        db.reindex_notes()
        db.close()
        self.db = store.reader(self.data / 'content_manager.db')

    def test_stats(self):
        s = reads.stats(self.db)
        self.assertEqual(s['items'], 3)
        self.assertEqual(s['missing']['description'], 2)
        self.assertEqual(s['missing']['thumbnail'], 3)

    def test_search_full_text_without_embedding(self):
        r = reads.search(self.db, 'pasta', limit=5)
        self.assertEqual([i['id'] for i in r['items']], [self.pasta])
        self.assertFalse(r['semantic'])

    def test_search_survives_a_dead_embedder(self):
        r = reads.search(self.db, 'pasta', embed=lambda q: None)
        self.assertEqual(r['count'], 1)

    def test_list_items_missing(self):
        r = reads.list_items(self.db, missing='description')
        self.assertEqual(sorted(i['id'] for i in r['items']), sorted([self.pasta, self.bike]))
        self.assertEqual(r['total'], 2)
        r = reads.list_items(self.db, category='GARDEN')
        self.assertEqual([i['id'] for i in r['items']], [self.done])
        with self.assertRaises(ValueError):
            reads.list_items(self.db, missing='1; DROP TABLE items')

    def test_list_items_paging(self):
        r = reads.list_items(self.db, offset=1, limit=1)
        self.assertEqual((r['total'], r['count']), (3, 1))

    def test_show_item_and_files(self):
        r = reads.show_item(self.db, self.pasta)
        self.assertIn('report.md', r['files'])
        self.assertEqual(r['creator'], 'chef')
        with self.assertRaises(ValueError):
            reads.show_item(self.db, 9999)

    def test_read_item_file_allow_list(self):
        r = reads.read_item_file(self.db, self.pasta, 'report.md')
        self.assertIn('boil water', r['text'])
        for bad in ('secret.txt', '../content_manager.db', '..\\..\\x', 'transcript.txt'):
            with self.assertRaises(ValueError):
                reads.read_item_file(self.db, self.pasta, bad)

    def test_notes(self):
        self.assertEqual(reads.list_notes(self.db)['notes'], ['cooking.md', 'diary.md'])
        self.assertEqual(reads.search_notes(self.db, 'salt')['count'], 1)
        self.assertIn('salt the water', reads.read_note(self.db, 'cooking.md')['text'])
        for bad in ('../x.md', 'cooking.txt', '', 'missing.md'):
            with self.assertRaises(ValueError):
                reads.read_note(self.db, bad)

    def test_personal_notes(self):
        r = reads.list_personal_notes(self.db)
        self.assertEqual((r['count'], r['notes'][0]['file'], r['notes'][0]['category']), (1, 'diary.md', 'General'))
        self.assertEqual(r['notes'][0]['chars'], len('messy bits'))

    def test_note_categories(self):
        from knowledge import my_notes
        rw = Database(self.data / 'content_manager.db')
        my_notes.add_category(rw, 'Training')
        rw.close()
        r = reads.note_categories(store.reader(self.data / 'content_manager.db'))
        self.assertEqual(r['categories'], ['General', 'Training'])

    def test_connection_is_read_only(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.db.conn.execute("UPDATE items SET category = 'X'")


    def test_topics_with_and_without_cache(self):
        from library import map_engine
        self.assertEqual(reads.list_topics(self.db), {'count': 0, 'topics': []})
        with self.assertRaises(ValueError):
            reads.read_topic(self.db, 't-1')
        cache = map_engine.empty('m')
        cache['clusters']['t-1'] = {'title': 'Cooking', 'synthesis': 'Salt first.\nThen taste.', 'member_ids': [self.pasta, self.done, 999],
                                    'name': 'cooking-t1', 'summary_basis': None, 'stale': True}
        cache['clusters']['t-2'] = {'title': '', 'synthesis': '', 'member_ids': [self.bike], 'name': '', 'summary_basis': None, 'stale': False}
        map_engine.save(self.data / 'obsidian_graph.json', cache)
        r = reads.list_topics(self.db)
        self.assertEqual(r['count'], 2)
        self.assertEqual(r['topics'][0], {'id': 't-1', 'title': 'Cooking', 'items': 3, 'status': 'stale', 'summary': 'Salt first.'})
        self.assertEqual(r['topics'][1]['status'], 'new')
        t = reads.read_topic(self.db, 't-1')
        self.assertEqual((t['id'], t['title'], t['status']), ('t-1', 'Cooking', 'stale'))
        self.assertEqual(t['summary'], 'Salt first.\nThen taste.')
        self.assertEqual([m['id'] for m in t['items']], [self.pasta, self.done])     # 999 is gone from the library
        self.assertEqual(t['items'][1]['title'], 'Tips for a small garden')
        with self.assertRaises(ValueError):
            reads.read_topic(self.db, 'topic:t-9')

        # Current text determines status without rewriting the cache or running maintenance.
        from core import ai_client
        cache['clusters']['t-1']['member_ids'] = [self.pasta, self.done]
        fps = map_engine.fingerprints(ai_client.EMBEDDING_MODEL, self.db.get_items_by_ids([self.pasta, self.done]))
        cache['clusters']['t-1']['summary_basis'] = {str(i): fp for i, fp in fps.items()}
        path = self.data / 'obsidian_graph.json'
        map_engine.save(path, cache)
        saved = path.read_bytes()
        self.assertEqual(reads.list_topics(self.db)['topics'][0]['status'], 'fresh')
        self.assertEqual(reads.read_topic(self.db, 'topic:t-1')['status'], 'fresh')
        writer = Database(self.data / 'content_manager.db')
        try:
            writer.update_item(self.pasta, {'transcript': 'New transcript text'})
        finally:
            writer.close()
        self.assertEqual(reads.list_topics(self.db)['topics'][0]['status'], 'stale')
        self.assertEqual(reads.read_topic(self.db, 't-1')['status'], 'stale')
        self.assertEqual(path.read_bytes(), saved)


@unittest.skipIf(mcp_app is None, 'needs the MCP SDK (pip install mcp)')
class EmbedFallbackTest(unittest.TestCase):
    """search_library (semantic=True by default) when the query embedding fails or stalls: full-text results
    still come back, quickly, with no network call (embed_texts is replaced)."""

    def setUp(self):
        ReadsTest.setUp(self)           # the same temp library
        for p in (mock.patch.object(mcp_app, 'DB_PATH', self.data / 'content_manager.db'),
                  mock.patch.object(mcp_app, '_embed_off_until', 0.0),
                  mock.patch.object(mcp_app, 'EMBED_TIMEOUT', 0.3),
                  mock.patch.object(mcp_app.sys, 'stderr', io.StringIO())):
            p.start()
            self.addCleanup(p.stop)

    def test_failed_embedding_keeps_full_text(self):
        with mock.patch('core.ai_client.embed_texts', side_effect=RuntimeError('connection refused')) as embed:
            r = mcp_app.search_library('pasta')
        embed.assert_called_once()
        self.assertEqual([i['id'] for i in r['items']], [self.pasta])
        self.assertFalse(r['semantic'])

    def test_stalled_embedding_times_out_then_cools_down(self):
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []

        def stalled(texts):
            calls.append(texts)
            release.wait(30)            # an OpenAI read that does not answer
            return [[0.0]]
        with mock.patch('core.ai_client.embed_texts', stalled):
            t0 = time.monotonic()
            r = mcp_app.search_library('pasta')
            self.assertLess(time.monotonic() - t0, 5)
            self.assertEqual([i['id'] for i in r['items']], [self.pasta])
            self.assertFalse(r['semantic'])
            r = mcp_app.search_library('bike')          # cooldown: no second embedding, no second wait
            self.assertEqual([i['id'] for i in r['items']], [self.bike])
        self.assertEqual(len(calls), 1)


class SourceRulesTest(unittest.TestCase):
    """Invariants 1 and 2: no writable connection, no file change, anywhere under mcp_local/."""

    def test_no_writable_database_and_no_file_changes(self):
        banned = ('unlink', 'rmtree', 'os.remove', 'shutil', 'write_text', 'write_bytes',
                  'sqlite3.connect', 'os.rename', 'os.replace')
        for path in (ROOT / 'mcp_local').glob('*.py'):
            text = path.read_text(encoding='utf-8')
            for word in banned:
                self.assertNotIn(word, text, f'{path.name} contains {word}')
            for line in text.splitlines():
                if 'Database(' in line:
                    self.assertIn('ReadOnlyDatabase(', line, f'{path.name}: {line.strip()}')


if __name__ == '__main__':
    unittest.main()
