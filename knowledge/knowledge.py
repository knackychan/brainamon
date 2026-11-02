"""
knowledge.py - the Knowledge tab's note and source logic, Qt-free. Moved from
ui/knowledge_panel.py so the Qt tab and the V6 server (server/routes/knowledge.py) share it.

Notes are data/notes/<slug>.md with a `--- key: value ---` frontmatter (topic, created, updated,
sources, kind, category). Every write here is followed by the caller running db.reindex_notes()
(on the Qt main thread or the server Writer).
"""
import re
from datetime import datetime
from pathlib import Path

from library import search as search_core

NOTE_SORTS = ('updated', 'created', 'az')


def slugify(text: str) -> str:
    text = (text or '').strip().lower()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:60] or 'note'


def source_title(s: dict) -> str:
    # Prefer the AI description (what the wiki is actually built from) over the raw caption.
    return (s.get('ai_desc') or s.get('short_desc') or s.get('description')
            or s.get('creator') or '(untitled)').strip().split('\n')[0]


def split_frontmatter(text: str):
    """Return (meta dict, body) for a note file with a `--- ... ---` frontmatter block."""
    m = re.match(r'^---\n(.*?)\n---\n+', text, flags=re.DOTALL)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def parse_source_ids(s: str) -> set:
    out = set()
    for tok in (s or '').split(','):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


def relative_date(dt: datetime) -> str:
    seconds = (datetime.now() - dt).total_seconds()
    if seconds < 0:
        return dt.strftime('%Y-%m-%d')
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{int(seconds // 60)}m ago'
    if seconds < 86400:
        return f'{int(seconds // 3600)}h ago'
    days = int(seconds // 86400)
    if days < 30:
        return f'{days}d ago'
    if days < 365:
        return f'{days // 30}mo ago'
    return f'{days // 365}y ago'


def note_date(meta: dict, path: Path, prefer: str = 'updated') -> datetime:
    keys = ('updated', 'created') if prefer == 'updated' else ('created',)
    for key in keys:
        raw = meta.get(key)
        if raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def note_snippet(body: str, max_chars: int = 140) -> str:
    lines = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        line = re.sub(r'^#+\s*', '', line)
        line = re.sub(r'^[-*]\s+', '', line)
        line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
        line = re.sub(r'[*_`]', '', line)
        lines.append(line)
        if len(lines) >= 3:
            break
    snippet = ' '.join(lines)
    if len(snippet) > max_chars:
        return snippet[:max_chars].rstrip() + chr(8230)
    return snippet


def note_kind(meta: dict, path: Path, topic_note_paths: set) -> str:
    if path.name in topic_note_paths:
        return 'Topic digest'
    if meta.get('kind') == 'personal':
        return 'Personal'
    return 'Synthesized'


def write_front(path: Path, meta: dict, body: str) -> None:
    front = '---\n' + ''.join(f'{k}: {v}\n' for k, v in meta.items()) + '---\n\n'
    path.write_text(front + body, encoding='utf-8')


# ── note rows (the Saved notes list) ─────────────────────────────────────────
def note_row(path: Path, topic_note_paths: set) -> dict:
    meta, body = split_frontmatter(path.read_text(encoding='utf-8'))
    return {
        'path': path,
        'file': path.name,
        'kind': note_kind(meta, path, topic_note_paths),
        'title': meta.get('topic') or path.stem,
        'date_updated': note_date(meta, path, prefer='updated'),
        'date_created': note_date(meta, path, prefer='created'),
        'sources': sorted(parse_source_ids(meta.get('sources', ''))),
        'source_count': len(parse_source_ids(meta.get('sources', ''))),
        'snippet': note_snippet(body) or '(no content)',
    }


def note_rows(notes_dir, topic_note_paths: set) -> list:
    notes_dir = Path(notes_dir)
    if not notes_dir.exists():
        return []
    out = []
    for p in notes_dir.glob('*.md'):
        try:
            out.append(note_row(p, topic_note_paths))
        except OSError:
            continue
    return out


def note_sort_key(row: dict, mode: str):
    if mode in ('alpha', 'az'):
        return row['title'].lower()
    if mode == 'created':
        return -row['date_created'].timestamp()
    return -row['date_updated'].timestamp()


def sort_note_rows(rows: list, mode: str = 'updated') -> list:
    return sorted(rows, key=lambda r: note_sort_key(r, mode))


def safe_note_path(notes_dir, name: str):
    """data/notes/<name> when `name` is a plain .md file name inside the folder, else None."""
    if not name or '/' in name or '\\' in name or not name.endswith('.md') or name.startswith('.'):
        return None
    p = Path(notes_dir) / name
    return p if p.is_file() else None


# ── writes ───────────────────────────────────────────────────────────────────
def save_new_note(notes_dir, topic: str, source_ids, md: str) -> tuple:
    """A new synthesis note (the Qt _save_note): data/notes/<slug>.md, never overwriting.
    Returns (path, meta)."""
    notes_dir = Path(notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(topic)
    path = notes_dir / f'{slug}.md'
    n = 2
    while path.exists():
        path = notes_dir / f'{slug}-{n}.md'
        n += 1
    meta = {
        'topic': topic,
        'created': datetime.now().isoformat(timespec='seconds'),
        'sources': ','.join(str(i) for i in sorted(set(source_ids))),
    }
    write_front(path, meta, md)
    return path, meta


def write_back_note(path: Path, md: str, meta: dict, source_ids, topic: str = '') -> dict:
    """Overwrite an opened note in place, growing its frontmatter (sources + updated).
    Returns the new meta. (The Qt _write_back_note without the widget updates.)"""
    meta = dict(meta or {})
    new_ids = parse_source_ids(meta.get('sources', '')) | {int(i) for i in source_ids}
    meta['topic'] = meta.get('topic') or topic or Path(path).stem
    meta.setdefault('created', datetime.now().isoformat(timespec='seconds'))
    meta['updated'] = datetime.now().isoformat(timespec='seconds')
    meta['sources'] = ','.join(str(i) for i in sorted(new_ids))
    write_front(Path(path), meta, md)
    return meta


def rename_note(notes_dir, path: Path, new_title: str) -> Path:
    """Rename a note: a fresh file name from the slug (kept when the slug is unchanged) and
    the new title in its frontmatter. Returns the new path."""
    notes_dir, path = Path(notes_dir), Path(path)
    meta, body = split_frontmatter(path.read_text(encoding='utf-8'))
    slug = slugify(new_title)
    new_path = notes_dir / f'{slug}.md'
    n = 2
    while new_path.exists() and new_path != path:
        new_path = notes_dir / f'{slug}-{n}.md'
        n += 1
    meta['topic'] = new_title
    meta['updated'] = datetime.now().isoformat(timespec='seconds')
    write_front(new_path, meta, body)
    if new_path != path:
        try:
            path.unlink()
        except Exception:
            pass
    return new_path


def delete_note(path: Path) -> None:
    Path(path).unlink()


# ── topics I follow ──────────────────────────────────────────────────────────
def topic_note_path(notes_dir, topic: dict):
    """The digest note file for a topic, or None when it has no note yet."""
    if topic.get('note_path'):
        p = Path(notes_dir) / topic['note_path']
        if p.exists():
            return p
    return None


TOPIC_FTS_POOL = 100          # keyword candidates per topic (bm25, every word required)
TOPIC_SEMANTIC_K = 30         # nearest-neighbour candidates per topic once its query is embedded
TOPIC_SEMANTIC_FLOOR = 0.30   # min query-item cosine for a semantic candidate (noise guard)


def topic_candidates(db, query: str, index=None, query_vec=None) -> list:
    """Candidate item ids for a followed topic, best-first.

    Keyword-only unless both a search.EmbeddingIndex and the embedded query are given;
    then the keyword hits and the query's TOPIC_SEMANTIC_K nearest items (above
    TOPIC_SEMANTIC_FLOOR) are fused with search.hybrid_rank. The union is kept whole,
    so semantic ranking only adds candidates to the keyword set, never drops one."""
    fts = db.fts_ids(query, TOPIC_FTS_POOL, match_all=True)
    if index is None or query_vec is None or len(index) == 0:
        return fts
    vec_hits = [(i, s) for i, s in index.topk(query_vec, TOPIC_SEMANTIC_K)
                if s >= TOPIC_SEMANTIC_FLOOR]
    return search_core.hybrid_rank(fts, vec_hits, limit=len(fts) + len(vec_hits))


def topic_new_ids(db, notes_dir, topic: dict, index=None, query_vec=None) -> list:
    """New items for a topic = current candidates (topic_candidates) minus the ids
    already folded into its digest note (the note's `sources:` frontmatter is the
    ledger, so there is no created-vs-modified timestamp ambiguity)."""
    candidates = topic_candidates(db, topic['query'], index=index, query_vec=query_vec)
    path = topic_note_path(notes_dir, topic)
    if path is None:
        return candidates
    meta, _body = split_frontmatter(path.read_text(encoding='utf-8'))
    done = parse_source_ids(meta.get('sources', ''))
    return [i for i in candidates if i not in done]


def new_digest_path(notes_dir, name: str) -> Path:
    """data/notes/topic-<slug>.md for a topic's first digest (not written here)."""
    notes_dir = Path(notes_dir)
    path = notes_dir / f'topic-{slugify(name)}.md'
    n = 2
    while path.exists():
        path = notes_dir / f'topic-{slugify(name)}-{n}.md'
        n += 1
    return path


# ── find sources ─────────────────────────────────────────────────────────────
def search_sources(db, topic: str, limit: int, index=None, vec=None) -> tuple:
    """(rows, mode). FTS (every word must match), upgraded to hybrid bm25 + cosine when an
    index and the topic's vector are given (the Qt _on_query_vec numbers)."""
    rows = db.fts_search(topic, limit=limit, match_all=True)
    if index is not None and vec is not None and len(index):
        pool = max(limit, 100)   # candidate pool per side; never smaller than the old default
        ids = search_core.hybrid_rank(db.fts_ids(topic, pool, match_all=True), index.topk(vec, pool), limit=limit)
        hybrid = db.get_items_by_ids(ids)
        if hybrid:
            return hybrid, 'hybrid'
    return rows, 'fts'
