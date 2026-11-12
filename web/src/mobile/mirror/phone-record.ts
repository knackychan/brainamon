// D13: this phone's own record in the app data folder, so the PC's Phones list (server/sync.py _read_phones,
// BackupPhonesPage.svelte) names it and says when it last synced. The other side is library/mirror.py seal_phone and
// open_phone: the Drive name `ph-` + key.name('phones/<device>') is also the logical name the sealing authenticates, and
// the body is {"device", "name", "seen", "v": 1} with `seen` in ms. A paired phone writes it after a complete read of
// the library (source/mirror.ts), at most every 30 minutes (the PC shows the last reported sync, not live connection
// status) and at once when its name or its pairing changes, replacing it in place. Unpair removes it, best effort
// within 3 s; Remove all phones on the PC removes the old key's records. A solo phone writes none.
import { kv } from '../store'
import type { MirrorKey } from './crypto'
import { DriveError, type Drive } from './drive'

export const PHONE_PREFIX = 'ph-'
export const PHONE_MAX = 4096                    // library/mirror.py PHONE_MAX
export const NAME_MAX = 60                       // what open_phone keeps
export const RECORD_EVERY = 30 * 60_000
export const DROP_WITHIN = 3_000
const STATE = 'phone_record'

// kv `phone_record`: the record this phone last wrote (the pairing's fingerprint, the device, its Drive id, the name, when)
export interface RecordState { f: string; d: string; id: string; name: string; at: number }
export interface RecordPairing { f: string; solo?: boolean }
export type Synced = 'solo' | 'fresh' | 'written' | 'stopped'

let chain: Promise<unknown> = Promise.resolve()  // one write at a time: a read and a look can end together
let writing: AbortController | null = null        // the write in flight, which Unpair stops
let dropping = ''                                 // the pairing Unpair is removing: no write starts for it until a reload

// one line of at most 60 characters, counted as Python counts them (code points), so the PC reads back what was sealed
export function cleanName(name: string): string {
  const line = name.replace(/[\p{Cc}\s]+/gu, ' ').trim()
  return [...line].slice(0, NAME_MAX).join('').trim() || 'Phone'
}

export async function phoneRecordName(key: MirrorKey, device: string): Promise<string> {
  return PHONE_PREFIX + await key.name('phones/' + device)
}

// (Drive name, sealed record), as seal_phone makes them
export async function sealPhoneRecord(key: MirrorKey, device: string, name: string, seen: number): Promise<[string, Uint8Array]> {
  const logical = await phoneRecordName(key, device)
  const body = JSON.stringify({ device, name: cleanName(name), seen: Math.trunc(seen), v: 1 })   // _json's sorted order
  return [logical, await key.seal(logical, new TextEncoder().encode(body))]
}

// {device, name, seen} of a record sealed with this key under this name, else null (open_phone's checks)
export async function openPhoneRecord(key: MirrorKey, logical: string, blob: Uint8Array): Promise<{ device: string; name: string; seen: number } | null> {
  if (blob.length > PHONE_MAX) return null
  try {
    const r = await key.openJSON<{ device?: unknown; name?: unknown; seen?: unknown }>(logical, blob)
    const device = r?.device, name = r?.name, seen = r?.seen
    if (typeof device !== 'string' || !device || device.length > 40 || typeof name !== 'string' || typeof seen !== 'number'
      || !Number.isSafeInteger(seen) || seen <= 0 || logical !== await phoneRecordName(key, device)) return null
    return { device, name, seen }
  } catch { return null }
}

// after a complete read of the library: writes the record when it is due, else 'fresh'. A failure throws and counts
// for nothing (the next read tries again).
export function syncPhoneRecord(drive: Drive, key: MirrorKey, pair: RecordPairing, device: string, name: string, now = Date.now()): Promise<Synced> {
  if (pair.solo) return Promise.resolve('solo')
  const run = chain.then(() => write(drive, key, pair, device, cleanName(name), now))
  chain = run.catch(() => undefined)
  return run
}

async function write(drive: Drive, key: MirrorKey, pair: RecordPairing, device: string, name: string, now: number): Promise<Synced> {
  if (dropping === pair.f) return 'stopped'
  const ctl = new AbortController()
  writing = ctl                    // before the first wait: an Unpair from now on stops this write
  try {
    const st = await kv.get<RecordState>(STATE)
    if (ctl.signal.aborted || dropping === pair.f) return 'stopped'
    const same = !!st && st.f === pair.f && st.d === device && !!st.id
    // a clock set back (now before the last write) never holds the record back
    if (same && st!.name === name && now >= st!.at && now - st!.at < RECORD_EVERY) return 'fresh'
    const [logical, blob] = await sealPhoneRecord(key, device, name, now)
    let id = same ? st!.id : ''
    if (id) {
      try { await drive.update(id, blob, ctl.signal) }
      catch (e) { if (!(e instanceof DriveError) || e.status !== 404) throw e; id = '' }   // removed meanwhile
    }
    if (!id) id = await adopt(drive, key, logical, device, blob, ctl.signal)
    if (ctl.signal.aborted || dropping === pair.f) return 'stopped'
    await kv.set(STATE, { f: pair.f, d: device, id, name, at: now } satisfies RecordState)
    return 'written'
  } finally {
    if (writing === ctl) writing = null
  }
}

// no Drive id here (a create whose answer was lost, a cleared phone, a record removed meanwhile): a record under this
// name that opens with this key and names this device is this phone's own. The first is kept and replaced, its other
// copies are removed, files that do not open are left alone; a new one is made only when none is there.
async function adopt(drive: Drive, key: MirrorKey, logical: string, device: string, blob: Uint8Array, signal: AbortSignal): Promise<string> {
  const mine: string[] = []
  for (const f of await drive.named(logical, signal)) {
    signal.throwIfAborted()
    if (f.size > PHONE_MAX) continue
    if ((await openPhoneRecord(key, logical, await drive.get(f.id)))?.device === device) mine.push(f.id)
  }
  signal.throwIfAborted()
  if (!mine.length) return drive.create(logical, blob, signal, 0)      // never made twice: a lost answer is adopted next time
  const [id, ...copies] = mine
  await drive.update(id, blob, signal)
  for (const c of copies) await drive.remove(c, signal)
  return id
}

// Unpair: removes this phone's record, best effort, and gives up after `within` ms (the request in flight is aborted).
// Never throws, so Unpair always goes on; a write in flight stops and none starts for this pairing until a reload.
export async function dropPhoneRecord(drive: Drive, key: MirrorKey, pair: RecordPairing, device: string, within = DROP_WITHIN): Promise<'dropped' | 'none' | 'stopped' | 'failed'> {
  if (pair.solo) return 'none'
  dropping = pair.f
  writing?.abort()
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), within)
  const stopped = new Promise<'stopped'>(res => ctl.signal.addEventListener('abort', () => res('stopped'), { once: true }))
  const work = (async (): Promise<'dropped' | 'none'> => {
    const st = await kv.get<RecordState>(STATE)
    const ids = new Set<string>(st && st.f === pair.f && st.d === device && st.id ? [st.id] : [])
    for (const f of await drive.named(await phoneRecordName(key, device), ctl.signal)) ids.add(f.id)
    for (const id of ids) await drive.remove(id, ctl.signal)
    await kv.del(STATE)
    return ids.size ? 'dropped' : 'none'
  })().catch(() => 'failed' as const)
  try { return await Promise.race([work, stopped]) }
  finally { clearTimeout(timer); ctl.abort() }
}
