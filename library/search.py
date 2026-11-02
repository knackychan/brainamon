"""
search.py — semantic-search core for Brainamon.

Qt-free, network-free. Holds the embed-text builder, vector blob codecs, the
in-memory cosine index, and hybrid (FTS + vector) rank fusion. Embedding API
calls live in ai_client.embed_texts; persistence lives in db.py
(item_embeddings table). numpy is imported lazily (present transitively via
opencv-python).
"""

import hashlib
import itertools

# Fields folded into the embedded text, in order. ai_desc already carries the
# analysis report's Summary section (set by _on_analysis_done), so report.md
# does not need to be re-read here.
EMBED_FIELDS = ('description', 'ai_desc', 'tags', 'creator', 'transcript')

_TRANSCRIPT_CAP = 2000   # chars of transcript included
_TOTAL_CAP = 6000        # overall cap (~1.5k tokens), safe per embedding input


def build_embed_text(item: dict) -> str:
    """Concatenate the item's text fields into the string that gets embedded."""
    parts = []
    for field in EMBED_FIELDS:
        val = (item.get(field) or '').strip()
        if not val:
            continue
        if field == 'transcript':
            val = val[:_TRANSCRIPT_CAP]
        parts.append(val)
    return '\n'.join(parts)[:_TOTAL_CAP]


def text_hash(model: str, text: str) -> str:
    """Staleness key: changes whenever the model or the embedded text changes."""
    return hashlib.sha256(f"{model}\n{text}".encode('utf-8')).hexdigest()


def vec_to_blob(vec) -> bytes:
    import numpy as np
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes, dim: int):
    import numpy as np
    return np.frombuffer(blob, dtype=np.float32, count=dim)


class EmbeddingIndex:
    """In-memory cosine index over all stored item vectors.

    Built on the main thread from db.get_all_embeddings(model); brute-force
    matmul over a few thousand normalized float32 rows is well under a
    millisecond. Read-only once built — rebuild after embedding runs.
    """

    def __init__(self, rows, count: int | None = None):
        """rows: (item_id, dim, vector_blob) rows: the list db.get_all_embeddings returns, or the
        db.iter_embeddings cursor with its `count` (see from_db).

        Streaming build (plan 10-footprint A2): the vectors go straight into one preallocated
        float32 matrix, normalized in place, so the build costs about the matrix itself instead of
        every blob + a per-row list + two full copies (+20 MB instead of +54 on 3,000 items)."""
        import numpy as np
        it = iter(rows)
        first = next(it, None)
        dim = first[1] if first else 0
        n = len(rows) if count is None else count
        m = np.empty((n if first else 0, dim), dtype=np.float32)
        ids = np.empty(m.shape[0], dtype=np.int64)
        k = 0
        for item_id, d, blob in itertools.chain((first,) if first else (), it):
            if d != dim or len(blob) != dim * 4:
                continue   # skip stale/corrupt rows rather than fail the index
            if k == m.shape[0]:   # rows added between the count and the read
                grow = max(16, k // 8)
                m = np.concatenate([m, np.empty((grow, dim), dtype=np.float32)])
                ids = np.concatenate([ids, np.empty(grow, dtype=np.int64)])
            m[k] = blob_to_vec(blob, dim)
            ids[k] = item_id
            k += 1
        if k < m.shape[0]:
            m, ids = m[:k].copy(), ids[:k].copy()
        for s in range(0, k, 512):   # in blocks: np.linalg.norm squares a full copy of its input
            blk = m[s:s + 512]
            norms = np.linalg.norm(blk, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            blk /= norms
        self._ids = ids
        self._matrix = m
        self._row_of = {int(i): n for n, i in enumerate(self._ids)}

    @classmethod
    def from_db(cls, db, model: str) -> 'EmbeddingIndex':
        """The index over `db`'s vectors for `model`, read with a cursor (a reader or the Writer's db)."""
        return cls(db.iter_embeddings(model), count=db.count_embeddings(model))

    def __len__(self):
        return int(self._ids.shape[0])

    def has(self, item_id: int) -> bool:
        return int(item_id) in self._row_of

    def ids(self) -> list:
        """All indexed item ids, row order (parallel to matrix())."""
        return [int(i) for i in self._ids]

    def matrix(self):
        """The L2-normalized (n, dim) float32 matrix. Treat as read-only."""
        return self._matrix

    def _rank(self, query_vec, k: int, exclude_id=None):
        import numpy as np
        if len(self) == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32).ravel()
        n = np.linalg.norm(q)
        if n == 0:
            return []
        # einsum, not `@`: the first BLAS call makes OpenBLAS keep a 32 MB work buffer for the life of
        # the process (plan 10-footprint A2); einsum's own loop takes about 0.6 ms on 3,000 x 1536
        scores = np.einsum('ij,j->i', self._matrix, q / n)
        if exclude_id is not None and self.has(exclude_id):
            scores[self._row_of[int(exclude_id)]] = -2.0
        k = min(k, len(self))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(self._ids[i]), float(scores[i])) for i in top]

    def topk(self, query_vec, k: int = 100) -> list:
        """[(item_id, cosine_score)] best-first for an embedded query vector."""
        return self._rank(query_vec, k)

    def similar_to(self, item_id: int, k: int = 8) -> list:
        """[(item_id, cosine_score)] of the items nearest to an indexed item."""
        if not self.has(item_id):
            return []
        return self._rank(self._matrix[self._row_of[int(item_id)]], k, exclude_id=item_id)


def hybrid_rank(fts_ids: list, vec_hits: list, limit: int = 30) -> list:
    """Fuse a bm25 id list and a [(id, score)] vector list via Reciprocal Rank
    Fusion: score(id) = sum of 1/(60 + rank) over the lists it appears in.
    Either list may be empty, degrading gracefully to the other."""
    scores = {}
    for rank, item_id in enumerate(fts_ids):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
    for rank, (item_id, _score) in enumerate(vec_hits):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return [item_id for item_id, _ in ranked[:limit]]
