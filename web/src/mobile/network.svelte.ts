// One policy for Drive reads, uploads and automatic offline downloads. Unknown networks wait too.
import { isApp, networkStatus, onNetworkChange, type NetworkStatus } from './native'
import type { AccessKind } from './mirror/license'
import { nativeSyncPolicy, nativeSync } from './sync/native.svelte'
import { languageWorkChanged, registerLanguageCheck } from './language-switch.ts'

const savedWifiOnly = () => { try { return localStorage.getItem('bp-wifi') !== 'off' } catch { return true } }
// licenseKind / licenseAt: why the last access check refused this phone, and when the refused confirmation was issued (ms)
const savedPause = () => { try { return localStorage.getItem('bp-sync-paused') === 'on' } catch { return false } }
export const network = $state({ manualPause: savedPause(), pausePending: false, pauseFailed: false, background: typeof document !== 'undefined' && document.hidden, wifiOnly: savedWifiOnly(), type: 'unknown', online: navigator.onLine, ready: false, licenseLocked: false, licenseProblem: '', licenseKind: '' as '' | AccessKind, licenseAt: 0 })
registerLanguageCheck(() => network.pausePending || network.pauseFailed ? 'settings.language.unsavedWork' : null)

export const syncPaused = () => network.manualPause || network.background || !network.online || (network.wifiOnly && network.type !== 'wifi' && network.type !== 'ethernet')
export function syncPauseReason(words?: (key: string, params?: Record<string, unknown>) => string, detailOnly = false): string {
  if (network.pausePending) return words?.('settings.sync.savingPolicy') ?? 'Saving sync setting…'
  if (network.pauseFailed) return words?.('settings.sync.policyFailed') ?? 'Sync setting could not be saved. Retry before closing the app.'
  if (network.manualPause) return (words?.(detailOnly ? 'shell.sync.paused.manual.detail' : 'shell.sync.paused.manual') ?? (detailOnly ? 'resume when ready' : 'Sync paused · resume when ready'))
  if (network.background) return (words?.(detailOnly ? 'shell.sync.paused.background.detail' : 'shell.sync.paused.background') ?? (detailOnly ? 'app in background' : 'Sync paused · app in background'))
  if (!network.online) return (words?.(detailOnly ? 'shell.sync.paused.offline.detail' : 'shell.sync.paused.offline') ?? (detailOnly ? 'offline' : 'Sync paused · offline'))
  if (!network.ready) return (words?.(detailOnly ? 'shell.sync.paused.checking.detail' : 'shell.sync.paused.checking') ?? (detailOnly ? 'checking Wi-Fi' : 'Sync paused · checking Wi-Fi'))
  return network.type === 'unknown' ? (words?.(detailOnly ? 'shell.sync.paused.unknown.detail' : 'shell.sync.paused.unknown') ?? (detailOnly ? 'cannot confirm Wi-Fi' : 'Sync paused · cannot confirm Wi-Fi')) : (words?.(detailOnly ? 'shell.sync.paused.wifi.detail' : 'shell.sync.paused.wifi') ?? (detailOnly ? 'waiting for Wi-Fi' : 'Sync paused · waiting for Wi-Fi'))
}
export class SyncPaused extends Error { constructor() { super(syncPauseReason()) } }

let gate = new AbortController(), blocked = syncPaused()
if (blocked) gate.abort()
function policyChanged() {
  const paused = syncPaused(), wasBlocked = blocked
  blocked = paused
  if (paused) gate.abort()
  else if (gate.signal.aborted) gate = new AbortController()
  if (wasBlocked && !paused) window.dispatchEvent(new Event('brainamon-sync-resume'))
}
function update(s: NetworkStatus) {
  network.online = s.connected; network.type = s.type; network.ready = true
  policyChanged()
}
export function setWifiOnly(on: boolean) {
  network.wifiOnly = on
  try { localStorage.setItem('bp-wifi', on ? 'on' : 'off') } catch { /* kept for this session */ }
  policyChanged()
  void nativeSyncPolicy({ wifiOnly: on }).catch(() => { nativeSync.state = 'attention' })
}
export async function setSyncPaused(on: boolean): Promise<boolean> {
  if (network.pausePending) return false
  network.pausePending = true; network.pauseFailed = false
  network.manualPause = true
  languageWorkChanged()
  policyChanged()
  try {
    // A reload during resume must retain the conservative pause until native policy is durable.
    localStorage.setItem('bp-sync-paused', 'on')
    await nativeSyncPolicy({ paused: on })
    localStorage.setItem('bp-sync-paused', on ? 'on' : 'off')
    network.manualPause = on
    return true
  } catch {
    network.pauseFailed = true; nativeSync.state = 'attention'
    return false
  } finally {
    network.pausePending = false
    languageWorkChanged()
    policyChanged()
  }
}

type Connection = EventTarget & { type?: string }
const connection = () => (navigator as Navigator & { connection?: Connection }).connection
async function readNetwork() {
  if (isApp) {
    try { update(await networkStatus()); return } catch { /* older APK: unknown is kept paused */ }
  }
  update({ connected: navigator.onLine, type: connection()?.type || 'unknown' })
}
let started: Promise<void> | undefined
export function initNetwork(): Promise<void> {
  return started ??= (async () => {
    if (isApp) await onNetworkChange(update).catch(() => {})
    else connection()?.addEventListener('change', readNetwork)
    window.addEventListener('online', readNetwork)
    window.addEventListener('offline', readNetwork)
    document.addEventListener('visibilitychange', () => { network.background = document.hidden; policyChanged(); if (!document.hidden) void readNetwork() })
    await readNetwork()
  })()
}

// Recheck before each attempt, including retries; the same signal cancels response bodies on Wi-Fi loss.
export async function syncSignal(): Promise<AbortSignal> {
  await initNetwork()
  await readNetwork()
  if (syncPaused()) throw new SyncPaused()
  return gate.signal
}
