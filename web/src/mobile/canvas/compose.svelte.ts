import { say, type ToolWords } from '../tools.ts'
import { ApiError } from '../../lib/api'
import { strip, splitJoin } from '../ai/quick'
import { canonJson, type CanvasDocument, type RawCanvasProposal } from '../ai/canvas'
import type { CanvasDraftContext, MobileSource, Row } from '../source/types'
import { baseKey, CanvasIssue, CHANGED, clash, COLOURS, count, identity, LIMIT, proposal, refusal, textProblem, UNCERTAIN, version } from './compose'
import { languageWorkChanged } from '../language-switch.ts'

export type Pick = { key: string; row: Row; version: string; state: 'checking' | 'ready' | 'unavailable'; blob?: Blob; size?: [number, number]; url?: string; job: object }
const hex = () => crypto.randomUUID().replaceAll('-', '')
export class Composer {
  name = $state(''); note = $state(''); color = $state(COLOURS[0]); layout = $state('rows')
  id = $state<string | null>(null); base = $state.raw<CanvasDocument | null>(null)
  picks = $state.raw<Pick[]>([]); selected = $state<string | null>(null)
  q = $state(''); cat = $state('all'); fav = $state(false); smart = $state(false)
  ids = $state.raw<Set<number> | null>(null); rank = $state.raw<Map<number, number> | null>(null)
  searching = $state(false); ranking = $state(false); searchError = $state('')
  noteMode = $state(false); busy = $state(false); uncertain = $state(false); targetLoading = $state(false)
  problem = $state(''); error = $state(''); errorLabel = $state(''); nameError = $state(false)
  notice = $state(''); clashId = $state<string | null>(null)
  private noticeTimer: ReturnType<typeof setTimeout> | undefined
  private generation = 0; private targetGeneration = 0; private alive = true
  private jobs: (() => Promise<void>)[] = []; private running = 0
  private attempt: { key: string; raw: RawCanvasProposal; context: CanvasDraftContext } | null = null
  get n() { return count(this.picks, this.note) }
  get locked() { return this.busy || this.uncertain }
  get unavailable() { return this.picks.filter(p => p.state === 'unavailable').length }
  get invalid() { return textProblem(this.name, this.note, !this.id, this.words) }
  get canAdd() { return !this.busy && (this.uncertain || !!this.n && !textProblem('', this.note, false) && !this.problem && !this.targetLoading && this.picks.every(p => p.state === 'ready')) }
  constructor(readonly source: MobileSource, smart: boolean, readonly words?: ToolWords) { this.smart = smart }
  edited() { this.error = ''; this.errorLabel = ''; this.nameError = false; this.clashId = null; languageWorkChanged() }
  tell(text: string, action: string | null = null) {
    clearTimeout(this.noticeTimer); this.notice = text; this.clashId = action
    this.noticeTimer = setTimeout(() => { this.notice = ''; this.clashId = null }, action ? 6500 : 3200)
  }
  search() {
    const gen = ++this.generation, q = strip(this.q), smart = this.smart
    this.ids = null; this.rank = null; this.searchError = ''; this.searching = !!q; this.ranking = !!q && smart
    const current = () => this.alive && gen === this.generation && strip(this.q) === q && this.smart === smart
    const timer = setTimeout(() => {
      if (!q || !current()) return
      void this.source.search(q).then(ids => { if (current()) this.ids = new Set(ids) })
        .catch(() => { /* null means the same substring fallback as Library */ }).finally(() => { if (current()) this.searching = false })
      if (smart) void this.source.smart(q).then(ids => { if (current()) this.rank = new Map(ids.map((id, i) => [id, i])) })
        .catch(e => { if (current()) { this.searchError = refusal(e); this.tell(this.showError(e)) } }).finally(() => { if (current()) this.ranking = false })
    }, 150)
    return () => { clearTimeout(timer); if (gen === this.generation) this.generation++ }
  }
  clear() { if (this.locked) return; this.q = ''; this.cat = 'all'; this.fav = false; this.edited() }
  used(row: Row) { return !!this.base?.items.some(e => e.source === 'db' && (e.uid ? e.uid === row.uid : e.item_id === row.id)) }
  remove(key: string) {
    if (this.locked) return
    if (key === 'note') this.note = ''
    else { this.picks.filter(p => p.key === key).forEach(p => { if (p.url) URL.revokeObjectURL(p.url) }); this.picks = this.picks.filter(p => p.key !== key) }
    this.selected = null; this.edited()
  }
  pick(row: Row) {
    if (this.locked || this.used(row)) return
    const key = identity(row)
    if (this.picks.some(p => p.key === key)) { this.remove(key); return }
    if (this.n >= 60) { this.tell(say(this.words, 'canvas.composer.limit', {}, LIMIT)); return }
    const p: Pick = { key, row, version: version(row), state: 'checking', job: {} }
    this.picks = [...this.picks, p]; this.edited(); this.prepare(p)
  }
  private prepare(p: Pick, recheck = false) {
    const job = p.job
    const current = () => this.alive && this.picks.find(x => x.key === p.key && x.job === job)
    this.jobs.push(async () => {
      if (!current()) return
      try {
        let blob: Blob | null
        if (this.source.thumbBlob) blob = await this.source.thumbBlob(p.row)
        else {
          const url = new URL(this.source.thumbUrl(p.row), location.href)
          // A refused geometry check must also bypass the service worker's old image.
          if (recheck) url.searchParams.set('check', crypto.randomUUID())
          const r = await fetch(url, { cache: 'reload' }); if (!r.ok) throw new Error('Thumbnail unavailable'); blob = await r.blob()
        }
        if (!blob) throw new Error('Thumbnail unavailable')
        const bitmap = await createImageBitmap(blob)
        const size: [number, number] = [bitmap.width, bitmap.height]; bitmap.close()
        if (size.some(n => !Number.isSafeInteger(n) || n <= 0 || n > 100000)) throw new Error('Invalid image size')
        const active = current()
        if (active) this.picks = this.picks.map(x => x === active ? { ...x, state: 'ready', blob, size, url: URL.createObjectURL(blob) } : x)
      } catch {
        const active = current()
        if (active) this.picks = this.picks.map(x => x === active ? { ...x, state: 'unavailable' } : x)
      }
    })
    this.drain()
  }
  private drain() {
    while (this.running < 4 && this.jobs.length) {
      const run = this.jobs.shift()!; this.running++
      void run().finally(() => { this.running--; if (this.alive) this.drain() })
    }
  }
  reconcile(rows: Row[], force = false) {
    if (this.locked) return
    const by = new Map(rows.map(r => [identity(r), r]))
    const work: Pick[] = []
    this.picks = this.picks.map(p => {
      const row = by.get(p.key)
      if (!row || !row.thumb) { if (p.url) URL.revokeObjectURL(p.url); return { ...p, state: 'unavailable', blob: undefined, size: undefined, url: undefined, job: {} } }
      if (force || version(row) !== p.version) {
        if (p.url) URL.revokeObjectURL(p.url)
        const next: Pick = { key: p.key, row, version: version(row), state: 'checking', job: {} }; work.push(next); return next
      }
      return row === p.row ? p : { ...p, row }
    })
    for (const p of work) this.prepare(p, force)
  }
  async target(id: string | null, retarget = false) {
    const generation = ++this.targetGeneration
    this.targetLoading = true
    try {
      const base = id ? await this.source.canvas(id) as CanvasDocument : null
      const problem = id ? await this.source.canvasDraftProblem?.(id, this.words) || '' : ''
      if (!this.alive || generation !== this.targetGeneration) return false
      if (retarget && problem) { this.error = problem; this.errorLabel = problem; return false }
      this.id = id; this.base = base; this.problem = problem
      const duplicates = this.picks.filter(p => this.used(p.row))
      for (const p of duplicates) this.remove(p.key)
      if (duplicates.length) this.tell(say(this.words, 'canvas.composer.duplicates', { n: duplicates.length }, `${duplicates.length} ${duplicates.length === 1 ? 'pick is' : 'picks are'} already on this canvas.`))
      this.selected = null
      const checking = this.picks.filter(p => p.state === 'checking').map(p => ({ ...p, job: {} }))
      this.picks = this.picks.map(p => checking.find(x => x.key === p.key) || p)
      for (const p of checking) this.prepare(p)
      return true
    } catch (e) { if (this.alive && generation === this.targetGeneration) { this.error = refusal(e); this.errorLabel = this.showError(e); if (!retarget) this.problem = this.error } return false }
    finally { if (generation === this.targetGeneration) this.targetLoading = false }
  }
  async add(readRows: () => Row[]): Promise<{ id: string; text: string; add: boolean } | null> {
    if (!this.canAdd || !this.source.applyCanvasDraft) return null
    this.busy = true; this.error = ''; this.errorLabel = ''
    let submitted = false
    try {
      const raw = proposal(this.name, this.id, this.picks.map(p => p.row.id), this.note, this.color, this.layout)
      const key = canonJson([raw, baseKey(this.base), this.base?._sourceRev ?? null, this.picks.map(p => [p.key, p.version, p.size])])
      if (!this.uncertain && key !== this.attempt?.key) {
        const name = splitJoin(this.name)
        if (!this.id && !name) { this.nameError = true; throw new CanvasIssue('canvas.composer.nameFirst', 'Name your canvas first.') }
        if (this.invalid) { this.nameError = true; throw new Error(this.invalid) }
        if (this.n > 60) throw new CanvasIssue('canvas.composer.limit', LIMIT)
        if (!this.id) {
          const found = clash(name, await this.source.canvases())
          if (found) { this.nameError = true; this.tell(say(this.words, 'canvas.composer.exists', { name: found.name }, `"${found.name}" already exists.`), found.id); return null }
        }
        if (this.id) {
          const base = await this.source.canvas(this.id) as CanvasDocument
          if (baseKey(base) !== baseKey(this.base)) { this.busy = false; await this.target(this.id); throw new CanvasIssue('canvas.composer.changed', CHANGED) }
        }
        const rows = readRows(), now = new Map(rows.map(r => [identity(r), r]))
        if (this.picks.some(p => !now.has(p.key) || version(now.get(p.key)!) !== p.version || now.get(p.key)!.id !== p.row.id)) {
          this.busy = false; this.reconcile(rows); throw new CanvasIssue('canvas.composer.changed', CHANGED)
        }
        this.attempt = { key, raw, context: { opId: hex(), canvasId: this.id || hex(), at: Date.now(),
          base: this.base ? structuredClone(this.base) : null,
          thumbs: this.picks.map(p => ({ id: p.row.id, uid: p.row.uid, version: p.version, blob: p.blob!, size: p.size! })) } }
      }
      const attempt = this.attempt!
      submitted = true
      const id = await this.source.applyCanvasDraft(attempt.raw, attempt.context)
      const add = !!attempt.raw.canvas_id, name = this.base?.name || splitJoin(this.name)
      const n = (attempt.raw.elements as unknown[]).length
      this.uncertain = false
      return { id, add, text: add ? say(this.words, 'canvas.composer.added', { n, name }, `Added ${n} to ${name}.`) : say(this.words, 'canvas.composer.created', { n, name }, `${name} created with ${n}.`) }
    } catch (e) {
      if (submitted && this.source.kind === 'desktop' && !(e instanceof ApiError && e.status < 500) && !(e instanceof Error && e.message === CHANGED)) {
        this.uncertain = true; this.error = UNCERTAIN; this.errorLabel = say(this.words, 'canvas.composer.uncertain', {}, UNCERTAIN)
      } else {
        this.uncertain = false; this.error = refusal(e); this.errorLabel = this.showError(e)
        if (this.error === CHANGED) { this.busy = false; this.reconcile(readRows(), true); if (this.id) await this.target(this.id) }
      }
      this.tell(this.errorLabel || this.error)
      return null
    } finally { this.busy = false }
  }
  private showError(e: unknown): string {
    const known = e as { displayKey?: string; displayParams?: Record<string, unknown> } | null
    return e instanceof CanvasIssue ? say(this.words, e.key, e.params, e.message)
      : known?.displayKey ? say(this.words, known.displayKey, known.displayParams ?? {}, refusal(e))
      : say(this.words, 'canvas.error.detail', { detail: refusal(e) }, refusal(e))
  }
  destroy() { this.alive = false; this.generation++; this.targetGeneration++; clearTimeout(this.noticeTimer); this.jobs = []; for (const p of this.picks) if (p.url) URL.revokeObjectURL(p.url); this.picks = []; languageWorkChanged() }
}
