"""Threads desktop reader checks with synthetic cards and sessions only."""
import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HAS_PLAYWRIGHT = importlib.util.find_spec('playwright') is not None
if HAS_PLAYWRIGHT:
    with mock.patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1] / 'scrapers'), *sys.path]):
        import threads_saved_playwright as threads


@unittest.skipUnless(HAS_PLAYWRIGHT, 'optional Playwright not installed')
class ThreadsTest(unittest.TestCase):
    def page(self, batches):
        page = mock.Mock()
        page.url = threads.SAVED_URL
        page.evaluate.side_effect = [None, *batches]
        return page

    @mock.patch.object(threads, 'session_ready', return_value=True)
    def test_collects_and_deduplicates_keys_and_writes_importable_csv(self, _ready):
        row = {'key': 'th:abcde', 'url': 'https://www.threads.com/@sam/post/abcde',
               'description': 'hello, world', 'creator': 'sam', 'type': 'Post', 'thumb': __import__('tests.test_importers', fromlist=['b64_jpeg']).b64_jpeg()}
        page = self.page([[row.copy()], [row.copy()], []])
        rows = threads.scrape_saved(page, '', True, 1, 0)
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as d:
            path = threads.write_csv(rows, Path(d))
            self.assertTrue(path.name.startswith('threads_saved_'))
            with path.open(encoding='utf-8', newline='') as f:
                self.assertEqual(list(csv.DictReader(f)), [{k: v for k, v in row.items() if k != 'key'}])
            self.assertEqual(list(Path(d).glob('*.tmp')), [])
            from core.db import Database
            from library import importers
            db = Database(Path(d) / 'data' / 'content_manager.db')
            try:
                added, skipped, ids = importers.import_csv(db, path)
                self.assertEqual((added, skipped), (1, 0))
                self.assertEqual(db.get_item(ids[0])['description'], row['description'])
                self.assertTrue((db.item_dir(ids[0]) / 'thumb.jpg').is_file())
            finally:
                db.close()

    @mock.patch.object(threads, 'session_ready', return_value=True)
    def test_empty_page_and_lost_session_do_not_return_success(self, ready):
        with self.assertRaisesRegex(RuntimeError, 'No Threads posts'):
            threads.scrape_saved(self.page([[], []]), '', False, 2, 0)
        ready.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'became unavailable'):
            threads.scrape_saved(self.page([]), '', False, 2, 0)

    @mock.patch.object(threads, 'session_ready', return_value=True)
    def test_stop_text_stops_before_matching_post(self, _ready):
        row = {'key': 'th:abcde', 'url': 'https://www.threads.com/@sam/post/abcde',
               'description': 'Last post', 'creator': 'sam', 'type': 'Post', 'thumb': ''}
        self.assertEqual(threads.scrape_saved(self.page([[row]]), 'last', False, 2, 0), [])

    def test_login_waits_through_checkpoint(self):
        from tests.test_scraper_login import Page
        page = Page('threads', [
            {'auth': True, 'url': 'https://www.threads.com/checkpoint/'},
            {'url': 'https://www.threads.com/'},
        ])
        threads.wait_for_saved_page(page, 0)
        self.assertEqual(page.visits, [threads.SAVED_URL, threads.SAVED_URL])

    def test_extraction_reuses_phone_adapter_on_synthetic_dom(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel='msedge', headless=True)
            except Exception as exc:
                self.skipTest(f'Edge unavailable: {exc}')
            try:
                page = browser.new_page()
                page.route('https://www.threads.com/', lambda route: route.fulfill(
                    path=str(Path(__file__).resolve().parent / 'fixtures/site_cards/threads.html'), content_type='text/html'))
                page.goto('https://www.threads.com/')
                cards = page.evaluate(threads.EXTRACT_JS, {'seen': [], 'thumbs': False})
                self.assertEqual(len(cards), 2)
                self.assertEqual(cards[0]['url'], 'https://www.threads.com/@sam.example/post/DAbc_12xyz')
                self.assertEqual(cards[0]['key'], 'th:DAbc_12xyz')
                remaining = page.evaluate(threads.EXTRACT_JS, {'seen': [cards[0]['key']], 'thumbs': False})
                self.assertEqual(len(remaining), 1)
                self.assertNotEqual(remaining[0]['key'], cards[0]['key'])
                self.assertEqual(cards[0]['description'], 'A made-up thought about bread\nand butter')
                page.evaluate("() => { document.querySelectorAll('img').forEach(i => i.src = 'https://scontent.cdninstagram.com/a.jpg'); window.fetch = async () => new Response(new Blob(['abc'])) }")
                with_pic = page.evaluate(threads.EXTRACT_JS, {'seen': [], 'thumbs': True})
                self.assertEqual(with_pic[0]['thumb'], 'YWJj')
                page.evaluate("() => { document.querySelectorAll('img').forEach(i => i.src = 'https://example.org/picture.jpg'); window.fetchCount = 0; window.fetch = () => { window.fetchCount++; throw new Error('unexpected fetch') } }")
                without_unsafe_pic = page.evaluate(threads.EXTRACT_JS, {'seen': [], 'thumbs': True})
                self.assertEqual(without_unsafe_pic[0]['thumb'], '')
                self.assertEqual(page.evaluate('window.fetchCount'), 0)
            finally:
                browser.close()
