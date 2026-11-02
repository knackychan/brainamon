// Run with node tests/check_capture_fetch.mjs. Exercise the component's real event handlers.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../web/src/components/CaptureFetch.svelte', import.meta.url), 'utf8')
const script = source.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1]
const js = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const job = (state = 'running', kind = 'thumb', id = 7) => ({ id, kind, state })
const flush = () => new Promise(resolve => setImmediate(resolve))

async function setup(get) {
  const handlers = new Map(), live = { jobs: { current: job(), last: null } }
  let mount
  const modules = {
    svelte: { onMount: fn => { mount = fn } },
    '../lib/api': { api: { get } },
    '../lib/events.svelte': { live, on: (kind, fn) => { handlers.set(kind, fn); return () => handlers.delete(kind) } },
    './ui/Progress.svelte': {},
  }
  const component = new Function('require', 'exports', '$props', '$state', '$derived', `${js}\nreturn { read: () => ({ status, step, error }), load }`)(
    id => modules[id], {}, () => ({ itemId: 226 }), v => v, v => v)
  const close = mount()
  await flush()
  return { ...component, close, handlers, emit: (kind, data) => handlers.get(kind)?.(data), live }
}

const snapshot = (state, step = '') => ({ job: job(), items: [{ id: 226, state, step }] })
const c = await setup(async () => snapshot('working', 'Reading the page…'))
assert.deepEqual(c.read(), { status: 'working', step: 'Reading the page…', error: '' })
c.emit('job_item', { job: 7, id: 999, state: 'done' })
c.emit('job_item', { job: 8, id: 226, state: 'error' })
assert.equal(c.read().status, 'working', 'Ignore other items and jobs')
c.emit('job_item', { job: 7, id: 226, state: 'working', step: 'Fetching thumbnail…' })
assert.equal(c.read().step, 'Fetching thumbnail…')
c.emit('job', { current: job('paused'), last: null })
assert.equal(c.read().status, 'paused')
c.emit('job', { current: job(), last: null })
assert.equal(c.read().status, 'working')
c.emit('job_item', { job: 7, id: 226, state: 'done' })
await flush()
assert.equal(c.read().status, 'done', 'A stale snapshot cannot overwrite completion')
c.close()
assert.equal(c.handlers.size, 0, 'Closing unsubscribes without stopping the job')

const failed = await setup(async () => snapshot('working'))
failed.emit('job_item', { job: 7, id: 226, state: 'error', error: 'Login required' })
assert.equal(failed.read().status, 'error')
assert.equal(failed.read().error, 'Login required')
failed.close()

const stopped = await setup(async () => snapshot('working'))
stopped.emit('job', { current: null, last: job('stopped') })
assert.equal(stopped.read().status, 'stopped')
stopped.close()

const fast = await setup(async url => url.endsWith('/progress')
  ? { job: job('running', 'index', 8), items: [] }
  : { url: 'https://example.com', description: 'Fetched caption' })
assert.equal(fast.read().status, 'done', 'Recover a fast fetch after automatic indexing takes over')
fast.close()

const offline = await setup(async () => { throw new Error('Offline') })
assert.equal(offline.read().status, 'unknown', 'Do not spin forever when progress cannot be read')
offline.close()

let recovered = snapshot('working')
const reconnect = await setup(async () => recovered)
recovered = snapshot('done')
reconnect.emit('hello', {})
await flush()
assert.equal(reconnect.read().status, 'done', 'Reconnecting recovers a missed completion event')
reconnect.close()

let finish
const closing = await setup(() => new Promise(resolve => { finish = resolve }))
closing.close()
finish(snapshot('done'))
await flush()
assert.equal(closing.read().status, 'working', 'Ignore responses after closing')
console.log('Capture fetch checks passed: steps, scoping, pause, resume, success, error, stop, fast completion, offline, reconnect and cleanup.')
