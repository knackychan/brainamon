// The command table: one list feeds the menubar menus, the Ctrl+K palette and the keyboard
// (V6 c-shell.js `cmd` / `runCmd`). lib/command-table.ts registers every command of the app in
// menu order on start-up, including the ones a later sub-plan builds: those start disabled with
// a "not in V6 yet" message, and the sub-plan that builds them calls bind(id, run).
import { closeMenu } from './menu.svelte'
import { toast } from './ui.svelte'

export type MenuKey = 'cmos' | 'file' | 'edit' | 'process' | 'view'
export interface Cmd {
  id: string
  menu: MenuKey
  label: string | (() => string)
  run: () => void
  key?: string                    // shortcut shown in menus and the palette
  icon?: string                   // a key of IC or PX (lib/px.ts)
  check?: () => boolean           // a checkbox item
  off?: () => boolean             // disabled when true
  offMsg?: () => string           // toast shown when a disabled command is run
  danger?: boolean
  hide?: boolean                  // run by a button only: not in the menus or the palette
}
export type MenuEntry = Cmd | { sep: true } | { head: string }

export const CMD = new Map<string, Cmd>()
export const MENUS: Record<MenuKey, MenuEntry[]> = { cmos: [], file: [], edit: [], process: [], view: [] }
export const MENU_NAMES: Record<MenuKey, string> = { cmos: 'Brainamon', file: 'File', edit: 'Edit', process: 'Process', view: 'View' }

export function cmd(menu: MenuKey, id: string, label: Cmd['label'], run: () => void, o: Partial<Cmd> = {}): Cmd {
  if (CMD.has(id)) throw new Error(`command registered twice: ${id}`)
  const c: Cmd = { id, menu, label, run, ...o }
  CMD.set(id, c)
  if (!c.hide) MENUS[menu].push(c)
  return c
}

export function sep(menu: MenuKey) { MENUS[menu].push({ sep: true }) }
export function head(menu: MenuKey, title: string) { MENUS[menu].push({ head: title }) }

export const labelOf = (c: Cmd) => (typeof c.label === 'function' ? c.label() : c.label)
export const isCmd = (x: MenuEntry): x is Cmd => 'id' in x

export function runCmd(id: string) {
  const c = CMD.get(id)
  if (!c) return
  if (c.off?.()) {
    toast(c.offMsg ? c.offMsg() : `${labelOf(c).replace('…', '')} is not available right now`, 'w')
    return
  }
  closeMenu(true)
  c.run()
}

// A command a later sub-plan builds. Disabled until that plan calls bind().
export const soonText = (plan: string) => `Not in V6 yet (plan ${plan}). Use the Qt app for this for now.`
export function soon(plan: string): Partial<Cmd> {
  return { off: () => true, offMsg: () => soonText(plan) }
}

// Run a menu entry: a registered command through runCmd, or an ad-hoc entry (the card menu)
// directly, with the same disabled-explains-itself rule.
export function runEntry(c: Cmd) {
  if (CMD.get(c.id) === c) { runCmd(c.id); return }
  if (c.off?.()) {
    toast(c.offMsg ? c.offMsg() : `${labelOf(c).replace('…', '')} is not available right now`, 'w')
    return
  }
  closeMenu(true)
  c.run()
}

// Install the real handler for a command registered with soon(). `o` may set new off/offMsg rules.
export function bind(id: string, run: () => void, o: Partial<Cmd> = {}) {
  const c = CMD.get(id)
  if (!c) throw new Error(`no such command: ${id}`)
  c.run = run
  c.off = o.off
  c.offMsg = o.offMsg
  if (o.check) c.check = o.check
  if (o.label) c.label = o.label
}
