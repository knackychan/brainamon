"""
export.py — Builds the shared metadata/media payload for export targets.

Phase 5 seam: build_export_payload() is the target-agnostic data core (text
metadata, canvases as geometry + image references, report.md text, thumb
manifest; no HTML, no base64). export_targets.py turns it into an output.
The unsupported single-file HTML exporter was removed (security finding 17).
"""

import json, re, time, io
from pathlib import Path
from urllib.parse import urlparse
from core.db import Database


THUMB_MAX_WIDTH = 320
THUMB_QUALITY = 65


def downscale_jpeg(path: Path, max_width: int = THUMB_MAX_WIDTH,
                   quality: int = THUMB_QUALITY) -> bytes:
    """Return the image at `path` as optimized JPEG bytes, at most `max_width` wide.

    Falls back to the raw file bytes when Pillow is missing or cannot decode the
    file; returns b'' when the file is missing or unreadable."""
    try:
        from PIL import Image
    except ImportError:
        Image = None

    image_path = Path(path)
    try:
        if not image_path.exists():
            return b''

        if Image is None:
            return image_path.read_bytes()

        with Image.open(image_path) as im:
            if im.mode not in ('RGB', 'L'):
                im = im.convert('RGB')
            if max_width and im.width > max_width:
                ratio = max_width / float(im.width)
                new_size = (max_width, max(1, int(im.height * ratio)))
                im = im.resize(new_size, Image.LANCZOS)
            buffer = io.BytesIO()
            im.save(buffer, format='JPEG', quality=quality, optimize=True)
            return buffer.getvalue()
    except Exception:
        try:
            return image_path.read_bytes()
        except Exception:
            return b''


PAYLOAD_VERSION = 1

# report.md sections that duplicate data the payload already carries (Description)
# or deliberately leaves out (Transcript: ~1.6 MB across the library).
_REPORT_DROP_SECTIONS = ('transcript', 'description')

_PLATFORMS = (
    ('facebook.com', 'facebook'), ('fb.watch', 'facebook'),
    ('instagram.com', 'instagram'),
    ('reddit.com', 'reddit'), ('redd.it', 'reddit'),
    ('youtube.com', 'youtube'), ('youtu.be', 'youtube'),
    ('tiktok.com', 'tiktok'),
    ('threads.net', 'threads'), ('threads.com', 'threads'),
)


def _platform_of(url: str) -> str:
    host = (urlparse(url or '').hostname or '').lower()
    for suffix, name in _PLATFORMS:
        if host == suffix or host.endswith('.' + suffix):
            return name
    return 'web' if host else ''


TITLE_CAP = 90


def card_title(r: dict) -> str:
    """Same text the Qt card shows: short_desc, else ai_desc, else description (first line).
    One rule for the desktop's rows (server/library.py) and the Drive mirror's (library/mirror.py)."""
    text = next((value for key in ('short_desc', 'ai_desc', 'description')
                 if (value := (r.get(key) or '').strip()) and value.upper() != 'NO_CONTENT'), '')
    first = text.splitlines()[0] if text else ''
    return first[:TITLE_CAP]


def _norm_ws(s: str) -> str:
    return ' '.join((s or '').split())


def report_section(text: str, header: str) -> str:
    """Return the body text under a '### <header>' markdown section, or '' if absent.
    (knowledge.tasks.report_section; here so the Drive mirror can use it too.)"""
    if not text:
        return ''
    out, capturing = [], False
    for ln in text.splitlines():
        m = re.match(r'^\s{0,3}#{1,6}\s+(.*)', ln)
        if m:
            if capturing:
                break  # next header ends the section
            capturing = m.group(1).strip().lower().startswith(header.lower())
            continue
        if capturing:
            out.append(ln)
    return '\n'.join(out).strip()


def _strip_report(text: str, ai_desc: str = '') -> str:
    """Trim report.md to what the payload does not already carry: drop the
    level-2 sections named in _REPORT_DROP_SECTIONS, and any level-3 section
    whose body is exactly the item's ai_desc (Analyze copies its Summary there;
    the modal shows ai_desc already). Keeps index.html under budget."""
    parts = re.split(r'(?m)^(## .*)$', text)
    out = [parts[0]]
    for i in range(1, len(parts), 2):
        if parts[i][3:].strip().lower() in _REPORT_DROP_SECTIONS:
            continue
        out.append(parts[i])
        out.append(parts[i + 1])
    text = ''.join(out)
    dup = _norm_ws(ai_desc)
    if dup:
        parts = re.split(r'(?m)^(### .*)$', text)
        out = [parts[0]]
        for i in range(1, len(parts), 2):
            if _norm_ws(parts[i + 1]) == dup:
                continue
            out.append(parts[i])
            out.append(parts[i + 1])
        text = ''.join(out)
    return text.strip()


def canvas_thumb_key(file_path: str) -> str:
    """Manifest key for a canvas upload image (item thumbs are keyed by item id)."""
    return 'c-' + Path(file_path).stem


def collect_thumb_sources(db: Database, canvas_store=None) -> dict:
    """Map manifest key -> existing source image Path. Keys are item ids as
    strings plus canvas_thumb_key() for canvas uploads. Never creates
    directories (db.item_dir would)."""
    sources = {}
    for (item_id,) in db.conn.cursor().execute("SELECT id FROM items").fetchall():
        f = db.items_dir / str(item_id) / 'thumb.jpg'
        if f.is_file():
            sources[str(item_id)] = f
    if canvas_store:
        for c in canvas_store.list_canvases():
            full = canvas_store.load_canvas(c['id']) or {}
            for ci in full.get('items', []):
                if ci.get('type') == 'image' and ci.get('source') == 'file' and ci.get('file_path'):
                    f = canvas_store.upload_path(ci['file_path'])
                    if f.is_file():
                        sources[canvas_thumb_key(ci['file_path'])] = f
    return sources


def export_items_csv(db: Database, path) -> int:
    """Write every item as one CSV row (header = importers.EXPORT_FIELDS). Reads only; reuses
    importers.write_csv, so the file stays re-importable with importers.import_csv.
    Returns the number of rows."""
    from library import importers
    return importers.write_csv(db.search_items(include_thumbs=False), path)


def build_export_payload(db: Database, canvas_store=None, thumb_sources=None,
                         mirror: bool = False, vectors_model: str = '') -> dict:
    """Read the library into a JSON-serializable dict. Reads only.

    `thumbs` is the manifest: key -> 'thumbs/<key>.jpg' or None. Pass the dict
    from collect_thumb_sources() to avoid a second scan; that same dict is what
    an ExportTarget copies.

    mirror=True is the Google Drive mirror's read (library/mirror.py, run on the server's
    Writer by server/sync.py): every item also carries uid, favourite, modified, analysis_done,
    its notes and transcript, and `reports` stays empty (the mirror reads report.md itself, off
    the Writer, and has_report only says the file is there). vectors_model adds `vectors`:
    {'model', 'rows': [(item_id, dim, float32 blob)]} for that embedding model."""
    if thumb_sources is None:
        thumb_sources = collect_thumb_sources(db, canvas_store)

    extra = (", uid, favourite, analysis_done, notes, COALESCE(transcript, '') AS transcript"
             if mirror else '')
    rows = db.conn.cursor().execute(
        "SELECT id, url, description, short_desc, creator, type, category, tags, "
        "ai_desc, processed, created, modified, "
        "(transcript IS NOT NULL AND transcript != '') AS has_transcript" + extra +
        " FROM items ORDER BY COALESCE(created, modified, 0) DESC"
    ).fetchall()

    thumbs, reports, items = {}, {}, []
    for r in rows:
        key = str(r['id'])
        has_thumb = key in thumb_sources
        thumbs[key] = f'thumbs/{key}.jpg' if has_thumb else None
        report_file = db.items_dir / key / 'report.md'
        if mirror:
            if report_file.is_file():
                reports[key] = ''
        elif report_file.is_file():
            try:
                text = _strip_report(report_file.read_text(encoding='utf-8', errors='replace'),
                                     r['ai_desc'] or '')
            except OSError:
                text = ''
            if text:
                reports[key] = text
        items.append({
            # No 'title' here: it is short_desc || ai_desc || description, derived
            # by the JS DataSource (inlining it cost ~1.1 MB on the live library).
            'id': r['id'],
            'creator': r['creator'] or '',
            'url': r['url'] or '',
            'platform': _platform_of(r['url']),
            'type': r['type'] or 'Reel',
            'category': r['category'] or 'INTERESTING',
            'tags': [t.strip() for t in (r['tags'] or '').split(',') if t.strip()],
            'description': r['description'] or '',
            'short_desc': r['short_desc'] or '',
            'ai_desc': r['ai_desc'] or '',
            'processed': bool(r['processed']),
            'has_transcript': bool(r['has_transcript']),
            'has_thumb': has_thumb,
            'has_report': key in reports,
            'created': r['created'] or r['modified'] or 0,
        })
        if mirror:
            items[-1].update(uid=r['uid'] or '', favourite=bool(r['favourite']), modified=r['modified'] or 0,
                             analysis_done=bool(r['analysis_done']), notes=r['notes'] or '',
                             transcript=r['transcript'] or '')

    canvases = []
    if canvas_store:
        for c in canvas_store.list_canvases():
            full = canvas_store.load_canvas(c['id'])
            if not full:
                continue
            elements = []
            for ci in full.get('items', []):
                el = {
                    'type': ci.get('type', 'image'),
                    'x': ci.get('x', 0), 'y': ci.get('y', 0),
                    'w': ci.get('w', 200), 'h': ci.get('h', 150),
                }
                if el['type'] == 'note':
                    el['text'] = ci.get('text', '')
                    el['color'] = ci.get('color', '#FFF9C4')
                else:
                    el['label'] = ci.get('label', '')
                    el['item_id'] = None
                    el['thumb'] = None
                    if ci.get('source') == 'db' and ci.get('item_id'):
                        el['item_id'] = int(ci['item_id'])
                        el['thumb'] = str(el['item_id'])
                    elif ci.get('source') == 'file' and ci.get('file_path'):
                        key = canvas_thumb_key(ci['file_path'])
                        if key in thumb_sources:
                            el['thumb'] = key
                            thumbs[key] = f'thumbs/{key}.jpg'
                elements.append(el)
            canvases.append({'id': c['id'], 'name': c.get('name', ''), 'items': elements})

    categories = [{'name': c['name'], 'color': c['color'], 'hidden': bool(c['hidden'])} for c in db.get_categories()]

    payload = {
        'version': PAYLOAD_VERSION,
        'generated_at': time.strftime('%Y-%m-%d %H:%M'),
        'items': items,
        'categories': categories,
        'canvases': canvases,
        'reports': {} if mirror else reports,
        'thumbs': thumbs,
    }
    if vectors_model:
        payload['vectors'] = {'model': vectors_model,
                              'rows': [tuple(v) for v in db.iter_embeddings(vectors_model)]}
    if mirror:
        payload['recovery_settings'] = {k: db.get_setting(k, '') for k in
                                        ('cloud_uid_alias', 'my_note_categories', 'cloud_synth_queue')}
    return payload
