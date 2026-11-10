// Vault sync round, phone side (projects/vault-sync/plans/03-phone-side.md; owner vaults: spec
// docs/superpowers/specs/2026-10-28-owner-vault-sync-design.md): the same steps as SyncService._vault_round on
// the PC, but the phone merges only against the PC's list. Everything it needs comes in through `Env` (Drive,
// key, file system, state), so Node can run it against memory stand-ins.
//
// The PC's list says which rules apply (merge.ts): a classic vault (no `generated`) keeps Content Manager/ one
// way; a vault with a manifest publishes `generated` (the only one-way paths), `removed` (deletion records) and
// `vault` (its identity). This phone declares CAPS in its own list; a PC that sees an older phone pauses.
import type { MirrorKey } from '../mirror/crypto'
import type { Drive } from '../mirror/drive'
import { blobLogical, blobName, CAPS, decodeIndexFull, encodeIndex, excluded, INDEX_LOGICAL, INDEX_PREFIX, MAX_FILE, mergeVault, NOMEDIA, ONE_WAY, STATUS_LOGICAL, STATUS_PREFIX, validRel, type Map_ } from './merge'

export interface DriveLike {
  list(): Promise<{ id: string; name: string; size: number }[]>
  get(id: string): Promise<Uint8Array>
  remove(id: string): Promise<void>
  create(name: string, data: Uint8Array): Promise<string>
}
export interface Fs {
  list(): Promise<{ path: string; size: number; mtime: number }[]>
  read(path: string): Promise<Uint8Array>
  write(path: string, data: Uint8Array): Promise<void>
  remove(path: string): Promise<void>
  has(path: string): Promise<boolean>
}
// fp: the mirror key's fingerprint. Content ids are keyed, so a state kept under another key (a new
// pairing, Unpair) matches nothing: the round drops it and starts as a first sync (no deletions).
// vault: the PC vault's identity the base was built against (spec 1b decision 4); another identity makes
// the next round non-destructive. manifest: the PC's vault has a manifest (the last list carried `generated`).
// legacy: leftover Content Manager/ copies the last round kept (never listed or sent; Remove old Brainamon pages)
export interface VaultState { base: Map_; cache: Record<string, [number, number, string]>; cacheVersion?: number; fp?: string; vault?: string; manifest?: boolean; legacy?: number }
const CACHE_VERSION = 1
export interface Env {
  drive: DriveLike; key: MirrorKey; fs: Fs; device: string; force: boolean; now?: Date
  load(): Promise<VaultState | undefined>; save(s: VaultState): Promise<void>
  // `overall`: how far the whole round is, 0..1 (the bar); done/total count the files of this step (total 0: no count)
  progress?(step: string, done: number, total: number, overall?: number, display?: string): void
  words?: (key: string, params?: Record<string, unknown>) => string
  // Stop: looked at between files, never inside one (a file being written is finished first)
  signal?: { aborted: boolean }
}
export interface Result { state: 'idle' | 'brake' | 'waiting' | 'stopped'; reason: string; summary: string; legacy?: number }
class Stopped extends Error {}
const lap = (env: Env) => { if (env.signal?.aborted) throw new Stopped() }
// files read, taken or sent at once: one Drive call or native file call each, and a first round has thousands.
// Google's per-user quota is far above this; a burst refusal (403 rate limit, 429) is retried by Drive.call
export const PARALLEL = 8
// `list` PARALLEL at a time. Stop is looked at before each file, and a file already started always finishes:
// every running one ends before this returns (or throws, with the first error, or Stopped once they have)
async function each<T>(env: Env, list: T[], f: (t: T, i: number) => Promise<void>): Promise<void> {
  let next = 0, err: { e: unknown } | null = null
  await Promise.all(Array.from({ length: Math.min(PARALLEL, list.length) }, async () => {
    while (next < list.length && !err && !env.signal?.aborted) {
      const i = next++
      try { await f(list[i], i) } catch (e) { err ??= { e } }
    }
  }))
  if (err) throw (err as { e: unknown }).e
  lap(env)
}
// where a step sits in the round: [lo, hi] of the bar, `done` of `total` files into it
const at = (lo: number, hi: number, done = 0, total = 0) => lo + (hi - lo) * (total > 0 ? Math.min(1, done / total) : 0)
// what the PC's last round wrote to Drive: the Settings window's vault fields without the `vault_` prefix, plus `at`
export interface PcStatus { state: string; step: string; done: number; total: number; since: number; reason: string; summary: string; last: number; at: number }

export async function pcStatus(drive: Pick<Drive, 'find' | 'get'>, key: MirrorKey): Promise<PcStatus | null> {
  const name = STATUS_PREFIX + await key.name('vault/status/pc')
  const f = await drive.find(name)
  if (!f) return null
  const d = JSON.parse(await key.openText(STATUS_LOGICAL, await drive.get(f.id))) as Partial<PcStatus>
  return { state: String(d.state || ''), step: String(d.step || ''), done: Number(d.done) || 0, total: Number(d.total) || 0, since: Number(d.since) || 0,
           reason: String(d.reason || ''), summary: String(d.summary || ''), last: Number(d.last) || 0, at: Number(d.at) || 0 }
}

// the manifest's hash of a file (library/owner_vault.py data_hash): what a deletion record carries
async function sha256(data: Uint8Array): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', data as BufferSource))].map(b => b.toString(16).padStart(2, '0')).join('')
}

async function scan(env: Env, cache: VaultState['cache'], lo: number, hi: number): Promise<{ files: Map_; cache: VaultState['cache'] }> {
  const files: Map_ = {}, fresh: VaultState['cache'] = {}
  const settled = Date.now() - 2000          // a file modified in the last two seconds is not cached (same rule as the PC scan)
  env.progress?.('Listing the vault folder', 0, 0, lo, env.words?.('backup.vault.step.listing'))
  const list = await env.fs.list()
  await each(env, list, async (f, i) => {
    if (i % 25 === 0) env.progress?.('Checking files', i, list.length, at(lo, hi, i, list.length), env.words?.('backup.vault.step.checking'))
    if (excluded(f.path) || !validRel(f.path) || f.size > MAX_FILE) return
    const c = cache[f.path]
    const id = c && c[0] === f.size && c[1] === f.mtime ? c[2] : await env.key.contentId(await env.fs.read(f.path))
    files[f.path] = id
    if (f.mtime < settled) fresh[f.path] = [f.size, f.mtime, id]
  })
  return { files, cache: fresh }
}

async function trash(fs: Fs, rel: string) {
  const slash = rel.lastIndexOf('/'), dir = slash >= 0 ? rel.slice(0, slash + 1) : '', name = rel.slice(slash + 1)
  const dot = name.lastIndexOf('.'), cut = dot > 0 && dot < name.length - 1 ? dot : name.length
  let dst = `.trash/${rel}`
  for (let n = 2; await fs.has(dst); n++) dst = `.trash/${dir}${name.slice(0, cut)} (${n})${name.slice(cut)}`
  await fs.write(dst, await fs.read(rel))
  await fs.remove(rel)
}

// Settings > Obsidian > Remove old Brainamon pages (spec 1b decision 3): what is left of the classic
// Content Manager/ folder goes to .trash/, on the user's click. Returns how many files moved.
export async function removeLegacy(env: Pick<Env, 'fs' | 'signal' | 'progress' | 'words'>): Promise<number> {
  const list = (await env.fs.list()).filter(f => f.path.startsWith(ONE_WAY) && validRel(f.path) && !excluded(f.path))
  let n = 0
  for (const f of list) {
    if (env.signal?.aborted) break
    env.progress?.('Moving old pages to .trash', n, list.length, n / Math.max(1, list.length), env.words?.('backup.vault.step.movingOld'))
    await trash(env.fs, f.path)
    n++
  }
  return n
}

// Stop (env.signal) is looked at between files only. Cache hints for files about to be replaced may be
// invalidated first; the saved base stays as it was while changes are applied: a file already taken is
// then equal on both sides next round, and a conflict copy is written together with its file, so no round
// repeats one. After they are applied the base is saved (it is true by then); only the phone's own list is
// not sent, the next round does.
export async function vaultRound(env: Env): Promise<Result> {
  try {
    return await round(env)
  } catch (e) {
    if (e instanceof Stopped) return { state: 'stopped', reason: (env.words?.('backup.vault.stoppedBefore') ?? 'Stopped before the PC\'s changes were taken.'), summary: '' }
    throw e
  }
}

async function round(env: Env): Promise<Result> {
  const { drive, key, fs } = env
  // the vault's pictures (Content Manager/attachments alone is thousands) stay out of the phone's gallery;
  // Obsidian still shows them. Never synced (excluded), so the PC never gets one.
  try { if (!await fs.has(NOMEDIA)) await fs.write(NOMEDIA, new Uint8Array()) } catch { /* the round goes on without it */ }
  const savedState = await env.load()
  const st: VaultState = savedState && savedState.fp === key.fingerprint ? savedState : { base: {}, cache: {}, fp: key.fingerprint }
  // Older builds could keep a pre-replacement hash after a same-size write.
  if (st.cacheVersion !== CACHE_VERSION) st.cache = {}
  env.progress?.('Reading the Drive list', 0, 0, 0, env.words?.('backup.vault.step.driveList'))
  const listing = await drive.list()
  lap(env)
  const byName = new Map(listing.map(f => [f.name, f]))
  const pcName = INDEX_PREFIX + await key.name('vault/index/pc')
  const pc = byName.get(pcName)
  if (!pc) return { state: 'waiting', reason: (env.words?.('backup.vault.pcNotStarted') ?? 'The PC has not started vault sync yet.'), summary: '' }
  env.progress?.("Reading the PC's file list", 0, 0, 0.04, env.words?.('backup.vault.step.pcList'))
  const pcIndex = decodeIndexFull(await key.openText(INDEX_LOGICAL, await drive.get(pc.id)))
  const theirs = pcIndex.files, manifest = pcIndex.generated !== null
  lap(env)
  // vault identity (spec 1b decision 4): another identity than the base was built against makes this round
  // non-destructive: the base is dropped, except the leftover Content Manager/ entries of a vault with a
  // manifest, which decide later what may go to .trash (decision 3, legacy)
  const fresh = !!st.vault && !!pcIndex.vault && st.vault !== pcIndex.vault
  if (fresh) st.cache = {}
  const base: Map_ = fresh ? Object.fromEntries(Object.entries(st.base).filter(([r]) => manifest && r.startsWith(ONE_WAY))) : st.base
  let { files: mine, cache } = await scan(env, st.cache, 0.08, 0.4)
  // deletion records (decision 3): a copy that differs from the base is compared with the hash Brainamon last wrote
  const mineHash: Map_ = {}
  for (const rel of Object.keys(pcIndex.removed)) {
    lap(env)
    if (mine[rel] !== undefined && mine[rel] !== base[rel]) mineHash[rel] = await sha256(await fs.read(rel))
  }
  env.progress?.('Comparing with the PC', 0, 0, 0.4, env.words?.('backup.vault.step.comparing'))
  const plan = mergeVault(base, mine, theirs, 'phone', env.now ?? new Date(), { generated: pcIndex.generated, removed: pcIndex.removed, mineHash, fresh }, env.words)
  if (plan.brake && !env.force) return { state: 'brake', reason: plan.reason, summary: '' }
  const legacy = new Set(plan.legacy)
  const editedRemoved: Map_ = {}
  if (!fresh) for (const [rel, hash] of Object.entries(pcIndex.removed)) {
    if (mine[rel] !== undefined && mine[rel] !== base[rel] && mineHash[rel] !== hash) editedRemoved[rel] = mine[rel]
  }
  const state = (): VaultState => ({ base: plan.new_base, cache, cacheVersion: CACHE_VERSION, fp: key.fingerprint, vault: pcIndex.vault || st.vault, manifest, legacy: legacy.size })

  // Choose all destinations before parallel writes so no conflict copy collides with another pull or copy.
  const copies: Map_ = {}, reserved = new Set([...Object.keys(mine), ...Object.keys(theirs), ...Object.keys(plan.pull)])
  for (const [rel, preferred] of Object.entries(plan.conflicts)) {
    const slash = preferred.lastIndexOf('/'), dot = preferred.lastIndexOf('.')
    const cut = dot > slash + 1 ? dot : preferred.length
    let copy = preferred
    for (let n = 2; reserved.has(copy) || await fs.has(copy); n++) copy = `${preferred.slice(0, cut)} (${n})${preferred.slice(cut)}`
    reserved.add(copy); copies[rel] = copy
  }
  const pulls = Object.entries(plan.pull), moves = plan.trash.length
  const writePaths = [...pulls.map(([rel]) => rel), ...Object.values(copies)]
  // Persist invalidation before any write so a restart cannot trust the replaced file's old hash.
  if (writePaths.some(rel => Object.hasOwn(st.cache, rel))) {
    const oldCache = { ...st.cache }
    for (const rel of writePaths) delete oldCache[rel]
    await env.save({ ...st, cache: oldCache })
  }
  let took = 0
  await each(env, pulls, async ([rel, id], i) => {
    if (i === 0) env.progress?.("Taking the PC's changes", 0, pulls.length, 0.4, env.words?.('backup.vault.step.taking'))
    const f = byName.get(blobName(id))
    if (!f) throw new Error(`${rel} is not in Drive yet`)
    const data = await key.open(blobLogical(id), await drive.get(f.id))
    if (await key.contentId(data) !== id) throw new Error(`${rel} does not match its content id`)
    const copy = copies[rel]
    if (copy) {
      if (await fs.has(copy)) throw new Error('A conflict copy appeared during sync. Retry to keep both edits.')
      await fs.write(copy, await fs.read(rel))
      delete cache[copy]
    }
    await fs.write(rel, data)
    delete cache[rel]                                             // providers may preserve size and mtime after replacement
    took++
    env.progress?.("Taking the PC's changes", took, pulls.length, at(0.4, 0.6, took, pulls.length + moves), env.words?.('backup.vault.step.taking'))
  })
  for (const [i, rel] of plan.trash.entries()) {
    lap(env)
    env.progress?.('Moving deleted files to .trash', i, moves, at(0.4, 0.6, pulls.length + i, pulls.length + moves), env.words?.('backup.vault.step.trashing'))
    await trash(fs, rel)
  }

  ;({ files: mine, cache } = await scan(env, cache, 0.6, 0.75))
  // leftover Content Manager/ copies are never listed or sent (decision 3, legacy)
  const listed: Map_ = {}
  for (const [rel, id] of Object.entries(mine)) if (!legacy.has(rel)) listed[rel] = id
  // Acknowledgements describe this exact published copy, after processing this vault's deletion record.
  const kept: Map_ = {}
  for (const [rel, id] of Object.entries(editedRemoved)) if (listed[rel] === id) kept[rel] = pcIndex.removed[rel]
  let sent = 0, processed = 0
  const seen = new Set<string>(), pending: [string, string][] = []
  for (const [rel, id] of Object.entries(listed)) {
    if (seen.has(id) || byName.has(blobName(id))) continue
    seen.add(id); pending.push([rel, id])
  }
  const done = () => (env.words?.('backup.vault.summary', { pulled: pulls.length, trashed: plan.trash.length, conflicts: Object.keys(plan.conflicts).length, sent }) ?? `${pulls.length} pulled, ${plan.trash.length} moved to .trash, ${Object.keys(plan.conflicts).length} conflict copies, ${sent} sent`)
  try {
    await each(env, pending, async ([rel, id], i) => {
      if (i === 0) env.progress?.('Sending to Drive', 0, pending.length, 0.75, env.words?.('backup.vault.step.sending'))
      const data = await fs.read(rel)
      if (await key.contentId(data) === id) {                       // files edited since the scan wait for the next round
        await drive.create(blobName(id), await key.seal(blobLogical(id), data))
        sent++
      }
      processed++
      env.progress?.('Sending to Drive', processed, pending.length, at(0.75, 0.97, processed, pending.length), env.words?.('backup.vault.step.sending'))
    })
  } catch (e) {
    if (!(e instanceof Stopped)) throw e
    await env.save(state())
    return { state: 'stopped', reason: (env.words?.('backup.vault.stoppedSending') ?? 'Stopped while sending; the rest goes next round.'), summary: done(), legacy: legacy.size }
  }
  env.progress?.('Writing the file list', 0, 0, 0.97, env.words?.('backup.vault.step.writing'))
  const mineName = INDEX_PREFIX + await key.name('vault/index/' + env.device)
  const old = byName.get(mineName)
  if (old) await drive.remove(old.id)
  await drive.create(mineName, await key.seal(INDEX_LOGICAL, encodeIndex(listed, env.device, { caps: CAPS, vault: pcIndex.vault, kept })))
  await env.save(state())
  const summary = pulls.length || plan.trash.length || sent ? done() : (env.words?.('backup.vault.inStep') ?? 'Already in step')
  return { state: 'idle', reason: '', summary, legacy: legacy.size }
}
