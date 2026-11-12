// Run from the repo root: node tests/check_mobile_network.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from '../web/node_modules/typescript/lib/typescript.js'
import { t } from '../web/src/lib/i18n/index.ts'
import { fmtDate, fmtTime } from '../web/src/lib/i18n/format.ts'
import { phoneWords, nativeError } from '../web/src/mobile/settings-words.ts'

function load(path, deps, globals) {
  const exports = {}
  const js = ts.transpileModule(readFileSync(new URL('../' + path, import.meta.url), 'utf8').replaceAll('import.meta.env?.DEV === true', 'false'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  vm.runInNewContext(js, { exports, require: s => {
    assert.ok(s in deps, `unexpected import ${s}`)
    return deps[s]
  }, AbortController, AbortSignal, Event, setTimeout, clearTimeout, setInterval, clearInterval, URL, URLSearchParams, TextEncoder, Uint8Array, ...globals })
  return exports
}

const language = load('web/src/mobile/language-switch.ts', {}, {})
async function setup(isApp, saved, savePolicy = async () => {}) {
  const storage = new Map(saved === undefined ? [] : [['bp-wifi', saved]])
  const browser = new EventTarget(), document = new EventTarget(), connection = new EventTarget()
  connection.type = 'cellular'
  const navigator = { onLine: true, connection }
  let status = { connected: true, type: 'cellular' }, change, requests = 0, transport
  const policy = load('web/src/mobile/network.svelte.ts', { './native': {
    isApp, networkStatus: async () => status, onNetworkChange: async fn => { change = fn },
  }, './sync/native.svelte': { nativeSyncPolicy: savePolicy, nativeSync: {} }, './language-switch.ts': language }, { $state: x => x, navigator, document, window: browser,
    localStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v) } })
  const pairing = { k: 'synthetic', l: 'synthetic', solo: false }
  const { Drive } = load('web/src/mobile/mirror/drive.ts', {
    '../network.svelte': policy,
    './pairing': { pairing: () => pairing },
    './crypto': {}, './license': { LicenseRequired: class extends Error {} }, './recovery-envelope': {},
    './gate': { cloudRevision: () => 0, cloudCheckpoint: () => {}, cloudReadSignal: () => new AbortController().signal },
  }, {
    fetch: (...args) => { requests++; return transport(...args) },
  })
  // This fixture isolates network policy; signed-grant authorization has its own phone access suites.
  Drive.prototype.authorize = async () => Infinity
  await policy.initNetwork()
  return { policy, storage, browser, connection, navigator, drive: new Drive('https://www.googleapis.com', () => 'test-token', () => {}),
    get requests() { return requests }, transport(fn) { transport = fn },
    change(type, connected = true) {
      status = { connected, type }
      if (isApp) change(status)
      else { navigator.onLine = connected; connection.type = type; connection.dispatchEvent(new Event('change')) }
    },
  }
}

for (const isApp of [false, true]) {
  const s = await setup(isApp)
  let resumes = 0
  s.browser.addEventListener('brainamon-sync-resume', () => resumes++)
  assert.equal(s.policy.network.wifiOnly, true)
  await assert.rejects(s.drive.list(), /waiting for Wi-Fi/)
  await assert.rejects(s.drive.create('change', new Uint8Array([1])), /waiting for Wi-Fi/)
  assert.equal(s.requests, 0)
  s.change('unknown')
  await assert.rejects(s.drive.list(), /cannot confirm Wi-Fi/)
  s.policy.setWifiOnly(false)
  assert.equal(s.storage.get('bp-wifi'), 'off')
  assert.equal(resumes, 1)
  s.transport(async () => new Response(JSON.stringify({ files: [] })))
  await s.drive.list()
  s.change('none', false)
  await assert.rejects(s.drive.list(), /offline/)
  s.change('cellular')
  s.policy.setWifiOnly(true)
  assert.equal(s.storage.get('bp-wifi'), 'on')
  s.change('wifi')
  const signal = await s.policy.syncSignal()
  assert.equal(signal.aborted, false)

  // Wi-Fi loss while waiting for headers cancels the request without retries.
  let started
  const began = new Promise(resolve => { started = resolve })
  s.transport((url, init) => new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    started()
  }))
  const before = s.requests, pending = s.drive.list()
  await began
  s.change('cellular')
  await assert.rejects(pending, /waiting for Wi-Fi/)
  assert.equal(signal.aborted, true)
  assert.equal(s.requests, before + 1)
  s.change('wifi')
  assert.equal((await s.policy.syncSignal()).aborted, false)

  // Headers may already be back: body reads still carry the policy's abort signal.
  let bodyStarted
  const bodyBegan = new Promise(resolve => { bodyStarted = resolve })
  s.transport(async (url, init) => ({ ok: true, arrayBuffer: () => new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    bodyStarted()
  }) }))
  const download = s.drive.get('video')
  await bodyBegan
  s.change('cellular')
  await assert.rejects(download, { name: 'AbortError' })

  // A retry cannot upload after Wi-Fi is lost during backoff.
  s.change('wifi')
  s.transport(async () => { s.change('cellular'); return new Response('{}', { status: 503 }) })
  const retriesBefore = s.requests
  await assert.rejects(s.drive.create('change', new Uint8Array([2])), /waiting for Wi-Fi/)
  assert.equal(s.requests, retriesBefore + 1)
  s.change('ethernet')
  assert.equal(s.policy.syncPaused(), false)
}
const allowed = await setup(true, 'off')
assert.equal(allowed.policy.network.wifiOnly, false)
assert.equal(allowed.policy.syncPaused(), false)
await allowed.policy.setSyncPaused(true)
assert.equal(allowed.storage.get('bp-sync-paused'), 'on')
assert.equal(allowed.policy.syncPaused(), true)
await allowed.policy.setSyncPaused(false)
assert.equal(allowed.policy.syncPaused(), false)

// A pause is acknowledged only after native persistence; resume stays blocked until its commit too.
let commitPolicy, failPolicy
const durable = await setup(true, 'off', () => new Promise((resolve, reject) => { commitPolicy = resolve; failPolicy = reject }))
let durableResumes = 0
durable.browser.addEventListener('brainamon-sync-resume', () => durableResumes++)
let acknowledged = false
const pausing = durable.policy.setSyncPaused(true).then(ok => { acknowledged = ok })
await new Promise(resolve => setImmediate(resolve))
assert.equal(acknowledged, false)
assert.equal(durable.policy.network.pausePending, true)
assert.equal(durable.policy.syncPauseReason(t), t('settings.sync.savingPolicy'))
const switchWhileSaving = () => language.switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
assert.equal((await switchWhileSaving()).status, 'blocked')
commitPolicy(); await pausing
assert.equal(acknowledged, true)
assert.equal(durable.policy.network.pausePending, false)
const resuming = durable.policy.setSyncPaused(false)
assert.equal(durable.policy.syncPaused(), true)
assert.equal(durable.storage.get('bp-sync-paused'), 'on')
assert.equal(durableResumes, 0, 'resume triggers must wait for native persistence')
commitPolicy(); assert.equal(await resuming, true)
assert.equal(durableResumes, 1)
assert.equal(durable.policy.syncPaused(), false)
assert.equal(durable.storage.get('bp-sync-paused'), 'off')
const refused = durable.policy.setSyncPaused(true)
failPolicy(Error('synthetic policy save failure'))
assert.equal(await refused, false)
assert.equal(durable.policy.network.pauseFailed, true)
assert.equal(durable.policy.syncPaused(), true)
assert.equal(durable.policy.syncPauseReason(t), t('settings.sync.policyFailed'))
assert.equal((await switchWhileSaving()).status, 'blocked')
const retryPause = durable.policy.setSyncPaused(true)
commitPolicy(); assert.equal(await retryPause, true)
assert.equal(durable.policy.network.pauseFailed, false)
assert.equal((await switchWhileSaving()).status, 'reloaded')

// Manual/forced vault rounds and PC status reads share the gate; reconnect waits for a prior round to end.
const v = await setup(true)
let rounds = 0, pcReads = 0
Object.assign(v.browser, { setInterval, setTimeout })
let finishRemove
const vaultSource = { syncVault: async () => { rounds++; return { state: 'idle', summary: 'Done' } },
  vaultPc: async () => { pcReads++; return null }, vaultRemoveLegacy: () => new Promise(resolve => { finishRemove = resolve }) }
const vault = load('web/src/mobile/vault/auto.svelte.ts', {
  '../../lib/i18n/index.ts': { t }, '../../lib/i18n/format.ts': { fmtDate, fmtTime },
  '../settings-words': { phoneWords, nativeError },
  '../language-switch.ts': language,
  '../sync/native.svelte': { nativeSyncPolicy: async () => {}, nativeSyncSupported: async () => false, readNativeStatus: async () => {}, nativeSync: {} },
  '../obsidian': { setVaultName() {} },
  '../native': { isApp: true }, '../network.svelte': v.policy,
  '../store': { kv: { get: async () => undefined, set: async () => {} } },
  '../../lib/progress': { progress: () => ({ pct: 0, left: '' }) },
  '../state.svelte': { driveStatus: () => ({ ok: true }), phone: { tried: true }, solo: false,
    source: vaultSource },
}, { $state: x => x, window: v.browser, document: new EventTarget() })
vault.vault.opts = { on: true, uri: 'vault://test', name: 'Test' }
await vault.runVault(true)
await vault.readPc()
assert.equal(rounds, 0)
assert.equal(pcReads, 0)
const stop = vault.startVault()
vault.vault.busy = true
v.change('wifi')
await new Promise(resolve => setTimeout(resolve, 20))
assert.equal(rounds, 0)
vault.vault.busy = false
await new Promise(resolve => setTimeout(resolve, 300))
assert.equal(rounds, 1)
stop()
const remove = vault.removeOldPages()
const attempt = () => language.switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
assert.equal((await attempt()).status, 'blocked')
finishRemove(1)
await remove
assert.equal((await attempt()).status, 'reloaded')
let finishRound
vaultSource.syncVault = () => new Promise(resolve => { finishRound = resolve })
const round = vault.runVault(true)
assert.equal((await attempt()).status, 'blocked')
vault.vault.busy = false // the UI can stop waiting while the file is still being written
assert.equal((await attempt()).status, 'blocked')
finishRound({ state: 'idle', summary: 'Done' })
await round
assert.equal((await attempt()).status, 'reloaded')

// Offline saving and auto-keep can write outside their narrow video progress indicator.
let finishPersist, finishLoad
const state = x => x
state.raw = x => x
let offlineWrites = 0
const offlineItems = { putRequired: async () => {}, all: async () => [] }
const offlineKv = { get: async () => undefined, getRequired: async () => { throw Error('synthetic read failure') },
  setOfflineRequired: async () => { offlineWrites++ } }
const offline = load('web/src/mobile/offline.svelte.ts', {
  '../lib/i18n/index.ts': { t },
  './language-switch.ts': language,
  './store': { items: offlineItems, kv: offlineKv },
  './state.svelte': { mirrorSource: {}, phone: { byId: new Map(), rows: [] }, source: { item: async () => ({ files: {} }) } },
  './network.svelte': v.policy,
}, { $state: state, localStorage: { getItem: () => null }, navigator: { onLine: true,
  storage: { persist: () => new Promise(resolve => { finishPersist = resolve }), persisted: async () => false } },
  caches: { open: async () => ({}) } })
const itemSave = offline.saveItem(1, false)
assert.equal((await attempt()).status, 'blocked')
finishPersist(true)
await itemSave
assert.equal((await attempt()).status, 'reloaded')
offline.offline.load = () => new Promise(resolve => { finishLoad = resolve })
const keep = offline.autoKeep()
assert.equal((await attempt()).status, 'blocked')
finishLoad()
await keep
assert.equal((await attempt()).status, 'reloaded')
await assert.rejects(offline.removeCanvas('synthetic'), /synthetic read failure/)
assert.equal(offlineWrites, 0)
offlineItems.putRequired = async () => { throw Error('synthetic write failure') }
offline.offline.persisted = true
await assert.rejects(offline.saveItem(1, false), /synthetic write failure/)
assert.equal((await attempt()).status, 'reloaded')

// A link without durable storage stays in its capture draft when it cannot be sent.
let finishOutbox
const outboxDb = { add: () => new Promise(resolve => { finishOutbox = resolve }) }
const outbox = load('web/src/mobile/outbox.svelte.ts', {
  './language-switch.ts': language, './links': { cleanLink: x => x },
  './store': { outbox: outboxDb },
}, { $state: state, navigator: { onLine: false } })
const box = new outbox.Outbox({}, false)
const linkSave = box.save('https://example.test', '', '')
assert.equal((await attempt()).status, 'blocked')
finishOutbox(undefined)
await assert.rejects(linkSave, /Keep the draft and retry/)
assert.equal(box.entries.length, 0)
assert.equal((await attempt()).status, 'reloaded')
outboxDb.add = async () => 77
outboxDb.putRequired = async () => { throw Error('synthetic storage failure') }
const sentBox = new outbox.Outbox({ saveLink: async () => ({ id: 1, new: true }) }, true)
await sentBox.save('https://example.test/sent', '', '')
assert.equal((await attempt()).reason, 'settings.language.unsavedOutbox')
outboxDb.putRequired = async () => 77
assert.equal((await attempt()).status, 'reloaded')

outboxDb.add = async () => 78
outboxDb.putRequired = async () => { throw Error('synthetic storage failure') }
const removeBox = new outbox.Outbox({ saveLink: async () => ({ id: 2, new: true }) }, true)
await removeBox.save('https://example.test/remove', '', '')
let finishStatus
const order = []
outboxDb.putRequired = () => new Promise(resolve => { finishStatus = () => { order.push('write'); resolve(78) } })
outboxDb.delRequired = async () => { order.push('delete') }
const switchingOutbox = attempt()
while (!finishStatus) await Promise.resolve()
const removingOutbox = removeBox.remove(78)
finishStatus()
await removingOutbox
assert.equal((await switchingOutbox).status, 'reloaded')
assert.deepEqual(order, ['write', 'delete'])

const recovery = load('web/src/mobile/recovery.svelte.ts', {
  '../lib/i18n/index.ts': { t }, './settings-words': { nativeError },
  './language-switch.ts': language, '../lib/pick': {}, './mirror/recovery-envelope': {},
  './mirror/phone-recovery': {}, './state.svelte': { phone: {} },
}, { $state: state })
let finishRecovery
const recoveryRun = recovery.recoveryRun(() => new Promise(resolve => { finishRecovery = resolve }))
assert.equal((await attempt()).status, 'blocked')
finishRecovery()
await recoveryRun
assert.equal((await attempt()).status, 'reloaded')

let finishBackup
const backup = load('web/src/mobile/backup.svelte.ts', {
  '../lib/i18n/index.ts': { t }, './settings-words': { phoneWords, nativeError },
  './language-switch.ts': language, './mirror/pairing': { pairing: () => null },
  './mirror/phone-backup': { backupTask: () => null, beginBackupTask: async () => {},
    runBackupTask: () => new Promise(resolve => { finishBackup = resolve }), pauseBackupTask: async () => {} },
}, { $state: state, location: { pathname: '/', replace() {}, reload() {} } })
const backupRun = backup.runBackup({}, 'synthetic')
await Promise.resolve()
assert.equal((await attempt()).status, 'blocked')
finishBackup()
await backupRun
assert.equal((await attempt()).status, 'reloaded')

let finishJournal, finishChat
const journalDb = { all: async () => [], add: () => new Promise(resolve => { finishJournal = resolve }),
  forChat: () => new Promise(resolve => { finishChat = resolve }), saveChat: async () => 2 }
let journalDurable = true
const journal = load('web/src/mobile/mirror/changes.ts', {
  '../language-switch.ts': language,
  '../store': { changes: journalDb, journal: async () => journalDurable, kv: { get: async () => undefined } },
  '../ai/canvas.ts': {}, '../ai/describe.ts': {}, './resend': { resendPending: () => false }, './pairing': { requeueWaiting: () => false },
}, { crypto: { getRandomValues: x => x } })
const changes = new journal.Changes()
const addChange = changes.add({ op: 'link', url: 'https://example.test' })
while (!finishJournal) await Promise.resolve()
assert.equal((await attempt()).status, 'blocked')
finishJournal(1)
await addChange
assert.equal((await attempt()).status, 'reloaded')
const saveChat = changes.saveChat({ op: 'chat', slug: 'synthetic' })
while (!finishChat) await Promise.resolve()
assert.equal((await attempt()).status, 'blocked')
finishChat([])
await saveChat
assert.equal((await attempt()).status, 'reloaded')
const volatileChanges = new journal.Changes()
journalDb.add = async () => undefined
await volatileChanges.add({ op: 'note', file: 'synthetic.md', body: 'kept in memory' })
assert.equal((await attempt()).reason, 'settings.language.unsavedJournal')
journalDb.add = async () => 42
await volatileChanges.add({ op: 'note', file: 'synthetic.md', body: 'retry' })
assert.equal((await attempt()).status, 'reloaded')
journalDb.put = async () => undefined
await volatileChanges.add({ op: 'note', file: 'synthetic.md', body: 'failed update' })
assert.equal((await attempt()).reason, 'settings.language.unsavedJournal')
journalDb.put = async () => 42
await volatileChanges.add({ op: 'note', file: 'synthetic.md', body: 'saved update' })
assert.equal((await attempt()).status, 'reloaded')
journalDurable = false
await volatileChanges.commit(volatileChanges.list, () => {}, [], { delivery: { next: 2 } })
assert.equal((await attempt()).reason, 'settings.language.unsavedJournal')
journalDurable = true
await volatileChanges.commit(volatileChanges.list, () => {}, [], { delivery: { next: 2 } })
assert.equal((await attempt()).status, 'reloaded')
const deleted = []
journalDb.delConfirmed = async id => { deleted.push(id); return false }
await assert.rejects(volatileChanges.dropQueuedNote('synthetic.md'), /Retry the deletion/)
assert.equal((await attempt()).reason, 'settings.language.unsavedJournal')
journalDb.delConfirmed = async id => { deleted.push(id); return true }
await volatileChanges.dropQueuedNote('synthetic.md')
assert.equal((await attempt()).status, 'reloaded')
assert.deepEqual(deleted, [42, 42])

// Native handoff freezes a large backlog durably without marking uploads complete.
const backlog = new journal.Changes()
await backlog.load()
backlog.list = Array.from({ length: 1251 }, (_, i) => ({ id: i + 100, op: 'link', uid: String(i), url: 'https://example.test/' + i, at: i + 1, state: 'queued' }))
const staged = []
await backlog.prepareUploads(async doc => { staged.push(structuredClone(doc)) }, 'p0000000001', true, true)
assert.equal(staged.length, 6)
assert.equal(staged.reduce((n, d) => n + d.changes.length, 0), 1251)
assert.ok(backlog.list.every(e => e.state === 'sending'))
const repeat = []
await backlog.prepareUploads(async doc => { repeat.push(structuredClone(doc)) }, 'p0000000001', true, true)
assert.deepEqual(staged, repeat, 'restart/retry preserves frozen batch identities')
await backlog.flush(async doc => 'chg-' + String(doc.seq).padStart(32, '0'), 'p0000000001', true, true)
assert.ok(backlog.list.every(e => e.state === 'sent'))
const stream = staged[0].stream
await backlog.prune(0, { delivery: 2, published: 10, receipts: { [stream]: { seq: 0, want: 1 } } })
const requested = []
await backlog.prepareUploads(async doc => requested.push(doc), 'p0000000001', true, true)
assert.equal(requested.length, 1); assert.ok(requested[0].previous)
assert.equal(requested[0].seq, staged[0].seq)
journalDurable = false
const unsafe = new journal.Changes(); await unsafe.load()
unsafe.list = [{ id: 9, op: 'link', uid: 'unsafe', at: 1, state: 'queued' }]
let handedOff = false
await assert.rejects(() => unsafe.prepareUploads(async () => { handedOff = true }, 'p0000000001', true, true), /storage could not save/)
assert.equal(handedOff, false)

console.log('Mobile network policy passed: defaults, persistence, native/browser changes, retries, active requests/bodies and vault pause/resume.')
