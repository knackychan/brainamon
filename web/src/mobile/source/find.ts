// Plain search over the phone's rows: every word must appear in the text fields. A query that is
// one whole number also finds the item with that id (src/lib/whole-id.ts: never a partial id;
// phone-only links, id < 0, are not matched by number).
import { idFirst, wholeId } from '../../lib/whole-id'

interface Findable { id: number; title: string; creator: string; tags: string; desc: string; cat: string; url: string }

export function findIds(rows: Findable[], q: string): number[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const num = wholeId(q)
  return idFirst(rows.filter(r => {
    if (num > 0 && r.id === num) return true
    const t = `${r.title} ${r.creator} ${r.tags} ${r.desc} ${r.cat} ${r.url}`.toLowerCase()
    return words.every(w => t.includes(w))
  }), q).map(r => r.id)
}

// The Library search box on the mirror (milestone-2026-10-14/plans/E-phone-fixes.md): the PC's ids.
// The PC matches every word as a prefix over the full text (description, AI description, transcript,
// creator, tags) with FTS5; the phone's rows do not carry that text, so `fts` comes from the search
// text (PhoneLibrary.ftsIds, every word). Links saved on the phone are not in the search text: they
// are matched on their row. `fts` null (no search text on the phone yet): the plain scan, as before.
export function libraryIds(rows: Findable[], q: string, fts: number[] | null): number[] {
  if (!fts) return findIds(rows, q)
  const have = new Set(rows.map(r => r.id))
  const ids = [...fts.filter(id => have.has(id)), ...findIds(rows.filter(r => r.id < 0), q)]
  const num = wholeId(q)
  return num > 0 && have.has(num) ? [num, ...ids.filter(id => id !== num)] : ids
}
