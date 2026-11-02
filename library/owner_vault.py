"""owner_vault.py - identity, names, ownership and recoverable writes of a Brainamon-owned vault
(spec 2026-10-28, decisions 1, 2, 4, 8, 10). Pure files: no DB, no threads, no network.

<vault>/.brainamon/manifest.json:
  {version: 1, vault_id, library_id,
   names: {item: {id: name}, topic: {topic id: name}, tag: {folded key: name}, category: {folded key: name}},
   files: {relative path: {hash, source, key}},
   removed: {relative path: hash}                 deletion records (spec 1b decision 2): the hash Brainamon last
                                                  wrote before it removed the file; kept only while vault sync is
                                                  on (the render clears them otherwise), pruned by the PC's rounds
   pending: [{path, old, new, source, key}]      only between a pass's first manifest save and its last}

Brainamon overwrites or removes a file only when it is listed and its current hash equals the recorded one.
A listed file with another hash was edited by the user: adopted, never updated or removed. An unlisted
file is never touched, in or outside Brainamon/. Every write is temp file + os.replace, and the pending
list makes a crash between the writes and the manifest save settle correctly next time (settle_pending).
The caller holds the vault lock (server/map_service.py VAULT_LOCK).
"""
import hashlib
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

from library.obsidian_export import _slugify, _yaml_value
from library.owner_pages import FOLDER, SOURCE_LINE

META_DIR = '.brainamon'
MANIFEST = META_DIR + '/manifest.json'
TMP_SUFFIX = '.brainamon-tmp'
RESERVED = {'con', 'prn', 'aux', 'nul'} | {f'com{n}' for n in range(1, 10)} | {f'lpt{n}' for n in range(1, 10)}
COPIED = ('Reports', 'Attachments', 'Notes')      # Brainamon-only folders whose files carry no source line
OWN = ('.obsidian', META_DIR, FOLDER)              # entries that do not count as "other files" in a folder
CONFIRM_MAX = 5                                    # 1..5 other entries: Use it anyway; more: refused
OTHER_LIBRARY = 'This vault belongs to another Brainamon library.'
TAKEOVER = 'This folder is a Brainamon vault from an earlier install or another library.'
TOO_MANY = ('This folder already holds other files. Brainamon needs an empty vault of its own; connecting a vault '
            'you already use comes in a later update.')


class VaultError(Exception):
    pass


def new_id() -> str:
    return secrets.token_hex(16)


def file_hash(path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def data_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    tmp.write_bytes(data)
    os.replace(tmp, path)


def new_manifest(library_id: str, vault_id: str | None = None) -> dict:
    """A fresh manifest. `vault_id`: the identity vault sync recorded for this folder (spec 1b decision 4:
    Reclaim reuses it so sync history stays valid); otherwise a new one."""
    return {'version': 1, 'vault_id': vault_id or new_id(), 'library_id': str(library_id), 'names': {}, 'files': {}}


def read_manifest(vault) -> dict | None:
    """The manifest, or None when missing or unreadable (then nothing that exists is touched)."""
    try:
        d = json.loads((Path(vault) / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get('files'), dict) or not d.get('library_id'):
        return None
    d.setdefault('names', {})
    d.setdefault('vault_id', new_id())
    return d


def write_manifest(vault, man: dict) -> None:
    atomic_write(Path(vault) / MANIFEST, json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True).encode('utf-8'))


def generated_paths(vault, man: dict) -> set:
    """Spec 1b decision 1: the listed paths whose file still carries the recorded hash, the only ones vault sync
    sends one way. An adopted (edited) or missing file is not generated. Computed when asked, never stored."""
    root = Path(vault)
    return {rel for rel, entry in man['files'].items() if file_hash(root / rel) == entry['hash']}


def record_removed(man: dict, rel: str, hash_: str | None) -> None:
    """Spec 1b decision 2: a generated file Brainamon removes leaves its last hash, so a phone can tell a page
    Brainamon deleted from one the user took over. Nothing is recorded without a hash."""
    if hash_:
        man.setdefault('removed', {})[rel] = hash_


class Names:
    """The manifest's names map: a name is chosen once and kept (decision 3)."""

    def __init__(self, man: dict):
        self.map = man.setdefault('names', {})
        self.changed = False

    def _table(self, source: str) -> dict:
        return self.map.setdefault(source, {})

    def item(self, item_id, title: str) -> str:
        t, key = self._table('item'), str(item_id)
        if key not in t:
            t[key] = f"{_slugify((title or '')[:60])}-{item_id}"
            self.changed = True
        return t[key]

    def topic(self, tid: str, name: str) -> str:
        """The recorded name wins over the cache's (a cache rebuilt from scratch must not rename pages)."""
        t = self._table('topic')
        if tid not in t:
            t[tid] = name
            self.changed = True
        return t[tid]

    def hub(self, source: str, key: str, label: str) -> str:
        """Tags and categories: the slug, or the next free -2, -3 suffix when another source holds it or
        it is a Windows reserved name."""
        t = self._table(source)
        if key not in t:
            taken, base = set(t.values()), _slugify(label)
            cand, n = base, 1
            while cand in RESERVED or cand in taken:
                n += 1
                cand = f'{base}-{n}'
            t[key] = cand
            self.changed = True
        return t[key]


# ── where a vault may be (decisions 1, 2) ────────────────────────────────────
def default_location() -> Path:
    """<Documents>\\Brainamon Vault: the Windows Documents known folder (it may be redirected, for example
    to OneDrive); elsewhere ~/Documents."""
    docs = None
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                            ('Data4', wintypes.BYTE * 8)]

            documents = GUID(0xFDD39AD0, 0x238F, 0x46AF, (wintypes.BYTE * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(documents), 0, None, ctypes.byref(out)) == 0:
                docs = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
        except Exception:
            docs = None
    return (docs or Path.home() / 'Documents') / 'Brainamon Vault'


def _within(a: Path, b: Path) -> bool:
    return a == b or b in a.parents


def location_error(folder, data_dir, home) -> str:
    """Decision 2, both directions: '' when the folder may hold a vault. `home`: core.app_paths.HOME."""
    f, d, h = Path(folder).resolve(), Path(data_dir).resolve(), Path(home).resolve()
    if _within(f, d) or _within(d, f):
        return 'Choose a folder that is neither inside nor around the Brainamon data folder.'
    if _within(f, h) or _within(h, f):
        return 'Choose a folder that is neither inside nor around the Brainamon settings folder.'
    return ''


def folder_check(folder, library_id: str) -> tuple:
    """Decision 1: ('ok' | 'confirm' | 'takeover' | 'refused', message, count). ok: missing, empty,
    .obsidian/ only, or this library's previous render. takeover: another library's render (an earlier
    install, a Drive restore, a rebuilt library): the caller asks before taking it over; count = the files
    that library listed; the 5-file rule does not apply (the other entries are the user's own). confirm:
    1 to CONFIRM_MAX top-level entries besides .obsidian/, .brainamon/ and Brainamon/ (Use it anyway; they
    are never touched). refused: more, or a file."""
    p = Path(folder)
    if not p.exists():
        return 'ok', '', 0
    if not p.is_dir():
        return 'refused', 'That path is a file, not a folder.', 0
    entries = [e.name for e in p.iterdir()]
    if META_DIR in entries or FOLDER in entries:
        man = read_manifest(p)
        if man is not None and man['library_id'] != str(library_id):
            return 'takeover', TAKEOVER, len(man['files'])
    others = sorted(n for n in entries if n not in OWN)
    if not others:
        return 'ok', '', 0
    if len(others) <= CONFIRM_MAX:
        shown = ', '.join(others[:3]) + (', ...' if len(others) > 3 else '')
        return 'confirm', f'This folder holds {len(others)} other item(s) ({shown}). Brainamon never touches them.', len(others)
    return 'refused', TOO_MANY, len(others)


def obsidian_vaults(path=None) -> list:
    """Obsidian's own vault list ([{path, open, ts}]) from %APPDATA%\\obsidian\\obsidian.json, an
    undocumented internal file (shape checked on this PC, 2026-10-28, Obsidian 1.14.5). [] when missing,
    unreadable or shaped otherwise: the folder dialog stays the way in."""
    if path is None:
        base = os.environ.get('APPDATA')
        if not base:
            return []
        path = Path(base) / 'obsidian' / 'obsidian.json'
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    vaults = d.get('vaults') if isinstance(d, dict) else None
    if not isinstance(vaults, dict):
        return []
    out = []
    for v in vaults.values():
        if isinstance(v, dict) and isinstance(v.get('path'), str) and v['path']:
            out.append({'path': v['path'], 'open': bool(v.get('open')), 'ts': int(v.get('ts') or 0)})
    return sorted(out, key=lambda v: -v['ts'])


# ── ownership (decision 8) ───────────────────────────────────────────────────
def settle_pending(vault, man: dict) -> None:
    """Recover completed writes and removals; unfinished writes and user edits keep their old ownership."""
    root = Path(vault)
    for p in man.pop('pending', None) or []:
        rel, old, new = p['path'], p.get('old'), p.get('new')
        cur = file_hash(root / rel)
        if cur == new:
            if new is None:
                if p.get('record_removed'):
                    record_removed(man, rel, old)
                man['files'].pop(rel, None)
                if p.get('released'):
                    (man.get('released') or {}).pop(rel, None)
            elif rel in man['files']:
                man['files'][rel]['hash'] = new
            else:
                man['files'][rel] = {'hash': new, 'source': p.get('source', ''), 'key': p.get('key', '')}


def _copy_atomic(src, dst: Path) -> None:
    atomic_write(dst, Path(src).read_bytes())


def apply_render(vault, man: dict, files: dict, track_removed: bool = False) -> dict:
    """One pass. `files`: owner_pages.render's output. Writes listed-and-unchanged or new paths, removes
    listed-and-unchanged paths no longer rendered, adopts listed-and-changed paths, never touches unlisted
    ones. Saves the manifest with `pending` before the writes and without it after. `track_removed` (vault
    sync on): every removal leaves a deletion record and a path rendered again drops its record; off, the
    records are cleared (there is no phone to tell).
    Returns {'written', 'removed', 'adopted': [rel], 'unlisted': [rel]}."""
    root = Path(vault)
    settle_pending(root, man)
    listed = man['files']
    if track_removed:
        for rel in [r for r in man.get('removed') or {} if r in files]:
            del man['removed'][rel]
    else:
        man.pop('removed', None)
    writes, removals, adopted, unlisted = [], [], [], []
    current = {rel: file_hash(root / rel) for rel in set(listed) | set(files)}
    for rel, spec in files.items():
        new = data_hash(spec['data']) if 'data' in spec else file_hash(spec['src'])
        if new is None:
            continue                                     # the source file vanished: leave the copy as it is
        cur = current[rel]
        if rel in listed:
            if cur is not None and cur != listed[rel]['hash']:
                adopted.append(rel)
                continue
            if cur == new:
                listed[rel].update(source=spec['source'], key=spec['key'])
                continue
            writes.append((rel, spec, listed[rel]['hash'] if cur is not None else None, new))
        elif cur is not None:
            unlisted.append(rel)
        else:
            writes.append((rel, spec, None, new))
    for rel, entry in listed.items():
        if rel in files:
            continue
        cur = current[rel]
        if cur is None:
            removals.append((rel, entry['hash'], True))            # already gone: drop the entry
        elif cur == entry['hash']:
            removals.append((rel, entry['hash'], False))
        else:
            adopted.append(rel)
    if writes or removals:
        man['pending'] = ([{'path': r, 'old': o, 'new': n, 'source': s['source'], 'key': s['key']} for r, s, o, n in writes]
                          + [{'path': r, 'old': o, 'new': None, 'record_removed': track_removed} for r, o, _gone in removals])
        write_manifest(root, man)
        for rel, spec, _old, new in writes:
            if 'data' in spec:
                atomic_write(root / rel, spec['data'])
            else:
                _copy_atomic(spec['src'], root / rel)
            listed[rel] = {'hash': new, 'source': spec['source'], 'key': spec['key']}
        for rel, old, gone in removals:
            if not gone:
                try:
                    (root / rel).unlink()
                except FileNotFoundError:
                    pass
            if track_removed:
                record_removed(man, rel, old)
            listed.pop(rel, None)
        man.pop('pending', None)
    write_manifest(root, man)
    return {'written': len(writes), 'removed': len(removals), 'adopted': sorted(adopted), 'unlisted': sorted(unlisted)}


# ── user actions on the manifest (decision 8) ────────────────────────────────
def reset_page(vault, man: dict, rel: str, files: dict) -> None:
    """Reset to generated: overwrite one adopted listed page with its current content, or remove it when
    its source no longer exists. Never for an unlisted path."""
    root = Path(vault)
    settle_pending(root, man)
    if rel not in man['files']:
        raise VaultError('That file is not one Brainamon wrote.')
    spec = files.get(rel)
    man['pending'] = [{'path': rel, 'old': man['files'][rel]['hash'],
                       'new': (data_hash(spec['data']) if 'data' in spec else file_hash(spec['src'])) if spec else None,
                       'source': spec['source'] if spec else '', 'key': spec['key'] if spec else '',
                       'record_removed': spec is None}]
    write_manifest(root, man)
    if spec is None:
        try:
            (root / rel).unlink()
        except FileNotFoundError:
            pass
        record_removed(man, rel, man['files'][rel]['hash'])
        man['files'].pop(rel, None)
    else:
        if 'data' in spec:
            atomic_write(root / rel, spec['data'])
        else:
            _copy_atomic(spec['src'], root / rel)
        man['files'][rel] = {'hash': file_hash(root / rel), 'source': spec['source'], 'key': spec['key']}
    man.pop('pending', None)
    write_manifest(root, man)


def reclaim(vault, man: dict, files: dict) -> int:
    """Reclaim generated pages (a lost manifest): list the unlisted files Brainamon can prove it wrote: .md
    files under Brainamon/ whose frontmatter carries `source: brainamon`, and copies under Reports/,
    Attachments/ and Notes/ only when the current render (`files`) produces that same path. A note of the
    user's saved there stays unlisted. Leftovers of a take-over (`released`) are Remove leftovers' job.
    Returns how many."""
    root = Path(vault)
    base = root / FOLDER
    if not base.is_dir():
        return 0
    released = man.get('released') or {}
    n = 0
    for p in sorted(base.rglob('*')):
        if not p.is_file() or p.name.endswith(TMP_SUFFIX):
            continue
        rel = p.relative_to(root).as_posix()
        if rel in man['files'] or rel in released:
            continue
        parts = p.relative_to(base).parts
        ok = len(parts) > 1 and parts[0] in COPIED and rel in files
        if not ok and p.suffix == '.md':
            try:
                head = p.read_text(encoding='utf-8', errors='replace')[:4000]
            except OSError:
                continue
            ok = head.startswith('---\n') and SOURCE_LINE in head[4:].split('\n---', 1)[0].splitlines()
        if ok:
            h = file_hash(p)
            if h:
                man['files'][rel] = {'hash': h, 'source': 'reclaimed', 'key': ''}
                n += 1
    return n


# ── take-over (decision 4, amended 2026-10-28): refresh what matches, never delete by default ──
def keep_names(vault, man: dict, item_urls: dict) -> None:
    """In memory: keep the earlier library's names only where they still mean the same thing. An item name
    stays when its page exists and its frontmatter records the same link as this library's item with that id
    (the same item: a Drive restore keeps ids and links). Tag and category names are keyed by their folded
    source name and stay. Topic names go (topic ids belong to one map). `item_urls`: {str(id): url}."""
    root = Path(vault)
    old = man.get('names') or {}
    items = {}
    for key, name in (old.get('item') or {}).items():
        url = item_urls.get(str(key))
        if not url:
            continue
        try:
            head = (root / FOLDER / 'Items' / f'{name}.md').read_text(encoding='utf-8', errors='replace')[:4000]
        except OSError:
            continue
        if head.startswith('---\n') and f'url: {_yaml_value(url)}' in head[4:].split('\n---', 1)[0].splitlines():
            items[key] = name
    man['names'] = {k: v for k, v in old.items() if k in ('tag', 'category')}
    man['names']['item'] = items


def takeover_split(vault, man: dict, files: dict) -> tuple:
    """(edited, matched, leftovers) among the listed paths: changed by the user (stay listed: adopted),
    unchanged and produced again by `files` (stay listed: refreshed), unchanged and not produced (pages about
    items or topics this library does not have). Paths already gone are in none."""
    root = Path(vault)
    edited, matched, leftovers = [], [], []
    for rel, entry in man['files'].items():
        cur = file_hash(root / rel)
        if cur is None:
            continue
        if cur != entry['hash']:
            edited.append(rel)
        elif rel in files:
            matched.append(rel)
        else:
            leftovers.append(rel)
    return sorted(edited), sorted(matched), sorted(leftovers)


def takeover_message(edited: int, matched: int, leftovers: int) -> str:
    text = (f'{TAKEOVER} Taking it over refreshes the {matched} page(s) that match your library and keeps the '
            f'{edited} page(s) you edited as you left them. Files you made yourself are never touched.')
    if leftovers:
        text += (f' {leftovers} page(s) are about items or topics this library does not have: keep them as they '
                 'are, or remove them.')
    return text


def take_over(vault, man: dict, library_id: str, files: dict, remove: bool = False) -> tuple:
    """Take over this vault. The caller settled pending, ran keep_names and rendered `files` with the kept
    names. Matched and edited pages stay listed (refreshed, adopted). Leftovers move to `released`: unlisted,
    never touched, removed only by Remove leftovers; with remove=True they stay listed and the next render
    removes them. Only the manifest is written; the vault_id stays. Returns takeover_split's lists."""
    split = takeover_split(vault, man, files)
    released = man.setdefault('released', {})
    if not remove:
        for rel in split[2]:
            released[rel] = man['files'].pop(rel)
    man['library_id'] = str(library_id)
    write_manifest(vault, man)
    return split


def rejoin_released(vault, man: dict, files: dict) -> None:
    """A leftover the render produces again (its item came back), still unchanged: Brainamon's again."""
    root = Path(vault)
    released = man.get('released') or {}
    for rel in [r for r in released if r in files]:
        if file_hash(root / rel) == released[rel]['hash']:
            man['files'][rel] = released.pop(rel)


def remove_leftovers(vault, man: dict) -> int:
    """Remove unchanged released pages after confirmation, with recoverable deletion records."""
    root = Path(vault)
    settle_pending(root, man)
    removals = [(rel, entry['hash']) for rel, entry in (man.get('released') or {}).items()
                if file_hash(root / rel) == entry['hash']]
    if removals:
        man['pending'] = [{'path': rel, 'old': old, 'new': None, 'record_removed': True, 'released': True}
                          for rel, old in removals]
        write_manifest(root, man)
    n = 0
    for rel, old in removals:
        try:
            (root / rel).unlink()
            n += 1
        except FileNotFoundError:
            pass
        record_removed(man, rel, old)
    man['released'] = {}
    man.pop('pending', None)
    write_manifest(root, man)
    return n


# ── moving off the legacy vault (decision 10) ────────────────────────────────
def move(old_vault, new_vault, should_stop=lambda: False) -> int:
    """Copy everything from the old vault except Content Manager/ (the user's files, .obsidian/ and .trash/
    included; nothing chosen file by file), then verify every copy by hash. Returns the files copied.
    Raises VaultError on a mismatch or a stop; the partial copy stays for inspection and nothing else
    changes. The old vault is never deleted."""
    src, dst = Path(old_vault), Path(new_vault)
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in sorted(src.rglob('*')):
        if should_stop():
            raise VaultError('Move cancelled. The partial copy was left in place; nothing changed.')
        rel = p.relative_to(src)
        if rel.parts[0] == 'Content Manager':
            continue
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        copied.append((p, target))
    for p, target in copied:
        if file_hash(p) != file_hash(target):
            raise VaultError(f'The copy of {p.relative_to(src)} does not match the original. The move stopped and '
                             f'nothing changed; check {dst}.')
    return len(copied)
