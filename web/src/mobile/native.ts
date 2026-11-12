// The phone page inside the Android app (projects/mobile-app/PLAN.md Phase 6, mobile-shell/): the
// same page as the PWA, with five things the app does natively through the Brainamon plugin
// (mobile-shell/android/.../BrainamonPlugin.java). In a browser every function here falls back to
// what the PWA already does, so nothing else needs to know which one it runs in.
// - secrets: the pairing (mirror key, AI keys) and the Google token in Android Keystore-encrypted
//   storage; read once before the page starts (initNative), then sync. In a browser they live in
//   IndexedDB, sealed with a key the page cannot read back (below), never in plain localStorage
// - googleToken: Drive sign-in with Google's Android flow (a browser redirect cannot work in an app)
// - scanQr: the pairing QR from inside the app
// - onShared: links shared to Brainamon from other apps (the PWA's share target is the service worker)
// - onSharedFile: pictures, PDFs and .md / .txt files shared to Brainamon (projects/wiskit-files)
// - aiFetch: the AI providers through native HTTP when the WebView's fetch is refused (CORS), whole
//   incremental Wiskit bytes with cancellation; other calls retain buffered HTTP
// - linkGet / linkImage: a saved link's page and picture for the phone's link details (plans/09-link-details.md)
// - onBackButton / exitApp: the hardware back button (milestone-2026-10-14/plans/E-phone-fixes.md)
// - openObsidian: an obsidian:// link, and whether an app took it (See my knowledge graph)
// - deviceName: the phone's name for the PC's Phones list (D13, mirror/phone-record.ts)
// - siteState / siteOpen / sitePending / siteClear / siteForget: the phone site reader's window and run files
//   (projects/phone-site-reader)
import { App } from '@capacitor/app'
import { Capacitor, CapacitorHttp, registerPlugin, type PluginListenerHandle } from '@capacitor/core'
import { withTimeout } from './wait'
import { languageSecretsSaved, languageWorkChanged } from './language-switch.ts'
import { SKIP_DIRS } from './vault/merge'       // the folders the native listing skips (.brainamon/ among them, spec 1b)
import type { SiteId } from './sites'

interface BrainamonPlugin {
  networkStatus(): Promise<NetworkStatus>
  addListener(ev: 'networkChange', fn: (e: NetworkStatus) => void): Promise<PluginListenerHandle>
  aiStreamStart(o: { id: string; url: string; headers: Record<string, string>; body: string; connectTimeoutMs: number; requestTimeoutMs: number }): Promise<void>
  aiStreamCancel(o: { id: string }): Promise<void>
  aiStreamAck(o: { id: string; seq: number }): Promise<void>
  addListener(ev: 'aiStream', fn: (e: AiStreamEvent) => void): Promise<PluginListenerHandle>
  secretGet(o: { key: string }): Promise<{ value: string | null }>
  secretSet(o: { key: string; value: string | null }): Promise<void>
  googleToken(o: { silent?: boolean; account?: string; choose?: boolean }): Promise<{ token: string; expiresIn: number }>
  scanQr(): Promise<{ text: string }>
  addListener(ev: 'shared', fn: (e: { text: string }) => void): Promise<PluginListenerHandle>
  addListener(ev: 'sharedFile', fn: (e: { name?: string; type?: string; data?: string; error?: string }) => void): Promise<PluginListenerHandle>
  vaultPick(): Promise<{ uri: string; name: string }>
  vaultList(o: { uri: string; skip: string[] }): Promise<{ files: { path: string; size: number; mtime: number }[] }>
  vaultStat(o: { uri: string; path: string }): Promise<{ exists: boolean }>
  vaultRead(o: { uri: string; path: string; offset: number; length: number }): Promise<{ data: string; eof: boolean }>
  vaultWrite(o: { uri: string; path: string; data: string; append: boolean }): Promise<void>
  vaultFinish(o: { uri: string; tmp: string; path: string }): Promise<void>
  vaultDelete(o: { uri: string; path: string }): Promise<void>
  openUri(o: { uri: string }): Promise<{ opened: boolean }>
  clipboardText(): Promise<{ text: string }>
  deviceName(): Promise<{ name: string }>
  siteState(): Promise<SiteReaderState>
  siteOpen(o: { site: SiteId; known: string[]; full: boolean; complete: boolean; unsave: boolean }): Promise<SiteRunResult>
  sitePending(o: { site: SiteId; offset: number; max: number }): Promise<SitePage>
  siteClear(o: { site: SiteId }): Promise<void>
  siteForget(o: { site: SiteId }): Promise<{ result: 'deleted' | 'cleared' }>
}
type AiStreamEvent = { id: string; kind: 'headers'; status: number; headers: Record<string, string> }
  | { id: string; kind: 'chunk'; seq: number; data: string }
  | { id: string; kind: 'done' }
  | { id: string; kind: 'error'; message: string }

export const isApp = Capacitor.isNativePlatform()
const B = registerPlugin<BrainamonPlugin>('Brainamon')
export const appInfo = () => withTimeout(App.getInfo(), 5000, 'Could not read app info.')

export interface NetworkStatus { connected: boolean; type: string }
export const networkStatus = () => withTimeout(B.networkStatus(), 5000, 'Could not check the network.', 'timeout')
export const onNetworkChange = (fn: (e: NetworkStatus) => void) => B.addListener('networkChange', fn)

// D13 (P5): the name the PC's Phones list shows: Android's device name (Settings > About phone), else maker and model;
// "Phone browser" in a browser, "Android phone" when the app cannot say
export async function deviceName(): Promise<string> {
  if (!isApp) return 'Phone browser'
  try { return (await withTimeout(B.deviceName(), 5000, 'Could not read the device name.')).name || 'Android phone' }
  catch { return 'Android phone' }
}

// the keys mirror/pairing.ts keeps (PAIR, TOKEN)
const SECRET_KEYS = ['bp-pair', 'bp-gtoken']
const cache = new Map<string, string | null>()
let saved: Promise<unknown> = Promise.resolve()           // writes in order; secretsSaved() waits for them
let saveFailed = false
const failedSecretKeys = new Set<string>()
const secretFailed = (key: string) => { saveFailed = true; failedSecretKeys.add(key) }
const secretSaved = (key: string) => {
  if (failedSecretKeys.delete(key) && !failedSecretKeys.size) { saveFailed = false; languageSecretsSaved() }
}
export const secretsHaveFailures = (): boolean => failedSecretKeys.size > 0

// In a browser (audit 2026-10-11, H2): IndexedDB, each value sealed with AES-GCM under a key the
// page generated as non-extractable. WebCrypto never hands that key's bytes to script, so a copy of
// the storage (a backup, a synced profile, a read of localStorage by another page on the host)
// opens nothing. A script running in this page could still ask it to decrypt: mobile.html keeps
// scripts to the page's own files (Content-Security-Policy), and the setup guide treats the
// browser as the second choice after the app. Values an older build left in localStorage move over
// on the first start and are removed there. With no IndexedDB (some private windows) it falls back
// to localStorage, as before.
const VAULT_DB = 'bp-secrets', VAULT_STORE = 'kv', WRAP = 'wrap'
let vault: { db: IDBDatabase; key: CryptoKey } | null = null
interface Sealed { iv: Uint8Array; ct: ArrayBuffer }

function req<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error) })
}
function tx(db: IDBDatabase, mode: IDBTransactionMode) { return db.transaction(VAULT_STORE, mode).objectStore(VAULT_STORE) }
function vaultWrite(db: IDBDatabase, action: (store: IDBObjectStore) => void): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    try {
      const t = db.transaction(VAULT_STORE, 'readwrite')
      t.oncomplete = () => resolve()
      t.onerror = t.onabort = () => reject(t.error || new Error('Phone storage could not save the secret.'))
      action(t.objectStore(VAULT_STORE))
    } catch (error) { reject(error) }
  })
}
async function openVault(): Promise<{ db: IDBDatabase; key: CryptoKey }> {
  const open = indexedDB.open(VAULT_DB, 1)
  open.onupgradeneeded = () => open.result.createObjectStore(VAULT_STORE)
  const db = await req(open)
  let key = await req(tx(db, 'readonly').get(WRAP)) as CryptoKey | undefined
  if (!key) {
    key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
    await vaultWrite(db, store => { store.put(key!, WRAP) })
  }
  return { db, key }
}
async function vaultGet(k: string): Promise<string | null> {
  const v = vault!
  const rec = await req(tx(v.db, 'readonly').get(k)) as Sealed | undefined
  if (!rec) return null
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: rec.iv as Uint8Array<ArrayBuffer>, additionalData: new TextEncoder().encode(k) }, v.key, rec.ct)
  return new TextDecoder().decode(plain)
}
async function vaultSet(k: string, value: string | null) {
  const v = vault!
  const iv = value === null ? null : crypto.getRandomValues(new Uint8Array(12))
  const ct = value === null ? null : await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv!, additionalData: new TextEncoder().encode(k) }, v.key, new TextEncoder().encode(value))
  await vaultWrite(v.db, store => {
    if (value === null) store.delete(k)
    else store.put({ iv: iv!, ct: ct! } satisfies Sealed, k)
  })
}
const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string | null) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); return true } catch { secretFailed(k); return false } },
}

export async function initNative() {
  if (isApp) {
    // Publish together only after the bounded read succeeds; late native callbacks cannot change a retry.
    const values = await withTimeout(Promise.all(SECRET_KEYS.map(async k => (await B.secretGet({ key: k })).value)),
      10_000, 'Saved sign-in did not respond in 10 seconds.')
    SECRET_KEYS.forEach((k, i) => cache.set(k, values[i]))
    return
  }
  try {
    if (typeof indexedDB === 'undefined' || !crypto?.subtle) return
    vault = await openVault()
    for (const k of SECRET_KEYS) {
      const legacy = ls.get(k)
      if (legacy !== null) {                // an older build's copy, or one written while IndexedDB was out
        await vaultSet(k, legacy)
        ls.set(k, null)
        cache.set(k, legacy)
      } else {
        cache.set(k, await vaultGet(k).catch(() => null))
      }
    }
  } catch {
    vault = null                            // localStorage, as before; keys already read stay in the cache
  }
}

export const secrets = {
  get(k: string): string | null {
    if (isApp || vault || cache.has(k)) return cache.get(k) ?? null
    return ls.get(k)
  },
  set(k: string, v: string | null) {
    languageWorkChanged()
    cache.set(k, v)
    if (isApp) saved = saved.then(() => withTimeout(B.secretSet({ key: k, value: v }), 10_000, 'Saving sign-in timed out.')).then(() => secretSaved(k)).catch(() => secretFailed(k))
    else if (vault) saved = saved.then(() => vaultSet(k, v)).then(() => secretSaved(k)).catch(() => secretFailed(k))
    else if (ls.set(k, v)) secretSaved(k)
  },
}

// before the page reloads or leaves: the secrets written so far are on disk
export async function secretsSaved(): Promise<void> {
  await saved
  if (saveFailed) { saveFailed = false; throw Object.assign(new Error('Sign-in could not be saved securely. Retry before leaving this page.'), { code: 'write' }) }
}

// Drive access token with Google's Android sign-in; `silent` never shows anything. `account`: ask
// for that Google account only; `choose`: show Google's account chooser even if it remembers one
// Google's sheet waits for the person, but not for ever: an answer that never comes (the sheet closed, Play
// services stuck) used to leave Connect and Change account working with no end. A late answer is dropped.
export function googleToken(silent: boolean, o: { account?: string; choose?: boolean } = {}): Promise<{ token: string; expiresIn: number }> {
  return withTimeout(B.googleToken({ silent, account: o.account || '', choose: !!o.choose }), silent ? 20_000 : 120_000,
    silent ? 'Google did not answer the sign-in renewal in 20 seconds.' : 'Google did not answer in 2 minutes (its sheet may have closed). Try again.', silent ? 'renewal-timeout' : 'timeout')
}

// the pairing QR's text, or '' when the user backed out
export async function scanQr(): Promise<string> {
  try { return (await B.scanQr()).text || '' } catch (e) {
    if ((e as { code?: string }).code === 'cancelled') return ''
    throw e
  }
}

export function onShared(fn: (text: string) => void) {
  if (isApp) B.addListener('shared', e => { if (e.text) fn(e.text) })
}

// a picture, PDF or .md / .txt file shared to Brainamon (projects/wiskit-files plan 04): base64, or an error
export function onSharedFile(fn: (f: { name: string; type: string; data: string; error: string }) => void) {
  if (isApp) B.addListener('sharedFile', e => fn({ name: e.name || '', type: e.type || '', data: e.data || '', error: e.error || '' }))
}

// the hardware back button (Android app only). Registering a listener turns the default off: the
// handler must go back or leave itself. `canGoBack`: the WebView has a page behind this one.
export function onBackButton(fn: (canGoBack: boolean) => void) {
  if (isApp) App.addListener('backButton', e => fn(e.canGoBack))
}
export function exitApp() { if (isApp) App.exitApp() }

// an obsidian:// link: in the app, true / false for "Obsidian opened" / "not installed"; a browser
// cannot tell, so null there
export async function openObsidian(uri: string): Promise<boolean | null> {
  if (isApp) {
    try { return (await B.openUri({ uri })).opened } catch { /* an older APK without openUri */ }
  }
  location.href = uri
  return null
}

// the clipboard's text for a Paste button: the Android WebView refuses navigator.clipboard.readText,
// so the app reads it natively (an older APK without clipboardText falls back to the page's own)
export async function readClipboard(): Promise<string> {
  if (isApp) {
    try { return (await B.clipboardText()).text } catch { /* an older APK */ }
  }
  return navigator.clipboard.readText()
}

// fetch for the AI providers (ai/providers.ts setFetch): the WebView's own fetch first, so answers
// stream; if the provider refuses the app's origin (a TypeError, as CORS failures are), the same
// request through native HTTP; Wiskit uses the bounded streaming bridge below.
export async function aiFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init)
  } catch (e) {
    if (!isApp || (e as Error).name === 'AbortError' || init.signal?.aborted || navigator.onLine === false) throw e
  }
  if (typeof init.body === 'string') {
    let streaming = false
    try { streaming = JSON.parse(init.body).stream === true } catch { /* non-JSON request */ }
    if (streaming) return nativeStream(url, init)
  }
  const r = await CapacitorHttp.request({
    url, method: init.method || 'GET', headers: init.headers as Record<string, string>,
    data: typeof init.body === 'string' ? init.body : undefined, responseType: 'text', readTimeout: 180000,
  })
  if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  const body = typeof r.data === 'string' ? r.data : JSON.stringify(r.data)
  return new Response(body, { status: r.status, headers: r.headers })
}

function nativeStream(url: string, init: RequestInit): Promise<Response> {
  const id = crypto.randomUUID(), signal = init.signal
  return new Promise<Response>((resolve, reject) => {
    let listener: PluginListenerHandle | undefined, controller: ReadableStreamDefaultController<Uint8Array>
    let ended = false, headers = false, next = 0, pending: number | null = null, demand = false
    let bytes: Uint8Array<ArrayBufferLike> | undefined
    const cancelNative = () => { void B.aiStreamCancel({ id }).catch(() => {}) }
    const cleanup = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      if (listener) void listener.remove()
    }
    const fail = (e: unknown) => {
      if (ended) return
      ended = true; cleanup(); cancelNative()
      if (headers) controller.error(e)
      else reject(e)
    }
    const abort = () => fail(signal?.reason ?? new DOMException('Stopped.', 'AbortError'))
    const ack = () => {
      if (pending === null || ended || !demand || !bytes) return
      const seq = pending; pending = null; demand = false
      controller.enqueue(bytes)
      bytes = undefined
      void B.aiStreamAck({ id, seq }).catch(fail)
    }
    const timer = setTimeout(() => fail(new DOMException('Native AI stream timed out.', 'TimeoutError')), 60000)
    const body = new ReadableStream<Uint8Array>({
      start(c) { controller = c },
      pull() { demand = true; ack() },
      cancel() { if (!ended) { ended = true; cleanup(); cancelNative() } },
    }, { highWaterMark: 0 })
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) { abort(); return }
    void (async () => {
      try {
        listener = await B.addListener('aiStream', e => {
          if (ended || e.id !== id) return
          try {
            if (e.kind === 'headers') {
              if (headers) throw new Error('Duplicate native stream headers.')
              const response = new Response(body, { status: e.status, headers: e.headers })
              headers = true; resolve(response)
            } else if (e.kind === 'chunk') {
              if (!headers || e.seq !== next++ || pending !== null) throw new Error('Invalid native stream sequence.')
              pending = e.seq
              bytes = fromB64(e.data)
              ack()
            } else if (e.kind === 'done') {
              if (!headers || pending !== null) throw new Error('Native stream ended before consumption.')
              ended = true; cleanup(); controller.close()
            } else fail(new Error(e.message))
          } catch (e) { fail(e) }
        })
        if (ended) { await listener.remove(); return }
        await B.aiStreamStart({ id, url, headers: init.headers as Record<string, string>, body: init.body as string,
          connectTimeoutMs: 10000, requestTimeoutMs: 60000 })
        if (signal?.aborted) { cancelNative(); abort() }
      } catch (e) {
        const error = e as { code?: string; message?: string }
        fail(error.code === 'UNIMPLEMENTED' || /not implemented|not available/i.test(error.message || '')
          ? new Error('This Android app needs an update to stream Wiskit through native HTTP.') : e)
      }
    })()
  })
}

// ── link details (plans/09-link-details.md): a saved link's page and its picture through native
// HTTP (no CORS), with a plain User-Agent: Facebook answers a browser's with HTTP 400 ──
const LINK_UA = 'Brainamon/1.0 (link preview)'

export async function linkGet(url: string): Promise<{ status: number; text: string }> {
  if (!isApp) throw new Error('Link details need the Android app.')
  const r = await CapacitorHttp.request({
    url, method: 'GET', headers: { 'User-Agent': LINK_UA, 'Accept-Language': 'en' }, responseType: 'text', connectTimeout: 10000, readTimeout: 15000,
  })
  return { status: r.status, text: typeof r.data === 'string' ? r.data : JSON.stringify(r.data) }
}

// a picture as bytes (native HTTP hands binary back as base64, with line breaks)
export async function linkImage(url: string): Promise<Uint8Array> {
  if (!isApp) throw new Error('Link details need the Android app.')
  const r = await CapacitorHttp.request({
    url, method: 'GET', headers: { 'User-Agent': LINK_UA }, responseType: 'blob', connectTimeout: 10000, readTimeout: 15000,
  })
  if (r.status !== 200 || typeof r.data !== 'string') throw Object.assign(new Error(`picture: HTTP ${r.status}`), { status: r.status })
  return fromB64(r.data.replace(/\s+/g, ''))
}

// ── vault sync: the folder the user picked (BrainamonPlugin.java vault*; the Android app only) ──
const CHUNK = 3 * 1024 * 1024
const toB64 = (a: Uint8Array) => { let s = ''; for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000)); return btoa(s) }
const fromB64 = (s: string) => Uint8Array.from(atob(s), c => c.charCodeAt(0))

export async function vaultPick(): Promise<{ uri: string; name: string }> {
  if (!isApp) throw new Error('Vault sync needs the Android app.')
  return B.vaultPick()
}

export function vaultFs(uri: string) {
  return {
    async list() { return (await B.vaultList({ uri, skip: SKIP_DIRS })).files },
    async has(path: string) { return (await B.vaultStat({ uri, path })).exists },
    async read(path: string) {
      const parts: Uint8Array[] = []
      for (let offset = 0; ; offset += CHUNK) {
        const r = await B.vaultRead({ uri, path, offset, length: CHUNK })
        parts.push(fromB64(r.data))
        if (r.eof) break
      }
      const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0))
      let at = 0
      for (const p of parts) { out.set(p, at); at += p.length }
      return out
    },
    async write(path: string, data: Uint8Array) {
      const tmp = path + '.vsync-tmp'
      await B.vaultDelete({ uri, path: tmp })
      for (let at = 0; at === 0 || at < data.length; at += CHUNK) {
        await B.vaultWrite({ uri, path: tmp, data: toB64(data.subarray(at, at + CHUNK)), append: at > 0 })
      }
      await B.vaultFinish({ uri, tmp, path })
    },
    async remove(path: string) { await B.vaultDelete({ uri, path }) },
  }
}

// ── the phone site reader (projects/phone-site-reader). siteState() is
// null in a browser, in a build without the reader, or when the app does not answer; the other calls are
// made only after it answered ──
export interface SiteReaderState {
  supported: boolean
  sites: Record<SiteId, { signedIn: boolean; pending: number; forgetting: boolean; reader: boolean }>
}
export interface SiteRunResult { reason: string; added: number; known: number; other: number; dropped: number; unsaveFailed?: boolean }
export interface SitePage { items: unknown[]; total: number }

export async function siteState(): Promise<SiteReaderState | null> {
  if (!isApp) return null
  try { return await withTimeout(B.siteState(), 5000, 'The site reader did not answer.') } catch { return null }
}
// resolves when the site window closes: no time limit, the user signs in, reads or stops
export const siteOpen = (site: SiteId, known: string[], full: boolean, complete: boolean, unsave = false) => B.siteOpen({ site, known, full, complete, unsave })
export const sitePending = (site: SiteId, offset: number, max: number) =>
  withTimeout(B.sitePending({ site, offset, max }), 15000, 'The site reader did not answer.')
export const siteClear = (site: SiteId) => withTimeout(B.siteClear({ site }), 5000, 'The site reader did not answer.')
export async function siteForget(site: SiteId): Promise<'deleted' | 'cleared'> {
  return (await withTimeout(B.siteForget({ site }), 15000, 'The site reader did not answer.')).result
}
