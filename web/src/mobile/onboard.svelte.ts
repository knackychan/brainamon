// The phone's first run (spec P1-P4): the welcome's answer, Hide and the coach mark, kept in IndexedDB kv
// 'onboard' (not in store.wipe(), so a pairing change keeps it), and the scroll to a More box that Get
// started, the empty library and Settings > Setup share.
import { tick } from 'svelte'
import { kv } from './store'
import { phone, solo } from './state.svelte'
import { setMoreFrom } from './back'

export interface Onb { answer: string; hidden: boolean; coach: boolean }
export const onb = $state({ loaded: false, answer: '', hidden: false, coach: false })

export async function loadOnb() {
  const v = await kv.get<Partial<Onb>>('onboard')
  onb.answer = typeof v?.answer === 'string' ? v.answer : ''
  onb.hidden = !!v?.hidden
  onb.coach = !!v?.coach
  onb.loaded = true
}

// the screen follows at once; the copy in IndexedDB follows (a plain object: a $state proxy cannot be stored)
export async function saveOnb(patch: Partial<Onb>) {
  Object.assign(onb, patch)
  await kv.set('onboard', { answer: onb.answer, hidden: onb.hidden, coach: onb.coach })
}

// a screen that sends the reader to More (Wiskit's "Add a key") tells back.ts where More's Back goes (setMoreFrom);
// it is forgotten as soon as the reader leaves More's screens, so an ordinary visit to More keeps the Library
// (plan phone-wiskit-chat 02 Task 6)
// (More's routes as parseRoute reads them: more, backup, recover)
if (typeof window !== 'undefined') window.addEventListener('hashchange', () => { if (!/^#\/?(more|backup|recover)(\/|$)/.test(location.hash)) setMoreFrom('') })

// open More (when not on it: Backup & phones and Recover a library are More's screens too) and bring the box
// into view once it is on screen; `fallback` when More, in its current state, has no `id`
export async function openMoreBox(id: string, fallback = '') {
  const group = id === 'm-ai' ? 'wiskit' : id === 'm-vault' ? 'obsidian' : ['m-desktop', 'm-app-info'].includes(id) ? 'about' : ''
  const hash = group ? `#/more/${group}` : '#/more'
  if (location.hash !== hash) location.hash = hash
  await reveal(id, fallback)
}

// the same for a box of Settings > Backup & phones (a phone paired with a PC or used without one: This phone, Google account,
// Recovery)
export async function openBackupBox(id: string, fallback = '') {
  if (!phone.route.backup || phone.route.manage) location.hash = '#/backup'
  await reveal(id, fallback)
}

async function reveal(id: string, fallback: string) {
  for (let i = 0; i < 20; i++) {
    await tick()
    const el = document.getElementById(id) ?? (fallback ? document.getElementById(fallback) : null)
    if (el && el.getClientRects().length) {
      for (let node: HTMLElement | null = el; node; node = node.parentElement) {
        if (node instanceof HTMLDetailsElement) node.open = true
      }
      await tick()
      const row = el.matches('input, button, a, [tabindex]') ? el : el.querySelector<HTMLElement>('.m-srow, .m-group-row') ?? el
      if (!row.hasAttribute('tabindex') && !row.matches('input, button, a')) row.setAttribute('tabindex', '-1')
      ;(row as HTMLElement).focus({ preventScroll: true })
      el.scrollIntoView({ block: 'start', behavior: phone.motionOff || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
      return
    }
    await new Promise(r => requestAnimationFrame(r))
  }
}

// "Connect your PC": without a PC (solo) the pairing rows are in This phone on Backup & phones (m-pair); every other
// connection box on More is about the PC already (m-conn)
export const openPairing = () => solo ? openBackupBox('m-pair', 'm-phone') : openMoreBox('m-pair', 'm-conn')
