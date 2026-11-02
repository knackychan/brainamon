// The server push channel: one EventSource on GET /api/events (server/events.py lists the kinds).
// EventSource reconnects by itself; on every (re)connect the server sends `hello` with the job state.
import { api } from './api'
import type { CloudTask } from './backup'
import type { RequestSnapshot } from './job-requests'
import { pushLine, toast, type ConsoleEntry, type ToastLevel } from './ui.svelte'

export interface JobSnap {
  id: number; kind: string; label: string; state: 'running' | 'paused' | 'finished' | 'stopped'
  total: number; done: number; err: number; current: number | null; auto: boolean; t0: number; t1: number
}
export interface JobsState { current: JobSnap | null; last: JobSnap | null; request?: RequestSnapshot | null }

// the Google Drive upload's state (server/sync.py status, the SSE `cloud` event and GET /api/cloud)
// seq grows with every change: a guard against an older snapshot landing after a newer one
export interface CloudSnap {
  seq: number; running: boolean; state: string; done: number; total: number; error: string
  vault_running: boolean; vault_state: string; vault_step: string; vault_done: number; vault_total: number; vault_since: number
  // the Backup & phones facts the rail's Jobs module reads (server/sync.py `status`)
  signed_in?: boolean; last_publish?: number; paused_since?: number; bytes_done?: number; bytes_total?: number; task?: CloudTask | null
}

export const live = $state({
  connected: false,
  jobs: { current: null, last: null } as JobsState,
  step: '',                          // the running job's latest step line (job_item `step`), '' between items
  cloud: null as CloudSnap | null,   // null until the first read; the rail's Jobs module shows the upload from it
})

// The lamp's short names (V6 stations). Server kinds: describe (plan 03); thumb, categorize,
// analyze, index, note (plan 07).
export const JOB_SHORT: Record<string, string> = {
  thumb: 'THUMB', describe: 'DESCRIBE', categorize: 'SORT', analyze: 'ANALYZE', index: 'INDEX', note: 'NOTE', download: 'YT-DLP',
  connections: 'CONNECT',
  refresh_map: 'MAP', export_obsidian: 'EXPORT',
}

type Handler = (data: any) => void
const handlers = new Map<string, Set<Handler>>()

// Subscribe to one event kind; returns the unsubscribe function.
export function on(kind: string, fn: Handler): () => void {
  let set = handlers.get(kind)
  if (!set) handlers.set(kind, (set = new Set()))
  set.add(fn)
  return () => set!.delete(fn)
}

// plan 07 adds ytdlp (a download job's output lines) and notes_changed (a note was written);
// plan 09 canvas_changed (a canvas file was written) and canvas_active (the target changed);
// plan 12 scrape (scraper activity lines), export_done, video_tools, settings_changed;
// sleep mode ask_saved (a Wiskit answer finished, also one whose page had closed); cloud (the
// Google Drive mirror's state and upload progress, server/sync.py); chats_changed (chats deleted
// on the phone); capture_open (Wiskit's panel asks the main window for Add to Brainamon)
const KINDS = ['hello', 'job', 'job_item', 'items_changed', 'log', 'toast', 'ytdlp', 'notes_changed', 'connections_changed', 'synth',
  'canvas_changed', 'canvas_active', 'scrape', 'export_done', 'video_tools', 'settings_changed', 'ask_saved', 'cloud', 'chats_changed', 'reformat_preview', 'capture_open', 'update']
let es: EventSource | null = null

// on every (re)connect: a server that restarted counts seq from 0 again, so this read is taken as is
function loadCloud() {
  api.get<CloudSnap>('/api/cloud').then(c => { live.cloud = c }).catch(() => { /* the next cloud event fills it */ })
}

// a (re)connect mid-job: the step line already sent is read back from the progress list
async function syncStep() {
  try {
    const p = await api.get<{ items: { state: string; step?: string }[] }>('/api/jobs/progress')
    const w = p.items.find(it => it.state === 'working')
    if (w?.step && live.jobs.current && !live.step) live.step = w.step
  } catch { /* the next step event fills it */ }
}

export async function connect() {
  if (es) return
  try {
    const backlog = await api.get<ConsoleEntry[]>('/api/console')
    backlog.forEach(pushLine)
  } catch { /* the stream still connects; the console starts empty */ }
  es = new EventSource('/api/events')
  es.onopen = () => { live.connected = true }
  es.onerror = () => { live.connected = false }
  for (const kind of KINDS) {
    es.addEventListener(kind, ev => {
      const data = JSON.parse((ev as MessageEvent).data)
      if (kind === 'hello') { live.jobs = data.jobs; live.step = ''; if (data.jobs.current) syncStep(); loadCloud() }
      else if (kind === 'job') { if (data.current?.id !== live.jobs.current?.id) live.step = ''; live.jobs = data }
      else if (kind === 'job_item') live.step = data.step ?? (data.state === 'working' ? '' : live.step)
      else if (kind === 'cloud') { if (!live.cloud || data.seq >= live.cloud.seq) live.cloud = data }
      else if (kind === 'log') pushLine(data)
      else if (kind === 'toast') toast(data.text, (data.level || '') as ToastLevel)
      handlers.get(kind)?.forEach(fn => fn(data))
    })
  }
}
