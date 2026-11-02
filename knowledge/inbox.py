"""The Inbox: where things dropped on Wiskit's panel land (projects/desktop-app plan 07). Qt-free.

One personal note, "Inbox" in the My Notes category "Inbox" (created on first use), collects dropped
text, the screenshot digests (the existing digest job writes into it) and the list of dropped files.
Files are copied to data/inbox/<date>-<name>. The caller runs db.reindex_notes() after a note write
(on the server's Writer).
"""
import re
from datetime import datetime
from pathlib import Path

from knowledge import knowledge
from knowledge import my_notes

TITLE = 'Inbox'
CATEGORY = 'Inbox'
_URL = re.compile(r'^https?://\S+$', re.I)
_FIND = re.compile(r'https?://[^\s<>"\']+', re.I)
_BARE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24})(:\d{1,5})?([/?#]\S*)?$', re.I)
# endings that read as a file name (notes.md, app.py), not an address, unless www. or a path says otherwise
_FILE_ENDINGS = {'md', 'txt', 'py', 'js', 'ts', 'json', 'csv', 'html', 'css', 'xml', 'yaml', 'yml', 'log', 'ini',
                 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'pdf', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'zip',
                 'exe', 'doc', 'docx'}
# share-sheet tracking parameters, dropped so items.url UNIQUE still dedupes a link shared twice
# (= web/src/mobile/links.ts TRACKING and public/sw.js; tests/fixtures/share_links.json checks all of them)
_TRACKING = re.compile(r'^(utm_\w+|igsh|igshid|si|mibextid|fbclid|rdid|share_id|feature)$', re.I)
_UNSAFE = re.compile(r'[^\w.\- ]+')
MAX_FILE_BYTES = 200 * 1024 * 1024


def is_url(text: str) -> bool:
    return bool(_URL.match((text or '').strip()))


def clean_link(url: str) -> str:
    """A found link without trailing punctuation and share tracking parameters (igsh, si, mibextid,
    utm_*...). Plain string work, no URL normalising, so the phone's copy gives the same text."""
    url = re.sub(r'[.,;:!?\'"]+$', '', url)
    if url.endswith(')') and '(' not in url:
        url = url.rstrip(')')
    base, hash_, frag = url.partition('#')
    path, q, query = base.partition('?')
    if q:
        keep = [p for p in query.split('&') if p and not _TRACKING.match(p.split('=', 1)[0])]
        base = path + ('?' + '&'.join(keep) if keep else '')
    return base + hash_ + frag


def link(text: str) -> str | None:
    """The web link in what was typed, dropped or shared: the first http(s)://... in the text (apps
    share "Check this out https://www.instagram.com/reel/...?igsh=..."), cleaned by clean_link; a
    bare address (text.com, www.x.com/a) that is the whole text gets https:// in front. None when
    there is no link (a file name like notes.md is not one). desktop/widget.py and the phone
    (web/src/mobile/links.ts) have copies; tests/fixtures/share_links.json checks they agree."""
    t = (text or '').strip()
    m = _FIND.search(t)
    if m:
        return clean_link(m.group(0))
    m = _BARE.match(t)
    if not m or (m.group(1).lower() in _FILE_ENDINGS and not t.lower().startswith('www.') and not m.group(3)):
        return None
    return clean_link('https://' + t)


def note(notes_dir) -> Path:
    """The Inbox note, created when missing."""
    for p, meta, _body in my_notes.personal_notes(notes_dir):
        if meta.get('topic') == TITLE and meta.get('category') == CATEGORY:
            return p
    return my_notes.create_note(notes_dir, TITLE, CATEGORY)


def append(path: Path, heading: str, text: str, when: str | None = None) -> None:
    """Add a dated section to the Inbox note (newest last, like the screenshot digest)."""
    meta, body = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
    when = when or datetime.now().isoformat(timespec='seconds')
    body = body.rstrip() + f'\n\n## {heading} - {when}\n\n{text.strip()}\n'
    my_notes.save_note(path, meta.get('topic') or TITLE, meta.get('category') or CATEGORY, body)


def save_file(data_dir, name: str, raw: bytes) -> Path:
    """Copy a dropped file to data/inbox/<date>-<name> (never overwrites)."""
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('That file is too large for the Inbox (200 MB at most).')
    clean = _UNSAFE.sub('_', Path(name or 'file').name).strip(' .') or 'file'
    folder = Path(data_dir) / 'inbox'
    folder.mkdir(parents=True, exist_ok=True)
    stem = f'{datetime.now():%Y-%m-%d}-{clean}'
    path, n = folder / stem, 2
    while path.exists():
        base, dot, ext = stem.rpartition('.')
        path = folder / (f'{base}-{n}.{ext}' if dot else f'{stem}-{n}')
        n += 1
    path.write_bytes(raw)
    return path
