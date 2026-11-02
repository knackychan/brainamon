// Citation tether (V6 hl / unhl / drawTether): hovering a citation chip in Wiskit highlights its card
// on the mat and draws a cable from the chip to it. The grid is virtualized: a card that is not
// mounted is above or below the visible rows (or hidden by the filters), and the tag says so.
import { geo, locate } from './map'
import { lib } from './library.svelte'
import { setWS, ui } from './ui.svelte'

let from: HTMLElement | null = null

const svg = () => document.getElementById('tether')
const tag = () => document.getElementById('tether-tag')

export function hl(id: number, el: HTMLElement) {
  if (lib.hlId === id && from === el) return
  lib.hlId = id
  from = el
  requestAnimationFrame(drawTether)
}

export function unhl() {
  if (lib.hlId === null) return
  lib.hlId = null
  from = null
  const s = svg(), t = tag()
  if (s) s.innerHTML = ''
  if (t) t.hidden = true
}

export function drawTether() {
  const s = svg(), t = tag(), id = lib.hlId, board = document.getElementById('board'), jv = document.getElementById('jv')
  if (!s || !t) return
  if (id === null || !from || !from.isConnected || !board || !jv || ui.ws !== 'lib') { s.innerHTML = ''; t.hidden = true; return }
  const a = from.getBoundingClientRect(), B = board.getBoundingClientRect(), J0 = jv.getBoundingClientRect()
  if (!a.width || !B.width) { s.innerHTML = ''; t.hidden = true; return }
  const sheet = J0.left < 4 && J0.top > 60          // phone: Wiskit is a bottom sheet
  const x0 = sheet ? a.left + a.width / 2 : J0.left - 1, y0 = sheet ? J0.top - 1 : a.top + a.height / 2
  const slot = board.querySelector<HTMLElement>(`.cell[data-id="${id}"] .slot, .cell.lr[data-id="${id}"]`)
  let x1: number, y1: number, label = '', mounted = !!slot
  if (slot) {
    const r = slot.getBoundingClientRect()
    x1 = r.left + r.width / 2
    if (r.bottom < B.top + 30) { y1 = B.top + 14; label = `No.${id} is above ↑` }
    else if (r.top > B.bottom - 30) { y1 = B.bottom - 14; label = `No.${id} is below ↓` }
    else y1 = r.top + 4
  } else {
    const i = lib.visIds.indexOf(id)
    x1 = B.left + B.width / 2
    if (i < 0) { y1 = B.top + B.height / 2; label = `No.${id} is hidden by your filters` }
    else {
      const top = geo.top0 + Math.floor(i / Math.max(1, geo.cols)) * geo.rowH - board.scrollTop
      if (top < 0) { y1 = B.top + 14; label = `No.${id} is above ↑` } else { y1 = B.bottom - 14; label = `No.${id} is below ↓` }
      mounted = true
    }
  }
  const dx = Math.max(70, Math.abs(x0 - x1) * 0.5), up = Math.max(60, Math.abs(y1 - y0) * 0.35)
  const d = sheet ? `M${x0} ${y0} C${x0} ${y0 - up} ${x1} ${y1 - up} ${x1} ${y1 - 8}` : `M${x0} ${y0} C${x0 - dx} ${y0} ${x1} ${y1 - up} ${x1} ${y1 - 8}`
  s.innerHTML = !mounted ? '' : `<path class="cb" d="${d}"/><path class="cb-hi" d="${d}"/><path class="flow" d="${d}"/><rect class="plug" x="${x1 - 5}" y="${y1 - 14}" width="10" height="15" rx="2"/><circle class="led" cx="${x1}" cy="${y1 - 3}" r="2"/><rect class="plug" x="${x0 - 5}" y="${y0 - 5}" width="10" height="10" rx="2"/><circle class="led" cx="${x0}" cy="${y0}" r="1.6"/>`
  if (label) { t.textContent = label; t.style.left = x1 + 'px'; t.style.top = y1 + (y1 < B.top + 40 ? 18 : -22) + 'px'; t.hidden = false }
  else t.hidden = true
}

// Find a card on the mat: switch to the Library, scroll it into the middle
export function locateCard(id: number) {
  if (ui.ws !== 'lib') setWS('lib')
  if (matchMedia('(max-width:1199px)').matches) ui.drawer = null
  requestAnimationFrame(() => locate(id))
}
