// Starting a job from the UI (V6 f-jobs.js jobTargets + startJob): pick the targets, ask the server
// for a preview, confirm (AI jobs with the count and the cost), then start. The server runs it
// (server/jobs.py); progress arrives on the SSE stream. Analyze opens its options window instead of
// the confirm; a note asks for its topic first.
import { api, ApiError } from './api'
import { live } from './events.svelte'
import { lib, NEED, tagsOf } from './library.svelte'
import { toast } from './ui.svelte'
import { confirmWin, promptWin } from './windows.svelte'
import { PROCESS_ACTIONS, processingEligible, processingTargets } from './processing'
import type { NeedKey } from './library.svelte'

export interface KindInfo {
  label: string; name: string; ai: boolean; need: number; cost: number
  done: string                              // "every visible item <done>"
  what?: (force: boolean) => string         // the confirm window's first sentence
}
export const KINDS: Record<string, KindInfo> = {
  thumb: { label: 'Fetch link info', name: 'Fetch', ai: false, need: NEED.thumb, cost: 0, done: 'has a thumbnail' },
  describe: {
    label: 'Describe', name: 'Describe', ai: true, need: NEED.describe, cost: 0.004, done: 'is described',
    what: f => `${PROCESS_ACTIONS.find(a => a.kind === 'describe')!.description} ${f ? 'Replaces existing AI descriptions.' : 'Items already described are skipped.'}`,
  },
  categorize: {
    label: 'Auto-categorize', name: 'Sort', ai: true, need: NEED.categorize, cost: 0.002, done: 'has a collection',
    what: f => `The AI picks a collection and up to 3 tags for each item${f ? ', replacing the ones it has.' : ' still in INTERESTING with no tags.'}`,
  },
  analyze: { label: 'Analyze videos', name: 'Analyze', ai: true, need: NEED.analyze, cost: 0.03, done: 'is analyzed' },
  index: { label: 'Index for search', name: 'Index', ai: false, need: NEED.index, cost: 0, done: 'is indexed' },
  note: { label: 'Synthesize a note', name: 'Note', ai: true, need: 0, cost: 0.01, done: '' },
}

export const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

export const jobBusy = () => !!live.jobs.current
export const jobBusyMsg = () => `One job at a time: ${live.jobs.current?.label ?? 'a job'} is running`

// Pause / Resume / Stop of the running job (the progress window and the rail's Jobs module)
export async function jobControl(p: 'pause' | 'resume' | 'stop') {
  try { await api.post(`/api/jobs/${p}`) } catch (e) { toast((e as Error).message, 'w') }
}

// Plan 07 installs the Analyze options window and the progress window here.
export const jobHooks: {
  analyzeOptions: ((count: number, force: boolean) => Promise<Record<string, unknown> | null>) | null
  openProgress: (() => void) | null
} = { analyzeOptions: null, openProgress: null }

export interface StartOpts { ids?: number[]; force?: boolean; opts?: Record<string, unknown>; quiet?: boolean; from?: 'selection' | 'visible' }

export function jobTargets(kind: string, o: StartOpts = {}) {
  const ok = (id: number) => { const r = lib.byId.get(id); return !!r && (kind === 'note' || processingEligible(r, kind as NeedKey)) }
  const from = o.from ?? (o.ids || lib.sel.size ? 'selection' as const : 'visible' as const)
  if (kind === 'note') {
    const ids = (o.ids ?? (lib.sel.size ? [...lib.sel] : lib.visIds.slice(0, 30))).filter(ok)
    return { ids, force: true, from }
  }
  const rows = (o.ids ?? (lib.sel.size ? [...lib.sel] : lib.visIds)).filter(ok).map(id => lib.byId.get(id)!)
  const force = kind !== 'index' && !!o.force
  return { ids: processingTargets(rows, kind as NeedKey, force), force, from }
}

function confirmText(kind: string, n: number, force: boolean, from: string, model: string) {
  const k = KINDS[kind]
  const where = from === 'selection' ? 'Runs on your selection.'
    : force ? 'Runs on the visible items, including completed ones.' : 'Runs on the visible items that still need it.'
  if (kind === 'thumb') return {
    msg: 'Try to fetch each link’s thumbnail and caption: yt-dlp for social and video posts (no video is downloaded), the page’s public preview elsewhere. Some requests need saved login access in Settings > Imports & downloads; cookies cannot fix every blocked preview.',
    detail: `${where}${force ? ' Existing thumbnails and saved captions may be replaced. Custom titles and creators are kept.' : ' Links that already have a thumbnail are skipped.'} Text changes also refresh the search index; embeddings charges may apply.`,
  }
  if (kind === 'index') return {
    msg: `Update search by meaning for ${plural(n, 'item')} with ${model}.`,
    detail: `${where} Costs may apply to your embeddings account; typically well under $0.01 per 1,000 items. Unchanged items are skipped.`,
  }
  return {
    msg: `${k.what ? k.what(force) : `${k.label} runs on each item.`} Uses ${model} (Settings > Wiskit & AI).`,
    detail: `Estimated cost: about $${Math.max(0.01, n * k.cost).toFixed(2)} for ${plural(n, 'item')}. ${where} The search index is refreshed afterwards; embeddings charges may also apply.`,
  }
}

export async function startJob(kind: string, o: StartOpts = {}): Promise<boolean> {
  const k = KINDS[kind]
  if (live.jobs.current && !(kind === 'analyze' && live.jobs.current.kind === 'analyze')) {
    if (live.jobs.current.kind === kind && !o.ids) { jobHooks.openProgress?.(); return false }
    toast(jobBusyMsg(), 'w', jobHooks.openProgress ? { label: 'Show', run: jobHooks.openProgress } : undefined)
    return false
  }
  const T = jobTargets(kind, o), n = T.ids.length
  if (!n) {
    const why = kind === 'analyze' ? `No ${T.from === 'selection' ? 'selected' : 'visible'} video needs analysis: none is a reel or video, or each one is already analyzed. Open Process items and include completed items to run again.`
      : kind === 'note' ? 'No items to read' : `No eligible items need this step. Open Process items to choose another step or include completed items.`
    toast(why, 'w')
    return false
  }
  let opts = o.opts ?? {}
  try {
    if (kind === 'note' && !opts.topic) {
      const tally = new Map<string, number>()
      T.ids.forEach(id => { const r = lib.byId.get(id); if (r) tagsOf(r).forEach(t => tally.set(t, (tally.get(t) ?? 0) + 1)) })
      const top = [...tally].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'saved items'
      const topic = await promptWin({
        title: `Synthesize ${plural(n, 'item')} into a note`, code: 'WIK-22', label: 'Topic', value: top, ok: 'Synthesize',
        hint: `The AI combines available text from ${plural(n, 'item')} into one saved note in Knowledge and the Obsidian export.${T.from === 'visible' ? ' Uses up to the first 30 visible items.' : ' Uses the chosen items.'} Items without usable text are skipped. Estimated AI cost: about $${Math.max(0.01, n * k.cost).toFixed(2)}; actual cost varies.`,
      })
      if (!topic?.trim()) return false
      opts = { ...opts, topic: topic.trim() }
    }
    const p = await api.post<{ count: number; provider?: string; model?: string }>(
      '/api/jobs/preview', { kind, ids: T.ids, force: T.force, opts })
    if (!p.count) { toast(`Nothing to do: every one of these items ${k.done || 'is done'}`, 'w'); return false }
    if (kind === 'analyze' && live.jobs.current?.kind === 'analyze') {
      // added to the running analysis: the server keeps that job's options, so none are asked here
      const ok = await confirmWin({
        title: `Add ${plural(p.count, 'video')} to the running analysis?`, code: 'JOB-01', ok: `Add ${p.count}`,
        msg: 'These videos join the analysis already running and use its options (frames, transcript, AI report).',
        detail: `Estimated AI report cost: about $${Math.max(0.01, p.count * k.cost).toFixed(2)}; actual cost varies by model and video length.`,
      })
      if (!ok) return false
    } else if (kind === 'analyze') {
      if (!jobHooks.analyzeOptions) return false
      const chosen = await jobHooks.analyzeOptions(p.count, T.force)
      if (!chosen) return false
      opts = { ...opts, ...chosen }
    } else if (kind !== 'note' && !o.quiet) {
      const model = p.model ? `${p.provider} · ${p.model}` : 'the model from Settings'
      const t = confirmText(kind, p.count, T.force, T.from, model)
      const ok = await confirmWin({ title: `${k.label} ${plural(p.count, 'item')}?`, code: 'JOB-01', ok: `${k.name} ${p.count}`, msg: t.msg, detail: t.detail })
      if (!ok) return false
    }
    await api.post('/api/jobs', { kind, ids: T.ids, force: T.force, opts })
    toast(`${k.label}: ${plural(p.count, 'item')} started`, '', jobHooks.openProgress ? { label: 'Progress', run: jobHooks.openProgress } : undefined)
    return true
  } catch (e) {
    toast(e instanceof ApiError ? e.message : String(e), 'w')
    return false
  }
}
