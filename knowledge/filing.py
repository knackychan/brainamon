"""Filing: what Wiskit does with a dropped, attached or pasted file (projects/wiskit-files). Qt-free.

Nothing here opens SQLite. The caller passes a reader for the candidate notes, makes the AI calls on a
thread of its own, and runs file_text() on the server's Writer (it writes data/notes/ and reindexes).

Actions, one per choice the UI shows:
  new     a new personal note (My Notes > Inbox) holding the text
  append  the text added under a dated heading to an existing note (personal or wiki)
  extend  a section an AI writes to fold the text into an existing note (ai_defaults.SYNTHESIZE)
suggest() is one cheap-model call that picks the best note and a title; when it fails the choices
fall back to the best keyword match, so the user can always file. Topic digest notes are never
targets: Refresh digest rewrites them.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from core import ai_client
from core.db import fts_terms
from knowledge import knowledge
from knowledge import my_notes
from knowledge.prompt_files import fill

ACTIONS = ('new', 'append', 'extend')
CATEGORY = 'Inbox'            # My Notes category of a note made from a file
CANDIDATES = 6                # notes the suggestion call chooses from
EXCERPT = 600                 # characters of each candidate shown to the model
TEXT_FOR_AI = 6000            # characters of the file shown to the suggestion call
EXTEND_TEXT = 20000           # characters of the file and of the note shown to the extend call
MAX_TEXT = 200_000            # characters filed into a note at most

SUGGEST_SYSTEM = ('You file documents into a personal knowledge base. Answer with one JSON object and '
                  'nothing else.')
SUGGEST_PROMPT = (
    'A file was dropped on the assistant: "{name}".\n\nIts text (may be cut):\n"""\n{text}\n"""\n\n'
    'Notes it could be added to, as [file] title (kind) then an excerpt:\n\n{notes}\n\n'
    'Answer with JSON: {"best": "<the file name in brackets of the note this belongs in, or an empty '
    'string when none fits well>", "why": "<one short sentence>", "title": "<a short title for a new '
    'note about this file, at most 8 words>"}'
)
EXTEND_PROMPT = (
    'Here is a note titled "{title}":\n"""\n{note}\n"""\n\nNew material from "{name}":\n"""\n{text}\n"""\n\n'
    'Write the section to add at the end of the note so it absorbs the new material: what the material '
    'adds, corrects or confirms, in the note\'s own style. Markdown, short bullets where they fit, no '
    'heading line (one is added), no preamble. Do not repeat what the note already says. Do not invent '
    'anything that is not in the material.'
)


def plain_title(name: str) -> str:
    """A readable title from a file name: the data/inbox date prefix and the extension dropped."""
    stem = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', Path(name or '').stem)
    return re.sub(r'[-_]+', ' ', stem).strip()[:80] or 'From a file'


def query_of(name: str, text: str) -> str:
    """Keywords for the candidate notes: the file name's words, then the text's first content words."""
    return ' '.join(fts_terms(plain_title(name) + ' ' + (text or '')[:4000])[:30])


def candidates(rd, notes_dir, name: str, text: str, topic_files: set) -> list:
    """Up to CANDIDATES notes worth adding this file to, keyword-ranked (db.search_notes), topic
    digests left out. [{'file', 'title', 'kind', 'excerpt'}]"""
    out = []
    for n in rd.search_notes(query_of(name, text), CANDIDATES * 2):
        if n['filename'] in topic_files:
            continue
        p = knowledge.safe_note_path(notes_dir, n['filename'])
        if p is None:
            continue
        meta, _body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        out.append({'file': p.name, 'title': n['topic'] or p.stem,
                    'kind': 'Personal' if meta.get('kind') == 'personal' else 'Synthesized',
                    'excerpt': ' '.join((n.get('body') or '').split())[:EXCERPT]})
        if len(out) == CANDIDATES:
            break
    return out


def suggest(name: str, text: str, cands: list, provider: str, model: str) -> dict:
    """{'title', 'best', 'why', 'ai'}: the model's pick among `cands` (best is a file name, or '').
    Any failure (no key, no JSON, a file not offered) falls back to the top keyword match."""
    fallback = {'title': plain_title(name), 'best': cands[0]['file'] if cands else '',
                'why': 'Shares the most words with this file.' if cands else '', 'ai': False}
    listing = '\n\n'.join(f"[{c['file']}] {c['title']} ({c['kind']})\n{c['excerpt']}" for c in cands) or '(no notes match)'
    prompt = fill(SUGGEST_PROMPT, name=name, text=(text or '')[:TEXT_FOR_AI], notes=listing)
    try:
        raw = ai_client.complete_text(provider, model, prompt=prompt, system=SUGGEST_SYSTEM, max_tokens=400)
        d = json.loads(re.search(r'\{.*\}', raw, re.S).group(0))
        best = str(d.get('best') or '').strip().strip('[]')
    except Exception:
        return fallback
    files = {c['file'] for c in cands}
    return {'title': str(d.get('title') or '').strip()[:80] or fallback['title'],
            'best': best if best in files else '',
            'why': str(d.get('why') or '').strip()[:200], 'ai': True}


def options(sug: dict, cands: list) -> list:
    """The choices the UI shows, best first (at most 6):
    [{'action', 'file', 'title', 'label', 'why', 'best'}]. Exactly one has best=True."""
    by = {c['file']: c for c in cands}
    out = []
    if sug['best'] in by:
        c = by[sug['best']]
        out.append({'action': 'append', 'file': c['file'], 'title': c['title'], 'label': f'Add to "{c["title"]}"',
                    'why': sug['why'] or 'The closest note.', 'best': True})
        out.append({'action': 'extend', 'file': c['file'], 'title': c['title'], 'label': f'Extend "{c["title"]}" with it',
                    'why': 'Wiskit writes what this adds to the note.', 'best': False})
    out.append({'action': 'new', 'file': '', 'title': sug['title'], 'label': f'New note "{sug["title"]}"',
                'why': 'Starts a note in My Notes > Inbox.', 'best': not out})
    for c in cands:
        if c['file'] != sug['best']:
            out.append({'action': 'append', 'file': c['file'], 'title': c['title'], 'label': f'Add to "{c["title"]}"',
                        'why': f'{c["kind"]} note', 'best': False})
    return out[:6]


def extend_section(title: str, note_body: str, name: str, text: str, provider: str, model: str) -> str:
    """The section that folds `text` into the note (one AI call). Raises when the call fails."""
    md = ai_client.complete_text(provider, model, max_tokens=1500, prompt=fill(
        EXTEND_PROMPT, title=title, note=(note_body or '').strip()[:EXTEND_TEXT], name=name, text=(text or '')[:EXTEND_TEXT]))
    if not md.strip():
        raise ValueError('The AI sent back an empty section.')
    return md.strip()


def heading(action: str, name: str, when: str) -> str:
    return f"## {'Extended from' if action == 'extend' else 'From'} {name} - {when}"


def add_section(path: Path, head: str, text: str) -> None:
    """Append a section to any note in data/notes, keeping its frontmatter (kind, sources, category...)
    and bumping `updated`."""
    meta, body = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
    meta['updated'] = datetime.now().isoformat(timespec='seconds')
    knowledge.write_front(path, meta, body.rstrip() + f'\n\n{head}\n\n{text.strip()}\n')


def file_text(db, action: str, name: str, text: str, file: str = '', title: str = '') -> Path:
    """Write `text` into data/notes (a new personal note, or a section of `file`). Runs on the
    Writer. Raises ValueError (bad action, no text) or LookupError (the note is gone). Returns the path."""
    text = (text or '').strip()[:MAX_TEXT]
    if not text:
        raise ValueError('Nothing to file.')
    when = datetime.now().strftime('%Y-%m-%d %H:%M')
    if action == 'new':
        p = my_notes.create_note(db.notes_dir, (title or plain_title(name)).strip()[:80], CATEGORY)
        meta, _body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        my_notes.save_note(p, meta['topic'], meta['category'], f'{heading(action, name, when)}\n\n{text}\n')
    elif action in ('append', 'extend'):
        p = knowledge.safe_note_path(db.notes_dir, file)
        if p is None:
            raise LookupError('That note is gone.')
        add_section(p, heading(action, name, when), text)
    else:
        raise ValueError(f'Unknown filing action: {action}')
    db.reindex_notes()
    return p
