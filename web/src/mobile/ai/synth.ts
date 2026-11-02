// Synthesize on the phone: the TypeScript port of knowledge/synth.py (excerpts, batches of 12, the
// fold prompt, clean), reading the same prompt file (knowledge/prompts/synth.json, passed in as
// `P`). Capped at P.limits.phone_max_sources (36 sources, 3 AI calls); a bigger run is queued for
// the PC. tests/test_phone_ai.py checks both build the same prompts.
// Run by Node in the tests (type stripping): no parameter properties, imports with .ts.
import { cut, fill, strip, type Item } from './quick.ts'

export interface SynthPrompts {
  limits: { batch_size: number; excerpt_limit: number; max_tokens: number; phone_max_sources: number }
  rules: string; source: string; creator: string; url: string; first: string; append: string; reorganize: string
}

export class Synth {
  readonly P: SynthPrompts
  constructor(P: SynthPrompts) { this.P = P }

  get max() { return this.P.limits.phone_max_sources }
  calls(n: number) { return Math.ceil(n / this.P.limits.batch_size) }

  excerpt(s: Item): string {
    return cut(s.ai_desc || s.transcript || s.description || s.short_desc || '', this.P.limits.excerpt_limit)
  }

  title(s: Item): string {
    return cut(strip(s.short_desc || s.description || s.creator || '').split('\n')[0], 120)
  }

  sourceBlock(s: Item): string {
    const text = this.excerpt(s)
    if (!text) return ''
    const creator = strip(s.creator || '')
    const meta: string[] = []
    if (creator) meta.push(fill(this.P.creator, { creator }))
    if (s.url) meta.push(fill(this.P.url, { url: s.url }))
    return fill(this.P.source, { id: s.id, title: this.title(s), meta: meta.length ? meta.join('\n') + '\n' : '', text })
  }

  foldPrompt(topic: string, mode: string, existing: string, sources: string): string {
    if (!strip(existing)) return fill(this.P.first, { topic, rules: this.P.rules, sources })
    return fill(mode === 'append' ? this.P.append : this.P.reorganize, { topic, rules: this.P.rules, note: existing, sources })
  }

  // synth.batches: the usable sources (with some text) in batches
  batches(sources: Item[]): Item[][] {
    const usable = sources.filter(s => this.excerpt(s)), n = this.P.limits.batch_size, out: Item[][] = []
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
