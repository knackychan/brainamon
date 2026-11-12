// Vault sync controls and foreground fallback. Supported Android devices use the shared native worker;
// WorkManager owns periodic checks. Older devices retain visible-page rounds every two minutes.
// Android app paired to a PC only.
// The PC's side (state, step, done/total) comes from the status file its rounds write to Drive (readPc, watchPc).
//
// A round always ends, so the panel never stays on "syncing":
// - Stop syncing (stopVault) asks the round to stop between two files (vault/sync.ts); a file being written is
//   finished first. If the round has not ended STOP_GRACE_MS later (a call that hangs), the panel moves on and
//   the round finishes its file in the background; no new round starts until it has.
// - a round that reports no step for STALL_MS is stopped the same way, and the panel says where it was.
// - a round does not start while Google Drive is not usable (not connected, wrong account, no library): the
//   panel says why, in the Drive box's words (state.svelte.ts driveStatus).
// - the read of the library goes first: a round asked for while it runs (or before the first one at app start
//   has ended) is queued until it ends, so the two do not share Google's rate limit and Settings > Sync shows
//   which one runs. A read asked for during a round runs at once.
import { t } from '../../lib/i18n/index.ts'
import { fmtDate, fmtTime } from '../../lib/i18n/format.ts'
import { phoneWords, nativeError } from '../settings-words'
import { kv } from '../store'
import { isApp, vaultPick } from '../native'
import { setVaultName } from '../obsidian'
import { driveStatus, phone, solo, source } from '../state.svelte'
import type { FileCounts, PcStatus } from './sync'
import { progress, type Progress } from '../../lib/progress'
import { syncPaused, syncPauseReason } from '../network.svelte'
import { nativeSyncPolicy, nativeSyncSupported, readNativeStatus, nativeSync } from '../sync/native.svelte'
import { languageWorkChanged, registerLanguageCheck } from '../language-switch.ts'

export interface VaultOpts { on: boolean; uri: string; name: string }
// outcome: how the last round ended ('' before the first one)
export type VaultOutcome = '' | 'ok' | 'waiting' | 'error' | 'brake' | 'stopped'
export const vault = $state({ opts: { on: false, uri: '', name: '' } as VaultOpts, busy: false, picking: false, stopping: false, queued: false, line: '', brake: '', step: '',
                              outcome: '' as VaultOutcome, lastAt: 0,
                              files: null as FileCounts | null, pc: null as PcStatus | null, pcRead: false,
                              legacy: 0 })      // leftover Content Manager/ copies the last round kept (spec 1b decision 3)

export const PC_FIRST = 'The PC has not reported a vault round yet. It runs one every 30 seconds once "Sync my Obsidian vault" is on, so this can take a few minutes.'

const STALL_MS = 2 * 60 * 1000        // no step reported for this long: the round is stopped
const LISTING = 'Listing the vault folder'   // one native call that takes long on thousands of files: it gets twice the time
const STOP_GRACE_MS = 20 * 1000       // after Stop syncing, how long the panel waits for the file in progress
const MIN_GAP_MS = 60 * 1000          // automatic rounds (after a read of Drive) at most this often
// the PC reports at least every few seconds while a round runs (SyncService._vault_report): no news for this
// long means it stopped (the app closed, the computer slept) whatever its last words were
export const PC_STALE_MS = 2 * 60 * 1000

function when(ms: number, localized = false): string {
  const d = new Date(ms), time = localized ? fmtTime(d, { hour: '2-digit', minute: '2-digit' }, []) : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? time : `${localized ? fmtDate(d, {}) : d.toLocaleDateString()} ${time}`
}

// the PC's status as the Settings window words it: the step, done/total, percent and time left while a round runs, else the last round
export function pcLine(p: PcStatus, words?: (key: string, params?: Record<string, unknown>) => string): string {
  if (p.state === 'syncing') {
    if (Date.now() - p.at > PC_STALE_MS) return (words?.('backup.vault.stale', { when: when(p.at, !!words) }) ?? `No news from the PC since ${when(p.at)}: its round may have stopped`)
    const pr = pcProgress(p, words)
    return `${p.step} ${p.done}/${p.total}${pr ? ` · ${pr.pct}%${pr.left ? ` · ${pr.left}` : ''}` : ''}`
  }
  if (p.state === 'off') return (words?.('backup.vault.pcOff', { when: when(p.at, !!words) }) ?? `Vault sync is off on the PC (Settings > Obsidian & map > Vault sync with phone) · reported ${when(p.at)}`)
  if (p.state === 'starting' || p.state === 'stopping') return (words?.(p.state === 'starting' ? 'backup.vault.pcStarting' : 'backup.vault.pcStopping', { when: when(p.at, !!words) }) ?? `${p.state === 'starting' ? 'Starting' : 'Stopping'} on the PC · reported ${when(p.at)}`)
  if (p.state === 'brake') return (words?.('backup.vault.pcHeld', { detail: p.reason }) ?? `Held on the PC: ${p.reason} (Apply deletions anyway in Settings > Obsidian & map)`)
  if (p.state === 'error') return words?.('shared.native.vault.detail', { detail: p.reason }) ?? p.reason
  return (words?.('backup.vault.lastRound', { when: when(p.last, !!words), summary: p.summary ? ` · ${p.summary}` : '' }) ?? `Last round ${when(p.last)}${p.summary ? ` · ${p.summary}` : ''}`)
}

// the PC round's bar, paced on the PC's own clock (at: when it wrote the status), so the phone's clock does not matter
export function pcProgress(p: PcStatus, words?: (key: string, params?: Record<string, unknown>) => string): Progress | null {
  return p.state === 'syncing' && p.total > 0 && Date.now() - p.at <= PC_STALE_MS ? progress(p.done, p.total, p.since, p.at, words) : null
}

export async function readPc() {
  if (!source.vaultPc || syncPaused()) return
  try { vault.pc = await source.vaultPc(); vault.pcRead = true } catch { /* offline: keep the last status */ }
}

// while the Vault panel is open: every 5 seconds during a PC round, every 30 otherwise
export function watchPc(): () => void {
  let timer = 0, live = true
  const tick = async () => { await readPc(); if (live) timer = window.setTimeout(tick, vault.pc?.state === 'syncing' ? 5000 : 30000) }
  tick()
  return () => { live = false; clearTimeout(timer) }
}

export async function saveVaultOpts() { await kv.setRequired('vault', { ...vault.opts }) }

let halt: (() => void) | null = null        // the running round's Stop
let running = false                         // a round's own promise has not ended (an abandoned one still counts)
registerLanguageCheck(() => vault.busy || vault.picking || vault.queued || running ? 'settings.language.unsavedWork' : null)

// Stop syncing: the round stops after the file it is on; the panel shows it at once
export function stopVault() {
  halt?.()
  vault.opts = { ...vault.opts, on: false }
  void Promise.all([kv.setRequired('vault', { ...vault.opts }), nativeSyncPolicy({ vault: false })]).catch(e => { vault.line = nativeError('vault', e) })
}

// Choose / Start / Stop, shared by Settings > Sync (the vault's row) and Settings > Obsidian
export async function pickVaultFolder() {
  if (vault.picking || vault.busy || vault.queued || running) return
  vault.picking = true
  languageWorkChanged()
  // the chosen folder is the vault, so Open in Obsidian uses its name from now on (a name typed later still wins)
  try {
    const r = await vaultPick(), opts = { ...vault.opts, uri: r.uri, name: r.name }
    await kv.delRequired('vault-state')
    await kv.setRequired('vault', opts)
    await nativeSyncPolicy({ uri: opts.uri, vault: opts.on })
    vault.opts = opts
    if (r.name) setVaultName(r.name)
    vault.line = ''
  }
  catch (e) { if ((e as Error).message !== 'cancelled') vault.line = nativeError('vault', e) }
  finally { vault.picking = false; languageWorkChanged() }
}
// Stop syncing is asked of the round first (it finishes the file it is on), then saved
export async function setVaultOn(on: boolean) {
  if (vault.picking) return
  if (!on) stopVault()
  try {
    const opts = { ...vault.opts, on }
    await nativeSyncPolicy({ vault: on })
    await kv.setRequired('vault', opts)
    vault.opts = opts
    if (on) await runVault()
  } catch (e) { vault.line = nativeError('vault', e) }
}

// Remove old Brainamon pages (spec 1b decision 3): what is left of the classic Content Manager/ folder goes to
// .trash, on the user's click, between rounds
export async function removeOldPages() {
  if (vault.busy || vault.queued || running || !source.vaultRemoveLegacy) return
  vault.busy = true; vault.step = t('backup.vault.movingOld'); vault.line = ''
  languageWorkChanged()
  try {
    const n = await source.vaultRemoveLegacy()
    vault.legacy = 0
    vault.line = t('backup.vault.oldMoved', { n })
    const st = await kv.get<{ legacy?: number }>('vault-state')
    if (st) await kv.set('vault-state', { ...st, legacy: 0 })
  } catch (e) { vault.line = nativeError('vault', e) }
  finally { vault.busy = false; vault.step = ''; languageWorkChanged() }
}

// the library is being read from Google Drive (on its own or within Sync now), or the first read has not ended
export const driveReading = () => phone.refreshing || (!!phone.sync && !phone.sync.end) || !phone.tried

export async function runVault(force = false, auto = false) {
  if (vault.picking || vault.busy || vault.queued || !vault.opts.on || !vault.opts.uri || !source.syncVault) return
  if (syncPaused()) return
  if (auto && Date.now() - vault.lastAt < MIN_GAP_MS) return
  if (running) { vault.line = t('backup.vault.stillFinishing'); return }
  if (!driveStatus().ok) return                   // the panel shows why (Vault.svelte)
  if (driveReading()) {
    vault.queued = true
    languageWorkChanged()
    try { while (driveReading() && !syncPaused()) await new Promise(res => setTimeout(res, 500)) } finally { vault.queued = false; languageWorkChanged() }
    // the read decides: Google Drive may want a sign-in now, or Stop syncing came meanwhile
    if (!vault.opts.on || !driveStatus().ok || syncPaused()) return
  }
  const stop = new AbortController()
  const t0 = Date.now()
  let tick = t0, stoppedAt = 0, step = '', displayStep = '', over = false          // over: the panel no longer waits for this round
  vault.busy = true; vault.stopping = false; vault.brake = ''; vault.line = ''; vault.step = t('backup.vault.starting'); vault.files = null
  languageWorkChanged()
  halt = () => {
    if (vault.stopping) return
    vault.stopping = true; stoppedAt = Date.now(); vault.step = t('backup.vault.stoppingAfter')
    stop.abort()
  }
  let cut: (why: string) => void = () => {}
  const cutting = new Promise<{ cut: string }>(res => { cut = why => res({ cut: why }) })
  const dog = window.setInterval(() => {
    if (nativeSync.supported) return       // the native worker owns its deadline, including while this page sleeps
    if (vault.stopping) { if (Date.now() - stoppedAt > STOP_GRACE_MS) cut(t('backup.vault.stoppedBackground')) }
    else if (Date.now() - tick > (step === LISTING ? 2 * STALL_MS : STALL_MS)) {
      stop.abort()
      cut(t('backup.vault.stalled', { minutes: step === LISTING ? 4 : 2, step: step ? t('backup.vault.stalledAt', { step: displayStep || step }) : '' }))
    }
  }, 2000)
  readPc()
  running = true
  const round = source.syncVault(force, (name, done, total, _overall, display, files) => {
    tick = Date.now()
    if (over || vault.stopping) return
    step = name
    displayStep = display ?? name
    if (files) vault.files = files
    vault.step = `${display ?? name}${total > 0 ? ` ${done}/${total}` : ''}`
  }, stop.signal, phoneWords).then(r => ({ r }), (e: Error) => ({ e }))
  round.finally(() => { running = false; languageWorkChanged() })
  try {
    const o = await Promise.race([round, cutting])
    over = true
    if ('r' in o && o.r.legacy !== undefined) vault.legacy = o.r.legacy
    if (syncPaused()) { vault.line = syncPauseReason(phoneWords); vault.outcome = 'waiting' }
    else if ('cut' in o) { vault.line = o.cut; vault.outcome = 'error' }
    else if ('e' in o) { vault.line = nativeError('vault', o.e); vault.outcome = 'error' }
    else if (o.r.state === 'brake') { vault.brake = o.r.reason; vault.outcome = 'brake' }
    else if (o.r.state === 'stopped') { vault.line = t('backup.vault.stopped', { detail: o.r.summary || o.r.reason }); vault.outcome = 'stopped' }
    else if (o.r.state === 'waiting') { vault.line = o.r.reason; vault.outcome = 'waiting' }
    else { vault.line = `${fmtTime(new Date(), {})} · ${o.r.summary}`; vault.outcome = 'ok' }
  } finally {
    clearInterval(dog)
    halt = null
    vault.busy = false; vault.stopping = false; vault.step = ''; vault.lastAt = Date.now()
    languageWorkChanged()
  }
}

export function startVault(): () => void {
  if (!isApp || solo || !source.syncVault) return () => {}
  kv.get<VaultOpts>('vault').then(o => { if (o) vault.opts = o; runVault(false, true) })
  kv.get<{ legacy?: number }>('vault-state').then(s => { vault.legacy = s?.legacy ?? 0 })
  const visible = () => { if (document.visibilityState === 'visible') { void readNativeStatus(); runVault(false, true) } }
  let resumeT = 0
  const resume = () => {
    if (syncPaused()) return
    if (vault.busy || vault.queued || running) { resumeT = window.setTimeout(resume, 250); return }
    void runVault()
  }
  document.addEventListener('visibilitychange', visible)
  window.addEventListener('brainamon-sync-resume', resume)
  const timer = window.setInterval(async () => { if (!document.hidden && !await nativeSyncSupported()) runVault(false, true) }, 2 * 60 * 1000)
  return () => { document.removeEventListener('visibilitychange', visible); window.removeEventListener('brainamon-sync-resume', resume); clearInterval(timer); clearTimeout(resumeT) }
}
