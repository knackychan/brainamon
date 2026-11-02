// The finger on the Item card. The locked engine listens to pointer events, and a phone browser can
// take a finger away from the page (a long press opens the image menu, or the browser decides the
// touch is a scroll) and then sends pointercancel, which lays the card flat. Touch events with a
// non-passive touchmove are not taken away like that, so the stage turns each finger into the same
// calls the engine's pointer handlers make (HandCard press / move / up / cancel) and keeps the
// touch pointer events off the slot (capture phase, so the engine never sees them twice). Mouse and
// pen still reach the engine unchanged; the motion values are the engine's own.
const POINTER = ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'pointerover', 'pointerout', 'pointerenter', 'pointerleave']

export function fingerTilt(stage: HTMLElement, hand: () => HandCard | null): () => void {
  let finger: number | null = null
  let x0 = 0, y0 = 0, moved = false
  const like = (t: Touch): PointerLike => ({ button: 0, pointerId: -1, pointerType: 'touch', clientX: t.clientX, clientY: t.clientY })
  const mine = (e: TouchEvent) => [...e.changedTouches].find(t => t.identifier === finger)

  const block = (e: Event) => { if ((e as PointerEvent).pointerType === 'touch') e.stopPropagation() }
  const start = (e: TouchEvent) => {
    const t = e.changedTouches[0]
    if (finger !== null || !t || !(t.target as Element | null)?.closest?.('.slot')) return
    finger = t.identifier
    x0 = t.clientX; y0 = t.clientY; moved = false
    hand()?.press(like(t))
  }
  const move = (e: TouchEvent) => {
    const t = mine(e)
    if (!t) return
    if (Math.hypot(t.clientX - x0, t.clientY - y0) > 6) moved = true
    if (e.cancelable) e.preventDefault()        // the finger tilts the card; it never scrolls the page
    hand()?.move(like(t))
  }
  const end = (e: TouchEvent) => {
    const t = mine(e)
    if (!t) return
    finger = null
    // The engine's quick release ignores travel unless drag mode is on; keep tilt without a tap.
    if (moved || Math.hypot(t.clientX - x0, t.clientY - y0) > 6) hand()?.cancel()
    else hand()?.up(like(t))
  }
  const cancel = (e: TouchEvent) => {
    if (!mine(e)) return
    finger = null
    hand()?.cancel()
  }
  const menu = (e: Event) => e.preventDefault()   // no "save image" menu on a long press

  for (const k of POINTER) stage.addEventListener(k, block, true)
  stage.addEventListener('touchstart', start, { passive: true })
  stage.addEventListener('touchmove', move, { passive: false })
  stage.addEventListener('touchend', end)
  stage.addEventListener('touchcancel', cancel)
  stage.addEventListener('contextmenu', menu)
  return () => {
    for (const k of POINTER) stage.removeEventListener(k, block, true)
    stage.removeEventListener('touchstart', start)
    stage.removeEventListener('touchmove', move)
    stage.removeEventListener('touchend', end)
    stage.removeEventListener('touchcancel', cancel)
    stage.removeEventListener('contextmenu', menu)
  }
}
