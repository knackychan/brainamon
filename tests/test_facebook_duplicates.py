"""Facebook identity across desktop imports, phone sync and existing URL forms; synthetic data only."""
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db import Database, ReadOnlyDatabase
from core.urls import facebook_post_key
from library.importers import import_csv
from server import intake

FIXTURE = Path(__file__).parent / 'fixtures' / 'site_cards' / 'facebook.json'
WATCH = 'https://www.facebook.com/watch/?v=1234567890'
REEL = 'https://www.facebook.com/reel/1234567890/'


class FacebookDuplicateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = Database(self.root / 'content_manager.db')
        self.addCleanup(self.db.close)

    def test_identity_matches_phone_fixtures_and_rejects_lookalikes(self):
        for url, _canonical, key in json.loads(FIXTURE.read_text(encoding='utf-8'))['links']:
            with self.subTest(url=url):
                self.assertEqual(facebook_post_key(url), key)
        for url in ('https://user@facebook.com/reel/1234567890/',
                    'https://facebook.com:8443/reel/1234567890/',
                    REEL + 'extra', WATCH + 'evil',
                    'https://example.com/?v=1234567890'):
            self.assertEqual(facebook_post_key(url), '', url)

    def test_existing_urls_are_found_without_changing_the_records(self):
        variants = [WATCH, REEL, 'http://m.facebook.com/Example/videos/title/1234567890?ref=save',
                    'https://facebook.com/watch/?v=%31%32%33%34%35%36%37%38%39%30']
        for stored in variants:
            with self.subTest(stored=stored):
                item = self.db.add_item({'url': stored, 'description': 'Full original caption'})
                before = self.db.get_item(item)
                reader = ReadOnlyDatabase(self.db.db_path)
                try:
                    for url in variants:
                        self.assertEqual(reader.get_item_by_url(url), before)
                    self.assertFalse(reader.item_exists('https://facebook.com/reel/12345678901/'))
                    self.assertFalse(reader.item_exists('https://example.com/reel/1234567890/'))
                finally:
                    reader.close()
                self.assertEqual(self.db.get_item(item), before)
                self.db.delete_item(item)

    def test_desktop_imports_skip_aliases_with_different_titles_and_descriptions(self):
        for stored, incoming in ((WATCH, REEL), (REEL, WATCH)):
            with self.subTest(stored=stored):
                item = self.db.add_item({'url': stored, 'description': 'Full recipe', 'source': 'phone'})
                self.db.update_item(item, {'notes': 'Personal note', 'short_desc': 'My title'})
                before = self.db.get_item(item)
                path = self.root / 'facebook.csv'
                with path.open('w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['url', 'description', 'short_desc'])
                    writer.writeheader()
                    writer.writerow({'url': incoming, 'description': 'Creator, view story', 'short_desc': 'Other title'})
                counts = {}
                self.assertEqual(import_csv(self.db, path, counts), (0, 1, []))
                self.assertEqual(counts, {'duplicates': 1})
                exported = self.root / 'facebook.json'
                exported.write_text(json.dumps([{'url': incoming, 'description': 'Changed again'}]), encoding='utf-8')
                self.assertEqual(self.db.import_from_json(exported), (0, 1))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.add_item({'url': incoming})
                self.assertEqual(self.db.get_item(item), before)
                self.assertEqual(self.db.count_items(), 1)
                self.db.delete_item(item)

    def test_phone_alias_keeps_details_and_later_edits_on_the_original(self):
        item = self.db.add_item({'url': REEL, 'description': 'Original caption', 'short_desc': 'My title'})
        original_uid = self.db.get_item(item)['uid']
        phone_uid = 'ab' * 16
        out = intake.apply(self.db, {'changes': [
            {'op': 'link', 'uid': phone_uid, 'url': WATCH},
            {'op': 'details', 'uid': phone_uid, 'desc': 'Different caption', 'title': 'Different title', 'creator': 'Sam'},
        ]})
        self.assertEqual((out.links, out.dups, out.skipped), (0, 1, 0))
        self.assertEqual(out.alias, {phone_uid: original_uid})
        out = intake.apply(self.db, {'changes': [{'op': 'fav', 'uid': phone_uid, 'on': True}]}, out)
        self.assertEqual(out.skipped, 0)
        row = self.db.get_item(item)
        self.assertEqual((row['description'], row['short_desc'], row['creator'], row['favourite']),
                         ('Original caption', 'My title', 'Sam', 1))
        self.assertEqual(self.db.count_items(), 1)

    def test_legacy_duplicates_remain_and_exact_links_keep_their_identity(self):
        first = self.db.add_item({'url': WATCH, 'description': 'Original'})
        # Simulate the pair saved by the old version, before the shared identity check existed.
        second = self.db.conn.execute('INSERT INTO items (url, description, uid) VALUES (?, ?, ?)',
                                      (REEL, 'Other caption', 'cd' * 16)).lastrowid
        self.db.conn.commit()
        self.assertEqual(self.db.get_item_by_url(WATCH)['id'], first)
        self.assertEqual(self.db.get_item_by_url(REEL)['id'], second)
        self.assertEqual(self.db.count_items(), 2)


if __name__ == '__main__':
    unittest.main()
