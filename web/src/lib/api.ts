import { net } from './net.svelte'

// Setup, Settings and their tool panels share only checks still running, never cached readiness.
const toolChecks = new Map<string, Promise<unknown>>()
function get<T>(url: string): Promise<T> {
  if (url !== '/api/settings/tools' && url !== '/api/settings/scraper-runtime') return req<T>('GET', url)
  const pending = toolChecks.get(url)
  if (pending) return pending as Promise<T>
  const check = req<T>('GET', url).finally(() => { if (toolChecks.get(url) === check) toolChecks.delete(url) })
  toolChecks.set(url, check)
  return check
}

// The one HTTP client. Every non-GET request carries X-CM: 1 (server/guard.py rejects it otherwise).
export class ApiError extends Error {
  status: number
  // a Drive failure the server classified (server/cloud_errors.py): its code and the next action, beside the message
  code: string
  action: string
  constructor(status: number, message: string, code = '', action = '') {
    super(message)
    this.status = status
    this.code = code
    this.action = action
  }
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  if (method !== 'GET') toolChecks.delete(url)
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-CM'] = '1'
  const init: RequestInit = { method, headers }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  net.n++
  let r: Response, text: string
  try {
    r = await fetch(url, init)
    text = await r.text()
  } finally {
    net.n--
    if (method !== 'GET') toolChecks.delete(url)
  }
  let data: any = null
  if (text) {
    try { data = JSON.parse(text) } catch { data = { detail: text } }
  }
  if (!r.ok) throw new ApiError(r.status, (data && data.detail) || r.statusText, typeof data?.code === 'string' ? data.code : '', typeof data?.action === 'string' ? data.action : '')
  return data as T
}

async function upload<T>(url: string, body: Blob): Promise<T> {
  net.n++
  let r: Response, text: string
  try {
    r = await fetch(url, { method: 'POST', headers: { 'X-CM': '1', 'Content-Type': body.type || 'application/octet-stream' }, body })
    text = await r.text()
  } finally {
    net.n--
  }
  let data: any = null
  if (text) {
    try { data = JSON.parse(text) } catch { data = { detail: text } }
  }
  if (!r.ok) throw new ApiError(r.status, (data && data.detail) || r.statusText)
  return data as T
}

export const api = {
  get,
  post: <T>(url: string, body: unknown = {}) => req<T>('POST', url, body),
  patch: <T>(url: string, body: unknown) => req<T>('PATCH', url, body),
  put: <T>(url: string, body: unknown) => req<T>('PUT', url, body),
  del: <T>(url: string) => req<T>('DELETE', url),
  upload: <T>(url: string, body: Blob) => upload<T>(url, body),
}
