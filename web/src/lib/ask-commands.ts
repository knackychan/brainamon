// Plan 11: Ask Wiskit about the selection (Edit menu, tray) and about one card (card menu).
import { askAbout } from './ask.svelte'
import { cardActs } from './cardmenu'
import { bind } from './commands'
import { lib } from './library.svelte'

let installed = false
export function installAsk() {
  if (installed) return
  installed = true
  bind('sel-ask', () => askAbout([...lib.sel]), { off: () => !lib.sel.size, offMsg: () => 'Select items in the Library first' })
  cardActs.ask = id => askAbout([id])
}
