// A card tap (V6 cardTap): Ctrl+click toggles the selection, Shift+click selects a range, a plain
// click opens the item. The modifier keys are read at pointerdown, because the card engine's tap
// callback gets no event.
import { act } from '../../lib/cardmenu'
import { rangeSel, toggleSel } from '../../lib/library.svelte'

export const tapMod = { shift: false, ctrl: false }

export function cardTap(id: number) {
  const m = { ...tapMod }
  tapMod.shift = tapMod.ctrl = false
  if (m.ctrl) toggleSel(id)
  else if (m.shift) rangeSel(id)
  else act('open', id)
}
