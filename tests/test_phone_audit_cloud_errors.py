"""Keep API setup, quota, and real expiry failures distinct after the 403 follow-up."""
import unittest

from library import drive_client
from server import cloud_errors as errors


class DriveFailureReasons(unittest.TestCase):
    def test_disabled_drive_api_has_a_specific_next_step_before_generic_forbidden(self):
        result = errors.classify(drive_client.DriveError('untrusted server body', 403, 'accessNotConfigured'))
        self.assertEqual((result['code'], result['action']), ('other', 'retry'))
        self.assertIn('Enable Google Drive API', result['message'])
        self.assertNotIn('untrusted server body', result['message'])
        self.assertNotIn('expired', result['message'])

    def test_expiry_quota_and_rate_limits_keep_their_specific_classifications(self):
        cases = [(401, 'authError', 'auth_expired'),
                 (403, 'storageQuotaExceeded', 'drive_full'),
                 (403, 'userRateLimitExceeded', 'rate_limited'),
                 (403, 'domainPolicy', 'other')]
        for status, reason, expected in cases:
            with self.subTest(status=status, reason=reason):
                self.assertEqual(errors.classify(drive_client.DriveError('untrusted', status, reason))['code'], expected)
        self.assertEqual(errors.classify(drive_client.DriveError(drive_client.SIGN_IN_REQUIRED))['code'], 'auth_expired')
