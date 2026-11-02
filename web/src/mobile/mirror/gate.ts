// Reconnect (mirror/phone-reconnect.ts) runs on one thread, but every awaited Drive call is a window for a tap.
// A local cloud change that must not race it (Connect, Change account, Pair, Start or Restore, Disconnect, Remove,
// Send now, Sync now, a refresh, the background look, recovery setup) calls reconnectGate() first: it throws at
// once and never waits. Callers that answer with a note instead read reconnecting(). No imports: every caller
// (pairing.ts included) can use it without a cycle.
export const RECONNECT_BUSY = 'Recovery is reconnecting this phone. Wait for it to finish, then retry.'
let active = false
let cloudChanges = 0
export const reconnecting = () => active
export const cloudChanging = () => cloudChanges > 0
export function setReconnecting(on: boolean) { active = on }
export function reconnectGate() { if (active) throw new Error(RECONNECT_BUSY) }
export function beginCloudChange() { reconnectGate(); cloudChanges++ }
export function endCloudChange() { cloudChanges-- }
