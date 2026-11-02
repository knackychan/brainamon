// One policy for Drive reads, uploads and automatic offline downloads. Unknown networks wait too.
import { isApp, networkStatus, onNetworkChange, type NetworkStatus } from './native'
import type { AccessKind } from './mirror/license'

const savedWifiOnly = () => { try { return localStorage.getItem('bp-wifi') !== 'off' } catch { return true } }
// licenseKind / licenseAt: why the last access check refused this phone, and when the refused confirmation was issued (ms)
export const network = $state({ wifiOnly: savedWifiOnly(), type: 'unknown', online: navigator.onLine, ready: false, licenseLocked: false, licenseProblem: '', licenseKind: '' as '' | AccessKind, licenseAt: 0 })

export const syncPaused = () => !network.online || (network.wifiOnly && network.type !== 'wifi' && network.type !== 'ethernet')
export function syncPauseReason(): string {
  if (!network.online) return 'Sync paused · offline'
  if (!network.ready) return 'Sync paused · checking Wi-Fi'
  return network.type === 'unknown' ? 'Sync paused · cannot confirm Wi-Fi' : 'Sync paused · waiting for Wi-Fi'
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
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void readNetwork() })
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
