"""Phone change files applied exactly once (delivery 2; docs/superpowers/plans/2026-10-31-phone-backup-phones/
02-s5-resend-after-pairing-again.md).

A phone paired with a PC numbers its change files: {format: 1, device, at, stream, seq, acked, legacy?, changes}.
`stream` is a random id the phone keeps with its journal, `seq` counts that stream's files from 1, `acked` is the
highest seq the phone knows the PC applied, and `legacy` marks a batch an older phone build sent before it numbered
its files. The envelope stays format 1: an older PC ignores the new fields and keeps its `applied` floor.

This PC applies a stream's files in seq order, each in one transaction with its receipt, and holds a file whose
earlier seq has not arrived (a download that failed, a listing that left it out, a file sealed with a key this PC
no longer has): nothing later in that stream is applied before it. Receipts (the cloud_receipts setting, copied
into the manifest with `delivery: 2`): {stream: {"device", "seq": the highest applied, "digests": {seq: sha256} for
the last DIGESTS, "want": the first missing seq while later ones wait}}. A file at or below its stream's receipt
is a duplicate: deleted when its digest matches or is no longer kept, refused and retained when it differs.
Receipts are never pruned (one small entry per phone journal), so a file resent much later is never applied twice.

A legacy batch applies only above the `applied` floor (an older PC may have applied its unnumbered copy) and
raises the floor. A file without `stream` (an older phone build) keeps the floor rules, but once its device sends
numbered files its unnumbered copies wait for the numbered ones, and are deleted when the floor passes them.

run() applies one file on the Writer: database helpers' commit() waits for the end of the file, every library
file it changes is copied first into data/.phone-intake/ and every one it makes is listed there, and the commit
writes a token with the receipts. recover() (each file, and server/sync.py boot) finishes a committed file whose
journal is still there, or puts the library files back and removes the ones it made. A change that raises for its
own content is skipped and counted as before; an error of the PC itself (disk, database) undoes the whole file,
which waits for the next look.
"""
import copy
import json
import os
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from core import app_console
from library import mirror
from server import intake

APPLIED = 'cloud_applied'                 # server/sync.py S_APPLIED
ALIAS = 'cloud_uid_alias'                 # server/sync.py S_ALIAS
CANVAS_RESULTS = 'cloud_canvas_results'   # server/sync.py S_CANVAS_RESULTS
ALIAS_KEEP = 500                          # server/sync.py ALIAS_KEEP
RECEIPTS = 'cloud_receipts'
COMMIT = 'cloud_intake_commit'            # the token of the last file committed
DIGESTS = 32
UNDO = '.phone-intake'
_STREAM = re.compile(r'^[0-9a-f]{32}$')
_MAX = 2 ** 53 - 1


def kind(doc: dict) -> str:
    """'v1' (no stream: the floor rules), 'v2' (numbered), 'newer' (a format this PC cannot read yet) or 'invalid'."""
    fmt = doc.get('format', 1)
    if type(fmt) is not int or fmt < 1:
        return 'invalid'
    if fmt > mirror.CHANGE_FORMAT:
        return 'newer'
    if 'stream' not in doc:
        return 'v1'
    s, n, a, at = doc.get('stream'), doc.get('seq'), doc.get('acked', 0), doc.get('at')
    ok = (isinstance(s, str) and bool(_STREAM.fullmatch(s)) and type(n) is int and 1 <= n <= _MAX
          and type(a) is int and 0 <= a <= _MAX and type(at) is int and 0 < at <= _MAX
          and isinstance(doc.get('device'), str) and bool(doc['device']) and type(doc.get('legacy', False)) is bool
          and isinstance(doc.get('changes'), list))
    return 'v2' if ok else 'invalid'


def digest(doc: dict) -> str:
    """What makes two copies of a numbered file the same file: its number, its time and its changes."""
    return intake._digest({'stream': doc['stream'], 'seq': doc['seq'], 'at': doc['at'], 'changes': doc['changes']})


def clean(value) -> dict:
    """Receipts read back (the setting, a manifest): entries of the wrong shape are left out."""
    out = {}
    for stream, r in (value.items() if isinstance(value, dict) else ()):
        if not isinstance(stream, str) or not _STREAM.fullmatch(stream) or not isinstance(r, dict):
            continue
        seq = r.get('seq')
        if type(seq) is not int or not 0 <= seq <= _MAX:
            continue
        dig = r.get('digests') if isinstance(r.get('digests'), dict) else {}
        entry = {'device': str(r.get('device') or '')[:40], 'seq': seq,
                 'digests': {k: v for k, v in dig.items() if isinstance(k, str) and k.isdigit() and isinstance(v, str)
                             and re.fullmatch(r'[0-9a-f]{64}', v)}}
        if type(r.get('want')) is int and seq < r['want'] <= _MAX:
            entry['want'] = r['want']
        out[stream] = entry
    return out


def receipts(db) -> dict:
    return clean(_setting(db, RECEIPTS))


def _setting(db, name: str) -> dict:
    try:
        got = json.loads(db.get_setting(name, '') or '{}')
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}


def take(rec: dict, doc: dict) -> str:
    """What to do with one numbered file now: 'apply', 'duplicate', 'conflict' or 'hold'."""
    r = rec.get(doc['stream']) or {'seq': 0, 'digests': {}}
    n = max(r['seq'], doc.get('acked', 0))
    if doc['seq'] <= n:
        known = r['digests'].get(str(doc['seq']))
        return 'conflict' if known and known != digest(doc) else 'duplicate'
    return 'apply' if doc['seq'] == n + 1 else 'hold'


def advance(rec: dict, doc: dict) -> dict:
    """The receipts once `doc` is applied (a new dict: the old one stays until the commit)."""
    rec = copy.deepcopy(rec)
    r = rec.setdefault(doc['stream'], {'device': '', 'seq': 0, 'digests': {}})
    r['device'], r['seq'] = str(doc['device'])[:40], doc['seq']
    r['digests'][str(doc['seq'])] = digest(doc)
    r['digests'] = {k: v for k, v in r['digests'].items() if int(k) > doc['seq'] - DIGESTS}
    r.pop('want', None)
    return rec


def fatal(e: BaseException) -> bool:
    """An error of this PC (disk, database), not of the change: the whole file waits for the next look."""
    return isinstance(e, (OSError, MemoryError, sqlite3.OperationalError)) or type(e) is sqlite3.DatabaseError


# ── one file, atomically ─────────────────────────────────────────────────────────
class Batch:
    """db.conn while one change file applies: the real connection, except that commit() waits for the file."""

    def __init__(self, db, conn):
        self._db, self._conn = db, conn
        self.batch = self                  # server/intake.py looks for db.conn.batch
        self.root = Path(db.data_dir) / UNDO
        self.token = secrets.token_hex(16)
        self.files: list[dict] = []        # [{'path': relative to the library folder, 'pre': copy name or None}]
        self.folders: list[int] = []       # items deleted: their folders go after the commit
        self.change_files: dict[str, bytes | None] = {}
        self.change_folders = 0

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def commit(self):
        pass

    def rollback(self):
        self._conn.execute('ROLLBACK TO change')
        self._conn.execute('RELEASE change')
        for rel, before in self.change_files.items():
            path = Path(self._db.data_dir) / rel
            if before is None:
                path.unlink(missing_ok=True)
            else:
                _write(path, before)
        del self.folders[self.change_folders:]
        self._save()

    def begin(self):
        self._conn.execute('SAVEPOINT change')
        self.change_files = {}
        self.change_folders = len(self.folders)

    def end(self):
        self._conn.execute('RELEASE change')

    def fatal(self, e: BaseException) -> bool:
        return fatal(e)

    def before(self, path) -> None:
        """Called before a library file is changed or removed: keep what it holds."""
        rel = self._rel(path)
        if rel is None:
            return
        src, pre = Path(self._db.data_dir) / rel, None
        # A skipped change restores its own starting point, including earlier edits in this batch.
        if rel not in self.change_files:
            self.change_files[rel] = src.read_bytes() if src.is_file() else None
        if any(f['path'] == rel for f in self.files):
            return
        if src.is_file():
            pre = f'pre-{len(self.files)}'
            self.root.mkdir(parents=True, exist_ok=True)
            _copy(src, self.root / pre)
        self.files.append({'path': rel, 'pre': pre})
        self._save()

    def created(self, path) -> None:
        """Called right after a new library file was made: undo removes it."""
        rel = self._rel(path)
        if rel is None:
            return
        self.change_files.setdefault(rel, None)
        if any(f['path'] == rel for f in self.files):
            return
        self.files.append({'path': rel, 'pre': None})
        self._save()

    def folder(self, item_id: int) -> None:
        self.folders.append(int(item_id))
        self._save()

    def _rel(self, path):
        try:
            return Path(path).resolve().relative_to(Path(self._db.data_dir).resolve()).as_posix()
        except ValueError:
            return None

    def _save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        _write(self.root / 'journal.json', json.dumps({'token': self.token, 'files': self.files, 'folders': self.folders}).encode('utf-8'))


def _copy(src: Path, dst: Path) -> None:
    _write(dst, src.read_bytes())


def _write(dst: Path, data: bytes) -> None:
    tmp = dst.with_name(dst.name + '.tmp')
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dst)


def _undo(data_dir: Path, files: list) -> None:
    root = Path(data_dir) / UNDO
    for f in reversed(files):
        target = _inside(data_dir, f.get('path'))
        if target is None:
            continue
        if f.get('pre'):
            _copy(root / str(f['pre']), target)
        elif target.is_file():
            target.unlink()


def _inside(data_dir: Path, rel) -> Path | None:
    if not isinstance(rel, str) or not rel:
        return None
    base = Path(data_dir).resolve()
    target = (base / rel).resolve()
    return target if target != base and target.is_relative_to(base) and UNDO not in target.relative_to(base).parts else None


def _remove_folders(db, folders) -> None:
    for i in folders:
        try:
            shutil.rmtree(db.items_dir / str(int(i)), ignore_errors=True)
        except Exception:
            pass


def recover(db) -> bool:
    """On the Writer, before any file applies: finish or undo the file an interruption left. True when it did."""
    root = Path(db.data_dir) / UNDO
    if not root.exists():
        return False
    try:
        journal = json.loads((root / 'journal.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        # The first preimage can exist before its journal is saved; no library write has started yet.
        shutil.rmtree(root)
        return True
    if (not isinstance(journal, dict) or not isinstance(journal.get('token'), str)
            or not _STREAM.fullmatch(journal['token']) or not isinstance(journal.get('files'), list)
            or not isinstance(journal.get('folders'), list)):
        raise ValueError('Invalid phone undo journal; keep it for recovery.')
    files = journal['files']
    if any(not isinstance(f, dict) or _inside(db.data_dir, f.get('path')) is None
           or (f.get('pre') is not None and not re.fullmatch(r'pre-\d+', str(f['pre']))) for f in files):
        raise ValueError('Invalid phone undo file; keep the journal for recovery.')
    if journal.get('token') and db.get_setting(COMMIT, '') == journal['token']:
        _remove_folders(db, journal.get('folders') if isinstance(journal.get('folders'), list) else [])
    else:
        _undo(db.data_dir, [f for f in files if isinstance(f, dict)])
        if files:
            app_console.emit('log', 'From the phone: an interrupted change file was undone; it applies again on the next look',
                             level='warning')
    shutil.rmtree(root)
    return True


def run(db, fn):
    """Run fn() as one change file: what it writes commits with the receipts it sets, or nothing stays."""
    recover(db)
    conn = db.conn
    conn.commit()                          # nothing from earlier is folded into this file
    b = Batch(db, conn)
    conn.execute('BEGIN')
    db.conn = b
    try:
        result = fn()
        db.set_setting(COMMIT, b.token)
        conn.commit()
    except BaseException:
        db.conn = conn
        try:
            conn.rollback()
        finally:
            _undo(db.data_dir, b.files)
            shutil.rmtree(b.root, ignore_errors=True)
        raise
    finally:
        db.conn = conn
    _remove_folders(db, b.folders)
    shutil.rmtree(b.root, ignore_errors=True)
    return result


# ── one look at the phone's files ───────────────────────────────────────────────
@dataclass
class Round:
    out: intake.Applied
    done: list = field(default_factory=list)   # the files applied, or seen before: delete them
    held: int = 0          # wait for an earlier file of their stream
    refused: int = 0       # the same number with other content: retained, never applied
    blocked: int = 0       # this PC could not apply them now (disk, database, a failed download): the next look
    superseded: int = 0    # unnumbered copies from a phone that numbers its files: its numbered copies apply
    changed: bool = False  # receipts or the floor moved: the manifest says so


def _persist(db, out: intake.Applied, rec: dict) -> None:
    db.set_setting(APPLIED, json.dumps(out.applied, sort_keys=True))
    db.set_setting(ALIAS, json.dumps(dict(list(out.alias.items())[-ALIAS_KEEP:])))
    db.set_setting(CANVAS_RESULTS, json.dumps(out.canvas_results, sort_keys=True))
    db.set_setting(RECEIPTS, json.dumps(rec, sort_keys=True))


def intake_round(db, docs: list, check=None, defer_legacy: bool = False) -> Round:
    """On the Writer: apply what can be applied of these opened files [(listing entry, doc)], each file atomically.
    `defer_legacy`: a download failed this look, so no unnumbered file applies (its floor could pass the unread one)."""
    check = check or (lambda: None)
    rec = receipts(db)
    r = Round(intake.Applied(applied=_setting(db, APPLIED), alias=_setting(db, ALIAS),
                             canvas_results=_setting(db, CANVAS_RESULTS)))
    stored = copy.deepcopy(rec)

    def one(doc, legacy_ack: bool, keep_floor: bool, new_rec, numbered: bool):
        part = copy.deepcopy(r.out)

        def work():
            if not legacy_ack:
                floor = dict(part.applied)
                try:
                    intake.apply(db, doc, part)
                except Exception as e:     # apply skips what it cannot read: this is a backstop
                    if numbered or fatal(e):
                        raise              # a numbered file is never acknowledged unapplied: it waits
                    app_console.emit('log', 'Drive mirror: a phone change file could not be applied', level='error', error=e)
                    part.skipped += 1      # an unnumbered file keeps the floor rules: its time is recorded
                    device, at = str(doc.get('device') or 'phone')[:40], intake._int(doc.get('at'))
                    if at:
                        part.applied[device] = max(intake._int(part.applied.get(device)), at)
                if keep_floor:
                    part.applied = floor
            _persist(db, part, new_rec)
        run(db, work)
        r.out = part

    numbered = sorted((d for d in docs if kind(d[1]) == 'v2'), key=lambda d: (d[1]['stream'], d[1]['seq']))
    blocked, wants = set(), {}
    for f, doc in numbered:
        check()
        stream = doc['stream']
        if stream in blocked:
            r.blocked += 1
            continue
        what = take(rec, doc)
        if what == 'duplicate':
            r.done.append(f)
        elif what == 'conflict':
            r.refused += 1
            app_console.emit('log', 'From the phone: refused a change file that reuses an applied number with other content',
                             level='warning')
        elif what == 'hold':
            r.held += 1
            # `acked` may be left out of a numbered file: kind() and take() read it as 0
            wants.setdefault(stream, (max((rec.get(stream) or {}).get('seq', 0), doc.get('acked', 0)) + 1, str(doc['device'])[:40]))
        else:
            device = str(doc['device'])[:40]
            legacy = doc.get('legacy') is True
            new_rec = advance(rec, doc)
            try:                           # a legacy batch an unnumbered copy already applied: only the receipt moves
                one(doc, legacy and doc['at'] <= intake._int(r.out.applied.get(device)), not legacy, new_rec, True)
            except Exception as e:
                blocked.add(stream)
                r.blocked += 1
                app_console.emit('log', 'From the phone: a change file waits for the next look', level='warning', error=e)
                continue
            rec = new_rec
            r.done.append(f)
            r.changed = True
    for stream, entry in rec.items():
        if stream not in wants:
            entry.pop('want', None)
    for stream, (want, device) in wants.items():
        rec.setdefault(stream, {'device': device, 'seq': 0, 'digests': {}})['want'] = want
    numbered_devices = {e['device'] for e in rec.values() if e['seq']}
    stop_legacy = defer_legacy
    legacy_docs = sorted((d for d in docs if kind(d[1]) == 'v1'), key=lambda d: intake._int(d[1].get('at')))
    for f, doc in legacy_docs:
        check()
        device, at = str(doc.get('device') or 'phone')[:40], intake._int(doc.get('at'))
        if at and at <= intake._int(r.out.applied.get(device)):
            r.done.append(f)               # applied before (its delete did not go through)
        elif device in numbered_devices:
            r.superseded += 1
        elif stop_legacy:
            r.blocked += 1
        else:
            try:
                one(doc, False, False, rec, False)
            except Exception as e:
                if not fatal(e):
                    raise
                stop_legacy = True         # in time order: a later file would pass this one's floor
                r.blocked += 1
                app_console.emit('log', 'From the phone: a change file waits for the next look', level='warning', error=e)
                continue
            r.done.append(f)
            r.changed = True
    if rec != stored:
        db.set_setting(RECEIPTS, json.dumps(rec, sort_keys=True))
        r.changed = True
    return r
