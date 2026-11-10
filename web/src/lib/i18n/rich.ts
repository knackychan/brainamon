import type { Params } from './index.ts'

export type RichNode = { type: 'text'; value: string } | { type: 'b' | 'i' | 'code' | 'a'; name?: string; children: RichNode[] }

const own = (o: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(o, key)
const interpolate = (text: string, params: Params) => text.replace(/\{([\w.-]+)\}/g,
  (match, name: string) => own(params, name) ? String(params[name]) : match)

export function parseRich(text: string, params: Params = {}): RichNode[] {
  if (!params || typeof params !== 'object') params = {}
  const root: RichNode[] = []
  const stack: { type: string; children: RichNode[] }[] = [{ type: '', children: root }]
  const parts = text.split(/(<[^>]*>)/g)
  for (const part of parts) {
    if (!part) continue
    const open = part.match(/^<(b|i|code|a:([\w.-]+))>$/)
    const close = part.match(/^<\/(b|i|code|a)>$/)
    if (open) {
      const type = open[1].startsWith('a:') ? 'a' : open[1] as 'b' | 'i' | 'code'
      if (type === 'a' && stack.some(item => item.type === 'a')) return [{ type: 'text', value: interpolate(text, params) }]
      const node: RichNode = { type, ...(type === 'a' ? { name: open[2] } : {}), children: [] }
      stack[stack.length - 1].children.push(node)
      stack.push(node)
    } else if (close) {
      if (stack.length === 1 || stack[stack.length - 1].type !== close[1]) return [{ type: 'text', value: interpolate(text, params) }]
      stack.pop()
    } else if (part.includes('<') || part.includes('>')) return [{ type: 'text', value: interpolate(text, params) }]
    else stack[stack.length - 1].children.push({ type: 'text', value: interpolate(part, params) })
  }
  return stack.length === 1 ? root : [{ type: 'text', value: interpolate(text, params) }]
}

export function safeHref(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return (url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password ? value : null
  } catch { return null }
}
