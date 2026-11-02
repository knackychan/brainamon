// The Library map strip (V6 drawMap / mapHit / mapTo): one dot per visible card in its thumbnail
// tint, an orange line for the viewport. The grid is virtualized, so dot positions come from the
// card's index and the grid geometry (geo, kept by VirtualGrid), not from mounted cells.
// Redrawn at most once per animation frame (scheduleMap); a scroll only repaints the cached dots and
// moves the viewport line.
import { lib, setZoomIndex, Z } from './library.svelte'

export const geo = { cols: 1, rowH: 300, top0: 0, cellH: 280 }

let board: HTMLElement | null = null
let mm: HTMLElement | null = null
let cv: HTMLCanvasElement | null = null
let dots: { x: number; y: number; id: number }[] = []
let fy0 = 24, fy1 = 100

export function bindBoard(el: HTMLElement | null) { board = el }
export function bindMap(m: HTMLElement | null, c: HTMLCanvasElement | null) { mm = m; cv = c }

let raf = 0
let dirty = true
// full: the dots, the dot grid or the colours changed (a full redraw into the cached base layer);
// a scroll only moves the viewport line, so it repaints the cached base plus the line.
export function scheduleMap(full: unknown = true) {
  if (full !== false) dirty = true
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(drawMap)
}

const tintOf = (id: number, cat: string) => lib.tints[String(id)] || TYPE[cat] || '#9cc4e2'

export let mapPct = 0

let base: HTMLCanvasElement | null = null
let W = 0, H = 0, dpr = 1, S = 1, ORG = '#ff5a1f'
const Y = (v: number) => fy0 + (v / S) * (fy1 - fy0)

// the dot grid and one dot per visible card, drawn into `base` (same pixel size as the strip)
function drawBase(): boolean {
  W = mm!.clientWidth; H = mm!.clientHeight
  if (!W || !H) return false
  dpr = Math.min(2, devicePixelRatio || 1)
  const pw = Math.round(W * dpr), ph = Math.round(H * dpr)
  if (cv!.width !== pw) cv!.width = pw
  if (cv!.height !== ph) cv!.height = ph
  base ??= document.createElement('canvas')
  base.width = pw; base.height = ph
  const c = base.getContext('2d')
  if (!c) return false
  c.setTransform(dpr, 0, 0, dpr, 0, 0)
  const cs = getComputedStyle(document.documentElement)
  ORG = cs.getPropertyValue('--accent').trim() || '#ff5a1f'
  fy0 = 24; fy1 = H - 22
  const P = 5, D = 4, mcols = Math.max(1, Math.floor((W - 6) / P)), ox = Math.floor((W - mcols * P + 1) / 2)
  c.fillStyle = cs.getPropertyValue('--map-dot').trim() || 'rgba(255,255,255,.12)'
  for (let y = fy0; y < fy1; y += P) for (let k = 0; k < mcols; k++) c.fillRect(ox + k * P + 1, y + 1, 1, 1)
  const rows = lib.visible, cols = Math.max(1, geo.cols), sel = lib.sel, cells = lib.cellState
  dots = []
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i], gr = Math.floor(i / cols), j = i % cols
    const y0 = fy0 + Math.round((Y(geo.top0 + gr * geo.rowH + geo.cellH * 0.25) - fy0) / P) * P
    const yy = y0 + Math.floor(j / mcols) * P, xx = ox + (j % mcols) * P
    if (yy > fy1 - D) continue
    c.fillStyle = tintOf(r.id, r.cat); c.fillRect(xx, yy, D, D)
    if (r.fav) { c.fillStyle = '#ffd34d'; c.fillRect(xx, yy, D, 1) }
    if (cells.get(r.id) === 'worked') { c.fillStyle = '#fff'; c.fillRect(xx + 1, yy + 1, 1, 1) }
    if (sel.has(r.id)) { c.fillStyle = ORG; c.fillRect(xx, yy + D - 1, D, 1) }
    dots.push({ x: xx, y: yy, id: r.id })
  }
  dirty = false
  return true
}

function drawMap() {
  if (!mm || !cv || !board) return
  const s = Math.max(1, board.scrollHeight)
  if (s !== S) { S = s; dirty = true }
  if ((dirty || !base) && !drawBase()) return
  const c = cv.getContext('2d')
  if (!c || !base) return
  c.setTransform(1, 0, 0, 1, 0, 0)
  c.clearRect(0, 0, cv.width, cv.height)
  c.drawImage(base, 0, 0)
  c.setTransform(dpr, 0, 0, dpr, 0, 0)
  const a = Y(board.scrollTop), b = Y(board.scrollTop + board.clientHeight)
  c.fillStyle = 'rgba(255,90,31,.18)'; c.fillRect(2, a, W - 4, Math.max(2, b - a))
  c.fillStyle = ORG; c.fillRect(0, Math.round(a) - 1, W, 2)
  c.fillStyle = 'rgba(255,90,31,.55)'; c.fillRect(0, Math.round(b) - 1, W, 1)
  const pct = Math.max(0, Math.min(100, Math.round(board.scrollTop / Math.max(1, S - board.clientHeight) * 100)))
  if (pct === mapPct) return
  mapPct = pct
  const pe = mm.querySelector('#mm-pct')
  if (pe) pe.textContent = String(pct)
  mm.setAttribute('aria-valuenow', String(pct))
}

export function mapHit(e: PointerEvent): { id: number; y: number } | null {
  if (!mm) return null
  const r = mm.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top
  let best: { id: number; y: number } | null = null, bd = 7
  for (const d of dots) {
    const dd = Math.hypot(d.x + 1.5 - x, d.y + 1.5 - y)
    if (dd < bd) { bd = dd; best = d }
  }
  return best
}

export function mapTo(e: PointerEvent) {
  if (!mm || !board) return
  const r = mm.getBoundingClientRect(), f = Math.min(1, Math.max(0, (e.clientY - r.top - fy0) / (fy1 - fy0)))
  board.scrollTop = f * board.scrollHeight - board.clientHeight / 2
}

// Scroll the board so the card is in the middle (V6 locate, for the virtualized grid).
export function locate(id: number) {
  if (!board) return
  const i = lib.visIds.indexOf(id)
  if (i < 0) return
  const top = geo.top0 + Math.floor(i / Math.max(1, geo.cols)) * geo.rowH
  board.scrollTo({ top: top - board.clientHeight / 2 + geo.cellH / 2, behavior: MOTION.off ? 'auto' : 'smooth' })
}

// ── zoom (V6 setZoom / fitAll) ───────────────────────────────────────────────
// A zoom keeps the card under the pointer in place: VirtualGrid applies `anchor` after it has
// re-measured the grid at the new card size.
export const anchor: ({ id: number; dy: number } | null)[] = [null]

export function setZoom(i: number, at?: { x: number; y: number }) {
  if (lib.view === 'list') return
  i = Math.max(0, Math.min(Z.length - 1, i))
  if (i === lib.zi) return
  anchor[0] = null
  if (at && board) {
    const cell = document.elementFromPoint(at.x, at.y)?.closest<HTMLElement>('.cell[data-id]')
    if (cell) anchor[0] = { id: +cell.dataset.id!, dy: cell.getBoundingClientRect().top - board.getBoundingClientRect().top }
  }
  setZoomIndex(i)
}

export function fitAll() {
  if (lib.view === 'list' || !board) return
  const n = Math.max(1, lib.visible.length), bw = board.clientWidth - 20, avail = board.clientHeight - 20
  let pick = 0
  for (let i = Z.length - 1; i >= 0; i--) {
    const cw = Z[i] * 1.14, cols = Math.max(1, Math.floor(bw / cw)), rows = Math.ceil(n / cols)
    const h = rows * (Z[i] * 88 / 63 + 18 + Z[i] * 0.14) + Z[i] * 0.28 + 40
    if (h <= avail) { pick = i; break }
  }
  anchor[0] = null
  setZoomIndex(pick)
  board.scrollTop = 0
  scheduleMap()
}
