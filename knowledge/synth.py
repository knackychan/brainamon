"""
synth.py - Qt-free synthesis of saved sources into one markdown note, shared by the Qt Knowledge
tab (ui/synthesize_worker.py) and the V6 server "note" job. Moved from ui/synthesize_worker.py.

Sources are folded into the note in rolling batches: each batch is merged into the document built
so far (`fold`). Two merge modes, "reorganize" and "append", control how much a batch rewrites.
`write_note` saves the result as data/notes/<slug>.md with the brain.py frontmatter.
"""
import re
from datetime import datetime
from pathlib import Path

from core import ai_client
from knowledge import prompt_files
from knowledge.prompt_files import fill

# Prompt texts and limits live in knowledge/prompts/synth.json, shared with the phone
# (web/src/mobile/ai/synth.ts): change them there.
P = prompt_files.load('synth')
# Sources folded per call. One source's parts together are capped at EXCERPT_LIMIT (each part at its own
# cap, the report and the transcript trimmed first), so a batch stays well under the context window
# while leaving room for the growing note that is fed back in each pass.
BATCH_SIZE = P['limits']['batch_size']
EXCERPT_LIMIT = P['limits']['excerpt_limit']
TITLE_LIMIT = P['limits']['title_limit']
MAX_TOKENS = P['limits']['max_tokens']
PHONE_MAX_SOURCES = P['limits']['phone_max_sources']   # the phone folds at most this many (3 calls)
PART_LIMITS = P['limits']['parts']                     # characters of each labelled part
PART_ORDER = P['part_order']                           # report, ai_desc, transcript, description, notes
TRIM_ORDER = P['trim_order']                           # cut further, in this order, until the parts fit


def _text(source: dict, key: str) -> str:
    """One part's text, stripped. A description that is only the item's link (a link saved on the
    phone, or a bare link the PC made from it, before its page was read) is no text."""
    text = (source.get(key) or '').strip()
    link = (source.get('url') or '').strip()
    bare = lambda value: re.sub(r'^(?:https?://)?(?:www\.)?', '', value.lower()).rstrip('/')
    if text.upper() == 'NO_CONTENT' or (key == 'description' and link and bare(text) == bare(link)):
        return ''
    return text


def parts(source: dict, limit: int = EXCERPT_LIMIT) -> list:
    """The labelled parts of one source: [(key, text), ...] in PART_ORDER, each cut to its own cap,
    then the TRIM_ORDER parts cut further (each down to what fits, never below nothing) until all of
    them together fit in `limit`. Empty parts are left out. The phone builds the same list
    (web/src/mobile/ai/synth.ts parts)."""
    out = [[k, _text(source, k)[:PART_LIMITS[k]]] for k in PART_ORDER if _text(source, k)]
    over = sum(len(t) for _, t in out) - limit
    for key in TRIM_ORDER:
        for p in out:
            if over > 0 and p[0] == key:
                cut = min(over, len(p[1]))
                p[1] = p[1][:len(p[1]) - cut]
                over -= cut
    return [(k, t) for k, t in out if t]


def has_text(source: dict) -> bool:
    """Whether Synthesize can fold this source (at least one part). The title alone is not enough."""
    return bool(parts(source))


def excerpt(source: dict, limit: int = EXCERPT_LIMIT) -> str:
    """The one best text of a source, capped (knowledge/weekly_review.py). Synthesize itself folds
    every part (`parts`). Mirrors the item schema column priority (ai_desc is the AI analysis, then
    transcript, then the raw description)."""
    text = (source.get('ai_desc') or source.get('transcript')
            or source.get('description') or source.get('short_desc') or '')
    return text[:limit]


def title(source: dict) -> str:
    texts = (source.get('short_desc'), source.get('description'), source.get('creator'))
    return next((t.strip() for t in texts if t and t.strip().upper() != 'NO_CONTENT'), '').split('\n')[0][:TITLE_LIMIT]


def tags_line(source: dict) -> str:
    """The item's tags as one comma list (the PC's raw column and the mirror's field give the same)."""
    return ', '.join(t.strip() for t in (source.get('tags') or '').split(',') if t.strip())


def source_block(s: dict) -> str:
    texts = parts(s)
    if not texts:
        return ''
    creator = (s.get('creator') or '').strip()
    meta = []
    if creator:
        meta.append(fill(P['creator'], creator=creator))
    if s.get('url'):
        meta.append(fill(P['url'], url=s['url']))
    tags = tags_line(s)
    if tags:
        meta.append(fill(P['tags'], tags=tags))
    category = (s.get('category') or '').strip()
    if category:
        meta.append(fill(P['category'], category=category))
    meta_line = ("\n".join(meta) + "\n") if meta else ""
    text = "\n\n".join(fill(P['part'], label=P['labels'][k], text=t) for k, t in texts)
    return fill(P['source'], id=s['id'], title=title(s), meta=meta_line, text=text)


RULES = P['rules']


def clean(text: str) -> str:
    text = text.strip()
    # Defensively strip a wrapping ```markdown ... ``` fence if the model added one.
    if text.startswith('```'):
        first_nl = text.find('\n')
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.rstrip().endswith('```'):
            text = text.rstrip()[:-3]
    return text.strip()


def fold_prompt(topic: str, mode: str, existing_md: str, sources_text: str) -> str:
    if not existing_md.strip():
        return fill(P['first'], topic=topic, rules=RULES, sources=sources_text)
    return fill(P['append' if mode == 'append' else 'reorganize'], topic=topic, rules=RULES,
                note=existing_md, sources=sources_text)


def fold(provider: str, model: str, topic: str, existing_md: str, batch: list,
         mode: str = 'reorganize', log=None) -> str:
    """One merge pass: fold a batch of sources into the note so far. Returns the new note."""
    log = log or (lambda _m: None)
    blocks = [b for b in (source_block(s) for s in batch) if b]
    if not blocks:
        return existing_md
    sources_text = "\n\n".join(blocks)
    log(f"    sources: [{', '.join(str(s['id']) for s in batch)}]")
    prompt = fold_prompt(topic, mode if mode in ('reorganize', 'append') else 'reorganize', existing_md, sources_text)
    action = 'merging into note' if existing_md.strip() else 'first draft'
    log(f"    calling {model} ({action}, prompt {len(prompt):,} chars)…")
    text = ai_client.complete_text(provider, model, prompt=prompt, max_tokens=MAX_TOKENS)
    log(f"    model returned {len(text):,} chars")
    return clean(text) or existing_md


def batches(sources: list) -> list:
    """The usable sources (at least one part, `has_text`) in batches of BATCH_SIZE."""
    usable = [s for s in sources if has_text(s)]
    return [usable[i:i + BATCH_SIZE] for i in range(0, len(usable), BATCH_SIZE)]


def slugify(text: str) -> str:
    """Same rule as brain.py _slugify."""
    text = (text or '').strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text).strip('-')
    return text or 'untitled'


def write_note(notes_dir, topic: str, source_ids: list, body: str, created: str = None) -> Path:
    """data/notes/<slug>.md with the brain.py frontmatter (topic, created, sources). Never
    overwrites: a taken name gets -2, -3, ..."""
    notes_dir = Path(notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(topic)
    path = notes_dir / f"{slug}.md"
    n = 2
    while path.exists():
        path = notes_dir / f"{slug}-{n}.md"
        n += 1
    created = created or datetime.now().isoformat(timespec='seconds')
    ids = ','.join(str(i) for i in sorted(set(int(s) for s in source_ids)))
    front = f"---\ntopic: {topic}\ncreated: {created}\nsources: {ids}\n---\n\n"
    path.write_text(front + body.strip() + "\n", encoding='utf-8')
    return path
