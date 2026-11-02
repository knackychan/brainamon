"""
skills.py - skill-candidate proposer for Brainamon (step 1 of the skill pipeline).

Qt-free, network-free, lazy numpy (mirrors connections.py). Finds saved items and notes
that teach a *procedure* (steps, commands, a how-to) and groups the same technique shown
by several creators into one "merge" candidate. It only proposes: a later Claude gate
decides what becomes a skill, the same split as Connections (numpy proposes, Claude
disposes). Today the only caller is `py brain.py skills`, which prints the candidates so
the thresholds can be tuned on the real library before any UI is built.

All thresholds are module constants: if the list skews to vague "tips" reels, raise
_MIN_SCORE; if merges glue unrelated techniques together, raise _MERGE_FLOOR.
"""

import json
import re
from pathlib import Path

_MIN_SCORE = 0.30         # procedure score needed to be a candidate (0..1)
_MIN_TEXT = 200           # shorter combined text is too thin to judge; its score is halved
_TRANSCRIPT_CAP = 3000    # chars of transcript judged (long talks would saturate every count)
_MERGE_FLOOR = 0.66       # min cosine between a merge seed and each member
_MERGE_MIN_ITEMS = 3      # a merge needs at least this many items...
_MERGE_MIN_CREATORS = 2   # ...from at least this many different creators
_MERGE_PER_CREATOR = 2    # one creator's series counts at most twice in a merge
_MAX_MERGES = 8
_MAX_ITEMS = 15
_MAX_NOTES = 8

# ── procedure signals ─────────────────────────────────────────────────────────
# English and French, since the library is both.
_HOWTO_RE = re.compile(
    r"\b(how to|step[- ]by[- ]step|tutorial|tuto|walkthrough|guide|method|workflow|"
    r"set ?up|install(?:s|ed|ing|ation)?|comment faire|m[ée]thode|[ée]tapes?)\b", re.I)
_STEP_RE = re.compile(
    r"\b(step \d+|step (?:one|two|three|four|five)|\d+[- ]steps?|firstly|secondly|finally|"
    r"[ée]tape \d+|\d+ [ée]tapes|premi[eè]re [ée]tape|d'abord|ensuite|enfin)\b", re.I)
_NUMBERED_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S", re.M)
_COMMAND_RE = re.compile(
    r"`[^`\n]{2,80}`"                                                # inline code
    r"|\b(?:pip3?|npm|npx|pnpm|brew|winget|git|uv|docker|curl|ffmpeg|yt-dlp)\s+[a-z-]"
    r"|(?:^|\s)/[a-z][a-z0-9-]{2,}(?=\s|$)"                         # slash commands
    r"|(?:^|\s)--[a-z][a-z-]{2,}"                                    # cli flags
    r"|\b[\w-]+\.(?:md|py|json|ya?ml|js|ts|sh|bat)\b", re.I | re.M)
_IMPERATIVE_RE = re.compile(
    r"(?:^|[.!?:]\s+)(install|open|run|add|create|copy|paste|click|type|go to|select|"
    r"set|drag|export|import|ouvre|installe|lance|ajoute|cr[ée]e|copie|colle|clique|"
    r"tape|va sur|s[ée]lectionne)\b", re.I | re.M)
# "Comment GUIDE", "Commente « SKILL »", "commentez MOTION": the steps are behind a DM.
_GATED_RE = re.compile(r"\b[Cc]omment(?:e|ez)?\b\W{0,4}([A-Z][A-Z0-9]{1,15})\b")

# (regex, cap, weight): each signal's count is capped, then weighted; weights sum to 1.
_SIGNALS = (
    ('howto', _HOWTO_RE, 3, 0.30),
    ('steps', _STEP_RE, 6, 0.20),
    ('numbered', _NUMBERED_RE, 5, 0.15),
    ('commands', _COMMAND_RE, 4, 0.20),
    ('imperative', _IMPERATIVE_RE, 5, 0.15),
)


def item_text(item: dict) -> str:
    """The text a procedure is judged on: AI description, caption, transcript (capped)."""
    return '\n'.join([(item.get('ai_desc') or '').strip(),
                      (item.get('description') or '').strip(),
                      (item.get('transcript') or '').strip()[:_TRANSCRIPT_CAP]]).strip()


def procedure_signals(text: str, list_text: str = None) -> dict:
    """Raw signal counts, e.g. {'howto': 2, 'steps': 5, ...}. `list_text` (default: text)
    is what numbered/bulleted lines are counted in: for items that is the caption and the
    transcript only, because AI descriptions are themselves formatted as numbered lists."""
    text = text or ''
    out = {}
    for name, rx, _cap, _w in _SIGNALS:
        src = list_text if (name == 'numbered' and list_text is not None) else text
        out[name] = len(rx.findall(src or ''))
    return out


def procedure_score(text: str, signals: dict = None) -> float:
    """0..1: how much the text reads like a repeatable procedure."""
    signals = signals if signals is not None else procedure_signals(text)
    score = sum(min(signals[name], cap) / cap * w for name, _rx, cap, w in _SIGNALS)
    if len(text or '') < _MIN_TEXT:
        score *= 0.5
    return round(score, 3)


def gate_keyword(item: dict) -> str:
    """The DM keyword when the caption hides the steps behind "comment X", else ''."""
    m = _GATED_RE.search(item.get('description') or '')
    return m.group(1) if m else ''


def item_title(item: dict) -> str:
    t = (item.get('short_desc') or item.get('ai_desc') or item.get('description')
         or f"item {item.get('id')}")
    return re.sub(r'\s+', ' ', t).strip()[:90]


# ── what existing skills already cover ───────────────────────────────────────
_ID_REF_RE = re.compile(r'\[id (\d+)\]')
_NOTE_REF_RE = re.compile(r'([\w.-]+\.md)\b')


def skill_ledger(skills_dirs) -> tuple:
    """(covered_ids, covered_notes, names) from every `<dir>/<name>/SKILL.md` (and its
    optional meta.json `sources` / `notes`). Items and notes a skill already cites are
    not proposed again, the same idea as connections.load_note_ledger for notes."""
    covered_ids, covered_notes, names = set(), set(), set()
    for d in skills_dirs or ():
        d = Path(d)
        if not d.is_dir():
            continue
        for skill_md in d.glob('*/SKILL.md'):
            names.add(skill_md.parent.name)
            try:
                text = skill_md.read_text(encoding='utf-8')
            except Exception:
                continue
            covered_ids.update(int(i) for i in _ID_REF_RE.findall(text))
            covered_notes.update(n for n in _NOTE_REF_RE.findall(text) if n != 'SKILL.md')
            meta = skill_md.parent / 'meta.json'
            if meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding='utf-8'))
                    covered_ids.update(int(i) for i in data.get('sources', []))
                    covered_notes.update(data.get('notes', []))
                except Exception:
                    pass
    return covered_ids, covered_notes, names


# ── candidates ───────────────────────────────────────────────────────────────
def _creator(item: dict, item_id: int) -> str:
    """Normalized creator; an unknown creator counts as its own voice."""
    return (item.get('creator') or '').strip().lower() or f'#{item_id}'
def score_items(items) -> dict:
    """{id: {'score', 'signals', 'gated'}} for every item."""
    out = {}
    for item in items:
        text = item_text(item)
        sig = procedure_signals(text, list_text='\n'.join(
            [item.get('description') or '', (item.get('transcript') or '')[:_TRANSCRIPT_CAP]]))
        out[int(item['id'])] = {'score': procedure_score(text, sig), 'signals': sig,
                                'gated': gate_keyword(item)}
    return out


def find_merges(ids, matrix, scored: dict, items_by_id: dict, eligible: set) -> list:
    """Same technique, several creators: greedy groups around the best-scored seeds.

    ids/matrix are parallel (EmbeddingIndex.ids()/matrix(), rows L2-normalized). Only
    `eligible` ids (procedural, not covered by a skill) take part; each item joins at most
    one group. Returns [{key, item_ids, creators, score}] best first."""
    import numpy as np
    rows = [r for r, i in enumerate(ids) if int(i) in eligible]
    if len(rows) < _MERGE_MIN_ITEMS:
        return []
    sub_ids = [int(ids[r]) for r in rows]
    sub = matrix[rows]
    sims = sub @ sub.T
    order = sorted(range(len(sub_ids)), key=lambda n: -scored[sub_ids[n]]['score'])
    used, merges = set(), []
    for seed in order:
        if seed in used:
            continue
        near = [n for n in np.nonzero(sims[seed] >= _MERGE_FLOOR)[0].tolist()
                if n not in used and n != seed]
        near.sort(key=lambda n: -scored[sub_ids[n]]['score'])
        members, per_creator = [], {}
        for n in [seed] + near:
            c = _creator(items_by_id[sub_ids[n]], sub_ids[n])
            if per_creator.get(c, 0) < _MERGE_PER_CREATOR:
                per_creator[c] = per_creator.get(c, 0) + 1
                members.append(n)
        member_ids = [sub_ids[n] for n in members]
        creators = set(per_creator)
        if len(member_ids) < _MERGE_MIN_ITEMS or len(creators) < _MERGE_MIN_CREATORS:
            continue
        used.update(members)
        member_ids.sort(key=lambda i: -scored[i]['score'])
        merges.append({
            'key': 'merge-' + '-'.join(str(i) for i in sorted(member_ids)[:4]),
            'item_ids': member_ids,
            'creators': len(creators),
            'score': round(sum(scored[i]['score'] for i in member_ids) / len(member_ids), 3),
        })
    merges.sort(key=lambda m: (-len(m['item_ids']), -m['score']))
    return merges[:_MAX_MERGES]


def note_candidates(notes_dir, covered_notes: set) -> list:
    """[{file, topic, score}] for notes that read like procedures, best first."""
    out = []
    notes_dir = Path(notes_dir) if notes_dir else None
    if not notes_dir or not notes_dir.is_dir():
        return out
    for p in notes_dir.glob('*.md'):
        if p.name in covered_notes:
            continue
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            continue
        m = re.search(r'^topic:\s*(.*)$', text[:2000], flags=re.M)
        score = procedure_score(text)
        if score >= _MIN_SCORE:
            out.append({'file': p.name, 'topic': (m.group(1).strip() if m else p.stem),
                        'score': score})
    out.sort(key=lambda n: -n['score'])
    return out[:_MAX_NOTES]


def candidates(items, ids=None, matrix=None, notes_dir=None, skills_dirs=(),
               min_score: float = _MIN_SCORE) -> dict:
    """Everything a scan proposes, as plain data:
    {'merges': [...], 'items': [{id, score, signals, gated}], 'notes': [...],
     'gated': [ids of gated items too thin to use], 'covered': n, 'skills': [names]}.
    ids/matrix (an EmbeddingIndex's) are optional: without them there are no merges."""
    items_by_id = {int(i['id']): i for i in items}
    scored = score_items(items)
    covered_ids, covered_notes, names = skill_ledger(skills_dirs)
    eligible = {i for i, s in scored.items()
                if s['score'] >= min_score and i not in covered_ids}
    merges = []
    if ids is not None and matrix is not None and len(ids):
        merges = find_merges(ids, matrix, scored, items_by_id, eligible)
    in_merge = {i for m in merges for i in m['item_ids']}
    singles = sorted((i for i in eligible if i not in in_merge),
                     key=lambda i: -scored[i]['score'])[:_MAX_ITEMS]
    gated = sorted((i for i, s in scored.items()
                    if s['gated'] and s['score'] < min_score), reverse=True)
    return {
        'merges': merges,
        'items': [dict(id=i, **scored[i]) for i in singles],
        'notes': note_candidates(notes_dir, covered_notes),
        'gated': gated,
        'covered': len(covered_ids & set(scored)),
        'skills': sorted(names),
        'scored': scored,
    }


def signal_summary(signals: dict) -> str:
    """'howto 2, steps 5, commands 1' (non-zero signals only)."""
    return ', '.join(f'{k} {v}' for k, v in signals.items() if v) or 'none'



# ── the Claude gate: one batched call sorts every candidate ──────────────────
# Same split as connections.py: the code above proposes, this call disposes. A candidate
# is never shown as a skill without a gate verdict.
GATE_MAX_TOKENS = 3000
GATE_EXCERPT = 600        # chars of text per item (or note) sent to the gate
GATE_MERGE_ITEMS = 3      # members of a merge group shown to the gate
BUCKETS = ('skill', 'agent', 'rule', 'note', 'reject')

GATE_SYSTEM = (
    "You are a strict curator turning a personal library of saved social-media reels and "
    "notes into Claude Code skills. A skill is a short instruction page Claude loads when a "
    "matching task comes up: a repeatable procedure with a trigger moment, ordered steps and "
    "a result you can check. The owner builds a desktop app, does design and motion work and "
    "edits video with Claude Code.\n"
    "For each CANDIDATE pick exactly one bucket:\n"
    "- skill: a repeatable procedure Claude Code could follow or guide (the default when it "
    "fits);\n"
    "- agent: a job that should run on its own with its own tools or model and leave a file "
    "for a next step;\n"
    "- rule: a one-line habit for every task, better as a line in CLAUDE.md;\n"
    "- note: worth keeping as knowledge but not something Claude does (fitness routines, "
    "recipes, opinions, news, tool lists without steps);\n"
    "- reject: no real steps, steps hidden behind 'comment X', pure promotion, or already "
    "covered by an EXISTING SKILL.\n"
    "For skill, agent and rule also give a lowercase-hyphen name (2-4 words) and one sentence "
    "starting 'Use when' that says when it applies and what it produces. Set overlaps to the "
    "existing skill name it duplicates or should improve, else empty. Reply with ONLY a JSON "
    "object, no prose, shaped exactly:\n"
    '{"<key>": {"bucket": "skill", "name": "<name>", "use_when": "Use when ...", '
    '"overlaps": ""}}\n'
    "Every input key must appear in the output."
)


def _excerpt(text: str, limit: int = GATE_EXCERPT) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()[:limit]


def gate_payload(res: dict, items_by_id: dict, notes_dir=None) -> dict:
    """The gate input built from a candidates() result, plain data only:
    {'skills': [names], 'candidates': [{key, kind, item_ids | note, text}]}."""
    out = []
    for m in res.get('merges', []):
        parts = [f"[id {i}] {item_title(items_by_id[i])}\n"
                 f"{_excerpt(item_text(items_by_id[i]), GATE_EXCERPT // 2)}"
                 for i in m['item_ids'][:GATE_MERGE_ITEMS]]
        out.append({'key': m['key'], 'kind': 'merge', 'item_ids': m['item_ids'],
                    'text': f"{len(m['item_ids'])} saves from {m['creators']} creators "
                            "on one technique:\n" + '\n'.join(parts)})
    for it in res.get('items', []):
        item = items_by_id[it['id']]
        out.append({'key': f"item-{it['id']}", 'kind': 'item', 'item_ids': [it['id']],
                    'text': f"[id {it['id']}] {item_title(item)}\n"
                            f"{_excerpt(item_text(item))}"})
    for n in res.get('notes', []):
        body = ''
        if notes_dir:
            try:
                body = (Path(notes_dir) / n['file']).read_text(encoding='utf-8')
            except Exception:
                body = ''
        body = re.sub(r'^---\n.*?\n---\n+', '', body, flags=re.DOTALL)
        out.append({'key': f"note-{n['file']}", 'kind': 'note', 'note': n['file'],
                    'text': f"note {n['file']}: {n['topic']}\n{_excerpt(body)}"})
    return {'skills': list(res.get('skills', [])), 'candidates': out}


def gate_prompt(payload: dict) -> str:
    skills_line = ', '.join(payload.get('skills') or []) or '(none)'
    blocks = [f"CANDIDATE {c['key']}\n{c['text']}\n" for c in payload.get('candidates', [])]
    return f"EXISTING SKILLS: {skills_line}\n\n" + '\n'.join(blocks)


def _slug(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (text or '').strip().lower()).strip('-')
    return s[:48]


def parse_gate(text: str) -> dict:
    """{key: {'bucket', 'name', 'use_when', 'overlaps'}} from the gate reply; unknown
    buckets become reject. Raises ValueError when the reply has no JSON object."""
    m = re.search(r'\{.*\}', text or '', flags=re.DOTALL)
    if not m:
        raise ValueError('no JSON object in the model reply')
    data = json.loads(m.group(0))
    out = {}
    for key, v in data.items():
        if not isinstance(v, dict):
            continue
        bucket = str(v.get('bucket', '')).strip().lower()
        if bucket not in BUCKETS:
            bucket = 'reject'
        out[str(key)] = {'bucket': bucket, 'name': _slug(v.get('name', '')),
                         'use_when': str(v.get('use_when') or '').strip(),
                         'overlaps': _slug(v.get('overlaps', ''))}
    return out


def verdicts(payload: dict, res: dict) -> list:
    """The gate's kept verdicts joined to their candidates, skill > agent > rule > note.
    Candidates the gate rejected, or left out of its reply, are dropped."""
    order = {b: n for n, b in enumerate(BUCKETS)}
    out = []
    for c in payload.get('candidates', []):
        v = res.get(c['key'])
        if not v or v['bucket'] == 'reject':
            continue
        if v['bucket'] in ('skill', 'agent', 'rule') and not v['name']:
            v = dict(v, name=_slug(c['key']))
        out.append({'key': c['key'], 'kind': c['kind'], **v,
                    'item_ids': c.get('item_ids', []), 'note': c.get('note', '')})
    out.sort(key=lambda r: order[r['bucket']])
    return out
