// Save for offline (PLAN.md "What lives on the phone", Phase 4 step 6): an item with its report,
// transcript, thumbnail and video, or a canvas with its images, kept until the user removes it.
// The cache trimming never touches these: items carry `saved` in IndexedDB (store.ts), and the
// files sit in their own cache (OFFLINE), which public/sw.js reads after the thumbnail cache.
// The auto-keep settings (Keep all canvases, Keep videos Off / Favourites / All) save what matches
// after each refresh, on Wi-Fi only unless the user allows mobile data. The first save asks the
// browser for persistent storage so Android does not clear it.
import type { CanvasDoc, Row } from './source/types'
import { items as idb, kv, type StoredItem } from './store'
import { mirrorSource, phone, source } from './state.svelte'
import { network, setWifiOnly, syncPaused } from './network.svelte'
import { t } from '../lib/i18n/index.ts'
import { beginLanguageWork } from './language-switch.ts'

export const OFFLINE = 'bp-offline-v1'
export interface SavedCanvas { id: string; name: string; at: number; size: number; doc: CanvasDoc; images: string[]; missing?: number }
export type KeepVideos = 'off' | 'fav' | 'all'

const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private window */ } },
}

class Offline {
  keepCanvases = $state(ls.get('bp-keep-canvases') === 'on')
  keepVideos = $state<KeepVideos>((ls.get('bp-keep-videos') as KeepVideos) || 'off')
  get wifiOnly() { return network.wifiOnly }
  busy = $state('')                       // what is downloading now, for the More screen
  persisted = $state(false)
  saved = $state.raw<StoredItem[]>([])
  canvases = $state.raw<SavedCanvas[]>([])

  async load() {
    this.saved = (await idb.all()).filter(s => s.saved).sort((a, b) => b.at - a.at)
    this.canvases = ((await kv.get<SavedCanvas[]>('saved-canvases')) ?? []).sort((a, b) => b.at - a.at)
    try { this.persisted = !!(await navigator.storage?.persisted?.()) } catch { /* unsupported */ }
  }
}
export const offline = new Offline()

export function setKeep(k: 'canvases' | 'wifi', on: boolean) {
  if (k === 'canvases') { offline.keepCanvases = on; ls.set('bp-keep-canvases', on ? 'on' : 'off') }
  else setWifiOnly(on)
}
export function setKeepVideos(v: KeepVideos) { offline.keepVideos = v; ls.set('bp-keep-videos', v) }

const bigOk = () => !syncPaused()

async function persist() {
  try { if (!offline.persisted) offline.persisted = !!(await navigator.storage?.persist?.()) } catch { /* unsupported */ }
}

// ── items ────────────────────────────────────────────────────────────────────
export const videoKey = (id: number) => `/offline/video/${id}`
export const thumbKey = (id: number) => `/offline/thumb/${id}`

export async function saveItem(id: number, withVideo = true, onProgress?: (got: number, total: number) => void): Promise<StoredItem> {
  const done = beginLanguageWork()
  try {
    await persist()
    const row = phone.byId.get(id)
    const it = await source.item(id)
    const [report, transcript] = await Promise.all([
      it.files.report ? source.itemText(id, 'report').catch(() => '') : Promise.resolve(''),
      it.files.transcript ? source.itemText(id, 'transcript').catch(() => it.transcript || '') : Promise.resolve(it.transcript || ''),
    ])
    let size = report.length + transcript.length + 2000
    const c = await caches.open(OFFLINE)
    if (row?.thumb && source.thumbBlob) {
      const b = await source.thumbBlob(row).catch(() => null)
      if (b) { await c.put(thumbKey(id), new Response(b, { headers: { 'Content-Type': 'image/jpeg' } })); size += b.size }
    }
    if (withVideo && source.video && (source.videoSize?.(id) ?? 0) > 0) {
      offline.busy = t('settings.storage.videoOf', { id })
      try {
        const v = await source.video(id, onProgress)
        await c.put(videoKey(id), new Response(v, { headers: { 'Content-Type': v.type || 'video/mp4' } }))
        size += v.size
      } finally { offline.busy = '' }
    }
    const s: StoredItem = { id, at: Date.now(), item: it, report, transcript, saved: true, size, uid: (row as Row & { uid?: string })?.uid }
    await idb.putRequired(s)
    await offline.load()
    return s
  } finally { done() }
}

export async function removeItem(id: number) {
  const done = beginLanguageWork()
  try {
    const s = await idb.getRequired(id)
    if (s) await idb.putRequired({ ...s, saved: false, size: 0 })
    const c = await caches.open(OFFLINE)
    await c.delete(videoKey(id)); await c.delete(thumbKey(id))
    await offline.load()
  } finally { done() }
}

export async function isSaved(id: number) { return !!(await idb.get(id))?.saved }

// a playable URL for the item's video: the saved copy, else downloaded from the mirror now
export async function videoUrl(id: number, onProgress?: (got: number, total: number) => void): Promise<string> {
  const hit = await (await caches.open(OFFLINE)).match(videoKey(id))
  if (hit) return URL.createObjectURL(await hit.blob())
  if (!source.video) throw new Error('Videos play from the Google Drive mirror.')
  return URL.createObjectURL(await source.video(id, onProgress))
}

// ── canvases ─────────────────────────────────────────────────────────────────
export async function saveCanvas(id: string): Promise<SavedCanvas> {
  const done = beginLanguageWork()
  try {
    await persist()
    const doc = await source.canvas(id)
    const list = await source.canvases().catch(() => [])
    const c = await caches.open(OFFLINE)
    const images: string[] = []
    let size = JSON.stringify(doc).length
    let missing = 0
    for (const el of doc.items) {
      if (el.source === 'file' && el.file_path && source.canvasImage) {
        const name = el.file_path.split(/[\\/]/).pop() || ''
        const b = await source.canvasImage(name).catch(() => null)
        if (b) { await c.put(source.canvasImageUrl(name), new Response(b, { headers: { 'Content-Type': b.type } })); images.push(name); size += b.size }
        else missing++
      } else if (el.item_id) {
        const r = phone.byId.get(el.item_id)
        if (r?.thumb && source.thumbBlob) {
          const b = await source.thumbBlob(r).catch(() => null)
          if (b) { await c.put(thumbKey(r.id), new Response(b, { headers: { 'Content-Type': 'image/jpeg' } })); size += b.size }
          else missing++
        }
      }
    }
    const s: SavedCanvas = { id, name: list.find(x => x.id === id)?.name || doc.name || id, at: Date.now(), size, doc, images, missing }
    const all = ((await kv.getRequired<SavedCanvas[]>('saved-canvases')) ?? []).filter(x => x.id !== id)
    await kv.setOfflineRequired('saved-canvases', [s, ...all])
    await offline.load()
    return s
  } finally { done() }
}

export async function removeCanvas(id: string) {
  const done = beginLanguageWork()
  try {
    const all = (await kv.getRequired<SavedCanvas[]>('saved-canvases')) ?? []
    const gone = all.find(x => x.id === id)
    await kv.setOfflineRequired('saved-canvases', all.filter(x => x.id !== id))
    if (gone) { const c = await caches.open(OFFLINE); for (const n of gone.images) await c.delete(source.canvasImageUrl(n)) }
    await offline.load()
  } finally { done() }
}

export async function savedCanvas(id: string): Promise<CanvasDoc | null> {
  return ((await kv.get<SavedCanvas[]>('saved-canvases')) ?? []).find(x => x.id === id)?.doc ?? null
}

// ── auto-keep ────────────────────────────────────────────────────────────────
// what turning a setting on would download (from the manifest), before it is turned on
export function keepVideosNeed(v: KeepVideos): { count: number; bytes: number } {
  if (!mirrorSource || v === 'off') return { count: 0, bytes: 0 }
  let count = 0, bytes = 0
  for (const r of phone.rows) {
    if (v === 'fav' && !r.fav) continue
    const n = mirrorSource.videoSize(r.id)
    if (n) { count++; bytes += n }
  }
  return { count, bytes }
}
export function keepCanvasesNeed(): number {
  const m = mirrorSource?.manifest
  if (!m) return 0
  return Object.entries(m.files).filter(([k]) => k.startsWith('canvases/') || k.startsWith('canvas-uploads/')).reduce((a, [, f]) => a + f.size, 0)
}

let keeping = false
// after a refresh: save what the auto-keep settings ask for and is not saved yet
export async function autoKeep() {
  if (keeping || !mirrorSource || !navigator.onLine || !bigOk()) return
  const done = beginLanguageWork()
  keeping = true
  try {
    await offline.load()
    if (offline.keepCanvases) {
      const have = new Map(offline.canvases.map(c => [c.id, c.at]))
      for (const cv of await source.canvases()) if (!have.has(cv.id) || (have.get(cv.id)! < cv.updated)) await saveCanvas(cv.id).catch(() => null)
    }
    if (offline.keepVideos !== 'off') {
      const have = new Set(offline.saved.map(s => s.id))
      for (const r of phone.rows) {
        if (have.has(r.id) || (offline.keepVideos === 'fav' && !r.fav) || !mirrorSource.videoSize(r.id)) continue
        if (!bigOk()) break
        await saveItem(r.id).catch(() => null)
      }
    }
  } finally { keeping = false; done() }
}

// storage the phone reports (quota and use), for the size warning
export async function freeSpace(): Promise<number> {
  try { const e = await navigator.storage?.estimate(); return e?.quota ? e.quota - (e.usage ?? 0) : 0 } catch { return 0 }
}
