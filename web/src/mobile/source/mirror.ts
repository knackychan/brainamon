// MirrorSource: the phone reads the encrypted Google Drive mirror the PC uploads (PLAN.md Phase 4),
// so it works with the PC off. Same interface as DesktopSource (./types.ts), so no screen knows
// which one it talks to.
//
// - The manifest (found by its hashed name) lists every file with its Drive id and version; a
//   refresh downloads only the files whose version changed (kept decrypted in IndexedDB, store
//   `files`): card-row parts, categories, notes, chats, canvases, the search vectors.
// - Thumbnails come in packs of 100 (thumbs/pack-NNNN.bin) when a card scrolls into view: the
//   service worker (public/sw.js) asks this page for a missing /thumb/<id>, the page downloads and
//   opens the pack and puts every JPEG of it in the thumbnail cache. Canvas images the same way
//   (/mirror/canvas-uploads/<name>).
// - Full items (report, transcript) are fetched when opened; the Item screen keeps them (store.ts).
// - What the phone does (links, favourites, edits, My Notes) is queued (../mirror/changes.ts),
//   shown at once, and sent to the PC as a sealed change file.
// - Related by meaning compares the mirror's int8 vectors on the phone, with no AI call.
// - Wiskit Quick, Smart search and Synthesize call the AI from the phone with the user's own keys
//   (Phase 5, ../ai/): the phone ranks its copy like the desktop (bm25 over the search text, the
//   vectors, the same fusion) and builds the same prompts; chats, answers saved as notes and
//   synthesized notes go back as change files.
// - Wiskit Deep (plans/07-wiskit-deep.md, ../ai/deep.ts) runs the librarian's tools on the phone: the
//   topics, the websites and tools index and the topic and note-section vectors come from two more
//   mirror files fetched the first time Deep runs (search/deep.json.gz, search/aux.bin); read_items
//   fetches the items' files from Drive for their reports.
// - Without a PC (pairing `solo`, plans/08-phone-solo.md) there is no manifest: the phone's change
//   journal is the whole library (links, favourites, edits, notes, chats), its change files stay in
//   Drive as the backup, and a refresh reads back the ones this phone does not hold (another phone on
//   the same recovery code, or this one after a reset). The AI settings come bundled (PHONE_AI).
import { CHANGE_PREFIX, MirrorKey, MirrorKeyError, nearest, readPack, readVectors, type Vectors } from '../mirror/crypto'
import { Drive, NeedsSignIn } from '../mirror/drive'
import { SyncPaused, syncPaused, network } from '../network.svelte'
import { nativeCache, nativeReceipt, nativeRound, nativeUploads, nativeSyncError, nativeSyncPolicy, nativeSyncSupported, seedNativeVault, stageNative } from '../sync/native.svelte'
import { transferId, syncOwner } from '../sync/transfer'
import { Changes, type ChangeEntry } from '../mirror/changes'
import { deviceId, dropToken, forgetKeys, GOOGLE_DRIVE, requeueWaiting, takeKeys, takeRequeue, token, tokenProject, type Pairing } from '../mirror/pairing'
import { diagnoseNoLibrary, isLibraryName, projectOf, type NoLibraryWhy } from '../mirror/diagnose'
import { CONTROL_LOGICALS, LicenseRequired } from '../mirror/license'
import { cleanLink } from '../links'
import { libraryIds } from './find'
import { canvasWire, declineCanvasPending, files, items as stored, kv, putCanvasPending } from '../store'
import { baseKey, CHANGED, contextCheck, identity, version } from '../canvas/compose'
import type { CanvasDraftContext } from './types'
import { deviceName, isApp, linkGet, linkImage, secretsSaved, vaultFs } from '../native'
import { linkInfo } from '../linkinfo'
import { importChanges, type Saved } from '../imports'
import { PIC_HINT_KEEP_MS, postPicOk, picturePlan, postKey, type PicHint } from '../sites'
import { pcStatus, removeLegacy, vaultRound, type PcStatus, type Env as VaultEnv, type Result as VaultResult } from '../vault/sync'
import { beginCloudChange, CloudCancelled, cloudCheckpoint, cloudRevision, cloudStopped, endCloudChange, reconnecting, stopCloudWork } from '../mirror/gate'
import { finishReconnect, recordPublish } from '../mirror/phone-reconnect'
import { resendPending } from '../mirror/resend'
import { dropPhoneRecord as dropRecord, syncPhoneRecord } from '../mirror/phone-record'
import { PhoneLibrary, type TextRow } from '../ai/library'
import { answerTitle, autoName, citedIds, citedNotes, Quick, strip, type Item, type Note, type Turn } from '../ai/quick'
import { clean, Synth } from '../ai/synth'
import { hybridRank, SMART_LIMIT, topk } from '../ai/search'
import { AiError, askAgent, CLOUD, complete, embed, listModels, pdfText, transcribe, vision, type Endpoints, type Provider } from '../ai/providers'
import { ATTACH_PROMPT, decodeText, DIGEST_PROMPT, mediaType, PDF_PROMPT, stamp, withSection, type Picked } from '../files'
import { ASK, DEEP, PHONE_AI, SYNTH } from '../ai/prompts'
import { appendLanguage } from '../ai/language'
import { lang, t, type Key, type Lang } from '../../lib/i18n/index'
import { CATEGORIZE_TOKENS, categorizePrompt, DESCRIBE_TOKENS, describePrompt, hasDescribeContent, mergeTags, NO_CONTENT, parseCategory, type ItemText } from '../ai/describe'
import { auxRows, deepTurn, describeCall, Librarian, noteSections, PROFILE_FILE, profileOf, readAux, systemPrompt, topicTexts, type AuxVectors, type Cluster, type Resource } from '../ai/deep'
import { applyCanvasLocal, canonJson, canvasHash, canvasView, checkCanvas, normalizeCanvas, type CanvasDocument, type RawCanvasProposal, type CanvasProposal } from '../ai/canvas'
import type { AiInfo, AskEvent, CanvasDoc, CanvasRow, Category, CategoryProposal, PhoneCanvasProposal, Chat, ChatRow, FullItem, MobileSource, MyNote, NoteRow, OpenNote, Row } from './types'
import { head as noteHead, parseStamps, plain, wordCount, type Stamp } from '../../lib/note-format'
import { checkRename, renameNotes, RENAME_NEEDS_PC } from '../../lib/note-category'
import type { Preview } from '../../lib/capture'
import { clearRun, dropWork, endLane, endWork, queueWork, startWork } from '../work.svelte'
import { say, UndoRefused, type ToolWords, type ToolsUndo } from '../tools'

export interface Manifest {
  format: number; reader?: number; published: number; items: number; embedding_model: string; videos: string; canvases: boolean
  video_chunk: number; canvas_change?: number; note_category?: number; applied?: Record<string, number>; files: Record<string, { n: string; v: string; size: number; id?: string; integrity?: number; bytes?: number; sha256?: string }>
  // server/delivery.py: the PC applies numbered change files once each; receipts per phone stream
  delivery?: number; receipts?: Record<string, { device: string; seq: number; digests?: Record<string, string>; want?: number }>
}
// library/meta.json; `ai` is core/ai_client.phone_settings
export interface AiSettings {
  ask: { default: string; models: Record<string, { id: string; label: string }[]> }
  synth: { provider: string; model: string }; embedding_model: string; ask_max_tokens: number; cloud_min_tokens: number
  agent_max_tokens?: number; agent_max_rounds?: number; transcription_model?: string; retired?: string[]
}
interface Meta { categories: { name: string; color: string }[]; items: number; topic_notes?: string[]; ai?: AiSettings; obsidian_vault?: string; obsidian_notes?: string }
export type MRow = Row & { uid?: string; tint?: string }

// `why`: which cause the phone could tell (mirror/diagnose.ts); the message is its words
export class NoMirror extends Error {
  why: NoLibraryWhy | null
  constructor(message: string, why: NoLibraryWhy | null = null) { super(message); this.why = why }
}
export { NeedsSignIn }

// The mirror format this phone app reads (library/mirror.py READER). A copy that needs a newer reader is
// not opened: the phone keeps its last copy, and `tooOld.fn` lets the page ask for an app update.
export const READER = 1
export const UPDATE_APP = 'The PC uploaded the library in a newer format. Update Brainamon on this phone to see new changes; the copy already here still works.'
export class PhoneTooOld extends Error { constructor() { super(UPDATE_APP) } }
export const tooOld = { fn: () => {} }

export const THUMB_CACHE = 'bp-thumbs-v1', MIRROR_CACHE = 'bp-mirror-v1'
const PIC_GAP_MS = 8000, PIC_JITTER_MS = 4000   // between two pictures of the slow queue (plans/09-link-details.md step 13)
const HINT_GAP_MS = 1500, HINT_JITTER_MS = 1000 // after a picture from a site's own picture link (projects/phone-site-reader)
const PIC_HINTS = 'site-pics'                   // kv: those links by phone link (sites.ts PicHint), never in a change file
const LINK_THUMB_PX = 400          // a link's picture rides in a change file: as wide as the PC's thumbnails (library/importers.py)
const NO_KEY = 'Wiskit needs an AI key on this phone: on the PC open Settings > Backup & phones > Add a phone, tick your Anthropic or OpenAI key under Also send, then pair this phone again with the new code.'
const NO_TEXT = 'The PC has not uploaded the search text yet: update Brainamon on the PC and let it upload once.'
const PROVIDER_LABEL: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI' }
const Q = new Quick(ASK), S = new Synth(SYNTH)
const AI_PICK = 'bp-ai'
// Settings > Wiskit > Refresh: the models each key can use, after the PC's lists ({provider: [{id,label}]})
const AI_FOUND = 'bp-ai-found'
const DEEP_TIP = 'Tip: create a note titled "About me" in My Notes (goals, equipment, level, constraints) and Deep mode will tailor its answers to it.'
// without a PC (plans/08-phone-solo.md)
const SOLO_NO_KEY = 'Wiskit needs an AI key on this phone: add your Anthropic or OpenAI key under Settings > Wiskit on this phone.'
const SOLO_SMART = 'Smart search needs the PC: it indexes the library by meaning. Keyword search works on this phone.'
// Synthesize (projects/phone-solo-synthesize): no ticked source has a part to fold (synth.ts parts)
const NO_SOURCE_TEXT = 'None of the selected sources have any text to synthesize yet: a report, an AI description, a transcript, a caption or a note on the card.'
const SOLO_MANIFEST: Manifest = { format: 1, published: 0, items: 0, embedding_model: '', videos: 'off', canvases: false, video_chunk: 0, files: {} }

// a gzip-compressed mirror file (search/text-NNN.json.gz), opened as text
async function gunzip(data: Uint8Array): Promise<string> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream('gzip'))
  return new Response(stream).text()
}
// knowledge/ask_chats._slugify_name
const chatSlug = (name: string) => name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60).replace(/-+$/, '') || 'chat'

// run `f` over `list`, `n` at a time
async function pool<T, R>(list: T[], n: number, f: (t: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(list.length)
  let i = 0
  await Promise.all(Array.from({ length: Math.min(n, list.length) }, async () => {
    while (i < list.length) { const k = i++; out[k] = await f(list[k]) }
  }))
  return out
}

// knowledge.split_frontmatter
export function splitFront(text: string): [Record<string, string>, string] {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n)+/)
  if (!m) return [{}, text]
  const meta: Record<string, string> = {}
  for (const line of m[1].split(/\r?\n/)) {
    const i = line.indexOf(':')
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return [meta, text.slice(m[0].length)]
}

// knowledge.note_snippet
function snippet(body: string, max = 140): string {
  const lines: string[] = []
  for (const raw of body.split('\n')) {
    const line = raw.trim()
    if (!line) { if (lines.length) break; continue }
    lines.push(line.replace(/^#+\s*/, '').replace(/^[-*]\s+/, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*_`]/g, ''))
    if (lines.length >= 3) break
  }
  const s = lines.join(' ')
  return s.length > max ? s.slice(0, max).trimEnd() + '…' : s || '(no content)'
}

const isoNow = (ms = Date.now()) => { const d = new Date(ms - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 19) }
const slug = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'note'
const hex = (n: number) => [...crypto.getRandomValues(new Uint8Array(n))].map(b => b.toString(16).padStart(2, '0')).join('')
const MIME: Record<string, string> = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif' }

interface NoteFile { file: string; meta: Record<string, string>; body: string }

export class MirrorSource implements MobileSource {
  readonly kind = 'mirror' as const
  readonly label = 'Drive'
  readonly pair: Pairing
  readonly drive: Drive
  readonly changes = new Changes()
  manifest: Manifest | null = null
  lastError = ''
  private key: Promise<MirrorKey>
  private meta: Meta | null = null
  private base: MRow[] = []                    // the mirror's rows
  private rowsNow: MRow[] = []                 // with the phone's changes on top
  private byId = new Map<number, MRow>()
  private texts = new Map<number, { report: string; transcript: string; notes: string }>()
  private vec: { v: string; data: Vectors } | null = null
  private inflight = new Map<string, Promise<unknown>>()
  private flushT = 0
  private nativeScope = ''
  private nativeInit: Promise<boolean> | null = null
  private staging: Promise<string[]> | null = null
  private stageAgain = false
  private nativeDirty = false
  private looked = 0                           // the last read of the manifest's rows (rows, watch)
  pcMirror = false                             // solo: Drive also holds a PC's mirror (pair with it instead)
  round: { at: number; ok: boolean; error: string } | null = null   // solo: the last backup round (send, then read back), null none yet
  private mine = new Set<string>()             // solo: change files this phone uploaded this session
  private unreadable = new Set<string>()       // solo: change files sealed with another key
  private unresolvedCanvases = new Set<string>()
  private supersededCanvases = new Set<string>()  // a refused phone copy the PC's later edits replaced on screen
  private proposalQueue: Promise<unknown> = Promise.resolve()
  private canvasReceipts: Record<string, { canvas_id: string; state: 'applied' | 'refused'; reason: string; hash: string }> = {}

  get solo() { return !!this.pair.solo }
  // canvas changes go up only to a PC that says it takes them (or to the solo journal)
  get canvasSync() { return this.solo || this.manifest?.canvas_change === 1 }
  // paired again (mirror/resend.ts): nothing goes until a fresh manifest from this pairing was read
  get resendPending() { return !this.solo && resendPending(this.pair) }
  // PH8's count (mirror/phone-state.ts `resending`)
  get resending() { return this.solo ? 0 : this.changes.resending(this.canvasSync, this.resendPending) }

  // D13 (mirror/phone-record.ts): the PC's Phones list hears this phone is in sync after a complete read of the rows,
  // or a look that found the same upload again. Its errors never become the read's (lastError).
  private full = -1                            // the manifest `published` the rows were last read whole from
  recorded: Promise<unknown> = Promise.resolve()
  private recordSoon() {
    if (this.solo) return
    this.recorded = (async () => syncPhoneRecord(this.drive, await this.key, this.pair, deviceId(), await deviceName()))()
      .catch(() => undefined)
  }
  // Unpair (More): the record goes first, best effort and at most 3 s; Unpair goes on whatever happens here
  async dropPhoneRecord(): Promise<void> {
    if (this.solo) return
    try { await dropRecord(new Drive(this.pair.d || GOOGLE_DRIVE, () => token(this.pair), dropToken), await this.key, this.pair, deviceId()) } catch { /* Unpair goes on */ }
  }

  private words?: ToolWords
  constructor(pair: Pairing, words?: ToolWords) {
    this.words = words
    this.pair = pair
    if (pair.backupTask) void stopCloudWork()
    this.drive = new Drive(pair.d || GOOGLE_DRIVE, () => token(pair), () => dropToken())
    this.key = MirrorKey.fromText(pair.k)
    navigator.serviceWorker?.addEventListener('message', e => this.onWorker(e))
    window.addEventListener('online', () => this.flushSoon(0))
  }

  // ── the manifest and the files ─────────────────────────────────────────────
  loadManifest(): Promise<Manifest> { return this.once('manifest', () => this.readManifest()) }
  private async readManifest(): Promise<Manifest> {
    if (this.solo) return (this.manifest = SOLO_MANIFEST)
    const key = await this.key
    let m: Manifest
    if (await this.nativeReady()) {
      await this.runNative()
      const snapshot = await nativeCache<Manifest>(this.nativeScope, 'manifest')
      if (!snapshot) throw new NoMirror('The library has not finished downloading.')
      m = snapshot
    } else {
      const f = await this.drive.find(await key.name('manifest.json'))
      if (!f) throw await this.noLibrary(key)
      m = await key.openJSON<Manifest>('manifest.json', await this.drive.get(f.id))
    }
    this.drive.checkpoint()
    // Sent changes still overlay the cached copy; retain them until a compatible refresh.
    if ((m.reader ?? 1) > READER) { tooOld.fn(); throw new PhoneTooOld() }
    this.manifest = m
    await kv.set('manifest', m)
    if (m.files['canvas-results.json']) {
      try { this.canvasReceipts = JSON.parse(await this.cached('canvas-results.json')) }
      catch { this.canvasReceipts = {} }
    } else this.canvasReceipts = {}
    // paired again: this read is the fresh one the resend waits for; what goes again goes now
    if (await this.changes.prune(m.applied?.[deviceId()] ?? 0, m, this.pair)) this.flushSoon()
    return m
  }

  // no manifest: look in the app data folder to tell why (diagnose.ts), instead of one guess for every cause
  private async noLibrary(key: MirrorKey): Promise<NoMirror> {
    // the PC's access confirmation for this pairing is no library content (every read passed it to get here:
    // mirror/drive.ts authorize)
    const access = new Set(await Promise.all(CONTROL_LOGICALS.map(path => key.name(path))))
    let listed: string[] | null = null, problem = ''
    try { listed = (await this.drive.list()).map(f => f.name).filter(name => !access.has(name)) } catch (e) {
      if (e instanceof NeedsSignIn || e instanceof SyncPaused || syncPaused()) throw e
      problem = (e as Error).message
    }
    const ours = !!listed && listed.includes(await key.name('library/meta.json'))
    const empty = !!listed && !ours && !listed.some(isLibraryName)
    // pairings made before the PC sent `p` still carry its web client id, which starts with the project
    const pcProject = this.pair.p || projectOf(this.pair.c || '')
    const why = diagnoseNoLibrary({
      listed, ours, problem, signedAs: this.pair.g || '', pcAccount: this.pair.e || '', pcProject,
      phoneProject: empty && pcProject ? await tokenProject() : '',
    }, this.words)
    return new NoMirror(why.message, why)
  }

  private async man(): Promise<Manifest> {
    if (this.manifest) return this.manifest
    this.manifest = (await kv.get<Manifest>('manifest')) ?? null
    return this.manifest ?? this.loadManifest()
  }

  private once<T>(k: string, f: () => Promise<T>): Promise<T> {
    let p = this.inflight.get(k) as Promise<T> | undefined
    if (!p) { p = f().finally(() => this.inflight.delete(k)); this.inflight.set(k, p) }
    return p
  }

  // one file, downloaded and opened
  private async fetchFile(logical: string, onProgress?: (got: number, total: number) => void): Promise<Uint8Array> {
    const m = await this.man()
    const f = m.files[logical]
    if (!f) throw Object.assign(new Error(`${logical} is not in the mirror`), { displayKey: 'common.error.mirrorFileMissing', displayParams: { logical: logical } })
    const id = f.id ?? (await this.drive.find(f.n))?.id
    if (!id) throw Object.assign(new Error(`${logical} is missing from Google Drive`), { displayKey: 'common.error.driveFileMissing', displayParams: { logical: logical } })
    return (await this.key).open(logical, await this.drive.get(id, onProgress))
  }

  // a small file, kept decrypted by version: downloaded only when the manifest has a new one
  private async cached(logical: string): Promise<string> {
    const m = await this.man()
    const f = m.files[logical]
    const hit = await files.get(logical)
    if (hit && typeof hit.data === 'string' && (!f || hit.v === f.v)) return hit.data
    return this.once(logical, async () => {
      if (await this.nativeReady()) {
        const copy = await nativeCache<{ v: string; data: string }>(this.nativeScope, `file/${logical}/${f?.v}`)
        if (copy && copy.v === f?.v) { await files.set(logical, copy); return copy.data }
      }
      const raw = await this.fetchFile(logical)
      const text = logical.endsWith('.gz') ? await gunzip(raw) : new TextDecoder().decode(raw)
      this.drive.checkpoint()
      await files.set(logical, { v: f!.v, data: text })
      return text
    })
  }

  private names(prefix: string, suffix = ''): string[] {
    const names = Object.keys(this.manifest?.files ?? {}).filter(k => k.startsWith(prefix) && k.endsWith(suffix)).sort()
    return prefix === 'library/part-' || prefix === 'search/text-' ? names.reverse() : names
  }

  // ── the light copy ─────────────────────────────────────────────────────────
  health() { return this.loadManifest().then(m => ({ ok: true, items: m.items })) }

  rows(step?: (key: 'read' | 'lib', note?: string) => void, progress?: (done: number, total: number) => void) {
    return this.once('rows', () => this.readRows(step, progress))
  }
  private async readRows(step?: (key: 'read' | 'lib', note?: string) => void, progress?: (done: number, total: number) => void) {
    const revision = cloudRevision()
    await this.ready()
    if (cloudStopped()) return { rows: this.rowsNow as Row[], cats: this.cats() }
    step?.('read')
    if (this.solo) {
      let note = say(this.words, 'shell.sync.localOnly', {}, 'not connected to Google Drive: the library stays on this phone')
      try {
        const sent = await this.flush().then(() => true, () => false)
        if (navigator.onLine && token(this.pair)) {
          const n = await this.readBack()
          note = n ? say(this.words, 'shell.sync.changesRead', { n }, `${n} change${n > 1 ? 's' : ''} read from Google Drive`) : say(this.words, 'shell.sync.nothingNew', {}, 'nothing new in Google Drive')
          // the status says Backed up only after a round that sent what was queued and read Drive back
          this.round = { at: Date.now(), ok: sent, error: sent ? '' : this.lastError }
        }
      } catch (e) {
        if (e instanceof CloudCancelled) throw e
        // the library is on the phone either way; a refused sign-in drops the token, so Backup & phones asks to sign in again
        note = say(this.words, 'shell.sync.driveNotRead', { detail: (e as Error).message }, `Google Drive not read (${(e as Error).message})`)
        this.round = { at: Date.now(), ok: false, error: (e as Error).message }
      }
      step?.('lib', note)
      cloudCheckpoint(revision)
      this.manifest = SOLO_MANIFEST
      this.setRows()
      this.looked = Date.now()
      return { rows: this.rowsNow as Row[], cats: this.cats() }
    }
    const before = this.manifest
    const m = await this.loadManifest()
    const names = this.names('library/part-'), fresh = names.filter(p => before?.files[p]?.v !== m.files[p].v).length
    step?.('lib', before?.published === m.published ? say(this.words, 'shell.sync.noNewUpload', {}, 'no new upload from the PC') : say(this.words, 'shell.sync.partsChanged', { changed: fresh, total: names.length }, `${fresh} of ${names.length} parts changed`))
    this.meta = JSON.parse(await this.cached('library/meta.json')) as Meta
    let got = 0
    progress?.(0, names.length)
    const parts = await pool(names, 8, async p => {
      const part = JSON.parse(await this.cached(p)) as MRow[]
      progress?.(++got, names.length)
      return part
    })
    this.drive.checkpoint()
    this.base = parts.flat().map(r => ({ ...r, nd: r.nd ?? 0 }))
    this.setRows()
    await this.reconcileCanvas()
    this.looked = Date.now()
    this.full = m.published
    this.recordSoon()
    this.background(m)
    this.flushSoon()
    return { rows: this.rowsNow as Row[], cats: this.cats() }
  }

  // A scheduled native snapshot is local content too, including on an offline reopening.
  async localCopy() {
    await this.ready()
    if (!await this.nativeReady()) return null
    if (this.solo) {
      await this.stagePending()                  // recognize this phone's envelopes before importing other phones
      const names = await nativeCache<string[]>(this.nativeScope, 'solo-list') ?? []
      this.pcMirror = await nativeCache<boolean>(this.nativeScope, 'pc-mirror') ?? false
      const known = this.changes.known()
      for (const name of names) {
        if (known.has(name) || this.mine.has(name)) continue
        const doc = await nativeCache<{ name: string; doc: { at?: number; changes?: Omit<ChangeEntry, 'id' | 'state'>[] } }>(this.nativeScope, 'solo/' + name)
        if (doc) await this.changes.merge([doc])
      }
      this.setRows()
    } else {
      const m = await nativeCache<Manifest>(this.nativeScope, 'manifest')
      if (!m) return null
      this.manifest = m
      this.meta = JSON.parse(await this.cached('library/meta.json'))
      const parts: MRow[][] = []
      for (const name of this.names('library/part-')) {
        parts.push(JSON.parse(await this.cached(name)))
        await new Promise(resolve => setTimeout(resolve, 0))
      }
      this.base = parts.flat().map(r => ({ ...r, nd: r.nd ?? 0 }))
      this.setRows()
    }
    return { rows: this.rowsNow as Row[], cats: this.cats() }
  }

  // solo: the change files in Drive this phone does not hold yet, merged into its journal; returns how
  // many changes came in. Files sealed with another key (a PC's pairing) are skipped.
  private async readBack(): Promise<number> {
    beginCloudChange()
    try {
      const key = await this.key
      if (await this.nativeReady()) {
        await this.runNative()
        const names = await nativeCache<string[]>(this.nativeScope, 'solo-list') ?? []
        this.pcMirror = await nativeCache<boolean>(this.nativeScope, 'pc-mirror') ?? false
        const known = this.changes.known()
        const docs = []
        for (const name of names) {
          if (known.has(name) || this.mine.has(name)) continue
          const doc = await nativeCache<{ name: string; doc: { at?: number; changes?: Omit<ChangeEntry, 'id' | 'state'>[] } }>(this.nativeScope, 'solo/' + name)
          if (doc) docs.push(doc)
        }
        this.drive.checkpoint()
        return await this.changes.merge(docs)
      }
      const all = await this.drive.list()
      this.pcMirror = all.some(f => isLibraryName(f.name))
      const prefix = await key.soloPrefix()
      await this.changes.load()
      const known = this.changes.known()
      const fresh = all.filter(f => (f.name.startsWith(prefix) || f.name.startsWith(CHANGE_PREFIX)) && !known.has(f.name) && !this.mine.has(f.name) && !this.unreadable.has(f.name))
      const docs = await pool(fresh, 4, async f => {
        try {
          return { name: f.name, doc: await key.openJSON<{ at?: number; changes?: Omit<ChangeEntry, 'id' | 'state'>[] }>(f.name, await this.drive.get(f.id)) }
        } catch (e) {
          if (e instanceof NeedsSignIn || e instanceof SyncPaused || syncPaused() || (e as Error).name === 'AbortError') throw e
          if (!f.name.startsWith(CHANGE_PREFIX) || !(e instanceof MirrorKeyError)) throw e
          this.unreadable.add(f.name)
          return null
        }
      })
      this.drive.checkpoint()
      return await this.changes.merge(docs.filter((d): d is NonNullable<typeof d> => !!d))
    } finally {
      endCloudChange()
    }
  }

  // the phone's last copy, before any refresh this session (no signal: the app opens from it)
  private primed: Promise<void> | null = null
  private ready() {
    this.primed ??= (async () => {
      await this.changes.load()
      // a phone used without a PC, now paired with one: its whole journal goes to the PC, as a new stream. The marker
      // goes once the journal is saved: storage that fails keeps it for the next start, and the library still opens.
      if (!this.solo && requeueWaiting()) {
        try { await this.changes.requeue(); takeRequeue(); this.flushSoon() }
        catch { /* the marker stays */ }
      }
      // solo: an interrupted reconnect left its marker: what went up under the old key goes again under this one
      if (this.solo && await finishReconnect(this.changes, await this.key)) this.flushSoon()
      if (!this.base.length) {
        this.base = ((await kv.get<MRow[]>('rows')) ?? []).filter(r => r.id > 0)
        this.setRows()
      }
      this.manifest ??= (await kv.get<Manifest>('manifest')) ?? null
      if (!this.meta) { const m = await files.get('library/meta.json'); if (typeof m?.data === 'string') this.meta = JSON.parse(m.data) as Meta }
    })()
    return this.primed
  }

  private setRows() {
    this.rowsNow = (this.changes.overlay(this.base) as MRow[]).map(r => r.desc?.trim() === NO_CONTENT ? { ...r, ai: false, desc: '' } : r)
    this.byId = new Map(this.rowsNow.map(r => [r.id, r]))
  }

  private cats(): Category[] {
    const n = new Map<string, number>()
    for (const r of this.rowsNow) n.set(r.cat, (n.get(r.cat) ?? 0) + 1)
    // solo: no PC categories, only the ones the phone's cards use
    const list = this.meta?.categories ?? [...n.keys()].sort().map(name => ({ name, color: '' }))
    return list.map(c => ({ name: c.name, color: c.color, count: n.get(c.name) ?? 0 }))
  }

  // after the rows: notes, chats, canvases and the vectors, so they are on the phone with no signal;
  // files the mirror dropped leave the phone too
  private background(m: Manifest) {
    const want = [...this.names('notes/', '.md'), ...this.names('chats/', '.json'), ...(m.files['canvases/index.json'] ? ['canvases/index.json'] : [])]
    pool(want, 6, k => this.cached(k).catch(() => '')).then(async () => {
      for (const k of await files.keys()) if (!m.files[k]) await files.del(k)
      if (m.files['vectors.bin']) await this.vectors().catch(() => null)
      await pool(this.names('search/text-'), 4, k => this.cached(k).catch(() => ''))
    }).catch(() => { /* the next refresh tries again */ })
  }

  async rowsByIds(ids: number[]) { await this.ready(); return ids.map(i => this.byId.get(i)).filter((r): r is MRow => !!r) }

  async tints() {
    const t: Record<string, string> = {}
    for (const r of this.rowsNow) if (r.tint) t[String(r.id)] = r.tint
    return t
  }

  // the service worker serves this from its cache, or asks onWorker() for the pack (public/sw.js)
  thumbUrl(r: Row, _w = 0) { return `/thumb/${r.id}?v=${r.tv || 0}&m=1${r.fav ? '&pin=1' : ''}` }

  private onWorker(e: MessageEvent) {
    const d = e.data as { type?: string; kind?: string; id?: number; name?: string } | null
    if (d?.type !== 'need' || !e.ports[0]) return
    const port = e.ports[0]
    const job = d.kind === 'thumb' ? this.fillPack(Number(d.id)) : d.kind === 'upload' ? this.fillUpload(String(d.name)) : Promise.reject(new Error('?'))
    job.then(() => port.postMessage({ ok: true }), () => port.postMessage({ ok: false }))
  }

  private pack(id: number) { return `thumbs/pack-${String(Math.floor(id / 100)).padStart(4, '0')}.bin` }

  fillPack(id: number) {
    if (id < 0) return this.fillLinkThumb(id)
    const logical = this.pack(id)
    return this.once(logical, async () => {
      await this.ready()
      const pack = readPack(await this.fetchFile(logical))
      const c = await caches.open(THUMB_CACHE)
      await Promise.all([...pack].map(([i, jpg]) => {
        const r = this.byId.get(i)
        return r ? c.put(this.thumbUrl(r), new Response(jpg.slice(), { headers: { 'Content-Type': 'image/jpeg' } })) : null
      }))
      navigator.serviceWorker?.controller?.postMessage({ type: 'trim' })
    })
  }

  // a phone link's picture, from its `details` change (a second phone, or after the cache was trimmed)
  private async fillLinkThumb(id: number) {
    await this.ready()
    const r = this.byId.get(id)
    const d = r && [...this.changes.list].reverse().find(e => e.op === 'details' && e.uid === r.uid && e.thumb)
    if (!r || !d?.thumb) throw new Error('no picture for this link')
    const c = await caches.open(THUMB_CACHE)
    await c.put(this.thumbUrl(r), new Response(Uint8Array.from(atob(d.thumb), ch => ch.charCodeAt(0)), { headers: { 'Content-Type': 'image/jpeg' } }))
  }

  // ── link details (plans/09-link-details.md; the Android app only) ──
  // Add to Brainamon's preview card (projects/link-preview): the same reader, nothing kept. A browser
  // cannot read another site (CORS), so outside the app the answer is "nothing found" at once.
  async linkPreview(url: string): Promise<Preview> {
    const info = isApp ? await linkInfo(url, linkGet).catch(() => null) : null
    let image = ''
    try { image = info?.image ? new URL(info.image, url).href : '' } catch { /* a broken address: no picture */ }
    return { title: info?.title ?? '', creator: info?.creator ?? '', desc: info?.desc ?? '', image, asked: url, url, found: !!info }
  }

  private triedLinks = new Set<string>()

  // links saved on the phone (negative ids) with no details yet: the ids given, or every one not tried
  // since the app started. Reads each link's page, keeps what it says as a `details` change (sent like
  // any change) and its picture in the thumbnail cache. Returns the ids that changed.
  async linkDetails(ids?: number[], onRow?: (id: number) => Promise<void>): Promise<number[]> {
    if (!isApp || syncPaused()) return []
    await this.ready()
    const have = new Set(this.changes.list.filter(e => e.op === 'details').map(e => e.uid))
    const want = this.rowsNow.filter(r => r.id < 0 && r.uid && !have.has(r.uid) && (ids ? ids.includes(r.id) : !this.triedLinks.has(r.uid)))
      .sort((a, b) => b.created - a.created || b.id - a.id)
    const done: number[] = []
    // the cards show which link is being read and which wait (work.svelte.ts)
    queueWork('links', 'FETCH', want.map(r => r.id))
    try {
      for (const r of want) {
        if (syncPaused()) break
        this.triedLinks.add(r.uid!)
        startWork('links', 'FETCH', r.id)
        const info = await linkInfo(r.url, linkGet).catch(() => null)
        if (!info) { endWork(r.id, false); continue }
        const thumb = info.image && !syncPaused() ? await linkImage(info.image).then(shrinkJpeg).catch(() => '') : ''
        if (!info.title && !info.desc && !thumb) { endWork(r.id, false); continue }
        await this.changes.add({ op: 'details', uid: r.uid, title: info.title.slice(0, 300), creator: info.creator.slice(0, 120), desc: info.desc.slice(0, 5000), thumb })
        this.setRows()
        const row = this.byId.get(r.id)
        if (thumb && row) {
          try {
            const c = await caches.open(THUMB_CACHE)
            await c.put(this.thumbUrl(row), new Response(Uint8Array.from(atob(thumb), ch => ch.charCodeAt(0)), { headers: { 'Content-Type': 'image/jpeg' } }))
          } catch { /* the picture is durable in the journal; cache failure must not stop the queue */ }
        }
        endWork(r.id, true)
        done.push(r.id)
        await onRow?.(r.id)
      }
    } finally { endLane('links') }
    if (done.length) this.flushSoon()
    return done
  }

  private triedPics = new Set<string>()
  private pictures: Promise<{ got: number[]; blocked: boolean }> | null = null
  private hintsLoad: Promise<Record<string, PicHint>> | null = null

  // the picture links the site reader saw, by phone link: one object, shared by addPicHints and the queue
  private picHints() {
    return (this.hintsLoad ??= kv.get<Record<string, PicHint>>(PIC_HINTS).then(async h => {
      const hints = h && typeof h === 'object' && !Array.isArray(h) ? h : {}
      const now = Date.now()
      for (const [url, v] of Object.entries(hints)) {
        if (!v || !Number.isFinite(v.at) || v.at > now || now - v.at > PIC_HINT_KEEP_MS ||
          !postPicOk(url, v.u)) delete hints[url]
      }
      await kv.set(PIC_HINTS, hints)
      return hints
    }))
  }

  // keeps the picture links of posts read from a site (screens/SiteRead.svelte, projects/phone-site-reader):
  // they are signed and expire within days, so they stay on this phone and never ride in a change file
  async addPicHints(pairs: [string, string][]) {
    if (!pairs.length) return
    const hints = await this.picHints(), now = Date.now()
    const rows = new Map(this.rowsNow.map(r => [postKey(r.url), r]))
    for (const [k, v] of Object.entries(hints)) if (!v || now - v.at > PIC_HINT_KEEP_MS) delete hints[k]
    for (const [url, u] of pairs) {
      if (!postPicOk(url, u)) continue
      const row = rows.get(postKey(url))
      hints[cleanLink(row?.url || url) || url] = { u, at: now }
      if (row?.uid) this.triedPics.delete(row.uid)
    }
    await kv.setRequired(PIC_HINTS, hints)
  }

  // The slow picture queue (plans/09-link-details.md step 13). Phone links with no picture yet whose picture
  // can be found (sites.ts picturePlan): the site's own picture link first (posts read from a site), then
  // the link's rule (imageUrl), then the picture the post's page names. One at a time, paced; a picture
  // from a site's link waits less. `step` reports progress; `stop()` ends the run early. Returns the ids
  // that got a picture and whether the site asked to slow down (403 / 429 / 3 failures in a row of the
  // rule or page reads).
  async fillPictures(step: (p: { done: number; total: number }) => void, stop: () => boolean,
    options: { ids?: number[]; retry?: boolean; onRow?: (id: number) => Promise<void> } = {}): Promise<{ got: number[]; blocked: boolean }> {
    while (this.pictures) await this.pictures.catch(() => {})
    const run = this.fetchPictures(step, stop, options)
    this.pictures = run
    try { return await run } finally { this.pictures = null }
  }

  private async fetchPictures(step: (p: { done: number; total: number }) => void, stop: () => boolean,
    options: { ids?: number[]; retry?: boolean; onRow?: (id: number) => Promise<void> }): Promise<{ got: number[]; blocked: boolean }> {
    if (!isApp || syncPaused()) return { got: [], blocked: false }
    await this.ready()
    const hints = await this.picHints(), now = Date.now()
    const withPic = new Set(this.changes.list.filter(e => e.op === 'details' && e.thumb).map(e => e.uid))
    const plans = new Map<number, ReturnType<typeof picturePlan>>()
    for (const r of this.rowsNow) {
      if (options.ids && !options.ids.includes(r.id)) continue
      if (options.retry && r.uid) this.triedPics.delete(r.uid)
      if (r.id >= 0 || !r.uid || withPic.has(r.uid) || this.triedPics.has(r.uid)) continue
      const plan = picturePlan(r.url, hints[cleanLink(r.url) || r.url], now)
      if (options.retry) plan.page = true  // A failed or expired hint may already have been consumed.
      if (plan.hint || plan.rule || plan.page) plans.set(r.id, plan)
    }
    const want = this.rowsNow.filter(r => plans.has(r.id)).sort((a, b) => b.created - a.created || b.id - a.id)
    const got: number[] = []
    let failed = 0, used = 0
    step({ done: 0, total: want.length })
    queueWork('pics', 'PICTURE', want.map(r => r.id))
    let blocked = false
    try {
      for (const r of want) {
        if (stop() || syncPaused()) break
        this.triedPics.add(r.uid!)
        startWork('pics', 'PICTURE', r.id)
        const plan = plans.get(r.id)!
        let thumb = '', asked = false
        if (plan.hint) {
          thumb = await linkImage(plan.hint).then(shrinkJpeg).catch(() => '')
          delete hints[cleanLink(r.url) || r.url]
          used++
        }
        if (!thumb && (plan.rule || plan.page)) {
          asked = true
          try {
            thumb = await shrinkJpeg(await linkImage(plan.rule || await pagePicture(r.url)))
            failed = 0
          } catch (e) {
            const status = (e as { status?: number }).status
            failed++
            if (status === 403 || status === 429 || failed >= 3) {
              if (got.length) this.flushSoon()
              blocked = true
              dropWork(r.id)
              return { got, blocked: true }
            }
          }
        }
        if (thumb) {
          const prev = [...this.changes.list].reverse().find(e => e.op === 'details' && e.uid === r.uid)
          await this.changes.add({ op: 'details', uid: r.uid, title: prev?.title ?? '', creator: prev?.creator ?? '', desc: prev?.desc ?? '', thumb })
          this.setRows()
          const row = this.byId.get(r.id)
          if (row) {
            try {
              const c = await caches.open(THUMB_CACHE)
              await c.put(this.thumbUrl(row), new Response(Uint8Array.from(atob(thumb), ch => ch.charCodeAt(0)), { headers: { 'Content-Type': 'image/jpeg' } }))
            } catch { /* the picture is durable in the journal; cache failure must not stop the queue */ }
          }
          got.push(r.id)
          endWork(r.id, true)
          await options.onRow?.(r.id)
        } else dropWork(r.id)
        step({ done: got.length, total: want.length })
        await new Promise(res => setTimeout(res, asked ? PIC_GAP_MS + Math.random() * PIC_JITTER_MS : HINT_GAP_MS + Math.random() * HINT_JITTER_MS))
      }
    } finally {
      // slowed down by the site: the rest keep waiting for the next run (runPictures), else the marks go
      if (blocked) clearRun('pics'); else endLane('pics')
      if (used) await kv.set(PIC_HINTS, hints)
    }
    if (got.length) this.flushSoon()
    return { got, blocked: false }
  }

  async fetchInfo(id: number, onRow?: (id: number) => Promise<void>): Promise<Row | null> {
    if (!isApp || syncPaused()) return null
    const links = await this.linkDetails([id], onRow)
    const result = await this.fillPictures(() => {}, () => false, { ids: [id], retry: true, onRow })
    if (result.blocked) throw new Error(t('library.fetchBlocked'))
    const row = this.byId.get(id)
    return links.includes(id) || result.got.includes(id) ? row ?? null : null
  }

  // one thumbnail as a Blob (Save for offline), from the cache or its pack
  async thumbBlob(r: Row): Promise<Blob | null> {
    const c = await caches.open(THUMB_CACHE)
    let hit = await c.match(this.thumbUrl(r))
    if (!hit) { await this.fillPack(r.id).catch(() => null); hit = await c.match(this.thumbUrl(r)) }
    return hit ? hit.blob() : null
  }

  canvasImageUrl(name: string) { return `/mirror/canvas-uploads/${encodeURIComponent(name)}` }

  // a few canvas pictures at a time: a large canvas asks for all of them at once, and Google refuses the burst
  private uploadSlots = 8
  private uploadWaiting: (() => void)[] = []
  private fillUpload(name: string) {
    return this.once('up:' + name, async () => {
      while (this.uploadSlots <= 0) await new Promise<void>(res => this.uploadWaiting.push(res))
      this.uploadSlots--
      let data: Uint8Array
      try { data = await this.fetchFile(`canvas-uploads/${name}`) } finally { this.uploadSlots++; this.uploadWaiting.shift()?.() }
      const c = await caches.open(MIRROR_CACHE)
      await c.put(this.canvasImageUrl(name), new Response(data.slice(), { headers: { 'Content-Type': MIME[name.split('.').pop()?.toLowerCase() ?? ''] ?? 'application/octet-stream' } }))
    })
  }

  async canvasImage(name: string): Promise<Blob> {
    const c = await caches.open(MIRROR_CACHE)
    let hit = await c.match(this.canvasImageUrl(name))
    if (!hit) { await this.fillUpload(name); hit = await c.match(this.canvasImageUrl(name)) }
    if (!hit) throw new Error('image missing')
    return hit.blob()
  }

  // ── one item ───────────────────────────────────────────────────────────────
  async item(id: number): Promise<FullItem> {
    await this.ready()
    const r = this.byId.get(id)
    if (id < 0 || !r?.uid) {
      if (!r) throw new Error('This card is not in the phone\'s copy.')
      const link = this.changes.list.find(e => e.op === 'link' && e.uid === r.uid)
      const d = [...this.changes.list].reverse().find(e => e.op === 'details' && e.uid === r.uid)
      let notes = link?.note ?? ''
      let aiDesc = ''
      for (const e of this.changes.list) {
        if (e.op !== 'edit' || e.uid !== r.uid) continue
        if (e.fields?.notes !== undefined) notes = e.fields.notes
        if (e.fields?.ai_desc !== undefined) aiDesc = e.fields.ai_desc
      }
      return {
        id, url: r.url, description: d?.desc || r.url, short_desc: d?.title || '', creator: d?.creator || '', type: r.type, category: r.cat, tags: r.tags,
        ai_desc: aiDesc, notes, thumb_path: d?.thumb ? 'thumb.jpg' : '', created: r.created, modified: r.created, favourite: r.fav ? 1 : 0,
        files: { thumb: !!d?.thumb, report: false, transcript: false, frames: 0, frame_names: [], video: false },
      }
    }
    const it = JSON.parse(new TextDecoder().decode(await this.fetchFile(`items/${r.uid}.json`))) as FullItem & { report: string; transcript: string }
    const full: FullItem = { ...it, thumb_path: it.files.thumb ? 'thumb.jpg' : '', favourite: r.fav ? 1 : 0, tags: r.tags, category: r.cat,
      files: { ...it.files, frames: 0, frame_names: [], video: !!this.manifest?.files[`videos/${r.uid}.bin`] } }
    for (const e of this.changes.list) if (e.op === 'edit' && e.uid === r.uid && e.fields?.notes !== undefined) full.notes = e.fields.notes
    for (const e of this.changes.list) if (e.op === 'edit' && e.uid === r.uid && e.fields?.ai_desc !== undefined) full.ai_desc = e.fields.ai_desc
    this.texts.set(id, { report: it.report || '', transcript: it.transcript || '', notes: it.notes || '' })
    delete (full as Record<string, unknown>).report
    return full
  }

  async itemText(id: number, which: 'report' | 'transcript') {
    if (!this.texts.has(id)) await this.item(id)
    const t = this.texts.get(id)?.[which] ?? ''
    if (!t) throw new Error(`No ${which} yet`)
    return t
  }

  private async vectors(): Promise<Vectors | null> {
    const m = await this.man()
    const f = m.files['vectors.bin']
    if (!f) return null
    if (this.vec?.v === f.v) return this.vec.data
    return this.once('vectors.bin', async () => {
      const hit = await files.get('vectors.bin')
      let data: ArrayBuffer
      if (hit && hit.v === f.v && hit.data instanceof ArrayBuffer) data = hit.data
      else {
        const b = await this.fetchFile('vectors.bin')
        data = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer
        await files.set('vectors.bin', { v: f.v, data })
      }
      this.vec = { v: f.v, data: readVectors(new Uint8Array(data)) }
      return this.vec.data
    })
  }

  // Related by meaning: the nearest items by the PC's embeddings, compared on the phone
  async related(id: number) {
    await this.ready()
    const v = await this.vectors()
    const at = v ? v.ids.indexOf(id) : -1
    if (!v || at < 0) return []
    return nearest(v, at, 12).map(i => this.byId.get(i)).filter((r): r is MRow => !!r)
  }

  // ── search ─────────────────────────────────────────────────────────────────
  async search(q: string) {
    await this.ready()
    // the PC's box: every word, prefix, over the full text; the plain scan while the phone has no search text
    const fts = await this.library().then(l => l.ftsIds(q, 100000, true)).catch(() => null)
    return libraryIds(this.rowsNow, q, fts)
  }
  // Smart search: server/routes/smart.py on the phone (the question embedded with the phone's
  // OpenAI key, cosine over vectors.bin, fused with the bm25 ranking)
  async smart(q: string): Promise<number[]> {
    if (this.solo) throw new AiError(SOLO_SMART)
    const key = this.keys().openai
    if (!key) throw new AiError('Smart search needs your OpenAI key on this phone: pair it again from the PC with the OpenAI key ticked.')
    const [lib, v] = await Promise.all([this.library(), this.vectors()])
    if (!v || !v.ids.length) throw new AiError('Smart search needs the PC to run "Index for search" and upload once.')
    const [vec] = await embed(this.endpoints(), key, v.model, [q])
    return hybridRank(lib.ftsIds(q, SMART_LIMIT), topk(v, vec, SMART_LIMIT), SMART_LIMIT)
  }

  obsidianVault() { return this.meta?.obsidian_vault ?? '' }
  obsidianNotes() { return this.meta?.obsidian_notes ?? '' }

  // ── the phone's writes: queued, shown at once, sent as a change file ───────
  private replace(r: MRow) {
    this.setRows()
    return this.byId.get(r.id) ?? r
  }

  async favourite(id: number, on: boolean) {
    await this.ready()
    const r = this.byId.get(id)
    if (!r?.uid) throw new Error('This card is not in the phone\'s copy.')
    await this.changes.add({ op: 'fav', uid: r.uid, on })
    this.flushSoon()
    return this.replace(r)
  }

  // Settings > Storage > Clear the phone's copy: forget what was read, so the next refresh downloads it all again
  forgetCopy() {
    this.manifest = null; this.meta = null; this.base = []; this.texts.clear(); this.vec = null
    this.lib = null; this.deepAux = null; this.looked = 0; this.primed = null
    this.setRows()
  }

  // gone from the list at once; with `pc` the PC deletes it too when it applies the change
  // (server/intake.py `delete`), else only the phone hides it. A link the PC never got just goes.
  async deleteItem(id: number, pc: boolean): Promise<void> {
    await this.ready()
    const r = this.byId.get(id)
    if (!r?.uid) throw Object.assign(new Error("This card is not in the phone's copy."), { displayKey: 'common.error.cardMissing' })
    if (!(id < 0 && await this.changes.dropQueuedLink(r.uid))) {
      await this.changes.add({ op: 'delete', uid: r.uid, pc })
      this.flushSoon()
    }
    await stored.del(id)
    this.setRows()
  }

  async edit(id: number, fields: Record<string, string>) {
    await this.ready()
    const r = this.byId.get(id)
    if (!r?.uid) throw new Error('This card is not in the phone\'s copy.')
    const f: Record<string, string> = {}
    for (const k of ['tags', 'category', 'notes']) if (fields[k] !== undefined) f[k] = String(fields[k])
    if (id < 0 && f.tags === undefined && await this.changes.amendLink(r.uid, { note: f.notes, category: f.category })) {
      this.flushSoon()
      return this.replace(r)
    }
    const was: Record<string, unknown> = { tags: r.tags, category: r.cat }
    // notes are not on the card row: read the item first, so the PC can tell a newer PC edit from
    // an old value (server/intake.py keeps the PC's when it changed after the phone read it)
    if (f.notes !== undefined && !this.texts.has(id)) await this.item(id).catch(() => { /* no signal: sent without */ })
    const known = this.texts.get(id)
    if (known) was.notes = known.notes
    await this.changes.add({ op: 'edit', uid: r.uid, fields: f, was })
    if (known && f.notes !== undefined) known.notes = f.notes
    this.flushSoon()
    return this.replace(r)
  }

  async saveLink(url: string) {
    await this.ready()
    const clean = cleanLink(url) || url
    const hit = this.rowsNow.find(r => r.url === clean)
    if (hit) return { id: hit.id, new: false }
    const e = await this.changes.add({ op: 'link', uid: hex(16), url: clean, note: '', category: '' })
    this.setRows()
    this.flushSoon()
    return { id: Changes.linkId(e), new: true }
  }

  // saved posts read from an export (screens/Import.svelte, milestone-2026-10-14/mobile-import/PLAN.md):
  // links the phone does not hold yet become a link and a details change each; the slow picture
  // queue adds their pictures. Returns the new rows' ids and how many were already there.
  async importLinks(posts: Saved[]): Promise<{ ids: number[]; dups: number }> {
    await this.ready()
    const existing = new Set(this.rowsNow.map(x => x.url))
    const keys = new Set(this.rowsNow.map(x => postKey(x.url)).filter(Boolean))
    const fresh: Saved[] = []
    let duplicates = 0
    for (const p of posts) {
      const key = postKey(p.url)
      if (key && keys.has(key)) { duplicates++; continue }
      if (key) keys.add(key)
      fresh.push(p)
    }
    const r = importChanges(fresh, existing, cleanLink, () => hex(16))
    const ids: number[] = []
    for (const e of await this.changes.addBatch(r.changes)) {
      if (e.op === 'link') ids.push(Changes.linkId(e))
    }
    if (ids.length) { this.setRows(); this.flushSoon() }
    return { ids, dups: r.dups + duplicates }
  }

  private async nativeReady(): Promise<boolean> {
    if (!isApp || this.pair.d || !this.pair.g || this.pair.backupTask || cloudStopped()) return false
    if (!await nativeSyncSupported()) return false
    return this.nativeInit ??= (async () => {
      await secretsSaved()
      this.nativeScope = await syncOwner(this.pair, deviceId())
      const opts = await kv.get<{ on: boolean; uri: string }>('vault')
      await nativeSyncPolicy({ enabled: true, blocked: false, paused: network.manualPause, wifiOnly: network.wifiOnly,
        device: deviceId(), vault: !!opts?.on && !this.solo, uri: opts?.uri ?? '' })
      const state = await kv.get('vault-state')
      if (state) await seedNativeVault(this.nativeScope, state)
      return true
    })().catch(e => { this.nativeInit = null; throw e })
  }

  private async stagePending(): Promise<string[]> {
    if (!await this.nativeReady() || this.resendPending) return []
    this.stageAgain = true
    if (this.staging) return this.staging
    this.staging = (async () => {
      const ids = new Set<string>()
      while (this.stageAgain) {
        this.stageAgain = false
        await this.changes.prepareUploads(async doc => {
          const id = await transferId(doc)
          ids.add(id)
          const prior = await nativeReceipt(this.nativeScope, id)
          if (!prior.name) {
            const [name, data] = await (await this.key).sealChange(doc, this.solo)
            const receipt = await stageNative(this.nativeScope, id, name, toB64(data))
            this.mine.add(receipt.name)
            this.nativeDirty ||= !receipt.remote
          } else { this.mine.add(prior.name); this.nativeDirty ||= !prior.remote }
        }, deviceId(), this.canvasSync, !this.solo)
      }
      return [...ids]
    })().finally(() => { this.staging = null })
    return this.staging
  }

  private async runNative(uploadsOnly = false) {
    const ids = await this.stagePending()
    const dirty = this.nativeDirty
    this.nativeDirty = false
    try {
      // Delivery receipts release Send immediately; the independent native vault round may continue.
      if (uploadsOnly) {
        if (!ids.length) return
        await nativeUploads(this.nativeScope, ids, nativeRound(false, false, dirty))
      } else await nativeRound(false, false, dirty, undefined, true)
      network.licenseLocked = false; network.licenseKind = ''; network.licenseProblem = ''
    }
    catch (e) {
      this.nativeDirty ||= dirty
      const code = (e as { code?: string }).code
      if (code === 'auth') { dropToken(); throw new NeedsSignIn((e as Error).message) }
      if (code === 'access') { network.licenseLocked = true; network.licenseKind = 'invalid'; throw new LicenseRequired((e as Error).message) }
      if (code === 'update') { tooOld.fn(); throw new PhoneTooOld() }
      throw e
    }
  }

  flushSoon(ms = 1500) {
    void this.stagePending().catch(e => { this.lastError = (e as Error).message })
    clearTimeout(this.flushT)
    this.flushT = window.setTimeout(() => { this.flush().catch(() => { /* stays queued */ }) }, ms)
  }

  // send what is queued as one change file
  async flush(): Promise<number> {
    if (cloudStopped()) throw new CloudCancelled()
    if (await this.nativeReady()) {
      await this.stagePending()
      if (network.manualPause || !network.online || (network.wifiOnly && !['wifi', 'ethernet'].includes(network.type))) throw new SyncPaused()
      beginCloudChange()
      try {
        await this.runNative(true)
        const n = await this.changes.flush(async doc => {
          const receipt = await nativeReceipt(this.nativeScope, await transferId(doc))
          if (!receipt.name || !receipt.remote) throw nativeSyncError('retry')
          this.drive.checkpoint()
          this.mine.add(receipt.name)
          if (this.solo) await recordPublish(await this.key, receipt.name, receipt.remote, doc as { at: number; changes: unknown[] })
          return receipt.name
        }, deviceId(), this.canvasSync, !this.solo)
        this.lastError = ''; return n
      } catch (e) { this.lastError = (e as Error).message; throw e }
      finally { endCloudChange() }
    }
    if (syncPaused()) throw new SyncPaused()
    if (!navigator.onLine || !token(this.pair)) return 0
    // paired again (mirror/resend.ts): first a fresh manifest says what the PC has (it throws while there is none)
    if (this.resendPending) await this.loadManifest()
    if (this.resendPending) return 0
    beginCloudChange()
    try {
      const n = await this.changes.flush(async doc => {
        this.drive.checkpoint()
        const key = await this.key
        const [name, blob] = await key.sealChange(doc, this.solo)
        this.mine.add(name)                        // solo: never read back as someone else's
        const id = await this.drive.create(name, blob)
        this.drive.checkpoint()
        // solo: the proof a later reconnect checks (mirror/phone-reconnect.ts); sealChange sealed exactly this JSON
        if (this.solo) await recordPublish(key, name, id, doc as { at: number; changes: unknown[] })
        return name
      }, deviceId(), this.canvasSync, !this.solo)
      this.lastError = ''
      return n
    } catch (e) {
      this.lastError = (e as Error).message
      throw e
    } finally {
      endCloudChange()
    }
  }

  // ── notes ──────────────────────────────────────────────────────────────────
  private async noteFiles(signal?: AbortSignal, deadline?: number): Promise<NoteFile[]> {
    await this.man()
    await this.changes.load()
    const parts = await pool(this.names('notes/', '.md'), 4, async k => {
      signal?.throwIfAborted()
      if (deadline !== undefined && performance.now() >= deadline) return null
      const [meta, body] = splitFront(await this.cached(k).catch(e => { if (signal || (e as Error).name === 'AbortError') throw e; return '' }))
      return { file: k.slice(6), meta, body }
    })
    const out = parts.filter((n): n is NonNullable<typeof n> => n !== null)
    const gone = new Set(this.changes.list.filter(e => e.op === 'note_delete').map(e => e.file))
    for (const e of this.changes.list) {
      if ((e.op === 'answer' || e.op === 'synth') && e.file) {
        const [t, body] = e.op === 'answer' ? answerTitle(e.md || '') : [e.topic || '', e.body || '']
        out.push({ file: e.file, body, meta: { topic: t || 'Ask - ' + isoNow(e.at).slice(0, 16).replace('T', ' '), created: isoNow(e.at), sources: (e.op === 'answer' ? e.ids : e.sources)?.join(',') || '' } })
        continue
      }
      if (e.op === 'note_append' && e.file) {        // Add to Brainamon: the section at the end, shown before the PC has it
        const n = out.find(x => x.file === e.file)
        if (n) { n.body = withSection(n.body, e.name || 'Phone', e.text || '', e.when); n.meta = { ...n.meta, updated: isoNow(e.at) } }
        continue
      }
      if (e.op === 'note_category') {                // a category renamed: shown before the PC has it
        try { const r = checkRename(e.from ?? '', e.to ?? ''); out.splice(0, out.length, ...renameNotes(out, r.from, r.to)) }
        catch { /* the PC skips a refused rename too */ }
        continue
      }
      if (e.op !== 'note' || !e.file) continue
      const at = out.findIndex(n => n.file === e.file)
      const old = at >= 0 ? out[at].meta : {}
      const n: NoteFile = { file: e.file, body: e.body ?? '', meta: { ...old, topic: e.title || old.topic || '', category: e.category || old.category || 'General', kind: 'personal', created: old.created || isoNow(e.at), updated: isoNow(e.at) } }
      if (e.stamps !== undefined) n.meta.stamps = JSON.stringify(e.stamps)
      if (at >= 0) out[at] = n; else out.push(n)
    }
    return gone.size ? out.filter(n => !gone.has(n.file)) : out
  }

  private noteRow(n: NoteFile): NoteRow {
    const kind = (this.meta?.topic_notes ?? []).includes(n.file) ? 'Topic digest' : n.meta.kind === 'personal' ? 'Personal' : 'Synthesized'
    // a note synthesized on this phone cites links saved on it by their phone ids (negative)
    const sources = (n.meta.sources || '').split(',').map(s => s.trim()).filter(s => /^-?\d+$/.test(s)).map(Number).sort((a, b) => a - b)
    return { file: n.file, title: n.meta.topic || n.file.replace(/\.md$/, ''), kind, sources: [...new Set(sources)], created: n.meta.created || '', updated: n.meta.updated || n.meta.created || '', snippet: snippet(n.body) }
  }

  private myNoteOf(n: NoteFile, body = false): MyNote {
    const m: MyNote = { file: n.file, title: n.meta.topic || n.file.replace(/\.md$/, ''), category: n.meta.category || 'General', created: n.meta.created || '', updated: n.meta.updated || n.meta.created || '' }
    m.stamps = parseStamps(n.meta.stamps)
    m.snippet = snippet(n.body)
    m.head = noteHead(n.body); m.words = wordCount(n.body)          // the note card (plans/08-note-cards.md)
    if (body) m.body = n.body
    return m
  }

  async notes() {
    // the meta only names the Topic digests: a phone with no PC copy has none (its Knowledge notes are its own
    // syntheses), so its missing meta is no error there
    if (!this.meta) {
      try { this.meta = JSON.parse(await this.cached('library/meta.json')) as Meta }
      catch (e) { if (!this.solo) throw e }
    }
    return (await this.noteFiles()).map(n => this.noteRow(n)).sort((a, b) => b.updated.localeCompare(a.updated))
  }
  async note(file: string): Promise<OpenNote> {
    const n = (await this.noteFiles()).find(x => x.file === file)
    if (!n) throw Object.assign(new Error('No such note in the mirror.'), { displayKey: 'common.error.noteMissing' })
    return { file, meta: n.meta, body: n.body, row: this.noteRow(n) }
  }
  async myNotes() {
    return (await this.noteFiles()).filter(n => n.meta.kind === 'personal').map(n => this.myNoteOf(n)).sort((a, b) => b.updated.localeCompare(a.updated))
  }
  async myNote(file: string) {
    const n = (await this.noteFiles()).find(x => x.file === file)
    if (!n) throw Object.assign(new Error('No such note in the mirror.'), { displayKey: 'common.error.noteMissing' })
    return this.myNoteOf(n, true)
  }
  // the Notes search (projects/phone-notes-manager): every note's whole text, from the phone's copy and its journal
  async noteBodies() {
    const out: Record<string, string> = {}
    for (const n of await this.noteFiles()) out[n.file] = plain(n.body)
    return out
  }
  async myNoteCategories() {
    const c = new Set(['General'])
    for (const n of await this.noteFiles()) if (n.meta.kind === 'personal' && n.meta.category) c.add(n.meta.category)
    return [...c].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()))
  }
  // a category rename travels as one note_category change; a paired PC must announce it (an older PC drops it)
  renameBlocked(words?: ToolWords) { return this.solo || this.manifest?.note_category === 1 ? '' : say(words, 'notes.editor.renameNeedsPc', {}, RENAME_NEEDS_PC) }
  async renameMyNoteCategory(from: string, to: string) {
    const blocked = this.renameBlocked()
    if (blocked) throw new Error(blocked)
    const r = checkRename(from, to)
    await this.changes.add({ op: 'note_category', from: r.from, to: r.to })
    this.flushSoon()
    return this.myNoteCategories()
  }
  async createMyNote(title: string, category: string) {
    const file = `${slug(title || 'Untitled')}-${hex(3)}.md`
    const cat = !category || category === 'All' ? 'General' : category
    await this.changes.add({ op: 'note', file, title: title || 'Untitled', category: cat, body: '', was: '' })
    this.flushSoon()
    return this.myNote(file)
  }
  async saveMyNote(file: string, title: string, category: string, body: string, stamps?: Stamp[]) {
    const mirrorText = this.manifest?.files[`notes/${file}`] ? await this.cached(`notes/${file}`).catch(() => '') : ''
    const was = splitFront(mirrorText)[0].updated ?? ''
    await this.changes.add({ op: 'note', file, title, category, body, was, ...(stamps !== undefined ? { stamps } : {}) })
    this.flushSoon()
    return this.myNote(file)
  }
  // Add to Brainamon (plans/09-add-to-brainamon.md): only the new section travels (server/intake.py
  // _note_append adds it to the PC's current note), so a PC edit made since this phone read it stays
  async appendMyNote(file: string, title: string, name: string, text: string) {
    await this.changes.add({ op: 'note_append', file, title, name, text: text.trim(), when: stamp() })
    this.flushSoon()
    return this.myNote(file)
  }
  async deleteMyNote(file: string) {
    await this.changes.dropQueuedNote(file)
    await this.changes.add({ op: 'note_delete', file })
    this.flushSoon()
  }
  canTranscribe() { return !!this.keys().openai }
  async transcribe(audio: Blob, signal?: AbortSignal): Promise<string> {
    // Use this app's transcription model even when the PC's cached metadata predates its migration.
    const key = this.keys().openai, model = PHONE_AI.transcription_model
    if (!key) throw Object.assign(new AiError('Voice notes need an OpenAI key on this phone (Settings > Wiskit on this phone).'), { displayKey: 'voice.record.keyNeeded' })
    return transcribe(this.endpoints(), key, model, audio, signal)
  }
  // Add a picture or file (projects/wiskit-files plan 04): pictures and PDFs read with the phone's own
  // key and Wiskit's model; text files need no AI. Nothing is kept or sent to the PC.
  async readFile(f: Picked, how: 'digest' | 'describe') {
    const language = lang()
    if (f.kind === 'text') return decodeText(f.data)
    const info = this.ai()
    const key = info && this.keys()[info.provider as Provider]
    if (!info || !key || !info.model) throw Object.assign(new AiError(this.noKey()), { displayKey: this.solo ? 'processing.error.soloKey' : 'processing.error.pairedKey' })
    const p = info.provider as Provider, base = f.kind === 'pdf' ? 8000 : 4000
    const max = p === 'openai' ? this.cap(base) : base
    const text = f.kind === 'pdf'
      ? await pdfText(this.endpoints(), p, key, info.model, PDF_PROMPT, f.name, f.data, max)
      : await vision(this.endpoints(), p, key, info.model, how === 'digest' ? DIGEST_PROMPT : appendLanguage(ATTACH_PROMPT, language, 'describe'), mediaType(f.name, f.type), f.data, max)
    if (!text) throw Object.assign(new AiError('The AI sent back no text.'), { displayKey: 'capture.attachment.emptyAi' })
    return text
  }

  // ── Describe and Categorize on the phone (milestone-2026-10-14/plans/E-phone-fixes.md): the PC's two
  // item jobs (knowledge/tasks.py), run with the phone's own key and Wiskit's model; the result goes to
  // the PC as an `edit` change. Describe = thumbnail + caption (a transcript when the PC analysed the
  // video); a full video analysis stays on the PC.
  private itemAi() {
    const info = this.ai()
    const key = info && this.keys()[info.provider as Provider]
    if (!info || !key || !info.model) throw Object.assign(new AiError(this.noKey()), { displayKey: this.solo ? 'processing.error.soloKey' : 'processing.error.pairedKey' })
    const p = info.provider as Provider
    return { p, key, model: info.model, cap: (n: number) => (p === 'openai' ? this.cap(n) : n) }
  }

  async describe(id: number, undo?: (t: ToolsUndo) => void): Promise<string | null> {
    const language = lang()
    await this.ready()
    const r = this.byId.get(id)
    if (!r?.uid) throw new Error('This card is not in the phone\'s copy.')
    const full = await this.item(id)
    const saved = this.texts.get(id)
    const content = { ...full, transcript: saved?.transcript || full.transcript || '', report: saved?.report || '' }
    const blob = await this.thumbBlob(r).catch(() => null)
    const b64 = blob ? toB64(new Uint8Array(await blob.arrayBuffer())) : ''
    if (!hasDescribeContent(content, !!b64)) return null
    const a = this.itemAi()
    const prompt = appendLanguage(describePrompt(content, !!b64), language, 'describe')
    const text = b64
      ? await vision(this.endpoints(), a.p, a.key, a.model, prompt, blob!.type || 'image/jpeg', b64, a.cap(DESCRIBE_TOKENS))
      : await complete(this.endpoints(), a.p, a.key, a.model, prompt, a.cap(DESCRIBE_TOKENS))
    if (!text.trim()) throw new AiError('The AI sent back no text.')
    if (text.trim() === NO_CONTENT) return null
    await this.changes.add({ op: 'edit', uid: r.uid, fields: { ai_desc: text }, was: { ai_desc: full.ai_desc || '' } })
    undo?.({ kind: 'describe', uid: r.uid, was: { ai_desc: full.ai_desc || '' }, now: { ai_desc: text } })    // Tools' Undo token (a single-item run keeps it)
    this.setRows()
    this.flushSoon()
    return text
  }

  // Tools' Undo on one item (projects/phone-processing-flow, plans/00-review-repairs.md R5): one more `edit` change puts
  // back what the single-item Describe or Auto-categorize replaced, but only while the card still holds what that run
  // wrote. The card is found by its uid (a link's number can change when the PC numbers it); the written values are the
  // change's `was`, so the PC still keeps a newer edit of its own (server/intake.py); a card that changed or is gone
  // writes nothing (UndoRefused); two calls take turns. A restored empty description puts the card's own text back:
  // `plain` rides on the local change only (mirror/changes.ts) and never reaches the change file.
  async undoTool(t: ToolsUndo): Promise<Row> {
    await this.ready()
    let row: Row
    await this.changes.commitUndo(async (): Promise<Omit<ChangeEntry, 'state' | 'at'>> => {
      this.setRows()
      const r = this.rowsNow.find(x => x.uid === t.uid)
      if (!r?.uid) throw new UndoRefused('This card is no longer on the phone, so nothing was undone.')
      row = r
      if (t.kind === 'describe') {
        const full = await this.item(r.id)
        if ((full.ai_desc || '').trim() !== (t.now.ai_desc ?? '').trim()) throw new UndoRefused('The description changed after Describe, so nothing was undone.')
        const empty = !(t.was.ai_desc ?? '').trim()
        return { op: 'edit', uid: r.uid, fields: { ai_desc: t.was.ai_desc ?? '' }, was: { ai_desc: t.now.ai_desc ?? '' },
          ...(empty && r.id > 0 ? { plain: (full.description || '').slice(0, 200) } : {}) }     // 200: the mirror row's SNIPPET
      } else {
        if (r.cat !== t.now.cat || r.tags !== t.now.tags) throw new UndoRefused('The collection or tags changed after Auto-categorize, so nothing was undone.')
        return { op: 'edit', uid: r.uid, fields: { category: t.was.cat ?? '', tags: t.was.tags ?? '' }, was: { category: r.cat, tags: r.tags } }
      }
    })
    this.flushSoon()
    return this.replace(row!)
  }

  async categorize(id: number, categories: string[]): Promise<Row> {
    const language = lang()
    await this.ready()
    const r = this.byId.get(id)
    if (!r?.uid) throw new Error('This card is not in the phone\'s copy.')
    if (!categories.length) throw Object.assign(new Error('There are no collections to choose from yet.'), { displayKey: 'capture.suggest.noCollections' })
    const a = this.itemAi()
    const full = await this.item(id)
    const text = await complete(this.endpoints(), a.p, a.key, a.model, appendLanguage(categorizePrompt(full, categories), language, 'tags'), a.cap(CATEGORIZE_TOKENS))
    const got = parseCategory(text, categories)
    return this.edit(id, { category: got.category, tags: mergeTags(r.tags, got.tags) })
  }

  // Add's Suggest (projects/phone-add-confirm): Categorize's prompt for a link that is not a card yet. Nothing is
  // written or queued; the recap shows the answer and Save sends it with the link.
  async suggestCategory(item: ItemText, categories: string[]): Promise<{ category: string; tags: string }> {
    const language = lang()
    if (!categories.length) throw Object.assign(new Error('There are no collections to choose from yet.'), { displayKey: 'capture.suggest.noCollections' })
    const a = this.itemAi()
    const text = await complete(this.endpoints(), a.p, a.key, a.model, appendLanguage(categorizePrompt(item, categories), language, 'tags'), a.cap(CATEGORIZE_TOKENS))
    return parseCategory(text, categories)
  }

  // vault sync (Android app): the folder in kv 'vault' against the PC's list, through this pairing's Drive and key
  async syncVault(force = false, progress?: VaultEnv['progress'], signal?: { aborted: boolean }, words?: (key: string, params?: Record<string, unknown>) => string): Promise<VaultResult> {
    const opts = await kv.get<{ on: boolean; uri: string; name: string }>('vault')
    if (!opts?.on || !opts.uri) return { state: 'idle', reason: 'Vault sync is off.', summary: '' }
    if (await this.nativeReady()) {
      await nativeSyncPolicy({ vault: opts.on, uri: opts.uri })
      if (signal?.aborted) return { state: 'stopped', reason: '', summary: '' }
      await nativeRound(force, false, this.nativeDirty, s => {
        const step = s.phase === 'vault' ? s.vaultStep : undefined
        progress?.(step?.key ?? 'Syncing the vault', step?.done ?? 0, step?.total ?? 0, undefined,
          words?.(step?.key ?? 'backup.vault.starting'), s.vaultFiles ?? undefined)
      })
      this.nativeDirty = false
      const result = await nativeCache<VaultResult & { display?: Partial<Record<'reason' | 'summary', { key: string; params?: Record<string, unknown> }>> }>(this.nativeScope, 'vault-result')
      if (!result) return { state: 'waiting', reason: '', summary: '' }
      for (const field of ['reason', 'summary'] as const) {
        const message = result.display?.[field]
        if (message) result[field] = words ? words(message.key, message.params) : t(message.key as Key, message.params)
      }
      return result
    }
    const fs = vaultFs(opts.uri)
    await this.drive.authorize()
    return vaultRound({
      drive: this.drive, key: await this.key, fs: { ...fs,
        write: async (path, data) => { await this.drive.authorize(); await fs.write(path, data) },
        remove: async path => { await this.drive.authorize(); await fs.remove(path) },
      }, device: deviceId(), force, progress, signal, words,
      load: async () => kv.get('vault-state'), save: async s => { await kv.setRequired('vault-state', s) },
    })
  }
  // the PC's last vault round (state, step, done/total), null until the PC has written one
  async vaultPc(): Promise<PcStatus | null> { return pcStatus(this.drive, await this.key) }

  // Remove old Brainamon pages (spec 1b decision 3): the leftover Content Manager/ copies of the folder in kv 'vault'
  async vaultRemoveLegacy(): Promise<number> {
    const opts = await kv.get<{ on: boolean; uri: string; name: string }>('vault')
    if (!opts?.uri) return 0
    if (await this.nativeReady()) { await nativeRound(false, true); return await nativeCache<number>(this.nativeScope, 'vault-legacy-moved') ?? 0 }
    return removeLegacy({ fs: vaultFs(opts.uri) })
  }

  // ── canvases ──────────────────────────────────────────────────────────────
  private async mirrorCanvas(id: string, pcOnly = false): Promise<CanvasDocument | null> {
    const m = await this.man().catch(() => null)
    if (m?.files[`canvases/${id}.json`]) {
      try {
        const d = JSON.parse(await this.cached(`canvases/${id}.json`)) as CanvasDocument
        if (d?.id === id && Array.isArray(d.items)) return d
      } catch { /* use the pinned local copy below */ }
    }
    if (pcOnly) return null
    const saved = (await kv.get<{ id: string; doc: CanvasDocument }[]>('saved-canvases')) ?? []
    return saved.find(x => x.id === id)?.doc ?? null
  }

  private async effectiveCanvas(id: string): Promise<CanvasDocument | null> {
    await this.ready()
    this.unresolvedCanvases.delete(id)
    this.supersededCanvases.delete(id)
    const canonical = await this.mirrorCanvas(id, true)
    const saved = canonical ? null : ((await kv.get<{ id: string; doc: CanvasDocument }[]>('saved-canvases')) ?? []).find(c => c.id === id)?.doc ?? null
    let doc = canonical || saved
    const pcAt = doc?.modified ?? doc?.created ?? 0
    const byUid = new Map(this.rowsNow.map(r => [r.uid, r.id])), uidOf = new Map(this.rowsNow.map(r => [r.id, r.uid]))
    const ops = this.changes.list.filter(e => e.op === 'canvas' && e.canvas_id === id)
      .sort((a, b) => (a.proposal?.new_name ? -1 : 0) - (b.proposal?.new_name ? -1 : 0)
        || (a.id ?? 0) - (b.id ?? 0) || a.at - b.at || (a.op_id ?? '').localeCompare(b.op_id ?? ''))
    // A pinned local snapshot already includes the operations through its last reflected result.
    const savedOps = new Set(saved?.items.map(e => e.id.split('_')[0]))
    const savedElements = new Map(saved?.items.map(e => [e.id, canonJson(e)]))
    let through = -1
    if (saved) ops.forEach((e, i) => {
      const result = e.canvasLocal?.result.items
      if (savedOps.has(e.op_id!) || result?.length && result.every(el => savedElements.get(el.id) === canonJson(el))) through = i
    })
    for (const [i, e] of ops.entries()) {
      if (i <= through) continue
      if (doc?.phone_ops?.[e.op_id ?? '']) continue
      if (e.canvasLocal?.status === 'refused') {
        // the kept phone copy, until the PC's own canvas changes after the refusal
        if (e.canvasLocal.pc !== undefined && pcAt > e.canvasLocal.pc) this.supersededCanvases.add(id)
        else doc = e.canvasLocal.result
        continue
      }
      try {
        const raw = structuredClone(e.proposal ?? {})
        const dims = new Map<number, [number, number]>(), missing = new Map<number, string>()
        for (const x of (raw.elements as Record<string, unknown>[] ?? [])) if (x.kind === 'thumbnail') {
          const uid = e.refs?.[String(x.item_id)]
          if (!uid) throw Object.assign(new Error('A canvas item reference is missing.'), { displayKey: 'common.error.canvasReferenceMissing' })
          // an item not on this phone (a change restored from a backup) keeps its place as a placeholder
          let localId = byUid.get(uid)
          if (localId === undefined) {
            localId = [...missing].find(([, u]) => u === uid)?.[0] ?? Number.MIN_SAFE_INTEGER + missing.size
            missing.set(localId, uid)
          }
          x.item_id = localId
          if (e.sizes?.[uid]) dims.set(localId, e.sizes[uid])
        }
        const p = normalizeCanvas(raw)
        if (p.canvas_id && !doc) { this.unresolvedCanvases.add(id); throw Object.assign(new Error('The earlier canvas creation is missing.'), { displayKey: 'common.error.canvasEarlierMissing' }) }
        doc = applyCanvasLocal(p, doc, dims, e.op_id!, id, e.at)
        for (const el of doc.items) if (el.source === 'db' && el.item_id !== undefined && !el.uid) {
          const uid = missing.get(el.item_id) ?? uidOf.get(el.item_id)
          if (uid) el.uid = uid
          if (missing.has(el.item_id)) delete el.item_id
        }
      } catch { if (e.canvasLocal?.result) doc = e.canvasLocal.result }
    }
    // a kept copy names items by UID: a saved link's negative ID ends when its change is pruned
    if (doc?.items.some(el => el.uid && byUid.get(el.uid) !== el.item_id)) {
      doc = { ...doc, items: doc.items.map(el => {
        const now = el.uid ? byUid.get(el.uid) : el.item_id
        if (now === el.item_id) return el
        const c = { ...el }
        if (now === undefined) delete c.item_id; else c.item_id = now
        return c
      }) }
    }
    for (const e of ops) for (const asset of e.canvasLocal?.assets ?? []) {
      const row = asset.uid ? this.rowsNow.find(r => r.uid === asset.uid) : null
      const url = asset.file ? this.canvasImageUrl(asset.file) : row ? this.thumbUrl(row) : ''
      if (url) {
        try {
          const cache = await caches.open(asset.file ? MIRROR_CACHE : THUMB_CACHE)
          if (!await cache.match(url)) await cache.put(url, new Response(asset.blob))
        } catch { /* geometry and notes remain readable when image cache is full */ }
      }
    }
    return doc
  }

  private async reconcileCanvas() {
    await this.changes.load()
    let changed = false
    for (const e of [...this.changes.list]) {
      if (e.op !== 'canvas' || !e.op_id || !e.canvas_id) continue
      const receipt = this.canvasReceipts[e.op_id]
      if (!receipt || receipt.canvas_id !== e.canvas_id) continue
      if (receipt.hash !== await canvasHash(e)) {
        if (e.canvasLocal?.status !== 'refused') changed = await this.refuseCanvas(e, 'The PC saw different content for this canvas operation ID.') || changed
        continue
      }
      if (receipt.state === 'refused') {
        if (e.canvasLocal?.status !== 'refused') changed = await this.refuseCanvas(e, receipt.reason || 'The PC refused this change.') || changed
        continue
      }
      const m = await this.man()
      if (!m.files[`canvases/${e.canvas_id}.json`] && m.canvases) {
        // applied, and the PC publishes canvases, yet this one is gone: Fred deleted it on the PC
        const saved = (await kv.get<{ id: string }[]>('saved-canvases')) ?? []
        if (saved.some(x => x.id === e.canvas_id)) await putCanvasPending('saved-canvases', saved.filter(x => x.id !== e.canvas_id))
        await this.changes.pruneCanvas(e)
        changed = true
        continue
      }
      if (!m.files[`canvases/${e.canvas_id}.json`]) {
        if (e.canvasLocal?.status !== 'synced') {
          const result = e.canvasLocal?.result || await this.effectiveCanvas(e.canvas_id)
          if (result) { e.canvasLocal ??= { base: null, result, assets: [], status: 'pending' }; await this.changes.canvasResult(e, 'synced'); changed = true }
        }
        continue
      }
      let canonical: CanvasDocument
      try { canonical = JSON.parse(await this.cached(`canvases/${e.canvas_id}.json`)) }
      catch { continue }
      if (canonical?.phone_ops?.[e.op_id] !== receipt.hash || !Array.isArray(canonical.items)) continue
      try {
        const saved = (await kv.get<{ id: string; name: string; at: number; size: number; doc: CanvasDocument; images: string[] }[]>('saved-canvases')) ?? []
        const images: string[] = []
        const cache = await caches.open(MIRROR_CACHE)
        const thumbCache = await caches.open(THUMB_CACHE)
        let bytes = JSON.stringify(canonical).length
        for (const el of canonical.items) {
          if (el.source === 'file' && el.file_path) {
            const file = el.file_path.split(/[\\/]/).pop()!
            if (images.includes(file)) continue
            const blob = e.canvasLocal?.assets.find(a => a.file === file)?.blob || await this.canvasImage(file)
            await cache.put(this.canvasImageUrl(file), new Response(blob)); images.push(file); bytes += blob.size
          } else if (el.source === 'db' && el.item_id !== undefined) {
            const row = this.byId.get(el.item_id)
            if (!row) throw Object.assign(new Error('A canonical canvas item is missing from the mirror.'), { displayKey: 'common.error.canvasCanonicalMissing' })
            const blob = e.canvasLocal?.assets.find(a => a.uid === row.uid)?.blob || await this.thumbBlob(row)
            if (!blob) throw Object.assign(new Error('A canonical thumbnail is unavailable.'), { displayKey: 'common.error.canvasThumbnailMissing' })
            await thumbCache.put(this.thumbUrl(row), new Response(blob)); bytes += blob.size
          }
        }
        await putCanvasPending('saved-canvases', [{ id: e.canvas_id, name: canonical.name, at: Date.now(), size: bytes,
          doc: canonical, images }, ...saved.filter(x => x.id !== e.canvas_id)])
        await this.changes.pruneCanvas(e)
        changed = true
      } catch { if (e.canvasLocal?.status !== 'synced') await this.changes.canvasResult(e, 'synced') }
    }
    if (changed) window.dispatchEvent(new Event('brainamon-canvas-change'))
  }

  // keep the phone copy and say why the PC did not take it
  private async refuseCanvas(e: ChangeEntry, reason: string): Promise<boolean> {
    const result = e.canvasLocal?.result || await this.effectiveCanvas(e.canvas_id!)
    if (!result) return false
    const pc = await this.mirrorCanvas(e.canvas_id!, true)
    e.canvasLocal ??= { base: null, result, assets: [], status: 'pending' }
    e.canvasLocal.pc = pc?.modified ?? pc?.created ?? 0
    await this.changes.canvasResult(e, 'refused', reason)
    return true
  }

  // the mirror's canvas list (canvases/index.json), with no canvas file read
  private async canvasIndex(): Promise<{ id: string; name?: string; item_count?: number; modified?: number }[]> {
    const m = await this.man().catch(() => null)
    if (!m?.files['canvases/index.json']) return []
    try {
      const idx = JSON.parse(await this.cached('canvases/index.json')) as { id: string }[]
      return Array.isArray(idx) ? idx.filter(e => typeof e?.id === 'string' && m.files[`canvases/${e.id}.json`]) : []
    } catch { return [] }      // offline with nothing cached: the phone's own canvases still list
  }

  // what Quick tells the model: the index and the phone's new canvases, without folding any canvas
  private async canvasList(): Promise<CanvasRow[]> {
    const rows = new Map((await this.canvasIndex()).map(e => [e.id, { id: e.id, name: String(e.name ?? ''), count: Number(e.item_count) || 0, updated: Number(e.modified) || 0 }]))
    await this.ready()
    for (const e of this.changes.list) if (e.op === 'canvas' && e.canvas_id && !rows.has(e.canvas_id) && typeof e.proposal?.new_name === 'string')
      rows.set(e.canvas_id, { id: e.canvas_id, name: e.proposal.new_name, count: Array.isArray(e.proposal.elements) ? e.proposal.elements.length : 0, updated: e.at })
    return [...rows.values()].sort((a, b) => b.updated - a.updated)
  }

  async canvases(): Promise<CanvasRow[]> {
    const idx = await this.canvasIndex()
    await this.ready()
    const saved = (await kv.get<{ id: string }[]>('saved-canvases')) ?? []
    const ids = new Set([...idx.map(e => e.id), ...saved.map(e => e.id),
      ...this.changes.list.filter(e => e.op === 'canvas' && e.canvas_id).map(e => e.canvas_id!)])
    const rows: CanvasRow[] = []
    for (const id of ids) {
      const d = await this.effectiveCanvas(id)
      if (this.unresolvedCanvases.has(id)) rows.push({ id, name: 'Canvas waiting for earlier backup', count: 0, updated: 0 })
      else if (d) rows.push({ id, name: d.name, count: d.items.length, updated: d.modified ?? d.created ?? 0 })
    }
    return rows.sort((a, b) => b.updated - a.updated)
  }
  canvasTitle(id: string, words?: ToolWords): string {
    return this.unresolvedCanvases.has(id) ? say(words, 'canvas.waitingBackup', {}, 'Canvas waiting for earlier backup') : ''
  }
  async canvas(id: string): Promise<CanvasDoc> {
    const d = await this.effectiveCanvas(id)
    if (!d) throw Object.assign(new Error('This canvas is unavailable. Refresh and try again.'), { displayKey: 'common.error.canvasUnavailable' })
    return d as CanvasDoc
  }
  async canvasDraftProblem(id: string, words?: ToolWords): Promise<string | null> {
    const doc = await this.effectiveCanvas(id), canonical = await this.mirrorCanvas(id)
    const pc = await this.mirrorCanvas(id, true)
    const ops = this.changes.list.filter(e => e.op === 'canvas' && e.canvas_id === id)
    const creation = ops.find(e => e.proposal?.new_name)
    if (creation?.canvasLocal?.status === 'refused') return say(words, 'canvas.status.refusedCreation', { reason: creation.canvasLocal.reason || say(words, 'canvas.status.creationReason', {}, 'The PC refused this creation.') }, `Not synced: ${creation.canvasLocal.reason || 'The PC refused this creation.'}`)
    if (!canonical && !creation || !doc || this.unresolvedCanvases.has(id)) return say(words, 'canvas.status.missing', {}, 'Earlier canvas creation is missing. Refresh after the backup arrives.')
    const pcAt = canonical?.modified ?? canonical?.created ?? 0
    for (const e of ops) {
      if (e.canvasLocal?.status !== 'refused' || canonical?.phone_ops?.[e.op_id!] === await canvasHash(e)) continue
      if (pc && e.canvasLocal.pc !== undefined && (pc.modified ?? pc.created ?? 0) > e.canvasLocal.pc) continue
      const existing = Array.isArray(e.proposal?.elements) ? e.proposal.elements as { kind: string; id?: string }[] : []
      const kept = doc.items.some(el => el.id.startsWith(`${e.op_id}_`)) || existing.some(p => {
        if (p.kind !== 'existing') return false
        const before = e.canvasLocal?.base?.items.find(el => el.id === p.id), after = e.canvasLocal?.result.items.find(el => el.id === p.id), now = doc.items.find(el => el.id === p.id)
        return after && now && (!before || before.x !== after.x || before.y !== after.y) && now.x === after.x && now.y === after.y
      })
      if (kept || e.canvasLocal.pc === undefined || pcAt <= e.canvasLocal.pc)
        return say(words, 'canvas.status.refused', { reason: e.canvasLocal.reason || say(words, 'canvas.status.changeReason', {}, 'The PC refused this change.'), kept: say(words, 'canvas.status.kept', {}, 'Your phone copy is kept.') }, `Not synced: ${e.canvasLocal.reason || 'The PC refused this change.'} Your phone copy is kept.`)
    }
    return null
  }
  canvasStatus(id: string, words?: ToolWords): string {
    if (this.unresolvedCanvases.has(id)) return say(words, 'canvas.status.missing', {}, 'Earlier canvas creation is missing. Refresh after the backup arrives.')
    const last = this.changes.list.filter(e => e.op === 'canvas' && e.canvas_id === id).at(-1)
    if (last?.canvasLocal?.status === 'refused') return say(words, 'canvas.status.refused', { reason: last.canvasLocal.reason || say(words, 'canvas.status.changeReason', {}, 'The PC refused this change.'), kept: this.supersededCanvases.has(id) ? say(words, 'canvas.status.pcCopy', {}, 'The PC changed this canvas since, so its copy is shown.') : say(words, 'canvas.status.kept', {}, 'Your phone copy is kept.') }, `Not synced: ${last.canvasLocal.reason || 'The PC refused this change.'} ${this.supersededCanvases.has(id) ? 'The PC changed this canvas since, so its copy is shown.' : 'Your phone copy is kept.'}`)
    if (last?.canvasLocal?.status === 'synced') return say(words, 'canvas.status.synced', {}, 'Synced')
    if (last) return this.solo ? say(words, 'canvas.status.phone', {}, 'On this phone') : this.manifest?.canvas_change === 1 ? say(words, 'canvas.status.waiting', {}, 'Waiting to sync') : say(words, 'canvas.status.update', {}, 'Saved on this phone. Update the PC to sync canvases.')
    return say(words, 'canvas.status.synced', {}, 'Synced')
  }
  lastCanvasRefusal(): { id: string; reason: string } | null {
    const e = [...this.changes.list].reverse().find(e => e.op === 'canvas' && e.canvas_id && e.canvasLocal?.status === 'refused')
    return e ? { id: e.canvas_id!, reason: e.canvasLocal!.reason || 'The PC refused this change.' } : null
  }

  // ── videos (the PC mirrors them: Off / Favourites / All) ───────────────────
  videoSize(id: number) {
    const uid = this.byId.get(id)?.uid
    return (uid && this.manifest?.files[`videos/${uid}.bin`]?.size) || 0
  }
  async video(id: number, onProgress?: (got: number, total: number) => void): Promise<Blob> {
    await this.ready()
    const uid = this.byId.get(id)?.uid
    const logical = `videos/${uid}.bin`
    const m = await this.man()
    const f = m.files[logical]
    if (!uid || !f) throw Object.assign(new Error('The PC has not put this video in Google Drive.'), { displayKey: 'common.error.videoNotUploaded' })
    const id_ = f.id ?? (await this.drive.find(f.n))?.id
    if (!id_) throw Object.assign(new Error('The video is missing from Google Drive.'), { displayKey: 'common.error.videoMissing' })
    const blob = await this.drive.get(id_, onProgress)
    const parts = await (await this.key).openVideo(logical, blob, f)
    return new Blob(parts as BlobPart[], { type: 'video/mp4' })
  }

  // ── Wiskit: the chats (the mirror's, with the phone's on top) ───────────────
  private drafts = new Map<string, Chat>()      // New chat, until its first question

  private async chatFiles() {
    await this.man()
    return pool(this.names('chats/', '.json'), 4, async k => {
      try { return { slug: k.slice(6, -5), d: JSON.parse(await this.cached(k)) as { name?: string; created?: string; updated?: string; history?: Turn[]; source_ids?: number[] } } } catch { return null }
    })
  }
  // the newest change for each chat the phone asked in, and the chats it deleted since
  private phoneChats(): Map<string, ChangeEntry> {
    const m = new Map<string, ChangeEntry>()
    for (const e of this.changes.list) if (e.op === 'chat' && e.slug) m.set(e.slug, e); else if (e.op === 'chat_delete' && e.slug) m.delete(e.slug)
    return m
  }
  private deletedChats(): Set<string> {
    const d = new Set<string>()
    for (const e of this.changes.list) if (e.op === 'chat_delete' && e.slug) d.add(e.slug); else if (e.op === 'chat' && e.slug) d.delete(e.slug)
    return d
  }
  async chats() {
    await this.changes.load()
    const list = new Map<string, ChatRow>(), gone = this.deletedChats()
    for (const c of await this.chatFiles()) {
      if (c && !gone.has(c.slug)) list.set(c.slug, { slug: c.slug, name: c.d.name || 'Chat', created: c.d.created || '', updated: c.d.updated || c.d.created || '',
        message_count: (c.d.history || []).length, source_count: (c.d.source_ids || []).length })
    }
    for (const [slug, e] of this.phoneChats()) {
      list.set(slug, { slug, name: e.name || 'Chat', created: e.created || isoNow(e.at), updated: isoNow(e.at), message_count: (e.history || []).length, source_count: (e.source_ids || []).length })
    }
    for (const d of this.drafts.values()) if (!list.has(d.slug)) list.set(d.slug, { slug: d.slug, name: d.name, created: isoNow(), updated: isoNow(), message_count: 0, source_count: 0 })
    const rows = [...list.values()].sort((a, b) => b.updated.localeCompare(a.updated))
    return { chats: rows, active: rows[0]?.slug ?? '' }
  }
  async chat(slug: string): Promise<Chat> {
    await this.ready()
    const e = this.phoneChats().get(slug)
    if (e) return { slug, name: e.name || 'Chat', history: e.history || [], sources: (e.source_ids || []).map(i => this.byId.get(i)).filter((r): r is MRow => !!r) }
    const d = this.drafts.get(slug)
    if (d) return d
    if (this.deletedChats().has(slug)) throw Object.assign(new Error('This chat was deleted.'), { displayKey: 'common.error.chatDeleted' })
    const c = JSON.parse(await this.cached(`chats/${slug}.json`)) as { name?: string; history?: Turn[]; source_ids?: number[] }
    return { slug, name: c.name || 'Chat', history: (c.history || []).filter(t => t && (t.role === 'user' || t.role === 'assistant')), sources: (c.source_ids || []).map(i => this.byId.get(i)).filter((r): r is MRow => !!r) }
  }
  async newChat(name = 'New chat'): Promise<Chat> {
    const c: Chat = { slug: `${chatSlug(name)}-${hex(2)}`, name, history: [], sources: [] }
    this.drafts.set(c.slug, c)
    return c
  }
  // gone from the list at once; the PC deletes its copy when it applies the change (server/intake.py
  // `chat_delete`), unless someone asked in it on the PC since
  async deleteChat(slug: string): Promise<void> {
    if (this.drafts.delete(slug)) return             // never asked in: the PC has nothing
    const c = await this.chat(slug).catch(() => null)
    await this.changes.dropQueuedChat(slug)
    await this.changes.add({ op: 'chat_delete', slug, turns: c?.history.length ?? 0 })
    this.flushSoon()
  }

  // ── the phone's own AI ─────────────────────────────────────────────────────
  private keys(): Partial<Record<Provider, string>> { return this.pair.ai || {} }
  // the AI keys a new pairing left in Drive (a note for the More screen, or '')
  takeKeys(): Promise<string> { return takeKeys(this.pair, this.drive, this.words) }
  async forgetKeys() {
    const next = { ...this.pair }
    forgetKeys(next)
    await secretsSaved()
    this.pair.ai = next.ai
    delete this.pair.t; delete this.pair.tx
  }
  private endpoints(): Endpoints { return { ...CLOUD, ...(this.pair.x || {}) } }
  private settings(): AiSettings | null { return this.meta?.ai ?? (this.solo ? PHONE_AI as AiSettings : null) }
  private noKey(words?: ToolWords) { return this.solo ? say(words, 'processing.error.soloKey', {}, SOLO_NO_KEY) : say(words, 'processing.error.pairedKey', {}, NO_KEY) }
  // the Tools panel's no-key line (projects/phone-processing-flow), before any AI call
  noKeyText(words?: ToolWords) { return this.noKey(words) }

  ai(): AiInfo | null {
    const st = this.settings(), keys = this.keys()
    let found: Partial<Record<Provider, { id: string; label: string }[]>> = {}
    try { found = JSON.parse(localStorage.getItem(AI_FOUND) || '{}') } catch { /* none */ }
    const withFound = (p: Provider) => {
      const base = st?.ask.models[p] ?? [], ids = new Set(base.map(m => m.id))
      return [...base, ...(found[p] ?? []).filter(m => !ids.has(m.id))]
    }
    const providers = (['anthropic', 'openai'] as Provider[]).filter(p => keys[p]).map(p => ({ id: p, label: PROVIDER_LABEL[p], models: withFound(p) }))
    if (!providers.length) return null
    let pick: { provider?: string; model?: string } = {}
    try { pick = JSON.parse(localStorage.getItem(AI_PICK) || '{}') } catch { /* none */ }
    const prov = providers.find(p => p.id === pick.provider) ?? providers.find(p => p.id === st?.ask.default) ?? providers[0]
    const model = prov.models.find(m => m.id === pick.model) ?? prov.models[0]
    const syn = this.synthChoice()
    return { providers, provider: prov.id, model: model?.id ?? '', label: model?.label ?? '', smart: !!keys.openai, synth: syn ? `${PROVIDER_LABEL[syn[0]]} · ${syn[1]}` : '' }
  }
  setAi(provider: string, model: string) {
    try { localStorage.setItem(AI_PICK, JSON.stringify({ provider, model })) } catch { /* private window */ }
  }
  // ai_client.discover_cloud_models, from the phone with its own keys: one line per provider for More
  async refreshModels(words?: ToolWords, signal?: AbortSignal): Promise<string> {
    const keys = this.keys(), ep = this.endpoints(), retired = this.settings()?.retired ?? []
    let found: Partial<Record<Provider, { id: string; label: string }[]>> = {}
    try { found = JSON.parse(localStorage.getItem(AI_FOUND) || '{}') } catch { /* none */ }
    const lines = await Promise.all((['anthropic', 'openai'] as Provider[]).filter(p => keys[p]).map(async p => {
      try { found[p] = await listModels(ep, p, keys[p]!, retired, signal); return say(words, 'settings.keys.modelCount', { provider: PROVIDER_LABEL[p], n: found[p]!.length }, `${PROVIDER_LABEL[p]}: ${found[p]!.length} models`) }
      catch (e) { return say(words, 'settings.keys.modelError', { provider: PROVIDER_LABEL[p], detail: (e as Error).message }, `${PROVIDER_LABEL[p]}: ${(e as Error).message}`) }
    }))
    signal?.throwIfAborted()
    try { localStorage.setItem(AI_FOUND, JSON.stringify(found)) } catch { /* private window */ }
    return lines.join(' · ')
  }
  private synthChoice(): [Provider, string] | null {
    const st = this.settings(), keys = this.keys()
    if (st && keys[st.synth.provider as Provider]) return [st.synth.provider as Provider, st.synth.model]
    const p = (['anthropic', 'openai'] as Provider[]).find(x => keys[x])
    const m = p && st?.ask.models[p]?.[0]?.id
    return p && m ? [p, m] : null
  }
  // ai_client._ask_cap: cloud models get the floor (they think before answering)
  private cap(n: number) { return Math.max(n, this.settings()?.cloud_min_tokens ?? 8000) }

  // the phone's stand-in for the desktop's db, rebuilt when the mirror or the phone's notes change
  private lib: { v: string; data: PhoneLibrary } | null = null
  private async library(signal?: AbortSignal, deadline?: number): Promise<PhoneLibrary> {
    await this.ready()
    const m = await this.man()
    const parts = this.names('search/text-')
    if (!parts.length && !this.solo) throw new AiError(NO_TEXT)    // solo: Wiskit reads the notes
    const v = `${m.published}:${this.changes.list.length}:${this.rowsNow.length}`
    if (this.lib?.v === v) return this.lib.data
    return this.once('library', async () => {
      const texts = (await pool(parts, 3, async k => {
        signal?.throwIfAborted()
        if (deadline !== undefined && performance.now() >= deadline) return []
        return JSON.parse(await this.cached(k)) as TextRow[]
      })).flat()
      const notes: Note[] = (await this.noteFiles(signal, deadline)).map(n => ({ filename: n.file, topic: n.meta.topic || n.file.replace(/\.md$/, ''), body: n.body }))
      const data = new PhoneLibrary(texts, this.rowsNow.filter(r => r.id > 0).map(r => ({ id: r.id, cat: r.cat, url: r.url, created: r.created, type: r.type })), notes)
      if (deadline === undefined || performance.now() < deadline) this.lib = { v, data }
      return data
    })
  }

  // a note file name the phone shows until the PC's copy arrives (the PC picks its own)
  private async newNoteFile(title: string): Promise<string> {
    const taken = new Set((await this.noteFiles()).map(n => n.file))
    const base = slug(title)
    let f = `${base}.md`
    for (let n = 2; taken.has(f); n++) f = `${base}-${n}.md`
    return f
  }

  private categoryKey() { return `wiskit-category-proposal:${this.pair.f}` }
  private canvasKey() { return `wiskit-canvas-proposal:${this.pair.f}` }
  private proposalLocked<T>(f: () => Promise<T>): Promise<T> {
    const p = this.proposalQueue.then(f, f)
    this.proposalQueue = p.catch(() => {})
    return p
  }

  async canvasProposal(): Promise<PhoneCanvasProposal | null> {
    const p = await kv.get<{ token: string; preview: PhoneCanvasProposal['preview'] }>(this.canvasKey())
    return p ? { mode: 'local', token: p.token, preview: p.preview } : null
  }

  private async canvasSizes(p: CanvasProposal, refs: Record<string, string>): Promise<Map<number, [number, number]>> {
    const sizes = new Map<number, [number, number]>()
    for (const e of p.elements) if (e.kind === 'thumbnail' && !sizes.has(e.item_id!)) {
      const r = this.byId.get(e.item_id!)
      if (!r?.uid || r.uid !== refs[String(e.item_id)]) throw Object.assign(new Error('A canvas item changed. Ask Wiskit for a fresh proposal.'), { displayKey: 'common.error.canvasItemChanged' })
      const blob = await this.thumbBlob(r).catch(() => null)
      if (!blob) throw Object.assign(new Error('Thumbnail unavailable offline. Connect and retry, or ask for text only.'), { displayKey: 'common.error.thumbnailOffline' })
      const bitmap = await createImageBitmap(blob)
      sizes.set(e.item_id!, [bitmap.width, bitmap.height]); bitmap.close()
    }
    return sizes
  }

  private async proposeCanvas(raw: RawCanvasProposal, allowed: Set<number> | null,
    onEvent: (e: AskEvent) => void, signal: AbortSignal): Promise<string> {
    return this.proposalLocked(async () => {
      if (signal.aborted) throw new DOMException('Stopped.', 'AbortError')
      if (await this.categoryProposal() || await this.canvasProposal()) return 'Error: review the pending proposal first.'
      await this.ready()
      const p = normalizeCanvas(raw)
      if (p.elements.some(e => e.kind === 'frame')) return 'Error: extracted frames are not in this phone library. Use thumbnails or text.'
      const refs: Record<string, string> = {}
      for (const e of p.elements) if (e.kind === 'thumbnail') {
        const r = this.byId.get(e.item_id!)
        if (!r?.uid || (allowed && !allowed.has(e.item_id!))) return 'Error: use item IDs verified in this turn.'
        refs[String(e.item_id)] = r.uid
      }
      const sizes = await this.canvasSizes(p, refs)
      const base = p.canvas_id ? await this.effectiveCanvas(p.canvas_id) : null
      const names = (await this.canvases()).map(c => ({ id: c.id, name: c.name }))
      const items = new Map(this.rowsNow.map(r => [r.id, r]))
      const preview = checkCanvas(p, base, names, items, sizes)
      if (signal.aborted) throw new DOMException('Stopped.', 'AbortError')
      const token = hex(16)
      await putCanvasPending(this.canvasKey(), { token, raw, refs, preview }, signal)
      onEvent({ ev: 'canvas_proposal', proposal: { mode: 'local', token, preview } })
      return 'Prepared for review on this phone. Nothing changes until you tap Apply.'
    })
  }

  async declineCanvasProposal(review: PhoneCanvasProposal): Promise<void> {
    if (review.mode !== 'local') throw Object.assign(new Error('This is not a phone proposal.'), { displayKey: 'common.error.phoneProposal' })
    await this.proposalLocked(() => declineCanvasPending(this.canvasKey(), review.token))
  }

  async applyCanvasProposal(review: PhoneCanvasProposal): Promise<string> {
    if (review.mode !== 'local') throw Object.assign(new Error('This is not a phone proposal.'), { displayKey: 'common.error.phoneProposal' })
    return this.proposalLocked(async () => {
      await this.ready()
      const pending = await kv.get<{ token: string; raw: RawCanvasProposal; refs: Record<string, string>; quick?: boolean; preview?: PhoneCanvasProposal['preview'] }>(this.canvasKey())
      if (!pending || pending.token !== review.token) throw Object.assign(new Error('This proposal is no longer pending.'), { displayKey: 'common.error.proposalPending' })
      const p = normalizeCanvas(pending.raw)
      const sizes = await this.canvasSizes(p, pending.refs)
      const base = p.canvas_id ? await this.effectiveCanvas(p.canvas_id) : null
      const names = (await this.canvases()).map(c => ({ id: c.id, name: c.name }))
      const current = checkCanvas(p, base, names, new Map(this.rowsNow.map(r => [r.id, r])), sizes)
      if (p.canvas_id && pending.preview && JSON.stringify(current) !== JSON.stringify(pending.preview)) throw Object.assign(new Error('The canvas changed after review. Decline this proposal and prepare it again.'), { displayKey: 'common.error.canvasReviewChanged' })
      const at = Date.now(), op_id = hex(16), canvas_id = p.canvas_id || hex(16)
      return this.commitCanvas(pending.raw, pending.refs, p, base, sizes, op_id, canvas_id, at, undefined, { key: this.canvasKey(), token: review.token })
    })
  }

  async applyCanvasDraft(raw: RawCanvasProposal, context: CanvasDraftContext): Promise<string> {
    return this.proposalLocked(async () => {
      const p = contextCheck(raw, context, true)
      await this.ready()
      const refs = Object.fromEntries(context.thumbs.map(t => [String(t.id), t.uid!]))
      const sizes = new Map(context.thumbs.map(t => [t.id, t.size]))
      const entry: ChangeEntry = { op: 'canvas', op_id: context.opId, canvas_id: context.canvasId, at: context.at,
        state: 'queued', proposal: raw, refs, sizes: Object.fromEntries(context.thumbs.map(t => [t.uid!, t.size])) }
      const old = this.changes.list.find(e => e.op === 'canvas' && e.op_id === context.opId)
      if (old) {
        if (canvasWire(old) !== canvasWire(entry)) throw Object.assign(new Error('Canvas operation ID was reused with different content.'), { displayKey: 'common.error.canvasOperationReused' })
        return old.canvas_id!
      }
      const hash = await canvasHash(entry), canonical = await this.mirrorCanvas(context.canvasId)
      if (canonical?.phone_ops?.[context.opId]) {
        if (canonical.phone_ops[context.opId] !== hash) throw Object.assign(new Error('Canvas operation ID was reused with different content.'), { displayKey: 'common.error.canvasOperationReused' })
        return context.canvasId
      }
      if (!p.canvas_id && (canonical || this.changes.list.some(e => e.op === 'canvas' && e.canvas_id === context.canvasId))) throw Object.assign(new Error('The new canvas ID is occupied.'), { displayKey: 'common.error.canvasIdOccupied' })
      const base = p.canvas_id ? await this.effectiveCanvas(p.canvas_id) : null
      if (p.canvas_id) { const problem = await this.canvasDraftProblem(p.canvas_id); if (problem) throw new Error(problem) }
      if (baseKey(base) !== baseKey(context.base)) throw new Error(CHANGED)
      const used = new Set((base?.items ?? []).filter(e => e.source === 'db').map(e => e.uid || this.byId.get(e.item_id!)?.uid || String(e.item_id)))
      for (const t of context.thumbs) {
        const row = this.byId.get(t.id)
        if (!row || identity(row) !== identity(t) || version(row) !== t.version) throw new Error(CHANGED)
        if (used.has(identity(t))) throw Object.assign(new Error('A picked image is already on this canvas.'), { displayKey: 'common.error.imageAlreadyPicked' })
      }
      checkCanvas(p, base, await this.canvases(), new Map(this.rowsNow.map(r => [r.id, r])), sizes)
      return this.commitCanvas(raw, refs, p, base, sizes, context.opId, context.canvasId, context.at, context)
    })
  }

  private async commitCanvas(raw: RawCanvasProposal, refs: Record<string, string>, p: CanvasProposal,
    base: CanvasDocument | null, sizes: Map<number, [number, number]>, op_id: string, canvas_id: string, at: number,
    context?: CanvasDraftContext, review?: { key: string; token: string }): Promise<string> {
      const retained = context?.thumbs ?? []
      const result = applyCanvasLocal(p, base, sizes, op_id, canvas_id, at)
      for (const el of result.items) if (el.source === 'db' && el.item_id !== undefined && !el.uid) {
        const uid = refs[String(el.item_id)] || this.byId.get(el.item_id)?.uid
        if (uid) el.uid = uid
      }
      const assets: { uid?: string; file?: string; blob: Blob }[] = retained.map(t => ({ uid: t.uid, blob: t.blob }))
      for (const el of result.items) {
        if (el.source === 'db' && el.item_id !== undefined) {
          const row = this.byId.get(el.item_id), uid = row?.uid
          if (uid && !assets.some(a => a.uid === uid)) {
            const blob = await this.thumbBlob(row).catch(() => null)
            if (blob) assets.push({ uid, blob })
          }
        } else if (el.source === 'file' && el.file_path) {
          const file = el.file_path.split(/[\\/]/).pop()!
          if (!assets.some(a => a.file === file)) {
            const blob = await this.canvasImage(file).catch(() => null)
            if (blob) assets.push({ file, blob })
          }
        }
      }
      const sizeRecord: Record<string, [number, number]> = {}
      for (const [id, dims] of sizes) sizeRecord[refs[String(id)]] = dims
      if (context) {
        const current = p.canvas_id ? await this.effectiveCanvas(p.canvas_id) : null
        if (baseKey(current) !== baseKey(base)) throw new Error(CHANGED)
        if (p.canvas_id) { const problem = await this.canvasDraftProblem(p.canvas_id); if (problem) throw new Error(problem) }
        if (retained.some(t => { const r = this.byId.get(t.id); return !r || identity(r) !== identity(t) || version(r) !== t.version })) throw new Error(CHANGED)
      }
      await this.changes.commitCanvas({
        op: 'canvas', op_id, canvas_id, at, state: 'queued', proposal: raw, refs, sizes: sizeRecord,
        canvasLocal: { base, result, assets, status: 'pending' },
      }, review)
      window.dispatchEvent(new Event('brainamon-canvas-change'))
      try { this.flushSoon() } catch { /* the saved operation remains queued */ }
      return canvas_id
  }

  async categoryProposal(): Promise<CategoryProposal | null> { return (await kv.get<CategoryProposal>(this.categoryKey())) ?? null }

  async declineCategoryProposal(): Promise<void> { await kv.del(this.categoryKey()) }

  async applyCategoryProposal(proposal: CategoryProposal): Promise<void> {
    await this.ready()
    const pending = await this.categoryProposal()
    if (!pending || JSON.stringify(pending) !== JSON.stringify(proposal)) throw Object.assign(new Error('This proposal is no longer pending.'), { displayKey: 'common.error.proposalPending' })
    const names = new Set(this.cats().map(c => c.name))
    const seen = new Set<number>(), entries: { uid: string; from: string; category: string }[] = []
    if (!proposal.entries.length || proposal.entries.length > 100) throw Object.assign(new Error('A category batch must contain 1 to 100 items.'), { displayKey: 'common.error.categoryBatchSize' })
    for (const e of proposal.entries) {
      const r = this.byId.get(e.id)
      if (!r?.uid || seen.has(e.id) || r.cat !== e.from || !names.has(e.category)) throw Object.assign(new Error('An item or category changed. Ask Wiskit for a fresh proposal.'), { displayKey: 'common.error.itemCategoryChanged' })
      seen.add(e.id); entries.push({ uid: r.uid, from: e.from, category: e.category })
    }
    await this.changes.add({ op: 'category_batch', entries })
    await this.declineCategoryProposal()
    this.setRows()
    this.flushSoon()
  }

  private async proposeCategories(name: string, args: Record<string, unknown>, allowed: Set<number>, onEvent: (e: AskEvent) => void, signal: AbortSignal): Promise<string> {
    return this.proposalLocked(() => this.prepareCategories(name, args, allowed, onEvent, signal))
  }

  private async prepareCategories(name: string, args: Record<string, unknown>, allowed: Set<number>, onEvent: (e: AskEvent) => void, signal: AbortSignal): Promise<string> {
    if (signal.aborted) throw new DOMException('Stopped.', 'AbortError')
    if (await this.categoryProposal() || await this.canvasProposal()) return 'Error: a proposal is already waiting for review on this phone.'
    const keys = name === 'propose_category' ? ['ids', 'category'] : ['groups']
    if (Object.keys(args).some(k => !keys.includes(k))) return 'Error: unexpected category proposal arguments.'
    const groups = name === 'propose_category' ? [{ ids: args.ids, category: args.category }] : args.groups
    if (!Array.isArray(groups) || !groups.length) return 'Error: give category groups.'
    const names = new Set(this.cats().map(c => c.name)), seen = new Set<number>()
    const entries: CategoryProposal['entries'] = []
    for (const g of groups) {
      if (!g || typeof g !== 'object' || Array.isArray(g)) return 'Error: invalid category group.'
      const group = g as { ids?: unknown; category?: unknown }
      if (Object.keys(group).some(k => !['ids', 'category'].includes(k))) return 'Error: unexpected category group arguments.'
      if (typeof group.category !== 'string' || !names.has(group.category) || !Array.isArray(group.ids) || !group.ids.length) return 'Error: use an exact existing category name and item IDs.'
      for (const id of group.ids) {
        if (!Number.isSafeInteger(id) || !allowed.has(id) || seen.has(id)) return 'Error: use unique IDs verified in this turn only.'
        const r = this.byId.get(id)
        if (!r?.uid) return 'Error: an item is missing from this phone.'
        seen.add(id); entries.push({ id, title: r.title || `No. ${id}`, from: r.cat || '', category: group.category })
      }
    }
    if (entries.length > 100) return 'Error: this phone can review up to 100 items in one category batch.'
    if (signal.aborted) throw new DOMException('Stopped.', 'AbortError')
    const proposal = { entries }
    await putCanvasPending(this.categoryKey(), proposal, signal)
    onEvent({ ev: 'category_proposal', proposal })
    return `${entries.length} category change(s) prepared for review on this phone. Nothing changes until the user taps Apply batch.`
  }

  // Wiskit Quick: knowledge/ask_core.py + server/routes/ask.py _quick, on the phone
  async ask(question: string, chat: string, onEvent: (e: AskEvent, display?: string) => void, signal: AbortSignal, mode: 'quick' | 'deep' = 'quick', words?: ToolWords): Promise<void> {
    const language = lang()
    const q = question.trim()
    if (!q) { onEvent({ ev: 'error', message: say(words, 'wiskit.progress.typeFirst', {}, 'Type a question first.') }); return }
    const info = this.ai()
    const key = info && this.keys()[info.provider as Provider]
    if (!info || !key || !info.model) throw new AiError(this.noKey(words))
    onEvent({ ev: 'start', run: hex(6) })
    const base = chat ? await this.chat(chat).catch(() => null) : null
    const history = base?.history ?? []
    onEvent({ ev: 'progress', line: 'Reading the library…' }, words?.('wiskit.reading'))
    const policy = DEEP.agent_budgets
    const budget = { ...policy[mode] }
    const deadline = performance.now() + budget.research_seconds * 1000
    if (mode === 'deep') {
      const { text, ids, notes } = await this.deep(q, history, info.provider as Provider, key, info.model, info.label, onEvent, signal, language, mode, undefined, deadline, words)
      return this.finish(q, text, ids, base, history, info, onEvent, signal, notes)
    }
    const lib = await this.library(signal, deadline)
    const depth = Q.effectiveDepth(q, Q.L.depth_default)
    const keys = this.keys(), v = await this.vectors().catch(() => null)
    let rows, retrieval, displayRetrieval
    if (keys.openai && v?.ids.length) {
      try {
        const [vec] = await embed(this.endpoints(), keys.openai, v.model, [q], signal)
        rows = Q.rankRows(lib, q, depth, '', k => topk(v, vec, k))
        retrieval = 'keyword + semantic search'; displayRetrieval = words?.('wiskit.retrieval.both')
      } catch (e) {
        if ((e as Error).name === 'AbortError') throw e
        rows = Q.fallbackRows(lib, q, depth, '', lib.all)
        retrieval = Q.fallbackLabel(`embedding failed: ${(e as Error).message.slice(0, 120)}`)
        displayRetrieval = words?.('wiskit.retrieval.fallback', { reason: words('wiskit.retrieval.embedError', { detail: (e as Error).message.slice(0, 120) }) })
      }
    } else {
      rows = Q.fallbackRows(lib, q, depth, '', lib.all)
      retrieval = Q.fallbackLabel(keys.openai ? 'no items indexed - run "Index for search" on the PC' : 'no OpenAI key on this phone')
      displayRetrieval = words?.('wiskit.retrieval.fallback', { reason: words(keys.openai ? 'wiskit.retrieval.noIndex' : 'wiskit.retrieval.noKey') })
    }
    let displayInfo: string | undefined
    const turn = Q.buildTurn(lib, q, rows, history, retrieval, { ...budget, control_chars: policy.control_chars }, words, text => displayInfo = text, displayRetrieval)
    onEvent({ ev: 'context', line: turn.info, ids: turn.sources.map(r => r.id), list: turn.listMode }, displayInfo)
    const { text, ids, notes } = await this.deep(q, history, info.provider as Provider, key, info.model, info.label,
      onEvent, signal, language, mode, turn, deadline, words)
    return this.finish(q, text, Q.answerSources(turn.sources, text, turn.listMode).map(r => r.id).concat(ids).filter((id, n, all) => all.indexOf(id) === n), base, history, info, onEvent, signal, notes)
  }

  // the turn goes back to the PC as the whole chat (server/intake.py `chat`)
  private async finish(q: string, text: string, usedIds: number[], base: Chat | null, history: Turn[], info: AiInfo, onEvent: (e: AskEvent) => void, signal: AbortSignal, noteSources?: string[]) {
    let { slug: s, name } = base ?? { slug: '', name: 'New chat' }
    if (!history.length && (name === 'New chat' || !name)) {
      name = autoName(q) || 'New chat'
      if (!s || this.drafts.has(s)) s = `${chatSlug(name)}-${hex(2)}`
    }
    const prev = this.phoneChats().get(s)
    const mirrored = this.manifest?.files[`chats/${s}.json`] ? await this.cached(`chats/${s}.json`).then(t => (JSON.parse(t) as { updated?: string; created?: string })).catch(() => null) : null
    await this.changes.saveChat({
      op: 'chat', slug: s, name, created: prev?.created || mirrored?.created || isoNow(),
      history: [...history, { role: 'user', content: q }, { role: 'assistant', content: text }],
      source_ids: usedIds, was: prev ? prev.was : (mirrored?.updated ?? ''),
      options: { provider: info.provider, model_id: info.model, model_label: info.label, depth: Q.L.depth_default, scope: '' },
    }, signal)
    if (base) this.drafts.delete(base.slug)
    this.flushSoon()
    onEvent({ ev: 'done', text, cited: citedIds(text).filter(i => usedIds.includes(i)), notes: citedNotes(text).filter(f => noteSources === undefined || noteSources.includes(f)), sources: usedIds.map(i => this.byId.get(i)).filter((r): r is MRow => !!r), chat: { slug: s, name } })
  }

  // ── Wiskit Deep: server/routes/ask.py _deep + ask_core.deep_setup / deep_answer, on the phone ──
  private deepAux: { v: string; data: AuxVectors } | null = null
  private async deepFiles(): Promise<{ topics: Cluster[]; resources: Resource[]; aux: AuxVectors | null }> {
    const m = await this.man()
    if (!m.files['search/deep.json.gz']) {
      if (this.solo) return { topics: [], resources: [], aux: null }     // no PC: no topics, no websites index
      return { topics: [], resources: [], aux: null }
    }
    const d = JSON.parse(await this.cached('search/deep.json.gz')) as { topics?: Cluster[]; resources?: Resource[] }
    let aux: AuxVectors | null = null
    const f = m.files['search/aux.bin']
    if (f) {
      if (this.deepAux?.v === f.v) aux = this.deepAux.data
      else {
        aux = await this.once('search/aux.bin', async () => {
          const hit = await files.get('search/aux.bin')
          let data: ArrayBuffer
          if (hit && hit.v === f.v && hit.data instanceof ArrayBuffer) data = hit.data
          else {
            const b = await this.fetchFile('search/aux.bin')
            data = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer
            await files.set('search/aux.bin', { v: f.v, data })
          }
          const a = readAux(new Uint8Array(data))
          this.deepAux = { v: f.v, data: a }
          return a
        })
      }
    }
    return { topics: d.topics ?? [], resources: d.resources ?? [], aux }
  }

  // the notes as whole files (the librarian reads its own frontmatter): the mirror's, with the phone's on top
  private async noteTexts(signal?: AbortSignal, deadline?: number): Promise<[string, string][]> {
    return (await this.noteFiles(signal, deadline)).map(n => {
      const meta = Object.entries(n.meta)
      return [n.file, meta.length ? `---\n${meta.map(([k, v]) => `${k}: ${v}`).join('\n')}\n---\n\n${n.body}` : n.body]
    })
  }

  // an item's report for read_items; with no signal, the Key information the search text carries
  private async report(lib: PhoneLibrary, id: number): Promise<string> {
    try {
      if (!this.texts.has(id)) await this.item(id)
      return this.texts.get(id)?.report ?? ''
    } catch (e) {
      if ((e as Error).name === 'AbortError') throw e
      const k = lib.items.get(id)?.key
      return k ? `### Key information\n${k}` : ''
    }
  }

  private async deep(q: string, history: Turn[], provider: Provider, key: string, model: string, label: string,
    onEvent: (e: AskEvent, display?: string) => void, signal: AbortSignal, language: Lang, mode: 'quick' | 'deep' = 'deep',
    startingTurn?: ReturnType<typeof Q.buildTurn>, researchDeadline?: number, words?: ToolWords): Promise<{ text: string; ids: number[]; notes: string[] }> {
    const P = DEEP, st = this.settings(), keys = this.keys()
    const budget = { ...P.agent_budgets[mode] }
    const positive = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n) && n > 0
    if (positive(st?.agent_max_rounds)) budget.max_rounds = Math.min(budget.max_rounds, st.agent_max_rounds)
    if (positive(st?.agent_max_tokens)) budget.max_tokens = Math.min(budget.max_tokens, Math.max(8000, st.agent_max_tokens))
    if (positive(st?.cloud_min_tokens) && st.cloud_min_tokens > budget.max_tokens) throw new AiError('Incompatible agent token limits.')
    const deadline = researchDeadline ?? performance.now() + budget.research_seconds * 1000
    const check = () => signal.throwIfAborted()
    check()
    const [lib, d, v] = await Promise.all([this.library(signal, deadline), this.deepFiles(), this.vectors().catch(e => { if ((e as Error).name === 'AbortError') throw e; return null })])
    lib.setResources(d.resources)
    if (!this.manifest?.files['search/deep.json.gz']) onEvent({ ev: 'progress', line: 'Topic/resource indexes unavailable; item and note keyword search is available.' }, words?.('wiskit.progress.topicIndexMissing'))
    const progress = (line: string, display?: string) => onEvent({ ev: 'progress', line }, display)
    // embeddings need the OpenAI key (Anthropic has none): without it Deep searches by keywords only
    const embedKey = keys.openai || ''
    const eModel = v?.model || st?.embedding_model || d.aux?.model || ''
    const quantize = (x: number[]) => { let m = 0; for (const n of x) m = Math.max(m, Math.abs(n)); m = m || 1; return Int8Array.from(x, n => Math.max(-127, Math.min(127, Math.round(n / m * 127)))) }
    const notes = await this.noteTexts(signal, deadline)
    const live = [...topicTexts(d.topics), ...noteSections(notes, P.limits.section_max)]
    const cache = new Map<string, Int8Array>(Object.entries((await kv.get<{ model: string; v: Record<string, Int8Array> }>('deep-aux').then(c => (c?.model === eModel ? c.v : null))) ?? {}))
    const aux = await auxRows(live, eModel, d.aux, cache,
      embedKey && mode === 'deep' ? async texts => {
        check()
        if (performance.now() >= deadline) return []
        return (await embed(this.endpoints(), embedKey, eModel, texts, signal)).map(quantize)
      } : null, P.limits.aux_batch, progress, () => { check(); return performance.now() < deadline }, words)
    if (aux.fresh.size) {
      const keep = new Set(aux.hashes), out: Record<string, Int8Array> = {}
      for (const [h, x] of [...cache, ...aux.fresh]) if (keep.has(h)) out[h] = x as Int8Array
      await kv.set('deep-aux', { model: eModel, v: out })
    }
    if (!embedKey) progress('No OpenAI key on this phone: Deep searches by keywords only.', words?.('wiskit.progress.keyword'))
    const profile = profileOf(notes.find(([f]) => f === PROFILE_FILE)?.[1], P.limits.profile_max)
    if (!profile) progress(DEEP_TIP, words?.('wiskit.progress.tip'))
    if (!startingTurn) onEvent({ ev: 'context', line: `Deep mode · ${label} is researching your library...`, ids: [], list: false }, words?.('wiskit.progress.deep', { model: label }))
    const qvec = async (text: string) => { check(); if (performance.now() >= deadline) return null; return (await embed(this.endpoints(), embedKey, eModel, [text], signal))[0] }
    const L = new Librarian(P, lib, embedKey && v?.model === eModel ? v : null, aux.rows, embedKey ? qvec : async () => null, id => this.report(lib, id))
    L.budget = budget; L.signal = signal; L.deadline = deadline
    if (startingTurn) {
      L.chars = startingTurn.contextChars
      for (const file of startingTurn.notes) L.noteSources.add(file)
      for (const row of startingTurn.sources) { L.read.push(row.id); L.admitted.add(row.id); L.delivered.add(row.id); L.consulted.push(row.id) }
    }
    const canvasRows = await this.canvases().catch(() => [])
    const system = appendLanguage(systemPrompt(P, profile, lib.countByCategory(), lib.countItems()) + '\n\n'
      + (P.category_instructions + '\n- On this phone, any one proposal stops at 100 items.')
        .replace('on this desktop', 'on this phone').replace('{categories}', JSON.stringify(this.cats().map(c => c.name)))
      + `\n\n${mode} mode: research only as needed, within ${budget.max_items} distinct items, ${budget.read_max_ids} IDs per read and ${budget.max_rounds} rounds including the final answer. State partial coverage honestly.`
      + '\n\n' + P.phone_canvas_instructions.replace('{canvases}', JSON.stringify(canvasRows.map(c => ({ id: c.id, name: c.name, elements: c.count })))), language, 'reply')
    const content = startingTurn ? '' : await deepTurn(L, q)
    const hist = history.slice(-(Q.L.history_turns * 2))
    const text = strip(await askAgent(this.endpoints(), provider, key, model, system,
      startingTurn?.messages ?? [...hist, { role: 'user', content }], [...P.tools, ...P.category_tools, ...P.canvas_tools],
      async (n, a) => {
        check()
        if (n === 'propose_categories' || n === 'propose_category')
          return L.admitResult(n, await this.proposeCategories(n, a, new Set(L.read), onEvent, signal))
        if (n === 'propose_canvas') {
          try {
            const p = normalizeCanvas(a)
            if (p.canvas_id && !L.canvases.has(p.canvas_id)) return 'Error: read the target canvas in this turn first.'
            if (p.elements.some(e => e.kind === 'existing' && !L.canvases.get(p.canvas_id!)?.has(e.id!))) return 'Error: existing element was not exposed by read_canvas.'
            return L.admitResult(n, await this.proposeCanvas(a, new Set(L.read), onEvent, signal))
          } catch (e) { if ((e as Error).name === 'AbortError') throw e; return `Error: ${(e as Error).message}` }
        }
        try {
          const keys = n === 'list_canvases' ? [] : n === 'read_canvas' ? ['canvas_id'] : n === 'list_frames' ? ['item_id'] : null
          if (keys && Object.keys(a).some(k => !keys.includes(k))) return 'Error: unexpected canvas read arguments.'
          if (n === 'list_canvases') return L.admitResult(n, JSON.stringify((await this.canvases()).map(r => ({ id: r.id, name: r.name, elements: r.count, modified: r.updated }))))
          if (n === 'read_canvas') return L.admitResult(n, JSON.stringify(canvasView(await this.canvas(String(a.canvas_id || '')) as CanvasDocument)))
          if (n === 'list_frames') return L.admitResult(n, Number.isSafeInteger(a.item_id) && this.byId.has(a.item_id as number)
            ? JSON.stringify({ item_id: a.item_id, count: 0, frames: [], truncated: false, unavailable: 'Extracted frames are not in this phone library. Use thumbnails or text.' })
            : 'Error: no item with that ID on this phone.')
          return L.runTool(n, a)
        } catch (e) { if ((e as Error).name === 'AbortError') throw e; return `Error: ${(e as Error).message}` }
      },
      (n, a) => { check(); progress(describeCall(n, a), words ? describeCall(n, a, words) : undefined) }, budget.max_rounds, budget.max_tokens, signal,
      { onText: text => onEvent({ ev: 'chunk', text }), onReset: () => onEvent({ ev: 'reset' }),
        maxToolCalls: budget.max_tool_calls, researchDeadline: deadline, requestTimeoutMs: P.agent_budgets.request_seconds * 1000 }))
    // ask_core.deep_sources: the cited items, else the first 20 the agent consulted
    const cited = citedIds(text)
    return { text, notes: citedNotes(text).filter(f => L.noteSources.has(f) && notes.some(([file]) => file === f)), ids: lib.getItemsByIds(cited.length ? cited.filter(id => L.delivered.has(id)) : [...L.delivered].slice(0, 20)).map(r => r.id) }
  }
  async stopAsk() { /* the Stop button aborts the request (its signal) */ }

  // Save as note: the PC writes it (ask_core.save_note); the phone shows it at once
  async saveAnswer(md: string, ids: number[]): Promise<{ file: string }> {
    const [t] = answerTitle(md)
    const file = await this.newNoteFile(t || 'ask')
    await this.changes.add({ op: 'answer', md, ids, file })
    this.flushSoon()
    return { file }
  }

  // Synthesize: knowledge/synth.py on the phone, up to S.max sources (3 AI calls). A paired phone queues more for
  // the PC (server/intake.py `synth_queue`); a phone with no PC refuses them (the page disables the run key and says
  // to untick). Sources (projects/phone-solo-synthesize): the PC's items from the search text, links saved on this
  // phone from the journal (synthItems). A source with no part is left out and counted in the last line.
  readonly synthMax = S.max
  async synthTextless(ids: number[]): Promise<number[]> {
    const items = await this.synthItems(ids)
    const usable = new Set(items.filter(item => S.hasText(item)).map(item => item.id))
    return ids.filter(id => !usable.has(id))
  }
  async synthesize(topic: string, ids: number[], onLine: (line: string) => void, signal: AbortSignal, words?: ToolWords) {
    const language = lang()
    topic = topic.trim()
    if (!topic) throw new Error(say(words, 'notes.synthesize.topicFirst', {}, 'Give the note a topic first.'))
    if (ids.length > S.max) {
      if (this.solo) throw new Error(say(words, 'notes.synthesize.limit', { max: S.max, n: ids.length - S.max }, `Over the phone limit (${S.max}): untick ${ids.length - S.max} source${ids.length - S.max === 1 ? '' : 's'}`) + '.')
      await this.changes.add({ op: 'synth_queue', topic, ids })
      this.flushSoon()
      onLine(say(words, 'notes.synthesize.queued', { n: ids.length, max: S.max }, `${ids.length} sources is more than the phone folds (${S.max}): the PC writes this note when it runs.`))
      return { file: '', queued: true }
    }
    const pick = this.synthChoice()
    const key = pick && this.keys()[pick[0]]
    if (!pick || !key) throw new AiError(this.noKey(words))
    const items = await this.synthItems(ids)
    const batches = S.batches(items)
    if (!batches.length) throw new Error(say(words, 'notes.synthesize.noSourceText', {}, NO_SOURCE_TEXT))
    const left = items.length - batches.flat().length
    let note = ''
    const max = pick[0] === 'openai' ? this.cap(S.P.limits.max_tokens) : S.P.limits.max_tokens
    for (const [i, b] of batches.entries()) {
      onLine(say(words, 'notes.synthesize.folding', { n: b.length, at: i + 1, total: batches.length }, `Folding ${b.length} source(s) into the note (${i + 1} of ${batches.length})…`))
      note = clean(await complete(this.endpoints(), pick[0], key, pick[1], appendLanguage(S.batchPrompt(topic, note, b), language, strip(note) ? 'keep' : 'write'), max, signal)) || note
    }
    if (!strip(note)) throw new AiError(say(words, 'notes.synthesize.emptyAi', {}, 'The AI sent back an empty note.'))
    const file = await this.newNoteFile(topic)
    const sources = batches.flat().map(r => r.id)
    // a link saved on this phone is cited to the PC by its uid (server/intake.py _source_ids): its phone id means nothing there
    const uids = sources.map(id => (id < 0 && this.byId.get(id)?.uid) || '')
    await this.changes.add({ op: 'synth', topic, sources, uids, body: note, file })
    this.flushSoon()
    onLine((left ? say(words, 'notes.synthesize.leftOut', { n: left }, `${left} source${left === 1 ? ' was' : 's were'} left out (no text yet). `) : '')
      + (this.solo ? say(words, 'notes.synthesize.writtenSolo', {}, 'Written. It is in Notes.') : say(words, 'notes.synthesize.writtenPhone', {}, 'Written. It reaches the PC\'s Knowledge tab once the PC runs.')))
    return { file, queued: false }
  }

  // the items Synthesize folds, in the order asked: a PC item from the phone's search text (quick.ts Item; the
  // report's Key information stands in for the report, the search text carries no note), a link saved on this phone
  // from its journal entries (item(): title, caption, AI description, note, tags, category). The library is read only
  // when a PC item is asked, so a phone with no PC copy never needs it.
  private async synthItems(ids: number[]): Promise<Item[]> {
    const out = new Map<number, Item>()
    const pc = ids.filter(id => id > 0)
    if (pc.length) for (const it of (await this.library()).getItemsByIds(pc)) out.set(it.id, { ...it, report: it.key || '' })
    for (const id of ids) {
      if (id > 0) continue
      const f = await this.item(id).catch(() => null)
      if (f) out.set(id, { id, url: f.url, description: f.description, short_desc: f.short_desc, creator: f.creator, category: f.category,
        ai_desc: f.ai_desc, tags: f.tags, notes: f.notes, created: f.created, type: f.type })
    }
    return ids.map(id => out.get(id)).filter((s): s is Item => !!s)
  }

  // no live stream from Drive: look at the manifest when the app comes back to the front and every
  // few minutes while it is open; changed rows are handed to the page
  watch(onItems: (ids: number[]) => void, onNotes: () => void) {
    // a pull to refresh counts as a look: no second read of Drive right after it
    const look = async () => {
      if (document.hidden || !navigator.onLine || syncPaused() || reconnecting() || cloudStopped() || Date.now() - this.looked < 60_000) return
      this.looked = Date.now()
      const before = this.manifest?.published, old = new Map(this.rowsNow.map(r => [r.id, JSON.stringify(r)]))
      try {
        if (this.solo) {                           // another phone on the same recovery code
          if (!token(this.pair) || !(await this.readBack())) return
          this.setRows()
        } else {
          await this.rows()
          if (this.manifest?.published === before) return
        }
        const ids = this.rowsNow.filter(r => old.get(r.id) !== JSON.stringify(r)).map(r => r.id)
        for (const id of old.keys()) if (!this.byId.has(id)) ids.push(id)
        onItems(ids)
        onNotes()
      } catch { /* the lamp shows the last refresh */ }
    }
    const t = window.setInterval(look, 180_000)
    document.addEventListener('visibilitychange', look)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', look) }
  }
}

const toB64 = (a: Uint8Array) => { let s = ''; for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000)); return btoa(s) }

// a post's picture as its own page names it (og:image), for a post read from a site whose picture link
// failed or expired (sites.ts picturePlan)
async function pagePicture(url: string): Promise<string> {
  const info = await linkInfo(url, linkGet)
  if (!info?.image) throw new Error('no picture')
  const pic = new URL(info.image, url).href
  if (!postPicOk(url, pic)) throw new Error('no safe picture')
  return pic
}

// a link's picture as a small JPEG (base64, at most LINK_THUMB_PX wide), so it rides in a change file
async function shrinkJpeg(bytes: Uint8Array): Promise<string> {
  const bmp = await createImageBitmap(new Blob([bytes.slice()]))
  const w = Math.min(LINK_THUMB_PX, bmp.width), h = Math.max(1, Math.round(bmp.height * w / bmp.width))
  const cv = new OffscreenCanvas(w, h)
  cv.getContext('2d')!.drawImage(bmp, 0, 0, w, h)
  bmp.close()
  const out = new Uint8Array(await (await cv.convertToBlob({ type: 'image/jpeg', quality: 0.8 })).arrayBuffer())
  let s = ''
  for (let i = 0; i < out.length; i += 0x8000) s += String.fromCharCode(...out.subarray(i, i + 0x8000))
  return btoa(s)
}
