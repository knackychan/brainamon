// The Library cards' processing marks (Grid.svelte, mobile.css .m-cell.m-w-*): the phone's version of
// the desktop's working cards (lib/library-commands.ts cellState). An item waits (queued in a run), is
// worked on (one at a time per lane), then flashes done or failed for a moment. Lanes: `links` (page
// details of phone links, source/mirror.ts linkDetails), `pics` (the slow picture queue, fillPictures),
// `phone` (own-key Describe/Categorize, tools-run.svelte.ts) and `pc` (the PC's job, pc-jobs.svelte.ts).
// The Tools panel's runs (projects/phone-processing-flow) keep their skipped and failed marks (keepWork) until the
// panel closes after the run, or the lane's next run starts (clearKept).
import { t, type Key } from '../lib/i18n/index.ts'
import { SvelteMap } from 'svelte/reactivity'
import type { ItemState, ToolsUndo } from './tools'

export type WorkState = 'wait' | 'run' | 'done' | 'err' | 'skip'
export type WorkLane = 'links' | 'pics' | 'phone' | 'pc'
export interface WorkMark { st: WorkState; lane: WorkLane; tag: string; keep?: boolean }

// the tag above a card: the desktop's short job names (lib/events.svelte.ts JOB_SHORT, not imported:
// that module pulls the desktop's UI state into the phone bundle)
export const WORK_TAG: Record<string, string> = {
  thumb: 'FETCH', describe: 'DESCRIBE', categorize: 'SORT', analyze: 'ANALYZE', index: 'INDEX', note: 'NOTE', download: 'YT-DLP',
}

const TAG_WORDS: Record<string, Key> = {
  FETCH: 'library.work.fetch', DESCRIBE: 'library.work.describe', SORT: 'library.work.sort', ANALYZE: 'library.work.analyze',
  INDEX: 'library.work.index', NOTE: 'library.work.note', DONE: 'processing.work.tagDone', FAILED: 'processing.work.tagFailed', SKIPPED: 'processing.work.tagSkipped',
}
export const workLabel = (mark: WorkMark): string => mark.st === 'wait' ? t('library.work.waiting') : Object.hasOwn(TAG_WORDS, mark.tag) ? t(TAG_WORDS[mark.tag]) : mark.tag

export const work = new SvelteMap<number, WorkMark>()
export const pcResult = $state({ job: 0, kind: '', state: '', done: 0, skipped: 0, err: 0, detail: '' })
const flashT = new Map<number, number>()
const DONE_MS = 2800, ERR_MS = 3200

// One Tools run (projects/phone-processing-flow): the phone's own loop (tools-run.svelte.ts) or a PC job started or
// joined from the panel (pc-jobs.svelte.ts). It outlives the panel: closing the panel leaves it running, the Tools key
// carries its ring (ToolsRing.svelte). The run is one batch ledger: Retry and Continue work on its entries in place
// (a phone attempt, or a new PC job whose events fill the same entries); Next replaces it with the next batch.
//   scope    what the run was started on, frozen: reopening the panel on another screen never changes it
//   rest     the phone's targets after this batch (Next 25)
//   attempt  the items the current attempt works through (the bar's "3 of 5")
//   opts     a PC Analyze run's options as confirmed (a follow-up keeps them)
//   job      the PC job now filling the ledger; known: the total the server last listed; loaded: its items were read
//   prov     submitted ids the server has not confirmed yet; fresh: those that were not in the ledger before
//   counts   the PC's own counts for that job; unavailable: it no longer lists the job's items
//   undo     one single-item result's Undo token; why: a note about the run (Undo refused, Stop failed)
export interface RunItem { id: number; uid?: string; title: string; st: ItemState; why: string }
export interface RunScope { item: boolean; heading: string; count: number }
export interface PcJob { id: number; kind: string; label: string; state: string; total: number; done: number }
export interface Run {
  lane: 'phone' | 'pc'; kind: string; label: string; job: number; rerun: boolean; joined: boolean; scope: RunScope
  items: RunItem[]; rest: RunItem[]; ended: boolean; stopping: boolean; stopped: boolean
  total: number; counts: { done: number; skip: number; err: number } | null
  attempt: { total: number; done: number }; text: string; opts: Record<string, unknown> | null
  known: number; loaded: boolean; unavailable: boolean; prov: number[]; fresh: number[]; sync: number
  undo: ToolsUndo | null; undone: boolean; undoing: boolean; why: string
}
// runs.pcJob: the PC's job running now, whoever started it (the "The PC is busy" box when no run of ours is shown)
export const runs = $state<{ phone: Run | null; pc: Run | null; pcJob: PcJob | null }>({ phone: null, pc: null, pcJob: null })

export function newRun(lane: 'phone' | 'pc', kind: string, items: RunItem[], o: Partial<Run> = {}): Run {
  return { lane, kind, label: '', job: 0, rerun: false, joined: false, scope: { item: false, heading: 'Items', count: items.length },
    items, rest: [], ended: false, stopping: false, stopped: false, total: items.length, counts: null,
    attempt: { total: items.length, done: 0 }, text: '', opts: null, known: 0, loaded: false, unavailable: false, prov: [], fresh: [], sync: 0,
    undo: null, undone: false, undoing: false, why: '', ...o }
}

function put(id: number, mark: WorkMark) {
  clearTimeout(flashT.get(id)); flashT.delete(id)
  work.set(id, mark)
}

// the ids a lane's run will work through: any earlier wait of that lane is replaced (unless `replace`
// is false: one more item joins)
export function queueWork(lane: WorkLane, tag: string, ids: number[], replace = true) {
  if (replace) clearWaits(lane)
  for (const id of ids) {
    const m = work.get(id)
    if (m?.st !== 'run' || m.lane === lane) put(id, { st: 'wait', lane, tag })
  }
}

// one item is worked on; `alone` (the phone's lanes) ends the lane's previous one. The PC's job can
// work on several at once (an index batch), so it passes false.
export function startWork(lane: WorkLane, tag: string, id: number, alone = true) {
  if (alone) for (const [i, m] of work) if (m.lane === lane && m.st === 'run' && i !== id) work.delete(i)
  put(id, { st: 'run', lane, tag })
}

// done or failed: shown for a moment, then the mark goes (unless a new run took the item meanwhile)
export function endWork(id: number, ok: boolean) {
  const m = work.get(id)
  if (!m) return
  const st: WorkState = ok ? 'done' : 'err'
  put(id, { ...m, st, tag: ok ? 'DONE' : 'FAILED' })
  flashT.set(id, window.setTimeout(() => { if (work.get(id)?.st === st) work.delete(id); flashT.delete(id) }, ok ? DONE_MS : ERR_MS))
}

// a Tools run's skipped or failed item: its mark stays (no flash) until clearKept
export function keepWork(id: number, st: 'skip' | 'err', lane?: WorkLane) {
  const m = work.get(id)
  const at = lane ?? m?.lane
  if (!at) return
  put(id, { st, lane: at, tag: st === 'skip' ? 'SKIPPED' : 'FAILED', keep: true })
}

export function clearKept(lane: WorkLane) {
  for (const [id, m] of work) if (m.lane === lane && m.keep) work.delete(id)
}

// an item the run skipped (nothing found, stopped): its mark goes without a flash
export function dropWork(id: number) {
  const m = work.get(id)
  if (m && (m.st === 'wait' || m.st === 'run')) work.delete(id)
}

export function clearWaits(lane: WorkLane) {
  for (const [id, m] of work) if (m.lane === lane && m.st === 'wait') work.delete(id)
}

// a lane paused (the site asked to slow down): nothing is worked on, the rest keep waiting
export function clearRun(lane: WorkLane) {
  for (const [id, m] of work) if (m.lane === lane && m.st === 'run') work.delete(id)
}

// a lane's run ended (finished, stopped, failed): its waiting and working marks go, flashes and kept marks stay
export function endLane(lane: WorkLane) {
  for (const [id, m] of work) if (m.lane === lane && (m.st === 'wait' || m.st === 'run')) work.delete(id)
}
