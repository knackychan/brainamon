// Where the Android back button goes when the WebView has no page behind the current one
// (projects/milestone-2026-10-14/plans/E-phone-fixes.md item 6). '' = the Library root: the app
// leaves there. Run by Node in the tests (type stripping): type-only import, nothing else.
import type { Route } from './state.svelte'

export function parentHash(r: Route): string {
  if (r.item) return '#/lib'
  if (r.canvas) return '#/canvas'
  if (r.note || r.mynote || r.synth !== undefined) return '#/notes'
  if (r.chats) return '#/jv'
  if (r.recover) return '#/backup'
  if (r.imp || r.backup) return '#/more'
  return r.tab === 'lib' ? '' : '#/lib'
}
