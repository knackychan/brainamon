// The Tools panel's words and rules (projects/phone-processing-flow, option C: step rows, a run bar, a grouped
// ledger). Pure: no Svelte, no source, so tests/test_phone_tools.py runs it under Node. Processing.svelte draws them,
// tools-run.svelte.ts runs them; the labels and the replace lines stay in lib/processing.ts (PROCESS_ACTIONS).
export type StepKind = 'thumb' | 'describe' | 'categorize' | 'analyze' | 'index'
export type ToolsSrc = 'pc' | 'phone' | 'solo'
export type ItemState = 'wait' | 'run' | 'done' | 'skip' | 'err'
export type StepGlyph = 'photo' | 'text' | 'tag' | 'play' | 'search'
export type Act = 'retry' | 'continue' | 'next'
// what a step costs: nothing, one model call per item, one embeddings call per EMBED_BATCH texts, or an analysis
// (frames, transcription and an optional report: no call count can be promised)
export type Charge = 'none' | 'model' | 'embed' | 'analyze'

export interface Step { label: string; verb: string; ing: string; glyph: StepGlyph; charge: Charge; line: (n: number) => string; one: string }

const s = (n: number) => (n === 1 ? '' : 's')
export type ToolWords = (key: string, params?: Record<string, unknown>) => string
export const say = (words: ToolWords | undefined, key: string, params: Record<string, unknown>, english: string): string => words ? words(key, params) : english

export const STEPS: Record<StepKind, Step> = {
  thumb: { label: 'Fetch link info', verb: 'fetched', ing: 'Fetching', glyph: 'photo', charge: 'none', line: n => `${n} without a preview`, one: 'Its thumbnail, title and caption' },
  describe: { label: 'Describe', verb: 'described', ing: 'Describing', glyph: 'text', charge: 'model', line: n => `${n} without a summary`, one: 'A short summary from the caption and thumbnail' },
  categorize: { label: 'Auto-categorize', verb: 'sorted', ing: 'Sorting', glyph: 'tag', charge: 'model', line: n => `${n} unsorted`, one: 'A collection and tags' },
  analyze: { label: 'Analyze videos', verb: 'analyzed', ing: 'Analyzing', glyph: 'play', charge: 'analyze', line: n => `${n} video${s(n)}`, one: 'Frames and a transcript of its video' },
  index: { label: 'Index for search', verb: 'indexed', ing: 'Indexing', glyph: 'search', charge: 'embed', line: n => `${n} to check for changed text`, one: 'Search by meaning for its text' },
}
// Labels are lazy presentation; charge, glyph and operation IDs remain the original values.
export function stepWords(kind: StepKind, words?: ToolWords, n?: number): Step {
  const step = STEPS[kind]
  return words ? { ...step, label: words(`processing.action.${kind}.label`), verb: words(`processing.action.${kind}.verb`, { n }),
    ing: words(`processing.action.${kind}.ing`), one: words(`processing.action.${kind}.one`),
    line: n => words(`processing.action.${kind}.line`, { n }) } : step
}
export const MAIN_STEPS: StepKind[] = ['describe', 'categorize']
export const PC_STEPS: StepKind[] = ['thumb', 'analyze', 'index']
export const PHONE_LIMIT = 25        // the phone's own key works through at most this many per run ("Next 25")
export const CONFIRM_OVER = 20       // more AI calls than this ask first (decision 2)
export const EMBED_BATCH = 64        // server/job_kinds.py: Index sends this many texts per embeddings call
export const NOTHING_TO_DESCRIBE = 'Nothing to describe yet: open it online once or add a note.'
export const PC_NO_KEY = 'API key required: on the PC open Settings > API keys.'
export const GONE = 'This item is no longer in your library.'
export const NOT_NEEDED = 'No longer needs this step.'
export const UNAVAILABLE = 'Result details unavailable; refresh the library.'
export const PROVIDER: Record<string, string> = { anthropic: 'Anthropic', claude: 'Anthropic', openai: 'OpenAI', freellmapi: 'FreeLLMAPI', local: 'Local', embeddings: 'embeddings' }

// what the PC says when the tapped step's own key is missing (the PC's preview, not the Describe line, decides)
export const KEY_MSG: Record<StepKind, string> = {
  thumb: '',
  describe: PC_NO_KEY,
  categorize: PC_NO_KEY,
  index: 'Embeddings key required: on the PC open Settings > API keys (Embeddings provider).',
  analyze: 'The AI report has no key on the PC. Choose None under AI report for frames and transcription only, or on the PC open Settings > API keys.',
}

// Tools' Undo (R5): what one single-item run replaced and what it wrote, with the card's uid (a numeric id can change
// when the PC numbers a link saved on the phone). Only the last single-item result keeps one.
export interface ToolsUndo {
  kind: 'describe' | 'categorize'
  uid: string
  was: { ai_desc?: string; cat?: string; tags?: string }
  now: { ai_desc?: string; cat?: string; tags?: string }
}
// the source refuses an Undo whose card changed since, or is gone: nothing was written
export class UndoRefused extends Error {}

// What a step still has to do for a row on the phone (the mirror): Describe for a card without an AI description,
// Auto-categorize for an unsorted card (INTERESTING or none) without tags. Run again takes every row.
export function phoneNeeds(r: { ai: boolean; cat: string; tags: string }, kind: StepKind): boolean {
  return kind === 'describe' ? !r.ai : kind === 'categorize' ? (r.cat === 'INTERESTING' || !r.cat) && !r.tags : false
}
export function phoneTargets(rows: { id: number; ai: boolean; cat: string; tags: string }[], kind: StepKind, rerun: boolean): number[] {
  return rows.filter(r => rerun || phoneNeeds(r, kind)).map(r => r.id)
}

// model calls a step may make for n items (Describe and Auto-categorize: one per item; Index: one per EMBED_BATCH
// texts; fetching and analysis are counted otherwise)
export function aiCalls(kind: StepKind, n: number): number {
  const c = STEPS[kind].charge
  return c === 'model' ? n : c === 'embed' ? Math.ceil(n / EMBED_BATCH) : 0
}
export const callsLine = (n: number, words?: ToolWords) => (n ? say(words, 'processing.calls', { n }, `${n} AI call${s(n)}`) : '')
// the charge as a line: "25 AI calls", "2 embedding calls", "charges may apply" (analysis), '' (fetching)
export function chargeLine(kind: StepKind, n: number, words?: ToolWords): string {
  const c = STEPS[kind].charge
  if (c === 'model') return callsLine(aiCalls(kind, n), words)
  if (c === 'embed') { const k = aiCalls(kind, n); return k ? say(words, 'processing.embeddings', { n: k }, `${k} embedding call${s(k)}`) : '' }
  return c === 'analyze' ? say(words, 'processing.charge.analyze', {}, 'charges may apply') : ''
}

// Ask before starting: Run again, Analyze, and more than CONFIRM_OVER model calls (decision 2). A follow-up (Retry,
// Continue, Next) asks by the same rule: its label names the action, it does not waive the question.
export function needsConfirm(kind: StepKind, n: number, rerun: boolean): boolean {
  return rerun || kind === 'analyze' || aiCalls(kind, n) > CONFIRM_OVER
}

export interface ConfirmIn {
  kind: StepKind; n: number; all: number; rerun: boolean; src: ToolsSrc; provider: string; replace: string
  join?: boolean; act?: Act | null; retained?: boolean
}

function keyName(src: ToolsSrc, provider: string, words?: ToolWords) {
  return say(words, src === 'pc' ? 'processing.review.pcKey' : 'processing.review.phoneKey', { provider: provider ? provider + ' ' : '' },
    [src === 'pc' ? 'the PC’s' : 'this phone’s', provider, 'key'].filter(Boolean).join(' '))
}
const actLead = (act: Act | null | undefined, n: number, words?: ToolWords) =>
  act === 'retry' ? say(words, 'processing.review.retryLead', { n }, `Retry ${n} failed. `) : act === 'continue' ? say(words, 'processing.review.continueLead', { n }, `Continue with ${n}. `) : act === 'next' ? say(words, 'processing.review.nextLead', { n }, `Next ${n}. `) : ''

// the confirm line inside the tapped row: a bold lead and the rest
export function confirmText(o: ConfirmIn, words?: ToolWords): { lead: string; rest: string } {
  const S = stepWords(o.kind, words), n = o.n, pre = actLead(o.act, n, words)
  if (o.kind === 'analyze') {
    const lead = pre + say(words, 'processing.review.videos', { n }, `${n} video${s(n)}.`)
    if (o.join) return { lead, rest: say(words, 'processing.review.join', {}, 'They join the running analysis and use its options, which are shared with that job.') }
    if (o.retained) return { lead, rest: say(words, 'processing.review.retained', {}, 'Same options as this run. Uses a saved copy or downloads it, then frames and transcription. Several minutes per video; AI and transcription charges may apply.') }
    return { lead, rest: say(words, 'processing.review.analysis', {}, 'Uses a saved copy or downloads it, then frames and transcription, with the options below. Several minutes per video; AI and transcription charges may apply.') }
  }
  const calls = chargeLine(o.kind, n, words)
  if (o.rerun) return { lead: pre + say(words, 'processing.review.rerun', { n }, `Run again on ${n} item${s(n)}.`), rest: [o.replace, calls ? say(words, 'processing.review.rerunCost', { calls, key: keyName(o.src, o.provider, words) }, `${calls} on ${keyName(o.src, o.provider)}; provider charges may apply.`) : ''].filter(Boolean).join(' ') }
  if (o.src !== 'pc' && o.all > n) return { lead: pre + say(words, 'processing.review.need', { n: o.all, label: S.label }, `${o.all} items need ${S.label}.`), rest: say(words, 'processing.review.batch', { n, provider: o.provider ? o.provider + ' ' : '' }, `This phone does ${n} at a time: the first ${n} now, ${n} AI calls on its ${o.provider ? o.provider + ' ' : ''}key. Provider charges may apply.`) }
  return { lead: `${pre}${calls}`, rest: say(words, 'processing.review.cost', { key: keyName(o.src, o.provider, words), pc: o.src === 'pc' ? say(words, 'processing.review.pcContinues', {}, ' The PC works through them; you can close this.') : '' }, `on ${keyName(o.src, o.provider)}. Provider charges may apply.${o.src === 'pc' ? ' The PC works through them; you can close this.' : ''}`) }
}

// the confirm line's orange key
export function confirmGo(o: Pick<ConfirmIn, 'kind' | 'n' | 'all' | 'src'>, words?: ToolWords): string {
  const S = stepWords(o.kind, words)
  if (o.src !== 'pc' && o.all > o.n) return say(words, 'processing.review.first', { label: S.label, n: o.n }, `${S.label} the first ${o.n}`)
  return o.src === 'pc' ? say(words, 'processing.review.startPc', { n: o.n }, `Start ${o.n} on the PC`) : say(words, 'processing.review.now', { label: S.label, n: o.n }, `${S.label} ${o.n} now`)
}

// the line under the rows: where the steps run and with which model
export function whereLine(src: ToolsSrc, provider: string, model: string, words?: ToolWords): string {
  if (src === 'pc') return say(words, 'processing.where.pc', { model: provider || model ? ` · ${[provider, model].filter(Boolean).join(' ')}` : '' }, `Runs on your PC${provider || model ? ` · ${[provider, model].filter(Boolean).join(' ')}` : ''}. Tap a step to start it.`)
  return say(words, 'processing.where.phone', { provider: provider ? provider + ' ' : '', model: model ? ` · ${model}` : '' }, `Runs on this phone with its ${provider ? provider + ' ' : ''}key${model ? ` · ${model}` : ''}. Tap a step to start it.`)
}

export function runNote(src: ToolsSrc, stopping: boolean, joined = false, words?: ToolWords): string {
  if (src === 'pc') return joined ? say(words, 'processing.run.pcJoined', {}, 'Runs on your PC, joined to a running analysis. Stop ends the whole PC job. Close this any time.') : say(words, 'processing.run.pc', {}, 'Runs on your PC. Close this any time: the PC keeps going.')
  return stopping ? say(words, 'processing.run.stopping', {}, 'Stopping after this item…') : say(words, 'processing.run.phone', {}, 'Stop finishes this item first. Each result is saved as it lands. Closing this keeps it going while the app stays open.')
}
export const stopLabel = (joined: boolean, words?: ToolWords) => (joined ? say(words, 'processing.stopPc', {}, 'Stop PC job') : say(words, 'notes.synthesize.stop', {}, 'Stop'))

export function savedLine(src: ToolsSrc, words?: ToolWords): string {
  return src === 'pc' ? say(words, 'processing.savedPc', {}, 'Saved on the PC.') : src === 'solo' ? say(words, 'processing.savedSolo', {}, 'Saved on this phone.') : say(words, 'processing.savedPhone', {}, 'Saved on this phone. It reaches the PC at the next sync.')
}

export function pcBusy(label: string, done: number, total: number, step: string, words?: ToolWords): { lead: string; rest: string } {
  return { lead: say(words, 'processing.busy.lead', {}, 'The PC is busy:'), rest: say(words, 'processing.busy.rest', { label, done, total, step }, `${label}, ${done} of ${total}. One job at a time; ${step} can start when it ends.`) }
}

export interface Tally { done: number; skip: number; err: number; left: number }
export function tally(items: { st: ItemState }[]): Tally {
  const t: Tally = { done: 0, skip: 0, err: 0, left: 0 }
  for (const i of items) if (i.st === 'done') t.done++; else if (i.st === 'skip') t.skip++; else if (i.st === 'err') t.err++; else t.left++
  return t
}
// the PC's own counts when its item rows are not available (a job the server no longer lists)
export const fromCounts = (c: { done: number; skip: number; err: number }): Tally => ({ done: c.done, skip: c.skip, err: c.err, left: 0 })

export function summary(t: Tally, kind: StepKind, words?: ToolWords): string {
  return [say(words, 'processing.summary.done', { n: t.done, verb: stepWords(kind, words, t.done).verb }, `${t.done} ${STEPS[kind].verb}`), t.skip && say(words, 'processing.summary.skipped', { n: t.skip }, `${t.skip} skipped`), t.err && say(words, 'processing.summary.failed', { n: t.err }, `${t.err} failed`)].filter(Boolean).join(' · ')
}

// the finished bar's orange key: Retry the failed, else Continue after a Stop, else the phone's Next batch
export function nextKey(t: Tally, stopped: boolean, rest: number, words?: ToolWords): { act: Act; text: string } | null {
  if (t.err) return { act: 'retry', text: say(words, 'processing.next.retry', { n: t.err }, `Retry ${t.err} failed`) }
  if (stopped && t.left) return { act: 'continue', text: say(words, 'processing.next.continue', { n: t.left }, `Continue with ${t.left}`) }
  if (rest > 0) return { act: 'next', text: say(words, 'processing.next.next', { n: Math.min(PHONE_LIMIT, rest) }, `Next ${Math.min(PHONE_LIMIT, rest)}`) }
  return null
}

// while running, a long ledger shows six lines from two before the current one
export function ledgerWindow<T extends { st: ItemState }>(items: T[], size = 6): T[] {
  if (items.length <= size) return items
  const cur = Math.max(0, items.findIndex(i => i.st === 'run' || i.st === 'wait'))
  const at = Math.min(Math.max(0, cur - 2), items.length - size)
  return items.slice(at, at + size)
}

export const scopeText = (item: boolean, heading: string, n: number, words?: ToolWords) => (item ? say(words, 'processing.scope.item', {}, 'This item') : say(words, 'processing.scope.list', { heading, n }, `${heading} · ${n}`))

// the run bar's progress: the meter needs a range above zero and a count that cannot pass it (a PC job whose rows are
// not loaded yet reports only its own counts)
export function meter(total: number, done: number): { max: number; now: number } {
  const max = Math.max(1, Math.floor(total) || 0)
  return { max, now: Math.min(max, Math.max(0, Math.floor(done) || 0)) }
}

// where a run is: its ledger's counts, or (a PC job whose rows are not loaded) the PC's own counts
export interface Progress { n: number; done: number; skip: number; err: number; left: number }
export function progress(r: { items: { st: ItemState }[]; total: number; counts: { done: number; skip: number; err: number } | null; unavailable?: boolean }): Progress {
  const t = tally(r.items), n = r.unavailable ? Math.max(0, r.total) : r.items.length || Math.max(0, r.total)
  const c = (!r.items.length || r.unavailable) && r.counts ? r.counts : null
  const done = c ? c.done : t.done, skip = c ? c.skip : t.skip, err = c ? c.err : t.err
  return { n, done, skip, err, left: Math.max(0, n - done - skip - err) }
}

// the closed Tools key's status for a screen reader (the ring and the badge are only drawn)
export function ringText(p: Progress, ended: boolean, words?: ToolWords): string {
  if (!ended) return say(words, 'processing.ring.running', { done: p.done + p.skip + p.err, total: p.n, left: p.left }, `Tools: ${p.done + p.skip + p.err} of ${p.n} done, ${p.left} left`)
  return p.err ? say(words, 'processing.ring.failed', { n: p.err }, `Tools: finished, ${p.err} failed`) : say(words, 'processing.ring.finished', {}, 'Tools: finished')
}
