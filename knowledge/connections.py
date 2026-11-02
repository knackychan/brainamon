"""
connections.py — proactive Connections detection core for Brainamon.

Qt-free, network-free, lazy numpy (mirrors search.py). Proposes bridge
candidates (high-similarity item pairs across different embedding clusters)
and drift clusters (recent saves piling into one theme with no covering note).
Candidates are proposed here with pure numpy; the Claude gate in
ui/connections_worker.py decides what is actually shown as a card. Raw bridge
candidates are never rendered ungated.

All thresholds are module constants, expected to be tuned against the real
library: if cards skew obvious, raise _BRIDGE_FLOOR; if scans come back empty,
lower it.
"""

import re
from pathlib import Path

from library import search as search_core

_K_CLUSTERS = 20          # k-means k (n=2526 -> ~125 items/cluster)
_KMEANS_SEED = 7          # deterministic clustering across runs
_KMEANS_ITERS = 25        # hard cap; converges long before this
_MIN_TEXT = 200           # min build_embed_text length for bridge eligibility
_BRIDGE_FLOOR = 0.45      # min cosine for a bridge candidate pair
_BRIDGE_CANDIDATES = 12   # max candidates sent to the gate per scan
_DRIFT_WINDOW_DAYS = 30   # "recent" for drift
_DRIFT_MIN_ITEMS = 6      # recent items in one cluster to count as drift
_DRIFT_MAX_CARDS = 3      # max drift cards per scan


def bridge_key(a_id: int, b_id: int) -> str:
    """Stable dismissal/dedupe key for a pair, order-independent."""
    lo, hi = sorted((int(a_id), int(b_id)))
    return f"{lo}-{hi}"


def label_key(label: str) -> str:
    """Dismissal key for a drift card: slug of its (gate or tag) label."""
    s = re.sub(r'[^a-z0-9]+', '-', (label or '').strip().lower()).strip('-')
    return 'drift-' + (s[:60] or 'theme')


def load_note_ledger(notes_dir):
    """Parse every note's `sources:` frontmatter line under notes_dir.

    Returns (noted_ids, noted_pairs): the union of all cited item ids, and the
    set of same-note id pairs as frozensets. This is the "already synthesized"
    ledger — an accepted card's new note lands here and self-excludes the pair
    from every future scan.
    """
    noted_ids, noted_pairs = set(), set()
    notes_dir = Path(notes_dir)
    if not notes_dir.exists():
        return noted_ids, noted_pairs
    for p in notes_dir.glob('*.md'):
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            continue
        m = re.search(r'^sources:\s*(.*)$', text[:2000], flags=re.MULTILINE)
        if not m:
            continue
        ids = sorted({int(t) for t in m.group(1).split(',') if t.strip().isdigit()})
        noted_ids.update(ids)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                noted_pairs.add(frozenset((a, b)))
    return noted_ids, noted_pairs


def kmeans(matrix, k=_K_CLUSTERS, seed=_KMEANS_SEED, iters=_KMEANS_ITERS):
    """Seeded k-means over L2-normalized rows. Returns (labels, centroids).

    Deterministic across runs (fixed seed) so cluster identities behave stably
    between scans. Cosine on normalized rows is a plain dot product, so the
    assignment step is one matmul; milliseconds at n=2526.
    """
    import numpy as np
    n = int(matrix.shape[0])
    if n == 0:
        return np.empty(0, dtype=np.int64), matrix
    k = max(1, min(int(k), n))
    rng = np.random.default_rng(seed)
    centroids = matrix[rng.choice(n, size=k, replace=False)].copy()
    labels = np.full(n, -1, dtype=np.int64)
    for _i in range(iters):
        new_labels = np.argmax(matrix @ centroids.T, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for c in range(k):
            members = matrix[labels == c]
            if len(members):
                v = members.mean(axis=0)
                norm = np.linalg.norm(v)
                centroids[c] = v / norm if norm else v
    return labels, centroids


def find_bridges(ids, matrix, labels, items_by_id, noted_pairs, dismissed_keys):
    """Bridge candidates: best cross-cluster pairs by cosine, hub/noise-guarded.

    Guards (the filtering IS the feature — raw nearest-pairs are noise):
      - both items have >= _MIN_TEXT chars of build_embed_text (thin generic
        descriptions sit near every centroid: the hubness problem);
      - different clusters only (cross-domain is where insight lives);
      - different creators (the same voice twice is not a connection);
      - not already co-cited in a note (noted_pairs: frozenset pairs);
      - not dismissed (dismissed_keys: bridge_key strings);
      - each item appears in at most one candidate (greedy, best pair first).

    Returns at most _BRIDGE_CANDIDATES dicts {key, a_id, b_id, score}, best
    first. ids/matrix/labels are parallel (EmbeddingIndex.ids()/matrix() plus
    kmeans labels). items_by_id maps id -> full item dict.
    """
    import numpy as np
    n = len(ids)
    if n < 2:
        return []
    eligible = np.zeros(n, dtype=bool)
    for row, item_id in enumerate(ids):
        item = items_by_id.get(int(item_id))
        if item and len(search_core.build_embed_text(item)) >= _MIN_TEXT:
            eligible[row] = True
    sims = matrix @ matrix.T                           # (n, n) float32, ~25 MB at n=2526
    ok = (labels[:, None] != labels[None, :])          # different clusters only
    ok &= eligible[:, None] & eligible[None, :]
    ok &= sims >= _BRIDGE_FLOOR
    ok &= np.triu(np.ones((n, n), dtype=bool), k=1)    # upper triangle: each pair once
    rows, cols = np.nonzero(ok)
    if not len(rows):
        return []
    order = np.argsort(-sims[rows, cols])
    used, out = set(), []
    for idx in order:
        r, c = int(rows[idx]), int(cols[idx])
        a_id, b_id = int(ids[r]), int(ids[c])
        if a_id in used or b_id in used:
            continue
        key = bridge_key(a_id, b_id)
        if key in dismissed_keys or frozenset((a_id, b_id)) in noted_pairs:
            continue
        creator_a = (items_by_id[a_id].get('creator') or '').strip().lower()
        creator_b = (items_by_id[b_id].get('creator') or '').strip().lower()
        if creator_a and creator_a == creator_b:
            continue
        used.update((a_id, b_id))
        out.append({'key': key, 'a_id': a_id, 'b_id': b_id,
                    'score': float(sims[r, c])})
        if len(out) >= _BRIDGE_CANDIDATES:
            break
    return out


def _top_tags(member_ids, items_by_id, n=3):
    """Most frequent tags among the members — the fallback drift label."""
    from collections import Counter
    counts = Counter()
    for item_id in member_ids:
        item = items_by_id.get(item_id) or {}
        for tag in (item.get('tags') or '').split(','):
            tag = tag.strip().lower()
            if tag:
                counts[tag] += 1
    return [t for t, _c in counts.most_common(n)]


def find_drift(ids, labels, items_by_id, noted_ids, now_ms):
    """Drift: clusters where >= _DRIFT_MIN_ITEMS items were created inside
    _DRIFT_WINDOW_DAYS and fewer than half of those are cited by any note.

    Returns at most _DRIFT_MAX_CARDS dicts {member_ids, top_tags}, biggest
    first. Dismissal filtering happens later, at card-build time in the panel:
    a drift card's key is the slug of its final label (label_key), which does
    not exist until the gate labels the cluster.
    """
    cutoff = now_ms - _DRIFT_WINDOW_DAYS * 86400 * 1000
    by_cluster = {}
    for row, item_id in enumerate(ids):
        item = items_by_id.get(int(item_id)) or {}
        if (item.get('created') or 0) >= cutoff:
            by_cluster.setdefault(int(labels[row]), []).append(int(item_id))
    clusters = []
    for members in by_cluster.values():
        if len(members) < _DRIFT_MIN_ITEMS:
            continue
        covered = sum(1 for i in members if i in noted_ids)
        if covered * 2 >= len(members):
            continue
        clusters.append(members)
    clusters.sort(key=len, reverse=True)
    return [{'member_ids': m, 'top_tags': _top_tags(m, items_by_id)}
            for m in clusters[:_DRIFT_MAX_CARDS]]


# ── the Claude gate (moved from ui/connections_worker.py) and the scan steps (moved from
# ui/connections_panel.py), shared with the V6 server (plan 08) ───────────────
import json as _json
import time as _time

GATE_MAX_TOKENS = 1500
GATE_EXCERPT = 800         # chars of item text per side sent to the gate
DISMISS_DRIFT_DAYS = 30    # drift dismissals expire; bridge ones are permanent
CARDS_KEY = 'connections_cards'
DISMISSED_KEY = 'connections_dismissed'
LAST_SCAN_KEY = 'connections_last_scan'

GATE_SYSTEM = (
    "You are a strict curator of insight cards for a personal content library. "
    "You are given candidate BRIDGES (pairs of saved items linked by embedding "
    "similarity across different topic clusters) and DRIFT clusters (recent "
    "saves on one theme). For each bridge decide whether the two items share a "
    "genuinely non-obvious underlying idea across domains. REJECT pairs whose "
    "only link is platform, format, or creator style ('both are Reels about "
    "content creation' is a reject). Keep only links a thoughtful person would "
    "find interesting. For each kept bridge write ONE sentence naming the "
    "shared idea and touching both items. For each drift cluster write a 2-5 "
    "word theme label. Reply with ONLY a JSON object, no prose, shaped "
    'exactly:\n'
    '{"bridges": {"<key>": {"verdict": "keep", "insight": "<sentence>"}}, '
    '"drifts": {"<key>": {"label": "<2-5 words>"}}}\n'
    'Use "verdict": "reject" (insight may be empty) for rejected bridges. '
    "Every input key must appear in the output."
)


def item_title(item: dict) -> str:
    return (item.get('ai_desc') or item.get('short_desc')
            or item.get('description') or item.get('creator')
            or '(untitled)').strip().split('\n')[0][:90]


def item_excerpt(item: dict) -> str:
    text = (item.get('ai_desc') or item.get('description')
            or item.get('transcript') or '').strip()
    return text[:GATE_EXCERPT]


def gate_prompt(payload: dict) -> str:
    """payload: {'bridges': [{key, a: {id, title, excerpt}, b: {...}}],
    'drifts': [{key, count, titles: [...], top_tags: [...]}]}"""
    lines = []
    for b in payload.get('bridges', []):
        lines.append(
            f"BRIDGE {b['key']}\n"
            f"  item A [id {b['a']['id']}] {b['a']['title']}\n"
            f"    {b['a']['excerpt']}\n"
            f"  item B [id {b['b']['id']}] {b['b']['title']}\n"
            f"    {b['b']['excerpt']}\n"
        )
    for d in payload.get('drifts', []):
        titles = '\n    '.join(d['titles'])
        lines.append(
            f"DRIFT {d['key']}\n"
            f"  {d['count']} recent saves. "
            f"Frequent tags: {', '.join(d['top_tags']) or '(none)'}\n"
            f"  Sample titles:\n    {titles}\n"
        )
    return '\n'.join(lines)


def parse_gate(text: str) -> dict:
    """{'bridges': {key: insight}, 'drifts': {key: label}} from the gate reply; raises when
    there is no JSON object."""
    m = re.search(r'\{.*\}', text or '', flags=re.DOTALL)
    if not m:
        raise ValueError('no JSON object in the model reply')
    data = _json.loads(m.group(0))
    bridges, drifts = {}, {}
    for key, v in (data.get('bridges') or {}).items():
        if isinstance(v, dict) and v.get('verdict') == 'keep' and v.get('insight'):
            bridges[key] = str(v['insight']).strip()
    for key, v in (data.get('drifts') or {}).items():
        if isinstance(v, dict) and v.get('label'):
            drifts[key] = str(v['label']).strip()
    return {'bridges': bridges, 'drifts': drifts}


def candidates(index, items_by_id: dict, notes_dir, dismissed_keys: set, now_ms: int = None):
    """Cluster the embedded items and propose bridges and drifts. Returns (pending, payload):
    `pending` feeds cards_from_gate, `payload` is the gate input."""
    ids = index.ids()
    noted_ids, noted_pairs = load_note_ledger(notes_dir)
    labels, _cents = kmeans(index.matrix())
    bridges = find_bridges(ids, index.matrix(), labels, items_by_id, noted_pairs, dismissed_keys)
    drifts = find_drift(ids, labels, items_by_id, noted_ids, now_ms or int(_time.time() * 1000))
    payload = {'bridges': [], 'drifts': []}
    for b in bridges:
        a, bb = items_by_id[b['a_id']], items_by_id[b['b_id']]
        payload['bridges'].append({
            'key': b['key'],
            'a': {'id': a['id'], 'title': item_title(a), 'excerpt': item_excerpt(a)},
            'b': {'id': bb['id'], 'title': item_title(bb), 'excerpt': item_excerpt(bb)},
        })
    for i, d in enumerate(drifts):
        payload['drifts'].append({
            'key': f'd{i}',   # correlation id; the card key comes from the label
            'count': len(d['member_ids']),
            'titles': [item_title(items_by_id[m]) for m in d['member_ids'][:6] if m in items_by_id],
            'top_tags': d['top_tags'],
        })
    pending = {'bridges': bridges, 'drifts': drifts, 'items_by_id': items_by_id,
               'dismissed_keys': dismissed_keys}
    return pending, payload


def drift_card(d: dict, label: str, items_by_id: dict) -> dict:
    return {
        'kind': 'drift',
        'key': label_key(label),
        'text': (f"{len(d['member_ids'])} recent saves about \"{label}\" "
                 "- no note covers them yet. Synthesize one?"),
        'item_ids': d['member_ids'],
        'items': [{'id': m, 'title': item_title(items_by_id[m])}
                  for m in d['member_ids'][:6] if m in items_by_id],
    }


def cards_from_gate(pending: dict, res) -> list:
    """The cards a scan adds: gate-kept bridges, and drifts with the gate's label. When the
    gate failed (`res` None) only drifts, with tag-derived labels: bridges are never shown
    ungated."""
    items_by_id = pending['items_by_id']
    cards = []
    if res is not None:
        for b in pending['bridges']:
            insight = (res.get('bridges') or {}).get(b['key'])
            if not insight:
                continue           # rejected by the gate
            cards.append({
                'kind': 'bridge', 'key': b['key'], 'text': insight,
                'item_ids': [b['a_id'], b['b_id']],
                'items': [{'id': i, 'title': item_title(items_by_id[i])} for i in (b['a_id'], b['b_id'])],
            })
    for i, d in enumerate(pending['drifts']):
        label = (((res or {}).get('drifts') or {}).get(f'd{i}')
                 or ', '.join(d['top_tags']) or 'a recent theme')
        card = drift_card(d, label, items_by_id)
        if card['key'] not in pending['dismissed_keys']:
            cards.append(card)
    return cards


def merge_cards(existing: list, cards: list) -> tuple:
    """(cards, n_new): the new cards first, existing keys kept once."""
    have = {c['key'] for c in existing}
    new = [c for c in cards if c['key'] not in have]
    return new + list(existing), len(new)


def prune_dismissed(entries: list, now_ms: int = None) -> list:
    """The dismissal ledger without expired drift entries (bridge keys are permanent)."""
    cutoff = (now_ms or int(_time.time() * 1000)) - DISMISS_DRIFT_DAYS * 86400 * 1000
    return [e for e in entries
            if not (str(e.get('key', '')).startswith('drift-') and e.get('ts', 0) < cutoff)]


def card_topic(card: dict) -> str:
    """The note topic an accepted card is synthesized under."""
    return card['text'][:60].rstrip(' .,?')
