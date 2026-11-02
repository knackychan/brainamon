// The one CM-OS menu panel (#mnu): menubar menus, the card context menu, the canvas chip menu.
// The entries are kept outside $state on purpose: they are the live Cmd objects of the command
// table (bind() replaces their handlers), and a deep $state proxy would snapshot them.
import type { MenuEntry } from './commands'

export const menu = $state({
  open: false,
  rev: 0,                         // bumped on every open so the panel re-reads the entries
  x: 0,
  y: 0,
  fromKey: '',                    // data-menu of the menubar button that opened it, else empty
  focus: true,
})
let items: MenuEntry[] = []
let opener: HTMLElement | null = null

export const menuItems = () => items

export function openMenu(list: MenuEntry[], anchor: HTMLElement | null, at?: { x: number; y: number }, focus = true) {
  closeMenu(true)
  opener = anchor
  items = list
  menu.fromKey = anchor?.dataset.menu ?? ''
  menu.focus = focus
  if (at) { menu.x = at.x; menu.y = at.y }
  else if (anchor) { const r = anchor.getBoundingClientRect(); menu.x = r.left; menu.y = r.bottom + 6 }
  anchor?.setAttribute('aria-expanded', 'true')
  menu.rev++
  menu.open = true
}

export function closeMenu(quiet = false) {
  if (!menu.open) return
  menu.open = false
  document.querySelectorAll('[aria-haspopup="menu"][aria-expanded="true"]').forEach(b => b.setAttribute('aria-expanded', 'false'))
  if (!quiet && opener?.isConnected) opener.focus({ preventScroll: true })
  opener = null
}
