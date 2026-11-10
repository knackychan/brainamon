// A Library row as a locked card on the phone: by default Cover (cardHTML 'full') for every card,
// Full holo (cardFA2) for favourites, as the desktop's booster and the mockup do; Settings > Look can
// pin either one for every card (phone.cardStyle). The markup comes from the
// engine with escaped text (src/lib/cards/card.ts toCard); only the thumbnail URL is swapped for
// the source's cached, versioned one. In French and 繁中 the display fields of the temporary card model and the engine's
// own label nodes are swapped here (card-words.ts); the Row, the engine and the shared card files stay as they are.
import { esc, realCard, srcLabel, srcMark, toCard } from '../lib/cards/card'
import { themeSlot } from '../lib/cards/theme'
import { fmtDate } from '../lib/i18n/format.ts'
import { lang, t } from '../lib/i18n/index.ts'
import { cardWords, sourceName, themeWords, typeName } from './card-words.ts'
import { THUMB_W } from './source/desktop'
import type { Row } from './source/types'
import { phone, solo, source } from './state.svelte'

export const variantOf = (r: Row): 'fa2' | 'full' => phone.cardStyle === 'auto' ? (r.fav ? 'fa2' : 'full') : phone.cardStyle

// the card's date and the Item screen's: day, short month, year; English keeps its en-GB call-site locale
const DAY = { day: '2-digit', month: 'short', year: 'numeric' } as const
export const displayDate = (ms: number): string => (ms ? fmtDate(ms, DAY, 'en-GB') : '')

// the display fields the engine prints: only for the page language, on a copy (nothing localized is stored or written back)
function displayModel(r: Row, c: CardModel): CardModel {
  if (lang() === 'en') return c
  return { ...c, creator: esc(r.creator || t('item.creatorUnknown')), size: esc(typeName(r.type)), src: esc(sourceName(srcLabel(r.src))), date: displayDate(r.created) }
}

export function cardMarkup(r: Row, variant: 'fa2' | 'full' = variantOf(r), w = THUMB_W): string {
  const c = displayModel(r, toCard(r, phone.rankOf.get(r.id) ?? Math.abs(r.id)))       // a phone link's id is negative
  const html = srcMark(realCard(variant === 'fa2' ? cardFA2(c) : cardHTML(c, 'full'), phone.rows.filter(x => x.id > 0).length), r.src, c.date)
    .replace(`<img class="art" src="/thumb/${r.id}"`, `<img class="art" decoding="async" loading="lazy" src="${source.thumbUrl(r, w)}"`)
  return cardWords(html, esc, { source: sourceName(srcLabel(r.src)), date: displayDate(r.created), creator: r.creator || t('item.creatorUnknown') })
}

// themeSlot paints the source colour and the creator stat; the phone then swaps that stat's two words (card-words.ts)
export function themeCard(slot: HTMLElement, r: Row): void {
  themeSlot(slot, r)
  themeWords(slot, r.creator)
}

// a link just saved: no title of its own yet, no thumbnail, not processed (the PC fills it in)
export const isBare = (r: Row) => !r.thumb && !r.ai && (!r.title || r.title === r.url)
export const tintOf = (r: Row) => phone.tints[String(r.id)] || TYPE[r.cat] || '#6f8a96'

// the words of a card without art (Grid.svelte, ItemStrip.svelte): the ghost badge of a link and the tint caption
export const ghostText = (r: Row): string => r.id < 0 ? t(solo ? 'library.ghost.link' : 'library.ghost.waitsPc') : t('library.ghost.noDetails')
export const tintText = (r: Row): string => t('library.tint.noThumb', { creator: r.creator || r.src })
