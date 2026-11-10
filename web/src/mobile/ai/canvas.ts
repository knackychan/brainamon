// The phone copy of library/canvas_plan.py and canvas_elements.py. Pure so Node checks both ports.
import { cut, splitJoin, strip } from './quick.ts'

export type RawCanvasProposal = Record<string, unknown>
export type ProposalElement = { kind: 'thumbnail' | 'frame' | 'text' | 'existing'; item_id?: number; frame?: string; text?: string;
  color?: string; id?: string; label?: string; group?: string; order?: number; dx?: number; dy?: number }
export type CanvasProposal = { canvas_id: string | null; new_name: string | null; layout: 'rows' | 'columns'; arrange: boolean; elements: ProposalElement[] }
export type CanvasElement = { id: string; type: 'image' | 'note'; x: number; y: number; w: number; h: number;
  source?: 'db' | 'file'; item_id?: number; uid?: string; file_path?: string; label?: string; text?: string; color?: string; dx?: number; dy?: number }
export type CanvasDocument = { id: string; name: string; created?: number; modified?: number; items: CanvasElement[]; phone_ops?: Record<string, string>; [k: string]: unknown }
export type ItemView = { id: number; uid?: string; title?: string; short_desc?: string; ai_desc?: string; description?: string; url?: string }
export type PreviewElement = ProposalElement & { title?: string; type?: string; file_path?: string }

const CID = /^[A-Za-z0-9_-]{1,64}$/u, COLOR = /^#[0-9A-Fa-f]{6}$/u
const FRAME = /^[A-Za-z0-9_.-]+\.(jpg|jpeg|png|bmp|webp)$/iu
const KIND_KEYS: Record<string, string[]> = {
  thumbnail: ['item_id', 'label', 'group', 'order', 'x', 'y'],
  frame: ['item_id', 'frame', 'label', 'group', 'order', 'x', 'y'],
  text: ['text', 'color', 'group', 'order', 'x', 'y'],
  existing: ['id', 'group', 'order'],
}
const own = (v: object, k: string) => Object.prototype.hasOwnProperty.call(v, k)
const line = (v: unknown, n: number) => cut(splitJoin(String(v || '')), n)
const points = (s: string) => [...s].length
const safe = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v)
const pyTruthy = (v: unknown) => Array.isArray(v) ? v.length > 0 : obj(v) ? Object.keys(v).length > 0 : !!v
const error = (problems: string[]) => { throw new Error('Canvas proposal refused, nothing was changed:\n- ' + problems.slice(0, 10).join('\n- ') + (problems.length > 10 ? `\n- and ${problems.length - 10} more` : '')) }
const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

// library/mirror._json: keys sorted as text at every depth, no spaces, non-ASCII kept. Written out by
// hand because a rebuilt object puts number-like keys ("3", "12") first in numeric order.
export const canonJson = (v: unknown): string => Array.isArray(v) ? `[${v.map(x => x === undefined ? 'null' : canonJson(x)).join(',')}]`
  : obj(v) ? `{${Object.keys(v).filter(k => v[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonJson(v[k])}`).join(',')}}`
  : JSON.stringify(v) ?? 'null'

// the receipt hash server/intake.py gives one canvas change (sha256 of its wire form)
export async function canvasHash(e: { op: string; op_id?: string; canvas_id?: string; at: number; proposal?: unknown; refs?: unknown; sizes?: unknown }): Promise<string> {
  const wire = { op: e.op, op_id: e.op_id, canvas_id: e.canvas_id, at: e.at, proposal: e.proposal, refs: e.refs, sizes: e.sizes }
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonJson(wire))))
  return [...hash].map(b => b.toString(16).padStart(2, '0')).join('')
}

export function normalizeCanvas(raw: unknown): CanvasProposal {
  if (!obj(raw)) throw Object.assign(new Error('Give a canvas proposal object.'), { displayKey: 'common.error.canvasProposalObject' })
  const problems: string[] = []
  const extra = Object.keys(raw).filter(k => !['canvas_id', 'new_name', 'layout', 'arrange', 'elements'].includes(k))
  if (extra.length) problems.push(`unknown field(s): ${extra.sort().join(', ')}`)
  for (const k of ['canvas_id', 'new_name']) if (raw[k] != null && typeof raw[k] !== 'string') problems.push(`${k} must be a string`)
  const cid = strip(String(raw.canvas_id || '')), name = line(raw.new_name, 10000)
  if (!!cid === !!name) problems.push('give exactly one of canvas_id (an existing canvas) or new_name (a new canvas)')
  if (cid && !CID.test(cid)) problems.push('canvas_id is not a canvas id (list_canvases gives the ids)')
  if (points(name) > 80) problems.push('new_name is longer than 80 characters')
  const layout = pyTruthy(raw.layout) ? raw.layout : 'rows'
  if (layout !== 'rows' && layout !== 'columns') problems.push('layout must be one of rows, columns')
  let arrange = raw.arrange ?? false
  if (typeof arrange !== 'boolean') { problems.push('arrange must be true or false'); arrange = false }
  else if (arrange && !cid) problems.push('arrange works only on an existing canvas (canvas_id)')
  let elements: unknown[] = Array.isArray(raw.elements) ? raw.elements : []
  if (!Array.isArray(elements) || !elements.length) { problems.push('elements must be a non-empty list'); elements = [] }
  if (elements.length > 60) { problems.push(`at most 60 elements per proposal (got ${elements.length})`); elements = elements.slice(0, 60) }
  const out: ProposalElement[] = [], groups: string[] = [], seen = new Set<string>()
  let notes = 0
  for (let i = 0; i < elements.length; i++) {
    const v = elements[i], at = `element ${i + 1}`
    if (!obj(v)) { problems.push(`${at}: not an object`); continue }
    const kind = v.kind
    if (typeof kind !== 'string' || !own(KIND_KEYS, kind)) { problems.push(`${at}: kind must be one of thumbnail, frame, text, existing`); continue }
    const bad = Object.keys(v).filter(k => k !== 'kind' && !KIND_KEYS[kind].includes(k))
    if (bad.length) problems.push(`${at}: field(s) not allowed for ${kind}: ${bad.sort().join(', ')}`)
    for (const k of ['frame', 'text', 'color', 'id', 'label', 'group']) if (v[k] != null && typeof v[k] !== 'string') problems.push(`${at}: ${k} must be a string`)
    const e: ProposalElement = { kind: kind as ProposalElement['kind'] }
    if (kind === 'thumbnail' || kind === 'frame') {
      if (!safe(v.item_id)) problems.push(`${at}: item_id must be an integer item id`)
      else e.item_id = v.item_id as number
    }
    if (kind === 'frame') {
      const frame = String(v.frame || '')
      if (!FRAME.test(frame) || frame.includes('..')) problems.push(`${at}: frame must be a frame file name from list_frames (e.g. frame_001.jpg)`)
      else e.frame = frame
    }
    if (kind === 'text') {
      const text = strip(String(v.text || ''))
      if (!text) problems.push(`${at}: text is empty`)
      else if (points(text) > 1000) problems.push(`${at}: text is longer than 1000 characters`)
      e.text = text
      if (v.color != null) {
        if (!COLOR.test(String(v.color))) problems.push(`${at}: color must look like #FFF9C4`)
        else e.color = String(v.color)
      }
      notes++
    }
    if (kind === 'existing') {
      const id = String(v.id || '')
      if (!arrange) problems.push(`${at}: existing elements move only with arrange: true`)
      if (!CID.test(id)) problems.push(`${at}: id must be an element id from read_canvas`)
      else if (seen.has(id)) problems.push(`${at}: element ${id} appears twice`)
      seen.add(id); e.id = id
    }
    if (v.label != null && (kind === 'thumbnail' || kind === 'frame')) e.label = line(v.label, 80)
    if (v.group != null) {
      const group = line(v.group, 80)
      if (!group) problems.push(`${at}: group is empty`)
      else { e.group = group; if (!groups.includes(group)) groups.push(group) }
    }
    if (v.order != null) {
      if (!safe(v.order)) problems.push(`${at}: order must be an integer`)
      else e.order = v.order as number
    }
    if (own(v, 'x') || own(v, 'y')) {
      if (!own(v, 'x') || !own(v, 'y') || !safe(v.x) || !safe(v.y) || (v.x as number) < 0 || (v.x as number) > 20000 || (v.y as number) < 0 || (v.y as number) > 20000)
        problems.push(`${at}: x and y go together, integers from 0 to 20000`)
      else if (e.group) problems.push(`${at}: give either a group or x/y, not both`)
      else { e.dx = v.x as number; e.dy = v.y as number }
    }
    out.push(e)
  }
  if (groups.length > 12) problems.push('at most 12 groups (sections) per proposal')
  if (notes + groups.length > 20) problems.push('at most 20 text notes per proposal, section titles included')
  if (problems.length) error(problems)
  return { canvas_id: cid || null, new_name: name || null, layout: layout as 'rows' | 'columns', arrange: arrange as boolean, elements: out }
}

export function canvasSections<T>(pairs: [ProposalElement, T][]): [{ title: string | null; elements: T[] }[], T[]] {
  const groups = new Map<string | null, [number, number, T][]>(), explicit: T[] = []
  pairs.forEach(([p, value], i) => {
    if (p.dx !== undefined) { explicit.push(value); return }
    const key = p.group ?? null
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push([p.order ?? 1e9, i, value])
  })
  const keys: (string | null)[] = [...groups.keys()].filter(k => k !== null)
  if (groups.has(null)) keys.push(null)
  return [keys.map(k => ({ title: k, elements: groups.get(k)!.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(x => x[2]) })), explicit]
}

export const pyRound = (v: number) => {
  const lo = Math.floor(v), frac = v - lo
  return frac < 0.5 ? lo : frac > 0.5 ? lo + 1 : lo % 2 === 0 ? lo : lo + 1
}
export const footprint = (e: Pick<CanvasElement, 'type' | 'h'>): [number, number] => e.type === 'image' ? [22, 22 + Math.max(40, e.h) + 34] : [0, e.h]
export const origin = (staying: CanvasElement[]): [number, number] => !staying.length ? [40, 40]
  : [Math.max(...staying.map(e => e.x + (e.w ?? 150))) + 80, Math.min(...staying.map(e => e.y))]

export function arrange(sections: { title: string | null; elements: CanvasElement[] }[], at: [number, number], layout: 'rows' | 'columns', explicit: CanvasElement[] = []): CanvasElement[] {
  let [x, y] = at, exBottom = y
  const out: CanvasElement[] = []
  for (const e of explicit) {
    const [top, h] = footprint(e), bx = x + (e.dx ?? 0), by = y + (e.dy ?? 0)
    e.x = pyRound(bx); e.y = pyRound(by + top); delete e.dx; delete e.dy
    exBottom = Math.max(exBottom, by + h); out.push(e)
  }
  if (out.length) y = exBottom + 80
  for (const sec of sections) {
    let title: CanvasElement | null = null
    if (sec.title) { title = { id: '', type: 'note', text: sec.title, color: '#FFF9C4', w: 240, h: 72, x: pyRound(x), y: pyRound(y) }; out.push(title) }
    if (layout === 'columns') {
      const top = y + (title ? 100 : 0)
      let cx = x, right = x + (title?.w ?? 0)
      for (let i = 0; i < sec.elements.length; i += 8) {
        const chunk = sec.elements.slice(i, i + 8); let cy = top
        for (const e of chunk) { const [ft, fh] = footprint(e); e.x = pyRound(cx); e.y = pyRound(cy + ft); cy += fh + 28; out.push(e) }
        right = Math.max(right, cx + Math.max(...chunk.map(e => e.w ?? 150)))
        cx = right + 60
      }
      x = right + 80
    } else {
      const sx = x + (title ? title.w + 28 : 0)
      let bottom = y + (title ? 72 : 0), ly = y
      for (let i = 0; i < sec.elements.length; i += 8) {
        const chunk = sec.elements.slice(i, i + 8); let lx = sx
        for (const e of chunk) { e.x = pyRound(lx); e.y = pyRound(ly + footprint(e)[0]); lx += (e.w ?? 150) + 28; out.push(e) }
        bottom = Math.max(bottom, ly + Math.max(...chunk.map(e => footprint(e)[1])))
        ly = bottom + 60
      }
      y = bottom + 80
    }
  }
  return out
}

export function canvasView(doc: CanvasDocument, itemId: (id: number) => number | null = id => id) {
  const els = doc.items.filter(e => !!e && typeof e === 'object')
  return { id: doc.id, name: doc.name, count: els.length, shown: Math.min(150, els.length), truncated: els.length > 150,
    elements: els.slice(0, 150).map(e => ({ id: e.id, type: e.type, ...(e.type === 'image' ? (e.source === 'db' ? { item_id: itemId(e.item_id ?? 0) } : { file_path: e.file_path }) : {}),
      ...(e.label ? { label: line(e.label, 80) } : {}), ...(e.type === 'note' ? { text: line(e.text, 300) } : {}),
      x: pyRound(Number(e.x || 0)), y: pyRound(Number(e.y || 0)), w: pyRound(Number(e.w || 0)), h: pyRound(Number(e.h || 0)) })) }
}

export function checkCanvas(p: CanvasProposal, base: CanvasDocument | null, names: { id: string; name: string }[],
  items: Map<number, ItemView>, sizes: Map<number, [number, number]>, frames: Set<string> = new Set()) {
  if (p.canvas_id && (!base || base.id !== p.canvas_id || !Array.isArray(base.items))) error([`no canvas with id ${p.canvas_id} (list_canvases gives the ids)`])
  if (!p.canvas_id) {
    const found = names.find(r => strip(r.name).toLowerCase() === p.new_name?.toLowerCase())
    if (found) error([`a canvas named '${found.name}' exists: add to it with canvas_id ${found.id}, or choose another new_name`])
  }
  const have = new Map((base?.items ?? []).map(e => [e.id, e])), problems: string[] = []
  for (const [i, e] of p.elements.entries()) {
    const at = `element ${i + 1}`
    if (e.item_id !== undefined && !items.has(e.item_id)) problems.push(`${at}: no item with id ${e.item_id}`)
    else if (e.kind === 'thumbnail' && !sizes.has(e.item_id!)) problems.push(`${at}: item ${e.item_id} has no thumbnail yet (Fetch link info makes one)`)
    else if (e.kind === 'frame' && !frames.has(`${e.item_id}/${e.frame}`)) problems.push(`${at}: item ${e.item_id} has no frame named ${e.frame}`)
    else if (e.kind === 'existing' && !have.has(e.id!)) problems.push(`${at}: no element ${e.id} on this canvas`)
  }
  if (problems.length) error(problems)
  const explicit = p.elements.filter(e => e.dx !== undefined).map(e => {
    const size = e.kind === 'thumbnail' ? sizes.get(e.item_id!) : null
    const w = e.kind === 'thumbnail' ? 220 : e.kind === 'frame' ? 200 : 240
    const h = size ? pyRound(w * size[1] / size[0]) : e.kind === 'frame' ? 150 : 160
    return [e.dx!, e.dy!, w, e.kind === 'text' ? h : 22 + Math.max(40, h) + 34]
  })
  for (let i = 0; i < explicit.length; i++) for (const b of explicit.slice(i + 1)) {
    const a = explicit[i]
    if (a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3]) error(['elements placed with x/y overlap each other: space them out or use groups'])
  }
  const view = (e: ProposalElement): PreviewElement => {
    const v: PreviewElement = { ...e }
    if (e.item_id !== undefined) v.title = line(items.get(e.item_id)?.title || items.get(e.item_id)?.short_desc || items.get(e.item_id)?.ai_desc || items.get(e.item_id)?.description || items.get(e.item_id)?.url, 80)
    if (e.kind === 'existing') { const old = have.get(e.id!)!; v.type = old.type; v.text = line(old.text || old.label, 300); v.item_id = old.item_id; v.file_path = old.file_path }
    return v
  }
  const [sections, ex] = canvasSections(p.elements.map(e => [e, view(e)]))
  const count = (k: string) => p.elements.filter(e => e.kind === k).length
  return { target: { id: p.canvas_id, name: base?.name || p.new_name || '', new: !base, count: base?.items.length ?? 0 },
    layout: p.layout, arrange: p.arrange,
    counts: { thumbnail: count('thumbnail'), frame: count('frame'), text: count('text'), sections: sections.filter(s => s.title).length, moves: count('existing') },
    sections, explicit: ex }
}

export function applyCanvasLocal(p: CanvasProposal, base: CanvasDocument | null, sizes: Map<number, [number, number]>, opId: string, canvasId: string, at: number): CanvasDocument {
  const doc: CanvasDocument = base ? structuredClone(base) : { id: canvasId, name: p.new_name || '', created: at, items: [] }
  const have = new Map(doc.items.map(e => [e.id, e])), built: CanvasElement[] = []
  for (const e of p.elements) {
    if (e.kind === 'frame') throw Object.assign(new Error('Extracted frames are unavailable in the phone library. Use thumbnails or text.'), { displayKey: 'common.error.canvasFrames' })
    const old = e.kind === 'existing' ? have.get(e.id!) : null
    if (e.kind === 'existing' && !old) throw Object.assign(new Error(`No element ${e.id} on this canvas.`), { displayKey: 'common.error.canvasElementMissing', displayParams: { id: e.id } })
    const dims = e.kind === 'thumbnail' ? sizes.get(e.item_id!) : null
    const el: CanvasElement = old ?? (e.kind === 'thumbnail'
      ? { id: '', type: 'image', source: 'db', item_id: e.item_id, label: e.label ?? '', w: 220, h: dims ? pyRound(220 * dims[1] / dims[0]) : 165, x: 0, y: 0 }
      : { id: '', type: 'note', text: e.text, color: e.color ?? '#FFF9C4', w: 240, h: 160, x: 0, y: 0 })
    if (e.dx !== undefined) { el.dx = e.dx; el.dy = e.dy }
    built.push(el)
  }
  const moved = new Set(p.elements.filter(e => e.kind === 'existing').map(e => e.id))
  const staying = doc.items.filter(e => !moved.has(e.id))
  const [secs, ex] = canvasSections(p.elements.map((e, i) => [e, built[i]]))
  const placed = arrange(secs, origin(staying), p.layout, ex)
  const added = placed.filter(e => !moved.has(e.id))
  added.forEach((e, i) => { e.id = `${opId}_${i}` })
  doc.items.push(...added)
  doc.modified = at
  return doc
}
