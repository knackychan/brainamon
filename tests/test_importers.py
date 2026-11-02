"""importers.py, scrape_watch.py and obsidian_run.py (plan 12), Qt-free.

Run from the project root:  py -m unittest tests.test_importers -v
"""
import base64
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from library import importers
from library import obsidian_run
from library import scrape_watch
from library import ytdlp
from core.db import Database


def b64_jpeg() -> str:
    b = io.BytesIO()
    Image.new('RGB', (300, 500), (10, 120, 200)).save(b, 'JPEG')
    return base64.b64encode(b.getvalue()).decode()


class ImportersTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)
        self.db = Database(self.dir / 'data' / 'content_manager.db')
        self.addCleanup(self.db.close)

    def test_csv_round_trip(self):
        src = self.dir / 'fb_saved_1.csv'
        src.write_text('url,description,creator,thumb\n'
                       f'https://x/1,Hip drill,Coach,{b64_jpeg()}\n'
                       'https://x/2,Knee lift,Coach,\n'
                       ',no url,,\n', encoding='utf-8')
        added, skipped, ids = importers.import_csv(self.db, src)
        self.assertEqual((added, skipped, len(ids)), (2, 1, 2))
        self.assertEqual(self.db.get_categories(), [])
        self.assertTrue((self.db.item_dir(ids[0]) / 'thumb.jpg').is_file())
        self.assertEqual(self.db.get_item(ids[0])['thumb_path'], 'thumb.jpg')
        self.assertEqual(importers.import_csv(self.db, src)[:2], (0, 3))   # duplicates skipped
        out = self.dir / 'backup.csv'
        self.assertEqual(importers.export_csv(self.db, out), 2)
        fresh = Database(self.dir / 'other' / 'content_manager.db')
        self.addCleanup(fresh.close)
        self.assertEqual(importers.import_file(fresh, out)[:2], (2, 0))
        self.assertFalse(fresh.get_item(1)['thumb_path'])  # the image file is not in an item CSV

    def test_json(self):
        src = self.dir / 'export.json'
        src.write_text(json.dumps([{'url': 'https://x/9', 'description': 'From JSON'}]), encoding='utf-8')
        added, _skipped, ids = importers.import_file(self.db, src)
        self.assertEqual(added, len(ids))
        self.assertEqual(self.db.get_categories(), [])
        with self.assertRaises(ValueError):
            importers.import_file(self.db, self.dir / 'x.txt')

    def test_csv_preserves_item_text(self):
        item_id = self.db.add_item({'url': 'https://x/text', 'description': 'A description',
                                    'short_desc': 'Short note', 'source': 'manual'})
        self.db.update_item(item_id, {'notes': '  A personal note\nwith a second line  '})
        out = self.dir / 'items.csv'
        importers.export_csv(self.db, out)
        fresh = Database(self.dir / 'restore' / 'content_manager.db')
        self.addCleanup(fresh.close)
        added, skipped, ids = importers.import_file(fresh, out)
        self.assertEqual((added, skipped), (1, 0))
        restored = fresh.get_item(ids[0])
        self.assertEqual(restored['short_desc'], 'Short note')
        self.assertEqual(restored['notes'], '  A personal note\nwith a second line  ')
        self.assertEqual(restored['source'], 'manual')

    def test_invalid_json_row_does_not_partially_import(self):
        src = self.dir / 'invalid.json'
        src.write_text(json.dumps([{'url': 'https://x/valid'}, 42]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'JSON items'):
            importers.import_file(self.db, src)
        self.assertFalse(self.db.item_exists('https://x/valid'))
        src.write_text(json.dumps([{'url': 'https://x/valid'},
                                   {'url': 'https://x/bad', 'description': ['not text']}]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'JSON items'):
            importers.import_file(self.db, src)
        self.assertFalse(self.db.item_exists('https://x/valid'))


class ScrapeWatchTest(unittest.TestCase):
    def test_build_script(self):
        js = "const STOP_AT = '';\nconst UNSAVE_AFTER_SCRAPE = false;\n"
        out = scrape_watch.build_script(js, 'facebook', True, "Bob's \\ title")
        self.assertIn("const STOP_AT = 'Bob\\'s \\\\ title';", out)
        self.assertIn('const UNSAVE_AFTER_SCRAPE = true;', out)
        self.assertIn('UNSAVE_AFTER_SCRAPE = false', scrape_watch.build_script(js, 'instagram', True, ''))
        for key in scrape_watch.PLATFORMS:
            self.assertTrue(scrape_watch.script_for(key))

    def test_reddit_csv_is_watched(self):
        self.assertIn('reddit_saved_', scrape_watch.CSV_PREFIXES)
        self.assertIn('/saved.json', scrape_watch.script_for('reddit'))

    def test_playwright_args_per_platform(self):
        for key in scrape_watch.PLAYWRIGHT:
            with self.subTest(key=key):
                self.assertTrue(scrape_watch.playwright_script(key).is_file())
                args = scrape_watch.playwright_args(Path('W'), 'Last', True, '', key)
                self.assertEqual(args[1], str(scrape_watch.playwright_script(key)))
                self.assertEqual(args[3], str(scrape_watch.playwright_profile(key)))
                self.assertIn('--unsave', args)
                self.assertEqual(args[args.index('--stop-at') + 1], 'Last')
        self.assertEqual(scrape_watch.playwright_args(Path('W'))[1], str(scrape_watch.PLAYWRIGHT_FB))
        ig = scrape_watch.playwright_args(Path('W'), key='instagram', username='knackichan')
        self.assertEqual(ig[ig.index('--username') + 1], 'knackichan')
        self.assertNotIn('--username', scrape_watch.playwright_args(Path('W'), key='reddit', username='x'))

    def test_watcher_waits_for_a_stable_file(self):
        with tempfile.TemporaryDirectory() as td:
            got = []
            w = scrape_watch.Watcher(td, got.append)
            old = Path(td) / 'fb_saved_old.csv'
            old.write_text('x')
            os.utime(old, (time.time() - 60, time.time() - 60))
            (Path(td) / 'other.csv').write_text('x')
            new = Path(td) / 'fb_saved_new.csv'
            new.write_text('url\n')
            self.assertEqual(w.scan(), [])            # first sight: size not yet stable
            self.assertEqual([p.name for p in w.scan()], ['fb_saved_new.csv'])
            self.assertEqual(w.scan(), [])            # never twice
            self.assertEqual([p.name for p in got], ['fb_saved_new.csv'])


class CookieAndObsidianTest(unittest.TestCase):
    def test_validate_cookie_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'c.txt'
            self.assertEqual(ytdlp.validate_cookie_file(str(p)), 'missing')
            p.write_text('# Netscape HTTP Cookie File\n')
            self.assertEqual(ytdlp.validate_cookie_file(str(p)), 'invalid format')
            p.write_text('# Netscape HTTP Cookie File\n.fb.com\tTRUE\t/\tTRUE\t0\tc_user\t1\n')
            self.assertEqual(ytdlp.validate_cookie_file(str(p)), '')
            p.write_text('not cookies\n')
            self.assertEqual(ytdlp.validate_cookie_file(str(p)), 'invalid format')

    def test_tag_map_and_titles(self):
        rows = [{'tags': 'Knee, mobility'}, {'tags': 'knee,  ,vlog'}]
        self.assertEqual(obsidian_run.unmapped_tags(rows, {'vlog': None}), [('knee', 2), ('mobility', 1)])
        m = obsidian_run.parse_tag_map('Sure: {"knee": "knee health", "mobility": null}',
                                       [('knee', 2), ('mobility', 1), ('odd', 1)])
        self.assertEqual(m, {'knee': 'knee health', 'mobility': None, 'odd': 'odd'})
        self.assertEqual(obsidian_run.split_title('TITLE: Knee care\n\nBody'), ('Knee care', 'Body'))
        self.assertEqual(obsidian_run.split_title('Plain answer')[0], 'Plain answer')


if __name__ == '__main__':
    unittest.main()
