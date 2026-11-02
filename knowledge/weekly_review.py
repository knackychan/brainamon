"""weekly_review.py - the on-demand "Review this week" action in Wiskit (projects/knowledge-maintenance).

This module owns the deterministic half of the feature: request/metadata validation, the seven-calendar-day
selection (library items by recorded `created`, notes by their effective date), honest coverage counting, the
bounded prompt, and structural citation-target validation of the model's answer. It does no I/O to the network
and no writes; collection reads the library through the caller's read-only connection and the notes folder
directly. It must not import `ask_core` or `ask_chats` (both depend on its metadata validation).
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core import note_format
from knowledge import knowledge
from knowledge import prompt_files
from knowledge.prompt_files import fill
from knowledge import synth

P = prompt_files.load('weekly_review')
L = P['limits']
SECTIONS = list(P['sections'])
SECTION_LIMITS = (5, 5, 5, 3)
SENTINEL = 'None found in the reviewed material.'

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_HEADING_RE = re.compile(r'^## (.+)$')
_BULLET_RE = re.compile(r'^-\s+(.+)$')
_NOTE_REF_RE = re.compile(r'^\s*note\s*:\s*(.+?)\s*$', re.IGNORECASE)
_ID_REF_RE = re.compile(r'^\s*ids?\b', re.IGNORECASE)


def _has_ws_or_control(s: str) -> bool:
    return any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in s)


def _parse_instant(raw: object) -> datetime:
    """Parse an ISO instant, accepting a trailing Z or an explicit offset. Raises ValueError."""
    if not isinstance(raw, str):
        raise ValueError('The review time must be an ISO instant.')
    s = raw.strip()
    if not s:
        raise ValueError('The review time is missing.')
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError('The review time needs a timezone.')
    return dt


def _resolve_zone(raw: object) -> ZoneInfo:
    if not isinstance(raw, str) or not raw:
        raise ValueError('The review timezone is missing.')
    if len(raw) > 100 or _has_ws_or_control(raw):
        raise ValueError('The review timezone is not valid.')
    try:
        return ZoneInfo(raw)
    except Exception:
        raise ValueError('The review timezone is not recognized.')


def _epoch_ms(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def _one_line(value: str, cap: int) -> str:
    return ' '.join((value or '').split())[:cap]


def _local_date(epoch_ms: int, zone: ZoneInfo) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).astimezone(zone).date().isoformat()


def _representable(filename: str) -> bool:
    return bool(filename) and not any(ch in filename for ch in ('[', ']', '\n', '\r')) \
        and not any(ord(ch) < 32 for ch in filename)


# ── request and metadata validation ──────────────────────────────────────────
def validate_request(body: dict, *, now: datetime) -> dict:
    """Validate a weekly-review request and return canonical metadata. Raises ValueError with a
    short user-facing reason. `now` is an aware UTC datetime supplied by the caller."""
    if (body.get('chat') or ''):
        raise ValueError('Start a review from a fresh chat.')
    if (body.get('attachments') or []):
        raise ValueError('A review cannot use attachments.')
    if not str(body.get('question') or '').strip():
        raise ValueError('Type a question first.')

    at = _parse_instant(body.get('review_at'))
    zone = _resolve_zone(body.get('review_timezone'))

    at_utc = at.astimezone(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    if abs((at_utc - now_utc).total_seconds()) > 300:
        raise ValueError('The review time is too far from the server clock.')

    local = at_utc.astimezone(zone)
    end_date = local.date()
    start_date = end_date - timedelta(days=6)
    return {
        'kind': 'weekly',
        'start': start_date.isoformat(),
        'end': end_date.isoformat(),
        'timezone': zone.key,
        'through': at_utc.isoformat(),
    }


def validate_metadata(raw: object) -> dict:
    """Strictly validate a persisted review metadata object (independent of the current date) and
    return the canonical dict. Raises ValueError on any structural or date mismatch."""
    if not isinstance(raw, dict):
        raise ValueError('Review metadata must be an object.')
    if set(raw.keys()) != {'kind', 'start', 'end', 'timezone', 'through'}:
        raise ValueError('Review metadata has unexpected fields.')
    if raw.get('kind') != 'weekly':
        raise ValueError('Review metadata kind must be weekly.')

    start, end, tz, through = raw.get('start'), raw.get('end'), raw.get('timezone'), raw.get('through')
    if not all(isinstance(v, str) for v in (start, end, tz, through)):
        raise ValueError('Review metadata fields must be strings.')
    if not _DATE_RE.fullmatch(start) or not _DATE_RE.fullmatch(end):
        raise ValueError('Review metadata dates must be YYYY-MM-DD.')

    zone = _resolve_zone(tz)
    through_dt = _parse_instant(through)

    local = through_dt.astimezone(zone)
    end_date = local.date()
    start_date = end_date - timedelta(days=6)
    if start_date.isoformat() != start or end_date.isoformat() != end:
        raise ValueError('Review metadata dates do not match its time.')

    return {
        'kind': 'weekly',
        'start': start,
        'end': end,
        'timezone': zone.key,
        'through': through_dt.astimezone(timezone.utc).isoformat(),
    }


# ── source collection ────────────────────────────────────────────────────────
def collect(db, notes_dir: Path, review: dict, *, should_stop=lambda: False):
    """Read the library and notes for the review's seven-calendar-date window and return the source
    bundle, or None when cancelled. Read-only: no writes and no network work."""
    zone = ZoneInfo(review['timezone'])
    through_dt = _parse_instant(review['through'])
    at_utc = through_dt.astimezone(timezone.utc)
    start_date = date.fromisoformat(review['start'])
    start_utc = datetime(start_date.year, start_date.month, start_date.day, tzinfo=zone).astimezone(timezone.utc)
    start_ms, through_ms = _epoch_ms(start_utc), _epoch_ms(at_utc)

    item_count, item_chars = L['item_count'], L['item_chars']
    title_chars, category_chars = L['title_chars'], L['category_chars']
    note_count, note_chars = L['note_count'], L['note_chars']

    items, rows = [], []
    items_cov = {'eligible': 0, 'empty': 0, 'included': 0, 'omitted': 0, 'truncated': 0}
    cur = db.conn.cursor()
    cur.execute(
        'SELECT * FROM items WHERE created >= ? AND created < ? ORDER BY created DESC, id ASC',
        (start_ms, through_ms))
    for row in cur:
        if should_stop():
            return None
        items_cov['eligible'] += 1
        r = dict(row)
        # Same precedence as synth.excerpt (ai_desc, transcript, description, short_desc).
        full = (r.get('ai_desc') or r.get('transcript') or r.get('description') or r.get('short_desc') or '').strip()
        if not full:
            items_cov['empty'] += 1
            continue
        if items_cov['included'] >= item_count:
            items_cov['omitted'] += 1
            continue
        items.append({
            'id': r['id'],
            'title': _one_line(synth.title(r), title_chars),
            'date': _local_date(r['created'], zone),
            'category': _one_line(r.get('category') or '', category_chars),
            'text': full[:item_chars],
        })
        rows.append(r)
        items_cov['included'] += 1
        if len(full) > item_chars:
            items_cov['truncated'] += 1

    notes_dir = Path(notes_dir)
    resolved_dir = notes_dir.resolve()
    notes = []
    candidates = []   # (sort_key, note_dict, truncated, fallback)
    notes_cov = {'eligible': 0, 'empty': 0, 'included': 0, 'omitted': 0, 'truncated': 0,
                 'fallback_eligible': 0, 'fallback_included': 0, 'unreadable': 0, 'excluded_reviews': 0}
    for path in sorted(notes_dir.glob('*.md')):
        if should_stop():
            return None
        if path.is_symlink():
            try:
                if path.resolve().parent != resolved_dir:
                    notes_cov['unreadable'] += 1
                    continue
            except OSError:
                notes_cov['unreadable'] += 1
                continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            notes_cov['unreadable'] += 1
            continue
        meta, body = knowledge.split_frontmatter(text)
        if meta.get('review_kind') == 'weekly':
            notes_cov['excluded_reviews'] += 1
            continue
        try:
            instant, fallback = _note_instant(meta, path, zone)
        except OSError:
            notes_cov['unreadable'] += 1
            continue
        utc = instant.astimezone(timezone.utc)
        if not (start_utc <= utc < at_utc):
            continue
        notes_cov['eligible'] += 1
        if fallback:
            notes_cov['fallback_eligible'] += 1
        plain = note_format.plain(body).strip()
        if not plain:
            notes_cov['empty'] += 1
            continue
        filename = path.name
        if not _representable(filename):
            notes_cov['unreadable'] += 1
            continue
        candidates.append((
            (-utc.timestamp(), filename),
            {
                'file': filename,
                'title': _one_line(meta.get('topic') or path.stem, title_chars),
                'date': utc.astimezone(zone).date().isoformat(),
                'category': _one_line(meta.get('category') or '', category_chars),
                'text': plain[:note_chars],
            },
            len(plain) > note_chars,
            fallback,
        ))

    candidates.sort(key=lambda c: c[0])
    kept = candidates[:note_count]
    notes = [c[1] for c in kept]
    notes_cov['included'] = len(kept)
    notes_cov['omitted'] = len(candidates) - len(kept)
    notes_cov['truncated'] = sum(1 for c in kept if c[2])
    notes_cov['fallback_included'] = sum(1 for c in kept if c[3])

    return {
        'review': review,
        'items': items,
        'notes': notes,
        'rows': rows,
        'coverage': {'items': items_cov, 'notes': notes_cov},
    }


def _note_instant(meta: dict, path: Path, zone: ZoneInfo) -> tuple:
    """A note's effective instant: `updated`, else `created`, else filesystem mtime (UTC).
    Returns (aware datetime, fallback_bool). Naive values get the requested timezone."""
    for key in ('updated', 'created'):
        raw = (meta.get(key) or '').strip()
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone, fold=0)
        return dt, False
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc), True


# ── prompt and output ────────────────────────────────────────────────────────
def build_turn(bundle: dict) -> dict:
    """The single bounded model request: {messages, system, max_tokens}. One user message holding
    the serialized source bundle; no chat history, profile, attachments or tool messages."""
    data = json.dumps({
        'period': {
            'start': bundle['review']['start'],
            'end': bundle['review']['end'],
            'timezone': bundle['review']['timezone'],
        },
        'included': {'items': len(bundle['items']), 'notes': len(bundle['notes'])},
        'items': bundle['items'],
        'notes': bundle['notes'],
    }, ensure_ascii=False)
    sections_block = '\n'.join(f'## {s}' for s in SECTIONS)
    system = fill(P['system'], sections=sections_block) + '\n\n' + note_format.contract()
    return {
        'messages': [{'role': 'user', 'content': fill(P['user'], data=data)}],
        'system': system,
        'max_tokens': L['requested_max_tokens'],
    }


def validate_output(text: str, bundle: dict) -> str:
    """Validate the model's four-section Markdown body against the included source set. Returns the
    stripped body, or raises ValueError on any structural or citation-target failure."""
    text = (text or '').strip()
    if not text:
        raise ValueError('The review came back empty.')
    if len(text) > L['max_output_chars']:
        raise ValueError('The review is too long.')

    item_ids = {it['id'] for it in bundle['items']}
    note_files = {n['file'] for n in bundle['notes']}

    seen, sections, current = [], [], -1
    for raw_line in text.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('```'):
            raise ValueError('The review must not contain code fences.')
        if line.startswith('#'):
            m = _HEADING_RE.match(line)
            if not m:
                raise ValueError('Only the four level-2 sections are allowed.')
            title = m.group(1).strip()
            if len(seen) >= 4 or title != SECTIONS[len(seen)]:
                raise ValueError('Sections must appear exactly once in order.')
            seen.append(title)
            current = len(seen) - 1
            sections.append([])
            continue
        bm = _BULLET_RE.match(line)
        if not bm:
            raise ValueError('Only single-line bullet points are allowed inside sections.')
        if current < 0:
            raise ValueError('The review must open with the first section.')
        sections[current].append(bm.group(1).strip())

    if seen != SECTIONS:
        raise ValueError('The review must contain the four sections in order.')
    for i, sec in enumerate(sections):
        if not sec:
            raise ValueError(f'The section "{SECTIONS[i]}" is empty.')
        if len(sec) > SECTION_LIMITS[i]:
            raise ValueError(f'Too many bullet points in "{SECTIONS[i]}".')

    for i, sec in enumerate(sections):
        for bullet in sec:
            if bullet == SENTINEL:
                if len(sec) != 1:
                    raise ValueError(f'The empty sentinel must stand alone in "{SECTIONS[i]}".')
                continue
            ids, notes = _bullet_citations(bullet)
            if not ids and not notes:
                raise ValueError('A bullet point needs at least one citation.')
            for bad in ids:
                if bad not in item_ids:
                    raise ValueError(f'Citation [id {bad}] is not in the reviewed material.')
            for bad in notes:
                if bad not in note_files:
                    raise ValueError(f'Citation [note: {bad}] is not in the reviewed material.')
            if i == 1 and not notes:
                raise ValueError('"Notes worth revisiting" bullets must cite a note.')
    return text


def _bullet_citations(bullet: str) -> tuple:
    """Parse one bullet's citation targets. Raises ValueError on malformed brackets, wikilinks or
    raw Markdown links. Returns (item_ids, note_files), each deduped in order."""
    if re.search(r'\[\[|\]\]', bullet):
        raise ValueError('Wikilinks are not allowed.')
    if re.search(r'\]\(', bullet):
        raise ValueError('Raw Markdown links are not allowed.')
    ids, notes = [], []
    for group in re.findall(r'\[([^\]]*)\]', bullet):
        g = group.strip()
        m = _NOTE_REF_RE.fullmatch(g)
        if m:
            filename = m.group(1).strip()
            if not filename:
                raise ValueError('A note reference has no filename.')
            notes.append(filename)
            continue
        if _ID_REF_RE.match(g):
            nums = re.findall(r'\d+', g)
            if not nums:
                raise ValueError('An item reference has no id.')
            ids.extend(int(n) for n in nums)
            continue
        raise ValueError('A bracket is not a valid citation.')
    return list(dict.fromkeys(ids)), list(dict.fromkeys(notes))


def compose_answer(body: str, bundle: dict) -> str:
    """Prepend the deterministic title and Coverage section to a validated body, or build the
    deterministic empty answer when there is no body."""
    review = bundle['review']
    items = bundle['coverage']['items']
    notes = bundle['coverage']['notes']
    zone = ZoneInfo(review['timezone'])
    hhmm = _parse_instant(review['through']).astimezone(zone).strftime('%H:%M')
    lines = [
        f"- Period: {review['start']} to {review['end']}, through {hhmm} ({review['timezone']}).",
        f"- Library: {items['included']} reviewed; {items['eligible']} date-eligible; {items['empty']} empty; "
        f"{items['omitted']} omitted; {items['truncated']} excerpts shortened.",
        f"- Notes: {notes['included']} reviewed; {notes['eligible']} date-eligible; {notes['empty']} empty; "
        f"{notes['omitted']} omitted; {notes['truncated']} excerpts shortened.",
        f"- Note dates: {notes['fallback_eligible']} eligible notes used file modification time; "
        f"{notes['fallback_included']} of those were reviewed.",
        f"- Note scan: {notes['unreadable']} files unavailable; {notes['excluded_reviews']} earlier review excluded.",
        f"- Items use recorded creation dates; imports may retain older dates. Notes show current text, not an edit "
        f"history. Legacy note dates without a timezone are interpreted in {review['timezone']}.",
    ]
    head = f"# Weekly review — {review['start']} to {review['end']}\n\n## Coverage\n" + '\n'.join(lines)
    if (body or '').strip():
        return head + '\n\n' + body
    return head + '\n\nNo material found for these dates.'
