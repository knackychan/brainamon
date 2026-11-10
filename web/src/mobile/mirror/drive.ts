import { network, SyncPaused, syncPaused, syncSignal } from '../network.svelte'
import { confirmAccessV2, pairing } from './pairing'
import { CHANGE_PREFIX, MirrorKey } from './crypto'
import { ACCESS_EXPIRED, ACCESS_LOGICAL, LICENSE_LOGICAL, LICENSE_REQUIRED, LicenseRequired, noteAccess, verifyAccess, verifyGrant } from './license'
import { PHONE_RECOVERY_PREFIX, RECOVERY_LIMIT } from './recovery-envelope'
import { CloudCancelled, cloudCheckpoint, cloudReadSignal, cloudRevision } from './gate'

// The phone's Google Drive calls: the app data folder only (scope drive.appdata), the same REST
// calls as the desktop's library/drive_client.py, plus `about` (which account signed in). Reads go by
// file id (the manifest lists every file's id), so the only searches are for the manifest and the AI keys of a new pairing, plus
// this phone's record (mirror/phone-record.ts). The writes are change files and that record (made once, then replaced in
// place); the deletes are those keys once taken and the record at Unpair. Without a PC (plans/08-phone-solo.md)
// the phone also lists the folder to read its change files back.

export class DriveError extends Error {
  status: number
  constructor(msg: string, status = 0) { super(msg); this.status = status }
}
// no token, or Google refused it: the page shows "Connect Google Drive"
export class NeedsSignIn extends DriveError {}

export interface DriveFile { id: string; size: number }

// a refused access check, for every screen: the app bar lamp, Settings > Backup & phones and the line under the app bar
// (mirror/phone-state.ts reads network.licenseKind and licenseAt)
function refused(e: LicenseRequired): LicenseRequired {
  network.licenseLocked = true; network.licenseProblem = e.message; network.licenseKind = e.kind; network.licenseAt = e.at
  return e
}

const CALL_TIMEOUT = 20_000
const LIMITED_TRIES = 6               // a rate-limit refusal (403 rateLimit, 429, 5xx): backoff 0.8 s doubling ..
const MAX_DELAY = 32_000              // .. up to 32 s, Google's advice

// a multipart/related upload body (files.create and files.update): the JSON metadata, then the bytes
function multipart(meta: object, data: Uint8Array): [Uint8Array<ArrayBuffer>, string] {
  const b = 'bp' + Math.random().toString(16).slice(2)
  const head = new TextEncoder().encode(`--${b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(meta)}\r\n--${b}\r\nContent-Type: application/octet-stream\r\n\r\n`)
  const tail = new TextEncoder().encode(`\r\n--${b}--`)
  const body = new Uint8Array(head.length + data.length + tail.length)
  body.set(head, 0); body.set(data, head.length); body.set(tail, head.length + data.length)
  return [body, b]
}

export class Drive {
  private revision = cloudRevision()
  private base: string
  private token: () => string | null
  private onAuthFail: () => void
  private grant: Promise<number> | null = null
  private bound: string | null = null
  private backups = new Set<string>()
  private recoveryFiles = new Set<string>()
  private listed = new Map<string, string>()      // id -> name from the last list(): what getRecovered may read
  constructor(base: string, token: () => string | null, onAuthFail: () => void) {
    const u = new URL(base)
    if (u.origin !== 'https://www.googleapis.com' && !(import.meta.env?.DEV === true && u.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname))) throw new DriveError('Untrusted Drive endpoint')
    this.base = base.replace(/\/$/, ''); this.token = token; this.onAuthFail = onAuthFail
    const p = pairing()
    if (p) this.bound = `${p.k}:${p.l}:${!!p.solo}`
  }

  checkpoint() { cloudCheckpoint(this.revision) }

  // `timeout`: how long Google may take to start answering (ms). A call that gets no answer used to wait for
  // the WebView's own limit, minutes per try and four tries, so a button could look stuck for good.
  async authorize(backup = false): Promise<number> {
    this.checkpoint()
    const p = pairing()
    if (!p || (p.solo ? !backup : !p.l)) throw refused(new LicenseRequired())
    const identity = `${p.k}:${p.l}:${!!p.solo}`
    this.bound ??= identity
    if (this.bound !== identity) throw new LicenseRequired()
    if (p.solo) { network.licenseLocked = false; return Infinity }
    if (!this.grant) this.grant = (async () => {
      const key = await MirrorKey.fromText(p.k)
      let logical = ACCESS_LOGICAL
      const lookup = async (path: string) => {
        const name = await key.name(path)
        const q = new URLSearchParams({ spaces: 'appDataFolder', q: `name = '${name}'`, fields: 'files(id,size),incompleteSearch,nextPageToken', pageSize: '10' })
        const found = await (await this.call(`/drive/v3/files?${q}`, {}, 0, CALL_TIMEOUT, 'control')).json() as { files?: { id: string; size?: string }[]; incompleteSearch?: boolean; nextPageToken?: string }
        if (!found || !Array.isArray(found.files) || found.incompleteSearch !== undefined && found.incompleteSearch !== false
            || found.nextPageToken !== undefined && found.nextPageToken !== '') throw new LicenseRequired()
        return found as { files: { id: string; size?: string }[] }
      }
      let found = await lookup(logical)
      if (!found.files.length) {
        if (pairing()?.accessVersion === 2) throw new LicenseRequired(LICENSE_REQUIRED)
        logical = LICENSE_LOGICAL
        found = await lookup(logical)
      }
      if (!found.files.length) throw new LicenseRequired(LICENSE_REQUIRED)
      if (found.files.length !== 1 || Number(found.files[0].size) > 20000) throw new LicenseRequired()
      const r = await this.call(`/drive/v3/files/${encodeURIComponent(found.files[0].id)}?alt=media`, {}, 0, CALL_TIMEOUT, 'control')
      const rd = r.body?.getReader(), parts: Uint8Array[] = []
      let size = 0
      if (!rd) throw new LicenseRequired()
      try {
        for (;;) {
          const { value, done } = await rd.read()
          if (done) break
          size += value.length
          if (size > 20000) throw new LicenseRequired()
          parts.push(value)
        }
      } finally { await rd.cancel() }
      const data = new Uint8Array(size)
      let at = 0
      for (const part of parts) { data.set(part, at); at += part.length }
      const envelope = await key.openJSON<{ body: string; sig: string }>(logical, data).catch(() => { throw new LicenseRequired() })
      const expires = logical === ACCESS_LOGICAL ? await verifyAccess(envelope, p.f, p.l!) : await verifyGrant(envelope, p.f, p.l!)
      const current = pairing()
      if (!current || `${current.k}:${current.l}:${!!current.solo}` !== identity) throw new LicenseRequired()
      if (logical === LICENSE_LOGICAL && current.accessVersion === 2) throw new LicenseRequired(LICENSE_REQUIRED)
      if (logical === ACCESS_LOGICAL) {
        await confirmAccessV2(current)
        const saved = pairing()
        if (!saved || `${saved.k}:${saved.l}:${!!saved.solo}` !== identity) throw new LicenseRequired()
      }
      return expires
    })()
    try {
      const expires = await this.grant
      if (expires <= Date.now() / 1000) throw new LicenseRequired(ACCESS_EXPIRED)
      network.licenseLocked = false
      network.licenseProblem = ''
      network.licenseKind = ''
      network.licenseAt = 0
      noteAccess(p.f)
      return expires
    }
    catch (e) { if (e instanceof LicenseRequired) refused(e); throw e }
    finally { this.grant = null }
  }

  private async call(path: string, init: RequestInit = {}, retries = 3, timeout = CALL_TIMEOUT, access: 'paired' | 'backup' | 'control' = 'paired'): Promise<Response> {
    this.checkpoint()
    const t = this.token()
    const p = pairing()
    const identity = (p: ReturnType<typeof pairing>) => p ? `${p.k}:${p.l}:${!!p.solo}:${p.g ?? ''}` : ''
    const original = identity(p)
    const current = () => {
      this.checkpoint()
      if (identity(pairing()) !== original || this.token() !== t) throw new CloudCancelled()
    }
    if (!t) throw new NeedsSignIn('Connect Google Drive to read your library.', 401)
    let delay = 800
    for (let i = 0; ; i++) {
      current()
      init.signal?.throwIfAborted()               // the caller stopped it (Unpair): no further try
      const allowed = await syncSignal()
      const expires = access === 'control' || path.startsWith('/drive/v3/about?') ? Infinity : await this.authorize(access === 'backup')
      current()
      if (expires <= Date.now() / 1000) throw new LicenseRequired()
      let r: Response
      const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), timeout)
      try {
        r = await fetch(this.base + path, { ...init, redirect: 'error', signal: AbortSignal.any([ctl.signal, allowed, ...(!init.method || init.method === 'GET' ? [cloudReadSignal()] : []), ...(init.signal ? [init.signal] : [])]), headers: { ...(init.headers || {}), Authorization: `Bearer ${t}` } })
      } catch (e) {
        current()
        if (init.signal?.aborted) throw e
        if (allowed.aborted || syncPaused()) throw new SyncPaused()
        const why = ctl.signal.aborted ? `no answer in ${Math.round(timeout / 1000)} s` : (e as Error).message
        if (i >= retries) throw new DriveError(`Google Drive is out of reach (${why})`)
        await new Promise(res => setTimeout(res, delay)); delay *= 2
        continue
      } finally { clearTimeout(timer) }
      try { current() } catch (e) { await r.body?.cancel(); throw e }
      if (r.ok) return r
      if (r.status === 401) { this.onAuthFail(); throw new NeedsSignIn('Google Drive wants you to sign in again.', 401) }
      let why = '', reason = ''
      try {
        const err = ((await r.json()) as { error?: { message?: string; errors?: { reason?: string }[] } }).error
        why = err?.message ?? ''; reason = err?.errors?.[0]?.reason ?? ''
      } catch { /* no JSON */ }
      // Google answers a burst of reads (a canvas of 200 pictures, a vault round) with 403 rateLimitExceeded
      // a rate refusal (429, 403 rateLimit) did nothing on Google's side, so it gets up to LIMITED_TRIES even for an
      // upload: many files go at once (vault/sync.ts PARALLEL) and it passes in seconds. A 5xx keeps `retries`.
      const slow = r.status === 429 || (r.status === 403 && /rateLimit/i.test(reason))
      const limited = slow || r.status >= 500
      if (limited && i < (slow ? Math.max(retries, LIMITED_TRIES) : retries)) { await new Promise(res => setTimeout(res, delay + Math.random() * delay)); delay = Math.min(delay * 2, MAX_DELAY); continue }
      throw new DriveError(`Google Drive answered ${r.status}${why ? ': ' + why : ''}`, r.status)
    }
  }

  // the signed-in Google account's address (the drive.appdata scope is enough, as on the desktop)
  async about(): Promise<string> {
    const d = await (await this.call('/drive/v3/about?fields=user(emailAddress)', {}, 1, 10_000)).json() as { user?: { emailAddress?: string } }
    this.checkpoint()
    return d.user?.emailAddress ?? ''
  }

  async listPhoneRecovery(): Promise<(DriveFile & { name: string })[]> {
    if (!pairing()?.solo) throw new DriveError('Use a standalone phone backup for phone recovery.')
    this.recoveryFiles.clear()
    const files: (DriveFile & { name: string })[] = []
    let page = ''
    const names = new Set<string>()
    do {
      const q = new URLSearchParams({ spaces: 'appDataFolder', q: `trashed = false and name contains '${PHONE_RECOVERY_PREFIX}'`, fields: 'nextPageToken,files(id,name,size)', pageSize: '100' })
      if (page) q.set('pageToken', page)
      const d = await (await this.call(`/drive/v3/files?${q}`, {}, 3, CALL_TIMEOUT, 'backup')).json() as { nextPageToken?: string; files?: { id: string; name: string; size?: string }[] }
      for (const f of d.files ?? []) {
        if (!/^vi-phone-recovery-[a-f0-9]{32}-[a-f0-9]{32}\.json$/.test(f.name) || !Number.isSafeInteger(Number(f.size)) || Number(f.size) <= 0 || Number(f.size) > RECOVERY_LIMIT) throw new DriveError('Invalid phone recovery file in Drive.')
        if (names.has(f.name)) throw new DriveError('Duplicate phone recovery records found. Keep your saved recovery file and retry later.')
        names.add(f.name); files.push({ ...f, size: Number(f.size) })
      }
      page = d.nextPageToken ?? ''
      if (files.length > 100 || page) throw new DriveError('Too many phone recovery records. Keep your saved recovery file or original code.')
    } while (page)
    for (const f of files) this.recoveryFiles.add(f.id)
    this.checkpoint()
    return files
  }

  async getPhoneRecovery(id: string): Promise<string> {
    if (!pairing()?.solo || !this.recoveryFiles.has(id)) throw new DriveError('Find the available phone recovery setups first.')
    const r = await this.call(`/drive/v3/files/${encodeURIComponent(id)}?alt=media`, {}, 3, CALL_TIMEOUT, 'backup')
    const reader = r.body?.getReader()
    if (!reader) throw new DriveError('Could not read the phone recovery file.')
    const chunks: Uint8Array[] = []
    let size = 0
    try {
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        size += value.length
        if (size > RECOVERY_LIMIT) throw new DriveError('Recovery file is too large.')
        chunks.push(value)
      }
    } finally { await reader.cancel() }
    const bytes = new Uint8Array(size)
    let at = 0
    for (const chunk of chunks) { bytes.set(chunk, at); at += chunk.length }
    this.checkpoint()
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  }

  // the file with this (hashed) name, or null
  async find(name: string): Promise<DriveFile | null> {
    const q = new URLSearchParams({ spaces: 'appDataFolder', q: `name = '${name}'`, fields: 'files(id,size)', pageSize: '10' })
    const d = await (await this.call(`/drive/v3/files?${q}`)).json() as { files?: { id: string; size?: string }[] }
    const f = d.files?.[0]
    return f ? { id: f.id, size: +(f.size || 0) } : null
  }

  // every file with this (hashed) name: this phone's record made again after a lost answer leaves two (phone-record.ts)
  async named(name: string, signal?: AbortSignal): Promise<DriveFile[]> {
    const q = new URLSearchParams({ spaces: 'appDataFolder', q: `name = '${name}'`, fields: 'files(id,size)', pageSize: '10' })
    const d = await (await this.call(`/drive/v3/files?${q}`, { signal })).json() as { files?: { id: string; size?: string }[] }
    return (d.files ?? []).map(f => ({ id: f.id, size: +(f.size || 0) }))
  }

  // every file in the app data folder (a phone without a PC reads its change files back, and looks for
  // a PC's mirror): [{id, name, size}]
  async list(): Promise<(DriveFile & { name: string })[]> {
    const p = pairing()
    if (p?.solo) await this.authorize(true)
    const prefix = p?.solo ? await (await MirrorKey.fromText(p.k)).soloPrefix() : ''
    this.backups.clear()
    this.listed.clear()
    const out: (DriveFile & { name: string })[] = []
    let page = ''
    for (;;) {
      const q = new URLSearchParams({ spaces: 'appDataFolder', q: 'trashed = false', fields: 'nextPageToken,incompleteSearch,files(id,name,size)', pageSize: '1000' })
      if (page) q.set('pageToken', page)
      const d = await (await this.call(`/drive/v3/files?${q}`, {}, 3, CALL_TIMEOUT, 'backup')).json() as { nextPageToken?: string; incompleteSearch?: boolean; files?: { id: string; name: string; size?: string }[] }
      this.checkpoint()
      if (!Array.isArray(d.files) || d.incompleteSearch) throw new DriveError('Google Drive returned an incomplete listing. Retry before changing a backup.')
      for (const f of d.files ?? []) {
        out.push({ id: f.id, name: f.name, size: +(f.size || 0) })
        this.listed.set(f.id, f.name)
        // Older standalone backups used chg- names; decryption still requires their original key.
        if (prefix && (f.name.startsWith(prefix) || f.name.startsWith(CHANGE_PREFIX))) this.backups.add(f.id)
      }
      page = d.nextPageToken ?? ''
      if (!page) return out
    }
  }

  async get(id: string, onProgress?: (got: number, total: number) => void): Promise<Uint8Array> {
    const r = await this.call(`/drive/v3/files/${encodeURIComponent(id)}?alt=media`, {}, 3, CALL_TIMEOUT, this.backups.has(id) ? 'backup' : 'paired')
    if (!onProgress || !r.body) {
      const bytes = new Uint8Array(await r.arrayBuffer())
      this.checkpoint()
      return bytes
    }
    const total = +(r.headers.get('Content-Length') || 0), parts: Uint8Array[] = []
    const rd = r.body.getReader()
    let got = 0
    for (;;) {
      const { value, done } = await rd.read()
      this.checkpoint()
      if (done) break
      parts.push(value); got += value.length
      onProgress(got, total)
    }
    const out = new Uint8Array(got)
    let at = 0
    for (const p of parts) { out.set(p, at); at += p.length }
    return out
  }

  // reconnect (mirror/phone-reconnect.ts): one listed backup file of the key the user just recovered, which this
  // pairing's own prefix does not cover. That key proves the namespace, as the pairing's key does for `get`.
  async getRecovered(id: string, key: MirrorKey): Promise<Uint8Array> {
    const name = this.listed.get(id)
    if (!pairing()?.solo || !name || !(name.startsWith(await key.soloPrefix()) || name.startsWith(CHANGE_PREFIX))) throw new DriveError('Find the backup first.')
    const r = await this.call(`/drive/v3/files/${encodeURIComponent(id)}?alt=media`, {}, 3, CALL_TIMEOUT, 'backup')
    const bytes = new Uint8Array(await r.arrayBuffer())
    this.checkpoint()
    return bytes
  }

  // Explicit standalone management only: a PC pairing can never use this deletion capability.
  async removeSolo(id: string, prefix: string): Promise<void> {
    this.checkpoint()
    const name = this.listed.get(id)
    if (!pairing()?.solo || !/^solo-[a-f0-9]{32}-$/.test(prefix) || !name ||
        !name.startsWith(prefix) || !/^[a-f0-9]{32}$/.test(name.slice(prefix.length))) throw new DriveError('List and select a standalone phone backup first.')
    try { await this.call(`/drive/v3/files/${encodeURIComponent(id)}`, { method: 'DELETE' }, 1, CALL_TIMEOUT, 'backup') }
    catch (e) { if (!(e instanceof DriveError) || e.status !== 404) throw e }
  }

  async removeSoloMany(ids: string[], prefix: string, progress?: (done: number) => void): Promise<void> {
    this.checkpoint()
    if (ids.length > 100 || new Set(ids).size !== ids.length || !pairing()?.solo || !/^solo-[a-f0-9]{32}-$/.test(prefix)
        || ids.some(id => !/^[A-Za-z0-9_-]+$/.test(id) || !new RegExp(`^${prefix}[a-f0-9]{32}$`).test(this.listed.get(id) || ''))) throw new DriveError('List and select a standalone phone backup first.')
    if (!ids.length) return
    const boundary = 'brainamon-' + crypto.randomUUID()
    const body = ids.map((id, i) => `--${boundary}\r\nContent-Type: application/http\r\nContent-ID: <delete-${i}>\r\n\r\nDELETE /drive/v3/files/${id} HTTP/1.1\r\n\r\n`).join('') + `--${boundary}--\r\n`
    const response = await this.call('/batch/drive/v3', { method: 'POST', body, headers: { 'Content-Type': `multipart/mixed; boundary=${boundary}` } }, 3, CALL_TIMEOUT, 'backup')
    const separator = /boundary=(?:"([^"]+)"|([^;\s]+))/i.exec(response.headers.get('content-type') || '')
    if (!separator) throw new DriveError('Invalid Drive batch response. Retry to check remaining files.')
    const results = new Map<number, number>()
    for (const part of (await response.text()).split('--' + (separator[1] || separator[2])).slice(1, -1)) {
      const identity = /Content-ID:\s*<response-delete-(\d+)>/i.exec(part)
      const status = /\r?\nHTTP\/\d(?:\.\d)? (\d{3})(?: |\r?\n)/.exec(part)
      const index = Number(identity?.[1])
      if (!identity || !status || index >= ids.length || results.has(index)) throw new DriveError('Invalid Drive batch response. Retry to check remaining files.')
      results.set(index, Number(status[1]))
    }
    if (results.size !== ids.length) throw new DriveError('Incomplete Drive batch response. Retry to check remaining files.')
    let done = 0
    const failed: string[] = []
    ids.forEach((id, i) => { if ([200, 204, 404].includes(results.get(i)!)) progress?.(++done); else failed.push(id) })
    for (const id of failed) { await this.removeSolo(id, prefix); progress?.(++done) }
  }

  // A replacement uses a fresh key and keeps the selected old copy until read-back verification.
  async createReplacement(key: MirrorKey, name: string, data: Uint8Array): Promise<string> {
    if (!pairing()?.solo || !name.startsWith(await key.soloPrefix()) || !/^solo-[a-f0-9]{32}-[a-f0-9]{32}$/.test(name)) throw new DriveError('Only standalone phone backups can be replaced here.')
    const [body, b] = multipart({ name, parents: ['appDataFolder'] }, data)
    const r = await this.call('/upload/drive/v3/files?uploadType=multipart&fields=id', {
      method: 'POST', body, headers: { 'Content-Type': `multipart/related; boundary=${b}` },
    }, 0, CALL_TIMEOUT + Math.ceil(body.length / 50_000) * 1000, 'backup')
    const result = await r.json() as { id: string }
    this.checkpoint()
    return result.id
  }

  async remove(id: string, signal?: AbortSignal): Promise<void> {
    try { await this.call(`/drive/v3/files/${encodeURIComponent(id)}`, { method: 'DELETE', signal }, 1) } catch (e) {
      if (!(e instanceof DriveError) || e.status !== 404) throw e        // already gone is fine
    }
  }

  // a new file in the app data folder (multipart upload); returns its id. `retries` 0: a lost answer is not sent again
  // (the upload may have gone through; the phone's record finds it at its next write, mirror/phone-record.ts)
  async create(name: string, data: Uint8Array, signal?: AbortSignal, retries = 1): Promise<string> {
    const p = pairing()
    if (!p) throw new LicenseRequired()
    if (p?.solo) await this.authorize(true)
    if (p?.solo) {
      const key = await MirrorKey.fromText(p.k), prefix = await key.soloPrefix()
      const recoveryPrefix = PHONE_RECOVERY_PREFIX + await key.name('phone-recovery') + '-'
      const recovery = name.startsWith(recoveryPrefix) && /^[a-f0-9]{32}\.json$/.test(name.slice(recoveryPrefix.length)) && data.length <= RECOVERY_LIMIT
      if (!recovery && (!name.startsWith(prefix) || !/^[0-9a-f]{32}$/.test(name.slice(prefix.length)))) throw new DriveError('Standalone phones can only upload their own backup and recovery files.')
    }
    const [body, b] = multipart({ name, parents: ['appDataFolder'] }, data)
    // the answer comes after the upload: time for the bytes (about 50 KB/s at the least) on top of the usual wait
    const r = await this.call('/upload/drive/v3/files?uploadType=multipart&fields=id', {
      method: 'POST', body, headers: { 'Content-Type': `multipart/related; boundary=${b}` }, signal,
    }, retries, CALL_TIMEOUT + Math.ceil(body.length / 50_000) * 1000, 'backup')
    const result = await r.json() as { id: string }
    this.checkpoint()
    return result.id
  }

  // replaces a file's bytes in place (files.update, multipart PATCH; metadata {} keeps its name and folder): this phone's
  // record only (mirror/phone-record.ts). A phone without a PC replaces nothing.
  async update(id: string, data: Uint8Array, signal?: AbortSignal): Promise<void> {
    const p = pairing()
    if (!p) throw new LicenseRequired()
    if (p.solo) throw new DriveError('Standalone phones do not replace files in Google Drive.')
    const [body, b] = multipart({}, data)
    await this.call(`/upload/drive/v3/files/${encodeURIComponent(id)}?uploadType=multipart&fields=id`, {
      method: 'PATCH', body, headers: { 'Content-Type': `multipart/related; boundary=${b}` }, signal,
    }, 1, CALL_TIMEOUT + Math.ceil(body.length / 50_000) * 1000)
  }
}
