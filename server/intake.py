"""Phone changes: the change files the phone leaves in the Drive mirror, applied on the Writer
(projects/mobile-app/PLAN.md Phase 4, step 5; format in projects/mobile-app/plans/04-phone-mirror.md).

The phone works from its copy of the mirror with the PC off; what it does there comes back as a
sealed change file (`chg-...`, library/mirror.py) holding {format, device, at, changes}. Each
change is one of:

    {"op": "link", "uid", "url", "note", "category", "tags", "at"}  a link saved (share sheet, paste, an
                                                                      Import: tags optional, at = save time)
    {"op": "details", "uid", "title", "creator", "desc", "thumb", "at"}  read from that link's page on the
                                                                      phone (thumb: base64 JPEG); fills empties
    {"op": "fav",  "uid", "on", "at"}                                 favourite on or off
    {"op": "edit", "uid", "fields": {...}, "was": {...}, "at"}        tags / category / notes / ai_desc
    {"op": "category_batch", "entries": [{"uid", "from", "category"}], "at"} one approved Wiskit batch
    {"op": "note", "file", "title", "category", "body", "was", "at"}  a My Note written or edited
    {"op": "note_append", "file", "title", "name", "text", "when", "at"}  one section added at the end of a
                                                                      My Note (Add to Brainamon, note-organic-ui plan 09)
    {"op": "note_category", "from", "to", "at"}                       a My Notes category renamed on the phone
                                                                      (manifest `note_category`, spec 2026-11-07)
    {"op": "chat", "slug", "name", "created", "history", "source_ids", "options", "was", "at"}
                                                                      a Wiskit chat asked on the phone (Phase 5)
    {"op": "chat_delete", "slug", "turns", "at"}                      a Wiskit chat deleted on the phone
    {"op": "delete", "uid", "pc", "at"}                               an item deleted on the phone; the PC
                                                                       deletes it too only when `pc` is true
    {"op": "answer", "md", "ids", "at"}                               a phone answer saved as a note
    {"op": "synth", "topic", "sources", "uids", "body", "at"}         a note synthesized on the phone (uids: one
                                                                      per source, a link saved on the phone's uid,
                                                                      '' for a PC item; an older phone sends none)
    {"op": "synth_queue", "topic", "ids", "at"}                       too many sources for the phone: the PC
                                                                      runs Synthesize (SYNTH_QUEUE setting)

`at` is when the phone made the change (ms); the file's own `at` is when it was sealed, and
`applied[device]` (the cloud_applied setting, copied into the manifest) records the latest file
applied, so the phone drops its pending copy and a file seen twice is skipped. Rules:
- A link goes through inbox.link (the same cleaning as POST /api/inbox/link). A link already in
  the library is a duplicate; a new one keeps the phone's uid, so its later edits find it. When
  the uids differ (a duplicate), `alias` maps the phone's to the library's, in this file and later
  ones (the phone may edit the card before its copy shows the PC's row).
- Favourites and edits, per field: the phone's value goes in unless the PC changed that field
  since the phone read it (the PC's value is no longer `was`) and the PC's write is newer than
  the phone's (items.modified > at - SKEW). Newest wins; SKEW gives the PC near ties, since the
  two clocks are not the same clock.
- Notes land in data/notes/ as personal notes under the phone's file name. When the PC edited the
  note after the phone read it and the PC's edit is newer, or the file is not a personal note,
  the phone's text is kept beside it as "<title> (from phone)" instead of overwriting.
- An addition (note_append) is one "## From <name> - <when>" section at the end of the PC's current
  note (knowledge/filing.py add_section): only the new text travels, so nothing the PC wrote is touched.
  A note gone on the PC (or not a My Note) keeps the text in a new "<title> (from phone)" note.
- A renamed category (note_category) moves every personal note filed under `from` to `to` and renames it in
  the stored list. Only the category line changes, never `updated` or the text, so it cannot conflict with an
  edit; a name the rules refuse (my_notes.clean_category, General) is skipped.
- A chat replaces the PC's copy (data/ask_chats/<slug>.json) unless the PC added to that chat after
  the phone read it (its `updated` is no longer `was`) and later than the phone's turn: then the
  phone's chat is saved beside it as "<name> (from phone)".
- A chat deleted on the phone goes from data/ask_chats/ unless the PC has more turns in it than
  the phone saw (`turns`): someone asked on the PC since, so the PC's chat stays (no clock compare:
  the PC's own save of a phone turn bumps `updated`, and a delete cannot be undone).
- Phone answers and syntheses become new Knowledge notes (never overwriting); a queued synthesis
  waits in the SYNTH_QUEUE setting until the sync thread can start a Synthesize job.

A change the PC cannot read (a field of the wrong type, a phone and a PC on different versions)
is skipped and counted, never raised: one bad change must not stop the rest of its file, and a
file that raises would be applied again from the top on the next look (server/sync.py records
each file as applied once apply() returns).

apply() runs on the Writer (it writes items and notes and reindexes); the sync thread downloads,
opens and deletes the files (server/sync.py).
"""
import base64
import io
import json
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core import app_console
from core.urls import http_url
from knowledge import ask_core, filing, inbox, knowledge, my_notes
from knowledge.ask_chats import AskChatStore
from library.importers import _save_thumb
from library import canvas_plan
from library.canvas import CanvasStore

EDITABLE = ('tags', 'category', 'notes', 'ai_desc')
SKEW = 30_000                          # ms: a PC edit this close before the phone's still wins a conflict
SYNTH_QUEUE = 'cloud_synth_queue'      # [{topic, ids}] asked from the phone, run by server/sync.py
_NOTE_FILE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,120}\.md$')
_UID = re.compile(r'^[0-9a-f]{32}$')
_LONE = re.compile('[\\ud800-\\udfff]')          # a lone UTF-16 surrogate (JSON "\ud800"): UTF-8 cannot carry it
_SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,80}$')


@dataclass
class Applied:
    new_ids: list = field(default_factory=list)       # items made from saved links (they need thumbnails)
    item_ids: list = field(default_factory=list)      # items changed (new ones included)
    notes: list = field(default_factory=list)         # note files written
    chats: list = field(default_factory=list)         # chat slugs written
    deleted_chats: list = field(default_factory=list) # chat slugs deleted
    queued: int = 0                                    # syntheses left for the PC to run
    links: int = 0
    dups: int = 0
    favs: int = 0
    edits: int = 0
    deleted: int = 0                                   # items deleted from the phone
    kept_pc: int = 0                                   # fields where the PC's newer value won
    skipped: int = 0                                   # changes the PC could not read
    applied: dict = field(default_factory=dict)        # {device: latest change time applied}
    alias: dict = field(default_factory=dict)          # phone uid of a link -> the library item's uid,
                                                       # when they differ (kept across files by server/sync.py)
    canvases: list = field(default_factory=list)
    canvas_results: dict = field(default_factory=dict)

    def summary(self) -> str:
        parts = [f'{n} {w}' for n, w in ((self.links, 'link(s) saved'), (self.dups, 'duplicate link(s)'),
                                         (self.favs, 'favourite(s)'), (self.edits, 'edit(s)'), (self.deleted, 'item(s) deleted'),
                                         (len(self.notes), 'note(s)'), (len(self.chats), 'chat(s)'),
                                         (len(self.deleted_chats), 'chat(s) deleted'),
                                         (self.queued, 'synthesis(es) queued'), (self.kept_pc, 'newer PC value(s) kept'),
                                         (self.skipped, 'unreadable change(s) skipped'))
                 if n]
        return ', '.join(parts) or 'nothing new'


def _int(v) -> int:
    """A time or an id from the phone; anything that is not a whole number is 0."""
    if isinstance(v, bool):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return 0


def _ts(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def apply(db, doc: dict, out: Applied | None = None) -> Applied:
    """Apply one opened change file. Unknown ops, unreadable changes and items the PC deleted are
    skipped; nothing here raises for a change the phone sent."""
    out = out or Applied()
    device = str(doc.get('device') or 'phone')[:40]
    alias = out.alias                      # the phone's later edits to a duplicate link find the item
    batch = getattr(db.conn, 'batch', None)   # server/delivery.py: this file applies as one transaction
    wrote_notes = False
    last = 0
    changes = doc.get('changes')
    for ch in changes if isinstance(changes, list) else []:
        if not isinstance(ch, dict):
            out.skipped += 1
            continue
        at = _int(ch.get('at')) or _int(doc.get('at'))
        last = max(last, at)
        op = ch.get('op')
        try:
            if batch:
                batch.begin()
            if op == 'link':
                _link(db, ch, at, alias, out)
            elif op == 'details':
                _details(db, ch, alias, out)
            elif op in ('fav', 'edit'):
                _edit(db, ch, at, alias, out)
            elif op == 'category_batch':
                _category_batch(db, ch, alias, out)
            elif op == 'canvas':
                try:
                    _canvas(db, ch, alias, out)
                except Exception as e:
                    if batch and batch.fatal(e):
                        raise
                    out.skipped += 1
                    op_id = ch.get('op_id')
                    try:                   # never raise here: the rest of the file still applies
                        digest = _digest(ch)
                    except Exception:
                        digest = ''
                    if digest and isinstance(op_id, str) and _UID.fullmatch(op_id):
                        if op_id not in out.canvas_results or out.canvas_results[op_id].get('hash') == digest:
                            out.canvas_results[op_id] = {'canvas_id': str(ch.get('canvas_id') or '')[:64],
                                                         'state': 'refused', 'reason': _canvas_reason(e),
                                                         'hash': digest}
            elif op == 'note':
                wrote_notes |= _note(db, ch, at, out)
            elif op == 'note_append':
                wrote_notes |= _note_append(db, ch, out)
            elif op == 'note_delete':
                wrote_notes |= _note_delete(db, ch, out)
            elif op == 'note_category':
                wrote_notes |= _note_category(db, ch, out)
            elif op == 'chat':
                _chat(db, ch, at, out)
            elif op == 'chat_delete':
                _chat_delete(db, ch, out)
            elif op == 'delete':
                _delete(db, ch, alias, out)
            elif op in ('answer', 'synth'):
                wrote_notes |= _new_note(db, ch, out)
            elif op == 'synth_queue':
                _queue(db, ch, out)
            if batch:
                batch.end()
        except Exception as e:             # a phone on another version, a damaged change: skip it
            if batch and batch.fatal(e):
                raise                      # an error of this PC (disk, database): the whole file waits
            try:
                db.conn.rollback()         # whatever this change left uncommitted
            except Exception:
                if batch:
                    raise                  # failed file rollback must abort the batch before its receipt
            out.skipped += 1
            app_console.emit('log', f'From the phone: skipped a {str(op)[:20]} change the PC could not read',
                             level='warning', error=e)
    if wrote_notes:
        try:
            db.reindex_notes()
        except Exception as e:             # the notes are written; the next reindex picks them up
            if batch and batch.fatal(e):
                raise
            app_console.emit('log', 'From the phone: notes not reindexed', level='warning', error=e)
    last = _int(doc.get('at')) or last          # the file's time covers every change in it
    if last:
        out.applied[device] = max(_int(out.applied.get(device)), last)
    return out


_CANVAS_REASONS = {
    'reused': 'The canvas operation ID was reused with different content.',
    'name_taken': 'A canvas with that name already exists on the PC.',
    'missing_canvas': 'The target canvas is missing on the PC.',
    'target': 'The canvas ID is already in use on the PC.',
    'missing_element': 'A referenced canvas element is missing on the PC.',
    'no_thumbnail': 'A referenced thumbnail is unavailable on the PC.',
    'missing_item': 'A referenced item is missing on the PC.',
    'overlap': 'The proposed positions overlap on the PC.',
    'no_frame': 'Raw frames are unavailable from a phone proposal.',
    'text': 'The canvas change has text the PC cannot store.',
}


def _before(db, path) -> None:
    """A library file a change is about to write or remove: a batch (server/delivery.py) keeps it until its commit."""
    batch = getattr(db.conn, 'batch', None)
    if batch is not None:
        batch.before(path)


def _created(db, path) -> None:
    """A library file a change has just made: a batch removes it if the file does not commit."""
    batch = getattr(db.conn, 'batch', None)
    if batch is not None:
        batch.created(path)


def _made(db, make) -> Path:
    """make() writes a new note and returns its path. The note is listed for undo (a batch removes it if the change file
    does not commit), also when make() fails after it made the file (a disk error while it writes, a database error while
    it reindexes), so the next look does not leave a second copy beside it."""
    if getattr(db.conn, 'batch', None) is None:
        return make()
    folder = Path(db.notes_dir)
    had = {p.name for p in folder.glob('*.md')}
    try:
        path = make()
    except BaseException:
        for p in folder.glob('*.md'):
            if p.name not in had:
                _created(db, p)
        raise
    _created(db, path)
    return path


def _readable(b64: str) -> None:
    """A thumbnail from the phone that Pillow cannot read (not base64, not a picture, cut short) is wrong in itself:
    ValueError, so only its change is skipped. A disk error while it is saved stays this PC's (delivery.fatal)."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(base64.b64decode(b64))) as img:
            img.load()
    except (OSError, ValueError, SyntaxError) as e:
        raise ValueError(f'unreadable thumbnail: {e}') from None


def _canvas_reason(error: Exception) -> str:
    """Receipts carry a useful refusal without copying canvas names or note text to the mirror. The
    reason comes from the error's code (canvas_plan.ProposalError, _canvas below), never its text."""
    return _CANVAS_REASONS.get(getattr(error, 'code', ''), 'The PC could not apply this canvas change.')


def _digest(ch: dict) -> str:
    """The receipt hash: sha256 of mirror._json(ch), the bytes the phone hashes (web/src/mobile/ai/canvas.ts
    canonJson). A lone surrogate is written as the \\uXXXX escape JSON.stringify gives it, so the hash
    never raises and still matches the phone's."""
    text = json.dumps(ch, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(_LONE.sub(lambda m: '\\u%04x' % ord(m.group()), text).encode('utf-8')).hexdigest()


def _canvas(db, ch: dict, alias: dict, out: Applied) -> None:
    """Resolve one approved phone intent on the Writer; the canvas snapshot is its commit."""
    keys = {'op', 'op_id', 'canvas_id', 'at', 'proposal', 'refs', 'sizes'}
    if set(ch) != keys or ch.get('op') != 'canvas':
        raise ValueError('Canvas change has unexpected fields.')
    op_id, cid, at = ch['op_id'], ch['canvas_id'], ch['at']
    if not isinstance(op_id, str) or not _UID.fullmatch(op_id):
        raise ValueError('Invalid canvas operation ID.')
    if not isinstance(cid, str) or not canvas_plan.CID.fullmatch(cid) or cid == 'index':
        raise ValueError('Invalid canvas ID.')
    if type(at) is not int or not 0 <= at <= 2 ** 53 - 1:
        raise ValueError('Invalid canvas change time.')
    raw, refs, sizes = ch['proposal'], ch['refs'], ch['sizes']
    if not isinstance(raw, dict) or not isinstance(refs, dict) or not isinstance(sizes, dict):
        raise ValueError('Invalid canvas change contents.')
    p = canvas_plan.normalize(raw)
    if any(abs(e[k]) > 2 ** 53 - 1 for e in p['elements'] for k in ('item_id', 'order') if k in e):
        raise ValueError('Canvas item IDs and order must be safe JSON integers.')
    if p['canvas_id'] != (cid if p['canvas_id'] else None) or (not p['canvas_id'] and not _UID.fullmatch(cid)):
        raise ValueError('Canvas target does not match the approved operation.')
    if any(e['kind'] == 'frame' for e in p['elements']):
        raise canvas_plan.ProposalError('Extracted frames are unavailable in the phone library.', 'no_frame')
    if _LONE.search(json.dumps(ch, ensure_ascii=False)):
        raise canvas_plan.ProposalError('Canvas change has a lone surrogate in its text.', 'text')
    used = {str(e['item_id']) for e in p['elements'] if e['kind'] == 'thumbnail'}
    if set(refs) != used or set(sizes) != set(refs.values()) or len(refs) > 60:
        raise ValueError('Canvas item references are incomplete or contain extras.')
    for uid in refs.values():
        if not isinstance(uid, str) or not _UID.fullmatch(uid):
            raise ValueError('Invalid canvas item UID.')
    for dims in sizes.values():
        if (not isinstance(dims, list) or len(dims) != 2 or
                any(type(v) is not int or not 0 < v <= 100000 for v in dims)):
            raise ValueError('Invalid canvas image dimensions.')
    digest = _digest(ch)
    old = canvas_plan.load(db.data_dir / 'canvases', cid)
    marker = (old or {}).get('phone_ops') or {}
    if isinstance(marker, dict) and op_id in marker:
        if marker[op_id] != digest:
            raise canvas_plan.ProposalError('Canvas operation ID was reused with different content.', 'reused')
        out.canvas_results[op_id] = {'canvas_id': cid, 'state': 'applied', 'reason': '', 'hash': digest}
        return
    gone = canvas_plan.deleted_ops(db).get(op_id)
    if gone:                               # applied before, then Fred deleted the canvas: it stays deleted
        if gone != [cid, digest]:
            raise canvas_plan.ProposalError('Canvas operation ID was reused with different content.', 'reused')
        out.canvas_results[op_id] = {'canvas_id': cid, 'state': 'applied', 'reason': '', 'hash': digest}
        return
    mapped = json.loads(json.dumps(raw))
    for e in mapped['elements']:
        if e['kind'] != 'thumbnail':
            continue
        uid = alias.get(refs[str(e['item_id'])], refs[str(e['item_id'])])
        row = db.conn.execute('SELECT id FROM items WHERE uid = ?', (uid,)).fetchone()
        if not row:
            raise canvas_plan.ProposalError('A referenced item is no longer on the PC.', 'missing_item')
        e['item_id'] = row[0]
    store = CanvasStore(db.data_dir)
    _before(db, store.canvas_dir / f'{cid}.json')
    result = canvas_plan.apply(db, store, canvas_plan.normalize(mapped),
                               phone={'op_id': op_id, 'canvas_id': cid, 'at': at, 'hash': digest})
    out.canvas_results[op_id] = {'canvas_id': cid, 'state': 'applied', 'reason': '', 'hash': digest}
    if cid not in out.canvases:
        out.canvases.append(cid)


def _link(db, ch: dict, at: int, alias: dict, out: Applied) -> None:
    url = inbox.link(str(ch.get('url') or ''))
    uid = str(ch.get('uid') or '')
    if not http_url(url):
        return
    row = db.get_item_by_url(url)
    if row:
        out.dups += 1
        if uid:
            alias[uid] = row['uid']
        return
    phone_uid = uid
    if not _UID.match(uid) or db.conn.execute('SELECT 1 FROM items WHERE uid = ?', (uid,)).fetchone():
        uid = ''                          # add_item makes a fresh one
    data = {'url': url, 'description': url, 'source': 'phone', 'uid': uid, 'created': at or None}
    if ch.get('category'):
        data['category'] = str(ch['category'])[:80]
    if ch.get('tags'):
        data['tags'] = str(ch['tags'])[:1000]
    new_id = db.add_item(data)
    if phone_uid and not uid:
        alias[phone_uid] = db.conn.execute('SELECT uid FROM items WHERE id = ?', (new_id,)).fetchone()[0]
    note = str(ch.get('note') or '').strip()
    if note:
        db.update_item(new_id, {'notes': note})
    out.links += 1
    out.new_ids.append(new_id)
    out.item_ids.append(new_id)


def _details(db, ch: dict, alias: dict, out: Applied) -> None:
    """What the phone read from a saved link's page (projects/mobile-app/plans/09-link-details.md). Fills
    only what is still empty, so the PC's own thumbnail job and the user's edits always win."""
    uid = alias.get(str(ch.get('uid') or ''), str(ch.get('uid') or ''))
    row = db.conn.execute('SELECT id, url, description, short_desc, creator, thumb_path FROM items WHERE uid = ?',
                          (uid,)).fetchone() if uid else None
    if not row:
        return
    item_id, url, desc, short, creator, thumb = tuple(row)
    f = {}
    text = str(ch.get('desc') or '').strip()[:5000]
    title = str(ch.get('title') or '').strip()[:300]
    who = str(ch.get('creator') or '').strip()[:120]
    if text and (desc or '') in ('', url):
        f['description'] = text
    if title and not short:
        f['short_desc'] = title
    if who and not creator:
        f['creator'] = who
    if f:
        db.update_item(item_id, f)
    b64 = str(ch.get('thumb') or '')
    if b64 and not thumb:
        _readable(b64)
        _before(db, db.item_dir(item_id) / 'thumb.jpg')
        _save_thumb(db, item_id, b64)
        db.update_item(item_id, {'thumb_source': 'phone'})
    if f or (b64 and not thumb):
        out.item_ids.append(item_id)


def _edit(db, ch: dict, at: int, alias: dict, out: Applied) -> None:
    uid = alias.get(str(ch.get('uid') or ''), str(ch.get('uid') or ''))
    row = db.conn.execute('SELECT id, tags, category, notes, ai_desc, favourite, modified FROM items WHERE uid = ?',
                          (uid,)).fetchone()
    if not row:
        return
    if ch.get('op') == 'fav':
        fields, was = {'favourite': bool(ch.get('on'))}, {'favourite': not ch.get('on')}
    else:
        fields = ch.get('fields')
        fields = {k: str(v) for k, v in fields.items() if k in EDITABLE and v is not None} if isinstance(fields, dict) else {}
        was = ch.get('was') if isinstance(ch.get('was'), dict) else {}
    cur = {'tags': row['tags'] or '', 'category': row['category'] or '', 'notes': row['notes'] or '',
           'ai_desc': row['ai_desc'] or '',
           'favourite': bool(row['favourite'])}
    pc_newer = (row['modified'] or 0) > at - SKEW
    put = {}
    for k, v in fields.items():
        if cur[k] == v:
            continue
        if k in was and cur[k] != (bool(was[k]) if k == 'favourite' else str(was[k])) and pc_newer:
            out.kept_pc += 1
            continue
        put[k] = v
    if not put:
        return
    db.update_item(row['id'], put)
    if 'favourite' in put:
        out.favs += 1
    else:
        out.edits += 1
    if row['id'] not in out.item_ids:
        out.item_ids.append(row['id'])


def _category_batch(db, ch: dict, alias: dict, out: Applied) -> None:
    """Validate the whole phone proposal before one transaction changes any category."""
    entries = ch.get('entries')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError('bad category batch size')
    names = {c['name'] for c in db.get_categories()}
    seen, put = set(), []
    for e in entries:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ('uid', 'from', 'category')):
            raise ValueError('bad category batch entry')
        uid = alias.get(e['uid'], e['uid'])
        if uid in seen or e['category'] not in names:
            raise ValueError('duplicate item or unknown category')
        seen.add(uid)
        row = db.conn.execute('SELECT id, category FROM items WHERE uid = ?', (uid,)).fetchone()
        if not row or (row['category'] or '') != e['from']:
            raise ValueError('an item changed since the phone proposal')
        put.append((e['category'], row['id']))
    now = int(time.time() * 1000)
    db.conn.executemany('UPDATE items SET category = ?, modified = ? WHERE id = ?', [(cat, now, id) for cat, id in put])
    db.conn.commit()
    out.edits += len(put)
    out.item_ids.extend(id for _, id in put if id not in out.item_ids)


def _note(db, ch: dict, at: int, out: Applied) -> bool:
    notes_dir = Path(db.notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    title = str(ch.get('title') or '').strip() or 'Phone note'
    category = str(ch.get('category') or '').strip()
    body = str(ch.get('body') or '')
    stamps = ch.get('stamps') if isinstance(ch.get('stamps'), list) else None   # absent: kept
    file = str(ch.get('file') or '')
    path = notes_dir / file if _NOTE_FILE.match(file) else None
    if path is not None and path.exists():
        meta, _ = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
        pc_edit = meta.get('updated') or meta.get('created') or ''
        mine = meta.get('kind') == 'personal'
        if mine and (pc_edit == str(ch.get('was') or '') or _ts(pc_edit) <= at - SKEW):
            _before(db, path)
            my_notes.save_note(path, title, category or meta.get('category') or '', body, stamps)
            out.notes.append(path.name)
            return True
        path = None                        # the PC's note is newer (or not a My Note): keep both
        title = f'{title} (from phone)'
        out.kept_pc += 1
    if path is None:
        path = _made(db, lambda: my_notes.create_note(notes_dir, title, category))
    _before(db, path)                      # a phone file name new on this PC (one made here is listed already)
    my_notes.save_note(path, title, category, body, stamps)
    out.notes.append(path.name)
    return True


_WHEN = re.compile(r'^\d{4}-\d\d-\d\d \d\d:\d\d$')


def _note_append(db, ch: dict, out: Applied) -> bool:
    """A section added at the end of a My Note (Add to Brainamon on the phone). Only the new text travels,
    so what the PC wrote into the note since the phone read it stays. A note that is gone on the PC (or is
    not a My Note) does not lose the text: it lands in a new "<title> (from phone)" note in Inbox."""
    text = str(ch.get('text') or '').strip()[:filing.MAX_TEXT]
    if not text:
        return False
    name = str(ch.get('name') or '').strip()[:80] or 'Phone'
    when = str(ch.get('when') or '')
    if not _WHEN.match(when):
        when = datetime.now().strftime('%Y-%m-%d %H:%M')
    head = filing.heading('append', name, when)
    notes_dir = Path(db.notes_dir)
    file = str(ch.get('file') or '')
    path = notes_dir / file if _NOTE_FILE.match(file) else None
    if path is not None and path.exists() and knowledge.split_frontmatter(path.read_text(encoding='utf-8'))[0].get('kind') == 'personal':
        _before(db, path)
        filing.add_section(path, head, text)
    else:
        notes_dir.mkdir(parents=True, exist_ok=True)
        title = (str(ch.get('title') or '').strip()[:70] or 'Phone note') + ' (from phone)'
        path = _made(db, lambda: my_notes.create_note(notes_dir, title, filing.CATEGORY))
        my_notes.save_note(path, title, filing.CATEGORY, f'{head}\n\n{text}\n')
        out.kept_pc += 1
    out.notes.append(path.name)
    return True


def _note_category(db, ch: dict, out: Applied) -> bool:
    """A My Notes category renamed on the phone: only the two names travel (knowledge/my_notes.py
    rename_category). A refused name raises, so apply() skips and counts it."""
    old, new = ch.get('from'), ch.get('to')
    if not isinstance(old, str) or not isinstance(new, str):
        raise ValueError('bad note category rename')
    paths = my_notes.rename_category(db, db.notes_dir, old, new, before=lambda p: _before(db, p))
    out.notes.extend(p.name for p in paths)
    return bool(paths)


def _note_delete(db, ch: dict, out: Applied) -> bool:
    file = str(ch.get('file') or '')
    path = Path(db.notes_dir) / file if _NOTE_FILE.match(file) else None
    if path is None or not path.exists():
        return False
    meta, _ = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
    if meta.get('kind') != 'personal':
        return False                     # only personal notes are deleted from the phone
    _before(db, path)
    knowledge.delete_note(path)
    out.notes.append(path.name)
    return True


def _ids(v) -> list:
    out = []
    for i in v if isinstance(v, list) else []:
        try:
            out.append(int(i))
        except (TypeError, ValueError, OverflowError):
            continue
    return out


def _chat(db, ch: dict, at: int, out: Applied) -> None:
    store = AskChatStore(db.data_dir)
    name = str(ch.get('name') or '').strip()[:80] or 'Phone chat'
    slug = str(ch.get('slug') or '')
    if not _SLUG.match(slug):
        slug = store._unique_slug(name)
    data = {'name': name, 'created': str(ch.get('created') or ''), 'history': ch.get('history') or [],
            'source_ids': _ids(ch.get('source_ids')), 'options': ch.get('options') or {}}
    cur = store.load(slug)
    if cur is not None and cur['updated'] != str(ch.get('was') or '') and _ts(cur['updated']) > at - SKEW:
        data['name'] = f'{name} (from phone)'          # the PC went on with this chat too: keep both
        slug = store._unique_slug(data['name'])
        out.kept_pc += 1
    _before(db, store._path(slug))
    store.save(slug, data)
    out.chats.append(slug)


def _chat_delete(db, ch: dict, out: Applied) -> None:
    slug = str(ch.get('slug') or '')
    store = AskChatStore(db.data_dir)
    cur = store.load(slug) if _SLUG.match(slug) else None
    if cur is None:
        return
    if len(cur['history']) > _int(ch.get('turns')):
        out.kept_pc += 1                                # the PC went on with this chat: it stays
        return
    _before(db, store._path(slug))
    store.delete(slug)
    if slug in out.chats:
        out.chats.remove(slug)
    out.deleted_chats.append(slug)


def _delete(db, ch: dict, alias: dict, out: Applied) -> None:
    if ch.get('pc') is not True:                        # "only on this phone": the PC keeps it
        return
    uid = alias.get(str(ch.get('uid') or ''), str(ch.get('uid') or ''))
    row = db.conn.execute('SELECT id FROM items WHERE uid = ?', (uid,)).fetchone() if uid else None
    if not row:
        return
    batch = getattr(db.conn, 'batch', None)
    db.delete_items_bulk([row['id']], folders=batch is None)    # a batch removes the folder after its commit
    if batch is not None:
        batch.folder(row['id'])
    out.deleted += 1
    if row['id'] not in out.item_ids:
        out.item_ids.append(row['id'])
    if row['id'] in out.new_ids:
        out.new_ids.remove(row['id'])


def _new_note(db, ch: dict, out: Applied) -> bool:
    body = str((ch.get('md') if ch.get('op') == 'answer' else ch.get('body')) or '').strip()
    if not body:
        return False
    if ch.get('op') == 'answer':
        path = _made(db, lambda: ask_core.save_note(db, body, _ids(ch.get('ids'))))
    else:
        topic = str(ch.get('topic') or '').strip()[:120] or 'Phone note'
        path = _made(db, lambda: knowledge.save_new_note(db.notes_dir, topic, _source_ids(db, ch, out.alias), body)[0])
    out.notes.append(path.name)
    return True


def _source_ids(db, ch: dict, alias: dict) -> list:
    """The PC ids a phone synthesis cites (projects/phone-solo-synthesize). For each entry of
    `sources`: its `uids` entry when the phone sent one (a link saved on the phone: the alias first,
    then items.uid, as the link op left it; a uid the library does not hold cites nothing), else the
    id itself when positive. A negative id with no uid (an older phone) cites nothing."""
    sources = ch.get('sources') if isinstance(ch.get('sources'), list) else []
    uids = ch.get('uids') if isinstance(ch.get('uids'), list) else []
    out = []
    for n, raw in enumerate(sources):
        try:
            sid = int(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        uid = uids[n] if n < len(uids) and isinstance(uids[n], str) else ''
        if uid:
            uid = alias.get(uid, uid)
            row = db.conn.execute('SELECT id FROM items WHERE uid = ?', (uid,)).fetchone()
            if row:
                out.append(row[0])
        elif sid > 0:
            out.append(sid)
    return out


def _queue(db, ch: dict, out: Applied) -> None:
    ids, topic = _ids(ch.get('ids')), str(ch.get('topic') or '').strip()[:120]
    if not ids or not topic:
        return
    try:
        q = json.loads(db.get_setting(SYNTH_QUEUE, '') or '[]')
    except ValueError:
        q = []
    q = (q if isinstance(q, list) else []) + [{'topic': topic, 'ids': ids}]
    db.set_setting(SYNTH_QUEUE, json.dumps(q))
    out.queued += 1
