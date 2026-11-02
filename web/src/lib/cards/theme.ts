// Page-level card theme, ported from the V6 themeSlot (assemble.py version): the source's colour
// (--t, like a Pokemon card's type; Fred, 2026-10-16) on the frame, header and body through
// v6-cards-theme.css (data-th), and the creator in the stub's middle stat. No category art: the
// V6 art tables are keyed by the sample collections. A favourite keeps its gold holo frame.
import { srcColor } from './card'

const hexRGB = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
const rgbHex = (c: number[]) => '#' + c.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')

export function hueShift(hex: string, deg: number, dl: number): string {
  const [r, g, b] = hexRGB(hex).map(v => v / 255), mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn
  let h = 0, s = 0
  if (d) { s = d / (1 - Math.abs(2 * l - 1)); h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h *= 60 }
  h = ((h + deg) % 360 + 360) % 360
  const L = Math.max(0, Math.min(1, l + dl)), C = (1 - Math.abs(2 * L - 1)) * s, X = C * (1 - Math.abs((h / 60) % 2 - 1)), m = L - C / 2
  const [R, G, B] = h < 60 ? [C, X, 0] : h < 120 ? [X, C, 0] : h < 180 ? [0, C, X] : h < 240 ? [0, X, C] : h < 300 ? [X, 0, C] : [C, 0, X]
  return rgbHex([R + m, G + m, B + m].map(v => v * 255))
}

export function themeSlot(slot: HTMLElement, r: { src: string, creator?: string }) {
  slot.style.setProperty('--t', srcColor(r.src))
  slot.dataset.th = r.src || 'web'
  // no rarity line: the stub's middle stat names the creator (a favourite already shows as holo)
  const st = slot.querySelector<HTMLElement>('.st>div:nth-child(2),.fa-st>div:nth-child(2)')
  if (st && !st.dataset.cr) {
    st.dataset.cr = '1'
    const small = st.querySelector('small'), b = st.querySelector('b')
    if (small) small.textContent = 'creator'
    if (b) { b.textContent = r.creator || 'unknown'; b.title = r.creator || '' }
  }
}
