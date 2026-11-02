// Plan 05: makes the Library commands live (bind), adds the Library keys (Ctrl+A, Esc, + - 0,
// Delete), follows job events on the cells, refetches changed rows, and adds the "Items" group to
// the Ctrl+K palette. Called once when the Library workspace mounts.
import { bind, runCmd } from './commands'
import { act } from './cardmenu'
import { titleOf } from './cards/card'
import { api } from './api'
import { live, on } from './events.svelte'
import { onEsc, onKey } from './keys'
import {
  clearFilters, clearSel, lib, loadLibrary, refetch, selectAll, setFilter, setSmart, thumbSrc } from './library.svelte'
import { fitAll, setZoom } from './map'
import { addPaletteProvider } from './palette'
import { setWS, toast, ui } from './ui.svelte'

const selOff = () => !lib.sel.size
const toLib = () => { if (ui.ws !== 'lib') setWS('lib') }

function zoomBy(d: number) {
  toLib()
  if (lib.view === 'list') { toast('Zoom works in the grid view', 'w'); return }
  if (d) setZoom(lib.zi + d); else fitAll()
}

// V6 cellFlash: working keeps the brackets on; done and error flash them
const flashT = new Map<number, number>()
function cellFlash(id: number, st: 'done' | 'err', ms: number) {
  clearTimeout(flashT.get(id))
  lib.cellState.set(id, st)
  flashT.set(id, window.setTimeout(() => { if (lib.cellState.get(id) === st) lib.cellState.delete(id); flashT.delete(id) }, ms))
}

async function syncWorking() {
  try {
    const p = await api.get<{ items: { id: number; state: string }[] }>('/api/jobs/progress')
    if (!live.jobs.current) return
    for (const it of p.items) if (it.state === 'working' && !lib.cellState.has(it.id)) lib.cellState.set(it.id, 'worked')
  } catch { /* the next job_item marks the next card */ }
}

let installed = false
export function installLibrary() {
  if (installed) return
  installed = true
  loadLibrary()

  bind('select-all', () => { toLib(); selectAll() })
  bind('clear-sel', () => { clearSel() }, { off: selOff, offMsg: () => 'Nothing is selected' })
  bind('clear-status', () => { lib.status = 0 }, { off: () => !lib.status, offMsg: () => 'No status filter is on' })
  bind('clear-filters', () => { toLib(); clearFilters() })
  bind('view-list', () => { toLib(); setFilter('view', lib.view === 'list' ? 'grid' : 'list') }, { check: () => lib.view === 'list' })
  bind('variant', () => { toLib(); setFilter('variant', lib.variant === 'fa2' ? 'full' : 'fa2') }, { check: () => lib.variant === 'full' })
  bind('smart', () => setSmart(!lib.smart), { check: () => lib.smart })
  bind('favs', () => { toLib(); setFilter('fav', lib.fav === 'fav' ? 'all' : 'fav') }, { check: () => lib.fav === 'fav' })
  bind('zin', () => zoomBy(1))
  bind('zout', () => zoomBy(-1))
  bind('zfit', () => zoomBy(0))

  onKey(e => {
    if (ui.ws !== 'lib') return false
    const mod = e.ctrlKey || e.metaKey
    if (mod && (e.key === 'a' || e.key === 'A')) { selectAll(); return true }
    if (mod || e.altKey) return false
    if ((e.key === 'Delete' || e.key === 'Backspace') && lib.sel.size) { runCmd('delete-sel'); return true }
    if (e.key === '+' || e.key === '=') { zoomBy(1); return true }
    if (e.key === '-' || e.key === '_') { zoomBy(-1); return true }
    if (e.key === '0') { zoomBy(0); return true }
    return false
  })
  onEsc(() => ui.ws === 'lib' && clearSel())

  // the "Clear filters" link in the empty state (and any other data-cmd button on the board)
  document.addEventListener('click', e => {
    const b = (e.target as HTMLElement).closest<HTMLElement>('#ws-lib [data-cmd]')
    if (b) runCmd(b.dataset.cmd!)
  })

  on('job_item', (d: { id: number; state: string }) => {
    if (d.state === 'working') lib.cellState.set(d.id, 'worked')
    else if (d.state === 'done') cellFlash(d.id, 'done', 2800)
    else if (d.state === 'error') cellFlash(d.id, 'err', 3200)
  })
  // coalesce bursts of items_changed into one refetch
  let pending = new Set<number>(), t = 0
  on('items_changed', (d: { ids: number[] }) => {
    d.ids.forEach(id => pending.add(id))
    clearTimeout(t)
    t = window.setTimeout(() => {
      const ids = [...pending]; pending = new Set()
      refetch(ids).catch(err => toast(`Could not refresh items: ${(err as Error).message}`, 'w'))
    }, 120)
  })
  // a job that ends while its last item still shows "working" (stopped, failed run)
  on('job', (d: { current: unknown }) => {
    if (!d.current) for (const [id, s] of lib.cellState) if (s === 'worked') lib.cellState.delete(id)
  })
  // a (re)connect or a reload mid-job: the items already working sent their job_item before we
  // listened, so read them from the progress list once
  on('hello', (d: { jobs: { current: unknown } }) => { if (d.jobs.current) syncWorking() })
  if (live.jobs.current) syncWorking()

  addPaletteProvider(q => {
    const rows = []
    for (const r of lib.rows) {
      if (String(r.id).includes(q) || r.title.toLowerCase().includes(q) || r.creator.toLowerCase().includes(q) || r.tags.toLowerCase().includes(q)) {
        rows.push({ label: `No.${r.id} · ${titleOf(r)}`, key: r.creator, img: r.thumb ? thumbSrc(r.id) : undefined, icon: 'img', run: () => act('open', r.id) })
        if (rows.length >= 6) break
      }
    }
    return { name: 'Items', rows }
  })
}
