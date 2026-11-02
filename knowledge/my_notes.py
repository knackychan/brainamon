"""
my_notes.py - the My Notes notebook's file logic, Qt-free. Moved from ui/my_notes_window.py so the
Qt window and the V6 server (server/routes/my_notes.py) share it.

Personal notes are data/notes/<slug>.md with `kind: personal` and `category` frontmatter, the same
folder and format as the Knowledge notes (so notes_fts indexes them). Categories are a JSON list
in the DB settings key `my_note_categories`, merged with the ones found in the notes. The caller
runs db.reindex_notes() after every write (Qt main thread or the server Writer).
"""
import json
from datetime import datetime
from pathlib import Path

from core import note_format
from knowledge import knowledge

ALL_CATEGORY = 'All'
DEFAULT_CATEGORY = 'General'
CATEGORIES_SETTING = 'my_note_categories'   # JSON list in the db settings table
SUMMARY_MARKER = '\n## AI summary\n'


def stored_categories(db) -> list:
    try:
        cats = json.loads(db.get_setting(CATEGORIES_SETTING, '[]'))
    except Exception:
        cats = []
    return [c for c in cats if isinstance(c, str) and c.strip()]


def personal_notes(notes_dir) -> list:
    """[(path, meta, body)] for every kind: personal note, newest-updated first."""
    out = []
    notes_dir = Path(notes_dir)
    if not notes_dir.exists():
        return out
    for p in notes_dir.glob('*.md'):
        try:
            meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        if meta.get('kind') == 'personal':
            out.append((p, meta, body))
    out.sort(key=lambda t: t[1].get('updated') or t[1].get('created') or '', reverse=True)
    return out


def all_categories(db, notes_dir) -> list:
    """Stored categories + any found in existing personal notes."""
    cats = set(stored_categories(db)) | {DEFAULT_CATEGORY}
    for _path, meta, _body in personal_notes(notes_dir):
        if meta.get('category'):
            cats.add(meta['category'])
    return sorted(cats, key=str.lower)


def add_category(db, name: str) -> bool:
    """Store a new category (a write). False when it is empty or already there."""
    name = (name or '').strip()
    cats = stored_categories(db)
    if not name or name.lower() in {c.lower() for c in cats}:
        return False
    cats.append(name)
    db.set_setting(CATEGORIES_SETTING, json.dumps(cats))
    return True


def _write(path: Path, meta: dict, body: str) -> None:
    front = '---\n' + ''.join(f'{k}: {v}\n' for k, v in meta.items()) + '---\n\n'
    path.write_text(front + body, encoding='utf-8')


def create_note(notes_dir, title: str, category: str) -> Path:
    """A new empty personal note filed under `category` (All becomes General)."""
    notes_dir = Path(notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    slug = knowledge.slugify(title)
    path = notes_dir / f'{slug}.md'
    n = 2
    while path.exists():
        path = notes_dir / f'{slug}-{n}.md'
        n += 1
    if not category or category == ALL_CATEGORY:
        category = DEFAULT_CATEGORY
    now = datetime.now().isoformat(timespec='seconds')
    meta = {'topic': title, 'created': now, 'updated': now, 'kind': 'personal', 'category': category}
    _write(path, meta, '')
    return path


def save_note(path: Path, title: str, category: str, body: str, stamps=None) -> dict:
    """Write a personal note (the autosave): title, category, body; keeps the other meta. `stamps` (a list,
    core/note_format.py) replaces the note's stamps; None keeps the `stamps:` line as it is."""
    path = Path(path)
    meta = {}
    if path.exists():
        meta, _old = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
    now = datetime.now().isoformat(timespec='seconds')
    meta['topic'] = (title or '').strip() or path.stem
    meta.setdefault('created', now)
    meta['updated'] = now
    meta['kind'] = 'personal'
    meta['category'] = category or DEFAULT_CATEGORY
    if stamps is not None:
        note_format.set_stamps(meta, stamps)
    _write(path, meta, (body or '').rstrip() + '\n')
    return meta


def replace_summary(body: str, md: str) -> str:
    """Append (or replace a previous) "## AI summary" section at the end of the note."""
    if SUMMARY_MARKER in '\n' + body:
        body = body[:('\n' + body).index(SUMMARY_MARKER)]
    return body.rstrip() + f'\n\n## AI summary\n\n{md}\n'


def append_digest(body: str, text: str, timestamp: str = None) -> str:
    """Append a screenshot transcription under a dated heading."""
    timestamp = timestamp or datetime.now().isoformat(timespec='seconds')
    return body.rstrip() + f'\n\n## Screenshot digest — {timestamp}\n\n{text}\n'


def append_voice(body: str, text: str, timestamp: str = None) -> str:
    """Append a voice transcription under a dated heading."""
    timestamp = timestamp or datetime.now().strftime('%Y-%m-%d %H:%M')
    head = (body or '').rstrip()
    return (head + '\n\n' if head else '') + f'## Voice note - {timestamp}\n\n{text.strip()}\n'


def add_voice(path: Path, text: str) -> dict:
    """Add a transcription to the note at `path` (a write: call on the Writer). Keeps title and category."""
    path = Path(path)
    meta, body = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
    return save_note(path, meta.get('topic') or '', meta.get('category') or '', append_voice(body.strip('\n'), text))


def combine_digest(parts: list) -> str:
    """[(filename, text)] as one block (a heading per screenshot when there are several)."""
    if len(parts) > 1:
        return '\n\n'.join(f'--- {name} ---\n{text}' for name, text in parts)
    return parts[0][1] if parts else ''
