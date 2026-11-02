// Rest mode: no animation runs while nobody is looking (projects/desktop-app, idle CPU).
// The page rests when the window is hidden or minimized, when it loses focus (another app in
// front, a game, ...), or after IDLE_MS without input while focused. Resting:
// - html.cm-rest pauses every CSS animation (the card sway, scan bars, blinking cursors), so the
//   compositor stops producing frames; paused, not removed, so nothing jumps on wake;
// - the card engine's own idle (item window, booster, deck cards) stops: MOTION.off is set in
//   memory only (setMotion would also save the user's Motion choice) and the cards settle;
// - rest.on lets script timers skip their work (the Wiskit CPU meter); onRest lets a timer stop
//   and start instead (the card sway, lib/cards/hand.ts; the clock, ClockTile.svelte).
// Any pointer, key, wheel or focus wakes it; the user's Motion choice is restored as it was.
export const rest = { on: false }

const listeners = new Set<(on: boolean) => void>()
/** Called with true on entering rest and false on leaving it; returns the function that removes it. */
export function onRest(fn: (on: boolean) => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

const IDLE_MS = 20_000      // plan 10-footprint B5 (was 60 s)
let idleT = 0
let savedOff = false

function enter() {
  if (rest.on) return
  rest.on = true
  document.documentElement.classList.add('cm-rest')
  savedOff = MOTION.off
  MOTION.off = true
  ALL.forEach(h => h.settle())
  listeners.forEach(fn => fn(true))
}

function leave() {
  if (!rest.on) return
  rest.on = false
  document.documentElement.classList.remove('cm-rest')
  MOTION.off = savedOff
  ALL.forEach(h => h.settle())
  listeners.forEach(fn => fn(false))
}

function armIdle() {
  clearTimeout(idleT)
  idleT = window.setTimeout(enter, IDLE_MS)
}

function activity() {
  if (document.hidden) return
  leave()
  armIdle()
}

export function installRest() {
  for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'focus'] as const)
    addEventListener(ev, activity, { passive: true, capture: true })
  addEventListener('blur', () => { clearTimeout(idleT); enter() })
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearTimeout(idleT); enter() } else if (document.hasFocus()) activity()
  })
  if (document.hidden || !document.hasFocus()) enter(); else armIdle()
}
