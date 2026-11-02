"""Transient Drive download failures must not hide a phone until its next record update."""
from unittest import mock

from library import drive_client, mirror
from tests.test_phone_delivery_prerequisite import Fixture


class PhoneRecordRetry(Fixture):
    def test_record_download_failure_retries_an_unchanged_record(self):
        record = self.drive.put(*mirror.seal_phone(self.key, 'probe-phone', 'Phone browser', 123456))
        listing = self.drive.list()
        original = self.drive.download

        def offline(file_id):
            if file_id == record:
                raise drive_client.DriveError('synthetic outage', 503)
            return original(file_id)

        with mock.patch.object(self.drive, 'download', offline):
            self.svc._read_phones(self.drive, self.key, listing)
        self.svc._read_phones(self.drive, self.key, listing)
        self.assertEqual(self.svc.status()['phones'], [
            {'device': 'probe-phone', 'name': 'Phone browser', 'seen': 123456}])
