import { applyCanvasLocal, canonJson, normalizeCanvas, type CanvasDocument, type RawCanvasProposal } from '../ai/canvas.ts'
import { splitJoin, strip } from '../ai/quick.ts'
import { say, type ToolWords } from '../tools.ts'
import { idFirst, inSearch, wholeId } from '../../lib/whole-id.ts'
import type { CanvasDraftContext, Row } from '../source/types'

export const COLOURS = ['#FFF9C4', '#FFE0CC', '#D9F2E3', '#D6E8FA', '#E6DDF5']
export const CHANGED = 'Canvas changed. Check the board and tap Add again.'
export const LIMIT = '60 is the most for one go. Add these, then add more.'
export const UNCERTAIN = 'Could not confirm Add. Tap Add to check the same addition.'
export class CanvasIssue extends Error {
  readonly key: string
  readonly params: Record<string, unknown>
  constructor(key: string, english: string, params: Record<string, unknown> = {}) { super(english); this.key = key; this.params = params }
}
export const identity = (r: Pick<Row, 'id' | 'uid'>) => r.uid || String(r.id)
export const version = (r: Row) => String(r.tv ?? 0)
export const points = (s: string) => [...s].length
export const invalidUnicode = (s: string) => /[\uD800-\uDFFF]/u.test(s)
export const baseKey = (d: CanvasDocument | null) => d ? canonJson({ id: d.id, name: d.name, items: d.items }) : 'null'
export const count = (picks: unknown[], note: string) => picks.length + (strip(note) ? 1 : 0)
export function textProblem(name: string, note: string, newMode: boolean, words?: ToolWords): string {
  if (invalidUnicode(name) || invalidUnicode(note)) return say(words, 'canvas.composer.invalid', {}, 'Remove invalid characters from the name or note.')
  if (newMode && points(splitJoin(name)) > 80) return say(words, 'canvas.composer.longName', {}, 'Use at most 80 characters for the canvas name.')
  if (points(strip(note)) > 1000) return say(words, 'canvas.composer.longNote', {}, 'Use at most 1000 characters for the note.')
  return ''
}
export const clash = (name: string, names: { id: string; name: string }[]) => names.find(c => strip(c.name).toLowerCase() === splitJoin(name).toLowerCase())
export function proposal(name: string, id: string | null, ids: number[], note: string, color: string, layout: string): RawCanvasProposal {
  return { ...(id ? { canvas_id: id } : { new_name: splitJoin(name) }), layout,
    elements: [...ids.map(item_id => ({ kind: 'thumbnail', item_id })), ...(strip(note) ? [{ kind: 'text', text: strip(note), color }] : [])] }
}
export function manual(raw: RawCanvasProposal, desktop = false) {
  const keys = Object.keys(raw).sort().join(',')
  if (keys !== 'canvas_id,elements,layout' && keys !== 'elements,layout,new_name' || !['rows', 'columns'].includes(String(raw.layout))) throw Object.assign(new Error('Invalid canvas addition fields.'), { displayKey: 'common.error.canvasFields' })
  const p = normalizeCanvas(raw), ids = new Set<number>()
  if (textProblem(p.new_name || '', p.elements.map(e => e.text || '').join(''), !p.canvas_id)) throw Object.assign(new Error('Remove invalid characters from the name or note.'), { displayKey: 'common.error.canvasCharacters' })
  let notes = 0
  for (const e of raw.elements as Record<string, unknown>[]) {
    if (e.kind === 'thumbnail' && Object.keys(e).sort().join(',') === 'item_id,kind') {
      const id = e.item_id as number
      if (!id || (desktop && id < 1) || ids.has(id)) throw Object.assign(new Error('Duplicate or invalid picked image.'), { displayKey: 'common.error.canvasImageDuplicate' })
      ids.add(id)
    } else if (e.kind === 'text' && Object.keys(e).sort().join(',') === 'color,kind,text') notes++
    else throw Object.assign(new Error('Invalid canvas addition element.'), { displayKey: 'common.error.canvasElement' })
  }
  if (notes > 1) throw Object.assign(new Error('Add one note at a time.'), { displayKey: 'common.error.canvasOneNote' })
  return p
}
export function contextCheck(raw: RawCanvasProposal, c: CanvasDraftContext, mirror: boolean) {
  const p = manual(raw, !mirror)
  if (!/^[0-9a-f]{32}$/.test(c.opId) || !/^[A-Za-z0-9_-]{1,64}$/.test(c.canvasId) || c.canvasId === 'index'
    || (!p.canvas_id && !/^[0-9a-f]{32}$/.test(c.canvasId)) || (p.canvas_id && p.canvas_id !== c.canvasId)
    || !Number.isSafeInteger(c.at) || c.at < 0 || (p.canvas_id ? c.base?.id !== p.canvas_id : c.base !== null)) throw Object.assign(new Error('Invalid canvas addition context.'), { displayKey: 'common.error.canvasContext' })
  if (c.base && (typeof c.base.name !== 'string' || !Array.isArray(c.base.items)
    || !mirror && (!Number.isSafeInteger(c.base._sourceRev) || Number(c.base._sourceRev) <= 0))) throw Object.assign(new Error('Invalid canvas addition base.'), { displayKey: 'common.error.canvasBase' })
  const ids = p.elements.filter(e => e.kind === 'thumbnail').map(e => e.item_id!)
  const keys = new Set<string>(), pickedIds = new Set<number>()
  if (!Array.isArray(c.thumbs) || c.thumbs.length !== ids.length) throw Object.assign(new Error('Invalid selected thumbnails.'), { displayKey: 'common.error.canvasThumbnails' })
  for (const t of c.thumbs) {
    const key = identity(t)
    if (!ids.includes(t.id) || pickedIds.has(t.id) || keys.has(key) || (mirror && !/^[0-9a-f]{32}$/.test(t.uid || '')) || typeof t.version !== 'string'
      || !(t.blob instanceof Blob) || !Array.isArray(t.size) || t.size.length !== 2
      || t.size.some(n => !Number.isSafeInteger(n) || n <= 0 || n > 100000)) throw Object.assign(new Error('Invalid selected thumbnail dimensions or identity.'), { displayKey: 'common.error.canvasThumbnailIdentity' })
    keys.add(key); pickedIds.add(t.id)
  }
  return p
}
export function preview(base: CanvasDocument | null, ids: number[], note: string, color: string, layout: string, sizes: Map<number, [number, number]>) {
  if (!count(ids, note)) return base || { id: 'draft', name: '', items: [] }
  // Only the pure preview sees this name; invalid user input never blocks staging.
  const raw = proposal('Preview', base?.id || null, ids, points(strip(note)) <= 1000 && !invalidUnicode(note) ? note : [...strip(note)].slice(0, 1000).join('').replace(/[\uD800-\uDFFF]/gu, '\uFFFD'), color, layout)
  return applyCanvasLocal(normalizeCanvas(raw), base, sizes, 'draft', base?.id || 'draft', 0)
}
export function filtered(rows: Row[], q: string, cat: string, fav: boolean, ids: Set<number> | null, rank: Map<number, number> | null) {
  const query = strip(q).toLowerCase()
  let out = rows.filter(r => r.thumb && (cat === 'all' || r.cat === cat) && (!fav || r.fav))
  if (query) out = out.filter(r => ids !== null ? inSearch(r.id, query, ids, rank)
    : r.id > 0 && r.id === wholeId(query) || !!rank?.has(r.id) || [r.title, r.creator, r.tags, r.desc, r.cat].some(s => (s || '').toLowerCase().includes(query)))
  out.sort(rank?.size && query ? (a, b) => (rank.get(a.id) ?? 1e9) - (rank.get(b.id) ?? 1e9) || b.id - a.id
    : (a, b) => b.created - a.created || b.id - a.id)
  return idFirst(out, query)
}
export function refusal(e: unknown) {
  const text = e instanceof Error ? e.message : String(e)
  const lines = text.replace(/^Canvas proposal refused, nothing was changed:\s*/u, '').split(/\n-\s*|^-[ ]*/u).filter(Boolean)
  if (lines.length < 2) return lines[0] || text
  const tail = lines.at(-1)?.match(/^and (\d+) more$/u)
  const n = lines.length - 1 - (tail ? 1 : 0) + Number(tail?.[1] || 0)
  return lines[0] + (n ? ` +${n} more` : '')
}
export const W = (e: { w?: number; type: string }) => e.w ?? (e.type === 'note' ? 200 : 150)
export const H = (e: { h?: number; w?: number; type: string }) => e.h ?? (e.type === 'note' ? 120 : W(e) * 1.4)
export function fit(doc: CanvasDocument, width: number, height: number) {
  if (!doc.items.length) return { x: 20, y: 20, s: 1 }
  if (width <= 76 || height <= 28) return null
  const x0 = Math.min(...doc.items.map(e => e.x)), y0 = Math.min(...doc.items.map(e => e.y))
  const w = Math.max(...doc.items.map(e => e.x + W(e))) - x0, h = Math.max(...doc.items.map(e => e.y + H(e))) - y0
  const s = Math.min(1, (width - 76) / Math.max(1, w), (height - 28) / Math.max(1, h))
  return { x: 12 + (width - 76 - w * s) / 2 - x0 * s, y: 14 + (height - 28 - h * s) / 2 - y0 * s, s }
}
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n))
export type Stop = 'closed' | 'half' | 'full' | 'note'
export function stops(bottom: number, top: number, headerBottom: number, inset: number) {
  const full = Math.max(0, bottom - headerBottom - 6), closed = Math.min(full, 62 + inset)
  return { full, closed, half: clamp(Math.round((bottom - top) * .56), closed, full), note: clamp(200 + inset, closed, full) }
}
export function snap(height: number, velocity: number, values: number[], prior: number) {
  const target = clamp(height - velocity * 140, Math.min(...values), Math.max(...values))
  return [...new Set(values)].sort((a, b) => Math.abs(a - target) - Math.abs(b - target) || Number(b === prior) - Number(a === prior) || a - b)[0]
}
