// Wiskit Deep on the phone (projects/mobile-app/plans/07-wiskit-deep.md): the TypeScript port of
// knowledge/librarian.py, the tools the model researches the library with, over the phone's copy of
// the mirror. The tool definitions, the system prompt and the framing come from the shared prompt
// file (knowledge/prompts/ask_deep.json, passed in as `P`); the text each tool hands back to the
// model is built here exactly as librarian.py builds it, and tests/test_phone_deep.py checks the two
// give the same text for the same library. `DeepLib` stands for the desktop's db calls (./library.ts
// answers them); the item vectors are vectors.bin, the topic and note-section vectors search/aux.bin
// plus what the phone embedded itself (see auxRows).
// Run by Node in the tests (type stripping): no parameter properties, imports with .ts.
import { ftsTerms } from './text.ts'
import { hybridRank, topk, type Hit, type VectorRows } from './search.ts'
import { cut, fill, PYWS, splitJoin, strip, type DisplayWords, type Item, type Note } from './quick.ts'
import { plain } from '../../lib/note-format.ts'

export interface Tool { name: string; description: string; parameters: Record<string, unknown> }
export interface DeepPrompts {
  agent_budgets: { quick: AgentBudget; deep: AgentBudget; control_chars: number; request_seconds: number; connect_seconds: number }
  limits: Record<string, number>; tools: Tool[]
  system: string; profile: string; orientation: string; turn: string; empty: string
  category_tools: Tool[]; category_instructions: string
  canvas_tools: Tool[]; canvas_instructions: string; phone_canvas_instructions: string
}
export interface AgentBudget {
  max_rounds: number; max_tool_calls: number; max_items: number; read_max_ids: number
  research_chars: number; result_chars: number; max_tokens: number; research_seconds: number
}
export type Resource = [number, string, string, string]          // item id, domain, url, context
export interface DeepLib {
  ftsIds(q: string, limit: number): number[]
  searchNotes(q: string, limit: number): Note[]
  getItemsByIds(ids: number[]): Item[]
  itemIdsByCategory(category: string): number[]
  countByCategory(): [string | null, number][]                  // db.count_by_category, in its order
  countItems(): number
  resourcesForItems(ids: number[]): Resource[]
  searchResources(terms: string[], limit: number): Resource[]
}
// the item's report.md ('' when it has none); the phone fetches the item's file from Drive
export type ReportFn = (id: number) => Promise<string>
// the question's embedding, or null (no OpenAI key, or the call failed)
export type EmbedFn = (text: string) => Promise<ArrayLike<number> | null>

export const PROFILE_FILE = 'about-me.md'

// ── Python string helpers (lengths and slices count code points) ─────────────
const cps = (s: string) => [...s].length
const oneLine = (s: string | null | undefined, n: number) => cut(splitJoin(s || ''), n)        // _one_line
const lower = (s: string) => s.toLowerCase()
// str.splitlines()
export function splitLines(s: string): string[] {
  const out = s.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)
  if (out.length > 1 && out[out.length - 1] === '') out.pop()
  return s ? out : []
}
// repr() of a str
export function pyRepr(s: string): string {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'"
  let out = ''
  for (const c of s) {
    const n = c.codePointAt(0)!
    if (c === '\\') out += '\\\\'
    else if (c === q) out += '\\' + q
    else if (c === '\n') out += '\\n'
    else if (c === '\r') out += '\\r'
    else if (c === '\t') out += '\\t'
    else if (n < 0x20 || n === 0x7f) out += '\\x' + n.toString(16).padStart(2, '0')
    else out += c
  }
  return q + out + q
}
// str() of a value the model sent (None for a missing one)
const pyStr = (v: unknown): string => (v === undefined || v === null ? 'None' : typeof v === 'boolean' ? (v ? 'True' : 'False') : typeof v === 'object' ? JSON.stringify(v) : String(v))
// int() of a value the model sent; null where Python raises
function pyInt(v: unknown): number | null {
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v === 'number') return Number.isFinite(v) ? Math.trunc(v) : null
  if (typeof v === 'string' && new RegExp(`^${PYWS}*[+-]?\\d+(_\\d+)*${PYWS}*$`).test(v)) return parseInt(strip(v).replace(/_/g, ''), 10)
  return null
}
// _clamp
function clamp(v: unknown, def: number, lo: number, hi: number): number {
  const n = pyInt(v)
  return Math.max(lo, Math.min(hi, n === null ? def : n))
}
class PyError extends Error {}

// librarian.split_frontmatter
export function splitFrontmatter(text: string): [Record<string, string>, string] {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/)
  if (!m) return [{}, text]
  const meta: Record<string, string> = {}
  for (const line of splitLines(m[1])) {
    const i = line.indexOf(':')
    if (i >= 0) meta[strip(line.slice(0, i))] = strip(line.slice(i + 1))
  }
  return [meta, text.slice(m[0].length)]
}

// librarian.report_section: the body under a '### <header>' heading (any level), or ''
export function reportSection(text: string, header: string): string {
  const out: string[] = []
  let capturing = false
  const h = new RegExp(`^${PYWS}{0,3}#{1,6}${PYWS}+(.*)`)
  for (const ln of splitLines(text || '')) {
    const m = ln.match(h)
    if (m) {
      if (capturing) break
      capturing = lower(strip(m[1])).startsWith(lower(header))
      continue
    }
    if (capturing) out.push(ln)
  }
  return strip(out.join('\n'))
}

// librarian.describe_call: the progress line shown for a tool call
export function describeCall(name: string, args: Record<string, unknown> = {}, words?: DisplayWords): string {
  args = args || {}
  const q = oneLine(args.query ? pyStr(args.query) : '', 80)
  if (name === 'find_topics') return words ? words('wiskit.progress.topics', { query: q }) : `Looking at topics: "${q}"`
  if (name === 'topic_items') return words ? words(q ? 'wiskit.progress.topicQuery' : 'wiskit.progress.topic', { query: q }) : 'Browsing a topic' + (q ? `: "${q}"` : '')
  if (name === 'search_library') {
    const cat = args.category, page = pyInt(args.offset || 0) ?? 0
    return words ? words('wiskit.progress.library', { query: q, category: cat ? words('wiskit.progress.inCategory', { category: pyStr(cat) }) : '', page: page ? words('wiskit.progress.more', { n: page + 1 }) : '' }) : `Searching the library: "${q}"` + (cat ? ` in ${pyStr(cat)}` : '') + (page ? ` (more results from #${page + 1})` : '')
  }
  if (name === 'read_items') return words ? words('wiskit.progress.read', { n: Array.isArray(args.ids) ? args.ids.length : args.ids ? cps(pyStr(args.ids)) : 0 }) : `Reading ${Array.isArray(args.ids) ? args.ids.length : args.ids ? cps(pyStr(args.ids)) : 0} item(s) in detail`
  if (name === 'search_notes') return words ? words('wiskit.progress.notes', { query: q }) : `Searching your notes: "${q}"`
  if (name === 'find_resources') return words ? words('wiskit.progress.resources', { query: q }) : `Looking for websites and tools: "${q}"`
  if (name === 'related_items') return words ? words('wiskit.progress.related', { id: pyStr(args.id) }) : `Finding items related to [id ${pyStr(args.id)}]`
  return words ? words('wiskit.progress.using', { name }) : `Using ${name}`
}

// librarian.read_profile: the user's 'About me' note body
export function profileOf(text: string | null | undefined, max: number): string {
  if (!text) return ''
  return cut(strip(plain(splitFrontmatter(text)[1])), max)
}

// librarian.build_system_prompt
export function systemPrompt(P: DeepPrompts, profile: string, counts: [string | null, number][], total: number): string {
  const cats = counts.map((c, i) => [c, i] as const).sort((a, b) => b[0][1] - a[0][1] || a[1] - b[1])
    .map(([[name, n]]) => `${name === null ? 'None' : name} (${n})`).join(', ')
  let prompt = fill(P.system, { total_items: total, categories: cats })
  if (profile) prompt += fill(P.profile, { profile })
  return prompt
}

// ── the topic and note-section texts (librarian._topic_texts, _note_sections) ─
export interface AuxPayload {
  title?: string; synthesis?: string; member_ids?: number[]
  filename?: string; topic?: string; heading?: string; kind?: string; sources?: number[]; text?: string
}
export interface AuxEntry { key: string; kind: 'topic' | 'note'; text: string; payload: AuxPayload }
export type Cluster = [string, string, string, number[]]          // mirror.topic_clusters

export function topicTexts(clusters: Cluster[]): AuxEntry[] {
  const out: AuxEntry[] = []
  for (const [key, t, s, ids] of clusters) {
    const title = strip(t || ''), synthesis = strip(s || '')
    if (!title && !synthesis) continue
    out.push({ key: `topic:${key}`, kind: 'topic', text: cut(`${title}\n${synthesis}`, 6000), payload: { title, synthesis, member_ids: ids.map(Number) } })
  }
  return out
}

// notes: [file name, whole text]; sorted by file name like the desktop's glob
export function noteSections(notes: [string, string][], sectionMax: number): AuxEntry[] {
  const out: AuxEntry[] = []
  const head = new RegExp(`^#{1,3}${PYWS}+(.*)`)
  for (const [file, text] of notes.slice().sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))) {
    if (file === PROFILE_FILE) continue
    const [meta, raw] = splitFrontmatter(text)
    const body = plain(raw)
    const topic = meta.topic || file.replace(/\.[^.]*$/, '')
    const kind = meta.kind || 'wiki'
    const sources = (meta.sources || '').match(/\d+/g)?.map(Number) ?? []
    const parts: [string, string][] = []
    let heading = topic, buf: string[] = []
    for (const line of splitLines(body)) {
      const m = line.match(head)
      if (m) { parts.push([heading, strip(buf.join('\n'))]); heading = strip(m[1]); buf = [] } else buf.push(line)
    }
    parts.push([heading, strip(buf.join('\n'))])
    let n = 0
    for (const [h, t] of parts) {
      if (cps(t) < 40) continue
      out.push({ key: `note:${file}#${n}`, kind: 'note', text: cut(`${topic} - ${h}\n${t}`, 6000),
        payload: { filename: file, topic, heading: h, kind, sources, text: cut(t, sectionMax) } })
      n++
    }
  }
  return out
}

// search.text_hash
export async function textHash(model: string, text: string): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${model}\n${text}`))
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('')
}

// search/aux.bin (library/mirror._aux_vectors): int8 rows with their key and text hash
export interface AuxVectors { model: string; dim: number; keys: string[]; hashes: string[]; mat: Int8Array }
export function readAux(data: Uint8Array): AuxVectors {
  const n = new DataView(data.buffer, data.byteOffset + 4, 4).getUint32(0)
  const head = JSON.parse(new TextDecoder().decode(data.subarray(8, 8 + n))) as { model: string; dim: number; count: number; keys: string[]; hashes: string[] }
  const mat = new Int8Array(data.buffer.slice(data.byteOffset + 8 + n, data.byteOffset + 8 + n + head.count * head.dim))
  return { model: head.model, dim: head.dim, keys: head.keys, hashes: head.hashes, mat }
}

export interface AuxRow { key: string; kind: 'topic' | 'note'; payload: AuxPayload; vec: ArrayLike<number> }

// ask_core.deep_setup + the start of deep_answer: the live topic and note-section texts with a
// vector each. A row the PC embedded is used while its text hash still matches; with `embed` (an
// OpenAI key) the others are embedded on the phone (`cache`: text hash -> vector, kept by the
// caller), without it they are left out, as the desktop leaves them out without an embeddings key.
export async function auxRows(live: AuxEntry[], model: string, stored: AuxVectors | null, cache: Map<string, ArrayLike<number>>,
  embed: ((texts: string[]) => Promise<ArrayLike<number>[]>) | null, batch: number, onProgress?: (line: string, display?: string) => void,
  canContinue?: () => boolean, words?: DisplayWords): Promise<{ rows: AuxRow[]; fresh: Map<string, ArrayLike<number>>; hashes: string[] }> {
  const pc = new Map<string, [string, number]>()
  if (stored && stored.model === model) stored.keys.forEach((k, i) => pc.set(k, [stored.hashes[i], i]))
  const hashes: string[] = []
  for (const e of live) {
    if (canContinue && !canContinue()) break
    hashes.push(await textHash(model, e.text))
  }
  live = live.slice(0, hashes.length)
  const vecs: (ArrayLike<number> | null)[] = live.map((e, i) => {
    const s = pc.get(e.key)
    if (s && s[0] === hashes[i]) return stored!.mat.subarray(s[1] * stored!.dim, (s[1] + 1) * stored!.dim)
    return cache.get(hashes[i]) ?? null
  })
  const fresh = new Map<string, ArrayLike<number>>()
  const todo = live.map((_, i) => i).filter(i => !vecs[i])
  if (todo.length && embed) {
    onProgress?.(`Indexing ${todo.length} topic and note sections (one-time)`, words?.('wiskit.progress.indexing', { n: todo.length }))
    for (let s = 0; s < todo.length; s += batch) {
      if (canContinue && !canContinue()) break
      const part = todo.slice(s, s + batch)
      const got = await embed(part.map(i => live[i].text))
      part.forEach((i, k) => { vecs[i] = got[k]; fresh.set(hashes[i], got[k]) })
    }
  }
  const rows: AuxRow[] = []
  live.forEach((e, i) => { if (vecs[i]) rows.push({ key: e.key, kind: e.kind, payload: e.payload, vec: vecs[i]! }) })
  return { rows, fresh, hashes }
}

// ── the tools (librarian.Librarian) ──────────────────────────────────────────
type Args = Record<string, unknown>
interface ToolDef { params: string[]; required: number; run: (a: unknown[]) => Promise<string> }

export class Librarian {
  readonly P: DeepPrompts
  readonly consulted: number[] = []
  readonly read: number[] = []
  readonly admitted = new Set<number>()
  readonly delivered = new Set<number>()
  readonly noteSources = new Set<string>()
  readonly canvases = new Map<string, Set<string>>()
  chars = 0
  controlSpent = 0
  budget?: AgentBudget
  signal?: AbortSignal
  deadline?: number
  private L: Record<string, number>
  private db: DeepLib
  private items: VectorRows | null
  private report: ReportFn
  private embed: EmbedFn
  private qcache = new Map<string, Promise<ArrayLike<number> | null>>()
  private aux: Record<'topic' | 'note', AuxRow[]> = { topic: [], note: [] }
  private norms: Record<'topic' | 'note', number[]> = { topic: [], note: [] }
  private tools: Record<string, ToolDef>

  // items: the item vectors (null or empty: keyword ranking only); aux: topic and note-section rows
  constructor(P: DeepPrompts, db: DeepLib, items: VectorRows | null, aux: AuxRow[], embed: EmbedFn, report: ReportFn) {
    this.P = P
    this.L = P.limits
    this.db = db
    this.items = items && items.ids.length ? items : null
    this.embed = embed
    this.report = report
    for (const a of aux) {
      if (a.kind !== 'topic' && a.kind !== 'note') continue
      this.aux[a.kind].push(a)
      let s = 0
      for (let j = 0; j < a.vec.length; j++) s += a.vec[j] * a.vec[j]
      this.norms[a.kind].push(Math.sqrt(s) || 1)
    }
    const t = (params: string[], required: number, run: (a: any[]) => Promise<string>): ToolDef => ({ params, required, run })
    this.tools = {
      find_topics: t(['query', 'limit'], 1, ([q, l]) => this.findTopics(q, l ?? 5)),
      topic_items: t(['topic_id', 'query', 'offset', 'limit'], 1, ([id, q, o, l]) => this.topicItems(id, q ?? '', o ?? 0, l ?? 20)),
      search_library: t(['query', 'category', 'offset', 'limit'], 1, ([q, c, o, l]) => this.searchLibrary(q, c ?? '', o ?? 0, l ?? 20)),
      read_items: t(['ids', 'query'], 1, ([ids, q]) => this.readItems(ids, q ?? '')),
      search_notes: t(['query', 'limit'], 1, ([q, l]) => this.searchNotes(q, l ?? 4)),
      find_resources: t(['query', 'limit'], 1, ([q, l]) => this.findResources(q, l ?? 15)),
      related_items: t(['id', 'limit'], 1, ([id, l]) => this.relatedItems(id, l ?? 8)),
    }
  }

  // run_tool: always text ('Error: ...' when it fails); an abort still throws
  async runTool(name: string, args: Args | null | undefined): Promise<string> {
    this.signal?.throwIfAborted()
    if (this.deadline !== undefined && performance.now() >= this.deadline) return 'Error: research deadline exhausted.'
    const def = Object.prototype.hasOwnProperty.call(this.tools, name) ? this.tools[name] : undefined
    if (!def) return `Error: unknown tool ${pyRepr(String(name))}.`
    const a = args || {}
    const fn = `Librarian.tool_${name}()`
    const extra = Object.keys(a).find(k => !def.params.includes(k))
    if (extra !== undefined) return `Error: bad arguments for ${name}: ${fn} got an unexpected keyword argument ${pyRepr(extra)}`
    const missing = def.params.slice(0, def.required).filter(k => !(k in a))
    if (missing.length) {
      const list = missing.map(k => pyRepr(k))
      return `Error: bad arguments for ${name}: ${fn} missing ${missing.length} required positional argument${missing.length > 1 ? 's' : ''}: ${list.length > 1 ? list.slice(0, -1).join(', ') + ' and ' + list[list.length - 1] : list[0]}`
    }
    try {
      if (this.budget && !this.room()) return 'Error: research context budget exhausted.'
      return this.admitResult(name, await def.run(def.params.map(k => a[k])))
    } catch (e) {
      if ((e as Error).name === 'AbortError') throw e
      return this.admitResult(name, e instanceof PyError ? `Error: bad arguments for ${name}: ${(e as Error).message}` : `Error: ${name} failed: ${(e as Error).message}`)
    }
  }

  private cap(text: string) {
    const max = this.L.result_max
    return cps(text) <= max ? text : cut(text, max) + '\n[truncated]'
  }

  room(): number {
    return this.budget ? Math.max(0, Math.min(this.budget.result_chars, this.budget.research_chars - this.P.agent_budgets.control_chars - (this.chars - this.controlSpent))) : this.L.result_max
  }

  admitIds(ids: number[], limit = Infinity): number[] {
    if (!this.budget) return ids.slice(0, limit)
    const out: number[] = [], fresh = new Set<number>()
    for (const id of new Set(ids)) {
      if (out.length >= limit) break
      if (!this.admitted.has(id) && new Set([...this.admitted, ...fresh]).size >= this.budget.max_items) continue
      out.push(id); fresh.add(id)
    }
    return out
  }

  admitResult(name: string, original: string): string {
    if (!this.budget) return this.cap(original)
    let text = original, view: any = null
    let control = name.startsWith('propose_') || text.startsWith('Error:')
    if (text.startsWith('Error:') && cps(text) > 64) text = cut(text, 48) + ' [truncated]'
    const max = control ? Math.min(name.startsWith('propose_') ? 512 : 64, this.P.agent_budgets.control_chars - this.controlSpent, this.budget.research_chars - this.chars) : this.room()
    if (name.startsWith('propose_') && cps(text) > 512) text = text.startsWith('Error:') ? 'Error: proposal could not be prepared.' : 'Prepared for review. Nothing changes until you approve.'
    if (/^[{[]/.test(text)) { try { view = JSON.parse(text) } catch { /* plain error */ } }
    if (view !== null) {
      const entries = Array.isArray(view) ? view : [view.elements, view.frames].find(Array.isArray)
      while (cps(text) > max && entries?.length) {
        entries.pop()
        if (!Array.isArray(view)) { view.truncated = true; view.shown = entries.length }
        text = JSON.stringify(view)
      }
      if (cps(text) > max) { text = 'Error: result exceeds remaining context budget.'; view = null }
    } else if (cps(text) > max) {
      const sep = text.includes('\n\n---\n\n') ? '\n\n---\n\n' : '\n', out: string[] = []
      for (const unit of text.split(sep)) {
        if (cps([...out, unit].join(sep)) + 24 > max) break
        out.push(unit)
      }
      text = out.join(sep) + '\n[truncated: budget]'
    }
    if (cps(text) > max) return 'Error: research context budget exhausted.'
    control ||= text.startsWith('Error:')
    this.chars += cps(text)
    if (control) this.controlSpent += cps(text)
    if (!text.startsWith('Error:')) {
      const ids = [...text.matchAll(/^\[id (\d+)\]/gm)].map(m => +m[1])
      for (const id of ids) this.admitted.add(id)
      for (const m of text.matchAll(/\[id (\d+)\]/g)) this.delivered.add(+m[1])
      for (const m of text.matchAll(/^\[note: ([^\]]+)\]/gm)) this.noteSources.add(m[1])
      this.consulted.push(...ids)
      if (name === 'read_items') this.read.push(...ids)
      if (name === 'read_canvas' && view && !Array.isArray(view)) this.canvases.set(view.id, new Set(view.elements.map((e: any) => e.id)))
    }
    return text
  }

  // _qvec: the query's embedding, once per query
  private qvec(query: unknown): Promise<ArrayLike<number> | null> {
    const q = strip(String(query ?? ''))
    if (!q) return Promise.resolve(null)
    let p = this.qcache.get(q)
    if (!p) {
      p = this.embed(q).catch(e => { if ((e as Error).name === 'AbortError') throw e; return null })
      this.qcache.set(q, p)
    }
    return p
  }

  // _rank: hybrid-ranked item ids, optionally restricted to a set of ids
  private async rank(query: string, restrict: Set<number> | null = null, pool = this.L.rank_pool): Promise<number[]> {
    let fts = this.db.ftsIds(query, restrict === null ? pool : 2000)
    const vec = await this.qvec(query)
    let hits: Hit[] = []
    if (vec && this.items) hits = topk(this.items, vec, restrict !== null ? this.items.ids.length : pool)
    if (restrict !== null) {
      fts = fts.filter(i => restrict.has(i))
      hits = hits.filter(h => restrict.has(h[0]))
    }
    return hybridRank(fts, hits, pool)
  }

  private lines(ids: number[]): string[] {
    const rows = this.db.getItemsByIds(this.admitIds(ids))
    this.consulted.push(...rows.map(r => r.id))
    return rows.map(r => {
      const body = oneLine(r.ai_desc || r.description || r.transcript || r.short_desc, this.L.line_excerpt)
      const meta = [r.creator, r.category].filter(Boolean).join(', ')
      return `[id ${r.id}] ${body}` + (meta ? ` (${meta})` : '')
    })
  }

  private async auxRank(kind: 'topic' | 'note', query: string, limit: number): Promise<[AuxRow, number][]> {
    const rows = this.aux[kind], norms = this.norms[kind]
    const vec = await this.qvec(query)
    if (rows.length && vec) {
      let qn = 0
      for (let j = 0; j < vec.length; j++) qn += vec[j] * vec[j]
      qn = Math.sqrt(qn)
      if (qn) {
        const scored = rows.map((r, i) => {
          let s = 0
          const n = Math.min(r.vec.length, vec.length)
          for (let j = 0; j < n; j++) s += r.vec[j] * vec[j]
          return [r, s / (norms[i] * qn)] as [AuxRow, number]
        })
        return scored.sort((a, b) => b[1] - a[1]).slice(0, limit)
      }
    }
    // keyword fallback: count the query words present
    const terms = ftsTerms(query)
    const scored: [AuxRow, number][] = []
    for (const r of rows) {
      const p = r.payload
      const text = lower(`${p.title ?? ''} ${p.synthesis ?? ''} ${p.topic ?? ''} ${p.heading ?? ''} ${p.text ?? ''}`)
      const s = terms.filter(t => text.includes(t)).length
      if (s) scored.push([r, s])
    }
    return scored.sort((a, b) => b[1] - a[1]).slice(0, limit)
  }

  // the always-attached starting context: the closest topics and note sections
  async orientation(question: string): Promise<string> {
    const topics = await this.runTool('find_topics', { query: question, limit: 3 })
    const notes = await this.runTool('search_notes', { query: question, limit: 3 })
    return fill(this.P.orientation, { topics, notes })
  }

  async findTopics(query: unknown, limit: unknown = 5): Promise<string> {
    const ranked = await this.auxRank('topic', String(query ?? ''), clamp(limit, 5, 1, 10))
    if (!ranked.length) return 'No topics available (the topic map has not been built).'
    return ranked.map(([r]) => {
      const p = r.payload
      return `topic_id=${r.key.split(':').slice(1).join(':')} | ${p.title} | ${p.member_ids!.length} items\n${oneLine(p.synthesis, 700)}`
    }).join('\n\n')
  }

  async topicItems(topicId: unknown, query: unknown = '', offset: unknown = 0, limit: unknown = 20): Promise<string> {
    const off = clamp(offset, 0, 0, 2000), lim = clamp(limit, 20, 1, 50)
    const key = 'topic:' + pyStr(topicId).split('topic:').join('')
    const row = this.aux.topic.find(r => r.key === key)
    if (!row) return `Error: unknown topic_id ${typeof topicId === 'string' ? pyRepr(topicId) : pyStr(topicId)}. Use an id from find_topics.`
    const members = row.payload.member_ids!
    const ids = query ? await this.rank(String(query), new Set(members)) : []
    const seen = new Set(ids)
    for (const i of members) if (!seen.has(i)) ids.push(i)
    const page = ids.slice(off, off + lim)
    const head = `Topic '${row.payload.title}': ${ids.length} items, showing ${off + 1}-${off + page.length}`
    return head + '\n' + this.lines(page).join('\n')
  }

  async searchLibrary(query: unknown, category: unknown = '', offset: unknown = 0, limit: unknown = 20): Promise<string> {
    const off = clamp(offset, 0, 0, this.L.rank_pool), lim = clamp(limit, 20, 1, 50)
    let restrict: Set<number> | null = null, label = ''
    if (category) {
      const names = new Map<string, string>()
      for (const [name] of this.db.countByCategory()) if (name) names.set(lower(name), name)
      const real = names.get(lower(strip(pyStr(category))))
      if (real === undefined) {
        const all = [...names.values()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
        return `Error: unknown category ${typeof category === 'string' ? pyRepr(category) : pyStr(category)}. Categories: ` + all.join(', ')
      }
      restrict = new Set(this.db.itemIdsByCategory(real))
      label = ` in ${real}`
    }
    const ids = await this.rank(String(query ?? ''), restrict)
    const page = ids.slice(off, off + lim)
    if (!page.length) return `No more results${label} (offset ${off}).`
    return `Results${label} ${off + 1}-${off + page.length}, ranked by relevance (later pages are less relevant):\n` + this.lines(page).join('\n')
  }

  async readItems(ids: unknown, query: unknown = ''): Promise<string> {
    if (ids && !Array.isArray(ids) && typeof ids !== 'string') throw new PyError(`'${typeof ids === 'number' ? (Number.isInteger(ids) ? 'int' : 'float') : typeof ids === 'boolean' ? 'bool' : 'dict'}' object is not iterable`)
    const list = this.admitIds((Array.isArray(ids) ? ids : ids ? [...(ids as string)] : []).map(i => {
      const n = pyInt(i)
      if (n === null) throw new Error(`invalid literal for int() with base 10: ${pyRepr(pyStr(i))}`)
      return n
    }), this.budget?.read_max_ids ?? this.L.read_max_ids)
    const rows = this.db.getItemsByIds(list)
    this.consulted.push(...rows.map(r => r.id))
    const terms = query ? ftsTerms(String(query)) : []
    const out: string[] = []
    for (const r of rows) {
      this.signal?.throwIfAborted()
      if (this.deadline !== undefined && performance.now() >= this.deadline) break
      const meta = [r.creator, r.category, r.type, r.url].filter(Boolean).join(' | ')
      const parts = [`[id ${r.id}] ${meta}`, 'Category: ' + (r.category || '(none)'), 'Summary: ' + oneLine(r.ai_desc || r.description, 900)]
      const remaining = this.room() - cps(out.join('\n\n---\n\n')) - 128
      if (this.budget && cps(parts.join('\n')) > remaining) break
      const rep = await this.report(r.id).catch(e => { if ((e as Error).name === 'AbortError') throw e; return '' })
      this.signal?.throwIfAborted()
      const key = reportSection(rep, 'Key information')
      if (key) parts.push('Key information:\n' + cut(key, this.L.keyinfo_max))
      const howto = reportSection(rep, 'How you could use this')
      if (howto) parts.push('How to use it:\n' + cut(howto, this.L.howto_max))
      if (r.description && r.ai_desc) parts.push('Post text: ' + oneLine(r.description, 400))
      const tr = r.transcript || ''
      if (tr) {
        const low = lower(tr), max = this.L.transcript_max
        const hits = terms.map(t => low.indexOf(t)).filter(p => p >= 0).map(p => cps(low.slice(0, p)))
        const start = hits.length ? Math.max(0, Math.min(...hits) - Math.floor(max / 4)) : 0
        parts.push('Transcript excerpt: ' + oneLine([...tr].slice(start, start + max).join(''), max))
      }
      if (this.budget) {
        const admitted: string[] = []
        for (const part of parts) if (cps([...admitted, part].join('\n')) + 24 <= remaining) admitted.push(part)
        if (admitted.length < parts.length) admitted.push('[truncated: budget]')
        out.push(admitted.join('\n'))
      } else out.push(parts.join('\n'))
    }
    const found = new Set(rows.map(r => r.id))
    const missing = [...new Set(list.filter(i => !found.has(i)))].sort((a, b) => a - b)
    if (missing.length) out.push('Not found: ' + missing.join(', '))
    if (this.budget) out.push('[Coverage limited by item, result and research budgets.]')
    else this.read.push(...rows.map(r => r.id))
    return out.length ? out.join('\n\n---\n\n') : 'No items found for those ids.'
  }

  async searchNotes(query: unknown, limit: unknown = 4): Promise<string> {
    const lim = clamp(limit, 4, 1, 8), q = String(query ?? '')
    const out = (await this.auxRank('note', q, lim)).map(([r]) => {
      const p = r.payload
      const src = (p.sources ?? []).slice(0, 40).join(', ')
      return `[note: ${p.filename}] ${p.topic} > ${p.heading} (${p.kind}; sources: ${src || 'none'})\n${cut(p.text ?? '', 1800)}`
    })
    if (!out.length) for (const n of this.db.searchNotes(q, lim)) out.push(`[note: ${n.filename}] ${n.topic}\n${cut(n.body || '', 1800)}`)
    return out.length ? out.join('\n\n---\n\n') : 'No matching notes.'
  }

  async findResources(query: unknown, limit: unknown = 15): Promise<string> {
    const lim = clamp(limit, 15, 1, 40), q = String(query ?? '')
    const ranked = await this.rank(q, null, 150)
    const pos = new Map(ranked.map((id, n) => [id, n]))
    const rows = [...this.db.resourcesForItems(ranked), ...this.db.searchResources(ftsTerms(q), 50)]
    const byDomain = new Map<string, { url: string; ctx: string; items: number[]; score: number }>()
    for (const [itemId, domain, url, ctx] of rows) {
      const score = 1 / (10 + (pos.get(itemId) ?? 300))
      let d = byDomain.get(domain)
      if (!d) { d = { url, ctx, items: [], score: 0 }; byDomain.set(domain, d) }
      if (!d.items.includes(itemId)) { d.items.push(itemId); d.score += score }
    }
    const best = [...byDomain].sort((a, b) => b[1].score - a[1].score).slice(0, lim)
    if (!best.length) return 'No websites or tools found for that.'
    return best.map(([domain, d]) => {
      this.consulted.push(...d.items.slice(0, 3))
      return `${domain} | ${d.url} | from ${d.items.slice(0, 5).map(i => `[id ${i}]`).join(', ')} | ${d.ctx}`
    }).join('\n')
  }

  async relatedItems(id: unknown, limit: unknown = 8): Promise<string> {
    const lim = clamp(limit, 8, 1, 20)
    const v = this.items, n = v ? pyInt(id) : null
    if (v && n === null) throw new Error(`invalid literal for int() with base 10: ${pyRepr(pyStr(id))}`)
    const at = v ? v.ids.indexOf(n!) : -1
    let hits: number[] = []
    if (v && at >= 0) {
      const { dim, mat, norms } = v, a = at * dim, scored: [number, number][] = []
      for (let r = 0; r < v.ids.length; r++) {
        if (r === at) continue
        let s = 0
        for (let j = 0, b = r * dim; j < dim; j++) s += mat[a + j] * mat[b + j]
        scored.push([v.ids[r], s / (norms[at] * norms[r])])
      }
      hits = scored.sort((x, y) => y[1] - x[1]).slice(0, lim).map(h => h[0])
    }
    if (!hits.length) return `No related items found for id ${pyStr(id)}.`
    return this.lines(hits).join('\n')
  }
}

// ask_core.deep_answer: the first message of the turn (the question, the starting points)
export async function deepTurn(lib: Librarian, question: string): Promise<string> {
  return fill(lib.P.turn, { question, orientation: await lib.orientation(question) })
}
