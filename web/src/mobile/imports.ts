// Import saved posts from Instagram's "Download your information" export, on the phone
// (projects/milestone-2026-10-14/mobile-import/PLAN.md): the zip Instagram sends, or the
// saved_posts.json inside it. A small zip reader (central directory; deflate through the
// platform's DecompressionStream), the parser for saved_posts.json (layout in BRAINSTORM.md), the
// mojibake fix, and the phone changes each new link becomes. No imports: the Python test runs this
// file under Node (tests/test_phone_import.py).

export const MAX_IMPORT_BYTES = 60 * 1024 * 1024
export const NOT_SAVED = 'This is not Instagram\'s saved posts. Choose the zip Instagram sent, or saved_posts.json from inside it.'
export const TOO_BIG = `That file is over ${MAX_IMPORT_BYTES / 1024 / 1024} MB. Ask Instagram for Saved only, in JSON (step 3).`

// one saved post, ready to become a link
export interface Saved { url: string; at: number; caption: string; creator: string; tags: string }
export interface Parsed { posts: Saved[]; skipped: number }

// Meta writes UTF-8 bytes as Latin-1 characters (a right quote arrives as "â\u0080\u0099"). Only a
// string made of 8-bit characters that decodes as UTF-8 is changed; anything else is kept.
export function fixText(s: string): string {
  if (!/[\u0080-ÿ]/.test(s) || /[^\u0000-ÿ]/.test(s)) return s
  try { return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(s, c => c.charCodeAt(0))) } catch { return s }
}

type LV = { label?: unknown; title?: unknown; value?: unknown; href?: unknown; dict?: unknown }
const list = (v: unknown): LV[] => (Array.isArray(v) ? v.filter(x => x && typeof x === 'object') : [])
const text = (v: unknown) => (typeof v === 'string' ? fixText(v).trim() : '')
const val = (lv: LV[], label: string) => text(lv.find(x => x.label === label)?.value)
// the {label, value} lists inside a {title, dict: [{dict: [...]}, ...]} group (Owner, Hashtags)
const group = (lv: LV[], title: string) => list(lv.find(x => x.title === title)?.dict).map(d => list(d.dict))

export function parseSaved(data: unknown): Parsed {
  if (!Array.isArray(data)) throw new Error(NOT_SAVED)
  const posts: Saved[] = []
  let skipped = 0, shaped = 0
  for (const e of data as { label_values?: unknown; timestamp?: unknown }[]) {
    const lv = list(e?.label_values)
    if (!lv.length) { skipped++; continue }
    shaped++
    const u = lv.find(x => x.label === 'URL')
    const url = text(u?.value) || text(u?.href)
    if (!/^https?:\/\//i.test(url)) { skipped++; continue }
    const caption = lv.filter(x => x.label === 'Caption').map(x => text(x.value)).find(Boolean) ?? ''
    const owner = group(lv, 'Owner')[0] ?? []
    const seen = new Set<string>(), tags: string[] = []
    for (const h of group(lv, 'Hashtags')) {
      const t = val(h, 'Name').replace(/^#+/, '')
      if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); tags.push(t) }
    }
    const ts = typeof e.timestamp === 'number' && e.timestamp > 0 ? Math.round(e.timestamp * 1000) : 0
    posts.push({ url, at: ts, caption: caption.slice(0, 5000), creator: (val(owner, 'Username') || val(owner, 'Name')).slice(0, 120), tags: tags.join(', ') })
  }
  if (data.length && !shaped) throw new Error(NOT_SAVED)
  return { posts, skipped }
}

// ── zip: the central directory at the end lists every file; each one's data follows its local header ──
export interface ZipEntry { name: string; method: number; packed: number; size: number; at: number }
const u16 = (b: Uint8Array, o: number) => b[o] | (b[o + 1] << 8)
const u32 = (b: Uint8Array, o: number) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0
const isZip = (b: Uint8Array) => b.length >= 4 && u32(b, 0) === 0x04034b50

export function zipEntries(b: Uint8Array): ZipEntry[] {
  let end = -1
  for (let i = b.length - 22; i >= Math.max(0, b.length - 22 - 0xffff); i--) if (u32(b, i) === 0x06054b50) { end = i; break }
  if (end < 0) throw new Error(NOT_SAVED)
  const out: ZipEntry[] = []
  let p = u32(b, end + 16)
  for (let k = u16(b, end + 10); k > 0; k--) {
    if (p + 46 > b.length || u32(b, p) !== 0x02014b50) throw new Error(NOT_SAVED)
    const n = u16(b, p + 28)
    out.push({ name: new TextDecoder().decode(b.subarray(p + 46, p + 46 + n)), method: u16(b, p + 10), packed: u32(b, p + 20), size: u32(b, p + 24), at: u32(b, p + 42) })
    p += 46 + n + u16(b, p + 30) + u16(b, p + 32)
  }
  return out
}

export async function unzipEntry(b: Uint8Array, z: ZipEntry): Promise<Uint8Array> {
  if ([z.packed, z.size, z.at].includes(0xffffffff) || z.size > MAX_IMPORT_BYTES) throw new Error(TOO_BIG)   // ZIP64: over 4 GB
  if (z.at + 30 > b.length || u32(b, z.at) !== 0x04034b50) throw new Error(NOT_SAVED)
  const start = z.at + 30 + u16(b, z.at + 26) + u16(b, z.at + 28)
  if (start > b.length || z.packed > b.length - start) throw new Error(NOT_SAVED)
  const raw = b.subarray(start, start + z.packed)
  if (z.method === 0) {
    if (raw.length !== z.size) throw new Error(NOT_SAVED)
    return raw
  }
  if (z.method !== 8) throw new Error(NOT_SAVED)
  const reader = new Blob([new Uint8Array(raw)]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.length
      if (size > MAX_IMPORT_BYTES) throw new Error(TOO_BIG)
      chunks.push(value)
    }
    if (size !== z.size) throw new Error(NOT_SAVED)
    const out = new Uint8Array(size)
    let at = 0
    for (const chunk of chunks) { out.set(chunk, at); at += chunk.length }
    return out
  } catch (e) {
    await reader.cancel().catch(() => {})
    throw new Error(e instanceof Error && e.message === TOO_BIG ? TOO_BIG : NOT_SAVED)
  } finally { reader.releaseLock() }
}

// the picked file's bytes (the zip, or saved_posts.json) as saved posts; throws NOT_SAVED / TOO_BIG
export async function readExport(b: Uint8Array): Promise<Parsed> {
  if (b.length > MAX_IMPORT_BYTES) throw new Error(TOO_BIG)
  if (isZip(b)) {
    const z = zipEntries(b).find(e => /(^|\/)saved_posts\.json$/i.test(e.name))
    if (!z) throw new Error(NOT_SAVED)
    b = await unzipEntry(b, z)
  }
  let data: unknown
  try { data = JSON.parse(new TextDecoder().decode(b).replace(/^﻿/, '')) } catch { throw new Error(NOT_SAVED) }
  return parseSaved(data)
}

// ── the phone changes: a link (dated at save time, hashtags as tags) and its details (caption,
// creator, no picture yet: the slow picture queue adds it). `have`: the URLs already on the phone;
// `clean`: links.ts cleanLink, the same rule as every saved link. ──
export type ImportChange =
  | { op: 'link'; uid: string; url: string; note: string; category: string; tags: string; at?: number }
  | { op: 'details'; uid: string; title: string; creator: string; desc: string; thumb: string }

export function importChanges(posts: Saved[], have: Set<string>, clean: (url: string) => string, uid: () => string): { changes: ImportChange[]; dups: number } {
  const seen = new Set(have), changes: ImportChange[] = []
  let dups = 0
  for (const p of posts) {
    const url = clean(p.url) || p.url
    if (seen.has(url)) { dups++; continue }
    seen.add(url)
    const id = uid()
    changes.push({ op: 'link', uid: id, url, note: '', category: '', tags: p.tags, ...(p.at ? { at: p.at } : {}) },
      { op: 'details', uid: id, title: '', creator: p.creator, desc: p.caption, thumb: '' })
  }
  return { changes, dups }
}
