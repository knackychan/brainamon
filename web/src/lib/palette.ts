// Extra groups for the Ctrl+K palette after the commands: items (plan 05), notes (plan 10),
// canvases (plan 09). A provider gets the lowercase query (2+ characters) and returns its rows.
export interface PaletteRow {
  label: string
  key?: string          // right-hand hint
  icon?: string         // a key of IC or PX
  img?: string          // a thumbnail URL instead of an icon
  off?: boolean
  run: () => void
}
export interface PaletteGroup { name: string; rows: PaletteRow[] }
export type PaletteProvider = (q: string) => PaletteGroup | null

export const providers: PaletteProvider[] = []
export function addPaletteProvider(p: PaletteProvider) { providers.push(p) }
