// Bundled only into the Android worker. No page, timers, IndexedDB or second WebView.
import { vaultRound, removeLegacy } from '../vault/sync'
import { SKIP_DIRS } from '../vault/merge'
import { isLibraryName } from '../mirror/diagnose'
import { verifyAccess, verifyGrant, ACCESS_LOGICAL, LICENSE_LOGICAL } from '../mirror/license'
import type { MirrorKey } from '../mirror/crypto'

type Call = { id: number; method: string; args: unknown[] }
const calls: Call[] = [], pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>()
let serial = 0, wake: (() => void) | undefined, finished: unknown
export function rpc<T = any>(method: string, ...args: unknown[]): Promise<T> {
  return new Promise((resolve, reject) => {
    const id = ++serial
    pending.set(id, { resolve, reject }); calls.push({ id, method, args }); wake?.()
  })
}
export async function next(): Promise<string> {
  if (!calls.length && finished === undefined) await new Promise<void>(resolve => { wake = resolve })
  wake = undefined
  return JSON.stringify(calls.length ? { calls: calls.splice(0) } : { finished })
}
export function answer(id: number, value: unknown, error?: string) {
  const p = pending.get(id); pending.delete(id)
  if (error) p?.reject(new Error(error)); else p?.resolve(value)
}

const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
export function b64(a: Uint8Array): string {
  const parts: string[] = []
  for (let start = 0; start < a.length; start += 12288) {
    let out = ''
    for (let i = start; i < Math.min(start + 12288, a.length); i += 3) {
      const n = (a[i] << 16) | ((a[i + 1] ?? 0) << 8) | (a[i + 2] ?? 0)
      out += alphabet[n >>> 18] + alphabet[n >>> 12 & 63] + (i + 1 < a.length ? alphabet[n >>> 6 & 63] : '=') + (i + 2 < a.length ? alphabet[n & 63] : '=')
    }
    parts.push(out)
  }
  return parts.join('')
}
export function unb64(s: string): Uint8Array {
  const raw = s.replace(/=+$/, ''), out = new Uint8Array(Math.floor(raw.length * 6 / 8))
  let n = 0, bits = 0, at = 0
  for (const c of raw) {
    const v = alphabet.indexOf(c)
    if (v < 0) throw new Error('Invalid binary data')
    n = (n << 6) | v; bits += 6
    if (bits >= 8) { bits -= 8; out[at++] = n >>> bits & 255 }
  }
  return out
}
// JavaScriptEngine intentionally has no browser APIs. Only the shared algorithms' required surface.
export function install() {
  const g = globalThis as any
  g.atob ??= (s: string) => Array.from(unb64(s), n => String.fromCharCode(n)).join('')
  g.btoa ??= (s: string) => b64(Uint8Array.from(s, c => c.charCodeAt(0)))
  g.TextEncoder ??= class { encode(s = '') { return Uint8Array.from(unescape(encodeURIComponent(s.replace(/[\uD800-\uDFFF]/gu, '\ufffd'))), c => c.charCodeAt(0)) } }
  g.TextDecoder ??= class { decode(a: Uint8Array) { return decodeURIComponent(Array.from(a, n => '%' + n.toString(16).padStart(2, '0')).join('')) } }
  g.DOMException ??= class extends Error {}
  g.crypto = { subtle: {
    digest: async (_: string, data: Uint8Array) => (await binary('digest', b64(new Uint8Array(data)))).buffer,
    importKey: async (format: string, data: Uint8Array, algorithm: unknown) => ({ format, data: b64(data), algorithm }),
    verify: async (algorithm: unknown, key: unknown, signature: Uint8Array, data: Uint8Array) => rpc('verify', algorithm, key, b64(signature), b64(data)),
  } }
}
async function binary(method: string, ...args: unknown[]): Promise<Uint8Array> {
  const result = await rpc<{ data?: string; binary?: string }>(method, ...args)
  if (result.binary) return new Uint8Array(await (globalThis as any).android.consumeNamedDataAsArrayBuffer(result.binary))
  return unb64(result.data ?? '')
}
export interface Config { fp: string; verifier: string; solo: boolean; device: string; vault: boolean; force: boolean; legacy: boolean; watermark: boolean }
export function start(config: Config) {
  finished = undefined
  void round(config).then(value => { finished = { ok: true, value }; wake?.() }, e => { finished = { ok: false, error: String(e.message) }; wake?.() })
}

async function round(config: Config) {
  const key = {
    fingerprint: config.fp,
    name: (name: string) => rpc<string>('name', name),
    contentId: (data: Uint8Array) => rpc<string>('contentId', b64(data)),
    open: (name: string, data: Uint8Array) => binary('open', name, b64(data)),
    openText: async (name: string, data: Uint8Array) => new TextDecoder().decode(await key.open(name, data)),
    seal: (name: string, data: Uint8Array) => binary('seal', name, b64(data)),
  } as unknown as MirrorKey
  const read = <T>(name: string) => rpc<T | undefined>('load', name)
  const save = (name: string, value: unknown) => rpc<void>('save', name, value)
  let expires = 0
  let watermark = config.watermark
  const authorize = async () => {
    if (config.solo) return
    if (expires > Date.now() / 1000 + 30) return
    let logical = ACCESS_LOGICAL
    let found = await rpc<{ id: string }[]>('find', await key.name(logical))
    if (!found.length && !watermark) { logical = LICENSE_LOGICAL; found = await rpc('find', await key.name(logical)) }
    if (found.length !== 1) throw new Error('access')
    const sealed = await binary('get', found[0].id, 20000)
    const plaintext = await key.openText(logical, sealed)
    try {
      const envelope = JSON.parse(plaintext)
      expires = logical === ACCESS_LOGICAL ? await verifyAccess(envelope, config.fp, config.verifier) : await verifyGrant(envelope, config.fp, config.verifier)
      if (logical === ACCESS_LOGICAL) { await rpc('watermark'); watermark = true }
      await rpc('authorized', expires)
    } catch { throw new Error('access') }
  }
  const drive = {
    list: async () => { await authorize(); return rpc<{ id: string; name: string; size: number }[]>('list') },
    get: async (id: string) => { await authorize(); return binary('get', id) },
    remove: async (id: string) => { await authorize(); await rpc('remove', id) },
    create: async (name: string, data: Uint8Array) => { await authorize(); return rpc<string>('create', name, b64(data)) },
    update: async (id: string, data: Uint8Array) => { await authorize(); await rpc('update', id, b64(data)) },
  }
  await authorize()
  const upload = async () => {
    for (;;) {
      const batch = await rpc<{ id: string; name: string; data: string } | null>('outbox')
      if (!batch) return
      await authorize()
      await rpc('progress', 'drive', 0)
      // Same immutable name/bytes across retries, including an upload whose response was lost.
      const found = await rpc<{ id: string }[]>('find', batch.name)
      const sealed = unb64(batch.data)
      let id = found[0]?.id
      if (id) {
        const remote = await drive.get(id)
        if (b64(remote) !== batch.data) throw new Error('conflict')
      } else id = await drive.create(batch.name, sealed)
      await rpc('delivered', batch.id, id)
      if (config.solo) await save('solo/' + batch.name, { name: batch.name, doc: JSON.parse(await key.openText(batch.name, sealed)) })
    }
  }
  await upload()
  await rpc('progress', 'drive', 0)
  if (config.solo) {
    const prefix = 'solo-' + await key.name('phone-backup') + '-'
    const all = await drive.list()
    await save('pc-mirror', all.some(f => isLibraryName(f.name)))
    const listing = all.filter(f => f.name.startsWith(prefix) || /^chg-[a-f0-9]{32}$/.test(f.name))
    for (const f of listing) {
      if (await read('solo/' + f.name)) continue
      try {
        const data = await key.openText(f.name, await drive.get(f.id))
        await save('solo/' + f.name, { name: f.name, doc: JSON.parse(data) })
      } catch (e) { if (f.name.startsWith(prefix) || (e as Error).message !== 'key') throw e }
    }
    await save('solo-list', listing.map(f => f.name))
  } else {
    const found = await rpc<{ id: string }[]>('find', await key.name('manifest.json'))
    if (found.length !== 1) throw new Error('library')
    const manifest = JSON.parse(await key.openText('manifest.json', await drive.get(found[0].id)))
    if (manifest.format !== 1 || (manifest.reader ?? 1) > 1 || !manifest.files || typeof manifest.files !== 'object') throw new Error('update')
    const want = Object.entries(manifest.files).filter(([p]) => /^(library\/|notes\/|chats\/|search\/text-)/.test(p) || ['canvases/index.json', 'canvas-results.json'].includes(p))
      .sort(([a], [b]) => Number(b.startsWith('library/')) - Number(a.startsWith('library/')) || (a < b ? 1 : a > b ? -1 : 0))
    let count = 0
    for (const [logical, file] of want) {
      const f = file as { id?: string; n: string; v: string }
      const cacheKey = `file/${logical}/${f.v}`
      const cached = await read<{ v: string }>(cacheKey)
      if (cached?.v !== f.v) {
        const id = f.id ?? (await rpc<{ id: string }[]>('find', f.n))[0]?.id
        if (!id) throw new Error('library')
        const data = await key.open(logical, await drive.get(id))
        const text = logical.endsWith('.gz') ? await rpc<string>('gunzip', b64(data)) : new TextDecoder().decode(data)
        await save(cacheKey, { v: f.v, data: text })
      }
      await rpc('progress', 'drive', ++count / Math.max(1, want.length))
    }
    // Publish a snapshot only when all of its required files are durable.
    await save('manifest', manifest)
  }
  let vault: unknown = null
  if (config.vault && !config.solo) {
    const fs = {
      list: () => rpc<{ path: string; size: number; mtime: number }[]>('fsList', SKIP_DIRS),
      read: (path: string) => binary('fsRead', path),
      write: async (path: string, data: Uint8Array, expected?: string | null) => { await authorize(); await rpc('fsWrite', path, b64(data), expected, expected !== undefined) },
      remove: async (path: string, expected?: string) => { await authorize(); await rpc('fsRemove', path, expected) },
      has: (path: string) => rpc<boolean>('fsHas', path),
    }
    if (config.legacy) await save('vault-legacy-moved', await removeLegacy({ fs }))
    const messages = new Map<string, { key: string; params?: Record<string, unknown> }>()
    const result = await vaultRound({ drive, key, fs, device: config.device, force: config.force,
      load: () => read('vault-state'), save: state => save('vault-state', state),
      words: (key, params) => { const id = JSON.stringify([key, params]); messages.set(id, { key, params }); return id },
      progress: (_step, done, total, overall = 0, display, files) => {
        void rpc('progress', 'vault', overall, { key: display && messages.get(display)?.key, done, total, files }).catch(() => {})
      },
    })
    // Persist message data, so reopening uses the phone's current language.
    const display = { reason: messages.get(result.reason), summary: messages.get(result.summary) }
    vault = { ...result, reason: display.reason ? '' : result.reason, summary: display.summary ? '' : result.summary, display }
    await save('vault-result', vault)
  }
  await upload()
  return { vault }
}
