// Markdown for report.md and notes, ported from V6 h-know.js mdHTML / mdInline and the shell's
// inline(): headings, bullet, numbered and task lists, quotes, dividers, bold, italics, code, links,
// "No. 1532" / "[id 1532]" as card chips, and the My Notes marks (lib/note-format.ts: <u>, <mark
// data-mark>, <span data-ink>, ==, ~~). The text is HTML-escaped first; only the tags made here reach the page.
import { esc } from './cards/card'
import { lib } from './library.svelte'
import { blocksHTML, marksInline } from './note-format'
import { IC, pxPath } from './px'
import { t } from './i18n/index'
import './note-marks.css'

// Where a card chip finds its item: the desktop's Library store by default; the phone
// (src/mobile, its own row store) registers its lookup with setCardLookup.
export interface ChipRow { title: string; cat: string; tint?: string }
let lookup: (n: number) => ChipRow | undefined = n => {
  const r = lib.byId.get(n)
  return r && { title: r.title, cat: r.cat, tint: lib.tints[String(n)] }
}
export function setCardLookup(fn: typeof lookup) { lookup = fn }

export function cardChip(n: number): string {
  const r = lookup(n)
  if (!r) return `<span class="cite miss" title="${esc(t('wiskit.citation.missing'))}">No.${n}?</span>`
  const tint = r.tint || TYPE[r.cat] || '#9cc4e2'
  return `<button type="button" class="cite" data-cid="${n}" aria-label="No.${n}, ${esc(r.title)}"><i style="background:${esc(tint)}"></i>No.${n}</button>`
}

const CITE_RE = /\[\s*(?:ids?|no\.?)\s*:?\s*(\d{1,6}(?:\s*(?:,|and|&amp;|&|;)\s*(?:(?:ids?|no\.?)\s*:?\s*)?\d{1,6})*)\s*\]/gi

// `s` is already escaped
export function mdInline(s: string): string {
  return marksInline(s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(?<![="'>])\bhttps?:\/\/[^\s<)]*[^\s<).,;:!?]/g, '<a href="$&" target="_blank" rel="noopener noreferrer">$&</a>')
    .replace(CITE_RE, (_, g: string) => (g.match(/\d{1,6}/g) ?? []).map(n => cardChip(+n)).join(''))
    .replace(/\(No\. ?(\d{1,6})\)/g, (_, d) => cardChip(+d))
    .replace(/\bNo\. (\d{1,6})\b/g, (_, d) => cardChip(+d)))
}

// blocks (lib/note-format.ts blocksHTML): # and ## as h2, deeper as h3, as before
export function mdHTML(body: string): string {
  return blocksHTML(esc(body || ''), mdInline)
}

// ── Wiskit answers (V6 fmtAnswer / inline): paragraphs and bullets, **bold**, [id N] and
// [note: file] as chips, "(general knowledge)" flagged. Headings become plain paragraphs. ──
const NOTE_PX_PATH = pxPath(IC.note)
// `file` is already escaped
export function noteChip(file: string): string {
  const f = file.trim()
  return `<button type="button" class="cite note" data-note="${f}"><svg class="px" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d="${NOTE_PX_PATH}"/></svg>${f}</button>`
}
const NOTE_RE = /\[\s*note\s*:\s*([^\]]+?)\s*\]/gi

// `s` is already escaped
function answerInline(s: string): string {
  return s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(NOTE_RE, (_, f: string) => noteChip(f))
    .replace(CITE_RE, (_, g: string) => (g.match(/\d{1,6}/g) ?? []).map(n => cardChip(+n)).join(''))
    .replace(/\(general knowledge\)/gi, () => `<span class="gk">${esc(t('wiskit.generalKnowledge'))}</span>`)
}

export function fmtAnswer(t: string): string {
  let html = '', list: string | null = null
  const close = () => { if (list !== null) { html += `<ul>${list}</ul>`; list = null } }
  esc(t || '').split('\n').forEach(raw => {
    const l = raw.trim().replace(/^#+\s*/, '')
    const b = l.match(/^(?:[-*•]|\d+[.)])\s+(.*)/)
    if (b) { list = (list ?? '') + `<li>${answerInline(b[1])}</li>`; return }
    close()
    if (l) html += `<p>${answerInline(l)}</p>`
  })
  close()
  return html
}
