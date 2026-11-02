// Reconnect (mirror/phone-reconnect.ts) runs on one thread, but every awaited Drive call is a window for a tap.
// Ordinary cloud changes call reconnectGate() and refuse while reconnecting/stopping. Confirmed priority
// actions use stopCloudWork(): cancel reads, invalidate late results and drain atomic writes before continuing.
// No imports: every caller (pairing.ts included) can use it without a cycle.
export const RECONNECT_BUSY = 'Recovery is reconnecting this phone. Wait for it to finish, then retry.'
let active = false
let cloudChanges = 0
let revision = 0
let reads = new AbortController()
export const cloudReadSignal = () => reads.signal
let stopping = false
const idle = new Set<() => void>()
export class CloudCancelled extends Error { constructor() { super('Previous cloud work stopped. Local changes stay on this phone.') } }
export const cloudRevision = () => revision
export function cloudCheckpoint(expected: number) { if (expected !== revision) throw new CloudCancelled() }
export const cloudStopped = () => stopping
function settled() { if (!active && !cloudChanges) { for (const done of idle) done(); idle.clear() } }
// Stop at request boundaries, then wait for local journal/reconnect commits before changing the connection.
export async function stopCloudWork() {
  stopping = true; revision++
  reads.abort(); reads = new AbortController()
  if (active || cloudChanges) await new Promise<void>(resolve => idle.add(resolve))
}
export function allowCloudWork() { stopping = false }
export const reconnecting = () => active
export const cloudChanging = () => cloudChanges > 0
export function setReconnecting(on: boolean) { active = on; settled() }
export function reconnectGate() { if (stopping) throw new CloudCancelled(); if (active) throw new Error(RECONNECT_BUSY) }
export function beginCloudChange() { reconnectGate(); cloudChanges++ }
export function endCloudChange() { cloudChanges--; settled() }
