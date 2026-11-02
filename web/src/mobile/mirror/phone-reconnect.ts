// Keep this phone's library after its Drive key was lost (docs/superpowers/plans/2026-10-29-phone-reconnect.md).
// The phone has no manifest: its proof is the newest batch it sent (mirror/changes.ts `chg`, `sentAt`) and, from
// this plan on, the publish record kv `solo_publish` written at every solo flush (the phone's cloud_epoch and
// manifest row). The checks here read Drive and the journal only; the commit (reconnectPhone, sub-plan 02) writes
// the pairing and the journal, never Drive. Names and formats shared with Python: tests/fixtures/phone_reconnect.json.
import { changes as db, kv } from '../store'
import { secrets, secretsSaved } from '../native'
import type { Changes, ChangeEntry } from './changes'
import { CHANGE_PREFIX, MirrorKey, MirrorKeyError } from './crypto'
import type { Drive } from './drive'
import { cloudChanging, cloudCheckpoint, cloudRevision, reconnectGate, setReconnecting } from './gate'
import { pairing, token, validateStoredPairing, type Pairing } from './pairing'
import { RECOVERY_LIMIT, type PhoneKit } from './recovery-envelope'

export const PUBLISH_KEY = 'solo_publish'
export const SOLO_NAME = /^solo-[0-9a-f]{32}-[0-9a-f]{32}$/
// one record per key fingerprint: after a key loss the phone flushes under its new key at the next refresh
export interface SoloPublish { fingerprint: string; name: string; id: string; at: number; n: number; sig: string }
export interface Batch { name: string; id?: string; at: number; n: number; sig?: string }

export const ELIGIBLE = "This phone matches its latest backup in Drive. You can keep its content and reconnect it instead of restoring on an empty phone."
export const REFUSALS = {
  paired_pc: 'This phone is paired with a PC. Desktop libraries are restored on the PC; reconnect is for a phone used without a PC.',
  not_connected: 'This phone is not connected to Google Drive, so it cannot be checked against its backup. Restore on an empty phone works without it.',
  no_upload: 'This phone has no record of a backup in Drive, so it cannot be reconnected. Save its recovery code and back it up, or restore on an empty phone.',
  other_library: 'This phone was last backed up with a different key, so it cannot be reconnected to this backup. Restore on an empty phone instead.',
  not_latest: 'The latest backup recorded on this phone is missing from Drive or does not open with this key, so it cannot be reconnected. Restore on an empty phone instead.',
  busy: 'Wait for the current sync or connection to finish, then find the backup again.',
  interrupted: 'Reconnect was interrupted. The previous pairing was kept in a backup; find the backup again before retrying.',
} as const
// a phone recovery file pasted in the code field: the screen offers "Use recovery file", which switches the method
export const KIT_IN_CODE = 'This is a recovery file. Open it with File under Unlock with.'
export type Reason = keyof typeof REFUSALS | 'eligible'
export interface Eligibility { ok: boolean; reason: Reason; message: string; batch?: Batch & { id: string } }
const refuse = (reason: keyof typeof REFUSALS): Eligibility => ({ ok: false, reason, message: REFUSALS[reason] })

const enc = new TextEncoder()
export async function sha256hex(data: Uint8Array): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', data as Uint8Array<ArrayBuffer>))].map(b => b.toString(16).padStart(2, '0')).join('')
}

// after a solo flush: what went up, so a later reconnect can prove this phone published it
export async function recordPublish(key: MirrorKey, name: string, id: string, doc: { at: number; changes: unknown[] }): Promise<void> {
  const records = (await kv.get<Record<string, SoloPublish>>(PUBLISH_KEY)) ?? {}
  records[key.fingerprint] = { fingerprint: key.fingerprint, name, id, at: doc.at, n: doc.changes.length, sig: await sha256hex(enc.encode(JSON.stringify(doc))) }
  await kv.set(PUBLISH_KEY, records)
}

// the newest batch in the journal under `prefix` (or a legacy chg- batch): its name, time and change count
export function latestBatch(list: ChangeEntry[], prefix: string): Batch | null {
  const sent = list.filter(e => e.state === 'sent' && !!e.chg && (e.chg.startsWith(prefix) || e.chg.startsWith(CHANGE_PREFIX)))
  if (!sent.length) return null
  const at = Math.max(...sent.map(e => e.sentAt ?? 0))
  const name = sent.find(e => (e.sentAt ?? 0) === at)!.chg!
  return { name, at, n: sent.filter(e => e.chg === name).length }
}

// sent under the key this phone reconnected away from (`from` is that key's solo prefix): they go again under the
// recovered one. Only that prefix: what went up under any other key is left alone, so a phone that never
// reconnects keeps its journal, and the evidence a later reconnect needs, exactly as today.
export function strays(list: ChangeEntry[], from: string): ChangeEntry[] {
  return list.filter(e => e.state === 'sent' && !!e.chg && e.chg.startsWith(from)
    && !(e.op === 'canvas' && e.canvasLocal && e.canvasLocal.status !== 'pending'))
}

// idempotent: reconnectPhone runs it after installing the key, and MirrorSource.ready runs it at the next solo start
// while the marker kv `solo_strays` is there (sub-plan 02), so an interrupted reconnect finishes itself
export async function requeueStrays(changes: Changes, from: string): Promise<number> {
  await changes.load()
  const out = strays(changes.list, from)
  for (const e of out) {
    const next: ChangeEntry = { ...e, state: 'queued' }
    delete next.sentAt; delete next.chg
    await db.put(next)
    e.state = 'queued'; delete e.sentAt; delete e.chg
  }
  return out.length
}

// the key a recovery material carries: a 43-character code, a pairing link (#pair=), or the text of this phone's
// exported recovery file (mirror/recovery.ts); the same set library/recovery.py import_key accepts
export async function keyFromMaterial(text: string): Promise<string> {
  let t = text.trim()
  if (t.length > RECOVERY_LIMIT) throw new Error('Recovery files must be smaller than 32 KiB.')
  let fingerprint = ''
  if (t.startsWith('{')) {
    let v: { format?: unknown; version?: unknown; key?: unknown; fingerprint?: unknown }
    try { v = JSON.parse(t) } catch { throw new Error('Unsupported recovery file.') }
    if (v.format === 'brainamon-phone-backup-kit') throw new Error(KIT_IN_CODE)
    if (v.format !== 'brainamon-phone-recovery' || v.version !== 1 || typeof v.key !== 'string') throw new Error('Unsupported recovery file.')
    t = v.key.trim()
    if (typeof v.fingerprint === 'string') fingerprint = v.fingerprint
  } else if (t.includes('#pair=')) {
    t = t.slice(t.indexOf('#pair=') + 6).trim()
    if (t.length !== 43) {
      try {
        const b = atob(t.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (t.length % 4)) % 4))
        t = String((JSON.parse(new TextDecoder().decode(Uint8Array.from(b, c => c.charCodeAt(0)))) as { k?: unknown }).k ?? '')
      } catch { throw new Error('Use the original recovery code, a pairing link or the text of an exported phone recovery file.') }
    }
  }
  if (!/^[A-Za-z0-9_-]{43}$/.test(t)) throw new Error('Use the original recovery code, a pairing link or the text of an exported phone recovery file.')
  const key = await MirrorKey.fromText(t)
  if (fingerprint && key.fingerprint !== fingerprint) throw new Error('Phone recovery key does not match its fingerprint.')
  return t
}

// Reads only: does this phone's latest backup live in Drive under `key`? (master plan, contract 1)
export async function reconnectCheck(key: MirrorKey, drive: Drive, changes: Changes): Promise<Eligibility> {
  if (cloudChanging()) return refuse('busy')
  const pair = pairing()
  if (!pair) return refuse('not_connected')
  if (!pair.solo) return refuse('paired_pc')
  await changes.load()
  const prefix = await key.soloPrefix()
  const records = (await kv.get<Record<string, SoloPublish>>(PUBLISH_KEY)) ?? {}
  const record = records[key.fingerprint]
  const batch: Batch | null = record ?? latestBatch(changes.list, prefix)
  if (!batch) return refuse(changes.list.some(e => e.state === 'sent' && !!e.chg) ? 'other_library' : 'no_upload')
  if (!record && !(batch.name.startsWith(prefix) || batch.name.startsWith(CHANGE_PREFIX))) return refuse('other_library')
  const file = (await drive.list()).find(f => f.name === batch.name)
  if (!file || (record?.id && file.id !== record.id)) return refuse('not_latest')
  let plain: Uint8Array
  try { plain = await key.open(batch.name, await drive.getRecovered(file.id, key)) }
  catch (e) { if (e instanceof MirrorKeyError) return refuse('not_latest'); throw e }
  let doc: { at?: unknown; changes?: unknown }
  try { doc = JSON.parse(new TextDecoder().decode(plain)) } catch { return refuse('not_latest') }
  if (doc.at !== batch.at || !Array.isArray(doc.changes) || doc.changes.length < batch.n) return refuse('not_latest')
  if (record && await sha256hex(plain) !== record.sig) return refuse('not_latest')
  return { ok: true, reason: 'eligible', message: ELIGIBLE, batch: { ...batch, id: file.id } }
}

// kv: a reconnect installed its key (or was about to) and the strays were not back in the queue yet
export const STRAYS_KEY = 'solo_strays'
export interface StraysMarker { from: string; to: string }

// MirrorSource.ready, every solo start: finish an interrupted reconnect. The marker is applied only when the
// pairing it belongs to is the one in use; otherwise it stays for the next successful reconnect to rewrite.
export async function finishReconnect(changes: Changes, key: MirrorKey): Promise<number> {
  const marker = await kv.get<StraysMarker>(STRAYS_KEY)
  if (!marker || marker.to !== await key.soloPrefix()) return 0
  const n = marker.from === marker.to ? 0 : await requeueStrays(changes, marker.from)
  await kv.del(STRAYS_KEY)
  return n
}

// Keep this phone: install the recovered key for the backup its latest batch matches. Writes only a backup of the
// current pairing, the marker, the pairing, and the journal entries that went up under the old key; never Drive.
export async function reconnectPhone(pair: Pairing, drive: Drive, changes: Changes, keyText: string, account: string, kit?: PhoneKit): Promise<void> {
  reconnectGate()
  if (cloudChanging()) throw new Error(REFUSALS.busy)
  setReconnecting(true)
  const revision = cloudRevision()
  let wrote = false
  try {
    const key = await MirrorKey.fromText(keyText.trim())
    const same = (p: Pairing | null): p is Pairing => !!p?.solo && p.k === pair.k && !!token(p) && (p.g ?? '').toLowerCase() === account.toLowerCase()
    const live = pairing()
    if (!same(live)) throw new Error('The phone library or Google account changed. Reconnect and retry recovery.')
    const check = await reconnectCheck(key, drive, changes)
    cloudCheckpoint(revision)
    if (!check.ok) throw new Error(check.message)
    if (!same(pairing())) throw new Error('The phone library or Google account changed. Reconnect and retry recovery.')
    // Everything above only read. The first write backs up the pairing this phone holds now (its key included).
    const stamp = Date.now()
    secrets.set(`bp-pair-before-reconnect-${stamp}`, JSON.stringify(live))
    await secretsSaved()
    wrote = true          // an extra backup is harmless; from the marker on, a failure is reported as interrupted
    // A retry in this session must finish the previous marker before replacing it.
    await finishReconnect(changes, await MirrorKey.fromText(live.k))
    // the marker MirrorSource.ready applies at the next start if the app dies before the strays went back in the queue
    const from = await (await MirrorKey.fromText(live.k)).soloPrefix(), to = await key.soloPrefix()
    await kv.set(STRAYS_KEY, { from, to } satisfies StraysMarker)
    const next: Pairing = { ...live, k: keyText.trim(), f: key.fingerprint, at: stamp, solo: true, e: account, g: account }
    delete next.t; delete next.tx
    if (kit) next.recovery = { kit, verified: false }; else delete next.recovery
    secrets.set('bp-pair', JSON.stringify(next))
    await secretsSaved()
    await validateStoredPairing()          // this session now answers pairing() with the recovered key
    // from here the old Drive instance refuses every call (its pairing identity changed); the screen reloads after this
    if (from !== to) await requeueStrays(changes, from)
    await kv.del(STRAYS_KEY)
  } catch (e) {
    if (wrote) throw new Error(REFUSALS.interrupted)
    throw e
  } finally {
    setReconnecting(false)
  }
}
