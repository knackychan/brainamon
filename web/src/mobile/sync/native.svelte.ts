import { Capacitor, registerPlugin } from '@capacitor/core'
import { withTimeout } from '../wait'
import { t, type Key } from '../../lib/i18n/index'
import { fmtTime } from '../../lib/i18n/format'
import type { FileCounts } from '../vault/sync'

export interface NativeSyncStatus { supported: boolean; state: string; nextAt?: number | null; retryable?: boolean; id?: string; observedId?: string; outcome?: string | null; requestReady?: boolean; phase?: string; progress?: number; last?: number; finished?: boolean; scheduled?: boolean; libraryReady?: boolean; driveStep?: { key: Key; done?: number; total?: number } | null; vaultFiles?: FileCounts | null; vaultStep?: { key?: Key; done: number; total: number } }
interface SyncPlugin {
  status(o: { id?: string }): Promise<NativeSyncStatus>
  configure(o: Record<string, unknown>): Promise<NativeSyncStatus>
  request(o: { force?: boolean; legacy?: boolean; uploads?: boolean }): Promise<{ id: string }>
  retry(): Promise<{ id: string }>
  barrier(): Promise<void>
  stage(o: { owner: string; id: string; name: string; data: string }): Promise<{ name: string; remote?: string }>
  receipt(o: { owner: string; id: string }): Promise<{ name?: string; remote?: string }>
  cache(o: { owner: string; name: string }): Promise<{ value: unknown }>
  seedVault(o: { owner: string; state: unknown }): Promise<void>
}
const S = registerPlugin<SyncPlugin>('BrainamonSync')
export const nativeSync = $state<NativeSyncStatus>({ supported: false, state: '' })
const states: Record<string, Key> = {
  syncing: 'settings.sync.native.syncing', idle: 'settings.sync.native.idle', queued: 'settings.sync.native.queued', retry: 'settings.sync.native.retry',
  wifi: 'settings.sync.native.wifi', offline: 'settings.sync.native.offline', paused: 'settings.sync.native.paused',
  auth: 'settings.sync.native.auth', access: 'settings.sync.native.access', permission: 'settings.sync.native.permission',
  conflict: 'settings.sync.native.conflict', update: 'settings.sync.native.update', library: 'settings.sync.native.library',
  attention: 'settings.sync.native.attention', key: 'settings.sync.native.attention', unsupported: 'settings.sync.native.unsupported',
}
export function nativeSyncText(state = nativeSync.state): string {
  if (['queued', 'retry'].includes(state) && nativeSync.nextAt && nativeSync.retryable) return t('settings.sync.native.delayed', { time: fmtTime(nativeSync.nextAt, { hour: '2-digit', minute: '2-digit' }) })
  return t(states[state] ?? 'settings.sync.native.attention')
}
export const nativeRetry = $state({ busy: false, error: '' })
export async function retryNativeSync() {
  if (nativeRetry.busy) return
  nativeRetry.busy = true; nativeRetry.error = ''
  try {
    await policy
    const { id } = await withTimeout(S.retry(), 30_000, nativeSyncText('retry'))
    Object.assign(nativeSync, await withTimeout(S.status({ id }), 15_000, nativeSyncText('retry')))
    checked = 0
    window.dispatchEvent(new Event('brainamon-sync-resume'))
  } catch (e) { nativeRetry.error = nativeSyncText((e as Error).message) }
  finally { nativeRetry.busy = false }
}
export function nativePhasePct(): number | null {
  if (nativeSync.progress === undefined || nativeSync.phase === 'send') return null
  if (nativeSync.phase === 'drive' && nativeSync.progress <= 0) return null
  // SyncRunner reserves 0–40% for Drive and 40–99% for the vault; each lane shows its own progress.
  const fraction = nativeSync.phase === 'vault' ? (nativeSync.progress - 0.4) / 0.59 : nativeSync.progress / 0.4
  return Math.min(99, Math.max(0, Math.round(fraction * 100)))
}
export function nativeDriveText(): string {
  if (nativeSync.phase === 'send') return t('shell.sync.sendStep')
  const step = nativeSync.driveStep
  return step?.key ? t(step.key, { done: step.done ?? 0, total: step.total ?? 0 }) : t('shell.sync.reading', { where: t('shell.sync.whereDrive') })
}
export const nativeSyncError = (code: string) => Object.assign(new Error(nativeSyncText(code)), { code, displayKey: states[code] })
let support: Promise<boolean> | undefined
let implemented = false, disabled: Promise<unknown> | undefined
export function nativeSyncSupported(): Promise<boolean> {
  support ??= (async () => {
    if (!Capacitor.isNativePlatform() || Capacitor.getPlatform?.() !== 'android') return false
    try { Object.assign(nativeSync, await withTimeout(S.status({}), 10_000, 'Sync did not respond.')); implemented = true; return nativeSync.supported }
    catch (e) {
      if ((e as { code?: string }).code === 'UNIMPLEMENTED' || /not implemented|not available/i.test(String(e))) return false
      throw e
    }
  })()
  return support.then(async ok => {
    if (ok && nativeSync.supported) return true
    // Foreground fallback may write the vault only after native ownership is released.
    if (implemented) await (disabled ??= S.configure({ enabled: false }).then(() => S.barrier()).catch(e => { disabled = undefined; throw e }))
    return false
  })
}
let policy: Promise<unknown> = Promise.resolve()
export function nativeSyncPolicy(patch: Record<string, unknown>): Promise<void> {
  const update = policy.catch(() => {}).then(async () => {
    if (await nativeSyncSupported()) Object.assign(nativeSync, await S.configure(patch))
  })
  policy = update
  return update
}
export async function nativeSyncBarrier() {
  await policy
  if (await nativeSyncSupported()) await withTimeout(S.barrier(), 50_000, 'Sync is finishing a file. Retry shortly.')
}
export async function nativeCache<T>(owner: string, name: string): Promise<T | undefined> {
  return (await S.cache({ owner, name })).value as T | undefined
}
export const seedNativeVault = (owner: string, state: unknown) => S.seedVault({ owner, state })
export const nativeReceipt = (owner: string, id: string) => S.receipt({ owner, id })
export async function nativeUploads(owner: string, ids: string[], round: Promise<void>): Promise<void> {
  let settled = false, problem: unknown
  void round.then(() => { settled = true }, e => { settled = true; problem = e })
  for (;;) {
    const receipts = await Promise.all(ids.map(id => nativeReceipt(owner, id)))
    if (receipts.every(r => r.name && r.remote)) return
    if (settled) throw problem ?? nativeSyncError('retry')
    await new Promise(resolve => setTimeout(resolve, 500))
  }
}
export const stageNative = (owner: string, id: string, name: string, data: string) => S.stage({ owner, id, name, data })
let running: Promise<void> | undefined
let reading: Promise<void> | undefined
let checked = 0
export function nativeRound(force = false, legacy = false, dirty = false, onProgress?: (s: NativeSyncStatus) => void, driveOnly = false): Promise<void> {
  if (running) return force || legacy ? running.catch(() => {}).then(() => nativeRound(force, legacy, dirty, onProgress, driveOnly)) : driveOnly ? reading! : running
  if (!force && !legacy && !dirty && Date.now() - checked < 60_000) return Promise.resolve()
  let ready!: () => void, failed!: (e: unknown) => void
  reading = new Promise<void>((resolve, reject) => { ready = resolve; failed = reject })
  void reading.catch(() => {})
  running = (async () => {
    await policy
    const { id } = await S.request({ force, legacy, uploads: dirty && !force && !legacy })
    for (;;) {
      const observed = await S.status({ id })
      Object.assign(nativeSync, observed)
      onProgress?.(nativeSync)
      // The complete library snapshot is usable while the independent vault round catches up.
      if (observed.requestReady || observed.id === (observed.observedId ?? id) && observed.libraryReady) ready()
      if (observed.finished) {
        const outcome = observed.outcome ?? observed.state
        if (!['idle', 'attention'].includes(outcome)) throw nativeSyncError(outcome || 'retry')
        checked = Date.now(); return
      }
      // Native work continues independently; the page waits only to update the existing indicator.
      if (!(observed.state === 'retry' && observed.finished === false) && ['paused', 'wifi', 'offline', 'auth', 'access', 'permission', 'conflict', 'update', 'library', 'retry', 'key', 'unsupported'].includes(observed.state)) throw nativeSyncError(observed.state)
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  })().catch(e => { if (states[(e as Error).message]) throw nativeSyncError((e as Error).message); throw e }).finally(() => { running = undefined; reading = undefined })
  void running.then(ready, failed)
  return driveOnly ? reading : running
}
export async function readNativeStatus() {
  if (await nativeSyncSupported()) Object.assign(nativeSync, await S.status({}))
}
