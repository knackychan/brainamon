"""
ask_core.py - the Ask-my-library retrieval and prompt assembly, Qt-free. Moved unchanged from
ui/main_window.py (`_ask_*`) so the Qt Ask tab and the V6 server (server/routes/ask.py) send the
same context to the same prompt. One copy of every prompt.

The caller passes a `db` for reads (the Qt main-thread Database, or a server reader); nothing here
writes except `save_note`, which the server runs on its Writer. Network work (the query
embedding, the chat stream, the Deep agent) stays with the caller, except `deep_answer`, the body
of the Deep worker, which opens its own read-only connection (the one documented exception in
root CLAUDE.md).
"""
import re
import time
from datetime import datetime

from core import ai_client
from core import config
from core import note_format
from knowledge import librarian
from knowledge import prompt_files
from knowledge.prompt_files import fill
from knowledge import weekly_review
from library import search
from knowledge import tasks
from core.db import fts_terms

# Prompt texts and limits live in knowledge/prompts/ask_quick.json, shared with the phone
# (web/src/mobile/ai/quick.ts): change them there.
P = prompt_files.load('ask_quick')
_L = P['limits']
DEPTH_DEFAULT = _L['depth_default']
CATEGORY_MAX = _L['category_max']
EXCERPT = _L['excerpt']
HISTORY_TURNS = _L['history_turns']
NOTES = _L['notes']                    # saved notes (data/notes) added to the context per question
NOTE_EXCERPT = _L['note_excerpt']
DETAIL_ITEMS = _L['detail_items']      # top items that also get report "Key information" + transcript hit
KEYINFO_EXCERPT = _L['keyinfo_excerpt']
SNIPPET = _L['snippet']
# List mode ("give me all ..."): a wide, compact candidate pool the model filters. 150 hybrid
# candidates measured full recall on knee (73/73), vegan (8/8), geometry nodes (2/2).
LIST_RE = re.compile(r'\b(' + '|'.join(P['list_words'].split()) + r')\b', re.IGNORECASE)
LIST_MAX = _L['list_max']
LIST_EXCERPT = _L['list_excerpt']
LIST_MAX_TOKENS = _L['list_max_tokens']
# Follow-ups ("tell me more about the second one"): carry the previous answer's cited items.
CARRY_MAX = _L['carry_max']
FOLLOWUP_WORDS = frozenset(P['followup_words'].split())
SYSTEM = P['system']


def is_list(question: str) -> bool:
    return bool(LIST_RE.search(question or ''))


def effective_depth(question: str, depth: int) -> int:
    """List mode widens the pool to LIST_MAX compact candidates."""
    return max(depth, LIST_MAX) if is_list(question) else depth


def cited_ids(text):
    """Item ids cited in an answer: every number inside a bracket group that says
    'id'/'ids' ([id 12], [ids 3, 4], [id 5, id 6]). Order kept, deduped."""
    ids = []
    for grp in re.findall(r'\[([^\]]*)\]', text or ''):
        if re.search(r'\bids?\b', grp, re.IGNORECASE):
            ids += [int(n) for n in re.findall(r'\d+', grp)]
    return list(dict.fromkeys(ids))


def cited_notes(text):
    """Note files cited as [note: file]. Order kept, deduped."""
    return list(dict.fromkeys(m.strip() for m in re.findall(r'\[\s*note\s*:\s*([^\]]+?)\s*\]', text or '', re.IGNORECASE)))


def topic_terms(question):
    """Content words minus follow-up referring words ("more", "second", "one"...):
    what the question is about, as opposed to what it points back at."""
    return [t for t in fts_terms(question) if t not in FOLLOWUP_WORDS]


def relevant_notes(db, question):
    """Top saved notes (data/notes) for the question. A note is kept only when it
    contains at least half of the question's content words: OR-ranked FTS alone
    lets one shared word (e.g. 'ai') pull in an unrelated note."""
    terms = [re.compile(r'\b' + re.escape(t)) for t in topic_terms(question)]
    if not terms:
        return []
    need = max(1, (len(terms) + 1) // 2)
    out = []
    for n in db.search_notes(question, NOTES * 3):
        text = f"{n['topic']}\n{n.get('body') or ''}".lower()
        if sum(1 for t in terms if t.search(text)) >= need:
            out.append(n)
            if len(out) == NOTES:
                break
    return out


def carried_items(db, history, question):
    """For a follow-up question ("tell me more about the second one"), the items
    cited in the previous answer: retrieval on the new words alone would miss what
    the user is pointing at. A question counts as a follow-up when it has at most 2
    content words or uses a referring word (it/these/second/more...)."""
    if not history or history[-1].get('role') != 'assistant':
        return []
    words = set(re.findall(r'\w+', question.lower()))
    if len(fts_terms(question)) > 2 and not (words & FOLLOWUP_WORDS):
        return []
    ids = cited_ids(history[-1].get('content'))[:CARRY_MAX]
    return db.get_items_by_ids(ids)


def item_text(items_dir, r, terms=(), detail=False):
    """One item's context entry. `detail` adds the analysis report's Key information
    and, when the item has an ai_desc (so the transcript is not already the body),
    the transcript passage where the question's words first appear."""
    title = (r.get('short_desc') or r.get('ai_desc')
             or r.get('description') or '')[:120]
    body = (r.get('ai_desc') or r.get('transcript')
            or r.get('description') or r.get('short_desc') or '')[:EXCERPT]
    head = f"[id {r['id']}] {title}"
    if r.get('creator'):
        head += f" - {r['creator']}"
    if r.get('url'):
        head += f"\n{r['url']}"
    head += '\nCategory: ' + (r.get('category') or '(none)')
    text = head + "\n" + body
    if not detail:
        return text
    rp = items_dir / str(r['id']) / 'report.md'
    if rp.exists():
        try:
            key = tasks.report_section(
                rp.read_text(encoding='utf-8', errors='replace'), 'Key information')
        except OSError:
            key = ''
        if key:
            text += P['key_info'] + key[:KEYINFO_EXCERPT]
    tr = r.get('transcript') or ''
    if tr and r.get('ai_desc') and terms:
        low = tr.lower()
        hits = [p for p in (low.find(t) for t in terms) if p >= 0]
        if hits:
            start = max(0, min(hits) - SNIPPET // 3)
            text += fill(P['transcript_excerpt'], text=' '.join(tr[start:start + SNIPPET].split()))
    return text


def context_block(db, rows, notes=(), question='', carried=(), list_mode=False):
    blocks = []
    if notes:
        note_parts = [
            f"[note: {n['filename']}] {n['topic']}\n"
            + (n.get('body') or '').strip()[:NOTE_EXCERPT]
            for n in notes
        ]
        blocks.append(P['notes_head'] + P['part_sep'].join(note_parts))
    terms = fts_terms(question)
    if carried:
        blocks.append(P['carried_head'] + P['part_sep'].join(
            item_text(db.items_dir, r, terms, detail=True) for r in carried))
    if not rows:
        if not carried:
            blocks.append(P['no_items'])
    elif list_mode:
        lines = []
        for r in rows:
            body = ' '.join((r.get('ai_desc') or r.get('description') or r.get('transcript')
                             or r.get('short_desc') or '').split())[:LIST_EXCERPT]
            meta = ', '.join(p for p in (r.get('creator'), r.get('category')) if p)
            lines.append(f"[id {r['id']}] {body}" + (f" ({meta})" if meta else ''))
        blocks.append(fill(P['list_head'], n=len(rows), total=db.count_items()) + "\n".join(lines))
    else:
        parts = [item_text(db.items_dir, r, terms, detail=n < DETAIL_ITEMS)
                 for n, r in enumerate(rows)]
        blocks.append(fill(P['items_head'], n=len(parts), total=db.count_items()) + P['part_sep'].join(parts))
    return P['block_sep'].join(blocks)


# ── retrieval ────────────────────────────────────────────────────────────────
def rank_rows(db, question, depth, category, index, vec):
    """Hybrid retrieval (keyword + the embedded question)."""
    if category:
        # Rank within the category (spec: whole-category mode feeds the
        # CATEGORY_MAX most-relevant items of the category, not the
        # category slice of a global top-k). Brute-force topk over the whole
        # index is fine at this scale (~2.5k vectors).
        cand = set(db.item_ids_by_category(category))
        vec_hits = [h for h in index.topk(vec, len(index)) if h[0] in cand]
        fts = [i for i in db.fts_ids(question, 400) if i in cand]
        ids = search.hybrid_rank(fts, vec_hits, limit=CATEGORY_MAX)
        if not ids:
            ids = db.item_ids_by_category(category)[:CATEGORY_MAX]
    else:
        ids = search.hybrid_rank(
            db.fts_ids(question, 200), index.topk(vec, 200), limit=depth)
    return db.get_items_by_ids(ids)


def fallback_rows(db, question, depth, category):
    """No embeddings key / embed failed: keyword retrieval (category: keyword-ranked
    within the category, padded with its newest items)."""
    if category:
        cand = db.item_ids_by_category(category)
        cset = set(cand)
        ids = [i for i in db.fts_ids(question, 400) if i in cset]
        seen = set(ids)
        ids += [i for i in cand if i not in seen]
        return db.get_items_by_ids(ids[:CATEGORY_MAX])
    return db.fts_search(question, depth)


def fallback_label(reason=''):
    """The retrieval label of a keyword-only search, so a degraded search is never silent."""
    label = P['fallback']
    if reason:
        label += f' ({reason})'
    return label


def provider_problem(provider):
    """The user-facing message when the selected Ask provider cannot be used (its API key or the local
    server URL is not set), else ''. /api/ask/options sends one per provider, so the pages can say so
    before a question is typed."""
    if provider == ai_client.ASK_PROVIDER_ANTHROPIC:
        return '' if config.anthropic_api_key() else 'Set your Anthropic API key in ⚙️ Settings to use Ask.'
    if provider == ai_client.ASK_PROVIDER_OPENAI:
        return '' if config.openai_api_key() else 'Set your OpenAI API key in ⚙️ Settings to use Ask.'
    if provider == ai_client.ASK_PROVIDER_FREELLMAPI:
        return '' if config.freellmapi_api_key() else 'Set your FreeLLMAPI key in ⚙️ Settings to use Ask.'
    if provider == ai_client.ASK_PROVIDER_LOCAL_OPENAI:
        return '' if config.local_openai_base_url() else ('Configure the local model server in ⚙️ Settings to use the '
                                                          'local provider.')
    return f'Unknown provider: {provider}'


def provider_ready(provider, model_id):
    """(error, local_base_url, local_api_key) for the selected Ask provider/model. `error` is
    the user-facing message when a key, server URL or model is missing, else None."""
    err = provider_problem(provider)
    if err:
        return err, None, None
    local_base_url = local_api_key = None
    if provider == ai_client.ASK_PROVIDER_LOCAL_OPENAI:
        local_base_url = config.local_openai_base_url()
        local_api_key = config.local_openai_api_key()
    if not model_id:
        return 'Select a model before asking.', None, None
    return None, local_base_url, local_api_key


def build_turn(db, question, rows, history, retrieval='', *, budget=None):
    """The Quick-mode request: {'messages', 'info', 'sources', 'list_mode', 'max_tokens'}.
    `history` is the chat so far ([{'role','content'}]); `rows` the retrieved items."""
    list_mode = is_list(question)
    notes = relevant_notes(db, question)
    carried = carried_items(db, history, question)
    if carried and not topic_terms(question):
        rows = []   # pure follow-up: fresh hits for "more"/"second" are noise
    elif carried and budget:
        selected = {r['id'] for r in rows}
        carried = [r for r in carried if r['id'] not in selected]
    elif carried:
        cids = {r['id'] for r in carried}
        rows = [r for r in rows if r['id'] not in cids]
    partial = False
    if budget:
        rows = rows[:budget['max_items']]
        carried = carried[:max(0, budget['max_items'] - len(rows))]
        partial = len(rows) + len(carried) >= budget['max_items']
    context = context_block(db, rows, notes, question=question,
                            carried=carried, list_mode=list_mode)
    if budget:
        room = budget['research_chars'] - librarian.PROMPTS['agent_budgets']['control_chars']
        while len(context) + 24 > room and (notes or carried or rows):
            (notes if notes else carried if carried else rows).pop()
            partial = True
            context = context_block(db, rows, notes, question=question, carried=carried, list_mode=list_mode)
        if partial:
            context += '\n[truncated: budget]'
    info = fill(P['info_sent'], n=len(rows))
    if carried:
        info += fill(P['info_carried'], n=len(carried))
    if notes:
        info += fill(P['info_notes'], n=len(notes), files=', '.join(n['filename'] for n in notes))
    if list_mode:
        info += P['info_list']
    if retrieval:
        info += fill(P['info_retrieval'], retrieval=retrieval)
    hist = list(history)[-(HISTORY_TURNS * 2):]
    # Question both before and after the context: with only a trailing question,
    # a long context (notes especially) let the model drift back to the previous
    # turn's topic (measured 2/3 wrong on a 2-turn chat; 0/3 with this layout).
    ask = fill(P['ask'], question=question)
    if list_mode:
        ask += P['list_ask']
    messages = hist + [{'role': 'user', 'content': fill(P['turn'], question=question, context=context, ask=ask)}]
    return {'messages': messages, 'info': info, 'sources': list(carried) + list(rows),
            'context_chars': len(context),
            'notes': [n['filename'] for n in notes],
            'list_mode': list_mode, 'max_tokens': LIST_MAX_TOKENS if list_mode else None}


def answer_sources(rows, text, list_mode=False):
    """The sources shown under an answer. In list mode the pool held up to 150 candidates,
    many irrelevant: show only the cited ones."""
    if list_mode:
        by_id = {r['id']: r for r in rows}
        cited = [by_id[i] for i in cited_ids(text) if i in by_id]
        return cited or rows
    return rows


def deep_sources(db, text, consulted, *, validated=False):
    """Deep mode: the cited items, else the first 20 the agent consulted."""
    allowed = set(consulted)
    return db.get_items_by_ids([i for i in cited_ids(text) if not validated or i in allowed] or list(consulted)[:20])


EMPTY_DEEP = librarian.PROMPTS['empty']


# ── Deep mode ────────────────────────────────────────────────────────────────
def deep_setup(db, embed_key, index, *, mode='deep', should_stop=None, research_deadline=None):
    """Everything Deep mode reads from the DB before the agent starts: the stale aux-embedding
    jobs, the stored topic / note-section vectors, the profile and the system prompt.
    `obsolete` aux keys are returned for the caller to delete (a write). `infos` are the
    lines to show the user."""
    model = ai_client.EMBEDDING_MODEL
    def can_continue():
        if should_stop and should_stop():
            raise RuntimeError('Stopped.')
        return research_deadline is None or time.monotonic() < research_deadline
    jobs, obsolete = librarian.aux_jobs(
        db.data_dir, db.notes_dir, db.get_aux_hashes(model), model, can_continue)
    skip = {j['key'] for j in jobs} | set(obsolete)     # stale, or the note / topic is gone
    if mode == 'quick':
        jobs = []
    aux_rows = [{'key': a['key'], 'kind': a['kind'], 'payload': a['payload'],
                 'vec': search.blob_to_vec(a['blob'], a['dim'])}
                for a in db.get_aux_embeddings(model) if a['key'] not in skip]
    infos = []
    if not embed_key:
        jobs = []
        index = search.EmbeddingIndex([])
        infos.append('No embeddings API key: Deep mode searches by keywords only.')
    profile = librarian.read_profile(db.notes_dir)
    system = librarian.build_system_prompt(profile, db.count_by_category(), db.count_items())
    return {'jobs': jobs, 'obsolete': obsolete, 'aux_rows': aux_rows, 'index': index,
            'profile': profile, 'system': system, 'infos': infos}


_AUX_BATCH = librarian.PROMPTS['limits']['aux_batch']


def agent_budget(mode):
    budget = dict(librarian.PROMPTS['agent_budgets'][mode])
    for key, cap in (('max_rounds', ai_client._AGENT_MAX_ROUNDS), ('max_tokens', ai_client._AGENT_MAX_TOKENS)):
        if type(cap) is int and cap > 0:
            budget[key] = min(budget[key], max(8000, cap) if key == 'max_tokens' else cap)
    if ai_client._ASK_CLOUD_MIN_TOKENS > budget['max_tokens']:
        raise ValueError('Incompatible agent token limits.')
    return budget


def deep_answer(db_path, provider, model_id, system_prompt, history, question, *,
                item_index, aux_rows, aux_jobs, embed_key, embed_base,
                on_progress=None, on_aux=None, should_stop=None, propose=None, propose_category=None,
                propose_categories=None, propose_canvas=None, mode='deep', starting_turn=None,
                on_text=None, on_reset=None, on_stream=None, research_deadline=None, evidence=None):
    """One Deep-mode answer: the librarian agent researches with tools. Opens its own
    READ-ONLY connection (closed at the end) so the tools can query while the model works;
    freshly embedded aux vectors go to `on_aux(rows)` for the caller to persist.
    Returns (answer markdown, consulted item ids). Moved from AskAgentWorker.run."""
    from core.db import ReadOnlyDatabase
    on_progress = on_progress or (lambda _m: None)
    budget = agent_budget(mode)
    research_deadline = research_deadline if research_deadline is not None else time.monotonic() + budget['research_seconds']

    def check():
        if should_stop and should_stop():
            raise RuntimeError('Stopped.')

    def embed(texts):
        check()
        return ai_client.embed_texts(texts, api_key=embed_key, base_url=embed_base)

    def embed_one(text):
        if not embed_key:
            return None
        return embed([text])[0]

    def on_tool(name, args):
        if should_stop and should_stop():
            raise RuntimeError('Stopped.')
        on_progress(librarian.describe_call(name, args))

    ro = None
    try:
        aux = list(aux_rows)
        if aux_jobs and embed_key:
            on_progress(f'Indexing {len(aux_jobs)} topic and note sections (one-time)')
            fresh = []
            for start in range(0, len(aux_jobs), _AUX_BATCH):
                check()
                if time.monotonic() >= research_deadline:
                    break
                batch = aux_jobs[start:start + _AUX_BATCH]
                vecs = embed([j['text'] for j in batch])
                for job, vec in zip(batch, vecs):
                    fresh.append({'key': job['key'], 'kind': job['kind'],
                                  'hash': job['hash'], 'dim': len(vec),
                                  'blob': search.vec_to_blob(vec),
                                  'payload': job['payload']})
                    aux.append({'key': job['key'], 'kind': job['kind'],
                                'payload': job['payload'], 'vec': vec})
            if on_aux:
                on_aux(fresh)

        ro = ReadOnlyDatabase(db_path)
        lib = librarian.Librarian(ro, item_index, aux, embed_one, propose_fn=propose,
                                  category_fn=propose_category, category_batch_fn=propose_categories,
                                  canvas_fn=propose_canvas, budget=budget,
                                  should_stop=should_stop, deadline=research_deadline)
        if starting_turn:
            lib.chars = starting_turn['context_chars']
            lib.evidence.update(r['id'] for r in starting_turn['sources'])
            lib.admitted.update(lib.evidence)
            lib.delivered.update(lib.evidence)
            lib.note_sources.update(starting_turn['notes'])
            lib.consulted.extend(lib.evidence)
            messages = starting_turn['messages']
        else:
            content = prompt_files.fill(librarian.PROMPTS['turn'], question=question,
                                        orientation=lib.orientation(question))
            messages = list(history) + [{'role': 'user', 'content': content}]
        tools = librarian.TOOLS + (librarian.PROPOSE_TOOLS if propose else [])
        if propose_category or propose_categories:
            tools = tools + [t for t in librarian.CATEGORY_TOOLS
                             if (t['name'] == 'propose_category' and propose_category)
                             or (t['name'] == 'propose_categories' and propose_categories)]
            system_prompt += '\n\n' + librarian.category_instructions(ro)
        if propose_canvas:   # desktop only: the canvas reads and the proposal (projects/wiskit-canvas)
            tools = tools + librarian.CANVAS_TOOLS
            system_prompt += '\n\n' + librarian.canvas_instructions(ro)
        system_prompt += f'\n\n{mode.title()} mode: research only as needed, within {budget["max_items"]} distinct items, {budget["read_max_ids"]} IDs per read and {budget["max_rounds"]} rounds including the final answer. State partial coverage honestly.'
        if propose:   # the desktop's note tools read and write the note format (the phone's port has neither)
            system_prompt = system_prompt + '\n\n' + note_format.contract()
        text = ai_client.ask_agent(
            messages,
            provider, model_id, system_prompt=system_prompt,
            tools=tools, run_tool=lib.run_tool, on_tool=on_tool,
            max_rounds=budget['max_rounds'], max_tokens=budget['max_tokens'],
            max_tool_calls=budget['max_tool_calls'], research_deadline=research_deadline,
            on_text=on_text, on_reset=on_reset, on_stream=on_stream, should_stop=should_stop)
        if evidence is not None:
            evidence['notes'] = set(lib.note_sources)
        return text, list(dict.fromkeys(i for i in lib.consulted if i in lib.delivered))
    finally:
        if ro is not None:
            ro.close()


# ── after the answer ─────────────────────────────────────────────────────────
def answer_title(answer_md):
    """(title, body) for a saved answer: the heading the answer opens with becomes the note
    title and leaves the body (the Knowledge view shows the title above it); ('', body) when
    it opens with anything else."""
    lines = (answer_md or '').lstrip().split('\n')
    m = re.match(r'#{1,3}\s+(.+?)\s*#*\s*$', lines[0])
    if not m:
        return '', answer_md
    title = re.sub(r'\[(?:id|note)[^\]]*\]', '', m.group(1))
    title = re.sub(r'[*_`]+', '', title)
    title = re.sub(r'\s+', ' ', title).strip()[:80].strip()
    return title, '\n'.join(lines[1:]).lstrip('\n')


def save_note(db, answer_md, source_ids, *, review=None):
    """Write an answer as data/notes/<slug>.md and reindex the notes. The topic is the
    answer's opening heading, else 'Ask - <date time>'. `review` (optional validated weekly-review
    metadata) adds five whitelisted frontmatter fields. A write: Qt main thread, or the server Writer.
    Returns the path."""
    from library.obsidian_export import _slugify
    if review is not None:
        review = weekly_review.validate_metadata(review)
    db.notes_dir.mkdir(parents=True, exist_ok=True)
    topic, answer_md = answer_title(answer_md)
    topic = topic or 'Ask - ' + datetime.now().strftime('%Y-%m-%d %H:%M')
    slug = _slugify(topic)[:60].strip('-') or 'ask'
    path = db.notes_dir / f'{slug}.md'
    n = 2
    while path.exists():
        path = db.notes_dir / f'{slug}-{n}.md'
        n += 1
    ids = ','.join(str(i) for i in sorted(set(source_ids)))
    front = (f"---\ntopic: {topic}\n"
             f"created: {datetime.now().isoformat(timespec='seconds')}\n"
             f"sources: {ids}\n")
    if review is not None:
        front += (f"review_kind: {review['kind']}\n"
                  f"review_start: {review['start']}\n"
                  f"review_end: {review['end']}\n"
                  f"review_timezone: {review['timezone']}\n"
                  f"review_through: {review['through']}\n")
    front += "---\n\n"
    path.write_text(front + answer_md + "\n", encoding='utf-8')
    db.reindex_notes()
    return path


def auto_name(question):
    """The name a new chat gets from its first question ('' when there is nothing to use)."""
    return re.sub(r'\s+', ' ', question or '').strip()[:40]
