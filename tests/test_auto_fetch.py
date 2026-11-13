"""Scraped previews wait for the shared job slot; all work and storage are stubs."""
import threading
import time
import unittest
from unittest import mock

from server.jobs import Busy, JobKind, JobManager, KINDS


class AutoFetchTest(unittest.TestCase):
    def setUp(self):
        self.rows = {i: {'id': i, 'url': f'https://example.com/{i}'} for i in (1, 2, 3)}
        self.rows[3]['thumb_path'] = 'existing.jpg'
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.fetched = []

        def prepare(db, job):
            return [self.rows[i] for i in job.ids if job.force or not self.rows[i].get('thumb_path')]

        def block(job, item):
            self.entered.set()
            while not self.gate.wait(.01) and not job.stopping:
                pass

        def fetch(job, item):
            self.assertFalse(job.force)
            self.assertTrue(job.auto)
            self.fetched.append(item['id'])

        def kind(key, run):
            return JobKind(key, key, key, False, False, prepare, run,
                           lambda *args: None, gap=0, error_gap=0)

        patch = mock.patch.dict(KINDS, {'scrape': kind('scrape', block),
                                      'index': kind('index', block),
                                      'thumb': kind('thumb', fetch)})
        patch.start()
        self.addCleanup(patch.stop)
        writer = mock.Mock()
        writer.call.side_effect = lambda fn: fn(None)
        self.jobs = JobManager(writer, mock.Mock(), '.')
        self.addCleanup(self.jobs.shutdown)
        self.addCleanup(self.gate.set)

    def wait(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            worker = self.jobs._thread
            if worker is None:
                return
            worker.join(.05)
            if worker is self.jobs._thread and not worker.is_alive():
                return
        self.fail('automatic jobs did not finish')

    def test_idle_fetch_skips_existing_thumbnails(self):
        self.jobs.queue_fetch([1, 3])
        self.wait()
        self.assertEqual(self.fetched, [1])
        self.assertFalse(self.jobs._fetch_ids)

    def test_waits_for_scrape_or_index_and_merges_csv_batches(self):
        for key in ('scrape', 'index'):
            with self.subTest(key=key):
                self.gate.clear()
                self.entered.clear()
                self.fetched.clear()
                self.jobs.start(key, [1])
                self.assertTrue(self.entered.wait(2))
                self.jobs.queue_fetch([1, 3])
                self.jobs.queue_fetch([1, 2])
                self.assertEqual(self.fetched, [])
                self.gate.set()
                self.wait()
                self.assertEqual(self.fetched, [1, 2])
                self.assertFalse(self.jobs._fetch_ids)

    def test_busy_at_start_keeps_pending_ids(self):
        with mock.patch.object(self.jobs, 'start', side_effect=Busy('another job won')):
            self.jobs.queue_fetch([1])
        self.assertEqual(self.jobs._fetch_ids, {1})
        self.jobs.queue_fetch(())
        self.wait()
        self.assertEqual(self.fetched, [1])

    def test_no_missing_thumbnails_does_not_restart(self):
        self.jobs.queue_fetch([3])
        self.assertIsNone(self.jobs.current)
        self.assertFalse(self.jobs._fetch_ids)
        self.jobs.queue_fetch(())
        self.assertEqual(self.fetched, [])

    def test_shutdown_does_not_start_queued_fetch(self):
        self.jobs.start('scrape', [1])
        self.assertTrue(self.entered.wait(2))
        self.jobs.queue_fetch([2])
        self.jobs.shutdown()
        self.assertEqual(self.fetched, [])
        self.assertIsNone(self.jobs.current)


if __name__ == '__main__':
    unittest.main()
