// Canvas state (V6 i-canvas.js CV; Qt canvas.py + ui/canvas_window.py): the canvases, the active
// one (the board shows it and every Add to canvas lands in it), its elements, the view, the
// selection. Files stay data/canvases/<id>.json; a save sends the rev it loaded and a stale one
// (the Qt canvas window saved in between) is refused with 409, then Reload is offered.
import { SvelteSet } from 'svelte/reactivity'
import { api, ApiError } from './api'
import { on } from './events.svelte'
import { setWS, toast, ui } from './ui.svelte'
import { confirmWin, promptWin } from './windows.svelte'
import { thumbSrc } from './library.svelte'

export interface CEl {
  id: string; type: 'image' | 'note'; x: number; y: number; w?: number; h?: number
  source?: 'db' | 'file'; item_id?: number; file_path?: string; label?: string; text?: string; color?: string
}
export interface CanvasRow { id: string; name: string; count: number; updated: number }
export interface CanvasDoc { id: string; name: string; items: CEl[]; [k: string]: unknown }

class Cv {
  list: CanvasRow[] = $state.raw([])
  active: string | null = $state(null)
  doc: CanvasDoc | null = $state(null)
  rev = 0
  dirty = $state(false)
  sel = new SvelteSet<string>()
  fresh = new SvelteSet<string>()
  editing: string | null = $state(null)
  s = $state(0.9)
  x = $state(20)
  y = $state(30)
  fitTick = $state(0)       // the board fits the view when this changes
}
export const cv = new Cv()

export const activeRow = () => cv.list.find(r => r.id === cv.active) ?? null
export const activeName = () => cv.doc?.name ?? activeRow()?.name ?? 'none'
export const activeCount = () => (cv.doc && cv.doc.id === cv.active ? cv.doc.items.length : activeRow()?.count ?? 0)
export const selEls = () => (cv.doc ? cv.doc.items.filter(e => cv.sel.has(e.id)) : [])
export const imgSrc = (e: CEl) => (e.source === 'file' ? `/files/canvas-uploads/${e.file_path}` : thumbSrc(e.item_id ?? 0))

export function markFresh(ids: string[]) {
  ids.forEach(id => cv.fresh.add(id))
  setTimeout(() => ids.forEach(id => cv.fresh.delete(id)), 900)
}

// ── load ─────────────────────────────────────────────────────────────────────
export async function loadList() {
  try { cv.list = await api.get<CanvasRow[]>('/api/canvases') } catch { /* keep */ }
}
async function loadDoc(id: string | null) {
  if (!id) { cv.doc = null; cv.rev = 0; cv.dirty = false; cv.sel.clear(); return }
  try {
    const r = await api.get<{ canvas: CanvasDoc; rev: number }>(`/api/canvases/${encodeURIComponent(id)}`)
    cv.doc = r.canvas; cv.rev = r.rev; cv.dirty = false; cv.editing = null
    for (const k of [...cv.sel]) if (!r.canvas.items.some(e => e.id === k)) cv.sel.delete(k)
  } catch (e) { toast((e as Error).message, 'w'); cv.doc = null }
}

export async function openCanvas(id: string) {
  if (id === cv.active && cv.doc?.id === id) return
  if (cv.dirty && !(await save(true))) return
  try { await api.put('/api/canvas/active', { id }) } catch (e) { toast((e as Error).message, 'w'); return }
  cv.active = id
  cv.sel.clear()
  await loadDoc(id)
  cv.fitTick++
}

// ── save ─────────────────────────────────────────────────────────────────────
export function markDirty() { cv.dirty = true }

export async function save(quiet = false, keepalive = false): Promise<boolean> {
  const d = cv.doc
  if (!d) return true
  cv.dirty = false
  try {
    const r = await fetch(`/api/canvases/${encodeURIComponent(d.id)}`, {
      method: 'PUT', keepalive, headers: { 'X-CM': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ canvas: $state.snapshot(d), rev: cv.rev }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new ApiError(r.status, j.detail || r.statusText)
    if (cv.doc?.id === d.id) cv.rev = j.rev
    cv.list = cv.list.map(x => (x.id === d.id ? { ...x, count: d.items.length } : x))
    if (!quiet) toast(`Saved ${d.name}`)
    return true
  } catch (e) {
    cv.dirty = true
    if (e instanceof ApiError && e.status === 409) conflict(d.name)
    else toast(`Could not save the canvas: ${(e as Error).message}`, 'w')
    return false
  }
}

async function conflict(name: string) {
  const ok = await confirmWin({
    title: `${name} changed elsewhere`, code: 'CNV-36', ok: 'Reload',
    msg: 'Another window (the Qt canvas?) saved this canvas after you opened it, so your save was refused to keep its changes.',
    detail: 'Reload shows the newer file and drops the unsaved changes made here. Cancel keeps them on screen, unsaved.',
  })
  if (ok) { await loadDoc(cv.active); cv.fitTick++ }
}

// ── canvases: new, rename, delete ────────────────────────────────────────────
const clash = (v: string, but?: string) => cv.list.some(c => c.id !== but && c.name.toLowerCase() === v.toLowerCase())

export async function newCanvas(): Promise<boolean> {
  const v = await promptWin({
    title: 'New canvas', code: 'CNV-30', label: 'Name', ok: 'Create',
    hint: 'Saved in data/canvases. It becomes the active canvas: Add to canvas lands there.',
    check: v => (!v ? 'Enter a name.' : clash(v) ? 'A canvas with that name exists.' : ''),
  })
  if (!v) return false
  if (cv.dirty && !(await save(true))) return false
  try {
    const row = await api.post<CanvasRow>('/api/canvases', { name: v })
    await loadList()
    cv.active = row.id
    cv.sel.clear()
    await loadDoc(row.id)
    cv.fitTick++
    if (ui.ws !== 'canvas') toast(`Created ${v}. Add to canvas lands there now.`, '', { label: 'Open', run: () => setWS('canvas') })
    return true
  } catch (e) { toast((e as Error).message, 'w'); return false }
}

export async function renameTo(v: string) {
  const d = cv.doc
  if (!d || !v || v === d.name) return
  if (clash(v, d.id)) { toast(`${v} already exists`, 'w'); return }
  if (cv.dirty && !(await save(true))) return
  try {
    await api.patch(`/api/canvases/${encodeURIComponent(d.id)}`, { name: v })
    await Promise.all([loadList(), loadDoc(d.id)])
    toast(`Renamed to ${v}`)
  } catch (e) { toast((e as Error).message, 'w') }
}
export async function renameCanvas() {
  const d = cv.doc
  if (!d) return
  const v = await promptWin({
    title: 'Rename the canvas', code: 'CNV-34', label: 'Name', value: d.name, ok: 'Rename',
    check: v => (!v ? 'Enter a name.' : clash(v, d.id) ? 'A canvas with that name exists.' : ''),
  })
  if (v) await renameTo(v)
}

export async function deleteCanvas() {
  const d = cv.doc
  if (!d) return
  const ok = await confirmWin({
    title: `Delete ${d.name}?`, code: 'CNV-35', danger: true, ok: 'Delete canvas',
    msg: `The canvas file and its ${d.items.length} element${d.items.length === 1 ? '' : 's'} are removed. The library items stay.`,
  })
  if (!ok) return
  try {
    await api.del(`/api/canvases/${encodeURIComponent(d.id)}`)
    cv.dirty = false; cv.sel.clear()
    await loadList()
    const a = await api.get<{ id: string | null }>('/api/canvas/active')
    cv.active = a.id
    await loadDoc(a.id)
    cv.fitTick++
    toast(`Deleted ${d.name}`)
  } catch (e) { toast((e as Error).message, 'w') }
}

// ── live updates ─────────────────────────────────────────────────────────────
let installed = false
export async function installCanvas() {
  if (installed) return
  installed = true
  await loadList()
  try { cv.active = (await api.get<{ id: string | null }>('/api/canvas/active')).id } catch { /* none */ }
  await loadDoc(cv.active)
  cv.fitTick++
  // another window (or an attach) wrote a canvas: refresh the list; reload the open one when it is
  // clean and the file is newer than what we hold (our own saves set cv.rev before this runs)
  on('canvas_changed', (d: { id: string; rev: number }) => {
    loadList()
    setTimeout(() => {
      if (d.id !== cv.active) return
      if (!d.rev) { reloadActive(); return }
      if (cv.doc && d.rev !== cv.rev && !cv.dirty) loadDoc(d.id)
    }, 250)
  })
  on('canvas_active', (d: { id: string | null }) => {
    if (d.id !== cv.active && !cv.dirty) { cv.active = d.id; loadDoc(d.id).then(() => cv.fitTick++) }
  })
  addEventListener('pagehide', () => { if (cv.dirty) save(true, true) })
}
async function reloadActive() {
  const a = await api.get<{ id: string | null }>('/api/canvas/active').catch(() => ({ id: null }))
  cv.active = a.id
  await loadDoc(a.id)
}
