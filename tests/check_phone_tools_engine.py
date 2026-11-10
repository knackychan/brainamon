"""The Tools panel's run engine, without the panel (projects/phone-processing-flow, plans/00-review-repairs.md R1, R3, R4, R5).

The real modules run in an isolated browser page (Vite only, the synthetic pairing of tests/test_mobile_info_browser.py, a
fresh IndexedDB): the phone's loop and its Retry / Continue / Next (R1), the PC's job events against the real
DesktopSource.watchJob with deferred answers in every order the server can produce (R3), Stop by job id (R4), and Undo
through the real MirrorSource, Changes journal and overlay, whose change files are then applied by the real
server/intake.py on a temporary database (R5). Every `/api` request is refused and counted as a failure; the PC's REST
answers and the model's replies are stubs inside the page. No Drive, no PC, no data folder.

    py tests/check_phone_tools_engine.py
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.db import Database  # noqa: E402
from server import intake  # noqa: E402
from tests.test_mobile_info_browser import mobile_browser, synthetic_phone  # noqa: E402

PRE = r"""
const { phone, source } = await import('/src/mobile/state.svelte.ts')
const T = await import('/src/mobile/tools-run.svelte.ts')
const W = await import('/src/mobile/work.svelte.ts')
const { runs, work } = W
const mkrows = n => Array.from({ length: n }, (_, i) => ({ id: i + 1, uid: 'u' + (i + 1), title: 'Item ' + (i + 1), creator: '', type: 'Reel', cat: 'Art',
  tags: '', desc: 'Caption ' + (i + 1), url: 'https://example.com/' + (i + 1), src: 'web', thumb: false, ai: false, an: false, nd: 2, fav: false, created: i, tv: 0 }))
const stubSource = () => {
  source.tints = async () => ({}); source.linkDetails = async () => []; source.fillPictures = async () => ({ got: [], blocked: false })
  source.rows = async () => ({ rows: phone.rows, cats: phone.cats })
  source.rowsByIds = async ids => ids.map(id => phone.rows.find(r => r.id === id)).filter(Boolean)
  source.flushSoon = () => {}
}
const snap = r => r && JSON.parse(JSON.stringify(r))
const by = (r, st) => r.items.filter(i => i.st === st).map(i => i.id)
const state = r => ({ done: by(r, 'done'), err: by(r, 'err'), wait: by(r, 'wait'), skip: by(r, 'skip'), run: by(r, 'run'),
  stopped: r.stopped, ended: r.ended, rest: r.rest.length, attempt: r.attempt.total, unavailable: r.unavailable })
const until = async (f, ms = 4000) => { const t = Date.now(); while (!f()) { if (Date.now() - t > ms) throw new Error('timeout: ' + f); await new Promise(r => setTimeout(r, 10)) } }
const sleep = ms => new Promise(r => setTimeout(r, ms))
const scope = { item: false, heading: 'Art', count: 80 }
"""

PCH = r"""
const { DesktopSource } = await import('/src/mobile/source/desktop.ts')
const { api } = await import('/src/lib/api.ts')
source.kind = 'desktop'
stubSource()
const pc = { posts: [], gets: [], puts: [], events: new EventTarget(), progress: null, post: null }
new DesktopSource().watchJob(pc.events)
const send = (type, data) => pc.events.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }))
const defer = () => { let resolve, reject; const p = new Promise((a, b) => { resolve = a; reject = b }); return { p, resolve, reject } }
const J = (id, state, o = {}) => ({ id, kind: 'describe', label: 'Describe', state, total: 3, done: 0, skipped: 0, err: 0, ...o })
const ev = (job, id, state, o = {}) => send('job_item', { job, id, state, ...o })
const P = (job, items) => ({ job, items: items.map(([id, state, o]) => ({ id, state, title: 'PC title ' + id, ...(o || {}) })) })
api.get = async url => { pc.gets.push(url); if (url === '/api/jobs/progress') return pc.progress(); throw new Error('refused ' + url) }
api.post = async (url, body) => { pc.posts.push({ url, body }); return pc.post(url, body) }
api.put = async (url, body) => { pc.puts.push({ url, body }); return {} }
phone.rows = mkrows(12)
"""


def js(page, body, pre=PRE):
    return page.evaluate('async () => {' + pre + body + '}')


class Failure(AssertionError):
    pass


def block_api(page):
    """Refuses every /api request before the page loads, and counts them: the engine check stubs all of them in the page."""
    attempts = []
    page.context.route('**/api/**', lambda route: (attempts.append(route.request.url), route.abort()))
    return attempts


def new_page(browser, base):
    return synthetic_phone(browser, base, 360, 780, 'light')


def boot(page, base):
    attempts = block_api(page)
    page.goto(base + '/mobile.html#/lib')
    page.wait_for_function("() => !!document.querySelector('#m-app')")
    # the app's own start (its first read of the copy) must be over before a scenario takes the source over
    for _ in range(150):
        if page.evaluate("async () => (await import('/src/mobile/state.svelte.ts')).phone.tried"):
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError('the app did not finish its first read')
    return attempts


# ── R1: the phone's loop ─────────────────────────────────────────────────────────────────────────────────────────────
PHONE_FLOW = r"""
phone.rows = mkrows(80); phone.cats = [{ name: 'Art', color: '#39776b', count: 80 }]
stubSource()
const ids = phone.rows.map(r => r.id)
const calls = [], log = []
const failing = new Set([3, 7]); let stopAt = 10
source.describe = async id => { calls.push(id); if (id === stopAt) { stopAt = 0; T.stopRun() } if (failing.has(id)) throw new Error('Synthetic ' + id); return 'text ' + id }
const step = label => log.push({ label, calls: [...calls], run: state(runs.phone) })
await T.runPhone('describe', ids.slice(0, 25), { rest: ids.slice(25), scope })
step('first batch, stopped at 10')
const plan = act => { const p = T.followPlan(act); return p && { ids: p.ids, rest: p.rest.length, gone: p.gone, rerun: p.rerun } }
const plans = { retry: plan('retry'), continue: plan('continue'), next: plan('next') }
failing.clear()
await T.startFollow(T.followPlan('retry'))
step('retry the two failed')
await T.startFollow(T.followPlan('continue'))
step('continue the fifteen waiting')
const next1 = T.followPlan('next')
await T.startFollow(next1); step('next 25')
const next2 = T.followPlan('next')
await T.startFollow(next2); step('next 25 again')
const next3 = T.followPlan('next')
await T.startFollow(next3); step('the last five')
return { log, plans, nexts: [next1, next2, next3].map(p => ({ ids: p.ids.length, first: p.ids[0], rest: p.rest.length })), last: T.followPlan('next') }
"""


def phone_flow(page):
    got = js(page, PHONE_FLOW)
    log = {x['label']: x for x in got['log']}
    first = log['first batch, stopped at 10']
    ten = list(range(1, 11))
    assert first['calls'] == ten, first
    run = first['run']
    assert run['done'] == [1, 2, 4, 5, 6, 8, 9, 10] and run['err'] == [3, 7], run
    assert run['wait'] == list(range(11, 26)) and run['stopped'] and run['rest'] == 55 and run['run'] == [], run
    assert got['plans']['retry'] == {'ids': [3, 7], 'rest': 55, 'gone': [], 'rerun': False}, got['plans']
    assert got['plans']['continue'] == {'ids': list(range(11, 26)), 'rest': 55, 'gone': [], 'rerun': False}, got['plans']
    assert got['plans']['next'] == {'ids': list(range(26, 51)), 'rest': 30, 'gone': [], 'rerun': False}, got['plans']
    retry = log['retry the two failed']
    assert retry['calls'] == ten + [3, 7], retry
    r = retry['run']
    assert r['err'] == [] and r['done'] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] and r['wait'] == list(range(11, 26)), r
    assert r['stopped'] and r['rest'] == 55 and r['attempt'] == 2, r            # the stop, the waiting items and the rest all survive a retry
    cont = log['continue the fifteen waiting']
    assert cont['calls'] == ten + [3, 7] + list(range(11, 26)), cont
    c = cont['run']
    assert c['wait'] == [] and not c['stopped'] and c['rest'] == 55 and c['attempt'] == 15, c
    assert len(c['done']) == 25 and c['err'] == [], c
    n1, n2, n3 = (log[k] for k in ('next 25', 'next 25 again', 'the last five'))
    assert n1['calls'][-25:] == list(range(26, 51)) and n1['run']['rest'] == 30, n1
    assert n2['calls'][-25:] == list(range(51, 76)) and n2['run']['rest'] == 5, n2
    assert n3['calls'][-5:] == list(range(76, 81)) and n3['run']['rest'] == 0 and n3['run']['attempt'] == 5, n3
    # every id exactly once, apart from the two retried
    every = n3['calls']
    assert sorted(every) == sorted(list(range(1, 81)) + [3, 7]), every
    assert [x['ids'] for x in got['nexts']] == [25, 25, 5] and [x['rest'] for x in got['nexts']] == [30, 5, 0], got['nexts']
    assert got['last'] is None, got['last']


REPEATED_FAILURE = r"""
phone.rows = mkrows(80); stubSource()
const ids = phone.rows.map(r => r.id), calls = []
source.describe = async id => { calls.push(id); if (id === 3 || id === 7) throw new Error('Still failing ' + id); return 'text ' + id }
await T.runPhone('describe', ids.slice(0, 25), { rest: ids.slice(25), scope })
const out = []
for (let k = 0; k < 3; k++) {
  await T.startFollow(T.followPlan('retry'))
  out.push({ calls: [...calls], run: state(runs.phone), why: runs.phone.items.filter(i => i.st === 'err').map(i => i.why) })
}
return out
"""


def repeated_failure(page):
    out = js(page, REPEATED_FAILURE)
    base = list(range(1, 26))
    for k, step in enumerate(out):
        assert step['calls'] == base + [3, 7] * (k + 1), (k, step['calls'])
        assert step['run']['err'] == [3, 7] and step['run']['rest'] == 55 and len(step['run']['done']) == 23, step
        assert step['why'] == ['Still failing 3', 'Still failing 7'], step


GONE = r"""
phone.rows = mkrows(40); stubSource()
const ids = phone.rows.map(r => r.id), calls = []
let stopAt = 5
source.describe = async id => { calls.push(id); if (id === stopAt) { stopAt = 0; T.stopRun() } return 'text ' + id }
await T.runPhone('describe', ids.slice(0, 25), { rest: ids.slice(25).concat([999]), scope })
// item 12 leaves the library; item 13 is a link the PC has numbered meanwhile (uid kept); 999 never existed
phone.rows = phone.rows.filter(r => r.id !== 12).map(r => (r.id === 13 ? { ...r, id: 513 } : r))
const plan = T.followPlan('continue')
await T.startFollow(plan)
const run = runs.phone
const gone = run.items.find(i => i.id === 12)
// next: the batch is capped at 25 even when the rest is long, and a vanished id shows as skipped
const nextPlan = T.followPlan('next')
await T.startFollow(nextPlan)
return { plan: { ids: plan.ids, gone: plan.gone }, calls, gone: gone && { st: gone.st, why: gone.why },
  remapped: calls.includes(513) && !calls.includes(13), nextIds: nextPlan.ids.length, nextGone: nextPlan.gone, ledger: state(runs.phone), skipWhy: runs.phone.items.filter(i => i.st === 'skip').map(i => [i.id, i.why]) }
"""


def gone_items(page):
    out = js(page, GONE)
    assert out['plan']['gone'] == [12] and 12 not in out['plan']['ids'] and 513 in out['plan']['ids'], out
    assert out['gone'] == {'st': 'skip', 'why': 'This item is no longer in your library.'}, out
    assert out['remapped'] and 12 not in out['calls'] and 999 not in out['calls'], out
    assert out['nextIds'] == 15 and out['nextGone'] == [999], out        # 26..40 still exist; 999 never did
    assert [i for i, _ in out['skipWhy']] == [999], out


def queued_identity(page):
    out = js(page, r"""
phone.rows = mkrows(4); stubSource()
const calls = []
source.describe = async id => {
  calls.push(id)
  if (id === 1) phone.rows = phone.rows.filter(r => r.id !== 2).map(r => r.id === 3 ? { ...r, id: 503 } : r)
  return 'text ' + id
}
await T.runPhone('describe', [1, 2, 3], { rest: [4], scope })
const first = state(runs.phone)
phone.rows = phone.rows.map(r => r.id === 4 ? { ...r, id: 504 } : r)
const next = T.followPlan('next')
if (next) await T.startFollow(next)
const second = state(runs.phone)
T.dismiss()
await T.runPhone('describe', [1], { rest: [504], scope })
phone.rows = phone.rows.filter(r => r.id !== 504)
const gone = T.followPlan('next')
if (gone) await T.startFollow(gone)
return { calls, first, second, last: state(runs.phone), next: T.followPlan('next') }
""")
    assert out['calls'] == [1, 503, 504, 1], out
    assert out['first']['skip'] == [2] and out['second']['done'] == [504], out
    assert out['last']['skip'] == [504] and out['last']['rest'] == 0 and out['last']['ended'], out
    assert out['next'] is None, out


# ── R3: the PC's events and the answer to POST /api/jobs, in every order ───────────────────────────────────────────────
PC_ENDED_BEFORE_THE_ANSWER = r"""
const D = defer()
pc.post = async url => (url === '/api/jobs' ? D.p : {})
pc.progress = async () => P(J(41, 'finished', { done: 2, err: 1 }), [[1, 'done'], [2, 'done'], [3, 'error', { error: 'Synthetic PC failure' }]])
const started = T.runPc('describe', [1, 2, 3], { scope })
send('job', { current: J(41, 'running'), last: null })
ev(41, 1, 'working'); ev(41, 1, 'done'); ev(41, 2, 'working'); ev(41, 2, 'done'); ev(41, 3, 'working'); ev(41, 3, 'error', { error: 'Synthetic PC failure' })
send('job', { current: null, last: J(41, 'finished', { done: 2, err: 1 }) })
D.resolve(J(41, 'running'))                     // the answer carries the older snapshot
await started
await until(() => runs.pc && runs.pc.ended)
return { run: state(runs.pc), why: runs.pc.items.find(i => i.id === 3).why, busy: runs.pcJob, counts: snap(runs.pc.counts), kept: [...work].filter(([, m]) => m.keep).map(([id, m]) => [id, m.st]) }
"""

PC_EVENTS_AFTER_THE_ANSWER = r"""
pc.post = async url => (url === '/api/jobs' ? J(42, 'running') : {})
let step = 0
pc.progress = async () => P(J(42, step ? 'finished' : 'running', step ? { done: 3 } : {}), [[1, step ? 'done' : 'queued'], [2, step ? 'done' : 'queued'], [3, step ? 'done' : 'queued']])
await T.runPc('describe', [1, 2, 3], { scope })
await until(() => runs.pc && runs.pc.loaded)
const early = state(runs.pc)
send('job', { current: J(42, 'running'), last: null })
ev(42, 1, 'working'); ev(42, 1, 'done')
const mid = state(runs.pc)
step = 1
ev(42, 2, 'done'); ev(42, 3, 'done')
send('job', { current: null, last: J(42, 'finished', { done: 3 }) })
await until(() => runs.pc.ended)
return { early, mid, end: state(runs.pc) }
"""

PC_FINISHED_WHILE_DISCONNECTED = r"""
pc.post = async url => (url === '/api/jobs' ? J(43, 'running') : {})
let over = false
pc.progress = async () => (over ? P(J(43, 'finished', { done: 2, skipped: 1 }), [[1, 'done'], [2, 'skipped', { step: 'Nothing to describe yet' }], [3, 'done']])
  : P(J(43, 'running'), [[1, 'queued'], [2, 'queued'], [3, 'queued']]))
await T.runPc('describe', [1, 2, 3], { scope })
await until(() => runs.pc.loaded)
const running = state(runs.pc)
over = true                                      // the job ends while the page is away; no event arrives
send('hello', { jobs: { current: null, last: J(43, 'finished', { done: 2, skipped: 1 }) } })
await until(() => runs.pc.ended)
return { running, end: state(runs.pc), skipWhy: runs.pc.items.find(i => i.id === 2).why, gets: pc.gets.filter(u => u === '/api/jobs/progress').length }
"""

PC_STALE_PROGRESS = r"""
pc.post = async url => (url === '/api/jobs' ? J(44, 'running') : {})
const D = defer(); let calls = 0
pc.progress = () => { calls++; return calls === 1 ? D.p : Promise.resolve(P(J(44, 'running', { total: 4 }), [[1, 'queued'], [2, 'queued'], [3, 'queued'], [4, 'queued']])) }
await T.runPc('describe', [1, 2, 3], { scope })
await sleep(20)                                  // the first read is on its way, the PC answered it before the next events
ev(44, 2, 'working'); ev(44, 2, 'done'); ev(44, 9, 'working')
D.resolve(P(J(44, 'running'), [[1, 'done'], [2, 'working'], [3, 'queued']]))      // 2 is stale here; 9 is not listed
await until(() => runs.pc.loaded)
const afterStale = state(runs.pc)
// a later read that lists a finished item as queued again must not take its result back
send('job', { current: J(44, 'running', { total: 4 }), last: null })
await until(() => calls >= 2)
await sleep(30)
return { afterStale, after: state(runs.pc), calls }
"""

PC_DIFFERENT_JOB = r"""
pc.post = async url => (url === '/api/jobs' ? J(45, 'running') : {})
const D = defer(); let calls = 0
pc.progress = () => { calls++; return calls === 1 ? D.p : Promise.resolve(P(J(46, 'running', { kind: 'index' }), [[1, 'queued']])) }
await T.runPc('describe', [1, 2, 3], { scope })
await sleep(20)
ev(45, 1, 'done'); ev(45, 2, 'done'); ev(45, 3, 'error', { error: 'Synthetic' })
// the job ends and the PC starts another one at once; the first read answers late, the second is about the new job
send('job', { current: J(46, 'running', { kind: 'index', label: 'Index for search', total: 1 }), last: J(45, 'finished', { done: 2, err: 1 }) })
D.resolve(P(J(45, 'running'), [[1, 'working'], [2, 'queued'], [3, 'queued']]))
await until(() => runs.pc.ended)
return { run: state(runs.pc), counts: snap(runs.pc.counts), busy: snap(runs.pcJob), kind: runs.pc.kind, why: runs.pc.items.find(i => i.id === 3).why }
"""

PC_ANALYZE_JOIN = r"""
const A = (id, state, o = {}) => J(id, state, { kind: 'analyze', label: 'Analyze videos', total: 2, ...o })
pc.post = async (url, body) => (url === '/api/jobs' ? A(50, 'running', { total: body.ids.length === 1 ? 4 : 2 }) : {})
let listed = [[1, 'queued'], [2, 'queued']]
pc.progress = async () => P(A(50, 'running', { total: listed.length }), listed)
await T.runPc('analyze', [1, 2], { scope, opts: { frame_interval: 3 } })
await until(() => runs.pc.loaded)
const first = state(runs.pc)
// another phone, or the desktop, adds a video to the same job: same id, a larger total, no queued event
listed = [[1, 'queued'], [2, 'queued'], [3, 'queued']]
send('job', { current: A(50, 'running', { total: 3 }), last: null })
await until(() => runs.pc.items.length === 3)
const grown = { items: runs.pc.items.map(i => i.id), total: runs.pc.total }
// ours takes one more: the answer is the same job again
listed = [[1, 'queued'], [2, 'queued'], [3, 'queued'], [4, 'queued']]
await T.runPc('analyze', [4], { scope, opts: {} })
await until(() => runs.pc.items.length === 4)
return { first, grown, ours: runs.pc.items.map(i => i.id), job: runs.pc.job, posts: pc.posts.filter(p => p.url === '/api/jobs').length }
"""

PC_SERVER_FILTERS = r"""
pc.post = async url => (url === '/api/jobs' ? J(47, 'running', { total: 2 }) : {})
pc.progress = async () => P(J(47, 'running', { total: 2 }), [[1, 'queued'], [3, 'queued']])
await T.runPc('describe', [1, 2, 3], { scope })
await until(() => runs.pc.loaded)
return { items: runs.pc.items.map(i => i.id), total: runs.pc.total, prov: runs.pc.prov.length, fresh: runs.pc.fresh.length }
"""

PC_AUTO_INDEX = r"""
pc.post = async url => (url === '/api/jobs' ? J(51, 'running') : {})
let phase = 0
pc.progress = async () => (phase ? P(J(52, 'running', { kind: 'index', label: 'Index for search', total: 2 }), [[1, 'working'], [2, 'queued']])
  : P(J(51, 'running'), [[1, 'queued'], [2, 'queued'], [3, 'queued']]))
await T.runPc('describe', [1, 2, 3], { scope })
await until(() => runs.pc.loaded)
ev(51, 1, 'working'); ev(51, 1, 'done'); ev(51, 2, 'working'); ev(51, 2, 'error', { error: 'Synthetic' }); ev(51, 3, 'working'); ev(51, 3, 'done')
phase = 1
// the PC finishes the Describe and starts its automatic Index in the same breath
send('job', { current: J(52, 'running', { kind: 'index', label: 'Index for search', total: 2 }), last: J(51, 'finished', { done: 2, err: 1 }) })
await until(() => runs.pc.ended)
const ended = { run: state(runs.pc), kind: runs.pc.kind, busy: snap(runs.pcJob), marks: [...work].filter(([, m]) => m.keep).map(([id, m]) => [id, m.st, m.lane]) }
// more index events must not touch the Describe ledger or its failure mark
ev(52, 1, 'done'); ev(52, 2, 'error', { error: 'index trouble' })
const after = { run: state(runs.pc), why: runs.pc.items.find(i => i.id === 2).why, marks: [...work].filter(([, m]) => m.keep).map(([id, m]) => [id, m.st]) }
T.dismiss('pc')
return { ended, after, busyAfterDone: snap(runs.pcJob), ledgerGone: runs.pc === null, marksGone: [...work].filter(([, m]) => m.keep).length }
"""

PC_UNAVAILABLE = r"""
pc.post = async url => (url === '/api/jobs' ? J(60, 'running') : {})
pc.progress = async () => P(J(62, 'running', { kind: 'index', total: 5 }), [[1, 'queued']])
await T.runPc('describe', [1, 2, 3], { scope })
await sleep(50)
// the PC lists another job and we never saw ours finish: nothing about it can be reported
await until(() => runs.pc.ended)
const a = { run: state(runs.pc), counts: snap(runs.pc.counts), retry: T.followPlan('retry'), cont: T.followPlan('continue') }
T.dismiss('pc')
// the same, but the PC's last snapshot of our job did arrive before the read was answered: its counts are kept
pc.post = async url => (url === '/api/jobs' ? J(63, 'running') : {})
const D = defer()
pc.progress = () => D.p
await T.runPc('describe', [1, 2, 3], { scope })
send('job', { current: J(65, 'running', { kind: 'index' }), last: J(63, 'finished', { done: 2, err: 1 }) })
D.resolve(P(J(65, 'running', { kind: 'index', total: 5 }), [[1, 'queued']]))
await until(() => runs.pc.ended)
const b = { run: state(runs.pc), counts: snap(runs.pc.counts), retry: T.followPlan('retry') }
return { a, b }
"""

PC_FAILED_POST = r"""
pc.post = async url => { if (url === '/api/jobs') throw new Error('The PC is not reachable.'); return {} }
const failed = await T.runPc('describe', [1, 2], { scope }).then(() => 'started', e => e.message)
const none = runs.pc
pc.post = async url => (url === '/api/jobs' ? J(70, 'running', { total: 2 }) : {})
pc.progress = async () => P(J(70, 'running', { total: 2 }), [[1, 'queued'], [2, 'queued']])
await T.runPc('describe', [1, 2], { scope })
return { failed, none, again: runs.pc && runs.pc.job }
"""

PC_LOST_AFTER_LOAD = r"""
pc.post = async () => J(71, 'running')
pc.progress = async () => P(J(71, 'running'), [[1, 'queued'], [2, 'queued'], [3, 'queued']])
await T.runPc('describe', [1, 2, 3], { scope })
await until(() => runs.pc.loaded)
// While disconnected the Describe ends and automatic Index replaces its progress rows.
pc.progress = async () => P(J(72, 'running', { kind: 'index' }), [[1, 'queued']])
send('hello', { jobs: { current: J(72, 'running', { kind: 'index' }), last: J(71, 'finished', { done: 2, err: 1 }) } })
await until(() => runs.pc.ended)
const { progress } = await import('/src/mobile/tools.ts')
return { run: state(runs.pc), progress: progress(runs.pc), retry: T.followPlan('retry') }
"""

PC_JOIN_OPTIONS = r"""
const options = { frame_interval: 5, transcribe: false, analysis_provider: 'none' }
pc.post = async () => J(73, 'running', { kind: 'analyze', options })
pc.progress = async () => P(J(73, 'stopped', { kind: 'analyze', options, err: 1 }), [[1, 'error'], [2, 'queued'], [3, 'queued']])
await T.runPc('analyze', [1, 2, 3], { scope, joined: true })
await until(() => runs.pc.ended)
return { opts: snap(runs.pc.opts), retry: T.followPlan('retry').opts, cont: T.followPlan('continue').opts }
"""

PC_STOP = r"""
pc.post = async (url, body) => {
  if (url === '/api/jobs') return J(80 + pc.posts.filter(p => p.url === '/api/jobs').length, 'running', { total: body.ids.length })
  if (url === '/api/jobs/stop') { if (pc.refuse) throw new Error(pc.refuse); return {} }
  return {}
}
pc.progress = async () => P(J(pc.shown, 'running'), [[1, 'queued'], [2, 'queued'], [3, 'queued']])
pc.shown = 81
await T.runPc('describe', [1, 2, 3], { scope })
await until(() => runs.pc.loaded)
pc.refuse = 'The PC is not reachable.'
const refused = await T.stopRun().then(() => 'stopped', e => e.message)
const afterRefusal = { stopping: runs.pc.stopping, ended: runs.pc.ended }
pc.refuse = 'That job is not running any more; nothing was stopped.'
const refused2 = await T.stopRun().then(() => 'stopped', e => e.message)
pc.refuse = ''
await T.stopRun()
const afterStop = { stopping: runs.pc.stopping }
// the job stops with an error on item 2; Retry starts job 82 in the same ledger and Stop then names job 82
ev(81, 1, 'done'); ev(81, 2, 'error', { error: 'x' }); ev(81, 3, 'queued')
pc.progress = async () => P(J(81, 'stopped', { done: 1, err: 1 }), [[1, 'done'], [2, 'error', { error: 'x' }], [3, 'queued']])
send('job', { current: null, last: J(81, 'stopped', { done: 1, err: 1 }) })
await until(() => runs.pc.ended)
pc.shown = 82
pc.progress = async () => P(J(82, 'running', { total: 1 }), [[2, 'queued']])
await T.startFollow(T.followPlan('retry'))
await until(() => runs.pc.loaded)
await T.stopRun()
return { refused, refused2, afterRefusal, afterStop, stops: pc.posts.filter(p => p.url === '/api/jobs/stop').map(p => p.body), jobs: pc.posts.filter(p => p.url === '/api/jobs').map(p => p.body),
  retried: state(runs.pc), job: runs.pc.job }
"""


def pc_scenarios(browser, base):
    cases = {
        'ended_before_the_answer': PC_ENDED_BEFORE_THE_ANSWER, 'events_after_the_answer': PC_EVENTS_AFTER_THE_ANSWER,
        'finished_while_disconnected': PC_FINISHED_WHILE_DISCONNECTED, 'stale_progress': PC_STALE_PROGRESS,
        'different_job': PC_DIFFERENT_JOB, 'analyze_join': PC_ANALYZE_JOIN, 'server_filters': PC_SERVER_FILTERS,
        'auto_index': PC_AUTO_INDEX, 'unavailable': PC_UNAVAILABLE, 'failed_post': PC_FAILED_POST, 'stop': PC_STOP,
        'lost_after_load': PC_LOST_AFTER_LOAD, 'join_options': PC_JOIN_OPTIONS,
    }
    out = {}
    for name, body in cases.items():
        with new_page(browser, base) as (page, errors):
            attempts = boot(page, base)
            try:
                out[name] = js(page, body, PRE + PCH)
            except Exception as exc:
                raise Failure(f'{name}: {exc}') from exc
            assert attempts == [], (name, attempts)
            assert errors == [], (name, errors)
    return out


def check_pc(out):
    lost = out['lost_after_load']
    assert lost['run']['unavailable'] and lost['retry'] is None, lost
    assert lost['progress'] == {'n': 3, 'done': 2, 'skip': 0, 'err': 1, 'left': 0}, lost
    joined = out['join_options']
    assert all(v == {'frame_interval': 5, 'transcribe': False, 'analysis_provider': 'none'} for v in joined.values()), joined
    a = out['ended_before_the_answer']
    assert a['run']['ended'] and a['run']['done'] == [1, 2] and a['run']['err'] == [3] and not a['run']['unavailable'], a
    assert a['why'] == 'Synthetic PC failure' and a['busy'] is None and a['counts'] == {'done': 2, 'skip': 0, 'err': 1}, a
    assert a['kept'] == [[3, 'err']], a
    b = out['events_after_the_answer']
    assert b['early']['wait'] == [1, 2, 3] and not b['early']['ended'], b
    assert b['mid']['done'] == [1] and b['mid']['ended'] is False, b
    assert b['end']['done'] == [1, 2, 3] and b['end']['ended'] and not b['end']['unavailable'], b
    c = out['finished_while_disconnected']
    assert c['running']['wait'] == [1, 2, 3] and c['end']['done'] == [1, 3] and c['end']['skip'] == [2] and c['end']['ended'], c
    assert c['skipWhy'] == 'Nothing to describe yet' and c['gets'] >= 2, c
    d = out['stale_progress']
    # the events after the request began win over the stale answer (2 was working in it); 9 was not listed and stays
    assert d['afterStale']['done'] == [1, 2] and d['afterStale']['wait'] == [3] and d['afterStale']['run'] == [9], d
    # a later read that lists a finished item as queued does not take its result back; 4 joins
    assert d['after']['done'] == [1, 2] and d['after']['wait'] == [3, 4] and d['after']['run'] == [9] and d['calls'] == 2, d
    e = out['different_job']
    assert e['run']['ended'] and e['run']['done'] == [1, 2] and e['run']['err'] == [3] and e['kind'] == 'describe', e
    assert e['counts'] == {'done': 2, 'skip': 0, 'err': 1} and e['busy']['kind'] == 'index' and e['why'] == 'Synthetic', e
    f = out['analyze_join']
    assert f['first']['wait'] == [1, 2] and f['grown']['items'] == [1, 2, 3] and f['grown']['total'] == 3, f
    assert f['ours'] == [1, 2, 3, 4] and f['job'] == 50 and f['posts'] == 2, f
    g = out['server_filters']
    assert g['items'] == [1, 3] and g['total'] == 2 and g['prov'] == 0 and g['fresh'] == 0, g
    h = out['auto_index']
    assert h['ended']['run']['ended'] and h['ended']['kind'] == 'describe' and h['ended']['run']['done'] == [1, 3] and h['ended']['run']['err'] == [2], h
    assert h['ended']['busy']['kind'] == 'index' and h['ended']['marks'] == [[2, 'err', 'pc']], h
    assert h['after']['run'] == h['ended']['run'] and h['after']['why'] == 'Synthetic' and h['after']['marks'] == [[2, 'err']], h
    assert h['busyAfterDone']['kind'] == 'index' and h['ledgerGone'] and h['marksGone'] == 0, h
    u = out['unavailable']
    assert u['a']['run']['ended'] and u['a']['run']['unavailable'] and u['a']['run']['done'] == [] and u['a']['counts'] is None, u
    assert u['a']['retry'] is None and u['a']['cont'] is None, u
    assert u['b']['run']['unavailable'] and u['b']['counts'] == {'done': 2, 'skip': 0, 'err': 1} and u['b']['run']['done'] == [] and u['b']['retry'] is None, u
    p = out['failed_post']
    assert p['failed'] == 'The PC is not reachable.' and p['none'] is None and p['again'] == 70, p
    s = out['stop']
    assert s['refused'] == 'The PC is not reachable.' and s['afterRefusal'] == {'stopping': False, 'ended': False}, s
    assert 'not running any more' in s['refused2'] and s['afterStop'] == {'stopping': True}, s
    assert s['stops'] == [{'id': 81}, {'id': 81}, {'id': 81}, {'id': 82}], s        # the displayed job's id, each time; after Retry the new job's
    assert s['jobs'][1] == {'kind': 'describe', 'ids': [2], 'force': False, 'opts': {}} and s['job'] == 82, s
    assert s['retried']['err'] == [] and s['retried']['done'] == [1] and s['retried']['wait'] == [2, 3], s    # the ledger keeps the other entries


# ── R5: Undo through the real source, journal, overlay and server intake ───────────────────────────────────────────────
UID1, UID2, UID3 = 'a1' * 16, 'b2' * 16, 'c3' * 16
UNDO = r"""
const { kv } = await import('/src/mobile/store.ts')
const { setFetch } = await import('/src/mobile/ai/providers.ts')
const { UndoRefused } = await import('/src/mobile/tools.ts')
const UIDS = %s
const enc = o => new TextEncoder().encode(JSON.stringify(o))
const full = (id, uid, o = {}) => ({ id, uid, url: 'https://example.com/' + id, description: 'The original caption ' + id, short_desc: '', creator: '', type: 'Reel',
  category: 'INTERESTING', tags: '', ai_desc: '', notes: '', created: 0, modified: 0, files: { thumb: false, report: false, transcript: false, frames: 0, frame_names: [], video: false },
  report: '', transcript: '', ...o })
const items = {}
const rowOf = (id, uid, o = {}) => ({ id, uid, title: 'Item ' + id, creator: '', type: 'Reel', cat: 'INTERESTING', tags: '', desc: 'The original caption ' + id, url: 'https://example.com/' + id,
  src: 'web', thumb: false, ai: false, an: false, nd: 2, fav: false, created: 0, tv: 0, ...o })
const seedBase = async rows => { await kv.set('rows', rows); source.forgetCopy(); source.changes.list = [] }
source.fetchFile = async name => { const f = items[name]; if (!f) throw new Error('missing ' + name); return enc(f) }
source.itemAi = () => ({ p: 'anthropic', key: 'k', model: 'm', cap: n => n })
source.endpoints = () => ({ anthropic: 'https://api.anthropic.com', openai: 'https://api.openai.com' })
source.thumbBlob = async () => null
source.flushSoon = () => {}
source.ai = () => ({ provider: 'anthropic', model: 'm', label: 'M' })
source.rows = async () => ({ rows: phone.rows, cats: phone.cats })
let reply = 'A model description'
setFetch(async () => new Response(JSON.stringify({ content: [{ type: 'text', text: reply }] }), { status: 200 }))
const publish = (uid, id) => { items['items/' + uid + '.json'] = full(id, uid) }
const docs = []
const flush = async () => { docs.length = 0; await source.changes.flush(async d => { docs.push(JSON.parse(JSON.stringify(d))); return 'chg-' + docs.length + '-' + Date.now() }, 'phone-1', true, false); return docs.map(d => d) }
const prune = () => source.changes.prune(Date.now() + 1e9)
const reload = async (rows, ids) => { await kv.set('rows', rows); source.forgetCopy(); await source.rowsByIds([]); phone.rows = await source.rowsByIds(ids) }
const one = id => phone.rows.find(r => r.id === id)
const itemScope = { item: true, heading: 'Item', count: 1 }
const out = {}
%s
return out
"""


def undo_body(steps):
    return UNDO % (str([UID1, UID2, UID3]), steps)


UNDO_STEPS = r"""
// 1. a PC card with no AI description: Describe, sync, Undo
publish(UIDS[0], 1)
await seedBase([rowOf(1, UIDS[0])]); await source.rowsByIds([]); phone.rows = await source.rowsByIds([1]); phone.cats = []
await T.runPhone('describe', [1], { scope: itemScope })
out.d1 = { token: snap(runs.phone.undo), text: runs.phone.text, card: { ai: one(1).ai, desc: one(1).desc } }
out.doc1 = await flush()                                  // what goes to the PC
await prune()                                             // ... which applied it; the published copy now holds the AI text
publish(UIDS[0], 1); items['items/' + UIDS[0] + '.json'].ai_desc = 'A model description'
await reload([rowOf(1, UIDS[0], { ai: true, desc: 'A model description' })], [1])
out.afterSync = { ai: one(1).ai, desc: one(1).desc }
await T.undo()
out.afterUndo = { ai: one(1).ai, desc: one(1).desc, undone: runs.phone.undone, note: runs.phone.why }     // the card's OWN text, not the AI excerpt
out.journal = source.changes.list.map(e => ({ op: e.op, fields: e.fields, was: e.was, plain: e.plain }))
out.doc2 = await flush()
out.wire = JSON.stringify(out.doc2)
// 2. the same card after its published row moved to another number (the uid is what names it)
await prune(); source.changes.list = []
await reload([rowOf(11, UIDS[0], { ai: true, desc: 'A model description' })], [11])
const renum = await source.undoTool({ kind: 'describe', uid: UIDS[0], was: { ai_desc: '' }, now: { ai_desc: 'A model description' } })
out.renumbered = { id: renum.id, desc: renum.desc, ai: renum.ai }
// 3. a nonempty earlier description comes back
publish(UIDS[1], 2); items['items/' + UIDS[1] + '.json'].ai_desc = 'Old AI text'
await prune(); source.changes.list = []
await reload([rowOf(2, UIDS[1], { ai: true, desc: 'Old AI text' })], [2])
reply = 'A newer AI text'
runs.phone = null
await T.runPhone('describe', [2], { rerun: true, scope: itemScope })
out.d2 = { token: snap(runs.phone.undo), card: one(2).desc }
await T.undo()
out.d2undo = { desc: one(2).desc, ai: one(2).ai }
// 4. a newer edit of the description prevents Undo and writes nothing
publish(UIDS[1], 2); items['items/' + UIDS[1] + '.json'].ai_desc = 'Rewritten on the PC'
const before = source.changes.list.length
const refused = await source.undoTool({ kind: 'describe', uid: UIDS[1], was: { ai_desc: 'Old AI text' }, now: { ai_desc: 'A newer AI text' } }).then(() => 'undone', e => (e instanceof UndoRefused) + ': ' + e.message)
out.refusedDescribe = { refused, added: source.changes.list.length - before }
// 5. Auto-categorize: newer category change prevents Undo; a deleted card too
await prune(); source.changes.list = []
await reload([rowOf(3, UIDS[2], { cat: 'INTERESTING', tags: '' })], [3])
publish(UIDS[2], 3)
source.categorize = async (id, cats) => source.edit(id, { category: 'Art', tags: 'cat, tag' })
runs.phone = null
await T.runPhone('categorize', [3], { scope: itemScope })
out.c1 = { token: snap(runs.phone.undo), card: { cat: one(3).cat, tags: one(3).tags } }
await source.edit(3, { category: 'Recipes' })                           // a newer local edit
phone.rows = await source.rowsByIds([3])
const n0 = source.changes.list.length
await T.undo().catch(e => { out.c1refused = e.message })
out.c1after = { entries: source.changes.list.length - n0, token: runs.phone.undo, note: runs.phone.why, undone: runs.phone.undone, cat: one(3).cat }
const gone = await source.undoTool({ kind: 'categorize', uid: 'f'.repeat(32), was: { cat: 'x', tags: '' }, now: { cat: 'y', tags: '' } }).then(() => 'undone', e => e.message)
out.goneCard = gone
// 6. a failed journal write is retryable; two taps run one Undo
await prune(); source.changes.list = []
await reload([rowOf(3, UIDS[2], { cat: 'Art', tags: 'cat, tag' })], [3])
runs.phone = null
await T.runPhone('categorize', [3], { scope: itemScope })              // no change needed: Art/cat, tag is what the stub writes again
const add = source.changes.commitUndo.bind(source.changes)
source.changes.commitUndo = async () => { throw new Error('disk full') }
const failed = await T.undo().then(() => 'undone', e => e.message)
out.failedWrite = { failed, undone: runs.phone.undone, undoing: runs.phone.undoing, tokenKept: !!runs.phone.undo }
source.changes.commitUndo = add
let adds = 0
source.changes.commitUndo = async (...a) => { adds++; return add(...a) }
await Promise.allSettled([T.undo(), T.undo()])
out.doubleTap = { adds, undone: runs.phone.undone }
"""

LINK_STEPS = r"""
// a link saved on this phone (a negative number), described from its page text, then undone
await seedBase([]); await source.rowsByIds([])
const link = await source.saveLink('https://example.com/saved-here')
await source.changes.add({ op: 'details', uid: source.changes.list.find(e => e.op === 'link').uid, title: 'Saved here', creator: 'someone', desc: 'The page caption', thumb: '' })
source.setRows()
phone.rows = await source.rowsByIds([link.id]); phone.cats = []
out.before = { id: link.id, desc: phone.rows[0].desc, ai: phone.rows[0].ai }
runs.phone = null
await T.runPhone('describe', [link.id], { scope: itemScope })
out.described = { desc: one(link.id).desc, ai: one(link.id).ai, token: snap(runs.phone.undo) }
await T.undo()
out.undone = { desc: one(link.id).desc, ai: one(link.id).ai }
out.wire = JSON.stringify(source.changes.list.filter(e => e.op === 'edit'))
"""

UNDO_STORAGE = r"""
publish(UIDS[0], 1)
await seedBase([rowOf(1, UIDS[0])]); await source.rowsByIds([]); phone.rows = await source.rowsByIds([1]); phone.cats = []
await T.runPhone('describe', [1], { scope: itemScope })
const before = JSON.stringify(source.changes.list)
const transaction = IDBDatabase.prototype.transaction
IDBDatabase.prototype.transaction = function(stores, mode, ...args) {
  if (mode === 'readwrite' && (stores === 'changes' || Array.isArray(stores) && stores.includes('changes'))) throw new DOMException('disk full', 'QuotaExceededError')
  return transaction.call(this, stores, mode, ...args)
}
try {
  out.failed = await T.undo().then(() => false, () => true)
  out.retryable = !runs.phone.undone && !!runs.phone.undo && !runs.phone.undoing
  out.unchanged = JSON.stringify(source.changes.list) === before
} finally { IDBDatabase.prototype.transaction = transaction }
await T.undo()
out.retried = runs.phone.undone && !one(1).ai
// An edit already queued behind a slow flush wins over Undo when its turn arrives.
await prune(); source.changes.list = []
await reload([rowOf(1, UIDS[0], { cat: 'INTERESTING', tags: '' })], [1])
source.categorize = async id => source.edit(id, { category: 'Art', tags: 'tag' })
runs.phone = null
await T.runPhone('categorize', [1], { scope: itemScope })
let release, entered
const held = new Promise(r => { release = r }), started = new Promise(r => { entered = r })
const flushing = source.changes.flush(async () => { entered(); await held; return 'chg-held' }, 'phone-1', true, false)
await started
const edit = source.edit(1, { category: 'Recipes' })
await sleep(20)
const undone = T.undo().then(() => false, e => e instanceof UndoRefused)
await sleep(20)
release()
await flushing; await edit
out.newerRefused = await undone
out.category = (await source.rowsByIds([1]))[0].cat
"""


def undo_storage(browser, base):
    with new_page(browser, base) as (page, errors):
        attempts = boot(page, base)
        out = js(page, undo_body(UNDO_STORAGE))
        assert out == {'failed': True, 'retryable': True, 'unchanged': True, 'retried': True,
                       'newerRefused': True, 'category': 'Recipes'}, out
        assert attempts == [] and errors == [], (attempts, errors)


def undo_end_to_end(browser, base):
    with new_page(browser, base) as (page, errors):
        attempts = boot(page, base)
        out = js(page, undo_body(UNDO_STEPS))
        assert attempts == [] and errors == [], (attempts, errors)
    with new_page(browser, base) as (page, errors):
        attempts = boot(page, base)
        link = js(page, undo_body(LINK_STEPS))
        assert attempts == [] and errors == [], (attempts, errors)
    return out, link


def check_undo(out, link):
    assert out['d1']['token'] == {'kind': 'describe', 'uid': UID1, 'was': {'ai_desc': ''}, 'now': {'ai_desc': 'A model description'}}, out['d1']
    assert out['d1']['card'] == {'ai': True, 'desc': 'A model description'}, out['d1']
    assert out['afterSync'] == {'ai': True, 'desc': 'A model description'}, out['afterSync']
    # R5: the card prints its own text again, not the AI excerpt the published row holds
    assert out['afterUndo'] == {'ai': False, 'desc': 'The original caption 1', 'undone': True, 'note': ''}, out['afterUndo']
    assert out['journal'] == [{'op': 'edit', 'fields': {'ai_desc': ''}, 'was': {'ai_desc': 'A model description'}, 'plain': 'The original caption 1'}], out['journal']
    assert 'plain' not in out['wire'], out['wire']                                     # local only: never in a change file
    assert out['renumbered'] == {'id': 11, 'desc': 'The original caption 1', 'ai': False}, out['renumbered']
    assert out['d2']['token']['was'] == {'ai_desc': 'Old AI text'} and out['d2']['card'] == 'A newer AI text', out['d2']
    assert out['d2undo'] == {'desc': 'Old AI text', 'ai': True}, out['d2undo']
    assert out['refusedDescribe']['refused'].startswith('true: The description changed after Describe') and out['refusedDescribe']['added'] == 0, out['refusedDescribe']
    assert out['c1']['token'] == {'kind': 'categorize', 'uid': UID3, 'was': {'cat': 'INTERESTING', 'tags': ''}, 'now': {'cat': 'Art', 'tags': 'cat, tag'}}, out['c1']
    assert out['c1after']['entries'] == 0 and out['c1after']['token'] is None and not out['c1after']['undone'] and out['c1after']['cat'] == 'Recipes', out['c1after']
    assert 'changed after Auto-categorize' in out['c1after']['note'] and out['c1refused'] == out['c1after']['note'], out['c1after']
    assert 'no longer on the phone' in out['goneCard'], out['goneCard']
    assert out['failedWrite'] == {'failed': 'disk full', 'undone': False, 'undoing': False, 'tokenKept': True}, out['failedWrite']
    assert out['doubleTap'] == {'adds': 1, 'undone': True}, out['doubleTap']
    # a link saved on the phone: its own page text comes back
    assert link['before'] == {'id': link['before']['id'], 'desc': 'The page caption', 'ai': False} and link['before']['id'] < 0, link['before']
    assert link['described']['ai'] is True and link['described']['desc'] == 'A model description', link['described']
    assert link['undone'] == {'desc': 'The page caption', 'ai': False}, link['undone']
    assert '"plain"' not in link['wire'], link['wire']        # a link saved here has its page text in the overlay already


def apply_to_the_pc(out):
    """The change files the page produced, applied by the real server/intake.py on a temporary database."""
    with tempfile.TemporaryDirectory(prefix='phone-tools-undo-') as folder:
        db = Database(Path(folder) / 'content_manager.db')
        try:
            item = db.add_item({'url': 'https://example.com/1', 'description': 'The original caption 1', 'uid': UID1})
            doc1, doc2 = out['doc1'][0], out['doc2'][0]
            now = int(time.time() * 1000)
            applied = intake.apply(db, {**doc1, 'at': now})
            assert db.get_item(item)['ai_desc'] == 'A model description' and applied.edits == 1, applied
            # the Undo goes through when nothing changed on the PC meanwhile
            applied = intake.apply(db, {**doc2, 'at': now + 5})
            assert db.get_item(item)['ai_desc'] == '' and applied.edits == 1 and applied.kept_pc == 0, applied
            # the same Undo after the PC rewrote the description keeps the PC's text (the existing conflict rule)
            db.update_item(item, {'ai_desc': 'Rewritten on the PC'})
            applied = intake.apply(db, {**doc2, 'at': now + 10})
            assert db.get_item(item)['ai_desc'] == 'Rewritten on the PC' and applied.kept_pc == 1, applied
        finally:
            db.close()


def main():
    with mobile_browser() as (browser, base):
        with new_page(browser, base) as (page, errors):
            attempts = boot(page, base)
            phone_flow(page)
            assert attempts == [] and errors == [], (attempts, errors)
        for name, check in (('repeated_failure', repeated_failure), ('gone', gone_items), ('queued_identity', queued_identity)):
            with new_page(browser, base) as (page, errors):
                attempts = boot(page, base)
                check(page)
                assert attempts == [] and errors == [], (name, attempts, errors)
        check_pc(pc_scenarios(browser, base))
        out, link = undo_end_to_end(browser, base)
        check_undo(out, link)
        apply_to_the_pc(out)
        undo_storage(browser, base)
    print('PASS: Tools run engine (R1 retry/continue/next, R3 PC events in every order, R4 stop by id, R5 undo through the journal and intake); no /api request left the page')


if __name__ == '__main__':
    main()
