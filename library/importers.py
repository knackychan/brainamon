"""CSV / JSON import and item CSV export, Qt-free (shared by the Qt main window, the scraper
watcher and the V6 server). Every function here writes through the `db` it is given, so callers
run it where SQLite writes are allowed (the Qt main thread, the V6 Writer thread).
"""
import base64
import csv
import io
import json
from pathlib import Path
from core.urls import http_url

EXPORT_FIELDS = [
    'id', 'url', 'description', 'short_desc', 'notes', 'creator',
    'type', 'category', 'tags', 'ai_desc',
    'thumb_source', 'source', 'created',
]


def _save_thumb(db, item_id: int, b64: str) -> None:
    """A base64 thumbnail embedded in a scrape CSV becomes data/items/<id>/thumb.jpg."""
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert('RGB')
    img.thumbnail((400, 400))
    dest = db.item_dir(item_id) / 'thumb.jpg'
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), 'JPEG', quality=82)
    db.update_item(item_id, {'thumb_path': 'thumb.jpg'})


def import_csv(db, path, counts=None) -> tuple:
    """Import a scrape CSV (or an item CSV export). Rows without a URL or whose URL is already in the
    library are skipped (items.url is UNIQUE). Returns (added, skipped, new_ids)."""
    added, skipped, ids = 0, 0, []
    # Base64 thumbnails can pass csv's 128 KB default field limit.
    csv.field_size_limit(2**31 - 1)
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): v or '' for k, v in row.items() if k}
            url = row.get('url', '').strip()
            if not http_url(url) or db.item_exists(url):
                if counts is not None:
                    key = 'duplicates' if http_url(url) else 'invalid'
                    counts[key] = counts.get(key, 0) + 1
                skipped += 1
                continue
            item_id = db.add_item({
                'url': url,
                'description': row.get('description', '') or row.get('desc', ''),
                'short_desc': row.get('short_desc', ''),
                'creator': row.get('creator', ''),
                'type': row.get('type', 'Reel'),
                'category': row.get('category', 'INTERESTING'),
                'prefix': '',
                'tags': row.get('tags', ''),
                'ai_desc': row.get('ai_description', '') or row.get('ai_desc', ''),
                'thumb_source': row.get('thumb_source', ''),
                'source': row.get('source', '') or 'csv_import',
                'created': int(row['created']) if row.get('created', '').isdigit() else None,
            })
            if item_id and row.get('notes'):
                db.update_item(item_id, {'notes': row['notes']})
            b64 = row.get('thumb', '') or row.get('thumb_b64', '')
            if b64 and len(b64) > 100 and item_id:
                try:
                    _save_thumb(db, item_id, b64)
                except Exception:
                    pass
            if item_id:
                ids.append(item_id)
            added += 1
    return added, skipped, ids


def import_file(db, path, counts=None) -> tuple:
    """Import a .json export (db.import_from_json) or a .csv. Returns (added, skipped, new_ids)."""
    path = Path(path)
    if path.suffix.lower() == '.json':
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if (isinstance(value, dict) and any(k in value for k in ('saved_saved_media', 'saved_posts', 'saved_collections'))) or \
                (isinstance(value, list) and any(isinstance(r, dict) and ('label_values' in r or 'string_map_data' in r) for r in value)):
            raise ValueError("This looks like a Meta export. Import Instagram Saved ZIP/JSON on the phone through More > Import, or use File > Scrapers on this PC. Desktop JSON import accepts a Brainamon export.")
        if isinstance(value, dict) and not any(k in value for k in ('items', 'cats')):
            raise ValueError('Desktop JSON import accepts a Brainamon export. For Instagram Saved ZIP/JSON, use More > Import on the phone or File > Scrapers on PC.')
        before = db.conn.execute('SELECT COALESCE(MAX(id), 0) FROM items').fetchone()[0]
        added, skipped = db.import_from_json(path, counts=counts)
        ids = [r[0] for r in db.conn.execute('SELECT id FROM items WHERE id > ?', (before,)).fetchall()]
        return added, skipped, ids
    if path.suffix.lower() == '.csv':
        return import_csv(db, path, counts=counts)
    raise ValueError('Pick a .csv or a .json file.')


def write_csv(rows, path) -> int:
    """Write item metadata as CSV (EXPORT_FIELDS), re-importable with import_csv."""
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def export_csv(db, path) -> int:
    """Every item as one CSV row. Returns the number of rows."""
    return write_csv(db.search_items(include_thumbs=False), path)
