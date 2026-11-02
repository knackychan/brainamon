// HandCard lifecycle for the Library grid (PLAN.md "Performance budget").
//
// A grid card at rest sways lightly on the compositor and runs no script (Fred, 2026-10-10).
// (Rendering resting cards flat, one layer instead of the 3D plies, was tried: no measurable gain.)
// - Light sway: a CSS animation of the card's `rotate` / `translate` (and the shadow's
//   `translate`) run by the compositor, built from the engine's own idle values (FEEL.idleX /
//   idleY / idleRoll / idleBob and its four frequencies), sampled over one SWAY_S loop with each
//   frequency rounded to whole cycles so the loop closes; a random negative delay per card keeps
//   rows out of lockstep. The engine's idle (a dozen light variables rewritten per frame) is off
//   (`idle: false`) and the card is taken off the engine's IntersectionObserver, which only feeds
//   that idle. Not reproduced: the light followed the idle tilt by at most about 10 % opacity.
// - Hover: the sway pose is frozen and eased to zero while the engine tilts the card (tilt, pop,
//   roll unchanged); after the pointer leaves and the engine settles, the sway restarts at the loop start, where all four sines are zero (no jump).
// Motion off (html.motion-off) stops the sway. The item window, booster and deck create their own
// HandCards and keep the engine's idle sway.
// - Frame rate (projects/desktop-app, idle CPU): a CSS animation makes the page redraw at the display
//   rate (60 to 144 Hz) however few cards sway, and the GPU process paid for every frame (about 5
//   CPU-seconds per 10 s on the live library). The sway animations are therefore paused and stepped by
//   one timer at SWAY_FPS: same keyframes, same amplitude, a quarter of the frames (measured 5.1 -> 2.2).
//   Rest mode (lib/rest.ts) clears the timer and leaving rest starts it again (plan 10-footprint A3:
//   no 20 wakeups a second while resting).

import { onRest, rest } from '../rest'

const SWAY_S = 30            // loop length; frequencies are rounded to whole cycles in it
const STEPS = 60             // keyframes per loop (one every 0.5 s, linear in between)
const EASE_MS = 450          // hover: the sway pose eases to zero over this
const SWAY_FPS = 12          // sway frames per second (the timer below); the display rate is not needed for a 1.5 deg drift
                             // (plan 10-footprint B1: 20 -> 12)

// One clock for every sway animation: it advances only while the timer runs (not in rest mode), so a
// card picks up where it stopped. Each animation keeps its own phase (the random --swd delay).
let swayClock = 0, lastTick = 0, swayT = 0
const seen = new WeakMap<Animation, number>()      // animation -> its currentTime minus swayClock when first seen
function tickSway() {
  const now = performance.now()
  if (rest.on || document.hidden) { lastTick = now; return }
  swayClock += Math.min(now - (lastTick || now), 200)
  lastTick = now
  for (const a of document.getAnimations()) {
    const name = (a as CSSAnimation).animationName
    if (name !== 'cm-sway' && name !== 'cm-sway-sh') continue
    if (!seen.has(a)) { seen.set(a, (Number(a.currentTime) || 0) - swayClock); a.pause() }
    else if (a.playState !== 'paused') a.pause()
    a.currentTime = seen.get(a)! + swayClock
  }
}

let styled = false
function swayCSS() {
  if (styled) return
  styled = true
  const cyc = (w: number) => Math.max(1, Math.round(w * SWAY_S / (2 * Math.PI))) * 2 * Math.PI / SWAY_S
  // engine.js HandCard.integrate: rx = sin(.83 T) idleX, ry = sin(.61 T) idleY, rl = sin(1.07 T) idleRoll, ty = sin(1.31 T) idleBob
  const wx = cyc(0.83), wy = cyc(0.61), wl = cyc(1.07), wb = cyc(1.31)
  const card: string[] = [], shadow: string[] = []
  for (let i = 0; i <= STEPS; i++) {
    const T = i / STEPS * SWAY_S, at = (i / STEPS * 100).toFixed(3) + '%'
    const rx = Math.sin(wx * T) * FEEL.idleX, ry = Math.sin(wy * T) * FEEL.idleY
    const rl = Math.sin(wl * T) * FEEL.idleRoll, ty = Math.sin(wb * T) * FEEL.idleBob
    // small angles: rotateZ(rl) rotateX(rx) rotateY(ry) is one turn about the vector (rx, ry, rl)
    const a = Math.hypot(rx, ry, rl)
    const rot = a < 1e-4 ? '1 0 0 0deg' : `${(rx / a).toFixed(4)} ${(ry / a).toFixed(4)} ${(rl / a).toFixed(4)} ${a.toFixed(3)}deg`
    card.push(`${at}{rotate:${rot};translate:0 ${ty.toFixed(2)}px}`)
    // the engine's shadow follows the pose: --sx = yaw * .8, --sy = 12 - rx * .45 + ty * .6
    shadow.push(`${at}{translate:${(ry * 0.8).toFixed(2)}px ${(-rx * 0.45 + ty * 0.6).toFixed(2)}px}`)
  }
  const el = document.createElement('style')
  el.id = 'cm-sway'
  el.textContent =
    `@keyframes cm-sway{${card.join('')}}@keyframes cm-sway-sh{${shadow.join('')}}` +
    `.slot.sw>.card{animation:cm-sway ${SWAY_S}s linear var(--swd,0s) infinite}` +
    `.slot.sw>.shadow{animation:cm-sway-sh ${SWAY_S}s linear var(--swd,0s) infinite}` +
    `.motion-off .slot.sw>.card,.motion-off .slot.sw>.shadow{animation:none}`
  document.head.appendChild(el)
  onRest(on => on ? stopSway() : startSway())
  if (!rest.on) startSway()
}

function startSway() {
  if (swayT) return
  lastTick = performance.now()      // the clock resumes from here: no jump for the time spent resting
  swayT = window.setInterval(tickSway, 1000 / SWAY_FPS)
}

function stopSway() {
  clearInterval(swayT)
  swayT = 0
}

// Creates the card's HandCard (no engine idle), starts the light sway, and returns the detach
// function: the card leaves ALL and ACTIVE (an unmounted card must not stay in them).
export function attachHand(slot: HTMLElement, onTap: () => void): () => void {
  swayCSS()
  const h = new HandCard(slot, { onTap, idle: false })
  IO?.unobserve(slot)
  const card = slot.querySelector<HTMLElement>('.card')!
  const shadow = slot.querySelector<HTMLElement>('.shadow')
  const parts = shadow ? [card, shadow] : [card]
  let held = 0, waitT = 0

  slot.style.setProperty('--swd', (-Math.random() * SWAY_S).toFixed(2) + 's')
  slot.classList.add('sw')

  function hold() {
    clearTimeout(waitT)
    if (!slot.classList.contains('sw')) return          // still easing from the last hover
    for (const el of parts) {
      const cs = getComputedStyle(el)
      el.style.rotate = cs.rotate
      el.style.translate = cs.translate
    }
    slot.classList.remove('sw')
    void card.offsetWidth                               // commit the frozen pose before easing
    for (const el of parts) {
      el.style.transition = `rotate ${EASE_MS}ms cubic-bezier(.2,.8,.2,1),translate ${EASE_MS}ms cubic-bezier(.2,.8,.2,1)`
      el.style.rotate = '0deg'
      el.style.translate = '0px 0px'
    }
    held = performance.now()
  }
  // after the pointer leaves: once the ease is done and the engine has settled, sway again
  function rest() {
    if (h.hover) return
    if (ACTIVE.has(h) || performance.now() < held + EASE_MS) { waitT = window.setTimeout(rest, 120); return }
    for (const el of parts) { el.style.transition = ''; el.style.rotate = ''; el.style.translate = '' }
    if (!slot.classList.contains('sw')) {
      slot.style.setProperty('--swd', '0s')             // the loop starts at rest: no jump
      slot.classList.add('sw')
    }
  }
  const leave = () => { clearTimeout(waitT); waitT = window.setTimeout(rest, 120) }
  slot.addEventListener('pointerenter', e => { if (e.pointerType !== 'touch' && !MOTION.off) hold() })
  slot.addEventListener('pointerdown', () => { if (!MOTION.off) hold() })
  slot.addEventListener('pointerleave', leave)
  slot.addEventListener('pointercancel', leave)
  slot.addEventListener('pointerup', e => { if (e.pointerType === 'touch') leave() })

  return () => {
    clearTimeout(waitT)
    ALL.delete(h)
    ACTIVE.delete(h)
  }
}

// A card outside the Library grid (item window, booster, deck): normal idle sway.
export function attachFree(slot: HTMLElement, onTap?: () => void): () => void {
  const h = new HandCard(slot, onTap ? { onTap } : {})
  return () => {
    ALL.delete(h)
    ACTIVE.delete(h)
    IO?.unobserve(slot)
  }
}
