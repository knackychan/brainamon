// Run with node tests/check_job_requests.mjs (uses the web app's installed TypeScript).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const ts = require('typescript')
const live = { jobs: { current: null, last: null, request: null } }
const handlers = new Map()
const windows = []
const posts = []
const puts = []
let failure = null
class ApiError extends Error { constructor(status) { super('Request failed'); this.status = status } }
const closeWin = w => { windows.splice(windows.indexOf(w), 1); w.onClose() }
const modules = {
  './api': { ApiError, api: { async post(url) {
    posts.push(url)
    if (failure) throw failure
    return { request: { ...live.jobs.request, state: url.endsWith('/approve') ? 'approved' : 'declined' }, moved: 1,
      canvas: live.jobs.request?.type === 'canvas_proposal' ? { canvas_id: 'c1', name: 'Morning', added: 2, moved: 0 } : null }
  }, async put(url, body) { puts.push([url, body]) } } },
  './events.svelte': { live, on: (event, fn) => handlers.set(event, fn) },
  './jobs': { KINDS: { describe: { label: 'Describe', name: 'Describe', ai: true, cost: 0.004 } },
    plural: (n, word) => `${n} ${word}${n === 1 ? '' : 's'}` },
  './ui.svelte': { toast() {} },
  './windows.svelte': { openWin: spec => { windows.push(spec); return spec }, closeWin },
  '../components/ConfirmBody.svelte': { default: {} },
  '../components/CategoryBatchBody.svelte': { default: {} },
  '../components/CanvasProposalBody.svelte': { default: {} },
}
const source = readFileSync(new URL('../web/src/lib/job-requests.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const exports = {}
new Function('require', 'exports', compiled)(id => {
  assert.ok(modules[id], `Unexpected import: ${id}`)
  return modules[id]
}, exports)
exports.installJobRequests()
const flush = () => new Promise(resolve => setImmediate(resolve))
const emit = (r, event = 'job') => {
  live.jobs = { ...live.jobs, request: r }
  handlers.get(event)(event === 'hello' ? { jobs: live.jobs } : live.jobs)
}
const requests = [
  { kind: 'describe', ids: [1], preview: { count: 1 } }, // legacy job request without type
  { type: 'job', kind: 'describe', ids: [1], preview: { count: 1 } },
  { type: 'note', topic: 'Design notes', excerpt: 'A note', chars: 6, sources: [1] },
  { type: 'note', topic: 'Design notes', excerpt: 'A note', chars: 6, sources: [], file: 'design.md' },
  { type: 'category', ids: [1], category: 'DESIGN', from: { INTERESTING: 1 }, sample: [{ id: 1, title: 'Design' }] },
  { type: 'category_batch', ids: [1], entries: [{ id: 1, title: 'Design', from: 'INTERESTING', category: 'DESIGN' }] },
  { type: 'canvas_proposal', ids: [1], preview: { target: { id: null, name: 'Morning', new: true, count: 0 }, layout: 'rows',
    arrange: false, counts: { thumbnail: 1, frame: 0, text: 1, sections: 1, moves: 0 }, sections: [], explicit: [] } },
]
let id = 0
for (const shape of requests) {
  for (const approved of [true, false]) {
    const request = { ...shape, id: ++id, state: 'pending', source: 'Wiskit' }
    const before = posts.length
    emit(request, 'hello')
    assert.equal(windows.length, 1)
    assert.ok(exports.requestLabel(request).length)
    await exports.reviewRequest() // opening twice must not duplicate a window
    assert.equal(windows.length, 1)
    closeWin(windows[0])
    await flush()
    assert.equal(posts.length, before, 'Close must not answer the request')
    assert.equal(live.jobs.request.state, 'pending')
    emit(request)
    assert.equal(windows.length, 0, 'SSE must not reopen a deferred prompt automatically')
    const reviewed = exports.reviewRequest()
    assert.equal(windows.length, 1, 'Jobs must reopen the prompt')
    windows[0].props.answer(approved)
    await reviewed
    assert.equal(posts.length, before + 1)
    assert.equal(posts.at(-1), `/api/jobs/request/${id}/${approved ? 'approve' : 'decline'}`)
    assert.equal(live.jobs.request.state, approved ? 'approved' : 'declined')
    await exports.reviewRequest()
    assert.equal(windows.length, 0, 'Answered requests cannot be reviewed again')
  }
}
// a canvas proposal with "Make it the active canvas" ticked sets the active canvas after Apply, and only then
{
  const request = { ...requests.at(-1), id: ++id, state: 'pending', source: 'Wiskit' }
  emit(request)
  windows[0].props.setActivate(true)
  const reviewed = exports.reviewRequest()
  windows[0].props.answer(true)
  await reviewed
  await flush()
  assert.deepEqual(puts, [['/api/canvas/active', { id: 'c1' }]])
}
assert.equal(puts.length, 1, 'Unticked canvas proposals never change the active canvas')
for (const error of [new ApiError(409), new Error('Offline')]) {
  const request = { ...requests[0], id: ++id, source: 'Wiskit', state: 'pending' }
  emit(request)
  failure = error
  windows[0].props.answer(true)
  await flush()
  assert.equal(live.jobs.request.state, 'pending', 'Failed answers remain recoverable')
  failure = null
  const reviewed = exports.reviewRequest()
  windows[0].props.answer(true)
  await reviewed
  assert.equal(live.jobs.request.state, 'approved')
}
console.log('Request UI checks passed: defer, reopen, approve, decline, reconnect and retry for all request types.')
