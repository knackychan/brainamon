"""The Drive error classifier (I7, audit F8): one code, one sentence from a fixed table and one next action per failure.
Synthetic exceptions only; nothing here touches Drive."""
import json
import socket
import unittest
import urllib.error
from unittest import mock

from library import drive_client, mirror, recovery as R
from server import cloud_errors as E
from server.cloud_errors import classify


def shape(exc, **kw):
    c = classify(exc, **kw)
    return c['code'], c['action']


class ClassifyTest(unittest.TestCase):
    def test_a_401_is_an_expired_sign_in_and_never_says_change_account(self):
        for exc in (drive_client.DriveError('Google Drive answered 401: Invalid Credentials', 401),
                    drive_client.DriveError(drive_client.SIGN_IN_REQUIRED, 401)):
            c = classify(exc, account='a@gmail.com')
            self.assertEqual((c['code'], c['action']), ('auth_expired', 'sign_in_again'))
            self.assertEqual(c['message'], 'Google Drive sign-in for a@gmail.com expired or was removed. Choose Sign in again and pick '
                                           'the same account. Your backup and settings stay as they are.')
            self.assertNotIn('Change account', c['message'])
        self.assertEqual(classify(drive_client.DriveError('x', 401))['message'],
                         'Google Drive sign-in expired or was removed. Choose Sign in again and pick the same account. '
                         'Your backup and settings stay as they are.')

    def test_a_403_permission_or_configuration_refusal_is_not_an_expired_sign_in(self):
        for reason in ('', 'appNotAuthorizedToFile', 'insufficientFilePermissions', 'domainPolicy', 'accessNotConfigured'):
            with self.subTest(reason=reason):
                result = classify(drive_client.DriveError('untrusted response', 403, reason))
                self.assertEqual((result['code'], result['action']), ('other', 'retry'))
                self.assertIn('permissions', result['message'])
                self.assertNotIn('untrusted response', result['message'])
                self.assertNotIn('Sign in again', result['message'])

    def test_the_quota_reason_is_a_full_drive_with_its_numbers(self):
        exc = drive_client.DriveError('Google Drive answered 403: The user\'s Drive storage quota has been exceeded.', 403, 'storageQuotaExceeded')
        c = classify(exc, used=int(14.5 * 2 ** 30), limit=15 * 2 ** 30)
        self.assertEqual((c['code'], c['action']), ('drive_full', 'free_space'))
        self.assertEqual(c['message'], 'Google Drive is full (14.5 of 15.0 GB). Free space in Google Drive, then choose Try again.')
        self.assertEqual(classify(exc)['message'], 'Google Drive is full. Free space in Google Drive, then choose Try again.')

    def test_rate_limit_reasons_and_429_wait_instead_of_asking_for_a_sign_in(self):
        for reason in ('userRateLimitExceeded', 'rateLimitExceeded', 'sharingRateLimitExceeded', 'dailyLimitExceeded', 'someNewRateLimit'):
            self.assertEqual(shape(drive_client.DriveError('x', 403, reason)), ('rate_limited', 'wait'), reason)
        self.assertEqual(shape(drive_client.DriveError('x', 429)), ('rate_limited', 'wait'))

    def test_no_connection_is_offline_and_changes_nothing(self):
        try:
            raise urllib.error.URLError('no route')
        except OSError as e:
            try:
                raise drive_client.DriveError(f'Google Drive is out of reach: {e}') from e
            except drive_client.DriveError as wrapped:
                out = wrapped
        c = classify(out)
        self.assertEqual((c['code'], c['action']), ('offline', 'none'))
        self.assertEqual(c['message'], "Can't reach Google Drive. Nothing changed. Brainamon retries when the connection is back.")
        for exc in (urllib.error.URLError('x'), ConnectionResetError(), TimeoutError(), socket.gaierror()):
            self.assertEqual(shape(exc), ('offline', 'none'), type(exc).__name__)

    def test_typed_failures_keep_their_own_sentence(self):
        stopping = E.WorkerStopping('Finishing one upload request first (up to a minute).')
        self.assertEqual(classify(stopping), {'code': 'worker_stopping', 'message': str(stopping), 'action': 'wait'})
        self.assertEqual(shape(E.Busy()), ('busy', 'wait'))
        self.assertEqual(classify(E.Busy())['message'], E.BUSY)
        self.assertEqual(shape(E.NotUploader('Another PC is now the uploader.')), ('not_owner', 'recover'))
        wrong = E.WrongAccount('b@gmail.com', 'a@gmail.com')
        self.assertEqual(classify(wrong), {'code': 'wrong_account', 'action': 'sign_in_again',
                                           'message': 'You signed in as b@gmail.com, but this library backs up to a@gmail.com. Nothing changed.'})

    def test_a_typed_failure_wins_over_its_status(self):
        # Busy and WorkerStopping are DriveErrors: a status must never turn them into a sign-in request
        busy = E.Busy('Another operation runs.')
        busy.status = 401
        self.assertEqual(classify(busy)['code'], 'busy')

    def test_local_files_are_local_storage_without_a_path_in_the_message(self):
        for exc in (PermissionError(13, 'denied', r'C:\Users\someone\secret\google_token.json'), mirror.MirrorKeyError('x'), RuntimeError('x')):
            c = classify(exc)
            self.assertEqual((c['code'], c['action']), ('local_storage', 'none'))
            self.assertNotIn('someone', c['message'])
        self.assertEqual(classify(OSError('x'), storage='Keep the current files.')['message'], 'Keep the current files.')

    def test_everything_else_is_other_with_the_callers_sentence(self):
        self.assertEqual(classify(drive_client.DriveError('Google Drive answered 500: boom', 500)),
                         {'code': 'other', 'message': 'Google Drive answered 500: boom', 'action': 'retry'})
        self.assertEqual(classify(drive_client.DriveError('raw', 500), fallback='Could not write the new key.')['message'], 'Could not write the new key.')
        recovery = classify(R.RecoveryError('The recovery passphrases do not match.'))
        self.assertEqual(recovery, {'code': 'other', 'message': 'The recovery passphrases do not match.', 'action': 'none'})
        self.assertEqual(classify(KeyError('k'), fallback='Upload failed.')['message'], 'Upload failed.')

    def test_a_table_message_never_carries_what_google_or_the_exception_said(self):
        secret = 'ya29.synthetic-access-token'
        for exc in (drive_client.DriveError(f'Google Drive answered 403: {secret}', 403, 'storageQuotaExceeded'),
                    drive_client.DriveError(f'Google Drive answered 403: {secret}', 403, 'rateLimitExceeded'),
                    drive_client.DriveError(f'Google Drive answered 401: {secret}', 401),
                    drive_client.DriveError(f'Google Drive answered 403: {secret}', 403, 'appNotAuthorizedToFile')):
            self.assertNotIn(secret, json.dumps(classify(exc, account='a@gmail.com', used=1, limit=2)))

    def test_the_audit_codes_and_actions_are_the_whole_vocabulary(self):
        self.assertEqual({E.AUTH_EXPIRED, E.WRONG_ACCOUNT, E.OFFLINE, E.DRIVE_FULL, E.RATE_LIMITED, E.WORKER_STOPPING, E.NOT_OWNER,
                          E.LOCAL_STORAGE, E.BUSY_CODE, E.OTHER},
                         {'auth_expired', 'wrong_account', 'offline', 'drive_full', 'rate_limited', 'worker_stopping', 'not_owner',
                          'local_storage', 'busy', 'other'})
        self.assertEqual({E.SIGN_IN_AGAIN, E.RETRY, E.FREE_SPACE, E.WAIT, E.RECOVER, E.NONE},
                         {'sign_in_again', 'retry', 'free_space', 'wait', 'recover', 'none'})


class DriveReasonTest(unittest.TestCase):
    """The reason Google gives travels on the exception, read the way `_rate_limited` reads it."""

    def test_error_reason_reads_the_first_reason_and_survives_a_bad_body(self):
        body = json.dumps({'error': {'code': 403, 'message': 'm', 'errors': [{'reason': 'storageQuotaExceeded', 'domain': 'usageLimits'}]}}).encode()
        self.assertEqual(drive_client._error_reason(body), 'storageQuotaExceeded')
        for bad in (b'', b'not json', b'[]', b'{"error":"text"}', b'{"error":{"errors":[]}}', b'{"error":{"errors":["x"]}}', b'{"error":{"errors":[{"reason":5}]}}'):
            self.assertEqual(drive_client._error_reason(bad), '', bad)

    def test_a_refused_call_carries_status_and_reason(self):
        client = drive_client.DriveClient('id', 'secret', {'refresh_token': 'r', 'access_token': 'a', 'expires_at': 9999999999})
        body = json.dumps({'error': {'message': 'quota', 'errors': [{'reason': 'storageQuotaExceeded'}]}}).encode()
        with mock.patch.object(drive_client, '_request', return_value=(403, {}, body)):
            with self.assertRaises(drive_client.DriveError) as caught:
                client.list()
        self.assertEqual((caught.exception.status, caught.exception.reason), (403, 'storageQuotaExceeded'))
        self.assertEqual(classify(caught.exception, used=2 ** 30, limit=2 ** 30)['code'], 'drive_full')

    def test_a_dead_network_has_no_status_and_classifies_as_offline(self):
        client = drive_client.DriveClient('id', 'secret', {'refresh_token': 'r', 'access_token': 'a', 'expires_at': 9999999999})
        client.attempts = 1
        with mock.patch.object(drive_client, '_request', side_effect=urllib.error.URLError('down')):
            with self.assertRaises(drive_client.DriveError) as caught:
                client.list()
        self.assertEqual((caught.exception.status, classify(caught.exception)['code']), (0, 'offline'))


if __name__ == '__main__':
    unittest.main()
