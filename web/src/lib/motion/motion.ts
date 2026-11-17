// The motion language (projects/motion-language; spec docs/superpowers/specs/2026-11-14-motion-language-design.md):
// one way for things to move on the desktop and the phone. A count ticks to its new value and lifts 3 px each
// time the number shown changes; rows arrive 90 ms apart; a finished run holds its green state for 2.8 s; what a
// step changed shows as a mint delta for 1.8 s. motion.css holds the same durations as tokens
// (tests/test_motion_js.py keeps them equal). Pure: nothing here touches the DOM at import, so Node tests and
// the server render load it. Motion off (html.motion-off: the desktop's and the phone's switch), the rest mode
// (html.cm-rest, lib/rest.ts) and the system's reduced motion all mean: values change at once, nothing moves.
export const LIFT_MS = 220
export const LIFT_PX = 3
export const ARRIVE_MS = 320
export const ARRIVE_GAP_MS = 90
export const READ_MS = 800
export const POP_MS = 250
export const FINISH_MS = 2800
export const DELTA_MS = 1800

export const out3 = (t: number): number => 1 - (1 - t) ** 3
export const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v))

// how long a count takes from one value to the next: none for a step of one, 40 ms per unit, 160 ms to 1.6 s
export function tickMs(from: number, to: number): number {
  const d = Math.abs(to - from)
  return d <= 1 ? 0 : clamp(40 * d, 160, 1600)
}

// the whole number a count shows `elapsed` ms into a tick of `ms`
export function tickValue(from: number, to: number, elapsed: number, ms: number): number {
  if (ms <= 0 || elapsed >= ms) return to
  return Math.round(from + (to - from) * out3(clamp(elapsed / ms, 0, 1)))
}

// how far up a count sits `since` ms after the number shown changed: 3 px, back to rest in 220 ms
export function liftPx(since: number): number {
  return since < 0 || since >= LIFT_MS ? 0 : LIFT_PX * (1 - since / LIFT_MS)
}

// the delay of the i-th row or card of a group that arrives together
export const arrivalDelay = (i: number): number => Math.max(0, i) * ARRIVE_GAP_MS

export function motionOn(): boolean {
  if (typeof document === 'undefined') return false
  const html = document.documentElement.classList
  if (html.contains('motion-off') || html.contains('cm-rest')) return false
  return !(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)
}

// A number on screen that ticks to each new target; `out` gets the whole number to show and its lift in px.
export class Tween {
  #raf = 0
  #v: number
  #out: (v: number, lift: number) => void
  constructor(v: number, out: (v: number, lift: number) => void) { this.#v = v; this.#out = out }
  get value(): number { return this.#v }
  // `jump`: show the target at once (the number now means something else)
  to(target: number, jump = false): void {
    this.stop()
    if (target === this.#v) { this.#out(target, 0); return }
    if (jump || !motionOn() || typeof requestAnimationFrame !== 'function') { this.#v = target; this.#out(target, 0); return }
    const from = this.#v, ms = tickMs(from, target), t0 = performance.now()
    let changed = -Infinity
    const frame = (now: number) => {
      if (!motionOn()) { this.#v = target; this.#out(target, 0); this.#raf = 0; return }
      const elapsed = now - t0, next = tickValue(from, target, elapsed, ms)
      if (next !== this.#v) { this.#v = next; changed = now }
      const lift = liftPx(now - changed)
      this.#out(this.#v, lift)
      this.#raf = elapsed < ms || lift > 0 ? requestAnimationFrame(frame) : 0
    }
    frame(t0)
  }
  stop(): void { if (this.#raf) cancelAnimationFrame(this.#raf); this.#raf = 0 }
}
