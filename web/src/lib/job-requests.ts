// Things asked for from outside the app (the local MCP for Claude Code: start_job,
// projects/mcp-local/plans/01-confirm-in-app.md; save_note, projects/milestone-2026-10-14/claude-code-engine/PLAN.md):
// The server keeps the pending request in the jobs snapshot. Show it once automatically;
// closing defers it to the Jobs rail, where it can be reviewed until explicitly answered.
import { api, ApiError } from './api'
import { live, on } from './events.svelte'
import { KINDS, plural } from './jobs'
import { toast } from './ui.svelte'
import { closeWin, openWin, type WinSpec } from './windows.svelte'
import ConfirmBody from '../components/ConfirmBody.svelte'
import CategoryBatchBody from '../components/CategoryBatchBody.svelte'
import CanvasProposalBody from '../components/CanvasProposalBody.svelte'

interface JobRequest {
  id: number; type?: 'job'; kind: string; ids: number[]; source: string; state: string
  preview: { count: number; provider?: string; model?: string }
}
interface NoteRequest {
  id: number; type: 'note'; topic: string; excerpt: string; chars: number; sources: number[]; source: string; state: string
  file?: string; category?: string; stamps?: unknown[]
}
interface CategoryRequest {
  id: number; type: 'category'; category: string; ids: number[]; source: string; state: string
  from: Record<string, number>; sample: { id: number; title: string }[]
}
interface CategoryBatchRequest {
  id: number; type: 'category_batch'; ids: number[]; source: string; state: string
  entries: { id: number; title: string; from: string; category: string }[]
}

export interface CanvasPreviewEl {
  kind: 'thumbnail' | 'frame' | 'text' | 'existing'; item_id?: number; frame?: string; text?: string
  label?: string; title?: string; type?: string; file_path?: string; id?: string
}
export interface CanvasPreview {
  target: { id: string | null; name: string; new: boolean; count: number }
  layout: 'rows' | 'columns'; arrange: boolean
  counts: { thumbnail: number; frame: number; text: number; sections: number; moves: number }
  sections: { title: string | null; elements: CanvasPreviewEl[] }[]
  explicit: CanvasPreviewEl[]
}
interface CanvasRequest {
  id: number; type: 'canvas_proposal'; ids: number[]; source: string; state: string; preview: CanvasPreview
}

export type RequestSnapshot = JobRequest | NoteRequest | CategoryRequest | CategoryBatchRequest | CanvasRequest

const shown = new Set<number>()
const reviewing = new Set<number>()

function check(snap: { request?: RequestSnapshot | null } | null | undefined) {
  const r = snap?.request
  if (!r || r.state !== 'pending' || shown.has(r.id)) return
  reviewRequest()
}

export function requestLabel(r: RequestSnapshot): string {
  if (r.type === 'note') return `${r.file ? 'Replace' : 'Save'} note: ${r.topic}`
  if (r.type === 'category') return `Move ${plural(r.ids.length, 'item')} to ${r.category}`
  if (r.type === 'category_batch') return `Category batch · ${plural(r.entries.length, 'item')}`
  if (r.type === 'canvas_proposal') return `${r.preview.target.new ? 'New canvas' : 'Add to canvas'}: ${r.preview.target.name}`
  return `${KINDS[r.kind]?.label ?? r.kind} · ${plural(r.preview.count, 'item')}`
}

export async function reviewRequest() {
  const r = live.jobs.request
  if (!r || r.state !== 'pending' || reviewing.has(r.id)) return
  if (r.type !== 'note' && r.type !== 'category' && r.type !== 'category_batch' && r.type !== 'canvas_proposal' && ((r.type !== 'job' && r.type !== undefined) || !KINDS[r.kind])) return
  shown.add(r.id)
  reviewing.add(r.id)
  try {
    await (r.type === 'note' ? askNote(r) : r.type === 'category' ? askCategory(r) : r.type === 'category_batch' ? askCategoryBatch(r) : r.type === 'canvas_proposal' ? askCanvas(r) : ask(r))
  } finally {
    reviewing.delete(r.id)
  }
}

function requestWindow(spec: WinSpec): Promise<boolean | null> {
  return new Promise(resolve => {
    const w = openWin({
      ...spec,
      props: { ...spec.props, answer: (ok: boolean) => { resolve(ok); closeWin(w) } },
      onClose: () => resolve(null),
    })
  })
}

function confirmRequest(o: { title: string; msg: string; detail?: string; ok: string; danger?: boolean; code: string }) {
  return requestWindow({
    title: o.title, code: o.code, w: 460, alert: true, body: ConfirmBody,
    props: { ...o, danger: !!o.danger, cancel: 'Decline', detail: `${o.detail ?? ''} Close keeps this request pending in Jobs.` },
  })
}

interface Answered { saved?: string | null; moved?: number | null; canvas?: { canvas_id: string; name: string; added: number; moved: number } | null }

async function send(id: number, ok: boolean | null): Promise<Answered | null> {
  if (ok === null) return null
  try {
    const res = await api.post<{ request: RequestSnapshot } & Answered>(`/api/jobs/request/${id}/${ok ? 'approve' : 'decline'}`)
    if (live.jobs.request?.id === id) live.jobs.request = res.request
    return res
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) shown.delete(id)   // busy: ask again after the next job event
    toast(e instanceof ApiError ? e.message : String(e), 'w')
    return null
  }
}

async function ask(r: JobRequest) {
  const k = KINDS[r.kind], n = r.preview.count
  const model = r.preview.model ? `${r.preview.provider} · ${r.preview.model}` : 'the model from Settings'
  const ids = r.ids.slice(0, 20).join(', ') + (r.ids.length > 20 ? ', ...' : '')
  const ok = await confirmRequest({
    title: `${r.source} asks: ${k.label} ${plural(n, 'item')}?`, code: 'JOB-02', ok: `${k.name} ${n}`,
    msg: `${r.source} wants to run ${k.label} on items it picked. Only items still missing this step run; nothing is replaced.`
      + (k.ai ? ` Uses ${model}.` : ''),
    detail: `Items: ${ids}.` + (k.ai ? ` Estimated cost: about $${Math.max(0.01, n * k.cost).toFixed(2)}.` : '')
      + ' Nothing starts unless you click the button.',
  })
  if (await send(r.id, ok) && ok) toast(`${k.label}: ${plural(n, 'item')} started`)
}

async function askNote(r: NoteRequest) {
  const cites = r.sources.length ? `, citing ${plural(r.sources.length, 'item')}` : ''
  const ok = r.file
    ? await confirmRequest({
        title: `${r.source} asks: replace “${r.topic}” (${r.file})?`, code: 'NOTE-02', ok: 'Replace note', danger: true,
        msg: `${r.source} wants to replace the personal note ${r.file} in data/notes/ (${plural(r.chars, 'character')}${r.category ? `, category ${r.category}` : ''}). The current text is overwritten; there is no undo.${r.stamps ? ` Its stamps are replaced too (${plural(r.stamps.length, 'stamp')}).` : ''}`,
        detail: `${r.excerpt}${r.chars > r.excerpt.length ? ' …' : ''} · Nothing is saved unless you click the button.`,
      })
    : await confirmRequest({
        title: `${r.source} asks: save the note “${r.topic}”?`, code: 'NOTE-02', ok: 'Save note',
        msg: `${r.source} wants to save a new note in data/notes/ (${plural(r.chars, 'character')}${cites}). No existing note is changed.`,
        detail: `${r.excerpt}${r.chars > r.excerpt.length ? ' …' : ''} · Nothing is saved unless you click the button.`,
      })
  const res = await send(r.id, ok)
  if (ok && res?.saved) toast(r.file ? `Replaced data/notes/${res.saved}.` : `Saved data/notes/${res.saved}. It shows up in Knowledge.`)
}

async function askCategory(r: CategoryRequest) {
  const n = r.ids.length
  const from = Object.entries(r.from).map(([c, k]) => `${k} from ${c}`).join(', ')
  const sample = r.sample.map(s => `No.${s.id} ${s.title}`).join(' · ')
  const ok = await confirmRequest({
    title: `${r.source} asks: move ${plural(n, 'item')} to ${r.category}?`, code: 'CAT-02', ok: `Move ${n}`, danger: true,
    msg: `${r.source} wants to set the category of ${plural(n, 'item')} to ${r.category} (${from}). Their current category is replaced; no other field changes.`,
    detail: `${sample}${n > r.sample.length ? ' …' : ''} · Nothing changes unless you click the button.`,
  })
  const res = await send(r.id, ok)
  if (ok && res) toast(`Moved ${plural(n, 'item')} to ${r.category}`)
}

async function askCategoryBatch(r: CategoryBatchRequest) {
  const ok = await requestWindow({
    title: 'Review category batch',
    code: 'CAT-03', w: 760, alert: true, body: CategoryBatchBody,
    props: { entries: r.entries, source: r.source },
  })
  const res = await send(r.id, ok)
  if (ok && res) toast(`Updated ${plural(res.moved ?? 0, 'item')} in one category batch`)
}

async function askCanvas(r: CanvasRequest) {
  let activate = false
  const ok = await requestWindow({
    title: `${r.source} asks: ${r.preview.target.new ? 'make the canvas' : 'add to the canvas'} ${r.preview.target.name}`,
    code: 'CANVAS-02', w: 760, alert: true, body: CanvasProposalBody,
    props: { preview: r.preview, source: r.source, setActivate: (on: boolean) => { activate = on } },
  })
  const res = await send(r.id, ok)
  const made = res?.canvas
  if (!ok || !made) return
  if (activate) {
    try { await api.put('/api/canvas/active', { id: made.canvas_id }) } catch (e) { toast(e instanceof ApiError ? e.message : String(e), 'w') }
  }
  toast(`Canvas ${made.name}: added ${plural(made.added, 'element')}${made.moved ? `, moved ${made.moved}` : ''}`)
}

export function installJobRequests() {
  on('hello', d => check(d.jobs))
  on('job', d => check(d))
}
