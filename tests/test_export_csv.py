"""export.export_items_csv: header is EXPORT_FIELDS, one row per item.

Run from the project root:  py -m unittest tests.test_export_csv -v
"""
import csv
import tempfile
import unittest
from pathlib import Path

from core.db import Database
from library import export, importers


class ExportItemsCsvTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)
        self.db = Database(self.dir / 'data' / 'content_manager.db')
        self.addCleanup(self.db.close)

    def test_header_and_one_row_per_item(self):
        urls = ['https://x/1', 'https://x/2', 'https://x/3']
        for i, u in enumerate(urls):
            self.db.add_item({'url': u, 'description': f'Item, "{i}"', 'creator': 'Coach',
                              'type': 'Reel', 'category': 'INTERESTING', 'prefix': '',
                              'tags': 'a,b', 'ai_desc': '', 'thumb_path': '', 'source': 'test'})
        out = self.dir / 'items.csv'
        self.assertEqual(export.export_items_csv(self.db, out), 3)
        with open(out, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(reader.fieldnames, importers.EXPORT_FIELDS)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r['url'] for r in rows}, set(urls))
        self.assertIn('Item, "0"', {r['description'] for r in rows})

    def test_empty_library_header_only(self):
        out = self.dir / 'empty.csv'
        self.assertEqual(export.export_items_csv(self.db, out), 0)
        with open(out, encoding='utf-8-sig', newline='') as f:
            self.assertEqual(next(csv.reader(f)), importers.EXPORT_FIELDS)


if __name__ == '__main__':
    unittest.main()
