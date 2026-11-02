// Run from the repo root: node tests/check_mobile_network.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from '../web/node_modules/typescript/lib/typescript.js'

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

async function setup(isApp, saved) {
  const storage = new Map(saved === undefined ? [] : [['bp-wifi', saved]])
  const browser = new EventTarget(), document = new EventTarget(), connection = new EventTarget()
  connection.type = 'cellular'
  const navigator = { onLine: true, connection }
  let status = { connected: true, type: 'cellular' }, change, requests = 0, transport
  const policy = load('web/src/mobile/network.svelte.ts', { './native': {
    isApp, networkStatus: async () => status, onNetworkChange: async fn => { change = fn },
  } }, { $state: x => x, navigator, document, window: browser,
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
allowed.policy.setSyncPaused(true)
assert.equal(allowed.storage.get('bp-sync-paused'), 'on')
assert.equal(allowed.policy.syncPaused(), true)
allowed.policy.setSyncPaused(false)
assert.equal(allowed.policy.syncPaused(), false)

// Manual/forced vault rounds and PC status reads share the gate; reconnect waits for a prior round to end.
const v = await setup(true)
let rounds = 0, pcReads = 0
Object.assign(v.browser, { setInterval, setTimeout })
const vault = load('web/src/mobile/vault/auto.svelte.ts', {
  '../native': { isApp: true }, '../network.svelte': v.policy,
  '../store': { kv: { get: async () => undefined, set: async () => {} } },
  '../../lib/progress': { progress: () => ({ pct: 0, left: '' }) },
  '../state.svelte': { driveStatus: () => ({ ok: true }), phone: { tried: true }, solo: false,
    source: { syncVault: async () => { rounds++; return { state: 'idle', summary: 'Done' } }, vaultPc: async () => { pcReads++; return null } } },
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
console.log('Mobile network policy passed: defaults, persistence, native/browser changes, retries, active requests/bodies and vault pause/resume.')
