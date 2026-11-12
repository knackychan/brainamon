"""Facebook removal ordering with disposable CSVs and synthetic browser cards only."""
import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from library import scrape_watch

HAS_PLAYWRIGHT = importlib.util.find_spec('playwright') is not None
if HAS_PLAYWRIGHT:
    with mock.patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1] / 'scrapers'), *sys.path]):
        import fb_saved_playwright as fb
        import ig_saved_playwright as ig
        import reddit_saved_playwright as reddit


@unittest.skipUnless(HAS_PLAYWRIGHT, 'optional Playwright not installed')
class FacebookAutomaticUnsaveTest(unittest.TestCase):
    def page(self, batches, on_unsave):
        page = mock.Mock()
        pending = iter(batches)

        def evaluate(script, arg=None):
            if script == fb.EXTRACT_VISIBLE_JS:
                return next(pending)
            if script == fb.UNSAVE_VISIBLE_JS:
                return on_unsave(arg)
        page.evaluate.side_effect = evaluate
        return page

    def test_every_visible_batch_is_persisted_before_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            removed = []

            def unsave(ids):
                path = next(directory.glob('fb_saved_*.csv'))
                with path.open(encoding='utf-8', newline='') as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual([row['id'] for row in rows], removed + ids)
                removed.extend(ids)
                return {item_id: True for item_id in ids}

            page = self.page([[{'id': '1', 'url': 'https://facebook.com/reel/1'}],
                              [{'id': '2', 'url': 'https://facebook.com/reel/2'}], []], unsave)
            rows = fb.scrape_saved_items(page, '', False, True, 1, 0, directory)
            self.assertEqual(removed, ['1', '2'])
            self.assertTrue(all(row['unsaved'] for row in rows))
            self.assertFalse(list(directory.glob('*.tmp')))

    def test_failed_export_or_missing_destination_never_removes_posts(self):
        removed = mock.Mock()
        with tempfile.TemporaryDirectory() as folder:
            page = self.page([[{'id': '1'}]], removed)
            with mock.patch.object(fb, 'write_csv', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    fb.scrape_saved_items(page, '', False, True, 1, 0, Path(folder))
            removed.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'CSV output directory'):
                fb.scrape_saved_items(page, '', False, True, 1, 0)
            removed.assert_not_called()

    def test_failed_checkpoint_replacement_preserves_last_complete_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = fb.write_csv([{'id': '1'}], directory)
            previous = path.read_bytes()
            with mock.patch.object(fb.os, 'replace', side_effect=OSError('write refused')):
                with self.assertRaisesRegex(OSError, 'write refused'):
                    fb.write_csv([{'id': '1'}, {'id': '2'}], directory)
            self.assertEqual(path.read_bytes(), previous)
            self.assertFalse(list(directory.glob('*.tmp')))

    def test_interruption_keeps_checkpoint_outside_the_watched_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            checkpoint = directory / 'pending' / 'facebook-test'
            removed = []
            page = self.page([[{'id': '1'}]], lambda ids: (removed.extend(ids), {})[1])
            with self.assertRaises(StopIteration):
                fb.scrape_saved_items(page, '', False, True, 1, 0, checkpoint)
            self.assertEqual(removed, ['1'])
            self.assertEqual(list(directory.glob('*.csv')), [])
            self.assertEqual(len(list(checkpoint.glob('fb_saved_*.csv'))), 1)

    def test_main_publishes_after_collection_and_preserves_checkpoint_on_publish_failure(self):
        for failed_publish in (False, True):
            with self.subTest(failed_publish=failed_publish), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder) / 'exports'
                removed = []

                def unsave(ids):
                    self.assertEqual(list(directory.glob('*.csv')), [])
                    self.assertEqual(len(list(directory.glob('pending/*/fb_saved_*.csv'))), 1)
                    removed.extend(ids)
                    return {}

                page = self.page([[{'id': '1'}], []], unsave)
                pw, context = mock.Mock(), mock.Mock()
                context.pages = [page]
                pw.chromium.launch_persistent_context.return_value = context
                write = fb.write_csv

                def export(rows, destination, filename=None):
                    if failed_publish and destination == directory:
                        raise OSError('final publish failed')
                    return write(rows, destination, filename)

                with mock.patch.object(sys, 'argv', ['facebook', '--output-dir', str(directory),
                                                     '--profile-dir', str(Path(folder) / 'profile'),
                                                     '--unsave', '--max-empty-scrolls', '1']), \
                        mock.patch.object(fb, 'sync_playwright') as playwright, \
                        mock.patch.object(fb, 'wait_for_saved_page'), \
                        mock.patch.object(fb, 'write_csv', side_effect=export):
                    playwright.return_value.__enter__.return_value = pw
                    if failed_publish:
                        with self.assertRaisesRegex(OSError, 'final publish failed'):
                            fb.main()
                    else:
                        self.assertEqual(fb.main(), 0)
                self.assertEqual(removed, ['1'])
                self.assertEqual(len(list(directory.glob('*.csv'))), 0 if failed_publish else 1)
                self.assertEqual(len(list(directory.glob('pending/*/fb_saved_*.csv'))), 1 if failed_publish else 0)
                context.close.assert_called_once()

    def test_same_day_facebook_runs_preserve_previous_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'exports'
            pw, context = mock.Mock(), mock.Mock()
            pw.chromium.launch_persistent_context.return_value = context
            with mock.patch.object(sys, 'argv', ['facebook', '--output-dir', str(directory),
                                                 '--profile-dir', str(Path(folder) / 'profile'),
                                                 '--max-empty-scrolls', '1']), \
                    mock.patch.object(fb, 'sync_playwright') as playwright, \
                    mock.patch.object(fb, 'wait_for_saved_page'):
                playwright.return_value.__enter__.return_value = pw
                for item_id in ('1', '2'):
                    context.pages = [self.page([[{'id': item_id}], []], mock.Mock())]
                    self.assertEqual(fb.main(), 0)
            exports = list(directory.glob('fb_saved_*.csv'))
            self.assertEqual(len(exports), 2)
            found = []
            for path in exports:
                with path.open(encoding='utf-8', newline='') as handle:
                    found.append(next(csv.DictReader(handle))['id'])
            self.assertEqual(sorted(found), ['1', '2'])

    def test_instagram_and_reddit_keep_same_day_exports(self):
        for module in (ig, reddit):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                first = module.write_csv([{'url': 'https://example.org/first'}], directory)
                previous = first.read_bytes()
                second = module.write_csv([{'url': 'https://example.org/second'}], directory)
                self.assertNotEqual(first, second)
                self.assertEqual(first.read_bytes(), previous)
                self.assertEqual(len(list(directory.glob('*.csv'))), 2)


@unittest.skipUnless(HAS_PLAYWRIGHT, 'optional Playwright not installed')
class FacebookManualUnsaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(channel='msedge', headless=True)
        except Exception as exc:
            cls.pw.stop()
            raise unittest.SkipTest(f'Edge unavailable: {exc}')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def run_script(self, accept, failed_download=False):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content('''<article><a href="https://www.facebook.com/reel/123456">Synthetic saved post</a>
          <div>Add to collection</div><button role="button" aria-label="More options">More</button></article>
          <button role="menuitem">Unsave</button>''')
        page.evaluate('''({accept, failed}) => {
          window.events = []; window.csvText = '';
          const timer = window.setTimeout;
          window.setTimeout = (fn, ms) => timer(fn, Math.min(ms, 10));
          URL.createObjectURL = blob => { blob.text().then(text => window.csvText = text); return 'blob:fixture'; };
          HTMLAnchorElement.prototype.click = function () {
            window.events.push('download');
            if (failed) throw new Error('download blocked');
          };
          window.confirm = message => {
            window.events.push('confirm');
            if (!window.csvText.includes('123456')) throw new Error('CSV missing collected post');
            return accept;
          };
          window.alert = message => window.events.push('alert:' + message);
          document.querySelector('[role=menuitem]').addEventListener('click', () => {
            window.events.push('unsave'); document.querySelector('article').remove();
          });
        }''', {'accept': accept, 'failed': failed_download})
        script = scrape_watch.script_for('facebook', unsave=True)
        self.assertTrue(script.rstrip().endswith('run();'))
        script = script.rstrip()[:-len('run();')] + 'window.runFacebook = run; void 0;'
        page.evaluate(script)
        page.evaluate('window.runFacebook()')
        return page.evaluate('window.events')

    def test_download_then_explicit_confirmation_then_removal(self):
        events = self.run_script(True)
        self.assertEqual(events[:3], ['download', 'confirm', 'unsave'])
        self.assertIn('1 unsaved', events[-1])

    def test_cancelled_confirmation_keeps_saved_posts(self):
        events = self.run_script(False)
        self.assertEqual(events[:2], ['download', 'confirm'])
        self.assertNotIn('unsave', events)
        self.assertIn('0 unsaved', events[-1])

    def test_download_failure_never_confirms_or_removes_posts(self):
        events = self.run_script(True, failed_download=True)
        self.assertEqual(events[0], 'download')
        self.assertNotIn('confirm', events)
        self.assertNotIn('unsave', events)
        self.assertIn('CSV download failed', events[-1])


if __name__ == '__main__':
    unittest.main()
