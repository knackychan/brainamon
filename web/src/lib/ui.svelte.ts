// Shared UI state: workspace, drawers, theme, Motion, toasts, console lines.
export type Ws = 'lib' | 'know' | 'canvas' | 'notes'
export const WS_LIST: Ws[] = ['lib', 'know', 'canvas', 'notes']
export const WS_NAME: Record<Ws, string> = { lib: 'Library', know: 'Knowledge', canvas: 'Canvas', notes: 'Notes' }
export const WS_SHORT: Record<Ws, string> = { lib: 'Lib', know: 'Know', canvas: 'Canvas', notes: 'Notes' }

export const ui = $state({
  ws: 'lib' as Ws,
  drawer: null as null | 'pad' | 'jv',   // below 1200 px the rail and Wiskit are drawers
  dark: false,
  motionOff: false,
  consoleOpen: false,
  consoleHot: false,                     // an error arrived while the console was closed
  libCount: 0,
  // false until the first Library cards are on screen: the rail docks and Wiskit mount after
  // them, so a cold start lays out the cards first (perf pass 2026-10-10)
  ready: false,
})

const WS_KEY = 'cm-v6-ws'
export function readyAfterPaint(ws: Ws) {
  requestAnimationFrame(() => setTimeout(() => {
    if (ui.ws !== ws) return
    ui.ready = true
    if (!performance.getEntriesByName('cm-first-screen').length) performance.mark('cm-first-screen')
  }))
}

// The desktop startup bar (web/public/boot.js): show why the first screen will not come.
export function bootFail(message: string) {
  (window as unknown as { cmBoot?: { fail(m: string): void } }).cmBoot?.fail(message)
}

export function setWS(ws: Ws) {
  ui.ws = ws
  ui.drawer = null
  try { localStorage.setItem(WS_KEY, ws) } catch { /* private window */ }
}
export function initWS() {
  try {
    const w = localStorage.getItem(WS_KEY) as Ws | null
    if (w && WS_LIST.includes(w)) ui.ws = w
  } catch { /* private window */ }
}

// Day / Night: same localStorage key and data-theme attribute as archive/2026-11-09/design/web-look/os.js themeToggle.
const THEME_KEY = 'cm-os-theme'
export function isDark(): boolean {
  const t = document.documentElement.dataset.theme
  return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
}
export function initTheme() {
  try {
    const t = localStorage.getItem(THEME_KEY)
    if (t) document.documentElement.dataset.theme = t
  } catch { /* private window */ }
  ui.dark = isDark()
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { ui.dark = isDark() })
}
export function toggleTheme() {
  const t = isDark() ? 'light' : 'dark'
  document.documentElement.dataset.theme = t
  try { localStorage.setItem(THEME_KEY, t) } catch { /* private window */ }
  ui.dark = t === 'dark'
}

// Motion: the card engine's own switch (engine.js setMotion / MOTION, key 'cm-card-motion').
export function initMotion() { ui.motionOff = MOTION.off }
export function toggleMotion() {
  setMotion(MOTION.off)
  ui.motionOff = MOTION.off
}

// Toasts replace the Qt status bar: at most 4, 4.2 s, 7 s when they carry an action.
export type ToastLevel = '' | 'w' | 'e' | 'off'
export interface Toast { id: number; text: string; level: ToastLevel; act?: { label: string; run: () => void } }
export const toasts: Toast[] = $state([])
let toastSeq = 0
export function toast(text: string, level: ToastLevel = '', act?: Toast['act']) {
  const id = ++toastSeq
  toasts.push({ id, text, level, act })
  while (toasts.length > 4) toasts.shift()
  setTimeout(() => dropToast(id), act ? 7000 : 4200)
}
export function dropToast(id: number) {
  const i = toasts.findIndex(t => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

// Console drawer lines, fed by GET /api/console then the SSE 'log' events (app_console entries).
export type Tag = 'API' | 'ERR' | 'LOG'
export interface Line { id: string; t: string; tag: Tag; msg: string }
export interface ConsoleEntry { id: string; ts: string; level: string; kind: string; title: string; error?: string }
export const cons = $state({ lines: [] as Line[], filter: 'all' as 'all' | Tag, follow: true })
const MAX_LINES = 1000
export function toLine(e: ConsoleEntry): Line {
  const tag: Tag = e.level === 'error' ? 'ERR' : e.kind === 'api' ? 'API' : 'LOG'
  return { id: e.id, t: e.ts.slice(0, 8), tag, msg: e.error ? `${e.title}: ${e.error}` : e.title }
}
export function pushLine(e: ConsoleEntry) {
  const line = toLine(e)
  cons.lines.push(line)
  if (cons.lines.length > MAX_LINES) cons.lines.splice(0, cons.lines.length - MAX_LINES)
  if (line.tag === 'ERR' && !ui.consoleOpen) ui.consoleHot = true
}
export function toggleConsole(on?: boolean) {
  ui.consoleOpen = on === undefined ? !ui.consoleOpen : on
  if (ui.consoleOpen) ui.consoleHot = false
}
