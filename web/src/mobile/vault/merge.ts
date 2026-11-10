// Vault sync merge, phone side: a port of library/vault_sync.py (merge, excluded, validRel, conflictName,
// the index codec). tests/test_vault_merge_js.py runs it against tests/fixtures/vault_cases.json, the same
// cases the Python tests use. No imports: Node runs this file under type stripping.
//
// Two rule sets, chosen by the PC's file list (spec docs/superpowers/specs/2026-10-28-owner-vault-sync-design.md).
// A classic vault (no `generated` key) keeps the first rules: Content Manager/ one way, PC to phone, the rest two
// ways. A vault with a manifest publishes `generated` (the only one-way paths), `removed` (deletion records:
// path and the SHA-256 Brainamon last wrote) and `vault` (its identity); this phone answers with `caps`.

export const ONE_WAY = 'Content Manager/'
export const MAX_FILE = 50 * 1024 * 1024
export const BRAKE_FILES = 20, BRAKE_PERCENT = 10, BRAKE_MIN = 3
export const INDEX_LOGICAL = 'vault/index'
export const INDEX_PREFIX = 'vi-', BLOB_PREFIX = 'vb-'
export const STATUS_LOGICAL = 'vault/status', STATUS_PREFIX = 'vs-'     // the PC's round status (SyncService._vault_report)
export const TMP_SUFFIX = '.vsync-tmp'
export const NOMEDIA = '.nomedia'     // the phone's own marker: the vault's pictures stay out of the Android gallery
export const CAPS = ['generated', 'identity']     // what this app declares in its file list (spec 1b decision 5)
export const SKIP_DIRS = ['.obsidian/plugins', '.obsidian/themes', '.trash', '.git', '.brainamon']
const ID = /^[0-9a-f]{32}$/, SHA = /^[0-9a-f]{64}$/

export type Map_ = Record<string, string>
export interface VPlan {
  pull: Map_; trash: string[]; conflicts: Map_; lost: string[]; legacy: string[]; new_base: Map_; brake: boolean; reason: string
}
// what a file list carries besides the files: the PC's vault identity, generated set and deletion records, a phone's caps
export interface IndexExtra { vault?: string; generated?: string[] | null; removed?: Map_; caps?: string[]; kept?: Map_ }
export interface FullIndex { device: string; files: Map_; vault: string; generated: Set<string> | null; removed: Map_; caps: Set<string>; kept: Map_ }
export interface MergeOpts { generated?: Set<string> | null; removed?: Map_; mineHash?: Map_; fresh?: boolean; kept?: Map_ }

export function validRel(rel: unknown): rel is string {
  if (typeof rel !== 'string' || !rel || rel.startsWith('/') || rel.includes('\\') || rel.includes(':') || rel.includes('\0')) return false
  return rel.split('/').every(p => p !== '' && p !== '.' && p !== '..')
}

export function excluded(path: string): boolean {
  const rel = path.replace(/\\/g, '/').replace(/^\/+/, '')
  if ((rel.endsWith(TMP_SUFFIX) || rel.endsWith('.vsync-backup')) || rel.startsWith('.obsidian/workspace') || rel === NOMEDIA) return true
  return SKIP_DIRS.some(d => rel === d || rel.startsWith(d + '/'))
}

export const blobName = (id: string) => BLOB_PREFIX + id
export const blobLogical = (id: string) => 'vault/blob/' + id

const sortedMap = (m: Map_): Map_ => { const out: Map_ = {}; for (const k of Object.keys(m).sort()) out[k] = m[k]; return out }

export function encodeIndex(files: Map_, device: string, extra: IndexExtra = {}): Uint8Array {
  const d: Record<string, unknown> = { v: 1, device, files: sortedMap(files) }
  if (extra.vault) d.vault = extra.vault
  if (extra.generated != null) d.generated = [...extra.generated].sort()
  if (extra.removed && Object.keys(extra.removed).length) d.removed = sortedMap(extra.removed)
  if (extra.caps?.length) d.caps = [...extra.caps].sort()
  if (extra.kept && Object.keys(extra.kept).length) d.kept = sortedMap(extra.kept)
  return new TextEncoder().encode(JSON.stringify(d))
}

export function decodeIndexFull(text: string): FullIndex {
  const d = JSON.parse(text) as { device?: string; files?: Record<string, unknown>; vault?: unknown; generated?: unknown; removed?: unknown; caps?: unknown; kept?: unknown }
  if (!d || typeof d !== 'object' || Array.isArray(d) || !d.files || typeof d.files !== 'object' || Array.isArray(d.files)) throw new Error('Invalid vault file list.')
  const files: Map_ = {}
  for (const [r, i] of Object.entries(d.files)) if (validRel(r) && !excluded(r) && typeof i === 'string' && ID.test(i)) files[r] = i
  const generated = Array.isArray(d.generated) ? new Set((d.generated as unknown[]).filter((r): r is string => typeof r === 'string' && r in files)) : null
  const removed: Map_ = {}
  if (d.removed && typeof d.removed === 'object' && !Array.isArray(d.removed)) {
    for (const [r, h] of Object.entries(d.removed as Record<string, unknown>)) if (validRel(r) && !excluded(r) && !(r in files) && typeof h === 'string' && SHA.test(h)) removed[r] = h
  }
  const kept: Map_ = {}
  if (d.kept && typeof d.kept === 'object' && !Array.isArray(d.kept)) {
    for (const [r, h] of Object.entries(d.kept as Record<string, unknown>)) if (r in files && typeof h === 'string' && SHA.test(h)) kept[r] = h
  }
  const caps = new Set(Array.isArray(d.caps) ? (d.caps as unknown[]).filter((c): c is string => typeof c === 'string') : [])
  return { device: String(d.device ?? ''), files, vault: typeof d.vault === 'string' ? d.vault : '', generated, removed, caps, kept }
}

// the pre-1b reader: files and device only (what an older phone sees)
export function decodeIndex(text: string): { device: string; files: Map_ } {
  const f = decodeIndexFull(text)
  return { device: f.device, files: f.files }
}

const p2 = (n: number) => String(n).padStart(2, '0')

export function conflictName(rel: string, when: Date): string {
  const slash = rel.lastIndexOf('/')
  const dir = slash >= 0 ? rel.slice(0, slash + 1) : ''
  const name = rel.slice(slash + 1)
  const dot = name.lastIndexOf('.')
  const cut = dot > 0 && dot < name.length - 1 ? dot : name.length
  const stamp = `${when.getFullYear()}-${p2(when.getMonth() + 1)}-${p2(when.getDate())} ${p2(when.getHours())}${p2(when.getMinutes())}`
  return `${dir}${name.slice(0, cut)} (phone conflict ${stamp})${name.slice(cut)}`
}

const over = (n: number, total: number) => n > BRAKE_FILES || (n >= BRAKE_MIN && n * 100 > BRAKE_PERCENT * total)

// The rules are library/vault_sync.py merge()'s, in the same order; keep the two in step (the fixture checks).
export function mergeVault(base: Map_, mine: Map_, theirs: Map_, role: 'pc' | 'phone', when: Date, opts: MergeOpts = {}, words?: (key: string, params?: Record<string, unknown>) => string): VPlan {
  const plan: VPlan = { pull: {}, trash: [], conflicts: {}, lost: [], legacy: [], new_base: {}, brake: false, reason: '' }
  const nb = plan.new_base
  const generated = opts.generated ?? null, removed = opts.removed ?? {}, mineHash = opts.mineHash ?? {}, fresh = !!opts.fresh, kept = opts.kept ?? {}
  const manifest = generated !== null
  const free = new Set<string>()                     // trashed under a one-way rule: not counted by the brake
  const all = new Set([...Object.keys(base), ...Object.keys(mine), ...Object.keys(theirs)])
  for (const rel of [...all].sort()) {
    const b = base[rel], m = mine[rel], t = theirs[rel]
    if (manifest) {
      if (generated!.has(rel)) {                       // a page Brainamon wrote: one way (t is never undefined here)
        if (role === 'pc') { if (m !== undefined && m === t) nb[rel] = m; else if (b !== undefined) nb[rel] = b }
        else if (m === undefined || m === b || m === t) { if (m !== t) plan.pull[rel] = t; nb[rel] = t }
        else { plan.conflicts[rel] = conflictName(rel, when); plan.pull[rel] = t; nb[rel] = t }
        continue
      }
      if (role === 'pc' && m === undefined && rel in removed) {
        if (t !== undefined && kept[rel] === removed[rel]) { plan.pull[rel] = t; nb[rel] = t }
        else if (b !== undefined) nb[rel] = b
        continue
      }
      if (role === 'pc' && m === undefined && rel.startsWith(ONE_WAY)) continue      // a phone's leftover classic copy: never taken
      if (role === 'phone' && t === undefined && m !== undefined && (rel in removed || rel.startsWith(ONE_WAY))) {
        const unedited = m === b || (rel in removed && mineHash[rel] === removed[rel])
        if (unedited && !fresh) { plan.trash.push(rel); free.add(rel) }
        else {
          if (b !== undefined) nb[rel] = b
          if (rel.startsWith(ONE_WAY)) plan.legacy.push(rel)
        }
        continue
      }
    } else if (rel.startsWith(ONE_WAY)) {
      if (role === 'pc') { if (m !== undefined) nb[rel] = m }
      else if (t === undefined) { if (m !== undefined && !fresh) { plan.trash.push(rel); free.add(rel) } else if (b !== undefined) nb[rel] = b }
      else { if (m !== t) plan.pull[rel] = t; nb[rel] = t }
      continue
    }
    if (m === t) { if (m !== undefined) nb[rel] = m }
    else if (m === b) {
      if (t === undefined) { if (fresh) nb[rel] = b; else plan.trash.push(rel) }
      else { plan.pull[rel] = t; nb[rel] = t }
    } else if (t === b) {
      if (m === undefined && !fresh && (role !== 'pc' || !(rel in removed))) plan.lost.push(rel)
      if (b !== undefined) nb[rel] = b
    } else if (m === undefined) { plan.pull[rel] = t; nb[rel] = t }
    else if (t === undefined) { if (b !== undefined) nb[rel] = b }
    else if (role === 'phone') { plan.conflicts[rel] = conflictName(rel, when); plan.pull[rel] = t; nb[rel] = t }
    else if (b !== undefined) nb[rel] = b
  }
  const counted = plan.trash.filter(r => !free.has(r))
  const total = Object.keys(base).length
  for (const [what, n, message] of [['removed here', counted.length, 'backup.vault.brakeHere'], ['removed there', plan.lost.length, 'backup.vault.brakeThere']] as const) {
    if (over(n, total)) {
      plan.brake = true
      plan.reason = (words?.(message, { n, files: BRAKE_FILES, percent: BRAKE_PERCENT }) ?? `${n} files would be ${what} (the limit is ${BRAKE_FILES} files or ${BRAKE_PERCENT}% of the vault).`)
      break
    }
  }
  return plan
}
