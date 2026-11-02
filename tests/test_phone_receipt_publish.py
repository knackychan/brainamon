"""F1-1: a held stream's want reaches the manifest after failure or restart, without a busy retry loop."""
import threading
import unittest
from unittest import mock

from library import drive_client, mirror
from server import sync as sync_mod
from tests.test_phone_delivery_prerequisite import Fixture, STREAM
from tests.test_sync import read_mirror


class ReceiptPublish(Fixture):
    def setUp(self):
        super().setUp()
        self.put('A', 100, 1)
        self.assertTrue(self.svc._intake())
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertEqual(self.manifest_receipt(), {'device': 'probe-phone', 'seq': 1})

    def manifest_receipt(self):
        manifest, _ = read_mirror(self.drive, self.key)
        return {k: v for k, v in manifest['receipts'][STREAM].items() if k in ('device', 'seq', 'want')}

    def hold(self):
        self.put('C', 300, 3, acked=1)
        self.assertTrue(self.svc._intake())
        self.assertEqual(self.receipt(), {'seq': 1, 'want': 2})
        self.assertFalse(self.svc._intake())

    def failed_then_retry(self, error):
        self.hold()
        self.svc._force_manifest = True
        original = self.drive.upload

        def fail_manifest(name, *args, **kwargs):
            if name == self.key.name(mirror.MANIFEST):
                raise error
            return original(name, *args, **kwargs)
        with mock.patch.object(self.drive, 'upload', side_effect=fail_manifest):
            self.assertFalse(self.svc._publish())
        self.assertNotIn('want', self.manifest_receipt())
        # There is no new library file or new intake result to force this second publish.
        self.assertFalse(self.svc._intake())
        self.assertTrue(self.svc._publish(), self.svc.status())
        self.assertEqual(self.manifest_receipt().get('want'), 2)
        self.drive.calls.clear()
        self.assertTrue(self.svc._publish())
        self.assertNotIn('upload ' + self.key.name(mirror.MANIFEST), self.drive.calls)
        self.assertEqual(self.counts('A', 'C'), (1, 0))

    def test_retry_after_drive_error_carries_want_once(self):
        self.failed_then_retry(drive_client.DriveError('synthetic manifest outage', 503))

    def test_retry_after_other_exception_carries_want_once(self):
        self.failed_then_retry(RuntimeError('synthetic manifest interruption'))

    def test_restart_after_intake_before_publish_carries_the_saved_want(self):
        self.hold()
        restarted = sync_mod.SyncService(self.fx.writer, self.svc.hub, self.fx.data, self.fx.cloud,
                                         client_factory=lambda tok: self.drive)
        try:
            with mock.patch.object(restarted.recovery, 'guard'):
                self.assertTrue(restarted._publish(), restarted.status())
            self.assertEqual(self.manifest_receipt().get('want'), 2)
        finally:
            restarted.shutdown()

    def test_idle_signature_changes_when_only_receipts_change(self):
        before = self.fx.writer.read(sync_mod._signature)
        self.hold()
        self.assertNotEqual(self.fx.writer.read(sync_mod._signature), before)

    def test_idle_loop_retries_after_the_existing_delay_without_another_library_edit(self):
        stop, clock, attempts = threading.Event(), [0.0], []
        service, original = self.svc, self.drive.upload
        case = self

        def upload(name, *args, **kwargs):
            if name == self.key.name(mirror.MANIFEST):
                attempts.append(clock[0])
                if len(attempts) == 1:
                    raise drive_client.DriveError('synthetic manifest outage', 503)
            return original(name, *args, **kwargs)

        class Wake:
            def wait(self, timeout):
                if clock[0] == 0:
                    case.put('C', 300, 3, acked=1)
                    service._look_now = True
                if case.manifest_receipt().get('want') == 2 or clock[0] >= 20:
                    stop.set()
                clock[0] += 1

            def clear(self):
                pass

            def set(self):
                pass

        with mock.patch.object(self.drive, 'upload', side_effect=upload), \
             mock.patch.object(service, '_wake', Wake()), \
             mock.patch.object(sync_mod.time, 'monotonic', side_effect=lambda: clock[0]), \
             mock.patch.object(sync_mod, 'DEBOUNCE', 0), mock.patch.object(sync_mod, 'RETRY', 5):
            service._loop(stop)
        self.assertEqual(attempts, [1.0, 6.0], 'retry once after RETRY, not every poll or never')
        self.assertEqual(self.manifest_receipt().get('want'), 2)
        self.assertEqual(self.counts('A', 'C'), (1, 0))


if __name__ == '__main__':
    unittest.main()
