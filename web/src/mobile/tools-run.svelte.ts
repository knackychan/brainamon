// The Tools panel's runs (projects/phone-processing-flow, decision 3): preview fetching, the phone's own-key Describe and
// Auto-categorize loop, and the start, stop and follow-ups of a PC job, outside the panel so that closing it leaves the
// run going (ToolsRing.svelte draws its ring on the Tools key). The state is work.svelte.ts `runs`; the PC's side is
// filled by its job events (pc-jobs.svelte.ts). A failure never ends a run: the item is marked and the next one starts.
// The words are tools.ts.
//
// One run is one batch ledger. Retry works on its failed entries in place and Continue on its waiting ones (nothing
// else is run again, nothing waiting is dropped); Next replaces it with the next batch. A follow-up asks like a first
// start (Processing.svelte: followPlan, then the same confirm line, then startFollow). Runs last as long as the app
// does: nothing restarts after the app is closed.
import { t } from '../lib/i18n/index.ts'
import { captureError } from './capture-words.ts'
import { api } from '../lib/api'
import { claimPcJob, pcHooks, reconcile, type Snap } from './pc-jobs.svelte'
import { patchRows, phone, refresh, replaceRow, source } from './state.svelte'
import { beginLanguageWork, registerLanguageCheck } from './language-switch.ts'
import { GONE, NOTHING_TO_DESCRIBE, PHONE_LIMIT, UndoRefused, type Act, type StepKind } from './tools'
import { clearKept, endLane, endWork, keepWork, newRun, queueWork, runs, startWork, WORK_TAG, type Run, type RunItem, type RunScope } from './work.svelte'

registerLanguageCheck(() => runs.phone || runs.pc ? 'settings.language.unsavedProcessing' : null)

const titleOf = (id: number) => { const r = phone.byId.get(id); return r?.title || r?.url || `No.${id}` }
const uidOf = (id: number) => phone.byId.get(id)?.uid
const itemsOf = (ids: number[]): RunItem[] => ids.map(id => ({ id, uid: uidOf(id), title: titleOf(id), st: 'wait' as const, why: '' }))

export const lane = (): 'phone' | 'pc' => (source.kind === 'desktop' ? 'pc' : 'phone')
export const current = (): Run | null => runs[lane()]
export const running = (): boolean => !!current() && !current()!.ended
// A run stays reachable even when the selection or filter is empty.
export const hasRun = (): boolean => !!current()

// the screen showing the item or the list refreshes itself when a run ends or is undone; the screen registers on
// mount and unregisters on destroy, so nothing here holds a closure of a screen that is gone
let screenDone: (() => unknown) | null = null
export function onToolsDone(fn: () => unknown): () => void {
  screenDone = fn
  return () => { if (screenDone === fn) screenDone = null }
}
async function finished() {
  await refresh().catch(() => {})
  try { await screenDone?.() } catch { /* the panel shows the run's own result */ }
}
pcHooks.title = titleOf
pcHooks.ended = () => finished()

// a ledger entry's card as the phone has it now: a link saved on the phone gets a new numeric id when the PC numbers
// it, so an entry with a uid follows that uid; no card means the item is gone
function live(it: RunItem) {
  const r = phone.byId.get(it.id)
  if (r && (!it.uid || r.uid === it.uid)) return r
  if (it.uid) {
    const m = phone.rows.find(x => x.uid === it.uid)
    if (m) { it.id = m.id; return m }
    return undefined
  }
  return r
}

// ── the phone's own loop ──────────────────────────────────────────────────────────────────────────────────────────
export interface PhoneStart { rest?: number[]; rerun?: boolean; scope: RunScope }
export function runPhone(kind: 'thumb' | 'describe' | 'categorize', ids: number[], o: PhoneStart): Promise<void> | undefined {
  if (!ids.length || running()) return undefined
  clearKept('phone')
  runs.phone = newRun('phone', kind, itemsOf(ids), { rest: itemsOf(o.rest ?? []), rerun: !!o.rerun, scope: o.scope })
  return drive(runs.phone!, ids)       // the reactive copy, not the object newRun returned
}

// works through these entries of the ledger in order. An attempt on a subset (Retry, Continue) leaves the other
// entries as they were; an entry waits as it was until its turn.
async function drive(run: Run, ids: number[]) {
  const kind = run.kind as 'thumb' | 'describe' | 'categorize'
  const tag = WORK_TAG[kind]
  const single = run.scope.item && run.items.length === 1
  run.ended = false; run.stopping = false; run.why = ''
  const todo: RunItem[] = []
  for (const id of ids) {
    const it = run.items.find(i => i.id === id)
    if (!it) continue
    if (!live(it)) { it.st = 'skip'; it.why = t('processing.error.gone'); keepWork(it.id, 'skip', 'phone'); continue }
    todo.push(it)
  }
  run.attempt = { total: todo.length, done: 0 }
  queueWork('phone', tag, todo.map(i => i.id))
  const finishLanguageWork = beginLanguageWork()
  try {
    for (const it of todo) {
      if (run.stopping) break
      // Sync or deletion can change a waiting card while the previous provider call is in flight.
      if (!live(it)) { it.st = 'skip'; it.why = t('processing.error.gone'); keepWork(it.id, 'skip', 'phone'); run.attempt.done++; continue }
      it.st = 'run'; it.why = ''
      startWork('phone', tag, it.id)
      try {
        if (kind === 'thumb') {
          const updated = await source.fetchInfo!(it.id, id => patchRows([id]))
          if (!updated) { it.st = 'skip'; it.why = t('library.fetchMissing'); keepWork(it.id, 'skip', 'phone'); run.attempt.done++; continue }
          replaceRow(updated)
        } else if (kind === 'describe') {
          const text = await source.describe!(it.id, t => { if (single) run.undo = t })
          if (text === null) { it.st = 'skip'; it.why = t('processing.error.noText'); keepWork(it.id, 'skip', 'phone'); run.attempt.done++; continue }
          run.text = text
          const updated = await source.rowsByIds([it.id])
          if (updated[0]) replaceRow(updated[0])
        } else {
          const before = phone.byId.get(it.id)
          const updated = await source.categorize!(it.id, phone.cats.map(c => c.name))
          replaceRow(updated)
          run.text = updated.tags ? `${updated.cat} · ${updated.tags}` : updated.cat
          if (single && before?.uid) run.undo = { kind: 'categorize', uid: before.uid, was: { cat: before.cat, tags: before.tags }, now: { cat: updated.cat, tags: updated.tags } }
        }
        it.st = 'done'
        endWork(it.id, true)
      } catch (e) {
        it.st = 'err'; it.why = captureError(e) || t('processing.error.failed')
        keepWork(it.id, 'err', 'phone')
      }
      run.attempt.done++
    }
  } finally {
    endLane('phone')
    run.stopped = run.items.some(i => i.st === 'wait') && (run.stopping || run.stopped)
    run.stopping = false
    run.ended = true
    try { await finished() } finally { finishLanguageWork() }
  }
}

// ── a PC job ──────────────────────────────────────────────────────────────────────────────────────────────────────
export interface PcStart { rerun?: boolean; opts?: Record<string, unknown> | null; scope: RunScope; joined?: boolean; into?: Run | null }
let pcStarting = false
// POST /api/jobs; the job's items, progress and end arrive as its events (pc-jobs.svelte.ts). Its answer may come after
// the events, even after the job ended: the ledger is built from both. A failed start changes nothing.
export async function runPc(kind: StepKind, ids: number[], o: PcStart): Promise<void> {
  if (pcStarting) return
  const cur = runs.pc
  if (cur && !cur.ended && !(kind === 'analyze' && cur.kind === 'analyze')) throw Object.assign(new Error('A PC step started here is still running.'), { displayKey: 'common.error.pcStepRunning' })
  const finishLanguageWork = beginLanguageWork()
  pcStarting = true
  try {
    const snap = await api.post<Snap>('/api/jobs', { kind, ids, force: !!o.rerun, opts: o.opts ?? {} })
    claimPcJob({ snap, kind, ids, rerun: !!o.rerun, opts: o.opts ?? null, scope: o.scope, joined: o.joined, into: o.into ?? null, titleOf, uidOf })
  } finally { pcStarting = false; finishLanguageWork() }
}

// Stop: the phone's loop ends after the item it is on; a PC job is stopped by its id, so a job that ended meanwhile
// is left alone (the PC refuses an id that is not the running one). A refusal or a failed request leaves Stop usable.
export async function stopRun() {
  const run = current()
  if (!run || run.ended || run.stopping) return
  run.stopping = true; run.why = ''
  if (run.lane !== 'pc') return
  const finishLanguageWork = beginLanguageWork()
  const job = run.job
  try { await api.post('/api/jobs/stop', { id: job }) }
  catch (e) {
    if (runs.pc === run && run.job === job && !run.ended) run.stopping = false
    void reconcile(run)
    throw e
  } finally { finishLanguageWork() }
}

// ── Retry, Continue, Next ─────────────────────────────────────────────────────────────────────────────────────────
export interface Plan {
  act: Act; kind: StepKind; lane: 'phone' | 'pc'; ids: number[]; rest: RunItem[]; gone: number[]; items?: RunItem[]
  rerun: boolean; opts: Record<string, unknown> | null; scope: RunScope
}
// what the finished bar's key would run: the failed entries (Retry), the waiting ones (Continue) or the next batch of
// the rest (Next). Nothing is changed; null when there is nothing to do.
export function followPlan(act: Act): Plan | null {
  const run = current()
  if (!run?.ended || run.unavailable) return null
  const base = { act, kind: run.kind as StepKind, lane: run.lane, rerun: run.rerun, opts: run.opts ? { ...run.opts } : null, scope: run.scope }
  if (run.lane === 'pc') {
    const ids = run.items.filter(i => i.st === (act === 'retry' ? 'err' : 'wait')).map(i => i.id)
    return act !== 'next' && ids.length ? { ...base, ids, rest: [], gone: [] } : null
  }
  if (act === 'next') {
    const entries = run.rest.map(it => ({ ...it })), kept: RunItem[] = [], gone: RunItem[] = []
    for (const it of entries) (live(it) ? kept : gone).push(it)
    const chosen = kept.slice(0, PHONE_LIMIT)
    return entries.length ? { ...base, ids: chosen.map(it => it.id), rest: kept.slice(PHONE_LIMIT),
      gone: gone.map(it => it.id), items: [...chosen, ...gone.map(it => ({ ...it, st: 'skip' as const, why: t('processing.error.gone') }))] } : null
  }
  const ids = run.items.filter(i => i.st === (act === 'retry' ? 'err' : 'wait')).filter(i => !!live(i)).map(i => i.id)
  const dropped = run.items.filter(i => i.st === (act === 'retry' ? 'err' : 'wait') && !ids.includes(i.id)).map(i => i.id)
  return ids.length || dropped.length ? { ...base, ids, rest: run.rest, gone: dropped } : null
}

export async function startFollow(plan: Plan): Promise<void> {
  const run = current()
  if (!run?.ended || running()) return
  if (plan.lane === 'pc') return runPc(plan.kind, plan.ids, { rerun: plan.rerun, opts: plan.opts, scope: plan.scope, into: run })
  for (const id of plan.gone) {
    const it = run.items.find(i => i.id === id)
    if (it) { it.st = 'skip'; it.why = t('processing.error.gone'); keepWork(it.id, 'skip', 'phone') }
  }
  if (plan.act !== 'next') { await drive(run, plan.ids); return }
  clearKept('phone')
  const items = plan.items!
  runs.phone = newRun('phone', plan.kind, items, { rest: plan.rest, rerun: plan.rerun, scope: plan.scope })
  for (const it of items) if (it.st === 'skip') keepWork(it.id, 'skip', 'phone')
  return drive(runs.phone!, plan.ids)
}

// Done, or the panel closed after the run ended: the ledger goes, so do the cards' kept marks (decision 6)
export function dismiss(l: 'phone' | 'pc' = lane()) {
  if (!runs[l]?.ended) return
  runs[l] = null
  clearKept(l)
}

// Undo on one item done on the phone (decision 5). The source puts back the description or the collection and tags
// only if the card still holds what the run wrote; a refusal writes nothing and takes the token away, a failed save
// leaves it for another try. Two taps run one Undo.
export async function undo() {
  const run = runs.phone
  if (!run?.ended || run.undone || run.undoing || !run.undo) return
  const finishLanguageWork = beginLanguageWork()
  run.undoing = true
  try {
    const row = await source.undoTool!($state.snapshot(run.undo) as NonNullable<Run['undo']>)
    replaceRow(row)
    run.undone = true
    try { await screenDone?.() } catch { /* the panel already shows the undo */ }
  } catch (e) {
    if (e instanceof UndoRefused) { run.undo = null; run.why = e.message }
    throw e
  } finally { run.undoing = false; finishLanguageWork() }
}
