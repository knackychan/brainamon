import { sse } from '../../lib/sse'
// DesktopSource: the phone reads the running desktop app (development only, PLAN.md Phase 2).
// The phone opens http://localhost:18765/mobile.html through `adb reverse tcp:18765 tcp:18765`, a Host
// server/guard.py already accepts, and every call here is the same REST API the desktop page uses
// (src/lib/api.ts adds the X-CM header the guard wants on writes).
import { api } from '../../lib/api'
import type { Stamp } from '../../lib/note-format'
import { decodeText, type Picked } from '../files'
import type { Preview } from '../../lib/capture'
import type { AskEvent, CanvasDoc, CanvasRow, Category, CategoryProposal, PhoneCanvasProposal, Chat, ChatRow, FullItem, MobileSource, MyNote, NoteRow, OpenNote, Row } from './types'

interface Cols { cols: string[]; rows: unknown[][]; total: number }
const BOOL = new Set(['thumb', 'ai', 'an', 'fav'])
// GET /api/items?fmt=cols: column names once, then one array per row (booleans as 0 / 1)
function decode(c: Cols): Row[] {
  const k = c.cols
  return c.rows.map(v => {
    const o: Record<string, unknown> = {}
    for (let i = 0; i < k.length; i++) o[k[i]] = BOOL.has(k[i]) ? !!v[i] : v[i]
    return o as unknown as Row
  })
}

export const THUMB_W = 320          // the grid's thumbnails: twice the card width on a 2-column phone grid

export class DesktopSource implements MobileSource {
  readonly kind = 'desktop' as const
  readonly label = 'PC'

  health() { return api.get<{ ok: boolean; items: number; licensed: boolean }>('/api/health') }

  async rows() {
    const [cats, cols] = await Promise.all([api.get<Category[]>('/api/categories'), api.get<Cols>('/api/items?fmt=cols')])
    return { rows: decode(cols), cats }
  }
  async rowsByIds(ids: number[]) {
    if (!ids.length) return []
    return decode(await api.get<Cols>('/api/items?fmt=cols&ids=' + ids.join(',')))
  }
  async tints() {
    const t = await api.get<{ ready: boolean; tints: Record<string, string> }>('/api/tints')
    return t.tints
  }

  // ?v=<tv> names one version of the image (cached for good); ?w= asks the server for a narrow copy;
  // pin=1 keeps a favourite's thumbnail out of the service worker's trimming (public/sw.js)
  thumbUrl(r: Row, w = 0) {
    const q = [r.tv ? `v=${r.tv}` : '', w ? `w=${w}` : '', r.fav ? 'pin=1' : ''].filter(Boolean).join('&')
    return q ? `/thumb/${r.id}?${q}` : `/thumb/${r.id}`
  }
  item(id: number) { return api.get<FullItem>(`/api/items/${id}`) }
  async itemText(id: number, which: 'report' | 'transcript') {
    const r = await fetch(`/files/items/${id}/${which === 'report' ? 'report.md' : 'transcript.txt'}`)
    if (!r.ok) throw new Error(r.status === 404 ? `No ${which} yet` : `Could not load the ${which} (${r.status})`)
    return r.text()
  }
  async related(id: number) {
    const r = await api.get<Row[] | { needs_index: boolean }>(`/api/items/${id}/related`)
    return Array.isArray(r) ? r : []
  }

  async search(q: string) { return (await api.get<{ ids: number[] }>('/api/search?q=' + encodeURIComponent(q))).ids }
  async smart(q: string) { return (await api.post<{ ids: number[] }>('/api/smart', { q })).ids }

  favourite(id: number, on: boolean) { return api.post<Row>(`/api/items/${id}/favourite`, { on }) }
  edit(id: number, fields: Record<string, string>) { return api.patch<Row>(`/api/items/${id}`, fields) }
  saveLink(url: string) { return api.post<{ id: number | null; new: boolean }>('/api/inbox/link', { url }) }
  linkPreview(url: string) { return api.post<Preview>('/api/link/preview', { url }) }

  notes() { return api.get<NoteRow[]>('/api/notes') }
  note(file: string) { return api.get<OpenNote>(`/api/notes/${encodeURIComponent(file)}`) }
  myNotes() { return api.get<MyNote[]>('/api/my-notes') }
  myNote(file: string) { return api.get<MyNote>(`/api/my-notes/${encodeURIComponent(file)}`) }
  async myNoteCategories() { return (await api.get<{ categories: string[] }>('/api/my-notes/categories')).categories }
  createMyNote(title: string, category: string) { return api.post<MyNote>('/api/my-notes', { title: title || 'Untitled', category }) }
  saveMyNote(file: string, title: string, category: string, body: string, stamps?: Stamp[]) {
    return api.put<MyNote>(`/api/my-notes/${encodeURIComponent(file)}`, { title, category, body, ...(stamps !== undefined ? { stamps } : {}) })
  }
  // one section at the end, written on the Writer (POST /api/filing/file, the desktop window's way)
  async appendMyNote(file: string, _title: string, name: string, text: string) {
    await api.post('/api/filing/file', { action: 'append', file, name, text })
    return this.myNote(file)
  }
  async deleteMyNote(file: string) { await api.del(`/api/my-notes/${encodeURIComponent(file)}`) }
  async readFile(f: Picked, how: 'digest' | 'describe') {
    if (f.kind === 'text') return decodeText(f.data)
    const r = await fetch(`/api/filing/read?name=${encodeURIComponent(f.name)}&how=${how}`, {
      method: 'POST', headers: { 'X-CM': '1' }, body: Uint8Array.from(atob(f.data), c => c.charCodeAt(0)),
    })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(d.detail || r.statusText)
    return String(d.text || '')
  }

  canvases() { return api.get<CanvasRow[]>('/api/canvases') }
  async canvas(id: string) { return (await api.get<{ canvas: CanvasDoc }>(`/api/canvases/${encodeURIComponent(id)}`)).canvas }
  canvasImageUrl(name: string) { return `/files/canvas-uploads/${encodeURIComponent(name)}` }

  chats() { return api.get<{ chats: ChatRow[]; active: string }>('/api/chats') }
  chat(slug: string) { return api.get<Chat>(`/api/chats/${encodeURIComponent(slug)}`) }
  newChat(name = 'Phone chat') { return api.post<Chat>('/api/chats', { name }) }
  async deleteItem(id: number) { await api.post('/api/items/delete', { ids: [id] }) }
  async deleteChat(slug: string) { await api.del(`/api/chats/${encodeURIComponent(slug)}`) }

  // POST /api/ask answers with an SSE stream read by fetch (EventSource is GET-only), same reader
  // as the desktop's src/lib/ask.svelte.ts
  async ask(question: string, chat: string, onEvent: (e: AskEvent) => void, signal: AbortSignal, mode: 'quick' | 'deep' = 'quick') {
    const r = await fetch('/api/ask', {
      method: 'POST', signal, headers: { 'X-CM': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, chat, mode }),
    })
    if (!r.ok || !r.body) throw new Error(`Wiskit is not reachable (${r.status})`)
    let terminal = false
    for await (const [ev, data] of sse(r)) {
      if (terminal) continue
      terminal = ['done', 'error', 'stopped'].includes(ev)
      onEvent({ ev, ...JSON.parse(data) } as AskEvent)
    }
    if (!terminal) throw new Error('Wiskit was interrupted before completion.')
  }

  async stopAsk(run: string) { await api.post('/api/ask/stop', { run }) }
  saveAnswer(md: string, ids: number[]) { return api.post<{ file: string }>('/api/ask/save-note', { answer_md: md, source_ids: ids }) }

  async categoryProposal(): Promise<CategoryProposal | null> {
    const snap = await api.get<{ request?: { id: number; type: string; state: string; category?: string; ids?: number[]; entries?: CategoryProposal['entries'] } }>('/api/jobs')
    const r = snap.request
    if (!r || r.state !== 'pending') return null
    if (r.type === 'category_batch' && r.entries) return { requestId: r.id, entries: r.entries }
    if (r.type === 'category' && r.ids && r.category) {
      const rows = await this.rowsByIds(r.ids)
      return { requestId: r.id, entries: rows.map(row => ({ id: row.id, title: row.title, from: row.cat, category: r.category! })) }
    }
    return null
  }
  async applyCategoryProposal(p: CategoryProposal): Promise<void> {
    if (!p.requestId) throw new Error('This request is no longer pending.')
    await api.post(`/api/jobs/request/${p.requestId}/approve`, {})
  }
  async declineCategoryProposal(): Promise<void> {
    const p = await this.categoryProposal()
    if (p?.requestId) await api.post(`/api/jobs/request/${p.requestId}/decline`, {})
  }

  async canvasProposal(): Promise<PhoneCanvasProposal | null> {
    const snap = await api.get<{ request?: { id: number; type: string; state: string; preview?: PhoneCanvasProposal['preview'] } }>('/api/jobs')
    const r = snap.request
    return r?.type === 'canvas_proposal' && r.state === 'pending' && r.preview
      ? { mode: 'pc', requestId: r.id, preview: r.preview } : null
  }
  async applyCanvasProposal(p: PhoneCanvasProposal): Promise<string> {
    const current = await this.canvasProposal()
    // the same ID and the same preview: a card left from before a PC restart never approves a newer request
    if (p.mode !== 'pc' || current?.mode !== 'pc' || current.requestId !== p.requestId
      || JSON.stringify(current.preview) !== JSON.stringify(p.preview)) throw new Error('This canvas request is no longer pending.')
    const done = await api.post<{ canvas?: { canvas_id: string } }>(`/api/jobs/request/${p.requestId}/approve`, {})
    return done.canvas?.canvas_id || p.preview.target.id || ''
  }
  async declineCanvasProposal(p: PhoneCanvasProposal): Promise<void> {
    const current = await this.canvasProposal()
    if (p.mode !== 'pc' || current?.mode !== 'pc' || current.requestId !== p.requestId) throw new Error('This canvas request is no longer pending.')
    await api.post(`/api/jobs/request/${p.requestId}/decline`, {})
  }

  // Synthesize runs as the PC's own job (server/job_kinds.py `note`), with its progress in the bay
  async synthesize(topic: string, ids: number[], onLine: (line: string) => void) {
    await api.post('/api/jobs', { kind: 'note', ids, force: true, opts: { topic } })
    onLine('Synthesize is running on the PC; the note shows up here when it is done.')
    return { file: '', queued: true }
  }

  // GET /api/events (server/events.py): items_changed {ids}, notes_changed {file}
  watch(onItems: (ids: number[]) => void, onNotes: () => void, onCanvas?: () => void) {
    let es: EventSource | null = null
    try {
      es = new EventSource('/api/events')
      es.addEventListener('items_changed', e => { try { onItems((JSON.parse((e as MessageEvent).data) as { ids: number[] }).ids || []) } catch { /* ignore */ } })
      es.addEventListener('notes_changed', () => onNotes())
      es.addEventListener('canvas_changed', () => onCanvas?.())
    } catch { /* no SSE: the Refresh button still works */ }
    return () => es?.close()
  }

  // server/jobs.py publishes `job` with its snapshot on every request and every job step: only a
  // different request (id, state) counts
  watchRequests(onChange: () => void) {
    let es: EventSource | null = null, last = ''
    try {
      es = new EventSource('/api/events')
      es.addEventListener('job', e => {
        try {
          const r = (JSON.parse((e as MessageEvent).data) as { request?: { id: number; state: string } | null }).request
          const key = r ? `${r.id}:${r.state}` : ''
          if (key !== last) { last = key; onChange() }
        } catch { /* ignore */ }
      })
    } catch { /* no SSE: the review shows on the next ask */ }
    return () => es?.close()
  }
}
