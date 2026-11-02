"""Recovery enrollment, read-only restore jobs and explicit desktop handover."""
import contextlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from core import app_paths, entitlements, private_storage, sync_license
from library import drive_client, mirror, recovery as R, restore, update_folder, vault_sync
from library.export_targets import ExportStopped
from server import cloud_errors, intents
from server.cloud_errors import BUSY, Busy, ForeignBackup, NotUploader      # re-exported: the routes and tests read SR.Busy and SR.BUSY

OWNER_LOGICAL = 'recovery/owner.json'
VAULT_GUARD_SECONDS = 30
OWNER_NAME = re.compile(re.escape(R.PREFIX) + r'owner-([0-9a-f]{32})\.json')
RECORD_LIMIT = 100      # the discovery bound: recovery setups or uploader records inspected per account
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
ELIGIBLE = 'This folder matches the latest upload in Drive. You can keep it and reconnect it instead of restoring a copy.'
REFUSALS = {
    'no_upload': 'This folder has no record of its last Drive upload, so it cannot be reconnected. Restore into a new folder instead.',
    'other_library': 'This folder was last uploaded with a different library key, so it cannot be reconnected. Restore into a new folder instead.',
    'not_latest': 'This folder does not match the latest upload in Drive: it is older, or another PC uploaded since. Restore into a new folder and keep this one to compare by hand.',
    'adoption_pending': 'A key change from this folder is still waiting to upload, so it cannot be reconnected. Restore into a new folder instead.',
    'rotation_pending': 'A key rotation is pending on this PC, so this folder cannot be reconnected. Restore into a new folder instead.',
    'activation_pending': 'Switching to a restored library is pending. Quit and reopen Brainamon before reconnecting.',
    'restored': 'This folder is a restored library. Use Take over uploads instead of reconnecting.',
    'sync_on': 'Turn off library uploads and vault sync above, then find your library again to reconnect this folder.',
    'restore_started': 'A restore into a new folder has started from this preview. Close it and find your library again to reconnect instead.',
    'account_changed': 'The Google account changed. Find your library again.',
    'local_damaged': 'Protected recovery settings on this PC cannot be read, so this folder cannot be reconnected. Keep those files and restore into a new folder instead.',
    'records_damaged': 'Recovery records in Drive are damaged, duplicated or too many, so this folder cannot be reconnected. Keep uploads off and restore into a new folder instead.',
    'owner_unknown': 'Drive holds an uploader record this key cannot open, so reconnect stays off to protect any other library. Restore into a new folder instead.',
    'owner_ambiguous': 'Drive holds more than one recovery identity for this library, so reconnect stays off. Restore into a new folder instead.',
    'owner_mismatch': 'This recovery setup belongs to a different uploader record, so reconnect stays off. Use another recovery method or restore into a new folder.',
    'interrupted': 'Reconnect was interrupted after it started writing. Find your library again before retrying.',
}


class ReconnectRefused(R.RecoveryError):
    """Reconnect is not offered for this folder; restoring into a new folder stays available."""

    def __init__(self, reason):
        super().__init__(REFUSALS[reason])
        self.reason = reason


RESTORE_HINT = ('Use Recover a library with your passphrase, recovery file or a phone code. '
                'If this folder matches the last backup, choose Keep this folder.')
ACTIVITY_FAILED = 'This step did not finish. Retry it; existing recovery material was kept.'
CHECK_QUEUED = 'Waiting for the current upload request, then checking recovery. Backup carries on.'


UPDATE_REFUSALS = {      # Update this folder is not offered (S9): the summary offers Get the newer library… instead (T14)
    'no_recovery': 'This PC has no recovery setup for this library, so it cannot take the newer backup in place.',
    'restored': 'This folder is a restored library. Make this PC the backup PC instead.',
    'pending': 'A key change or a switch to another library is pending on this PC.',
    'other_key': 'The newer backup uses another key (phones were removed or the backup was reset there).',
    'other_account': 'This library backs up to another Google account.',
    'is_owner': 'This PC is the backup PC.',
}
UPDATE_AGAIN = 'The other PC backed up again. Brainamon is fetching those changes first; restart when it says Downloaded.'
UPDATE_UNSETTLED = 'The other PC keeps backing up. Quit Brainamon there, then choose Update this folder again.'
UPDATE_FIRST = 'Check the newer backup first: open Backup & phones again.'


INTERRUPTED = ('Reconnect was interrupted after it started writing to Drive. Drive may now hold a new recovery setup '
               'or uploader record; this PC kept its previous key and recovery settings. Uploads stay off. '
               'Find your library again before retrying.')
INTERRUPTED_LOCAL = ('Reconnect was interrupted while saving the key on this PC. The uploader record in Drive may already '
                     'name this PC. Uploads stay off. Find your library again before retrying; a backup of the previous '
                     'settings was kept.')
HANDOVER = ('Another PC changed uploader ownership during reconnect. Drive may now hold an extra recovery setup or a '
            'changed uploader record; this PC kept its previous key and recovery settings. Stop every other PC, then '
            'find your library again.')


def _day(seconds):
    """'30 Oct': how the recovery window names a day. English month names on purpose, not the system locale's."""
    d = datetime.fromtimestamp(seconds)
    return f'{d.day} {MONTHS[d.month - 1]}'


class ReadinessError(R.RecoveryError):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


class RecoveryService:
    def __init__(self, sync):
        self.sync = sync
        self.path = sync.cloud_dir / 'recovery.json'
        self.journal = sync.cloud_dir / 'recovery-activation.json'
        self.lock = threading.RLock()
        self.mutation = threading.RLock()   # held by reconnect(); conflicting local cloud changes try it without waiting (gate)
        self.reconnecting = False           # SyncService._start_control stays off while it is set
        self.cancel = threading.Event()
        self.thread = None
        self.session = None
        self.check_wanted, self.check, self.check_at = False, None, 0.0     # the readiness check queued behind an upload (S8)
        self.job = {'state': 'idle', 'done': 0, 'total': 0, 'error': '', 'destination': ''}
        self.update = None                  # Update this folder (S9): the last check's public answer
        self._update = None                 # ... and what it read (key, snapshot, difference); never in status
        self.update_cancel = threading.Event()
        self.updating = False               # the sync thread is downloading the update now

    def _load(self, *, readonly=False):
        state = self._optional(self.path, readonly=readonly)
        if state:
            R.validate(state.get('record'))
            if not isinstance(state.get('device'), str) or not re.fullmatch('[0-9a-f]{32}', state['device']):
                raise R.RecoveryError('Protected recovery identity is damaged. Restore with your saved material.')
            if state.get('account') != state['record']['header']['account'] or type(state.get('verified')) is not bool:
                raise R.RecoveryError('Protected recovery metadata is damaged.')
            if 'enrolled' in state and type(state['enrolled']) is not bool:
                raise R.RecoveryError('Protected recovery completion metadata is damaged.')
            if state.get('secret'):
                R.decode(state['secret'], 32)
        return state

    @staticmethod
    def _optional(path, *, readonly=False):
        try:
            return R.parse(private_storage.read(path, readonly=readonly))
        except FileNotFoundError:
            return None

    def _save(self, state):
        private_storage.write(self.path, R.dump(state))

    def _client(self, *, readonly=False):
        self.sync.require_open()
        token = drive_client.load_token(self.sync.token_path, readonly=readonly)
        if token is None:
            raise R.RecoveryError('Connect Google Drive first. Recovery sign-in does not turn on uploads.')
        client = self.sync._factory(token, recovery=True)
        if isinstance(client.client, drive_client.DriveClient):
            # Small interactive recovery requests should fail promptly enough to offer a retry.
            client.client.request_timeout = 20
            client.client.attempts = 3
        if readonly and isinstance(client.client, drive_client.DriveClient):
            # Preflight may renew access in memory; it never migrates or saves credentials.
            client.client.token_path = None
        return client

    def _account(self, client):
        email = client.about().get('email', '')
        if not email or not isinstance(email, str):
            raise R.RecoveryError('Google did not confirm the account. Reconnect before continuing.')
        return email.casefold()

    def status(self):
        # Protected files are atomically replaced. Never wait on the lock held through network work.
        # Polling never migrates, re-secures or rewrites protected files.
        state = self._load(readonly=True)
        rotation = self.sync._rotation(readonly=True)
        pending = rotation.get('recovery') if rotation and rotation.get('stage') != 'complete' else None
        replaced = state if state and state.get('replaced') and not state.get('verified') else None
        state = pending or state
        return {'configured': bool(state), 'enrolled': self._completed(state), 'verified': bool(state and state.get('verified')),
                # the key was replaced when phones were removed and the new recovery file is not saved and read back yet (D1)
                'file_outdated': bool(replaced), 'replaced_at': replaced.get('replaced_at', 0) if replaced else 0,
                'rotation_pending': bool(pending), 'restored': bool(state and state.get('restored')),
                'restart_required': bool(state and state.get('restored') and state.get('target') != str(self.sync.data_dir.resolve())),
                'verified_at': state.get('verified_at', 0) if state else 0,
                'saved_at': state.get('saved_at', 0) if state else 0,       # the kit was written to a file (R6), checked or not
                'setup_at': state['record']['header']['created'] if state else 0,       # s: when the passphrase was set (R5, R7)
                'takeover_ready': bool(state and state.get('takeover')),       # D3: the record sealed at activation; Make this PC the backup PC asks for no passphrase
                'account': state.get('account', '') if state else '',
                'fingerprint': state['record']['header']['fingerprint'] if state else '',
                'activity': self.sync.st.get('recovery_activity'),
                'check': dict(self.check) if self.check else None,      # the last readiness check; {'state': 'queued'} while it waits for a slot
                'update': dict(self.update) if self.update else None, 'updated': self._updated(),
                'job': dict(self.job), 'preview': self._public_preview()}

    def _updated(self):
        """The last Update this folder that finished here: {at, published, kept, folder} (the summary names the kept changes)."""
        try:
            value = json.loads(self.sync.writer.read(lambda db: db.get_setting('cloud_update_done', '')) or 'null')
        except (ValueError, RuntimeError, OSError):
            return None
        return value if isinstance(value, dict) else None

    def _public_preview(self):
        session = self.session
        if not session:
            return None
        snap = session['snapshot']
        reconnect = dict(session.get('reconnect') or {'ok': False, 'reason': 'unknown', 'message': ''})
        if reconnect['ok'] and (self.job.get('state') != 'preview' or session.get('stage')):
            reconnect = {'ok': False, 'reason': 'restore_started', 'message': REFUSALS['restore_started']}
        return {**{k: snap[k] for k in ('items', 'files', 'bytes', 'published', 'videos', 'canvases', 'omissions')},
                'duplicates': snap.get('duplicates', 0), 'generation': session.get('generation'),
                'notice': session.get('notice', ''), 'reconnect': reconnect,
                'fingerprint': session['key'].fingerprint,      # W4b: the found backup has this folder's key
                'password_known': bool(session.get('password'))}      # D3: Keep this folder reuses the passphrase typed to find the backup

    def _idle(self):
        if self.thread and self.thread.is_alive():
            raise R.RecoveryError('A recovery operation is already running.')

    @contextlib.contextmanager
    def gate(self):
        """A local cloud change that must not race reconnect: never waits, refuses while reconnect runs."""
        if not self.mutation.acquire(blocking=False):
            activity = self.sync.st.get('recovery_activity') or {}
            if activity.get('state') == 'running':
                raise Busy(activity['step'] + ' Wait for this step to finish, then retry.')
            raise Busy()
        try:
            yield
        finally:
            self.mutation.release()

    @contextlib.contextmanager
    def activity(self, action, step):
        """One foreground cloud change, with status that survives closing Settings."""
        with self.gate():
            if not self.lock.acquire(blocking=False):
                raise Busy()
            self.sync._set(recovery_activity={'action': action, 'state': 'running', 'step': step,
                                              'started': int(time.time() * 1000)})
            try:
                yield
            except Exception as e:
                # the reason survives closing Settings: its code, its sentence from the fixed table and the next action (I7)
                c = self.sync.classified(e, fallback=ACTIVITY_FAILED)
                # `action` of the activity names the operation ('enroll', 'unpair'); the next step is `next`
                self.sync._set(recovery_activity={**self.sync.st['recovery_activity'], 'state': 'error', 'step': c['message'],
                                                 'code': c['code'], 'next': c['action']})
                raise
            else:
                self.sync._set(recovery_activity=None)
            finally:
                self.lock.release()

    def progress(self, step):
        activity = self.sync.st.get('recovery_activity')
        if activity and activity['state'] == 'running':
            self.sync._set(recovery_activity={**activity, 'step': step})

    def forget_reconnect(self):
        """The account changed: the preview's Reconnect answer is stale (restore re-checks the account itself)."""
        session = self.session
        if session and session.get('reconnect'):
            session['reconnect'] = {'ok': False, 'reason': 'account_changed', 'message': REFUSALS['account_changed']}

    @staticmethod
    def owner_name(library):
        if not isinstance(library, str) or not re.fullmatch('[0-9a-f]{32}', library):
            raise R.RecoveryError('Invalid library identity.')
        return R.PREFIX + 'owner-' + library + '.json'

    def _owner(self, client, key, library, listing=None):
        found = [f for f in (client.list() if listing is None else listing) if f['name'] == self.owner_name(library)]
        if len(found) != 1:
            raise R.RecoveryError('Uploader ownership is missing or ambiguous. Keep uploads off and retry recovery.')
        try:
            value = R.parse(key.open(OWNER_LOGICAL, restore.download(client, found[0], R.MAX_RECORD)))
        except mirror.MirrorKeyError:
            raise R.RecoveryError('Uploader ownership cannot be authenticated.') from None
        if (value.get('library') != library or value.get('fingerprint') != key.fingerprint
                or not isinstance(value.get('device'), str) or not isinstance(value.get('generation'), str)):
            raise R.RecoveryError('Invalid uploader ownership record.')
        return found[0], value

    def _write_owner(self, client, key, library, device, generation, existing=''):
        body = {'library': library, 'fingerprint': key.fingerprint, 'device': device,
                'generation': generation, 'changed': int(time.time())}
        client.upload(self.owner_name(library), data=key.seal(OWNER_LOGICAL, R.dump(body)), file_id=existing)
        _, readback = self._owner(client, key, library)
        if readback != body:
            raise R.RecoveryError('Another PC changed uploader ownership. Refresh recovery before retrying.')

    def guard(self, client, *, cached=False):
        """Only immutable vault blobs and status may reuse a recent remote check.

        Local recovery state is always reread. Index publication and destructive
        operations use a fresh check; concurrent blob uploads share one check.
        """
        # Keep each account client's cache and lock separate from sign-in and recovery clients.
        from server.sync import _GuardedClient
        wrapper = client if isinstance(client, _GuardedClient) else None
        if wrapper:
            client = wrapper.client
        with wrapper._guard_lock if wrapper else contextlib.nullcontext():
            try:
                if self._optional(self.journal):
                    raise R.RecoveryError('Recovery activation is pending. Restart Brainamon before uploading.')
                state = self._load()
                if state is None and self._optional(self.sync.cloud_dir / 'recovery-legacy.json'):
                    raise R.RecoveryError('Set up verified recovery for the restored legacy library before uploading.')
                epoch = self.sync.writer.read(lambda db: db.get_setting('cloud_epoch', ''))
                key = mirror.MirrorKey.load(self.sync.key_path)
                context = (client, state, epoch, key.fingerprint if key else '')
                if cached and wrapper and context == wrapper._guard_cache and time.monotonic() < wrapper._guard_until:
                    return
                if wrapper:
                    wrapper._guard_cache = None
                self._guard_remote(client, state, epoch, key)
                if wrapper:
                    wrapper._guard_cache = context
                    wrapper._guard_until = time.monotonic() + VAULT_GUARD_SECONDS
            except R.RecoveryError as e:
                if wrapper:
                    wrapper._guard_cache = None
                raise drive_client.DriveError(str(e)) from None
            except BaseException:
                if wrapper:
                    wrapper._guard_cache = None
                raise

    def _guard_remote(self, client, state, epoch, key):
        try:
            if state:
                if state.get('restored'):
                    raise R.RecoveryError('Use Take over uploads after restarting the restored library. Uploads remain off until then.')
                if key is None or key.fingerprint != state['record']['header']['fingerprint']:
                    raise R.RecoveryError("This PC's library key does not match its recovery setup. " + RESTORE_HINT)
                if self._account(client) != state['account']:
                    raise R.RecoveryError('Reconnect the Google account used for this library, or restore its library before uploading.')
                _, owner = self._owner(client, key, state['record']['header']['library'])
                if owner['device'] != state['device']:
                    raise NotUploader('Another PC became the backup PC. This PC stopped backing up so it does not overwrite newer changes.',
                                      at=int(owner.get('changed') or 0) * 1000)
                return
            listing = client.list()
            fingerprint = epoch or (key.fingerprint if key else '')
            if fingerprint:
                for f in listing:
                    if f['name'].startswith(R.PREFIX) and not f['name'].startswith(R.PREFIX + 'owner-'):
                        record = R.parse(restore.download(client, f, R.MAX_RECORD))
                        if R.validate(record)['fingerprint'] == fingerprint:
                            raise R.RecoveryError('Recovery is configured for this library, but this PC does not hold its key. ' + RESTORE_HINT)
            if epoch:
                if key is None:
                    raise R.RecoveryError('The original library key is missing. ' + RESTORE_HINT)
                return
            own_names = {key.name(mirror.MANIFEST), vault_sync.status_name(key), vault_sync.index_name(key, 'pc')} if key else set()
            own_controls = {key.name(path) for path in sync_license.CONTROL_LOGICALS} if key else set()
            unknown = [f for f in listing if f['name'] not in own_controls
                       and not re.fullmatch(r'solo-[0-9a-f]{32}-[0-9a-f]{32}', f['name'])
                       and not re.fullmatch(r'vi-phone-recovery-[0-9a-f]{32}-[0-9a-f]{32}\.json', f['name'])]
            if unknown and not any(f['name'] in own_names for f in unknown):
                # T3: another PC's backup. Nothing was changed; the page offers Recover this backup and Use another account.
                from server.sync import _drive_ms
                stamps = [t for t in (_drive_ms(f.get('modifiedTime')) for f in unknown) if t]
                raise ForeignBackup(max(stamps, default=0))
        except R.RecoveryError as e:
            raise drive_client.DriveError(str(e)) from None

    def discover(self):
        with self.lock:
            self._idle()
            client = self._client(readonly=True)
            account = self._account(client)
            return [header for header, _record in self._records(client, account, client.list())]

    def _records(self, client, account, listing):
        """[(header plus its Drive id, parsed record)] of this account's recovery setups, newest first. Reads only."""
        candidates, seen = [], set()
        for f in listing:
            if not f['name'].startswith(R.PREFIX) or f['name'].startswith(R.PREFIX + 'owner-'):
                continue
            if f['name'] in seen:
                raise R.RecoveryError('Duplicate recovery records found. Do not enable uploads; resolve them before restoring.')
            seen.add(f['name'])
            if len(seen) > RECORD_LIMIT:
                raise R.RecoveryError('Too many recovery generations. Use a saved kit or original code.')
            candidates.append(f)

        def read(f):
            record = R.parse(restore.download(client, f, R.MAX_RECORD))
            h = R.validate(record)
            if f['name'] != R.name(record):
                raise R.RecoveryError('Recovery record has an inconsistent identity.')
            return ({'id': f['id'], **h}, record) if h['account'] == account else None

        found = []
        with ThreadPoolExecutor(4, thread_name_prefix='cm-recovery-find') as pool:
            for start in range(0, len(candidates), 4):
                found.extend(r for r in pool.map(read, candidates[start:start + 4]) if r is not None)
        return sorted(found, key=lambda r: r[0]['created'], reverse=True)

    def enroll(self, password, confirmation):
        """Set up (or change) the recovery passphrase. The record is sealed here and saved as a task; the sync thread uploads it
        between two upload requests (`run_enroll`), so back-to-back uploads cannot starve it. With no sync thread the
        caller runs it at once. Returns the recovery kit, which is complete locally; `status()['enrolled']` says when
        Drive holds the record. A second click while the task exists is refused (Busy)."""
        if password != confirmation:
            raise R.RecoveryError('The recovery passphrases do not match.')
        R.password_bytes(password)
        sync = self.sync
        with self.activity('enroll', 'Preparing the recovery setup…'):
            self._idle()
            rotation = sync._rotation()
            if rotation and rotation['stage'] != 'complete':
                raise ReadinessError('rotation_pending', 'Finish the pending key rotation before changing recovery setup.')
            client = self._client()
            account = self._account(client)
            previous = self._load()
            if previous and previous['account'] != account:
                previous = None             # another account: _eligibility decides whether that is allowed
            key = mirror.MirrorKey.load(sync.key_path)
            made = key is None
            if made:
                key = mirror.MirrorKey.generate()
            record, secret = R.create(key, password, account, library=previous['record']['header']['library'] if previous else None)
            payload = {'record': record, 'secret': R.encode(secret), 'account': account, 'key': key.text() if made else '',
                       'device': previous['device'] if previous else secrets.token_hex(16)}
            sync.intents.add(intents.ENROLL, payload)
            kit = R.kit(record, payload['secret'])
            if sync.running or sync.vault_running:
                sync.ensure_running()
                return kit
            try:
                self.run_enroll(sync.intents.find(intents.ENROLL), inline=True)
            except Exception:
                sync.intents.finish(intents.ENROLL)
                raise
            return kit

    def run_enroll(self, intent, *, inline=False):
        """Upload the sealed record, read it back, write the uploader record (R4). On the sync thread (`inline` False) it first
        ends the vault thread, which also uploads; a stuck request there means the task stays queued and tries again."""
        sync = self.sync
        control = bool(sync._control_thread and sync._control_thread.is_alive())
        vault = sync.vault_running
        try:
            if inline:
                self._run_enroll(intent, from_sync=False)
            else:
                with self.activity('enroll', 'Saving the recovery setup between upload requests…'):
                    sync.intents.update(intents.ENROLL, stage='uploading')
                    sync._emit()
                    if vault:
                        try:
                            sync._end_vault()
                        except cloud_errors.WorkerStopping:
                            sync.intents.update(intents.ENROLL, stage='queued')
                            return
                    self._run_enroll(intent, from_sync=True)
        finally:
            if not sync._closing and not inline:
                if control:
                    sync._start_control()
                if vault and entitlements.feature_enabled('phone_sync') and sync.writer.read(lambda db: db.get_setting('cloud_vault', '') == 'on'):
                    sync.start_vault()

    def _run_enroll(self, intent, *, from_sync):
        self._enroll(intent['payload'], from_sync=from_sync)
        self.sync.intents.finish(intents.ENROLL)

    def _eligibility(self, client=None, account=None, *, readonly=False):
        rotation = self.sync._rotation(readonly=readonly)
        if rotation and rotation['stage'] != 'complete':
            raise ReadinessError('rotation_pending', 'Finish the pending key rotation before changing recovery setup.')
        client = client or self._client(readonly=readonly)
        account = account or self._account(client)
        previous = self._load(readonly=readonly)
        legacy = self._optional(self.sync.cloud_dir / 'recovery-legacy.json', readonly=readonly)
        if legacy and legacy.get('target') != str(self.sync.data_dir.resolve()):
            raise ReadinessError('restart_required', 'Quit and reopen the restored library before setting up recovery.')
        if previous and previous.get('restored'):
            raise ReadinessError('takeover_required', 'Use Take over uploads for this restored library before changing recovery setup.')
        key = mirror.MirrorKey.load(self.sync.key_path, readonly=readonly)
        listing = client.list()
        epoch = self.sync.writer.read(lambda db: db.get_setting('cloud_epoch', ''))
        if previous:
            if account != previous['account']:
                selected = self.sync.writer.read(lambda db: db.get_setting('cloud_account', '')).casefold()
                if epoch or selected != account:
                    raise ReadinessError('account_mismatch', 'Reconnect the Google account used for recovery, or use Change account before checking a different account.')
                previous = None
            else:
                if key is None or key.fingerprint != previous['record']['header']['fingerprint']:
                    raise ReadinessError('restore_required', "This PC's library key does not match its recovery setup. " + RESTORE_HINT)
                owners = [f for f in listing if f['name'] == self.owner_name(previous['record']['header']['library'])]
                if owners or self._completed(previous):
                    _, owner = self._owner(client, key, previous['record']['header']['library'], listing)
                    if owner['device'] != previous['device']:
                        raise ReadinessError('takeover_required', 'Only the current uploader can change recovery setup.')
        if epoch and (key is None or epoch != key.fingerprint):
            raise ReadinessError('restore_required', 'The local key does not belong to this library. ' + RESTORE_HINT)
        own_manifest = key.name(mirror.MANIFEST) if key is not None else ''
        own_controls = {key.name(path): path for path in sync_license.CONTROL_LOGICALS} if key is not None else {}
        unknown = [f for f in listing if f['name'] not in own_controls
                   and not re.fullmatch(r'solo-[0-9a-f]{32}-[0-9a-f]{32}', f['name'])
                   and not re.fullmatch(r'vi-phone-recovery-[0-9a-f]{32}-[0-9a-f]{32}\.json', f['name'])]
        own_names = {own_manifest, vault_sync.status_name(key), vault_sync.index_name(key, 'pc')} if key else set()
        if not previous and not epoch and unknown and not any(f['name'] in own_names for f in unknown):
            raise ReadinessError('restore_required', 'This account already contains app data. Restore it with your passphrase, kit or original code before creating a new mirror.')
        for f in listing:
            if f['name'] in own_controls:
                key.open(own_controls[f['name']], restore.download(client, f, R.MAX_RECORD))
        # This key's own mirror may hold duplicate copies after a forgotten sign-in (F1); the uploader heals them on its
        # next publish, so they never block recovery setup (I3). Every other duplicate name still refuses.
        mirror_names = set()
        if key is not None and any(f['name'] == own_manifest for f in listing):
            try:
                mirror_names = set().union(*(restore.manifest_names(key, man)
                                             for _entry, _raw, _plain, man in restore.manifests(client, key, listing=listing)))
            except R.RecoveryError:
                raise ReadinessError('restore_required', "A copy of this backup in Drive cannot be opened with this PC's key. " + RESTORE_HINT)
        names = [f['name'] for f in unknown if f['name'] not in mirror_names] + [f['name'] for f in listing if f['name'] in own_controls]
        if len(names) != len(set(names)):
            raise ReadinessError('restore_required', 'Duplicate app records found. Keep uploads off and restore or resolve them before continuing.')
        return client, account, previous, key, listing

    def preflight(self):
        """The recovery readiness check (read only). A busy publisher is not an empty account, and the check never pauses or waits
        for it: with the sync thread uploading, the check is queued and runs on that thread between two upload requests (F10, S8);
        the answer is `{'state': 'queued'}` now and `status()['check']` later. Anything else is answered at once."""
        if not self.lock.acquire(blocking=False):
            return {'state': 'retry', 'message': 'Recovery is busy. Wait and retry.', 'account': '', 'enrolled': False}
        publishing = False
        account = ''
        try:
            publishing = self.sync._publishing.acquire(blocking=False)
            if not publishing and self.sync.running and not (self.thread and self.thread.is_alive()):
                self.check_wanted, self.check = True, {'state': 'queued', 'message': CHECK_QUEUED, 'account': '', 'enrolled': False}
                self.sync.poke()
                return dict(self.check)
            return self._check(publishing)
        finally:
            if publishing:
                self.sync._publishing.release()
            self.lock.release()

    def run_queued_check(self):
        """On the sync thread, between upload requests (it holds the publish lock then): the check `preflight` queued."""
        if not self.check_wanted or not self.lock.acquire(blocking=False):
            return
        try:
            self.check_wanted = False
            self.check = self._check(True)
            self.check_at = time.monotonic()
        finally:
            self.lock.release()
        self.sync._emit()

    def _check(self, publishing):
        account = ''
        try:
            if not publishing or (self.thread and self.thread.is_alive()):
                raise ReadinessError('retry', 'An upload or recovery operation is running. Wait and retry.')
            if self._optional(self.journal, readonly=True):
                raise ReadinessError('restart_required', 'Recovery activation is pending. Quit and reopen Brainamon.')
            if drive_client.load_token(self.sync.token_path, readonly=True) is None:
                raise ReadinessError('sign_in_required', 'Connect Google Drive first. Uploads can stay off.')
            client = self._client(readonly=True)
            account = self._account(client)
            client, account, previous, key, listing = self._eligibility(client, account, readonly=True)
            enrolled = self._completed(previous)
            if previous and not enrolled and key and previous.get('secret'):
                # Old candidates stay unconfirmed unless envelope and ownership both authenticate.
                matches = [f for f in listing if f['name'] == R.name(previous['record'])]
                owners = [f for f in listing if f['name'] == self.owner_name(previous['record']['header']['library'])]
                if len(matches) == 1 and len(owners) == 1:
                    record = R.parse(restore.download(client, matches[0], R.MAX_RECORD))
                    if record == previous['record'] and R.unlock(record, secret=previous['secret']).master == key.master:
                        _, owner = self._owner(client, key, record['header']['library'], listing)
                        enrolled = owner['device'] == previous['device'] and owner['generation'] == record['header']['generation']
            return {'state': 'ready', 'message': 'This account and library key are ready for recovery setup.',
                    'account': account, 'enrolled': enrolled}
        except ReadinessError as e:
            return {'state': e.state, 'message': str(e), 'account': account, 'enrolled': False}
        except (OSError, ValueError, RuntimeError, drive_client.DriveError, mirror.MirrorKeyError) as e:
            c = self.sync.classified(e)
            expired = c['code'] == cloud_errors.AUTH_EXPIRED
            note = c['message'] if expired or c['code'] == cloud_errors.OFFLINE else 'Recovery could not be checked. Keep the existing files, check the connection and retry.'
            return {'state': 'sign_in_required' if expired else 'retry', 'message': note,
                    'code': c['code'], 'action': c['action'], 'account': account, 'enrolled': False}

    @staticmethod
    def _completed(state):
        return bool(state and not state.get('restored') and state.get('enrolled', state.get('verified')) is True)

    def reconcile(self):
        """Confirm an older local candidate only from authenticated envelope/owner evidence. The answer of a check that just ran
        between upload requests counts for two minutes (an upload may be running again by the time the page asks)."""
        with self.lock:
            fresh = self.check and self.check.get('state') == 'ready' and time.monotonic() - self.check_at < 120
            result = dict(self.check) if fresh else self.preflight()
            state = self._load()
            if not state or result['state'] != 'ready' or not result['enrolled'] or state['account'] != result['account']:
                raise R.RecoveryError('Enrollment completion could not be confirmed. Keep the existing files and retry the recovery check.')
            if not self._completed(state):
                state['enrolled'] = True
                self._save(state)
            return self.status()

    def _enroll(self, payload, *, from_sync=False):
        with self.lock, self.sync._publishing:
            self._idle()
            self._stop_writers(from_sync=from_sync)
            original = self._load()
            self.progress('Checking the Google account and existing recovery records…')
            client, account, previous, key, listing = self._eligibility()
            R.validate(payload['record'])
            record, secret = payload['record'], payload['secret']
            if key is None:
                key = mirror.MirrorKey(R.decode(payload['key'], 32)) if payload.get('key') else None
            if key is None or key.fingerprint != record['header']['fingerprint'] or account != payload['account']:
                raise R.RecoveryError('The library key or the Google account changed while the passphrase waited. Set it up again.')
            device = payload['device'] if not previous or previous['device'] == payload['device'] else previous['device']
            key.save(self.sync.key_path)
            state = {'record': record, 'secret': secret, 'device': device, 'account': account,
                     'verified': False, 'verified_at': 0, 'enrolled': False}
            # Persist the candidate before any upload so an interrupted first setup keeps its master/kit.
            backup = self.sync.cloud_dir / 'recovery-enrollment-previous.json'
            if original and (self._completed(original) or not self._optional(backup)):
                private_storage.write(backup, R.dump(original))
            self._save(state)
            try:
                self.progress('Saving and reading back the encrypted recovery record in Google Drive…')
                fid = client.upload(R.name(record), data=R.dump(record))
                uploaded = R.parse(restore.download(client, {'id': fid, 'size': len(R.dump(record))}, R.MAX_RECORD))
                if uploaded != record or R.unlock(uploaded, secret=secret).master != key.master:
                    raise R.RecoveryError('Recovery verification failed. Previous recovery material is unchanged.')
                self.progress('Confirming this PC as the uploader and completing recovery setup…')
                owners = [f for f in listing if f['name'] == self.owner_name(record['header']['library'])]
                self._write_owner(client, key, record['header']['library'], device, record['header']['generation'],
                                  owners[0]['id'] if owners else '')
                state['enrolled'] = True
                self._save(state)
            except Exception:
                if previous:
                    self._save(original)
                raise
            if previous:
                # D5: the setup this one replaces opens the same key; once the new one is in Drive it only confuses a restore
                self.prune(client, account, record['header']['library'], fingerprint=key.fingerprint, keep={R.name(record)})
            self.sync._set(error='')
            return R.kit(record, state['secret'])

    def export_kit(self):
        with self.lock:
            self._idle()
            rotation = self.sync._rotation()
            state = rotation.get('recovery') if rotation and rotation.get('stage') != 'complete' else None
            state = state or self._load()
            if not state:
                raise R.RecoveryError('Set up recovery first.')
            return R.kit(state['record'], state['secret'])

    def save_kit(self, path):
        with self.lock:
            value = self.export_kit()
            target = restore.destination(path, (self.sync.data_dir, self.sync.cloud_dir, app_paths.LOCAL))
            raw = R.dump(value)
            with target.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if target.read_bytes() != raw:
                raise R.RecoveryError('The recovery kit could not be verified on disk. Save it again.')
            self._mark_saved()
            out = {'path': str(target), 'saved': True, 'verified': False}
            try:
                self._verify(raw.decode())          # D11: no separate Check click: the file just written is read back against Drive
                out['verified'] = True
            except (R.RecoveryError, drive_client.DriveError, OSError) as e:
                out['message'] = self.sync.classified(e)['message']      # the file is saved; Check recovery file… can retry
            return out

    def _mark_saved(self):
        """Remember that this kit reached a file, so reopening Settings still says "saved, not checked" (F14)."""
        now = int(time.time())
        rotation = self.sync._rotation()
        if rotation and rotation.get('stage') != 'complete' and rotation.get('recovery'):
            rotation['recovery']['saved_at'] = now
            self.sync._save_rotation(rotation)
            return
        state = self._load()
        if state:
            state['saved_at'] = now
            self._save(state)

    def verify_kit(self, text):
        with self.activity('verify', 'Opening the saved recovery kit and checking its key…'):
            self._idle()
            return self._verify(text)

    def _verify(self, text):
        """Read a saved kit against Drive: it opens the library key, matches this setup and the record in Drive."""
        rotation = self.sync._rotation()
        pending = bool(rotation and rotation.get('stage') == 'prepared' and rotation.get('recovery'))
        state = rotation['recovery'] if pending else self._load()
        key, kit = R.import_key(text)
        if (not state or not kit or kit['record'] != state['record'] or kit['secret'] != state['secret']
                or key.fingerprint != state['record']['header']['fingerprint']):
            raise R.RecoveryError('Select the recovery kit you just saved for this setup.')
        self.progress('Checking the Google account for this recovery kit…')
        client = self._client()
        if self._account(client) != state['account']:
            raise R.RecoveryError('Reconnect the Google account used for this recovery kit.')
        self.progress('Finding the matching encrypted recovery record in Google Drive…')
        matches = [f for f in client.list() if f['name'] == R.name(state['record'])]
        if len(matches) != 1:
            raise R.RecoveryError('Recovery envelope is missing or duplicated in Drive.')
        self.progress('Downloading and verifying the recovery record against your saved kit…')
        record = R.parse(restore.download(client, matches[0], R.MAX_RECORD))
        if R.unlock(record, secret=kit['secret']).master != key.master or record != state['record']:
            raise R.RecoveryError('The saved kit does not match the uploaded recovery envelope.')
        state.update(verified=True, verified_at=int(time.time()))
        if pending:
            rotation['recovery'] = state
            self.sync._save_rotation(rotation)
        else:
            library = state['record']['header']['library']
            matches = [f for f in client.list() if f['name'] == self.owner_name(library)]
            if matches:
                owner_file, owner = self._owner(client, key, library)
                if owner['device'] != state['device']:
                    raise R.RecoveryError('Another PC is the uploader. Use explicit recovery takeover instead.')
                owner_id = owner_file['id']
            else:
                owner_id = ''
            self._write_owner(client, key, library, state['device'], state['record']['header']['generation'], owner_id)
            self._save(state)
        self.sync._set(error='')
        return self.status()

    def preview(self, *, material='', file_id='', password=''):
        with self.lock:
            self._idle()
            self._stop_writers()
            client = self._client(readonly=True)
            account = self._account(client)
            record, kit, snap, notice, how, unfinished = None, None, None, '', '', False
            listing = client.list()
            if file_id:
                candidates = [f for f in listing if f['id'] == file_id and f['name'].startswith(R.PREFIX)]
                if len(candidates) != 1:
                    raise R.RecoveryError('Select an available recovery generation.')
                record = R.parse(restore.download(client, candidates[0], R.MAX_RECORD))
                if R.name(record) != candidates[0]['name'] or record['header']['account'] != account:
                    raise R.RecoveryError('The recovery generation belongs to another account.')
                key = R.unlock(record, password=password)
            elif password and not material.strip():
                key, record, snap, notice, unfinished = self._by_passphrase(client, account, listing, password)
            else:
                key, kit = R.import_key(material)
                record = kit['record'] if kit else None
                how = 'kit' if kit else 'code'
                if record and record['header']['account'] != account:
                    raise R.RecoveryError('Connect the Google account shown in this recovery kit.')
            if snap is None:
                try:
                    snap = restore.preview(client, key, listing=listing)
                except restore.NoMirror:
                    self._explain_outdated(client, account, listing, key, record, how)
                    raise
            reconnect = self._reconnect_eligibility(client, key, account, record, snap)
            header = record['header'] if record else None
            # `password` stays in memory for this session only (never logged, never in status): Keep this folder and Make this
            # PC the backup PC reuse it instead of asking again (D3). `removal_unfinished`: the copy is from before a removal
            # of phones that never finished (finding 2).
            self.session = {'key': key, 'snapshot': snap, 'record': record, 'kit': kit, 'account': account, 'password': password,
                            'removal_unfinished': unfinished, 'reconnect': reconnect, 'notice': notice,
                            'generation': {'created': header['created'], 'fingerprint': header['fingerprint']} if header else None}
            self.job = {'state': 'preview', 'done': 0, 'total': snap['files'], 'error': '', 'destination': ''}
            return self.status()

    def _by_passphrase(self, client, account, listing, password):
        """The recovery setup this passphrase opens whose key has a backup, newest first (I5): (key, record, snapshot,
        notice). A newer setup that opens but has no backup is a removal of phones that never finished; it is skipped
        and named in the notice. A passphrase that opens nothing is the user's error, not a missing backup."""
        skipped, last = [], None
        for header, record in self._records(client, account, listing):
            try:
                key = R.unlock(record, password=password)
            except R.RecoveryError:
                continue
            try:
                snap = restore.preview(client, key, listing=listing)
            except restore.NoMirror as e:      # any other refusal (a format, an unfinished upload) is this setup's own
                skipped.append(header)
                last = e
                continue
            newer = [h for h in skipped if h['library'] == header['library']]
            notice = (f"Used the recovery setup from {_day(header['created'])}. The newer one from {_day(newer[0]['created'])} "
                      'has no backup because removing phones did not finish.') if newer else ''
            return key, record, snap, notice, bool(newer)
        raise last or R.RecoveryError(f"That passphrase doesn't unlock a backup in {account}. Check it, or use a recovery file or a phone code.")

    def _explain_outdated(self, client, account, listing, key, record, how):
        """A kit or phone code whose key has no backup, while the account holds a newer recovery setup of the same
        library: the key was replaced when phones were removed (I5). Says so; otherwise the plain message stands."""
        if how not in ('kit', 'code'):
            return
        try:
            headers = [h for h, _record in self._records(client, account, listing)]
        except R.RecoveryError:
            return
        mine = record['header'] if record else next((h for h in headers if h['fingerprint'] == key.fingerprint), None)
        newer = [h for h in headers if mine and h['library'] == mine['library'] and h['created'] > mine['created']]
        # D5: a completed removal deletes the setups of the old key, so a phone code from before it matches none. The account
        # still holds the setups of the key that replaced it, and that is the evidence now.
        if how == 'code' and (newer or (not mine and headers)):
            raise R.RecoveryError('That phone code is from before phones were removed. Use a phone you added again, or your passphrase.')
        if not newer:
            return
        raise R.RecoveryError(f"This recovery file is from before phones were removed on {_day(min(h['created'] for h in newer))}. "
                              'Use your passphrase or the newer recovery file.')

    def _reconnect_check(self, key, snap):
        """This folder's own proof that it is the latest upload, and no local work reconnect would race. Reads only."""
        def read(db):
            return (db.get_setting('cloud_epoch', ''), db.get_setting('cloud_epoch_next', ''),
                    db.get_setting('cloud_upload', ''), db.get_setting('cloud_vault', ''),
                    db.get_sync_state().get(mirror.MANIFEST))
        epoch, adopt, upload, vault, row = self.sync.writer.read(read)
        if not epoch:
            raise ReconnectRefused('no_upload')
        if epoch != key.fingerprint:
            raise ReconnectRefused('other_library')
        if adopt:
            raise ReconnectRefused('adoption_pending')
        # The fingerprint alone is not the proof: this folder must have published exactly this manifest.
        if not row or row['drive_id'] != snap['manifest_id'] or row['sig'] != snap['manifest_sig']:
            raise ReconnectRefused('not_latest')
        if upload == 'on' or vault == 'on' or self.sync.running or self.sync.vault_running:
            raise ReconnectRefused('sync_on')
        try:
            pending = self._optional(self.journal, readonly=True)
            legacy = self._optional(self.sync.cloud_dir / 'recovery-legacy.json', readonly=True)
            state = self._load(readonly=True)
            rotation = self.sync._rotation(readonly=True)
        except (R.RecoveryError, OSError, RuntimeError, ValueError):
            raise ReconnectRefused('local_damaged') from None
        if pending:
            raise ReconnectRefused('activation_pending')
        if legacy or (state and state.get('restored')):
            raise ReconnectRefused('restored')
        if rotation and rotation.get('stage') != 'complete':
            raise ReconnectRefused('rotation_pending')

    def _reconnect_identity(self, client, key, account, record, listing):
        """The one uploader namespace every recovery method reuses. Reads Drive only; never picks between two."""
        named = [f for f in listing if f['name'].startswith(R.PREFIX)]
        if len(named) != len({f['name'] for f in named}):
            raise ReconnectRefused('records_damaged')
        owners = [f for f in named if f['name'].startswith(R.PREFIX + 'owner-')]
        setups = [f for f in named if not f['name'].startswith(R.PREFIX + 'owner-')]
        if len(owners) > RECORD_LIMIT or len(setups) > RECORD_LIMIT:
            raise ReconnectRefused('records_damaged')
        found = {}
        for f in owners:
            match = OWNER_NAME.fullmatch(f['name'])
            if not match:
                raise ReconnectRefused('records_damaged')
            try:
                found[match.group(1)] = (f['id'], self._owner(client, key, match.group(1), listing)[1])
            except R.RecoveryError:
                raise ReconnectRefused('owner_unknown') from None
        if len(found) > 1:
            raise ReconnectRefused('owner_ambiguous')
        libraries = set()
        for f in setups:
            try:
                value = R.parse(restore.download(client, f, R.MAX_RECORD))
                h = R.validate(value)
                if R.name(value) != f['name']:
                    raise R.RecoveryError('inconsistent recovery record name')
            except R.RecoveryError:
                raise ReconnectRefused('records_damaged') from None
            if h['account'] == account and h['fingerprint'] == key.fingerprint:
                libraries.add(h['library'])
        chosen = record['header']['library'] if record else None
        if found:
            library, (owner_id, owner) = next(iter(found.items()))
            if chosen not in (None, library):
                raise ReconnectRefused('owner_mismatch')
            if libraries - {library}:
                raise ReconnectRefused('owner_ambiguous')
            return {'library': library, 'owner_id': owner_id, 'owner': owner}
        if chosen:
            if libraries - {chosen}:
                raise ReconnectRefused('owner_ambiguous')
            return {'library': chosen, 'owner_id': '', 'owner': None}
        if len(libraries) > 1:
            raise ReconnectRefused('owner_ambiguous')
        # One matching setup is a namespace hint for an interrupted first setup; none is a legacy mirror.
        return {'library': next(iter(libraries), None), 'owner_id': '', 'owner': None}

    def _reconnect_eligibility(self, client, key, account, record, snap):
        """Advisory answer shown with the preview; reconnect() repeats every check."""
        try:
            self._reconnect_check(key, snap)
            self._reconnect_identity(client, key, account, record, list(snap['remote'].values()))
        except ReconnectRefused as e:
            return {'ok': False, 'reason': e.reason, 'message': str(e)}
        return {'ok': True, 'reason': 'eligible', 'message': ELIGIBLE}

    def _require_sync_off(self):
        upload, vault = self.sync.writer.read(lambda db: (db.get_setting('cloud_upload', ''), db.get_setting('cloud_vault', '')))
        if upload == 'on' or vault == 'on' or self.sync.running or self.sync.vault_running:
            raise ReconnectRefused('sync_on')

    def _same_owner(self, client, key, library, identity):
        """The uploader record is still the one resolved before the first write (or still absent)."""
        listing = client.list()
        owners = [f for f in listing if f['name'] == self.owner_name(library)]
        if not identity['owner_id']:
            if owners:
                raise R.RecoveryError(HANDOVER)
            return
        if len(owners) != 1 or owners[0]['id'] != identity['owner_id']:
            raise R.RecoveryError(HANDOVER)
        if self._owner(client, key, library, listing)[1] != identity['owner']:
            raise R.RecoveryError(HANDOVER)

    def reconnect(self, password, confirmation):
        """Keep this folder: install the recovered key for the library whose latest upload it matches.
        Writes only a protected backup, a new recovery setup, the uploader record, the key and recovery state."""
        if not password and not confirmation:
            password = confirmation = (self.session or {}).get('password', '')      # the one typed to find the backup (D3)
        if password != confirmation:
            raise R.RecoveryError('The recovery passphrases do not match.')
        R.password_bytes(password)
        # An activity record (F14): the progress and any failure stay readable after Settings closes. It holds the
        # mutation gate, so conflicting local cloud changes refuse at once as before.
        with self.activity('reconnect', 'Checking this library against Google Drive…'):
            self.reconnecting = True
            try:
                with self.lock:
                    self._idle()
                    session = self.session
                    if not session or self.job.get('state') != 'preview' or not (session.get('reconnect') or {}).get('ok'):
                        raise R.RecoveryError('Find your library in Drive again, then choose Reconnect this library.')
                    if session.get('stage') or session.get('target') or session.get('complete'):
                        raise ReconnectRefused('restore_started')
                    if self.sync._signin_thread and self.sync._signin_thread.is_alive():
                        raise R.RecoveryError('Google sign-in is still in progress. Finish or cancel it, then find your library again.')
                    self._require_sync_off()
                    # Drain license control before the publication lock; never join a worker while holding it.
                    self._stop_writers()
                    with self.sync._publishing:
                        return self._reconnect(session, password)
            finally:
                self.reconnecting = False

    @staticmethod
    def _interrupted(session):
        """After the first Drive write this preview is no longer proof: a retry needs a fresh one."""
        session['reconnect'] = {'ok': False, 'reason': 'interrupted', 'message': REFUSALS['interrupted']}

    def _reconnect(self, session, password):
        sync = self.sync
        sync.require_open()
        if sync._control_thread and sync._control_thread.is_alive():
            raise R.RecoveryError('Waiting for the current account check to finish. Retry shortly.')
        self._require_sync_off()
        key, snap = session['key'], session['snapshot']
        # Read-only token: a refresh stays in memory, so nothing is saved before the refusal checks pass.
        client = self._client(readonly=True)
        self.progress('Checking the Google account and that this folder matches the latest upload…')
        account = self._account(client)
        if account != session['account']:
            raise ReconnectRefused('account_changed')
        restore.unchanged(client, key, snap)
        self._reconnect_check(key, snap)
        identity = self._reconnect_identity(client, key, account, session['record'], client.list())
        # Everything above only read. The first write is a protected backup of what this PC holds now.
        previous_key = mirror.MirrorKey.load(sync.key_path, readonly=True)
        previous = self._load(readonly=True)
        private_storage.write(sync.cloud_dir / ('recovery-before-reconnect-' + secrets.token_hex(16) + '.json'),
                              R.dump({'key': previous_key.text() if previous_key else '', 'recovery': previous,
                                      'data': str(sync.data_dir)}))
        record, secret = R.create(key, password, account, library=identity['library'])
        library, generation, device = record['header']['library'], record['header']['generation'], secrets.token_hex(16)
        self.progress('Saving the new recovery setup and uploader record in Google Drive…')
        try:
            raw = R.dump(record)
            fid = client.upload(R.name(record), data=raw)
            readback = R.parse(restore.download(client, {'id': fid, 'size': len(raw)}, R.MAX_RECORD))
            if (readback != record or R.unlock(readback, password=password).master != key.master
                    or R.unlock(readback, secret=R.encode(secret)).master != key.master):
                raise R.RecoveryError(INTERRUPTED)
            if self._account(client) != account:
                raise R.RecoveryError(INTERRUPTED)
            restore.unchanged(client, key, snap)
            self._reconnect_check(key, snap)
            self._same_owner(client, key, library, identity)
            # Not a compare-and-swap: every other desktop copy must already be stopped (master plan, contract 5).
            self._write_owner(client, key, library, device, generation, identity['owner_id'])
            restore.unchanged(client, key, snap)
            _, owner = self._owner(client, key, library)
            if owner['device'] != device or owner['generation'] != generation:
                raise R.RecoveryError(HANDOVER)
        except Exception as e:
            # Drive may already have changed: never claim a rollback, never undo another PC's uploader record.
            self._interrupted(session)
            raise R.RecoveryError(HANDOVER if str(e) == HANDOVER else INTERRUPTED) from None
        self.progress('Keeping this folder with the recovered key…')
        try:
            key.save(sync.key_path)
            self._save({'record': record, 'secret': R.encode(secret), 'device': device, 'account': account,
                        'verified': False, 'verified_at': 0, 'enrolled': True})
        except Exception:
            self._interrupted(session)
            raise R.RecoveryError(INTERRUPTED_LOCAL) from None
        # No fallible work after the local commit: uploads, vault sync and license control stay stopped.
        self.session = None
        self.job = {'state': 'idle', 'done': 0, 'total': 0, 'error': '', 'destination': ''}
        sync._set(state='off', error='')
        return R.kit(record, R.encode(secret))


    def _stop_writers(self, from_sync=False):
        # Set stop flags first; never join a publisher while holding its publication lock. `from_sync`: the caller is the
        # sync thread between two exports, which is not a publisher right now.
        if (self.sync.running and not from_sync) or self.sync.vault_running:
            raise R.RecoveryError('Turn off library uploads and vault sync before changing recovery or restoring.')
        self.sync._control_stop.set()
        self.sync._control_wake.set()
        if self.sync._control_thread and self.sync._control_thread.is_alive():
            self.sync._control_thread.join(1)
            if self.sync._control_thread.is_alive():
                raise R.RecoveryError('Waiting for the current account check to finish. Retry shortly.')

    def start_restore(self, path):
        with self.lock:
            self._idle()
            self._stop_writers()
            if not self.session:
                raise R.RecoveryError('Preview the Drive library first.')
            forbidden = (self.sync.data_dir, self.sync.cloud_dir, app_paths.LOCAL)
            target = restore.destination(path, forbidden)
            session = self.session
            client = self._client()
            if self._account(client) != session['account']:
                raise R.RecoveryError('The Google account changed. Preview the library again.')
            stage = session.get('stage')
            # shortcut: staging resumes in this running session; persist job metadata before supporting resume after restart.
            if stage is None or session.get('target') != target or (Path(stage) / 'content_manager.db').exists():
                stage = target.parent / ('.brainamon-recovery-' + secrets.token_hex(16))
                session.update(stage=stage, target=target)
            self.cancel = threading.Event()
            client.stop = self.cancel
            self.job = {'state': 'restoring', 'done': 0, 'total': session['snapshot']['files'], 'error': '', 'destination': str(target)}
            def run():
                try:
                    def report(done, total):
                        with self.lock:
                            self.job.update(done=done, total=total)
                    result = restore.materialize(client, session['key'], session['snapshot'], stage, self.cancel, report)
                    if self.cancel.is_set():
                        raise R.RecoveryError('Recovery cancelled. Current library and Drive are unchanged.')
                    if target.exists():
                        raise R.RecoveryError('The destination appeared during recovery. Choose another new folder.')
                    Path(stage).rename(target)
                    with self.lock:
                        self.job.update(state='complete', result=result)
                        session['complete'] = True
                except Exception as e:
                    with self.lock:
                        # Fixed OS/network errors avoid disclosing local paths or token-bearing responses.
                        c = self.sync.classified(e)
                        named = isinstance(e, R.RecoveryError) or c['code'] in (cloud_errors.AUTH_EXPIRED, cloud_errors.OFFLINE,
                                                                                  cloud_errors.DRIVE_FULL, cloud_errors.RATE_LIMITED)
                        error = c['message'] if named else 'Recovery could not finish. Check Drive access and disk space, then retry. Your current library is unchanged.'
                        self.job.update(state='cancelled' if self.cancel.is_set() else 'error', error=error, code=c['code'], action=c['action'])
            self.thread = threading.Thread(target=run, name='cm-recovery', daemon=True)
            self.thread.start()
            return self.status()

    def activate(self):
        with self.lock:
            self._idle()
            self._stop_writers()
            s = self.session
            if not s or not s.get('complete'):
                raise R.RecoveryError('Finish restoring into a new folder first.')
            override = os.environ.get('CM_DATA_DIR')
            if override and Path(override).resolve() != s['target'].resolve():
                raise R.RecoveryError('CM_DATA_DIR overrides the library folder. Remove that launch override before activating the restored library.')
            client = self._client()
            if self._account(client) != s['account']:
                raise R.RecoveryError('The Google account changed. Preview again.')
            restore.unchanged(client, s['key'], s['snapshot'])
            record = {'key': s['key'].text(), 'target': str(s['target']), 'account': s['account'],
                      'snapshot_hash': s['snapshot']['hash'], 'snapshot_id': s['snapshot']['manifest_id'],
                      'snapshot_revision': s['snapshot']['revision'],
                      'kit': s['kit'], 'record': s['record'], 'stage': 'prepared', 'activation': secrets.token_hex(16),
                      'previous_key': (current.text() if (current := mirror.MirrorKey.load(self.sync.key_path)) else ''),
                      'previous_recovery': self._load(), 'previous_data': str(self.sync.data_dir)}
            if s.get('password') and s.get('record'):
                # The passphrase never reaches the journal: only records sealed with it. After the restart Make this PC the
                # backup PC uploads `takeover` without asking again; `removal` (a copy from before an unfinished removal of
                # phones) is the new key and its record for the removal that runs again (finding 2).
                library = s['record']['header']['library']
                sealed, secret = R.create(s['key'], s['password'], s['account'], library=library)
                record['takeover'] = {'record': sealed, 'secret': R.encode(secret)}
                if s.get('removal_unfinished'):
                    fresh = mirror.MirrorKey.generate()
                    sealed, secret = R.create(fresh, s['password'], s['account'], library=library)
                    record['removal'] = {'new': fresh.text(), 'record': sealed, 'secret': R.encode(secret)}
                s['password'] = ''
            private_storage.write(self.journal, R.dump(record))
            self.finish_activation()
            self.job.update(state='activated')
            return {'restart': True, 'destination': str(s['target'])}

    def finish_activation(self):
        try:
            j = R.parse(private_storage.read(self.journal))
        except FileNotFoundError:
            return
        if j.get('kind') == 'update':
            return self._finish_update(j)
        key = mirror.MirrorKey(R.decode(j['key'], 32))
        target = Path(j['target'])
        if not isinstance(j.get('activation'), str) or not re.fullmatch('[0-9a-f]{32}', j['activation']):
            raise R.RecoveryError('Recovery activation identity is damaged. Keep the recovery files.')
        for path in (target, *target.parents):
            if path.is_symlink() or path.is_junction():
                raise R.RecoveryError('Recovery activation cannot follow links or junctions.')
        if not target.is_absolute() or not (target / 'content_manager.db').is_file():
            raise R.RecoveryError('Recovery activation is incomplete. Keep both folders and retry activation.')
        # A durable journal precedes key/pointer changes and makes an interrupted commit retryable.
        previous = {'key': j.get('previous_key', ''), 'recovery': j.get('previous_recovery'), 'data': j.get('previous_data', '')}
        private_storage.write(self.sync.cloud_dir / ('recovery-before-' + j['activation'] + '.json'), R.dump(previous))
        key.save(self.sync.key_path)
        state = {'record': j['record'], 'secret': j['kit']['secret'] if j['kit'] else '',
                 'device': secrets.token_hex(16), 'account': j['account'], 'verified': False, 'verified_at': 0,
                 'restore_hash': j['snapshot_hash'], 'restore_id': j['snapshot_id'], 'restored': True,
                 'restore_revision': j['snapshot_revision'],
                 'target': str(target.resolve()),
                 **{k: j[k] for k in ('takeover', 'removal') if j.get(k)}}
        if not state['record']:
            # Legacy imports can restore immediately; recovery enrollment is required before publication.
            private_storage.write(self.sync.cloud_dir / 'recovery-legacy.json', R.dump({'restored': True, 'target': str(target.resolve())}))
            try:
                private_storage.remove(self.path)
            except FileNotFoundError:
                pass
        else:
            self._save(state)
        app_paths.set_data_dir(target)
        private_storage.remove(self.journal)
        return target

    def take_over(self, password, confirmation):
        """Make this restored library the backup PC. With no passphrase typed it uploads the record sealed at activation with the
        one used to find the backup (D3). A copy from before an unfinished removal of phones then removes them again
        (finding 2), so the lost phone stays out."""
        if password != confirmation:
            raise R.RecoveryError('The recovery passphrases do not match.')
        with self.lock, self.sync._publishing:
            self._idle()
            self._stop_writers()
            client, state = self._client(), self._load()
            if not state or not state.get('restored'):
                raise R.RecoveryError('Activate and restart the restored library before taking over uploads.')
            if state.get('target') != str(self.sync.data_dir.resolve()):
                raise R.RecoveryError('Quit and reopen Brainamon to load the restored library before taking over uploads.')
            if self._account(client) != state['account']:
                raise R.RecoveryError('Reconnect the restored library’s Google account.')
            key = mirror.MirrorKey.load(self.sync.key_path)
            current = restore.preview(client, key)
            if (current['hash'] != state['restore_hash'] or current['manifest_id'] != state['restore_id']
                    or current['revision'] != state['restore_revision']):
                raise R.RecoveryError('The original PC changed Drive after recovery. Restore a fresh copy before taking over uploads.')
            old_record = state['record']
            sealed = state.get('takeover') if not password else None
            if sealed:
                record, secret = sealed['record'], R.decode(sealed['secret'], 32)
            else:
                record, secret = R.create(key, password, state['account'], library=old_record['header']['library'])
            fid = client.upload(R.name(record), data=R.dump(record))
            readback = R.parse(restore.download(client, {'id': fid, 'size': len(R.dump(record))}, R.MAX_RECORD))
            if (readback != record or R.unlock(readback, secret=R.encode(secret)).master != key.master
                    or (password and R.unlock(readback, password=password).master != key.master)):
                raise R.RecoveryError('Replacement recovery setup could not be verified.')
            library, removal = record['header']['library'], state.get('removal')
            try:
                owner_file, _ = self._owner(client, key, library)
            except R.RecoveryError:
                # a copy from before a removal: the uploader record was sealed with the key that replaced this one
                owners = [f for f in client.list() if f['name'] == self.owner_name(library)]
                if not removal or len(owners) != 1:
                    raise
                owner_file = owners[0]
            self._write_owner(client, key, library, state['device'], record['header']['generation'], owner_file['id'])
            state.pop('takeover', None)
            state.pop('removal', None)
            state.update(record=record, secret=R.encode(secret), verified=False, verified_at=0, saved_at=0, restored=False, enrolled=True)
            self._save(state)
            kit = R.kit(record, state['secret'])
        if removal:
            self.sync.start_removal(removal)
        return kit

    # ── Update this folder (S9) ────────────────────────────────────────────
    # Another PC restored this library's backup with the same key (a temporary PC), became the backup PC and uploaded. This PC
    # downloads only what differs, switches to the newer library at the next start and becomes the backup PC again; the key
    # never changes, so phones, the passphrase and the recovery file keep working. Drive is only read until the claim.
    def update_preview(self):
        """Whether this folder can take the newer backup in place and what that costs (T14b, W4b). Reads only, here and in Drive."""
        with self.lock:
            try:
                self.update = self._update_check()
            except (R.RecoveryError, drive_client.DriveError, OSError, ValueError, RuntimeError, mirror.MirrorKeyError) as e:
                self._update = None
                self.update = {'eligible': False, 'reason': 'error', 'message': self.sync.classified(e)['message']}
            return self.status()

    def _update_check(self):
        sync = self.sync
        self._update = None

        def refuse(reason):
            return {'eligible': False, 'reason': reason, 'message': UPDATE_REFUSALS[reason]}
        state = self._load(readonly=True)
        if not state:
            return refuse('no_recovery')
        if state.get('restored'):
            return refuse('restored')
        rotation = sync._rotation(readonly=True)
        if self._optional(self.journal, readonly=True) or (rotation and rotation.get('stage') != 'complete'):
            return refuse('pending')
        key = mirror.MirrorKey.load(sync.key_path, readonly=True)
        epoch, last = sync.writer.read(lambda db: (db.get_setting('cloud_epoch', ''), int(db.get_setting('cloud_last_publish', '0') or 0)))
        if key is None or epoch != key.fingerprint or state['record']['header']['fingerprint'] != key.fingerprint:
            return refuse('other_key')
        client = self._client(readonly=True)
        account = self._account(client)
        if account != state['account']:
            return refuse('other_account')
        listing = client.list()
        try:
            snap = restore.preview(client, key, listing=listing)
            _, owner = self._owner(client, key, state['record']['header']['library'], listing)
        except restore.NoMirror:
            return refuse('other_key')
        except R.RecoveryError as e:
            if 'cannot be authenticated' in str(e) or 'missing or ambiguous' in str(e):
                return refuse('other_key')        # the uploader record is sealed with a key this PC does not hold
            raise
        if owner['device'] == state['device']:
            return refuse('is_owner')
        local, published = sync.local_files()
        diff = update_folder.difference(snap['manifest'], snap['remote'], local, published)
        self._update = {'snap': snap, 'diff': diff}
        return {'eligible': True, 'reason': 'eligible', 'message': '', 'bytes': diff['bytes'], 'files': diff['files'],
                'nothing': not diff['remote_changed'], 'local_changes': diff['local_changes'], 'published': snap['published'],
                'owner_at': int(owner.get('changed') or 0) * 1000, 'last_backup': last, 'account': account}

    def start_update(self):
        """Update this folder: saved as a task the sync thread runs (S3). When the other PC changed nothing, this PC becomes the
        backup PC at once, keeping its own later changes, with no download and no restart."""
        sync = self.sync
        with self.gate(), self.lock:
            self._idle()
            failed = sync.intents.find(intents.UPDATE)
            if failed and failed.get('error'):
                # Try again: the same task from its saved stage; the download keeps what it fetched and re-reads Drive itself
                self.update_cancel = threading.Event()
                sync.intents.update(intents.UPDATE, error='', code='')
                sync.ensure_running()
                return self.status()
            if not self._update:
                self.update = self._update_check()      # the page's check is gone (a Stop updating, a restart): check again
            u = self._update
            if not u:
                raise R.RecoveryError(self.update.get('message') or UPDATE_FIRST)
            snap, diff = u['snap'], u['diff']
            payload = {'manifest_id': snap['manifest_id'], 'hash': snap['hash'], 'published': snap['published'],
                       'bytes': diff['bytes'], 'files': diff['files'], 'local_changes': diff['local_changes']}
            if diff['remote_changed']:
                payload['stage'] = str(sync.data_dir.resolve().parent / (update_folder.STAGE_PREFIX + secrets.token_hex(16)))
            self.update_cancel = threading.Event()
            sync.intents.add(intents.UPDATE, payload)
            if not diff['remote_changed']:
                sync.intents.update(intents.UPDATE, stage='claim')
            self._update = None
        sync.ensure_running()
        return self.status()

    def run_update(self, it, stop):
        """On the sync thread: download what differs into staging (resumable), re-read the manifest until it holds still (at most
        3 rounds), build the newer database there, then wait for Restart now. A pause or a quit keeps what was downloaded;
        Stop updating removes the staging folder."""
        sync, cancel = self.sync, self.update_cancel
        stage = Path(it['payload']['stage'])

        def check():
            if cancel.is_set():
                raise update_folder.Cancelled()
            if stop.is_set() or sync._closing:
                raise ExportStopped()
        self.updating = True
        try:
            check()
            sync.intents.update(intents.UPDATE, stage='downloading')
            sync._set(done=0, total=0)
            state = self._load()
            key = mirror.MirrorKey.load(sync.key_path)
            client = self._client(readonly=True)
            client.stop = stop
            if not state or key is None or self._account(client) != state['account']:
                raise R.RecoveryError('The Google account or the library key changed. Nothing was changed; find your backup again.')
            update_folder.secure(stage)
            for _round in range(3):
                snap = restore.preview(client, key)
                local, published = sync.local_files()
                diff = update_folder.difference(snap['manifest'], snap['remote'], local, published)
                size = (sync.data_dir / 'content_manager.db').stat().st_size
                if shutil.disk_usage(stage).free < diff['bytes'] + 2 * size + 64 * 1024 ** 2:
                    raise R.RecoveryError('Not enough free disk space next to the library for the update.')
                update_folder.download(client, key, snap, diff['get'], stage, check,
                                       lambda n, of, b, total: sync._set(done=n, total=of, bytes_done=b, bytes_total=total))
                check()
                current = restore.preview(client, key)
                if current['hash'] == snap['hash'] and current['manifest_id'] == snap['manifest_id']:
                    break
            else:
                raise R.RecoveryError(UPDATE_UNSETTLED)
            sync.writer.read(lambda db: update_folder.copy_database(db.conn, stage / update_folder.DB_NAME))
            check()
            update_folder.build(stage, sync.data_dir, snap, diff, local)
            check()
            sync.intents.update(intents.UPDATE, stage='downloaded', payload={
                'manifest_id': snap['manifest_id'], 'hash': snap['hash'], 'published': snap['published'],
                'bytes': diff['bytes'], 'files': diff['files'], 'local_changes': diff['local_changes']})
            sync._set(done=0, total=0, error='')
        except update_folder.Cancelled:
            shutil.rmtree(stage, ignore_errors=True)
            sync.intents.finish(intents.UPDATE)
            sync._set(done=0, total=0)
        finally:
            self.updating = False

    def cancel_update(self):
        """Stop updating: the staging folder goes, this folder and Drive stay as they were. Not after Restart now prepared the switch."""
        it = self.sync.intents.find(intents.UPDATE)
        if it and it['stage'] == 'swap':
            raise R.RecoveryError('The switch to the newer library is prepared. Restart Brainamon to finish it.')
        self.update_cancel.set()
        if it and not self.updating:
            if it['payload'].get('stage'):
                shutil.rmtree(it['payload']['stage'], ignore_errors=True)
            self.sync.intents.finish(intents.UPDATE)
            self.sync._set(done=0, total=0)
        self._update = None
        return self.status()

    def update_activate(self):
        """Restart now: the newer backup must still be the one downloaded (else its new changes are fetched first); then the
        journal is written and the swap runs at the next start. Uploads stay off until then (the guard reads the journal)."""
        sync = self.sync
        with self.lock:
            it = sync.intents.find(intents.UPDATE)
            if not it or it['stage'] != 'downloaded':
                raise R.RecoveryError('The update is not downloaded yet.')
            p = it['payload']
            client = self._client(readonly=True)
            current = restore.preview(client, mirror.MirrorKey.load(sync.key_path))
            if current['hash'] != p['hash'] or current['manifest_id'] != p['manifest_id']:
                sync.intents.update(intents.UPDATE, stage='queued')
                sync.ensure_running()
                raise R.RecoveryError(UPDATE_AGAIN)
            data = sync.data_dir.resolve()
            private_storage.write(self.journal, R.dump({
                'kind': 'update', 'activation': secrets.token_hex(16), 'target': str(data), 'stage': p['stage'],
                'before': str(update_folder.before_folder(data)), 'step': 'prepared'}))
            sync.intents.update(intents.UPDATE, stage='swap')
            sync._emit()
            return {'restart': True, 'destination': str(data)}

    def _finish_update(self, j):
        """At the start (`finish_activation`): the swap, then the task waits for the claim on the first upload pass. A swap that
        fails before anything moved drops the journal and keeps this library as it was; a later one resumes at the next start."""
        target, stage, before = (Path(j.get(k) or '') for k in ('target', 'stage', 'before'))
        if (not isinstance(j.get('activation'), str) or not re.fullmatch('[0-9a-f]{32}', j['activation'])
                or j.get('step') not in ('prepared', 'copied', 'removed', 'moved', 'replaced', 'done') or not target.is_absolute()
                or stage.parent != target.parent or not stage.name.startswith(update_folder.STAGE_PREFIX)
                or before.parent != target or not before.name.startswith(update_folder.BEFORE_PREFIX)):
            raise R.RecoveryError('The update journal is damaged. Keep the library folder and its staging folder.')
        for path in (target, *target.parents):
            if path.is_symlink() or path.is_junction():
                raise R.RecoveryError('Update this folder cannot follow links or junctions.')
        tasks = intents.Intents(self.sync.cloud_dir / 'intents.json', os.path.normcase(str(target.resolve())))
        try:
            update_folder.swap(j, lambda value: private_storage.write(self.journal, R.dump(value)))
        except Exception as e:
            if j['step'] != 'prepared':
                raise
            private_storage.remove(self.journal)
            if tasks.find(intents.UPDATE):
                tasks.update(intents.UPDATE, stage='downloaded', error=f'The switch did not start: {e}', code='')
            return target
        if tasks.find(intents.UPDATE):
            tasks.update(intents.UPDATE, stage='claim')
        private_storage.remove(self.journal)
        return target

    def claim_update(self, it, stop):
        """After the switch, on the sync thread before anything uploads: if Drive still holds the backup this folder switched to,
        this PC becomes the backup PC again (the uploader record names it); the other PC stops when it next uploads. If the
        other PC backed up again meanwhile, nothing is claimed and Update this folder is offered again."""
        sync = self.sync
        with self.lock:
            if stop.is_set():
                raise ExportStopped()
            state = self._load()
            key = mirror.MirrorKey.load(sync.key_path)
            client = self._client()
            client.stop = stop
            if not state or key is None or self._account(client) != state['account']:
                raise R.RecoveryError('The Google account or the library key changed. Nothing was changed.')
            p = it['payload']
            listing = client.list()
            current = restore.preview(client, key, listing=listing)
            self.update, self._update = None, None
            if current['hash'] != p['hash'] or current['manifest_id'] != p['manifest_id']:
                sync.intents.finish(intents.UPDATE)
                from core import app_console
                app_console.emit('log', 'Drive mirror: the other PC backed up again after the update; Update this folder is offered again', level='warning')
                return
            library = state['record']['header']['library']
            if not any(f['name'] == R.name(state['record']) for f in listing):
                # a passphrase change there pruned this PC's setup (D5): put it back, so the uploader record names one that exists
                raw = R.dump(state['record'])
                fid = client.upload(R.name(state['record']), data=raw)
                if R.parse(restore.download(client, {'id': fid, 'size': len(raw)}, R.MAX_RECORD)) != state['record']:
                    raise R.RecoveryError('The recovery setup could not be verified in Google Drive. Retry.')
            owner_file, owner = self._owner(client, key, library, listing)
            if owner['device'] != state['device']:
                self._write_owner(client, key, library, state['device'], state['record']['header']['generation'], owner_file['id'])
            # only now: a claim that failed above stays a task with its reason, and Try again runs it once more
            sync.intents.finish(intents.UPDATE)
            sync._set(error='')

    def prepare_rotation(self, new_key, old_key, password, new_password=''):
        """Seal the replacement recovery records for a removal of phones. Local only: no Drive call, so the click works offline
        and the lock-out never waits for Drive (D1). With a new passphrase the current one is not needed (F7) and the new one
        also opens the old key until its copy is deleted (D2), so a PC lost mid-removal still has a way back. The records go up
        in `upload_replacement`, before the key switches."""
        state = self._load()
        if not state:
            return None
        self.progress('Checking your passphrase and protecting the replacement key…')
        if new_password:
            R.password_bytes(new_password)
        elif R.unlock(state['record'], password=password).fingerprint != state['record']['header']['fingerprint']:
            raise R.RecoveryError('The passphrase does not unlock the current recovery generation.')
        library = state['record']['header']['library']
        record, secret = R.create(new_key, new_password or password, state['account'], library=library)
        alongside = []
        if new_password:
            kit_secret = R.decode(state['secret'], 32) if state.get('secret') else None
            alongside.append(R.create(old_key, new_password, state['account'], library=library, kit_secret=kit_secret)[0])
        return {**state, 'record': record, 'secret': R.encode(secret), 'verified': False, 'verified_at': 0, 'saved_at': 0,
                'enrolled': False, 'alongside': alongside}

    def draft_replacement(self, draft):
        """The replacement setup of a removal that runs again after take-over (finding 2): sealed at activation."""
        state = self._load()
        if not state:
            return None
        return {**state, 'record': draft['record'], 'secret': draft['secret'], 'verified': False, 'verified_at': 0, 'saved_at': 0,
                'enrolled': False, 'alongside': []}

    def upload_replacement(self, client, state, new_key, old_key):
        """Put the replacement records in Drive and read each back, before the key switches (D1): a restore path exists the whole
        time. Idempotent: a record already in Drive is updated in place, never duplicated."""
        listing = client.list()
        for record in [state['record']] + list(state.get('alongside') or []):
            raw, name = R.dump(record), R.name(record)
            existing = [f['id'] for f in listing if f['name'] == name]
            fid = client.upload(name, data=raw, file_id=existing[0] if existing else '')
            if R.parse(restore.download(client, {'id': fid, 'size': len(raw)}, R.MAX_RECORD)) != record:
                raise R.RecoveryError('Replacement recovery records could not be verified; the library key was not replaced.')
        if R.unlock(state['record'], secret=state['secret']).master != new_key.master:
            raise R.RecoveryError('Replacement recovery records could not be verified; the library key was not replaced.')

    def commit_rotation(self, client, key, state):
        if state:
            library = state['record']['header']['library']
            matches = [f for f in client.list() if f['name'] == self.owner_name(library)]
            if len(matches) != 1:
                raise R.RecoveryError('Cannot commit recovery rotation while ownership is ambiguous.')
            self._write_owner(client, key, library, state['device'], state['record']['header']['generation'], matches[0]['id'])
            current = self._load()
            if current is None or current['record'] != state['record']:
                # a retry never takes back a recovery file the user already saved and checked
                state.pop('alongside', None)
                state.update(enrolled=True, replaced=True, replaced_at=int(time.time()))
                self._save(state)

    def resume_rotation(self, record, stop):
        """Repair an interrupted owner/state/key commit before normal ownership checks."""
        if not record or record.get('stage') not in ('publishing', 'cleanup') or not record.get('recovery'):
            return
        state = record['recovery']
        if stop.is_set():
            return
        old, new = (mirror.MirrorKey(R.decode(record[k], 32)) for k in ('old', 'new'))
        active = mirror.MirrorKey.load(self.sync.key_path)
        if active is None or active.fingerprint not in (old.fingerprint, new.fingerprint) or state['record']['header']['fingerprint'] != new.fingerprint:
            raise R.RecoveryError('Pending rotation does not match the local library master.')
        client = self._client()
        client.stop = stop
        if self._account(client) != state['account']:
            raise R.RecoveryError('Reconnect the rotation’s original Google account.')
        library = state['record']['header']['library']
        try:
            _, owner = self._owner(client, new, library)
        except R.RecoveryError:
            _, owner = self._owner(client, old, library)
        if owner['device'] != state['device']:
            raise R.RecoveryError('Another PC owns this library. Pending rotation is paused.')
        self.commit_rotation(client, new, state)
        new.save(self.sync.key_path)

    def prune(self, client, account, library, *, fingerprint, keep=()):
        """Delete this account's recovery records of `library` sealed to `fingerprint`'s key, except the names in `keep` (D5).
        Best effort after the commit point: a failure leaves a record that only confuses a restore, never data."""
        try:
            for header, record in self._records(client, account, client.list()):
                if header['library'] == library and header['fingerprint'] == fingerprint and R.name(record) not in keep:
                    client.delete(header['id'])
        except (R.RecoveryError, drive_client.DriveError, OSError) as e:
            from core import app_console
            app_console.emit('log', 'Drive recovery: an older recovery setup was not removed', level='warning', error=e)

    def prune_old_key(self, client, record):
        """A removal of phones is complete: every setup sealed to the old key opens nothing now (D5)."""
        state = record.get('recovery')
        if state:
            old = self.sync._rotation_key(record['old'])
            self.prune(client, state['account'], state['record']['header']['library'], fingerprint=old.fingerprint)

    def library_record_ids(self, client, listing, fingerprint):
        """Drive ids of the recovery records sealed to `fingerprint`'s key and of those libraries' uploader records: the part of
        an old copy that is not a mirror file (what Switch account and Reset backup delete with it)."""
        ids, libraries = set(), set()
        try:
            for header, _record in self._records(client, self._account(client), listing):
                if header['fingerprint'] == fingerprint:
                    ids.add(header['id'])
                    libraries.add(header['library'])
        except (R.RecoveryError, drive_client.DriveError, OSError) as e:
            from core import app_console
            app_console.emit('log', 'Drive recovery: the recovery records of the old copy could not be listed', level='warning', error=e)
        for library in libraries:
            ids |= {f['id'] for f in listing if f['name'] == self.owner_name(library)}
        return ids

    def archive_state(self, reason):
        """Recovery starts over (Reset backup): the setup stays in a protected backup beside the others, then is cleared."""
        state = self._load()
        if state:
            private_storage.write(self.sync.cloud_dir / f'recovery-before-{reason}-{int(time.time())}.json', R.dump(state))
            private_storage.remove(self.path)

    def shutdown(self):
        self.cancel.set()
        if self.thread:
            self.thread.join(5)
