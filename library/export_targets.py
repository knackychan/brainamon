"""
export_targets.py: export destinations.

Every export destination consumes the same target-agnostic payload from
export.build_export_payload(). DriveMirrorTarget writes the encrypted Google Drive mirror for
the phone (projects/mobile-app/PLAN.md Phase 3); Dropbox or OneDrive would be sibling targets
behind the same interface. The static "Export for phone" folder (StaticFolderTarget) retired
with it on 2026-10-11.

Targets do file and network I/O only and never receive the Database object, so they are safe
to run off the server's Writer thread (server/sync.py).
"""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from pathlib import Path

from library import mirror
from library.drive_client import DriveError


class ExportTargetError(Exception):
    """Raised when a target refuses to export."""


class ExportStopped(Exception):
    """The export was asked to stop between two files; what was sent so far is recorded."""


class ExportTarget:
    """Interface: write `payload` somewhere. `thumb_sources` maps a manifest key
    (see payload['thumbs']) to a source image Path. `progress(done, total)` is
    optional."""

    def export(self, payload: dict, thumb_sources: dict, out_dir: Path | None = None,
               progress=None):
        raise NotImplementedError


@dataclass
class MirrorResult:
    files: int = 0                 # logical files in the mirror after this publish
    uploaded: int = 0
    deleted: int = 0
    bytes_sent: int = 0
    size: int = 0                  # sealed bytes in Drive
    changed: bool = False          # anything uploaded or deleted (the manifest was rewritten)
    duplicates: int = 0            # same-name copies of this mirror's files removed after the manifest (F1)
    skipped: dict = field(default_factory=dict)   # {logical name: plain size} of the files left out because recovery would refuse them
    errors: list = field(default_factory=list)    # (logical name, message)


class DriveMirrorTarget(ExportTarget):
    """The mirror in the app data folder of the user's Google Drive.

    `client` is a drive_client.DriveClient (or anything with list / upload / delete), `key` a
    mirror.MirrorKey, `state` what was published: {logical: {'sig', 'drive_id', 'size'}} from the
    sync_state table. Only files whose signature changed are rebuilt, sealed and uploaded; files
    that left the library are deleted, and so are stray files in the folder (an upload cut off
    halfway, a mirror sealed with an older key). The manifest goes up last, so a phone never sees
    it point at a file that is not there yet. A file over the size recovery accepts is never built
    (mirror.build_files): `MirrorResult.skipped` names it and the manifest records it.

    `save(put, drop)` is called every few files with the state changes so far, so a first upload
    that is cut off resumes where it stopped. `stop` (a threading.Event) is checked between files:
    the files being sent finish and are recorded, the rest do not start."""

    SAVE_EVERY = 25
    TICK_EVERY = 5          # bounds wait rounds, not synchronous preparation or network calls
    UPLOAD_WORKERS = 12     # files sealed and sent at once: one request each, and a full upload has thousands;
                            # a 403/429 burst refusal is retried with backoff (drive_client._call)

    def __init__(self, client, key: 'mirror.MirrorKey', state: dict, data_dir: Path,
                 opts: 'mirror.Options', tints: dict | None = None, save=None,
                 stop: threading.Event | None = None, tmp_dir: Path | None = None,
                 force_manifest: bool = False, tick=None, skipped_before: dict | None = None):
        self.client, self.key, self.data_dir, self.opts = client, key, Path(data_dir), opts
        self.state = {k: dict(v) for k, v in state.items()}
        self.tints = tints or {}
        self.save = save or (lambda put, drop: None)
        self.stop = stop or threading.Event()
        self.tmp_dir = Path(tmp_dir) if tmp_dir else None
        self.force_manifest = force_manifest     # phone changes were applied: `applied` moved
        self.skipped_before = skipped_before     # the `skipped` the manifest in Drive says ({} for none); None: not known, nothing to compare
        self.tick = tick
        self._adopted: dict[str, str] = {}     # logical name: a same-name Drive file taken over this publish (I2)
        self.bytes_done = self.bytes_total = 0  # plain sizes of the files this publish sends and has sent: the bar beside the file count (S7)

    def export(self, payload: dict, thumb_sources: dict | None = None, out_dir: Path | None = None,
               progress=None) -> MirrorResult:
        res = MirrorResult()
        remote = {f['id']: f for f in self.client.list()}
        self._owned_before = {st['drive_id'] for st in self.state.values()}
        put: dict = {}
        drop: list = []

        # files Drive no longer has (deleted from outside) are sent again
        for name, st in list(self.state.items()):
            if st['drive_id'] not in remote:
                del self.state[name]
                drop.append(name)

        files = list(mirror.build_files(payload, self.data_dir, self.opts, self.tints, skipped=res.skipped))
        # Same-name files Drive holds that the state does not know: a sign-in that forgot the state, a create whose
        # answer was lost. The names are HMACs under this key, so they are this library's (F1). One per logical name
        # is taken over and updated in place; every other copy is deleted after the manifest.
        by_name: dict[str, list[str]] = {}
        for fid, f in remote.items():
            by_name.setdefault(f['name'], []).append(fid)
        known_ids = {st['drive_id'] for st in self.state.values()}
        self._adopted = {}
        for logical in [f.name for f in files] + [mirror.MANIFEST]:
            if logical not in self.state:
                spare = [fid for fid in by_name.get(self.key.name(logical), []) if fid not in known_ids]
                if spare:
                    self._adopted[logical] = spare[0]
        todo = [f for f in files if self.state.get(f.name, {}).get('sig') != f.sig]
        self.bytes_done, self.bytes_total = 0, sum(f.size for f in todo)
        if progress:
            progress(0, len(todo))
        refused = self._send_all(todo, res, put, drop, progress)
        if refused is not None or self.stop.is_set():
            self._flush(put, drop)
            if refused is not None:
                raise refused
            raise ExportStopped()

        # what left the library: the manifest stops listing it and goes up first; its file in Drive is a
        # stray like any other and is deleted after (an old manifest never points at a deleted file)
        names = {f.name for f in files}
        gone = [k for k in self.state if k not in names and k != mirror.MANIFEST]

        # the recovery preview reads the count of left-out files from the manifest, so it is rewritten when that list moved
        moved = self.skipped_before is not None and res.skipped != self.skipped_before
        res.changed = bool(res.uploaded or gone or self.force_manifest or mirror.MANIFEST not in self.state or moved)
        if res.changed:
            sizes = {f.name: f.size for f in files}
            # `s`: the whole version, so a PC that downloads only what changed (Update this folder, S9) records what it
            # holds exactly as this one would and sends nothing twice; readers use `v`
            listing = {name: {'n': self.key.name(name), 'v': st['sig'][:16], 's': st['sig'], 'size': sizes.get(name, 0),
                              'id': st['drive_id'], **({'integrity': 2, 'bytes': sizes[name], 'sha256': st['sig'][7:]} if name.startswith('videos/') and st['sig'].startswith('video2:') else {})}
                       for name, st in self.state.items() if name in names}
            m = _Blob(mirror.MANIFEST, mirror.manifest(listing, payload, self.opts, res.skipped))
            try:
                sent, size, drive_id = self._send(m)
            except (DriveError, ExportStopped):
                self._flush(put, drop)        # `gone` stays in the saved state: the next publish redoes it
                raise
            st = {'sig': m.sig, 'drive_id': drive_id, 'size': size}
            self.state[mirror.MANIFEST] = st
            put[mirror.MANIFEST] = st
            res.bytes_sent += sent
        self._flush(put, drop)
        put, drop = {}, []

        # stray files: not in the state at all (the files that left the library, an upload cut off halfway,
        # a mirror sealed with an older key). The phone's change files are not strays: the intake applies
        # and deletes them; nor are the vault sync files, `vb-`, `vi-` and `vs-`, which server/sync.py owns;
        # nor are AI keys a phone being paired has yet to collect. One call each, so they are counted in
        # the bar and `stop` is checked between them; what a stop leaves is a stray again next time.
        known = {st['drive_id'] for name, st in self.state.items() if name in names or name == mirror.MANIFEST}

        # Only formerly published records are owned. Unknown/recovery/other-library files survive.
        old_ids = {remote_id for remote_id in self._owned_before if remote_id not in known}
        strays = [fid for fid in remote if fid in old_ids]
        # duplicate same-name copies of the files the manifest now lists (F1): every id under one of this mirror's
        # names other than the one the state holds. Names under any other key, recovery records, change files,
        # vault files and pairing drops have other names and are never touched.
        current = {name: st['drive_id'] for name, st in self.state.items() if name in names or name == mirror.MANIFEST}
        duplicates = [fid for logical, kept in current.items()
                      for fid in by_name.get(self.key.name(logical), []) if fid != kept and fid not in self._owned_before]
        res.duplicates = len(duplicates)
        strays += duplicates
        if progress and strays:
            progress(len(todo), len(todo) + len(strays))
        for k, fid in enumerate(strays, 1):
            if self.stop.is_set():
                raise ExportStopped()
            try:
                self.client.delete(fid)
                removed = [name for name in gone if self.state.get(name, {}).get('drive_id') == fid]
                self._flush({}, removed)
                for name in removed:
                    self.state.pop(name, None)
                res.deleted += 1
            except DriveError as e:
                res.errors.append((remote[fid].get('name', fid), str(e)))
            if progress:
                progress(len(todo) + k, len(todo) + len(strays))
            if self.tick:
                self.tick()
        res.changed = res.changed or bool(res.deleted)
        res.files = len(files)
        res.size = sum(st.get('size') or 0 for st in self.state.values())
        return res

    def _send_all(self, todo: list, res: MirrorResult, put: dict, drop: list, progress) -> DriveError | None:
        """Seal and upload `todo`, UPLOAD_WORKERS at a time. The workers only read, seal and call Drive; this
        thread records each finished file, saves every SAVE_EVERY and moves the bar. Stop, or Drive refusing the
        sign-in (401/403, returned), lets the files being sent finish and be recorded; the rest never start."""
        cut = threading.Event()

        def one(f, old: str):
            return None if cut.is_set() or self.stop.is_set() else self._send(f, old)

        refused, abort, since, done = None, None, 0, 0
        with ThreadPoolExecutor(self.UPLOAD_WORKERS, thread_name_prefix='cm-mirror-up') as pool:
            futures = {pool.submit(one, f, self.state.get(f.name, {}).get('drive_id') or self._adopted.get(f.name, '')): f for f in todo}
            pending = set(futures)
            # One round even with no uploads: intake can force a later manifest.
            while True:
                finished, pending = wait(pending, timeout=self.TICK_EVERY, return_when=FIRST_COMPLETED)
                for fut in finished:
                    try:
                        f = futures[fut]
                        try:
                            got = fut.result()
                        except ExportStopped as e:
                            abort = abort or e
                            cut.set()
                            continue
                        except DriveError as e:
                            if e.status in (401, 403):      # the sign-in: nothing else would go through
                                refused = refused or e
                                cut.set()
                                continue
                            res.errors.append((f.name, str(e)))
                        except OSError as e:
                            res.errors.append((f.name, str(e)))
                        else:
                            if got is None:                 # not started: Stop, or the sign-in was refused
                                continue
                            sent, size, drive_id = got
                            st = {'sig': f.sig, 'drive_id': drive_id, 'size': size}
                            self.state[f.name] = st
                            put[f.name] = st
                            res.uploaded += 1
                            res.bytes_sent += sent
                            self.bytes_done += f.size
                            since += 1
                            if since >= self.SAVE_EVERY:
                                self._flush(put, drop)
                                put.clear()
                                drop.clear()
                                since = 0
                        done += 1
                        if progress:
                            progress(done, len(todo))
                    except BaseException as e:
                        abort = abort or e
                        cut.set()       # drain running results on this owner thread before raising
                if self.stop.is_set():
                    cut.set()
                if self.tick and not cut.is_set():
                    try:
                        self.tick()
                    except BaseException as e:
                        abort = abort or e
                        cut.set()
                if not pending:
                    break
        if abort is not None:
            self._flush(put, drop)
            raise abort
        return refused

    def _flush(self, put: dict, drop: list) -> None:
        if put or drop:
            self.save(dict(put), list(drop))

    def _send(self, f, old: str | None = None) -> tuple[int, int, str]:
        """Seal and upload one file; (bytes sent, sealed size, Drive id). `old`: its Drive id, read from the
        state when not given (a worker gets it from the thread that owns the state)."""
        name = self.key.name(f.name)
        if old is None:
            old = self.state.get(f.name, {}).get('drive_id') or self._adopted.get(f.name, '')
        if f.path is not None:
            with tempfile.TemporaryDirectory(dir=self.tmp_dir) as td:
                sealed = Path(td) / 'v.bin'
                size = self.key.seal_file(f.name, f.path, sealed, {'bytes': f.size, 'sha256': f.sig[7:]})
                return size, size, self._upload(name, None, sealed, old)
        blob = self.key.seal(f.name, f.data())
        return len(blob), len(blob), self._upload(name, blob, None, old)

    def _upload(self, name: str, data, path, old: str) -> str:
        if self.stop.is_set():
            raise ExportStopped()
        if old:
            try:
                return self.client.upload(name, data=data, path=path, file_id=old)
            except DriveError as e:
                if e.status != 404:
                    raise
        return self.client.upload(name, data=data, path=path)


class _Blob:
    """The manifest as a MirrorFile-like value (it is built after the others)."""

    def __init__(self, name: str, data: bytes):
        import hashlib
        self.name, self._d, self.path = name, data, None
        self.sig = hashlib.sha256(data).hexdigest()
        self.size = len(data)

    def data(self) -> bytes:
        return self._d
