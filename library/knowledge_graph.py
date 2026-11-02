"""
knowledge_graph.py - Qt-free spherical k-means for the knowledge map (library/map_engine.py) and the
atomic cache save. Lazy numpy (same convention as search.py). No DB access, no Qt, no network.

Topic identity and staleness live in map_engine (permanent ids, summary_basis fingerprints); this
module only clusters and writes the file.
"""
import json
from pathlib import Path

K_DIVISOR, K_MIN, K_MAX = 40, 12, 60   # k = clamp(n // K_DIVISOR, K_MIN, K_MAX)
MIN_CLUSTER_SIZE = 3
KMEANS_ITERS = 25
KMEANS_SEED = 42


def kmeans(matrix, k, iters=KMEANS_ITERS, seed=KMEANS_SEED):
    """Spherical k-means over L2-normalized rows. Returns labels array (len n).

    matrix: float32 (n, dim), rows already normalized (EmbeddingIndex guarantees it).
    Cosine similarity == dot product on normalized vectors, so assignment is
    argmax(matrix @ centroids.T). Deterministic via seeded rng.
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    n = matrix.shape[0]
    centroids = matrix[rng.choice(n, size=k, replace=False)].copy()
    labels = np.zeros(n, dtype=np.int64)
    for it in range(iters):
        sims = matrix @ centroids.T                 # (n, k)
        new_labels = sims.argmax(axis=1)
        if it > 0 and (new_labels == labels).all():
            break
        labels = new_labels
        for c in range(k):
            members = matrix[labels == c]
            if len(members) == 0:
                # dead centroid: reseed to the point worst-served by current centroids
                worst = sims.max(axis=1).argmin()
                centroids[c] = matrix[worst]
                continue
            m = members.mean(axis=0)
            norm = np.linalg.norm(m)
            centroids[c] = m / norm if norm > 0 else m
    return labels


def cluster_items(ids, matrix, min_size=MIN_CLUSTER_SIZE):
    """[[item_id, ...], ...] sorted largest-first; clusters under min_size dropped."""
    import numpy as np
    n = len(ids)
    if n < min_size * 2:
        return []
    k = max(K_MIN, min(K_MAX, n // K_DIVISOR))
    k = min(k, n)                                    # never more centroids than points
    labels = kmeans(np.asarray(matrix), k)
    out = {}
    for item_id, lab in zip(ids, labels):
        out.setdefault(int(lab), []).append(int(item_id))
    clusters = [sorted(v) for v in out.values() if len(v) >= min_size]
    return sorted(clusters, key=len, reverse=True)


def save_graph_cache(path, cache) -> None:
    p = Path(path)
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(p)                                        # atomic-ish on same volume
