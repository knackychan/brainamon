"""Regression tests for db.py data-layer behavior.

Run from the project root:  py -m unittest tests.test_db_regressions -v
"""

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db import Database


_ONE_PIXEL_JPEG = base64.b64decode(
    b'/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////'
    b'////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////////////'
    b'////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQ'
    b'AxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/ASP/xAAUEQEAAAAAAAAAAAAAAAAA'
    b'AAAA/9oACAECAQE/ASP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Ar//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IX//2gAMAwEA'
    b'AhEDEQA/AP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAA'
    b'AAAAAAAAABD/2gAIAQEAAT8QH//Z'
)


class DatabaseRegressionTest(unittest.TestCase):
    def _db(self):
        td = tempfile.TemporaryDirectory()
        db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(td.cleanup)
        self.addCleanup(db.close)
        return db

    def test_update_category_same_name_updates_color(self):
        db = self._db()
        db.add_category('TEST', '#111111')

        db.update_category('TEST', 'TEST', '#222222')

        self.assertEqual(db.category_color('TEST'), '#222222')

    def test_empty_collections_stay_empty_when_reopened(self):
        db = self._db()
        self.assertEqual(db.get_categories(), [])
        db.add_category('CUSTOM', '#123456')
        item = db.add_item({'url': 'https://example.com/item', 'category': 'CUSTOM'})
        db.delete_category('CUSTOM')
        reopened = Database(db.db_path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_categories(), [])
        self.assertEqual([r['id'] for r in reopened.search_items()], [item])
        self.assertEqual(reopened.get_item(item)['category'], 'INTERESTING')

    def test_existing_collections_and_items_are_preserved_when_reopened(self):
        db = self._db()
        db.add_category('SPORT', '#2E75B6')
        db.add_category('CUSTOM', '#123456', hidden=True)
        item = db.add_item({'url': 'https://example.com/item', 'category': 'CUSTOM'})
        categories = db.get_categories()
        original = db.get_item(item)
        reopened = Database(db.db_path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_categories(), categories)
        self.assertEqual(reopened.get_item(item), original)

    def test_tag_filter_matches_whole_tags_only(self):
        db = self._db()
        ai_id = db.add_item({'url': 'u1', 'description': 'one', 'tags': 'ai'})
        db.add_item({'url': 'u2', 'description': 'two', 'tags': 'painting'})

        rows = db.search_items(tag_filter='ai', sort='old')

        self.assertEqual([r['id'] for r in rows], [ai_id])

    def test_thumb_b64_migration_creates_item_thumbnail(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'content_manager.db'
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    thumb_b64 TEXT,
                    thumb_path TEXT DEFAULT ''
                )
            """)
            conn.execute(
                "INSERT INTO items (url, thumb_b64) VALUES (?, ?)",
                ('legacy', base64.b64encode(_ONE_PIXEL_JPEG).decode('ascii')),
            )
            conn.commit()
            conn.close()

            db = Database(db_path)

            try:
                self.assertEqual(db.get_item_thumb(1), 'thumb.jpg')
                self.assertTrue((Path(td) / 'items' / '1' / 'thumb.jpg').exists())
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
