// A deliberately bounded editor adapter. Markdown stays authoritative; display renderers are lossy.
import { ANCHOR_MAX, INKS, MARKS, type Stamp } from './note-format.ts'

export type Run = { text: string; marks: string[]; raw?: string }
export type Block = { kind: string; runs: Run[]; checked?: boolean; number?: number }
export type Point = { block: number; offset: number }
export type Selection = { anchor: Point; focus: Point }
export type Parsed = { ok: true; blocks: Block[] } | { ok: false; reason: string }
export const GRID = 24
const FAIL = 'This note uses Markdown outside Write’s supported format. Edit it in Markdown; Preview is still available.'
const same = (a: Run, b: Run) => !a.raw && !b.raw && a.marks.join('|') === b.marks.join('|')

export function mergeRuns(runs: Run[]): Run[] {
  const out: Run[] = []
  for (const run of runs) {
    if (!run.text) continue
    const r = { ...run, marks: [...new Set(run.marks)].filter((m, i, all) => !m.includes(':') || !all.slice(i + 1).some(n => n.startsWith(m.split(':')[0] + ':'))).sort() }
    const prev = out.at(-1)
    if (prev && same(prev, r)) prev.text += r.text
    else out.push(r)
  }
  return out
}

function inline(source: string, marks: string[] = []): Run[] {
  const out: Run[] = []
  const add = (text: string, raw?: string) => out.push({ text, marks: [...marks], ...(raw ? { raw } : {}) })
  let i = 0
  while (i < source.length) {
    const rest = source.slice(i)
    if (rest[0] === '\\' && rest.length > 1 && /[\\`*_{}[\]()#+.!<>~=-]/.test(rest[1])) {
      add(rest[1]); i += 2; continue
    }
    const code = rest.match(/^(`+)([\s\S]*?)\1(?!`)/)
    if (code) {
      let text = code[2]
      if (text.startsWith(' ') && text.endsWith(' ') && text.trim()) text = text.slice(1, -1)
      out.push({ text, marks: ['code'] }); i += code[0].length; continue
    }
    const raw = rest.match(/^\[[^\]\n]*\]\((?:https?:\/\/|mailto:)[^\s)]+\)|^\[(?:id\s+\d+|note:\s*[^\]\n]+)\]/i)
    if (raw) { add(raw[0], raw[0]); i += raw[0].length; continue }
    if (/^\[[^\]]*\]\(/.test(rest)) throw new Error(FAIL)
    const tag = rest.match(/^<u>|^<mark data-mark="([^"]+)">|^<span data-ink="([^"]+)">/)
    if (tag) {
      const mark = tag[1] ? `mark:${tag[1]}` : tag[2] ? `ink:${tag[2]}` : 'u'
      if ((tag[1] && !(MARKS as readonly string[]).includes(tag[1])) || (tag[2] && !(INKS as readonly string[]).includes(tag[2]))) throw new Error(FAIL)
      const close = tag[1] ? '</mark>' : tag[2] ? '</span>' : '</u>'
      // Match nested tags of the same type as well as mixed marks.
      const openName = tag[0].slice(0, tag[0].indexOf(' ') > 0 ? tag[0].indexOf(' ') : tag[0].length - 1)
      let depth = 1, end = i + tag[0].length
      for (; end < source.length; end++) {
        if (source.startsWith(close, end) && --depth === 0) break
        if (source.startsWith(openName, end) && /[ >]/.test(source[end + openName.length] || '')) depth++
      }
      if (depth) throw new Error(FAIL)
      out.push(...inline(source.slice(i + tag[0].length, end), [...marks, mark]))
      i = end + close.length; continue
    }
    if (/^<\/?[a-zA-Z!]/.test(rest)) throw new Error(FAIL)
    let paired = false
    for (const [delimiter, style] of [['***', 'b,i'], ['___', 'b,i'], ['**', 'b'], ['__', 'b'], ['~~', 's'], ['==', 'mark:sun'], ['*', 'i'], ['_', 'i']]) {
      if (!rest.startsWith(delimiter) || /\s/.test(rest[delimiter.length] || ' ')) continue
      if (delimiter.includes('_') && !marks.length && i > 0 && /\w/.test(source[i - 1])) continue
      let end = source.indexOf(delimiter, i + delimiter.length)
      while (end >= 0 && (source[end - 1] === '\\' || /\s/.test(source[end - 1]))) end = source.indexOf(delimiter, end + delimiter.length)
      if (end <= i + delimiter.length) continue
      out.push(...inline(source.slice(i + delimiter.length, end), [...marks, ...style.split(',')]))
      i = end + delimiter.length; paired = true; break
    }
    if (!paired) { add(source[i]); i++ }
  }
  return mergeRuns(out)
}

export function parseMarkdown(body: string): Parsed {
  try {
    const blocks: Block[] = []
    for (const line of body.split(/\r?\n/)) {
      if (/^(?:\t| {4}| {1,3}(?:[-*+] |\d+[.)] ))|^\s*(?:`{3}|~{3}|#{4,6}(?: |$)|!\[|\||\[[^\]]+\]:)|\S\s*\|.*\||^\s*>\s*>/.test(line)) throw new Error(FAIL)
      if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) { blocks.push({ kind: 'hr', runs: [] }); continue }
      // Setext headings, tables and HTML spanning rows cannot be flattened into editable lines.
      if (/^\s*(?:=+|-+)\s*$/.test(line) && blocks.at(-1)?.runs.length) throw new Error(FAIL)
      const h = line.match(/^(#{1,3}) (.*)$/)
      const q = line.match(/^> ?(.*)$/)
      const task = line.match(/^[-*+] \[([ xX])\] ?(.*)$/)
      const bullet = line.match(/^[-*+•] (.*)$/)
      const number = line.match(/^(\d+)[.)] (.*)$/)
      const kind = h ? `h${h[1].length}` : q ? 'quote' : task ? 'task' : bullet ? 'bullet' : number ? 'number' : 'p'
      const text = h ? h[2] : q ? q[1] : task ? task[2] : bullet ? bullet[1] : number ? number[2] : line
      if (h && / +#+\s*$/.test(text)) throw new Error(FAIL)
      blocks.push({ kind, runs: inline(text), ...(task ? { checked: task[1].toLowerCase() === 'x' } : {}), ...(number ? { number: +number[1] } : {}) })
    }
    // Cross-line emphasis would otherwise appear to be harmless literal delimiters.
    const across = body.replace(/`[^`\n]*`/g, '').replace(/\\./g, '')
    if (/(\*\*|__|~~|==|(?<!\*)\*(?!\*)|(?<!\w)_(?!_))[^\n]*\n[\s\S]*?\1/.test(across)) {
      const singles = body.split(/\r?\n/).some(l => {
        const parsed = inline(l)
        return parsed.some(r => !r.marks.length && /(?:\*\*|__|~~|==)/.test(r.text))
      })
      if (singles) throw new Error(FAIL)
    }
    return { ok: true, blocks }
  } catch { return { ok: false, reason: FAIL } }
}

function escaped(text: string): string {
  return text.replace(/[\\`*_~=<\[\]]/g, '\\$&')
}

export function serializeMarkdown(blocks: Block[]): string {
  return blocks.map(block => {
    if (block.kind === 'hr') return '---'
    const priority = (m: string) => m.startsWith('mark:') ? 0 : m.startsWith('ink:') ? 1 : m === 'u' ? 2 : m === 'b' ? 3 : m === 's' ? 4 : m === 'i' ? 5 : 6
    const runs = mergeRuns(block.runs).map(r => ({ ...r, marks: [...r.marks].sort((a,b) => priority(a) - priority(b)) }))
    function encode(items: Run[], ancestors: string[] = []): string {
      let out = ''
      for (let i = 0; i < items.length;) {
        const run = items[i], mark = run.marks[0]
        if (!mark) { out += run.raw === run.text ? run.raw : escaped(run.text); i++; continue }
        if (mark === 'code') {
          const ticks = '`'.repeat(Math.max(0, ...(run.text.match(/`+/g) || []).map(x => x.length)) + 1)
          const pad = run.text.startsWith('`') || run.text.endsWith('`') || (run.text.startsWith(' ') && run.text.endsWith(' ') && !!run.text.trim()) ? ' ' : ''
          out += ticks + pad + run.text + pad + ticks; i++; continue
        }
        let end = i + 1
        while (end < items.length && items[end].marks[0] === mark) end++
        let group = items.slice(i, end).map(r => ({...r, marks:r.marks.slice(1)}))
        let leading = '', trailing = ''
        // Markdown delimiters cannot enclose boundary whitespace. Keep every space outside them.
        if (['b','i','s','mark:sun'].includes(mark)) {
          const text = group.map(r => r.text).join('')
          leading = text.match(/^\s*/)?.[0] || ''
          trailing = text.slice(leading.length).match(/\s*$/)?.[0] || ''
          group = sliceRuns(group, leading.length, text.length - trailing.length)
        }
        const inner = encode(group, [...ancestors, mark])
        const italic = ancestors.includes('b') ? '_' : '*'
        const pair = mark === 'b' ? ['**','**'] : mark === 'i' ? [italic,italic] : mark === 's' ? ['~~','~~'] : mark === 'u' ? ['<u>','</u>'] : mark === 'mark:sun' ? ['==','=='] : mark.startsWith('mark:') ? [`<mark data-mark="${mark.slice(5)}">`,'</mark>'] : mark.startsWith('ink:') ? [`<span data-ink="${mark.slice(4)}">`,'</span>'] : null
        if (!pair) throw new Error('Unknown editor mark')
        out += escaped(leading) + (inner ? pair[0] + inner + pair[1] : '') + escaped(trailing)
        i = end
      }
      return out
    }
    let out = encode(runs)
    const prefix = block.kind.startsWith('h') ? '#'.repeat(+block.kind[1]) + ' ' : block.kind === 'quote' ? '> ' : block.kind === 'bullet' ? '- ' : block.kind === 'number' ? `${block.number ?? 1}. ` : block.kind === 'task' ? `- [${block.checked ? 'x' : ' '}] ` : ''
    if (!prefix) out = out.replace(/^(#{1,6}|>|[-+]|\d+[.)])(?= )/, '\\$1').replace(/^(-{3,}|\*{3,})$/, '\\$1')
    return prefix + out
  }).join('\n')
}

const tags: Record<string, string> = { p: 'p', h1: 'h1', h2: 'h2', h3: 'h3', quote: 'blockquote', bullet: 'li', number: 'li', task: 'li', hr: 'hr' }

export function writeDOM(root: HTMLElement, blocks: Block[]) {
  const doc = root.ownerDocument, fragment = doc.createDocumentFragment()
  let list: HTMLElement | null = null, previous = ''
  for (const block of blocks) {
    const el = doc.createElement(tags[block.kind] || 'p')
    el.dataset.block = block.kind
    if (block.kind === 'task') {
      const button = doc.createElement('button')
      button.type = 'button'; button.contentEditable = 'false'; button.dataset.task = ''
      button.setAttribute('aria-label', 'Toggle task'); button.setAttribute('aria-pressed', String(!!block.checked))
      button.textContent = block.checked ? '✓' : ''; el.append(button)
    }
    for (const run of block.runs) {
      let node: Node = doc.createTextNode(run.text)
      if (run.raw) { const literal = doc.createElement('span'); literal.dataset.raw = run.raw; literal.append(node); node = literal }
      for (const mark of [...run.marks].reverse()) {
        const tag = mark === 'code' ? 'code' : mark.startsWith('ink:') ? 'span' : mark.startsWith('mark:') ? 'mark' : mark
        const wrapper = doc.createElement(tag)
        if (mark.startsWith('ink:')) wrapper.dataset.ink = mark.slice(4)
        if (mark.startsWith('mark:')) wrapper.dataset.mark = mark.slice(5)
        wrapper.append(node); node = wrapper
      }
      el.append(node)
    }
    if (!block.runs.length && block.kind !== 'hr') el.append(doc.createElement('br'))
    if (['bullet', 'number', 'task'].includes(block.kind)) {
      if (!list || previous !== block.kind) {
        list = doc.createElement(block.kind === 'number' ? 'ol' : 'ul')
        if (block.kind === 'number') list.setAttribute('start', String(block.number ?? 1))
        fragment.append(list)
      }
      list.append(el)
    } else { list = null; fragment.append(el) }
    previous = block.kind
  }
  root.replaceChildren(fragment)
}

export function readDOM(root: HTMLElement): Block[] {
  const blocks: Block[] = []
  function runs(node: Node, marks: string[] = []): Run[] {
    if (node.nodeType === 3) return [{ text: node.textContent || '', marks }]
    if (node.nodeType !== 1) throw new Error('Unsupported editing content; the last good Markdown was kept.')
    const el = node as HTMLElement, tag = el.tagName.toLowerCase()
    if (tag === 'button' && el.hasAttribute('data-task')) return []
    if (tag === 'br') return [{ text: '\n', marks }]
    const style = ({ b: 'b', strong: 'b', i: 'i', em: 'i', u: 'u', s: 's', del: 's', code: 'code' } as Record<string, string>)[tag]
      || (tag === 'span' && (INKS as readonly string[]).includes(el.dataset.ink || '') ? `ink:${el.dataset.ink}` : '')
      || (tag === 'mark' && (MARKS as readonly string[]).includes(el.dataset.mark || '') ? `mark:${el.dataset.mark}` : '')
    if (el.hasAttribute('style') || [...el.attributes].some(a => /^on/i.test(a.name))) throw new Error('Unsupported editing content; the last good Markdown was kept.')
    if (!style && !(tag === 'span' && el.dataset.raw)) throw new Error('Unsupported editing content; the last good Markdown was kept.')
    if (el.dataset.raw) return [{ text: el.textContent || '', marks, ...(el.textContent === el.dataset.raw ? { raw: el.dataset.raw } : {}) }]
    return [...el.childNodes].flatMap(n => runs(n, [...marks, style]))
  }
  function block(el: HTMLElement, kind?: string, number?: number) {
    const k = kind || ({ DIV: 'p', P: 'p', H1: 'h1', H2: 'h2', H3: 'h3', BLOCKQUOTE: 'quote', HR: 'hr' } as Record<string, string>)[el.tagName]
    if (!k) throw new Error('Unsupported editing content; the last good Markdown was kept.')
    let r = [...el.childNodes].flatMap(n => runs(n))
    if (el.lastChild?.nodeName === 'BR') r = r.slice(0, -1)
    // A browser Shift+Enter is represented as separate Markdown rows, including their marks.
    const rows: Run[][] = [[]]
    for (const run of r) run.text.split('\n').forEach((text, i) => { if (i) rows.push([]); rows.at(-1)!.push({ ...run, text }) })
    for (const row of rows) blocks.push({ kind: k, runs: mergeRuns(row), ...(k === 'task' ? { checked: el.querySelector('[data-task]')?.getAttribute('aria-pressed') === 'true' } : {}), ...(k === 'number' ? { number } : {}) })
  }
  for (const node of root.childNodes) {
    if (node.nodeType === 3) { blocks.push({ kind: 'p', runs: [{ text: node.textContent || '', marks: [] }] }); continue }
    if (node.nodeType !== 1) throw new Error('Unsupported editing content')
    const el = node as HTMLElement
    if (el.tagName === 'UL' || el.tagName === 'OL') {
      let n = +(el.getAttribute('start') || 1)
      for (const li of el.children) {
        if (li.tagName !== 'LI') throw new Error('Unsupported editing content')
        block(li as HTMLElement, li.querySelector('[data-task]') ? 'task' : el.tagName === 'OL' ? 'number' : 'bullet', n++)
      }
    } else block(el)
  }
  return blocks.length ? blocks : [{ kind: 'p', runs: [] }]
}

export function blockElements(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('p,h1,h2,h3,blockquote,li,hr,div')].filter(e => e.parentElement === root || ['UL', 'OL'].includes(e.parentElement?.tagName || ''))
}

function texts(root: HTMLElement): Text[] {
  const walk = root.ownerDocument.createTreeWalker(root, 4)
  const out: Text[] = []; let n: Node | null
  while ((n = walk.nextNode())) if (!(n.parentElement?.closest('[data-task]'))) out.push(n as Text)
  return out
}

export function rememberSelection(root: HTMLElement): Selection | null {
  const sel = root.ownerDocument.getSelection()
  if (!sel?.anchorNode || !sel.focusNode || !root.contains(sel.anchorNode) || !root.contains(sel.focusNode)) return null
  const els = blockElements(root)
  function point(node: Node, offset: number): Point {
    let block = els.findIndex(el => el === node || el.contains(node))
    if (block < 0) return { block: Math.min(offset, els.length - 1), offset: 0 }
    const range = root.ownerDocument.createRange(); range.selectNodeContents(els[block]); range.setEnd(node, offset)
    const fragment = range.cloneContents(); fragment.querySelectorAll('[data-task]').forEach(e => e.remove())
    return { block, offset: fragment.textContent?.length || 0 }
  }
  return { anchor: point(sel.anchorNode, sel.anchorOffset), focus: point(sel.focusNode, sel.focusOffset) }
}

export function restoreSelection(root: HTMLElement, selection: Selection | null) {
  root.focus()
  if (!selection) return
  const els = blockElements(root)
  function locate(p: Point): [Node, number] {
    const el = els[Math.min(p.block, els.length - 1)] || root
    let offset = p.offset
    for (const t of texts(el)) { if (offset <= t.length) return [t, offset]; offset -= t.length }
    return [el, el.childNodes.length && el.lastChild?.nodeName === 'BR' ? el.childNodes.length - 1 : el.childNodes.length]
  }
  const [a, ao] = locate(selection.anchor), [f, fo] = locate(selection.focus)
  root.ownerDocument.getSelection()?.setBaseAndExtent(a, ao, f, fo)
}

export function orderedSelection(s: Selection): [Point, Point] {
  return s.anchor.block < s.focus.block || (s.anchor.block === s.focus.block && s.anchor.offset <= s.focus.offset) ? [s.anchor, s.focus] : [s.focus, s.anchor]
}

export function sliceRuns(runs: Run[], start: number, end = Infinity): Run[] {
  let pos = 0
  return runs.flatMap(r => {
    const from = Math.max(0, start - pos), to = Math.min(r.text.length, end - pos); pos += r.text.length
    return to > from ? [{ text: r.text.slice(from, to), marks: [...r.marks], ...(from === 0 && to === r.text.length && r.raw ? { raw: r.raw } : {}) }] : []
  })
}

export type Geometry = { width: number; height: number; textLeft: number; textRight: number; top: number; end: number; headings: { at: string; row: number }[] }
export const headingName = (text: string) => Array.from(text.replace(/\s+/g, ' ').trim()).slice(0, ANCHOR_MAX).join('')
export function anchorRow(at: string, g: Geometry): number {
  return at === 'top' ? g.top : at === 'end' ? g.end : g.headings.find(h => h.at === at)?.row ?? g.end
}
export function stampPosition(st: Stamp, g: Geometry): { left: number; top: number } {
  const size = st.s * GRID
  return { left: Math.max(0, Math.min(g.width - size, (st.x < 0 ? g.width : g.textLeft) + st.x * GRID)), top: Math.max(0, Math.min(Math.max(g.height, g.end + size + GRID) - size, anchorRow(st.at, g) + st.y * GRID)) }
}
export function stampFromPoint(st: Stamp, left: number, top: number, g: Geometry): Stamp {
  const heading = [...g.headings].reverse().find(h => h.row <= top)
  const at = heading?.at || 'top'
  const x = left >= g.textRight ? Math.min(-1, Math.round((left - g.width) / GRID)) : Math.max(0, Math.round((left - g.textLeft) / GRID))
  return { ...st, at, x, y: Math.round((top - anchorRow(at, g)) / GRID) }
}
