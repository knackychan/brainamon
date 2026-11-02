// Global keyboard (V6 l-init.js): Ctrl+K palette, Ctrl+, settings, Ctrl+` console, 1 to 4
// workspaces, ? shortcuts, / search, the Esc chain, and the focus trap of the top window.
// Later sub-plans add keys with onKey() (Ctrl+A, Delete, + - 0) and Esc steps with onEsc().
import { runCmd } from './commands'
import { closeMenu, menu } from './menu.svelte'
import { closeWin, topWin, wins } from './windows.svelte'
import { setWS, ui, WS_LIST } from './ui.svelte'

export const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))

type Hook = (e: KeyboardEvent) => boolean   // return true when the key was handled
const keyHooks: Hook[] = []
const escSteps: (() => boolean)[] = []

export function onKey(fn: Hook): () => void {
  keyHooks.push(fn)
  return () => { const i = keyHooks.indexOf(fn); if (i >= 0) keyHooks.splice(i, 1) }
}
export function onEsc(fn: () => boolean): () => void {
  escSteps.push(fn)
  return () => { const i = escSteps.indexOf(fn); if (i >= 0) escSteps.splice(i, 1) }
}

const FOCUSABLE = 'button:not([disabled]):not([hidden]),[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

function trapTab(e: KeyboardEvent): boolean {
  const w = topWin()
  if (!w || e.key !== 'Tab') return false
  const el = document.querySelector<HTMLElement>(`.cw[data-n="${w.n}"]`)
  if (!el) return false
  const f = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(x => x.offsetParent !== null || x === document.activeElement)
  if (!f.length) return false
  const a = f[0], z = f[f.length - 1]
  if (!el.contains(document.activeElement)) { a.focus(); return true }
  if (e.shiftKey && document.activeElement === a) { z.focus(); return true }
  if (!e.shiftKey && document.activeElement === z) { a.focus(); return true }
  return false
}

export function installKeys() {
  document.addEventListener('keydown', e => {
    const k = e.key, mod = e.ctrlKey || e.metaKey
    if (trapTab(e)) { e.preventDefault(); return }
    if (mod && (k === 'k' || k === 'K')) { e.preventDefault(); closeMenu(true); if (topWin()?.id !== 'palette') runCmd('palette'); return }
    if (mod && k === ',') { e.preventDefault(); runCmd('settings'); return }
    if (mod && k === '`') { e.preventDefault(); runCmd('console'); return }
    if (k === 'Escape') {
      if (menu.open) { e.preventDefault(); closeMenu(); return }
      if (topWin()) { e.preventDefault(); closeWin(); return }
      if (ui.drawer) { e.preventDefault(); ui.drawer = null; return }
      for (const step of escSteps) if (step()) { e.preventDefault(); return }
      return
    }
    if (wins.length || menu.open || typing(e.target)) return
    for (const hook of keyHooks) if (hook(e)) { e.preventDefault(); return }
    if (mod || e.altKey) return
    if (k >= '1' && k <= '4') { setWS(WS_LIST[+k - 1]); return }
    if (k === '?') { e.preventDefault(); runCmd('keys'); return }
    if (k === '/') {
      const q = document.getElementById('q') as HTMLInputElement | null
      if (q && ui.ws === 'lib') { e.preventDefault(); q.focus(); q.select() }
    }
  })
}
