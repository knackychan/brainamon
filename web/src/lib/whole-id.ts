// A search that is one whole number also means the item with that id (desktop Library and phone):
// the plain search adds it (server/routes/library.py /api/search, src/mobile/source/find.ts) and the
// list shows it first, whatever the sort or the Smart ranking. Never a partial id; ids < 1 (the
// phone-only links) are never matched by number.
export function wholeId(q: string): number {
  const t = q.trim()
  return /^\d+$/.test(t) ? Number(t) : 0
}

// Moves the row whose id is the whole-number query to the front (in place) and returns the list.
export function idFirst<T extends { id: number }>(L: T[], q: string): T[] {
  const n = wholeId(q)
  const at = n > 0 ? L.findIndex(r => r.id === n) : -1
  if (at > 0) L.unshift(...L.splice(at, 1))
  return L
}

// Whether a row survives the search narrowing: the search ids or the Smart ranking name it, or it is
// the item the whole-number query points at (the source may not have returned it).
export function inSearch(id: number, q: string, ids?: Set<number> | null, rank?: Map<number, number> | null): boolean {
  return !!(ids?.has(id) || rank?.has(id) || (id > 0 && id === wholeId(q)))
}
