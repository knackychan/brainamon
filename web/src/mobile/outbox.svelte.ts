// The outbox (PLAN.md Capture): a link saved on the phone is stored first, then sent to the source
// when it is reachable. With the desktop as the source the send is POST /api/inbox/link (a new item
// plus a thumbnail job); Phase 4 turns it into a change file in the mirror. Nothing here touches the
// DOM: the Capture screen reads `entries` and calls save() / flush().
import { outbox as db, type OutboxEntry } from './store'
import type { MobileSource } from './source/types'

// the link rule lives in links.ts (shared with the share target and the PC; tests check they agree)
export { cleanLink } from './links'

const SRC: [RegExp, string][] = [[/instagram\.com/, 'IG'], [/facebook\.com|fb\.watch/, 'f'], [/youtube\.com|youtu\.be/, 'YT'], [/reddit\.com/, 'R'], [/tiktok\.com/, 'TT'], [/threads\.(net|com)/, '@']]
export const srcMark = (url: string) => SRC.find(([re]) => re.test(url))?.[1] ?? 'W'
export const SRC_COLOR: Record<string, string> = { IG: 'linear-gradient(45deg,#f9a12e,#e1306c 55%,#7a37c9)', f: '#1877f2', YT: '#c4302b', R: '#ff4500', TT: '#111', W: '#6b6d70' }

export class Outbox {
  entries = $state.raw<OutboxEntry[]>([])
  sending = $state(false)
  // local: the source keeps the link on the phone (no PC), so a save needs no signal
  constructor(private source: MobileSource, private local = false) {}

  async load() { this.entries = await db.all() }

  // store first (works with no signal), then try to send
  // tags (and a type, only where the source can set it: the PC) are More details on the Add screen
  async save(url: string, note: string, category: string, tags = '', type = ''): Promise<OutboxEntry> {
    const e: OutboxEntry = { url, note, category, added: Date.now(), state: 'waiting', src: srcMark(url), ...(tags ? { tags } : {}), ...(type ? { type } : {}) }
    e.id = await db.add(e)
    this.entries = [e, ...this.entries]
    await this.flush()
    return this.entries.find(x => x.id === e.id) ?? e
  }

  async remove(id: number) {
    await db.del(id)
    this.entries = this.entries.filter(e => e.id !== id)
  }

  // send every waiting entry; a network failure leaves it waiting, a 4xx marks it
  async flush() {
    if (this.sending || (!navigator.onLine && !this.local)) return
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
        await db.put(e)
        this.entries = this.entries.map(x => (x.id === e.id ? { ...e } : x))
      }
    } finally { this.sending = false }
  }
}
