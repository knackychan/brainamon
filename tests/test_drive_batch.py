"""Batch deletion keeps confirmed identities, partial success, retries and stop boundaries."""
import threading
import unittest
from unittest import mock

from library import drive_client
from library.export_targets import DriveMirrorTarget
from library import mirror
from tests.test_sync import Library, FakeDrive


def response(statuses):
    parts = ''.join(f'--reply\r\nContent-Type: application/http\r\nContent-ID: <response-delete-{i}>\r\n\r\nHTTP/1.1 {status} Result\r\n\r\n'
                    for i, status in reversed(list(enumerate(statuses))))
    return 200, {'Content-Type': 'multipart/mixed; boundary=reply'}, (parts + '--reply--\r\n').encode()


class DriveBatchTest(unittest.TestCase):
    def setUp(self):
        self.client = drive_client.DriveClient('synthetic', 'synthetic', {'refresh_token': 'synthetic'})

    def test_250_deletions_use_three_requests_and_report_confirmed_successes(self):
        progress = []
        with mock.patch.object(self.client, '_call', side_effect=lambda *args, **kw: response([204] * args[2].count(b'DELETE /drive/v3/files/'))) as call:
            self.client.delete_many([f'file-{n}' for n in range(250)], lambda done, total: progress.append((done, total)))
        self.assertEqual(call.call_count, 3)
        self.assertEqual(progress, [(n, 250) for n in range(1, 251)])
        self.assertEqual(sorted(request.args[2].count(b'DELETE /drive/v3/files/') for request in call.call_args_list), [50, 100, 100])
        for request in call.call_args_list:
            self.assertEqual(request.args[:2], ('POST', 'https://www.googleapis.com/batch/drive/v3'))

    def test_only_failed_parts_are_retried_and_missing_files_count_as_done(self):
        progress = []
        with mock.patch.object(self.client, '_call', return_value=response([204, 429, 404])), mock.patch.object(self.client, 'delete') as delete:
            self.client.delete_many(['old1', 'old2', 'old3'], lambda d, t: progress.append((d, t)))
        delete.assert_called_once_with('old2')
        self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])

    def test_a_failed_retry_keeps_successful_progress_and_stops(self):
        progress = []
        with mock.patch.object(self.client, '_call', return_value=response([204, 403])), mock.patch.object(self.client, 'delete', side_effect=drive_client.DriveError('refused', 403)):
            with self.assertRaises(drive_client.DriveError):
                self.client.delete_many(['old1', 'old2'], lambda d, t: progress.append((d, t)))
        self.assertEqual(progress, [(1, 2)])

    def test_invalid_or_incomplete_responses_never_report_completion(self):
        for reply in [response([204]), (200, {'Content-Type': 'text/plain'}, b'not multipart')]:
            with self.subTest(reply=reply), mock.patch.object(self.client, '_call', return_value=reply), mock.patch.object(self.client, 'delete') as delete:
                progress = mock.Mock()
                with self.assertRaises(drive_client.DriveError):
                    self.client.delete_many(['old1', 'old2'], progress)
                progress.assert_not_called()
                delete.assert_not_called()

    def test_four_batches_overlap_and_progress_runs_on_the_caller_thread(self):
        barrier = threading.Barrier(4, timeout=5)
        caller = threading.get_ident()
        progress = []
        def call(*args, **kwargs):
            barrier.wait()
            return response([204] * args[2].count(b'DELETE /drive/v3/files/'))
        def progressed(done, total):
            self.assertEqual(threading.get_ident(), caller)
            progress.append((done, total))
        with mock.patch.object(self.client, '_call', side_effect=call) as request:
            self.client.delete_many([f'old{n}' for n in range(800)], progressed)
        self.assertEqual(request.call_count, 8)
        self.assertEqual(progress, [(n, 800) for n in range(1, 801)])

    def test_stop_prevents_the_next_window_and_drains_in_flight_work(self):
        barrier = threading.Barrier(4, timeout=5)
        def call(*args, **kwargs):
            barrier.wait()
            return response([204] * 100)
        def progressed(done, total):
            if done == 100:
                self.client.stop.set()
        with mock.patch.object(self.client, '_call', side_effect=call) as request:
            with self.assertRaises(drive_client.SignInCancelled):
                self.client.delete_many([f'old{n}' for n in range(501)], progressed)
        self.assertEqual(request.call_count, 4)

    def test_failed_window_never_starts_more_batches(self):
        barrier = threading.Barrier(4, timeout=5)
        def call(*args, **kwargs):
            barrier.wait()
            if b'/old0 HTTP' in args[2]:
                raise drive_client.DriveError('synthetic failure')
            return response([204] * 100)
        with mock.patch.object(self.client, '_call', side_effect=call) as request:
            with self.assertRaisesRegex(drive_client.DriveError, 'synthetic failure'):
                self.client.delete_many([f'old{n}' for n in range(501)])
        self.assertEqual(request.call_count, 4)

    def test_invalid_ids_are_rejected_before_sending_any_request(self):
        with mock.patch.object(self.client, '_call') as call:
            with self.assertRaises(drive_client.DriveError):
                self.client.delete_many(['old\r\nDELETE /another-file'])
        call.assert_not_called()


class ItemProgressTest(Library):
    def test_item_counts_advance_and_a_resumed_pass_counts_saved_records(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        target = DriveMirrorTarget(drive, key, {}, self.data, mirror.Options())
        counts = []
        result = target.export(self.payload(), progress=lambda d, t: counts.append((target.items_done, target.items_total)))
        self.assertFalse(result.errors)
        self.assertEqual(counts[0], (0, len(self.ids)))
        self.assertEqual(counts[-1], (len(self.ids), len(self.ids)))
        self.assertEqual(counts, sorted(counts))
        resumed = DriveMirrorTarget(drive, key, target.state, self.data, mirror.Options())
        resumed.export(self.payload())
        self.assertEqual((resumed.items_done, resumed.items_total), (len(self.ids), len(self.ids)))

    def test_failed_item_is_never_counted_as_uploaded(self):
        drive, key = FakeDrive(), mirror.MirrorKey.generate()
        target = DriveMirrorTarget(drive, key, {}, self.data, mirror.Options())
        failed = key.name(f"items/{self.payload()['items'][0]['uid']}.json")
        upload = drive.upload
        def send(name, *args, **kwargs):
            if name == failed:
                raise OSError('synthetic failed item')
            return upload(name, *args, **kwargs)
        with mock.patch.object(drive, 'upload', side_effect=send):
            progress = []
            result = target.export(self.payload(), progress=lambda d, t: progress.append((d, t)))
        self.assertTrue(result.errors)
        self.assertEqual(target.items_done, target.items_total - 1)
        self.assertLess(progress[-1][0], progress[-1][1])
