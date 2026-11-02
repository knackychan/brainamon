// The Knowledge workspace state (V6 h-know.js KS; Qt ui/knowledge_panel.py + connections_panel.py):
// found sources and their ticks, the saved notes, the open note, the topics, the connection cards,
// the synthesis step log. The logic is server-side (knowledge.py, connections.py).
import { SvelteSet } from 'svelte/reactivity'
import { api, ApiError } from './api'
import { live, on } from './events.svelte'
import { startJob, jobBusy, jobBusyMsg } from './jobs'
import { lib, type Row } from './library.svelte'
import { setWS, toast } from './ui.svelte'

export interface NoteRow { file: string; title: string; kind: string; sources: number[]; created: string; updated: string; snippet: string }
export interface OpenNote { file: string; meta: Record<string, string>; body: string; row: NoteRow }
export interface Topic { id: number; name: string; query: string; note_path: string | null; last_run: number | null; new: number }
export interface CxCard { kind: 'bridge' | 'drift'; key: string; text: string; item_ids: number[]; items: { id: number; title: string }[] }

const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private window */ } },
}
const CAPS = ['30', '100', '300', '1000', 'All'] as const

class Know {
  q = $state('')
  cap = $state<string>(CAPS.includes((ls.get('cm-v6-kcap') ?? '') as any) ? ls.get('cm-v6-kcap')! : '30')
  cat = $state('')
  items: Row[] = $state.raw([])
  mode = $state('')
  loading = $state(false)
  tick = new SvelteSet<number>()
  notes: NoteRow[] = $state.raw([])
  sort = $state<'updated' | 'created' | 'az'>('updated')
  note: OpenNote | null = $state.raw(null)
  noteMatches: string[] = $state.raw([])
  topics: Topic[] = $state.raw([])
  topicId: number | null = $state(null)
  cards: CxCard[] = $state.raw([])
  lastScan = $state(0)
  cxSel = new SvelteSet<string>()
  cxQueue: string[] = $state([])
  cxActive = $state('')                // the card whose Accept note job is running
  log: string[] = $state([])
  merge = $state<'integrate' | 'append'>('integrate')
}
export const ks = new Know()
export { CAPS }

const stamp = () => new Date().toTimeString().slice(0, 8)
export function klog(line: string) {
  ks.log.push(`[${stamp()}] ${line}`)
  if (ks.log.length > 80) ks.log.splice(0, ks.log.length - 80)
}

// ── find sources ─────────────────────────────────────────────────────────────
export async function searchSources(q = ks.q) {
  q = q.trim()
  if (!q) { toast('Enter a topic to search.', 'w'); return }
  ks.q = q; ks.cat = ''; ks.loading = true
  try {
    const r = await api.post<{ items: Row[]; mode: string; notes: { file: string }[] }>(
      '/api/knowledge/sources', { topic: q, limit: ks.cap === 'All' ? 100000 : +ks.cap, smart: true })
    ks.items = r.items; ks.mode = r.mode; ks.tick.clear()
    ks.noteMatches = r.notes.map(n => n.file)
    klog(`Search “${q}” · ${r.items.length} source(s) · ${r.mode === 'hybrid' ? 'keyword + meaning' : 'keyword (every word)'}`)
  } catch (e) { toast((e as Error).message, 'w') } finally { ks.loading = false }
}

export async function loadCategory(name: string) {
  if (!name) return
  ks.loading = true
  try {
    const r = await api.get<{ items: Row[] }>('/api/knowledge/category/' + encodeURIComponent(name))
    const cap = ks.cap === 'All' ? Infinity : +ks.cap
    ks.items = r.items.slice(0, cap); ks.cat = name; ks.mode = 'collection'; ks.tick.clear(); ks.noteMatches = []
    klog(`Loaded collection ${name} · ${r.items.length} item(s)${r.items.length > cap ? `, capped at ${cap}` : ''}`)
  } catch (e) { toast((e as Error).message, 'w') } finally { ks.loading = false }
}

export function setCap(c: string) {
  ks.cap = c
  ls.set('cm-v6-kcap', c)
  if (ks.cat) loadCategory(ks.cat); else if (ks.q) searchSources()
}

// none ticked = all listed
export const picked = () => (ks.tick.size ? ks.items.filter(r => ks.tick.has(r.id)) : ks.items).map(r => r.id)

// ── notes ────────────────────────────────────────────────────────────────────
export async function loadNotes() {
  try { ks.notes = await api.get<NoteRow[]>(`/api/notes?sort=${ks.sort}`) } catch { /* keep the list */ }
}
export async function openNote(file: string) {
  try {
    ks.note = await api.get<OpenNote>(`/api/notes/${encodeURIComponent(file)}`)
    const inNote = ks.items.filter(r => ks.note!.row.sources.includes(r.id)).length
    klog(`Opened ${file} (${ks.note.row.sources.length} sources)${inNote ? ` · ${inNote} of the listed sources are in it` : ''}`)
  } catch (e) { toast(e instanceof ApiError && e.status === 404 ? `${file} is gone` : (e as Error).message, 'w'); loadNotes() }
}
export function openNoteInKnowledge(file: string) {
  setWS('know')
  openNote(file)
}
export function closeNote() { ks.note = null }

export async function renameNote(title: string) {
  if (!ks.note) return
  const r = await api.post<NoteRow>(`/api/notes/${encodeURIComponent(ks.note.file)}/rename`, { title })
  await openNote(r.file)
  loadNotes(); loadTopics()
  toast(`Renamed the note to ${r.file}`)
}
export async function deleteNote() {
  if (!ks.note) return
  const f = ks.note.file
  await api.del(`/api/notes/${encodeURIComponent(f)}`)
  ks.note = null
  loadNotes(); loadTopics()
  toast(`Deleted ${f}`)
}

// ── synthesize, augment, the bench ───────────────────────────────────────────
export async function synthesize() {
  const ids = picked()
  if (!ids.length) { toast('No sources loaded. Search on the rail first.', 'w'); return }
  const topic = ks.cat || ks.q || 'saved items'
  klog(`Synthesize “${topic}” · ${ids.length} source(s)`)
  await startJob('note', { ids, force: true, opts: { topic } })
}
export async function augment() {
  if (!ks.note) { toast('Open a note first (Saved notes on the rail)', 'w'); return }
  const have = new Set(ks.note.row.sources)
  const ids = picked().filter(id => !have.has(id))
  if (!ids.length) { toast('All ticked sources are already in this note.', 'w'); return }
  klog(`Augment ${ks.note.file} · ${ids.length} new source(s) · ${ks.merge === 'append' ? 'append & merge' : 'integrate & reorganize'}`)
  await startJob('note', { ids, force: true, opts: { topic: ks.note.meta.topic || ks.note.row.title, mode: 'augment', note: ks.note.file, merge: ks.merge } })
}

// ── topics ───────────────────────────────────────────────────────────────────
export async function loadTopics() {
  try { ks.topics = await api.get<Topic[]>('/api/topics') } catch { /* keep the list */ }
}
export async function addTopic(name: string) {
  ks.topics = await api.post<Topic[]>('/api/topics', { name })
  ks.topicId = ks.topics.find(t => t.name === name)?.id ?? ks.topicId
}
export async function removeTopic(id: number) { ks.topics = await api.del<Topic[]>(`/api/topics/${id}`) }
export async function refreshTopic(id: number) {
  if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
  try {
    await api.post(`/api/topics/${id}/refresh`)
    const t = ks.topics.find(x => x.id === id)
    klog(`Refresh digest “${t?.name}” · ${t?.new ?? 0} new item(s)`)
    toast(`Refreshing the “${t?.name}” digest`)
  } catch (e) { toast((e as Error).message, 'w') }
}

// ── connections ──────────────────────────────────────────────────────────────
export async function loadCards() {
  try {
    const r = await api.get<{ cards: CxCard[]; last_scan: number }>('/api/connections')
    ks.cards = r.cards; ks.lastScan = r.last_scan
    for (const k of [...ks.cxSel]) if (!r.cards.some(c => c.key === k)) ks.cxSel.delete(k)
  } catch { /* keep the cards */ }
}
// a connections scan is a one-item `connections` job; its step lines arrive as live.step
export const cxScanning = () => live.jobs.current?.kind === 'connections'

export async function scanConnections() {
  if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
  try { await api.post('/api/connections/scan'); klog('Find connections: scanning the library…') }
  catch (e) { toast((e as Error).message, 'w') }
}
export async function resetConnections() {
  ks.cxQueue = []
  ks.cxActive = ''
  const r = await api.post<{ cards: CxCard[]; last_scan: number }>('/api/connections/reset')
  ks.cards = r.cards
  toast('Reset. You can scan or synthesize again.')
}
export async function dismissCard(key: string) {
  const r = await api.post<{ cards: CxCard[] }>(`/api/connections/${encodeURIComponent(key)}/dismiss`)
  ks.cards = r.cards
  ks.cxSel.delete(key)
}
export async function setCardSources(key: string, ids: number[]) {
  const r = await api.post<{ cards: CxCard[] }>(`/api/connections/${encodeURIComponent(key)}/sources`, { ids })
  ks.cards = r.cards
}
// Accept = synthesize the card's sources into a note; several cards run one after the other
export function acceptCards(keys: string[]) {
  ks.cxQueue = [...ks.cxQueue, ...keys.filter(k => k !== ks.cxActive && !ks.cxQueue.includes(k))]
  drainQueue()
}
async function drainQueue() {
  if (live.jobs.current || !ks.cxQueue.length) return
  const key = ks.cxQueue.shift()!
  try {
    await api.post(`/api/connections/${encodeURIComponent(key)}/accept`)
    ks.cxActive = key
    klog(`Accept: synthesizing the card ${key}`)
  } catch (e) { toast((e as Error).message, 'w'); drainQueue() }
}

// ── live updates ─────────────────────────────────────────────────────────────
let installed = false
export function installKnowledge() {
  if (installed) return
  installed = true
  loadNotes(); loadTopics(); loadCards()
  on('notes_changed', (d: { file: string; job?: boolean; personal?: boolean }) => {
    loadNotes(); loadTopics()
    if (d.file && ks.note?.file === d.file) openNote(d.file)
    else if (d.file && d.job && !d.personal && !ks.note) openNote(d.file)   // a synthesis just landed
  })
  on('connections_changed', () => loadCards())
  on('synth', (d: { line: string }) => klog(d.line))
  on('job', () => { if (!live.jobs.current) { ks.cxActive = ''; setTimeout(drainQueue, 300) } })
  on('items_changed', () => { if (ks.items.length) refreshItems() })
}

// keep the listed sources current after a bench job (Describe / Analyze) changed them
let rt = 0
function refreshItems() {
  clearTimeout(rt)
  rt = window.setTimeout(() => {
    ks.items = ks.items.map(r => lib.byId.get(r.id) ?? r)
  }, 400)
}
