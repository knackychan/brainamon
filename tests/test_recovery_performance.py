"""Bounded recovery parallelism, using synthetic files only."""
import hashlib
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from library import mirror, restore, drive_client
from library.recovery import RecoveryError


class DownloadBatchTest(unittest.TestCase):
    def test_interactive_requests_have_bounded_timeouts_and_retries(self):
        client = drive_client.DriveClient('synthetic', 'synthetic', {'access_token': 'synthetic', 'expires_at': 9999999999})
        client.request_timeout, client.attempts = 20, 3
        with mock.patch.object(drive_client, '_request', side_effect=OSError('offline')) as request, mock.patch.object(client.stop, 'wait'):
            with self.assertRaisesRegex(drive_client.DriveError, 'out of reach'):
                client.about()
        self.assertEqual(request.call_count, 3)
        self.assertTrue(all(call.args[4] == 20 for call in request.call_args_list))

    def test_network_buffer_is_bounded_by_the_listed_size(self):
        client = mock.Mock()
        client.download_bounded.return_value = b'12345678'
        self.assertEqual(restore.download(client, {'id': 'small', 'size': 8}, mirror.MAX_FILE), b'12345678')
        client.download_bounded.assert_called_once_with('small', 8)

    def test_four_small_downloads_overlap_and_large_files_travel_alone(self):
        names = [*(f'small-{n}' for n in range(8)), 'large', *(f'small-{n}' for n in range(8, 12))]
        files = {name: {'id': name} for name in names}
        remote = {name: {'id': name, 'size': 1024 * 1024 + 1 if name == 'large' else 8} for name in names}
        barrier, lock = threading.Barrier(4), threading.Lock()
        active, peak = 0, 0

        def download(client, entry, limit):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if entry['id'] == 'large':
                    self.assertEqual(active, 1)
            try:
                if entry['id'] != 'large':
                    barrier.wait(timeout=5)
                return b'synthetic'
            finally:
                with lock:
                    active -= 1

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(restore, 'download', side_effect=download):
            with closing(restore._blobs(None, files, remote, Path(folder), lambda: None)) as blobs:
                self.assertEqual([value[0] for value in blobs], names)
        self.assertEqual(peak, 4)
        self.assertEqual(active, 0)

    def test_cancel_stops_before_the_next_batch_and_cache_is_reused(self):
        files = {str(n): {'id': str(n)} for n in range(12)}
        remote = {name: {'id': name, 'size': 8} for name in files}
        cancelled = threading.Event()

        def check():
            if cancelled.is_set():
                raise RecoveryError('cancelled')

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(restore, 'download', return_value=b'new') as download:
            cache = Path(folder)
            (cache / hashlib.sha256(b'0').hexdigest()).write_bytes(b'cached')
            with closing(restore._blobs(None, files, remote, cache, check)) as blobs:
                self.assertEqual(next(blobs)[3], b'cached')
                cancelled.set()
                with self.assertRaisesRegex(RecoveryError, 'cancelled'):
                    next(blobs)
            self.assertLessEqual(download.call_count, 3)
            self.assertTrue(all(call.args[1]['id'] in ('1', '2', '3') for call in download.call_args_list))

    def test_download_failure_and_oversized_cache_propagate(self):
        files, remote = {'item': {'id': 'id'}}, {'id': {'id': 'id', 'size': 8}}
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with mock.patch.object(restore, 'download', side_effect=RecoveryError('changed')):
                with closing(restore._blobs(None, files, remote, cache, lambda: None)) as blobs:
                    with self.assertRaisesRegex(RecoveryError, 'changed'):
                        next(blobs)
            (cache / hashlib.sha256(b'item').hexdigest()).write_bytes(b'oversized')
            with mock.patch.object(mirror, 'MAX_FILE', 4):
                with closing(restore._blobs(None, files, remote, cache, lambda: None)) as blobs:
                    with self.assertRaisesRegex(RecoveryError, 'size limit'):
                        next(blobs)
