// The phone's stand-in for the desktop's db calls that Wiskit, Smart search and Synthesize make
// (./quick.ts Lib), over its copy of the mirror: the search texts (search/text-NNN.json.gz,
// library/mirror.py search_text), the card rows (category, url, date) and the notes. Two bm25
// indexes like the desktop's FTS5 tables: items (description, ai_desc, transcript, creator, tags)
// and notes (topic, body; core/db.py reindex_notes). Built once per mirror version.
// Run by Node in the tests (type stripping): no parameter properties, imports with .ts.
import { Bm25 } from './text.ts'
import { plain } from '../../lib/note-format.ts'
import type { Item, Lib, Note } from './quick.ts'
import type { DeepLib, Resource } from './deep.ts'

// one entry of search/text-NNN.json.gz
export interface TextRow { id: number; s: string; d: string; a: string; t: string; c: string; g: string; k: string }
export interface RowInfo { id: number; cat: string | null; url: string; created: number; type?: string }

// core/db.py reindex_notes: the topic from the frontmatter (else the file name), the body after it
export function noteOf(file: string, text: string): Note {
  const m = text.match(/^---\n([\s\S]*?)\n---\n+/)
  let topic = file.replace(/\.md$/, ''), body = text
  if (m) {
    body = text.slice(m[0].length)
    const t = m[1].match(/^topic:\s*(.+)$/m)
    if (t) topic = t[1].trim()
  }
  return { filename: file, topic, body: plain(body) }
}

export class PhoneLibrary implements Lib, DeepLib {
  readonly items = new Map<number, Item>()
  readonly all: Item[]
  private idx: Bm25 | null = null
  private notes: Note[]
  private nidx: Bm25 | null = null

  // notes: every note (noteOf), in any order; sorted by file name like reindex_notes
  constructor(texts: TextRow[], rows: RowInfo[], notes: Note[]) {
    const info = new Map(rows.map(r => [r.id, r]))
    for (const t of texts) {
      const r = info.get(t.id)
      if (!r) continue                                  // the PC deleted it since
      this.items.set(t.id, { id: t.id, url: r.url, description: t.d, short_desc: t.s, creator: t.c, category: r.cat,
        ai_desc: t.a, transcript: t.t, tags: t.g, key: t.k, created: r.created, type: r.type })
    }
    this.all = [...this.items.values()].sort((a, b) => a.id - b.id)
    this.notes = notes.slice().sort((a, b) => (a.filename < b.filename ? -1 : a.filename > b.filename ? 1 : 0))
  }

  private index(): Bm25 {
    this.idx ??= new Bm25(this.all.map(i => [i.id, [i.description || '', i.ai_desc || '', i.transcript || '', i.creator || '', i.tags || '']]))
    return this.idx
  }

  ftsIds(q: string, limit: number, matchAll = false) { return this.index().search(q, limit, matchAll) }

  searchNotes(q: string, limit: number): Note[] {
    this.nidx ??= new Bm25(this.notes.map((n, i) => [i, [n.topic, n.body]]))
    return this.nidx.search(q, limit).map(i => this.notes[i])
  }

  getItemsByIds(ids: number[]) { return ids.map(i => this.items.get(i)).filter((r): r is Item => !!r) }

  itemIdsByCategory(category: string) {
    return this.all.filter(i => i.category === category).sort((a, b) => (b.created ?? 0) - (a.created ?? 0) || a.id - b.id).map(i => i.id)
  }

  countItems() { return this.items.size }

  // db.count_by_category: GROUP BY category order (NULL first, then by code point)
  countByCategory(): [string | null, number][] {
    const n = new Map<string | null, number>()
    for (const i of this.all) { const c = i.category ?? null; n.set(c, (n.get(c) ?? 0) + 1) }
    return [...n].sort((a, b) => (a[0] === b[0] ? 0 : a[0] === null ? -1 : b[0] === null ? 1 : a[0] < b[0] ? -1 : 1))
  }

  // ── Wiskit Deep: the websites and tools index (search/deep.json.gz `resources`, in table order) ──
  private res: Resource[] = []
  private resBy: Map<number, Resource[]> | null = null
  setResources(rows: Resource[]) { this.res = rows; this.resBy = null }

  // db.resources_for_items: SQLite walks idx_resources_item, so by item id, then table order
  resourcesForItems(ids: number[]): Resource[] {
    if (!this.resBy) {
      this.resBy = new Map()
      for (const r of this.res) { const l = this.resBy.get(r[0]); if (l) l.push(r); else this.resBy.set(r[0], [r]) }
    }
    return [...new Set(ids)].sort((a, b) => a - b).flatMap(i => this.resBy!.get(i) ?? [])
  }

  // db.search_resources: LOWER(domain) LIKE '%t%' OR LOWER(context) LIKE '%t%' for any term, table
  // order (SQLite's LOWER and LIKE fold ASCII letters only; `_` matches any one character)
  searchResources(terms: string[], limit: number): Resource[] {
    const pats = terms.filter(Boolean).map(t => like(t))
    if (!pats.length) return []
    const out: Resource[] = []
    for (const r of this.res) {
      const d = asciiLower(r[1]), c = asciiLower(r[3])
      if (pats.some(p => p.test(d) || p.test(c))) { out.push(r); if (out.length >= limit) break }
    }
    return out
  }
}

const asciiLower = (s: string) => s.replace(/[A-Z]+/g, m => m.toLowerCase())
function like(t: string): RegExp {
  let src = ''
  for (const c of t) src += c === '_' ? '.' : c === '%' ? '[\\s\\S]*' : /[a-zA-Z]/.test(c) ? `[${c.toLowerCase()}${c.toUpperCase()}]` : c.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')
  return new RegExp(src, 'su')
}
