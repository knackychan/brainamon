// Session-local history provenance and one leave continuation. No draft is persisted.
export type LeaveGuard = (leave: () => void) => boolean
let guard: LeaveGuard | null = null, bypass = false
let accepted = typeof location === 'undefined' ? '' : location.hash
let previous: string | null = null
let origin: { hash: string; index: number } | null = null
type Nav = EventTarget & { currentEntry?: { index: number }; entries?: () => { url: string | null; index: number }[] }
const navigation = () => (globalThis as { navigation?: Nav }).navigation
export const unguarded = (f: () => void) => { const old = bypass; bypass = true; try { f() } finally { bypass = old } }
export const requestLeave = (f: () => void) => !bypass && !!guard?.(() => unguarded(f))
export function registerGuard(fn: LeaveGuard) { guard = fn; return () => { if (guard === fn) guard = null } }
const composing = (h: string) => /^#\/canvas\/(?:new|[^/]+\/add)$/u.test(h)
export function acceptHash(hash: string) {
  if (hash !== accepted && requestLeave(() => location.replace(location.pathname + hash))) {
    origin = null; previous = null
    history.replaceState(history.state, '', location.pathname + accepted)
    return false
  }
  if (hash !== accepted) {
    previous = accepted
    if (composing(hash) && !composing(accepted)) origin = { hash: accepted, index: (navigation()?.currentEntry?.index ?? 0) - 1 }
    if (!composing(hash)) origin = null
    accepted = hash
  }
  return true
}
export function installTraversalGuard() {
  const nav = navigation()
  const listener = (event: Event) => {
    const e = event as Event & { canIntercept?: boolean; destination?: { url: string; sameDocument?: boolean }; navigationType?: string }
    if (!e.cancelable || !e.canIntercept || !e.destination?.sameDocument || bypass) return
    const url = new URL(e.destination.url)
    if (url.hash === accepted) return
    if (requestLeave(() => location.replace(url.href))) e.preventDefault()
  }
  nav?.addEventListener('navigate', listener)
  return () => nav?.removeEventListener('navigate', listener)
}
export function composerBack(parent: string) {
  const nav = navigation(), now = nav?.currentEntry?.index
  const entry = now !== undefined ? nav?.entries?.().find(e => e.index === now - 1) : null
  const known = origin && (entry ? new URL(entry.url || location.href).hash === origin.hash && now === origin.index + 1 : previous === origin.hash)
  if (known) history.back()
  else location.replace(location.pathname + parent)
}
export function composerSuccess(hash: string, add: boolean) {
  unguarded(() => {
    if (add && origin?.hash === hash) composerBack(hash)
    else location.replace(location.pathname + hash)
  })
}
