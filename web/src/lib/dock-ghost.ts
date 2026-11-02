// Start-up placeholders for the rail docks (Rail.svelte). Until the docks mount (ui.ready), each
// dock shows skeleton tiles with the same surface (variant class), span and height as its real
// tiles, so the real content fades in on a tile that is already there instead of popping in. The
// heights are measured from the last session (saved a moment after the dock settles) and fall back
// to the defaults below (a 1440 px window, measured 2026-10-10).
import type { Ws } from './ui.svelte'

export type Ghost = [cls: string, height: number]

// the tile classes that shape a tile: span and surface variant (V6 .dock>.wg.k / .y / .s / .v / .term)
const SHAPE = /^(s[2-6]|k|y|s|v|term)$/

const KEY = 'cm-v6-dock-sk'
const DEFAULTS: Record<Ws, Ghost[]> = {
  lib: [['k s3', 136], ['y s3', 136], ['s6', 535], ['s6', 190], ['s6 term', 143], ['s6', 204], ['s3', 237], ['s s3', 237], ['s2', 165], ['v s2', 165], ['k s2', 165], ['s6', 88], ['s s3', 145], ['s3', 145]],
  know: [['k s3', 152], ['k s3', 152], ['s6', 145], ['s6', 106], ['s6', 287], ['y s3', 186], ['s s3', 186]],
  canvas: [['k s3', 142], ['y s3', 142], ['s6', 268], ['s6', 289], ['s2', 161], ['s s2', 161], ['k s2', 161]],
  notes: [['k s3', 113], ['k s3', 113], ['s6', 151], ['s6', 286], ['y s6', 93]],
}

function saved(): Partial<Record<Ws, Ghost[]>> {
  try { return JSON.parse(localStorage.getItem(KEY) || '{}') } catch { return {} }
}

export function ghosts(ws: Ws): Ghost[] {
  const g = saved()[ws]
  return Array.isArray(g) && g.length ? g : DEFAULTS[ws]
}

// Record the tiles of a visible dock (their shape classes and heights).
export function saveGhosts(ws: Ws, dock: HTMLElement) {
  const tiles = [...dock.children] as HTMLElement[]
  if (!tiles.length || !dock.offsetHeight) return
  const g: Ghost[] = tiles.map(t => [[...t.classList].filter(c => SHAPE.test(c)).join(' '), t.offsetHeight])
  try { localStorage.setItem(KEY, JSON.stringify({ ...saved(), [ws]: g })) } catch { /* private window */ }
}
