from core import private_storage
"""mirror.py: what the Google Drive mirror holds, and how it is sealed.

The desktop writes, the phone reads (projects/mobile-app/PLAN.md, "The mirror"). This module turns
the export payload (export.build_export_payload(mirror=True)) plus the files under data/ into the
mirror's logical files, and seals each one with the mirror key. export_targets.DriveMirrorTarget
diffs them against what was published and uploads. File I/O only, no SQLite: it runs on the sync
thread (server/sync.py), which loads the payload on the Writer.

Logical files (the names Drive sees are keyed hashes of these, so Drive learns nothing):

    manifest.json                 every other file: Drive name, version, size (the phone diffs it)
    library/meta.json             categories, item count, the embedding model
    library/part-NNN.json         card rows of the items with id // 500 == NNN
    items/<uid>.json              one full item: texts, report, transcript, which files exist
    thumbs/pack-NNNN.bin          the 320 px thumbnails of the items with id // 100 == NNNN
    notes/<file>.md               data/notes/*.md as they are (Knowledge notes and My Notes)
    chats/<slug>.json             data/ask_chats/*.json as they are
    canvases/<id>.json            data/canvases/*.json (setting: canvases on)
    canvas-uploads/<name>         data/canvases/uploads/* (setting: canvases on)
    videos/<uid>.bin              the item's downloaded video (setting: off / favourites / all)
    vectors.bin                   item embeddings as int8, with the id and uid lists
    search/text-NNN.json.gz       the texts the phone searches and quotes to Wiskit (Phase 5), by
                                  id // 500 like the parts, gzip-compressed JSON (see search_text)
    search/deep.json.gz           what Wiskit Deep reads besides the items (plans/07-wiskit-deep.md):
                                  the topic clusters of data/obsidian_graph.json and the websites
                                  and tools index (the resources table, in table order)
    search/aux.bin                the stored topic and note-section vectors (aux_embeddings) as int8,
                                  with each row's key and text hash (the phone uses a row only while
                                  its hash matches the text it has)

The manifest's entry for each file is {n: Drive name, v: version, size, id: Drive file id}, so the
phone downloads by id without listing the folder. `applied` ({device: ms}) says up to when each
phone's change files were applied (the phone drops its own pending edits once they are in).

Change files go the other way (projects/mobile-app/plans/04-phone-mirror.md): the phone uploads
`chg-<32 random hex>` (CHANGE_PREFIX), sealed as a file whose logical name is that Drive name,
holding {format, device, at, changes: [...]}. The desktop (server/intake.py) applies and deletes
them; the publish never deletes them as strays.

Packs and parts are keyed on the item id, not on the newest-first order, so a new item changes
only the last part and pack instead of shifting all of them.

Sealing (the phone does the same with WebCrypto in Phase 4):
- The mirror key is 32 random bytes, kept on the PC (the cloud folder) and given to the phone in
  the pairing QR; recovery.py can upload independently encrypted master-key envelopes.
- Two subkeys by HKDF-SHA256 (no salt): info b'brainamon-mirror-1 data' and b'brainamon-mirror-1 name'.
- Drive name of a logical file: HMAC-SHA256(name key, logical name), first 16 bytes as hex.
- A file: b'BAM1' + 12-byte nonce + AES-256-GCM(data key, nonce, plaintext, aad=logical name).
- A video: b'BAV1' + chunk size (4 bytes, big endian) + for each 4 MiB chunk i:
  12-byte nonce + AES-256-GCM(..., aad=f'{logical}#{i}'), so a download can be checked chunk by
  chunk; the manifest's size says where it ends.
"""
import base64
import re
import hashlib
import hmac
import json
import secrets
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from library.export import card_title, downscale_jpeg, report_section
from library.canvas import canvas_entries

FORMAT = 1
# The oldest phone reader that can open this copy (web/src/mobile/source/mirror.ts READER). Raise it only
# with a change an older phone app would misread: such a phone keeps its last copy and asks for an update.
READER = 1
# Change envelope fields format/device/at stay stable across versions; missing format means 1.
# Raise only for shapes an older PC would misread; keep accepting older formats.
CHANGE_FORMAT = 1
# The manifest's `delivery`: this PC applies numbered change files once each and publishes `receipts`
# (server/delivery.py); a phone sends again what they do not cover. Absent: an older PC, the `applied` floor only.
DELIVERY = 2
PART = 500
PACK = 100
SNIPPET = 200
VIDEO_CHUNK = 4 * 1024 * 1024
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}
VIDEO_MODES = ('off', 'fav', 'all')
KEYINFO = 1000          # characters of a report's "Key information" in the search text (Wiskit uses 600)
MANIFEST = 'manifest.json'
CHANGE_PREFIX = 'chg-'
# What recovery accepts: library/restore.py measures every uploaded object against these, and a backup that holds a
# larger one cannot be recovered at all. build_files leaves such a file out (too_big) and the manifest records it.
MAX_MANIFEST = 16 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024         # any object but a video
MAX_VIDEO = 512 * 1024 * 1024
MAX_TOTAL = 100 * 1024 ** 3         # every object together
MAX_FILES = 100000

_MAGIC, _VMAGIC = b'BAM1', b'BAV1'


class MirrorKeyError(Exception):
    """The mirror key is missing, malformed, or does not open a file."""


class MirrorKey:
    def __init__(self, master: bytes):
        if len(master) != 32:
            raise MirrorKeyError('A mirror key is 32 bytes.')
        self.master = master
        self._data = _hkdf(master, b'brainamon-mirror-1 data')
        self._name = _hkdf(master, b'brainamon-mirror-1 name')

    @classmethod
    def generate(cls) -> 'MirrorKey':
        return cls(secrets.token_bytes(32))

    @classmethod
    def load(cls, path: Path, *, readonly=False) -> 'MirrorKey | None':
        try:
            raw = private_storage.read(path, readonly=readonly).decode('ascii').strip()
        except FileNotFoundError:
            return None
        try:
            return cls(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
        except (ValueError, MirrorKeyError):
            raise MirrorKeyError(f'The mirror key in {path} is damaged.')

    def save(self, path: Path) -> None:
        private_storage.write(path, self.text().encode('ascii'))

    def text(self) -> str:
        """The key as the pairing QR will carry it (base64url, no padding)."""
        return base64.urlsafe_b64encode(self.master).rstrip(b'=').decode()

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(b'brainamon-mirror-1 id' + self.master).hexdigest()[:12]

    def name(self, logical: str) -> str:
        return hmac.new(self._name, logical.encode('utf-8'), hashlib.sha256).hexdigest()[:32]

    def content_id(self, data: bytes) -> str:
        """Names a vault file's content without revealing it (vault sync): the same bytes give the same
        id on every device that holds this key. web/src/mobile/mirror/crypto.ts contentId matches."""
        return hmac.new(self._name, b'vault-content ' + data, hashlib.sha256).hexdigest()[:32]

    def seal(self, logical: str, plaintext: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return _MAGIC + nonce + _gcm(self._data).encrypt(nonce, plaintext, logical.encode('utf-8'))

    def open(self, logical: str, blob: bytes) -> bytes:
        from cryptography.exceptions import InvalidTag
        if blob[:4] != _MAGIC:
            raise MirrorKeyError('Not a sealed mirror file.')
        try:
            return _gcm(self._data).decrypt(blob[4:16], blob[16:], logical.encode('utf-8'))
        except InvalidTag:
            raise MirrorKeyError(f'{logical} does not open with this key.')

    def seal_change(self, changes: dict) -> tuple[str, bytes]:
        """A phone change file: (Drive name, sealed bytes); the Drive name is its logical name.
        (The phone does this in web/src/mobile/mirror/crypto.ts; tests use this side.)"""
        name = CHANGE_PREFIX + secrets.token_hex(16)
        return name, self.seal(name, _json(changes))

    def open_change(self, name: str, blob: bytes) -> dict:
        try:
            out = json.loads(self.open(name, blob))
        except ValueError:
            raise MirrorKeyError(f'{name} is not a change file.')
        if not isinstance(out, dict):
            raise MirrorKeyError(f'{name} is not a change file.')
        return out

    def seal_file(self, logical: str, src: Path, dst: Path, integrity=None) -> int:
        """Seal a large file chunk by chunk into `dst`; returns the sealed size."""
        digest, length = hashlib.sha256(), 0
        g = _gcm(self._data)
        with open(src, 'rb') as fi, open(dst, 'wb') as fo:
            fo.write(_VMAGIC + struct.pack('>I', VIDEO_CHUNK))
            i = 0
            while True:
                chunk = fi.read(VIDEO_CHUNK)
                if not chunk and i:
                    break
                digest.update(chunk)
                length += len(chunk)
                nonce = secrets.token_bytes(12)
                fo.write(nonce + g.encrypt(nonce, chunk, f'{logical}#{i}'.encode('utf-8')))
                i += 1
                if len(chunk) < VIDEO_CHUNK:
                    break
            if integrity is not None and (length != integrity['bytes'] or digest.hexdigest() != integrity['sha256']):
                raise MirrorKeyError('Video changed while sealing; retry publication.')
            return fo.tell()

    def open_file(self, logical: str, blob: bytes, integrity) -> bytes:
        from cryptography.exceptions import InvalidTag
        if len(blob) < 36 or blob[:4] != _VMAGIC:
            raise MirrorKeyError('Not a sealed mirror video.')
        size = struct.unpack('>I', blob[4:8])[0]
        if size < 1 or size > VIDEO_CHUNK:
            raise MirrorKeyError('Invalid video chunk size.')
        g, out, at, i = _gcm(self._data), [], 8, 0
        while at < len(blob):
            n = min(12 + size + 16, len(blob) - at)
            part = blob[at:at + n]
            try:
                out.append(g.decrypt(part[:12], part[12:], f'{logical}#{i}'.encode('utf-8')))
            except InvalidTag:
                raise MirrorKeyError(f'{logical} chunk {i} does not open with this key.')
            at += n
            i += 1
        data = b''.join(out)
        verify_video(data, integrity)
        return data


def verify_video(data, integrity):
    if not isinstance(integrity, dict) or integrity.get('integrity') != 2 or type(integrity.get('bytes')) is not int or integrity['bytes'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', str(integrity.get('sha256', ''))):
        raise MirrorKeyError('Republish this legacy video from the PC before playback.')
    if len(data) != integrity['bytes'] or hashlib.sha256(data).hexdigest() != integrity['sha256']:
        raise MirrorKeyError('Complete video integrity verification failed.')


# ── what recovery accepts ────────────────────────────────────────────────────
def limit_of(logical: str) -> int:
    """The largest sealed object recovery accepts under this logical name."""
    return MAX_VIDEO if logical.startswith('videos/') else MAX_FILE


def sealed_size(logical: str, plain: int) -> int:
    """The size in Drive of a file of `plain` bytes once sealed (seal, seal_file): what recovery measures."""
    nonce, tag = 12, 16
    if logical.startswith('videos/'):
        return len(_VMAGIC) + 4 + plain + (nonce + tag) * max(1, -(-plain // VIDEO_CHUNK))
    return len(_MAGIC) + nonce + plain + tag


def too_big(logical: str, plain: int) -> bool:
    """True when recovery would refuse this file once sealed: build_files leaves it out."""
    return sealed_size(logical, plain) > limit_of(logical)


def mib(size: int) -> str:
    """A limit in words: '512 MiB' (a limit shrunk by a test prints a fraction)."""
    return f'{size / 1048576:g} MiB'


def skipped_note(count: int) -> str:
    """The one sentence about files left out for their size, for the Backup card and the recovery preview ('' for none)."""
    if count <= 0:
        return ''
    many = count != 1
    return (f"{count:,} file{'s were' if many else ' was'} not uploaded because {'they are' if many else 'it is'} too big to recover "
            f"(over {mib(MAX_VIDEO)} for a video, over {mib(MAX_FILE)} for anything else). "
            f"{'They are' if many else 'It is'} not in the backup.")


def _hkdf(master: bytes, info: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)


def _gcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


# ── The files ────────────────────────────────────────────────────────────────
@dataclass
class MirrorFile:
    """One logical file. `sig` changes exactly when the content does (a hash of the bytes, or of
    the source files' sizes and times for packs and videos), so an unchanged file is never
    rebuilt or uploaded. `data()` builds the plaintext; a video has `path` instead."""
    name: str
    sig: str
    size: int
    data: Callable[[], bytes] | None = None
    path: Path | None = None


@dataclass
class Options:
    videos: str = 'fav'           # off / fav / all
    canvases: bool = True


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')


def _blob(name: str, data: bytes) -> MirrorFile:
    return MirrorFile(name, _sha(data), len(data), data=lambda: data)


def _gz(name: str, data: bytes) -> MirrorFile:
    """A gzip-compressed file (the phone opens it with DecompressionStream). Versioned on the
    plain bytes; mtime 0 keeps the compressed bytes the same for the same text."""
    import gzip
    return MirrorFile(name, _sha(data), len(data), data=lambda: gzip.compress(data, compresslevel=6, mtime=0))


def _stamp(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f'{p.name}:{st.st_size}:{st.st_mtime_ns};'.encode())
    return h.hexdigest()


def row(it: dict, tint: str | None) -> dict:
    """A card row for the phone's light copy: the desktop's Row shape (server/library.compact)
    with the uid, a 200-character snippet and the thumbnail tint."""
    ai_desc = it['ai_desc'] or ''
    marker = ai_desc.strip().upper() == 'NO_CONTENT'
    return {
        'id': it['id'], 'uid': it.get('uid', ''), 'title': card_title(it), 'creator': it['creator'],
        'type': it['type'], 'cat': it['category'], 'tags': ', '.join(it['tags']),
        'desc': ((ai_desc if not marker else '') or it['description'])[:SNIPPET], 'url': it['url'], 'src': it['platform'],
        'thumb': it['has_thumb'], 'ai': bool(not marker and (ai_desc or it['processed'])), 'an': bool(it.get('analysis_done')),
        'fav': bool(it.get('favourite')), 'created': it['created'], 'tv': it.get('modified', 0), 'tint': tint or '',
    }


def search_text(it: dict, report: str) -> dict:
    """One item's entry in search/text-NNN.json.gz: the columns the desktop's items_fts indexes
    (description, ai_desc, transcript, creator, tags: d, a, t, c, g), short_desc (s) and the
    report's Key information (k), so the phone ranks keyword matches like bm25 (Smart search,
    Wiskit) and builds the same Wiskit context as knowledge/ask_core.py."""
    return {'id': it['id'], 's': it.get('short_desc') or '', 'd': it.get('description') or '',
            'a': it.get('ai_desc') or '', 't': it.get('transcript') or '', 'c': it.get('creator') or '',
            'g': ', '.join(it.get('tags') or []),
            'k': report_section(report, 'Key information')[:KEYINFO] if report else ''}


def video_of(data_dir: Path, item_id: int) -> Path | None:
    """The item's downloaded video: the largest in data/items/<id>/video/, else data/reels/<id>/."""
    for d in (data_dir / 'items' / str(item_id) / 'video', data_dir / 'reels' / str(item_id)):
        try:
            vids = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS]
        except OSError:
            continue
        if vids:
            return max(vids, key=lambda f: f.stat().st_size)
    return None


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def build_files(payload: dict, data_dir: Path, opts: Options, tints: dict | None = None,
                skipped: dict | None = None) -> Iterator[MirrorFile]:
    """Every logical file of the mirror except the manifest, built lazily (one at a time).

    A file recovery would refuse for its size (too_big: a video over MAX_VIDEO, any other file over MAX_FILE) is not
    built. `skipped`, when given, takes {logical name: plain size} of each one, once the iterator is used up, and
    `manifest` records them. The publish (export_targets) and Update this folder (sync.local_files) both come through
    here, so they agree on what a backup holds."""
    left_out = skipped if skipped is not None else {}
    for f in _files(payload, Path(data_dir), opts, tints or {}, left_out):
        if not _refused(left_out, f.name, f.size):
            yield f


def _refused(left_out: dict, logical: str, size: int) -> bool:
    """Whether recovery would refuse a file this big; if so it is noted in `left_out`, which becomes the manifest's `skipped`."""
    if not too_big(logical, size):
        return False
    left_out[logical] = size
    return True


def _uploads_video(it: dict, opts: Options) -> bool:
    """Whether the Videos setting puts this item's video in the backup."""
    return opts.videos == 'all' or (opts.videos == 'fav' and bool(it.get('favourite')))


def _files(payload: dict, data_dir: Path, opts: Options, tints: dict, left_out: dict) -> Iterator[MirrorFile]:
    items_dir = data_dir / 'items'
    items = sorted(payload['items'], key=lambda it: it['id'])
    vec = payload.get('vectors') or {}
    uploads: set[int] = set()       # ids of the items whose video goes up (the item loop below fills it)

    yield _blob('library/meta.json', _json({
        'format': FORMAT, 'categories': payload.get('categories', []), 'items': len(items),
        'embedding_model': vec.get('model', ''), 'part': PART, 'pack': PACK,
        'topic_notes': sorted(payload.get('topic_notes', [])), 'ai': payload.get('ai') or {},
        'obsidian_vault': payload.get('obsidian_vault', ''), 'obsidian_notes': payload.get('obsidian_notes', '')}))
    yield _blob('canvas-results.json', _json(payload.get('canvas_results') or {}))
    yield _blob('library/recovery-state.json', _json(payload.get('recovery_settings') or {}))

    # card rows, 500 per part by id
    parts: dict[int, list] = {}
    for it in items:
        parts.setdefault(it['id'] // PART, []).append(row(it, tints.get(str(it['id']))))
    for n, rows in parts.items():
        yield _blob(f'library/part-{n:03d}.json', _json(rows))

    # full items, and the search text of each part
    text: dict[int, list] = {}
    for it in items:
        d = items_dir / str(it['id'])
        report = _read(d / 'report.md') if it.get('has_report') else ''
        text.setdefault(it['id'] // PART, []).append(search_text(it, report))
        transcript = it.get('transcript') or (_read(d / 'transcript.txt') if (d / 'transcript.txt').is_file() else '')
        video = video_of(data_dir, it['id'])
        if video is not None and _uploads_video(it, opts):
            if _refused(left_out, f"videos/{it['uid']}.bin", _size(video)):
                video = None        # the item does not claim a video the backup lacks
            else:
                uploads.add(it['id'])
        full = {k: it.get(k) for k in ('id', 'uid', 'url', 'description', 'short_desc', 'creator', 'type', 'category',
                                         'ai_desc', 'notes', 'created', 'modified', 'analysis_done', 'favourite', 'processed')}
        full.update(tags=', '.join(it['tags']), report=report, transcript=transcript,
                    files={'thumb': it['has_thumb'], 'report': bool(report), 'transcript': bool(transcript),
                           'video': video is not None, 'video_name': video.name if video else ''})
        yield _blob(f"items/{it['uid']}.json", _json(full))
    for n, rows in text.items():
        yield _gz(f'search/text-{n:03d}.json.gz', _json(rows))

    # thumbnail packs, 100 per pack by id
    packs: dict[int, list] = {}
    for it in items:
        if it['has_thumb']:
            packs.setdefault(it['id'] // PACK, []).append(it['id'])
    for n, ids in packs.items():
        paths = [items_dir / str(i) / 'thumb.jpg' for i in ids]
        sig = _stamp(paths)
        yield MirrorFile(f'thumbs/pack-{n:04d}.bin', sig, sum(_size(p) for p in paths) // 3,
                         data=lambda ids=ids, paths=paths: _pack(ids, paths))

    # notes and chats, as they are on disk
    for folder, prefix, glob in ((data_dir / 'notes', 'notes', '*.md'), (data_dir / 'ask_chats', 'chats', '*.json')):
        if folder.is_dir():
            for p in sorted(folder.glob(glob)):
                try:
                    yield _blob(f'{prefix}/{p.name}', p.read_bytes())
                except OSError:
                    continue

    # canvases with their uploaded images
    if opts.canvases:
        cdir = data_dir / 'canvases'
        yield _blob('canvases/index.json', _json(canvas_entries(cdir)))
        if cdir.is_dir():
            for p in sorted(cdir.glob('*.json')):
                if p.name == 'index.json':
                    continue
                try:
                    raw = p.read_bytes()
                except OSError:
                    continue
                yield _blob(f'canvases/{p.name}', raw)
            up = cdir / 'uploads'
            if up.is_dir():
                for p in sorted(f for f in up.iterdir() if f.is_file()):
                    yield MirrorFile(f'canvas-uploads/{p.name}', _stamp([p]), _size(p),
                                     data=lambda p=p: p.read_bytes())

    # downloaded videos: the ones the Videos setting picks (a video over the limit was left out above, before it is read)
    for it in items:
        v = video_of(data_dir, it['id']) if it['id'] in uploads else None
        if v is not None:
            with v.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            yield MirrorFile(f"videos/{it['uid']}.bin", 'video2:' + digest, _size(v), path=v)

    # Wiskit Deep: topics, websites and tools, topic and note-section vectors (fetched by the phone
    # the first time Deep runs, not with the light copy)
    deep = payload.get('deep') or {}
    topics = topic_clusters(data_dir)
    if topics or deep.get('resources'):
        yield _gz('search/deep.json.gz', _json({'topics': topics, 'resources': [list(r) for r in deep.get('resources') or []]}))
    aux = deep.get('aux') or []
    if aux:
        sig = _sha(_json([deep.get('model', ''), [[a['key'], a['hash']] for a in aux]]))
        yield MirrorFile('search/aux.bin', sig, sum(a['dim'] for a in aux) + 64 * len(aux),
                         data=lambda: _aux_vectors(deep.get('model', ''), aux))

    # search vectors
    if vec.get('rows'):
        uid_of = {it['id']: it.get('uid', '') for it in items}
        rows = [r for r in vec['rows'] if r[0] in uid_of]
        sig = _sha(_json([vec['model'], [[r[0], r[1]] for r in rows]]) + b''.join(hashlib.sha256(r[2]).digest() for r in rows))
        yield MirrorFile('vectors.bin', sig, sum(r[1] for r in rows) + 64 * len(rows),
                         data=lambda: _vectors(vec['model'], rows, uid_of))


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _pack(ids: list[int], paths: list[Path]) -> bytes:
    """b'BTP1' + index length (4 bytes, big endian) + index JSON {"<id>": [offset, length]} +
    the JPEGs back to back (offsets count from the first JPEG)."""
    index, blobs, at = {}, [], 0
    for i, p in zip(ids, paths):
        jpg = downscale_jpeg(p)
        if not jpg:
            continue
        index[str(i)] = [at, len(jpg)]
        blobs.append(jpg)
        at += len(jpg)
    head = _json(index)
    return b'BTP1' + struct.pack('>I', len(head)) + head + b''.join(blobs)


def read_pack(data: bytes) -> dict[int, bytes]:
    """The other side of _pack (tests; the phone does the same)."""
    n = struct.unpack('>I', data[4:8])[0]
    index = json.loads(data[8:8 + n])
    base = 8 + n
    return {int(k): data[base + o:base + o + ln] for k, (o, ln) in index.items()}


def _vectors(model: str, rows: list, uid_of: dict) -> bytes:
    """b'BVE1' + header length + header JSON {model, dim, count, ids, uids} + int8 vectors, row
    after row. Each vector is scaled by its largest magnitude to 127: cosine ranking does not
    depend on the scale, so the phone compares the int8 values directly."""
    import numpy as np
    dim = max((r[1] for r in rows), default=0)
    rows = [r for r in rows if r[1] == dim]
    mat = np.zeros((len(rows), dim), dtype=np.int8)
    for k, (_, d, blob) in enumerate(rows):
        mat[k] = _quantize(blob, d)
    head = _json({'model': model, 'dim': dim, 'count': len(rows),
                  'ids': [r[0] for r in rows], 'uids': [uid_of[r[0]] for r in rows]})
    return b'BVE1' + struct.pack('>I', len(head)) + head + mat.tobytes()


def _quantize(blob: bytes, dim: int):
    import numpy as np
    v = np.frombuffer(blob, dtype=np.float32, count=dim)
    m = float(np.abs(v).max()) or 1.0
    return np.clip(np.rint(v / m * 127), -127, 127).astype(np.int8)


def _aux_vectors(model: str, rows: list) -> bytes:
    """search/aux.bin: like vectors.bin (b'BVE1' + header + int8 rows), the header carrying each
    row's key ('topic:<cluster>' or 'note:<file>#<n>') and text hash (search.text_hash) instead of
    item ids. Rows of another size than the first are left out."""
    import numpy as np
    dim = rows[0]['dim'] if rows else 0
    rows = [a for a in rows if a['dim'] == dim]
    mat = np.zeros((len(rows), dim), dtype=np.int8)
    for k, a in enumerate(rows):
        mat[k] = _quantize(a['blob'], dim)
    head = _json({'model': model, 'dim': dim, 'count': len(rows),
                  'keys': [a['key'] for a in rows], 'hashes': [a['hash'] for a in rows]})
    return b'BVE1' + struct.pack('>I', len(head)) + head + mat.tobytes()


def topic_clusters(data_dir: Path) -> list:
    """[[cluster key, title, synthesis, member ids]] from data/obsidian_graph.json, in file order (the
    phone builds the same topic texts as knowledge/librarian._topic_texts from them)."""
    try:
        clusters = json.loads((Path(data_dir) / 'obsidian_graph.json').read_text(encoding='utf-8')).get('clusters') or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for key, c in clusters.items():
        try:
            ids = [int(i) for i in c.get('member_ids') or []]
        except (TypeError, ValueError, AttributeError):
            continue
        out.append([str(key), c.get('title') or '', c.get('synthesis') or '', ids])
    return out


def is_change(name: str) -> bool:
    return name.startswith(CHANGE_PREFIX)


VAULT_PREFIXES = ('vb-', 'vi-', 'vs-')     # vault sync blobs, file lists and the PC's status (library/vault_sync.py)


def is_vault(name: str) -> bool:
    return name.startswith(VAULT_PREFIXES)


# ── the phones' own records (D13) ────────────────────────────────────────────
# A paired phone may keep one small sealed record in the app data folder so the PC can list phones by name and last sync:
# `ph-<key.name('phones/<device>')>`, sealed with the library key, its Drive name as the logical name (like a change file), the
# body {"v": 1, "device", "name", "seen"} (seen: ms). The phone replaces it in place; the PC only reads it. A later phone
# release writes it (web/src/mobile/mirror); until one does the PC finds none and says "Phones read your backup".
PHONE_PREFIX = 'ph-'
PHONE_MAX = 4096        # a record is a few hundred bytes


def phone_name(key: 'MirrorKey', device: str) -> str:
    return PHONE_PREFIX + key.name('phones/' + device)


def is_phone(name: str) -> bool:
    return name.startswith(PHONE_PREFIX)


def seal_phone(key: 'MirrorKey', device: str, name: str, seen: int) -> tuple[str, bytes]:
    """(Drive name, sealed record); the phone's side is web/src/mobile/mirror/crypto.ts once a phone release writes it."""
    drive = phone_name(key, device)
    return drive, key.seal(drive, _json({'v': 1, 'device': device, 'name': name, 'seen': int(seen)}))


def open_phone(key: 'MirrorKey', drive_name: str, blob: bytes) -> dict:
    """{device, name, seen} of a phone record, or MirrorKeyError: another key's, damaged, oversized, or a name that is not
    this device's (a record cannot stand in for another phone)."""
    if len(blob) > PHONE_MAX:
        raise MirrorKeyError('A phone record is small.')
    try:
        body = json.loads(key.open(drive_name, blob))
    except ValueError:
        raise MirrorKeyError(f'{drive_name} is not a phone record.') from None
    device, name, seen = (body.get('device'), body.get('name'), body.get('seen')) if isinstance(body, dict) else (None, None, None)
    if not (isinstance(device, str) and 0 < len(device) <= 40 and isinstance(name, str) and type(seen) is int and seen > 0
            and drive_name == phone_name(key, device)):
        raise MirrorKeyError(f'{drive_name} is not a phone record.')
    return {'device': device, 'name': name.strip()[:60], 'seen': seen}


# ── AI keys for a phone being paired ─────────────────────────────────────────
# The pairing link never carries API keys (a copy of the link in a clipboard or a chat would be a
# copy of the keys). When the user ticks keys, the PC seals them with a one-time key into a file in
# the app data folder, `pky-<expiry, unix s>-<Drive name of PAIR_LOGICAL under the one-time key>`,
# and the link carries only the one-time key (`t`) and the expiry (`tx`). The phone takes the file
# once (web/src/mobile/mirror/pairing.ts takeKeys) and deletes it; the PC deletes it when it
# expires. After that the link opens nothing.
PAIR_PREFIX = 'pky-'
PAIR_LOGICAL = 'pair-keys.json'
PAIR_TTL = 30 * 60          # seconds the phone has to collect the keys


def pair_drop(ai: dict, now: float | None = None) -> tuple[MirrorKey, int, str, bytes]:
    """The sealed keys file: (one-time key, expiry in unix seconds, Drive name, sealed bytes)."""
    one = MirrorKey.generate()
    exp = int(now if now is not None else time.time()) + PAIR_TTL
    return one, exp, pair_drop_name(one, exp), one.seal(PAIR_LOGICAL, _json({'ai': ai}))


def pair_drop_name(one: MirrorKey, exp: int) -> str:
    return f'{PAIR_PREFIX}{int(exp)}-{one.name(PAIR_LOGICAL)}'


def is_pair_drop(name: str) -> bool:
    return name.startswith(PAIR_PREFIX)


def pair_drop_expired(name: str, now: float | None = None) -> bool:
    """A keys file past its expiry (or with a name that does not parse): the PC deletes it."""
    try:
        exp = int(name[len(PAIR_PREFIX):].split('-', 1)[0])
    except ValueError:
        return True
    return (now if now is not None else time.time()) > exp


def manifest(files: dict, payload: dict, opts: Options, skipped: dict | None = None) -> bytes:
    """`files`: {logical: {'n': drive name, 'v': version, 'size': plaintext size, 'id': Drive id}}.
    `applied` (from the payload): {device: last applied change time, ms}. `receipts`: {stream: {device, seq,
    digests, want}} for numbered change files (server/delivery.py). `skipped`: {logical: plain size} of the files
    build_files left out because recovery would refuse them; the key is absent when there are none, so readers that
    never heard of it (and a manifest of a library within the limits) are untouched."""
    vec = payload.get('vectors') or {}
    body = {'format': FORMAT, 'reader': READER, 'generated_at': payload.get('generated_at', ''),
            'published': int(time.time() * 1000),
            'items': len(payload.get('items', [])), 'embedding_model': vec.get('model', ''),
            'videos': opts.videos, 'canvases': opts.canvases, 'canvas_change': 1, 'note_category': 1, 'video_chunk': VIDEO_CHUNK,
            'applied': payload.get('applied') or {}, 'delivery': DELIVERY, 'receipts': payload.get('receipts') or {},
            'files': files}
    if skipped:
        body['skipped'] = dict(skipped)
    return _json(body)


def _fits(logical: str, p: Path) -> int:
    """A file's size, or 0 when recovery would refuse it: build_files leaves it out, so it takes no room in Drive."""
    size = _size(p)
    return 0 if too_big(logical, size) else size


def estimate(data_dir: Path, rows: list[dict]) -> dict:
    """Drive space each choice needs, before it is applied (Settings > Cloud). `rows`: [{'id',
    'favourite'}] for every item. Bytes; thumbnails count at about a third of their file size
    (they go up at 320 px). A file recovery would refuse is not counted: it does not go up (build_files)."""
    data_dir = Path(data_dir)
    base = 0
    fav = allv = nfav = nall = 0
    for r in rows:
        base += 4000 + _size(data_dir / 'items' / str(r['id']) / 'thumb.jpg') // 3 + _size(data_dir / 'items' / str(r['id']) / 'report.md')
        v = video_of(data_dir, r['id'])
        if v is not None and not too_big('videos/', _size(v)):
            s = _size(v)
            allv += s
            nall += 1
            if r.get('favourite'):
                fav += s
                nfav += 1
    for folder, prefix in (('notes', 'notes'), ('ask_chats', 'chats')):
        d = data_dir / folder
        if d.is_dir():
            base += sum(_fits(f'{prefix}/{p.name}', p) for p in d.iterdir() if p.is_file())
    canv = 0
    cdir = data_dir / 'canvases'
    if cdir.is_dir():
        canv = sum(_fits(f'canvases/{p.name}', p) for p in cdir.rglob('*') if p.is_file())
    return {'base': base, 'canvases': canv, 'videos_fav': fav, 'videos_all': allv,
            'videos_fav_count': nfav, 'videos_all_count': nall}

