// The PC's jobs as this phone sees them (projects/phone-processing-flow, plans/00-review-repairs.md R3): the Library
// cards' marks (work.svelte.ts, lane `pc`) for whatever job the PC runs, and the Tools panel's ledger (runs.pc) for a
// job started or joined from this phone's panel. Fed by the PC's SSE events (source/desktop.ts watchJob):
//   job       the PC's current and last job (a snapshot, on every step and at the end)
//   hello     the same, first on every (re)connect: what happened while the page was away
//   job_item  one item of a job changed state
// Events and the POST /api/jobs answer arrive in any order (the server starts the job's thread before it answers, so a
// job can end first). So every event goes into a small book of the latest jobs, keyed by job id; a ledger is built
// from the book and from /api/jobs/progress, and an event that arrived after a progress request began wins over that
// response. The ledger belongs to the run started here; another job only sets `runs.pcJob` (the busy box) and its own
// card marks, and never replaces the ledger or its kept marks. Imports nothing of the phone's state (a cycle).
import { t } from '../lib/i18n/index.ts'
import { api } from '../lib/api'
import { NOT_NEEDED, type ItemState } from './tools'
import { clearKept, dropWork, endLane, endWork, keepWork, newRun, pcResult, queueWork, runs, startWork, work, WORK_TAG, type Run, type RunItem, type RunScope } from './work.svelte'

export interface Snap { id: number; kind: string; label?: string; state: string; total?: number; done: number; skipped?: number; err: number; detail?: string; options?: Record<string, unknown> }
interface Prog { id: number; state: string; title?: string; error?: string; step?: string }
interface Rec { st: ItemState; why: string; n: number }
interface Book { snap: Snap | null; items: Map<number, Rec> }

const ST: Record<string, ItemState> = { queued: 'wait', working: 'run', done: 'done', skipped: 'skip', error: 'err' }
const terminal = (s?: Snap | null) => !!s && (s.state === 'finished' || s.state === 'stopped')
const settled = (st: ItemState) => st === 'done' || st === 'skip' || st === 'err'
const count = (j: Snap) => j.done + (j.skipped ?? 0) + j.err

// set by tools-run.svelte.ts: a title for an item the PC listed without one, and what happens when a ledger ends
export const pcHooks: { title?: (id: number) => string; ended?: (run: Run) => unknown } = {}

const book = new Map<number, Book>()
let seq = 0, maxId = 0, obs = 0, tag = ''
const flight = new Set<Run>(), again = new Set<Run>()

function bookOf(id: number): Book {
  let b = book.get(id)
  if (!b) {
    b = { snap: null, items: new Map() }
    book.set(id, b)
    while (book.size > 6) book.delete(Math.min(...book.keys()))
  }
  return b
}
// a later snapshot replaces an earlier one, but a job that ended never goes back to running
function remember(s: Snap) {
  const b = bookOf(s.id)
  if (!b.snap || !terminal(b.snap) || terminal(s)) b.snap = s
}
const reason = (st: ItemState, p: { error?: string; step?: string }) => (st === 'err' ? p.error ?? '' : st === 'skip' ? p.step ?? '' : '')

function itemFor(run: Run, id: number): RunItem {
  let it = run.items.find(i => i.id === id)
  if (!it) { run.items.push({ id, title: pcHooks.title?.(id) || `No.${id}`, st: 'wait', why: '' }); it = run.items[run.items.length - 1] }
  return it
}
// an item never goes back from a result to waiting or working
function put(it: RunItem, st: ItemState, why: string) {
  if (settled(it.st) && !settled(st)) return
  it.st = st
  if (st !== 'run') it.why = why
}

// a failed or skipped item of the ledger keeps its card mark whatever another job does with that card
const free = (id: number) => !work.get(id)?.keep

// the cards of a ledger: its failed and skipped items keep their mark, the rest of an active job waits or works
function markFromRun(run: Run) {
  const t = WORK_TAG[run.kind] ?? run.kind.toUpperCase()
  for (const it of run.items) {
    if (it.st === 'err') keepWork(it.id, 'err', 'pc')
    else if (it.st === 'skip') keepWork(it.id, 'skip', 'pc')
    else if (!run.ended && it.st === 'wait') queueWork('pc', t, [it.id], false)
    else if (!run.ended && it.st === 'run') startWork('pc', t, it.id, false)
  }
}

// ── the progress read ─────────────────────────────────────────────────────────────────────────────────────────────
// at: the event number when the request began. An event numbered above it came after the PC answered, so it wins.
function merge(run: Run, p: { job: Snap; items: Prog[] }, at: number) {
  const bk = bookOf(run.job), seen = new Set<number>()
  for (const s of p.items) {
    seen.add(s.id)
    const it = itemFor(run, s.id)
    let st: ItemState = ST[s.state] ?? 'wait', why = reason(st, s)
    const ev = bk.items.get(s.id)
    if (ev && ev.n > at) { st = ev.st; why = ev.why }
    put(it, st, why)
    if (s.title) it.title = s.title
  }
  // items an event added after the request began (a joined Analyze takes more) stay
  for (const [id, ev] of bk.items) if (!seen.has(id) && ev.n > at) put(itemFor(run, id), ev.st, ev.why)
  // submitted ids the PC did not take: new ones were never real work; an earlier entry no longer needs this step
  for (const id of run.prov) {
    if (seen.has(id) || bk.items.has(id)) continue
    const i = run.items.findIndex(x => x.id === id)
    if (i < 0) continue
    if (run.fresh.includes(id)) run.items.splice(i, 1)
    else { run.items[i].st = 'skip'; run.items[i].why = t('processing.error.notNeeded') }
  }
  run.prov = []; run.fresh = []
  run.known = p.job.total ?? p.items.length
  run.total = p.job.total ?? run.total
  run.loaded = true
  markFromRun(run)
}

function settle(run: Run, snap: Snap | null) {
  if (run.ended) return
  run.counts = snap ? { done: snap.done, skip: snap.skipped ?? 0, err: snap.err } : null
  if (snap?.total !== undefined) run.total = snap.total
  for (const it of run.items) if (it.st === 'run') it.st = 'wait'
  const waiting = run.items.some(i => i.st === 'wait')
  run.stopped = snap?.state === 'stopped' || (run.stopped && waiting)
  // rows the PC never listed for this job and events never covered cannot be reported
  run.unavailable = !run.loaded && (waiting || run.items.length < run.total || !run.items.length)
  run.ended = true; run.stopping = false
  markFromRun(run)
  void pcHooks.ended?.(run)
}

// the PC reports another job: ours is over and its rows are gone; what the events and the last snapshot said stays
function lost(run: Run) {
  const snap = bookOf(run.job).snap
  // An earlier running snapshot does not prove which waiting items finished while disconnected.
  run.loaded = false
  settle(run, terminal(snap) ? snap : null)
}

export async function reconcile(run: Run): Promise<void> {
  if (flight.has(run)) { again.add(run); return }
  flight.add(run)
  try {
    do {
      again.delete(run)
      const job = run.job, mine = ++run.sync, at = seq
      let p: { job: Snap | null; items: Prog[] }
      try { p = await api.get<{ job: Snap | null; items: Prog[] }>('/api/jobs/progress') } catch { break }    // the next event tries again
      if (runs.pc !== run || run.job !== job || run.sync !== mine) continue                                    // a newer attempt took over
      if (p.job && p.job.id === job) {
        merge(run, p as { job: Snap; items: Prog[] }, at)
        remember(p.job)
        if (terminal(p.job)) settle(run, p.job)
      } else lost(run)
    } while (again.has(run))
  } finally { flight.delete(run) }
}

// ── the answer to POST /api/jobs ──────────────────────────────────────────────────────────────────────────────────
export interface Claim {
  snap: Snap; kind: string; ids: number[]; rerun: boolean; opts: Record<string, unknown> | null; scope: RunScope
  joined?: boolean; into?: Run | null; titleOf?: (id: number) => string; uidOf?: (id: number) => string | undefined
}
export function claimPcJob(c: Claim): Run {
  remember(c.snap)
  const mk = (id: number): RunItem => ({ id, uid: c.uidOf?.(id), title: c.titleOf?.(id) || `No.${id}`, st: 'wait', why: '' })
  const own = runs.pc
  let run: Run
  if (c.into && own === c.into) {
    // Retry or Continue: the same ledger, a new job; its events fill the entries in place
    run = c.into
    for (const id of c.ids) {
      const it = run.items.find(i => i.id === id)
      if (it) { it.st = 'wait'; it.why = '' } else { run.items.push(mk(id)); run.fresh.push(id) }
    }
    run.prov = [...c.ids]; run.fresh = run.fresh.filter(id => c.ids.includes(id))
    run.attempt = { total: c.ids.length, done: 0 }
    run.job = c.snap.id; run.total = c.snap.total ?? c.ids.length; run.counts = null
    run.joined = !!c.joined
    run.ended = false; run.stopping = false; run.unavailable = false; run.loaded = false; run.known = 0; run.sync++
  } else if (own && !own.ended && own.job === c.snap.id) {
    // an Analyze of ours that is running takes more items
    run = own
    for (const id of c.ids) if (!run.items.some(i => i.id === id)) { run.items.push(mk(id)); run.fresh.push(id) }
    run.prov = [...new Set([...run.prov, ...c.ids])]
    run.loaded = false; run.sync++
  } else {
    clearKept('pc')
    runs.pc = newRun('pc', c.kind, c.ids.map(mk), {
      job: c.snap.id, label: c.snap.label ?? '', rerun: c.rerun, joined: !!c.joined, scope: c.scope, opts: c.opts,
      total: c.snap.total ?? c.ids.length, prov: [...c.ids], fresh: [...c.ids],
    })
    run = runs.pc!          // the reactive copy: changes to the object newRun returned would not be seen
  }
  tag = WORK_TAG[run.kind] ?? run.kind.toUpperCase()
  if (c.snap.options) run.opts = { ...c.snap.options }
  // what the events said before this answer came
  for (const [id, r] of bookOf(c.snap.id).items) { const it = itemFor(run, id); put(it, r.st, r.why) }
  markFromRun(run)
  void reconcile(run)
  return run
}

// ── events ────────────────────────────────────────────────────────────────────────────────────────────────────────
// the first Describe-class snapshot sets the old "Last PC Describe" line the Tools panel and its check read
function onJobs(cur?: Snap | null, last?: Snap | null) {
  if (last?.kind === 'describe') Object.assign(pcResult, { job: last.id, kind: last.kind, state: last.state, done: last.done, skipped: last.skipped ?? 0, err: last.err, detail: last.detail ?? '' })
  const top = cur?.id ?? last?.id ?? 0
  if (top && top < maxId) { book.clear(); obs = 0; maxId = 0; endLane('pc') }       // the PC started again: its job numbers began from 1
  if (top) maxId = Math.max(maxId, top)
  if (last) remember(last)
  if (cur) remember(cur)
  if (!cur) {
    if (obs) endLane('pc')
    obs = 0; runs.pcJob = null
  } else {
    runs.pcJob = { id: cur.id, kind: cur.kind, label: cur.label ?? cur.kind, state: cur.state, total: cur.total ?? 0, done: count(cur) }
    if (cur.id !== obs) {
      endLane('pc'); obs = cur.id; tag = WORK_TAG[cur.kind] ?? cur.kind.toUpperCase()
      if (!(runs.pc && !runs.pc.ended && runs.pc.job === cur.id)) void marksFromProgress(cur.id)
    }
  }
  const run = runs.pc
  if (run && !run.ended) track(run, cur, last)
}

function track(run: Run, cur?: Snap | null, last?: Snap | null) {
  const mine = cur?.id === run.job ? cur : last?.id === run.job ? last : bookOf(run.job).snap
  if (mine) {
    run.counts = { done: mine.done, skip: mine.skipped ?? 0, err: mine.err }
    if (mine.label) run.label = mine.label
  }
  const over = terminal(mine) && cur?.id !== run.job
  const replaced = !!cur && cur.id !== run.job
  const absent = !cur && last?.id !== run.job
  const grew = cur?.id === run.job && run.loaded && cur.total !== undefined && cur.total !== run.known
  if (over || replaced || absent || grew || !run.loaded) void reconcile(run)
  else if (cur?.id === run.job) run.total = cur.total ?? run.total
}

async function marksFromProgress(id: number) {
  try {
    const p = await api.get<{ job: Snap | null; items: Prog[] }>('/api/jobs/progress')
    if (!p.job || p.job.id !== id || id !== obs || terminal(p.job)) return
    if (runs.pc && !runs.pc.ended && runs.pc.job === id) return
    queueWork('pc', tag, p.items.filter(i => i.state === 'queued' && free(i.id)).map(i => i.id))
    for (const i of p.items) if (i.state === 'working' && free(i.id)) startWork('pc', tag, i.id, false)
  } catch { /* the next job_item marks the next card */ }
}

function onItem(d: { job: number; id: number; state: string; error?: string; step?: string }) {
  const st = ST[d.state]
  if (!st) return
  const why = reason(st, d)
  bookOf(d.job).items.set(d.id, { st, why, n: ++seq })
  const run = runs.pc
  if (run && run.job === d.job && !run.ended) {
    put(itemFor(run, d.id), st, why)
    const t = WORK_TAG[run.kind] ?? run.kind.toUpperCase()
    if (st === 'run') startWork('pc', t, d.id, false)
    else if (st === 'done') endWork(d.id, true)
    else if (st === 'err') keepWork(d.id, 'err', 'pc')
    else if (st === 'skip') keepWork(d.id, 'skip', 'pc')
    else queueWork('pc', t, [d.id], false)
    return
  }
  if (d.job !== obs || !free(d.id)) return
  if (st === 'run') startWork('pc', tag, d.id, false)
  else if (st === 'done') endWork(d.id, true)
  else if (st === 'err') endWork(d.id, false)
  else if (st === 'skip') dropWork(d.id)
  else queueWork('pc', tag, [d.id], false)
}

export function watchPcJobs(es: EventTarget) {
  const data = (e: Event) => JSON.parse((e as MessageEvent).data)
  es.addEventListener('job', e => {
    try { const d = data(e) as { current?: Snap | null; last?: Snap | null }; onJobs(d.current, d.last) } catch { /* ignore */ }
  })
  // a (re)connect: events may have been missed, so a ledger that is not over is read again
  es.addEventListener('hello', e => {
    try {
      const jobs = (data(e) as { jobs?: { current?: Snap | null; last?: Snap | null } }).jobs
      onJobs(jobs?.current, jobs?.last)
      const run = runs.pc
      if (run && !run.ended) void reconcile(run)
    } catch { /* ignore */ }
  })
  es.addEventListener('job_item', e => {
    try { onItem(data(e)) } catch { /* ignore */ }
  })
}
