"""Update this folder (S9): bring this library up to the newer backup another PC made with the same key.

A temporary PC restored this library's backup, became the backup PC and uploaded changes. This PC still holds the
library and its key, so only the files whose version differs are downloaded (Drive is only read) into a staging folder
beside the library, and the newer database is built there from a copy of this one. The swap happens at the next start,
before anything opens the database (`swap`, run from the recovery activation journal). Changes made on this PC after
its last backup are not merged: the old database and every file the swap replaces or removes go to a dated folder in the
library (`before-update-<date>`), so nothing is deleted.

Like library/restore.py this module never receives the app's Database object: the caller copies the database on the
Writer (`copy_database`), and the staged copy gets its own short-lived Writer.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path, PurePosixPath

from core import private_storage
from library import mirror, restore
from library.recovery import RecoveryError
from server.store import Writer

STAGE_PREFIX = '.brainamon-update-'
BEFORE_PREFIX = 'before-update-'
PLAN = 'plan.json'
DB_NAME = 'content_manager.db'
ITEM = re.compile(r'items/([0-9a-f]{32})\.json')


class Cancelled(RecoveryError):
    """Stop updating: the staging folder is removed, this library and Drive are unchanged."""

    def __init__(self):
        super().__init__('Update stopped. This folder and Google Drive are unchanged.')


def _primary(logical: str) -> bool:
    """A change someone made: items, notes, chats, canvases and their images, videos. Not the indexes built from them."""
    if logical.startswith(('items/', 'notes/', 'chats/', 'canvas-uploads/', 'videos/')):
        return True
    return logical.startswith('canvases/') and logical != 'canvases/index.json'


def _same(local: str, published: str) -> bool:
    # a restored library's state holds the manifest's 16-character version until its first own upload
    return bool(published) and (local == published or (len(published) == 16 and local.startswith(published)))


def local_changes(local: dict, published: dict) -> int:
    """Changes made on this PC after its last backup: what it would send now against what it last sent (the audit's
    definition). One edited item counts once, not once per index file; a category edit alone counts one."""
    names = (set(local) | set(published)) - {mirror.MANIFEST}
    changed = {n for n in names if not _same(local[n][0] if n in local else '', published.get(n, {}).get('sig', ''))}
    return sum(_primary(n) for n in changed) or int('library/meta.json' in changed)


def difference(man: dict, remote: dict, local: dict, published: dict) -> dict:
    """What Update this folder downloads. `man`: the newer manifest; `remote`: Drive id -> listing entry; `local`:
    {logical: (sig, size)} of this library now; `published`: this PC's sync_state. `get` is every file whose newer version
    differs from what this folder holds (the other PC's changes, and this PC's own later changes, which the newer library
    does not have); `remote_changed` says whether the other PC changed anything at all."""
    files = man['files']
    get = sorted(n for n, e in files.items() if not (n in local and local[n][0][:16] == e.get('v')))
    other = {n for n, e in files.items() if published.get(n, {}).get('sig', '')[:16] != e.get('v')}
    other |= {n for n in published if n not in files and n != mirror.MANIFEST}
    return {'get': get, 'bytes': sum(remote[files[n]['id']]['size'] for n in get), 'files': len(get),
            'local_changes': local_changes(local, published), 'remote_changed': bool(other)}


def staged(stage: Path, logical: str, entry: dict) -> Path:
    """Where the opened newer version of one file waits: named by its name and version, so a resumed or repeated round keeps
    what it already has and fetches a file again only when the other PC changed it again."""
    return Path(stage) / 'files' / hashlib.sha256(f"{logical}\0{entry.get('v', '')}".encode()).hexdigest()


def download(client, key, snap: dict, names: list, stage: Path, check, progress) -> None:
    """Fetch `names` of the snapshot's manifest, authenticated and opened, into staging. `progress(done, of, bytes, total)`."""
    files, remote = snap['manifest']['files'], snap['remote']
    (Path(stage) / 'files').mkdir(parents=True, exist_ok=True)
    cache = Path(stage) / '.downloads'
    cache.mkdir(exist_ok=True)
    todo = {n: files[n] for n in names if not staged(stage, n, files[n]).is_file()}
    total = sum(remote[files[n]['id']]['size'] for n in names)
    done_bytes = total - sum(remote[e['id']]['size'] for e in todo.values())
    done = len(names) - len(todo)
    progress(done, len(names), done_bytes, total)
    with closing(restore._blobs(client, todo, remote, cache, check)) as blobs:
        for logical, entry, _cached, blob in blobs:
            check()
            try:
                plain = key.open_file(logical, blob, entry) if logical.startswith('videos/') else key.open(logical, blob)
            except mirror.MirrorKeyError:
                raise RecoveryError('A file of the newer backup cannot be authenticated. Nothing was changed; try again.') from None
            target = staged(stage, logical, entry)
            part = target.with_name(target.name + '.part')
            part.write_bytes(plain)
            part.replace(target)
            done, done_bytes = done + 1, done_bytes + remote[entry['id']]['size']
            progress(done, len(names), done_bytes, total)


def copy_database(conn, path: Path) -> None:
    """On the Writer: a consistent copy of this library's database (the WAL included) for the staged build."""
    path = Path(path)
    for p in (path, path.with_name(path.name + '-wal'), path.with_name(path.name + '-shm')):
        p.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as dst:
        conn.backup(dst)


def _rel(data: Path, path: Path) -> str:
    return PurePosixPath(Path(path).relative_to(data)).as_posix()


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _video_name(it: dict) -> str:
    name = it['files'].get('video_name') or ''
    if isinstance(name, str) and name and '/' not in name and Path(name).suffix.lower() in mirror.VIDEO_EXTS:
        restore.safe_rel(name)
        return name
    return ''


def build(stage: Path, data_dir: Path, snap: dict, diff: dict, local: dict) -> dict:
    """Make the staged database (already a copy of this one) the newer library's and write the plan the swap follows.
    Reads this library's folder; writes only in staging."""
    stage, data = Path(stage), Path(data_dir)
    man = snap['manifest']
    files, got = man['files'], set(diff['get'])

    def plain(logical):
        return staged(stage, logical, files[logical]).read_bytes()

    newer = {m.group(1) for n in files if (m := ITEM.fullmatch(n))}
    items = {}
    for n in got:
        if m := ITEM.fullmatch(n):
            items[m.group(1)] = restore._item(restore.json_value(plain(n)), n)
    meta = restore.json_value(plain('library/meta.json')) if 'library/meta.json' in got else None
    if meta is not None and (not isinstance(meta, dict) or not isinstance(meta.get('categories'), list)):
        raise RecoveryError('Invalid library metadata.')
    receipt = restore.json_value(plain('canvas-results.json')) if 'canvas-results.json' in got else None
    settings = restore.json_value(plain('library/recovery-state.json')) if 'library/recovery-state.json' in got else None
    if (not isinstance(man.get('applied', {}), dict) or not isinstance(man.get('receipts', {}), dict)
            or not isinstance(receipt, (dict, type(None))) or not isinstance(settings, (dict, type(None)))):
        raise RecoveryError('Invalid phone acknowledgement state.')

    fields = ('id', 'uid', 'url', 'description', 'short_desc', 'creator', 'type', 'category', 'ai_desc', 'tags', 'notes', 'transcript', 'created', 'modified')

    def apply(db):
        rows = {r[1]: r[0] for r in db.conn.execute('SELECT id, uid FROM items')}
        away = {i for uid, i in rows.items() if uid not in newer}       # this PC's items the newer library does not have
        with db.conn:
            for i in away:
                db.conn.execute('DELETE FROM items WHERE id = ?', (i,))
            for uid, it in items.items():
                # another row holding this id or url is this PC's own later item: it lives on only in the dated copy
                for (other,) in db.conn.execute('SELECT id FROM items WHERE (id = ? OR url = ?) AND uid != ?', (it['id'], it['url'], uid)).fetchall():
                    db.conn.execute('DELETE FROM items WHERE id = ?', (other,))
                    away.add(other)
                if rows.get(uid) not in (None, it['id']):
                    db.conn.execute('DELETE FROM items WHERE uid = ?', (uid,))
                    away.add(rows[uid])
                values = [it.get(k) if it.get(k) is not None else (0 if k in ('created', 'modified') else '') for k in fields]
                extra = [bool(it.get('processed', it.get('ai_desc') or it.get('analysis_done'))), bool(it.get('analysis_done')),
                         bool(it.get('favourite')), 'thumb.jpg' if it['files'].get('thumb') else '']
                if db.conn.execute('SELECT 1 FROM items WHERE uid = ?', (uid,)).fetchone():
                    sets = ','.join(f'{k} = ?' for k in fields[1:]) + ', processed = ?, analysis_done = ?, favourite = ?, thumb_path = ?'
                    db.conn.execute(f'UPDATE items SET {sets} WHERE uid = ?', [*values[1:], *extra, uid])
                else:
                    db.conn.execute(f"INSERT INTO items({','.join(fields)},processed,analysis_done,favourite,thumb_path) VALUES({','.join('?' for _ in range(len(fields) + 4))})",
                                    [*values, *extra])
            if meta is not None:
                db.conn.execute('DELETE FROM categories')
                for order, cat in enumerate(meta['categories']):
                    if not isinstance(cat, dict) or not isinstance(cat.get('name'), str) or not isinstance(cat.get('color'), str):
                        raise RecoveryError('Invalid restored category.')
                    db.conn.execute('INSERT INTO categories(name,color,sort_order,hidden) VALUES(?,?,?,?)',
                                    (cat['name'], cat['color'], order, bool(cat.get('hidden'))))
        for k, value in (settings or {}).items():
            if k in ('cloud_uid_alias', 'my_note_categories', 'cloud_synth_queue') and isinstance(value, str):
                db.set_setting(k, value)
        db.set_setting('cloud_applied', json.dumps(man.get('applied', {}), sort_keys=True))
        db.set_setting('cloud_receipts', json.dumps(man.get('receipts', {}), sort_keys=True))
        if receipt is not None:
            db.set_setting('cloud_canvas_results', json.dumps(receipt, sort_keys=True))
        return sorted(away), {r[1]: r[0] for r in db.conn.execute('SELECT id, uid FROM items')}

    writer = Writer(stage / DB_NAME)
    writer.start()
    try:
        away, ids = writer.call(apply)
        writer.call(lambda db: db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)'))
    finally:
        writer.stop()

    # The plan: every path is relative to the library. Removals first (an item folder this PC alone had can share its id
    # with a newer item), then the newer files.
    out, removals, places = stage / 'out', [], []

    def place(rel, source: Path):
        target = data.joinpath(*PurePosixPath(rel).parts)
        if not _same_bytes(target, source):         # an identical file stays as it is (its time, so its version, too)
            places.append({'path': rel, 'from': _rel(stage, source)})

    def write(rel, raw: bytes):
        path = out.joinpath(*PurePosixPath(rel).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        place(rel, path)

    def remove(rel):
        if data.joinpath(*PurePosixPath(rel).parts).exists():
            removals.append({'path': rel})

    for i in away:
        remove(f'items/{i}')
    folders = {'notes/': 'notes/', 'chats/': 'ask_chats/', 'canvas-uploads/': 'canvases/uploads/'}
    for n in sorted(set(local) - set(files)):
        # a note, chat or canvas the newer library does not have (made here later, or removed there): kept only in the dated copy
        prefix = next((p for p in folders if n.startswith(p)), None)
        if prefix and '/' not in n[len(prefix):]:
            remove(folders[prefix] + n[len(prefix):])
        elif n.startswith('canvases/') and n != 'canvases/index.json' and '/' not in n[len('canvases/'):]:
            remove(n)
    restamp_packs, restamp_uploads = {}, []
    for n in sorted(got):
        prefix = next((p for p in folders if n.startswith(p)), None)
        if prefix:
            filename = n[len(prefix):]
            restore.safe_rel(filename)
            if '/' in filename:
                raise RecoveryError('Invalid note, chat or canvas image path.')
            place(folders[prefix] + filename, staged(stage, n, files[n]))
            if prefix == 'canvas-uploads/':
                restamp_uploads.append(n)
        elif n.startswith('canvases/') and n != 'canvases/index.json':
            filename = n.split('/', 1)[1]
            restore.safe_rel(filename)
            value = restore.json_value(plain(n))
            if '/' in filename or not filename.endswith('.json') or not isinstance(value, dict) or value.get('id') != filename[:-5]:
                raise RecoveryError('Invalid canvas file.')
            place(n, staged(stage, n, files[n]))
        elif re.fullmatch(r'thumbs/pack-[0-9]+\.bin', n):
            pack = restore._pack(plain(n))
            restamp_packs[n] = sorted(pack)
            for item_id, jpg in pack.items():
                if item_id not in ids.values():
                    raise RecoveryError('Media references a missing item.')
                write(f'items/{item_id}/thumb.jpg', jpg)
        elif m := re.fullmatch(r'videos/([0-9a-f]{32})\.bin', n):
            uid = m.group(1)
            if uid not in ids:
                raise RecoveryError('Media references a missing item.')
            name = _video_name(items[uid]) if uid in items else ''
            if not name:
                current = mirror.video_of(data, ids[uid])
                name = current.name if current else 'recovered.mp4'
            places.append({'path': f'items/{ids[uid]}/video/{name}', 'from': _rel(stage, staged(stage, n, files[n]))})
    for uid, it in items.items():
        i, folder = it['id'], f"items/{it['id']}"
        for field, filename in (('report', 'report.md'), ('transcript', 'transcript.txt')):
            if it.get(field):
                write(f'{folder}/{filename}', it[field].encode('utf-8'))
            elif i not in away:
                remove(f'{folder}/{filename}')
        if not it['files'].get('thumb') and i not in away:
            remove(f'{folder}/thumb.jpg')
        # the same video under the name the newer library gives it (a restored PC names its videos itself)
        name = _video_name(it) if it['files'].get('video') else ''
        current = mirror.video_of(data, i) if i not in away else None
        if name and current and current.name != name and f'videos/{uid}.bin' not in got and current.parent == data / 'items' / str(i) / 'video':
            places.append({'path': f'{folder}/video/{name}', 'local': _rel(data, current)})

    state = {}
    for n, e in files.items():
        # what this folder already held is versioned as it is here; a downloaded file as its publisher versioned it
        sig = local[n][0] if n not in got else (e.get('s') or e.get('v', ''))
        state[n] = {'sig': sig, 'drive_id': e['id'], 'size': snap['remote'][e['id']]['size']}
    state[mirror.MANIFEST] = {'sig': snap['manifest_sig'], 'drive_id': snap['manifest_id'],
                              'size': snap['remote'][snap['manifest_id']]['size']}
    plan = {'moves': removals + places, 'state': state, 'restamp_packs': restamp_packs, 'restamp_uploads': restamp_uploads,
            'published': snap['published'], 'local_changes': diff['local_changes']}
    (stage / PLAN).write_text(json.dumps(plan), encoding='utf-8')
    return plan


def before_folder(data_dir: Path, now: float | None = None) -> Path:
    """`before-update-<YYYY-MM-DD>` in the library, numbered when one from the same day exists."""
    base = BEFORE_PREFIX + time.strftime('%Y-%m-%d', time.localtime(now))
    path, n = Path(data_dir) / base, 2
    while path.exists():
        path, n = Path(data_dir) / f'{base}-{n}', n + 1
    return path


def _checkpoint(path: Path) -> None:
    if path.is_file():
        with closing(sqlite3.connect(path)) as conn:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))


def _away(data: Path, before: Path, path: Path) -> None:
    dst = before / path.relative_to(data)
    n = 2
    while dst.exists():
        dst, n = dst.with_name(f'{path.name}.{n}'), n + 1
    _move(path, dst)


def swap(j: dict, save) -> Path:
    """At the start, before anything opens the database: switch this folder to the staged newer library. Every step is
    recorded in the journal (`save(j)`), so a crash in the middle resumes where it stopped. The old database is copied and
    opened before anything moves; what the swap replaces or removes goes to the dated folder."""
    data, stage, before = Path(j['target']), Path(j['stage']), Path(j['before'])
    if j['step'] == 'done':
        shutil.rmtree(stage, ignore_errors=True)
        return data
    plan = json.loads((stage / PLAN).read_text(encoding='utf-8'))
    live = data / DB_NAME
    if j['step'] == 'prepared':
        before.mkdir(parents=True, exist_ok=True)
        _checkpoint(live)
        copy = before / DB_NAME
        part = before / (DB_NAME + '.part')
        part.unlink(missing_ok=True)
        with closing(sqlite3.connect(live)) as src, closing(sqlite3.connect(part)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(part)) as check:
            if check.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RecoveryError('The copy of this library database could not be checked. Nothing was changed.')
            check.execute('SELECT count(*) FROM items').fetchone()
        part.replace(copy)
        j['step'] = 'copied'
        save(j)
    if j['step'] == 'copied':
        # Removals are a step of their own: a resume that ran them again after some placements would take the placed files
        # away (an item folder this PC alone had can share its id with a newer item).
        for m in plan['moves']:
            if m.get('from') or m.get('local'):
                continue
            target = data.joinpath(*PurePosixPath(m['path']).parts)
            if target.exists():
                _away(data, before, target)
        j['step'] = 'removed'
        save(j)
    if j['step'] == 'removed':
        for m in plan['moves']:
            if not (m.get('from') or m.get('local')):
                continue
            source = stage / m['from'] if m.get('from') else data / m['local']
            if not source.exists():
                continue            # placed before an interruption
            target = data.joinpath(*PurePosixPath(m['path']).parts)
            if target.exists():
                _away(data, before, target)
            _move(source, target)
        j['step'] = 'moved'
        save(j)
    if j['step'] == 'moved':
        newer = stage / DB_NAME
        if newer.is_file():
            _checkpoint(newer)
            _checkpoint(live)
            for p in (live.with_name(DB_NAME + '-wal'), live.with_name(DB_NAME + '-shm')):
                p.unlink(missing_ok=True)       # checkpointed and closed: they hold nothing of the old database
            os.replace(newer, live)
        j['step'] = 'replaced'
        save(j)
    if j['step'] == 'replaced':
        state = plan['state']
        for name, ids in plan['restamp_packs'].items():
            state[name]['sig'] = mirror._stamp([data / 'items' / str(i) / 'thumb.jpg' for i in ids])
        for name in plan['restamp_uploads']:
            state[name]['sig'] = mirror._stamp([data / 'canvases' / 'uploads' / name.split('/', 1)[1]])
        done = {'at': int(time.time() * 1000), 'published': plan['published'], 'kept': plan['local_changes'],
                'folder': str(before)}

        def finish(db):
            # what this PC holds now is exactly the newer backup: the next upload sends nothing it already has
            db.clear_sync_state()
            db.save_sync_state(state)
            db.set_setting('cloud_last_publish', str(plan['published']))
            db.set_setting('cloud_update_done', json.dumps(done))
            db.reindex_notes()
        writer = Writer(live)
        writer.start()
        try:
            writer.call(finish)
        finally:
            writer.stop()
        j['step'] = 'done'
        save(j)
    shutil.rmtree(stage, ignore_errors=True)
    return data


def secure(stage: Path) -> None:
    Path(stage).mkdir(exist_ok=True)
    private_storage._secure(Path(stage))
