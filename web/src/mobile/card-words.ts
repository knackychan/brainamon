// The words the locked card engine prints (design/card-designs/engine.js cardHTML, full-art-v2/fa2.js cardFA2) and the
// phone's display words for item types and sources (spec section 5.1). The engine and web/src/lib/cards/** stay
// untouched: cards.ts swaps only exact, known engine nodes after the markup exists, never a word anywhere in the
// serialized HTML (a title, creator or URL may read "NEW" or "Common"). Every inserted translation is escaped once,
// with the card escape helper the caller passes in. English never runs the pass. No t() runs at import time.
import { lang, t, type Key } from '../lib/i18n/index.ts'

const TYPES = { Reel: 'item.type.reel', Post: 'item.type.post', Video: 'item.type.video' } as const satisfies Record<string, Key>

// Known stored item types get a display word; any other value shows as stored.
export const typeName = (type: string): string => Object.hasOwn(TYPES, type) ? t(TYPES[type as keyof typeof TYPES]) : type

// srcLabel() (lib/cards/card.ts) answers "Web" for web pages and for any site it does not know; platform names are brands.
export const sourceName = (label: string): string => label === 'Web' ? t('item.source.web') : label

const RARITY: Record<string, Key> = { 'Holo rare': 'item.card.holo', Uncommon: 'item.card.uncommon', Common: 'item.card.common' }

export type CardParts = { source: string; date: string; creator: string }

// Cover prints class names as-is, Holo prefixes them with fa-; the optional group keeps the prefix of the node found.
export function cardWords(html: string, esc: (value: string) => string, parts: CardParts): string {
  if (lang() === 'en') return html
  const word = (key: Key, params?: Record<string, unknown>) => esc(t(key, params))
  return html
    .replace(/<span class="(fa-)?new">NEW<\/span>/, (_, fa = '') => `<span class="${fa}new">${word('item.card.new')}</span>`)
    .replace(/<span class="(fa-)?stage">Reel<\/span>/, (_, fa = '') => `<span class="${fa}stage">${word('item.card.stage')}</span>`)
    .replace(/<div class="(fa-)?evo">Saved from [^<]*<\/div>/, (_, fa = '') =>
      `<div class="${fa}evo">${word('item.card.savedFrom', { source: parts.source, date: parts.date })}</div>`)
    .replace(/(<span class="(?:fa-)?pill">)Flag(<\/span><b>)Interesting(<\/b>)/, (_, open, middle, close) =>
      `${open}${word('item.card.flag')}${middle}${word('item.card.interesting')}${close}`)
    .replace(/(<small>)rarity( <span class="(?:fa-)?pips">)/, (_, open, close) => `${open}${word('item.card.rarity')}${close}`)
    .replace(/(<b class="(?:fa-)?rv">[★◆●] )(Holo rare|Uncommon|Common)(<\/b>)/, (_, open, name, close) => `${open}${word(RARITY[name])}${close}`)
    .replace(/<small>size<\/small>/, () => `<small>${word('item.card.size')}</small>`)
    .replace(/<small>added<\/small>/, () => `<small>${word('item.card.added')}</small>`)
    .replace(/<span class="((?:fa-)?il)">Illus\. [^<]*<\/span>/, (_, cls) => `<span class="${cls}">${word('item.card.illus', { creator: parts.creator })}</span>`)
}

// themeSlot (lib/cards/theme.ts, shared with the desktop) turns the stub's middle stat into the creator: a "creator" label
// and the creator, or "unknown" when there is none. After it ran, the phone swaps those two words; a stored creator
// (even one that reads "unknown") is user data and stays exactly as stored.
export function themeWords(slot: HTMLElement, creator: string | undefined): void {
  if (lang() === 'en') return
  const stat = slot.querySelector<HTMLElement>('.st>div:nth-child(2),.fa-st>div:nth-child(2)')
  if (!stat) return
  const label = stat.querySelector('small'), value = stat.querySelector('b')
  if (label) label.textContent = t('item.card.creator')
  if (value && !creator) value.textContent = t('item.creatorUnknown')
}
