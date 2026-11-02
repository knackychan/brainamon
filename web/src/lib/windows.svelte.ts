// CM-OS windows: full dialogs use WinFrame, short item actions use ActionPopup.
// Bodies render `.cw-body` and, when they have buttons, `.cw-foot`.
import type { Component } from 'svelte'
import { tick } from 'svelte'
import ConfirmBody from '../components/ConfirmBody.svelte'
import PromptBody from '../components/PromptBody.svelte'
import { closeMenu } from './menu.svelte'

export interface WinSpec {
  id?: string                     // a second open with the same id replaces the first
  title: string
  code?: string                   // the little code on the title bar (e.g. 'ASK-00')
  w?: number                      // width in px (default 640)
  cls?: string                    // extra class on section.cw
  alert?: boolean                 // role=alertdialog; only popups allow scrim cancellation
  popup?: boolean                 // short item actions use ActionPopup, next to their source
  anchor?: DOMRect
  closeLabel?: string             // the title bar's close key (default 'Close'; the welcome says 'Skip')
  body: Component<any>
  props?: Record<string, unknown>
  onClose?: () => void
}
export interface Win extends WinSpec { n: number; from: Element | null }

export const wins: Win[] = $state([])
let seq = 0

export function openWin(spec: WinSpec): Win {
  if (spec.id) {
    const ex = wins.find(w => w.id === spec.id)
    if (ex) closeWin(ex, true)
  }
  closeMenu(true)
  const w: Win = { ...spec, n: ++seq, from: document.activeElement }
  wins.push(w)
  return w
}

export function closeWin(w?: Win, quiet = false) {
  const target = w ?? wins[wins.length - 1]
  if (!target) return
  const i = wins.findIndex(x => x.n === target.n)   // $state proxies: compare by n, not identity
  if (i < 0) return
  const [gone] = wins.splice(i, 1)
  gone.onClose?.()
  const from = gone.from
  const next = topWin()?.n
  // Wait for the shell to lose inert before restoring the action's keyboard focus.
  if (!quiet) tick().then(() => {
    if (topWin()?.n === next && from instanceof HTMLElement && from.isConnected) from.focus({ preventScroll: true })
  })
}

export const topWin = (): Win | undefined => wins[wins.length - 1]

let actionOrigin: DOMRect | undefined
export function withActionAnchor(from: HTMLElement, run: () => void) {
  const previous = actionOrigin
  actionOrigin = from.getBoundingClientRect()
  try { run() } finally { actionOrigin = previous }
}

function actionAnchor(): DOMRect | undefined {
  if (actionOrigin) return actionOrigin
  const from = document.activeElement
  if (!(from instanceof HTMLElement) || from === document.body || from === document.documentElement) return
  const r = from.getBoundingClientRect()
  if (r.width && r.height) return r
}

export function confirmWin(o: { title: string; msg: string; detail?: string; ok?: string; danger?: boolean; code?: string }): Promise<boolean> {
  return new Promise(res => {
    let done = false
    const finish = (v: boolean) => { if (!done) { done = true; res(v) } }
    const w = openWin({
      title: o.title, code: o.code ?? 'ASK-00', w: 340, alert: true, popup: true, anchor: actionAnchor(), body: ConfirmBody,
      props: { msg: o.msg, detail: o.detail, ok: o.ok ?? 'OK', danger: !!o.danger, answer: (v: boolean) => { finish(v); closeWin(w) } },
      onClose: () => finish(false),
    })
  })
}

export function promptWin(o: { title: string; label?: string; value?: string; hint?: string; ok?: string; code?: string; check?: (v: string) => string | null }): Promise<string | null> {
  return new Promise(res => {
    let done = false
    const finish = (v: string | null) => { if (!done) { done = true; res(v) } }
    const w = openWin({
      title: o.title, code: o.code ?? 'ASK-01', w: 340, popup: true, anchor: actionAnchor(), body: PromptBody,
      props: { label: o.label ?? 'Name', value: o.value ?? '', hint: o.hint, ok: o.ok ?? 'OK', check: o.check, answer: (v: string) => { finish(v); closeWin(w) } },
      onClose: () => finish(null),
    })
  })
}
