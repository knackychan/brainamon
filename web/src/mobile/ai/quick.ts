// Wiskit Quick on the phone: the TypeScript port of knowledge/ask_core.py (retrieval, the context
// block, the turn), reading the same prompt file (knowledge/prompts/ask_quick.json, passed in as
// `P`). `Lib` stands for the desktop's db calls, answered from the phone's copy of the mirror
// (./library.ts). tests/test_phone_ai.py checks that both build the same messages for the same
// library. Python string rules are kept where they show in the prompt: lengths and slices count
// code points, whitespace is Python's, \w and \b are Unicode.
// Run by Node in the tests (type stripping): no parameter properties, imports with .ts.
import { ftsTerms, W } from './text.ts'
import { hybridRank, type Hit } from './search.ts'

export interface AskPrompts {
  limits: Record<string, number>
  list_words: string; followup_words: string; system: string
  notes_head: string; carried_head: string; no_items: string; list_head: string; items_head: string
  key_info: string; transcript_excerpt: string; part_sep: string; block_sep: string
  ask: string; list_ask: string; turn: string
  info_sent: string; info_carried: string; info_notes: string; info_list: string; info_retrieval: string; fallback: string
  category_unavailable: string; canvas_unavailable: string
}

// an item as the desktop's db returns it (column names), plus the report's Key information
export interface Item {
  id: number; url?: string; description?: string; short_desc?: string; creator?: string; category?: string | null
  ai_desc?: string; transcript?: string; tags?: string; key?: string; created?: number; type?: string
}
export interface Note { filename: string; topic: string; body: string }
export interface Turn { role: 'user' | 'assistant'; content: string }
export interface Lib {
  ftsIds(q: string, limit: number): number[]
  searchNotes(q: string, limit: number): Note[]
  getItemsByIds(ids: number[]): Item[]
  itemIdsByCategory(category: string): number[]
  countItems(): number
}

// knowledge/prompt_files.fill: {name} replaced in one pass
export function fill(t: string, v: Record<string, string | number>): string {
  return t.replace(/\{(\w+)\}/g, (m, k: string) => (k in v ? String(v[k]) : m))
}

// ── Python string helpers ────────────────────────────────────────────────────
export const PYWS = '[\\t\\n\\v\\f\\r \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]'
const WS_RUN = new RegExp(PYWS + '+', 'g')
const WS_EDGE = new RegExp(`^${PYWS}+|${PYWS}+$`, 'g')
export const strip = (s: string) => s.replace(WS_EDGE, '')
export const splitJoin = (s: string) => s.split(WS_RUN).filter(Boolean).join(' ')       // ' '.join(s.split())
export const cut = (s: string, n: number) => (s.length <= n ? s : [...s].slice(0, n).join(''))  // s[:n]
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const or = (...v: (string | undefined | null)[]) => v.find(x => !!x) || ''

export class Quick {
  readonly P: AskPrompts
  readonly L: Record<string, number>
  private listRe: RegExp
  private followup: Set<string>

  constructor(P: AskPrompts) {
    this.P = P
    this.L = P.limits
    this.listRe = new RegExp(`(?<!${W})(${P.list_words.split(/\s+/).filter(Boolean).join('|')})(?!${W})`, 'iu')
    this.followup = new Set(P.followup_words.split(/\s+/).filter(Boolean))
  }

  isList(q: string) { return this.listRe.test(q || '') }
  effectiveDepth(q: string, depth: number) { return this.isList(q) ? Math.max(depth, this.L.list_max) : depth }

  topicTerms(q: string) { return ftsTerms(q).filter(t => !this.followup.has(t)) }

  relevantNotes(lib: Lib, q: string): Note[] {
    const terms = this.topicTerms(q).map(t => new RegExp(`(?<!${W})${esc(t)}`, 'u'))
    if (!terms.length) return []
    const need = Math.max(1, Math.floor((terms.length + 1) / 2))
    const out: Note[] = []
    for (const n of lib.searchNotes(q, this.L.notes * 3)) {
      const text = `${n.topic}\n${n.body || ''}`.toLowerCase()
      if (terms.filter(t => t.test(text)).length >= need) {
        out.push(n)
        if (out.length === this.L.notes) break
      }
    }
    return out
  }

  carriedItems(lib: Lib, history: Turn[], q: string): Item[] {
    if (!history.length || history[history.length - 1].role !== 'assistant') return []
    const words = new Set(q.toLowerCase().match(new RegExp(`${W}+`, 'gu')) ?? [])
    if (ftsTerms(q).length > 2 && ![...words].some(w => this.followup.has(w))) return []
    return lib.getItemsByIds(citedIds(history[history.length - 1].content).slice(0, this.L.carry_max))
  }

  itemText(r: Item, terms: string[] = [], detail = false): string {
    const title = cut(or(r.short_desc, r.ai_desc, r.description), 120)
    const body = cut(or(r.ai_desc, r.transcript, r.description, r.short_desc), this.L.excerpt)
    let head = `[id ${r.id}] ${title}`
    if (r.creator) head += ` - ${r.creator}`
    if (r.url) head += `\n${r.url}`
    head += '\nCategory: ' + (r.category || '(none)')
    let text = head + '\n' + body
    if (!detail) return text
    if (r.key) text += this.P.key_info + cut(r.key, this.L.keyinfo_excerpt)
    const tr = r.transcript || ''
    if (tr && r.ai_desc && terms.length) {
      const low = tr.toLowerCase()
      const hits = terms.map(t => low.indexOf(t)).filter(p => p >= 0).map(p => cps(low.slice(0, p)))
      if (hits.length) {
        const start = Math.max(0, Math.min(...hits) - Math.floor(this.L.snippet / 3))
        const chars = [...tr]
        text += fill(this.P.transcript_excerpt, { text: splitJoin(chars.slice(start, start + this.L.snippet).join('')) })
      }
    }
    return text
  }

  contextBlock(lib: Lib, rows: Item[], notes: Note[] = [], q = '', carried: Item[] = [], listMode = false): string {
    const P = this.P, blocks: string[] = []
    if (notes.length) {
      blocks.push(P.notes_head + notes.map(n => `[note: ${n.filename}] ${n.topic}\n` + cut(strip(n.body || ''), this.L.note_excerpt)).join(P.part_sep))
    }
    const terms = ftsTerms(q)
    if (carried.length) blocks.push(P.carried_head + carried.map(r => this.itemText(r, terms, true)).join(P.part_sep))
    if (!rows.length) {
      if (!carried.length) blocks.push(P.no_items)
    } else if (listMode) {
      const lines = rows.map(r => {
        const body = cut(splitJoin(or(r.ai_desc, r.description, r.transcript, r.short_desc)), this.L.list_excerpt)
        const meta = [r.creator, r.category].filter(Boolean).join(', ')
        return `[id ${r.id}] ${body}` + (meta ? ` (${meta})` : '')
      })
      blocks.push(fill(P.list_head, { n: rows.length, total: lib.countItems() }) + lines.join('\n'))
    } else {
      const parts = rows.map((r, n) => this.itemText(r, terms, n < this.L.detail_items))
      blocks.push(fill(P.items_head, { n: parts.length, total: lib.countItems() }) + parts.join(P.part_sep))
    }
    return blocks.join(P.block_sep)
  }

  // ask_core.rank_rows: keyword + the embedded question (`topk` ranks the vectors)
  rankRows(lib: Lib, q: string, depth: number, category: string, topk: (k: number) => Hit[]): Item[] {
    let ids: number[]
    if (category) {
      const cand = new Set(lib.itemIdsByCategory(category))
      const vec = topk(Infinity).filter(h => cand.has(h[0]))
      const fts = lib.ftsIds(q, 400).filter(i => cand.has(i))
      ids = hybridRank(fts, vec, this.L.category_max)
      if (!ids.length) ids = lib.itemIdsByCategory(category).slice(0, this.L.category_max)
    } else {
      ids = hybridRank(lib.ftsIds(q, 200), topk(200), depth)
    }
    return lib.getItemsByIds(ids)
  }

  // ask_core.fallback_rows (no OpenAI key on the phone, or the embedding failed)
  fallbackRows(lib: Lib, q: string, depth: number, category: string, all: Item[]): Item[] {
    if (category) {
      const cand = lib.itemIdsByCategory(category), cset = new Set(cand)
      const ids = lib.ftsIds(q, 400).filter(i => cset.has(i))
      const seen = new Set(ids)
      for (const i of cand) if (!seen.has(i)) ids.push(i)
      return lib.getItemsByIds(ids.slice(0, this.L.category_max))
    }
    // db.fts_search: bm25 hits, then items whose category holds the words (newest first)
    const query = strip(q || '')
    if (!query) return []
    const ids = lib.ftsIds(query, depth), seen = new Set(ids), low = query.toLowerCase()
    const byCat = all.filter(r => (r.category || '').toLowerCase().includes(low)).sort((a, b) => (b.created ?? 0) - (a.created ?? 0)).slice(0, depth)
    for (const r of byCat) if (!seen.has(r.id)) { seen.add(r.id); ids.push(r.id) }
    return lib.getItemsByIds(ids).slice(0, depth)
  }

  fallbackLabel(reason = '') { return this.P.fallback + (reason ? ` (${reason})` : '') }

  // ask_core.build_turn
  buildTurn(lib: Lib, q: string, rows: Item[], history: Turn[], retrieval = '', budget?: { max_items: number; research_chars: number; control_chars: number }) {
    const P = this.P, listMode = this.isList(q)
    const notes = this.relevantNotes(lib, q)
    let carried = this.carriedItems(lib, history, q)
    if (carried.length && !this.topicTerms(q).length) rows = []
    else if (carried.length && budget) { const selected = new Set(rows.map(r => r.id)); carried = carried.filter(r => !selected.has(r.id)) }
    else if (carried.length) { const c = new Set(carried.map(r => r.id)); rows = rows.filter(r => !c.has(r.id)) }
    let partial = false
    if (budget) {
      rows = rows.slice(0, budget.max_items)
      carried = carried.slice(0, Math.max(0, budget.max_items - rows.length))
      partial = rows.length + carried.length >= budget.max_items
    }
    let context = this.contextBlock(lib, rows, notes, q, carried, listMode)
    if (budget) {
      while (cps(context) + 24 > budget.research_chars - budget.control_chars && (notes.length || carried.length || rows.length)) {
        (notes.length ? notes : carried.length ? carried : rows).pop()
        partial = true
        context = this.contextBlock(lib, rows, notes, q, carried, listMode)
      }
      if (partial) context += '\n[truncated: budget]'
    }
    let info = fill(P.info_sent, { n: rows.length })
    if (carried.length) info += fill(P.info_carried, { n: carried.length })
    if (notes.length) info += fill(P.info_notes, { n: notes.length, files: notes.map(n => n.filename).join(', ') })
    if (listMode) info += P.info_list
    if (retrieval) info += fill(P.info_retrieval, { retrieval })
    const hist = history.slice(-(this.L.history_turns * 2))
    let ask = fill(P.ask, { question: q })
    if (listMode) ask += P.list_ask
    const messages: Turn[] = [...hist, { role: 'user', content: fill(P.turn, { question: q, context, ask }) }]
    return { messages, info, sources: [...carried, ...rows], notes: notes.map(n => n.filename), contextChars: cps(context), listMode, maxTokens: listMode ? this.L.list_max_tokens : 0 }
  }

  answerSources(rows: Item[], text: string, listMode = false): Item[] {
    if (!listMode) return rows
    const byId = new Map(rows.map(r => [r.id, r]))
    const cited = citedIds(text).map(i => byId.get(i)).filter((r): r is Item => !!r)
    return cited.length ? cited : rows
  }
}

const cps = (s: string) => [...s].length

// ask_core.cited_ids: every number in a bracket group that says id / ids
export function citedIds(text: string): number[] {
  const ids: number[] = []
  const word = new RegExp(`(?<!${W})ids?(?!${W})`, 'iu')
  for (const m of (text || '').matchAll(/\[([^\]]*)\]/g)) if (word.test(m[1])) for (const n of m[1].match(/\d+/g) ?? []) ids.push(+n)
  return [...new Set(ids)]
}

// ask_core.cited_notes
export function citedNotes(text: string): string[] {
  return [...new Set([...(text || '').matchAll(/\[\s*note\s*:\s*([^\]]+?)\s*\]/gi)].map(m => strip(m[1])))]
}

// ask_core.auto_name: the name a new chat gets from its first question
export function autoName(q: string): string {
  return cut(strip((q || '').replace(new RegExp(PYWS + '+', 'g'), ' ')), 40)
}

// ask_core.answer_title: (title, body) when the answer opens with a heading
export function answerTitle(md: string): [string, string] {
  const lines = (md || '').replace(/^\s+/, '').split('\n')
  const m = lines[0].match(/^#{1,3}\s+(.+?)\s*#*\s*$/)
  if (!m) return ['', md]
  let t = m[1].replace(/\[(?:id|note)[^\]]*\]/g, '').replace(/[*_`]+/g, '')
  t = strip(cut(strip(t.replace(/\s+/g, ' ')), 80))
  return [t, lines.slice(1).join('\n').replace(/^\n+/, '')]
}
