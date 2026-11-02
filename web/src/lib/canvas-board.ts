// The board's view and tools (V6 i-canvas.js cvApply, fitCanvas, cvZoom, toWorld, cvReveal,
// arrange, cvAction). Used by the board, its tool bar, the rail tiles and the context menu.
import { cv, deleteCanvas, markDirty, markFresh, newCanvas, renameCanvas, save, selEls, type CEl } from './canvas.svelte'
import { setWS, toast, ui } from './ui.svelte'
import { promptWin } from './windows.svelte'

const board = () => document.getElementById('cv-board')
const world = () => document.getElementById('cv-world')
// a file chooser (edit-commands has one too; kept local so this module imports no windows)
function pickFile(accept: string): Promise<File | null> {
  return new Promise(res => {
    const f = document.createElement('input')
    f.type = 'file'; f.accept = accept
    f.onchange = () => res(f.files?.[0] ?? null)
    f.oncancel = () => res(null)
    f.click()
  })
}
const uid = () => Math.random().toString(16).slice(2, 10)

export function toWorld(cx: number, cy: number) {
  const r = board()!.getBoundingClientRect()
  return { x: (cx - r.left - cv.x) / cv.s, y: (cy - r.top - cv.y) / cv.s }
}
export function center() {
  const b = board()
  return b && b.clientWidth ? { x: (b.clientWidth / 2 - cv.x) / cv.s, y: (b.clientHeight / 2 - cv.y) / cv.s } : { x: 200, y: 200 }
}

function bounds(w: HTMLElement) {
  const els = [...w.children] as HTMLElement[]
  if (!els.length) return null
  let a = 1e9, b = 1e9, c = -1e9, d = -1e9
  for (const el of els) {
    const x = el.offsetLeft, y = el.offsetTop
    a = Math.min(a, x); b = Math.min(b, y - 22); c = Math.max(c, x + el.offsetWidth); d = Math.max(d, y + el.offsetHeight)
  }
  return { a, b, c, d }
}

export function fit() {
  const w = world(), bd = board()
  const B = w ? bounds(w) : null, W = bd?.clientWidth ?? 0, H = bd?.clientHeight ?? 0
  if (!B || !W) { cv.s = 1; cv.x = 24; cv.y = 34; return }
  const s = Math.max(0.1, Math.min(1.4, Math.min((W - 60) / (B.c - B.a), (H - 80) / (B.d - B.b))))
  cv.s = s; cv.x = (W - (B.c - B.a) * s) / 2 - B.a * s; cv.y = (H - 30 - (B.d - B.b) * s) / 2 - B.b * s
}

export function zoom(f: number, at?: { x: number; y: number }) {
  const s2 = Math.max(0.1, Math.min(2.5, cv.s * f))
  const bd = board()
  if (s2 === cv.s || !bd) return
  const r = bd.getBoundingClientRect(), px = at ? at.x - r.left : r.width / 2, py = at ? at.y - r.top : r.height / 2
  cv.x = px - (px - cv.x) * s2 / cv.s; cv.y = py - (py - cv.y) * s2 / cv.s; cv.s = s2
}

// bring a new element into view when it landed off screen
export function reveal(e: CEl) {
  const bd = board()
  if (ui.ws !== 'canvas' || !bd?.clientWidth) return
  const W = bd.clientWidth, H = bd.clientHeight, x = e.x * cv.s + cv.x, y = e.y * cv.s + cv.y, w = (e.w || 150) * cv.s
  if (x < 0 || y < 0 || x + w > W || y + 60 > H) { cv.x = W / 2 - (e.x + (e.w || 150) / 2) * cv.s; cv.y = H / 3 - e.y * cv.s }
}

function arrange(kind: 'row' | 'grid') {
  const s = selEls()
  if (s.length < 2) { toast('Select two or more elements to arrange', 'w'); return }
  const dim = (e: CEl) => {
    const el = world()?.querySelector<HTMLElement>(`[data-eid="${e.id}"]`)
    return { w: el ? el.offsetWidth : e.w ?? 150, h: el ? el.offsetHeight : (e.w ?? 150) * 1.6 }
  }
  const x0 = Math.min(...s.map(e => e.x)), y0 = Math.min(...s.map(e => e.y))
  if (kind === 'row') {
    let x = x0
    s.slice().sort((a, b) => a.x - b.x).forEach(e => { e.x = x; e.y = y0; x += dim(e).w + 28 })
  } else {
    const L = s.slice().sort((a, b) => a.y - b.y || a.x - b.x), cols = Math.ceil(Math.sqrt(L.length))
    const cw = Math.max(...L.map(e => dim(e).w)) + 28, ch = Math.max(...L.map(e => dim(e).h)) + 40
    L.forEach((e, i) => { e.x = x0 + (i % cols) * cw; e.y = y0 + Math.floor(i / cols) * ch })
  }
  markDirty()
  requestAnimationFrame(() => {   // keep the result in view
    const w = world(), bd = board(), B = w ? bounds(w) : null
    if (B && bd && (B.a * cv.s + cv.x < 0 || B.b * cv.s + cv.y < 0 || B.c * cv.s + cv.x > bd.clientWidth || B.d * cv.s + cv.y > bd.clientHeight)) fit()
  })
}

export type CvAct = 'new' | 'rename' | 'del' | 'note' | 'image' | 'label' | 'delete' | 'row' | 'grid' | 'all' | 'zin' | 'zout' | 'fit' | 'save' | 'edit'

export async function cvAction(a: CvAct, at?: { x: number; y: number }) {
  const d = cv.doc
  if (a === 'new') { newCanvas(); return }
  if (!d) { toast('Create a canvas first', 'w'); return }
  if (a === 'note') {
    const p = at ?? center()
    const e: CEl = { id: uid(), type: 'note', text: 'New note', color: '#FFF9C4', x: Math.round(p.x - 100), y: Math.round(p.y - 30), w: 240, h: 160 }
    d.items.push(e)
    cv.sel.clear(); cv.sel.add(e.id); markFresh([e.id])
    if (ui.ws !== 'canvas') setWS('canvas')
    markDirty()
    cv.editing = e.id
  } else if (a === 'image') {
    const f = await pickFile('image/*')
    if (!f) return
    const p = at ?? center()
    try {
      const r = await fetch(`/api/canvases/${encodeURIComponent(d.id)}/image?name=${encodeURIComponent(f.name)}`, { method: 'PUT', headers: { 'X-CM': '1' }, body: f })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || r.statusText)
      const e: CEl = { ...j, id: uid(), x: Math.round(p.x - 100), y: Math.round(p.y - 120) }
      d.items.push(e)
      cv.sel.clear(); cv.sel.add(e.id); markFresh([e.id])
      markDirty()
    } catch (err) { toast(`Could not add the image: ${(err as Error).message}`, 'w') }
  } else if (a === 'label') {
    const s = selEls()
    if (s.length !== 1 || s[0].type !== 'image') { toast('Select one image to label', 'w'); return }
    const v = await promptWin({ title: 'Set label', code: 'CNV-33', label: 'Label', value: s[0].label ?? '', ok: 'Set label', hint: 'Leave it empty to remove the label.', check: () => '' })
    if (v === null) return
    s[0].label = v
    markDirty()
  } else if (a === 'edit') {
    const s = selEls()
    if (s.length === 1 && s[0].type === 'note') cv.editing = s[0].id
  } else if (a === 'delete') {
    const s = selEls()
    if (!s.length) { toast('Select elements first', 'w'); return }
    const before = d.items.slice()
    d.items = d.items.filter(e => !cv.sel.has(e.id))
    cv.sel.clear()
    markDirty()
    toast(`Deleted ${s.length} element${s.length === 1 ? '' : 's'}`, '', { label: 'Undo', run: () => { if (cv.doc === d) { d.items = before; markDirty() } } })
  } else if (a === 'row' || a === 'grid') arrange(a)
  else if (a === 'all') d.items.forEach(e => cv.sel.add(e.id))
  else if (a === 'zin') zoom(1.2)
  else if (a === 'zout') zoom(1 / 1.2)
  else if (a === 'fit') fit()
  else if (a === 'save') save()
  else if (a === 'rename') renameCanvas()
  else if (a === 'del') deleteCanvas()
}

// why a tool is unavailable right now (null = available)
export function offWhy(a: CvAct): string | null {
  const s = selEls()
  if (a === 'new') return null
  if (!cv.doc) return 'Create a canvas first'
  if (a === 'label') return s.length === 1 && s[0].type === 'image' ? null : 'Select one image to label'
  if (a === 'delete') return s.length ? null : 'Select elements first'
  if (a === 'row' || a === 'grid') return s.length >= 2 ? null : 'Select two or more elements'
  return null
}
