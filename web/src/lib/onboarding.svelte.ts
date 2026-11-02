// The desktop's first run (server/routes/onboarding.py): its state, and the windows it opens: the welcome
// question at the first start (HI-00), Turn on Wiskit (AI-01) and the answer's start action (Scrapers on
// that site, or Add). The rules both apps share are in onboarding.ts.
import { api } from './api'
import { openAdd } from './edit-commands'
import { on } from './events.svelte'
import { openImport, openScrapersFor } from './io-commands.svelte'
import { startFor, toolsReady, type DriveState, type SetupStep } from './onboarding'
import type { ToolsView } from './setup'
import { openWin } from './windows.svelte'
import WelcomeWin from '../windows/WelcomeWin.svelte'
import WiskitKeyWin from '../windows/WiskitKeyWin.svelte'

export interface OnbView { answer: string; hidden: boolean; welcome: boolean; items: number; notes: number; wiskit: boolean; step: SetupStep; skipped: string[] }
export const onb = $state({ loaded: false, saving: false, answer: '', hidden: false, welcome: false, items: 0, notes: 0, wiskit: false, tools: false, browser: false, drive: false, recovery: false, phone: false, step: 'library' as SetupStep, skipped: [] as string[] })

let installChecks: Promise<boolean> | null = null
export function loadInstallChecks(): Promise<boolean> {
  if (installChecks) return installChecks
  installChecks = Promise.allSettled([
    api.get<ToolsView>('/api/settings/tools').then(t => { onb.tools = toolsReady(t) }).catch(e => { onb.tools = false; throw e }),
    api.get<{ state: string }>('/api/settings/scraper-runtime').then(t => { onb.browser = t.state === 'ready' }).catch(e => { onb.browser = false; throw e }),
    api.get<DriveState & { last_publish?: number }>('/api/cloud').then(c => { onb.drive = c.signed_in && !!c.last_publish }).catch(e => { onb.drive = false; throw e }),
    api.get<{ enrolled: boolean }>('/api/cloud/recovery').then(r => { onb.recovery = r.enrolled }).catch(e => { onb.recovery = false; throw e }),
  ]).then(results => results.every(r => r.status === 'fulfilled')).finally(() => { installChecks = null })
  return installChecks
}

let preferenceVersion = 0, pendingWrites = 0
let writes: Promise<unknown> = Promise.resolve()
function take(v: OnbView, version: number, saved = false): OnbView {
  const { answer, hidden, step, skipped, ...facts } = v
  Object.assign(onb, facts, { loaded: true })
  if (version === preferenceVersion && (saved || !pendingWrites)) Object.assign(onb, { answer, hidden, step: step ?? 'library', skipped: skipped ?? [] })
  return v
}
export const loadOnboarding = () => {
  const version = pendingWrites ? -1 : preferenceVersion
  return api.get<OnbView>('/api/onboarding').then(v => take(v, version))
}
export function saveOnboarding(patch: { answer?: string; hidden?: boolean; step?: SetupStep; skipped?: string[] }) {
  pendingWrites++; onb.saving = true
  const version = ++preferenceVersion
  Object.assign(onb, patch)
  const result = writes.catch(() => {}).then(() => api.put<OnbView>('/api/onboarding', patch))
    .then(v => take(v, version, true)).finally(() => { onb.saving = --pendingWrites > 0 })
  writes = result
  return result
}
// Get started is on screen: a missing Wiskit key is then one of its tasks, not an error (the Wiskit desk)
export const guiding = () => onb.loaded && !!onb.answer && !onb.hidden

// a key or model saved anywhere (Settings, Turn on Wiskit) can tick the Wiskit task, and the first
// personal note (Add, My Notes) the saves task; new cards reach GetStarted through the library store
let watching = false
export function watchOnboarding() {
  if (watching) return
  watching = true
  const reload = () => { loadOnboarding().catch(() => {}) }
  on('settings_changed', reload)
  on('cloud', (c: DriveState & { last_publish?: number }) => { if (c.last_publish !== undefined || !c.signed_in) onb.drive = c.signed_in && !!c.last_publish })
  on('notes_changed', (d: { personal?: boolean }) => { if (d.personal) reload() })
}

export function openWelcome() {
  openWin({
    id: 'welcome', title: 'Welcome to Brainamon', code: 'HI-00', w: 920, cls: 'setup-win', closeLabel: 'Skip', body: WelcomeWin,
    // Skip, Escape and the scrim answer 'skip': the welcome does not come back, Get started stays
    onClose: () => {
      if (onb.answer) return
      onb.answer = 'skip'
      saveOnboarding({ answer: 'skip' }).catch(() => {})
    },
  })
}

// `want`: the provider a chat needs (the Wiskit desk's no-key line); empty = WiskitKeyWin's own choice
export function openWiskitKey(want = '') { openWin({ id: 'wiskit-key', title: 'Turn on Wiskit', code: 'AI-01', w: 520, body: WiskitKeyWin, props: { want } }) }

// the answer's start action: Scrapers with that site's guide, else Add
export function runStart(answer: string = onb.answer) {
  if (answer === 'files') { openImport(); return }
  const s = startFor(answer)
  if (s.site) openScrapersFor(s.site)
  else openAdd()
}
