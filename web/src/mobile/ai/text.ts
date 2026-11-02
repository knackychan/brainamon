// Keyword search on the phone, ranked like the desktop's SQLite FTS5 (PLAN.md Phase 5): the same
// content words as core/db.py fts_terms, each word a prefix match ORed with the others (the
// desktop's fts_match_query), scored with FTS5's bm25 (k1 1.2, b 0.75, every column weight 1, the
// document length over all indexed columns). The tokenizer follows FTS5's default unicode61:
// letters, digits and private-use characters make tokens, lowercased, Latin diacritics removed.
// tests/test_phone_ai.py checks the ranking against SQLite on a fixture library.
// Run by Node in the tests (type stripping): no parameter properties, imports with .ts.

// core/db.py _FTS_STOPWORDS (tests/test_phone_ai.py checks the two lists agree)
export const STOPWORDS = new Set(`
a an the and or of to for in on at by with from into about as is are was were be been
i me my we our us you your he she they them his her their it its this that these those there here
do does did have has had can could would should will shall may might must
what which who whom whose how why when where
give find show tell help please want need looking seeking related any some all
content stuff things up
le la les de des du un une et ou pour avec sur dans est que qui quoi comment
`.split(/\s+/).filter(Boolean))

// Python's \w (str.isalnum or _), for the ports of Python regexes
export const W = '[\\p{L}\\p{N}_]'
const WORDS = /[\p{L}\p{N}_]+/gu
const cps = (s: string) => (s.length < 2 ? s.length : [...s].length)

// db.fts_terms: the content words of free text, lowercased, deduped in order
export function ftsTerms(query: string): string[] {
  const words = (query || '').toLowerCase().match(WORDS) ?? []
  let keep = words.filter(w => !STOPWORDS.has(w) && cps(w) > 1)
  if (!keep.length) {
    keep = words.filter(w => cps(w) > 1)
    if (!keep.length) keep = words
  }
  return [...new Set(keep)]
}

// ── the unicode61 tokenizer ──────────────────────────────────────────────────
const TOKEN = /[\p{L}\p{N}\p{Co}]+/gu
const ASCII = /^[\x00-\x7f]*$/
const fold = new Map<string, string>()
function foldChar(c: string): string {
  let f = fold.get(c)
  if (f === undefined) {
    const d = c.normalize('NFD')
    f = d.length > 1 && /^[a-z]$/.test(d[0]) && /^\p{M}+$/u.test(d.slice(1)) ? d[0] : c
    fold.set(c, f)
  }
  return f
}
export function tokens(text: string): string[] {
  const out = (text || '').toLowerCase().match(TOKEN) ?? []
  for (let i = 0; i < out.length; i++) {
    const t = out[i]
    if (!ASCII.test(t)) { let s = ''; for (const c of t) s += c.charCodeAt(0) < 128 ? c : foldChar(c); out[i] = s }
  }
  return out
}

// ── bm25 over a few columns ──────────────────────────────────────────────────
const K1 = 1.2, B = 0.75

export class Bm25 {
  ids: number[] = []                       // document ids, in rowid order
  private len: number[] = []               // tokens per document, all columns
  private post = new Map<string, number[]>()   // term -> [doc, count, doc, count, ...]
  private terms: string[] = []             // sorted, for prefix lookups
  private total = 0

  // docs in rowid order: [id, column texts]
  constructor(docs: Iterable<[number, string[]]>) {
    for (const [id, cols] of docs) {
      const d = this.ids.length
      this.ids.push(id)
      const counts = new Map<string, number>()
      let n = 0
      for (const col of cols) for (const t of tokens(col)) { counts.set(t, (counts.get(t) ?? 0) + 1); n++ }
      this.len.push(n)
      this.total += n
      for (const [t, c] of counts) {
        let p = this.post.get(t)
        if (!p) { p = []; this.post.set(t, p) }
        p.push(d, c)
      }
    }
    this.terms = [...this.post.keys()].sort()
  }

  get size() { return this.ids.length }

  // documents holding a token that starts with `prefix`: doc -> occurrences
  private prefixFreq(prefix: string): Map<number, number> {
    const out = new Map<number, number>()
    let lo = 0, hi = this.terms.length
    while (lo < hi) { const m = (lo + hi) >> 1; if (this.terms[m] < prefix) lo = m + 1; else hi = m }
    for (let i = lo; i < this.terms.length && this.terms[i].startsWith(prefix); i++) {
      const p = this.post.get(this.terms[i])!
      for (let j = 0; j < p.length; j += 2) out.set(p[j], (out.get(p[j]) ?? 0) + p[j + 1])
    }
    return out
  }

  // one query word ("word"* in FTS5): its tokens must all be there (a word with an underscore
  // or a mark is a phrase to FTS5; matched here without positions, the rare case)
  private phrase(word: string): Map<number, number> {
    const toks = tokens(word)
    if (!toks.length) return new Map()
    let f = this.prefixFreq(toks[toks.length - 1])
    for (const t of toks.slice(0, -1)) {
      const exact = new Map<number, number>()
      const p = this.post.get(t) ?? []
      for (let j = 0; j < p.length; j += 2) exact.set(p[j], p[j + 1])
      const g = new Map<number, number>()
      for (const [d, c] of f) if (exact.has(d)) g.set(d, Math.min(c, exact.get(d)!))
      f = g
    }
    return f
  }

  // db.fts_ids: ids ranked by bm25 for the ORed prefix words of `query` (best first)
  // matchAll: only documents holding every word, as db.fts_ids(match_all=True) (the Library search box)
  search(query: string, limit: number, matchAll = false): number[] {
    const words = ftsTerms(query)
    const N = this.ids.length
    if (!words.length || !N) return []
    const avgdl = this.total / N
    const score = new Map<number, number>()
    const hits = new Map<number, number>()      // document -> how many of the words it holds
    for (const w of words) {
      const f = this.phrase(w)
      if (!f.size) continue
      let idf = Math.log((N - f.size + 0.5) / (f.size + 0.5))
      if (idf <= 0) idf = 1e-6
      for (const [d, c] of f) {
        const s = idf * ((c * (K1 + 1)) / (c + K1 * (1 - B + (B * this.len[d]) / avgdl)))
        score.set(d, (score.get(d) ?? 0) + s)
        hits.set(d, (hits.get(d) ?? 0) + 1)
      }
    }
    return [...score].filter(([d]) => !matchAll || hits.get(d) === words.length)
      .sort((a, b) => b[1] - a[1] || a[0] - b[0]).slice(0, limit).map(([d]) => this.ids[d])
  }
}
