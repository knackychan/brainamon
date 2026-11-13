// Run after web/scripts/build-sync.mjs: node --experimental-strip-types tests/check_native_sync.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { webcrypto } from 'node:crypto'
import { MirrorKey } from '../web/src/mobile/mirror/crypto.ts'
import { transferId } from '../web/src/mobile/sync/transfer.ts'
import ts from '../web/node_modules/typescript/lib/typescript.js'

const key = await MirrorKey.fromText(Buffer.alloc(32, 7).toString('base64url'))
const text = s => new TextEncoder().encode(s)
const b64 = b => Buffer.from(b).toString('base64'), raw = s => new Uint8Array(Buffer.from(s, 'base64'))
const bundle = readFileSync('mobile-shell/android/app/src/main/assets/sync/worker.js', 'utf8')
const signer = await webcrypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify'])
const verifier = Buffer.from(await webcrypto.subtle.exportKey('spki', signer.publicKey)).toString('base64url')
async function fixture() {
  const files = new Map(), cache = new Map(), queue = [], counts = { creates: 0, delivered: 0, reads: 0 }
  const f = { files, cache, queue, counts, fetched: [], phases: [], progress: [], readSteps: [], fail: '', lost: false, paused: false, expires: 0 }
  f.add = async (logical, value) => {
    const name = await key.name(logical), data = await key.seal(logical, text(JSON.stringify(value)))
    files.set(name, { id: name, name, data }); return name
  }
  f.grant = async (enabled = true, expires = Math.floor(Date.now() / 1000) + 3500) => {
    const body = JSON.stringify({ v: 2, fp: key.fingerprint, enabled, issued: Math.floor(Date.now() / 1000) - 10, expires })
    const sig = Buffer.from(await webcrypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, signer.privateKey, text(body))).toString('base64url')
    await f.add('control/access-v2.json', { body, sig })
  }
  await f.grant()
  const part = await f.add('library/meta.json', { categories: [], items: 0 })
  f.manifest = { format: 1, files: { 'library/meta.json': { id: part, n: part, v: '1' } } }
  await f.add('manifest.json', f.manifest)
  f.enqueue = async () => {
    const name = 'chg-' + 'a'.repeat(32), data = await key.seal(name, text('{"changes":[]}'))
    queue.push({ id: 'batch', name, data: b64(data) })
  }
  return f
}
async function run(f, solo = false) {
  const ctx = vm.createContext({ console }) // exercise the worker's UTF-8 and binary polyfills
  vm.runInContext(bundle + ';BrainamonSync.install()', ctx)
  const w = ctx.BrainamonSync
  const unicode = '漢字 café 😀 lone:\ud800'
  assert.equal(vm.runInContext(`new TextDecoder().decode(new TextEncoder().encode(${JSON.stringify(unicode)}))`, ctx), unicode.replace('\ud800', '\ufffd'))
  w.start({ fp: key.fingerprint, verifier, solo, device: 'p0000000001', vault: false, force: false, legacy: false, watermark: f.cache.has('access-v2') })
  const handle = async (method, a) => {
    if (f.paused) throw Error('paused')
    if (method === f.fail) throw Error('retry')
    switch (method) {
      case 'name': return key.name(a[0])
      case 'open': return { data: b64(await key.open(a[0], raw(a[1]))) }
      case 'verify': {
        const spec = a[1]
        const k = await webcrypto.subtle.importKey(spec.format, raw(spec.data), spec.algorithm, false, ['verify'])
        return webcrypto.subtle.verify(a[0], k, raw(a[2]), raw(a[3]))
      }
      case 'authorized': f.expires = a[0]; return null
      case 'watermark': f.cache.set('access-v2', true); return null
      case 'load': return cacheGet(a[0])
      case 'save': f.cache.set(a[0], structuredClone(a[1])); return null
      case 'find': return [...f.files.values()].filter(x => x.name === a[0]).map(({ id, name }) => ({ id, name }))
      case 'list': return [...f.files.values()].map(({ id, name }) => ({ id, name }))
      case 'get': f.counts.reads++; f.fetched.push(a[0]); f.readSteps.push(structuredClone(f.progress.at(-1))); return { data: b64(f.files.get(a[0]).data) }
      case 'outbox': return f.queue.find(x => !x.remote) ?? null
      case 'create': {
        f.counts.creates++
        f.files.set(a[0], { id: a[0], name: a[0], data: raw(a[1]) })
        if (f.lost) { f.lost = false; throw Error('retry') }
        return a[0]
      }
      case 'delivered': f.queue.find(x => x.id === a[0]).remote = a[1]; f.counts.delivered++; return null
      case 'progress': f.phases.push(a[0]); f.progress.push(structuredClone(a)); return null
      default: throw Error('Unexpected operation ' + method)
    }
  }
  const cacheGet = name => f.cache.get(name) ?? null
  for (;;) {
    const message = JSON.parse(await w.next())
    if (message.finished) return message.finished
    for (const c of message.calls) {
      try { w.answer(c.id, await handle(c.method, c.args)) }
      catch (e) { w.answer(c.id, null, e.message) }
    }
  }
}

const ordered = await fixture()
const parts = ['library/part-000.json', 'library/part-002.json', 'library/part-001.json']
for (const logical of parts) {
  const id = await ordered.add(logical, [])
  ordered.manifest.files[logical] = { id, n: id, v: '1' }
}
await ordered.add('manifest.json', ordered.manifest)
assert.equal((await run(ordered)).ok, true)
assert.deepEqual(ordered.fetched.filter(id => parts.some(p => ordered.manifest.files[p].id === id)),
  await Promise.all(['library/part-002.json', 'library/part-001.json', 'library/part-000.json'].map(p => key.name(p))))
assert.equal(ordered.readSteps[0], undefined, 'access checks must not enable Drive-read preemption before pending uploads drain')
assert.equal(ordered.readSteps[1][2].key, 'shell.sync.readingIndex', 'the manifest read has a visible step before I/O')
assert.deepEqual(ordered.readSteps[2], ['drive', 0, { key: 'shell.sync.readingFiles', done: 0, total: 4 }])
assert.deepEqual(ordered.progress.at(-1), ['drive', 1, { key: 'shell.sync.readingFiles', done: 4, total: 4 }])

// A lost POST response must neither acknowledge early nor create a second encrypted envelope.
const lost = await fixture(); await lost.enqueue(); lost.lost = true
assert.equal((await run(lost)).ok, false)
assert.equal(lost.phases.at(-1), 'send', 'sending changes is distinct from access checks or reading the library')
assert.equal(lost.counts.delivered, 0)
assert.equal((await run(lost)).ok, true)
assert.equal(lost.counts.creates, 1); assert.equal(lost.counts.delivered, 1)
assert.deepEqual(lost.cache.get('manifest'), lost.manifest)
const reads = lost.counts.reads
await run(lost)
assert.equal(lost.counts.reads - reads, 2, 'unchanged sync reads only grant and manifest')
const solo = await fixture(); await solo.enqueue()
assert.equal((await run(solo, true)).ok, true)
assert.equal(solo.counts.delivered, 1)
assert.equal(solo.counts.reads, 0, 'a phone must not download the backup it just uploaded')
assert.deepEqual(solo.progress.at(-1), ['drive', 1, { key: 'shell.sync.readingFiles', done: 1, total: 1 }], 'cached solo backups also advance the count')
assert.equal(solo.cache.get('pc-mirror'), true, 'native solo sync retains the desktop-mirror warning')
solo.files.clear()
assert.equal((await run(solo, true)).ok, true)
assert.equal(solo.cache.get('pc-mirror'), false, 'a later snapshot clears a stale desktop-mirror warning')

// Keep the committed snapshot when a new part is interrupted.
const prior = structuredClone(lost.cache.get('manifest'))
const missing = await lost.add('library/part.json', [1, 2, 3])
lost.manifest.files['library/part.json'] = { id: missing, n: missing, v: '2' }
await lost.add('manifest.json', lost.manifest)
lost.files.delete(missing)
assert.equal((await run(lost)).ok, false)
assert.deepEqual(lost.cache.get('manifest'), prior)
assert.equal(lost.progress.at(-1)[2].done, 0, 'an interrupted file is not counted as checked')

for (const reason of ['expired', 'disabled', 'paused']) {
  const f = await fixture(); await f.enqueue()
  if (reason === 'expired') await f.grant(true, Math.floor(Date.now() / 1000) - 1)
  if (reason === 'disabled') await f.grant(false)
  if (reason === 'paused') f.paused = true
  assert.equal((await run(f)).ok, false)
  assert.equal(f.counts.creates, 0); assert.equal(f.counts.delivered, 0)
  f.paused = false; await f.grant()
  assert.equal((await run(f)).ok, true)
}

const conflict = await fixture(); await conflict.enqueue()
const batch = conflict.queue[0]
conflict.files.set(batch.name, { id: batch.name, name: batch.name, data: text('different bytes') })
assert.equal((await run(conflict)).error, 'conflict')
assert.equal(conflict.counts.delivered, 0)

const doc = { device: 'p0000000001', at: 1, stream: 'abc', seq: 4, acked: 0 }
assert.equal(await transferId(doc), await transferId({ ...doc, acked: 3 }))
assert.notEqual(await transferId(doc), await transferId({ ...doc, previous: 'chg-prior' }))

// Startup, resume and manual refresh share one native request. A later dirty queue bypasses the cooldown.
let requests = 0, finish
const bridge = { status: async ({ id }) => id ? new Promise(resolve => { finish = () => resolve({ supported: true, state: 'idle', finished: true }) }) : { supported: true, state: 'idle' },
  request: async () => ({ id: String(++requests) }), retry: async () => ({ id: 'explicit' }), configure: async () => ({ supported: true, state: 'idle' }) }
const exports = {}
const code = ts.transpileModule(readFileSync('web/src/mobile/sync/native.svelte.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
vm.runInNewContext(code, { exports, $state: x => x, setTimeout, clearTimeout, Event, window: { dispatchEvent() {} }, require: name => ({
  '@capacitor/core': { Capacitor: { isNativePlatform: () => true, getPlatform: () => 'android' }, registerPlugin: () => bridge },
  '../wait': { withTimeout: p => p }, '../../lib/i18n/index': { t: key => key }, '../../lib/i18n/format': { fmtTime: () => '18:30' },
}[name]) })
const first = exports.nativeRound(), joined = exports.nativeRound(), manual = exports.nativeRound()
assert.equal(first, joined); assert.equal(first, manual)
await new Promise(resolve => setImmediate(resolve)); finish(); await first
await exports.nativeRound(); assert.equal(requests, 1)
const dirty = exports.nativeRound(false, false, true)
await new Promise(resolve => setImmediate(resolve)); finish(); await dirty
assert.equal(requests, 2)
const active = exports.nativeRound(false, false, true)
const cleanup = exports.nativeRound(false, true)
await new Promise(resolve => setImmediate(resolve)); finish(); await active
await new Promise(resolve => setImmediate(resolve)); finish(); await cleanup
assert.equal(requests, 4, 'an explicit cleanup must run after the ordinary round')
const retry = exports.retryNativeSync()
await new Promise(resolve => setImmediate(resolve)); finish(); await retry
const refreshed = exports.nativeRound()
await new Promise(resolve => setImmediate(resolve))
assert.equal(requests, 5, 'an explicit retry must bypass the recently completed refresh cooldown')
finish(); await refreshed
// A committed library is available before the vault finishes; it is never a full-round receipt.
const snapshot = Promise.withResolvers(), vaultDone = Promise.withResolvers()
let polls = 0, complete = false
bridge.status = async () => ({ supported: true, ...await (++polls === 1 ? snapshot.promise : vaultDone.promise) })
const whole = exports.nativeRound(false, false, true).then(() => { complete = true })
const library = exports.nativeRound(false, false, false, undefined, true)
await new Promise(resolve => setImmediate(resolve))
snapshot.resolve({ id: String(requests), state: 'syncing', phase: 'vault', libraryReady: true, finished: false })
await library
assert.equal(complete, false, 'library readiness must not acknowledge the vault round')
vaultDone.resolve({ id: String(requests), state: 'idle', libraryReady: true, finished: true })
await whole
bridge.status = async () => ({ supported: true, state: 'library', finished: true })
await assert.rejects(exports.nativeRound(false, false, true, undefined, true), e => e.code === 'library')
// Android can stop and re-enqueue the same job; keep observing it instead of freezing its old error.
let statuses = [
  { state: 'retry', scheduled: false, finished: false },
  { state: 'retry', scheduled: true, finished: false },
  { state: 'syncing', phase: 'vault', finished: false },
  { state: 'idle', finished: true },
]
bridge.status = async () => ({ supported: true, ...statuses.shift() })
const observed = []
await exports.nativeRound(false, false, true, s => observed.push(s.state))
assert.deepEqual(observed, ['retry', 'retry', 'syncing', 'idle'])
// A successful chunk is not a round receipt. Keep polling the original ID across successors.
const continuationIds = [], continuationCounts = [], publication = Promise.withResolvers()
let continuationPoll = 0, roundComplete = false
bridge.status = async ({ id }) => {
  continuationIds.push(id)
  if (++continuationPoll === 4) return publication.promise
  return { supported: true, id: `chunk-${continuationPoll}`, observedId: `chunk-${continuationPoll}`,
    state: continuationPoll === 2 ? 'queued' : 'syncing', finished: false, requestReady: true,
    libraryReady: false, vaultFiles: { done: continuationPoll * 2, total: 6 } }
}
const continued = exports.nativeRound(false, false, true, s => continuationCounts.push(s.vaultFiles.done)).then(() => { roundComplete = true })
await exports.nativeRound(false, false, false, undefined, true)
while (continuationPoll < 4) await new Promise(resolve => setTimeout(resolve, 10))
assert.equal(roundComplete, false, 'all verified files still do not prove phone-index publication')
publication.resolve({ supported: true, id: 'another-request', state: 'syncing', observedId: 'chunk-3',
  finished: true, outcome: 'idle', vaultFiles: { done: 6, total: 6 } })
await continued
assert.equal(new Set(continuationIds).size, 1, 'the bridge follows continuations durably for the original observer')
assert.deepEqual(continuationCounts, [2, 4, 6, 6])
// Another request's idle state cannot hide the observed request's account/cancellation outcome.
bridge.status = async () => ({ supported: true, state: 'idle', outcome: 'paused', finished: true, requestReady: false, libraryReady: false, vaultFiles: null })
await assert.rejects(exports.nativeRound(false, false, true), e => e.code === 'paused')
assert.equal(exports.nativeSync.vaultFiles, null)
for (const state of ['paused', 'auth', 'access', 'permission']) {
  bridge.status = async () => ({ supported: true, state, scheduled: true, finished: false })
  await assert.rejects(exports.nativeRound(false, false, true), e => e.code === state)
}
Object.assign(exports.nativeSync, { state: 'retry', retryable: true, nextAt: Date.now() + 80 * 60_000 })
assert.equal(exports.nativeSyncText(), 'settings.sync.native.delayed')
assert.equal(exports.nativeSyncText('offline'), 'settings.sync.native.offline', 'network restrictions take precedence over a retry time')
exports.nativeSync.retryable = false
assert.equal(exports.nativeSyncText('queued'), 'settings.sync.native.queued')
Object.assign(exports.nativeSync, { phase: 'send', progress: 0 })
assert.equal(exports.nativePhasePct(), null, 'upload progress is not the library-read percentage')
Object.assign(exports.nativeSync, { phase: 'drive', progress: 0, driveStep: { key: 'shell.sync.readingIndex' } })
assert.equal(exports.nativePhasePct(), null, 'startup has no measurable percentage')
assert.equal(exports.nativeDriveText(), 'shell.sync.readingIndex')
exports.nativeSync.progress = .2
assert.equal(exports.nativePhasePct(), 50)
// Confirm each requested upload independently, even while the vault round is still unfinished.
const longVault = Promise.withResolvers()
let delivery = false, delivered = false
bridge.receipt = async ({ id }) => ({ name: id, ...(delivery ? { remote: 'drive-' + id } : {}) })
const sent = exports.nativeUploads('synthetic', ['one', 'two'], longVault.promise).then(() => { delivered = true })
await new Promise(resolve => setImmediate(resolve))
assert.equal(delivered, false, 'staging must not be reported as delivery')
delivery = true
await sent
assert.equal(delivered, true, 'uploads should complete without waiting for the vault')
longVault.reject(Error('later vault failure'))
await new Promise(resolve => setImmediate(resolve))
delivery = false
await assert.rejects(exports.nativeUploads('synthetic', ['three'], Promise.reject(Error('auth'))), /auth/)
await assert.rejects(exports.nativeUploads('synthetic', ['three'], Promise.resolve()), e => e.code === 'retry')
// Exercise the real MirrorSource send path: a confirmed edit must leave the page journal before vault completion.
const mirrorSource = ts.createSourceFile('mirror.ts', readFileSync('web/src/mobile/source/mirror.ts', 'utf8'), ts.ScriptTarget.Latest, true)
const mirrorClass = mirrorSource.statements.find(n => ts.isClassDeclaration(n) && n.name.text === 'MirrorSource')
const flowCode = 'export class Flow {' + mirrorClass.members.filter(n => ['runNative', 'flush'].includes(n.name?.getText(mirrorSource))).map(n => n.getText(mirrorSource)).join('\n') + '}'
const flowExports = {}, heldVault = Promise.withResolvers()
let acknowledged = 0, changesOpen = 0
vm.runInNewContext(ts.transpileModule(flowCode, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
  exports: flowExports, nativeRound: () => heldVault.promise, nativeUploads: exports.nativeUploads,
  nativeReceipt: exports.nativeReceipt, nativeSyncError: exports.nativeSyncError,
  cloudStopped: () => false, network: { online: true, wifiOnly: false },
  beginCloudChange: () => changesOpen++, endCloudChange: () => changesOpen--,
  transferId: async () => 'one', deviceId: () => 'synthetic',
})
const flow = new flowExports.Flow()
Object.assign(flow, { nativeScope: 'synthetic', nativeDirty: true, nativeReady: async () => true, stagePending: async () => ['one'],
  mine: new Set(), drive: { checkpoint() {} }, changes: { flush: async send => { await send({}); return ++acknowledged } } })
delivery = true
assert.equal(await flow.flush(), 1)
assert.equal(acknowledged, 1); assert.equal(changesOpen, 0); assert.equal(flow.lastError, '')
heldVault.reject(Error('vault still needs attention'))
await new Promise(resolve => setImmediate(resolve))
assert.equal(flow.lastError, '', 'a later vault failure cannot undo a confirmed item upload')
// Unsupported native engines must release vault ownership before any foreground fallback.
const fallback = {}, calls = []
const unsupported = { status: async () => ({ supported: false, state: 'unsupported' }),
  configure: async p => { calls.push(p); return { supported: false } }, barrier: async () => { calls.push('barrier') } }
vm.runInNewContext(code, { exports: fallback, $state: x => x, setTimeout, clearTimeout, require: name => ({
  '@capacitor/core': { Capacitor: { isNativePlatform: () => true, getPlatform: () => 'android' }, registerPlugin: () => unsupported },
  '../wait': { withTimeout: p => p }, '../../lib/i18n/index': { t: key => key }, '../../lib/i18n/format': { fmtTime: () => '18:30' },
}[name]) })
assert.equal(await fallback.nativeSyncSupported(), false)
assert.equal(await fallback.nativeSyncSupported(), false)
assert.equal(JSON.stringify(calls), JSON.stringify([{ enabled: false }, 'barrier']))
// An unfinished page promise is not proof that Android is currently running the vault worker.
const laneExports = {}, laneState = { supported: true, state: 'retry' }
const laneSource = readFileSync('web/src/mobile/lanes.ts', 'utf8')
vm.runInNewContext(ts.transpileModule(laneSource.slice(laneSource.indexOf('export type LaneKey')), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: laneExports, t: key => key, driveStatus: () => ({ ok: true }), driveWork: () => null,
  mirrorSource: {}, phone: {}, syncPaused: () => false, backup: {}, nativeSync: laneState, nativeSyncText: () => laneState.state, nativePhasePct: () => null,
  isApp: true, solo: false, source: { syncVault: true }, vault: { opts: { on: true }, step: 'Starting', prog: { pct: 63 } },
  vaultLamp: () => 'syncing', fmtAgo: () => '', pics: { state: 'idle' },
})
for (const state of ['retry', 'queued', 'wifi', 'offline']) {
  laneState.state = state
  const lane = laneExports.syncLanes().find(l => l.key === 'vault')
  assert.equal(lane.tag, 'waiting'); assert.equal(lane.active, false); assert.equal(lane.pct, null)
}
Object.assign(laneState, { state: 'syncing', phase: 'vault', progress: .63 })
assert.equal(laneExports.syncLanes().find(l => l.key === 'vault').tag, 'running')
assert.equal(laneExports.syncLanes().find(l => l.key === 'vault').pct, null, 'weighted attempt progress is never a vault percentage')
laneState.phase = 'send'
assert.equal(laneExports.syncLanes().find(l => l.key === 'vault').tag, 'waiting', 'vault yields while phone changes are being sent')
laneState.phase = 'vault'
laneState.vaultFiles = { done: 125, total: 430 }
assert.equal(laneExports.syncLanes().find(l => l.key === 'vault').files.done, 125)
laneState.state = 'retry'
assert.equal(laneExports.syncLanes().find(l => l.key === 'vault').files.done, 125, 'verified counts survive backoff')
laneState.vaultFiles = null
assert.equal(laneExports.syncLanes().find(l => l.key === 'vault').files, undefined, 'a cleared account or folder cannot retain the former counts')
console.log('Native sync algorithm passed: interruption, idempotency, access, pause, conflict, snapshots, UTF-8 and trigger coalescing.')
