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
# Sources folded per call. Each excerpt is capped at EXCERPT_LIMIT, so a batch stays well under
# the context window while leaving room for the growing note that is fed back in each pass.
BATCH_SIZE = P['limits']['batch_size']
EXCERPT_LIMIT = P['limits']['excerpt_limit']
MAX_TOKENS = P['limits']['max_tokens']
PHONE_MAX_SOURCES = P['limits']['phone_max_sources']   # the phone folds at most this many (3 calls)


def excerpt(source: dict, limit: int = EXCERPT_LIMIT) -> str:
    """Best available text for a source, capped. Mirrors the item schema column priority
    (ai_desc is the AI analysis, then transcript, then the raw description)."""
    text = (source.get('ai_desc') or source.get('transcript')
            or source.get('description') or source.get('short_desc') or '')
    return text[:limit]


def title(source: dict) -> str:
    return (source.get('short_desc') or source.get('description')
            or source.get('creator') or '').strip().split('\n')[0][:120]


def source_block(s: dict) -> str:
    text = excerpt(s)
    if not text:
        return ''
    creator = (s.get('creator') or '').strip()
    meta = []
    if creator:
        meta.append(fill(P['creator'], creator=creator))
    if s.get('url'):
        meta.append(fill(P['url'], url=s['url']))
    meta_line = ("\n".join(meta) + "\n") if meta else ""
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
    """The usable sources (with some text) in batches of BATCH_SIZE."""
    usable = [s for s in sources if excerpt(s)]
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
