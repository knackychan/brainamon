// Open in Obsidian (PLAN.md "Obsidian", Phase 6): one note pushed into the phone's vault with the
// obsidian://new link, at the path the desktop's Export to Obsidian writes it
// (library/obsidian_export.py: <vault>/Content Manager/notes/<file>), so the next export replaces it.
// Obsidian sends nothing back. The vault name defaults to the PC's vault folder (library/meta.json
// `obsidian_vault`) and can be changed under More (the phone's vault may be named differently).
const KEY = 'bp-vault'

export function vaultName(fromPc = ''): string {
  try { return localStorage.getItem(KEY) ?? fromPc } catch { return fromPc }
}
export function setVaultName(v: string) {
  try { localStorage.setItem(KEY, v.trim()) } catch { /* private window */ }
}

// the note as the export writes it: its frontmatter, then the body
export function noteText(meta: Record<string, string>, body: string): string {
  const keys = Object.keys(meta).filter(k => meta[k] !== undefined && meta[k] !== '')
  return keys.length ? `---\n${keys.map(k => `${k}: ${meta[k]}`).join('\n')}\n---\n\n${body}` : body
}

// See my knowledge graph: Obsidian opened on the vault (the last one used when no name is set).
// Obsidian has no link for its graph view; the page says where to find it.
export function graphUrl(vault: string): string {
  return vault ? `obsidian://open?vault=${encodeURIComponent(vault)}` : 'obsidian://open'
}

// Obsidian wants every value URI-encoded, "/" as %2F and spaces as %20 (encodeURIComponent does both).
// `prefix`: the notes folder inside the vault from the mirror's library/meta.json (obsidian_notes):
// Brainamon/Notes/ for a Brainamon-owned vault, the classic export's Content Manager/notes/ when absent.
export function obsidianUrl(vault: string, file: string, text: string, prefix = ''): string {
  const dir = prefix || 'Content Manager/notes/'
  const q = [vault ? `vault=${encodeURIComponent(vault)}` : '', `file=${encodeURIComponent(dir + file.replace(/\.md$/i, ''))}`,
    `content=${encodeURIComponent(text)}`, 'overwrite=true'].filter(Boolean)
  return `obsidian://new?${q.join('&')}`
}
