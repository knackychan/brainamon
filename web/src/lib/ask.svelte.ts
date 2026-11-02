import { sse } from './sse'
// Wiskit state: the saved chats, the SET options, the transcript, the answer stream (POST /api/ask
// read with fetch: EventSource is GET-only), Stop, citations on the mat. Retrieval and prompts are
// server-side (ask_core.py), the same as the Qt Ask tab.
// An answer outlives its page (the window can close for sleep mode): Stop is an explicit POST
// /api/ask/stop with the run id, and an answer that finished while this page was gone arrives as an
// `ask_saved` event (server/routes/ask.py).
import { api } from './api'
import { on } from './events.svelte'
import { lib, type Row } from './library.svelte'
import { soonText } from './commands'
import { toast, ui } from './ui.svelte'

export interface ChatEntry { slug: string; name: string; created?: string; updated?: string; message_count?: number }
export interface AskOptions {
  providers: { id: string; label: string; enabled: boolean; note: string }[]
  models: Record<string, { id: string; label: string }[]>
  default_provider: string; default_models: Record<string, string>; agent_providers: string[]; depths: number[]; scopes: string[]
  problems: Record<string, string>      // provider id -> why it cannot be used (a missing key), '' when ready
  claude_code: boolean                  // Claude Code mode is on in Settings and its CLI is there (knowledge/claude_code.py)
}
export interface UserMsg { role: 'user'; text: string; t: string; files?: string[] }
export interface ReviewMeta { kind: 'weekly'; start: string; end: string; timezone: string; through: string }
export type ReviewRequest = { task: 'weekly_review'; review_at: string; review_timezone: string }
export interface WiskitMsg {
  role: 'jarvis'; tag: string; t: string; ctx: string; trace: string[]; text: string; streaming: boolean
  sources: Row[]; cited: number[]; notes: string[]; note?: string; error?: string; q: string; saved?: string
  task?: 'weekly_review'; review?: ReviewMeta; complete?: boolean; saving?: boolean
}
export type Msg = UserMsg | WiskitMsg
// an Ask attachment (POST /api/ask/attach): a data/inbox file Wiskit reads with the next question
export interface Att { id: string; name: string; kind: string; chars: number; filed?: string }

const ls = {
  get(k: string) { try { return localStorage.getItem(k) } catch { return null } },
  set(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* private window */ } },
}
const hhmm = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` }

export type Mode = 'quick' | 'deep' | 'claude_code'
const MODES: Mode[] = ['quick', 'deep', 'claude_code']
const savedMode = ls.get('cm-jarvis-depth') as Mode

class Ask {
  opts: AskOptions | null = $state.raw(null)
  chats: ChatEntry[] = $state.raw([])
  slug = $state('')
  name = $state('New chat')
  mode = $state<Mode>(MODES.includes(savedMode) ? savedMode : 'quick')
  provider = $state('')
  model = $state('')
  modelOverride = false
  depth = $state(25)
  scope = $state('')
  msgs: Msg[] = $state([])
  atts: Att[] = $state([])                  // chips over the composer (lib/filing.svelte.ts)
  busy = $state(false)
  pet = $state<'idle' | 'think' | 'talk' | 'point' | 'happy' | 'sad'>('idle')
  navId: number | null = $state(null)
  ctl: AbortController | null = null
  run = ''                                  // the answer streaming now (its `start` event)
  own = new Set<string>()                   // answers this page streamed: their ask_saved is not news
  stopRequested = $state(false)             // Stop pressed before the run id arrived

  canDeep = $derived(!!this.opts && this.opts.agent_providers.includes(this.provider))
  canClaude = $derived(!!this.opts?.claude_code)
  problem = $derived(this.mode === 'claude_code' ? '' : (this.opts?.problems?.[this.provider] ?? ''))   // Claude Code needs no key
  modelLabel = $derived(this.opts?.models[this.provider]?.find(m => m.id === this.model)?.label ?? this.model)
}
export const ask = new Ask()

// later plans install these: opening a note (plan 10), adding text to the canvas (plan 09)
export const askHooks: { openNote: ((file: string) => void) | null; attachText: ((text: string, from?: HTMLElement) => void) | null } = {
  openNote: null, attachText: null,
}
export function openNote(file: string) {
  if (askHooks.openNote) askHooks.openNote(file); else toast(soonText('10'), 'w')
}

// ── loading ──────────────────────────────────────────────────────────────────
let listening = false
export async function loadAsk() {
  if (!listening) {
    listening = true
    on('ask_saved', (d: { run: string; slug: string; name: string; detached: boolean }) => {
      if (ask.own.has(d.run) || !d.detached) return
      refreshChats()
      if (!ask.busy && (d.slug === ask.slug || !ask.msgs.length)) { openChat(d.slug, false); return }
      toast(`Wiskit finished an answer in “${d.name}”`, '', { label: 'Open', run: () => openChat(d.slug) })
    })
    // chats deleted on the phone (server/sync.py): the one on screen goes too
    on('chats_changed', (d: { deleted: string[] }) => {
      refreshChats()
      if (!ask.busy && d.deleted.includes(ask.slug)) { blankChat(); toast('This chat was deleted on the phone') }
    })
  }
  try {
    ask.opts = await api.get<AskOptions>('/api/ask/options')
    const c = await api.get<{ chats: ChatEntry[]; active: string }>('/api/chats')
    ask.chats = c.chats
    const slug = c.chats.some(x => x.slug === c.active) ? c.active : c.chats[0]?.slug
    if (slug) await openChat(slug, false)
    else setOptions({})
  } catch (e) { toast(`Wiskit could not start: ${(e as Error).message}`, 'w') }
}

// A key was added or removed in Settings, or the page is about to answer with "no key": read the options again.
export async function refreshAskOptions() {
  try {
    ask.opts = await api.get<AskOptions>('/api/ask/options')
    if (!ask.slug && !ask.msgs.length && !ask.modelOverride) setOptions({ depth: ask.depth, scope: ask.scope })
  } catch { /* keep what the page has */ }
}

function setOptions(o: { provider?: string; model_id?: string; depth?: number; scope?: string }) {
  const op = ask.opts
  if (!op) return
  ask.modelOverride = !!(o.provider || o.model_id)
  const valid = (p?: string) => !!p && op.providers.some(x => x.id === p && x.enabled)
  ask.provider = valid(o.provider) ? o.provider! : op.default_provider
  const models = op.models[ask.provider] ?? []
  ask.model = o.model_id && models.some(m => m.id === o.model_id) ? o.model_id : (op.default_models[ask.provider] || models[0]?.id || '')
  ask.depth = o.depth && [10, 25, 50].includes(o.depth) ? o.depth : 25
  ask.scope = o.scope && op.scopes.includes(o.scope) ? o.scope : ''
  if (ask.mode === 'deep' && !ask.canDeep) ask.mode = 'quick'
  if (ask.mode === 'claude_code' && !ask.canClaude) ask.mode = 'quick'
}

export async function refreshChats() {
  try { ask.chats = (await api.get<{ chats: ChatEntry[] }>('/api/chats')).chats } catch { /* keep the list */ }
}

export async function openChat(slug: string, activate = true) {
  if (ask.busy) { toast('Wait for the answer, or press Stop', 'w'); return }
  const d = await api.get<{ slug: string; name: string; history: { role: string; content: string; review?: ReviewMeta }[]; options: Record<string, any>; sources: Row[] }>(`/api/chats/${encodeURIComponent(slug)}`)
  ask.slug = d.slug
  ask.name = d.name
  setOptions(d.options ?? {})
  const msgs: Msg[] = []
  let q = ''
  for (const t of d.history ?? []) {
    if (t.role === 'user') { q = t.content; msgs.push({ role: 'user', text: t.content, t: '' }) }
    else if (t.role === 'assistant') {
      const isReview = !!t.review && t.review.kind === 'weekly'
      msgs.push({ role: 'jarvis', tag: isReview ? 'Weekly review' : 'saved', t: '', ctx: '', trace: [], text: t.content, streaming: false, sources: [], cited: citedIn(t.content), notes: citedNotesIn(t.content), q, ...(isReview ? { task: 'weekly_review' as const, review: t.review, complete: true } : {}) })
    }
  }
  const last = [...msgs].reverse().find(m => m.role === 'jarvis') as WiskitMsg | undefined
  if (last) last.sources = d.sources
  ask.msgs = msgs
  setCited(last?.cited ?? [])
  if (activate) api.put('/api/chats/active', { slug }).catch(() => {})
}

const CITE_IDS = /\[\s*(?:ids?|no\.?)\s*:?\s*(\d{1,6}(?:\s*(?:,|and|&|;)\s*(?:(?:ids?|no\.?)\s*:?\s*)?\d{1,6})*)\s*\]/gi
function citedIn(t: string): number[] {
  const ids: number[] = []
  for (const m of t.matchAll(CITE_IDS)) for (const n of m[1].match(/\d{1,6}/g) ?? []) if (!ids.includes(+n)) ids.push(+n)
  return ids
}
function citedNotesIn(t: string): string[] {
  const notes: string[] = []
  for (const m of (t || '').matchAll(/\[\s*note\s*:\s*([^\]]+?)\s*\]/gi)) {
    const f = m[1].trim()
    if (f && !notes.includes(f)) notes.push(f)
  }
  return notes
}

export function setCited(ids: number[]) {
  lib.cited = new Map(ids.map((id, k) => [id, k + 1]))
  ask.navId = null
}

// no chat open: the first question makes one (POST /api/ask with no chat)
export function blankChat() {
  ask.slug = ''
  ask.name = 'New chat'
  ask.msgs = []
  setCited([])
  setOptions({})
}

export async function newChat() {
  if (ask.busy) stopAsk()
  try {
    const d = await api.post<{ slug: string; name: string; options: { provider: string; model_id: string } }>('/api/chats', { name: 'New chat' })
    ask.slug = d.slug
    ask.name = d.name
    ask.msgs = []
    setCited([])
    setOptions(d.options)
    refreshChats()
  } catch (e) { toast((e as Error).message, 'w') }
}

export async function saveOptions() {
  ask.modelOverride = true
  ls.set('cm-jarvis-depth', ask.mode)
  if (!ask.slug) return
  try { await api.put(`/api/chats/${encodeURIComponent(ask.slug)}`, { options: { provider: ask.provider, model_id: ask.model, depth: ask.depth, scope: ask.scope } }) } catch { /* the next answer saves them */ }
}

export function setMode(m: Mode) {
  if (m === 'deep' && !ask.canDeep) { toast(`Deep mode needs Anthropic or OpenAI (now ${ask.provider})`, 'w'); return }
  if (m === 'claude_code' && !ask.canClaude) { toast('Turn on Claude Code in Settings > Claude Code first', 'w'); return }
  ask.mode = m
  ls.set('cm-jarvis-depth', m)
}

// ── asking ───────────────────────────────────────────────────────────────────
export async function askWiskit(question: string, reviewRequest?: ReviewRequest) {
  const q = question.trim()
  if (!q || ask.busy) return
  ask.busy = true
  let m: WiskitMsg | null = null
  try {
    if (ask.problem) await refreshAskOptions()      // a key may have been added since the options were read
    const files = ask.atts.map(a => a.id)
    ask.msgs.push({ role: 'user', text: q, t: hhmm(), ...(files.length ? { files: ask.atts.map(a => a.name) } : {}) })
    ask.msgs.push({ role: 'jarvis', tag: reviewRequest ? 'Weekly review' : ask.mode === 'claude_code' ? 'claude code' : ask.mode, t: hhmm(), ctx: 'Reading the library…', trace: [], text: '', streaming: true, sources: [], cited: [], notes: [], q, ...(reviewRequest ? { task: 'weekly_review' as const, complete: false } : {}) })
    m = ask.msgs[ask.msgs.length - 1] as WiskitMsg
    if (ask.problem) {                              // no key: say so here, no request
      m.streaming = false
      m.ctx = ''
      m.error = ask.problem
      ask.pet = 'sad'
      return
    }
    ask.pet = 'think'
    const ctl = (ask.ctl = new AbortController())
    const body: Record<string, unknown> = { question: q, chat: ask.slug, mode: ask.mode, provider: ask.provider, model: ask.model, depth: ask.depth, scope: ask.scope, attachments: files }
    if (reviewRequest) Object.assign(body, reviewRequest)
    const r = await fetch('/api/ask', {
      method: 'POST', signal: ctl.signal, headers: { 'X-CM': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok || !r.body) throw new Error(`Wiskit is not reachable (${r.status})`)
    let terminal = false
    for await (const [ev, data] of sse(r)) {
      if (ask.ctl !== ctl || terminal) continue
      terminal = ['done', 'error', 'stopped'].includes(ev)
      onEvent(m, ev, JSON.parse(data))
    }
    if (!terminal) throw new Error('Wiskit was interrupted before completion.')
    if (m.task === 'weekly_review' && !m.complete && !m.error && m.note !== 'Stopped.') {
      m.error = 'The review did not finish. Try again.'
    }
  } catch (e) {
    if (m) {
      if ((e as Error).name === 'AbortError') m.note = 'Stopped.'
      else m.error = (e as Error).message
    }
  } finally {
    if (m) {
      m.streaming = false
      if (m.error || m.note === 'Stopped.') ask.pet = m.error ? 'sad' : 'idle'
    }
    ask.busy = false
    ask.ctl = null
    ask.run = ''
    ask.stopRequested = false
  }
}

function onEvent(m: WiskitMsg, ev: string, d: any) {
  if (ev === 'start') {
    ask.run = d.run; ask.own.add(d.run)
    if (ask.stopRequested) {
      api.post('/api/ask/stop', { run: d.run }).catch(() => { /* already over */ })
      ask.ctl?.abort()
    }
  }
  else if (ev === 'context') { m.ctx = d.line; if (d.list) m.tag += ' · list' }
  else if (ev === 'progress') m.trace.push(d.line)
  else if (ev === 'reset') { m.text = ''; m.cited = []; m.notes = []; m.sources = []; setCited([]) }          // Claude Code mode: the text so far led into a tool call
  else if (ev === 'chunk') { m.text += d.text; if (ask.pet !== 'talk') ask.pet = 'talk' }
  else if (ev === 'done') {
    m.text = d.text
    m.sources = d.sources
    m.cited = d.cited
    m.notes = d.notes
    if (m.task === 'weekly_review') {
      m.complete = true
      if (d.review) m.review = d.review as ReviewMeta
    }
    setCited(d.cited)
    if (m.task !== 'weekly_review') ask.atts = []   // read: the chat history keeps their text for follow-ups
    ask.slug = d.chat.slug
    ask.name = d.chat.name
    ask.pet = d.cited.length ? 'happy' : 'idle'
    setTimeout(() => { if (ask.pet === 'happy') ask.pet = 'idle' }, 1600)
    refreshChats()
  } else if (ev === 'stopped') m.note = 'Stopped.'
  else if (ev === 'error') m.error = d.message
}

export function stopAsk() {
  if (ask.run) {
    api.post('/api/ask/stop', { run: ask.run }).catch(() => { /* already over */ })
    ask.ctl?.abort()
  } else {
    ask.stopRequested = true
  }
}

// Ask Wiskit about a card or a selection (V6 askAbout)
export function askAbout(ids: number[]) {
  ids = ids.filter(id => lib.byId.has(id))
  if (!ids.length) return
  if (matchMedia('(max-width:1199px)').matches) ui.drawer = 'jv'
  if (ask.busy) { toast('Wiskit is still answering. Press Stop first.', 'w'); return }
  askWiskit(ids.length === 1 ? `Tell me more about No. ${ids[0]}` : `What do No. ${ids.slice(0, 8).join(', No. ')} have in common?`)
}

export function reviewThisWeek() {
  if (!ask.opts) { toast('Wiskit is loading…', 'w'); return }
  if (ask.busy) { toast('Wait for this answer, or press Stop.', 'w'); return }
  if (ask.mode === 'claude_code') { toast('Choose an API model to review this week.', 'w'); return }
  if (ask.atts.length) { toast('Send or remove attached files first.', 'w'); return }
  if (!ask.provider || !ask.model) { toast('Choose a model in SET first.', 'w'); return }
  let zone = ''
  try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '' } catch { zone = '' }
  if (!zone) { toast('Your browser did not provide a timezone.', 'w'); return }
  askWiskit('Review this week', { task: 'weekly_review', review_at: new Date().toISOString(), review_timezone: zone })
}

export async function saveAnswer(m: WiskitMsg) {
  if (m.saving || (m.task === 'weekly_review' && m.complete !== true)) return
  m.saving = true
  try {
    const payload: Record<string, unknown> = { answer_md: m.text, source_ids: m.cited }
    if (m.review) payload.review = m.review
    const r = await api.post<{ file: string }>('/api/ask/save-note', payload)
    m.saved = r.file
    toast(`Saved data/notes/${r.file}. It shows up in Knowledge.`, '', { label: 'Open', run: () => openNote(r.file) })
  } catch (e) { toast((e as Error).message, 'w') }
  finally { m.saving = false }
}
