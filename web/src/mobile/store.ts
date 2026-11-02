// The phone's storage (PLAN.md "What lives on the phone"), in IndexedDB:
// - kv: the light copy (card rows, categories, tints, note lists, canvas list, chat list) and when it
//   was last refreshed; the whole row list is one record so it loads in one read
// - items: full items opened on the phone (the row, report, transcript), with when they were opened;
//   trimmed to ITEM_CAP, favourites and the last PIN_RECENT opened are never trimmed (the pinned tier)
// - outbox: links saved on the phone (src/mobile/outbox.ts)
// - kv 'drafts': Add to Brainamon captures waiting for Save (src/mobile/capture.svelte.ts; public/sw.js adds shares)
// - files: decrypted mirror files kept by version (card-row parts, notes, chats, canvases, vectors;
//   src/mobile/source/mirror.ts), so a refresh downloads only what the manifest says changed
// - changes: what the phone did while reading the mirror (saved links, favourites, edits, notes,
//   Wiskit chats, synthesized notes), queued, then sent to the PC as change files
//   (src/mobile/mirror/changes.ts)
// Items saved for offline carry `saved` and are never trimmed (src/mobile/offline.ts).
// Thumbnails live in the service worker's cache (public/sw.js). Every call swallows a missing or
// blocked IndexedDB (private window) so the page still works from the network alone.
// public/sw.js opens the same database (the share target writes the outbox): keep VERSION and the
// store list in step with it.
import type { FullItem, Row } from './source/types'
import type { Draft } from '../lib/capture'
import type { RawCanvasProposal, CanvasDocument } from './ai/canvas'

const DB = 'brainamon-phone', VERSION = 2
export const ITEM_CAP = 400           // full items kept (a few KB each), beyond the pinned ones
export const PIN_RECENT = 50

export interface StoredItem { id: number; at: number; item: FullItem; report?: string; transcript?: string; pinned?: boolean; saved?: boolean; size?: number; uid?: string }
export interface MirrorEntry { v: string; data: string | ArrayBuffer }
export interface ChangeEntry {
  id?: number; at: number; state: 'queued' | 'sending' | 'sent'; sentAt?: number; chg?: string     // chg: the change file it went in
  stream?: string; seq?: number; legacy?: boolean; resend?: boolean   // paired with a PC: its batch number (mirror/changes.ts)
    op: 'link' | 'details' | 'fav' | 'edit' | 'category_batch' | 'canvas' | 'note' | 'note_append' | 'note_delete' | 'chat' | 'chat_delete' | 'answer' | 'synth' | 'synth_queue' | 'delete'
  op_id?: string; canvas_id?: string; proposal?: RawCanvasProposal; refs?: Record<string, string>; sizes?: Record<string, [number, number]>
  canvasLocal?: { base: CanvasDocument | null; result: CanvasDocument; assets: { uid?: string; file?: string; blob: Blob }[];
    status: 'pending' | 'synced' | 'refused'; reason?: string; pc?: number }   // pc: the PC canvas's modified time when it refused
  uid?: string; url?: string; note?: string; category?: string; on?: boolean; file?: string
  text?: string; when?: string   // note_append: the section's text and its "YYYY-MM-DD HH:MM" (plans/09-add-to-brainamon.md)
  tags?: string               // link: hashtags from an Import (mobile-import/PLAN.md), comma-separated
  creator?: string; desc?: string; thumb?: string        // details: read from the link's page (thumb: base64 JPEG)
  fields?: Record<string, string>; was?: Record<string, unknown> | string; title?: string; body?: string
  stamps?: import('../lib/note-format').Stamp[]          // note: the plan 01 stamp list when the phone changed it
  // Phase 5: a chat asked on the phone, an answer saved as a note, a synthesized or queued note
  slug?: string; name?: string; created?: string; history?: { role: 'user' | 'assistant'; content: string }[]
  source_ids?: number[]; options?: Record<string, unknown>; md?: string; ids?: number[]; topic?: string; sources?: number[]
  turns?: number              // chat_delete: the turns the phone saw (the PC keeps a chat it went on with)
    entries?: { uid: string; from: string; category: string }[]  // one approved Wiskit batch
  pc?: boolean                // delete: the PC deletes the item too (else only the phone hides it)
}
export interface OutboxEntry {
  id?: number; url: string; note: string; category: string; added: number
  state: 'waiting' | 'sent' | 'dup' | 'error'; itemId?: number | null; error?: string; src: string
  tags?: string; type?: string          // Add > More details: sent as an edit once the link is in
}

let dbp: Promise<IDBDatabase | null> | null = null
function open(): Promise<IDBDatabase | null> {
  dbp ??= new Promise(res => {
    try {
      const rq = indexedDB.open(DB, VERSION)
      rq.onupgradeneeded = () => {
        const d = rq.result
        if (!d.objectStoreNames.contains('kv')) d.createObjectStore('kv')
        if (!d.objectStoreNames.contains('items')) d.createObjectStore('items', { keyPath: 'id' })
        if (!d.objectStoreNames.contains('outbox')) d.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true })
        if (!d.objectStoreNames.contains('files')) d.createObjectStore('files')
        if (!d.objectStoreNames.contains('changes')) d.createObjectStore('changes', { keyPath: 'id', autoIncrement: true })
      }
      rq.onsuccess = () => res(rq.result)
      rq.onerror = () => res(null)
      rq.onblocked = () => res(null)
    } catch { res(null) }
  })
  return dbp
}

function tx<T>(store: string, mode: IDBTransactionMode, f: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  return open().then(d => new Promise<T | undefined>(res => {
    if (!d) return res(undefined)
    try {
      const t = d.transaction(store, mode), s = t.objectStore(store)
      const rq = f(s)
      let out: T | undefined
      if (rq) rq.onsuccess = () => { out = rq.result }
      t.oncomplete = () => res(out)
      t.onerror = () => res(undefined)
      t.onabort = () => res(undefined)
    } catch { res(undefined) }
  }))
}

// ── kv ───────────────────────────────────────────────────────────────────────
export const kv = {
  get: <T>(k: string) => tx<T>('kv', 'readonly', s => s.get(k)),
  set: (k: string, v: unknown) => tx('kv', 'readwrite', s => { s.put(v, k) }),
  del: (k: string) => tx('kv', 'readwrite', s => { s.delete(k) }),
}

// Canvas review commits must report storage failures and keep the pending card retryable.
export async function putCanvasPending(key: string, value: unknown, signal?: AbortSignal): Promise<void> {
  const d = await open()
  if (!d) throw new Error('Phone storage is unavailable.')
  await new Promise<void>((resolve, reject) => {
    try {
      signal?.throwIfAborted()
      const t = d.transaction('kv', 'readwrite')
      t.objectStore('kv').put(value, key)
      t.oncomplete = () => resolve()
      t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage did not save the proposal.'))
    } catch (e) { reject(e) }
  })
}

export async function declineCanvasPending(key: string, token: string): Promise<void> {
  const d = await open()
  if (!d) throw new Error('Phone storage is unavailable.')
  await new Promise<void>((resolve, reject) => {
    try {
      const t = d.transaction('kv', 'readwrite'), s = t.objectStore('kv')
      s.get(key).onsuccess = e => {
        if ((e.target as IDBRequest).result?.token !== token) { t.abort(); return }
        s.delete(key)
      }
      t.oncomplete = () => resolve()
      t.onerror = t.onabort = () => reject(t.error || new Error('This proposal is no longer pending.'))
    } catch (e) { reject(e) }
  })
}

export async function approveCanvas(key: string, token: string, entry: ChangeEntry): Promise<number> {
  const d = await open()
  if (!d) throw new Error('Phone storage is unavailable.')
  return new Promise<number>((resolve, reject) => {
    try {
      const t = d.transaction(['changes', 'kv'], 'readwrite'), pending = t.objectStore('kv')
      let id = 0
      pending.get(key).onsuccess = e => {
        if ((e.target as IDBRequest).result?.token !== token) { t.abort(); return }
        t.objectStore('changes').add(entry).onsuccess = r => { id = Number((r.target as IDBRequest).result) }
        pending.delete(key)
      }
      t.oncomplete = () => resolve(id)
      t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage did not apply the canvas.'))
    } catch (e) { reject(e) }
  })
}

// ── full items ───────────────────────────────────────────────────────────────
export const items = {
  get: (id: number) => tx<StoredItem>('items', 'readonly', s => s.get(id)),
  all: () => tx<StoredItem[]>('items', 'readonly', s => s.getAll()).then(v => v ?? []),
  put: (v: StoredItem) => tx('items', 'readwrite', s => { s.put(v) }),
  del: (id: number) => tx('items', 'readwrite', s => { s.delete(id) }),
  clear: () => tx('items', 'readwrite', s => { s.clear() }),
}

// keep favourites (from the current rows), items saved for offline and the PIN_RECENT most recently
// opened; drop the oldest beyond ITEM_CAP
export async function trimItems(favIds: Set<number>) {
  const all = await items.all()
  const keep = new Set<number>(favIds)
  all.filter(s => s.saved).forEach(s => keep.add(s.id))
  all.sort((a, b) => b.at - a.at).slice(0, PIN_RECENT).forEach(s => keep.add(s.id))
  const rest = all.filter(s => !keep.has(s.id)).sort((a, b) => b.at - a.at)
  for (const s of rest.slice(Math.max(0, ITEM_CAP - keep.size))) await items.del(s.id)
}

// ── outbox ───────────────────────────────────────────────────────────────────
export const outbox = {
  all: () => tx<OutboxEntry[]>('outbox', 'readonly', s => s.getAll()).then(v => (v ?? []).sort((a, b) => b.added - a.added)),
  add: (e: OutboxEntry) => tx<IDBValidKey>('outbox', 'readwrite', s => s.add(e)).then(k => (typeof k === 'number' ? k : undefined)),
  put: (e: OutboxEntry) => tx('outbox', 'readwrite', s => { s.put(e) }),
  del: (id: number) => tx('outbox', 'readwrite', s => { s.delete(id) }),
}

// ── capture drafts ───────────────────────────────────────────────────────────
// What is shared to Brainamon or typed on Add waits here until Save, as one record in kv, so closing,
// reloading or being offline loses nothing (plans/09-add-to-brainamon.md). public/sw.js appends shares
// to the same record from the service worker, so every change is one read-modify-write transaction.
export const drafts = {
  all: () => kv.get<Draft[]>('drafts').then(v => v ?? []),
  // f gets the stored list and returns the new one; null when there is no IndexedDB (a private window)
  edit: (f: (list: Draft[]) => Draft[]): Promise<Draft[] | null> => open().then(d => new Promise<Draft[] | null>(res => {
    if (!d) return res(null)
    try {
      const t = d.transaction('kv', 'readwrite'), s = t.objectStore('kv'), g = s.get('drafts')
      let out: Draft[] | null = null
      g.onsuccess = () => { out = f(Array.isArray(g.result) ? g.result : []); s.put(out, 'drafts') }
      t.oncomplete = () => res(out)
      t.onerror = () => res(null)
      t.onabort = () => res(null)
    } catch { res(null) }
  })),
}

// ── the mirror's decrypted files and the phone's queued changes ─────────────
export const files = {
  get: (k: string) => tx<MirrorEntry>('files', 'readonly', s => s.get(k)),
  set: (k: string, v: MirrorEntry) => tx('files', 'readwrite', s => { s.put(v, k) }),
  del: (k: string) => tx('files', 'readwrite', s => { s.delete(k) }),
  keys: () => tx<IDBValidKey[]>('files', 'readonly', s => s.getAllKeys()).then(v => (v ?? []).map(String)),
  clear: () => tx('files', 'readwrite', s => { s.clear() }),
}
export const changes = {
  async forChat(signal?: AbortSignal): Promise<ChangeEntry[]> {
    const d = await open()
    if (!d) throw new Error('Phone storage is unavailable.')
    signal?.throwIfAborted()
    return new Promise((resolve, reject) => {
      try {
        const t = d.transaction('changes', 'readonly')
        const r = t.objectStore('changes').getAll()
        t.oncomplete = () => resolve(r.result)
        t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage could not read the chat queue.'))
      } catch (e) { reject(e) }
    })
  },
  async saveChat(entry: ChangeEntry, signal?: AbortSignal): Promise<number> {
    const d = await open()
    if (!d) throw new Error('Phone storage is unavailable.')
    return new Promise<number>((resolve, reject) => {
      try {
        signal?.throwIfAborted()
        const t = d.transaction('changes', 'readwrite')
        const request = t.objectStore('changes').put(entry)
        let id: number
        request.onsuccess = () => { id = Number(request.result) }
        t.oncomplete = () => resolve(id)
        t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage did not save the chat.'))
      } catch (e) { reject(e) }
    })
  },
  all: () => tx<ChangeEntry[]>('changes', 'readonly', s => s.getAll()).then(v => (v ?? []).sort((a, b) => (a.id ?? 0) - (b.id ?? 0))),
  add: (e: ChangeEntry) => tx<IDBValidKey>('changes', 'readwrite', s => s.add(e)).then(k => (typeof k === 'number' ? k : undefined)),
  put: (e: ChangeEntry) => tx('changes', 'readwrite', s => { s.put(e) }),
  del: (id: number) => tx('changes', 'readwrite', s => { s.delete(id) }),
  // a fresh start without a PC, or a solo library removed from the phone (plans/08-phone-solo.md)
  clear: () => Promise.all([tx('changes', 'readwrite', s => { s.clear() }), kv.del('hidden'), kv.del('delivery')]),   // with what deletes hid
}

// journal entries and kv records saved together, or not at all: rejects when IndexedDB did not save them. Without IndexedDB
// (a private window) the phone keeps its journal in memory, as everywhere in this file.
export async function journal(put: ChangeEntry[], del: number[], set: Record<string, unknown> = {}): Promise<void> {
  const d = await open()
  if (!d) {
    for (const e of put) await changes.put(e)
    for (const id of del) await changes.del(id)
    for (const [k, v] of Object.entries(set)) await kv.set(k, v)
    return
  }
  await new Promise<void>((resolve, reject) => {
    let t: IDBTransaction
    try { t = d.transaction(['changes', 'kv'], 'readwrite') } catch (e) { reject(e); return }
    t.oncomplete = () => resolve()
    t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage did not save the changes.'))
    try {
      const c = t.objectStore('changes'), s = t.objectStore('kv')
      for (const e of put) c.put(e)
      for (const id of del) c.delete(id)
      for (const [k, v] of Object.entries(set)) s.put(v, k)
    } catch (e) {
      try { t.abort() } catch { /* already over */ }        // what was put before the error goes too
      reject(e)
    }
  })
}

export async function updateCanvasChange(entry: ChangeEntry | null, id: number): Promise<void> {
  const d = await open()
  if (!d) throw new Error('Phone storage is unavailable.')
  await new Promise<void>((resolve, reject) => {
    try {
      const t = d.transaction('changes', 'readwrite'), s = t.objectStore('changes')
      if (entry) s.put(entry); else s.delete(id)
      t.oncomplete = () => resolve()
      t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage could not save the canvas result.'))
    } catch (e) { reject(e) }
  })
}

// ── sizes for the More screen ────────────────────────────────────────────────
export async function storageUse(rows: Row[]) {
  const light = JSON.stringify(rows).length
  const full = await items.all()
  const fullBytes = full.reduce((a, s) => a + (s.report?.length ?? 0) + (s.transcript?.length ?? 0) + 1200, 0)
  let thumbs = 0
  try { thumbs = (await (await caches.open('bp-thumbs-v1')).keys()).length } catch { /* no cache API */ }
  let quota = 0, usage = 0
  try { const e = await navigator.storage?.estimate(); quota = e?.quota ?? 0; usage = e?.usage ?? 0 } catch { /* unsupported */ }
  return { light, fullItems: full.length, fullBytes, thumbs, thumbBytes: thumbs * 30 * 1024, quota, usage }
}

// the phone's copy, refetched on the next refresh; queued changes and what was saved for offline stay
export async function wipe() {
  for (const s of await items.all()) if (!s.saved) await items.del(s.id)
  await files.clear()
  for (const k of ['rows', 'cats', 'tints', 'notes', 'mynotes', 'canvases', 'chats', 'synced', 'manifest']) await kv.del(k)
  try { await caches.delete('bp-thumbs-v1') } catch { /* no cache API */ }
}
