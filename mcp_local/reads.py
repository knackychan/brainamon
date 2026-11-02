"""Read tools for the local MCP server (projects/mcp-local/PLAN.md).

Plain functions over a db.ReadOnlyDatabase. Nothing here writes, deletes or prints (stdout is the
MCP protocol channel). Every function returns a dict (the SDK turns a returned list into one
content block per element, so lists are wrapped).
"""
import re

from knowledge import knowledge
from knowledge import my_notes
from library import canvas_elements
from library import canvas_plan
from library import search as lsearch

FILE_NAMES = ('report.md', 'transcript.txt')    # the only item files read_item_file serves
FILE_CAP = 40000                                # chars returned per file or note
LIMIT_MAX = 100
NOTES_MAX = 500
MISSING = {                                     # list_items(missing=...): fixed SQL, never caller text
    'description': "COALESCE(ai_desc, '') = ''",
    'thumbnail': "COALESCE(thumb_path, '') = ''",
    'category': "category = 'INTERESTING'",
}


def _clip(text, limit):
    text = re.sub(r'[ \t]+', ' ', text or '').strip()
    return text if len(text) <= limit else text[:limit] + '...'


def _limit(value, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, LIMIT_MAX))


def _brief(item):
    return {
        'id': item['id'],
        'title': _clip(item.get('short_desc') or item.get('ai_desc') or item.get('description'), 80),
        'creator': item.get('creator') or '',
        'category': item.get('category') or '',
        'url': item.get('url') or '',
        'has_description': bool(item.get('ai_desc')),
        'has_thumbnail': bool(item.get('thumb_path')),
    }


def stats(db):
    cur = db.conn.cursor()
    missing = {key: cur.execute(f'SELECT COUNT(*) FROM items WHERE {sql}').fetchone()[0]
               for key, sql in MISSING.items()}
    return {'items': db.count_items(), 'by_category': db.count_by_category(), 'missing': missing}


def search(db, query, limit=10, embed=None):
    """Ranked items. `embed(query)` returns a vector or None; without it the search is full-text only."""
    limit = _limit(limit, 10)
    pool = max(limit * 3, 30)
    fts = db.fts_ids(query, limit=pool)
    vec = []
    qvec = embed(query) if embed else None
    if qvec is not None:
        from core import ai_client
        rows = db.get_all_embeddings(ai_client.EMBEDDING_MODEL)
        if rows:
            vec = lsearch.EmbeddingIndex(rows).topk(qvec, k=pool)
    ids = lsearch.hybrid_rank(fts, vec, limit=limit)
    items = db.get_items_by_ids(ids)
    return {
        'query': query,
        'semantic': bool(vec),
        'count': len(items),
        'items': [{**_brief(it),
                   'snippet': _clip(it.get('ai_desc') or it.get('transcript') or it.get('description'), 200)}
                  for it in items],
    }


def list_items(db, category=None, missing=None, offset=0, limit=50):
    where, args = [], []
    if category:
        where.append('category = ?')
        args.append(category)
    if missing:
        if missing not in MISSING:
            raise ValueError(f"missing must be one of: {', '.join(MISSING)}")
        where.append(MISSING[missing])
    clause = (' WHERE ' + ' AND '.join(where)) if where else ''
    cur = db.conn.cursor()
    total = cur.execute(f'SELECT COUNT(*) FROM items{clause}', args).fetchone()[0]
    offset = max(0, int(offset or 0))
    limit = _limit(limit, 50)
    ids = [r[0] for r in cur.execute(f'SELECT id FROM items{clause} ORDER BY id LIMIT ? OFFSET ?',
                                     (*args, limit, offset)).fetchall()]
    return {'total': total, 'offset': offset, 'count': len(ids),
            'items': [_brief(it) for it in db.get_items_by_ids(ids)]}


def show_item(db, item_id):
    items = db.get_items_by_ids([int(item_id)])
    if not items:
        raise ValueError(f'No item with id {item_id}')
    it = items[0]
    folder = db.items_dir / str(it['id'])
    files = sorted(p.name for p in folder.iterdir())[:50] if folder.is_dir() else []
    return {
        'frame_count': len(canvas_elements.frame_paths(folder)),   # list_frames gives the names

        **_brief(it),
        'tags': it.get('tags') or '',
        'description': _clip(it.get('description'), 2000),
        'ai_desc': _clip(it.get('ai_desc'), 4000),
        'transcript': _clip(it.get('transcript'), 2000),
        'transcript_chars': len(it.get('transcript') or ''),
        'folder': str(folder),
        'files': files,
    }


def read_item_file(db, item_id, name):
    if name not in FILE_NAMES:
        raise ValueError(f"name must be one of: {', '.join(FILE_NAMES)}")
    path = db.items_dir / str(int(item_id)) / name
    if not path.is_file():
        raise ValueError(f'Item {item_id} has no {name}')
    text = path.read_text(encoding='utf-8', errors='replace')
    return {'id': int(item_id), 'name': name, 'chars': len(text),
            'truncated': len(text) > FILE_CAP, 'text': text[:FILE_CAP]}


def list_notes(db):
    folder = db.notes_dir
    names = sorted(p.name for p in folder.glob('*.md')) if folder.is_dir() else []
    return {'count': len(names), 'notes': names[:NOTES_MAX]}


def search_notes(db, query, limit=10):
    hits = db.search_notes(query, limit=_limit(limit, 10))
    return {'query': query, 'count': len(hits),
            'notes': [{'filename': h['filename'], 'topic': h['topic'], 'snippet': h['snippet']} for h in hits]}


def read_note(db, filename):
    path = knowledge.safe_note_path(db.notes_dir, filename)
    if path is None:
        raise ValueError(f'No note named {filename}')
    text = path.read_text(encoding='utf-8', errors='replace')
    return {'filename': filename, 'chars': len(text),
            'truncated': len(text) > FILE_CAP, 'text': text[:FILE_CAP]}


def list_personal_notes(db):
    """The user's own notes (My Notes, kind: personal), newest-updated first."""
    out = []
    for p, meta, body in my_notes.personal_notes(db.notes_dir):
        out.append({'file': p.name, 'title': meta.get('topic') or p.stem,
                    'category': meta.get('category') or my_notes.DEFAULT_CATEGORY,
                    'updated': meta.get('updated', ''), 'chars': len(body)})
    return {'count': len(out), 'notes': out[:NOTES_MAX]}


def note_categories(db):
    """The My Notes categories: the stored list plus any used in existing personal notes."""
    return {'categories': my_notes.all_categories(db, db.notes_dir)}


# ── canvases (projects/wiskit-canvas/PLAN.md): the JSON files, read only ───────
def list_canvases(db):
    rows = canvas_plan.canvas_rows(db.data_dir / 'canvases')
    return {'count': len(rows), 'canvases': rows}


def read_canvas(db, canvas_id):
    try:
        return canvas_plan.canvas_view(db.data_dir / 'canvases', str(canvas_id or '').strip())
    except canvas_plan.ProposalError as exc:
        raise ValueError(str(exc)) from None


def list_frames(db, item_id):
    iid = int(item_id)
    if not db.get_items_by_ids([iid]):
        raise ValueError(f'No item with id {item_id}')
    return canvas_plan.frames_view(db.items_dir / str(iid), iid)


# ── the knowledge map (library/map_engine.py): the cache file, read only ─────
def list_topics(db):
    from core import ai_client
    from library import map_engine
    cache = map_engine.load(map_engine.cache_path(db.data_dir))
    fps = map_engine.fingerprints(ai_client.EMBEDDING_MODEL, db.search_items(include_thumbs=True))
    map_engine.recompute_stale(cache, fps)
    rows = map_engine.topic_rows(cache)
    return {'count': len(rows),
            'topics': [{'id': r['id'], 'title': r['title'], 'items': r['count'], 'status': r['status'],
                        'summary': _clip((r['synthesis'] or '').strip().splitlines()[0] if r['synthesis'] else '', 200)}
                       for r in rows]}


def read_topic(db, topic_id):
    from core import ai_client
    from library import map_engine
    tid = str(topic_id or '').strip()
    if tid.startswith('topic:'):
        tid = tid[len('topic:'):]
    cache = map_engine.load(map_engine.cache_path(db.data_dir))
    t = cache['clusters'].get(tid)
    if t is None:
        raise ValueError(f'No topic with id {topic_id}')
    items = db.get_items_by_ids(t['member_ids'])
    t['stale'] = map_engine.is_stale(t, map_engine.fingerprints(ai_client.EMBEDDING_MODEL, items))
    return {'id': tid, 'title': t['title'], 'status': map_engine.status(t), 'summary': t['synthesis'],
            'name': t['name'], 'items': [_brief(it) for it in items]}
