// The Notes search (projects/phone-notes-manager, spec section 3.3 and its Review): every word typed must be found
// (AND, case-insensitive) in a note's title, its shelf (My notes) or kind (Knowledge), and its text: the whole note
// when the source gave it (`texts`, file to plain text: the Drive mirror's noteBodies), else what the list carries
// (a card's 14-line head or its snippet, a Knowledge row's snippet). The category chosen in the kicker filters My
// notes too. Pure; run by Node in the tests (type stripping): no imports.
export interface Mine { file: string; title: string; category: string; head?: string; snippet?: string }
export interface Know { file: string; title: string; kind: string; snippet?: string }

export const words = (q: string): string[] => q.toLocaleLowerCase().split(/\s+/).filter(Boolean)

const has = (hay: string, terms: string[]): boolean => {
  const h = hay.toLocaleLowerCase()
  return terms.every(t => h.includes(t))
}
// what the card shows (NoteCard.svelte): the head, else a snippet cached before plans/08, never "(no content)"
const preview = (n: Mine): string => n.head || (n.snippet && n.snippet !== '(no content)' ? n.snippet : '')
// a head keeps the note's marks (<u>, <mark data-mark>, <span data-ink>): their words count, not the tags
const untag = (s: string): string => s.replace(/<[^>]*>/g, '')

export function findMine<T extends Mine>(list: T[], terms: string[], cat = 'All', texts: Record<string, string> = {}): T[] {
  return list.filter(n => (cat === 'All' || n.category === cat)
    && (!terms.length || has([n.title, n.category, texts[n.file] ?? untag(preview(n))].join('\n'), terms)))
}

export function findKnow<T extends Know>(list: T[], terms: string[], texts: Record<string, string> = {}): T[] {
  return terms.length ? list.filter(n => has([n.title, n.kind, texts[n.file] ?? n.snippet ?? ''].join('\n'), terms)) : list
}
