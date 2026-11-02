// My Notes state (V6 j-notes.js; Qt ui/my_notes_window.py): categories, the notes of the category,
// the open note with an 800 ms autosave (flushed on note switch, workspace switch and page unload).
import { api } from './api'
import { on } from './events.svelte'
import { jobBusy, jobBusyMsg } from './jobs'
import { setWS, toast } from './ui.svelte'
import type { Stamp } from './note-format'

export interface MyNote { file: string; title: string; category: string; created: string; updated: string; body?: string; stamps?: Stamp[]; snippet?: string; head?: string; words?: number }
const AUTOSAVE_MS = 800

class Notes {
  categories: string[] = $state.raw([])
  cat = $state('All')
  list: MyNote[] = $state.raw([])
  file: string | null = $state(null)
  title = $state('')
  category = $state('General')
  body = $state('')
  stamps: Stamp[] = $state.raw([])   // core/note_format.py; sent with the autosave only after a change
  status = $state<'saved' | 'pending' | 'saving' | 'error'>('saved')
  savedAt = $state('')
  preview = $state(false)
  autoRecord = $state(false) // Wiskit asked to record: the empty-state VoiceRec starts and clears this
  revision = $state(0) // external replacements reset editor-local history, even for identical text
}
export const nt = new Notes()

let timer = 0
let dirty = false
let stampsTouched = false
let version = 0
let stampVersion = 0
let opening = 0
let saving: Promise<boolean> | null = null

// the editor's stamp layer (and Apply) change the stamps through this; the autosave sends them
export function setStamps(s: Stamp[]) {
  nt.stamps = s
  stampsTouched = true
  stampVersion++
  edited()
}

export async function loadCategories() {
  try { nt.categories = (await api.get<{ categories: string[] }>('/api/my-notes/categories')).categories } catch { /* keep */ }
}
export async function loadList() {
  try { nt.list = await api.get<MyNote[]>(`/api/my-notes?category=${encodeURIComponent(nt.cat)}`) } catch { /* keep */ }
}
export async function setCat(c: string) {
  nt.cat = c
  await loadList()
}

export async function openMyNote(file: string) {
  const request = ++opening
  if (!await flush()) return false
  const before = version
  try {
    const n = await api.get<MyNote>(`/api/my-notes/${encodeURIComponent(file)}`)
    if (request !== opening || before !== version) return false
    nt.file = n.file; nt.title = n.title; nt.category = n.category; nt.body = n.body ?? ''
    nt.stamps = n.stamps ?? []; stampsTouched = false
    nt.status = 'saved'; nt.savedAt = n.updated.slice(11, 19)
    dirty = false
    nt.revision++
    return true
  } catch (e) { toast((e as Error).message, 'w'); loadList(); return false }
}
function closeMyNote() { opening++; nt.file = null; nt.title = ''; nt.body = ''; nt.stamps = []; stampsTouched = false; dirty = false }

// call on every edit: saves 800 ms after the last change
export function edited() {
  if (!nt.file) return
  dirty = true
  version++
  nt.status = 'pending'
  clearTimeout(timer)
  timer = window.setTimeout(() => { void flush() }, AUTOSAVE_MS)
}

export async function flush(keepalive = false) {
  clearTimeout(timer)
  while (nt.file && (dirty || saving)) {
    if (!saving) saving = save(keepalive).finally(() => { saving = null })
    if (!await saving) return false
  }
  return true
}

async function save(keepalive = false) {
  if (!nt.file || !dirty) return true
  const file = nt.file
  const sendStamps = stampsTouched
  const sentVersion = version, sentStampVersion = stampVersion
  const snapshot = { title: nt.title, category: nt.category, body: nt.body, ...(sendStamps ? { stamps: nt.stamps } : {}) }
  nt.status = 'saving'
  try {
    const r = await fetch(`/api/my-notes/${encodeURIComponent(file)}`, {
      method: 'PUT', keepalive, headers: { 'X-CM': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshot),
    })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
    const m = await r.json() as MyNote
    if (nt.file === file) {
      if (version === sentVersion) { dirty = false; nt.status = 'saved'; nt.savedAt = m.updated.slice(11, 19) }
      else nt.status = 'pending'
      if (stampVersion === sentStampVersion) stampsTouched = false
    }
    nt.list = nt.list.map(x => (x.file === file ? { ...x, title: m.title, category: m.category, updated: m.updated } : x))
    return true
  } catch (e) {
    if (nt.file === file) { nt.status = 'error'; dirty = true; if (sendStamps) stampsTouched = true }
    toast(`Could not save the note: ${(e as Error).message}`, 'w')
    return false
  }
}

export async function newNote(title: string) {
  if (!await flush()) return
  const n = await api.post<MyNote>('/api/my-notes', { title, category: nt.cat })
  await Promise.all([loadCategories(), loadList()])
  await openMyNote(n.file)
  setWS('notes')
}
// Wiskit's wheel (POST /api/app/note): "write" opens a fresh dated note, "record" shows the empty state and VoiceRec starts at once
export async function quickNote(mode: 'write' | 'record') {
  setWS('notes')
  if (!await flush()) return
  if (mode === 'record') { closeMyNote(); nt.autoRecord = true; return }
  const d = new Date(), p = (n: number) => String(n).padStart(2, '0')
  try { await newNote(`Note ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`) }
  catch (e) { toast((e as Error).message, 'w') }
}
export async function deleteMyNote() {
  if (!nt.file) return
  if (!await flush()) return
  const file = nt.file, before = version
  try {
    await api.del(`/api/my-notes/${encodeURIComponent(file)}`)
    if (nt.file === file && before === version) closeMyNote()
    loadList()
  } catch (e) { toast((e as Error).message, 'w') }
}
export async function addCategory(name: string) {
  nt.categories = (await api.post<{ categories: string[] }>('/api/my-notes/categories', { name })).categories
}

export async function summarize() {
  if (!nt.file) return
  if (!nt.body.trim()) { toast('Nothing to summarize: write something first.', 'w'); return }
  if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
  if (!await flush()) return
  try { await api.post(`/api/my-notes/${encodeURIComponent(nt.file)}/summarize`); toast('Summarizing…') }
  catch (e) { toast((e as Error).message, 'w') }
}

// Reformat & classify: the job proposes, the preview window shows it, Apply saves through the autosave
export interface ReformatProposal { file: string; old_title: string; old_category: string; title: string; category: string; topics: string[]; body: string; stamps?: Stamp[] | null; instruction?: string }
export const rf: { proposal: ReformatProposal | null } = $state({ proposal: null })

export async function reformat() {
  if (!nt.file) return
  if (!nt.body.trim()) { toast('Nothing to reformat: write something first.', 'w'); return }
  if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
  if (!await flush()) return
  try { await api.post(`/api/my-notes/${encodeURIComponent(nt.file)}/reformat`); toast('Reformatting…') }
  catch (e) { toast((e as Error).message, 'w') }
}

export async function applyReformat(category: string) {
  const p = rf.proposal
  if (!p) return
  if (!await flush()) return
  if (nt.file !== p.file && !await openMyNote(p.file)) return
  nt.title = p.title; nt.category = category; nt.body = p.body
  if (p.stamps) setStamps(p.stamps)
  nt.revision++
  edited()
  if (!await flush()) return
  rf.proposal = null
  await Promise.all([loadCategories(), loadList()])
  toast('Reformatted note saved')
}
export function discardReformat() { rf.proposal = null }

export async function digestShots(files: File[]) {
  if (!nt.file || !files.length) return
  if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
  if (!await flush()) return
  const file = nt.file
  const images = await Promise.all(files.map(f => new Promise<{ name: string; type: string; data: string }>((res, rej) => {
    const r = new FileReader()
    r.onload = () => res({ name: f.name, type: f.type || 'image/png', data: String(r.result).split(',')[1] ?? '' })
    r.onerror = () => rej(r.error)
    r.readAsDataURL(f)
  })))
  try { await api.post(`/api/my-notes/${encodeURIComponent(file)}/digest`, { images }); toast(`Transcribing ${images.length} screenshot(s)…`) }
  catch (e) { toast((e as Error).message, 'w') }
}

// Voice note: the audio goes to the PC's Whisper call; the text lands in the open note (or a new one)
export async function voiceNote(audio: Blob, file: string | null) {
  if (!await flush()) return
  const q = file ? `?file=${encodeURIComponent(file)}` : ''
  try {
    const r = await api.upload<MyNote & { text: string }>(`/api/my-notes/voice${q}`, audio)
    await Promise.all([loadCategories(), loadList()])
    await openMyNote(r.file)
    setWS('notes')
    toast('Voice note added')
  } catch (e) { toast((e as Error).message, 'w') }
}

export const summaryLine = () => {
  const m = nt.body.match(/## AI summary\n([\s\S]*?)(?=\n## |$)/)
  return m ? m[1].replace(/^- /gm, '').split('\n').filter(Boolean).slice(0, 2).join(' · ').slice(0, 150) : ''
}

let installed = false
export function installNotes() {
  if (installed) return
  installed = true
  loadCategories(); loadList()
  // a Summarize / digest job wrote the open note: reload it (no pending edit to lose: flushed first)
  on('notes_changed', (d: { file: string; job?: boolean; personal?: boolean }) => {
    if (d.personal) loadList()
    if (d.job && d.file === nt.file && !dirty && !saving) void openMyNote(d.file)
  })
  on('reformat_preview', (d: ReformatProposal) => { rf.proposal = d })
  // Unload is best effort; a browser may end the page before keepalive completes.
  addEventListener('pagehide', () => { void flush(true) })
}
