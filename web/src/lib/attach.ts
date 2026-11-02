// Plan 09: "attach from anywhere" (V6 i-canvas.js attachItems / attachText / fly / grip drag;
// Qt main_window._attach_to_canvas). Every Add to canvas in the app lands in the active canvas
// (the menubar chip): the server builds the elements and appends them to the file, the open
// board adds them in place, and a thumbnail flies from where the action started to the target.
// Binds new-canvas, sel-canvas, canvas-target, the card canvas actions and the grip, Wiskit and
// Knowledge Attach, and the palette "Canvases" group.
import { api } from './api'
import { askHooks } from './ask.svelte'
import { cv, activeCount, activeName, installCanvas, markFresh, newCanvas, openCanvas, save, type CEl } from './canvas.svelte'
import { reveal, toWorld } from './canvas-board'
import { cardActs } from './cardmenu'
import { bind, type Cmd, type MenuEntry } from './commands'
import { lib, thumbSrc } from './library.svelte'
import { openMenu } from './menu.svelte'
import { addPaletteProvider } from './palette'
import { setWS, toast, ui } from './ui.svelte'

export type AttachKind = 'thumbnail' | 'desc' | 'ai' | 'report' | 'frame' | 'frames' | 'text'
const WHAT: Record<AttachKind, string> = {
  thumbnail: 'the thumbnail', frame: 'the frame', frames: 'the frames', desc: 'the description',
  ai: 'the AI summary', report: 'the report', text: 'the note',
}

// no active canvas yet: name one first (V6 chooseCanvas)
async function ensureCanvas(): Promise<boolean> {
  if (cv.active) return true
  toast('No canvas yet: name one first')
  return newCanvas()
}

interface AddReply { added: number; why?: string; rev: number; elements: CEl[]; count?: number }

async function attach(body: { kind: AttachKind; ids?: number[]; text?: string; frame?: string; at?: { x: number; y: number } },
  from?: HTMLElement | null, flyId?: number) {
  if (!(await ensureCanvas())) return
  const id = cv.active!
  // the open board has unsaved edits: save them first so the server appends to the same file
  if (cv.doc?.id === id && cv.dirty && !(await save(true))) return
  let r: AddReply
  try { r = await api.post<AddReply>(`/api/canvases/${encodeURIComponent(id)}/elements`, body) }
  catch (e) { toast((e as Error).message, 'w'); return }
  if (!r.added) { toast(r.why || 'Nothing to add', 'w'); return }
  const d = cv.doc
  if (d && d.id === id) {
    d.items.push(...r.elements)
    cv.rev = r.rev
    markFresh(r.elements.map(e => e.id))
  }
  cv.list = cv.list.map(x => (x.id === id ? { ...x, count: r.count ?? x.count } : x))
  const what = r.added === 1 ? WHAT[body.kind] : `${r.added} elements`
  if (body.at) { toast(`Added ${what} to ${activeName()}`); return }
  const done = () => { if (d && d.id === id) reveal(r.elements[0]); bump(document.getElementById('cvchip')) }
  if (flyId != null) fly(flyId, from).then(done); else done()
  toast(`Added ${what} to ${activeName()}`, '', ui.ws === 'canvas' ? undefined : { label: 'Open canvas', run: () => setWS('canvas') })
}

export function attachItems(ids: number[], kind: Exclude<AttachKind, 'text'>, from?: HTMLElement | null, frame?: string) {
  if (!ids.length) { toast('Nothing selected', 'w'); return }
  return attach({ kind, ids, frame }, from, ids[0])
}
export function attachText(text: string, from?: HTMLElement | null) {
  return attach({ kind: 'text', text: String(text) }, from)
}
// a drop on the board: the thumbnails land where they were dropped
export function attachAt(ids: number[], p: { x: number; y: number }) {
  return attach({ kind: 'thumbnail', ids, at: { x: Math.round(p.x), y: Math.round(p.y) } })
}

// ── the fly-in ───────────────────────────────────────────────────────────────
function flyTarget(): HTMLElement | null {
  const b = document.getElementById('cv-board')
  if (ui.ws === 'canvas' && b?.offsetParent) return b
  const ch = document.getElementById('cvchip')
  return ch?.offsetParent ? ch : null
}
function bump(t: HTMLElement | null) {
  if (!t) return
  t.classList.remove('bump'); void t.offsetWidth; t.classList.add('bump')
  setTimeout(() => t.classList.remove('bump'), 500)
}
function fly(id: number, fromEl?: HTMLElement | null): Promise<void> {
  return new Promise(res => {
    const tgt = flyTarget()
    const from = fromEl?.isConnected && fromEl.getBoundingClientRect().width ? fromEl
      : document.querySelector<HTMLElement>(`.cell[data-id="${id}"] .slot`)
    if (ui.motionOff || !tgt || !from || !from.getBoundingClientRect().width) { res(); return }
    const a = from.getBoundingClientRect(), b = tgt.getBoundingClientRect(), f = document.createElement('div')
    f.className = 'flyer'
    if (lib.byId.get(id)?.thumb) f.style.backgroundImage = `url(${thumbSrc(id)})`
    document.body.append(f)
    const sx = a.left + a.width / 2 - 22, sy = a.top + a.height / 2 - 31, ex = b.left + b.width / 2 - 22, ey = b.top + b.height / 2 - 31
    const mx = (sx + ex) / 2, my = Math.min(sy, ey) - 90
    const an = f.animate([
      { transform: `translate(${sx}px,${sy}px) rotate(0deg) scale(1)` },
      { transform: `translate(${mx}px,${my}px) rotate(-14deg) scale(1.15)`, offset: 0.5 },
      { transform: `translate(${ex}px,${ey}px) rotate(-4deg) scale(.5)`, opacity: 0.35 },
    ], { duration: 640, easing: 'cubic-bezier(.3,.6,.4,1)' })
    an.onfinish = () => { f.remove(); bump(tgt); res() }
  })
}

// ── drag a card's grip (or a "Your items" row) onto the chip or the board ────
const drag = { id: null as number | null, x: 0, y: 0, on: false, ids: [] as number[] }
let justDragged = false
let ghost: HTMLDivElement | null = null

export function dragArm(e: PointerEvent, id: number, ids: number[]) {
  if (e.button !== 0) return
  Object.assign(drag, { id, x: e.clientX, y: e.clientY, on: false, ids })
}
const dropTarget = (x: number, y: number) => document.elementFromPoint(x, y)?.closest<HTMLElement>('#cvchip,#cv-board') ?? null

function dragMove(e: PointerEvent) {
  if (drag.id === null) return
  if (!drag.on) {
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return
    drag.on = true
    if (!ghost) { ghost = document.createElement('div'); ghost.className = 'ghost'; ghost.hidden = true; document.body.append(ghost) }
    ghost.style.backgroundImage = lib.byId.get(drag.id)?.thumb ? `url(${thumbSrc(drag.id)})` : ''
    ghost.textContent = drag.ids.length > 1 ? String(drag.ids.length) : ''
    ghost.hidden = false
    document.documentElement.classList.add('dragging')
  }
  ghost!.style.left = e.clientX + 'px'; ghost!.style.top = e.clientY + 'px'
  const t = dropTarget(e.clientX, e.clientY)
  document.querySelectorAll('.drop').forEach(x => { if (x !== t) x.classList.remove('drop') })
  t?.classList.add('drop')
}
function dragEnd(e: PointerEvent) {
  if (drag.id === null) return
  const was = drag.on, ids = drag.ids
  drag.id = null; drag.on = false
  if (ghost) ghost.hidden = true
  document.documentElement.classList.remove('dragging')
  document.querySelectorAll('.drop').forEach(x => x.classList.remove('drop'))
  if (!was) return
  justDragged = true
  setTimeout(() => { justDragged = false }, 0)
  if (e.type === 'pointercancel') return
  const t = dropTarget(e.clientX, e.clientY)
  if (t?.id === 'cv-board' && cv.doc) { const p = toWorld(e.clientX, e.clientY); attachAt(ids, { x: p.x - 110, y: p.y - 160 }) }
  else if (t) attachItems(ids, 'thumbnail')
  else toast('Drop it on the canvas chip in the menubar, or on the canvas board', 'w')
}

// ── the menubar chip: pick the target, open, new ─────────────────────────────
function chipMenu() {
  let n = 0
  const e = (label: string, run: () => void, o: Partial<Cmd> = {}): Cmd => ({ id: `cvchip-${n++}`, menu: 'view', label, run, ...o })
  const list: MenuEntry[] = [
    { head: 'Add to canvas lands in' },
    ...cv.list.map(c => e(`${c.name} · ${c.id === cv.active ? activeCount() : c.count}`, () => openCanvas(c.id), { check: () => c.id === cv.active })),
    { sep: true },
    e('Open the canvas', () => setWS('canvas'), { icon: 'canvas' }),
    e('New canvas…', () => newCanvas(), { icon: 'plus' }),
  ]
  openMenu(list, document.getElementById('cvchip'))
}

let installed = false
export function installAttach() {
  if (installed) return
  installed = true
  installCanvas()
  cardActs.canvasThumb = (id, from) => attachItems([id], 'thumbnail', from)
  cardActs.canvasDesc = (id, from) => attachItems([id], 'desc', from)
  cardActs.canvasAi = (id, from) => attachItems([id], 'ai', from)
  cardActs.canvasReport = (id, from) => attachItems([id], 'report', from)
  cardActs.canvasFrame = (id, from) => attachItems([id], 'frames', from)
  cardActs.grip = (id, from) => { if (!justDragged) attachItems([id], 'thumbnail', from) }
  askHooks.attachText = (text, from) => attachText(text, from)
  bind('new-canvas', () => newCanvas())
  bind('sel-canvas', () => attachItems([...lib.sel], 'thumbnail'), { off: () => !lib.sel.size, offMsg: () => 'Select cards first' })
  bind('canvas-target', chipMenu)
  addPaletteProvider(q => {
    const rows = cv.list.filter(c => c.name.toLowerCase().includes(q)).slice(0, 4)
      .map(c => ({ label: c.name, key: `${c.count} elements`, icon: 'canvas', run: () => { openCanvas(c.id); setWS('canvas') } }))
    return { name: 'Canvases', rows }
  })
  // grips on the cards (the grid and the list) arm a drag; a press without a drag adds (cardActs.grip)
  document.addEventListener('pointerdown', e => {
    const g = (e.target as HTMLElement).closest('.ck.grip')
    const c = g?.closest<HTMLElement>('.cell[data-id]')
    if (!c) return
    const id = +c.dataset.id!
    dragArm(e, id, lib.sel.has(id) ? [...lib.sel] : [id])
  })
  addEventListener('pointermove', dragMove, { passive: true })
  addEventListener('pointerup', dragEnd)
  addEventListener('pointercancel', dragEnd)
}
