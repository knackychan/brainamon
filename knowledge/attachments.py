"""Ask attachments (projects/desktop-app plan 11): files, text and video analyses attached to a
Wiskit question. Qt-free, no SQLite.

An attachment is a file in data/inbox (copied there with inbox.save_file, like any dropped file) or a
Video Tools output folder data/video_tools/items/<name>. Its id is the inbox file name, or
'video:<folder name>'. An image is described once at upload and a PDF's text layer is read once
(pypdf); either text is kept next to the copy as '<file name>.txt'. resolve(id) turns an id back
into (name, text) for the Ask turn and for filing (knowledge/filing.py).
"""
import base64
import io
from pathlib import Path

from knowledge import inbox

TEXT_EXTS = {'.txt', '.md', '.csv', '.json', '.py', '.js', '.ts', '.html', '.css', '.xml', '.yaml', '.yml', '.log', '.ini'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
MEDIA = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
VIDEO_PREFIX = 'video:'
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_CHARS = 40_000        # one attachment's text in the question's turn
HISTORY_CHARS = 8_000     # one attachment's text kept in the saved chat
ACK = 'I have read the attached file(s) and will use them in my answers.'
GONE = 'That attachment is gone; drop it again.'


class Unsupported(ValueError):
    """The file type cannot be attached (the route answers 415)."""


class Gone(LookupError):
    """The id names nothing attachable: moved, deleted, or not a safe name."""


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in TEXT_EXTS:
        return 'text'
    if ext in IMAGE_EXTS:
        return 'image'
    if ext == '.pdf':
        return 'pdf'
    raise Unsupported(f'Wiskit cannot read {ext or "these"} files yet.')


def pdf_text(raw: bytes) -> str:
    """The text layer of a PDF, page by page (pypdf, no AI call). Raises ValueError when the file
    is not a readable PDF or has no text (a scan: the user drops page screenshots instead)."""
    from pypdf import PdfReader          # only PDFs need it
    try:
        pages = PdfReader(io.BytesIO(raw)).pages
        parts = [(i + 1, (pages[i].extract_text() or '').strip()) for i in range(min(len(pages), MAX_PDF_PAGES))]
    except Exception as exc:
        raise ValueError(f'That PDF could not be read: {str(exc)[:160]}') from None
    text = '\n\n'.join(f'### Page {n}\n\n{t}' for n, t in parts if t)
    if not text:
        raise ValueError('That PDF has no text layer (a scan). Drop screenshots of its pages instead.')
    return text


def save(data_dir, name: str, raw: bytes, describe) -> dict:
    """Copy an attached file into data/inbox. For an image, describe(media_type, raw) -> text runs
    first (one vision call; if it fails nothing is copied); a PDF's text layer is read first (if
    it has none nothing is copied). Either text is saved as '<copy>.txt'."""
    kind = kind_of(name)
    if not raw:
        raise ValueError('The file is empty.')
    desc = ''
    if kind == 'image':
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('That picture is over 10 MB.')
        desc = describe(MEDIA[Path(name).suffix.lower()], raw)
    elif kind == 'pdf':
        if len(raw) > MAX_PDF_BYTES:
            raise ValueError('That PDF is over 30 MB.')
        desc = pdf_text(raw)
    path = inbox.save_file(data_dir, name, raw)
    if kind in ('image', 'pdf'):
        path.with_name(path.name + '.txt').write_text(desc, encoding='utf-8')
    _name, text = resolve(data_dir, path.name)
    return {'id': path.name, 'name': path.name, 'kind': kind, 'chars': len(text)}


def save_text(data_dir, text: str) -> dict:
    """Attach dropped text (or a link) as data/inbox/<date>-pasted.txt."""
    text = (text or '').strip()
    if not text:
        raise ValueError('Nothing to attach.')
    path = inbox.save_file(data_dir, 'pasted.txt', text.encode('utf-8'))
    return {'id': path.name, 'name': path.name, 'kind': 'text', 'chars': len(text)}


def analysis(data_dir, folder: str) -> dict:
    """Attach a finished Video Tools analysis: only a folder directly in data/video_tools/items."""
    base = (Path(data_dir) / 'video_tools' / 'items').resolve()
    p = Path(str(folder or '')).resolve()
    if p.parent != base or not p.is_dir():
        raise Gone('That is not a Video Tools analysis.')
    aid = VIDEO_PREFIX + p.name
    name, text = resolve(data_dir, aid)
    return {'id': aid, 'name': name, 'kind': 'video', 'chars': len(text)}


def _safe(part: str) -> str:
    if not part or part in ('.', '..') or '/' in part or '\\' in part or ':' in part or Path(part).name != part:
        raise Gone(GONE)
    return part


def resolve(data_dir, aid: str) -> tuple[str, str]:
    """An attachment id -> (display name, text). Raises Gone."""
    data_dir, aid = Path(data_dir), str(aid or '')
    if aid.startswith(VIDEO_PREFIX):
        folder = data_dir / 'video_tools' / 'items' / _safe(aid[len(VIDEO_PREFIX):])
        parts = [(f, folder / f) for f in ('report.md', 'transcript.txt') if (folder / f).is_file()]
        if not parts:
            raise Gone(GONE)
        text = '\n\n'.join(f'### {f}\n\n{p.read_text(encoding="utf-8", errors="replace").strip()}' for f, p in parts)
        return f'{folder.name} (video analysis)', text
    p = data_dir / 'inbox' / _safe(aid)
    try:
        kind = kind_of(p.name)
    except Unsupported:
        raise Gone(GONE) from None
    src = p.with_name(p.name + '.txt') if kind in ('image', 'pdf') else p
    if not p.is_file() or not src.is_file():
        raise Gone(GONE)
    return p.name, src.read_text(encoding='utf-8', errors='replace')


def image_bytes(data_dir, aid: str) -> tuple[str, str, str]:
    """An attached picture as (name, media type, base64), for the screenshot digest. Raises Gone,
    or Unsupported when the attachment is not a picture."""
    aid = str(aid or '')
    if aid.startswith(VIDEO_PREFIX) or Path(aid).suffix.lower() not in IMAGE_EXTS:
        raise Unsupported('Only pictures can be digested.')
    p = Path(data_dir) / 'inbox' / _safe(aid)
    if not p.is_file():
        raise Gone(GONE)
    return p.name, MEDIA[p.suffix.lower()], base64.b64encode(p.read_bytes()).decode('ascii')


def block(name: str, text: str, cap: int) -> str:
    body = text[:cap]
    if len(text) > cap:
        body += f'\n\n[cut: the first {cap} of {len(text)} characters]'
    return f'Attached file "{name}":\n{body}'


def history_pair(resolved, cap: int) -> list[dict]:
    """The attachments as one user message plus Wiskit's acknowledgement, placed before the question
    in the chat history, so Quick and Deep mode both see them and follow-ups keep them."""
    if not resolved:
        return []
    return [{'role': 'user', 'content': '\n\n'.join(block(n, t, cap) for n, t in resolved)},
            {'role': 'assistant', 'content': ACK}]
