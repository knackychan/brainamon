"""One classifier for every Drive failure a user can see (I7, audit F8): a code, a message from a fixed table and the
next action. Routes, the upload thread and the recovery activity all use it, so the same failure reads the same
everywhere and survives closing Settings.

The message is built from the status, Google's reason string and our own texts. It never carries a Drive response
body, a token or a path: `classify` is only given the exception, and the exception types it trusts to carry their own
text (`WorkerStopping`, `Busy`, `NotUploader`, `WrongAccount`, `R.RecoveryError`) are raised with texts this program
wrote.

Imports library code only (sync.py, recovery.py and the routes all import this module).
"""
import socket
import urllib.error

from library import drive_client, mirror, recovery as R

AUTH_EXPIRED, WRONG_ACCOUNT, OFFLINE, DRIVE_FULL, RATE_LIMITED = 'auth_expired', 'wrong_account', 'offline', 'drive_full', 'rate_limited'
WORKER_STOPPING, NOT_OWNER, LOCAL_STORAGE, BUSY_CODE, OTHER = 'worker_stopping', 'not_owner', 'local_storage', 'busy', 'other'
FOREIGN_BACKUP, OTHER_COPY = 'foreign_backup', 'other_copy'      # the account holds another PC's backup (T3); the other copy on this PC made it (T15)

# what the page offers next
SIGN_IN_AGAIN, RETRY, FREE_SPACE, WAIT, RECOVER, NONE = 'sign_in_again', 'retry', 'free_space', 'wait', 'recover', 'none'

BUSY = 'Another Google Drive operation is running. Check its status in Backup & phones, then retry.'
FOREIGN_FOR = ('{account} already holds a Brainamon backup from another PC. '
               'Get it back on this PC, or use another Google account for this library.')
FOREIGN = ('This Google account already holds a Brainamon backup from another PC. '
           'Get it back on this PC, or use another Google account for this library.')

# audit section 7, verbatim
EXPIRED_FOR = ('Google Drive sign-in for {account} expired or was removed. Choose Sign in again and pick the same account. '
               'Your backup and settings stay as they are.')
EXPIRED = ('Google Drive sign-in expired or was removed. Choose Sign in again and pick the same account. '
           'Your backup and settings stay as they are.')
OFFLINE_TEXT = "Can't reach Google Drive. Nothing changed. Brainamon retries when the connection is back."
FULL_OF = 'Google Drive is full ({used} of {limit} GB). Free space in Google Drive, then choose Try again.'
FULL = 'Google Drive is full. Free space in Google Drive, then choose Try again.'
# not in the mockup's tables: plain sentences for the states the table has no row for
RATE_TEXT = 'Google Drive asked Brainamon to slow down. Brainamon tries again by itself.'
STORAGE_TEXT = 'Brainamon could not read or write its protected files on this PC. Keep the current files and retry.'
FORBIDDEN_TEXT = ('Google Drive refused access. Check this account\'s permissions and any administrator restrictions, '
                  'then choose Try again.')
API_DISABLED_TEXT = ('Google Drive API is not enabled for this app. Enable Google Drive API in the app\'s Google Cloud '
                     'project, check its permissions, then choose Try again.')
WRONG_ACCOUNT_TEXT = 'You signed in as {got}, but this library backs up to {expected}. Nothing changed.'

# Google's own reason strings (developers.google.com/workspace/drive/api/guides/handle-errors, checked 2026-10-30):
QUOTA_REASONS = {'storageQuotaExceeded'}
RATE_REASONS = {'userRateLimitExceeded', 'rateLimitExceeded', 'sharingRateLimitExceeded', 'dailyLimitExceeded'}


class WorkerStopping(drive_client.DriveError):
    """A stop outlasted the wait: one request is still in flight. The state already says 'stopping' and the worker
    finishes the stop by itself (I4)."""


class Busy(drive_client.DriveError):
    """A local cloud change refused because reconnect or another foreground operation runs (routes answer 409, never a
    write failure)."""

    def __init__(self, message=BUSY):
        super().__init__(message)


class NotUploader(drive_client.DriveError):
    """Another PC is the backup PC now: this PC stays paused instead of overwriting newer changes. `at`: when it took over (ms, 0 unknown)."""

    def __init__(self, message: str, at: int = 0):
        super().__init__(message)
        self.at = int(at or 0)


class RecoveryBlocked(drive_client.DriveError):
    """Local recovery state prevents uploads or saved cloud work."""


class ResumeOffline(drive_client.DriveError):
    """A failed Resume has no worker to retry when connectivity returns."""


class OtherCopy(drive_client.DriveError):
    """Another local app copy uses a different library key."""


class ForeignBackup(drive_client.DriveError):
    """The account already holds a Brainamon backup this PC knows nothing about (T3): getting it back is the way on, a second
    library in the same account is not. `at`: the newest time Drive stamped on it (ms, 0 unknown)."""

    def __init__(self, at: int = 0):
        super().__init__(FOREIGN)
        self.at = int(at or 0)


class WrongAccount(drive_client.DriveError):
    """Sign in again chose another Google account than the library backs up to (S1)."""

    def __init__(self, got: str, expected: str):
        super().__init__(WRONG_ACCOUNT_TEXT.format(got=got, expected=expected))
        self.got, self.expected = got, expected


def _gb(n: int) -> str:
    return f'{n / 2 ** 30:.1f}'


def _network(exc: BaseException) -> bool:
    return isinstance(exc, (urllib.error.URLError, ConnectionError, TimeoutError, socket.gaierror))


def _result(code: str, message: str, action: str) -> dict:
    return {'code': code, 'message': message, 'action': action}


def _expired(account: str) -> dict:
    return _result(AUTH_EXPIRED, EXPIRED_FOR.format(account=account) if account else EXPIRED, SIGN_IN_AGAIN)


def classify(exc: BaseException, *, account: str = '', used: int = 0, limit: int = 0, fallback: str = '', storage: str = '') -> dict:
    """{'code', 'message', 'action'} for `exc`. `account` names the signed-in Google account, `used` and `limit` are
    its Drive quota in bytes (both 0 when unknown); `fallback` replaces the text of a failure that has no row in the
    table (a raw Drive error), so the page keeps the sentence it showed before; `storage` does the same for a failure
    of this PC's protected files. Neither is ever filled from the exception, so a path or a token cannot reach a message
    through them unless the caller puts it there."""
    if isinstance(exc, ResumeOffline):
        return _result(OFFLINE, "Can't reach Google Drive. Backup stays paused; choose Resume backup again when the connection is back.", NONE)
    if isinstance(exc, WorkerStopping):
        return _result(WORKER_STOPPING, str(exc), WAIT)
    if isinstance(exc, Busy):
        return _result(BUSY_CODE, str(exc), WAIT)
    if isinstance(exc, WrongAccount):
        return _result(WRONG_ACCOUNT, str(exc), SIGN_IN_AGAIN)
    if isinstance(exc, NotUploader):
        return _result(NOT_OWNER, str(exc), RECOVER)
    if isinstance(exc, OtherCopy):
        return _result(OTHER_COPY, str(exc), NONE)
    if isinstance(exc, RecoveryBlocked):
        return _result(OTHER, str(exc), NONE)
    if isinstance(exc, ForeignBackup):
        return _result(FOREIGN_BACKUP, FOREIGN_FOR.format(account=account) if account else FOREIGN, RECOVER)
    if isinstance(exc, drive_client.DriveError):
        status, reason = getattr(exc, 'status', 0), getattr(exc, 'reason', '')
        if status == 401 or str(exc) == drive_client.SIGN_IN_REQUIRED:
            return _expired(account)
        if status == 403:
            if reason in QUOTA_REASONS:
                return _result(DRIVE_FULL, FULL_OF.format(used=_gb(used), limit=_gb(limit)) if limit else FULL, FREE_SPACE)
            if reason in RATE_REASONS or 'ratelimit' in reason.lower():
                return _result(RATE_LIMITED, RATE_TEXT, WAIT)
            if reason == 'accessNotConfigured':
                return _result(OTHER, API_DISABLED_TEXT, RETRY)
            return _result(OTHER, FORBIDDEN_TEXT, RETRY)  # permissions/configuration do not prove the token expired
        if status == 429:
            return _result(RATE_LIMITED, RATE_TEXT, WAIT)
        if status == 0 and isinstance(exc.__cause__, OSError):      # `DriveClient._call` wraps a request that never completed
            return _result(OFFLINE, OFFLINE_TEXT, NONE)
        return _result(OTHER, fallback or str(exc), RETRY)
    if isinstance(exc, R.RecoveryError):
        return _result(OTHER, str(exc), NONE)         # recovery's own sentences, written for the page
    if _network(exc):
        return _result(OFFLINE, OFFLINE_TEXT, NONE)
    if isinstance(exc, (OSError, RuntimeError, mirror.MirrorKeyError)):
        return _result(LOCAL_STORAGE, storage or STORAGE_TEXT, NONE)
    return _result(OTHER, fallback or str(exc), RETRY)
