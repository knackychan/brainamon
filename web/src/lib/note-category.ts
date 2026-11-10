// My Notes categories (docs/superpowers/specs/2026-11-07-phone-note-page-design.md, sections 3-4): the name
// rules and the rename, shared by the phone (its queued `note_category` overlay, source/mirror.ts) and the
// desktop Notes rail. knowledge/my_notes.py holds the same rules for the PC; tests/fixtures/note_category.json
// keeps the two equal (tests/test_note_category.py).
export const DEFAULT_CATEGORY = 'General'
export const CATEGORY_MAX = 80
export const CATEGORY_ERRORS = {
  empty: 'Enter a category name.',
  long: 'Category names are at most 80 characters.',
  reserved: '"All" is reserved: choose another name.',
  general: 'General cannot be renamed.',
} as const
// a paired PC that does not announce `note_category: 1` in its manifest would drop the change
export const RENAME_NEEDS_PC = 'Update Brainamon on the PC to rename.'

// a name as it is stored: trimmed; throws the rule it breaks (length in code points, as Python's len)
export function cleanCategory(name: string): string {
  const n = (name ?? '').trim()
  if (!n) throw new Error(CATEGORY_ERRORS.empty)
  if ([...n].length > CATEGORY_MAX) throw new Error(CATEGORY_ERRORS.long)
  if (n.toLowerCase() === 'all') throw new Error(CATEGORY_ERRORS.reserved)
  return n
}

// the checked pair of a rename: `from` trimmed (never General), `to` cleaned; throws for a refused name
export function checkRename(from: string, to: string): { from: string; to: string } {
  const f = (from ?? '').trim()
  if (!f) throw new Error(CATEGORY_ERRORS.empty)
  if (f === DEFAULT_CATEGORY) throw new Error(CATEGORY_ERRORS.general)
  return { from: f, to: cleanCategory(to) }
}

// another category with the same name but for case (the UI's merge question), or undefined
export const otherNamed = (categories: string[], name: string, from: string): string | undefined =>
  categories.find(c => c !== from && c.toLowerCase() === name.toLowerCase())

// personal notes filed under `from` (no category: General) move to `to`; nothing else changes
export function renameNotes<T extends { meta: Record<string, string> }>(notes: T[], from: string, to: string): T[] {
  return notes.map(n => n.meta.kind === 'personal' && (n.meta.category || DEFAULT_CATEGORY) === from
    ? { ...n, meta: { ...n.meta, category: to } } : n)
}
