"""Restore an authenticated mirror to an isolated library; never mutate Drive."""
import hashlib
import json
import re
import shutil
import struct
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath

from core import private_storage
from library import mirror
from library.recovery import RecoveryError
from server.store import Writer

# The limits recovery enforces (mirror.MAX_*, mirror.limit_of) are defined with the sealing code in library/mirror.py: the
# backup leaves out what they refuse, so the two cannot disagree.
OMISSIONS = ['Only the latest uploaded mirror is available; deleted or unuploaded content is not included.',
             'Thumbnails use the uploaded reduced resolution. Videos depend on the original upload settings.',
             'API keys, Google/site logins, license, machine settings, original processing files and Obsidian vault files are excluded.',
             'Search text indexes are rebuilt. Semantic search embeddings can be rebuilt after recovery.']


def omissions(man):
    """OMISSIONS, led by the files the uploading PC left out because they were over the limits (the manifest's `skipped`,
    {logical name: plain size}; an entry that is not a size is ignored)."""
    skipped = man.get('skipped') if isinstance(man, dict) else None
    count = sum(1 for size in skipped.values() if type(size) is int and size >= 0) if isinstance(skipped, dict) else 0
    return ([mirror.skipped_note(count)] if count else []) + list(OMISSIONS)


class NoMirror(RecoveryError):
    """Drive holds no library backup under this key (a wrong account, a key from before phones were removed, an
    unfinished first upload). Callers that can try another key (the passphrase restore, I5) skip only this one."""


def json_value(raw):
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise RecoveryError('An uploaded library file contains invalid JSON.') from None


def safe_rel(name, devices=True):
    """`devices=False` for logical Drive labels (e.g. search/aux.bin) that never become disk paths."""
    if not isinstance(name, str) or len(name) > 240 or '\\' in name or name.startswith('/'):
        raise RecoveryError('Unsafe path in uploaded library.')
    parts = name.split('/')
    for part in parts:
        if not part or part in ('.', '..') or part[-1:] in ('.', ' ') or any(ord(c) < 32 or c in '<>:"|?*' for c in part):
            raise RecoveryError('Unsafe path in uploaded library.')
        if devices and part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
            raise RecoveryError('Unsafe Windows filename in uploaded library.')
    return PurePosixPath(name)


def download(client, entry, limit):
    size = entry.get('size')
    if type(size) is not int or not 0 <= size <= limit:
        raise RecoveryError('A Drive object exceeds the recovery size limit.')
    if hasattr(client, 'download_bounded'):
        raw = client.download_bounded(entry['id'], size)
    else:  # In-memory Drive implementations used by the development server/tests.
        raw = client.download(entry['id'])
    if len(raw) != size or len(raw) > limit:
        raise RecoveryError('A Drive object changed or is incomplete. Refresh the recovery preview.')
    return raw


def manifest_names(key, man):
    """The Drive names of a manifest's files plus the manifest's own: this key's mirror and nothing else."""
    files = man.get('files') if isinstance(man, dict) and isinstance(man.get('files'), dict) else {}
    return {key.name(mirror.MANIFEST)} | {key.name(logical) for logical in files if isinstance(logical, str)}


def manifests(client, key, *, listing=None):
    """Every manifest Drive holds under this key, newest publication first: [(entry, raw, plain, man)].
    Several arise from a sign-in that forgot the upload state (F1); the uploader removes the extra copies on its
    next publish (export_targets). Order: the sealed `published` stamp, then Drive's modifiedTime, then the listing.
    Reads only."""
    listing = client.list() if listing is None else listing
    out = []
    for entry in listing:
        if entry['name'] != key.name(mirror.MANIFEST):
            continue
        raw = download(client, entry, mirror.MAX_MANIFEST)
        try:
            plain = key.open(mirror.MANIFEST, raw)
        except mirror.MirrorKeyError:
            raise RecoveryError('The uploaded manifest cannot be authenticated.') from None
        man = json_value(plain)
        published = man.get('published') if isinstance(man, dict) and type(man.get('published')) is int else 0
        out.append((published, entry.get('modifiedTime') or '', entry, raw, plain, man))
    out.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return [c[2:] for c in out]


def preview(client, key, *, listing=None):
    """The newest manifest under this key that validates against the listing, read-only. `duplicates` counts the
    other copies (I3)."""
    listing = client.list() if listing is None else listing
    found = manifests(client, key, listing=listing)
    if not found:
        raise NoMirror('No library mirror matches this key. Check the account/code, or finish uploading on the original PC.')
    first = None
    for entry, raw, plain, man in found:
        try:
            snap = _check_manifest(client, key, listing, entry, raw, plain, man)
        except RecoveryError as e:
            first = first or e
            continue
        snap['duplicates'] = len(found) - 1
        return snap
    raise first


def _check_manifest(client, key, listing, entry, raw, plain, man):
    if not isinstance(man, dict) or type(man.get('format')) is not int or man['format'] != mirror.FORMAT or type(man.get('reader')) is not int or man['reader'] != mirror.READER:
        raise RecoveryError('Update Brainamon to restore this library format.')
    files = man.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= mirror.MAX_FILES or type(man.get('items')) is not int or not 0 <= man['items'] <= mirror.MAX_FILES:
        raise RecoveryError('Invalid library manifest counts.')
    remote = {f['id']: f for f in listing}
    manifest_time = entry.get('modifiedTime')
    seen_names, seen_ids, total = set(), set(), 0
    for logical, item in files.items():
        safe_rel(logical, devices=False)
        if logical.casefold() in seen_names or not isinstance(item, dict):
            raise RecoveryError('Duplicate or invalid manifest entry.')
        seen_names.add(logical.casefold())
        fid = item.get('id')
        if not isinstance(fid, str) or fid in seen_ids or fid not in remote or item.get('n') != key.name(logical) or remote[fid]['name'] != item['n']:
            raise RecoveryError('A referenced library file is missing or has an inconsistent identity.')
        seen_ids.add(fid)
        if manifest_time:
            try:
                published = datetime.fromisoformat(manifest_time)
                modified = datetime.fromisoformat(remote[fid]['modifiedTime'])
                if not published.tzinfo or not modified.tzinfo:
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise RecoveryError('Drive did not return valid publication timestamps. Retry the preview.') from None
            if modified > published:
                raise RecoveryError('The library has an unfinished upload. Finish uploading on the original PC before restoring; Drive was left unchanged.')
        limit = mirror.limit_of(logical)
        size = remote[fid].get('size')
        if type(size) is not int or not 0 <= size <= limit:
            raise RecoveryError(f'An uploaded file is too large for recovery v1 ({mirror.mib(mirror.MAX_VIDEO)} per video, {mirror.mib(mirror.MAX_FILE)} per other file).')
        if type(item.get('size')) is not int or not 0 <= item['size'] <= limit:
            raise RecoveryError('Invalid file size in uploaded manifest.')
        total += size
    if total > mirror.MAX_TOTAL or 'library/meta.json' not in files:
        raise RecoveryError('Uploaded library exceeds recovery limits or has no metadata.')
    revisions = {fid: [remote[fid].get('version'), remote[fid]['size']] for fid in [entry['id'], *seen_ids]}
    # manifest_sig is the publisher's sync_state signature (export_targets._Blob.sig): the reconnect proof.
    return {'manifest': man, 'manifest_id': entry['id'], 'hash': hashlib.sha256(raw).hexdigest(),
            'manifest_sig': hashlib.sha256(plain).hexdigest(),
            'revision': hashlib.sha256(json.dumps(revisions, sort_keys=True).encode()).hexdigest(),
            'remote': remote, 'bytes': total, 'items': man['items'], 'files': len(files),
            'published': man.get('published', 0), 'videos': man.get('videos', 'off'),
            'canvases': bool(man.get('canvases')), 'omissions': omissions(man), 'duplicates': 0}


def unchanged(client, key, snap):
    current = preview(client, key)
    if current['hash'] != snap['hash'] or current['manifest_id'] != snap['manifest_id']:
        raise RecoveryError('The Drive library changed since preview. Refresh the preview before continuing.')
    for fid in [snap['manifest_id'], *(f['id'] for f in snap['manifest']['files'].values())]:
        before, after = snap['remote'][fid], current['remote'][fid]
        if before.get('version') != after.get('version') or before['size'] != after['size']:
            raise RecoveryError('A referenced Drive file changed since preview. Refresh before continuing.')
    return current


def destination(path, forbidden):
    if not isinstance(path, str) or not path or len(path) > 1000:
        raise RecoveryError('Choose an absolute path for a new recovery folder.')
    target = Path(path)
    if not target.is_absolute():
        raise RecoveryError('The recovery folder must use an absolute path.')
    safe_rel(target.name)
    for ancestor in (target, *target.parents):
        if ancestor.is_symlink() or getattr(ancestor, 'is_junction', lambda: False)():
            raise RecoveryError('Recovery folders cannot contain links or junctions.')
    resolved = target.resolve()
    for blocked in forbidden:
        blocked = Path(blocked).resolve()
        if resolved == blocked or resolved.is_relative_to(blocked) or blocked.is_relative_to(resolved):
            raise RecoveryError('Choose a new folder outside the active library and app settings.')
    if target.exists() or not target.parent.is_dir():
        raise RecoveryError('Choose a folder name that does not exist inside an existing parent folder.')
    return resolved


def _pack(raw):
    if len(raw) < 8 or raw[:4] != b'BTP1':
        raise RecoveryError('Invalid thumbnail pack.')
    n = struct.unpack('>I', raw[4:8])[0]
    if n > len(raw) - 8:
        raise RecoveryError('Incomplete thumbnail pack.')
    index = json_value(raw[8:8 + n])
    if not isinstance(index, dict) or len(index) > mirror.PACK:
        raise RecoveryError('Invalid thumbnail index.')
    out = {}
    for k, value in index.items():
        if not re.fullmatch(r'[1-9][0-9]{0,14}', k) or not isinstance(value, list) or len(value) != 2:
            raise RecoveryError('Invalid thumbnail identity.')
        offset, length = value
        if type(offset) is not int or type(length) is not int or min(offset, length) < 0 or 8 + n + offset + length > len(raw):
            raise RecoveryError('Invalid thumbnail range.')
        out[int(k)] = raw[8 + n + offset:8 + n + offset + length]
    return out


def _item(value, logical):
    if not isinstance(value, dict) or type(value.get('id')) is not int or not 0 < value['id'] < 2 ** 53:
        raise RecoveryError('Invalid restored item identity.')
    uid = value.get('uid')
    if not isinstance(uid, str) or not re.fullmatch(r'[0-9a-f]{32}', uid) or logical != f'items/{uid}.json':
        raise RecoveryError('Invalid restored item UID.')
    for k in ('url', 'description', 'short_desc', 'creator', 'type', 'category', 'ai_desc', 'tags', 'notes', 'report', 'transcript'):
        if value.get(k) is not None and not isinstance(value[k], str):
            raise RecoveryError('Invalid text in a restored item.')
    if not value.get('url'):
        raise RecoveryError('A restored item has no URL.')
    if not isinstance(value.get('files'), dict):
        raise RecoveryError('Invalid restored item media metadata.')
    for k in ('created', 'modified'):
        if value.get(k) is not None and (type(value[k]) is not int or not 0 <= value[k] < 2 ** 53):
            raise RecoveryError('Invalid restored item timestamp.')
    return value


def _blobs(client, files, remote, cache, check):
    # Four small objects in flight; a large object travels alone (no four-video memory spike).
    def fetch(logical, entry):
        check()
        limit = mirror.limit_of(logical)
        cached = cache / hashlib.sha256(logical.encode()).hexdigest()
        if cached.exists() and cached.stat().st_size > min(limit, remote[entry['id']]['size']):
            raise RecoveryError('Recovery staging file exceeds its size limit.')
        blob = cached.read_bytes() if cached.is_file() else download(client, remote[entry['id']], limit)
        return logical, entry, cached, blob

    with ThreadPoolExecutor(4, thread_name_prefix='cm-recovery-down') as pool:
        batch = []
        for logical, entry in files.items():
            check()
            small = remote[entry['id']]['size'] <= 1024 * 1024
            if batch and (not small or len(batch) == 4):
                for future in batch:
                    check()
                    yield future.result()
                batch = []
            if small:
                batch.append(pool.submit(fetch, logical, entry))
            else:
                yield fetch(logical, entry)
        for future in batch:
            check()
            yield future.result()


def materialize(client, key, snap, stage, cancel, progress):
    """A failed restore leaves only its own stage; an existing library is never opened."""
    stage = Path(stage)
    stage.mkdir(exist_ok=True)
    private_storage._secure(stage)
    cache = stage / '.recovery-downloads'
    cache.mkdir(exist_ok=True)
    current = unchanged(client, key, snap)
    if shutil.disk_usage(stage).free < snap['bytes'] * 3 + 16 * 1024 ** 2:
        raise RecoveryError('Not enough free disk space for recovery staging and the restored library.')
    man, items, meta, receipt, restored_settings = snap['manifest'], [], None, {}, {}
    # shortcut: item metadata stays in memory; stream it through staging SQLite when metadata size becomes material.
    written, thumbnails, canvases, videos = set(), set(), [], {}

    def check():
        if cancel.is_set():
            raise RecoveryError('Recovery cancelled. The current library and Drive are unchanged; you can resume.')

    def write(rel, data):
        safe_rel(rel)
        identity = rel.casefold()
        if identity in written:
            raise RecoveryError('Conflicting output paths in uploaded library.')
        written.add(identity)
        path = stage.joinpath(*PurePosixPath(rel).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    with closing(_blobs(client, man['files'], current['remote'], cache, check)) as blobs:
        for done, (logical, entry, cached, blob) in enumerate(blobs, 1):
            check()
            raw = key.open_file(logical, blob, entry) if logical.startswith('videos/') else key.open(logical, blob)
            if not cached.exists():
                cached.write_bytes(blob)
            if logical == 'library/meta.json':
                meta = json_value(raw)
            elif logical == 'library/recovery-state.json':
                restored_settings = json_value(raw)
            elif re.fullmatch(r'items/[0-9a-f]{32}\.json', logical):
                items.append(_item(json_value(raw), logical))
            elif re.fullmatch(r'thumbs/pack-[0-9]+\.bin', logical):
                pack = _pack(raw)
                if thumbnails & pack.keys():
                    raise RecoveryError('Duplicate item thumbnails.')
                for item_id, jpg in pack.items():
                    write(f'items/{item_id}/thumb.jpg', jpg)
                thumbnails.update(pack)
            elif logical.startswith(('notes/', 'chats/')):
                prefix, filename = logical.split('/', 1)
                if '/' in filename or not filename.endswith('.md' if prefix == 'notes' else '.json'):
                    raise RecoveryError('Invalid note or chat path.')
                if prefix == 'chats' and not isinstance(json_value(raw), dict):
                    raise RecoveryError('Invalid chat file.')
                raw.decode('utf-8')
                write(('ask_chats/' if prefix == 'chats' else 'notes/') + filename, raw)
            elif logical.startswith('canvases/'):
                filename = logical.split('/', 1)[1]
                if '/' in filename or not filename.endswith('.json'):
                    raise RecoveryError('Invalid canvas path.')
                if filename != 'index.json':
                    value = json_value(raw)
                    if not isinstance(value, dict) or value.get('id') != filename[:-5] or not isinstance(value.get('items'), list):
                        raise RecoveryError('Invalid canvas file.')
                    canvases.append(value)
                    write(logical, raw)
            elif logical.startswith('canvas-uploads/'):
                filename = logical.split('/', 1)[1]
                if '/' in filename:
                    raise RecoveryError('Invalid canvas image path.')
                write('canvases/uploads/' + filename, raw)
            elif re.fullmatch(r'videos/[0-9a-f]{32}\.bin', logical):
                uid = logical[7:-4]
                temporary = stage / '.recovery-videos' / (uid + '.bin')
                temporary.parent.mkdir(exist_ok=True)
                temporary.write_bytes(raw)
                videos[uid] = temporary
            elif logical == 'canvas-results.json':
                receipt = json_value(raw)
            elif logical.startswith(('library/part-', 'search/')) or logical == 'vectors.bin':
                pass  # Derived phone indexes are authenticated above and rebuilt from restored source text.
            else:
                raise RecoveryError('This mirror includes unsupported content. Update Brainamon before restoring it.')
            progress(done, len(man['files']))
    check()
    if not isinstance(meta, dict) or meta.get('format') != 1 or not isinstance(meta.get('categories'), list):
        raise RecoveryError('Invalid library metadata.')
    if len(items) != man['items'] or len({it['id'] for it in items}) != len(items) or len({it['uid'] for it in items}) != len(items) or len({it['url'] for it in items}) != len(items):
        raise RecoveryError('Item counts or identities do not match the mirror.')
    if (not isinstance(man.get('applied', {}), dict) or not isinstance(man.get('receipts', {}), dict)
            or not isinstance(receipt, dict) or not isinstance(restored_settings, dict)):
        raise RecoveryError('Invalid phone acknowledgement state.')
    ids, uids = {it['id'] for it in items}, {it['uid'] for it in items}
    if thumbnails - ids or videos.keys() - uids:
        raise RecoveryError('Media references a missing item.')
    for canvas in canvases:
        for el in canvas['items']:
            if not isinstance(el, dict):
                raise RecoveryError('Invalid canvas element.')
            if el.get('source') == 'file' and el.get('file_path'):
                path = safe_rel(el['file_path'])
                if len(path.parts) != 1 or not (stage / 'canvases' / 'uploads' / path).is_file():
                    raise RecoveryError('A canvas image is missing from the mirror.')
            if el.get('source') == 'db' and el.get('item_id') not in ids:
                raise RecoveryError('A canvas references a missing item.')
    for it in items:
        check()
        prefix = f"items/{it['id']}/"
        for field, filename in (('report', 'report.md'), ('transcript', 'transcript.txt')):
            if it.get(field):
                write(prefix + filename, it[field].encode('utf-8'))
        if it['uid'] in videos:
            original = it['files'].get('video_name') or ''
            if not isinstance(original, str):
                raise RecoveryError('Invalid uploaded video name.')
            extension = Path(original).suffix.lower() or '.mp4'
            if extension not in mirror.VIDEO_EXTS:
                raise RecoveryError('Unsupported uploaded video type.')
            video = stage / prefix / 'video' / ('recovered' + extension)
            video.parent.mkdir(parents=True, exist_ok=True)
            videos.pop(it['uid']).replace(video)
    writer = Writer(stage / 'content_manager.db')
    writer.start()
    try:
        def populate(db):
            if db.count_items():
                raise RecoveryError('Staging already contains a restored database. Start a fresh preview.')
            with db.conn:
                db.conn.execute('DELETE FROM categories')
                for order, cat in enumerate(meta['categories']):
                    if not isinstance(cat, dict) or not isinstance(cat.get('name'), str) or not isinstance(cat.get('color'), str):
                        raise RecoveryError('Invalid restored category.')
                    db.conn.execute('INSERT INTO categories(name,color,sort_order,hidden) VALUES(?,?,?,?)',
                                    (cat['name'], cat['color'], order, bool(cat.get('hidden'))))
                fields = ('id', 'uid', 'url', 'description', 'short_desc', 'creator', 'type', 'category', 'ai_desc', 'tags', 'notes', 'transcript', 'created', 'modified')
                for it in items:
                    row = [it.get(k) if it.get(k) is not None else (0 if k in ('created', 'modified') else '') for k in fields]
                    db.conn.execute(f"INSERT INTO items({','.join(fields)},processed,analysis_done,favourite,thumb_path) VALUES({','.join('?' for _ in range(len(fields) + 4))})",
                                    [*row, bool(it.get('processed', it.get('ai_desc') or it.get('analysis_done'))), bool(it.get('analysis_done')), bool(it.get('favourite')), 'thumb.jpg' if it['id'] in thumbnails else ''])
            allowed = {'cloud_uid_alias', 'my_note_categories', 'cloud_synth_queue'}
            for k, value in restored_settings.items():
                if k in allowed and isinstance(value, str):
                    db.set_setting(k, value)
            for k, value in (('cloud_applied', man.get('applied', {})), ('cloud_canvas_results', receipt),
                             ('cloud_receipts', man.get('receipts', {}))):
                db.set_setting(k, json.dumps(value))
            db.set_setting('cloud_epoch', key.fingerprint)
            state = {logical: {'sig': entry.get('v', ''), 'drive_id': entry['id'],
                               'size': snap['remote'][entry['id']]['size']}
                     for logical, entry in man['files'].items()}
            state[mirror.MANIFEST] = {'sig': '', 'drive_id': snap['manifest_id'],
                                      'size': snap['remote'][snap['manifest_id']]['size']}
            db.save_sync_state(state)
            db.set_setting('cloud_upload', '')
            db.set_setting('cloud_vault', 'off')
            db.set_setting('onboard_answer', 'recover')
            db.reindex_notes()
        writer.call(populate)
        # Pending changes are applied only in staging. Their remote files remain untouched.
        from server import delivery
        pending = []
        for f in client.list():
            check()
            if mirror.is_change(f['name']):
                try:
                    doc = key.open_change(f['name'], download(client, f, mirror.MAX_FILE))
                except mirror.MirrorKeyError:
                    continue  # Preserve another key's journal; it is never deleted remotely.
                if delivery.kind(doc) in ('v1', 'v2'):
                    pending.append((None, doc))   # a newer or invalid file waits in Drive for the restored PC
        def apply_pending(db):
            # the live PC's rules (server/delivery.py), each file with its receipt; a held file stays in Drive
            out = delivery.intake_round(db, pending, check).out
            db.reindex_notes()
            return out.skipped
        skipped = writer.call(apply_pending)
        if skipped:
            raise RecoveryError('Some pending phone changes could not be restored. Drive was left unchanged; update or recover them on the original device first.')
    finally:
        writer.stop()
    check()
    unchanged(client, key, snap)
    return {'items': len(items), 'files': len(man['files']), 'omissions': omissions(man)}
