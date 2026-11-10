// The paired PC signs one-hour grants; the issuer's Ed25519 key proves the license.
// Neither key may be supplied by an untrusted Drive record.
declare const __LICENSE_PUBLIC_KEYS__: string[]
export const LICENSE_LOGICAL = 'control/license-v1.json'
export const ACCESS_LOGICAL = 'control/access-v2.json'
export const CONTROL_LOGICALS = [LICENSE_LOGICAL, ACCESS_LOGICAL] as const
export const LICENSE_REQUIRED = 'Waiting for your PC to confirm this phone: keep Brainamon open on your PC with Google Drive connected, then retry. Saved content and queued edits stay on this phone.'
export const ACCESS_EXPIRED = "This phone's sync access expired: your PC hasn't renewed it. Open Brainamon on your PC, then retry. Saved content and queued edits stay here."
export const ACCESS_INVALID = 'This phone could not check its access. Update Brainamon on this phone and on your PC; if it stays, pair again with the new code from your PC. Saved content and queued edits stay here.'
export const ACCESS_INACTIVE = 'Your PC needs an update. It is using older phone access. Update Brainamon on the PC for payment-free sync, then retry. Saved content and queued edits stay here.'
export const ACCESS_DISABLED = 'Your PC disabled this phone’s access. Pair again only with a new code you trust from your PC. Saved content and queued edits stay here.'
export const PC_REPLACED = 'Your PC changed (restored or reinstalled): its access confirmation is signed with a new key. Pair again with the new code from your PC. Saved content and queued edits stay here.'
export const WEBVIEW_OLD = 'Update your browser or Android System WebView to verify phone access. Saved content and queued edits stay here.'
// Why access was refused; Settings > Backup & phones words each one (mirror/phone-state.ts):
//   missing   no confirmation in Drive: the PC removed this phone's access, or has not confirmed it yet
//   expired   the PC has not renewed it (off, offline, signed out of Google, or backing up elsewhere now)
//   replaced  a confirmation with a valid license signed by another PC key: the PC was restored or reinstalled.
//             Advisory only: it never grants access, and only a holder of the library key can write one
//   inactive  the PC's own signed confirmation says its sync license is not active
//   invalid   anything else that does not verify (damaged, another library, a pairing without the PC's key)
//   webview   this browser or WebView cannot check the signatures
export type AccessKind = 'missing' | 'expired' | 'replaced' | 'inactive' | 'invalid' | 'webview'
const KINDS: Record<string, AccessKind> = { [LICENSE_REQUIRED]: 'missing', [ACCESS_EXPIRED]: 'expired', [PC_REPLACED]: 'replaced', [ACCESS_INACTIVE]: 'inactive', [WEBVIEW_OLD]: 'webview' }
export class LicenseRequired extends Error {
  kind: AccessKind
  at: number                    // when the refused confirmation was issued (ms), 0 when unknown
  constructor(message = ACCESS_INVALID, kind?: AccessKind, at = 0) {
    super(message)
    this.kind = kind ?? KINDS[message] ?? 'invalid'
    this.at = at
  }
}
export const issuerKeys = () => typeof __LICENSE_PUBLIC_KEYS__ === 'undefined' ? [] : __LICENSE_PUBLIC_KEYS__
const bytes = (s: string) => {
  if (!/^[A-Za-z0-9_-]+$/.test(s)) throw new LicenseRequired()
  const raw = Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0))
  if (btoa(String.fromCharCode(...raw)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') !== s) throw new LicenseRequired()
  return raw
}

// V2 trusts only the verifier from explicit pairing, with no receipt or key from Drive.
export async function verifyAccess(envelope: { body: string; sig: string }, fp: string, publicKey: string,
                                   now = Date.now() / 1000): Promise<number> {
  try {
    if (!Number.isFinite(now) || !envelope || Object.keys(envelope).sort().join(',') !== 'body,sig'
        || typeof envelope.body !== 'string' || envelope.body.length > 4096
        || typeof envelope.sig !== 'string' || envelope.sig.length > 128) throw new LicenseRequired()
    const pc = await crypto.subtle.importKey('spki', bytes(publicKey), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
    if (!await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, pc, bytes(envelope.sig), new TextEncoder().encode(envelope.body))) throw new LicenseRequired()
    const g = JSON.parse(envelope.body)
    if (!g || Object.keys(g).sort().join(',') !== 'enabled,expires,fp,issued,v'
        || g.v !== 2 || g.fp !== fp || !Number.isSafeInteger(g.issued) || !Number.isSafeInteger(g.expires)
        || g.issued < 0 || g.issued > now || g.expires <= g.issued || g.expires - g.issued > 3600
        || typeof g.enabled !== 'boolean') throw new LicenseRequired()
    if (!g.enabled) throw new LicenseRequired(ACCESS_DISABLED, 'missing', g.issued * 1000)
    if (g.expires <= now) throw new LicenseRequired(ACCESS_EXPIRED, 'expired', g.issued * 1000)
    return g.expires
  } catch (e) {
    if (e instanceof DOMException && e.name === 'NotSupportedError') throw new LicenseRequired(WEBVIEW_OLD)
    if (e instanceof LicenseRequired) throw e
    throw new LicenseRequired()
  }
}
export async function verifyGrant(envelope: { body: string; sig: string }, fp: string, publicKey: string,
                                  issuers = issuerKeys(), now = Date.now() / 1000): Promise<number> {
  try {
    if (!envelope || typeof envelope.body !== 'string' || envelope.body.length > 12000) throw new LicenseRequired()
    const pc = await crypto.subtle.importKey('spki', bytes(publicKey), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
    // checked first, required last: a confirmation another PC key signed is still read, to tell a restored PC from damage
    const signed = await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, pc, bytes(envelope.sig), new TextEncoder().encode(envelope.body))
    const g = JSON.parse(envelope.body)
    if (g.v !== 1 || g.fp !== fp || !Number.isSafeInteger(g.issued) || !Number.isSafeInteger(g.expires)
        || g.issued > now || g.expires < g.issued || g.expires - g.issued > 3600
        || typeof g.license !== 'string' || g.license.length > 8192) throw new LicenseRequired()
    if (!g.license && g.expires === g.issued) throw new LicenseRequired(signed ? ACCESS_INACTIVE : ACCESS_INVALID)
    if (g.expires === g.issued) throw new LicenseRequired()
    const [prefix, body, sig, extra] = g.license.split('.')
    if (prefix !== 'BRAINAMON1' || extra !== undefined) throw new LicenseRequired()
    const signature = bytes(sig), payload = bytes(body)
    if (signature.length !== 64) throw new LicenseRequired()
    let valid = false
    for (const hex of issuers) {
      if (!/^[0-9a-f]{64}$/i.test(hex)) continue
      const key = await crypto.subtle.importKey('raw', Uint8Array.from(hex.match(/../g)!, x => parseInt(x, 16)), 'Ed25519', false, ['verify'])
      if (await crypto.subtle.verify('Ed25519', key, signature, new TextEncoder().encode(`${prefix}.${body}`))) { valid = true; break }
    }
    const p = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payload))
    if (!valid || p.v !== 1 || p.ed !== 'cloud' || ![null, '', undefined].includes(p.exp)
        || ![['id', 128], ['to', 200], ['email', 320], ['iss', 10]].every(([field, limit]) => typeof p[field] === 'string' && p[field].length <= Number(limit) && (field === 'email' || p[field].trim()))
        || !/^\d{4}-\d{2}-\d{2}$/.test(p.iss) || new Date(p.iss).toISOString().slice(0, 10) !== p.iss) throw new LicenseRequired()
    if (!signed) throw new LicenseRequired(PC_REPLACED, 'replaced', g.issued * 1000)
    if (g.expires <= now) throw new LicenseRequired(ACCESS_EXPIRED, 'expired', g.issued * 1000)
    return g.expires
  } catch (e) {
    if (e instanceof DOMException && e.name === 'NotSupportedError') throw new LicenseRequired(WEBVIEW_OLD)
    if (e instanceof LicenseRequired) throw e
    throw new LicenseRequired()
  }
}

// When this pairing last had its access confirmed: Settings > Backup & phones says "Last access 15:05" once the PC removes
// it, and tells a removal (access before) from a first confirmation still on its way. Saved at most once a minute;
// unavailable storage keeps no history, and the phone then says less.
const ACCESS_SEEN = 'bp-access'
export interface AccessSeen { f: string; at: number }
let seen: AccessSeen | null = null
export function noteAccess(f: string, now = Date.now()): void {
  if (seen && seen.f === f && now - seen.at < 60_000) return
  seen = { f, at: now }
  try { localStorage.setItem(ACCESS_SEEN, JSON.stringify(seen)) } catch { /* not kept: the phone says less */ }
}
export function lastAccess(f: string): AccessSeen | null {
  try {
    const v = JSON.parse(localStorage.getItem(ACCESS_SEEN) || 'null') as AccessSeen | null
    return v && v.f === f && Number.isFinite(v.at) ? v : null
  } catch { return null }
}
