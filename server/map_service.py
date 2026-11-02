"""The knowledge map thread (`cm-map`) and the two process-wide locks
(docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md, decisions 6 and 7).

MAP_LOCK guards every write of data/obsidian_graph.json (this thread's maintenance, the refresh_map job's
persist steps). VAULT_LOCK guards every write inside the vault folder (this thread's render, the classic
export's write step, a classic vault's sync round in server/sync.py, Move, Reset, Reclaim, Take over,
owner setup). Two locks, not one: a first vault upload can hold the vault lock for hours and must not
freeze map maintenance for Wiskit.

The thread never opens SQLite: it reads through Writer.read like cm-sync and writes files only. It runs
whenever a map exists or an owner vault is set: maintenance (assign new items, drop deleted ones,
recompute staleness) then, with an owner vault, the render (changed files only, removals and adoptions by
the manifest). Triggers: a cheap library signature polled every POLL seconds, debounced to QUIET seconds
of calm, app start, and poke(now=True) from a finished refresh_map job. Background work never waits for a
lock: a held lock leaves `pending` set and the pass is retried every RETRY seconds. User actions wait with
a visible waiting state and a cancel event (with_vault_lock).

Settings (DB): obsidian_vault (the vault Brainamon renders into, never the user's notes vault),
obsidian_mode ('owner' or ''), obsidian_pictures ('on' to copy thumbnails), obsidian_first_open
('pending' until the user opened a vault Brainamon created).
"""
import threading
import time
from pathlib import Path

from core import ai_client, app_console, app_paths
from library import map_engine, obsidian_run, owner_pages, owner_vault, search

POLL, QUIET, RETRY = 5, 60, 60
S_VAULT, S_MODE, S_PICTURES, S_FIRST_OPEN = 'obsidian_vault', 'obsidian_mode', 'obsidian_pictures', 'obsidian_first_open'
# spec 1b (owner vault sync): the phone capability gate (decision 5), the Move and Create gate (decision 6, Fred
# 2026-10-28: refused until a round has read the phone lists) and the missing manifest (Fred 2026-10-28: wait)
PHONE_OLD = 'Update Brainamon on your phone to keep syncing this vault'
PHONES_UNCHECKED = ('Vault sync has not checked your phones yet. Wait for its first round, or turn vault sync off in '
                    'Settings > Backup & phones.')
MANIFEST_MISSING = ("The vault's manifest is missing or unreadable, so vault sync waits. Use Reclaim generated pages "
                    'in Settings > Obsidian.')


def phone_old(devices) -> str:
    """Decision 5: the phones whose file list declares no caps (an older app), by name."""
    return f"{PHONE_OLD}: {', '.join(sorted(devices))}."


MAP_LOCK = threading.RLock()
VAULT_LOCK = threading.RLock()


class NeedsConfirm(owner_vault.VaultError):
    """The folder holds 1 to 5 other entries: the caller must send confirm (Use it anyway)."""
    def __init__(self, message, count):
        super().__init__(message)
        self.count = count


class NeedsTakeover(owner_vault.VaultError):
    """The folder is another library's Brainamon vault (an earlier install): the caller must send takeover.
    count = the leftovers (pages about items or topics this library does not have)."""
    def __init__(self, message, count):
        super().__init__(message)
        self.count = count


def _signature(db) -> tuple:
    """Changes whenever something the map or the vault carries changes in the DB."""
    c = db.conn
    items = tuple(c.execute(
        "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(MAX(modified), 0), COALESCE(SUM(LENGTH(description)), 0), "
        "COALESCE(SUM(LENGTH(short_desc)), 0), COALESCE(SUM(LENGTH(ai_desc)), 0), COALESCE(SUM(LENGTH(tags)), 0), "
        "COALESCE(SUM(LENGTH(transcript)), 0), COALESCE(SUM(analysis_done), 0) FROM items").fetchone())
    cats = tuple(r[0] for r in c.execute("SELECT name FROM categories ORDER BY name"))
    vec = tuple(c.execute("SELECT COUNT(*), COALESCE(MAX(updated), 0) FROM item_embeddings WHERE model = ?",
                          (ai_client.EMBEDDING_MODEL,)).fetchone())
    keys = tuple(db.get_setting(k, '') for k in (S_VAULT, S_MODE, S_PICTURES))
    return items, cats, vec, keys, len(db.get_setting(obsidian_run.TAG_MAP_KEY, ''))


def _notes_stamp(data_dir: Path) -> tuple:
    d = Path(data_dir) / 'notes'
    try:
        return tuple(sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in d.iterdir() if e.is_file()))
    except OSError:
        return ()


def with_vault_lock(fn, cancel: threading.Event, on_wait=None):
    """Run fn() holding VAULT_LOCK. User actions wait for the lock (decision 7) until `cancel` is set;
    `on_wait()` is called every half second while waiting so the caller can show a waiting state."""
    while not VAULT_LOCK.acquire(timeout=0.5):
        if on_wait:
            on_wait()
        if cancel.is_set():
            raise owner_vault.VaultError('Cancelled while waiting for the vault.')
    try:
        return fn()
    finally:
        VAULT_LOCK.release()


class MapService:
    def __init__(self, writer, hub, data_dir, vault_devices=None, vault_id_for=None):
        """`vault_devices()`: the phones vault sync saw in its last round ([{device, ok}], None before a round;
        server/app.py passes the SyncService's). `vault_id_for(folder)`: the vault identity vault sync recorded
        for that folder ('' when none; server.sync.recorded_vault_id). Both are spec 1b's."""
        self.writer, self.hub, self.data_dir = writer, hub, Path(data_dir)
        self.vault_devices = vault_devices or (lambda: None)
        self.vault_id_for = vault_id_for or (lambda folder: '')
        self.cache_path = map_engine.cache_path(self.data_dir)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._force = False
        self._lock = threading.Lock()
        self.cancel = threading.Event()        # set by POST /api/obsidian/cancel: the waiting user action gives up
        # seq: bumped by every change, so the page can drop an answer older than the last `map` event
        self.st = {'seq': 0, 'state': 'idle', 'pending': False, 'error': '', 'busy': '', 'waiting': False,
                   'last_maintenance': 0, 'last_render': 0, 'written': 0, 'removed': 0,
                   'adopted': [], 'unlisted': 0, 'other_library': False, 'missing': False, 'leftovers': 0,
                   'topics': 0, 'stale': 0, 'pending_summaries': 0}

    # ── state ────────────────────────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            return dict(self.st)

    def _set(self, **kw) -> None:
        with self._lock:
            self.st.update(kw)
            self.st['seq'] += 1
            snap = dict(self.st)
        self.hub.publish('map', snap)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def boot(self) -> None:
        self._force = True
        self._thread = threading.Thread(target=self._loop, name='cm-map', daemon=True)
        self._thread.start()

    def poke(self, now: bool = False) -> None:
        """A change worth looking at; now=True runs the pass at once (a finished Refresh map)."""
        if now:
            self._force = True
        self._wake.set()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t:
            t.join(10)

    def _loop(self) -> None:
        seen, changed_at, retry_at = None, 0.0, 0.0
        while not self._stop.is_set():
            try:
                sig = (self.writer.read(_signature), _notes_stamp(self.data_dir))
            except Exception as e:                  # the Writer is shutting down
                app_console.emit('log', 'Knowledge map: could not read the library', level='warning', error=e)
                sig = seen
            now = time.monotonic()
            if self._force:
                due = True
            elif sig != seen:
                changed_at = changed_at or now
                due = now - changed_at >= QUIET
            else:
                due = self.st['pending'] and now >= retry_at
            if due:
                self._force = False
                seen, changed_at = sig, 0.0
                try:
                    ok = self.run_pass()
                except Exception as e:              # never the end of the thread
                    ok = False
                    app_console.emit('error', 'Knowledge map pass failed', level='error', error=e)
                    self._set(error=str(e)[:300], pending=True, state='pending')
                if not ok:
                    retry_at = now + RETRY
            self._wake.wait(POLL)
            self._wake.clear()

    # ── one pass ─────────────────────────────────────────────────────────────
    def _read_inputs(self, db) -> dict:
        model = ai_client.EMBEDDING_MODEL
        rows = db.search_items(include_thumbs=True)          # SELECT *: the transcript is part of the fingerprint
        return {'model': model, 'live_ids': [r['id'] for r in rows],
                'urls': {str(r['id']): r['url'] or '' for r in rows},
                'fps': map_engine.fingerprints(model, rows),
                'idx': search.EmbeddingIndex.from_db(db, model),
                'tag_map': obsidian_run.stored_tag_map(db) or None,
                'vault': db.get_setting(S_VAULT, '') or '', 'owner': db.get_setting(S_MODE, '') == 'owner',
                'pictures': db.get_setting(S_PICTURES, '') == 'on',
                'vault_sync': db.get_setting('cloud_vault', '') == 'on',       # spec 1b: deletion records only then
                'library_id': db.get_setting('library_id', '')}

    def run_pass(self) -> bool:
        """Maintenance (when a map exists) then the render (when an owner vault is set), each with a
        non-blocking lock. False: something stayed pending (retried by the thread)."""
        inputs = self.writer.read(self._read_inputs)
        ok = True
        if self.cache_path.exists():
            ok = self._maintain(inputs) and ok
        if inputs['owner'] and inputs['vault']:
            ok = self._render(inputs) and ok
        self._set(pending=not ok, state='idle' if ok else 'pending', error='' if ok else self.st['error'])
        return ok

    def _maintain(self, inputs: dict) -> bool:
        if not MAP_LOCK.acquire(blocking=False):
            return False
        try:
            cache = map_engine.load(self.cache_path)
            if cache['clusters']:
                map_engine.assign(cache, inputs['idx'], inputs['fps'], inputs['live_ids'])
                map_engine.save(self.cache_path, cache)
            s = map_engine.stats(cache)
            self._set(last_maintenance=int(time.time() * 1000), topics=s['topics'], stale=s['stale'],
                      pending_summaries=s['pending'])
            return True
        finally:
            MAP_LOCK.release()

    def _files(self, inputs: dict, man: dict) -> dict:
        """The owner render for the current library, with names recorded in `man`. Under VAULT_LOCK."""
        cache = map_engine.load(self.cache_path) if self.cache_path.exists() else None
        if cache is not None:
            map_engine.recompute_stale(cache, inputs['fps'])
        names = owner_vault.Names(man)
        idx = inputs['idx'] if len(inputs['idx']) else None
        payload = self.writer.read(lambda db: owner_pages.build_owner_payload(
            db, names, idx, inputs['tag_map'], cache, inputs['pictures']))
        return owner_pages.render(payload)

    def _render(self, inputs: dict, vault=None) -> bool:
        vault = Path(vault or inputs['vault'])
        if not VAULT_LOCK.acquire(blocking=False):
            return False
        try:
            if not vault.is_dir():
                self._set(missing=True, other_library=False)            # moved or renamed by hand: never recreated
                return True
            self._set(state='rendering')
            man = owner_vault.read_manifest(vault)
            if man is None:
                if inputs['vault_sync']:
                    self._set(error=MANIFEST_MISSING, pending=True, state='pending')
                    return False
                man = owner_vault.new_manifest(inputs['library_id'])     # existing files stay unlisted
            if man['library_id'] != inputs['library_id']:
                self._set(other_library=True, missing=False)            # another library's vault: no writes
                return True
            files = self._files(inputs, man)
            owner_vault.rejoin_released(vault, man, files)
            res = owner_vault.apply_render(vault, man, files, track_removed=inputs['vault_sync'])
            first_open = self.writer.read(lambda db: db.get_setting(S_FIRST_OPEN, ''))
            if first_open == 'pending' and (vault / '.obsidian' / 'workspace.json').is_file():
                self.writer.call(lambda db: db.set_setting(S_FIRST_OPEN, ''))   # Obsidian opened it
            self._set(last_render=int(time.time() * 1000), written=res['written'], removed=res['removed'],
                      adopted=res['adopted'], unlisted=len(res['unlisted']), other_library=False, missing=False,
                      leftovers=sum(1 for r in man.get('released') or {} if (vault / r).exists()))
            return True
        finally:
            VAULT_LOCK.release()

    # ── user actions (decisions 1, 4, 8, 10): wait for the vault lock, cancellable ──
    def _begin(self, what: str) -> None:
        self.cancel.clear()
        self._set(busy=what, waiting=False, error='')

    def _end(self) -> None:
        self._set(busy='', waiting=False)

    def _waiting(self) -> None:
        if not self.st['waiting']:
            self._set(waiting=True)

    def _phones_ready(self) -> None:
        """Spec 1b decision 6 (Fred 2026-10-28): with vault sync on, a Move or a new owner vault needs the device
        list of a round (none yet: refused) in which every phone runs the current app."""
        devices = self.vault_devices()
        if devices is None:
            raise owner_vault.VaultError(PHONES_UNCHECKED)
        old = [d['device'] for d in devices if not d['ok']]
        if old:
            raise owner_vault.VaultError(phone_old(old))

    def _guard_setup(self, path: str) -> tuple:
        """The checks every owner setup and Move share: an absolute path, the location rules, the phone gate when vault sync is on.
        Returns (Path, library_id)."""
        if not path or not Path(path).is_absolute():
            raise owner_vault.VaultError('Enter an absolute folder path.')
        err = owner_vault.location_error(path, self.data_dir, app_paths.HOME)
        if err:
            raise owner_vault.VaultError(err)
        vault_sync, library_id = self.writer.read(lambda db: (db.get_setting('cloud_vault', '') == 'on',
                                                                 db.get_setting('library_id', '')))
        if vault_sync:
            self._phones_ready()
        if not library_id:
            library_id = self.writer.call(lambda db: db.library_id())     # a write: not inside Writer.read
        return Path(path), library_id

    def _take_over(self, vault: Path, man: dict, library_id: str, remove: bool = False, write: bool = True) -> tuple:
        """Decision 4 (amended): settle, keep the names that still hold, render with them, then split, and
        with write take over (under VAULT_LOCK). write=False only counts, for the question; nothing is saved.
        Returns (edited, matched, leftovers)."""
        owner_vault.settle_pending(vault, man)
        inputs = self.writer.read(self._read_inputs)
        owner_vault.keep_names(vault, man, inputs['urls'])
        files = self._files(inputs, man)
        if not write:
            return owner_vault.takeover_split(vault, man, files)
        return owner_vault.take_over(vault, man, library_id, files, remove)

    def set_owner_vault(self, path: str, confirm: bool = False, create: bool = False, takeover: bool = False,
                        remove: bool = False) -> dict:
        """Owner mode on `path`. create=True (Create a new vault): the folder and an empty .obsidian/ are
        made and the first-open step starts. create=False (a vault made in Obsidian, or one Brainamon made
        before): .obsidian/ is never touched and there is no first-open step. The folder rule may ask for
        confirm (NeedsConfirm). Another library's vault asks first (NeedsTakeover, with the counts); with
        takeover it is taken over in place, leftovers kept, or removed by the render with remove."""
        vault, library_id = self._guard_setup(path)
        state, msg, count = owner_vault.folder_check(vault, library_id)
        if state == 'refused':
            raise owner_vault.VaultError(msg)
        if state == 'takeover' and not takeover:
            edited, matched, leftovers = self._take_over(vault, owner_vault.read_manifest(vault), library_id, write=False)
            raise NeedsTakeover(owner_vault.takeover_message(len(edited), len(matched), len(leftovers)), len(leftovers))
        if state == 'confirm' and not confirm:
            raise NeedsConfirm(msg, count)
        self._begin('setup')
        try:
            def go():
                if self.writer.read(lambda db: db.get_setting('cloud_vault', '') == 'on'):
                    self._phones_ready()
                vault.mkdir(parents=True, exist_ok=True)
                if create:
                    (vault / '.obsidian').mkdir(exist_ok=True)
                man = owner_vault.read_manifest(vault) or owner_vault.new_manifest(library_id)
                if man['library_id'] != library_id:
                    if not takeover:
                        raise owner_vault.VaultError(owner_vault.OTHER_LIBRARY)    # appeared while waiting for the lock
                    self._take_over(vault, man, library_id, remove)
                else:
                    owner_vault.write_manifest(vault, man)
                self.writer.call(lambda db: (db.set_setting(S_VAULT, str(vault)), db.set_setting(S_MODE, 'owner'),
                                             db.set_setting(S_FIRST_OPEN, 'pending' if create else '')))
                inputs = self.writer.read(self._read_inputs)
                self._render(inputs, vault)
            with_vault_lock(go, self.cancel, on_wait=self._waiting)
        finally:
            self._end()
        self.poke(now=True)
        return {'vault': str(vault), 'first_open': 'pending' if create else ''}

    def move(self, dest: str) -> int:
        """Decision 10: copy the current classic vault (everything but Content Manager/) into `dest`, verify,
        create the manifest, render, then point obsidian_vault there. The old vault is never deleted."""
        vault, library_id = self._guard_setup(dest)
        old, mode = self.writer.read(lambda db: (db.get_setting(S_VAULT, '') or '', db.get_setting(S_MODE, '')))
        if not old or not Path(old).is_dir():
            raise owner_vault.VaultError('There is no vault to move: set one up instead.')
        if mode == 'owner':
            raise owner_vault.VaultError('This vault is already a Brainamon vault; there is nothing to move.')
        if Path(old).resolve() == vault.resolve():
            raise owner_vault.VaultError('Choose a different folder for the new vault.')
        state, msg, _count = owner_vault.folder_check(vault, library_id)
        if state == 'takeover':
            raise owner_vault.VaultError('That folder is already a Brainamon vault. Choose another folder for the move.')
        if state != 'ok':
            raise owner_vault.VaultError(msg or 'Choose an empty folder for the new vault.')
        self._begin('move')
        try:
            def go():
                if self.writer.read(lambda db: db.get_setting('cloud_vault', '') == 'on'):
                    self._phones_ready()
                n = owner_vault.move(old, vault, should_stop=self.cancel.is_set)
                owner_vault.write_manifest(vault, owner_vault.new_manifest(library_id))
                inputs = self.writer.read(self._read_inputs)
                self._render(inputs, vault)
                self.writer.call(lambda db: (db.set_setting(S_VAULT, str(vault)), db.set_setting(S_MODE, 'owner'),
                                             db.set_setting(S_FIRST_OPEN, '')))
                return n
            n = with_vault_lock(go, self.cancel, on_wait=self._waiting)
        finally:
            self._end()
        self.poke(now=True)
        return n

    def _owner(self) -> tuple:
        vault, mode, library_id = self.writer.read(lambda db: (db.get_setting(S_VAULT, '') or '', db.get_setting(S_MODE, ''),
                                                                db.get_setting('library_id', '')))
        if mode != 'owner' or not vault:
            raise owner_vault.VaultError('No Brainamon vault is set up.')
        return Path(vault), library_id

    def reset(self, rel: str) -> None:
        """Reset to generated: one adopted page gets its generated content back (or goes when its source is gone)."""
        vault, library_id = self._owner()
        self._begin('reset')
        try:
            def go():
                man = owner_vault.read_manifest(vault)
                if man is None or man['library_id'] != library_id:
                    raise owner_vault.VaultError('This vault has no manifest of this library.')
                inputs = self.writer.read(self._read_inputs)
                owner_vault.reset_page(vault, man, rel, self._files(inputs, man))
                with self._lock:
                    adopted = [a for a in self.st['adopted'] if a != rel]
                self._set(adopted=adopted)
            with_vault_lock(go, self.cancel, on_wait=self._waiting)
        finally:
            self._end()

    def reclaim(self) -> int:
        """Reclaim generated pages: adopt Brainamon's unlisted files into the manifest (a new one when lost)."""
        vault, library_id = self._owner()
        self._begin('reclaim')
        try:
            def go():
                man = owner_vault.read_manifest(vault) or owner_vault.new_manifest(library_id, self.vault_id_for(vault) or None)
                if man['library_id'] != library_id:
                    raise owner_vault.VaultError(owner_vault.OTHER_LIBRARY)
                inputs = self.writer.read(self._read_inputs)
                n = owner_vault.reclaim(vault, man, self._files(inputs, man))
                owner_vault.write_manifest(vault, man)
                return n
            n = with_vault_lock(go, self.cancel, on_wait=self._waiting)
        finally:
            self._end()
        self.run_pass()                  # synchronously: the tab's unlisted count is right when the request answers
        return n

    def take_over(self) -> None:
        """Take over this vault (decision 4, amended): matches refreshed, edits kept, leftovers kept."""
        vault, library_id = self._owner()
        self._begin('takeover')
        try:
            def go():
                man = owner_vault.read_manifest(vault)
                if man is None:
                    raise owner_vault.VaultError('This vault has no manifest to take over.')
                self._take_over(vault, man, library_id)
                self._set(other_library=False)
            with_vault_lock(go, self.cancel, on_wait=self._waiting)
        finally:
            self._end()
        self.run_pass()                  # synchronously: the tab's counts are right when the request answers

    def remove_leftovers(self) -> int:
        """Remove leftovers (the user's confirmed click): earlier pages kept at take-over, deleted when still
        unchanged."""
        vault, library_id = self._owner()
        self._begin('remove')
        try:
            def go():
                man = owner_vault.read_manifest(vault)
                if man is None or man['library_id'] != library_id:
                    raise owner_vault.VaultError('This vault has no manifest of this library.')
                return owner_vault.remove_leftovers(vault, man)
            n = with_vault_lock(go, self.cancel, on_wait=self._waiting)
        finally:
            self._end()
        self.run_pass()
        return n
