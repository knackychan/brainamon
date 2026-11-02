// What the phone does while it reads the mirror (PLAN.md Phase 4 step 2): saved links, favourites,
// tag / category / note edits and My Notes; Phase 5 adds Wiskit chats, answers saved as notes and
// synthesized notes. Each is queued in IndexedDB first (works with no
// signal), shown at once over the mirror's rows, and sent to the PC as one sealed change file per
// flush (`chg-...`, src/mobile/mirror/crypto.ts). The PC applies it (server/intake.py) and the
// manifest's `applied[device]` says so; then the queued copy is dropped. Paired with a PC, each file also
// carries this phone's stream and the batch's number (server/delivery.py): a PC whose manifest says `delivery: 2`
// applies them once each, in order, and its `receipts` say which went in. Change shapes:
//   {op: 'link', uid, url, note, category, tags?, at}   tags + at = save time: an Import (milestone-2026-10-14/mobile-import)
//   {op: 'details', uid, title, creator, desc, thumb, at}   read from a saved link's page (plans/09-link-details.md)
//   {op: 'fav', uid, on, at}
//   {op: 'edit', uid, fields: {tags|category|notes|ai_desc}, was: {...}, at}
//   {op: 'category_batch', entries: [{uid, from, category}], at} one approved Wiskit batch
//   {op: 'note', file, title, category, body, was, at}
//   {op: 'note_append', file, title, name, text, when, at}   one section at the end (Add to Brainamon, plans/09)
//   {op: 'chat', slug, name, created, history, source_ids, options, was, at}     the whole chat so far
//   {op: 'chat_delete', slug, turns, at}  a chat deleted (turns: how many the phone saw)
//   {op: 'delete', uid, pc, at}           an item deleted (pc: on the PC too, else hidden on the phone)
//   {op: 'answer', md, ids, file, at}       Save as note (file: the name the phone shows until the PC's)
//   {op: 'synth', topic, sources, body, file, at}
//   {op: 'synth_queue', topic, ids, at}     more sources than the phone folds: the PC runs it
import { changes as db, journal, kv, updateCanvasChange, type ChangeEntry } from '../store'
import type { Row } from '../source/types'
import { normalizeCanvas } from '../ai/canvas.ts'
import { clearResend, resendPending, type ResendPair } from './resend'
import { requeueWaiting } from './pairing'

export type { ChangeEntry }

// kv 'delivery': this phone's stream, its next batch number, the highest number it knows the PC applied, and the last
// `want` answered ("<seq>:<manifest published>")
export interface Delivery { stream: string; next: number; acked: number; wanted?: string }
// what prune reads from a fresh manifest (source/mirror.ts Manifest)
export interface Acks { delivery?: number; published?: number; receipts?: Record<string, { seq: number; want?: number }> }
const hex = (n: number) => [...crypto.getRandomValues(new Uint8Array(n))].map(b => b.toString(16).padStart(2, '0')).join('')
const settled = (e: ChangeEntry) => e.op === 'canvas' && !!e.canvasLocal && e.canvasLocal.status !== 'pending'

// Stable envelope: format, device, at. Keep equal to library/mirror.py.
export const CHANGE_FORMAT = 1

const SINGLE = new Set(['link', 'answer', 'synth', 'synth_queue', 'note_append', 'category_batch', 'canvas'])

export class Changes {
  list: ChangeEntry[] = []
  private loaded: Promise<void> | null = null
  private busy: Promise<number> | null = null
  private floor = 0          // the latest file time the PC applied (prune)
  private delivery: Delivery | null = null
  private chain: Promise<unknown> = Promise.resolve()
  mergeErrors: string[] = []
  // items deleted "only on this phone" whose change the PC applied: the PC keeps them, so the phone
  // goes on hiding them after prune drops the change (kv 'hidden'; prune never clears it, only
  // store.ts changes.clear() on a fresh pairing or a solo wipe)
  hidden = new Set<string>()
  // told once the journal is loaded and after every change to it (state.svelte.ts measurePend: the status card counts it)
  private watchers = new Set<() => void>()
  watch(fn: () => void): () => void { this.watchers.add(fn); return () => { this.watchers.delete(fn) } }
  private changed() { for (const fn of this.watchers) try { fn() } catch { /* a watcher's failure stays its own */ } }

  load() {
    this.loaded ??= Promise.all([db.all(), kv.get<string[]>('hidden'), kv.get<Delivery>('delivery')]).then(([l, h, d]) => {
      this.list = l; this.hidden = new Set(h ?? []); this.delivery = d ?? null
      this.changed()
    })
    return this.loaded
  }
  async reload() { this.loaded = null; await this.load() }

  get pending() { return this.list.length }
  get unsent() { return this.list.filter(e => e.state !== 'sent').length }

  // what More shows: a canvas change the PC settled (refused, or synced with its copy kept) waits for
  // nothing, and one an older PC cannot take is held, not "not sent yet"
  counts(allowCanvas: boolean) {
    let unsent = 0, waiting = 0, held = 0
    for (const e of this.list) {
      if (e.op === 'canvas' && e.canvasLocal && e.canvasLocal.status !== 'pending') continue
      if (e.state === 'sent') waiting++
      else if (e.op === 'canvas' && !allowCanvas) held++
      else unsent++
    }
    return { unsent, waiting, held }
  }

  // the edits that go again after pairing again (PH8, mirror/resend.ts): while the marker waits for a fresh manifest
  // (`pending`) every edit still here, then the ones it flagged until the PC acknowledges them. A canvas change an
  // older PC cannot take is held, not sending.
  resending(allowCanvas: boolean, pending = false): number {
    return this.list.filter(e => !settled(e) && (allowCanvas || e.op !== 'canvas') && (pending || e.resend === true)).length
  }

  // flush, prune, resend and canvas results take turns: none sees another's half-saved journal
  private serial<T>(f: () => Promise<T>): Promise<T> {
    const run = this.chain.then(f, f).finally(() => this.changed())
    this.chain = run.catch(() => undefined)
    return run
  }

  // entries change in memory and storage together: storage that fails puts memory back, and the caller sees the error
  private async commit(entries: ChangeEntry[], change: (e: ChangeEntry) => void, drop: ChangeEntry[] = [], set: Record<string, unknown> = {}) {
    const was = entries.map(e => ({ ...e }))
    entries.forEach(change)
    try { await journal(entries, drop.map(e => e.id ?? 0).filter(Boolean), set) }
    catch (err) {
      entries.forEach((e, i) => { for (const k of Object.keys(e)) delete (e as unknown as Record<string, unknown>)[k]; Object.assign(e, was[i]) })
      throw err
    }
  }

  private stream(): Delivery { return this.delivery ?? { stream: hex(16), next: 1, acked: 0 } }

  // queue one change; an unsent change to the same thing is updated instead of doubled (a saved
  // link, answer or synthesis is always a new one)
  private prepare(e: Omit<ChangeEntry, 'state' | 'at'> & { at?: number }, list = this.list) {
    const key = (x: Omit<ChangeEntry, 'state' | 'at'>) => (x.op === 'note' || x.op === 'note_delete' ? x.file : x.op === 'chat' || x.op === 'chat_delete' ? x.slug : x.uid)
    const same = SINGLE.has(e.op) ? undefined : list.find(x => x.state === 'queued' && x.op === e.op && key(x) === key(e))
    const entry: ChangeEntry = { ...same, ...e, at: e.at ?? Date.now(), state: 'queued' }
    if (same) {
      entry.was = same.was ?? e.was
      if (e.op === 'edit') {
        entry.fields = { ...same.fields, ...e.fields }
        entry.was = { ...(e.was as Record<string, unknown>), ...(same.was as Record<string, unknown>) }
      }
    }
    return { same, entry }
  }

  async add(e: Omit<ChangeEntry, 'state' | 'at'> & { at?: number }): Promise<ChangeEntry> {
    await this.load()
    const { same, entry } = this.prepare(e)
    if (same) { Object.assign(same, entry); await db.put(same); this.changed(); return same }
    entry.id = await db.add(entry)
    this.list.push(entry)
    this.changed()
    return entry
  }

  async saveChat(e: Omit<ChangeEntry, 'state' | 'at'>, signal?: AbortSignal): Promise<ChangeEntry> {
    await this.load()
    signal?.throwIfAborted()
    const rows = await db.forChat(signal)
    const { same, entry } = this.prepare(e, rows)
    entry.id = await db.saveChat(entry, signal)
    if (same && this.list.some(x => x.id === same.id)) this.list = this.list.map(x => x.id === same.id ? entry : x)
    else this.list.push(entry)
    this.changed()
    return entry
  }

  // a chat deleted before its turns went: they never go
  async dropQueuedChat(slug: string) {
    await this.load()
    const out = this.list.filter(x => x.op === 'chat' && x.slug === slug && x.state === 'queued')
    for (const e of out) if (e.id) await db.del(e.id)
    this.list = this.list.filter(e => !out.includes(e))
    this.changed()
  }

  // a note deleted before its queued edits went: they never go (the delete stands)
  async dropQueuedNote(file: string) {
    await this.load()
    const out = this.list.filter(x => (x.op === 'note' || x.op === 'note_append') && x.file === file && x.state === 'queued')
    for (const e of out) if (e.id) await db.del(e.id)
    this.list = this.list.filter(e => !out.includes(e))
    this.changed()
  }

  // a link deleted before it went: it never goes, and nothing else about it either
  async dropQueuedLink(uid: string): Promise<boolean> {
    await this.load()
    const out = this.list.filter(x => x.uid === uid && x.state === 'queued')
    if (!out.some(x => x.op === 'link')) return false
    for (const e of out) if (e.id) await db.del(e.id)
    this.list = this.list.filter(e => !out.includes(e))
    this.changed()
    return true
  }

  // a link still waiting to go: its note and category ride along with it
  async amendLink(uid: string, f: { note?: string; category?: string }): Promise<boolean> {
    await this.load()
    const l = this.list.find(x => x.op === 'link' && x.uid === uid && x.state === 'queued')
    if (!l) return false
    if (f.note !== undefined) l.note = f.note
    if (f.category !== undefined) l.category = f.category
    await db.put(l)
    this.changed()
    return true
  }

  // seal every queued change into one file and upload it; `send` does the Drive part. A batch is
  // frozen ('sending', with its time) before the upload: if the upload went through but its answer
  // was lost, the retry sends the same batch with the same time, and the PC skips a file whose time
  // it already applied (server/sync.py _intake), so an answer or synthesis never lands twice.
  // Changes queued meanwhile go in the next file.
  // `numbered` (paired with a PC): each batch also takes the next number of this phone's stream, saved with it, and
  // batches go whole, lowest number first; one sent again keeps its number and time (server/delivery.py).
  async flush(send: (doc: unknown) => Promise<string>, device: string, allowCanvas = true, numbered = false): Promise<number> {
    this.busy ??= this.flushAll(send, device, allowCanvas, numbered).finally(() => { this.busy = null; this.changed() })
    return this.busy
  }

  private async flushAll(send: (doc: unknown) => Promise<string>, device: string, allowCanvas: boolean, numbered: boolean): Promise<number> {
    await this.load()
    if (numbered && requeueWaiting()) throw new Error('This phone has not prepared its saved changes for this PC. Reopen Brainamon to retry.')
    if (numbered) return this.flushNumbered(send, device, allowCanvas)
    let n = 0
    for (;;) {
      let out = this.list.filter(e => e.state === 'sending')
      if (out.some(e => e.op === 'canvas') && !allowCanvas) return n
      if (!out.length) {
        out = this.list.filter(e => e.state === 'queued' && (allowCanvas || e.op !== 'canvas') && (!e.canvasLocal || e.canvasLocal.status === 'pending'))
        if (!out.length) return n
        // later than anything sent before, even if the phone's clock went back since: the PC skips
        // a time it already applied
        const at = Math.max(Date.now(), this.floor + 1, ...this.list.map(e => (e.sentAt ?? 0) + 1))
        for (const e of out) { e.state = 'sending'; e.sentAt = at; await db.put(e) }
      }
      const at = out[0].sentAt ?? 0
      const doc = { format: CHANGE_FORMAT, device, at, changes: out.map(({ id: _id, state: _s, sentAt: _a, chg: _c, canvasLocal: _l, ...c }) => c) }
      const chg = await send(doc)
      for (const e of out) { e.state = 'sent'; e.chg = chg; await db.put(e) }
      n += out.length
    }
  }

  private async flushNumbered(send: (doc: unknown) => Promise<string>, device: string, allowCanvas: boolean): Promise<number> {
    let n = 0
    for (;;) {
      const went = await this.serial(async () => {
        await this.number()
        let out = this.batches()[0]
        if (!out) {
          const queued = this.list.filter(e => e.state === 'queued' && (allowCanvas || e.op !== 'canvas') && !settled(e))
          if (!queued.length) return -1
          out = await this.freeze(queued)
        }
        if (out.some(e => e.op === 'canvas') && !allowCanvas) return -1
        const d = this.stream(), first = out[0]
        const doc = { format: CHANGE_FORMAT, device, at: first.sentAt ?? 0, stream: first.stream, seq: first.seq,
          acked: first.stream === d.stream ? d.acked : 0, ...(first.legacy ? { legacy: true } : {}),
          changes: out.map(({ id: _id, state: _s, sentAt: _a, chg: _c, canvasLocal: _l, stream: _t, seq: _q, legacy: _g, resend: _r, ...c }) => c) }
        const chg = await send(doc)
        await this.commit(out, e => { e.state = 'sent'; e.chg = chg })
        return out.length
      })
      if (went < 0) return n
      n += went
    }
  }

  // the batches still to upload, lowest number first, each whole (never split or merged)
  private batches(): ChangeEntry[][] {
    const by = new Map<string, ChangeEntry[]>()
    for (const e of this.list) if (e.state === 'sending' && e.seq !== undefined) by.set(`${e.stream} ${e.seq}`, [...(by.get(`${e.stream} ${e.seq}`) ?? []), e])
    return [...by.values()].sort((a, b) => (a[0].seq ?? 0) - (b[0].seq ?? 0) || String(a[0].stream).localeCompare(String(b[0].stream)))
  }

  // the next number goes to the queued changes, with a time later than anything sent before (even if the phone's clock
  // went back since); the number and the batch are saved together
  private async freeze(out: ChangeEntry[]): Promise<ChangeEntry[]> {
    const d = this.stream(), next = { ...d, next: d.next + 1 }
    const at = Math.max(Date.now(), this.floor + 1, ...this.list.map(e => (e.sentAt ?? 0) + 1))
    await this.commit(out, e => { e.state = 'sending'; e.sentAt = at; e.stream = d.stream; e.seq = d.next }, [], { delivery: next })
    this.delivery = next
    return out
  }

  // batches an older build sent without a number get the next numbers, oldest first, marked legacy, and go once more:
  // the PC applies one only above its floor, so a batch it already applied is not applied twice (server/delivery.py)
  private async number() {
    const old = this.list.filter(e => e.state !== 'queued' && e.seq === undefined && !settled(e))
    if (!old.length) return
    const d = this.stream(), times = [...new Set(old.map(e => e.sentAt ?? 0))].sort((a, b) => a - b)
    const next = { ...d, next: d.next + times.length }
    await this.commit(old, e => { e.state = 'sending'; e.stream = d.stream; e.seq = d.next + times.indexOf(e.sentAt ?? 0); e.legacy = true },
      [], { delivery: next })
    this.delivery = next
  }

  // the PC applied every file up to `applied` (ms): their queued copies go (a 'sending' batch too:
  // its upload went through). `acks`, a fresh manifest: with `delivery` 2 a numbered batch goes once its stream's
  // receipt covers its number, and a `want` sends that batch again (once per manifest). `pair` with a resend marker
  // (pairing again): every edit still here goes again with its number and time, then the marker goes (true).
  async prune(applied: number, acks?: Acks | null, pair?: ResendPair | null): Promise<boolean> {
    await this.load()
    return this.serial(async () => {
      this.floor = Math.max(this.floor, applied)
      const rec = (acks?.delivery ?? 0) >= 2 ? acks?.receipts ?? {} : null
      const done = this.list.filter(e => e.op !== 'canvas' && e.state !== 'queued' &&
        (rec && e.seq !== undefined ? e.seq <= (rec[e.stream ?? '']?.seq ?? 0) : (e.sentAt ?? 0) <= applied))
      const hide = done.filter(e => e.op === 'delete' && !e.pc && e.uid).map(e => e.uid as string)
      const hidden = hide.some(u => !this.hidden.has(u)) ? [...new Set([...this.hidden, ...hide])] : null
      const left = this.list.filter(e => !done.includes(e))
      const d = this.delivery
      let next: Delivery | null = null, again: ChangeEntry[] = []
      if (d) {
        const mine = rec ? rec[d.stream]?.seq ?? 0 : Math.max(0, ...done.filter(e => e.stream === d.stream).map(e => e.seq ?? 0))
        const want = rec?.[d.stream]?.want ?? 0, key = `${want}:${acks?.published ?? 0}`
        if (want && d.wanted !== key) again = left.filter(e => e.state === 'sent' && e.stream === d.stream && e.seq === want)
        if (mine > d.acked || again.length) next = { ...d, acked: Math.max(d.acked, mine), ...(again.length ? { wanted: key } : {}) }
      }
      // a canvas change stays here until the PC's canvas result (reconcileCanvas), but once a receipt covers its batch it
      // never goes again: sent alone under that number, the PC would refuse it (another file already used the number)
      const covered = (e: ChangeEntry) => !!rec && e.seq !== undefined && e.seq <= (rec[e.stream ?? '']?.seq ?? 0)
      const landed = left.filter(e => covered(e) && (e.state === 'sending' || e.resend))
      const resend = !!pair && resendPending(pair)
      const flag = resend ? left.filter(e => !settled(e) && !covered(e)) : []
      const change = [...new Set([...again, ...flag, ...landed])]
      if (done.length || hidden || next || change.length) {
        await this.commit(change, e => {
          if (landed.includes(e)) { e.state = 'sent'; delete e.resend; return }
          if (e.state === 'sent') e.state = 'sending'
          if (resend) e.resend = true
        }, done, { ...(hidden ? { hidden } : {}), ...(next ? { delivery: next } : {}) })
        this.list = this.list.filter(e => !done.includes(e))       // with what was queued meanwhile
        if (hidden) this.hidden = new Set(hidden)
        if (next) this.delivery = next
      }
      if (resend) clearResend(pair!)
      return resend
    })
  }

  async canvasResult(e: ChangeEntry, state: 'synced' | 'refused', reason = '') {
    if (!e.canvasLocal || !e.id) return
    return this.serial(async () => {
      if (!e.canvasLocal || !e.id) return
      const was = { status: e.canvasLocal.status, reason: e.canvasLocal.reason }
      e.canvasLocal.status = state; e.canvasLocal.reason = reason
      try { await updateCanvasChange(e, e.id) }
      catch (err) { e.canvasLocal.status = was.status; e.canvasLocal.reason = was.reason; throw err }
    })
  }

  async pruneCanvas(e: ChangeEntry) {
    if (!e.id) return
    return this.serial(async () => {
      await updateCanvasChange(null, e.id!)
      this.list = this.list.filter(x => x !== e)
    })
  }

  // ── without a PC (plans/08-phone-solo.md): the change files in Drive are the library ──
  // the change files this phone already holds (its own, and those read back)
  known(): Set<string> { return new Set(this.list.map(e => e.chg ?? '').filter(Boolean)) }

  async acceptBackup(snapshot: ChangeEntry[], name: string, at: number) {
    await this.load()
    return this.serial(async () => {
      const same = this.list.filter(e => snapshot.some(old => old.id === e.id && JSON.stringify(old) === JSON.stringify(e)))
      await this.commit(same, e => { e.state = 'sent'; e.chg = name; e.sentAt = at })
      this.changed()
    })
  }

  // change files read back from Drive (another phone on the same recovery code, or this phone after
  // a reset), oldest first; they count as sent, so they never go up again
  async merge(docs: { name: string; doc: { at?: number; changes?: Omit<ChangeEntry, 'id' | 'state'>[] } }[]): Promise<number> {
    await this.load()
    let n = 0
    const ops = new Map(this.list.filter(e => e.op === 'canvas' && e.op_id).map(e => [e.op_id!, JSON.stringify([e.canvas_id, e.at, e.proposal, e.refs, e.sizes])]))
    for (const { name, doc } of [...docs].sort((a, b) => (a.doc.at ?? 0) - (b.doc.at ?? 0) || a.name.localeCompare(b.name))) {
      for (const c of doc.changes ?? []) {
        if (!c || typeof c !== 'object' || !c.op) continue
        if (c.op === 'canvas') {
          try {
            if (Object.keys(c).sort().join(',') !== 'at,canvas_id,op,op_id,proposal,refs,sizes') throw new Error('Invalid canvas operation fields.')
            const p = normalizeCanvas(c.proposal)
            if (p.elements.some(e => e.kind === 'frame')) throw new Error('Raw frames are unavailable in a phone canvas operation.')
            if (!/^[0-9a-f]{32}$/.test(c.op_id || '') || !/^[A-Za-z0-9_-]{1,64}$/.test(c.canvas_id || '') ||
              c.canvas_id === 'index' || !Number.isSafeInteger(c.at) || c.at! < 0 || !c.refs || !c.sizes ||
              Array.isArray(c.refs) || Array.isArray(c.sizes) || typeof c.refs !== 'object' || typeof c.sizes !== 'object' ||
              (p.canvas_id ? p.canvas_id !== c.canvas_id : !/^[0-9a-f]{32}$/.test(c.canvas_id || ''))) throw new Error('Invalid canvas operation.')
            const refs = c.refs!, sizes = c.sizes!
            const used = new Set(p.elements.filter(e => e.kind === 'thumbnail').map(e => String(e.item_id)))
            const uids = new Set(Object.values(refs))
            if (Object.keys(refs).length !== used.size || Object.keys(sizes).length !== uids.size ||
              Object.keys(sizes).some(uid => !uids.has(uid)) ||
              [...used].some(k => !/^[0-9a-f]{32}$/.test(refs[k] || '') || !Array.isArray(sizes[refs[k]]) ||
                sizes[refs[k]].length !== 2 || sizes[refs[k]].some(v => !Number.isSafeInteger(v) || v <= 0 || v > 100000)))
              throw new Error('Invalid canvas references.')
            const wire = JSON.stringify([c.canvas_id, c.at, c.proposal, c.refs, c.sizes])
            if (ops.has(c.op_id!)) {
              if (ops.get(c.op_id!) !== wire) this.mergeErrors.push(`Canvas operation ${c.op_id} changed in a backup file.`)
              continue
            }
            ops.set(c.op_id!, wire)
          } catch (e) { this.mergeErrors.push((e as Error).message); continue }
        }
        const entry = { ...c, at: c.at ?? doc.at ?? 0, state: 'sent', sentAt: doc.at ?? 0, chg: name } as ChangeEntry
        entry.id = await db.add(entry)
        this.list.push(entry)
        n++
      }
    }
    this.changed()
    return n
  }

  // a phone used without a PC is now paired with one: everything goes again, sealed with the PC's key
  // (the PC drops the old files: it cannot open them), as the first batches of a new stream: a number kept from an
  // earlier pairing would make the PC wait for a batch the phone no longer holds. The entries and the stream are saved
  // in one write; storage that fails leaves both as they were, and the caller sees the error.
  async requeue() {
    await this.load()
    return this.serial(async () => {
      const fresh: Delivery = { stream: hex(16), next: 1, acked: 0 }
      await this.commit(this.list.filter(e => !settled(e)), e => {
        e.state = 'queued'; delete e.sentAt; delete e.chg; delete e.stream; delete e.seq; delete e.legacy; delete e.resend
      }, [], { delivery: fresh })
      this.delivery = fresh
      this.floor = 0
    })
  }

  // a negative id names a link saved on the phone until the PC gives it a number
  static linkId = (e: ChangeEntry) => -(e.id ?? 0)

  // the mirror's rows with what the phone did on top
  overlay(rows: Row[]): Row[] {
    if (!this.list.length && !this.hidden.size) return rows
    const byUid = new Map<string, Row>(), urls = new Set<string>()
    let out = rows.map(r => { const c = { ...r }; byUid.set((r as Row & { uid?: string }).uid ?? '', c); urls.add(r.url); return c })
    const added: Row[] = []
    for (const e of this.list) {
      if (e.op === 'link' && e.url && !urls.has(e.url)) {
        const r = {
          id: Changes.linkId(e), uid: e.uid, title: '', creator: '', type: 'Reel', cat: e.category || 'INTERESTING', tags: e.tags || '',
          desc: e.note || '', url: e.url, src: srcOf(e.url), thumb: false, ai: false, an: false, nd: 0, fav: false, created: e.at, tv: 0,
        } as Row
        urls.add(e.url); added.push(r); byUid.set(e.uid ?? '', r)
      } else if (e.op === 'details') {
        const r = byUid.get(e.uid ?? '')
        if (r && added.includes(r)) {        // only a link saved on the phone: the PC's rows have their own
          r.title = (e.title || (e.desc ?? '').split('\n')[0]).slice(0, 90)
          if (e.creator) r.creator = e.creator
          if (e.thumb) { r.thumb = true; r.tv = e.at }
        }
      } else if (e.op === 'fav') {
        const r = byUid.get(e.uid ?? ''); if (r) r.fav = !!e.on
      } else if (e.op === 'edit') {
        const r = byUid.get(e.uid ?? '')
        if (r && e.fields) {
          if (e.fields.tags !== undefined) r.tags = e.fields.tags
          if (e.fields.category !== undefined) r.cat = e.fields.category
          if (e.fields.ai_desc) r.ai = true
        }
      } else if (e.op === 'category_batch') {
        for (const x of e.entries ?? []) { const r = byUid.get(x.uid); if (r) r.cat = x.category }
      }
    }
    if (added.length) out = [...added.reverse(), ...out]
    const gone = new Set([...this.hidden, ...this.list.filter(e => e.op === 'delete').map(e => e.uid)])
    return gone.size ? out.filter(r => !gone.has((r as Row & { uid?: string }).uid)) : out
  }
}

// the source mark of a link (server/library.py platform names)
function srcOf(url: string): string {
  return /instagram\.com/i.test(url) ? 'instagram' : /facebook\.com|fb\.watch/i.test(url) ? 'facebook'
    : /youtube\.com|youtu\.be/i.test(url) ? 'youtube' : /reddit\.com|redd\.it/i.test(url) ? 'reddit' : /tiktok\.com/i.test(url) ? 'tiktok'
    : /threads\.(net|com)/i.test(url) ? 'threads' : 'web'
}
