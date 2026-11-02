// Smart search on the phone: the question's embedding against the mirror's int8 vectors
// (vectors.bin; cosine does not depend on each row's scale), fused with the keyword ranking by
// library/search.py hybrid_rank (Reciprocal Rank Fusion). Same numbers as server/routes/smart.py.
// Run by Node in the tests (type stripping): no parameter properties, no imports.

export type Hit = [number, number]                  // [item id, cosine]
export interface VectorRows { ids: number[]; dim: number; mat: Int8Array; norms: Float32Array }

export const SMART_LIMIT = 150

// search.hybrid_rank: score(id) = sum of 1 / (60 + rank) over the lists it is in; ties keep the
// first-seen order (keyword hits first), as Python's stable sort does
export function hybridRank(ftsIds: number[], vecHits: Hit[], limit = 30): number[] {
  const scores = new Map<number, number>()
  ftsIds.forEach((id, rank) => scores.set(id, (scores.get(id) ?? 0) + 1 / (60 + rank)))
  vecHits.forEach(([id], rank) => scores.set(id, (scores.get(id) ?? 0) + 1 / (60 + rank)))
  return [...scores].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([id]) => id)
}

// EmbeddingIndex.topk: [(id, cosine)] best first for an embedded question
export function topk(v: VectorRows, query: ArrayLike<number>, k: number): Hit[] {
  const { dim, mat, norms } = v
  if (query.length !== dim) return []        // another embedding model: keyword ranking only
  let qn = 0
  for (let j = 0; j < dim; j++) qn += query[j] * query[j]
  qn = Math.sqrt(qn)
  if (!qn || !v.ids.length) return []
  const out: Hit[] = new Array(v.ids.length)
  for (let r = 0; r < v.ids.length; r++) {
    let s = 0
    for (let j = 0, b = r * dim; j < dim; j++) s += mat[b + j] * query[j]
    out[r] = [v.ids[r], s / (norms[r] * qn)]
  }
  out.sort((a, b) => b[1] - a[1])
  return out.slice(0, Math.min(k, out.length))
}
