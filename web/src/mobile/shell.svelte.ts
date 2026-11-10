// The phone shell's state (projects/phone-dock-shell): the section under a sheet, the sync panel, the
// collection filter put aside while searching, and navigation that grows a sheet out of its dock key and back
// (View Transitions where the WebView has them; at once with reduced motion or motion off).
import { tick } from 'svelte'
import { parseRoute, phone } from './state.svelte'
import { parentHash } from './back'
import { baseHash, isCompose, isSection, sheetOf, sheetSub, type Base } from './shell'
import { acceptHash, composerBack, requestLeave, unguarded } from './canvas/navigation'

export const shell = $state({
  base: 'lib' as Base,                                 // the section a sheet opens over (Mobile.svelte keeps it)
  panel: false,                                        // the sync panel is open (SyncKey.svelte)
  home: -1,                                            // history index of the section a dock key opened a sheet from
  keep: null as null | { cat: string; fav: boolean },  // the collection filter, put aside while searching
  canvasNotice: null as null | { canvasId: string; text: string; until: number },
})

// the Navigation API (Chromium: the Android WebView, the desktop window): where in history the page is
type Nav = { currentEntry?: { index: number } | null; entries?: () => { url: string | null }[] }
const nav = (): Nav | null => (globalThis as { navigation?: Nav }).navigation ?? null
// the history entry this page load opened on: a page behind it belongs to this app session, while a cold start or
// a reload has none (projects/phone-settings, spec section 5.1: the round Back of the settings pages). Without the
// Navigation API there is never a page behind, so Back takes the parent.
const START = nav()?.currentEntry?.index ?? -1
export const inAppBehind = (): boolean => { const i = nav()?.currentEntry?.index ?? -1; return START >= 0 && i > START }
type ViewTransitions = { startViewTransition?: (update: () => Promise<void>) => unknown }

const still = () => phone.motionOff || matchMedia('(prefers-reduced-motion: reduce)').matches

// run a route change; `morph` when a sheet appears or goes: the dock key and the sheet share a
// view-transition-name (mobile.css .m-vt-*), so one grows into the other
function run(change: () => Promise<void>, morph: boolean) {
  const d = document as unknown as ViewTransitions
  if (!morph || still() || typeof d.startViewTransition !== 'function') { void change(); return }
  d.startViewTransition(change)
}

// the next hashchange, or 400 ms
function hashed(): Promise<void> {
  return new Promise(resolve => {
    const done = () => { clearTimeout(t); removeEventListener('hashchange', done); resolve() }
    const t = setTimeout(done, 400)
    addEventListener('hashchange', done)
  })
}

// open a hash (replace: in place of the current history entry)
export function go(hash: string, replace = false) {
  if (requestLeave(() => go(hash, replace))) return
  const from = phone.route, to = parseRoute(hash)
  if (isSection(from) && sheetOf(to)) shell.home = nav()?.currentEntry?.index ?? -1
  run(async () => {
    unguarded(() => { if (replace) location.replace(location.pathname + hash); else location.hash = hash; acceptHash(hash) })
    phone.route = to
    await tick()
  }, !!sheetOf(from) !== !!sheetOf(to))
}

// steps back in history (-1: one page)
export function back(steps = -1, morph = false) {
  if (requestLeave(() => back(steps, morph))) return
  run(async () => {
    const wait = hashed()
    history.go(steps)
    await wait
    await tick()
  }, morph)
}

// close the sheet onto its section: back through history to the section's own entry when a dock key opened the
// sheet from it, else the section takes the sheet's place in history
export function closeSheet() {
  const home = shell.home, now = nav()?.currentEntry?.index ?? -1
  const url = home >= 0 ? nav()?.entries?.()[home]?.url ?? '' : ''
  shell.home = -1
  if (home >= 0 && now > home && url && isSection(parseRoute(new URL(url).hash))) back(home - now, true)
  else go(baseHash(shell.base), true)
}

// one step up, as Android's back button: a sheet's root closes the sheet; else the page behind (canGoBack),
// else the parent page
export function up(canGoBack: boolean) {
  const r = phone.route
  if (isCompose(r)) { if (!requestLeave(() => composerBack(parentHash(r)))) unguarded(() => composerBack(parentHash(r))) }
  else if (sheetOf(r) && !sheetSub(r)) closeSheet()
  else if (canGoBack) back()
  else go(parentHash(r, shell.base) || '#/lib')
}
