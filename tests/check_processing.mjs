// Run with node tests/check_processing.mjs. No server, keys or paid requests.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const ts = require('typescript')
const NEED = { thumb: 1, describe: 2, analyze: 4, categorize: 8, index: 16 }
const row = (id, extra = {}) => ({ id, type: 'Article', url: 'https://example.org', nd: 0, tags: '', ...extra })
const rows = [row(1, { nd: 31 }), row(2), row(3, { type: 'Video', nd: 6 }), row(4, { url: '', nd: 3 }), row(5, { nd: 8 })]
const lib = { rows, byId: new Map(rows.map(r => [r.id, r])), visible: rows, visIds: rows.map(r => r.id), sel: new Set() }
const live = { jobs: { current: null } }
const posts = [], confirmations = [], messages = []
let allow = false, previewCount = null, error = null, topic = 'Test topic'
const modules = {
  './library.svelte': { lib, NEED, isVid: r => ['Reel', 'Video'].includes(r.type), tagsOf: () => [] },
  './events.svelte': { live },
  './ui.svelte': { toast: msg => messages.push(msg) },
  './windows.svelte': {
    confirmWin: async o => { confirmations.push(o); return allow },
    promptWin: async () => topic,
  },
  './api': { ApiError: Error, api: { post: async (url, body) => {
    posts.push({ url, body })
    if (error) throw error
    return { count: previewCount ?? body.ids.length, provider: 'test', model: 'test-model' }
  } } },
}
function load(file) {
  const source = readFileSync(new URL(`../web/src/lib/${file}.ts`, import.meta.url), 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports = {}
  new Function('require', 'exports', js)(id => { assert.ok(modules[id], id); return modules[id] }, exports)
  return exports
}
const processing = modules['./processing'] = load('processing')
const { processingTargets, recommendedProcessing } = processing
const { jobTargets, startJob, jobHooks } = load('jobs')
let queuesOpened = 0
jobHooks.openProgress = () => queuesOpened++

assert.deepEqual(processingTargets(rows, 'thumb'), [1], 'Fetch only web links missing thumbnails')
assert.deepEqual(processingTargets(rows, 'thumb', true), [1, 2, 3, 5], 'Rerun still excludes local items')
assert.deepEqual(processingTargets(rows, 'analyze'), [3], 'Analyze only videos/reels')
assert.deepEqual(processingTargets(rows, 'describe'), [1, 3, 4])
assert.deepEqual(processingTargets(rows, 'categorize'), [1, 5], 'Use compact needs flags; do not recategorize completed items')
assert.deepEqual(processingTargets(rows, 'index'), [1, 2, 3, 4, 5], 'Let the server detect stale indexes')
assert.equal(recommendedProcessing(rows), 'thumb')
assert.equal(recommendedProcessing([row(6, { url: '', nd: 3 })]), 'describe')
assert.equal(recommendedProcessing([row(7, { type: 'Video', nd: 4 })]), null, 'Video downloads are an optional choice')
assert.equal(recommendedProcessing([]), null)

lib.sel = new Set([2, 3, 4])
assert.deepEqual(jobTargets('describe'), { ids: [3, 4], force: false, from: 'selection' })
assert.deepEqual(jobTargets('describe', { ids: [2], force: true }).ids, [2])
assert.deepEqual(jobTargets('thumb', { ids: [4], force: true }).ids, [])
assert.equal(jobTargets('index', { force: true }).force, false)
assert.deepEqual(jobTargets('describe', { ids: [] }).ids, [], 'An empty explicit scope must not fall back to visible items')

assert.equal(await startJob('describe', { ids: [1] }), false)
assert.equal(posts.length, 1, 'Cancel sends only preview, never a job')
assert.equal(queuesOpened, 0, 'Cancel must not open a queue')
assert.match(confirmations.at(-1).msg, /already described are skipped/)
allow = true
assert.equal(await startJob('describe', { ids: [2], force: true }), true)
assert.match(confirmations.at(-1).msg, /Replaces existing AI descriptions/)
assert.deepEqual(posts.at(-1), { url: '/api/jobs', body: { kind: 'describe', ids: [2], force: true, opts: {} } })
assert.equal(await startJob('thumb', { ids: [2], force: true }), true)
assert.match(confirmations.at(-1).detail, /captions may be replaced/)
assert.equal(queuesOpened, 2, 'Describe and Fetch both open their progress queue after starting')
jobHooks.analyzeOptions = async () => ({})
for (const [kind, ids, opts] of [['categorize', [1], {}], ['index', [1], {}], ['analyze', [3], {}], ['note', [1], { topic: 'Test' }]]) {
  assert.equal(await startJob(kind, { ids, opts }), true)
}
assert.equal(queuesOpened, 6, 'Every processing tool opens its queue')

const before = posts.length
live.jobs.current = { kind: 'describe', label: 'Describe' }
assert.equal(await startJob('index', { ids: [1] }), false)
assert.equal(posts.length, before, 'Busy guard must prevent another job')
live.jobs.current = null
previewCount = 0
assert.equal(await startJob('index', { ids: [2] }), false)
assert.equal(posts.at(-1).url, '/api/jobs/preview')
previewCount = null
error = new Error('Missing API key')
assert.equal(await startJob('describe', { ids: [1] }), false)
assert.equal(messages.at(-1), 'Missing API key')
error = null
jobHooks.analyzeOptions = async (count, force) => { assert.equal(count, 1); assert.equal(force, true); return null }
assert.equal(await startJob('analyze', { ids: [3], force: true }), false)
assert.equal(posts.at(-1).url, '/api/jobs/preview', 'Closing video options must not start a job')
topic = null
const beforeNote = posts.length
assert.equal(await startJob('note', { ids: [1] }), false)
assert.equal(posts.length, beforeNote, 'Canceling a synthesis topic must not send a request')
lib.sel.clear()
lib.visIds = Array.from({ length: 35 }, (_, i) => i + 10)
lib.byId = new Map(lib.visIds.map(id => [id, row(id)]))
assert.equal(jobTargets('note').ids.length, 30, 'Retain the visible-items synthesis limit')
assert.equal(jobTargets('note', { ids: lib.visIds }).ids.length, 35, 'Explicit selections retain all sources')
console.log('Processing checks passed: eligibility, suggestions, scope, rerun, stale index, cancel, busy, preview errors and synthesis limits.')
