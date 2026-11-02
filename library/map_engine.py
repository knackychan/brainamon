"""map_engine.py - the knowledge map: stable AI topics kept in data/obsidian_graph.json, schema 2
(docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md, decisions 5 and 6).

The map is Brainamon's; an Obsidian vault is a rendering of it. A topic key is a permanent id
('t-1', 't-2', ...) and `next_id` never reuses one, retired ids included. Each topic holds `title`,
`synthesis` (the written summary), `member_ids`, `name` (the recorded page name, '' until the first
summary), `summary_basis` ({member id: text fingerprint} captured when the summary was written; None
for a topic migrated from schema 1, whose basis nothing proves) and `stale`, which recompute_stale
derives and nothing trusts from disk. The top level keeps `model`, the embedding model: a change
forces a rebuild.

Pure: no DB, no network, no threads; numpy lazily, like search.py. Callers hold the map lock
(server/map_service.py MAP_LOCK) around load + change + save.
"""
import json
from pathlib import Path

from library import knowledge_graph, search

VERSION = 2
CACHE_NAME = 'obsidian_graph.json'
ASSIGN_MIN_SCORE = 0.35        # cosine floor for joining a topic (the Related floor, obsidian_export.RELATED_MIN_SCORE)
STALE_PERCENT = 25             # drift at or above this share of summary_basis makes a summary stale


def cache_path(data_dir) -> Path:
    return Path(data_dir) / CACHE_NAME


# ── fingerprints ─────────────────────────────────────────────────────────────
def fingerprint(model: str, item: dict) -> str:
    """The fingerprint of the item's current text: search.text_hash over build_embed_text. Free, and
    current; never read from item_embeddings.text_hash (that is the text last embedded, not the text now)."""
    return search.text_hash(model, search.build_embed_text(item))


def fingerprints(model: str, items) -> dict:
    return {int(it['id']): fingerprint(model, it) for it in items}


# ── the cache ────────────────────────────────────────────────────────────────
def empty(model: str = '') -> dict:
    return {'version': VERSION, 'model': model, 'next_id': 1, 'clusters': {}}


def _topic(title='', synthesis='', member_ids=(), name='', summary_basis=None) -> dict:
    return {'title': str(title or ''), 'synthesis': str(synthesis or ''),
            'member_ids': sorted({int(i) for i in member_ids}), 'name': str(name or ''),
            'summary_basis': summary_basis, 'stale': False}


def _num(tid: str) -> int:
    try:
        return int(str(tid).split('-', 1)[1])
    except (IndexError, ValueError):
        return 0


def migrate_v1(data: dict) -> dict:
    """Schema 1 (membership-hash keys) -> 2, once: ids in size order, largest first; title, summary and
    members kept; summary_basis unknown (None), so every migrated topic with a summary reads as stale."""
    old = data.get('clusters') or {}
    order = sorted(old.items(), key=lambda kv: (-len(kv[1].get('member_ids') or []), kv[0]))
    cache = empty(str(data.get('model') or ''))
    for n, (_key, c) in enumerate(order, 1):
        cache['clusters'][f't-{n}'] = _topic(c.get('title'), c.get('synthesis'), c.get('member_ids') or [])
    cache['next_id'] = len(order) + 1
    return cache


def load(path) -> dict:
    """The cache, migrated to schema 2 in memory (the caller saves). Missing or corrupt: empty."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict) or not isinstance(data.get('clusters'), dict):
        return empty()
    if data.get('version') != VERSION:
        return migrate_v1(data)
    cache = empty(str(data.get('model') or ''))
    try:
        cache['next_id'] = max(1, int(data.get('next_id') or 1))
    except (TypeError, ValueError):
        cache['next_id'] = 1
    for tid, c in data['clusters'].items():
        if not isinstance(c, dict):
            continue
        basis = c.get('summary_basis')
        basis = {str(k): str(v) for k, v in basis.items()} if isinstance(basis, dict) else None
        cache['clusters'][str(tid)] = _topic(c.get('title'), c.get('synthesis'), c.get('member_ids') or [],
                                             c.get('name'), basis)
    # the floor: never hand an id out twice, even after a hand-edited file
    cache['next_id'] = max(cache['next_id'], 1 + max((_num(t) for t in cache['clusters']), default=0))
    return cache


def save(path, cache: dict) -> None:
    knowledge_graph.save_graph_cache(path, cache)


def new_id(cache: dict) -> str:
    tid = f"t-{cache['next_id']}"
    cache['next_id'] += 1
    return tid


def page_name(title: str, tid: str) -> str:
    """'<slug of the first summary title>-t<n>': the id keeps two topics with one title apart."""
    from library.obsidian_export import _slugify
    return f"{_slugify((title or '')[:60])}-{tid.replace('-', '')}"


# ── staleness ────────────────────────────────────────────────────────────────
def status(topic: dict) -> str:
    """'new' (no summary yet: no page), 'stale' or 'fresh'."""
    if not topic.get('synthesis'):
        return 'new'
    return 'stale' if topic.get('stale') else 'fresh'


def drift(topic: dict, fps: dict) -> tuple:
    """(added, removed, changed) members against summary_basis; (0, 0, 0) without a basis."""
    basis = topic.get('summary_basis')
    if not isinstance(basis, dict):
        return 0, 0, 0
    members = {int(i) for i in topic['member_ids']}
    based = {int(k) for k in basis}
    added = len(members - based)
    removed = len(based - members)
    changed = sum(1 for i in members & based if fps.get(i) != basis[str(i)])
    return added, removed, changed


def is_stale(topic: dict, fps: dict) -> bool:
    if not topic.get('synthesis'):
        return False
    basis = topic.get('summary_basis')
    if not isinstance(basis, dict):
        return True                              # migrated: nothing proves which text wrote the summary
    a, r, c = drift(topic, fps)
    n = len(basis)
    return n == 0 or (a + r + c) * 100 >= STALE_PERCENT * n


def recompute_stale(cache: dict, fps: dict) -> None:
    for t in cache['clusters'].values():
        t['stale'] = is_stale(t, fps)


def needs_rebuild(cache: dict, model: str) -> bool:
    """No topics yet (the first build), or the embedding model changed."""
    return not cache['clusters'] or cache.get('model') != model


# ── free maintenance ─────────────────────────────────────────────────────────
def assign(cache: dict, idx, fps: dict, live_ids) -> bool:
    """Drop members deleted from the library; give each embedded item that is in no topic to the topic
    whose centroid (mean of the members' stored vectors, computed here, never stored) is nearest, when the
    cosine reaches ASSIGN_MIN_SCORE; otherwise it waits for the next rebuild. Then recompute staleness.
    True when membership changed."""
    import numpy as np
    live = {int(i) for i in live_ids}
    changed = False
    assigned = set()
    for t in cache['clusters'].values():
        kept = [i for i in t['member_ids'] if i in live]
        if len(kept) != len(t['member_ids']):
            t['member_ids'], changed = kept, True
        assigned.update(kept)
    if cache['clusters'] and idx is not None and len(idx):
        ids = idx.ids()
        mat = idx.matrix()
        row_of = {i: n for n, i in enumerate(ids)}
        tids, cents = [], []
        for tid, t in cache['clusters'].items():
            rows = [row_of[i] for i in t['member_ids'] if i in row_of]
            if not rows:
                continue
            c = mat[rows].mean(axis=0)
            norm = np.linalg.norm(c)
            if norm:
                tids.append(tid)
                cents.append(c / norm)
        if cents:
            cm = np.vstack(cents)
            for i in ids:
                if i in assigned or i not in live:
                    continue
                sims = np.einsum('ij,j->i', cm, mat[row_of[i]])    # einsum, not @: no BLAS buffer (search.py)
                best = int(sims.argmax())
                if float(sims[best]) >= ASSIGN_MIN_SCORE:
                    t = cache['clusters'][tids[best]]
                    t['member_ids'] = sorted(t['member_ids'] + [int(i)])
                    assigned.add(int(i))
                    changed = True
    recompute_stale(cache, fps)
    return changed


# ── paid, explicit: rebuild and summaries ────────────────────────────────────
def rebuild(cache: dict, clusters: list, fps: dict, model: str) -> dict:
    """`clusters`: knowledge_graph.cluster_items' member lists. Largest clusters first, each takes the id of
    the old topic it overlaps most when at least half of its members came from there; each old id is used
    once. Unmatched clusters get new ids; old ids without a successor retire (never reused). A carried
    topic keeps title, summary, name and basis; the drift rule then decides stale. Returns the new cache."""
    old = cache['clusters']
    out = empty(model)
    out['next_id'] = cache['next_id']
    used = set()
    for members in sorted(clusters, key=len, reverse=True):
        mset = {int(i) for i in members}
        best, best_n = None, 0
        for tid, t in old.items():
            if tid in used:
                continue
            n = len(mset & set(t['member_ids']))
            if n > best_n:
                best, best_n = tid, n
        if best is not None and best_n * 2 >= len(mset):
            used.add(best)
            t = old[best]
            out['clusters'][best] = _topic(t['title'], t['synthesis'], mset, t['name'], t['summary_basis'])
        else:
            out['clusters'][new_id(out)] = _topic(member_ids=mset)
    recompute_stale(out, fps)
    return out


def summary_jobs(cache: dict, items_by_id: dict, fps: dict, excerpts_for) -> list:
    """One job per topic that is new or stale: {'topic_id', 'member_ids', 'basis', 'excerpts'}. The inputs
    are captured now; merge_summary later writes only this topic's text and this basis."""
    jobs = []
    for tid, t in cache['clusters'].items():
        if status(t) == 'fresh':
            continue
        rows = [items_by_id[i] for i in t['member_ids'] if i in items_by_id]
        ex = excerpts_for(rows)
        if not ex:
            continue
        jobs.append({'topic_id': tid, 'member_ids': list(t['member_ids']),
                     'basis': {str(r['id']): fps[int(r['id'])] for r in rows if int(r['id']) in fps},
                     'excerpts': ex})
    return jobs


def merge_summary(cache: dict, job: dict, title: str, synthesis: str, fps: dict) -> bool:
    """Write one answered summary into the latest cache: title, synthesis, summary_basis (the captured
    fingerprints) and, for a first summary, the page name. Membership stays as maintenance left it;
    staleness is recomputed against the current text, so a summary written from text that changed
    meanwhile shows as stale at once. False: the topic retired meanwhile, the answer is dropped."""
    t = cache['clusters'].get(job['topic_id'])
    if t is None:
        return False
    t['title'], t['synthesis'] = str(title or ''), str(synthesis or '')
    t['summary_basis'] = {str(k): str(v) for k, v in dict(job.get('basis') or {}).items()}
    if not t['name']:
        t['name'] = page_name(t['title'], job['topic_id'])
    t['stale'] = is_stale(t, fps)
    return True


# ── views ────────────────────────────────────────────────────────────────────
def stats(cache: dict) -> dict:
    topics = cache['clusters']
    return {'topics': len(topics),
            'stale': sum(1 for t in topics.values() if status(t) == 'stale'),
            'pending': sum(1 for t in topics.values() if status(t) == 'new')}


def topic_rows(cache: dict) -> list:
    """[{id, title, name, count, status, synthesis, member_ids}] largest first: Wiskit, MCP, the tab."""
    rows = [{'id': tid, 'title': t['title'], 'name': t['name'], 'count': len(t['member_ids']),
             'status': status(t), 'synthesis': t['synthesis'], 'member_ids': list(t['member_ids'])}
            for tid, t in cache['clusters'].items()]
    return sorted(rows, key=lambda r: (-r['count'], _num(r['id'])))
