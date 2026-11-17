// Wiskit Deep research (motion language D4, projects/motion-language/plans/05-d4-wiskit.md): one answer's tool
// calls as steps, and the items read_items opens as source rows that read, then show READ or NOT USED. Fed by
// the `tool` events of POST /api/ask (knowledge/ask_core.py deep_answer). Pure and immutable, like
// scrape-tray.ts: ask.svelte.ts keeps the state on the message, tests/test_motion_research_js.py runs it in
// Node. Nothing here is saved; a chat opened later shows today's answer without it.
import { READ_MS, arrivalDelay } from './motion/motion.ts'

export type StepState = 'run' | 'ok' | 'err'
export type RowState = 'reading' | 'read' | 'unused'
export interface ResearchStep { n: number; name: string; label: string; q: string; state: StepState; hits: number | null }
// `d`: the row's arrival delay within its call; `at`: when its call started (performance.now); `got`: its call delivered it
export interface ResearchRow { id: number; n: number; d: number; at: number; state: RowState; got: boolean }
// `read`: how many rows were read, set when the answer is done (null while it runs, and after Stop or an error)
export interface Research { steps: ResearchStep[]; rows: ResearchRow[]; read: number | null }
export interface ToolEvent { phase: 'start' | 'done'; n: number; name: string; line?: string; q?: string; ids?: number[]; ok?: boolean }

export const VERB: Record<string, string> = {
  search_library: 'search library', search_notes: 'search notes', find_topics: 'find topics', topic_items: 'browse topic',
  related_items: 'related items', find_resources: 'find resources', read_note: 'read note', list_canvases: 'list canvases',
  read_canvas: 'read canvas', list_frames: 'list frames', read_items: 'read sources',
}
// the steps that show their hits: these tools list items, one [id N] line each
export const COUNTED = new Set(['search_library', 'topic_items', 'related_items'])
export const ROWS_PER_CALL = 8
export const ROWS_MAX = 24
export const READ_DELAY_MS = 200

export const emptyResearch = (): Research => ({ steps: [], rows: [], read: null })
const isId = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) > 0
export const readAt = (row: ResearchRow): number => row.at + row.d + READ_DELAY_MS + READ_MS

// one `tool` event; `now`: performance.now(); `known`: the ids the library has (rows only for those)
export function onTool(r: Research, e: ToolEvent, now: number, known: (id: number) => boolean): Research {
  if (!e || r.read !== null || !Number.isSafeInteger(e.n) || typeof e.name !== 'string') return r
  const step = r.steps.find(s => s.n === e.n)
  if (e.phase === 'start') {
    if (step || e.name.startsWith('propose_')) return r
    const q = typeof e.q === 'string' ? e.q.slice(0, 80) : ''
    const steps = [...r.steps, { n: e.n, name: e.name, label: VERB[e.name] ?? e.name.replace(/_/g, ' '), q, state: 'run' as const, hits: null }]
    if (e.name !== 'read_items' || !Array.isArray(e.ids)) return { ...r, steps }
    const have = new Set(r.rows.map(x => x.id)), room = Math.min(ROWS_PER_CALL, ROWS_MAX - r.rows.length), ids: number[] = []
    for (const id of e.ids) {
      if (ids.length >= room) break
      if (isId(id) && !have.has(id) && known(id)) { have.add(id); ids.push(id) }
    }
    return { ...r, steps, rows: [...r.rows, ...ids.map((id, i) => ({ id, n: e.n, d: arrivalDelay(i), at: now, state: 'reading' as const, got: false }))] }
  }
  if (e.phase !== 'done' || !step || step.state !== 'run') return r
  const ok = e.ok === true, got = new Set(ok && Array.isArray(e.ids) ? e.ids.filter(isId) : [])
  return {
    ...r,
    steps: r.steps.map(s => s === step ? { ...s, state: ok ? 'ok' as const : 'err' as const, hits: ok && COUNTED.has(s.name) ? got.size : null } : s),
    rows: r.rows.map(x => x.n !== e.n || x.state !== 'reading' ? x : got.has(x.id) ? { ...x, got: true } : { ...x, state: 'unused' as const }),
  }
}

// rows their call delivered read once their fill ran; `now` Infinity reads them at once (motion off, the end).
// `wait`: the ms until the next row reads, -1 when none waits.
export function settle(r: Research, now: number): { research: Research; wait: number } {
  let wait = Infinity, changed = false
  const rows = r.rows.map(x => {
    if (x.state !== 'reading' || !x.got) return x
    const due = readAt(x)
    if (now >= due) { changed = true; return { ...x, state: 'read' as const } }
    wait = Math.min(wait, due - now)
    return x
  })
  return { research: changed ? { ...r, rows } : r, wait: wait === Infinity ? -1 : Math.ceil(wait) }
}

// the answer ended without a done event for some calls: they close as `state`, their rows were not delivered
export function closeResearch(r: Research, state: 'ok' | 'err'): Research {
  const open = new Set(r.steps.filter(s => s.state === 'run').map(s => s.n))
  const closed = open.size ? {
    ...r,
    steps: r.steps.map(s => open.has(s.n) ? { ...s, state } : s),
    rows: r.rows.map(x => x.state === 'reading' && open.has(x.n) ? { ...x, state: 'unused' as const } : x),
  } : r
  return settle(closed, Infinity).research
}

// the answer is done: what was read and not cited was not used
export function researchDone(r: Research, cited: number[]): Research {
  if (r.read !== null) return r
  const c = closeResearch(r, 'ok'), keep = new Set(cited)
  return { ...c, read: c.rows.filter(x => x.state === 'read').length,
    rows: c.rows.map(x => x.state === 'read' && !keep.has(x.id) ? { ...x, state: 'unused' as const } : x) }
}
