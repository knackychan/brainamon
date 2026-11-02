"""Export to Obsidian, Qt-free steps (the V6 `export_obsidian` job and the `refresh_map` job).

The classic export chain: an embedding-coverage check, then obsidian_export.build_obsidian_payload with
the stored tag map and the summarized topics of the knowledge map (library/map_engine.py), then
write_obsidian_vault. The paid parts (normalize_tags, synthesize_topic) run only from Refresh map
(server/job_kinds.py `refresh_map`); they take plain data and no `db`. Functions that take `db` run where
SQLite access is allowed (the Writer).
"""
import json
import re
from collections import Counter

from core import ai_client

TAG_MAP_KEY = 'obsidian_tag_map'
TAG_CHUNK = 300            # raw tags per call; a vocabulary of 1-2k tags is a handful of calls
MAX_MEMBERS_PER_PROMPT = 40
EXCERPT_CHARS = 400

TAG_PROMPT = """You are cleaning the tag vocabulary of a personal content library
(social-media saves about sport/kettlebell, AI tools, SEO/GEO, cooking, 3D/design,
etc.). Below is a list of raw tags with usage counts.

Return a JSON object mapping EVERY raw tag to either:
- a canonical topic name (lowercase, singular concept, merge synonyms and umbrella
  duplicates: "kick" and "martial arts" both -> "martial arts"), or
- null if the tag is generic filler that describes format rather than subject
  (e.g. "visual moments", "short form content", "tutorial style", "time lapse or").

Rules:
- Output ONLY the JSON object, no prose, no code fences.
- Every input tag must appear exactly once as a key, spelled exactly as given.
- Prefer merging into an existing frequent tag's name over inventing new wording.
- Keep genuinely specific tags as themselves (e.g. "kettlebell" -> "kettlebell").

Tags (tag: count):
{tag_block}
"""

TOPIC_PROMPT = """These are excerpts from {n} saved social-media items that an
embedding model grouped together as one topic. They come from one person's library
(interests include sport/kettlebell, AI tools, SEO/GEO, cooking, 3D/design).

First line of your answer: "TITLE: <a specific 2-5 word topic name>".
Then a blank line, then 150-300 words of markdown synthesizing the cluster:
- the common theme and the 2-4 sub-threads inside it
- non-obvious correlations between items worth exploring
- 2-3 concrete takeaways or next actions

Do not list the items one by one; synthesize across them. No code fences.

Excerpts:
{excerpts}
"""


# ── the tag map ──────────────────────────────────────────────────────────────
def stored_tag_map(db) -> dict:
    try:
        v = json.loads(db.get_setting(TAG_MAP_KEY, '') or '{}')
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def unmapped_tags(rows, stored: dict) -> list:
    """[(raw_tag, count)] of the library's tags not in the stored map, most used first."""
    counts = Counter()
    for r in rows:
        for t in (r.get('tags') or '').split(','):
            key = t.strip().lower()
            if key:
                counts[key] += 1
    return [(t, c) for t, c in counts.most_common() if t not in stored]


def parse_tag_map(text: str, chunk) -> dict:
    """The model's JSON answer for one chunk -> {raw_tag: canonical or None}; tolerant of prose
    around the object; a missing or garbage value keeps the tag as itself."""
    m = re.search(r'\{.*\}', text or '', re.DOTALL)
    raw = json.loads(m.group(0)) if m else {}
    out = {}
    for tag, _count in chunk:
        key = tag.strip().lower()
        val = raw.get(tag, raw.get(key, ''))
        if val is None:
            out[key] = None
        elif isinstance(val, str) and val.strip():
            out[key] = val.strip().lower()
        else:
            out[key] = key
    return out


def normalize_tags(tag_counts, provider, model, log=None) -> dict:
    """Map every unmapped tag to a canonical topic (or None) with the Synthesize model."""
    chunks = [tag_counts[i:i + TAG_CHUNK] for i in range(0, len(tag_counts), TAG_CHUNK)]
    mapping = {}
    for n, chunk in enumerate(chunks, 1):
        if log:
            log(f'Normalizing tags, chunk {n} of {len(chunks)} ({len(chunk)} tags)')
        block = '\n'.join(f'{t}: {c}' for t, c in chunk)
        text = ai_client.complete_text(provider, model or ai_client.CLAUDE_MODEL,
                                       prompt=TAG_PROMPT.format(tag_block=block), max_tokens=4096)
        mapping.update(parse_tag_map(text, chunk))
    return mapping


# ── the topic summaries ──────────────────────────────────────────────────────
def excerpts_for(rows) -> list:
    """One excerpt per item row with usable text: the summary prompt's input (map_engine.summary_jobs)."""
    excerpts = []
    for it in rows:
        head = (it.get('short_desc') or (it.get('ai_desc') or '')[:80]).strip()
        body = (it.get('ai_desc') or it.get('description') or '').strip()
        tags = (it.get('tags') or '').strip()
        tr = (it.get('transcript') or '')[:300].strip()
        text = re.sub(r'\s+', ' ', f'{head}. {body} [tags: {tags}] {tr}')
        if text.strip('. '):
            excerpts.append(text)
    return excerpts


def split_title(text: str) -> tuple:
    lines = (text or '').strip().splitlines()
    if lines and lines[0].upper().startswith('TITLE:'):
        return lines[0].split(':', 1)[1].strip() or 'Untitled topic', '\n'.join(lines[1:]).strip()
    return (lines[0][:60] if lines else 'Untitled topic'), (text or '').strip()


def synthesize_topic(job: dict, provider, model) -> tuple:
    """One cluster -> (title, synthesis markdown)."""
    ex = job['excerpts'][:MAX_MEMBERS_PER_PROMPT]
    block = '\n'.join(f'- {e[:EXCERPT_CHARS]}' for e in ex)
    text = ai_client.complete_text(provider, model or ai_client.CLAUDE_MODEL,
                                   prompt=TOPIC_PROMPT.format(n=len(job['member_ids']), excerpts=block),
                                   max_tokens=1024)
    return split_title(text)


# ── the export inputs ────────────────────────────────────────────────────────
def export_inputs(db, cache_path) -> tuple:
    """(tag_map or None, ai_topics or None) for build_obsidian_payload: the topics of the v2 cache that
    have a summary (library/map_engine.py), in the {'key', 'title', 'synthesis', 'member_ids'} shape."""
    from library import map_engine
    tag_map = stored_tag_map(db) or None
    cache = map_engine.load(cache_path)
    topics = [{'key': k, 'title': v['title'], 'synthesis': v['synthesis'], 'member_ids': v['member_ids']}
              for k, v in cache['clusters'].items() if v.get('synthesis')] or None
    return tag_map, topics
