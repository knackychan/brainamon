// ARRIVE (motion language): a row or a card slides in from (x, y) px and fades in, 320 ms, eased out. Svelte's
// `in:` transition, local: it plays when the element is added to a keyed list, not when the list first shows.
// Stagger a group with motion.ts `arrivalDelay(i)`. Motion off or reduced motion: there at once.
import { cubicOut } from 'svelte/easing'
import type { TransitionConfig } from 'svelte/transition'
import { ARRIVE_MS, motionOn } from './motion.ts'

export function arrive(_node: Element | null, { x = 0, y = 0, delay = 0, duration = ARRIVE_MS }:
  { x?: number; y?: number; delay?: number; duration?: number } = {}): TransitionConfig {
  if (!motionOn()) return { duration: 0 }
  return { delay, duration, easing: cubicOut, css: (t: number, u: number) => `transform:translate(${x * u}px,${y * u}px);opacity:${t}` }
}
