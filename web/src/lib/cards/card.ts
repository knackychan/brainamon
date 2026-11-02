// A Library row as a locked card: the CardModel the engine's cardFA2 / cardHTML expect.
// Every text field is HTML-escaped here, before it reaches the card functions (PLAN.md invariant 5).
import { thumbSrc, type Row } from '../library.svelte'

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
export const esc = (s: string) => String(s ?? '').replace(/[&<>"']/g, c => ESC[c])

const SRC_LABEL: Record<string, string> = {
  facebook: 'Facebook', instagram: 'Instagram', reddit: 'Reddit', youtube: 'YouTube', tiktok: 'TikTok', threads: 'Threads', web: 'Web',
}
export const srcLabel = (s: string) => SRC_LABEL[s] ?? 'Web'

export const hexOf = (id: number) => '0x' + ((Math.imul(id, 2654435761) >>> 8) & 0xffffff).toString(16).padStart(6, '0')

const DAY = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
export const dateOf = (ms: number) => (ms ? DAY.format(new Date(ms)) : '')

const WEEK = 7 * 24 * 3600 * 1000

export const titleOf = (r: Row) => r.title || `No.${r.id}`

export function toCard(r: Row, rank: number): CardModel {
  return {
    key: String(r.id), id: r.id, hex: hexOf(r.id),
    title: esc(titleOf(r)), creator: esc(r.creator || 'unknown'), src: esc(srcLabel(r.src)),
    rar: r.fav ? 'holo' : 'common', rank, isNew: !!r.created && Date.now() - r.created < WEEK,
    size: esc(r.type), date: dateOf(r.created), cat: esc(r.cat), focus: 42, desc: esc(r.desc),
  }
}

// Full = the full-art card (cardFA2); Cover = cardHTML(..., 'full') (V5 decision: classic retired).
export type Variant = 'fa2' | 'full'
// thumbW: the grid passes GRID_THUMB_W (twice the card width, sharp at 200 %); the item window
// passes nothing and keeps the full file.
export const GRID_THUMB_W = 320
// The engine's markup carries specimen copy from the design pages (audit 2026-10-15, #6): the series
// code "S01", "Specimen series 01" on the back, the holo-rule footnote and "specimen" in the Cover
// strip. Real cards drop them, and (Fred, 2026-10-16) the hex code next to the barcode and the word
// "Rank" (the number stays). The set count stays, as id/<items in the
// library> (total), instead of the engine's sample 1532. The card files stay untouched.
export function realCard(html: string, total = 0): string {
  html = html
    .replace(/<div class="fa-rule">.*?<\/div>/s, '')
    .replace(/<span class="fa-code">[^<]*<\/span>/, '')
    .replace(/<span class="(?:fa-)?hx">[^<]*<\/span>/, '')
    .replace(/<div class="sub">[^<]*<\/div>/, '')
    .replace(/ specimen · /, ' · ')
    .replace(/(<span class="(?:fa-)?hp">)<small>Rank<\/small>/, '$1')
  return total ? html.replace(/<b>(-?\d+)\/\d+<\/b>/, `<b>$1/${total}</b>`) : html
}

// The engine's source mark is a Facebook "f" on every card; each platform gets its own mark and colour
// in the badge top right, and the stub's "source" stat shows the date added instead (Fred, 2026-10-16).
// Same sizes and places as the engine's, so the layout does not move.
const SVG = (d: string) => `<svg viewBox="0 0 24 24" width="62%" height="62%" aria-hidden="true">${d}</svg>`
// Each source has a colour, like a Pokemon card's type (Fred, 2026-10-16): the mark here and the card
// frame (themeSlot, lib/cards/theme.ts) both read it.
export const SRC_COLOR: Record<string, string> = {
  facebook: '#1877f2', instagram: '#d6249f', youtube: '#ff0000', reddit: '#ff4500',
  threads: '#2b2b2b', tiktok: '#00b2c2', web: '#6f8a96',
}
export const srcColor = (s: string) => SRC_COLOR[s] ?? SRC_COLOR.web
export const SRC_MARK: Record<string, [string, string]> = {
  facebook: ['f', SRC_COLOR.facebook],
  instagram: [SVG('<rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="#fff" stroke-width="2.4"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="#fff" stroke-width="2.4"/><circle cx="17.3" cy="6.7" r="1.4" fill="#fff"/>'),
    'radial-gradient(circle at 30% 107%,#fdf497 0%,#fd5949 45%,#d6249f 60%,#285aeb 90%)'],
  youtube: [SVG('<path d="M8 5.5v13l11-6.5z" fill="#fff"/>'), SRC_COLOR.youtube],
  reddit: ['r', SRC_COLOR.reddit],
  threads: ['@', '#000'],
  tiktok: ['\u266a', '#000'],
  web: [SVG('<circle cx="12" cy="12" r="8.5" fill="none" stroke="#fff" stroke-width="2"/><path d="M3.5 12h17M12 3.5c-3 3.2-3 13.8 0 17M12 3.5c3 3.2 3 13.8 0 17" fill="none" stroke="#fff" stroke-width="1.6"/>'), SRC_COLOR.web],
}
export function srcMark(html: string, src: string, date: string): string {
  const [glyph, bg] = SRC_MARK[src] ?? SRC_MARK.web
  return html
    .replace(/<span class="((?:fa-)?type)"([^>]*)>f<\/span>/, `<span class="$1"$2 style="background:${bg}">${glyph}</span>`)
    .replace(/<div><small>source<\/small><b><span class="(?:fa-)?ico">f<\/span>[^<]*<\/b><\/div>/, `<div><small>added</small><b>${date || '-'}</b></div>`)
}

export function cardMarkup(r: Row, variant: Variant, rank: number, thumbW = 0, total = 0): string {
  const c = toCard(r, rank)
  const html = srcMark(realCard(variant === 'full' ? cardHTML(c, 'full') : cardFA2(c), total), r.src, c.date)
  // the engine writes src="${THUMBS[key]}" (= /thumb/<id>); swap in the cached, versioned URL and
  // let the browser decode the image off the main thread (the card files stay untouched)
  return html.replace(`<img class="art" src="/thumb/${r.id}"`, `<img class="art" decoding="async" src="${thumbSrc(r.id, thumbW)}"`)
}
