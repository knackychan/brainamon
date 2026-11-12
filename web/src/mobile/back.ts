// Where the Android back button goes when the WebView has no page behind the current one
// (projects/milestone-2026-10-14/plans/E-phone-fixes.md item 6). '' = the Library root: the app
// leaves there. Run by Node in the tests (type stripping): type-only import, nothing else.
// `base`: the section a sheet (Notes, Wiskit, Add) opened over (projects/phone-dock-shell, shell.svelte.ts);
// a sheet's root goes back to it.
import type { Route } from './state.svelte'

// where More's parent is when a screen sent the reader there (Wiskit's "Add a key"); onboard.svelte.ts sets it and
// forgets it when the reader leaves More's screens, so an ordinary visit to More keeps the Library
let moreFrom = ''
export const setMoreFrom = (hash: string) => { moreFrom = hash }

export function parentHash(r: Route, base: 'lib' | 'cv' = 'lib'): string {
  if (r.item || r.search) return '#/lib'
  if (r.canvas) return r.add ? `#/canvas/${encodeURIComponent(r.canvas)}` : '#/canvas'
  if (r.note || r.mynote || r.synth !== undefined || r.find) return '#/notes'
  if (r.chats) return '#/jv'
  if (r.recover) return '#/backup'
  if (r.imp || r.save) return '#/cap'
  if (r.manage) return '#/backup'
  if (r.group || r.backup) return '#/more'
  if (r.tab === 'notes' || r.tab === 'jv' || r.tab === 'cap') return base === 'cv' ? '#/canvas' : '#/lib'
  return r.tab === 'lib' ? '' : r.tab === 'more' && moreFrom ? moreFrom : '#/lib'
}

// The round Back of Settings, Backup & phones and Recover a library (projects/phone-settings, spec section 5.1): ''
// goes one page back (`behind`: the page behind belongs to this app session, shell.svelte.ts inAppBehind), else the
// parent; a cold start or a reload has nothing behind.
export function pageBack(r: Route, behind: boolean): string {
  return behind ? '' : parentHash(r) || '#/lib'
}
