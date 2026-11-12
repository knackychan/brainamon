"""Upload to Google Drive: the mirror service (projects/mobile-app/PLAN.md Phase 3).

Off by default. While the `cloud_upload` and `cloud_vault` settings are off there is no sync thread
and no content cloud calls; a paired, signed-in PC separately renews or locks
the license-control record. Settings > Cloud only reads local state.

On, one daemon thread (`cm-sync`) keeps the encrypted mirror in the app data folder of the user's
Google Drive in step with the library:
- it publishes when it starts and about a minute after a change (it polls a cheap signature of
  the library every POLL seconds, and jobs poke it when they finish);
- the library is read on the Writer (`Writer.read`: the export payload with mirror=True and the
  published state), never through a connection of its own; building, sealing and uploading run
  on this thread; the state of each uploaded file is saved back with `Writer.call` as it goes,
  so a first upload that is cut off resumes where it stopped;
- it is not a JobManager job, so it never blocks the one-job-at-a-time rule;
- every INTAKE seconds it looks for the phone's change files (Phase 4; each look that finds none
  doubles the wait up to INTAKE_MAX, a look that finds some or Publish now resets it), applies them on the Writer
  (server/intake.py), deletes eligible files, starts Fetch thumbnails on saved links, and republishes;
  owner-thread ticks also poll during upload waits and between deletions. Unsupported/invalid
  change envelopes stay in Drive and block later acknowledgements for their device;
  a synthesis the phone left for the PC (too many sources) starts as a Synthesize job when no
  other job runs (Phase 5).

The Obsidian vault sync (`cloud_vault`, projects/vault-sync) runs on a second thread (`cm-vault`) with
its own On / Off; both share one Google sign-in. Turn off uploads and Disconnect stop both.

Local files (the cloud folder, `app_paths.LOCAL / 'cloud'`, never in data/ or .env):
    google_token.json    the Google sign-in (refresh token)
    mirror.key           the mirror key (32 bytes, base64url); the phone gets it in the pairing QR
"""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from pathlib import Path, PureWindowsPath

from core import ai_client, ai_defaults, app_console, app_paths, config, private_storage, entitlements, sync_license
from library import drive_client, export, mirror, recovery, vault_sync
from library.export_targets import DriveMirrorTarget, ExportStopped
from server import cloud_errors, delivery, intake, intents
from server.cloud_errors import WorkerStopping      # raised here; the tests and routes read it as sync.WorkerStopping

POLL = 5                # seconds between two looks at the library
DEBOUNCE = 10           # a change is published this long after it was first seen
RETRY = 300             # after a failed publish (no network, Google down)
INTAKE = 15             # seconds between two looks for the phone's change files
INTAKE_MAX = 60         # ... stretched up to this while the phone sends nothing (a full listing each time)
INTAKE_FAILED = 'Phone changes not applied'
GRANT_MS = sync_license.LIFETIME * 1000     # a renewed phone-access record stays valid this long; a phone reads it on every
                                            # Drive call (web/src/mobile/mirror/drive.ts `authorize`) and compares its own clock
OLD_GRACE_MS = 60_000       # a removal whose click could not list Drive: old-key change files count if Drive stamped them this soon after
VERIFY_WORKERS = 8          # downloads in flight while checking a re-encrypted copy (deletes keep four)
VERIFY_BIG = 64 * 1024 * 1024   # a file over this size is held in memory whole while it is checked ...
VERIFY_BIG_AT_ONCE = 2          # ... so no more than this many of them are read at the same time
CONTROL_WAIT = 8           # seconds a Remove click waits for an access-record renewal already in flight



KEY_MISSING = ("This PC no longer has the key that opens this library's backup in Google Drive, so nothing was uploaded. "
               'Unlock the backup with your passphrase, recovery file or a phone code, or reset the backup.')
S_PAUSE_RESTORE = 'cloud_pause_restore'
S_PAUSED = 'cloud_paused_at'        # ms: when backup was paused; it stays paused until Resume (D14)
DISCONNECT_PREPARING = 'Preparing disconnect.'
PREVIOUS_TOKEN = 'google_token.previous.json'      # the old account's sign-in while its copy waits to be deleted (finding 7)


def _store_settings(db, values):
    with db.conn:
        for key, value in values.items():
            if value is None:
                db.conn.execute('DELETE FROM settings WHERE key = ?', (key,))
            else:
                db.conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))


TASKS = {      # kind: (title, step labels); `STEPS` below maps a persisted stage to the step it is in
    intents.REMOVE: ('Removing all phones', ['New key ready', 'Phones locked out', 'Re-encrypting', 'Checking the new copy', 'Deleting the old copy']),
    intents.ENROLL: ('Saving the recovery passphrase', ['Waiting for the current upload request', 'Saving the encrypted key', 'Reading it back']),
    intents.SWITCH: ('Switching Google account', ['Signing out', 'Signing in and backing up', 'Deleting the old copy']),
    intents.RESET: ('Resetting the backup', ['New key ready', 'Backing up again', 'Deleting the old backup']),
    intents.ONE_SHOT: ('Backing up once', ['Backing up']),
    intents.UPDATE: ('Updating this folder', ['Downloading what changed', 'Switching at the restart', 'Becoming the backup PC']),
    intents.DISCONNECT: ('Disconnecting Google Drive', ['Stopping current work', 'Deleting the backup if requested', 'Signing out']),
}
TASK_ERRORS = {cloud_errors.AUTH_EXPIRED: cloud_errors.EXPIRED, cloud_errors.OFFLINE: cloud_errors.OFFLINE_TEXT,
               cloud_errors.DRIVE_FULL: cloud_errors.FULL, cloud_errors.RATE_LIMITED: cloud_errors.RATE_TEXT,
               cloud_errors.LOCAL_STORAGE: cloud_errors.STORAGE_TEXT, cloud_errors.BUSY_CODE: cloud_errors.BUSY,
               cloud_errors.FOREIGN_BACKUP: cloud_errors.FOREIGN}
TASK_ERROR_CODES = {*TASK_ERRORS, cloud_errors.WRONG_ACCOUNT, cloud_errors.WORKER_STOPPING, cloud_errors.NOT_OWNER,
                    cloud_errors.OTHER, cloud_errors.OTHER_COPY}
RESUME_BLOCKERS = {cloud_errors.NOT_OWNER, cloud_errors.FOREIGN_BACKUP, cloud_errors.WRONG_ACCOUNT, cloud_errors.OTHER_COPY}

STEPS = {(intents.REMOVE, 'requested'): 3, (intents.REMOVE, 'prepared'): 3, (intents.REMOVE, 'publishing'): 3, (intents.REMOVE, 'cleanup'): 5,
         (intents.ENROLL, 'queued'): 1, (intents.ENROLL, 'uploading'): 2,
         (intents.SWITCH, 'queued'): 1, (intents.SWITCH, 'signing-in'): 2, (intents.SWITCH, 'cleanup'): 3,
         (intents.RESET, 'queued'): 1, (intents.RESET, 'backing-up'): 2, (intents.RESET, 'cleanup'): 3,
         (intents.ONE_SHOT, 'queued'): 1, (intents.ONE_SHOT, 'running'): 1,
         (intents.UPDATE, 'queued'): 1, (intents.UPDATE, 'downloading'): 1, (intents.UPDATE, 'downloaded'): 2,
         (intents.UPDATE, 'swap'): 2, (intents.UPDATE, 'claim'): 3,
         (intents.DISCONNECT, 'deleting'): 2, (intents.DISCONNECT, 'signing-out'): 3}


class ExportInterrupted(ExportStopped):
    """An intent wants the slot between upload requests: the export in progress ends with its state flushed and runs again
    after the intent (S3)."""


MIRROR_STOPPING = ('Finishing one upload request first (up to a minute). Try again after it ends; '
                   'uploads that were on start again by themselves.')
UNPAIR_STOPPING = 'Finishing one upload request first (up to a minute). Removing phones starts right after; you can close Settings.'
VAULT_STOPPING = 'Vault sync is still stopping. Retry after the outstanding request ends.'

S_ON, S_VIDEOS, S_CANVASES = 'cloud_upload', 'cloud_videos', 'cloud_canvases'
S_LAST, S_EPOCH, S_ACCOUNT = 'cloud_last_publish', 'cloud_epoch', 'cloud_account'
S_EXPIRED = 'cloud_token_expired'   # '1' once Google refused this PC's sign-in; cleared by a call that worked or a new sign-in (S1)
S_APPLIED = 'cloud_applied'     # {device: time of the latest change file applied}, into the manifest
S_ALIAS = 'cloud_uid_alias'     # {phone uid of a saved link: the library uid} when they differ (intake)
S_CANVAS_RESULTS = 'cloud_canvas_results'
S_ADOPT = 'cloud_epoch_next'    # the key Unpair made: the next publish replaces the mirror with it
def key_conflict_text(frozen: bool) -> str:
    """T15: the other copy is named and nothing points at a restore (A18). The installed app and the copy run from source share
    a data folder but each has its own key; uploads, phone changes and vault sync stay paused in the one that is not the author."""
    other = 'the copy run from source' if frozen else 'the installed app'
    return f'Another Brainamon on this PC ({other}) made this backup with a different key. Use that copy, or quit it before using this one.'


KEY_CONFLICT = key_conflict_text(app_paths.FROZEN)
ALIAS_KEEP = 500                # the latest ones; the phone's copy shows the PC's row long before
S_VAULT = 'cloud_vault'         # 'on': keep the Obsidian vault in step with the phone app (library/vault_sync.py)
VAULT_STATE = 'vault_base.json'
VAULT_EVERY = 30                # seconds between two vault rounds
ORPHAN_KEEP = 24 * 3600         # an unreferenced blob is deleted after this long
VAULT_STATUS_EVERY = 5          # seconds between two uploads of the round's progress for the phone
VAULT_UPLOAD_WORKERS = 12       # vault files sent to Drive at once (one request each; a first upload has thousands).
                                # Google's per-user quota is far above this; a 403/429 burst refusal is retried (drive_client)


def _load_vault_state(path: Path, fp: str) -> dict:
    """`fp`: the mirror key's fingerprint. Content ids are keyed, so a state kept under another key (Unpair,
    another copy's key) matches nothing: it is dropped and the round starts as a first sync (no deletions).
    `vault`: the identity the state was built for (spec 1b decision 4); `folder`: what the interim guard
    recorded before 1b (migrated by the next round); `vault_ids`: folder to the manifest identity last seen
    there (Reclaim reuses it), kept across keys. `devices` remembers membership and last known capability
    support independently of transient Drive list absence; only explicit Drop removes a member."""
    try:
        d = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        d = {}
    ids = d.get('vault_ids') if isinstance(d.get('vault_ids'), dict) else {}
    if d.get('fp') != fp:
        d = {}
    return {'fp': fp, 'bases': d.get('bases') or {}, 'cache': d.get('cache') or {},
            'orphans': d.get('orphans') or {}, 'index_sig': d.get('index_sig') or '',
            'vault': str(d.get('vault') or ''), 'folder': str(d.get('folder') or ''), 'vault_ids': ids,
            'devices': d.get('devices') or {device: False for device in (d.get('bases') or {})}}


def _save_vault_state(path: Path, st: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(st), encoding='utf-8')
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.1 * (attempt + 1))


def _folder_key(folder) -> str:
    return str(Path(folder).resolve()).replace('\\', '/').lower()


def recorded_vault_id(cloud_dir, folder) -> str:
    """The manifest identity (vault_id) vault sync last saw in `folder`, '' when none (spec 1b decision 4:
    Reclaim reuses it so the phones' sync history stays valid). Read-only; the map thread calls it."""
    try:
        d = json.loads((Path(cloud_dir) / VAULT_STATE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    ids = d.get('vault_ids') if isinstance(d.get('vault_ids'), dict) else {}
    return str(ids.get(_folder_key(folder)) or '')


def read_options(db) -> mirror.Options:
    v = db.get_setting(S_VIDEOS, 'fav')
    return mirror.Options(videos=v if v in mirror.VIDEO_MODES else 'fav',
                          canvases=db.get_setting(S_CANVASES, 'on') != 'off')


def _signature(db) -> tuple:
    """Changes whenever something the mirror carries changes in the DB."""
    c = db.conn
    items = tuple(c.execute("SELECT COUNT(*), COALESCE(MAX(modified), 0), COALESCE(SUM(favourite), 0) FROM items").fetchone())
    cats = tuple(tuple(r) for r in c.execute("SELECT name, color FROM categories ORDER BY name"))
    vec = tuple(c.execute("SELECT COUNT(*), COALESCE(MAX(updated), 0) FROM item_embeddings WHERE model = ?",
                          (ai_client.EMBEDDING_MODEL,)).fetchone())
    return items, cats, vec, (db.get_setting(S_VIDEOS, 'fav'), db.get_setting(S_CANVASES, 'on')), db.get_setting(delivery.RECEIPTS, '{}')


def _files_stamp(data_dir: Path) -> tuple:
    out = []
    for sub in ('notes', 'ask_chats', 'canvases', 'canvases/uploads'):
        d = data_dir / sub
        try:
            out.append(tuple(sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in d.iterdir() if e.is_file())))
        except OSError:
            out.append(())
    return tuple(out)



def deep_rows(db) -> dict:
    """What Wiskit Deep on the phone needs from the database (projects/mobile-app/plans/07-wiskit-deep.md):
    the websites and tools index and the stored topic and note-section vectors, for library/mirror.py
    (search/deep.json.gz, search/aux.bin). Read on the Writer with the rest of the payload."""
    return {'model': ai_client.EMBEDDING_MODEL, 'resources': db.all_resources(),
            'aux': db.get_aux_embeddings(ai_client.EMBEDDING_MODEL)}


def _payload(db) -> dict:
    """On the Writer: what the mirror is built from (export.build_export_payload plus the phone's settings)."""
    delivery.recover(db)                    # never export files left by an uncommitted phone batch
    payload = export.build_export_payload(db, None, export.collect_thumb_sources(db), mirror=True,
                                          vectors_model=ai_client.EMBEDDING_MODEL)
    payload['applied'] = _applied(db)
    payload['canvas_results'] = _applied(db, S_CANVAS_RESULTS)
    payload['receipts'] = delivery.receipts(db)
    payload['topic_notes'] = sorted({t['note_path'] for t in db.list_topics() if t.get('note_path')})
    payload['ai'] = ai_client.phone_settings(*ai_defaults.get(db, ai_defaults.SYNTHESIZE),
                                             found=ai_defaults.found_models(db))
    payload['deep'] = deep_rows(db)
    vault = db.get_setting('obsidian_vault', '') or ''        # the phone's Open in Obsidian default
    payload['obsidian_vault'] = PureWindowsPath(vault).name if vault else ''
    # the notes' folder inside that vault (spec 2026-10-28 decision 9): the owner layout, or the classic export's
    payload['obsidian_notes'] = 'Brainamon/Notes/' if db.get_setting('obsidian_mode', '') == 'owner' else 'Content Manager/notes/'
    return payload


def _hm(ms: int) -> str:
    """'15:05': a time of day on this PC's clock, for the phone-lock line."""
    return time.strftime('%H:%M', time.localtime(ms / 1000))


def _drive_ms(stamp) -> int | None:
    """Drive's RFC 3339 `modifiedTime` ('2026-10-31T09:30:00.000Z') in ms, or None when there is none."""
    try:
        return int(datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        return None


class _GuardedClient:
    def __init__(self, service, client, recovery=False, phone=False):
        self.service, self.client = service, client
        self.recovery, self.phone = recovery, phone
        self._guard_lock = threading.RLock()
        self._guard_cache, self._guard_until = None, 0.0
        self._guard_flight = None

    @property
    def stop(self):
        return self.client.stop

    @stop.setter
    def stop(self, value):
        self.client.stop = value

    def __getattr__(self, name):
        method = getattr(self.client, name)
        def call(*args, **kwargs):
            self.service.require_open()
            if self.phone:
                self.service.require_license()
            if name in ('upload', 'delete', 'delete_many') and not self.recovery:
                remote_name = (args[0] if args else kwargs.get('name', '')) if name == 'upload' else ''
                file_id = args[3] if len(args) > 3 else kwargs.get('file_id', '')
                cached = (name == 'upload' and
                          (remote_name.startswith(vault_sync.STATUS_PREFIX) or
                           (remote_name.startswith(vault_sync.BLOB_PREFIX) and not file_id)))
                self.service.recovery.guard(self, cached=cached)
            return method(*args, **kwargs)
        return call


class SyncService:
    def __init__(self, writer, hub, data_dir: Path, cloud_dir: Path, tints=None, client_factory=None,
                 sign_in=None, on_new_links=None, on_synth=None):
        self.writer, self.hub = writer, hub
        self.data_dir, self.cloud_dir = Path(data_dir), Path(cloud_dir)
        self.token_path = self.cloud_dir / 'google_token.json'
        self.previous_token_path = self.cloud_dir / PREVIOUS_TOKEN
        self.intents = intents.Intents(self.cloud_dir / 'intents.json', os.path.normcase(str(self.data_dir.resolve())))
        self.key_path = self.cloud_dir / 'mirror.key'
        self.control_key_path = self.cloud_dir / 'license-control.pem'
        self.tints = tints or (lambda: {})
        self._raw_factory = client_factory or self._client
        self._factory = lambda tok, recovery=False, phone=False: _GuardedClient(self, self._raw_factory(tok), recovery, phone)
        self.license_lock = getattr(writer, 'phone_license_lock', threading.RLock())
        self._closing = False
        self._control_stop = threading.Event()
        self._control_wake = threading.Event()
        self._control_thread = None
        self._sign_in = sign_in or drive_client.sign_in
        self._lock = threading.Lock()
        self._pause_control = threading.RLock()
        self._resume_check_stop = None
        self._paused_task = None
        self._failed_task = None
        self._pair_cache = None
        self._pair_identity = None
        self._pair_identity_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()      # this run's: start() makes a new one, so a thread that outlived shutdown() stays stopped
        self._life = threading.Lock()       # start() and a worker's last step: which thread is current, whether one follows
        self._resume = False                # start() found the old worker still stopping: it starts the next one as it exits (I4)
        self._oneshot = False               # the thread runs for an intent or a pending removal only: backup itself is off (D4)
        self._vault_resume = False          # the same for the vault thread
        self._publishing = threading.Lock() # one publish at a time, even across an old thread and a new one
        self._wake = threading.Event()
        self._force = False
        self._force_manifest = False
        self._published_receipts: dict | None = None  # the snapshot last sent successfully by this service
        self._published_skipped: dict | None = None   # the files left out of the manifest last sent by this service (None: none sent yet; that first manifest is forced anyway)
        self._account_read = False      # the account name is read from Google once per server run
        self._look_now = False          # Publish now: look for the phone's changes at once too
        self._next_intake, self._gap = 0.0, INTAKE
        self._vault_now = False
        self._vault_thread: threading.Thread | None = None     # the vault rounds: their own thread, see _vault_loop
        self._vault_stop = threading.Event()    # like _stop, for the vault thread: it has its own On / Off
        self._vault_wake = threading.Event()
        self._vault_tls = threading.local()     # the running vault thread's stop flag (_vault_stopped)
        self._vault_force = False       # "Apply anyway": lets the next round through the deletion brake
        self.on_new_links = on_new_links or (lambda ids: True)     # True: the thumbnail job took them
        self._thumbs: list[int] = []
        self._held: dict[str, tuple[str | None, int, str]] = {}
        self._held_context = None
        self._ignored: set[str] = set()     # old-key change files left alone while phones are being removed (I6)
        self._unreadable: set[str] = set()  # change files this run could not open with the key: downloaded once per (session, key) (A17)
        self._phone_cache: dict[str, tuple] = {}    # Drive id -> ((modifiedTime, size), the phone's record or None): D13 reads each record once
        self._control_lock = threading.Lock()   # one pass at a time on the phone-access record: its renewal, or the lock-out
        self._rotation_lock = threading.RLock() # read-modify-write of rotation.json from the Remove click and the control thread
        self._grant = ('', 0)               # (key fingerprint, expiry in ms) of the access record this run renewed last
        self._checking_copy = False         # `_rotation_finish` is checking the new copy: the Remove task is in its step 4, library and vault
        self.on_synth =on_synth or (lambda topic, ids: True)       # True: the Synthesize job took it
        self._generation = 0
        self._signin_cancel: threading.Event | None = None
        self._signin_thread: threading.Thread | None = None
        self._after_sign_in: set[str] = set()   # what Connect turns on once Google answers: 'mirror', 'vault'
        # seq: bumped by every change, so the page can drop an answer older than the last `cloud` event
        self.st = {'seq': 0, 'recovery_gate_active': False, 'on': False, 'vault': {'on': False, 'folder': ''}, 'state': 'off', 'done': 0, 'total': 0, 'bytes_done': 0, 'bytes_total': 0, 'items_done': 0, 'items_total': 0,
                   'error': '', 'error_code': '', 'error_action': '',
                   'error_at': 0,              # ms: when the other PC became the backup PC (not_owner) or made its backup (foreign_backup)
                   'error_account': '',        # the Google account a discarded sign-in used (wrong_account): the page offers Switch to it
                   'files': 0, 'size': 0,
                   'skipped': 0, 'skipped_note': '',   # files the last publish left out because recovery would refuse their size (library/mirror.py too_big), and the card's sentence about them
                   'last_publish': 0, 'last_summary': '', 'account': '', 'used': 0, 'limit': 0,
                   'last_intake': 0, 'intake_summary': '',
                   'phones': None,             # D13: [{device, name, seen}] from the phones' own records; None until one look read them
                   'rotation_clicked': 0, 'rotation_locked_at': 0, 'rotation_locked_by': 0, 'rotation_lock': '',
                   'ignored_changes': 0,       # old-key change files not applied since the Remove click (I6)
                   'paused_since': 0,          # ms; backup paused by the user and waiting for Resume (D14)
                   'key_missing': False,       # the library was backed up before but this PC has no key (reinstall, D9)
                   'token_expired': False,     # Google stopped accepting this PC's sign-in: the token file stays, Sign in again renews it (S1)
                   'vault_state': 'off', 'vault_reason': '', 'vault_summary': '', 'vault_last': 0,
                   'vault_skipped': 0, 'vault_skipped_note': '',   # files the last round left out for their size (library/vault_sync.py MAX_FILE), and the sentence about them
                   'vault_step': '', 'vault_done': 0, 'vault_total': 0, 'vault_since': 0,
                   'vault_devices': None,      # spec 1b: [{device, ok}] after a complete phone check
                   'vault_members': []}       # remembered phones remain droppable during an incomplete check
        self._vault_status_id, self._vault_status_at = '', 0.0
        from server.recovery import RecoveryService
        self.recovery = RecoveryService(self)
        self.intents.on_change = lambda: self._set()

    # ── what the Settings window reads ──────────────────────────────────────
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def vault_running(self) -> bool:
        return bool(self._vault_thread and self._vault_thread.is_alive())

    def signed_in(self) -> bool:
        """A token file exists. Whether Google still accepts it is `st['token_expired']` (S1)."""
        return drive_client.load_token(self.token_path, readonly=True) is not None

    def _token_view(self) -> dict:
        """What the page reads about the sign-in: a token exists, and when the user last signed in (seconds, 0 for a
        token saved before this was recorded)."""
        tok = drive_client.load_token(self.token_path, readonly=True)
        return {'signed_in': tok is not None, 'token_issued': float(tok.get('signed_in_at') or 0) if tok else 0}

    def status(self) -> dict:
        with self.intents._lock:
            items = self.intents.all()
            task = self._task_view(items)
            tasks = []
            for it in items:
                error, code = it.get('error', ''), it.get('code', '')
                if code not in TASK_ERROR_CODES:
                    code = cloud_errors.OTHER if error else ''
                tasks.append({'id': it['id'], 'kind': it['kind'], 'title': TASKS[it['kind']][0], 'stage': it['stage'],
                              'error': TASK_ERRORS.get(code, 'This task needs attention. Open it for details.') if error else '', 'code': code})
            with self._lock:
                snap = dict(self.st)
        return dict(snap, licensed=entitlements.feature_enabled('phone_sync'), running=self.running, vault_running=self.vault_running,
                    **self._token_view(), configured=bool(config.google_client()[0]), task=task, tasks=tasks,
                    pair_ready=self._pair_ready(snap, items))

    def _pair_ready(self, snap, items) -> bool:
        if self._closing or snap['recovery_gate_active'] or self._pair_identity is None or not entitlements.feature_enabled('phone_sync'):
            return False
        try:
            def stamp(path):
                try:
                    st = path.stat()
                    return st.st_ino, st.st_mtime_ns, st.st_size
                except FileNotFoundError:
                    return None
            paths = (self.cloud_dir / 'rotation.json', self.key_path, self.control_key_path)
            signature = (snap['key_missing'], self._pair_identity, tuple((it['kind'], it['payload'].get('new')) for it in items),
                         tuple((stamp(path), stamp(private_storage.location(path))) for path in paths))
            if self._pair_cache and self._pair_cache[0] == signature:
                return self._pair_cache[1]
            try:
                signer = private_storage.read(self.control_key_path, readonly=True)
            except FileNotFoundError:
                signer = None
            if signer is not None:
                from cryptography.hazmat.primitives import serialization
                serialization.load_pem_private_key(signer, password=None)
            rotation = self._rotation(readonly=True)
            if rotation and rotation.get('stage') != 'complete':
                key = self._rotation_key(rotation['new'])
                ready = any(it['kind'] == intents.REMOVE and it['payload'].get('new') == key.fingerprint for it in items)
            elif snap['key_missing']:
                ready = False
            else:
                key = mirror.MirrorKey.load(self.key_path, readonly=True)
                epoch, adopt = self._pair_identity
                if epoch and (not key or key.fingerprint not in (epoch, adopt)):
                    self._pair_cache = signature, False
                    return False
                ready = True
            self._pair_cache = signature, ready
            return ready
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, mirror.MirrorKeyError):
            return False

    def _write_identity(self, fn):
        with self._pair_identity_lock:
            self._pair_identity = None
            def write(db):
                result = fn(db)
                return result, db.get_setting(S_EPOCH, '') or '', db.get_setting(S_ADOPT, '') or ''
            result, epoch, adopt = self.writer.call(write)
            self._pair_identity = epoch, adopt
            return result

    def refresh_vault_folder(self) -> None:
        with self._pause_control:
            folder = self.writer.read(lambda db: db.get_setting('obsidian_vault', '') or '')
            if folder != self.st['vault']['folder']:
                self._set(vault={**self.st['vault'], 'folder': folder})

    def _task_view(self, items=None):
        task = self._live_task_view(items)
        saved = self._paused_task
        if self.st['paused_since'] and task:
            if saved and (saved['id'], saved['stage']) == (task['id'], task['stage']):
                return {**saved, 'error': task['error'], 'code': task['code'], 'paused_snapshot': True}
            self._paused_task = None
            return {**task, 'done': 0, 'total': 0, 'bytes_done': 0, 'bytes_total': 0, 'items_done': 0, 'items_total': 0,
                    'uploaded_items': None, 'uploaded_items_total': None, 'uploaded_files': None}
        if not task:
            self._paused_task = None
        failed = self._failed_task
        if failed and (not task or (failed['id'], failed['stage']) != (task['id'], task['stage'])):
            self._failed_task = failed = None
        if failed and self.st['state'] == 'error':
            return {**failed, 'error': task['error'], 'code': task['code']}
        return task

    def _live_task_view(self, items=None):
        """The long task the page shows as one card (S3): its saved stage, the step that stage is in and the live counts (files and
        bytes, S7). Everything comes from the intent's persisted stage, so a restart shows the same step."""
        if items is None:
            items = self.intents.all()
        if not items:
            return None
        it = items[0]
        activity = self.st.get('recovery_activity') or {}
        if activity.get('action') == 'enroll' and activity.get('state') == 'running':
            it = next((item for item in items if item['kind'] == intents.ENROLL), it)
        title, labels = TASKS[it['kind']]
        step = STEPS.get((it['kind'], it['stage']), 1)
        if it['kind'] == intents.REMOVE and self._checking_copy:
            step = 4        # the whole check: the library's files, then the Obsidian vault's upload and read-back
        vault = step == 4 and it['kind'] == intents.REMOVE and self.st.get('vault_state') == 'syncing' and self.st.get('vault_total', 0) > 0
        steps = [{'label': label, 'state': 'done' if n < step else 'active' if n == step else 'waiting'} for n, label in enumerate(labels, 1)]
        task = {'id': it['id'], 'kind': it['kind'], 'stage': it['stage'], 'title': title, 'step': step, 'of': len(labels), 'steps': steps,
                'done': self.st.get('vault_done' if vault else 'done', 0), 'total': self.st.get('vault_total' if vault else 'total', 0),
                'bytes_done': 0 if vault else self.st.get('bytes_done', 0), 'bytes_total': 0 if vault else self.st.get('bytes_total', 0), 'since': it['created'],
                'items_done': self.st.get('items_done', 0), 'items_total': self.st.get('items_total', 0),
                'uploaded_items': it['payload'].get('uploaded_items'), 'uploaded_items_total': it['payload'].get('uploaded_items_total'), 'uploaded_files': it['payload'].get('uploaded_files'),
                'error': it.get('error', ''), 'code': it.get('code', ''), 'lock': self.st.get('rotation_lock', '') if it['kind'] == intents.REMOVE else ''}
        if it['kind'] == intents.ENROLL or it['kind'] == intents.DISCONNECT and it.get('error') == DISCONNECT_PREPARING:
            task.update(done=0, total=0, bytes_done=0, bytes_total=0, items_done=0, items_total=0)
        return task

    def _set(self, emit: bool = True, **kw) -> None:
        if 'error' in kw and 'error_code' not in kw:
            kw['error_code'] = kw['error_action'] = ''      # a plain message has no code: only a classified failure sets one (I7)
        if 'error' in kw:
            kw.setdefault('error_at', 0)
            kw.setdefault('error_account', '')
        if ('done' in kw or 'total' in kw) and 'bytes_done' not in kw:
            kw['bytes_done'] = kw['bytes_total'] = 0        # a count of files without bytes (S7): the bar shows files only
        with self._lock:
            self.st.update(kw)
            self.st['seq'] += 1
        if emit:
            self._emit()

    def classified(self, exc: BaseException, fallback: str = '', storage: str = '') -> dict:
        """`cloud_errors.classify` with this service's account and Drive quota: {'code', 'message', 'action'}.
        Classifying an expired sign-in also records it (S1), so every route, thread and activity that meets one marks it
        the same way and a restart still knows."""
        with self._lock:
            account, used, limit = self.st.get('account', ''), self.st.get('used', 0), self.st.get('limit', 0)
        c = cloud_errors.classify(exc, account=account, used=used, limit=limit, fallback=fallback, storage=storage)
        if c['code'] == cloud_errors.AUTH_EXPIRED:
            self._mark_expired()
        return c

    def _mark_expired(self) -> None:
        if self.st.get('token_expired') or not self.signed_in():
            return
        self._set(token_expired=True)
        try:
            self.writer.call(lambda db: db.set_setting(S_EXPIRED, '1'))
        except Exception as e:      # the Writer is shutting down: the mark is still in memory for this run
            app_console.emit('log', 'Drive mirror: could not remember the expired sign-in', level='warning', error=e)

    def _clear_expired(self) -> None:
        """A call with this sign-in worked, or a new one was saved: Google accepts it."""
        if not self.st.get('token_expired'):
            return
        self._set(token_expired=False)
        try:
            self.writer.call(lambda db: db.set_setting(S_EXPIRED, ''))
        except Exception as e:
            app_console.emit('log', 'Drive mirror: could not clear the expired sign-in', level='warning', error=e)

    def _emit(self) -> None:
        """The `cloud` SSE snapshot: the latest state, whichever thread changed it last."""
        self.hub.publish('cloud', self.status())

    # ── lifecycle ───────────────────────────────────────────────────────────
    def require_open(self):
        if self._closing:
            raise drive_client.DriveError('Cloud work is stopping.')

    def require_license(self):
        if self._closing:
            raise drive_client.DriveError('Cloud work is stopping.')
        if not entitlements.feature_enabled('phone_sync'):
            raise drive_client.DriveError('license_required')

    def _licensed_call(self, fn):
        def run(db):
            with self.license_lock:
                self.require_license()
                return fn(db)
        return self.writer.call(run)

    def _start_control(self):
        if any(i['kind'] == intents.DISCONNECT or i['kind'] in (intents.RESET, intents.SWITCH) and i['stage'] == 'queued' for i in self.intents.all()):
            return
        # Hold the reconnect gate until the thread exists: reconnect either sees it and drains it, or it never starts.
        try:
            with self.recovery.gate():
                state = self.recovery._load()
                if state and state.get('restored'):
                    return
                if self._closing or self.recovery.reconnecting or not self.signed_in() or not self.key_path.exists():
                    return
                if self._control_stop.is_set():
                    if self._control_thread and self._control_thread.is_alive():
                        return
                    self._control_stop = threading.Event()
                if not self._control_thread or not self._control_thread.is_alive():
                    self._control_thread = threading.Thread(target=self._control_loop, name='cm-license-control', daemon=True)
                    self._control_thread.start()
                self._control_wake.set()
        except cloud_errors.Busy:
            return

    def _start_control_after_accept(self):
        try:
            self._start_control()
        except Exception:
            app_console.emit('log', 'Phone access checks could not start after the saved change.', level='warning')
            try:
                self._set(error='Phone access checks could not start. Restart Brainamon to try again.',
                          error_code=cloud_errors.OTHER, error_action=cloud_errors.NONE)
            except Exception:
                pass

    def _control_loop(self):
        last, renew = None, 0
        while not self._control_stop.is_set():
            try:
                current = entitlements.feature_enabled('phone_sync')
                if current != last or current and time.monotonic() >= renew:
                    self.publish_license_control()
                    last, renew = current, time.monotonic() + 300
            except (OSError, ValueError, RuntimeError, mirror.MirrorKeyError, drive_client.DriveError) as e:
                # Retry the phone access control record independently of backups. A sign-in Google no longer accepts is
                # recorded here too (S1): phones pause within the hour, and the page says so.
                if isinstance(e, drive_client.DriveError):
                    self.classified(e)
            if self._control_wake.wait(60):
                renew = 0
            self._control_wake.clear()

    def publish_license_control(self):
        """Renew or lock phone access independently of desktop backups. While phones are being removed the old key's
        record is deleted and never renewed (I6): the record that is renewed is the new key's, so a phone added again
        later finds it."""
        with self._control_lock:
            rotation = self._rotation()
            pending = rotation if rotation and rotation['stage'] != 'complete' else None
            tok = drive_client.load_token(self.token_path)
            key = self._rotation_key(pending['new']) if pending else mirror.MirrorKey.load(self.key_path)
            private = sync_license.signer(self.control_key_path)
            if tok is None or key is None or private is None:
                return
            client = self._raw_factory(tok)
            client.stop = self._control_stop
            if self.recovery._load():
                self.recovery.guard(client)
            listing = client.list()
            if pending and pending.get('lock_pending', True):       # also a removal begun before the lock was recorded
                self._lock_out(client, pending, listing)
            with self.license_lock:
                grant = sync_license.access_record(key, private)
                controls = [(sync_license.ACCESS_LOGICAL, grant), (sync_license.LOGICAL, sync_license.record(key, private))]
            for logical, raw in controls:
                name = key.name(logical)
                files = [f for f in listing if f['name'] == name]
                client.upload(name, data=key.seal(logical, raw), file_id=files[0]['id'] if files else '')
                expires = int(json.loads(json.loads(raw)['body'])['expires']) * 1000
                fp, previous = self._grant
                self._grant = (key.fingerprint, max(previous if fp == key.fingerprint else 0, expires))
                self._clear_expired()   # each successful renewal counts even if the other protocol's upload fails

    @staticmethod
    def _rotation_key(text: str) -> mirror.MirrorKey:
        return mirror.MirrorKey(base64.urlsafe_b64decode(text + '='))

    def _lock_out(self, client, rotation, listing) -> None:
        """Delete the old key's phone-access record (I6). A phone reads it on every Drive call, so it stops at that call;
        a phone that cannot reach Drive keeps the grant it already holds, which ends by itself (GRANT_MS after the last
        renewal)."""
        self._check_expected_account(rotation.get('expected_account'), client)
        key = self._rotation_key(rotation['old'])
        names = {key.name(path) for path in sync_license.CONTROL_LOGICALS}
        for f in listing:
            if f['name'] in names:
                client.delete(f['id'])
        record = self._update_rotation(rotation['new'], lock_pending=False, locked_at=int(time.time() * 1000))
        self._lock_status(record)

    def _lock_out_now(self, rotation, fresh: bool) -> None:
        """At the Remove click: list Drive once, remember which old-key change files are already there (they are the
        only ones trusted later), delete the old access record. Bounded and best effort: offline, signed out or refused,
        `lock_pending` stays and the control thread retries (`publish_license_control`)."""
        if not self._control_lock.acquire(timeout=CONTROL_WAIT):
            return          # a renewal is in flight; the next pass of the control thread sees the pending removal
        try:
            tok = drive_client.load_token(self.token_path)
            if tok is None:
                return
            client = self._raw_factory(tok)
            if isinstance(client, drive_client.DriveClient):
                client.attempts, client.request_timeout = 2, 10      # a click does not wait out the full backoff
            if self.recovery._load():
                self.recovery.guard(client)
            listing = client.list()
            if fresh:
                self._update_rotation(rotation['new'], old_changes=[f['id'] for f in listing if mirror.is_change(f.get('name', ''))])
            self._lock_out(client, rotation, listing)
            if fresh and rotation.get('recovery') and not rotation.get('sent'):
                # Online at the click: the replacement records go up now, so a restore path with the passphrase exists from the first
                # moment (D1, D2). Offline, or on any failure, the sync thread does it before the key switch.
                self.recovery.upload_replacement(client, rotation['recovery'], self._rotation_key(rotation['new']),
                                                 self._rotation_key(rotation['old']))
                self._update_rotation(rotation['new'], sent=True)
        except Exception as e:
            app_console.emit('log', 'Drive mirror: phone access not removed yet; retrying', level='warning', error=e)
        finally:
            self._control_lock.release()

    def _grant_bound(self, old: mirror.MirrorKey, clicked: int) -> int:
        """The latest moment (ms) a phone that cannot reach Drive can still use the old key's access record: the expiry
        of the last record this run renewed for it, else one grant's lifetime after the click (a renewal is never later
        than the click)."""
        bound = clicked + GRANT_MS
        fp, expires = self._grant
        return max(clicked, min(expires, bound)) if fp == old.fingerprint and expires else bound

    def _lock_status(self, record) -> None:
        """What the page shows about the lock-out: clicked, locked at (0 until the old record is gone), locked by."""
        if not record or not record.get('clicked'):
            return
        locked_at = int(record.get('locked_at') or 0)
        line = (f'Phones locked out at {_hm(locked_at)}.' if locked_at else
                f'Locked out by {_hm(record["locked_by"])} at the latest: this PC stopped renewing their access')
        self._set(rotation_clicked=record['clicked'], rotation_locked_at=locked_at,
                  rotation_locked_by=int(record.get('locked_by') or 0), rotation_lock=line)

    def license_changed(self):
        # Legacy receipt changes renew compatibility records; they never revoke a pairing or change sync switches.
        self._start_control()
        self._control_wake.set()
        self._emit()

    def boot(self) -> None:
        """At server start: the phone mirror and the vault sync each run only if on and signed in."""
        try:                                # a phone change file interrupted at the last quit: finish or undo it first
            self.writer.call(delivery.recover)
        except Exception as e:
            app_console.emit('log', 'From the phone: an interrupted change file could not be undone yet', level='error', error=e)
        with self._pair_identity_lock:
            on, vault, folder, last, account, expired, paused, epoch, adopt = self.writer.read(lambda db: (db.get_setting(S_ON, '') == 'on',
                                                                                      db.get_setting(S_VAULT, '') == 'on',
                                                                                      db.get_setting('obsidian_vault', '') or '',
                                                                                      int(db.get_setting(S_LAST, '0') or 0),
                                                                                      db.get_setting(S_ACCOUNT, ''),
                                                                                      db.get_setting(S_EXPIRED, '') == '1',
                                                                                      int(db.get_setting(S_PAUSED, '0') or 0),
                                                                                      db.get_setting(S_EPOCH, '') or '', db.get_setting(S_ADOPT, '') or ''))
            self._pair_identity = epoch, adopt
        disconnect = self.intents.find(intents.DISCONNECT)
        priority_disconnect = bool(disconnect)
        if disconnect and disconnect.get('error') == DISCONNECT_PREPARING:
            self.writer.call(lambda db: _store_settings(db, {S_ON: '', S_VAULT: 'off', S_PAUSED: '', S_PAUSE_RESTORE: ''}))
            on = vault = False
            paused = 0
            self.intents.update(intents.DISCONNECT, error='', code='')
        elif (paused or priority_disconnect) and (on or vault):
            self.writer.call(lambda db: _store_settings(db, {S_ON: '', S_VAULT: 'off'}))
            on = vault = False
        signed = self.signed_in()
        key_missing = self._key_missing()
        with self._lock:
            self.st.update(on=on, vault={'on': vault, 'folder': folder}, last_publish=last, account=account,
                           token_expired=expired and signed, paused_since=paused, key_missing=key_missing)
        rotation = self._rotation()
        if rotation and rotation['stage'] != 'complete':
            self._set(rotation='pending')
            # A removal begun before tasks were saved gets its task now, but only in the library it belongs to: this cloud folder
            # can be opened by another data folder (a second copy, a test), and that one must never drive the removal.
            if not self.intents.find(intents.REMOVE) and self._rotation_is_here(rotation):
                self.intents.add(intents.REMOVE, {'new': self._rotation_key(rotation['new']).fingerprint})
                self._sync_remove_intent(rotation)
        self._lock_status(rotation)
        self._start_control()
        if priority_disconnect:
            self.start(oneshot=True)
        elif expired and signed:
            # Google refused this PC's sign-in before the last quit: show why instead of starting work that fails again.
            # Nothing was deleted; Sign in again renews it and starts what was on (T11).
            c = cloud_errors.classify(drive_client.DriveError('expired', 401), account=account)
            if on:
                self._set(state='signed-out', error=c['message'], error_code=c['code'], error_action=c['action'])
            if vault and entitlements.feature_enabled('phone_sync'):
                self._set(vault_state='error', vault_reason=c['message'])
        elif on and signed:
            self.start()
        elif signed and self.intents.all() and (not paused or self.intents.find(intents.DISCONNECT)):
            self.start(oneshot=True)        # a removal, a passphrase save or a one-time backup was waiting when the app closed
        elif on:
            self._set(state='signed-out', error='Sign in to Google Drive again to keep uploading.')
        if not entitlements.feature_enabled('phone_sync'):
            self._set(vault_state='locked')
        elif expired and signed:
            pass
        elif vault and signed:
            self.start_vault()
        elif vault:
            self._set(vault_state='error', vault_reason='Sign in to Google Drive again to keep the vault in step.')

    def _rotation_is_here(self, rotation) -> bool:
        """The pending removal is this library's: its database recorded the old or the new key as the one it backed up with."""
        old, new = (self._rotation_key(rotation[k]).fingerprint for k in ('old', 'new'))
        epoch, adopt = self.writer.read(lambda db: (db.get_setting(S_EPOCH, ''), db.get_setting(S_ADOPT, '')))
        return epoch in (old, new) or adopt in (old, new)

    def start(self, oneshot: bool = False, *, _control: bool = True) -> None:
        with self._pause_control:
            if self.st['paused_since'] and not self.intents.find(intents.DISCONNECT):
                return
            self._start_worker(oneshot)
        if _control and not self.st['paused_since']:
            self._start_control_after_accept()

    def _start_worker(self, oneshot: bool = False) -> None:
        """The sync thread. `oneshot`: backup itself is off and the thread only runs what is waiting (an intent, a pending
        removal); it ends when that is done (D4). Turning backup on makes any running thread an ordinary one."""
        self.require_open()
        with self._life:
            if self.running:
                if not oneshot:
                    self._oneshot = False
                if self._stop.is_set():
                    self._resume = True     # the old worker is still stopping: it starts the next one when it exits
                return
            self._resume = False
            self._oneshot = oneshot
            self._stop = stop = threading.Event()
            self._force = True
            # 'starting' before the threads run, so it never lands after their 'publishing'; sent once
            # they run, so the snapshot says running. The first publish ends it.
            self._set(emit=False, state='starting', error='')
            self._thread = threading.Thread(target=self._loop, args=(stop,), name='cm-sync', daemon=True)
            self._thread.start()
        self._emit()

    def ensure_running(self, *, _control: bool = True) -> None:
        """After a handler saved an intent (and at boot): the sync thread exists while backup is on or something is waiting
        for it, and it is told to look now. Handlers call this and return; they never wait for the thread (S3)."""
        if self._closing or not self.intents.all():
            return
        on = self.writer.read(lambda db: db.get_setting(S_ON, '') == 'on')
        if not self.running or self._stop.is_set():
            self.start(oneshot=not on, _control=_control)
        self.poke(force=True)

    def start_vault(self, *, _control: bool = True) -> None:
        with self._pause_control:
            if self.st['paused_since']:
                return
            self._start_vault_worker()
        if _control and not self.st['paused_since']:
            self._start_control_after_accept()

    def _start_vault_worker(self) -> None:
        """The vault rounds' thread, with its own On / Off beside the phone mirror's. The first round runs at once."""
        self.require_license()
        with self._life:
            if self.vault_running:
                if self._vault_stop.is_set():
                    self._vault_resume = True
                return
            self._vault_resume = False
            self._vault_stop = stop = threading.Event()
            self._vault_now = True
            self._set(emit=False, vault_state='starting', vault_reason='', vault_devices=None)
            self._vault_thread = threading.Thread(target=self._vault_loop, args=(stop,), name='cm-vault', daemon=True)
            self._vault_thread.start()
        self._emit()

    def _end_mirror(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread:
            thread.join(10)
        if thread and thread.is_alive():
            # One request outlasts the wait. The state says so at once; the worker settles it as it exits (I4).
            self._set(state='stopping', **({} if self.st['paused_since'] else {'done': 0, 'total': 0}))
            raise WorkerStopping(MIRROR_STOPPING)
        elif self._thread is thread:
            self._thread = None

    def _end_vault(self) -> None:
        self._vault_stop.set()
        self._vault_wake.set()
        thread = self._vault_thread
        if thread:
            thread.join(10)
        if thread and thread.is_alive():
            self._set(vault_state='stopping', **({} if self.st['paused_since'] else {'vault_step': '', 'vault_done': 0, 'vault_total': 0, 'vault_since': 0}))
            raise WorkerStopping(VAULT_STOPPING)
        elif self._vault_thread is thread:
            self._vault_thread = None

    def _continue_mirror(self) -> None:
        """The old worker exits after a stop that outlasted its caller's wait (I4): uploads that are still on start
        again, once, from here. A Stop, a Disconnect or a closing server since then wins: the setting is read now."""
        if self._closing:
            return
        try:
            on = self.writer.read(lambda db: db.get_setting(S_ON, '') == 'on')
            paused = self.writer.read(lambda db: bool(db.get_setting(S_PAUSED, '')))
            if self.intents.find(intents.DISCONNECT) or (on or (self.intents.all() and not paused)) and self.signed_in():
                self.start(oneshot=not on)
        except Exception as e:      # the Writer is shutting down, or cloud work is stopping
            app_console.emit('log', 'Drive mirror: uploads did not start again after the stop', level='warning', error=e)

    def _continue_vault(self) -> None:
        if self._closing:
            return
        try:
            if entitlements.feature_enabled('phone_sync') and self.signed_in() \
                    and self.writer.read(lambda db: db.get_setting(S_VAULT, '') == 'on'):
                self.start_vault()
        except Exception as e:
            app_console.emit('log', 'Vault sync: did not start again after the stop', level='warning', error=e)

    def _finish_stop(self) -> None:
        """Workers complete an accepted stop even after the HTTP request has returned."""
        with self._lock:
            changes = {}
            if (self.st['vault_state'] == 'stopping' or self.st['state'] == 'stopping') and not self.vault_running:
                changes.update(vault_state='off', vault_reason='', vault_summary='', vault_skipped=0, vault_skipped_note='')
                if not self.st['paused_since']:
                    changes.update(vault_step='', vault_done=0, vault_total=0, vault_since=0)
            if self.st['state'] == 'stopping' and not self.running and not self.vault_running:
                changes.update(state='off')
                if not self.st['paused_since'] or self.st.get('error_code') not in RESUME_BLOCKERS:
                    changes['error'] = ''
                if not self.st['paused_since']:
                    changes.update(done=0, total=0)
            if not changes:
                return
            self.st.update(changes)
            self.st['seq'] += 1
        self._emit()

    def shutdown(self, stop_control=True) -> None:
        if stop_control:
            self._control_stop.set()
            self._control_wake.set()
            if self._control_thread:
                self._control_thread.join(10)
                if self._control_thread.is_alive():
                    raise drive_client.DriveError('License control update is still stopping.')
        # a sign-in cut off here says nothing: the caller sets the state
        with drive_client._SAVE_LOCK:
            self._generation += 1
            cancel, self._signin_cancel = self._signin_cancel, None
        if cancel:
            cancel.set()
        self._stop.set()
        self._vault_stop.set()
        try:
            self._end_mirror()
        finally:
            self._end_vault()
        if self._signin_thread:
            self._signin_thread.join(10)
            if self._signin_thread.is_alive():
                raise drive_client.DriveError('Google sign-in is still stopping. Retry after the outstanding request ends.')
            self._signin_thread = None

    def poke(self, force: bool = False) -> None:
        """Something changed (a job finished, an option was set): look now instead of at the next poll."""
        if self.running:
            self._force = self._force or force
            self._look_now = self._look_now or force
            self._wake.set()

    # ── the user's actions ──────────────────────────────────────────────────
    def publish_once(self) -> None:
        """Back up once, with backup off (D4), or Try again after a failure: Upload now when the thread runs, else a task for a
        one-time thread that ends by itself and leaves backup as it was."""
        self.require_open()
        for it in self.intents.all():
            if it.get('error'):
                self.intents.update(it['kind'], error='', code='')
        if self.intents.find(intents.DISCONNECT):
            self.ensure_running()
            return
        if self.running and not self._stop.is_set():
            self.upload_now()
            return
        if drive_client.load_token(self.token_path) is None:
            raise drive_client.DriveError('Google Drive is not connected. Choose Back up to Google Drive first.')
        if self._key_missing():
            self._set(key_missing=True)
            raise drive_client.DriveError(KEY_MISSING)
        self.intents.add(intents.ONE_SHOT)
        self.ensure_running()

    def upload_now(self) -> None:
        """Upload now: 'publishing' at once, then the thread takes the forced publish."""
        self.require_open()
        if self.running and not self._stop.is_set():
            self._set(state='publishing', done=0, total=0, error='')
            self.poke(force=True)

    def connect(self, what: str = 'mirror') -> None:
        """Upload to Google Drive ('mirror') or Sync my Obsidian vault ('vault'): sign in (in the
        browser) if needed, then turn that one on. Returns at once; the sign-in waits on its own
        thread. A Connect while a sign-in is open joins it: both turn on when Google answers."""
        with self.recovery.gate():
            self.require_open()
            if self.intents.find(intents.DISCONNECT):
                raise cloud_errors.Busy('Disconnecting from Google Drive. This finishes automatically after the current request.')
            if what == 'vault':
                self.require_license()
            with drive_client._SAVE_LOCK:
                if self.signed_in():
                    self._turn_on(what)
                    return
                if self._signin_thread and self._signin_thread.is_alive() and self.st['state'] != 'signing-in':
                    raise drive_client.DriveError('Previous Google sign-in is still stopping. Retry after it ends.')
                cid, secret = config.google_client()
                if not cid:
                    raise drive_client.DriveError('No Google sign-in app is configured for this build.')
                self._after_sign_in.add(what)
                waits = {'vault_state': 'starting', 'vault_reason': ''} if what == 'vault' else {}
                if self.st['state'] == 'signing-in':
                    if waits:
                        self._set(**waits)
                    return
                cancel = self._signin_cancel = threading.Event()
                generation = self._generation
                self._set(state='signing-in', error='', **waits)

                def run():
                    try:
                        if cancel.is_set():
                            return
                        tok = self._sign_in(cid, secret, cancel=cancel)
                        if cancel.is_set():                      # Cancel sign-in won the race with Google's answer
                            raise drive_client.SignInCancelled('Google sign-in was cancelled.')
                        with drive_client._SAVE_LOCK:
                            if cancel.is_set() or generation != self._generation or cancel is not self._signin_cancel:
                                raise drive_client.SignInCancelled('Google sign-in was replaced.')
                            self.require_open()
                            # Never wait for reconnect while holding the token lock: the gate refuses at once.
                            with self.recovery.gate():
                                drive_client.save_token(self.token_path, tok)
                            self.recovery.forget_reconnect()
                            self._clear_expired()               # a new sign-in is a good one
                    except drive_client.DriveError as e:
                        if cancel is self._signin_cancel:       # not a sign-in that Change account or Cancel replaced
                            self._set(state='off' if not self.running else 'idle', error=str(e), **self._sign_in_dropped())
                        return
                    if cancel.is_set() or generation != self._generation:
                        return
                    client = self._factory(tok)
                    client.stop = cancel
                    self._read_account(client, generation, cancel)
                    with drive_client._SAVE_LOCK:
                        if cancel.is_set() or generation != self._generation:
                            return
                        want, self._after_sign_in = self._after_sign_in, set()
                        for w in ('mirror', 'vault', 'recovery'):
                            if w in want and (w != 'vault' or entitlements.feature_enabled('phone_sync')):
                                try:
                                    self._turn_on(w, after_sign_in=True)
                                except drive_client.DriveError as e:     # reconnect is running: nothing turns on
                                    self._set(state='idle' if self.running else 'off', error=str(e))
                self._signin_thread = threading.Thread(target=run, name='cm-signin', daemon=True)
                self._signin_thread.start()

    def _sign_in_dropped(self) -> dict:
        """A sign-in that ends without a token: a vault sync waiting on it goes back to off."""
        want, self._after_sign_in = self._after_sign_in, set()
        if 'vault' in want and not self.vault_running and self.st['vault_state'] == 'starting':
            return {'vault_state': 'off', 'vault_reason': ''}
        return {}

    def cancel_sign_in(self) -> None:
        """Cancel sign-in: the wait for Google's answer ends (sign_in binds port 0, so Connect
        again gets a new listener). Back to 'off' (or 'idle' while uploading) at once."""
        with drive_client._SAVE_LOCK:
            self._generation += 1
            cancel, self._signin_cancel = self._signin_cancel, None
            if cancel:
                cancel.set()
            if self.st['state'] == 'signing-in':
                self._set(state='idle' if self.running else 'off', error='', **self._sign_in_dropped())

    def _check_expected_account(self, expected, client=None) -> None:
        if expected is None:
            return
        account = client.about().get('email', '') if client is not None else self.st.get('account', '')
        if not expected.strip() or account.strip().casefold() != expected.strip().casefold():
            raise cloud_errors.RecoveryBlocked('The Google account changed. Review this action again for the current account.')

    def switch(self, delete_old: bool | None = None, *, expected_account: str | None = None) -> None:
        """Change account. Without `delete_old` (None): sign out without starting uploads or vault sync; existing copies and
        keys stay. With it (the Switch account form): a task (finding 7). This PC signs in to the other account and backs
        up there; the copy in the old account is deleted only after that first backup is complete, and only when asked."""
        with self.recovery.gate():
            self._check_expected_account(expected_account)
            if not config.google_client()[0]:
                raise drive_client.DriveError('No Google sign-in app is configured for this build.')
            if delete_old is None:
                self.sign_out(delete_mirror=False)
                self.connect('recovery')
                return
            with self._pause_control:
                update = self.intents.find(intents.UPDATE)
                if update and update['stage'] == 'swap':
                    raise drive_client.DriveError('The switch to the newer library is prepared. Restart Brainamon to finish it.')
                self.intents.add(intents.SWITCH, {'delete_old': bool(delete_old), 'account': self.st.get('account', ''),
                                                **({'expected_account': expected_account} if expected_account is not None else {})})
                self.recovery.cancel_update()
                self._start_intent(intents.SWITCH)

    def _start_intent(self, kind: str) -> None:
        """Accept a backup/account change without doing network or key work in the request handler."""
        self._vault_stop.set()
        self._vault_wake.set()
        self._control_stop.set()
        self._control_wake.set()
        self._stop.set()
        self._wake.set()
        with self._pause_control:
            self._stop.set()
            self._vault_stop.set()
            try:
                self.writer.call(lambda db: _store_settings(db, {S_PAUSED: '', S_PAUSE_RESTORE: '', S_VAULT: 'off'}))
            except Exception:
                message = 'The cloud task was saved, but its local settings could not be updated. Try again.'
                self.intents.update(kind, error=message, code=cloud_errors.LOCAL_STORAGE)
                self._set(state='error', error=message, error_code=cloud_errors.LOCAL_STORAGE, error_action=cloud_errors.RETRY)
                return
            self._paused_task = None
            self._set(paused_since=0, error='', vault={**self.st['vault'], 'on': False})
        try:
            self.ensure_running(_control=False)
        except (OSError, RuntimeError, drive_client.DriveError):
            app_console.emit('log', 'A saved cloud task could not start.', level='warning')
            try:
                self._set(state='error', error='The cloud task was saved. Restart Brainamon to continue.')
            except Exception:
                pass

    def _old_copy_ids(self) -> list:
        """Drive ids of the copy this PC backs up now: its mirror files, its access record, and this library's recovery records
        (Drive read only). What Switch account and Reset backup delete once the new backup is complete."""
        tok = drive_client.load_token(self.token_path)
        if tok is None:
            return []
        client = self._raw_factory(tok)
        listing = client.list()
        key = mirror.MirrorKey.load(self.key_path)
        ids = set()
        if key is not None:
            ids |= self._mirror_ids(client, key, listing)
            controls = {key.name(path) for path in sync_license.CONTROL_LOGICALS}
            ids |= {f['id'] for f in listing if f['name'] in controls}
        fingerprint = key.fingerprint if key is not None else self.writer.read(lambda db: db.get_setting(S_EPOCH, ''))
        if fingerprint:
            ids |= self.recovery.library_record_ids(client, listing, fingerprint)
        return sorted(ids)

    def _switch_signout(self, it, stop) -> None:
        """The Switch task's first step, on the sync thread: backup and vault sync off, the old
        sign-in put aside (kept while the old copy is to be deleted, revoked otherwise), then the browser opens for the other
        account and backup starts when Google answers."""
        p = it['payload']
        if p.get('expected_account') is not None:
            self._check_expected_account(p['expected_account'], self._raw_factory(drive_client.load_token(self.token_path)))
        if 'ids' not in p:
            p = self.intents.update(intents.SWITCH, payload={'ids': self._desktop_backup_ids() if p.get('delete_old') else []})['payload']
        if stop and stop.is_set():
            raise ExportStopped()
        with self._pause_control:
            if stop and stop.is_set():
                raise ExportStopped()
            rotation = self._rotation()
            if rotation and rotation['stage'] != 'complete':
                # Switching accounts must not revive a phone key that Remove already revoked.
                new = self._rotation_key(rotation['new'])
                new.save(self.key_path)
                self.recovery.archive_state('switch')
                self._write_identity(lambda db: (db.clear_sync_state(), db.set_setting(S_EPOCH, ''), db.set_setting(S_ADOPT, new.fingerprint)))
            self._retire_tasks(intents.SWITCH)
            self._vault_resume = False
            self.writer.call(lambda db: (db.set_setting(S_ON, ''), db.set_setting(S_VAULT, 'off'), db.set_setting(S_PAUSED, ''), db.set_setting(S_PAUSE_RESTORE, '')))
            self._paused_task = None
            self._set(on=False, vault={**self.st['vault'], 'on': False}, paused_since=0)
        self._vault_stop.set()
        self._vault_wake.set()
        self._end_vault()
        if stop and stop.is_set():
            raise ExportStopped()
        self.recovery.forget_reconnect()
        tok = drive_client.load_token(self.token_path)
        if tok and p.get('delete_old'):
            drive_client.save_token(self.previous_token_path, tok)
        elif tok:
            drive_client.revoke(tok)
        with drive_client._SAVE_LOCK:
            drive_client.private_storage.remove(self.token_path)
        self._clear_expired()
        self._account_read = False
        self._oneshot = True            # a running thread now only waits for the sign-in
        self._set(state='off', on=False, vault={**self.st['vault'], 'on': False}, done=0, total=0, used=0, limit=0, files=0, size=0, skipped=0, skipped_note='', error='',
                  vault_state='off', vault_reason='', vault_summary='', vault_skipped=0, vault_skipped_note='')
        self.intents.update(intents.SWITCH, stage='signing-in')
        if not (stop and stop.is_set()) and not self.intents.find(intents.DISCONNECT):
            self.connect('mirror')

    def _finish_switch(self, stop) -> None:
        """The first backup in the other account is complete: the old copy goes, if the form asked for that (finding 7). A delete
        that stopped part way leaves the stage at 'cleanup', and the next complete publish takes it up again."""
        it = self.intents.find(intents.SWITCH)
        account = self.st.get('account', '')
        if not it or it['stage'] not in ('signing-in', 'cleanup') or (it.get('error') and it['stage'] != 'cleanup') or not account:
            return
        p = it['payload']
        previous = drive_client.load_token(self.previous_token_path)
        if previous and p.get('delete_old') and (p.get('account') or '').casefold() != account.casefold():
            self.intents.update(intents.SWITCH, stage='cleanup')
            self._emit()
            client = self._raw_factory(previous)
            client.stop = stop
            if isinstance(client, drive_client.DriveClient):
                client.token_path = self.previous_token_path        # a refresh of the old sign-in never lands in the new one's file
            self._check_expected_account(p.get('expected_account'), client)
            old_ids = p.get('ids', [])
            self._set(done=0, total=len(old_ids))
            drive_client.delete_files(client, old_ids, lambda done, total: self._set(done=done, total=total), ExportStopped)
            try:
                drive_client.revoke(previous)
            except Exception as e:
                app_console.emit('log', 'Drive mirror: the old account sign-in was not revoked', level='warning', error=e)
        with drive_client._SAVE_LOCK:
            try:
                drive_client.private_storage.remove(self.previous_token_path)
            except FileNotFoundError:
                pass
        self.intents.finish(intents.SWITCH)

    def reset_backup(self, replace_existing: bool = False, *, expected_account: str | None = None) -> None:
        """Reset backup: a new library key and a new first backup. The old backup is deleted only once the new one is complete,
        so there is never a moment with nothing to restore. Recovery starts over (a new passphrase and file)."""
        with self.recovery.gate():
            self._check_expected_account(expected_account)
            if drive_client.load_token(self.token_path) is None:
                raise drive_client.DriveError('Google Drive is not connected. Choose Back up to Google Drive first.')
            self.recovery.cancel_update()
            with self._pause_control:
                pending = self.intents.find(intents.RESET)
                if pending:
                    self._check_expected_account(pending['payload'].get('expected_account'))
                    if expected_account is not None:
                        self.intents.update(intents.RESET, payload={'expected_account': expected_account})
                    # Upgrading a stuck reset to an explicit replacement starts once; ordinary retries reuse its key.
                    if replace_existing and not pending['payload'].get('replace_existing'):
                        self.intents.update(intents.RESET, stage='queued', error='', code='', payload={'replace_existing': True, 'ids': None, 'new': None})
                    else:
                        self.intents.update(intents.RESET, error='', code='')
                    if self.intents.find(intents.RESET)['stage'] == 'queued':
                        self._start_intent(intents.RESET)
                    else:
                        before = self.writer.read(lambda db: {key: db.get_setting(key, None) for key in (S_PAUSED, S_PAUSE_RESTORE)})
                        old_task, was_running = self._paused_task, self.running
                        try:
                            self.clear_pause()
                            self.ensure_running(_control=False)
                        except Exception:
                            if not was_running:
                                self._stop.set()
                            self.writer.call(lambda db: _store_settings(db, before))
                            self._paused_task = old_task
                            self.intents.update(intents.RESET, error=pending.get('error', ''), code=pending.get('code', ''))
                            self._set(paused_since=int(before[S_PAUSED] or 0))
                            raise
                    return
                self.intents.add(intents.RESET, {'replace_existing': replace_existing,
                                               **({'expected_account': expected_account} if expected_account is not None else {})})
                self._start_intent(intents.RESET)

    def _reset_begin(self, it, stop) -> None:
        p = it['payload']
        if p.get('expected_account') is not None:
            self._check_expected_account(p['expected_account'], self._raw_factory(drive_client.load_token(self.token_path)))
        if p.get('ids') is None:
            p = self.intents.update(intents.RESET, payload={'ids': self._desktop_backup_ids() if p.get('replace_existing') else self._old_copy_ids()})['payload']
        if stop and stop.is_set():
            raise ExportStopped()
        self._retire_tasks(intents.RESET)
        new = self._rotation_key(p['new']) if p.get('new') else mirror.MirrorKey.generate()
        self.intents.update(intents.RESET, payload={'new': new.text()})
        self._vault_resume = False
        self._vault_stop.set()
        self._vault_wake.set()
        self._end_vault()
        with self._pause_control:
            if stop.is_set():
                raise ExportStopped()
            self.recovery.archive_state('reset')
            old = mirror.MirrorKey.load(self.key_path)
            if old and old.fingerprint != new.fingerprint:
                old.save(self.cloud_dir / f'mirror-before-reset-{it["id"]}.key')
            new.save(self.key_path)
            self._write_identity(lambda db: (db.set_setting(S_ADOPT, new.fingerprint), db.set_setting(S_EPOCH, ''), db.clear_sync_state(), db.set_setting(S_ON, 'on'),
                                          db.set_setting(S_PAUSED, ''), db.set_setting(S_PAUSE_RESTORE, ''), db.set_setting(S_VAULT, 'off')))
            self._paused_task = None
            self._set(on=True, vault={**self.st['vault'], 'on': False}, paused_since=0, key_missing=False, error='', vault_state='off')
        self.intents.update(intents.RESET, stage='backing-up')
        self._control_wake.set()
        if stop.is_set() and not self.st['paused_since']:
            resume = self._resume
            self.turn_off()
            self._resume = self._resume or resume
        self._force = True
        self.poke(force=True)

    @staticmethod
    def _desktop_backup_file(name: str) -> bool:
        # Standalone phone backups have separate namespaces and are never part of a desktop replacement.
        return bool(re.fullmatch(r'(?:[0-9a-f]{32}|(?:chg-|vb-|vi-|vs-|ph-)[0-9a-f]{32}|pky-\d+-[0-9a-f]{32}|vi-recovery-(?:owner-)?[0-9a-f]{32}(?:-[0-9a-f]{32})?\.json)', name))

    def _desktop_backup_ids(self) -> list:
        tok = drive_client.load_token(self.token_path)
        return sorted(f['id'] for f in self._raw_factory(tok).list() if self._desktop_backup_file(f['name'])) if tok else []

    def _finish_reset(self, stop) -> None:
        """The new backup is complete: the old one goes (never earlier, never after a partial publish). A delete that stopped
        part way leaves the stage at 'cleanup', and the next complete publish takes it up again."""
        it = self.intents.find(intents.RESET)
        tok = drive_client.load_token(self.token_path)
        if not it or it['stage'] not in ('backing-up', 'cleanup') or (it.get('error') and it['stage'] != 'cleanup') or tok is None:
            return
        self._set(emit=False, upload_step='Checking the old backup files to delete…', done=0, total=0)
        if it['stage'] != 'cleanup':
            self.intents.update(intents.RESET, stage='cleanup')
        else:
            self._emit()
        client = self._raw_factory(tok)
        client.stop = stop
        self._check_expected_account(it['payload'].get('expected_account'), client)
        present = {f['id'] for f in client.list()}
        remaining = [fid for fid in it['payload'].get('ids', []) if fid in present]
        self._set(upload_step='Deleting the old backup…', done=0, total=len(remaining))
        drive_client.delete_files(client, remaining, lambda done, total: self._set(done=done, total=total), ExportStopped)
        self.intents.finish(intents.RESET)
        self._set(upload_step='', done=0, total=0)

    def _after_complete_publish(self, stop) -> None:
        """A publish ended with no errors and its manifest written. Old copies that waited for it can go now."""
        for kind, finish in ((intents.SWITCH, self._finish_switch), (intents.RESET, self._finish_reset)):
            if stop.is_set():
                return
            if self.intents.find(kind):
                try:
                    finish(stop)
                except ExportStopped:
                    return
                except Exception as e:      # the next complete publish tries again; the new backup is not at risk
                    if stop.is_set():
                        return
                    c = self.classified(e, fallback=str(e))
                    self.intents.update(kind, error=c['message'], code=c['code'])
                    self._emit()
                    app_console.emit('log', f'Drive mirror: the old copy was not deleted yet ({kind})', level='warning', error=e)

    def _expected_accounts(self) -> tuple[str, set[str]]:
        """The Google account this library already belongs to, as it was recorded: (the address to hint, every recorded
        address casefolded). Sources: the account of the last upload, the recovery setup and a pending removal of phones."""
        stored = self.writer.read(lambda db: db.get_setting(S_ACCOUNT, '')) or self.st.get('account', '')
        state = self.recovery._load(readonly=True)
        rotation = self._rotation(readonly=True)
        pending = rotation.get('account', '') if rotation and rotation['stage'] != 'complete' else ''
        known = [a for a in (stored, (state or {}).get('account', ''), pending) if a]
        return (known[0] if known else ''), {a.casefold() for a in known}

    def sign_in_again(self) -> None:
        """Renew an expired Google sign-in for the same account (S1). Returns at once; the sign-in waits on its own thread
        as Connect does. The new token replaces the stored one only after Google names the account this library backs up
        to; another account's token is revoked and dropped, and nothing else changes: no sign-out, no state cleared, the
        copy in Drive untouched (T12). On success the access record is renewed at once and what was on starts again."""
        with self.recovery.gate():
            self.require_open()
            if drive_client.load_token(self.token_path) is None:
                raise drive_client.DriveError('Google Drive is not connected. Choose Connect Google Drive.')
            cid, secret = config.google_client()
            if not cid:
                raise drive_client.DriveError('No Google sign-in app is configured for this build.')
            hint, expected = self._expected_accounts()
            with drive_client._SAVE_LOCK:
                if self._signin_thread and self._signin_thread.is_alive():
                    if self.st['state'] == 'signing-in':
                        return              # one is open: this joins it
                    raise drive_client.DriveError('Previous Google sign-in is still stopping. Retry after it ends.')
                cancel = self._signin_cancel = threading.Event()
                generation = self._generation
                self._set(state='signing-in', error='')

                def run():
                    try:
                        if cancel.is_set():
                            return
                        tok = self._sign_in(cid, secret, cancel=cancel, login_hint=hint)
                        if cancel.is_set():
                            raise drive_client.SignInCancelled('Google sign-in was cancelled.')
                        probe = self._raw_factory(tok)
                        if isinstance(probe, drive_client.DriveClient):
                            probe.token_path, probe.stop = None, cancel      # in memory: nothing is saved before the check
                        about = probe.about()
                        got = about.get('email') or ''
                        if not got:
                            raise drive_client.DriveError('Google did not confirm the account. Choose Sign in again.')
                        if expected and {got.casefold()} != expected:
                            try:
                                drive_client.revoke(tok)
                            except Exception as e:      # best effort: the token was never saved
                                app_console.emit('log', 'Drive mirror: the discarded sign-in was not revoked', level='warning', error=e)
                            raise cloud_errors.WrongAccount(got, hint)
                        with drive_client._SAVE_LOCK:
                            if cancel.is_set() or generation != self._generation or cancel is not self._signin_cancel:
                                raise drive_client.SignInCancelled('Google sign-in was replaced.')
                            self.require_open()
                            with self.recovery.gate():          # never wait for reconnect while holding the token lock
                                drive_client.save_token(self.token_path, tok)
                            self._set(account=about.get('email', ''), used=about.get('used', 0), limit=about.get('limit', 0))
                            self._clear_expired()
                    except Exception as e:
                        if cancel is self._signin_cancel:       # not a sign-in that Cancel or Change account replaced
                            # a Drive error carries a sentence written for the page; anything else gets a fixed one
                            c = self.classified(e, fallback='' if isinstance(e, drive_client.DriveError) else 'Google sign-in did not finish. Choose Sign in again.')
                            self._set(state='idle' if self.running else 'off', error=c['message'], error_code=c['code'], error_action=c['action'],
                                      error_account=str(getattr(e, 'got', '') or ''))     # WrongAccount.got; '' for every other failure
                        return
                    if cancel.is_set() or generation != self._generation:
                        return
                    self._resume_after_sign_in()
                self._signin_thread = threading.Thread(target=run, name='cm-signin', daemon=True)
                self._signin_thread.start()

    def _resume_after_sign_in(self) -> None:
        """A renewed sign-in: the access record is renewed at once and the uploads and vault sync that were on go on."""
        self._set(state='idle' if self.running else 'off', error='')
        self._start_control()
        self._control_wake.set()
        pending = self.intents.find(intents.DISCONNECT)
        if pending:
            self.intents.update(intents.DISCONNECT, error='', code='')
            self.ensure_running()
        on, vault = self.writer.read(lambda db: (db.get_setting(S_ON, '') == 'on', db.get_setting(S_VAULT, '') == 'on'))
        try:
            if on:
                if self.running:
                    self.poke(force=True)
                else:
                    self.start()
            if vault and entitlements.feature_enabled('phone_sync'):
                self.start_vault()
        except drive_client.DriveError as e:        # reconnect or a close is running: nothing starts
            self._set(error=str(e))

    def _turn_on(self, what: str, after_sign_in: bool = False) -> None:
        if what == 'recovery':
            self._set(state='off', error='')
        elif what == 'vault':
            self.turn_vault_on(after_sign_in=after_sign_in)
        else:
            self.turn_on(after_sign_in=after_sign_in)

    def _key_missing(self) -> bool:
        """The library was backed up before (an epoch is recorded) but this PC has no key file: a reinstall (D9). Making a
        new key here would upload the whole library a second time."""
        try:
            if mirror.MirrorKey.load(self.key_path, readonly=True) is not None:
                return False
        except mirror.MirrorKeyError:
            return False        # damaged, not missing: the next use says so
        return bool(self.writer.read(lambda db: db.get_setting(S_EPOCH, '')))

    def _enable_switch(self, vault: bool, start: bool = True, extra_settings=None) -> None:
        keys = (S_ON, S_VAULT, S_PAUSED, S_PAUSE_RESTORE, *(extra_settings or {}))
        before = self.writer.read(lambda db: {key: db.get_setting(key, None) for key in keys})
        fields = ('on', 'vault', 'paused_since', 'key_missing', 'state', 'vault_state', 'vault_devices',
                  'error', 'error_code', 'error_action', 'error_at', 'error_account')
        old_state = {key: self.st[key] for key in fields}
        old_task = self._paused_task
        was_running = self.vault_running if vault else self.running
        changes = {S_VAULT if vault else S_ON: 'on', S_PAUSED: '', S_PAUSE_RESTORE: '', **(extra_settings or {})}
        write = lambda db: _store_settings(db, changes)
        committed = False
        try:
            if vault:
                self._set(vault_devices=None)
            self._licensed_call(write) if vault else self.writer.call(write)
            committed = True
            self._paused_task = None
            if vault:
                self._set(vault={**self.st['vault'], 'on': True}, paused_since=0)
                if start:
                    self.start_vault(_control=False)
            else:
                self._set(on=True, paused_since=0, key_missing=False)
                if start:
                    self.start(_control=False)
        except Exception:
            if not was_running:
                (self._vault_stop if vault else self._stop).set()
            if committed:
                self.writer.call(lambda db: _store_settings(db, before))
            self._paused_task = old_task
            self._set(**old_state)
            raise

    def turn_on(self, after_sign_in: bool = False) -> None:
        with self.recovery.gate(), self._pause_control:
            if after_sign_in and self.st['paused_since']:
                return
            self.require_open()
            self._finish_stop()
            if self.st['state'] in ('stopping', 'disconnecting'):
                raise drive_client.DriveError('Uploads are still stopping. Wait for the current requests to finish.')
            if self._key_missing():
                self._set(key_missing=True)
                raise drive_client.DriveError(KEY_MISSING)
            self._enable_switch(False)
        self._start_control_after_accept()

    def turn_vault_on(self, after_sign_in: bool = False, *, start: bool = True, extra_settings=None) -> None:
        with self.recovery.gate(), self._pause_control:
            if after_sign_in and self.st['paused_since']:
                return
            self._finish_stop()
            if self.st['state'] in ('stopping', 'disconnecting') or self.st['vault_state'] == 'stopping':
                raise drive_client.DriveError('Vault sync is still stopping. Wait for the current requests to finish.')
            self._enable_switch(True, start=start, extra_settings=extra_settings)
        if start:
            self._start_control_after_accept()

    def turn_vault_off(self) -> None:
        """Stop syncing the vault: its thread ends, the phone mirror goes on. 'stopping' shows at
        once; an outstanding request can outlast the 10 s wait."""
        with self._pause_control:
            def disable(db):
                raw = db.get_setting(S_PAUSE_RESTORE, '')
                values = {S_VAULT: 'off'}
                if db.get_setting(S_PAUSED, '') and raw:
                    record = self._read_pause_record(raw)
                    record.update(vault=False, owner='user', token=secrets.token_hex(16))
                    values[S_PAUSE_RESTORE] = json.dumps(record, separators=(',', ':'))
                _store_settings(db, values)
            self.writer.call(disable)
            if self._resume_check_stop:
                self._resume_check_stop.set()
            self._set(vault={**self.st['vault'], 'on': False}, vault_state='stopping', vault_step='', vault_done=0, vault_total=0, vault_since=0, vault_devices=None)
        self._end_vault()
        # the phone reads the last status the PC sealed into Drive: say it is off, or it goes on showing a round
        self._vault_announce(vault_state='off', vault_reason='', vault_summary='', vault_skipped=0, vault_skipped_note='', vault_step='', vault_done=0, vault_total=0, vault_since=0)

    def _halt(self, state: str, vault: bool = False) -> None:
        """Uploading off and the mirror thread ended (`vault`: the vault sync too, for Disconnect).
        `state` ('stopping', 'disconnecting') shows at once: the joins can take up to 10 s each.
        The caller sets the end state."""
        more = {}
        if vault and self.vault_running:
            more = dict(vault_state='stopping', vault_step='', vault_done=0, vault_total=0, vault_since=0)
        self._resume = self._vault_resume = False
        with self._pause_control:
            self.writer.call(lambda db: (db.set_setting(S_ON, ''), vault and db.set_setting(S_VAULT, 'off')))
            self._set(state=state, on=False, vault={**self.st['vault'], 'on': False} if vault else self.st['vault'], done=0, total=0, **more)
        try:
            if vault:
                self.shutdown()
            else:
                self._end_mirror()
        except drive_client.DriveError:
            # The caller's action never ran, so nothing is 'disconnecting': the workers were told to stop (the
            # settings are already off) and the state is 'stopping' until the last one exits (I4).
            self._stop.set()
            self._vault_stop.set()
            self._wake.set()
            self._vault_wake.set()
            self._set(state='stopping', done=0, total=0, **({'vault_state': 'stopping'} if self.vault_running else {}))
            self._finish_stop()
            raise

    @staticmethod
    def _read_pause_record(raw):
        if not raw:
            return None
        try:
            record = json.loads(raw)
            if (not isinstance(record, dict) or set(record) != {'upload', 'vault', 'owner', 'token'}
                    or type(record['upload']) is not bool or type(record['vault']) is not bool
                    or record['owner'] not in ('user', 'recovery') or not isinstance(record['token'], str)
                    or not re.fullmatch(r'[0-9a-f]{32}', record['token'])):
                raise ValueError()
            return record
        except (ValueError, TypeError):
            raise drive_client.DriveError('The saved pause settings are damaged. Turn on backup explicitly to continue.')

    def clear_pause(self) -> None:
        with self._pause_control:
            self.writer.call(lambda db: _store_settings(db, {S_PAUSED: '', S_PAUSE_RESTORE: ''}))
            self._paused_task = None
            self._set(paused_since=0)

    def turn_off(self, source: str = 'user') -> str | None:
        """Pause work, retaining its original switches and the last reported task progress."""
        with self._pause_control:
            if source == 'recovery' and (self.st['paused_since'] or not (self.running or self.vault_running)
                                         or self.st['state'] in ('stopping', 'disconnecting')
                                         or self.st['vault_state'] == 'stopping'):
                return None
            now_ms = int(time.time() * 1000)
            was_running = self.running or self.vault_running or self.st['state'] == 'signing-in'
            snapshot = self._task_view() if not self.st['paused_since'] else None
            def pause(db):
                since = int(db.get_setting(S_PAUSED, '0') or 0)
                raw = db.get_setting(S_PAUSE_RESTORE, '')
                if since and raw:
                    record = self._read_pause_record(raw)
                elif since:
                    record = {'upload': True, 'vault': False}
                else:
                    record = {'upload': db.get_setting(S_ON, '') == 'on', 'vault': db.get_setting(S_VAULT, '') == 'on'}
                    if record['upload'] or record['vault'] or self.intents.all() or was_running:
                        since = now_ms
                if not since:
                    return 0, None
                record.update(owner=source, token=secrets.token_hex(16))
                _store_settings(db, {S_PAUSED: str(since), S_PAUSE_RESTORE: json.dumps(record, separators=(',', ':')),
                                     S_ON: '', S_VAULT: 'off'})
                return since, record['token']
            paused, token = self.writer.call(pause)
            if not paused:
                return None
            if self._resume_check_stop:
                self._resume_check_stop.set()
            if snapshot is not None:
                self._paused_task = snapshot
            self._resume = self._vault_resume = False
            self._stop.set()
            self._vault_stop.set()
            error = {} if self.st.get('error_code') in RESUME_BLOCKERS else {'error': ''}
            self._set(state='stopping', on=False, vault={**self.st['vault'], 'on': False},
                      vault_state='stopping', paused_since=paused, **error)
            self._wake.set()
            self._vault_wake.set()
            self._finish_stop()
            return token if source == 'recovery' else None

    def _resume_plan(self, token):
        since, raw = self.writer.read(lambda db: (db.get_setting(S_PAUSED, ''), db.get_setting(S_PAUSE_RESTORE, '')))
        if not since:
            return None
        record = self._read_pause_record(raw)
        if token is not None and (not record or record['owner'] != 'recovery' or record['token'] != token):
            return None
        if record is None:
            record = {'upload': True, 'vault': False}
        self.require_open()
        self._finish_stop()
        if self.st['state'] in ('stopping', 'disconnecting') or self.st['vault_state'] == 'stopping':
            raise WorkerStopping('The current requests are still stopping. Backup stays paused; choose Resume again after they finish.')
        if self.recovery._activation_pending():
            raise cloud_errors.RecoveryBlocked('A library change was saved. Restart Brainamon to finish before resuming.')
        try:
            recovery_state = self.recovery._load(readonly=True)
            legacy = self.recovery._optional(self.cloud_dir / 'recovery-legacy.json', readonly=True) if not recovery_state else None
        except (OSError, RuntimeError, ValueError):
            raise cloud_errors.RecoveryBlocked('Recovery settings cannot be read. Keep backup paused and check recovery.') from None
        if recovery_state and recovery_state.get('restored'):
            raise cloud_errors.RecoveryBlocked('This is a restored library. Restart and make this PC the backup PC before resuming.')
        if legacy:
            raise cloud_errors.RecoveryBlocked('Set up recovery for the restored legacy library before resuming.')
        tasks = self.intents.all()
        disconnect = next((it for it in tasks if it['kind'] == intents.DISCONNECT), None)
        ready = [it for it in tasks if not it.get('error') and it['stage'] not in intents.WAITING.get(it['kind'], ())]
        runnable = bool(ready) and not (disconnect and disconnect.get('error'))
        needs_work = bool(record['upload'] or record['vault'] or runnable)
        if needs_work and (not self.signed_in() or self.st['token_expired']):
            raise drive_client.DriveError(drive_client.SIGN_IN_REQUIRED)
        blocker = self.st.get('error_code') if needs_work else ''
        if blocker == cloud_errors.WRONG_ACCOUNT:
            raise cloud_errors.WrongAccount(self.st.get('error_account', ''), self.st.get('account', ''))
        if blocker == cloud_errors.FOREIGN_BACKUP:
            raise cloud_errors.ForeignBackup(self.st.get('error_at', 0))
        if blocker == cloud_errors.NOT_OWNER and not any(it['kind'] == intents.UPDATE and not it.get('error') for it in tasks):
            raise cloud_errors.NotUploader(self.st.get('error') or 'Another PC is the backup PC. Recover or update this library before resuming.', self.st.get('error_at', 0))
        if blocker == cloud_errors.OTHER_COPY:
            raise cloud_errors.OtherCopy(self.st.get('error') or KEY_CONFLICT)
        if needs_work and self._key_missing():
            raise drive_client.DriveError(KEY_MISSING)
        key = mirror.MirrorKey.load(self.key_path, readonly=True) if needs_work else None
        if key is not None and self._key_conflict(key):
            self._set(error=KEY_CONFLICT, error_code=cloud_errors.OTHER_COPY, error_action=cloud_errors.NONE)
            raise cloud_errors.OtherCopy(KEY_CONFLICT)
        if record['vault']:
            self.require_license()
        repair = runnable and ready[0]['kind'] in (intents.DISCONNECT, intents.SWITCH, intents.RESET, intents.UPDATE)
        return since, raw, record, runnable, needs_work and not repair

    def resume(self, token: str | None = None) -> None:
        with self.recovery.gate():
            with self._pause_control:
                plan = self._resume_plan(token)
                if plan is None:
                    return
                since, raw, record, runnable, needs_guard = plan
                check_stop = threading.Event() if needs_guard else None
                self._resume_check_stop = check_stop
            if needs_guard:
                failure = None
                try:
                    client = self.recovery._client(readonly=True)
                    if isinstance(client.client, drive_client.DriveClient):
                        client.client.stop = check_stop
                    self.recovery.guard(client)
                except recovery.RecoveryError as exc:
                    failure = drive_client.DriveError(str(exc))
                except Exception as exc:
                    failure = exc
                with self._pause_control:
                    if self._resume_check_stop is check_stop:
                        self._resume_check_stop = None
                    current = self.writer.read(lambda db: (db.get_setting(S_PAUSED, ''), db.get_setting(S_PAUSE_RESTORE, '')))
                    if check_stop.is_set() or current != (since, raw):
                        return
                    if failure is not None:
                        classified = self.classified(failure)
                        if classified['code'] == cloud_errors.OFFLINE:
                            failure = cloud_errors.ResumeOffline('Backup stays paused; choose Resume backup again when the connection is back.')
                            classified = self.classified(failure)
                        self._set(error=classified['message'], error_code=classified['code'], error_action=classified['action'],
                                  error_at=getattr(failure, 'at', 0))
                        raise failure
            with self._pause_control:
                current = self.writer.read(lambda db: (db.get_setting(S_PAUSED, ''), db.get_setting(S_PAUSE_RESTORE, '')))
                if current != (since, raw):
                    return
                plan = self._resume_plan(token)
                if plan is None:
                    return
                _, _, record, runnable, _ = plan
                self.writer.call(lambda db: _store_settings(db, {S_ON: 'on' if record['upload'] else '',
                    S_VAULT: 'on' if record['vault'] else 'off', S_PAUSED: '', S_PAUSE_RESTORE: ''}))
                saved_task, saved_failed = self._paused_task, self._failed_task
                self._paused_task = self._failed_task = None
                try:
                    self._set(on=record['upload'], vault={**self.st['vault'], 'on': record['vault']}, paused_since=0)
                    if record['upload']:
                        self.start(_control=False)
                    elif runnable:
                        self.ensure_running(_control=False)
                    if record['vault']:
                        self.start_vault(_control=False)
                except Exception:
                    self._stop.set()
                    self._vault_stop.set()
                    self._paused_task, self._failed_task = saved_task, saved_failed
                    self.writer.call(lambda db: _store_settings(db, {S_ON: '', S_VAULT: 'off',
                                                                        S_PAUSED: since, S_PAUSE_RESTORE: raw}))
                    self._set(on=False, vault={**self.st['vault'], 'on': False}, paused_since=int(since))
                    raise
        if record['upload'] or record['vault'] or runnable:
            self._start_control_after_accept()

    def sign_out(self, delete_mirror: bool = False) -> None:
        """Stop uploading and the vault sync, optionally delete the mirror from Drive, forget the Google sign-in.
        Without `delete_mirror` (Change account, Disconnect keeping the copy) what was uploaded stays known:
        `sync_state`, `cloud_epoch` and `cloud_account` are kept, so a sign-in to the same account updates the same
        files instead of making a second copy (F1, I1). `_read_account` forgets them on the first contact with
        another account."""
        with self.recovery.gate():
            self.recovery.forget_reconnect()
            self._halt('disconnecting', vault=True)
            self._disconnect(delete_mirror)

    def request_disconnect(self, delete_mirror: bool = False, delete_existing: bool = False, *, expected_account: str | None = None) -> None:
        """Accept the action now; the sync worker completes it after current requests drain."""
        self.require_open()
        self._check_expected_account(expected_account)
        self.recovery.cancel_update()
        self.recovery.cancel.set()
        self.cancel_sign_in()
        with self._pause_control:
            if self._resume_check_stop:
                self._resume_check_stop.set()
            pending = self.intents.find(intents.DISCONNECT)
            if pending:
                self._check_expected_account(pending['payload'].get('expected_account'))
                self.intents.update(intents.DISCONNECT, error=DISCONNECT_PREPARING, code=cloud_errors.BUSY_CODE,
                                    payload={'delete_mirror': delete_mirror, 'delete_existing': delete_existing,
                                             **({'expected_account': expected_account} if expected_account is not None else {})})
            else:
                self.intents.add(intents.DISCONNECT, {'delete_mirror': delete_mirror, 'delete_existing': delete_existing,
                                                     **({'expected_account': expected_account} if expected_account is not None else {})},
                                 error=DISCONNECT_PREPARING, code=cloud_errors.BUSY_CODE)
            self._resume = self._vault_resume = False
            self._stop.set()
            self._vault_stop.set()
            self._control_stop.set()
            self._wake.set()
            self._vault_wake.set()
            self._control_wake.set()
            try:
                self.writer.call(lambda db: _store_settings(db, {S_ON: '', S_VAULT: 'off', S_PAUSED: '', S_PAUSE_RESTORE: ''}))
            except Exception:
                message = 'Disconnect was saved, but its local settings could not be updated. Try again.'
                self.intents.update(intents.DISCONNECT, error=message, code=cloud_errors.LOCAL_STORAGE)
                self._set(state='error', error=message, error_code=cloud_errors.LOCAL_STORAGE, error_action=cloud_errors.RETRY)
                return
            self._paused_task = self._failed_task = None
            self._set(state='disconnecting', on=False, vault={**self.st['vault'], 'on': False}, error='', paused_since=0,
                      done=0, total=0, items_done=0, items_total=0, upload_step='',
                      vault_state='stopping' if self.vault_running else 'off', vault_step='', vault_done=0, vault_total=0, vault_since=0)
            self.intents.update(intents.DISCONNECT, error='', code='')
            self.ensure_running(_control=False)

    def _disconnect(self, delete_mirror: bool, delete_existing: bool = False, stop=None, expected_account=None) -> None:
        """Called only after writers have stopped. Deletion is explicit and needs no decryption key."""
        with self.recovery.gate():
            tok = drive_client.load_token(self.token_path)
            if expected_account is not None:
                pending = self.intents.find(intents.DISCONNECT)
                if tok is None and (not pending or pending['stage'] != 'signing-out'):
                    raise cloud_errors.RecoveryBlocked('The Google account changed. Review this action again for the current account.')
                if tok is not None:
                    self._check_expected_account(expected_account, self._raw_factory(tok))
            self.recovery.forget_reconnect()
            self._retire_tasks(intents.DISCONNECT, keep_rotation=not delete_mirror)
            self._set(state='disconnecting', rotation='', error='')
            try:
                if tok and delete_mirror:
                    client = self._raw_factory(tok)
                    client.stop = stop if stop is not None else threading.Event()
                    listing = client.list()
                    if delete_existing:
                        files = [f for f in listing if self._desktop_backup_file(f['name'])]
                    else:
                        key = mirror.MirrorKey.load(self.key_path)
                        if key is None:
                            raise drive_client.DriveError('This PC has no backup key. Use Delete cloud backup and disconnect to remove an inaccessible backup.')
                        owned = self._mirror_ids(client, key, listing)
                        owned |= self.recovery.library_record_ids(client, listing, key.fingerprint)
                        files = [f for f in listing if f['id'] in owned]
                    self.intents.update(intents.DISCONNECT, stage='deleting')
                    self._set(done=0, total=len(files))         # 'disconnecting' counts the deletes
                    drive_client.delete_files(client, [f['id'] for f in files], lambda done, total: self._set(done=done, total=total), ExportStopped)
            except ExportStopped:
                raise
            except Exception:
                self._set(state='off', done=0, total=0, vault_state='off')     # still signed in; the route reports the failure
                raise
            if stop and stop.is_set():
                raise ExportStopped()
            self.intents.update(intents.DISCONNECT, stage='signing-out')
            if tok:
                drive_client.revoke(tok)
            with drive_client._SAVE_LOCK:
                try:
                    drive_client.private_storage.remove(self.token_path)
                except FileNotFoundError:
                    pass
            self._clear_expired()       # no sign-in left to be expired
            if delete_mirror:
                # the copy is gone: no "last backup" either, so the next backup on this PC is a first backup again
                self.recovery.archive_state('delete')
                self._write_identity(lambda db: (db.clear_sync_state(), db.set_setting(S_EPOCH, ''), db.set_setting(S_ADOPT, ''), db.set_setting(S_ACCOUNT, ''), db.set_setting(S_LAST, '0')))
            # A superseded account switch must never delete its old account later.
            try:
                private_storage.remove(self.previous_token_path)
            except FileNotFoundError:
                pass
            self.intents.finish(intents.DISCONNECT)
            self._account_read = False
            self.writer.call(lambda db: (db.set_setting(S_PAUSED, ''), db.set_setting(S_PAUSE_RESTORE, '')))
            self._set(state='off', done=0, total=0, used=0, limit=0, files=0, size=0, skipped=0, skipped_note='', error='', paused_since=0,
                      upload_step='', phones=None, key_missing=False, vault_state='off', vault_reason='', vault_summary='', vault_skipped=0, vault_skipped_note='', **({'account': '', 'last_publish': 0} if delete_mirror else {}))

    def _retire_tasks(self, keep: str, keep_rotation: bool = False) -> None:
        """A deliberate account/backup change supersedes old work only after its workers have drained."""
        current = self.intents.find(keep)
        for it in self.intents.all():
            if it['kind'] != keep and (keep == intents.DISCONNECT or it['kind'] != intents.DISCONNECT and (not current or it['created'] <= current['created'])):
                self.intents.finish(it['kind'])
        rotation = self._rotation()
        if rotation and not keep_rotation:
            private_storage.write(self.cloud_dir / f'rotation-before-{keep}.json', json.dumps(rotation).encode())
            private_storage.remove(self.cloud_dir / 'rotation.json')
        self._set(rotation='', rotation_lock='', rotation_locked_at=0, rotation_locked_by=0)

    def _rotation(self, *, readonly=False):
        try:
            return json.loads(private_storage.read(self.cloud_dir / 'rotation.json', readonly=readonly))
        except FileNotFoundError:
            return None

    def _save_rotation(self, record):
        with self._rotation_lock:
            try:
                disk = self._rotation()
            except ValueError:
                disk = None
            if disk and disk.get('new') == record.get('new'):
                # what the click and the control thread learned only moves forward, whichever thread saves a stale copy
                if disk.get('locked_at'):
                    record.update(lock_pending=False, locked_at=disk['locked_at'])
                if disk.get('old_changes') is not None and record.get('old_changes') is None:
                    record['old_changes'] = disk['old_changes']
                if disk.get('sent'):
                    record['sent'] = True
            private_storage.write(self.cloud_dir / 'rotation.json', json.dumps(record).encode())
        self._sync_remove_intent(record)

    def _sync_remove_intent(self, record) -> None:
        """The removal task's saved stage follows the rotation's, so a restart shows the step that was last reached."""
        if record.get('stage') == 'complete':
            self.intents.finish(intents.REMOVE)
            return
        stage = 'prepared' if record.get('stage') == 'prepared' and record.get('staged') else \
            'requested' if record.get('stage') == 'prepared' else record.get('stage')
        task = self.intents.find(intents.REMOVE)
        if task and task['stage'] != stage:
            self.intents.update(intents.REMOVE, stage=stage)
            self._emit()

    def _update_rotation(self, new_text: str, **fields):
        """Change fields of the pending rotation on disk (never a copy held by another thread); None when that rotation
        is no longer the one on disk."""
        with self._rotation_lock:
            record = self._rotation()
            if not record or record.get('new') != new_text:
                return None
            record.update(fields)
            private_storage.write(self.cloud_dir / 'rotation.json', json.dumps(record).encode())
            return record

    def _mirror_ids(self, client, key, listing):
        """Every Drive id this key's mirror owns: all manifest copies and every file any of them lists (I3)."""
        from library import restore
        found = restore.manifests(client, key, listing=listing)
        if not found:
            return set()
        names = set().union(*(restore.manifest_names(key, man) for _entry, _raw, _plain, man in found))
        return {f['id'] for f in listing if f['name'] in names}

    def unpair(self, recovery_passphrase: str = '', new_passphrase: str = '', *, expected_account: str | None = None) -> str:
        """Remove all phones: record the removal, lock the phones out and save the task; `cm-sync` does the rest (S3). The click
        needs no Drive for the recovery part (the replacement records are sealed here and go up later), so a lost phone is
        locked out offline too. Nothing joins a worker: a request in flight delays the re-encrypting, never the lock-out
        (I6). A second click while the task exists is refused (A19). Returns the new key's fingerprint."""
        with self.recovery.activity('unpair', 'Locking phones out…'):
            self._check_expected_account(expected_account)
            if self.intents.find(intents.REMOVE):
                raise cloud_errors.Busy(intents.BUSY_TEXT[intents.REMOVE])
            record = self._begin_rotation(recovery_passphrase, new_passphrase, int(time.time() * 1000), expected_account=expected_account)
            fingerprint = self._rotation_key(record['new']).fingerprint
            self.intents.add(intents.REMOVE, {'new': fingerprint})
            self._sync_remove_intent(record)
            self.poke(force=True)
            return fingerprint

    def start_removal(self, draft: dict) -> str:
        """A restored copy from before an unfinished removal becomes the backup PC: run the removal again with the key and
        recovery record sealed for it at activation, so the lost phone stays out (finding 2)."""
        with self.recovery.activity('unpair', 'Locking phones out…'):
            if self.intents.find(intents.REMOVE):
                raise cloud_errors.Busy(intents.BUSY_TEXT[intents.REMOVE])
            record = self._begin_rotation('', '', int(time.time() * 1000), draft=draft)
            fingerprint = self._rotation_key(record['new']).fingerprint
            self.intents.add(intents.REMOVE, {'new': fingerprint})
            self._sync_remove_intent(record)
            self.poke(force=True)
        self.ensure_running()
        return fingerprint

    def _begin_rotation(self, recovery_passphrase, new_passphrase, clicked: int, draft=None, expected_account=None) -> dict:
        """The Remove click, before anything else (I6): record the rotation when none is pending, then lock the phones out.
        Another click while one is pending only retries the lock-out. Returns the rotation record."""
        record, fresh = self._rotation(), False
        if not record or record['stage'] == 'complete':
            if record:
                private_storage.write(self.cloud_dir / ('rotation-' + str(time.time_ns()) + '.json'), json.dumps(record).encode())
            old = self._key()
            new = self._rotation_key(draft['new']) if draft else mirror.MirrorKey.generate()
            replacement = (self.recovery.draft_replacement(draft) if draft
                           else self.recovery.prepare_rotation(new, old, recovery_passphrase, new_passphrase))
            token = drive_client.load_token(self.token_path)
            record = {'stage': 'prepared', 'old': old.text(), 'new': new.text(), 'owned': [],
                      'account': self.st.get('account', ''),
                      'session': hashlib.sha256(token['refresh_token'].encode()).hexdigest() if token else '',
                      # the lock-out (I6): `old_changes` is the old-key change files already in Drive at the click (None
                      # until a listing worked), `lock_pending` until the old access record is gone
                      'clicked': clicked, 'old_changes': None, 'lock_pending': True, 'locked_at': 0,
                      'locked_by': self._grant_bound(old, clicked)}
            if replacement:
                record['recovery'] = replacement
            if expected_account is not None:
                record['expected_account'] = expected_account
            self._save_rotation(record)
            fresh = True
        self._lock_status(record)
        self._set(rotation='pending', error='')
        self._control_wake.set()
        if record.get('lock_pending', True):
            self._lock_out_now(record, fresh and bool(record.get('clicked')))
            record = self._rotation() or record
        return record

    def _rotation_vault_round(self, client, key, vault: Path, retired_files=()) -> None:
        from server.map_service import VAULT_LOCK
        if not VAULT_LOCK.acquire(blocking=False):
            raise drive_client.DriveError('Waiting for the vault; retry key rotation when it is free.')
        try:
            owner = self.writer.read(lambda db: db.get_setting('obsidian_mode', '')) == 'owner'
            self._vault_round(client, key, vault, owner=owner, retired_files=retired_files)
        finally:
            VAULT_LOCK.release()

    def _rotation_prepare(self, client, stop):
        record = self._rotation()
        if not record or record['stage'] == 'complete':
            return record
        self._check_expected_account(record.get('expected_account'), client)
        old, new = self._rotation_key(record['old']), self._rotation_key(record['new'])
        if stop.is_set():
            raise ExportStopped()
        if not self._account_read or not self.st.get('account'):
            raise drive_client.DriveError('Confirm the Google account before resuming rotation.')
        if record['account'] and self.st.get('account') != record['account']:
            raise drive_client.DriveError('Rotation belongs to another account; reconnect that account to resume.')
        token = drive_client.load_token(self.token_path)
        if not record['account'] and record.get('session') and (not token or hashlib.sha256(token['refresh_token'].encode()).hexdigest() != record['session']):
            raise drive_client.DriveError('Rotation belongs to another account session; reconnect that account to resume.')
        if not record['account']:
            record['account'] = self.st['account']
            self._save_rotation(record)
        self._vault_tls.stop = stop
        # A resumed rotation owns both publishers until verification and cleanup finish.
        self._end_vault()
        if record['stage'] == 'prepared' and not record.get('staged'):
            if entitlements.feature_enabled('phone_sync'):
                self._set(upload_step='Collecting pending phone changes before replacing the key…', done=0, total=0)
                self._intake(stop)
            # Old-phone vault edits are no longer accepted after Remove; publish the local vault under the new key.
            self._set(upload_step='Checking which encrypted files need to be replaced…', done=0, total=0)
            listing = client.list()
            owned = list(self._mirror_ids(client, old, listing))
            # F9: a vault blob is named by its content, so the blobs this key owns are the ones its own sealed file lists name: one
            # small download per list, status and phone record, never one per blob. The blobs are read once, by the verification
            # pass after the key switch.
            blobs = {f['name'][len(vault_sync.BLOB_PREFIX):]: f['id'] for f in listing if f['name'].startswith(vault_sync.BLOB_PREFIX)}
            small = [f for f in listing if f['name'].startswith((vault_sync.INDEX_PREFIX, vault_sync.STATUS_PREFIX, mirror.PHONE_PREFIX))]
            for index, f in enumerate(small):
                if stop.is_set():
                    raise ExportStopped()
                self._set(done=index, total=len(small))
                name = f['name']
                try:
                    if name.startswith(vault_sync.INDEX_PREFIX):
                        device, files = vault_sync.decode_index(old.open(vault_sync.INDEX_LOGICAL, client.download(f['id'])))
                        if name == vault_sync.index_name(old, device):
                            owned.append(f['id'])
                            owned.extend(blobs[cid] for cid in set(files.values()) if cid in blobs)
                    elif name.startswith(mirror.PHONE_PREFIX):
                        mirror.open_phone(old, name, client.download(f['id']))
                        owned.append(f['id'])
                    elif name == vault_sync.status_name(old):
                        old.open(vault_sync.STATUS_LOGICAL, client.download(f['id']))
                        owned.append(f['id'])
                except (mirror.MirrorKeyError, ValueError):
                    pass  # Another library's namespace is never ours to remove.
            if stop.is_set():
                raise ExportStopped()
            if record.get('recovery') and not record.get('sent'):
                # D1: the replacement recovery records (and, with a new passphrase, the old key's) go up before the key switches
                # when the click could not send them; the user's recovery file comes after the switch
                self._set(upload_step='Saving the replacement recovery record to Google Drive…', done=0, total=0)
                self.recovery.upload_replacement(client, record['recovery'], new, old)
            record.update(staged=True, sent=True, owned=sorted(set(owned)))
            self._save_rotation(record)
        if record['stage'] == 'prepared':
            record.update(stage='publishing')
            self._save_rotation(record)
        if record.get('recovery'):
            self._set(upload_step='Activating the replacement recovery key…', done=0, total=0)
            self.recovery.commit_rotation(client, new, record['recovery'])
        new.save(self.key_path)
        self._write_identity(lambda db: db.set_setting(S_ADOPT, new.fingerprint))
        self._set(rotation='pending')
        return record

    def _rotation_files(self, items, work, stop, workers: int = 4):
        """Bound reads/deletes to `workers` requests in flight (a sliding window: a slow file never idles the others);
        after a failure or pause nothing new starts, and in-flight successes are drained and yielded first."""
        items = iter(items)
        with ThreadPoolExecutor(workers, thread_name_prefix='cm-rotate') as pool:
            def one(item):
                if stop.is_set():
                    raise ExportStopped()
                return work(item)

            running, error, end = {}, None, object()
            while True:
                while error is None and not stop.is_set() and len(running) < workers:
                    item = next(items, end)
                    if item is end:
                        break
                    running[pool.submit(one, item)] = item
                if not running:
                    break
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    item = running.pop(future)
                    try:
                        result = future.result()
                    except Exception as e:
                        error = error or e
                    else:
                        yield item, result
            if error:
                raise error
            if stop.is_set():
                raise ExportStopped()

    def _rotation_finish(self, client, key, record, stop):
        if not record or record['stage'] == 'complete':
            return
        if stop.is_set():
            raise ExportStopped()
        self._checking_copy = True
        try:
            self._set(upload_step='Verifying the uploaded library with the replacement key…', done=0, total=0)
            from library import restore
            found = restore.manifests(client, key)
            if not found:
                raise drive_client.DriveError('The re-encrypted library has no manifest yet. Retry the upload.')
            man = found[0][3]
            whole, read = sum(int(e.get('size') or 0) for e in man['files'].values()), 0       # plain sizes: the pass shows bytes beside files (S7)
            self._set(done=0, total=len(man['files']), bytes_done=0, bytes_total=whole)
            big = threading.BoundedSemaphore(VERIFY_BIG_AT_ONCE)
            def verify(item):
                logical, entry = item
                size = int(entry.get('size') or 0)
                held = big if size > VERIFY_BIG else None       # a file is read into memory whole: few big ones at a time
                if held:
                    held.acquire()
                try:
                    blob = client.download(entry['id'])
                    if logical.startswith('videos/'):
                        key.open_file(logical, blob, entry)
                    else:
                        key.open(logical, blob)
                finally:
                    if held:
                        held.release()
                return size

            for index, (_, size) in enumerate(self._rotation_files(man['files'].items(), verify, stop, workers=VERIFY_WORKERS)):
                read += size
                self._set(done=index + 1, total=len(man['files']), bytes_done=read, bytes_total=whole)
            folder = self.writer.read(lambda db: db.get_setting('obsidian_vault', '') or '')
            if folder and Path(folder).is_dir():
                self._set(upload_step='Uploading and verifying the vault with the replacement key…', done=0, total=0)
                self._rotation_vault_round(client, key, Path(folder), retired_files=record['owned'])
                if self.st.get('vault_state') != 'idle':
                    raise drive_client.DriveError('Rotated vault publication is incomplete; retry before cleanup.')
                listing = client.list()
                idx = next(f for f in listing if f['name'] == vault_sync.index_name(key, 'pc'))
                _, files = vault_sync.decode_index(key.open(vault_sync.INDEX_LOGICAL, client.download(idx['id'])))
                by_name = {f['name']: f for f in listing}
                blobs = set(files.values())
                self._set(upload_step='Verifying the uploaded Obsidian vault…', done=0, total=len(blobs))
                def verify_vault(cid):
                    f = by_name[vault_sync.blob_name(cid)]
                    data = key.open(vault_sync.blob_logical(cid), client.download(f['id']))
                    if key.content_id(data) != cid:
                        raise mirror.MirrorKeyError('Rotated vault verification failed.')
                for index, _ in enumerate(self._rotation_files(blobs, verify_vault, stop)):      # sizes unknown here: four at a time
                    self._set(done=index + 1)
        except ExportStopped:
            raise
        except Exception:
            task = self._live_task_view()
            if task and task['kind'] == intents.REMOVE:
                self._failed_task = task
            raise
        finally:
            self._checking_copy = False
        self._set(emit=False, upload_step='Checking the old encrypted files to delete…', done=0, total=0)
        record['stage'] = 'cleanup'
        self._save_rotation(record)
        listing = client.list()
        present = {f['id'] for f in listing}
        # the old key's phone-access record goes with the rest when the click's lock-out never got through (I6)
        old_key = self._rotation_key(record['old'])
        grants = {old_key.name(path) for path in sync_license.CONTROL_LOGICALS}
        record['owned'] += [f['id'] for f in listing if f['name'] in grants and f['id'] not in record['owned']]
        record['cleanup_total'] = max(record.get('cleanup_total', 0), len(record['owned']))
        record['owned'] = [fid for fid in record['owned'] if fid in present]
        self._save_rotation(record)
        self._set(upload_step='Removing the old encrypted copies to finish unpairing…',
                  done=record['cleanup_total'] - len(record['owned']), total=record['cleanup_total'])
        def deleted(ids):
            confirmed = set(ids)
            record['owned'] = [fid for fid in record['owned'] if fid not in confirmed]
            # Checkpoint each confirmed batch, not every file; an interrupted request is safely retried as missing.
            self._save_rotation(record)
            self._set(done=record['cleanup_total'] - len(record['owned']))

        remaining = list(record['owned'])
        window = drive_client.DELETE_BATCH_SIZE * drive_client.DELETE_WORKERS
        for start in range(0, len(remaining), window):
            if stop.is_set():
                raise ExportStopped()
            # Each window rechecks ownership through the guarded client before deleting.
            drive_client.delete_files(client, remaining[start:start + window], stopped=ExportStopped, deleted=deleted)
        self.recovery.prune_old_key(client, record)        # D5: setups of the old key open nothing now
        # Retain the old key locally to recover pending old edits; never apply them automatically.
        if not record.get('locked_at'):
            record.update(lock_pending=False, locked_at=int(time.time() * 1000))     # the cleanup removed the old access record too
        record['stage'] = 'complete'
        self._save_rotation(record)
        self._lock_status(self._rotation())
        self._write_identity(lambda db: db.set_setting(S_ADOPT, ''))
        self._set(rotation='complete', error='')
        if entitlements.feature_enabled('phone_sync') and self.writer.read(lambda db: db.get_setting(S_VAULT, '') == 'on'):
            self.start_vault()

    def account(self) -> str:
        """The account the mirror uploads to, for the pairing link (the phone checks its Google account against it).
        Read from Google when this run has not yet: a link made before that carried no account, so the phone could not
        tell a wrong one."""
        if not self.st['account']:
            tok = drive_client.load_token(self.token_path)
            if tok is not None:
                self._read_account(self._factory(tok))
        return self.st['account']

    def mirror_key(self) -> mirror.MirrorKey:
        """The mirror key, made on first use (the pairing QR carries it)."""
        with self.recovery.gate(), self.license_lock:
            self.require_license()
            sync_license.signer(self.control_key_path, create=True)
            rotation = self._rotation()
            if rotation and rotation['stage'] != 'complete':
                key = self._rotation_key(rotation['new'])
                task = self.intents.find(intents.REMOVE)
                if not task or task['payload'].get('new') != key.fingerprint:
                    raise drive_client.DriveError('Another library has a pending phone removal. Finish it there before pairing.')
                return key      # D15: a phone added now gets the new key and waits for its copy
            if self._key_missing():
                raise drive_client.DriveError(KEY_MISSING)
            key = self._key()
            if self._key_conflict(key):
                raise drive_client.DriveError(KEY_CONFLICT)
        return key

    def license_public_key(self):
        with self.recovery.gate(), self.license_lock:
            self.require_license()
            return sync_license.public(sync_license.signer(self.control_key_path, create=True))

    def send_keys(self, ai: dict) -> dict:
        """The AI keys ticked for a phone being paired, left in Drive sealed with a one-time key
        (library/mirror.py pair_drop): {'t': one-time key, 'tx': expiry} for the pairing link,
        which never carries the keys themselves. Called from the pairing request."""
        self.require_license()
        tok = drive_client.load_token(self.token_path)
        if tok is None:
            raise drive_client.DriveError('Sign in to Google Drive first: the AI keys reach the phone through it.')
        one, exp, name, blob = mirror.pair_drop(ai)
        generation = self._generation
        client = self._factory(tok, phone=True)
        self.recovery.guard(client)
        fid = client.upload(name, blob)
        with drive_client._SAVE_LOCK:
            current = drive_client.load_token(self.token_path)
            if generation != self._generation or not current or current.get('refresh_token') != tok['refresh_token']:
                raise drive_client.SignInCancelled('The Google account session changed.')
            transfers = self._transfers()
            transfers.append({'id': fid, 'name': name, 'session': hashlib.sha256(tok['refresh_token'].encode()).hexdigest()})
            private_storage.write(self.cloud_dir / 'pair-transfers.json', json.dumps(transfers).encode())
        return {'t': one.text(), 'tx': exp}

    def _transfers(self):
        try:
            return json.loads(private_storage.read(self.cloud_dir / 'pair-transfers.json'))
        except FileNotFoundError:
            return []

    # ── the thread ──────────────────────────────────────────────────────────
    def _client(self, tok: dict):
        cid, secret = config.google_client()
        client = drive_client.DriveClient(cid, secret, tok, self.token_path)
        if threading.current_thread().name.startswith('cm-vault'):
            client.stop = self._vault_stop
        elif threading.current_thread().name.startswith('cm-sync'):
            client.stop = self._stop
        return client

    def _read_account(self, client, generation=None, stop=None) -> None:
        """The signed-in account's address and Drive quota, from Google; stored for the next run.
        A failure leaves it unread: the next publish tries again. When Google names another account than the one
        this folder backed up to, what was published there is forgotten (`sync_state`, `cloud_epoch`), so the new
        account starts clean; the same account keeps everything (I1)."""
        generation = self._generation if generation is None else generation
        if generation != self._generation or stop and stop.is_set():
            return
        try:
            a = client.about()
        except (drive_client.DriveError, OSError):
            return
        with drive_client._SAVE_LOCK:
            if generation != self._generation or stop and stop.is_set():
                return
            before = self.writer.read(lambda db: db.get_setting(S_ACCOUNT, ''))
            other = bool(before) and before.casefold() != (a['email'] or '').casefold()

            def save(db):
                if other:
                    db.clear_sync_state()
                    db.set_setting(S_EPOCH, '')
                db.set_setting(S_ACCOUNT, a['email'])
            self._write_identity(save)
            self._set(account=a['email'], used=a['used'], limit=a['limit'])
            if other:
                self.recovery.archive_state('account-switch')
                app_console.emit('log', f'Drive mirror: signed in as {a["email"]}; the copy in {before} stays there and is no longer updated from this PC', level='warning')
            self._account_read = True
            self._clear_expired()       # Google answered for this sign-in

    def _key(self) -> mirror.MirrorKey:
        key = mirror.MirrorKey.load(self.key_path)
        if key is None:
            key = mirror.MirrorKey.generate()
            key.save(self.key_path)
        return key

    def _key_conflict(self, key: mirror.MirrorKey) -> bool:
        """The data folder's mirror was published with another key that this copy did not make (the
        installed app and the source copy share data/ but each keeps its own key in its cloud folder).
        Publishing would delete that mirror as strays and the intake would drop its phone's changes."""
        def check(db):
            stored = db.get_setting(S_EPOCH, '') or ''
            return bool(stored) and stored != key.fingerprint and db.get_setting(S_ADOPT, '') != key.fingerprint
        if not self.writer.read(check):
            return False
        if self.st.get('error') != KEY_CONFLICT:
            app_console.emit('log', 'Drive mirror: paused, another copy of Brainamon uses a different key', level='warning')
        return True

    def local_files(self) -> tuple[dict, dict]:
        """({logical: (sig, size)} of what this library would back up now, its sync_state): Update this folder compares them with
        the newer manifest (S9). The payload is read on the Writer as a publish reads it; the files are built on this thread."""
        payload, state, opts = self.writer.call(lambda db: (_payload(db), db.get_sync_state(), read_options(db)))
        return {f.name: (f.sig, f.size) for f in mirror.build_files(payload, self.data_dir, opts, self.tints())}, state

    def _other_copy_wrote(self) -> bool:
        """`_key_conflict` for the key this PC has, asked before the recovery guard so that a backup made by the other copy
        reads as that (T15), never as "restore it" (A18). It never makes a key: with none (a reinstall) the guard says so."""
        key = mirror.MirrorKey.load(self.key_path)
        return key is not None and self._key_conflict(key)

    def _tick_intake(self, stop: threading.Event) -> None:
        """Poll on the sync owner thread, including while uploads run on workers."""
        if stop.is_set() or self._closing:
            raise ExportStopped()
        if self._look_now:
            self._look_now, self._next_intake, self._gap = False, 0.0, INTAKE
        if not entitlements.feature_enabled('phone_sync') or time.monotonic() < self._next_intake:
            return
        try:
            found = self._intake(stop)
            if stop.is_set():
                raise ExportStopped()
            if found:
                self._force = self._force_manifest = True
            self._gap = INTAKE if found else min(self._gap * 2, INTAKE_MAX)
        except ExportStopped:
            raise
        except Exception as e:      # never the end of the thread: uploads go on
            if stop.is_set():
                raise ExportStopped() from e
            app_console.emit('log', 'Drive mirror: phone changes not applied', level='error', error=e)
            self._set(last_intake=int(time.time() * 1000), intake_summary=f'{INTAKE_FAILED}: {e}')
        self._next_intake = time.monotonic() + self._gap

    def _loop(self, stop: threading.Event) -> None:
        finished = False        # a one-shot thread that found nothing left to do (D4)
        try:
            with self._pause_control:
                if stop.is_set() or (self.st['paused_since'] and not self.intents.find(intents.DISCONNECT)):
                    return
            seen, changed_at, wait_until = None, 0.0, 0.0
            self._next_intake, self._gap = 0.0, INTAKE
            while not stop.is_set() and not self._closing:
                try:
                    if self.st['state'] == 'starting':
                        self._set(upload_step='Checking for pending phone changes in Google Drive…', upload_since=int(time.time() * 1000))
                    self._run_intents(stop)
                    if self.st['paused_since'] and not self.intents.find(intents.DISCONNECT):
                        break
                    if any(i['kind'] == intents.DISCONNECT or
                           i['kind'] in (intents.RESET, intents.SWITCH) and i['stage'] == 'queued' or
                           i['kind'] == intents.SWITCH and i['stage'] == 'signing-in' and not self.signed_in()
                           for i in self.intents.all()):
                        self._wake.wait(POLL)
                        self._wake.clear()
                        continue
                    if stop.is_set():
                        break
                    self._tick_intake(stop)
                except ExportStopped:
                    break
                try:
                    if stop.is_set():
                        break
                    if entitlements.feature_enabled('phone_sync'):
                        self._retry_thumbs()
                        self._retry_synth()
                except Exception as e:
                    app_console.emit('log', 'Drive mirror: a job for the phone did not start', level='warning', error=e)
                try:
                    sig = (self.writer.read(_signature), _files_stamp(self.data_dir))
                except Exception as e:          # the Writer is shutting down
                    app_console.emit('log', 'Drive mirror: could not read the library', level='warning', error=e)
                    sig = seen
                now = time.monotonic()
                if self._force:
                    due = True
                elif sig != seen:
                    changed_at = changed_at or now
                    due = now - changed_at >= DEBOUNCE and now >= wait_until
                else:
                    due = False
                if due and self.intents.find(intents.UPDATE):
                    due = False     # this folder is being replaced by the newer library (S9): nothing goes up before the claim
                if due:
                    self._force = False
                    ok = self._publish(stop)
                    one = self.intents.find(intents.ONE_SHOT)
                    if one and one['stage'] == 'running':
                        self.intents.finish(intents.ONE_SHOT)       # done, or failed with its reason in the status: Try again asks anew
                    if ok:
                        seen, changed_at, wait_until = sig, 0.0, 0.0
                    else:
                        retry = POLL if self.st.get('error_code') == 'worker_stopping' else RETRY
                        changed_at, wait_until = changed_at or now, now + retry
                if self._oneshot and not self._wanted():
                    finished = True
                    break
                self._wake.wait(POLL)
                self._wake.clear()
        finally:
            with self._life:
                mine = self._thread is threading.current_thread()
                if mine:
                    self._thread = None
                resume, self._resume = self._resume and mine, False
            if mine:
                if resume:
                    self._continue_mirror()     # before the settle: 'starting' replaces 'stopping' without a flicker of 'off'
                if finished and self.st['state'] not in ('error', 'signed-out', 'stopping', 'signing-in'):
                    self._set(state='off', done=0, total=0, upload_step='')
                self._finish_stop()

    def _vault_loop(self, stop: threading.Event) -> None:
        """The Obsidian vault rounds, on their own thread: one round can send thousands of files, and
        the phone mirror must keep uploading meanwhile."""
        try:
            with self._pause_control:
                if stop.is_set() or self.st['paused_since']:
                    return
            self._vault_tls.stop = stop
            next_vault = 0.0
            while not stop.is_set() and not self._closing and entitlements.feature_enabled('phone_sync'):
                if self._vault_now:
                    self._vault_now, next_vault = False, 0.0
                if time.monotonic() >= next_vault:
                    next_vault = time.monotonic() + VAULT_EVERY
                    try:
                        self._vault_tick()
                    except Exception as e:      # never the end of the thread
                        app_console.emit('log', 'Vault sync failed', level='warning', error=e)
                        if not stop.is_set():
                            self._vault_announce(vault_state='error', vault_reason=str(e))
                if stop.is_set():
                    break
                self._vault_wake.wait(POLL)
                self._vault_wake.clear()
        finally:
            with self._life:
                mine = self._vault_thread is threading.current_thread()
                if mine:
                    self._vault_thread = None
                resume, self._vault_resume = self._vault_resume and mine, False
            if mine:
                if resume:
                    self._continue_vault()
                self._finish_stop()

    def _wanted(self) -> bool:
        """A one-shot thread stays while backup is on or a task waits for it; otherwise it ends (D4). A task waiting for the user
        (an update waiting for Restart now) does not keep it."""
        if any(not i.get('error') and i['stage'] not in intents.WAITING.get(i['kind'], ()) for i in self.intents.all()):
            return True
        try:
            return self.writer.read(lambda db: db.get_setting(S_ON, '') == 'on')
        except Exception:
            return False

    def _tick(self, stop: threading.Event) -> None:
        """Between upload requests: the phone's changes, then a task that wants the slot ends this export (S3)."""
        self._tick_intake(stop)
        self.recovery.run_queued_check()        # a recovery check that met this upload runs here, uploads carry on (F10, S8)
        if self.intents.preempting():
            self._force = True
            raise ExportInterrupted()

    def _run_intents(self, stop: threading.Event) -> None:
        """Run what handlers saved, at the top of the loop and never in the middle of an upload request (S3). A removal needs
        nothing here: its stages run inside the publish (`_rotation_prepare`, `_rotation_finish`)."""
        disconnect = self.intents.find(intents.DISCONNECT)
        if not disconnect and self.st['paused_since']:
            return
        if disconnect:
            if disconnect.get('error') or stop.is_set():
                return
            if self.vault_running or (self._control_thread and self._control_thread.is_alive()) or (self.recovery.thread and self.recovery.thread.is_alive()):
                self._set(state='disconnecting', upload_step='Stopping current work…')
                return
            try:
                self._disconnect(disconnect['payload'].get('delete_mirror', False), disconnect['payload'].get('delete_existing', False), stop,
                                 expected_account=disconnect['payload'].get('expected_account'))
                stop.set()
            except ExportStopped:
                raise
            except cloud_errors.Busy:
                return       # An atomic recovery write finishes before the accepted disconnect takes over.
            except Exception as e:
                c = self.classified(e, fallback=str(e))
                self.intents.update(intents.DISCONNECT, error=c['message'], code=c['code'])
                self._set(state='error', error=c['message'], error_code=c['code'], error_action=c['action'])
            return
        self.recovery.run_queued_check()
        for it in self.intents.all():
            if stop.is_set() or self._closing:
                return
            kind = it['kind']
            if kind in (intents.RESET, intents.SWITCH) and it['stage'] == 'queued':
                self._vault_stop.set()
                self._vault_wake.set()
                self._control_stop.set()
                self._control_wake.set()
                if self.vault_running or (self._control_thread and self._control_thread.is_alive()):
                    return
            try:
                if kind == intents.ONE_SHOT and it['stage'] == 'queued':
                    self.intents.update(kind, stage='running')
                    self._force = True
                elif kind == intents.UPDATE:
                    if it.get('error'):
                        continue
                    if it['stage'] in ('queued', 'downloading'):
                        self.recovery.run_update(it, stop)
                    elif it['stage'] == 'claim':
                        self.recovery.claim_update(it, stop)
                elif it['stage'] == intents.FIRST_STAGE[kind] and not it.get('error'):
                    if kind == intents.ENROLL:
                        self.recovery.run_enroll(it)
                    elif kind == intents.SWITCH:
                        with self.recovery.gate():
                            self._switch_signout(it, stop)
                    elif kind == intents.RESET:
                        with self.recovery.gate():
                            self._reset_begin(it, stop)
                    if kind in (intents.RESET, intents.SWITCH):
                        return
            except ExportStopped:
                raise
            except cloud_errors.Busy:
                return       # A short atomic recovery write still owns the slot; the accepted task retries itself.
            except Exception as e:
                c = self.classified(e, fallback=str(e) if not isinstance(e, drive_client.DriveError) else '')
                self.intents.update(kind, error=c['message'], code=c['code'])
                app_console.emit('log', f'Drive mirror: {kind} did not finish', level='warning', error=c['message'])
                self._emit()

    def _unless_stopped(self, stop: threading.Event, state: str) -> str:
        """`state`, or the current one once this run is stopped: 'stopping' / 'disconnecting' stays up."""
        return self.st['state'] if stop.is_set() else state

    def _publish(self, stop: threading.Event | None = None) -> bool:
        stop = stop or self._stop
        with self._publishing:
            return self._publish_locked(stop)

    def _publish_locked(self, stop: threading.Event) -> bool:
        force_manifest = False
        if stop.is_set() or self._closing:
            return False
        self._failed_task = None
        tok = drive_client.load_token(self.token_path)
        if tok is None:
            self._set(state='signed-out', error='Sign in to Google Drive again to keep uploading.')
            stop.set()
            return False
        reset = self.intents.find(intents.RESET)
        if reset and reset['stage'] == 'cleanup':
            self.intents.update(intents.RESET, stage='backing-up', error='', code='')
        try:
            self._set(upload_step='Checking the Google account and library ownership…', upload_since=int(time.time() * 1000), done=0, total=0, items_done=0, items_total=0)
            pending = self._rotation()
            client = self._factory(tok)
            client.stop = stop
            if self._other_copy_wrote():
                # before the recovery guard: another copy's backup must not read as "restore it" (A18)
                self._set(state=self._unless_stopped(stop, 'error'), error=KEY_CONFLICT, error_code=cloud_errors.OTHER_COPY, error_action=cloud_errors.NONE)
                return False
            self.recovery.resume_rotation(pending, stop)
            self.recovery.guard(client)
            if not self._account_read:
                self._read_account(client, stop=stop)
            rotation = self._rotation_prepare(client, stop)
            key = self._key()
            # the stored name can be stale (another account, the development Drive): read it again
            if not self._account_read:
                self._read_account(client)
            epoch = key.fingerprint      # sign_out clears the state, so another account starts clean too
            if self._key_conflict(key):
                self._set(state=self._unless_stopped(stop, 'error'), error=KEY_CONFLICT, error_code=cloud_errors.OTHER_COPY, error_action=cloud_errors.NONE)
                return False

            def load(db):
                if db.get_setting(S_EPOCH, '') != epoch:     # a new key (Unpair, a first sign-in): everything goes up again
                    db.clear_sync_state()
                    db.set_setting(S_EPOCH, epoch)
                    db.set_setting(S_ADOPT, '')
                return _payload(db), db.get_sync_state(), read_options(db)
            self._set(upload_step='Preparing the encrypted library for upload…', done=0, total=0)
            payload, state, opts = self._write_identity(load)
            self._set(state=self._unless_stopped(stop, 'publishing'), upload_step='Uploading the encrypted library…', done=0, total=0, error='')
            force_manifest, self._force_manifest = self._force_manifest or payload['receipts'] != self._published_receipts, False
            target = DriveMirrorTarget(
                client, key, state, self.data_dir, opts, tints=self.tints(), stop=stop,
                tmp_dir=self.cloud_dir, save=lambda put, drop: self.writer.call(lambda db: db.save_sync_state(put, drop)),
                force_manifest=force_manifest, tick=lambda: self._tick(stop), skipped_before=self._published_skipped)
            t0 = time.monotonic()
            res = target.export(payload, progress=lambda d, t: self._set(done=d, total=t, bytes_done=target.bytes_done, bytes_total=target.bytes_total,
                                                                        items_done=target.items_done, items_total=target.items_total))
            if stop.is_set():
                raise ExportStopped()
            if not res.errors:
                self._rotation_finish(client, key, rotation, stop)
        except ExportStopped as e:
            self._force_manifest = self._force_manifest or force_manifest
            if isinstance(e, ExportInterrupted):
                self._force = True          # a task took the slot between requests: this export goes on right after it
            # stopped: whoever stopped it (Stop uploading, Disconnect) sets the state, so 'stopping'
            # or 'disconnecting' stays up; an old run that ended after Off and On says nothing either
            if stop is self._stop and not stop.is_set():
                self._set(state='idle')
            return False
        except drive_client.DriveError as e:
            if stop.is_set():
                return False
            c = self.classified(e)
            # when the other PC wrote (not_owner, foreign_backup): the page names the day
            self._set(state=self._unless_stopped(stop, 'error'), error=c['message'], error_code=c['code'], error_action=c['action'], error_at=getattr(e, 'at', 0))
            app_console.emit('log', 'Drive mirror: publish failed', level='warning', error=c['message'])
            return False
        except Exception as e:
            c = self.classified(e, fallback=f'Upload to Google Drive failed: {e}')
            self._set(state=self._unless_stopped(stop, 'error'), error=c['message'], error_code=c['code'], error_action=c['action'])
            app_console.emit('log', 'Drive mirror: publish failed', level='error', error=e)
            return False
        if stop.is_set():
            return False
        now_ms = int(time.time() * 1000)
        summary = (f'{res.uploaded} file(s) sent ({res.bytes_sent / 1_048_576:.1f} MB), {res.deleted} removed'
                   if res.changed else 'Already up to date')
        if res.duplicates:
            summary += f'; {res.duplicates} duplicate cop{"y" if res.duplicates == 1 else "ies"} of this backup removed'
        if res.skipped:
            summary += f'; {len(res.skipped)} not uploaded (over the size limit recovery accepts)'
        if res.errors:
            summary += f'; {len(res.errors)} could not be sent and are tried again next time'
            for name, msg in res.errors[:20]:
                app_console.emit('log', f'Drive mirror: {name} not sent', level='warning', error=msg)
        self.writer.call(lambda db: db.set_setting(S_LAST, str(now_ms)))
        self._set(state=self._unless_stopped(stop, 'idle'), done=0, total=0, files=res.files, size=res.size, last_publish=now_ms,
                  skipped=len(res.skipped), skipped_note=mirror.skipped_note(len(res.skipped)), last_summary=summary, error='')
        self._clear_expired()
        if res.changed:
            app_console.emit('log', f'Drive mirror published in {time.monotonic() - t0:.0f} s: {summary}')
        if not res.errors:
            self._published_receipts = payload['receipts']
            self._published_skipped = dict(res.skipped)
            if self.intents.find(intents.RESET):
                self.intents.update(intents.RESET, payload={'uploaded_items': target.items_done, 'uploaded_items_total': target.items_total, 'uploaded_files': res.files})
            self._after_complete_publish(stop)
        return not res.errors

    # ── Obsidian vault sync (projects/vault-sync) ───────────────────────────
    def reset_vault_history(self) -> None:
        """Off/on starts a fresh merge, retaining membership and identities needed by Reclaim."""
        from server.map_service import VAULT_LOCK
        with VAULT_LOCK:
            path = self.cloud_dir / VAULT_STATE
            try:
                st = json.loads(path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                return
            st['devices'] = st.get('devices') or {d: False for d in (st.get('bases') or {})}
            st.update(bases={}, cache={}, orphans={}, index_sig='')
            _save_vault_state(path, st)
            self._set(vault_devices=None, vault_members=sorted(st['devices']))

    def confirm_vault(self) -> None:
        self.require_license()
        """"Apply anyway" after a braked round: the next round may delete."""
        self._vault_force = True
        self.vault_now()

    def drop_device(self, device: str) -> int:
        """Explicitly forget a phone's list, membership and PC base. Its local phone state is unchanged."""
        self.require_license()
        from server.map_service import VAULT_LOCK
        if not VAULT_LOCK.acquire(blocking=False):
            raise drive_client.DriveError('Waiting for the vault; retry dropping this phone when it is free.')
        try:
            self._set(vault_devices=None)
            tok = drive_client.load_token(self.token_path)
            if tok is None:
                raise drive_client.DriveError('Sign in to Google Drive first.')
            client, key = self._factory(tok, phone=True), self._key()
            self.recovery.guard(client)
            name = vault_sync.index_name(key, device)
            n = 0
            for f in client.list():
                if f['name'] == name:
                    client.delete(f['id'])
                    n += 1
            sp = self.cloud_dir / VAULT_STATE
            st = _load_vault_state(sp, key.fingerprint)
            st['devices'].pop(device, None)
            st['bases'].pop(device, None)
            _save_vault_state(sp, st)
            self._set(vault_members=sorted(st['devices']))
            return n
        finally:
            VAULT_LOCK.release()

    def vault_now(self) -> None:
        """Sync now: 'starting' at once (unless a round runs), then the vault thread takes a round."""
        self.require_license()
        if not self.vault_running or self._vault_stop.is_set():
            return
        if self.st['vault_state'] != 'syncing':
            self._set(vault_state='starting', vault_reason='')
        self._vault_now = True
        self._vault_wake.set()

    def _vault_stopped(self) -> bool:
        """True on a vault thread that Stop syncing or Disconnect ended: its round no longer reports."""
        stop = getattr(self._vault_tls, 'stop', None)
        key = getattr(self._vault_tls, 'key', None)
        return (self._closing or not entitlements.feature_enabled('phone_sync') or bool(stop and stop.is_set())
                or bool(key and self._vault_key_retired(key)))

    def _vault_key_retired(self, key) -> bool:
        rotation = self._rotation(readonly=True)
        return bool(rotation and rotation['old'] == key.text())

    def _vault_tick(self) -> None:
        self.require_license()
        on, folder, mode = self.writer.read(lambda db: (db.get_setting(S_VAULT, '') == 'on', db.get_setting('obsidian_vault', '') or '',
                                                        db.get_setting('obsidian_mode', '')))
        if not on:                  # turned off under it: the thread ends
            if self.st['vault_state'] != 'off':
                self._set(vault_state='off', vault_reason='', vault_summary='', vault_skipped=0, vault_skipped_note='')
            stop = getattr(self._vault_tls, 'stop', None)
            if stop:
                stop.set()
            return
        vault = Path(folder) if folder else None
        if vault is None or not vault.is_dir():
            self._vault_announce(vault_state='error', vault_reason='Pick your vault folder in the Export window (classic export) or set up a Brainamon vault in Settings > Obsidian.')
            return
        from server.map_service import VAULT_LOCK
        # every write inside the vault folder takes the vault lock (spec decision 7); a round can hold it for
        # hours, so this round never waits: the next tick tries again
        if not VAULT_LOCK.acquire(blocking=False):
            if self.st['vault_state'] in ('starting', 'idle'):
                self._set(vault_state='idle', vault_summary='Waiting for the vault')
            return
        try:
            current = self.writer.read(lambda db: (db.get_setting(S_VAULT, '') == 'on', db.get_setting('obsidian_vault', '') or '',
                                                   db.get_setting('obsidian_mode', '')))
            if current != (on, folder, mode):
                return
            tok = drive_client.load_token(self.token_path)
            if tok is None:
                self._set(vault_state='error', vault_reason='Sign in to Google Drive first.')
                return
            key = self._key()
            if self._key_conflict(key):
                self._vault_announce(vault_state='error', vault_reason=KEY_CONFLICT)
                return
            # an owner vault (obsidian_mode, spec 1b) brings its manifest into the round; a classic vault syncs as before
            self._vault_round(self._factory(tok, phone=True), key, vault, owner=mode == 'owner')
        finally:
            VAULT_LOCK.release()

    def _vault_report(self, client, key, push=False, **kw) -> None:
        """Set the vault fields and seal them into Drive (`vs-`), where the phone's Vault panel reads the PC's
        state, step, done/total and since (when the step began, ms). Mid-round progress uploads at most every VAULT_STATUS_EVERY seconds.
        Silent once Stop syncing ended this round's thread."""
        if self._vault_stopped():
            return
        if kw:
            self._set(**kw)
        now = time.monotonic()
        if not push and now - self._vault_status_at < VAULT_STATUS_EVERY:
            return
        if not isinstance(client, _GuardedClient):
            self.recovery.guard(client)
        self._vault_status_at = now
        with self._lock:
            body = {k[len('vault_'):]: v for k, v in self.st.items() if k.startswith('vault_')}
        body['at'] = int(time.time() * 1000)
        try:
            self._vault_status_id = client.upload(
                vault_sync.status_name(key), data=key.seal(vault_sync.STATUS_LOGICAL, json.dumps(body).encode('utf-8')),
                file_id=self._vault_status_id)
        except drive_client.DriveError as e:     # the phone just sees an older status
            self._vault_status_id = ''
            app_console.emit('log', 'Vault sync: status not sent to the phone', level='warning', error=e)

    def _vault_announce(self, **kw) -> None:
        """Set the vault fields and tell the phone, outside a round (Stop syncing, an error before a round starts):
        a round reports its own progress, but without this the status in Drive keeps the last round's words, and the
        phone shows 'syncing' or 'in step' for a PC that stopped. Best effort: the fields are set either way."""
        tok = drive_client.load_token(self.token_path)
        if tok is None:
            self._set(**kw)
            return
        try:
            client, key = self._factory(tok, phone=True), self._key()
            if not self._vault_status_id:
                self._vault_status_id = next((f['id'] for f in client.list() if f['name'] == vault_sync.status_name(key)), '')
            self._vault_report(client, key, push=True, **kw)
        except (drive_client.DriveError, mirror.MirrorKeyError, OSError) as e:
            self._set(**kw)
            app_console.emit('log', 'Vault sync: status not sent to the phone', level='warning', error=e)

    def _vault_round(self, client, key, vault: Path, owner: bool = False, *, retired_files=()) -> None:
        previous = getattr(self._vault_tls, 'key', None)
        self._vault_tls.key = key
        try:
            self._vault_round_active(client, key, vault, owner, retired_files=retired_files)
        finally:
            self._vault_tls.key = previous

    def _vault_round_active(self, client, key, vault: Path, owner: bool = False, *, retired_files=()) -> None:
        """One PC round; the caller holds VAULT_LOCK. `owner`: a Brainamon-owned vault (obsidian_mode): its
        manifest gives the identity (vault_id), the generated set and the deletion records (spec 1b)."""
        from library import owner_vault
        from server.map_service import MANIFEST_MISSING, PHONES_UNCHECKED, phone_old
        import re
        self._set(vault_devices=None)
        self.recovery.guard(client)
        if self._vault_stopped():
            raise ExportStopped()
        sp = self.cloud_dir / VAULT_STATE
        st = _load_vault_state(sp, key.fingerprint)
        self._set(vault_members=sorted(st['devices']))
        ended = dict(vault_step='', vault_done=0, vault_total=0, vault_since=0)
        man, generated, removed = None, None, {}
        if owner:
            man = owner_vault.read_manifest(vault)
            if man is None:                       # Fred 2026-10-28: wait for Reclaim rather than change identity twice
                self._vault_report(client, key, push=True, vault_state='error', vault_reason=MANIFEST_MISSING, vault_summary='')
                return
            if man.get('pending'):
                owner_vault.settle_pending(vault, man)
                owner_vault.write_manifest(vault, man)
            identity = man['vault_id']
            generated = owner_vault.generated_paths(vault, man)
            removed = dict(man.get('removed') or {})
            st['vault_ids'][_folder_key(vault)] = identity
        else:
            identity = vault_sync.path_identity(vault)
        # vault identity (spec 1b decision 4): another identity (another folder, a Move, a Reclaim with no recorded
        # id) makes this round non-destructive: the bases are dropped, so nothing is trashed or lost and differences
        # become conflict copies as in a first sync. A state from before 1b recorded only the folder (adopted here).
        fresh = (st['vault'] != identity) if st['vault'] else bool(st['folder'] and st['folder'] != str(vault))
        if fresh:
            st['bases'] = {}
            st['cache'] = {}
        st['vault'], st['folder'] = identity, ''
        _save_vault_state(sp, st)
        force, self._vault_force = self._vault_force, False
        listing = client.list()
        if self._vault_stopped():
            raise ExportStopped()
        by_name = {f['name']: f for f in listing}
        self._vault_status_id = by_name.get(vault_sync.status_name(key), {}).get('id', '')
        over: dict = {}         # files left out for their size (vault_sync.MAX_FILE): counted, never called "in step"
        mine, cache = vault_sync.scan(vault, key, st['cache'], should_stop=self._vault_stopped, skipped=over)
        pc_index = vault_sync.index_name(key, 'pc')
        phones, caps, kept, unreadable, failed = {}, {}, {}, 0, 0
        retired_files = set(retired_files)
        for f in listing:
            if self._vault_stopped():
                raise ExportStopped()
            # Recovery records also start with vi-; only actual hashed vault-index names belong here.
            if not re.fullmatch(r'vi-[0-9a-f]{32}', f['name']) or f['name'] == pc_index:
                continue
            # Rotation authenticated these old-key files before switching keys; cleanup follows verification.
            if f['id'] in retired_files:
                continue
            try:
                idx = vault_sync.decode_index_full(key.open(vault_sync.INDEX_LOGICAL, client.download(f['id'])))
            except (mirror.MirrorKeyError, ValueError):
                unreadable += 1
                continue
            device = idx['device']
            if not device or device == 'pc' or f['name'] != vault_sync.index_name(key, device) or device in phones:
                unreadable += 1
                continue
            phones[device] = idx['files']
            caps[device] = idx['caps']
            kept[device] = idx['kept'] if idx['vault'] == identity else {}
        # the phone capability gate (spec 1b decision 5): an owner vault syncs only while every phone runs this app
        st['devices'].update({d: set(vault_sync.CAPS) <= c for d, c in caps.items()})
        missing = set(st['devices']) - set(phones)
        devices = [{'device': d, 'ok': ok and d in phones and not unreadable} for d, ok in sorted(st['devices'].items())]
        self._set(vault_devices=devices if not unreadable else None, vault_members=sorted(st['devices']))
        _save_vault_state(sp, st)
        if owner and (unreadable or missing):
            self._vault_report(client, key, push=True, vault_state='error', vault_reason=PHONES_UNCHECKED, vault_summary='')
            return
        old = [d['device'] for d in devices if not d['ok']]
        if owner and old:
            self._vault_report(client, key, push=True, vault_state='error', vault_reason=phone_old(old), vault_summary='')
            return
        # Missing lists are not departures. Only drop_device removes remembered membership and its base.

        def fetch(cid: str) -> bytes:
            f = by_name.get(vault_sync.blob_name(cid))
            if f is None:
                raise drive_client.DriveError(f'{cid} is not in Drive yet')
            data = key.open(vault_sync.blob_logical(cid), client.download(f['id']))
            if key.content_id(data) != cid:
                raise mirror.MirrorKeyError(f'{cid} does not match its content id')
            return data

        total = {'pulled': 0, 'trashed': 0, 'conflicts': 0}
        braked = ''
        for device, theirs in sorted(phones.items()):
            if self._vault_stopped():
                raise ExportStopped()
            plan = vault_sync.merge(st['bases'].get(device, {}), mine, theirs, 'pc', datetime.now(),
                                    generated=generated, removed=removed, kept=kept.get(device), fresh=fresh)
            if plan.brake and not force:
                braked = braked or plan.reason
                continue
            got = [0]

            def counted(cid: str) -> bytes:
                data = fetch(cid)
                got[0] += 1
                self._vault_report(client, key, vault_done=got[0])
                return data
            if plan.pull:
                self._vault_report(client, key, push=True, vault_state='syncing', vault_step="Taking the phone's changes",
                                   vault_done=0, vault_total=len(plan.pull), vault_since=int(time.time() * 1000))
            try:
                done = vault_sync.apply(vault, plan, counted, should_stop=self._vault_stopped)
            except (drive_client.DriveError, mirror.MirrorKeyError, OSError) as e:
                app_console.emit('log', f'Vault sync: {device} skipped this round', level='warning', error=e)
                unreadable += 1
                failed += 1
                continue
            for k in total:
                total[k] += done[k]
            st['bases'][device] = plan.new_base
            if done['pulled'] or done['trashed']:
                mine, cache = vault_sync.scan(vault, key, cache, should_stop=self._vault_stopped, skipped=over)
        sent = 0
        if not braked and not failed:
            by_id = {}
            for rel, cid in mine.items():
                by_id.setdefault(cid, rel)
            pending = [(cid, rel) for cid, rel in by_id.items() if vault_sync.blob_name(cid) not in by_name]
            if pending:
                self._vault_report(client, key, push=True, vault_state='syncing', vault_step='Sending to Drive',
                                   vault_done=0, vault_total=len(pending), vault_since=int(time.time() * 1000))
                sent = self._vault_send(client, key, vault, pending)
            if self._vault_stopped():
                raise ExportStopped()
            if man is not None:
                # deletion records (spec 1b decision 2) stay until every phone list has dropped the path; a path the
                # PC has again (rendered again, or taken back as the user's file) is an ordinary listed file
                keep = {r: h for r, h in removed.items() if r not in mine and
                        (unreadable or missing or any(r in files for files in phones.values()))}
                if keep != (man.get('removed') or {}):
                    man['removed'] = keep
                    owner_vault.write_manifest(vault, man)
                removed = keep
            index = vault_sync.encode_index(mine, 'pc', vault=identity, generated=generated, removed=removed)
            sig = hashlib.sha256(index).hexdigest()
            if sig != st['index_sig'] or pc_index not in by_name:
                client.upload(pc_index, data=key.seal(vault_sync.INDEX_LOGICAL, index), file_id=by_name.get(pc_index, {}).get('id', ''))
                st['index_sig'] = sig
            if not unreadable and not missing:
                referenced = set(mine.values())
                for files in phones.values():
                    referenced.update(files.values())
                now, orphans = time.time(), {}
                for name, f in by_name.items():
                    if name.startswith(vault_sync.BLOB_PREFIX) and name[len(vault_sync.BLOB_PREFIX):] not in referenced:
                        if self._vault_stopped():
                            raise ExportStopped()
                        cid = name[len(vault_sync.BLOB_PREFIX):]
                        try:
                            raw = key.open(vault_sync.blob_logical(cid), client.download(f['id']))
                            if key.content_id(raw) != cid:
                                continue
                        except (mirror.MirrorKeyError, ValueError):
                            continue
                        first = st['orphans'].get(name, now)
                        if now - first >= ORPHAN_KEEP:
                            client.delete(f['id'])
                        else:
                            orphans[name] = first
                st['orphans'] = orphans
        st['cache'] = cache
        if self._vault_stopped():
            raise ExportStopped()
        _save_vault_state(sp, st)
        summary = (f"{total['pulled']} pulled, {total['trashed']} moved to .trash, {total['conflicts']} conflict copies, {sent} sent"
                   if (any(total.values()) or sent) else 'Already in step')
        if over:
            # a vault with files left out is not "in step": the words say so first (the Settings line and the phone's panel show them)
            note = vault_sync.skipped_note(len(over))
            summary = note.rstrip('.') + ('' if summary == 'Already in step' else f'; {summary}')
        reported = dict(vault_last=int(time.time() * 1000), vault_skipped=len(over), vault_skipped_note=vault_sync.skipped_note(len(over)))
        if braked:
            self._vault_report(client, key, push=True, vault_state='brake', vault_reason=braked, vault_summary='', **reported)
        elif failed:
            self._vault_report(client, key, push=True, vault_state='error', vault_reason='Some phone vault changes could not be read or applied; retry before publishing.', vault_summary='', **reported)
        else:
            self._vault_report(client, key, push=True, vault_state='idle', vault_reason='', vault_summary=summary, **ended, **reported)
            if any(total.values()):
                app_console.emit('log', f'Vault sync: {summary}')

    def _vault_send(self, client, key, vault: Path, pending: list[tuple[str, str]]) -> int:
        """Upload the round's new blobs, VAULT_UPLOAD_WORKERS at a time; the number sent. The workers only read
        files and call Drive; this thread counts finished files and reports them. The first DriveError cancels
        what has not started, waits for what has, and is raised: the index is not sent before every blob is up."""
        stop = getattr(self._vault_tls, 'stop', self._vault_stop)
        def one(cid: str, rel: str) -> bool:
            if stop.is_set() or self._vault_key_retired(key):
                raise ExportStopped()
            data = (vault / rel).read_bytes()
            if key.content_id(data) != cid:        # edited while we looked: the next round has it
                raise OSError('Vault file changed while sending; retry before publishing its index.')
            if stop.is_set() or self._vault_key_retired(key):
                raise ExportStopped()
            client.upload(vault_sync.blob_name(cid), data=key.seal(vault_sync.blob_logical(cid), data))
            return True

        def report():
            self._vault_tls.key = key
            self._vault_tls.stop = stop
            self._vault_report(client, key)

        done = sent = 0
        status = None
        with ThreadPoolExecutor(1, thread_name_prefix='cm-vault-status') as reporter, \
                ThreadPoolExecutor(VAULT_UPLOAD_WORKERS, thread_name_prefix='cm-vault-up') as pool:
            futures = [pool.submit(one, cid, rel) for cid, rel in pending]
            try:
                for f in as_completed(futures):
                    sent += f.result()
                    done += 1
                    if not stop.is_set() and not self._vault_stopped():
                        self._set(vault_done=done)
                    if status is None or status.done():
                        if status is not None:
                            status.result()
                        if time.monotonic() - self._vault_status_at >= VAULT_STATUS_EVERY:
                            status = reporter.submit(report)
                if status is not None:
                    status.result()      # finish before the index/final status; never overwrite it later
            except BaseException:
                pool.shutdown(cancel_futures=True)
                raise
        return sent

    # ── the phone's change files ────────────────────────────────────────────
    def _without_late_old_changes(self, key, files: list[dict]) -> list[dict]:
        """While phones are being removed the old key still opens change files, a lost phone's too (I6). Only those
        already in Drive at the click are applied: by id when that listing worked, else by the time Drive stamped them
        (never the phone's own `at`). The others stay in Drive, unread and undeleted, and are counted for the page."""
        rotation = self._rotation()
        if not rotation or rotation['stage'] == 'complete' or rotation['old'] != key.text() or not rotation.get('clicked'):
            late = []
        elif rotation.get('old_changes') is not None:
            seen = set(rotation['old_changes'])
            late = [f for f in files if f['id'] not in seen]
        else:
            # shortcut: modifiedTime is client-writable; this cutoff constrains the real app, not a hostile token holder.
            late = [f for f in files if not (lambda t: t is not None and t <= rotation['clicked'] + OLD_GRACE_MS)(_drive_ms(f.get('modifiedTime')))]
        ids = {f['id'] for f in late}
        if ids - self._ignored:
            app_console.emit('log', f'Drive mirror: {len(ids - self._ignored)} change(s) from a phone removed since were left in Drive, not applied', level='warning')
        self._ignored = ids
        self._count_ignored()
        return [f for f in files if f['id'] not in ids]

    def _count_ignored(self) -> None:
        """`ignored_changes` for the page: change files from removed phones that were left alone, both those after the Remove click
        (I6) and those this key cannot open (A17)."""
        n = len(self._ignored | self._unreadable)
        if n != self.st.get('ignored_changes', 0):
            self._set(ignored_changes=n)

    def _read_phones(self, client, key, listing, stop=None) -> None:
        """D13: the phones' own records, read only. A record is downloaded again only when Drive says it changed; one that does not
        open (another key, damaged) is skipped. `phones` stays None until a phone has written one, so the page keeps saying
        "Phones read your backup" instead of "No phones"."""
        cache, found, seen = self._phone_cache, [], {}
        for f in listing:
            name = f.get('name', '')
            if not mirror.is_phone(name):
                continue
            if stop and stop.is_set():
                raise ExportStopped()
            sig = (f.get('modifiedTime'), f.get('size'))
            hit = cache.get(f['id'])
            if hit is None or hit[0] != sig:
                try:
                    hit = (sig, mirror.open_phone(key, name, client.download(f['id'])))
                except mirror.MirrorKeyError:
                    hit = (sig, None)
                except drive_client.DriveError:
                    if hit is None:
                        continue          # retry an unchanged record after a transient download failure
                    # Keep the last good value with its old signature, so the next poll retries the new one.
            seen[f['id']] = hit
            if hit[1]:
                found.append(hit[1])
        self._phone_cache = seen
        found.sort(key=lambda r: (-r['seen'], r['name']))
        newest = {}
        for r in found:                      # a phone with two records (a create answered twice, two windows): its newest
            newest.setdefault(r['device'], r)
        value = list(newest.values()) if seen else None
        if value != self.st.get('phones'):
            self._set(phones=value)

    def _intake(self, stop=None) -> bool:
        """Apply and delete the phone's change files; True when anything was applied."""
        self.require_license()
        tok = drive_client.load_token(self.token_path)
        if tok is None:
            return False
        try:
            client = self._factory(tok, phone=True)
            if self._other_copy_wrote():     # its change files are another copy's phone: never drop them (A18: before the guard)
                return False
            self.recovery.guard(client)
            key = self._key()
            if self._key_conflict(key):
                return False
            if stop and stop.is_set():          # a stopped run starts no listing of Drive
                raise ExportStopped()
            listing = client.list()
        except (drive_client.DriveError, mirror.MirrorKeyError) as e:
            app_console.emit('log', 'Drive mirror: could not look for phone changes', level='warning', error=e)
            return False
        if stop and stop.is_set():
            raise ExportStopped()
        files = [f for f in listing if mirror.is_change(f.get('name', ''))]
        files = self._without_late_old_changes(key, files)
        transfers = {(entry['id'], entry['name'], entry['session']) for entry in self._transfers()}
        session = hashlib.sha256(tok['refresh_token'].encode()).hexdigest()
        had_held = bool(self._held)
        context = (session, key.fingerprint)
        if context != self._held_context:
            self._held.clear()
            self._unreadable.clear()
            self._held_context = context
        ids = {f['id'] for f in files}
        self._held = {fid: meta for fid, meta in self._held.items() if fid in ids}
        self._unreadable &= ids
        self._count_ignored()
        self._read_phones(client, key, listing, stop)
        for f in listing:                    # Only transfers created by this PC/account are ours to expire.
            name = f.get('name', '')
            if (f['id'], name, session) in transfers and mirror.is_pair_drop(name) and mirror.pair_drop_expired(name):
                if stop and stop.is_set():
                    raise ExportStopped()
                try:
                    client.delete(f['id'])
                except drive_client.DriveError:
                    pass
        if not files:
            if had_held or self.st.get('intake_summary', '').startswith(INTAKE_FAILED):
                self._set(last_intake=int(time.time() * 1000), intake_summary='Nothing waiting')
            return False
        docs, drop, failed = [], [], False
        for f in files:
            if stop and stop.is_set():
                raise ExportStopped()
            if f['id'] in self._held or f['id'] in self._unreadable:
                continue
            try:
                blob = client.download(f['id'])
            except drive_client.DriveError as e:
                app_console.emit('log', 'Drive mirror: a phone change could not be read', level='warning', error=e)
                failed = True
                continue
            try:
                doc = key.open_change(f['name'], blob)
            except mirror.MirrorKeyError:
                # sealed with an older key (a phone unpaired since) or damaged: never applied, never read again by this session (A17)
                self._unreadable.add(f['id'])
                self._count_ignored()
                app_console.emit('log', 'Drive mirror: retained an unreadable or old-key phone change for recovery', level='warning')
                continue
            kind = delivery.kind(doc)
            if kind in ('newer', 'invalid'):
                device, at = doc.get('device'), doc.get('at')
                safe = isinstance(device, str) and bool(device) and type(at) is int and at > 0
                reason = 'newer' if kind == 'newer' and safe else 'invalid'
                self._held[f['id']] = (device[:40] if safe else None, at if safe else 0, reason)
                app_console.emit('log', 'Drive mirror: phone changes wait for a Brainamon update' if reason == 'newer'
                                 else 'Drive mirror: retained an invalid phone change envelope', level='warning')
            else:
                docs.append((f, doc))
        # Discover every barrier before allowing any cumulative acknowledgement to advance.
        barriers = {}
        defer_all = False
        for device, at, _reason in self._held.values():
            if device is None:
                defer_all = True
            else:
                barriers[device] = min(barriers.get(device, at), at)
        eligible = []
        for f, doc in docs:
            device, at = str(doc.get('device') or 'phone')[:40], doc.get('at')
            if not defer_all and (device not in barriers or type(at) is int and 0 < at < barriers[device]):
                eligible.append((f, doc))
        deferred = len(docs) - len(eligible)
        docs = eligible
        def check():
            if stop and stop.is_set():
                raise ExportStopped()

        # server/delivery.py: numbered files in order, each in one transaction with its receipt; unnumbered ones by the
        # floor, none of them after a failed download. A file is deleted only once applied or seen before.
        result = self._licensed_call(lambda db: delivery.intake_round(db, docs, check, defer_legacy=failed)) if docs \
            else delivery.Round(intake.Applied())
        out = result.out
        for f in result.done + drop:
            if stop and stop.is_set():
                raise ExportStopped()
            try:
                client.delete(f['id'])
            except drive_client.DriveError:
                pass                         # seen again next time: its receipt or the floor already covers it
        if out.item_ids:
            self.hub.publish('items_changed', {'ids': out.item_ids})
        for cid in out.canvases:
            self.hub.publish('canvas_changed', {'id': cid})
        for name in out.notes:
            self.hub.publish('notes_changed', {'file': name, 'personal': True})
        if out.deleted_chats:
            self.hub.publish('chats_changed', {'deleted': out.deleted_chats})
        if out.new_ids:
            self._thumbs += out.new_ids
            self._retry_thumbs()
        summary = out.summary()
        newer = sum(reason == 'newer' for _, _, reason in self._held.values())
        invalid = len(self._held) - newer
        if newer:
            summary += f'; {newer} phone change(s) wait for a Brainamon update'
        if invalid:
            summary += f'; {invalid} invalid phone change envelope(s) retained'
        if deferred:
            summary += f'; {deferred} phone change(s) waiting behind held files'
        for n, words in ((result.held, 'wait for an earlier one'), (result.blocked, 'wait for the next look'),
                         (result.refused, 'refused: another file already used their number'),
                         (result.superseded, 'wait for their numbered copies')):
            if n:
                summary += f'; {n} phone change(s) {words}'
        self._set(last_intake=int(time.time() * 1000), intake_summary=summary)
        app_console.emit('log', f'From the phone: {summary}')
        # files that only wait (an earlier one missing, refused, this PC's error) force no publish and keep the backoff
        return bool(result.done or result.changed)

    def _retry_synth(self) -> None:
        self.require_license()
        """Start the first synthesis the phone queued for the PC; waits while another job runs."""
        try:
            q = self.writer.read(_synth_queue)
        except Exception:
            return
        if not q:
            return
        first = q[0]
        context = entitlements.phone_request.set(True)
        try:
            ok = self.on_synth(str(first.get('topic') or ''), list(first.get('ids') or []))
        except Exception as e:
            app_console.emit('log', 'Drive mirror: a synthesis asked from the phone did not start', level='warning', error=e)
            ok = True                        # dropped: it would fail the same way every time
        finally:
            entitlements.phone_request.reset(context)

        def drop(db):
            rest = _synth_queue(db)
            if rest and rest[0] == first:
                rest = rest[1:]
            db.set_setting(intake.SYNTH_QUEUE, json.dumps(rest))
        if ok:
            self._licensed_call(drop)

    def _retry_thumbs(self) -> None:
        self.require_license()
        """Fetch thumbnails for links saved on the phone; waits while another job runs."""
        if self._thumbs:
            ids, self._thumbs = self._thumbs, []
            context = entitlements.phone_request.set(True)
            try:
                ok = self.on_new_links(ids)
            except Exception as e:
                app_console.emit('log', 'Drive mirror: thumbnails for phone links not started', level='warning', error=e)
                ok = True
            finally:
                entitlements.phone_request.reset(context)
            if not ok:
                self._thumbs = ids + self._thumbs


def _synth_queue(db) -> list:
    try:
        q = json.loads(db.get_setting(intake.SYNTH_QUEUE, '') or '[]')
    except ValueError:
        q = []
    return q if isinstance(q, list) else []


def _applied(db, key: str = S_APPLIED) -> dict:
    try:
        out = json.loads(db.get_setting(key, '') or '{}')
    except ValueError:
        out = {}
    return out if isinstance(out, dict) else {}
