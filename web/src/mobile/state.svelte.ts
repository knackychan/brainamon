// The phone's state: the light copy of the library (rows, categories, tints) loaded from IndexedDB
// first and refreshed from the source, the Library filters, the search, and the hash route.
// Filtering and sorting follow the desktop's rules (src/lib/library.svelte.ts); ranking stays on the
// source side (keyword = the server's FTS, Smart = POST /api/smart, or on the mirror the phone's own
// ranking with its OpenAI key, Phase 5) with a substring scan over the phone's copy when the source
// is out of reach.
import { setCardLookup } from '../lib/md'
import { idFirst, inSearch, wholeId } from '../lib/whole-id'
import { acceptHash } from './canvas/navigation'
import { DesktopSource } from './source/desktop'
import { MirrorSource, NeedsSignIn, NoMirror, PhoneTooOld, tooOld } from './source/mirror'
import type { Category, MobileSource, Row } from './source/types'
import { DriveError } from './mirror/drive'
import type { NoLibraryWhy } from './mirror/diagnose'
import { accountCheck, answered, driveLamp, type DriveLamp } from './mirror/status'
import { acceptLink, confirmAccount, disconnectDrive, newKeyText, pairing, signIn, startSolo, takeFromUrl, token, triedSilent, unconfirmedToken, whoSignedIn } from './mirror/pairing'
import { isApp, scanQr, secretsSaved } from './native'
import { changes as changesDb, drafts, items as storedItems, kv, outbox, trimItems, wipe } from './store'
import { network, SyncPaused, syncPaused, syncPauseReason } from './network.svelte'
import { lastAccess, LICENSE_REQUIRED, LicenseRequired } from './mirror/license'
import { allowCloudWork, CloudCancelled, cloudCheckpoint, cloudRevision, cloudStopped, reconnecting, RECONNECT_BUSY, stopCloudWork } from './mirror/gate'
import { backup } from './backup.svelte'
import { ACCESS_STATES, clock, phoneState, type PhoneFacts, type PhoneState, type PhoneWords } from './mirror/phone-state'
import { phoneWords, phoneLocale, nativeError } from './settings-words'
import { pairedFacts, soloFacts } from './mirror/phone-facts'
import { recoveryFact } from './mirror/recovery-fact'
import { beginLanguageWork } from './language-switch.ts'
import { t, type Key } from '../lib/i18n/index.ts'
import { nativeSync, nativeSyncText } from './sync/native.svelte'
import { fmtAgo as agoText, fmtNum, fmtSize } from '../lib/i18n/format.ts'

// A paired phone reads the Google Drive mirror (Phase 4); otherwise the desktop over USB
// (development). A pairing link or Google's sign-in answer in the URL is taken first, before the
// router reads location.hash.
export const pairNote = sessionStorage.getItem('bp-url-note') || popNote()
sessionStorage.removeItem('bp-url-note')
const paired = pairing()
export const source: MobileSource = paired ? new MirrorSource(paired, phoneWords) : new DesktopSource()
export const mirrorSource = source instanceof MirrorSource ? source : null
tooOld.fn = () => { phone.tooOld = true }      // also from the background look, which keeps quiet otherwise
// no PC (plans/08-phone-solo.md): the phone's own library, backed up in Google Drive
export const solo = !!mirrorSource?.solo
// Settings > Backup & phones (#/backup): a phone paired with a PC has it, and so does the phone without one (its own backup)
export const backupHere = !!mirrorSource
// Google Drive is an add-on: true while this phone holds a working Drive sign-in (read at call time)
export const driveLinked = () => !!mirrorSource && !!token(mirrorSource.pair)
// the page as server/dev_drive.py serves it (development only): solo runs on its stand-in Drive and AI.
// An isolated browser check on another port sets window.__bpDevSolo before the page loads.
export const devSolo = import.meta.env.DEV && !isApp && ['127.0.0.1', 'localhost'].includes(location.hostname)
  && (location.port === '18765' || (globalThis as { __bpDevSolo?: unknown }).__bpDevSolo === true)
// Recover a library… (#/recover): the phone without a PC, or one that can become one (the app, the development page); a
// phone paired with a PC recovers its library on the PC
export const recoverHere = solo || (!mirrorSource && (isApp || devSolo))

export type Tab = 'lib' | 'cv' | 'cap' | 'jv' | 'notes' | 'more'
export interface Route { tab: Tab; item?: number; canvas?: string | null; note?: string; mynote?: string; chats?: boolean; synth?: string; imp?: boolean; save?: boolean; backup?: boolean; manage?: boolean; group?: string; recover?: boolean; add?: boolean; find?: boolean; search?: boolean }
// the route names are catalog keys; the words are looked up when a screen shows them (never at import time)
const TAB_NAME: Record<Tab, Key> = { lib: 'shell.route.library', cv: 'shell.route.canvas', cap: 'shell.route.add', jv: 'shell.route.wiskit', notes: 'shell.route.notes', more: 'shell.route.more' }
export const tabName = (tab: Tab): string => t(TAB_NAME[tab])

export function parseRoute(hash: string): Route {
  const p = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent)
  switch (p[0]) {
    case 'item': return { tab: 'lib', item: +p[1] || undefined }
    case 'search': return { tab: 'lib', search: true }
    case 'canvas': return { tab: 'cv', canvas: p[1] || null, ...(p[1] && p[1] !== 'new' && p[2] === 'add' ? { add: true } : {}) }
    case 'cap': return p[1] === 'save' ? { tab: 'cap', save: true } : { tab: 'cap' }
    case 'jv': return { tab: 'jv', chats: p[1] === 'chats' }
    case 'notes': return { tab: 'notes', note: p[1] || undefined }
    case 'mynotes': return { tab: 'notes', mynote: p[1] || undefined }
    case 'synth': return { tab: 'notes', synth: p[1] ?? '' }
    case 'notes-search': return { tab: 'notes', find: true }
    case 'more': return ['sync', 'wiskit', 'obsidian', 'storage', 'look', 'about'].includes(p[1]) ? { tab: 'more', group: p[1] } : { tab: 'more' }
    case 'import': return { tab: 'cap', imp: true }
    case 'backup': return backupHere ? { tab: 'more', backup: true, ...(p[1] === 'manage' ? { manage: true } : {}) } : { tab: 'more' }
    case 'recover': return recoverHere ? { tab: 'more', recover: true } : { tab: 'more' }
    default: return { tab: 'lib' }
  }
}
function popNote(): string {
  try { const n = sessionStorage.getItem('bp-note') || ''; sessionStorage.removeItem('bp-note'); return n } catch { return '' }
}
export const go = (hash: string) => { location.hash = hash }
export const back = () => (history.length > 1 ? history.back() : go('#/lib'))

const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private window */ } },
}

export type Sort = 'new' | 'old' | 'az' | 'za'
// the card look: Auto (Cover, Full holo for favourites, as the desktop does), Cover for all, Holo for all
export type CardStyle = 'auto' | 'full' | 'fa2'
const CARD_STYLE_KEYS: [CardStyle, Key][] = [['auto', 'item.cardStyle.auto'], ['full', 'item.cardStyle.full'], ['fa2', 'item.cardStyle.fa2']]
export const cardStyles = (): [CardStyle, string][] => CARD_STYLE_KEYS.map(([id, key]) => [id, t(key)])
const asCardStyle = (v: string | null): CardStyle => v === 'full' || v === 'fa2' ? v : 'auto'
const SORT_KEYS: [Sort, Key][] = [['new', 'library.sort.new'], ['old', 'library.sort.old'], ['az', 'library.sort.az'], ['za', 'library.sort.za']]
export const sorts = (): [Sort, string][] => SORT_KEYS.map(([id, key]) => [id, t(key)])
const COLLATE = new Intl.Collator('en', { sensitivity: 'base', numeric: true })
const hasText = (r: Row, q: string) => [r.title, r.creator, r.tags, r.desc, r.cat].some(s => (s || '').toLowerCase().includes(q))

class Phone {
  rows: Row[] = $state.raw([])
  cats: Category[] = $state.raw([])
  tints: Record<string, string> = $state.raw({})
  loaded = $state(false)                    // something is on screen (from the copy or the source)
  load = $state.raw({ text: '', frac: 0 })  // until then: the Library's loading line and bar (refresh)
  read = $state.raw<{ text: string; frac: number } | null>(null)   // the refresh running now, any time: More's Sync box, the sync key's ring and its panel (lanes.ts)
  synced = $state(0)                        // when the copy was last refreshed from the source (ms)
  reachable = $state(false)                 // the last source call worked
  answered = $state(false)                  // the source replied to the last call (even with a refusal): Drive is not offline
  tried = $state(false)                     // a refresh has finished since the app started
  noLibrary = $state(false)                 // Drive has no manifest for this pairing (the PC has not finished its first upload)
  noLibraryWhy = $state.raw<NoLibraryWhy | null>(null)   // which cause the phone could tell, and what to offer (mirror/diagnose.ts)
  tooOld = $state(false)                    // the PC's copy needs a newer phone app (source/mirror.ts READER)
  online = $state(typeof navigator === 'undefined' ? true : navigator.onLine)
  refreshing = $state(false)
  error = $state('')
  signIn = $state(false)                    // the mirror needs Google Drive connected (again)
  connecting = $state(false)                // Connect / Change account is waiting for Google or the account check (the button shows it)
  connectStep = $state('')                  // ... and which of the two
  tokenAt = $state(0)                       // bumped when the Google token comes or goes: screens read token() again
  recoveryAt = $state(0)                    // bumped after every recovery action (recovery.svelte.ts): Setup's Recovery row and the status follow at once
  round = $state.raw<{ at: number; ok: boolean; error: string } | null>(null)   // without a PC: the last backup round (MirrorSource.round), null none yet
  account = $state.raw<{ got: string; check: 'mismatch' } | null>(null)   // signed in to another account than the PC's: More offers Change account
  note = $state(pairNote)                   // a line for the More screen (paired, sign-in refused)
  sync = $state.raw<SyncRun | null>(null)   // the sync steps (syncNow) the sync key and its panel show, until it closes
  route = $state.raw<Route>(parseRoute(location.hash))
  canvasRevision = $state(0)
  pend = $state.raw({ unsent: 0, waiting: 0, held: 0, resending: 0 })   // the change journal now (measurePend): the status and This phone
  now = $state(Date.now())                  // every 30 s (boot): an expired Google token and "checked 2 min ago" are read again
  scroll: Record<string, number> = {}       // the Library's scroll position per tab, restored on return
  lastItem: number | null = null           // consumed by Grid on return from the item screen/strip

  // filters
  q = $state('')
  searchIds: Set<number> | null = $state.raw(null)
  rank: Map<number, number> | null = $state.raw(null)
  smart = $state(ls.get('bp-smart') === 'on')
  ranking = $state(false)
  smartNote = $state('')                    // why Smart search did not rank (no key, no index, no signal)
  cat = $state('all')
  fav = $state(false)
  src = $state('all')
  sort = $state<Sort>('new')
  motionOff = $state(ls.get('bp-motion') === 'off')
  cardStyle = $state<CardStyle>(asCardStyle(ls.get('bp-cards')))
  gallery = $state('3')                     // Library layout, retained when returning from an item
  capMB = $state(+(ls.get('bp-cap') || 150))

  byId = $derived(new Map(this.rows.map(r => [r.id, r])))
  rankOf = $derived.by(() => {
    const m = new Map<number, number>()
    ;[...this.rows].sort((a, b) => b.created - a.created || b.id - a.id).forEach((r, i) => m.set(r.id, i + 1))
    return m
  })
  favIds = $derived(new Set(this.rows.filter(r => r.fav).map(r => r.id)))
  filtered = $derived.by(() => {
    const { cat, fav, src } = this
    return this.rows.filter(r => (cat === 'all' || r.cat === cat) && (!fav || r.fav) && (src === 'all' || r.src === src))
  })
  visible = $derived.by(() => {
    const q = this.q.trim().toLowerCase(), ids = this.searchIds, rank = this.rank
    let L = this.filtered
    if (q) L = ids || rank ? L.filter(r => inSearch(r.id, q, ids, rank)) : L.filter(r => r.id === wholeId(q) || hasText(r, q))
    L = L.slice()
    if (rank && q) {
      const at = (r: Row) => rank.get(r.id) ?? 1e9
      L.sort((a, b) => at(a) - at(b) || b.id - a.id)
    } else {
      const by: Record<Sort, (a: Row, b: Row) => number> = {
        new: (a, b) => b.created - a.created || b.id - a.id,
        old: (a, b) => a.created - b.created || a.id - b.id,
        az: (a, b) => COLLATE.compare(a.title, b.title) || b.id - a.id,
        za: (a, b) => COLLATE.compare(b.title, a.title) || b.id - a.id,
      }
      L.sort(by[this.sort])
    }
    return idFirst(L, q)                       // a whole number: that item first, Smart or not
  })
}

export const phone = new Phone()

setCardLookup(n => {
  const r = phone.byId.get(n)
  return r && { title: r.title, cat: r.cat, tint: phone.tints[String(n)] }
})

function applyCats(cats: Category[]) {
  for (const c of cats) if (c.color) TYPE[c.name] = c.color      // the card engine reads TYPE[cat]
  phone.cats = cats
}

// ── boot: the copy first, then the source ────────────────────────────────────
async function renewSignIn(): Promise<boolean> {
  if (paired?.g && !token(paired) && navigator.onLine && !syncPaused() && (paired.c || isApp) && !triedSilent()) {
    if (!phone.loaded) phone.load = { text: 'Signing in to Google', frac: 0.02 }
    try { return await signIn(paired, true) } catch { /* More offers Connect */ }
  }
  return true
}

export async function boot() {
  window.addEventListener('brainamon-canvas-change', () => { phone.canvasRevision++ })
  window.addEventListener('hashchange', () => {
    if (location.hash.startsWith('#pair=')) { location.reload(); return }
    if (acceptHash(location.hash)) phone.route = parseRoute(location.hash)
  })
  window.addEventListener('offline', () => { phone.online = false })
  let resumeTimer = 0
  const resume = () => {
    if (!mirrorSource || syncPaused() || resumeTimer) return
    resumeTimer = window.setTimeout(() => {
      resumeTimer = 0
      if (syncPaused()) return
      if (phone.refreshing || (phone.sync && !phone.sync.end)) { resume(); return }
      phone.sync = null
      void syncNow()
    }, 250)
  }
  window.addEventListener('online', () => { phone.online = true; if (mirrorSource) resume(); else void refresh() })
  window.addEventListener('brainamon-sync-resume', resume)
  // the phone's setting decides; the engine keeps its own copy (cm-card-motion), so set both ways
  if (phone.motionOff !== MOTION.off) setMotion(!phone.motionOff)
  document.documentElement.classList.toggle('motion-off', phone.motionOff)
  const [rows, cats, tints, synced] = await Promise.all([kv.get<Row[]>('rows'), kv.get<Category[]>('cats'), kv.get<Record<string, string>>('tints'), kv.get<number>('synced')])
  if (rows?.length) {
    applyCats(cats ?? [])
    phone.rows = rows
    phone.tints = tints ?? {}
    phone.synced = synced ?? 0
    phone.loaded = true
  }
  if (mirrorSource) {
    try {
      const local = await mirrorSource.localCopy()
      if (local) { phone.rows = local.rows; applyCats(local.cats); phone.loaded = true }
    } catch { /* the existing IndexedDB copy remains available */ }
  }
  // the journal counts follow every change to it, whichever screen or background work makes it, and the clock ticks
  if (mirrorSource) {
    mirrorSource.changes.watch(() => { void measurePend() })
    void measurePend()
    window.setInterval(() => { phone.now = Date.now() }, 30_000)
  }
  // the app with no pairing yet starts on its own library (plans/08-phone-solo.md, Phase 8b): nothing
  // is wiped, and More still offers the QR scan for a PC and Google Drive for the backup
  if (isApp && !paired) {
    try {
      await startSolo(newKeyText())
      await secretsSaved()
      location.reload()
    } catch (e) { phone.error = (e as Error).message }
    return
  }
  // a paired phone whose Google token ran out renews it with one silent round trip per app start
  // (the browser leaves for Google and comes back; the app asks Google's Android sign-in in place),
  // for the account confirmed on this phone only: after a reset there is none, so nothing is reused
  if (!(await renewSignIn())) return
  // back from Google's page (browser), or a token from before `g` existed: read its account
  if (paired && unconfirmedToken(paired) && navigator.onLine && !syncPaused()) await checkAccount().catch(e => { phone.note = t('shell.sync.accountFailed', { detail: nativeError('google', e) }) })
  await refresh()
  // the Notes screen reloads when opened; Wiskit re-reads its chat list when `synced` moves
  source.watch(ids => patchRows(ids), () => { phone.synced = Date.now() }, () => { phone.canvasRevision++ })
}

// ── the Google account ───────────────────────────────────────────────────────
const tokenMoved = () => { phone.tokenAt = Date.now() }

// which account the held token is for. The account Google gives after its chooser is the one used
// (remembered as `g`); one that is not the PC's is not: More says so and offers Change account
// (phone.account). True when Drive may be used now.
async function checkAccount(): Promise<boolean> {
  if (!paired || paired.d) return true
  const got = await whoSignedIn(paired)
  const check = accountCheck(paired.e, paired.g, got)
  if (check === 'mismatch') { disconnectDrive(paired); await secretsSaved(); tokenMoved(); phone.account = { got, check }; return false }
  phone.account = null
  confirmAccount(paired, got); await secretsSaved(); tokenMoved()
  return true
}

// What Google Drive allows right now, for every box that depends on it (the Google Drive box and the
// Obsidian vault box read the same answer): its lamp, and when it is not usable, why in words.
export function driveStatus(): { lamp: DriveLamp; ok: boolean; why: string } {
  const m = mirrorSource
  void phone.tokenAt
  const signedIn = phone.signIn ? false : m ? !!token(m.pair) : false
  const lamp = driveLamp({ online: phone.online, refreshing: phone.refreshing, tried: phone.tried, signedIn, signIn: phone.signIn, answered: phone.answered, noLibrary: phone.noLibrary })
  if (m && !m.solo && signedIn && phone.online && !phone.refreshing && (!m.pair.l || network.licenseLocked)) {
    // a refused access check: the status model's sentence and lamp, as on the status card (mirror/phone-state.ts)
    const st = phoneStatus()
    if (st && ACCESS_STATES.includes(st.id)) return { lamp: phoneState(phoneFacts()!).lamp as DriveLamp, ok: false, why: st.text }
    return { lamp: 'access pending', ok: false, why: network.licenseProblem || LICENSE_REQUIRED }
  }
  let why = ''
  if (lamp === 'sign in') {
    why = phone.account?.check === 'mismatch' && m
      ? t('backup.account.mismatch', { account: phone.account.got, pcAccount: m.pair.e })
      : t('backup.drive.notConnected')
  } else if (lamp === 'offline') why = t('backup.drive.offline')
  else if (lamp === 'no library yet') why = phone.noLibraryWhy?.message || t('backup.drive.noLibrary')
  else if (lamp === 'not reachable') why = t('backup.drive.unreachable')
  return { lamp, ok: !why, why }
}

// the journal now, for the status card, Backup & phones and the owner line (Changes.watch calls it after every change)
export async function measurePend() {
  const m = mirrorSource
  if (!m) return
  try {
    await m.changes.load()
    phone.pend = { ...m.changes.counts(m.canvasSync), resending: m.resending }
  } catch { /* storage refused the read: the counts stay, and the next change measures again */ }
}

// What the status model (mirror/phone-state.ts) reads, for a phone paired with a PC or used without one; null for a
// phone with neither (the PC over USB). Read phoneStatus() in $derived: the facts follow phone, network, the token
// (phone.tokenAt), the recovery setup (phone.recoveryAt) and the clock (phone.now).
export function phoneFacts(words?: PhoneWords): PhoneFacts | null {
  const m = mirrorSource
  if (!m) return null
  void phone.tokenAt
  if (m.solo) {
    void phone.recoveryAt; void phone.now
    return soloFacts({
      pause: network.pausePending || network.pauseFailed ? syncPauseReason(words) : network.manualPause ? (words?.('backup.state.manualPause') ?? 'Sync paused by you.') : undefined,
      backupTask: backup.task || backup.busy ? {
        busy: backup.busy,
        text: backup.busy ? backup.task?.paused ? (words?.('backup.task.pausing') ?? 'Pausing backup task…') : backup.step : backup.task?.paused ? (words?.('backup.task.paused') ?? 'Backup task paused.') : (words?.('backup.task.waiting') ?? 'Backup task waiting to continue.'),
        detail: backup.error || (words?.('backup.task.localDetail') ?? 'Local content and queued edits stay here. Open the saved task to continue.'),
      } : undefined,
      app: isApp, online: network.online, paused: syncPaused(), refreshing: phone.refreshing, started: phone.tried,
      token: !!token(m.pair), account: m.pair.g || '', round: phone.round && { ok: phone.round.ok, ago: fmtAgo(phone.round.at) },
      recovery: recoveryFact(m.pair), unsent: phone.pend.unsent,
    })
  }
  return pairedFacts({
    pause: network.pausePending || network.pauseFailed ? syncPauseReason(words) : network.manualPause ? (words?.('backup.state.manualPause') ?? 'Sync paused by you.') : undefined,
    app: isApp, online: network.online, paused: syncPaused(), refreshing: phone.refreshing, tried: phone.tried,
    token: !!token(m.pair), refused: phone.signIn, account: m.pair.g || '', pcAccount: m.pair.e || '',
    mismatch: phone.account?.check === 'mismatch' ? phone.account.got : '', access: network.licenseKind,
    accessAt: network.licenseAt, last: lastAccess(m.pair.f)?.at ?? 0, noLibrary: phone.noLibrary ? phone.noLibraryWhy : null,
    reachable: phone.reachable, tooOld: phone.tooOld, checked: phone.synced ? fmtAgo(phone.synced) : '', pend: phone.pend,
    now: phone.now,
  }, words ? (ms, now) => clock(ms, now, phoneLocale()) : undefined)
}
export function phoneStatus(): PhoneState | null {
  const f = phoneFacts(phoneWords)
  return f && phoneState(f, phoneWords)
}

// Connect (Backup & phones, the card): Google's sheet (app) or page (browser), then the account check. Every outcome
// ends in a note, so the button never looks dead; both waits are bounded (native.ts googleToken 2 min,
// Drive.call 20 s for the account), and the button says which one it is in (phone.connectStep).
export async function connectDrive(choose = false) {
  if (phone.connecting) return
  if (backup.busy) { phone.note = t('backup.warning.pauseBeforeSignIn'); return }
  if (!paired) { phone.note = t('backup.warning.pairFirst'); return }
  const finishLanguageWork = beginLanguageWork()
  phone.connecting = true
  phone.connectStep = 'Waiting for Google'
  phone.note = ''
  try {
    await stopCloudWork()
    allowCloudWork()
    if (choose && !isApp) { disconnectDrive(paired); await secretsSaved(); phone.signIn = true; tokenMoved() }
    if (!(await signIn(paired, false, choose))) return      // the browser is on its way to Google
    tokenMoved()
    phone.connectStep = 'Checking the account'
    const ok = await checkAccount()
    // the library read that follows shows itself (the Now row and the lamp): the button is free again
    phone.connecting = false; phone.connectStep = ''
    // the refusal an earlier read met is answered: More drops Connect now, not when the read after it lands
    if (!ok) { phone.note = t('backup.account.choose', { account: paired.e }); sessionStorage.setItem('bp-note', phone.note); location.reload(); return }
    await secretsSaved()
    phone.signIn = false
    phone.note = t('backup.account.connected', { account: paired.g || t('settings.account.signedIn') })
  } catch (e) {
    phone.note = t('backup.error.connect', { detail: nativeError('google', e) })
    sessionStorage.setItem('bp-note', phone.note)
    location.reload()
    return
  } finally {
    phone.connecting = false; phone.connectStep = ''
    finishLanguageWork()
  }
  sessionStorage.setItem('bp-note', phone.note)
  location.reload()
}

// Change account (Backup & phones, the card): Google's account chooser. The app keeps the current sign-in until Google
// answers (the account it picks replaces `g`, or a cancel changes nothing); the browser leaves for
// Google, so the token and `g` go first and the page reads the new account when it comes back.
export async function changeAccount() {
  if (!paired) return
  phone.account = null
  await connectDrive(true)
}

// the app: scan the pairing QR (or take a pasted link) and start again on the mirror
export async function pairFrom(text?: string) {
  if (backup.task || backup.busy) { phone.note = t('backup.warning.finishBeforePair'); return }
  if (reconnecting()) { phone.note = RECONNECT_BUSY; return }
  const done = beginLanguageWork()
  try {
    const got = text ?? (await scanQr())
    if (!got) return
    let display = ''
    const note = await acceptLink(got, phoneWords, value => { display = value })
    phone.note = display || note || t('settings.pair.invalid')
    if (note.startsWith('Paired') && pairing()) {
      try { sessionStorage.setItem('bp-note', phone.note) } catch { /* the note is only a courtesy */ }
      await secretsSaved()
      location.replace(location.pathname + '#/backup'); location.reload()     // the guide there finishes the pairing
    }
  } catch (e) { phone.note = nativeError('scanner', e) } finally { done() }
}

// use the phone without a PC: a new library (no code), or the one a recovery code opens in Drive
export async function useWithoutPc(code = '', recoveryAccount = '') {
  if (backup.task || backup.busy) { phone.note = t('recovery.warning.finishBeforeRestore'); return false }
  if (reconnecting()) { phone.note = RECONNECT_BUSY; return false }
  if (code.trim() && (phone.refreshing || phone.connecting || (paired && token(paired) && !recoveryAccount))) {
    phone.note = t('recovery.warning.disconnectBeforeRestore')
    return false
  }
  const done = beginLanguageWork()
  try {
    if (code.trim() && ((paired && !paired.solo) || phone.rows.length || (await changesDb.forChat()).length || (await storedItems.all()).length || (await outbox.all()).length || (await drafts.all()).length)) {
      phone.note = t('recovery.warning.emptyPhone')
      return false
    }
    const dev = devSolo ? { d: 'http://127.0.0.1:18766', x: { anthropic: 'http://127.0.0.1:18766/ai/anthropic', openai: 'http://127.0.0.1:18766/ai/openai' }, ai: {} } : undefined
    await startSolo(code.trim() || newKeyText(), dev, recoveryAccount)
    await Promise.all([wipe(), changesDb.clear()])         // nothing left over from an earlier pairing
    const note = code.trim() ? (recoveryAccount ? t('recovery.state.keyAccepted') : t('recovery.state.codeAccepted')) : t('backup.state.soloStarted')
    try { sessionStorage.setItem('bp-note', note) } catch { /* the note is only a courtesy */ }
    await secretsSaved()
    location.replace(location.pathname + '#/backup'); location.reload()
    return true
  } catch (e) {
    phone.note = (e as Error).message
    return false
  } finally { done() }
}

// the AI keys a new pairing left in Drive (mirror.py pair_drop). They need only Drive, not the library,
// so they are taken during the PC's first upload too: they expire 30 minutes after the code was made
async function collectKeys() {
  if (!mirrorSource?.pair.t) return
  const note = await mirrorSource.takeKeys().catch(e => t('shell.sync.keysFailed', { detail: (e as Error).message }))
  if (note) phone.note = note
}

// how far a refresh is when the library parts start coming, and the share of the bar they fill
const PARTS_AT = 0.3, PARTS_SPAN = 0.65

// The transport's missing-grant error is also used after removal; the state model knows which it is.
function syncProblem(e: unknown): string {
  if (e instanceof LicenseRequired) {
    const st = phoneStatus()
    if (st && ACCESS_STATES.includes(st.id)) return [st.text, st.detail].filter(Boolean).join(' ')
  }
  return nativeError('network', e)
}

// '' when the copy is fresh, else why not (the sync panel shows it)
export async function refresh(step?: (key: SyncKey, note?: string) => void): Promise<string> {
  if (phone.refreshing) return ''
  if (reconnecting()) return RECONNECT_BUSY
  if (mirrorSource && syncPaused()) { phone.loaded = true; phone.tried = true; return syncPauseReason(phoneWords) }
  const finishLanguageWork = beginLanguageWork()
  phone.refreshing = true
  const revision = cloudRevision()
  phone.error = ''
  // where it is: the steps, then the library parts (the first load, with nothing on screen yet, shows it too)
  const where = source.kind === 'mirror' ? t('shell.sync.whereDrive') : t('shell.sync.wherePc')
  const at = (text: string, frac: number) => { phone.read = { text, frac }; if (!phone.loaded) phone.load = { text, frac } }
  at(t('shell.sync.connectingTo', { where }), 0.05)
  try {
    const { rows, cats } = await source.rows((key, note) => {
      at(key === 'read' ? t('shell.sync.reading', { where }) : t('shell.sync.fetching'), key === 'read' ? 0.15 : PARTS_AT)
      step?.(key, note)
    }, (done, total) => at(t('shell.sync.fetchingPart', { done, total }), PARTS_AT + PARTS_SPAN * done / Math.max(1, total)))
    await collectKeys()
    cloudCheckpoint(revision)
    applyCats(cats)
    phone.rows = rows
    phone.loaded = true
    phone.reachable = phone.answered = true
    phone.noLibrary = false
    phone.noLibraryWhy = null
    phone.signIn = false
    phone.tooOld = false
    phone.error = ''
    phone.synced = Date.now()
    await Promise.all([kv.set('rows', rows), kv.set('cats', cats), kv.set('synced', phone.synced)])
    const finishTrim = beginLanguageWork()
    void trimItems(phone.favIds).catch(() => {}).finally(finishTrim)
    const finishTints = beginLanguageWork()
    void source.tints().then(async t => { phone.tints = t; await kv.set('tints', t) }).catch(() => { /* the map colours are optional */ }).finally(finishTints)
    fillLinks(); runPictures()
    return ''
  } catch (e) {
    if (e instanceof CloudCancelled) return e.message
    if (e instanceof SyncPaused || (mirrorSource && syncPaused())) { phone.loaded = true; return syncPauseReason(phoneWords) }
    const msg = syncProblem(e)
    if (e instanceof PhoneTooOld) { phone.answered = phone.loaded = true; if (!phone.rows.length) phone.error = msg; return msg }
    phone.reachable = false
    phone.noLibrary = e instanceof NoMirror
    phone.noLibraryWhy = e instanceof NoMirror ? e.why : null
    phone.answered = phone.noLibrary || answered(e)
    phone.signIn = e instanceof NeedsSignIn
    if (e instanceof LicenseRequired) { phone.answered = true; phone.loaded = true; phone.error = msg; return msg }
    if (e instanceof NoMirror) await collectKeys()            // Drive answered: no library yet (the PC's first upload)
    if (e instanceof NoMirror || e instanceof NeedsSignIn) return (phone.error = msg)
    if (!phone.loaded) phone.error = source.kind === 'mirror'
      ? t('shell.sync.driveUnreachable', { detail: msg })
      : t('shell.sync.pcUnreachable', { detail: msg })
    return t('shell.sync.keepsCopyError', { problem: e instanceof DriveError ? msg : t('shell.sync.unreachableDetail', { where: t(source.kind === 'mirror' ? 'shell.sync.whereDrive' : 'shell.sync.wherePcCap'), detail: msg }) })
  } finally {
    phone.refreshing = false
    phone.read = null
    if (mirrorSource?.solo) phone.round = mirrorSource.round     // without a PC: what this round sent and read back (the status)
    phone.tried = true
    void measurePend()                      // a read can change the counts: the PC's receipts, canvas support, the resend
    finishLanguageWork()
  }
}

// ── pull to refresh ──────────────────────────────────────────────────────────
// The phone's own sync steps, shown by the sync panel (SyncPanel.svelte): send the queued changes as
// a change file, read the mirror's manifest, update the library parts that changed. The PC uploads
// the mirror on its own schedule (server/sync.py) and the phone cannot ask it to, so the last line
// says when it last did.
export type SyncKey = 'send' | 'read' | 'lib'
export interface SyncStep { key: SyncKey; label: string; state: 'wait' | 'run' | 'ok' | 'err'; note: string }
export interface SyncRun { steps: SyncStep[]; end: '' | 'done' | 'error'; msg: string }

let syncT = 0
const syncEdit = (f: (s: SyncRun) => SyncRun) => { if (phone.sync) phone.sync = f(phone.sync) }
// that step runs now, the one before it is done
function stepAt(key: SyncKey, note = '') {
  syncEdit(s => {
    const i = s.steps.findIndex(x => x.key === key)
    return { ...s, steps: s.steps.map((x, j) => (j === i ? { ...x, state: 'run', note: note || x.note } : j < i && x.state === 'run' ? { ...x, state: 'ok' } : x)) }
  })
}
export function closeSync() { clearTimeout(syncT); if (phone.sync?.end) phone.sync = null }
// how far a sync run is, 0..1: steps finished out of all; the running one counts half, or the library
// parts fetched so far while that step runs (the sync key's ring and More's Sync box)
export function syncFill(run: SyncRun): number {
  if (run.end) return 1
  const done = run.steps.filter(s => s.state === 'ok' || s.state === 'err').length
  const s = run.steps.find(x => x.state === 'run')
  const part = !s ? 0 : s.key === 'lib' && phone.read ? Math.min(1, Math.max(0, (phone.read.frac - PARTS_AT) / PARTS_SPAN)) : 0.5
  return (done + part) / Math.max(1, run.steps.length)
}

// what the read of Google Drive (or of the PC, over USB) is doing now, null when nothing runs: Sync now
// (its steps, with the changes sent first) or a refresh on its own (app start, Connect, back online)
export function driveWork(): { text: string; pct: number | null } | null {
  if (backup.busy) return { text: backup.task?.paused ? t('shell.sync.pausingTask') : backup.step, pct: null }
  if (nativeSync.supported && nativeSync.state === 'syncing') return nativeSync.phase === 'vault' ? null : { text: nativeSyncText(), pct: Math.min(99, Math.floor((nativeSync.progress ?? 0) * 100)) }
  const run = phone.sync && !phone.sync.end ? phone.sync : null
  if (!run && !phone.refreshing) return null
  const s = run?.steps.find(x => x.state === 'run')
  const text = phone.read?.text || (s ? `${s.label}${s.note ? ` · ${s.note}` : ''}` : t('shell.sync.starting'))
  return { text, pct: Math.round((run ? syncFill(run) : phone.read?.frac ?? 0) * 100) }
}

export async function syncNow() {
  if (phone.refreshing || (phone.sync && !phone.sync.end)) return
  if (reconnecting() || cloudStopped()) return
  if (mirrorSource && syncPaused()) return
  const finishLanguageWork = beginLanguageWork()
  try {
    clearTimeout(syncT)
    const m = mirrorSource
    const plan: [SyncKey, string][] = m ? [['send', t('shell.sync.sendStep')], ['read', t('shell.sync.readDriveStep')], ['lib', t('shell.sync.libraryStep')]] : [['read', t('shell.sync.readPcStep')], ['lib', t('shell.sync.libraryStep')]]
    phone.sync = { steps: plan.map(([key, label]) => ({ key, label, state: 'wait', note: '' })), end: '', msg: '' }
    let why = '', unsent = ''
    // no Drive or PC call when there is nothing to call or no signal
    if (isApp && !paired) why = t('shell.sync.setupFirst')
    else if (!navigator.onLine) why = t('shell.sync.offlineCopy')
    else {
      if (!(await renewSignIn())) return
      if (m) {
        stepAt('send')
        await m.changes.load()
        const queued = m.changes.counts(m.canvasSync).unsent
        try {
          const n = await m.flush()
          if (queued && !n && !token(m.pair)) unsent = t('shell.sync.connectQueue')
          stepAt('send', n ? (solo ? t('shell.sync.backedUpCount', { n }) : t('shell.sync.sentCount', { n })) : queued ? t('shell.sync.waitingSignIn') : t('shell.sync.nothingToSend'))
        } catch (e) {
          unsent = syncProblem(e)
          syncEdit(s => ({ ...s, steps: s.steps.map(x => (x.key === 'send' ? { ...x, state: 'err', note: t('shell.sync.keptForLater', { detail: unsent }) } : x)) }))
        }
      }
      why = cloudStopped() ? t('shell.sync.cloudStopped') : await refresh(stepAt)
    }
    const n = fmtNum(phone.rows.length, 'en')
    const done = t('shell.sync.upToDate', { items: n, where: m?.manifest?.published ? t('shell.sync.pcUploaded', { ago: fmtAgo(m.manifest.published) }) : solo ? t('shell.sync.onPhone') : '' })
    syncEdit(s => ({
      steps: s.steps.map(x => (x.state === 'run' ? { ...x, state: why ? 'err' : 'ok' } : x.state === 'wait' && !why ? { ...x, state: 'ok' } : x)),
      end: why || unsent ? 'error' : 'done',
      msg: phone.noLibraryWhy ? t('shell.sync.noLibraryHelp', { title: phone.noLibraryWhy.title }) : why || (unsent ? t('shell.sync.readNotSent', { detail: unsent }) : done),
    }))
    syncT = window.setTimeout(() => { phone.sync = null }, why || unsent ? 8000 : 2200)
  } finally { finishLanguageWork() }
}

// after an items_changed event or a write: replace those rows, add new ones, drop the gone
export async function patchRows(ids: number[]) {
  if (!ids.length) return
  try {
    const got = await source.rowsByIds(ids)
    const fresh = new Map(got.map(r => [r.id, r]))
    const gone = new Set(ids.filter(id => !fresh.has(id)))
    const known = new Set<number>()
    const rows = phone.rows.filter(r => !gone.has(r.id)).map(r => { known.add(r.id); return fresh.get(r.id) ?? r })
    const added = got.filter(r => !known.has(r.id))
    phone.rows = added.length ? [...added, ...rows] : rows
    kv.set('rows', phone.rows)
  } catch { /* the next refresh catches up */ }
}

// links saved on the phone: read their pages for a picture and caption (plans/09-link-details.md),
// then redraw them; the ids given, or every one not tried since the app started
export async function fillLinks(ids?: number[]) {
  const done = beginLanguageWork()
  try {
    const got = (await mirrorSource?.linkDetails(ids).catch(() => [] as number[])) ?? []
    if (got.length) await patchRows(got)
  } finally { done() }
}

// The slow picture queue's state for the sync panel (SyncPanel.svelte, lanes.ts) and its runner. One run at a time;
// when the site asks to slow down it waits PIC_WAIT_MS and goes on, as long as the app is open.
const PIC_WAIT_MS = 15 * 60_000
export const pics = $state({ state: 'idle' as 'idle' | 'run' | 'wait', done: 0, total: 0 })
let picRunning = false, picAgain = false

// called during a run (links imported meanwhile): one more run follows, for the links that one did not list
export async function runPictures() {
  if (!mirrorSource) return
  if (picRunning) { picAgain = true; return }
  picRunning = true
  try {
    for (;;) {
      pics.state = 'run'
      picAgain = false
      const done = beginLanguageWork()
      let r: Awaited<ReturnType<MirrorSource['fillPictures']>>
      try {
        r = await mirrorSource.fillPictures(p => { pics.done = p.done; pics.total = p.total }, () => !picRunning)
        if (r.got.length) await patchRows(r.got)
      } finally { done() }
      if (!r.blocked && !picAgain) break
      if (!r.blocked) continue
      pics.state = 'wait'
      await new Promise(res => setTimeout(res, PIC_WAIT_MS))
    }
  } finally {
    picRunning = false
    pics.state = 'idle'
  }
}

export function replaceRow(r: Row) {
  phone.rows = phone.rows.map(x => (x.id === r.id ? r : x))
  kv.set('rows', phone.rows)
}

// ── search ───────────────────────────────────────────────────────────────────
let qT = 0, qSeq = 0
export function openLibrarySearch(text: string) {
  clearTimeout(qT)
  phone.q = text
  phone.searchIds = null
  phone.rank = null
  phone.smartNote = ''
  void runSearch(text)
  location.hash = '#/search'
}
export function setQuery(text: string) {
  clearTimeout(qT)
  qT = window.setTimeout(() => {
    phone.q = text
    phone.rank = null
    runSearch(text)
  }, 150)
}

async function runSearch(text: string) {
  const seq = ++qSeq, q = text.trim()
  if (!q) { phone.searchIds = null; return }
  try {
    const ids = await source.search(q)
    if (seq === qSeq) phone.searchIds = new Set(ids)
    if (phone.smart) smartRank()
  } catch { if (seq === qSeq) phone.searchIds = null }        // out of reach: the substring scan in `visible`
}

export async function smartRank() {
  const q = phone.q.trim()
  if (!q) return
  phone.ranking = true
  try {
    const ids = await source.smart(q)
    if (q !== phone.q.trim()) return
    phone.rank = ids.length ? new Map(ids.map((id, i) => [id, i])) : null
    phone.smartNote = ''
  } catch (e) { phone.rank = null; phone.smartNote = (e as Error).message } finally { phone.ranking = false }
}

export function setSmart(on: boolean) {
  phone.smart = on
  ls.set('bp-smart', on ? 'on' : 'off')
  if (!on) { phone.rank = null; phone.smartNote = '' }
  else if (phone.q.trim()) smartRank()
}

// ── writes ───────────────────────────────────────────────────────────────────
export async function deleteItem(id: number, pc: boolean) {
  await source.deleteItem(id, pc)
  phone.rows = phone.rows.filter(x => x.id !== id)
  kv.set('rows', phone.rows)
}

export async function toggleFav(id: number) {
  const r = phone.byId.get(id)
  if (!r) return
  replaceRow({ ...r, fav: !r.fav })                           // optimistic: the holo flips at once
  try { replaceRow(await source.favourite(id, !r.fav)) } catch { replaceRow(r) }
}

// ── settings ─────────────────────────────────────────────────────────────────
export function setMotionOff(off: boolean) {
  phone.motionOff = off
  ls.set('bp-motion', off ? 'off' : 'on')
  setMotion(!off)
}
export function setCardStyle(s: CardStyle) {
  phone.cardStyle = s
  ls.set('bp-cards', s)
}
export function setCap(mb: number) {
  phone.capMB = mb
  ls.set('bp-cap', String(mb))
  navigator.serviceWorker?.controller?.postMessage({ type: 'cap', mb })
}
export function isDark() {
  const t = document.documentElement.dataset.theme
  return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
}
export function toggleTheme() {
  const d = !isDark()
  document.documentElement.dataset.theme = d ? 'dark' : 'light'
  ls.set('bp-theme', d ? 'dark' : 'light')
}
export function initTheme() {
  const t = ls.get('bp-theme')
  if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t
}

// both formats are pinned in English by tests.test_phone_i18n (lib/i18n/format.ts); other languages change words and units only
export const fmtAgo = (ms: number) => agoText(ms)
export const fmtMB = (b: number) => fmtSize(b)
