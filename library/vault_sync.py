"""Vault sync core (projects/vault-sync/plans/01-export-and-merge.md; owner vaults: spec
docs/superpowers/specs/2026-10-28-owner-vault-sync-design.md): which files count, a scan that names every file by
content id, the three-way merge, conflict copies, .trash/ and the deletion brake.

Pure files and dicts: no Drive, no SQLite, no threads. server/sync.py (PC) and web/src/mobile/vault/merge.ts
(phone, a port of merge() checked against tests/fixtures/vault_cases.json) both build on it.

Two rule sets, chosen by the PC's file list. A classic vault (no `generated` key) keeps the first rules: the
classic export's Content Manager/ is one way, PC to phone, everything else two ways. A vault with a manifest
(spec 1b) publishes `generated` (the paths Brainamon wrote and nobody changed: the only one-way paths),
`removed` (deletion records: path and the SHA-256 Brainamon last wrote) and `vault` (its identity); the phone
answers with `caps`."""
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

ONE_WAY = 'Content Manager/'            # the classic export's folder: PC to phone only (a vault without a manifest)
MAX_FILE = 50 * 1024 * 1024
BRAKE_FILES, BRAKE_PERCENT, BRAKE_MIN = 20, 10, 3
INDEX_LOGICAL = 'vault/index'
INDEX_PREFIX, BLOB_PREFIX = 'vi-', 'vb-'
STATUS_LOGICAL, STATUS_PREFIX = 'vault/status', 'vs-'     # the PC's round status, read by the phone's Vault panel
TMP_SUFFIX = '.vsync-tmp'
NOMEDIA = '.nomedia'
CAPS = ('generated', 'identity')        # what a phone on this app declares in its file list (spec 1b decision 5)
_SKIP = ('.obsidian/plugins', '.obsidian/themes', '.trash', '.git', '.brainamon')
_ID = re.compile(r'[0-9a-f]{32}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def valid_rel(rel) -> bool:
    if not isinstance(rel, str) or not rel or rel.startswith('/') or '\\' in rel or ':' in rel or '\x00' in rel:
        return False
    return all(part not in ('', '.', '..') for part in rel.split('/'))


def excluded(rel: str) -> bool:
    rel = rel.replace('\\', '/').lstrip('/')
    # .nomedia: the phone's own marker that keeps the vault's pictures out of the Android gallery
    if rel.endswith((TMP_SUFFIX, '.vsync-backup')) or rel.startswith('.obsidian/workspace') or rel == NOMEDIA:
        return True
    return any(rel == d or rel.startswith(d + '/') for d in _SKIP)


def blob_name(content_id: str) -> str:
    return BLOB_PREFIX + content_id


def blob_logical(content_id: str) -> str:
    return 'vault/blob/' + content_id


def index_name(key, device: str) -> str:
    return INDEX_PREFIX + key.name('vault/index/' + device)


def status_name(key) -> str:
    return STATUS_PREFIX + key.name('vault/status/pc')


def encode_index(files: dict, device: str, *, vault: str = '', generated=None, removed=None, caps=None, kept=None) -> bytes:
    """The sealed file list. The PC adds `vault` (the identity), `generated` (given, even empty, only for a
    vault with a manifest) and `removed` ({path: sha256}); a phone adds `caps`, `vault` and `kept` ({path: deletion-record SHA-256 it processed and kept as an edit}). Older readers ignore them."""
    d = {'v': 1, 'device': device, 'files': files}
    if vault:
        d['vault'] = vault
    if generated is not None:
        d['generated'] = sorted(generated)
    if removed:
        d['removed'] = dict(removed)
    if caps:
        d['caps'] = sorted(caps)
    if kept:
        d['kept'] = dict(kept)
    return json.dumps(d, sort_keys=True, separators=(',', ':')).encode('utf-8')


def decode_index(data: bytes) -> tuple[str, dict]:
    """(device, {path: content id}); entries with a bad path or id are dropped. The pre-1b reader: it sees
    none of vault, generated, removed or caps, which is what an older phone does."""
    full = decode_index_full(data)
    return full['device'], full['files']


def decode_index_full(data: bytes) -> dict:
    """{device, files, vault, generated (a set, or None for a classic list), removed ({path: sha256}), caps (a
    set)}. Bad entries are dropped: a generated path must be in files, a removed path must not be."""
    d = json.loads(data)
    if not isinstance(d, dict) or not isinstance(d.get('files'), dict):
        raise ValueError('Invalid vault file list.')
    files = {r: i for r, i in (d.get('files') or {}).items()
             if valid_rel(r) and not excluded(r) and isinstance(i, str) and _ID.match(i)}
    gen = d.get('generated')
    generated = {r for r in gen if isinstance(r, str) and r in files} if isinstance(gen, list) else None
    rem = d.get('removed')
    removed = {r: h for r, h in rem.items()
               if valid_rel(r) and not excluded(r) and r not in files and isinstance(h, str) and _SHA.match(h)} if isinstance(rem, dict) else {}
    kept_raw = d.get('kept')
    kept = {r: h for r, h in kept_raw.items() if r in files and isinstance(h, str) and _SHA.match(h)} if isinstance(kept_raw, dict) else {}
    caps = {c for c in d.get('caps') if isinstance(c, str)} if isinstance(d.get('caps'), list) else set()
    vault = d.get('vault')
    return {'device': str(d.get('device') or ''), 'files': files, 'generated': generated, 'removed': removed,
            'caps': caps, 'vault': vault if isinstance(vault, str) else '', 'kept': kept}


def path_identity(folder) -> str:
    """A classic vault's identity (spec 1b decision 4): a hash of its resolved folder path. A vault with a
    manifest uses the manifest's vault_id instead."""
    p = str(Path(folder).resolve()).replace('\\', '/').lower()
    return 'path:' + hashlib.sha256(p.encode('utf-8')).hexdigest()[:32]


def sha256_hex(data: bytes) -> str:
    """The manifest's hash of a file (library/owner_vault.py data_hash): what a deletion record carries."""
    return hashlib.sha256(data).hexdigest()


def skipped_note(count: int) -> str:
    """The words for the files a scan leaves out because they are over MAX_FILE ('' for none): the PC's Settings and the
    phone's Vault panel must not call a vault complete while some are missing."""
    if count <= 0:
        return ''
    many = count != 1
    return f"{count:,} file{'s' if many else ''} over {MAX_FILE // 1048576} MiB {'are' if many else 'is'} not synced."


def scan(root, key, cache: dict | None = None, should_stop=lambda: False, skipped: dict | None = None, *, progress=None) -> tuple[dict, dict]:
    """({path: content id}, cache). `cache` is {path: [size, mtime_ns, id]} from the last scan: a file with the
    same size and mtime is not read again. A file modified in the last two seconds is not cached: an edit that
    keeps the size inside the same clock tick would otherwise keep its old id. A file over MAX_FILE is not listed;
    `skipped`, when given, takes {path: size} of each one."""
    def check():
        if should_stop():
            raise OSError('Vault sync is stopping.')
    check()
    root, cache = Path(root), cache or {}
    files, fresh = {}, {}
    paths = []
    if progress:
        progress('Finding vault files', 0, 0)
    settled = time.time_ns() - 2_000_000_000
    for dirpath, dirnames, names in os.walk(root):
        check()
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = '' if rel_dir == '.' else rel_dir
        dirnames[:] = [d for d in dirnames if not excluded(f'{rel_dir}/{d}/x'.lstrip('/'))]
        for n in names:
            check()
            rel = f'{rel_dir}/{n}'.lstrip('/')
            p = Path(dirpath) / n
            if excluded(rel) or not valid_rel(rel):
                continue
            paths.append((rel, p))
        if progress:
            progress('Finding vault files', len(paths), 0)
    if progress:
        progress('Checking vault files', 0, len(paths))
    for done, (rel, p) in enumerate(paths, 1):
        check()
        try:
            st = p.stat()
            if not p.is_file():
                continue
            if st.st_size > MAX_FILE:
                if skipped is not None:
                    skipped[rel] = st.st_size
                continue
            c = cache.get(rel)
            fid = c[2] if c and c[0] == st.st_size and c[1] == st.st_mtime_ns else key.content_id(p.read_bytes())
            files[rel] = fid
            if st.st_mtime_ns < settled:
                fresh[rel] = [st.st_size, st.st_mtime_ns, fid]
        except OSError:
            continue
        finally:
            if progress:
                progress('Checking vault files', done, len(paths))
    check()
    return files, fresh


@dataclass
class Plan:
    pull: dict = field(default_factory=dict)         # path -> content id to download and write
    trash: list = field(default_factory=list)        # paths to move to .trash/
    conflicts: dict = field(default_factory=dict)    # path -> copy name (phone only): own content is copied there first
    lost: list = field(default_factory=list)         # paths this side deleted: the new list drops them
    legacy: list = field(default_factory=list)       # phone only: leftover Content Manager/ copies kept, never listed or sent
    new_base: dict = field(default_factory=dict)     # the base to store once the round has succeeded
    brake: bool = False
    reason: str = ''


def conflict_name(rel: str, when: datetime) -> str:
    p = PurePosixPath(rel)
    return str(p.with_name(f'{p.stem} (phone conflict {when:%Y-%m-%d %H%M}){p.suffix}'))


def _over(n: int, total: int) -> bool:
    return n > BRAKE_FILES or (n >= BRAKE_MIN and n * 100 > BRAKE_PERCENT * total)


def merge(base: dict, mine: dict, theirs: dict, role: str, when: datetime, *,
          generated=None, removed=None, mine_hash=None, fresh: bool = False, kept=None) -> Plan:
    """Three-way merge of two {path: content id} maps against `base`.

    Classic rules (`generated` is None): Content Manager/ is one way, PC to phone; everything else two ways.
    Manifest-vault rules (`generated` is a set, spec 1b decision 3): only the generated paths are one way (a
    phone copy that is absent or equals the base takes the PC's directly; any other differing copy is saved as a
    conflict copy first). `removed` ({path: sha256}, the PC's deletion records): the phone trashes its copy only
    when it equals the base or that hash (`mine_hash`: {path: sha256 of the phone's copy}); an edited copy stays,
    keeps its base, and reaches the PC as the user's file. A leftover Content Manager/ copy the PC does not list
    is never uploaded (`legacy`) and trashed only when equal to the base; the PC never takes a phone-only
    Content Manager/ path. On the PC, a removed path is pulled only after a matching `kept` acknowledgement; stale phone lists never resurrect it. `fresh` (an identity change, decision 4): nothing is trashed or lost; the rest
    works as a first sync. One-way trashing never counts against the brake."""
    plan = Plan()
    nb = plan.new_base
    removed = removed or {}
    mine_hash = mine_hash or {}
    kept = kept or {}
    manifest = generated is not None
    free = set()                                      # trashed under a one-way rule: not counted by the brake
    for rel in sorted(set(base) | set(mine) | set(theirs)):
        b, m, t = base.get(rel), mine.get(rel), theirs.get(rel)
        if manifest:
            if rel in generated:                      # a page Brainamon wrote: one way (t is never None here)
                if role == 'pc':
                    if m is not None and m == t:
                        nb[rel] = m
                    elif b is not None:
                        nb[rel] = b
                elif m is None or m == b or m == t:   # absent, or provably a PC version
                    if m != t:
                        plan.pull[rel] = t
                    nb[rel] = t
                else:                                 # an edit, or a copy of unknown origin
                    plan.conflicts[rel] = conflict_name(rel, when)
                    plan.pull[rel] = t
                    nb[rel] = t
                continue
            if role == 'pc' and m is None and rel in removed:
                # Only the phone can distinguish its old generated copy from an edit after seeing this record.
                if t is not None and kept.get(rel) == removed[rel]:
                    plan.pull[rel] = t
                    nb[rel] = t
                elif b is not None:
                    nb[rel] = b
                continue
            if role == 'pc' and m is None and rel.startswith(ONE_WAY):
                continue                              # a phone's leftover classic copy: never taken (decision 3)
            if role == 'phone' and t is None and m is not None and (rel in removed or rel.startswith(ONE_WAY)):
                unedited = m == b or (rel in removed and mine_hash.get(rel) == removed[rel])
                if unedited and not fresh:
                    plan.trash.append(rel)
                    free.add(rel)
                else:
                    if b is not None:
                        nb[rel] = b
                    if rel.startswith(ONE_WAY):
                        plan.legacy.append(rel)
                continue
        elif rel.startswith(ONE_WAY):
            if role == 'pc':
                if m is not None:
                    nb[rel] = m
            elif t is None:
                if m is not None and not fresh:
                    plan.trash.append(rel)
                    free.add(rel)
                elif b is not None:
                    nb[rel] = b
            else:
                if m != t:
                    plan.pull[rel] = t
                nb[rel] = t
            continue
        if m == t:
            if m is not None:
                nb[rel] = m
        elif m == b:                                  # only theirs changed
            if t is None:
                if fresh:
                    nb[rel] = b
                else:
                    plan.trash.append(rel)
            else:
                plan.pull[rel] = t
                nb[rel] = t
        elif t == b:                                  # only mine changed
            if m is None and not fresh and (role != 'pc' or rel not in removed):
                plan.lost.append(rel)
            if b is not None:                         # the base moves only once the other side has it too
                nb[rel] = b
        elif m is None:                               # I deleted, they edited: the edit wins
            plan.pull[rel] = t
            nb[rel] = t
        elif t is None:                               # they deleted, I edited: the edit wins
            nb[rel] = b
        elif role == 'phone':                         # both edited: the PC's copy takes the path
            plan.conflicts[rel] = conflict_name(rel, when)
            plan.pull[rel] = t
            nb[rel] = t
        elif b is not None:                           # the PC waits for the phone to make the copy
            nb[rel] = b
    counted = [r for r in plan.trash if r not in free]
    for what, n in (('removed here', len(counted)), ('removed there', len(plan.lost))):
        if _over(n, len(base)):
            plan.brake = True
            plan.reason = f'{n} files would be {what} (the limit is {BRAKE_FILES} files or {BRAKE_PERCENT}% of the vault).'
            break
    return plan


def write_atomic(root, rel: str, data: bytes) -> None:
    dst = Path(root) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + TMP_SUFFIX)
    tmp.write_bytes(data)
    os.replace(tmp, dst)


def to_trash(root, rel: str) -> None:
    src = Path(root) / rel
    if not src.exists():
        return
    dst = Path(root) / '.trash' / rel
    n = 2
    while dst.exists():
        dst = dst.with_name(f'{src.stem} ({n}){src.suffix}')
        n += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def apply(root, plan: Plan, fetch, should_stop=lambda: False) -> dict:
    """Do a plan on disk. `fetch(content id) -> bytes` returns verified plaintext. Order: conflict copies
    first (so the phone's edit is on disk before the PC's copy replaces it), then pulls, then the trash."""
    def check():
        if should_stop():
            raise OSError('Vault sync is stopping.')
    root = Path(root)
    reserved = set(plan.pull)
    for rel, copy in plan.conflicts.items():
        check()
        src = root / rel
        if src.exists():
            preferred, n = PurePosixPath(copy), 2
            while copy in reserved or (root / copy).exists():
                copy = str(preferred.with_name(f'{preferred.stem} ({n}){preferred.suffix}'))
                n += 1
            reserved.add(copy)
            dst = root / copy
            dst.parent.mkdir(parents=True, exist_ok=True)
            with dst.open('xb') as out:
                out.write(src.read_bytes())
    for rel, fid in plan.pull.items():
        check()
        data = fetch(fid)
        check()
        write_atomic(root, rel, data)
    for rel in plan.trash:
        check()
        to_trash(root, rel)
    return {'pulled': len(plan.pull), 'trashed': len(plan.trash), 'conflicts': len(plan.conflicts)}
