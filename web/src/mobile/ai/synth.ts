// Synthesize on the phone: the TypeScript port of knowledge/synth.py (the labelled parts of a source with
// their caps, batches of 12, the fold prompt, clean), reading the same prompt file (knowledge/prompts/synth.json,
// passed in as `P`). Capped at P.limits.phone_max_sources (36 sources, 3 AI calls); a paired phone queues a
// bigger run for the PC, a phone with no PC refuses it. tests/test_phone_ai.py checks both build the same prompts.
// Run by Node in the tests (type stripping): no parameter properties, imports with .ts.
import { cut, fill, strip, type Item } from './quick.ts'

export interface SynthPrompts {
  limits: { batch_size: number; excerpt_limit: number; title_limit: number; max_tokens: number; phone_max_sources: number; parts: Record<string, number> }
  part_order: string[]; trim_order: string[]; labels: Record<string, string>
  rules: string; source: string; creator: string; url: string; tags: string; category: string; part: string
  first: string; append: string; reorganize: string
}

const len = (s: string) => [...s].length       // code points, as Python's len

export class Synth {
  readonly P: SynthPrompts
  constructor(P: SynthPrompts) { this.P = P }

  get max() { return this.P.limits.phone_max_sources }
  calls(n: number) { return Math.ceil(n / this.P.limits.batch_size) }

  // synth._text: one part's text, stripped; a description that is only the item's link is no text
  private text(s: Item, key: string): string {
    const t = strip(String((s as unknown as Record<string, unknown>)[key] ?? ''))
    const link = strip(s.url || '')
    const bare = (value: string) => value.toLowerCase().replace(/^(?:https?:\/\/)?(?:www\.)?/, '').replace(/\/+$/, '')
    return t.toUpperCase() === 'NO_CONTENT' || (key === 'description' && !!link && bare(t) === bare(link)) ? '' : t
  }

  // synth.parts: the labelled parts in part_order, each cut to its cap, then the trim_order parts cut further
  // until all of them together fit the limit; empty parts left out
  parts(s: Item, limit = this.P.limits.excerpt_limit): [string, string][] {
    const out: [string, string][] = []
    for (const k of this.P.part_order) { const t = this.text(s, k); if (t) out.push([k, cut(t, this.P.limits.parts[k])]) }
    let over = out.reduce((n, [, t]) => n + len(t), 0) - limit
    for (const key of this.P.trim_order) {
      for (const p of out) {
        if (over > 0 && p[0] === key) { const n = Math.min(over, len(p[1])); p[1] = cut(p[1], len(p[1]) - n); over -= n }
      }
    }
    return out.filter(([, t]) => t)
  }

  // synth.has_text: at least one part (the title alone is not enough)
  hasText(s: Item): boolean { return this.parts(s).length > 0 }

  title(s: Item): string {
    return cut(strip([s.short_desc, s.description, s.creator].find(t => t && strip(t).toUpperCase() !== 'NO_CONTENT') || '').split('\n')[0], this.P.limits.title_limit)
  }

  // synth.tags_line: the tags as one comma list
  tagsLine(s: Item): string {
    return (s.tags || '').split(',').map(t => strip(t)).filter(Boolean).join(', ')
  }

  sourceBlock(s: Item): string {
    const texts = this.parts(s)
    if (!texts.length) return ''
    const creator = strip(s.creator || '')
    const meta: string[] = []
    if (creator) meta.push(fill(this.P.creator, { creator }))
    if (s.url) meta.push(fill(this.P.url, { url: s.url }))
    const tags = this.tagsLine(s)
    if (tags) meta.push(fill(this.P.tags, { tags }))
    const category = strip(s.category || '')
    if (category) meta.push(fill(this.P.category, { category }))
    const text = texts.map(([k, t]) => fill(this.P.part, { label: this.P.labels[k], text: t })).join('\n\n')
    return fill(this.P.source, { id: s.id, title: this.title(s), meta: meta.length ? meta.join('\n') + '\n' : '', text })
  }

  foldPrompt(topic: string, mode: string, existing: string, sources: string): string {
    if (!strip(existing)) return fill(this.P.first, { topic, rules: this.P.rules, sources })
    return fill(mode === 'append' ? this.P.append : this.P.reorganize, { topic, rules: this.P.rules, note: existing, sources })
  }

  // synth.batches: the usable sources (at least one part) in batches
  batches(sources: Item[]): Item[][] {
    const usable = sources.filter(s => this.hasText(s)), n = this.P.limits.batch_size, out: Item[][] = []
    for (let i = 0; i < usable.length; i += n) out.push(usable.slice(i, i + n))
    return out
  }

  // the prompt of one fold pass, or '' when no source in the batch has text
  batchPrompt(topic: string, existing: string, batch: Item[], mode = 'reorganize'): string {
    const blocks = batch.map(s => this.sourceBlock(s)).filter(Boolean)
    return blocks.length ? this.foldPrompt(topic, mode === 'append' ? 'append' : 'reorganize', existing, blocks.join('\n\n')) : ''
  }
}

// synth.clean: strip a wrapping ``` fence the model may add
export function clean(text: string): string {
  text = strip(text)
  if (text.startsWith('```')) {
    const nl = text.indexOf('\n')
    if (nl !== -1) text = text.slice(nl + 1)
    if (text.trimEnd().endsWith('```')) text = text.trimEnd().slice(0, -3)
  }
  return strip(text)
}
