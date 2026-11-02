// The Library state: every compact row in memory, the filters (V6 LS), the visible list, the
// selection, zoom and the per-cell job status. Filtering and sorting run here (V6 libList rules);
// text search asks the server (GET /api/search, the app's FTS semantics) and Smart asks POST
// /api/smart. Ranking logic stays in Python.
import { SvelteMap, SvelteSet } from 'svelte/reactivity'
import { api } from './api'
import { idFirst, inSearch } from './whole-id'
import { bootFail, toast, ui } from './ui.svelte'

export interface Row {
  id: number; title: string; creator: string; type: string; cat: string; tags: string; desc: string
  url: string; src: string; thumb: boolean; ai: boolean; an: boolean; nd: number; fav: boolean; created: number
  tv: number                                            // thumbnail version (server/library.py)
}
export interface Category { name: string; color: string; count: number; hidden?: number }

// nd bits (server/library.py)
export const NEED = { thumb: 1, describe: 2, analyze: 4, categorize: 8, index: 16 } as const
export type NeedKey = keyof typeof NEED
export const NEED_LABEL: Record<NeedKey, string> = {
  thumb: 'Missing thumbnail', describe: 'Missing AI description', analyze: 'Video not analyzed',
  categorize: 'Not categorized', index: 'Not indexed for search',
}
export const isVid = (r: Row) => r.type === 'Reel' || r.type === 'Video'

export type Sort = 'new' | 'old' | 'az' | 'za' | 'type'
export const SORTS: [Sort, string][] = [['new', 'Newest'], ['old', 'Oldest'], ['az', 'A to Z'], ['za', 'Z to A'], ['type', 'By type']]
export const Z = [96, 116, 136, 160, 196, 226, 260, 300, 340]

const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private window */ } },
}

const COLLATE = new Intl.Collator('en', { sensitivity: 'base', numeric: true })
const tagCache = new WeakMap<Row, string[]>()
export function tagsOf(r: Row): string[] {
  let t = tagCache.get(r)
  if (!t) { t = r.tags.split(',').map(x => x.trim()).filter(Boolean); tagCache.set(r, t) }
  return t
}

function initZoom(): number {
  const p = new URLSearchParams(location.search).get('zoom')
  if (p !== null && /^\d$/.test(p) && +p < Z.length) return +p
  const s = ls.get('cm-wiskit-zoom')
  if (s !== null && /^\d$/.test(s) && +s < Z.length) return +s
  return innerWidth < 640 ? 1 : 3
}

class Library {
  rows: Row[] = $state.raw([])
  cats: Category[] = $state.raw([])
  tints: Record<string, string> = $state.raw({})
  loaded = $state(false)

  // filters (V6 LS)
  q = $state('')
  searchIds: Set<number> | null = $state.raw(null)
  rank: Map<number, number> | null = $state.raw(null)   // id -> position (Smart)
  ranking = $state(false)
  smart = $state(ls.get('cm-v5-smart') === 'on')
  cat = $state('all')
  tag = $state('all')
  type = $state('all')
  creator = $state('all')
  src = $state('all')
  fav = $state<'all' | 'fav'>('all')
  status = $state(0)                                      // OR of NEED bits
  sort = $state<Sort>('new')
  view = $state<'grid' | 'list'>(ls.get('cm-v5-view') === 'list' ? 'list' : 'grid')
  variant = $state<'fa2' | 'full'>(ls.get('cm-v5-card') === 'full' ? 'full' : 'fa2')
  zi = $state(initZoom())

  sel = new SvelteSet<number>()
  cellState = new SvelteMap<number, 'worked' | 'done' | 'err'>()
  nvId: number | null = $state(null)                      // the Viewing tile's card
  cited: Map<number, number> = $state.raw(new Map())      // plan 11: cards cited in the last answer -> 1-based order
  hlId: number | null = $state(null)                      // plan 11: the card a hovered citation points at

  byId = $derived(new Map(this.rows.map(r => [r.id, r])))
  // rank on the card = position in the whole library, newest first
  rankOf = $derived.by(() => {
    const m = new Map<number, number>()
    ;[...this.rows].sort((a, b) => b.created - a.created || b.id - a.id).forEach((r, i) => m.set(r.id, i + 1))
    return m
  })

  // Rows in a collection flagged hidden (NSFW) stay out of the main feed and the dock counts until
  // that collection is opened or Show hidden is on (this session only).
  showHidden = $state(false)
  hiddenCats = $derived(new Set(this.cats.filter(c => c.hidden).map(c => c.name)))
  pool = $derived.by(() => {
    const h = this.hiddenCats
    return this.showHidden || !h.size || h.has(this.cat) ? this.rows : this.rows.filter(r => !h.has(r.cat))
  })

  // rows that pass the filters (not the text search): the counts follow these
  filtered = $derived.by(() => {
    const { cat, tag, type, creator, src, fav, status } = this
    const tl = tag.toLowerCase()
    return this.pool.filter(r =>
      (cat === 'all' || r.cat === cat) &&
      (tag === 'all' || tagsOf(r).some(t => t.toLowerCase() === tl)) &&
      (type === 'all' || r.type === type) &&
      (creator === 'all' || r.creator === creator) &&
      (src === 'all' || r.src === src) &&
      (fav === 'all' || r.fav) &&
      (!status || (r.nd & status) !== 0))
  })

  visible = $derived.by(() => {
    const q = this.q.trim(), ids = this.searchIds, rank = this.rank
    let L = this.filtered
    if (q && (ids || rank)) L = L.filter(r => inSearch(r.id, q, ids, rank))
    L = L.slice()
    if (rank && q) {
      const at = (r: Row) => rank.get(r.id) ?? 1e9
      L.sort((a, b) => at(a) - at(b) || b.id - a.id)
    } else {
      const by: Record<Sort, (a: Row, b: Row) => number> = {
        new: (a, b) => b.created - a.created || b.id - a.id,
        old: (a, b) => a.created - b.created || a.id - b.id,
        az: (a, b) => COLLATE.compare(a.title, b.title) || b.id - a.id,
        za: (a, b) => COLLATE.compare(b.title, a.title) || b.id - a.id,
        type: (a, b) => COLLATE.compare(a.type, b.type) || COLLATE.compare(a.title, b.title),
      }
      L.sort(by[this.sort])
    }
    return idFirst(L, q)                       // a whole number: that item first, Smart or not
  })
  visIds = $derived(this.visible.map(r => r.id))
  // the cards whose job scan bar runs: the working items, at most SCAN_CAP of them in visible
  // order (an index batch marks 64 at once; PLAN.md performance budget)
  scanIds = $derived.by(() => {
    const w: number[] = []
    for (const [id, s] of this.cellState) if (s === 'worked') w.push(id)
    if (w.length <= SCAN_CAP) return new Set(w)
    const ws = new Set(w), out = new Set<number>()
    for (const id of this.visIds) if (ws.has(id) && out.add(id).size >= SCAN_CAP) break
    return out
  })
}

const SCAN_CAP = 40

export const lib = new Library()

// Every thumbnail <img> / background goes through here: the versioned URL is cached for good by
// the browser (server /thumb ?v=), and changes when the row's thumbnail does. w asks the server
// for a copy that many px wide (the Library grid only; everything else keeps the full file).
export function thumbSrc(id: number, w = 0): string {
  const tv = lib.byId.get(id)?.tv
  const q = [tv ? `v=${tv}` : '', w ? `w=${w}` : ''].filter(Boolean).join('&')
  return q ? `/thumb/${id}?${q}` : `/thumb/${id}`
}

// ── load + refetch ───────────────────────────────────────────────────────────
function applyCats(cats: Category[]) {
  for (const c of cats) if (c.color) TYPE[c.name] = c.color      // the engine reads TYPE[cat]
  lib.cats = cats
}
export async function loadCats() { applyCats(await api.get<Category[]>('/api/categories')) }

// GET /api/items?fmt=cols: column names once, then one array per row (booleans as 0 / 1)
interface Cols { cols: string[]; rows: unknown[][]; total: number }
const BOOL = new Set(['thumb', 'ai', 'an', 'fav'])
function decode(c: Cols): Row[] {
  const k = c.cols
  return c.rows.map(v => {
    const o: Record<string, unknown> = {}
    for (let i = 0; i < k.length; i++) o[k[i]] = BOOL.has(k[i]) ? !!v[i] : v[i]
    return o as unknown as Row
  })
}
const getRows = async (q = '') => decode(await api.get<Cols>('/api/items?fmt=cols' + q))

// Started by main.ts before the app mounts, so the row fetch overlaps the first render
// (index.html preloads the same URL).
let pre: Promise<[Category[], Row[]]> | null = null
export function prefetchLibrary() {
  pre ??= Promise.all([api.get<Category[]>('/api/categories'), getRows()])
}

async function loadTints(tries = 0) {
  try {
    const t = await api.get<{ ready: boolean; tints: Record<string, string> }>('/api/tints')
    lib.tints = t.tints
    if (!t.ready && tries < 40) setTimeout(() => loadTints(tries + 1), 1500)
  } catch { /* the map falls back to collection colours */ }
}

export async function loadLibrary() {
  try {
    prefetchLibrary()
    const [cats, items] = await pre!
    pre = null
    applyCats(cats)
    lib.rows = items
    ui.libCount = items.length
    lib.loaded = true
    performance.mark('cm-library-loaded')              // a startup bar step (web/public/boot.js)
  } catch (e) {
    toast(`Could not load the library: ${(e as Error).message}`, 'e')
    bootFail(`Could not load your library: ${(e as Error).message}`)
  }
  loadTints()
}

// After an items_changed event: replace those rows, add new ones, drop the ones that are gone.
export async function refetch(ids: number[]) {
  if (!ids.length) return
  const got = await getRows('&ids=' + ids.join(','))
  const fresh = new Map(got.map(r => [r.id, r]))
  const gone = new Set(ids.filter(id => !fresh.has(id)))
  const known = new Set<number>()
  const rows = lib.rows.filter(r => !gone.has(r.id)).map(r => { known.add(r.id); return fresh.get(r.id) ?? r })
  const added = got.filter(r => !known.has(r.id))
  lib.rows = added.length ? [...added, ...rows] : rows
  gone.forEach(id => lib.sel.delete(id))
  ui.libCount = lib.rows.length
}

export function replaceRow(r: Row) {
  lib.rows = lib.rows.map(x => (x.id === r.id ? r : x))
}

// ── search ───────────────────────────────────────────────────────────────────
let qT = 0, qSeq = 0
export function setQuery(text: string, now = false) {
  clearTimeout(qT)
  const fire = () => {
    performance.mark('cm-search-fire')                 // the perf harness measures from here
    lib.q = text
    lib.rank = null
    runSearch(text)
  }
  if (now) fire(); else qT = window.setTimeout(fire, 150)    // the app debounces 150 ms
}

async function runSearch(text: string) {
  const seq = ++qSeq, q = text.trim()
  if (!q) { lib.searchIds = null; return }
  try {
    const r = await api.get<{ ids: number[] }>('/api/search?q=' + encodeURIComponent(q))
    if (seq === qSeq) lib.searchIds = new Set(r.ids)
  } catch (e) { toast(`Search failed: ${(e as Error).message}`, 'w') }
}

export async function smartRank() {
  const q = lib.q.trim()
  if (!q) return
  lib.ranking = true
  try {
    const r = await api.post<{ ids: number[] }>('/api/smart', { q })
    if (q !== lib.q.trim()) return                     // superseded by newer typing
    lib.rank = r.ids.length ? new Map(r.ids.map((id, i) => [id, i])) : null
    if (!r.ids.length) toast('Smart search: no matches by meaning; showing keyword results.', 'w')
    document.getElementById('board')?.scrollTo({ top: 0 })
  } catch (e) {
    toast((e as Error).message, 'w')
  } finally {
    lib.ranking = false
  }
}

export function setSmart(on: boolean) {
  lib.smart = on
  ls.set('cm-v5-smart', on ? 'on' : 'off')
  if (!on && lib.rank) lib.rank = null
  else if (on && lib.q.trim()) smartRank()
}

// ── filters ──────────────────────────────────────────────────────────────────
export type Group = 'cat' | 'tag' | 'type' | 'creator' | 'src' | 'fav' | 'sort' | 'view' | 'variant'
export function setFilter(g: Group, v: string) {
  if (g === 'sort') { lib.sort = v as Sort; lib.rank = null }
  else if (g === 'view') { lib.view = v as 'grid' | 'list'; ls.set('cm-v5-view', v) }
  else if (g === 'variant') { lib.variant = v as 'fa2' | 'full'; ls.set('cm-v5-card', v) }
  else if (g === 'tag') lib.tag = lib.tag === v ? 'all' : v
  else if (g === 'fav') lib.fav = v as 'all' | 'fav'
  else lib[g] = v
}
export function toggleStatus(bit: number) { lib.status ^= bit }

// k: undefined = every filter; 'q', 'cat', ..., or 'st:<bit>'
export function clearFilters(k?: string) {
  if (!k || k === 'q') {
    const q = document.getElementById('q') as HTMLInputElement | null
    if (q) q.value = ''
    clearTimeout(qT); qSeq++
    lib.q = ''; lib.searchIds = null; lib.rank = null
  }
  for (const f of ['cat', 'tag', 'type', 'creator', 'src'] as const) if (!k || k === f) lib[f] = 'all'
  if (!k || k === 'fav') lib.fav = 'all'
  if (!k) lib.status = 0
  else if (k.startsWith('st:')) lib.status &= ~+k.slice(3)
}

// ── selection ────────────────────────────────────────────────────────────────
let anchor: number | null = null
export function toggleSel(id: number, on?: boolean) {
  on = on === undefined ? !lib.sel.has(id) : on
  if (on) lib.sel.add(id); else lib.sel.delete(id)
  anchor = id
}
export function rangeSel(id: number) {
  const V = lib.visIds, a = anchor === null ? -1 : V.indexOf(anchor), b = V.indexOf(id)
  if (a < 0 || b < 0) { toggleSel(id, true); return }
  const [s, e] = a < b ? [a, b] : [b, a]
  V.slice(s, e + 1).forEach(x => lib.sel.add(x))
  anchor = id
}
export function selectAll() {
  lib.visIds.forEach(id => lib.sel.add(id))
  toast(`Selected ${lib.visIds.length} visible items`)
}
export function clearSel(): boolean {
  if (!lib.sel.size) return false
  lib.sel.clear()
  return true
}

// ── zoom ─────────────────────────────────────────────────────────────────────
export function setZoomIndex(i: number) {
  lib.zi = Math.max(0, Math.min(Z.length - 1, i))
  ls.set('cm-wiskit-zoom', String(lib.zi))
}

// ── favourites ───────────────────────────────────────────────────────────────
export async function toggleFav(id: number) {
  const r = lib.byId.get(id)
  if (!r) return
  const on = !r.fav
  replaceRow({ ...r, fav: on })                         // show it at once
  try {
    replaceRow(await api.post<Row>(`/api/items/${id}/favourite`, { on }))
  } catch (e) {
    replaceRow(r)
    toast(`Could not save the favourite: ${(e as Error).message}`, 'w')
  }
}

// ── windows a later plan installs (plan 06: the item window, the Collection window) ──
export const hooks: {
  openItem: ((id: number, tab?: number) => void) | null
  editCollection: ((name: string) => void) | null
} = { openItem: null, editCollection: null }
