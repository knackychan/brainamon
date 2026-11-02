// Pairing and the Google sign-in on the phone (PLAN.md "Auth and keys", Phase 4 step 1).
//
// Pairing: desktop Settings > Backup & phones > Add a phone shows a QR of <phone page>#pair=<code>; the phone's
// camera opens it, and the code (base64url JSON, server/routes/cloud.py pair) is kept here:
//   {v, k: mirror key, c: Google web client id, e: Google account, f: key fingerprint,
//    p?: the PC's Google Cloud project number (tells a phone sign-in app of another project),
//    t?, tx?: one-time key and expiry of the AI keys the PC left in Drive, d?: Drive base URL,
//    x?: {provider: AI base URL} (development only, fakes)}
// The fragment never leaves the phone (browsers do not send it), and the page drops it at once.
// The link never carries an API key: once Drive answers, takeKeys collects the ticked keys from
// the sealed file the PC left (mirror.py pair_drop), deletes it and forgets `t`, so a copy of the
// link left in a clipboard or a chat opens no AI account. Older links (v 1) carried `ai` itself.
// The keys stay in `ai` here until Unpair or "Forget AI keys" (forgetKeys).
//
// Sign-in: Google's browser token flow (OAuth 2.0 for client-side web apps, response_type=token,
// scope drive.appdata). The page goes to Google and comes back with #access_token=...; the token
// lasts about an hour, and a silent round trip (prompt=none) renews it when the app opens. With a
// development Drive (`d`) there is no sign-in.
//
// In the Android app (native.ts, Phase 6) the pairing and the token live in Keystore-encrypted
// storage, the QR is scanned from inside the app (acceptLink), and Google's Android sign-in hands
// over the token (no redirect, no web client id: Google knows the app by its package and signature).
//
// The account: Google may sign in an account it remembers without showing anything (after a reset
// the app reused the old one). So a token is only used once the user confirmed its account on this
// phone (`g`, mirror/status.ts accountCheck): Connect reads the account (Drive about), and the More
// screen asks "Use X?" first, or says the PC uploads to another account. Silent renewals ask for `g`.
import { googleToken, isApp, secrets, secretsSaved } from '../native'
import { MirrorKey, PAIR_LOGICAL, pairDropName } from './crypto'
import { reconnectGate } from './gate'
import { Drive } from './drive'
import { projectOf } from './diagnose'
import { accountConfirmed } from './status'
import { markResend } from './resend'
import type { PhoneKit } from './recovery-envelope'

// x: development only, stand-in AI endpoints (server/dev_drive.py) instead of the providers' own
// solo: no PC (plans/08-phone-solo.md): the phone made the key itself, its change files in Drive are
// the library, and the AI keys were typed on the phone
// g: the Google account the user confirmed on this phone (never in a pairing code)
// recovery: the setup this phone made (solo), whether its recovery file was checked against Drive, and when the app saved
// that file (ms; a browser download is never confirmed, so it is not recorded)
export interface Pairing { v: number; k: string; c: string; e: string; f: string; l?: string; accessVersion?: 2; p?: string; ai: Record<string, string>; t?: string; tx?: number; d?: string; x?: Record<string, string>; at: number; solo?: boolean; g?: string; recovery?: { kit: PhoneKit; verified: boolean; saved?: number } }
interface Token { access: string; exp: number }

const verified = new Map<string, string>()
export const devPairing = import.meta.env?.DEV === true
export function devEndpoint(value: unknown): boolean {
  if (!devPairing || typeof value !== 'string') return false
  try { const u = new URL(value); return u.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname) && !u.username && !u.password } catch { return false }
}
function valid(p: Pairing): boolean {
  return !!p && p.v === 2 && typeof p.k === 'string' && /^[A-Za-z0-9_-]{43}$/.test(p.k) && typeof p.f === 'string' && /^[a-f0-9]{12}$/.test(p.f)
    && (!('l' in p) || typeof p.l === 'string' && /^[A-Za-z0-9_-]{122}$/.test(p.l))
    && (!('accessVersion' in p) || p.accessVersion === 2)
    && ['c', 'e'].every(k => typeof p[k as 'c' | 'e'] === 'string' && p[k as 'c' | 'e'].length <= 512)
    && (!('d' in p) || devEndpoint(p.d)) && (!('x' in p) || devPairing && !!p.x && typeof p.x === 'object' && Object.values(p.x).every(devEndpoint))
    && (!p.t || typeof p.t === 'string' && /^[A-Za-z0-9_-]{43}$/.test(p.t) && typeof p.tx === 'number' && Number.isFinite(p.tx))
}
export async function validateStoredPairing() {
  try { const p = JSON.parse(secrets.get('bp-pair') || 'null') as Pairing; if (valid(p)) { const k = await MirrorKey.fromText(p.k); if (k.fingerprint === p.f) verified.set(p.k, p.f) } } catch { /* retained for recovery, never used */ }
}

const PAIR = 'bp-pair', TOKEN = 'bp-gtoken', DEVICE = 'bp-device', OAUTH = 'bp-oauth', TRIED = 'bp-oauth-tried', REQUEUE = 'bp-requeue'
const AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
const SCOPE = 'https://www.googleapis.com/auth/drive.appdata'
export const GOOGLE_DRIVE = 'https://www.googleapis.com'

const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private window */ } },
  del(k: string) { try { localStorage.removeItem(k) } catch { /* private window */ } },
}
const ss = {
  get(k: string) { try { return sessionStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { sessionStorage.setItem(k, v) } catch { /* private window */ } },
  del(k: string) { try { sessionStorage.removeItem(k) } catch { /* private window */ } },
}

function b64json<T>(s: string): T {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4))
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(b, c => c.charCodeAt(0)))) as T
}

export function pairing(): Pairing | null {
  try { const p = JSON.parse(secrets.get(PAIR) || 'null') as Pairing | null; return p && valid(p) && verified.get(p.k) === p.f ? p : null } catch { return null }
}

const durableAccess = new Set<string>()
function savePairing(p: Pairing) {
  // A settings form may hold a snapshot from before the first v2 Drive call.
  // Updating keys/account must not erase the same trusted pairing's watermark.
  const live = pairing()
  if (live && live.k === p.k && live.l === p.l && live.accessVersion === 2) p.accessVersion = 2
  secrets.set(PAIR, JSON.stringify(p))
}
export async function confirmAccessV2(pair: Pairing): Promise<void> {
  const identity = `${pair.k}:${pair.l}`
  const live = pairing()
  if (!live || `${live.k}:${live.l}` !== identity) throw new Error('Pairing changed during access confirmation.')
  if (durableAccess.has(identity) && live.accessVersion === 2) return
  secrets.set(PAIR, JSON.stringify({ ...live, accessVersion: 2 }))
  await secretsSaved()                 // never grant v2 when the anti-downgrade state could not be saved
  durableAccess.add(identity)
}

// this phone's id in its change files (the PC records up to when each phone's changes are in)
export function deviceId(): string {
  let d = ls.get(DEVICE)
  if (!d) { d = 'p' + [...crypto.getRandomValues(new Uint8Array(5))].map(b => b.toString(16).padStart(2, '0')).join(''); ls.set(DEVICE, d) }
  return d
}

export function forget() { reconnectGate(); secrets.set(PAIR, null); secrets.set(TOKEN, null); ss.del(OAUTH) }

// keep the phone paired, drop its AI keys (Wiskit, Smart search and Synthesize then wait for a new pairing)
export function forgetKeys(p: Pairing) {
  p.ai = {}
  delete p.t; delete p.tx
  savePairing(p)
}

// the AI keys the PC left in Drive for this pairing: opened with the link's one-time key, kept with
// the pairing, then deleted from Drive. Returns a note for the More screen, or ''. Not found yet:
// tried again at the next refresh until the PC's expiry, then given up.
export async function takeKeys(p: Pairing, drive: Drive): Promise<string> {
  if (!p.t) return ''
  const revision = () => {
    const raw = secrets.get(PAIR)
    if (!raw) return raw
    try {
      const saved = JSON.parse(raw) as Pairing
      delete saved.accessVersion
      return JSON.stringify(saved)
    } catch { return raw }
  }
  const original = revision()
  const owns = () => revision() === original
  const done = (note: string) => { if (!owns()) return 'Pairing changed; the previous key transfer was cancelled.'; delete p.t; delete p.tx; savePairing(p); return note }
  const expired = () => typeof p.tx !== 'number' || !Number.isFinite(p.tx) || p.tx <= Date.now() / 1000
  const expiryNote = 'The AI keys from the pairing code expired before this phone collected them. Pair again from the PC with a key ticked.'
  if (expired()) return done(expiryNote)
  const one = await MirrorKey.fromText(p.t)
  if (!owns()) return 'Pairing changed; the previous key transfer was cancelled.'
  const f = await drive.find(await pairDropName(one, p.tx ?? 0))
  if (!owns()) return 'Pairing changed; the previous key transfer was cancelled.'
  if (!f) {
    return p.tx && Date.now() / 1000 > p.tx ? done('The AI keys from the pairing code expired before this phone collected them. Pair again from the PC with a key ticked.') : ''
  }
  const got = await one.openJSON<{ ai?: Record<string, unknown> }>(PAIR_LOGICAL, await drive.get(f.id))
  if (!owns()) return 'Pairing changed; the previous key transfer was cancelled.'
  if (expired()) return done(expiryNote)
  const ai: Record<string, string> = {}
  for (const [k, v] of Object.entries(got.ai ?? {})) if (typeof v === 'string' && v) ai[k] = v
  if (expired()) return done(expiryNote)
  p.ai = { ...(p.ai || {}), ...ai }
  const note = done(Object.keys(ai).length ? 'AI keys received.' : '')
  try { await drive.remove(f.id) } catch { return note + ' Remote deletion could not be confirmed; copied transfers cannot be revoked.' }
  return note
}

// what the page was opened with: a pairing link, or Google coming back. Runs before the router
// reads location.hash. Returns a note for the More screen, or ''.
export async function takeFromUrl(): Promise<string> {
  const h = location.hash
  if (h.startsWith('#pair=')) {
    history.replaceState(null, '', location.pathname + '#/backup')     // More when the code is refused (state.svelte.ts backupHere)
    const note = await acceptCode(h.slice(6))
    return note
  }
  const q = new URLSearchParams(h.startsWith('#/') ? '' : h.slice(1))
  if (q.has('state') && (q.has('access_token') || q.has('error'))) {
    const want = ss.get(OAUTH)
    let back = '#/lib', note = ''
    try { back = JSON.parse(want || '{}').back || back } catch { /* default */ }
    if (!want || q.get('state') !== JSON.parse(want).state) note = 'The Google sign-in did not match this page; try again.'
    else if (q.get('access_token')) {
      secrets.set(TOKEN, JSON.stringify({ access: q.get('access_token'), exp: Date.now() + (+(q.get('expires_in') || 3600) - 60) * 1000 }))
      ss.del(TRIED)
    } else note = q.get('error') === 'access_denied' ? 'Google Drive was not connected.' : ''
    ss.del(OAUTH)
    history.replaceState(null, '', location.pathname + back)
    await secretsSaved()
    return note
  }
  return ''
}

// keep a pairing code (the part after #pair=); a note for the More screen
async function acceptCode(code: string): Promise<string> {
  try {
    const p = b64json<Pairing>(code)
    if (code.length > 12000 || !valid(p)) throw new Error('invalid pairing')
    if (typeof p.l !== 'string' || !/^[A-Za-z0-9_-]{122}$/.test(p.l)) throw new Error('licensed pairing required')
    const key = await MirrorKey.fromText(p.k)
    if (key.fingerprint !== p.f) throw new Error('wrong fingerprint')
    if ('ai' in p && !devPairing) throw new Error('legacy key payload')
    p.ai = p.ai && typeof p.ai === 'object' ? p.ai : {}
    delete p.solo
    delete p.g
    delete p.accessVersion             // QR metadata is not proof that v2 was authenticated
    const old = pairing()
    const quarantined = secrets.get(PAIR)
    if (!old && quarantined) {
      if (!globalThis.confirm('Replace the quarantined pairing? Existing offline content stays on this phone.')) return 'Pairing cancelled.'
      secrets.set('bp-pair-quarantine', quarantined)
    }
    // the same account: the same Google account, OAuth client, project and Drive endpoint; the same library besides: a
    // PC pairing whose signer or library key is this one (a removal or a restore gives a new key, the signer stays)
    const fold = (s?: string) => (s ?? '').toLowerCase()
    const sameAccount = !!old && (['e', 'c', 'p', 'd'] as const).every(k => fold(old[k]) === fold(p[k]))
    const same = !!old && !old.solo && sameAccount && (old.l === p.l || old.k === p.k)
    if ((old?.solo || old && !same) && !globalThis.confirm(old.solo ? 'Send this phone’s library to this PC? Only continue if you trust this PC and its pairing code.' : 'Replace this phone’s paired PC and account?')) return 'Pairing cancelled.'
    verified.set(p.k, p.f)
    // a phone used without a PC sends its whole library to the PC it now pairs with (MirrorSource.ready)
    if (old?.solo) localStorage.setItem(REQUEUE, '1')  // refuse pairing if its retained library cannot be queued
    // a new key or signer: what the PC has not acknowledged goes again (mirror/resend.ts); the same link scanned again
    // keeps a marker still waiting. The marker is kept before the pairing, so a failure leaves the old pairing.
    else if (!old || old.f !== p.f || old.l !== p.l) markResend(p)
    // the confirmed account stays only for the same library and account; else it is asked for again
    secrets.set(PAIR, JSON.stringify({ ...p, at: Date.now(), ...(same && old.g ? { g: old.g } : {}),
      ...(old?.k === p.k && old.l === p.l && old.accessVersion === 2 ? { accessVersion: 2 } : {}) }))
    if (!same) { secrets.set(TOKEN, null); ss.del(OAUTH) }
    ss.set('bp-pair-setup', '1')
    if (same && (old.f !== p.f || old.l !== p.l) && old.g) return `Paired again. Kept your Google sign-in (${old.g}).`
    return same ? 'Paired again with the same PC.' : 'Paired with your PC.'
  } catch {
    return 'That pairing code could not be read. Show the QR on the PC again.'
  }
}

// ── without a PC (plans/08-phone-solo.md) ────────────────────────────────────
// A new key, or the recovery code of a library already in Drive (another phone, or this one before a
// reset): the same 43-character text as a pairing's `k`. `dev`: the stand-in Drive and AI of
// server/dev_drive.py (development only, the page on 127.0.0.1:18765).
export function newKeyText(): string {
  const a = crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...a)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
export async function startSolo(keyText: string, dev?: { d: string; x: Record<string, string>; ai: Record<string, string> }, recoveryAccount = ''): Promise<void> {
  reconnectGate()
  if (dev && (!devEndpoint(dev.d) || !Object.values(dev.x).every(devEndpoint))) throw new Error('Development endpoints require a development build and loopback addresses.')
  const k = keyText.trim()
  const key = await MirrorKey.fromText(k)          // throws on a wrong code
  const previous = pairing()
  if (recoveryAccount && (!previous?.solo || !token(previous) || previous.g?.toLowerCase() !== recoveryAccount.toLowerCase())) throw new Error('The Google account changed. Connect the recovery account again.')
  verified.set(k, key.fingerprint)
  const p: Pairing = { v: 2, k, c: '', e: '', f: key.fingerprint, ai: dev?.ai ?? {}, at: Date.now(), solo: true }
  if (recoveryAccount) { p.g = recoveryAccount; p.e = recoveryAccount }
  if (dev) { p.d = dev.d; p.x = dev.x }
  secrets.set(PAIR, JSON.stringify(p))
  if (!recoveryAccount) secrets.set(TOKEN, null)
}
// the AI keys typed on the phone (solo): kept with the pairing, in the app's encrypted storage
export function setAiKeys(p: Pairing, ai: Record<string, string>) {
  p.ai = {}
  for (const [k, v] of Object.entries(ai)) if (v.trim()) p.ai[k] = v.trim()
  savePairing(p)
}
// after a solo phone paired with a PC: every change goes again, under the PC's key (source/mirror.ts ready). The
// marker stays until the journal is saved for it; then takeRequeue removes it.
export function requeueWaiting(): boolean {
  return localStorage.getItem(REQUEUE) === '1'
}

// once, after a solo phone paired with a PC: true means send every change again, under the PC's key
export function takeRequeue(): boolean {
  const on = requeueWaiting()
  if (on) localStorage.removeItem(REQUEUE)
  return on
}

// a pairing link scanned or pasted in the app: '' when it is not one, else the note
export async function acceptLink(text: string): Promise<string> {
  const i = text.indexOf('#pair=')
  return i < 0 ? '' : acceptCode(text.slice(i + 6).trim())
}

// the Google token, whichever account it is for
function heldToken(): string | null {
  try {
    const t = JSON.parse(secrets.get(TOKEN) || 'null') as Token | null
    return t && t.exp > Date.now() ? t.access : null
  } catch { return null }
}
// the token every Drive call uses: none until the user confirmed its account on this phone
export function token(p: Pairing): string | null {
  if (!valid(p) || verified.get(p.k) !== p.f) return null
  if (p.d && devEndpoint(p.d)) return 'dev'                      // a development Drive takes any token
  return accountConfirmed(p) ? heldToken() : null
}
// a token is in, but its account is not confirmed yet (the More screen asks)
export const unconfirmedToken = (p: Pairing) => !accountConfirmed(p) && !!heldToken()
// which account the held token signed in (Drive about), confirmed or not
export function whoSignedIn(p: Pairing): Promise<string> {
  return new Drive(p.d || GOOGLE_DRIVE, heldToken, dropToken).about()
}
// the Google Cloud project of the held token's sign-in app (Google's token info; the app data folder belongs to
// the project), '' when it cannot be read
export async function tokenProject(): Promise<string> {
  const t = heldToken()
  if (!t) return ''
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 8000)
  try {
    const r = await fetch('https://oauth2.googleapis.com/tokeninfo', { method: 'POST', signal: ctl.signal,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ access_token: t }) })
    const d = await r.json() as { azp?: string; aud?: string }
    return projectOf(String(d.azp || d.aud || ''))
  } catch { return '' } finally { clearTimeout(timer) }
}
export function confirmAccount(p: Pairing, account: string) {
  p.g = account
  savePairing(p)
}
export function dropToken() { secrets.set(TOKEN, null) }
// Disconnect backup (Backup & phones, the phone without a PC), a refused account and Change account in a browser:
// the token and the confirmed account go, and no silent sign-in brings them back this session; the next Connect
// shows Google's account chooser
export function disconnectDrive(p: Pairing) {
  reconnectGate()
  secrets.set(TOKEN, null)
  ss.del(OAUTH)
  ss.set(TRIED, '1')
  delete p.g
  savePairing(p)
}

// go to Google; `silent` asks without showing anything (works while the user's Google session
// and consent last) and is tried once per app start, for the confirmed account only. In the browser
// the page leaves for Google and comes back (takeFromUrl); in the app Google's sheet answers here,
// and true means a token is in. `choose`: show the account chooser (the app shows it anyway while no
// account is confirmed; the browser always does when it is not silent).
export async function signIn(p: Pairing, silent = false, choose = false): Promise<boolean> {
  if (isApp && !p.d) {
    const original = secrets.get(PAIR)
    if (silent) ss.set(TRIED, '1')
    const t = await googleToken(silent, silent ? { account: p.g } : { choose: choose || !p.g })
    if (secrets.get(PAIR) !== original) throw new Error('Pairing changed; Google sign-in was cancelled.')
    secrets.set(TOKEN, JSON.stringify({ access: t.token, exp: Date.now() + (t.expiresIn - 60) * 1000 }))
    await secretsSaved()
    return true
  }
  if (!p.c) throw new Error('The PC has no Google sign-in app for the phone yet (Settings > Backup & phones).')
  const state = [...crypto.getRandomValues(new Uint8Array(12))].map(b => b.toString(16).padStart(2, '0')).join('')
  ss.set(OAUTH, JSON.stringify({ state, back: location.hash.startsWith('#/') ? location.hash : '#/lib' }))
  if (silent) ss.set(TRIED, '1')
  const q = new URLSearchParams({
    client_id: p.c, redirect_uri: location.origin + location.pathname, response_type: 'token', scope: SCOPE,
    include_granted_scopes: 'true', state, prompt: silent ? 'none' : 'select_account consent',
  })
  if (p.g || p.e) q.set('login_hint', p.g || p.e)
  location.assign(`${AUTH}?${q}`)
  return false
}
export const triedSilent = () => ss.get(TRIED) === '1'
