"""
librarian.py - shared knowledge tools for the Ask chat's native modes (Qt-free, no network).

The chat model answers by calling tools that walk the library's knowledge layers,
broad to specific:
  topics    data/obsidian_graph.json clusters (library/map_engine.py: title, summary, member ids by permanent topic id)
  notes     data/notes/*.md wiki syntheses + personal notes, searched per section
  items     hybrid FTS + embedding search over every saved item
  evidence  per-item report.md "Key information" / "How you could use this" + transcript
  resources websites / tools / links mentioned in items (resources table)

This module also builds the aux-embedding jobs (topic + note-section texts), extracts
resource links, and builds the Deep-mode system prompt (including the user's profile
note data/notes/about-me.md). The agent loop lives in ai_client.ask_agent; the QThread
wrapper is ui/ask_agent_worker.py. Every DB read goes through the Database-like object
passed in (db.ReadOnlyDatabase inside the worker), so this module never opens SQLite.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from core import note_format
from core.db import fts_terms
from knowledge import knowledge
from knowledge import prompt_files
from library import search

PROFILE_FILE = 'about-me.md'

# The tool definitions, the system prompt, the framing and the limits are shared with the phone
# (knowledge/prompts/ask_deep.json, web/src/mobile/ai/deep.ts; tests/test_phone_deep.py).
PROMPTS = prompt_files.load('ask_deep')
_L = PROMPTS['limits']
_RESULT_MAX = _L['result_max']        # chars per tool result handed back to the model
_SECTION_MAX = _L['section_max']      # chars of a note section kept for embedding + reading
_LINE_EXCERPT = _L['line_excerpt']    # chars per item in list-style results
_READ_MAX_IDS = _L['read_max_ids']
_KEYINFO_MAX = _L['keyinfo_max']
_HOWTO_MAX = _L['howto_max']
_TRANSCRIPT_MAX = _L['transcript_max']
_RANK_POOL = _L['rank_pool']          # candidates ranked per search (pages are cut from this)
_PROFILE_MAX = _L['profile_max']

TOOLS = PROMPTS['tools']
# Desktop-only tools (they write a proposal through the app's job queue); the phone's port never lists them.
PROPOSE_TOOLS = PROMPTS['desktop_tools']
CATEGORY_TOOLS = PROMPTS['category_tools']
# Canvas tool schemas are shared with the phone; available assets determine their results.
CANVAS_TOOLS = PROMPTS['canvas_tools']
CANVAS_LIST_MAX = 30          # canvases named in the instructions


def canvas_list(data_dir):
    """The newest canvases as compact JSON for the instructions (id, name, elements)."""
    from library import canvas_plan
    rows = canvas_plan.canvas_rows(data_dir / 'canvases')[:CANVAS_LIST_MAX]
    return json.dumps([{'id': r['id'], 'name': r['name'], 'elements': r['elements']} for r in rows], ensure_ascii=False)


def canvas_instructions(db, mcp=False):
    """The canvas rules for Deep (native tool names) or Claude Code (MCP names, job_status to wait)."""
    if mcp:
        return prompt_files.fill(PROMPTS['canvas_instructions'], canvases=canvas_list(db.data_dir), tool='set_canvas',
                                 read='show_item', after='after the user answers (job_status shows request.state '
                                 'approved or declined), call save_note if they want one.')
    return prompt_files.fill(PROMPTS['canvas_instructions'], canvases=canvas_list(db.data_dir), tool='propose_canvas',
                             read='read_items', after='offer it in your answer and queue it on a later turn, after '
                             'the user has answered this review.')


def category_instructions(db, tool_name='propose_category'):
    """Shared category policy for desktop Wiskit modes, with exact names including empty categories."""
    batch_tool = 'set_categories' if tool_name == 'set_category' else 'propose_categories'
    template = PROMPTS['category_instructions'].replace('propose_category', tool_name).replace('propose_categories', batch_tool)
    return prompt_files.fill(template,
        categories=json.dumps([c['name'] for c in db.get_categories()], ensure_ascii=False))


# ── text helpers ──────────────────────────────────────────────────────────────
def _clamp(value, default, lo, hi):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _one_line(text, limit):
    return ' '.join((text or '').split())[:limit]


def _cap(text):
    return text if len(text) <= _RESULT_MAX else text[:_RESULT_MAX] + '\n[truncated]'


def split_frontmatter(text):
    """({key: value}, body) for a note with optional '---' YAML-ish frontmatter."""
    m = re.match(r'^---\r?\n(.*?)\r?\n---\r?\n?', text, flags=re.DOTALL)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def report_section(text, header):
    """Body under a '### <header>' (any level) markdown heading, or ''."""
    out, capturing = [], False
    for ln in (text or '').splitlines():
        m = re.match(r'^\s{0,3}#{1,6}\s+(.*)', ln)
        if m:
            if capturing:
                break
            capturing = m.group(1).strip().lower().startswith(header.lower())
            continue
        if capturing:
            out.append(ln)
    return '\n'.join(out).strip()


def describe_call(name, args):
    """One human-readable progress line for a tool call (shown in the Ask transcript)."""
    args = args or {}
    q = _one_line(str(args.get('query') or ''), 80)
    if name == 'find_topics':
        return f'Looking at topics: "{q}"'
    if name == 'topic_items':
        return 'Browsing a topic' + (f': "{q}"' if q else '')
    if name == 'search_library':
        cat = args.get('category')
        page = int(args.get('offset') or 0)
        return (f'Searching the library: "{q}"' + (f' in {cat}' if cat else '')
                + (f' (more results from #{page + 1})' if page else ''))
    if name == 'read_items':
        return f"Reading {len(args.get('ids') or [])} item(s) in detail"
    if name == 'search_notes':
        return f'Searching your notes: "{q}"'
    if name == 'find_resources':
        return f'Looking for websites and tools: "{q}"'
    if name == 'related_items':
        return f"Finding items related to [id {args.get('id')}]"
    if name == 'propose_reformat':
        return f'Queuing a reformat proposal for {_one_line(str(args.get("file") or ""), 80)}'
    if name == 'read_note':
        return f'Reading the note {_one_line(str(args.get("file") or ""), 80)}'
    if name == 'propose_category':
        return f'Asking approval to categorize items as {_one_line(str(args.get("category") or ""), 80)}'
    if name == 'propose_categories':
        return 'Preparing one category batch for approval'
    if name == 'list_canvases':
        return 'Looking at your canvases'
    if name == 'read_canvas':
        return 'Reading a canvas'
    if name == 'list_frames':
        return f"Listing the frames of [id {args.get('item_id')}]"
    if name == 'propose_canvas':
        target = _one_line(str(args.get('new_name') or ''), 80)
        return f'Preparing the canvas "{target}" for review' if target else 'Preparing canvas additions for review'
    return f'Using {name}'


# ── profile + system prompt ───────────────────────────────────────────────────
def read_profile(notes_dir):
    """The user's 'About me' note body (data/notes/about-me.md), or ''."""
    p = notes_dir / PROFILE_FILE
    if not p.exists():
        return ''
    try:
        _meta, body = split_frontmatter(p.read_text(encoding='utf-8'))
    except OSError:
        return ''
    return note_format.plain(body).strip()[:_PROFILE_MAX]


def build_system_prompt(profile, category_counts, total_items):
    cats = ', '.join(f'{name} ({n})' for name, n in
                     sorted(category_counts.items(), key=lambda kv: -kv[1]))
    prompt = prompt_files.fill(PROMPTS['system'], total_items=total_items, categories=cats)
    if profile:
        prompt += prompt_files.fill(PROMPTS['profile'], profile=profile)
    return prompt


# ── aux embeddings: topics + note sections ────────────────────────────────────
# The topic texts embed title and summary only; member_ids travel in the payload for the phone, but the
# desktop reads current members from the cache at call time (_topic_members): membership changes
# without the text changing (map maintenance), and the aux vector is recomputed only when the text does.
def _topic_texts(data_dir, can_continue=None):
    path = data_dir / 'obsidian_graph.json'
    try:
        clusters = json.loads(path.read_text(encoding='utf-8')).get('clusters') or {}
    except (OSError, ValueError):
        return []
    out = []
    for key, c in clusters.items():
        if can_continue and not can_continue():
            break
        title = (c.get('title') or '').strip()
        synthesis = (c.get('synthesis') or '').strip()
        if not title and not synthesis:
            continue
        out.append({
            'key': f'topic:{key}', 'kind': 'topic',
            'text': f'{title}\n{synthesis}'[:6000],
            'payload': {'title': title, 'synthesis': synthesis,
                        'member_ids': [int(i) for i in c.get('member_ids') or []]},
        })
    return out


def _note_sections(notes_dir, can_continue=None):
    out = []
    if not notes_dir.exists():
        return out
    for p in sorted(notes_dir.glob('*.md')):
        if can_continue and not can_continue():
            break
        if p.name == PROFILE_FILE:
            continue   # the profile goes into the system prompt instead
        try:
            meta, body = split_frontmatter(p.read_text(encoding='utf-8'))
        except OSError:
            continue
        body = note_format.plain(body)
        topic = meta.get('topic') or p.stem
        kind = meta.get('kind') or 'wiki'
        sources = [int(n) for n in re.findall(r'\d+', meta.get('sources', ''))]
        parts, heading, buf = [], topic, []
        for line in body.splitlines():
            m = re.match(r'^#{1,3}\s+(.*)', line)
            if m:
                parts.append((heading, '\n'.join(buf).strip()))
                heading, buf = m.group(1).strip(), []
            else:
                buf.append(line)
        parts.append((heading, '\n'.join(buf).strip()))
        n = 0
        for heading, text in parts:
            if can_continue and not can_continue():
                break
            if len(text) < 40:
                continue
            out.append({
                'key': f'note:{p.name}#{n}', 'kind': 'note',
                'text': f'{topic} - {heading}\n{text}'[:6000],
                'payload': {'filename': p.name, 'topic': topic, 'heading': heading,
                            'kind': kind, 'sources': sources,
                            'text': text[:_SECTION_MAX]},
            })
            n += 1
    return out


def aux_jobs(data_dir, notes_dir, stored_hashes, model, can_continue=None):
    """(jobs, obsolete_keys). jobs: [{'key','kind','text','hash','payload'}] for topic
    and note-section texts whose stored hash is missing or stale; obsolete_keys: stored
    keys that no longer exist. Pure file reads; the caller owns the DB."""
    live = _topic_texts(data_dir, can_continue) + _note_sections(notes_dir, can_continue)
    jobs, keys = [], set()
    for entry in live:
        keys.add(entry['key'])
        h = search.text_hash(model, entry['text'])
        if stored_hashes.get(entry['key']) != h:
            jobs.append(dict(entry, hash=h))
    obsolete = [k for k in stored_hashes if k not in keys] if not can_continue or can_continue() else []
    return jobs, obsolete


# ── resource extraction ───────────────────────────────────────────────────────
_URL_RE = re.compile(r'https?://[^\s<>()\[\]{}"\'`|]+', re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r'(?<![@\w./-])((?:[a-z0-9-]+\.)+(?:com|io|ai|app|co|dev|net|org|so|sh|website|xyz|'
    r'tools|me|gg|design|studio|tv|fm|link|page|site|tech|cc|ly|to|fr|art|club|store|'
    r'shop|cloud|pro|tips|gallery|digital|land|world|academy))(?![\w-])',
    re.IGNORECASE)
_SKIP_DOMAINS = {
    'facebook.com', 'm.facebook.com', 'fb.com', 'fb.watch', 'fb.me', 'instagram.com',
    'l.instagram.com', 'fbcdn.net', 'cdninstagram.com', 'linktr.ee', 't.co',
}


def _norm_domain(host):
    host = (host or '').lower().strip('.')
    return host[4:] if host.startswith('www.') else host


def extract_resources(text):
    """[(domain, url, context)] for links and bare domains in text, one per domain."""
    found = {}
    for line in (text or '').splitlines():
        ctx = _one_line(line, 200)
        for m in _URL_RE.finditer(line):
            url = m.group(0).rstrip('.,;:!?*_')
            domain = _norm_domain(urlparse(url).netloc)
            if domain and domain not in _SKIP_DOMAINS and domain not in found:
                found[domain] = (domain, url, ctx)
        for m in _DOMAIN_RE.finditer(line):
            domain = _norm_domain(m.group(1))
            if domain and domain not in _SKIP_DOMAINS and domain not in found:
                found[domain] = (domain, 'https://' + domain, ctx)
    return list(found.values())


def resource_rows(items, items_dir, can_continue=None):
    """[(item_id, domain, url, context)] for every item. Scans the post text, ai_desc and
    the report up to its Description section (so the transcript is not scanned)."""
    rows = []
    for it in items:
        if can_continue and not can_continue():
            raise RuntimeError('Resource indexing stopped before completion.')
        parts = [it.get('description') or '', it.get('ai_desc') or '']
        rp = items_dir / str(it['id']) / 'report.md'
        if rp.exists():
            try:
                rep = rp.read_text(encoding='utf-8', errors='replace')
            except OSError:
                rep = ''
            parts.append(rep.split('\n## Description', 1)[0])
        for domain, url, ctx in extract_resources('\n'.join(parts)):
            rows.append((it['id'], domain, url, ctx))
    return rows


# ── the tools ─────────────────────────────────────────────────────────────────
class Librarian:
    """Executes the TOOLS over a Database-like object.

    db:         Database or db.ReadOnlyDatabase (fts_ids, get_items_by_ids,
                item_ids_by_category, count_by_category, search_notes,
                resources_for_items, search_resources, items_dir).
    item_index: search.EmbeddingIndex over item vectors (may be empty).
    aux:        [{'key','kind','payload','vec'}] topic + note-section vectors.
    embed_fn:   text -> vector or None (no embeddings key / network error).
    """

    def __init__(self, db, item_index, aux, embed_fn, propose_fn=None, category_fn=None, category_batch_fn=None,
                 canvas_fn=None, *, budget=None, should_stop=None, deadline=None):
        import numpy as np
        self.db = db
        self.item_index = item_index
        self._embed_fn = embed_fn
        self._propose_fn = propose_fn  # file -> result text; queues a reformat proposal (no write)
        self._category_fn = category_fn  # ids, category -> result text; requests approval (no write)
        self._category_batch_fn = category_batch_fn
        self._canvas_fn = canvas_fn    # proposal dict -> result text; requests approval (no write)
        self._qvec_cache = {}
        self.consulted = []           # item ids returned by tools, in order
        self.budget = budget
        self.should_stop = should_stop
        self.deadline = deadline
        self.admitted = set()
        self.delivered = set()
        self.evidence = set()
        self.canvases = {}
        self.frames = {}
        self.notes = set()
        self.note_sources = set()
        self.chars = 0
        self.control_spent = 0
        self._aux = {'topic': [], 'note': []}
        for a in aux:
            if a['kind'] in self._aux:
                self._aux[a['kind']].append(a)
        self._aux_mat = {}
        for kind, rows in self._aux.items():
            if rows:
                m = np.vstack([np.asarray(r['vec'], dtype=np.float32) for r in rows])
                norms = np.linalg.norm(m, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self._aux_mat[kind] = m / norms

        self._cache_clusters = None     # data/obsidian_graph.json clusters, read once per run (see _topic_members)

    # dispatcher
    def run_tool(self, name, args):
        """Run one tool call; always returns text (errors become 'Error: ...')."""
        self.check_stop()
        allowed = {t['name'] for t in TOOLS + PROPOSE_TOOLS + CATEGORY_TOOLS + CANVAS_TOOLS}
        fn = getattr(self, 'tool_' + str(name), None) if name in allowed else None
        if fn is None:
            return f'Error: unknown tool {name!r}.'
        try:
            if not name.startswith('propose_') and not self.can_research():
                return 'Error: research deadline exhausted.'
            if self.budget and not name.startswith('propose_') and not self.room():
                return 'Error: research context budget exhausted.'
            return self.admit_result(name, fn(**(args or {})))
        except TypeError as e:
            return self.admit_result(name, f'Error: bad arguments for {name}: {e}')
        except Exception as e:   # never let a tool failure kill the whole answer
            self.check_stop()
            return self.admit_result(name, f'Error: {name} failed: {e}')

    def check_stop(self):
        if self.should_stop and self.should_stop():
            raise RuntimeError('Stopped.')

    def can_research(self):
        self.check_stop()
        return self.deadline is None or time.monotonic() < self.deadline

    def room(self):
        if not self.budget:
            return _RESULT_MAX
        return max(0, min(self.budget['result_chars'], self.budget['research_chars']
                         - PROMPTS['agent_budgets']['control_chars'] - (self.chars - self.control_spent)))

    def admit_ids(self, ids, limit=None):
        if not self.budget:
            return list(ids)[:limit] if limit else list(ids)
        out, new = [], set()
        for iid in dict.fromkeys(ids):
            if limit is not None and len(out) >= limit:
                break
            if iid not in self.admitted and len(self.admitted | new) >= self.budget['max_items']:
                continue
            out.append(iid)
            new.add(iid)
        return out

    def admit_result(self, name, text):
        """Admit complete units; JSON views remain valid and omitted units grant no evidence."""
        if not self.budget:
            return _cap(text)
        proposal = name.startswith('propose_')
        control = proposal or text.startswith('Error:')
        if text.startswith('Error:') and len(text) > 64:
            text = text[:48] + ' [truncated]'
        maxchars = min(512 if proposal else 64, PROMPTS['agent_budgets']['control_chars'] - self.control_spent,
                       self.budget['research_chars'] - self.chars) if control else self.room()
        if proposal and len(text) > 512:
            text = 'Error: proposal could not be prepared.' if text.startswith('Error:') else 'Prepared for review. Nothing changes until you approve.'
        view = None
        if text.startswith(('{', '[')):
            try:
                view = json.loads(text)
            except ValueError:
                pass
        if view is not None:
            text = json.dumps(view, ensure_ascii=False, separators=(',', ':'))
            entries = view if isinstance(view, list) else next((view[k] for k in ('elements', 'frames') if isinstance(view.get(k), list)), None)
            while len(text) > maxchars and entries:
                entries.pop()
                if isinstance(view, dict):
                    view['truncated'] = True
                    view['shown'] = len(entries)
                text = json.dumps(view, ensure_ascii=False, separators=(',', ':'))
            if len(text) > maxchars:
                text, view = 'Error: result exceeds remaining context budget.', None
        elif len(text) > maxchars:
            sep = '\n\n---\n\n' if '\n\n---\n\n' in text else '\n'
            units, out = text.split(sep), []
            for unit in units:
                if len(sep.join(out + [unit])) + 24 > maxchars:
                    break
                out.append(unit)
            text = sep.join(out) + '\n[truncated: budget]'
        if len(text) > maxchars:
            return 'Error: research context budget exhausted.'
        control = control or text.startswith('Error:')
        self.chars += len(text)
        if control:
            self.control_spent += len(text)
        if not text.startswith('Error:'):
            # These IDs come from our formatted result, never model-supplied claims.
            ids = {int(i) for i in re.findall(r'^\[id (\d+)\]', text, re.M)}
            self.admitted.update(ids)
            self.delivered.update(int(i) for i in re.findall(r'\[id (\d+)\]', text))
            self.consulted.extend(ids)
            if name == 'read_items':
                self.evidence.update(ids)
            self.note_sources.update(f for f in re.findall(r'^\[note: ([^\]]+)\]', text, re.M)
                                     if knowledge.safe_note_path(self.db.notes_dir, f))
            if name == 'read_canvas' and isinstance(view, dict):
                self.canvases[view['id']] = {e['id'] for e in view['elements']}
            if name == 'list_frames' and isinstance(view, dict):
                self.frames[view['item_id']] = {f['name'] if isinstance(f, dict) else f for f in view['frames']}
            if name == 'read_note' and 'kind: personal' in text:
                self.notes.update(re.findall(r'^\[note: ([^\]]+)\]', text, re.M))
        return text

    # helpers
    def _qvec(self, query):
        if not self.can_research():
            return None
        query = (query or '').strip()
        if not query:
            return None
        if query not in self._qvec_cache:
            try:
                self._qvec_cache[query] = self._embed_fn(query)
            except Exception:
                self.check_stop()
                self._qvec_cache[query] = None
        return self._qvec_cache[query]

    def _rank(self, query, restrict=None, pool=_RANK_POOL):
        """Hybrid-ranked item ids for query, optionally restricted to a set of ids."""
        fts = self.db.fts_ids(query, pool if restrict is None else 2000)
        vec = self._qvec(query)
        hits = []
        if vec is not None and len(self.item_index):
            k = len(self.item_index) if restrict is not None else pool
            hits = self.item_index.topk(vec, k)
        if restrict is not None:
            fts = [i for i in fts if i in restrict]
            hits = [h for h in hits if h[0] in restrict]
        return search.hybrid_rank(fts, hits, limit=pool)

    def _lines(self, ids):
        rows = self.db.get_items_by_ids(self.admit_ids(ids))
        self.consulted.extend(r['id'] for r in rows)
        out = []
        for r in rows:
            body = _one_line(r.get('ai_desc') or r.get('description')
                             or r.get('transcript') or r.get('short_desc'), _LINE_EXCERPT)
            meta = ', '.join(p for p in (r.get('creator'), r.get('category')) if p)
            out.append(f"[id {r['id']}] {body}" + (f' ({meta})' if meta else ''))
        return out

    def _aux_rank(self, kind, query, limit):
        mat = self._aux_mat.get(kind)
        vec = self._qvec(query)
        rows = self._aux[kind]
        if mat is not None and vec is not None:
            import numpy as np
            q = np.asarray(vec, dtype=np.float32).ravel()
            n = np.linalg.norm(q)
            if n:
                scores = np.einsum('ij,j->i', mat, q / n)   # no BLAS: see search.EmbeddingIndex._rank
                order = np.argsort(-scores)[:limit]
                return [(rows[i], float(scores[i])) for i in order]
        # keyword fallback: count query words present
        terms = fts_terms(query)
        scored = []
        for r in rows:
            p = r['payload']
            text = (p.get('title', '') + ' ' + p.get('synthesis', '') + ' '
                    + p.get('topic', '') + ' ' + p.get('heading', '') + ' '
                    + p.get('text', '')).lower()
            s = sum(1 for t in terms if t in text)
            if s:
                scored.append((r, float(s)))
        scored.sort(key=lambda rs: -rs[1])
        return scored[:limit]

    def _topic_members(self, key, payload):
        """The topic's current member ids: the cache file (raw keys, as written) when it still has the topic,
        else the payload embedded with the text (a retired topic, or a cache this phone-shaped row predates)."""
        if self._cache_clusters is None:
            self._cache_clusters = {}
            data_dir = getattr(self.db, 'data_dir', None)
            if data_dir:
                try:
                    data = json.loads((Path(data_dir) / 'obsidian_graph.json').read_text(encoding='utf-8'))
                    if isinstance(data.get('clusters'), dict):
                        self._cache_clusters = data['clusters']
                except (OSError, ValueError, AttributeError):
                    pass
        t = self._cache_clusters.get(key)
        if isinstance(t, dict) and isinstance(t.get('member_ids'), list):
            return [int(i) for i in t['member_ids']]
        return [int(i) for i in payload.get('member_ids') or []]

    def orientation(self, question):
        """The always-attached starting context for a question: the closest topics and
        note sections. Guarantees the wiki/topic layers are used even when a model
        makes few tool calls; the model still reads items for the details."""
        topics = self.run_tool('find_topics', {'query': question, 'limit': 3})
        notes = self.run_tool('search_notes', {'query': question, 'limit': 3})
        return prompt_files.fill(PROMPTS['orientation'], topics=topics, notes=notes)

    # tools
    def tool_find_topics(self, query, limit=5):
        limit = _clamp(limit, 5, 1, 10)
        ranked = self._aux_rank('topic', query, limit)
        if not ranked:
            return 'No topics available (the topic map has not been built).'
        out = []
        for row, _score in ranked:
            p = row['payload']
            key = row['key'].split(':', 1)[1]
            out.append(f"topic_id={key} | {p['title']} | "
                       f"{len(self._topic_members(key, p))} items\n{_one_line(p['synthesis'], 700)}")
        return '\n\n'.join(out)

    def tool_topic_items(self, topic_id, query='', offset=0, limit=20):
        offset, limit = _clamp(offset, 0, 0, 2000), _clamp(limit, 20, 1, 50)
        key = 'topic:' + str(topic_id).replace('topic:', '')
        row = next((r for r in self._aux['topic'] if r['key'] == key), None)
        if row is None:
            return f'Error: unknown topic_id {topic_id!r}. Use an id from find_topics.'
        members = self._topic_members(key.split(':', 1)[1], row['payload'])
        ids = self._rank(query, restrict=set(members)) if query else []
        seen = set(ids)
        ids += [i for i in members if i not in seen]
        page = ids[offset:offset + limit]
        head = (f"Topic '{row['payload']['title']}': {len(ids)} items, showing "
                f"{offset + 1}-{offset + len(page)}")
        return head + '\n' + '\n'.join(self._lines(page))

    def tool_search_library(self, query, category='', offset=0, limit=20):
        offset, limit = _clamp(offset, 0, 0, _RANK_POOL), _clamp(limit, 20, 1, 50)
        restrict, label = None, ''
        if category:
            names = {name.lower(): name for name in self.db.count_by_category() if name}
            real = names.get(str(category).strip().lower())
            if real is None:
                return (f'Error: unknown category {category!r}. Categories: '
                        + ', '.join(sorted(names.values())))
            restrict, label = set(self.db.item_ids_by_category(real)), f' in {real}'
        ids = self._rank(query, restrict=restrict)
        page = ids[offset:offset + limit]
        if not page:
            return f'No more results{label} (offset {offset}).'
        head = (f'Results{label} {offset + 1}-{offset + len(page)}, ranked by relevance '
                f'(later pages are less relevant):')
        return head + '\n' + '\n'.join(self._lines(page))

    def tool_read_items(self, ids, query=''):
        ids = self.admit_ids([int(i) for i in (ids or [])], self.budget['read_max_ids'] if self.budget else _READ_MAX_IDS)
        rows = self.db.get_items_by_ids(ids)
        self.consulted.extend(r['id'] for r in rows)
        terms = fts_terms(query) if query else []
        out = []
        for r in rows:
            if not self.can_research():
                break
            head = f"[id {r['id']}]"
            meta = ' | '.join(p for p in (r.get('creator'), r.get('category'),
                                          r.get('type'), r.get('url')) if p)
            parts = [head + ' ' + meta,
                     'Category: ' + (r.get('category') or '(none)'),
                     'Summary: ' + _one_line(r.get('ai_desc') or r.get('description'), 900)]
            remaining = self.room() - len('\n\n---\n\n'.join(out)) - 128
            if self.budget and len('\n'.join(parts)) > remaining:
                break
            rp = self.db.items_dir / str(r['id']) / 'report.md'
            rep = ''
            if rp.exists():
                try:
                    rep = rp.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    rep = ''
            key = report_section(rep, 'Key information')
            if key:
                parts.append('Key information:\n' + key[:_KEYINFO_MAX])
            howto = report_section(rep, 'How you could use this')
            if howto:
                parts.append('How to use it:\n' + howto[:_HOWTO_MAX])
            if r.get('description') and r.get('ai_desc'):
                parts.append('Post text: ' + _one_line(r['description'], 400))
            tr = r.get('transcript') or ''
            if tr:
                low, start = tr.lower(), 0
                hits = [p for p in (low.find(t) for t in terms) if p >= 0]
                if hits:
                    start = max(0, min(hits) - _TRANSCRIPT_MAX // 4)
                parts.append('Transcript excerpt: '
                             + _one_line(tr[start:start + _TRANSCRIPT_MAX], _TRANSCRIPT_MAX))
            if self.budget:
                admitted = []
                for part in parts:
                    if len('\n'.join(admitted + [part])) + 24 <= remaining:
                        admitted.append(part)
                if len(admitted) < len(parts):
                    admitted.append('[truncated: budget]')
                parts = admitted
            out.append('\n'.join(parts))
        missing = set(ids) - {r['id'] for r in rows}
        if missing:
            out.append('Not found: ' + ', '.join(str(i) for i in sorted(missing)))
        if self.budget:
            out.append('[Coverage limited by item, result and research budgets.]')
        return '\n\n---\n\n'.join(out) if out else 'No items found for those ids.'

    def tool_search_notes(self, query, limit=4):
        limit = _clamp(limit, 4, 1, 8)
        ranked = self._aux_rank('note', query, limit)
        out = []
        for row, _score in ranked:
            p = row['payload']
            src = ', '.join(str(i) for i in p['sources'][:40])
            out.append(f"[note: {p['filename']}] {p['topic']} > {p['heading']} "
                       f"({p['kind']}; sources: {src or 'none'})\n{p['text'][:1800]}")
        if not out:   # no section vectors yet: whole-note keyword search
            for n in self.db.search_notes(query, limit):
                out.append(f"[note: {n['filename']}] {n['topic']}\n"
                           f"{(n.get('body') or '')[:1800]}")
        return '\n\n---\n\n'.join(out) if out else 'No matching notes.'

    def tool_find_resources(self, query, limit=15):
        limit = _clamp(limit, 15, 1, 40)
        ranked = self._rank(query, pool=150)
        pos = {iid: n for n, iid in enumerate(ranked)}
        rows = self.db.resources_for_items(ranked)
        rows += self.db.search_resources(fts_terms(query), 50)
        by_domain = {}
        for item_id, domain, url, ctx in rows:
            score = 1.0 / (10 + pos.get(item_id, 300))
            d = by_domain.setdefault(domain, {'url': url, 'ctx': ctx, 'items': [],
                                              'score': 0.0})
            if item_id not in d['items']:
                d['items'].append(item_id)
                d['score'] += score
        best = sorted(by_domain.items(), key=lambda kv: -kv[1]['score'])[:limit]
        if not best:
            return 'No websites or tools found for that.'
        out = []
        for domain, d in best:
            self.consulted.extend(d['items'][:3])
            ids = ', '.join(f'[id {i}]' for i in d['items'][:5])
            out.append(f"{domain} | {d['url']} | from {ids} | {d['ctx']}")
        return '\n'.join(out)

    def tool_propose_reformat(self, file, instruction=''):
        if self._propose_fn is None:
            return 'Error: reformat proposals are not available here.'
        if self.budget and file not in self.notes:
            return 'Error: read this personal note in this turn before proposing a reformat.'
        return self._propose_fn(str(file or '').strip(), ' '.join(str(instruction or '').split())[:500])

    def tool_propose_category(self, ids, category):
        if self._category_fn is None:
            return 'Error: category proposals are not available here.'
        if self.budget and (not isinstance(ids, list) or not ids or any(type(i) is not int or i not in self.evidence for i in ids) or len(set(ids)) != len(ids)):
            return 'Error: category proposal requires current-turn item evidence.'
        return self._category_fn(ids, category)

    def tool_propose_categories(self, groups):
        if self._category_batch_fn is None:
            return 'Error: category batch proposals are not available here.'
        if self.budget and (not isinstance(groups, list) or any(not isinstance(g, dict) or
                not isinstance(g.get('ids'), list) or any(type(i) is not int or i not in self.evidence for i in g['ids']) for g in groups)):
            return 'Error: category proposal requires current-turn item evidence.'
        return self._category_batch_fn(groups)

    # canvases (desktop only): read the JSON files, never through CanvasStore (its constructor writes)
    def tool_list_canvases(self):
        from library import canvas_plan
        rows = canvas_plan.canvas_rows(self.db.data_dir / 'canvases')
        return json.dumps(rows, ensure_ascii=False) if rows else 'No canvases yet.'

    def tool_read_canvas(self, canvas_id):
        from library import canvas_plan
        try:
            view = canvas_plan.canvas_view(self.db.data_dir / 'canvases', str(canvas_id or '').strip())
        except canvas_plan.ProposalError as e:
            return f'Error: {e}'
        self.consulted.extend(e['item_id'] for e in view['elements'] if isinstance(e.get('item_id'), int))
        return json.dumps(view, ensure_ascii=False)

    def tool_list_frames(self, item_id):
        from library import canvas_plan
        iid = int(item_id)
        if not self.db.get_items_by_ids([iid]):
            return f'Error: no item with id {iid}.'
        return json.dumps(canvas_plan.frames_view(self.db.items_dir / str(iid), iid))

    def tool_propose_canvas(self, **proposal):
        if self._canvas_fn is None:
            return 'Error: canvas proposals are not available here.'
        if self.budget:
            from library import canvas_plan
            p = canvas_plan.normalize(proposal)
            target = p.get('canvas_id')
            if target and target not in self.canvases:
                return 'Error: read the target canvas in this turn first.'
            for e in p['elements']:
                if e.get('item_id') is not None and e['item_id'] not in self.evidence:
                    return f"Error: read item {e['item_id']} in this turn first."
                if e['kind'] == 'existing' and e['id'] not in self.canvases.get(target, set()):
                    return 'Error: existing element was not exposed by read_canvas.'
                if e['kind'] == 'frame' and e['frame'] not in self.frames.get(e['item_id'], set()):
                    return 'Error: frame filename was not exposed by list_frames.'
        return self._canvas_fn(proposal)

    def tool_read_note(self, file):
        """One note as written (markup and the stamps line included), so Deep can format it."""
        p = knowledge.safe_note_path(self.db.notes_dir, str(file or '').strip())
        if p is None:
            return f'No note named {file!r}. Find notes with search_notes.'
        meta, body = split_frontmatter(p.read_text(encoding='utf-8', errors='replace'))
        head = [f"[note: {p.name}] {meta.get('topic') or p.stem}", f"kind: {meta.get('kind') or 'wiki'}"]
        for key in ('category', 'stamps'):
            if meta.get(key):
                head.append(f'{key}: {meta[key]}')
        return '\n'.join(head) + '\n\n' + body.strip()

    def tool_related_items(self, id, limit=8):
        limit = _clamp(limit, 8, 1, 20)
        hits = self.item_index.similar_to(int(id), limit) if len(self.item_index) else []
        if not hits:
            return f'No related items found for id {id}.'
        return '\n'.join(self._lines([h[0] for h in hits]))
