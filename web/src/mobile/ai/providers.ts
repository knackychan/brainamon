import { sse } from '../../lib/sse.ts'
// The phone calls the AI providers itself, with the user's own keys from the pairing QR (PLAN.md
// Phase 5): Anthropic Messages and OpenAI Chat Completions (streamed for Wiskit, whole for
// Synthesize, a picture or a PDF read for Add a picture or file), OpenAI embeddings for Smart search, and Wiskit Deep's tool loop (Anthropic Messages
// with tools, the OpenAI Responses API). The same requests as core/ai_client.py ask_chat_stream /
// complete_text / embed_texts / ask_agent. Model ids and caps come from the PC through the
// mirror (library/meta.json `ai`, ai_client.phone_settings); nothing here names a model.
//
// Browsers: Anthropic answers cross-origin calls when the request carries
// `anthropic-dangerous-direct-browser-access: true` (its preflight was checked from the cloud
// session on 2026-10-11); OpenAI's API allows cross-origin calls too (inferred from its own
// browser support, not checked from here). The Android app (Phase 6) falls back to native HTTP
// when the WebView's fetch is refused (native.ts aiFetch, installed with setFetch).
// Run by Node in the tests (type stripping): no parameter properties, no imports.

export type Provider = 'anthropic' | 'openai'
export interface Msg { role: 'user' | 'assistant'; content: string }
export interface Endpoints { anthropic: string; openai: string }
export const CLOUD: Endpoints = { anthropic: 'https://api.anthropic.com', openai: 'https://api.openai.com' }

export class AiError extends Error {}

// how requests go out: the page's fetch, or the app's (native.ts aiFetch)
let send: (url: string, init: RequestInit) => Promise<Response> = (url, init) => fetch(url, init)
export function setFetch(f: typeof send) { send = f }

function headers(p: Provider, key: string): Record<string, string> {
  return p === 'anthropic'
    ? { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' }
    : { 'content-type': 'application/json', authorization: `Bearer ${key}` }
}

const NAME: Record<Provider, string> = { anthropic: 'Anthropic', openai: 'OpenAI' }

async function failure(p: Provider, r: Response): Promise<AiError> {
  let detail = ''
  try { const j = await r.json() as { error?: { message?: string } }; detail = j.error?.message || '' } catch { /* not JSON */ }
  const what = r.status === 401 || r.status === 403 ? `${NAME[p]} refused the key (${r.status}). Pair the phone again with a working key.`
    : r.status === 429 ? `${NAME[p]} says too many requests or no credit left (429).`
    : `${NAME[p]} answered ${r.status}.`
  return new AiError(detail ? `${what} ${detail.slice(0, 200)}` : what)
}

async function post(p: Provider, url: string, key: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  return call(p, url, key, { method: 'POST', body: JSON.stringify(body), signal })
}
async function call(p: Provider, url: string, key: string, init: RequestInit): Promise<Response> {
  const target = new URL(url)
  if (target.origin !== CLOUD[p] && !(import.meta.env?.DEV === true && target.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname))) throw new AiError('Untrusted AI endpoint')
  let r: Response
  try {
    r = await send(url, { ...init, redirect: 'error', headers: headers(p, key) })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new AiError(navigator.onLine === false ? 'No signal: Wiskit needs the internet to reach the AI.' : `${NAME[p]} could not be reached (${(e as Error).message}).`)
  }
  if (!r.ok) throw await failure(p, r)
  return r
}

function request(p: Provider, model: string, system: string, messages: Msg[], maxTokens: number, stream: boolean) {
  const clean = messages.map(m => ({ role: m.role, content: m.content }))
  return p === 'anthropic'
    ? { model, max_tokens: maxTokens, system, messages: clean, ...(stream ? { stream: true } : {}) }
    : { model, messages: system ? [{ role: 'system', content: system }, ...clean] : clean, max_completion_tokens: maxTokens, ...(stream ? { stream: true } : {}) }
}
const path = (p: Provider) => (p === 'anthropic' ? '/v1/messages' : '/v1/chat/completions')

// server-sent events from a fetch body: (event name, data) per block
// ai_client.ask_chat_stream: the answer's text deltas as they come
export async function* chatStream(ep: Endpoints, p: Provider, key: string, model: string, system: string, messages: Msg[],
  maxTokens: number, signal?: AbortSignal): AsyncGenerator<string> {
  const r = await post(p, ep[p] + path(p), key, request(p, model, system, messages, maxTokens, true), signal)
  for await (const [ev, data] of sse(r)) {
    if (data === '[DONE]') break
    let j: Record<string, any>
    try { j = JSON.parse(data) } catch { continue }
    if (p === 'anthropic') {
      if (ev === 'error' || j.type === 'error') throw new AiError(`Anthropic: ${j.error?.message || 'the answer broke off'}`)
      if (j.type === 'content_block_delta' && j.delta?.type === 'text_delta' && j.delta.text) yield j.delta.text as string
    } else {
      if (j.error) throw new AiError(`OpenAI: ${j.error.message || 'the answer broke off'}`)
      const d = j.choices?.[0]?.delta?.content
      if (d) yield d as string
    }
  }
}

// ai_client.complete_text: one whole answer
export async function complete(ep: Endpoints, p: Provider, key: string, model: string, prompt: string, maxTokens: number, signal?: AbortSignal): Promise<string> {
  const r = await post(p, ep[p] + path(p), key, request(p, model, '', [{ role: 'user', content: prompt }], maxTokens, false), signal)
  const j = await r.json() as Record<string, any>
  if (p === 'anthropic') return ((j.content || []) as { type: string; text?: string }[]).filter(b => b.type === 'text').map(b => b.text || '').join('').trim()
  return String(j.choices?.[0]?.message?.content || '').trim()
}

// ai_client.discover_cloud_models + chat_models_from_list: the models the key can use (More > Wiskit >
// Refresh), retired ids dropped. OpenAI: chat ids only, newest first; Anthropic: its order and display names
const OPENAI_SKIP = ['audio', 'realtime', 'tts', 'transcribe', 'search', 'image', 'embedding',
  'instruct', 'moderation', 'dall-e', 'whisper', 'codex', 'davinci', 'babbage']
const openaiChatId = (id: string) => (id.startsWith('gpt-') || /^o\d/.test(id)) && !/-\d{4}-\d{2}-\d{2}$/.test(id) && !OPENAI_SKIP.some(s => id.includes(s))
export function chatModels(p: Provider, rows: { id?: unknown; display_name?: string; created?: number }[], retired: string[] = []): { id: string; label: string }[] {
  if (p === 'openai') rows = [...rows].sort((a, b) => (b.created || 0) - (a.created || 0))
  const out: { id: string; label: string }[] = [], seen = new Set<string>()
  for (const r of rows) {
    const id = r.id
    if (typeof id !== 'string' || !id || seen.has(id) || retired.includes(id)) continue
    if (p === 'openai' && !openaiChatId(id)) continue
    out.push({ id, label: (p === 'anthropic' && r.display_name) || id })
    seen.add(id)
  }
  return out
}
export async function listModels(ep: Endpoints, p: Provider, key: string, retired: string[] = [], signal?: AbortSignal): Promise<{ id: string; label: string }[]> {
  const r = await call(p, ep[p] + (p === 'anthropic' ? '/v1/models?limit=1000' : '/v1/models'), key, { method: 'GET', signal })
  const j = await r.json() as { data?: { id?: unknown; display_name?: string; created?: number }[] }
  return chatModels(p, j.data || [], retired)
}

const anthropicText = (j: Record<string, any>) => ((j.content || []) as { type: string; text?: string }[])
  .filter(b => b.type === 'text').map(b => b.text || '').join('').trim()
const responsesText = (j: Record<string, any>) => ((j.output || []) as { type: string; content?: { type: string; text?: string }[] }[])
  .filter(o => o.type === 'message').flatMap(o => o.content || []).filter(c => c.type === 'output_text').map(c => c.text || '').join('').trim()

// ai_client.complete_vision: one picture and a prompt, one whole answer (Add a picture, projects/wiskit-files).
// Anthropic Messages image block; OpenAI Responses input_image (the path ai_client uses)
export async function vision(ep: Endpoints, p: Provider, key: string, model: string, prompt: string, mediaType: string, b64: string,
  maxTokens: number, signal?: AbortSignal): Promise<string> {
  if (p === 'anthropic') {
    const r = await post(p, ep.anthropic + '/v1/messages', key, { model, max_tokens: maxTokens, messages: [{ role: 'user', content: [
      { type: 'image', source: { type: 'base64', media_type: mediaType, data: b64 } }, { type: 'text', text: prompt }] }] }, signal)
    return anthropicText(await r.json())
  }
  const r = await post(p, ep.openai + '/v1/responses', key, { model, max_output_tokens: maxTokens, store: false, input: [{ role: 'user', content: [
    { type: 'input_text', text: prompt }, { type: 'input_image', image_url: `data:${mediaType};base64,${b64}` }] }] }, signal)
  return responsesText(await r.json())
}

// a PDF read by the model itself (the phone has no PDF library): Anthropic document block, OpenAI
// Responses input_file
export async function pdfText(ep: Endpoints, p: Provider, key: string, model: string, prompt: string, name: string, b64: string,
  maxTokens: number, signal?: AbortSignal): Promise<string> {
  if (p === 'anthropic') {
    const r = await post(p, ep.anthropic + '/v1/messages', key, { model, max_tokens: maxTokens, messages: [{ role: 'user', content: [
      { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: b64 } }, { type: 'text', text: prompt }] }] }, signal)
    return anthropicText(await r.json())
  }
  const r = await post(p, ep.openai + '/v1/responses', key, { model, max_output_tokens: maxTokens, store: false, input: [{ role: 'user', content: [
    { type: 'input_file', filename: name, file_data: `data:application/pdf;base64,${b64}` }, { type: 'input_text', text: prompt }] }] }, signal)
  return responsesText(await r.json())
}

// ai_client.embed_texts (OpenAI only: Anthropic has no embeddings)
export async function embed(ep: Endpoints, key: string, model: string, texts: string[], signal?: AbortSignal): Promise<number[][]> {
  const r = await post('openai', ep.openai + '/v1/embeddings', key, { model, input: texts }, signal)
  const j = await r.json() as { data: { index: number; embedding: number[] }[] }
  return j.data.slice().sort((a, b) => a.index - b.index).map(d => d.embedding)
}

// Whisper (ai_client.transcribe_file): one multipart upload, the key in the header, the model id from the PC.
// OpenAI answers browser calls cross-origin like its other endpoints.
export async function transcribe(ep: Endpoints, key: string, model: string, audio: Blob, signal?: AbortSignal): Promise<string> {
  const form = new FormData()
  form.append('model', model)
  form.append('file', audio, audio.type.includes('mp4') ? 'voice.m4a' : audio.type.includes('ogg') ? 'voice.ogg' : 'voice.webm')
  let r: Response
  try {
    r = await send(ep.openai + '/v1/audio/transcriptions', { method: 'POST', headers: { authorization: `Bearer ${key}` }, body: form, signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new AiError(navigator.onLine === false ? 'No signal: the recording waits on this phone.' : `OpenAI could not be reached (${(e as Error).message}).`)
  }
  if (!r.ok) throw await failure('openai', r)
  const j = await r.json() as { text?: string }
  return (j.text || '').trim()
}

// ai_client.ask_agent: Wiskit Deep's tool loop (plans/07-wiskit-deep.md). Rounds are whole answers;
// the last round forbids tools so a text answer always comes back. Anthropic: Messages with tools,
// the assistant's content (text, tool_use, thinking) sent back unchanged. OpenAI: the Responses API
// (its reasoning models reject function tools on Chat Completions), store false, the reasoning
// carried between rounds as encrypted items. `runTool` never throws (errors come back as text
// starting with 'Error:'); `onTool` is called before each call (the progress lines).
export interface AgentTool { name: string; description: string; parameters: Record<string, unknown> }
export interface AgentOptions {
  onText?: (text: string) => void
  onReset?: () => void
  maxToolCalls?: number
  researchDeadline?: number
  requestTimeoutMs?: number
}

async function agentRound(r: Response, p: Provider, onText?: (text: string) => void): Promise<Record<string, any>> {
  if (!onText) return r.json()
  const blocks = new Map<number, Record<string, any>>(), closed = new Set<number>()
  let j: Record<string, any> = {}, terminal = false, started = false
  const items = new Set<number>(), completedItems = new Set<number>()
  for await (const [ev, data] of sse(r)) {
    const e = JSON.parse(data)
    if (ev === 'error' || e.type === 'error' || e.type === 'response.failed' || e.type === 'response.incomplete') throw new AiError('Provider stream failed or was incomplete.')
    if (p === 'anthropic') {
      if (e.type === 'message_start') {
        if (started || !e.message || typeof e.message !== 'object') throw new AiError('Invalid message start.')
        started = true; j = { ...e.message }
      }
      if (e.type === 'content_block_start') {
        if (!started || !Number.isSafeInteger(e.index) || e.index < 0 || blocks.has(e.index) || typeof e.content_block?.type !== 'string') throw new AiError('Invalid content block start.')
        blocks.set(e.index, { ...e.content_block })
      }
      if (e.type === 'content_block_delta') {
        const b = blocks.get(e.index), d = e.delta
        if (!b || !d || closed.has(e.index)) throw new AiError('Invalid content block delta.')
        const fields: Record<string, [string, string]> = { text_delta: ['text', 'text'], input_json_delta: ['tool_use', 'partial_json'], thinking_delta: ['thinking', 'thinking'], signature_delta: ['thinking', 'signature'] }
        const field = fields[d.type]
        if (field && (b.type !== field[0] || typeof d[field[1]] !== 'string')) throw new AiError('Malformed content block delta.')
        if (d.type === 'text_delta' && b.type === 'text') { b.text += d.text; onText(d.text) }
        else if (d.type === 'input_json_delta' && b.type === 'tool_use') b.partial = (b.partial || '') + d.partial_json
        else if (d.type === 'thinking_delta' && b.type === 'thinking') b.thinking += d.thinking
        else if (d.type === 'signature_delta') b.signature = (b.signature || '') + d.signature
      }
      if (e.type === 'content_block_stop') {
        const b = blocks.get(e.index)
        if (!b || closed.has(e.index)) throw new AiError('Invalid content block completion.')
        if ('partial' in b) { try { b.input = JSON.parse(b.partial) } catch { b.input = null }; delete b.partial }
        closed.add(e.index)
      }
      if (e.type === 'message_delta') {
        if (!started || !e.delta || typeof e.delta !== 'object') throw new AiError('Malformed message delta.')
        Object.assign(j, e.delta)
      }
      if (e.type === 'message_stop') {
        if (!started || closed.size !== blocks.size || [...blocks.keys()].some(i => i >= blocks.size)) throw new AiError('Unfinished content block.')
        terminal = true
        j.content = [...blocks].sort((a, b) => a[0] - b[0]).map(([, b]) => b)
      }
    } else {
      if (e.type === 'response.output_text.delta') {
        if (typeof e.delta !== 'string') throw new AiError('Malformed output text delta.')
        onText(e.delta)
      }
      if (e.type === 'response.output_item.added') {
        if (!Number.isSafeInteger(e.output_index) || e.output_index < 0 || items.has(e.output_index) || !e.item) throw new AiError('Malformed output item.')
        items.add(e.output_index)
      }
      if (e.type === 'response.output_item.done') {
        if (!items.has(e.output_index) || !e.item || e.item.status && e.item.status !== 'completed') throw new AiError('Incomplete output item.')
        completedItems.add(e.output_index)
      }
      if (e.type === 'response.completed') {
        if (!e.response || [...items].some(i => !completedItems.has(i))) throw new AiError('Unfinished output items.')
        j = e.response; terminal = true
      }
    }
    if (terminal) break
  }
  if (!terminal) throw new AiError('Provider stream ended without successful completion.')
  return j
}

export async function askAgent(ep: Endpoints, p: Provider, key: string, model: string, system: string, messages: Msg[],
  tools: AgentTool[], runTool: (name: string, args: Record<string, unknown>) => Promise<string>,
  onTool: (name: string, args: Record<string, unknown>) => void, maxRounds: number, maxTokens: number, signal?: AbortSignal,
  options: AgentOptions = {}): Promise<string> {
  const anthropic = p === 'anthropic'
  const schemas = tools.map(t => anthropic ? { name: t.name, description: t.description, input_schema: t.parameters } : { type: 'function', ...t, strict: false })
  const history: unknown[] = messages.map(m => ({ role: m.role, content: m.content }))
  const names = new Set(tools.map(t => t.name))
  let used = 0
  let controlUsed = 0
  const check = () => signal?.throwIfAborted()
  const limited = () => (options.maxToolCalls !== undefined && used >= options.maxToolCalls) || (options.researchDeadline !== undefined && performance.now() >= options.researchDeadline)
  for (let rnd = 0; rnd < maxRounds; rnd++) {
    check()
    const last = rnd === maxRounds - 1 || limited()
    const instructions = system + (last ? '\nFinal answer only: state limited coverage and use available evidence.' : '')
    const body = anthropic
      ? { model, max_tokens: maxTokens, system: instructions, messages: history, tools: schemas, tool_choice: { type: last ? 'none' : 'auto' } }
      : { model, instructions, input: history, tools: schemas, tool_choice: last ? 'none' : 'auto', max_output_tokens: maxTokens, store: false, include: ['reasoning.encrypted_content'] }
    const controller = new AbortController()
    const abort = () => controller.abort(signal?.reason)
    signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(() => controller.abort(new DOMException('Provider request timed out.', 'TimeoutError')), options.requestTimeoutMs ?? 60000)
    let j: Record<string, any>
    try {
      check()
      const r = await post(p, ep[p] + (anthropic ? '/v1/messages' : '/v1/responses'), key, { ...body, ...(options.onText ? { stream: true } : {}) }, controller.signal)
      j = await agentRound(r, p, options.onText)
      controller.signal.throwIfAborted()
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort) }
    check()
    const output = (anthropic ? j.content : j.output) || []
    const calls = output.filter((o: any) => o.type === (anthropic ? 'tool_use' : 'function_call'))
    if (anthropic && j.stop_reason === 'refusal') { options.onReset?.(); return 'The model declined to answer this request.' }
    if (anthropic ? !['end_turn', 'stop_sequence', 'tool_use'].includes(j.stop_reason) || (j.stop_reason === 'tool_use') !== !!calls.length
      : j.status !== 'completed' || output.some((o: any) => o.status != null && o.status !== 'completed' || o.type === 'message' && o.status !== 'completed')) throw new AiError('Provider response was incomplete or inconsistent.')
    if (last && calls.length) throw new AiError('Tools in an answer-only round.')
    const ids = calls.map((c: any) => anthropic ? c.id : c.call_id)
    if (ids.some((id: unknown) => typeof id !== 'string' || !id) || new Set(ids).size !== ids.length || calls.some((c: any) => typeof c.name !== 'string' || !c.name)) throw new AiError('Malformed provider tool call IDs or names.')
    if (!calls.length) {
      const refusal = anthropic ? '' : output.flatMap((o: any) => o.content || []).filter((c: any) => c.type === 'refusal').map((c: any) => c.refusal).join('')
      const text = refusal || (anthropic ? anthropicText(j) : responsesText(j))
      if (!text) throw new AiError('Provider returned an empty answer.')
      if (refusal) options.onReset?.()
      return text
    }
    if (controlUsed + calls.length * 64 + 128 > 2048) throw new AiError('Tool round exceeds control reserve.')
    options.onReset?.()
    if (anthropic) history.push({ role: 'assistant', content: output })
    else history.push(...output)
    const results = []
    for (const [index, c] of calls.entries()) {
      check()
      let args: unknown = anthropic ? c.input : null
      if (!anthropic) { try { args = JSON.parse(c.arguments) } catch { /* invalid call gets a result */ } }
      let out: string
      if (!args || typeof args !== 'object' || Array.isArray(args)) out = 'Error: tool arguments were not a JSON object.'
      else if (!names.has(c.name)) out = 'Error: unadvertised tool.'
      else if (limited()) out = 'Error: research budget exhausted; call skipped.'
      else if (c.name.startsWith('propose_') && controlUsed + 512 + 64 * (calls.length - index - 1) + 128 > 2048) out = 'Error: proposal control reserve exhausted; call skipped.'
      else { used++; onTool(c.name, args as Record<string, unknown>); check(); out = await runTool(c.name, args as Record<string, unknown>) }
      if (c.name?.startsWith('propose_') || out.startsWith('Error:')) {
        if (out.startsWith('Error:') && [...out].length > 64) out = 'Error: tool returned an oversized error.'
        if ([...out].length > 512) out = 'Error: tool receipt exceeded its reserved size.'
        controlUsed += [...out].length
      }
      if (anthropic) results.push({ type: 'tool_result', tool_use_id: c.id, content: out, is_error: out.startsWith('Error:') })
      else history.push({ type: 'function_call_output', call_id: c.call_id, output: out })
    }
    if (anthropic) history.push({ role: 'user', content: results })
  }
  throw new AiError('No final answer within the round budget.')
}
