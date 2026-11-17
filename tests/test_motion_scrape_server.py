"""D3 numeric scan events and the watcher's import handoff; no browser, credentials or site requests."""
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from server import job_kinds
from server.routes import io


class ScanEventsTest(unittest.TestCase):
    def process(self, job, lines=(), rc=0, wait=None):
        proc = mock.Mock(stdout=iter(lines))
        proc.wait.return_value = rc
        if wait:
            proc.wait.side_effect = wait
        say = mock.Mock()
        with mock.patch('subprocess.Popen', return_value=proc) as popen, \
                mock.patch.object(job_kinds.ytdlp, 'monitor', return_value=nullcontext()):
            result = job_kinds._scrape_process(job, ['python', '--session-state', 'synthetic.json'],
                                              {}, say, 'Instagram')
        return result, say, popen

    def test_only_growing_bounded_counts_are_published_without_page_text(self):
        job = SimpleNamespace(stopping=False, emit=mock.Mock())
        _, say, _ = self.process(job, [
            '[item 0] synthetic-secret\n', '[item 1] synthetic-secret\n',
            '[item 1] duplicate\n', '[item 0] backwards\n', '[item 20] title synthetic-secret\n',
            '[item -2] synthetic-secret\n', '[item 21.5] synthetic-secret\n',
            '[item 10000000] synthetic-secret\n', '[item ٢٢] synthetic-secret\n',
            'prefix [item 22] synthetic-secret\n', '[item 9999999] synthetic-secret\n',
        ])
        self.assertEqual(job.emit.call_args_list, [mock.call('scrape', {'read': n}) for n in (1, 20, 9999999)])
        self.assertNotIn('synthetic-secret', repr(job.emit.call_args_list) + repr(say.call_args_list))

    def test_old_jobs_without_emit_still_work(self):
        result, say, _ = self.process(SimpleNamespace(stopping=False), ['[item 3] private title\n'])
        self.assertEqual(result, 0)
        say.assert_called_once_with('Playwright Instagram scraper finished. The watcher imports its CSV.', 'g')

    def test_preexisting_stop_does_not_start_a_process_or_emit(self):
        job = SimpleNamespace(stopping=True, emit=mock.Mock())
        with mock.patch('subprocess.Popen') as popen, self.assertRaisesRegex(job_kinds.Stopped, 'Stopped'):
            job_kinds._scrape_process(job, [], {}, mock.Mock(), 'Instagram')
        popen.assert_not_called()
        job.emit.assert_not_called()

    def test_process_error_and_mid_scan_stop_keep_existing_failures(self):
        for stopped, rc, text in ((False, 7, 'exited with code 7'), (True, 0, 'Stopped')):
            with self.subTest(stopped=stopped):
                job = SimpleNamespace(stopping=False, emit=mock.Mock())
                def finish():
                    job.stopping = stopped
                    return rc
                with self.assertRaisesRegex(RuntimeError, text):
                    self.process(job, ['[item 4] synthetic-secret\n'], wait=finish)
                job.emit.assert_called_once_with('scrape', {'read': 4})


class ImportEventsTest(unittest.TestCase):
    def imported(self, result=None, failure=None, backup_failure=None, fetch_failure=None):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            events = mock.Mock()
            state = SimpleNamespace(data_dir=folder / 'data', scrape_watcher=None,
                                    hub=SimpleNamespace(publish=events.publish),
                                    jobs=SimpleNamespace(queue_fetch=events.queue_fetch), notify=events.notify)
            app = SimpleNamespace(state=state)
            watcher = mock.Mock(running=True, folder=folder)
            def run_import(*args):
                events.run_import(*args)
                if failure:
                    raise failure
                return result
            events.queue_fetch.side_effect = fetch_failure
            with mock.patch.object(io, '_watch_dir', return_value=folder), \
                    mock.patch.object(io.scrape_watch, 'Watcher', return_value=watcher) as make, \
                    mock.patch.object(io.scrape_watch, 'backup', side_effect=backup_failure), \
                    mock.patch.object(io, 'run_import', side_effect=run_import), \
                    mock.patch.object(io.app_console, 'emit'):
                io.scraper_watch(SimpleNamespace(app=app), {'on': True})
                watcher.start.assert_called_once_with()
                make.call_args.args[1](folder / 'fb_saved_test.csv')
            return events

    def test_import_result_precedes_fetch_and_contains_only_the_four_fields(self):
        for added, ids in ((2, [11, 12]), (0, [])):
            with self.subTest(added=added):
                result = {'added': added, 'duplicates': 3, 'invalid': 1, 'ids': ids,
                          'skipped': 4, 'file': 'synthetic-secret', 'raw': 'synthetic-secret'}
                events = self.imported(result)
                payload = {k: result[k] for k in ('added', 'duplicates', 'invalid', 'ids')}
                imported = mock.call.publish('scrape', {'imported': payload})
                self.assertIn(imported, events.mock_calls)
                names = [call[0] for call in events.mock_calls]
                at = events.mock_calls.index(imported)
                self.assertLess(names.index('run_import'), at)
                self.assertLess(at, names.index('queue_fetch'))
                events.queue_fetch.assert_called_once_with(ids)
                structured = [call.args[1] for call in events.publish.call_args_list if 'imported' in call.args[1]]
                self.assertEqual(structured, [{'imported': payload}])
                self.assertNotIn('synthetic-secret', repr(structured))
                self.assertEqual(events.notify.call_count, int(added > 0))

    def test_failed_import_never_claims_a_result_or_queues_rows(self):
        events = self.imported(failure=ValueError('synthetic failure'))
        self.assertFalse(any('imported' in call.args[1] for call in events.publish.call_args_list))
        events.queue_fetch.assert_not_called()
        events.notify.assert_not_called()
        self.assertTrue(any(call.args[1].get('c') == 'r' for call in events.publish.call_args_list))

    def test_backup_or_fetch_failure_keeps_a_successful_import_result(self):
        result = {'added': 1, 'duplicates': 0, 'invalid': 0, 'ids': [11], 'skipped': 0}
        for options in ({'backup_failure': OSError('backup unavailable')},
                        {'fetch_failure': RuntimeError('fetch unavailable')}):
            with self.subTest(options=options):
                events = self.imported(result, **options)
                events.publish.assert_any_call('scrape', {'imported': {
                    'added': 1, 'duplicates': 0, 'invalid': 0, 'ids': [11]}})
                events.queue_fetch.assert_called_once_with([11])


if __name__ == '__main__':
    unittest.main()
