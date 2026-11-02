// The card right-click menu and the card keys (V6 cardMenu / cardKey). Actions a later sub-plan
// builds are looked up in `cardActs`, which that plan fills; until then they explain themselves.
import { soonText, type Cmd, type MenuEntry } from './commands'
import { startJob, jobBusy, jobBusyMsg } from './jobs'
import { hooks, isVid, lib, NEED, toggleFav, toggleSel } from './library.svelte'
import { openMenu } from './menu.svelte'
import { titleOf } from './cards/card'
import { toast } from './ui.svelte'
import { cv } from './canvas.svelte'

export type CardAct = 'open' | 'report' | 'del' | 'download' | 'thumbOnly' | 'analyze'
  | 'canvasThumb' | 'canvasDesc' | 'canvasAi' | 'canvasReport' | 'canvasFrame' | 'grip' | 'ask'
const PLAN: Record<CardAct, string> = {
  open: '06', report: '06', del: '06', download: '07', thumbOnly: '07', analyze: '07',
  canvasThumb: '09', canvasDesc: '09', canvasAi: '09', canvasReport: '09', canvasFrame: '09', grip: '09', ask: '11',
}
export const cardActs: Partial<Record<CardAct, (id: number, from?: HTMLElement) => void>> = {}

export function act(name: CardAct, id: number, from?: HTMLElement) {
  if (name === 'open' && hooks.openItem) { hooks.openItem(id); return }
  const f = cardActs[name]
  if (f) f(id, from); else toast(soonText(PLAN[name]), 'w')
}

const cvName = () => cv.doc?.name ?? 'a new canvas'

export function openURL(url: string) {
  if (!/^https?:\/\//i.test(url)) { toast('This item has no web address', 'w'); return }
  window.open(url, '_blank', 'noopener')
}

export function openCardMenu(id: number, at: { x: number; y: number }, from: HTMLElement | null) {
  const r = lib.byId.get(id)
  if (!r) return
  let n = 0
  const e = (label: string, run: () => void, o: Partial<Cmd> = {}): Cmd => ({ id: `card-${n++}`, menu: 'edit', label, run, ...o })
  const step = (label: string, done: boolean, run: () => void, o: Partial<Cmd> = {}): Cmd =>
    e(done ? `${label} (run again)` : label, run, { check: () => done, off: jobBusy, offMsg: jobBusyMsg, ...o })
  const list: MenuEntry[] = [
    { head: `No.${id} · ${titleOf(r)}` },
    e('Edit / details', () => act('open', id), { icon: 'edit' }),
    e(lib.sel.has(id) ? 'Deselect' : 'Select', () => toggleSel(id), { icon: 'check' }),
    e(r.fav ? 'Remove from favourites' : 'Make favourite (holo)', () => toggleFav(id), { icon: 'star' }),
    { sep: true },
    e(`Add thumbnail to ${cvName()}`, () => act('canvasThumb', id), { icon: 'canvas' }),
    e(`Add description to ${cvName()}`, () => act('canvasDesc', id), { icon: 'note' }),
    e(`Add AI summary to ${cvName()}`, () => act('canvasAi', id), { icon: 'note', off: () => !r.ai, offMsg: () => 'This item has no AI summary yet' }),
    { sep: true },
    e('Open URL', () => openURL(r.url), { icon: 'link' }),
    // Process steps: the box is ticked when the step is done, and a done step reads "run again".
    step('Fetch link info', r.thumb, () => startJob('thumb', { ids: [id], force: true })),
    step('Describe', !(r.nd & NEED.describe), () => startJob('describe', { ids: [id], force: true })),
    step('Auto-categorize', !(r.nd & NEED.categorize), () => startJob('categorize', { ids: [id], force: true })),
    step('Analyze video', r.an, () => act('analyze', id), { off: () => !isVid(r), offMsg: () => 'Only reels and videos can be analyzed' }),
    step('Index for search', !(r.nd & NEED.index), () => startJob('index', { ids: [id] })),
    { sep: true },
    e('View analysis report', () => act('report', id), { icon: 'film', off: () => !r.an, offMsg: () => 'This item is not analyzed yet' }),
    e('Ask Wiskit about this', () => act('ask', id), { icon: 'note' }),
    { sep: true },
    e('Delete', () => act('del', id), { icon: 'trash', danger: true }),
  ]
  openMenu(list, from, at)
}
