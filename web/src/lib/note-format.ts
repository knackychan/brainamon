// The My Notes file format (projects/note-organic-ui/plans/01-note-format-agents.md): Markdown plus
// <u>, <mark data-mark>, <span data-ink>, and the one-line `stamps:` frontmatter value. The same rules
// as core/note_format.py (tests/fixtures/note_format.json checks both), plus the block renderer
// lib/md.ts mdHTML uses. Run by Node in the tests (type stripping): no imports, no enums.

export const INKS = ['graphite', 'indigo', 'sky', 'leaf', 'sun', 'ember', 'rose'] as const
export const MARKS = ['sun', 'mint', 'peach', 'sky'] as const
export const STAMPS = ['flower', 'sun', 'star', 'heart', 'check', 'arrow', 'sprout', 'mushroom', 'cloud', 'bolt',
  'coffee', 'bulb', 'kettlebell', 'pin', 'note', 'question', 'snail', 'sparkle', 'flag', 'smile'] as const
export const SIZES = [2, 3, 4] as const
export const ANCHOR_TOP = 'top', ANCHOR_END = 'end'
export const X_RANGE = [-40, 40] as const
export const Y_RANGE = [-400, 400] as const
export const ANCHOR_MAX = 120
export const MAX_STAMPS = 60
export const DEFAULT_INK = 'indigo'

export type Ink = typeof INKS[number]
export type Mark = typeof MARKS[number]
export interface Stamp { k: string; at: string; x: number; y: number; s: number; c: Ink; r: number }

const TAG = new RegExp(`</?u>|<mark data-mark="(?:${MARKS.join('|')})">|</mark>|<span data-ink="(?:${INKS.join('|')})">|</span>`, 'g')
const HIGHLIGHT = /==(?=\S)(.+?)(?<=\S)==/g
const TASK = /^([ \t]*[-*•][ \t]+)\[[ xX]\][ \t]?/gm

// note_format.plain: words for search, embeddings and Wiskit context
export function plain(body: string): string {
  return (body || '').replace(TAG, '').replace(HIGHLIGHT, '$1').replace(TASK, '$1')
}

// note_format.head / word_count: the phone's note card (plans/08-note-cards.md)
export const HEAD_LINES = 14, HEAD_CHARS = 600
export function head(body: string): string {
  const out: string[] = []
  let size = 0
  for (const line of (body || '').replace(/\r\n/g, '\n').split('\n')) {
    if (!out.length && !line.trim()) continue
    out.push(line)
    size += Array.from(line).length + 1               // code points, as Python len
    if (out.length >= HEAD_LINES || size >= HEAD_CHARS) break
  }
  return out.join('\n').replace(/\s+$/, '')
}
export function wordCount(body: string): number {
  return plain(body).split(/\s+/).filter(t => /[\p{L}\p{N}]/u.test(t)).length
}

function num(v: unknown, lo: number, hi: number, d: number): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return d
  return Math.max(lo, Math.min(hi, Math.floor(v + 0.5)))
}

function anchor(v: unknown): string {
  if (typeof v !== 'string') return ANCHOR_END
  // Python ' '.join(v.split())[:120]: whitespace runs to one space, cut by code points
  return Array.from(v.split(/\s+/).filter(Boolean).join(' ')).slice(0, ANCHOR_MAX).join('') || ANCHOR_END
}

const isIn = <T extends string>(list: readonly T[], v: unknown): v is T => typeof v === 'string' && (list as readonly string[]).includes(v)

export function cleanStamps(items: unknown): Stamp[] {
  const out: Stamp[] = []
  for (const st of Array.isArray(items) ? items : []) {
    if (!st || typeof st !== 'object' || Array.isArray(st) || !isIn(STAMPS, (st as Stamp).k)) continue
    const o = st as Record<string, unknown>
    const r = num(o.r, -90, 90, 0)
    out.push({ k: o.k as string, at: anchor(o.at), x: num(o.x, X_RANGE[0], X_RANGE[1], -4), y: num(o.y, Y_RANGE[0], Y_RANGE[1], 0),
      s: num(o.s, SIZES[0], SIZES[SIZES.length - 1], SIZES[0]), c: isIn(INKS, o.c) ? o.c : DEFAULT_INK, r: r < 0 ? -8 : r > 0 ? 8 : 0 })
    if (out.length === MAX_STAMPS) break
  }
  return out
}

export function parseStamps(value: unknown): Stamp[] {
  if (typeof value !== 'string' || !value.trim()) return []
  try { return cleanStamps(JSON.parse(value)) } catch { return [] }
}

export function dumpStamps(items: unknown): string {
  const s = cleanStamps(items)
  return s.length ? JSON.stringify(s) : ''
}

// ── rendering (the text is HTML-escaped by the caller first; only tags made here reach the page) ──

const E_OPEN = new RegExp(`&lt;(u|mark data-mark=&quot;(${MARKS.join('|')})&quot;|span data-ink=&quot;(${INKS.join('|')})&quot;)&gt;|&lt;/(u|mark|span)&gt;`, 'g')

// the three tags (escaped by esc) back to real ones, balanced: a closer with no matching opener stays
// text, openers left open are closed at the end of the line
export function marksInline(s: string): string {
  const open: string[] = []
  let out = s.replace(E_OPEN, (all, o?: string, mark?: string, ink?: string, c?: string) => {
    if (o) {
      const tag = o === 'u' ? 'u' : mark ? 'mark' : 'span'
      open.push(tag)
      return tag === 'u' ? '<u>' : mark ? `<mark data-mark="${mark}">` : `<span data-ink="${ink}">`
    }
    if (open.length && open[open.length - 1] === c) { open.pop(); return `</${c}>` }
    return all
  })
  while (open.length) out += `</${open.pop()}>`
  return out
    .replace(/~~(?=\S)(.+?)(?<=\S)~~/g, '<s>$1</s>')
    .replace(/==(?=\S)(.+?)(?<=\S)==/g, '<mark data-mark="sun">$1</mark>')
}

// mdHTML's blocks: headings, task / bullet / numbered lists, quotes, dividers, paragraphs.
// `exact` keeps h1 / h2 / h3 (the editor); otherwise # and ## render as h2 and deeper as h3 (as before).
export function blocksHTML(escaped: string, inline: (s: string) => string, exact = false): string {
  let h = '', list: string | null = null, tag = 'ul', check = false
  const close = () => { if (list !== null) { h += `<${tag}${check ? ' class="np-check"' : ''}>${list}</${tag}>`; list = null } }
  const item = (t: string, c: boolean, li: string) => {
    if (list !== null && (tag !== t || check !== c)) close()
    tag = t; check = c; list = (list ?? '') + li
  }
  for (const raw of escaped.split('\n')) {
    const l = raw.trim()
    let m = l.match(/^(#{1,6})\s+(.*)/)
    if (m) { close(); const n = m[1].length, t = exact ? `h${Math.min(n, 3)}` : n < 3 ? 'h2' : 'h3'; h += `<${t}>${inline(m[2])}</${t}>`; continue }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(l)) { close(); h += '<hr>'; continue }
    m = l.match(/^&gt;\s?(.*)/)
    if (m) { close(); h += `<blockquote>${inline(m[1])}</blockquote>`; continue }
    m = l.match(/^[-*•]\s+\[([ xX])\](?:\s+(.*))?$/)
    if (m) { item('ul', true, `<li${m[1] === ' ' ? '' : ' data-done=""'}>${inline(m[2] ?? '')}</li>`); continue }
    m = l.match(/^[-*•]\s+(.*)/)
    if (m) { item('ul', false, `<li>${inline(m[1])}</li>`); continue }
    m = l.match(/^\d+[.)]\s+(.*)/)
    if (m) { item('ol', false, `<li>${inline(m[1])}</li>`); continue }
    close()
    if (l) h += `<p>${inline(l)}</p>`
  }
  close()
  return h
}
