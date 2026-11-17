// The posts an import just added, handed from the Import screen to the Library (projects/motion-language plans 07
// and 08). Open in Library records them; the Library takes them once, when it shows with no search and no item
// open: `base` is the number of posts it held before the import (what the All chip shows first), `at` the moment
// (performance.now()) the arrival starts, 280 ms after the Library showed. The cards of `ids` slide in 90 ms apart,
// the All chip counts up from `base`, and a toast names the site. Nothing here is saved: a restart forgets it.
import { ARRIVE_GAP_MS, ARRIVE_MS } from '../lib/motion/motion.ts'

export const HOLD_MS = 280

export interface Arrival { site: string; name: string; ids: ReadonlySet<number>; base: number; total: number; at: number }

export const arrival = $state<{ cur: Arrival | null }>({ cur: null })

// `rowCount`: the posts the phone holds now, the added ones included
export function recordArrival(site: string, name: string, ids: readonly number[], rowCount: number): void {
  const set = new Set(ids)
  if (!set.size) { arrival.cur = null; return }
  arrival.cur = { site, name, ids: set, base: Math.max(0, rowCount - set.size), total: rowCount, at: 0 }
}

// the Library showed: the arrival starts after the hold. Returns it (already started or just started), else null.
export function takeArrival(now: number = performance.now()): Arrival | null {
  const cur = arrival.cur
  if (!cur) return null
  if (!cur.at) arrival.cur = { ...cur, at: now + HOLD_MS }
  return arrival.cur
}

export function endArrival(): void {
  arrival.cur = null
}

// how far into its turn a card is: the cell at `position` in the list (0 first), `elapsed` ms after the arrival
// started. Delay in ms (negative once it has begun) and whether the card is still to arrive or arriving.
export function turn(position: number, elapsed: number): { delay: number; live: boolean } {
  const delay = Math.max(0, position) * ARRIVE_GAP_MS - elapsed
  return { delay, live: delay + ARRIVE_MS > 0 }
}
