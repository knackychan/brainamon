// A Library row as a locked card on the phone: by default Cover (cardHTML 'full') for every card,
// Full holo (cardFA2) for favourites, as the desktop's booster and the mockup do; More > Look can
// pin either one for every card (phone.cardStyle). The markup comes from the
// engine with escaped text (src/lib/cards/card.ts toCard); only the thumbnail URL is swapped for
// the source's cached, versioned one.
import { realCard, srcMark, toCard } from '../lib/cards/card'
import { THUMB_W } from './source/desktop'
import type { Row } from './source/types'
import { phone, source } from './state.svelte'

export const variantOf = (r: Row): 'fa2' | 'full' => phone.cardStyle === 'auto' ? (r.fav ? 'fa2' : 'full') : phone.cardStyle

export function cardMarkup(r: Row, variant: 'fa2' | 'full' = variantOf(r), w = THUMB_W): string {
  const c = toCard(r, phone.rankOf.get(r.id) ?? Math.abs(r.id))       // a phone link's id is negative
  const html = srcMark(realCard(variant === 'fa2' ? cardFA2(c) : cardHTML(c, 'full'), phone.rows.filter(x => x.id > 0).length), r.src, c.date)
  return html.replace(`<img class="art" src="/thumb/${r.id}"`, `<img class="art" decoding="async" loading="lazy" src="${source.thumbUrl(r, w)}"`)
}

// a link just saved: no title of its own yet, no thumbnail, not processed (the PC fills it in)
export const isBare = (r: Row) => !r.thumb && !r.ai && (!r.title || r.title === r.url)
export const tintOf = (r: Row) => phone.tints[String(r.id)] || TYPE[r.cat] || '#6f8a96'
