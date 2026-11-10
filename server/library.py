"""Library read helpers: the compact card row the front end keeps in memory.

The front end loads every item once as compact rows (about 2 MB for 3,016 items) and
filters, sorts and windows them locally. Text search goes to the server (db FTS) so it keeps
the app's exact semantics (db.fts_match_query AND + LIKE fallback).
"""
from library.export import _platform_of as platform_of   # Qt-free; one platform table for both exports and V6
from library.export import TITLE_CAP, card_title  # noqa: F401  (one title rule; the mirror uses it too)

# Bit flags for the four "needs" statuses, same meaning as db.search_items(status_filter=...).
NEED_THUMB = 1
NEED_DESCRIBE = 2
NEED_ANALYZE = 4
NEED_CATEGORIZE = 8
NEED_INDEX = 16          # no vector for ai_client.EMBEDDING_MODEL (stale text is the Index job's call)

DESC_CAP = 400


def needs(r: dict, embedded: set | None = None) -> int:
    n = 0
    if not r.get('thumb_path'):
        n |= NEED_THUMB
    if (r.get('ai_desc') or '').strip().upper() in ('', 'NO_CONTENT'):
        n |= NEED_DESCRIBE
    if not r.get('analysis_done') and r.get('type') in ('Reel', 'Video'):
        n |= NEED_ANALYZE
    if r.get('category') == 'INTERESTING' and not (r.get('tags') or '').strip():
        n |= NEED_CATEGORIZE
    if embedded is not None and r['id'] not in embedded:
        n |= NEED_INDEX
    return n


def compact(r: dict, embedded: set | None = None) -> dict:
    """One row of GET /api/items. Keys are short on purpose (3,000+ rows).
    `embedded`: ids that have a vector (sets nd bit 16 for the others); None skips the bit."""
    ai_desc = r.get('ai_desc') or ''
    marker = ai_desc.strip().upper() == 'NO_CONTENT'
    return {
        'id': r['id'],
        'title': card_title(r),
        'creator': r.get('creator') or '',
        'type': r.get('type') or '',
        'cat': r.get('category') or '',
        'tags': r.get('tags') or '',
        'desc': ((ai_desc if not marker else '') or r.get('description') or '')[:DESC_CAP],
        'url': r.get('url') or '',
        'src': platform_of(r.get('url') or ''),
        'thumb': r.get('thumb_path') == 'thumb.jpg',
        'ai': bool(not marker and (ai_desc or r.get('processed'))),
        'an': bool(r.get('analysis_done')),
        'nd': needs(r, embedded),
        'fav': bool(r.get('favourite')),
        'created': r.get('created') or r.get('modified') or 0,
        # thumbnail version: db.update_item stamps `modified` on every write, including every
        # thumbnail write, so /thumb/{id}?v=<tv> changes exactly when the image may have changed
        'tv': r.get('modified') or 0,
    }
