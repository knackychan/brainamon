// The outbox (PLAN.md Capture): a link saved on the phone is stored first, then sent to the source
// when it is reachable. With the desktop as the source the send is POST /api/inbox/link (a new item
// plus a thumbnail job); Phase 4 turns it into a change file in the mirror. Nothing here touches the
// DOM: the Capture screen reads `entries` and calls save() / flush().
import { outbox as db, type OutboxEntry } from './store'
import type { MobileSource } from './source/types'
import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from './language-switch.ts'

// the link rule lives in links.ts (shared with the share target and the PC; tests check they agree)
export { cleanLink } from './links'

const SRC: [RegExp, string][] = [[/instagram\.com/, 'IG'], [/facebook\.com|fb\.watch/, 'f'], [/youtube\.com|youtu\.be/, 'YT'], [/reddit\.com/, 'R'], [/tiktok\.com/, 'TT'], [/threads\.(net|com)/, '@']]
export const srcMark = (url: string) => SRC.find(([re]) => re.test(url))?.[1] ?? 'W'
export const SRC_COLOR: Record<string, string> = { IG: 'linear-gradient(45deg,#f9a12e,#e1306c 55%,#7a37c9)', f: '#1877f2', YT: '#c4302b', R: '#ff4500', TT: '#111', W: '#6b6d70' }
export class OutboxStorageError extends Error {
  constructor() { super('Phone storage could not save the link. Keep the draft and retry.') }
}
const pendingWrites = new Map<number, OutboxEntry>()
const activeWrites = new Map<number, Set<Promise<unknown>>>()
const removing = new Set<number>()
function writeEntry(entry: OutboxEntry): Promise<unknown> {
  const id = entry.id!
  if (removing.has(id)) return Promise.reject(Object.assign(new Error('The queued link is being removed.'), { displayKey: 'common.error.queuedRemoving' }))
  const work = db.putRequired(entry), active = activeWrites.get(id) ?? new Set()
  active.add(work); activeWrites.set(id, active)
  return work.finally(() => { active.delete(work); if (!active.size) activeWrites.delete(id) })
}
registerLanguageCheck(async () => {
  for (const [id, entry] of pendingWrites) {
    if (removing.has(id)) return 'settings.language.unsavedOutbox'
    try { await writeEntry(entry); if (pendingWrites.get(id) === entry) pendingWrites.delete(id) } catch { /* retry on the next attempt */ }
  }
  return pendingWrites.size ? 'settings.language.unsavedOutbox' : null
})

export class Outbox {
  entries = $state.raw<OutboxEntry[]>([])
  sending = $state(false)
  // local: the source keeps the link on the phone (no PC), so a save needs no signal
  constructor(private source: MobileSource, private local = false) {}

  async load() { this.entries = (await db.all()).map(entry => entry.id === undefined ? entry : pendingWrites.get(entry.id) ?? entry) }

  // store first (works with no signal), then try to send
  // tags (and a type, only where the source can set it: the PC) are More details on the Add screen
  async save(url: string, note: string, category: string, tags = '', type = ''): Promise<OutboxEntry> {
    const done = beginLanguageWork()
    try {
      const e: OutboxEntry = { url, note, category, added: Date.now(), state: 'waiting', src: srcMark(url), ...(tags ? { tags } : {}), ...(type ? { type } : {}) }
      e.id = await db.add(e)
      this.entries = [e, ...this.entries]
      await this.flush()
      if (e.id === undefined && e.state === 'waiting') {
        this.entries = this.entries.filter(x => x !== e)
        throw new OutboxStorageError()
      }
      return this.entries.find(x => x.id === e.id) ?? e
    } finally { done() }
  }

  async remove(id: number) {
    if (removing.has(id)) return
    const done = beginLanguageWork()
    removing.add(id)
    try {
      await Promise.allSettled([...(activeWrites.get(id) ?? [])])
      await db.delRequired(id)
      pendingWrites.delete(id)
      this.entries = this.entries.filter(e => e.id !== id)
    } finally { removing.delete(id); done() }
  }

  // send every waiting entry; a network failure leaves it waiting, a 4xx marks it
  async flush() {
    if (this.sending || (!navigator.onLine && !this.local)) return
    const done = beginLanguageWork()
    this.sending = true
    try {
      for (const e of this.entries.filter(x => x.state === 'waiting')) {
        try {
          const r = await this.source.saveLink(e.url)
          e.itemId = r.id
          e.state = r.new ? 'sent' : 'dup'
          if (r.new && r.id && (e.note || e.category || e.tags || e.type)) {
            const f: Record<string, string> = {}
            if (e.category) f.category = e.category
            if (e.note) f.notes = e.note
            if (e.tags) f.tags = e.tags
            if (e.type) f.type = e.type
            await this.source.edit(r.id, f).catch(() => { /* the link is in; the note can be added on the PC */ })
          }
        } catch (err) {
          const status = (err as { status?: number }).status
          if (!status || status >= 500) break             // unreachable: stays waiting
          e.state = 'error'
          e.error = (err as Error).message
        }
        if (e.id !== undefined) {
          try { await writeEntry(e); pendingWrites.delete(e.id) }
          catch { pendingWrites.set(e.id, { ...e }); languageWorkChanged() }
        }
        this.entries = this.entries.map(x => (x.id === e.id ? { ...e } : x))
      }
    } finally { this.sending = false; done() }
  }
}
