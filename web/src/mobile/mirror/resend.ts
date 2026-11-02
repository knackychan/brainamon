// Pairing again (S5, docs/superpowers/plans/2026-10-31-phone-backup-phones/02-s5-resend-after-pairing-again.md): every
// edit the PC has not acknowledged goes again under the new key, with its batch number and time. The marker names the
// pairing it was set for (its fingerprint `f` and signer `l`). While it is there, nothing is sent; it goes only after a
// fresh manifest from that pairing was read and the journal saved what goes again (Changes.prune), so a restart, a failed
// read or a failed write leaves the work to do. localStorage, like the solo requeue flag (mirror/pairing.ts).
export const RESEND = 'bp-resend'
export interface ResendPair { f: string; l?: string }

let held: string | null = null          // no localStorage (blocked storage): the marker lasts while the page is open
function store(): Storage | null {
  try { return localStorage ?? null } catch { return null }
}

// throws when the phone has storage but did not keep the marker: the pairing then fails, and can be tried again
export function markResend(p: ResendPair): void {
  const v = JSON.stringify({ f: p.f, l: p.l ?? '', at: Date.now() }), s = store()
  if (s) s.setItem(RESEND, v)
  else held = v
}

export function resendPending(p: ResendPair | null | undefined): boolean {
  if (!p) return false
  try {
    const s = store(), m = JSON.parse((s ? s.getItem(RESEND) : held) ?? 'null') as { f?: unknown; l?: unknown } | null
    return !!m && m.f === p.f && m.l === (p.l ?? '')
  } catch { return false }
}

export function clearResend(p: ResendPair): void {
  if (!resendPending(p)) return
  const s = store()
  if (s) s.removeItem(RESEND)
  else held = null
}
