// Plan 07: every Process job becomes live (Fetch thumbnails, Auto-categorize, Analyze videos, Index
// for search, Synthesize a note), plus Show progress, the selection's Synthesize, and the per-item
// yt-dlp actions of the card keys and the item window (Download video, Thumbnail only, Analyze).
import AnalyzeOptionsWin from '../windows/AnalyzeOptionsWin.svelte'
import DownloadWin from '../windows/DownloadWin.svelte'
import ProgressWin from '../windows/ProgressWin.svelte'
import ProcessingWin from '../windows/ProcessingWin.svelte'
import { api, ApiError } from './api'
import { cardActs } from './cardmenu'
import { bind } from './commands'
import { jobBusy, jobBusyMsg, jobHooks, startJob } from './jobs'
import { lib, type NeedKey } from './library.svelte'
import { toast } from './ui.svelte'
import { closeWin, openWin } from './windows.svelte'

export function openProgress() {
  openWin({ id: 'progress', title: 'Processing progress', code: 'PRG-17', w: 620, body: ProgressWin })
}

export function openProcessing(initial?: NeedKey, ids?: number[]) {
  openWin({
    id: 'processing', title: 'Process items', code: 'JOB-01', w: 680, body: ProcessingWin,
    props: { initial, ids: ids ?? (lib.sel.size ? [...lib.sel] : [...lib.visIds]), scope: ids ? 'Chosen items' : lib.sel.size ? 'Selected items' : 'Visible items' },
  })
}

function analyzeOptions(count: number, force: boolean): Promise<Record<string, unknown> | null> {
  return new Promise(res => {
    let done = false
    const finish = (v: Record<string, unknown> | null) => { if (!done) { done = true; res(v) } }
    const w = openWin({
      id: 'ao', title: `Analyze ${count} video${count === 1 ? '' : 's'}`, code: 'ANL-11', w: 600, body: AnalyzeOptionsWin,
      props: { count, force, answer: (o: Record<string, unknown> | null) => { finish(o); closeWin(w) } },
      onClose: () => finish(null),
    })
  })
}

export async function downloadItem(id: number, thumbnailOnly: boolean) {
  if (!lib.byId.has(id)) return
  if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
  try {
    const job = await api.post<{ id: number }>(`/api/items/${id}/download`, { thumbnail_only: thumbnailOnly })
    openWin({
      id: 'dl', title: `Running yt-dlp · No.${id}`, code: 'DLD-13', w: 620, body: DownloadWin,
      props: { jobId: job.id, itemId: id, thumbnailOnly },
    })
  } catch (e) { toast(e instanceof ApiError ? e.message : String(e), 'w') }
}

let installed = false
export function installJobs() {
  if (installed) return
  installed = true
  jobHooks.analyzeOptions = analyzeOptions
  jobHooks.openProgress = openProgress

  const busy = { off: jobBusy, offMsg: jobBusyMsg }
  bind('process-items', () => openProcessing())
  for (const [id, kind] of [['job-thumb', 'thumb'], ['job-describe', 'describe'], ['job-categorize', 'categorize'], ['job-analyze', 'analyze'], ['job-index', 'index']] as const) {
    bind(id, () => openProcessing(kind))
  }
  bind('job-note', () => { startJob('note') }, busy)
  bind('sel-note', () => { startJob('note', { ids: [...lib.sel] }) }, { off: () => jobBusy() || !lib.sel.size, offMsg: () => jobBusy() ? jobBusyMsg() : 'Select items in the Library first' })
  bind('progress', openProgress)

  cardActs.analyze = id => { startJob('analyze', { ids: [id], force: true }) }
  cardActs.download = id => { downloadItem(id, false) }
  cardActs.thumbOnly = id => { downloadItem(id, true) }
}
