// Wiskit files (projects/wiskit-files plan 02): files dropped, pasted or attached on the Wiskit rail
// become Ask attachments (POST /api/ask/attach, kept in data/inbox) shown as chips over the composer.
// Each chip can be filed: Wiskit suggests where (POST /api/filing/suggest) and files it
// (POST /api/filing/file). Pictures can be digested to text (POST /api/filing/digest) that the user
// edits, then adds to a note, a new note, or copies.
import { api } from './api'
import { ask, openNote, type Att } from './ask.svelte'
import { toast } from './ui.svelte'
import { promptWin } from './windows.svelte'

export interface FileOpt { action: 'new' | 'append' | 'extend'; file: string; title: string; label: string; why: string; best: boolean }
export interface NoteRef { file: string; title: string; kind: string }

class Filing {
  busy = $state('')                          // what runs now, shown over the composer ('' = idle)
  att: Att | null = $state(null)             // the chip whose choices are open
  opts: FileOpt[] = $state.raw([])
  ai = $state(false)                         // the choices came from the model (else keyword match)
  notes: NoteRef[] = $state.raw([])          // every note a file can go into (topic digests left out)
  digest: { text: string; from: string } | null = $state(null)
}
export const fl = new Filing()

// what the Attach key offers (= knowledge/attachments.py TEXT_EXTS, IMAGE_EXTS and .pdf)
export const ACCEPT = '.pdf,.md,.txt,.csv,.json,image/png,image/jpeg,image/webp,image/gif'

const pastedName = (f: File) => f.type.startsWith('image/') ? `pasted.${f.type.slice(6) === 'jpeg' ? 'jpg' : f.type.slice(6)}` : 'pasted.txt'

async function noteList() {
  fl.notes = (await api.get<NoteRef[]>('/api/notes')).filter(n => n.kind !== 'Topic digest')
}

export async function attachFiles(files: File[]) {
  for (const f of files) {
    const name = f.name || pastedName(f)
    fl.busy = `Reading ${name}…`
    try {
      const r = await fetch(`/api/ask/attach?name=${encodeURIComponent(name)}`, { method: 'POST', headers: { 'X-CM': '1' }, body: f })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.detail || r.statusText)
      if (!ask.atts.some(a => a.id === d.id)) ask.atts.push(d as Att)
    } catch (e) { toast(`${name}: ${(e as Error).message}`, 'w') }
  }
  fl.busy = ''
}

export function closeFiling() { fl.att = null; fl.opts = [] }

export function dropAtt(id: string) {
  ask.atts = ask.atts.filter(a => a.id !== id)
  if (fl.att?.id === id) closeFiling()
}

export async function suggestFor(a: Att) {
  if (fl.att?.id === a.id) { closeFiling(); return }
  fl.att = a
  fl.opts = []
  fl.busy = `Wiskit is looking for the right note for ${a.name}…`
  try {
    const [s] = await Promise.all([api.post<{ options: FileOpt[]; ai: boolean }>('/api/filing/suggest', { id: a.id }), noteList()])
    if (fl.att?.id !== a.id) return
    fl.opts = s.options
    fl.ai = s.ai
  } catch (e) { toast((e as Error).message, 'w'); closeFiling() }
  finally { fl.busy = '' }
}

async function file(body: Record<string, unknown>, what: string): Promise<{ file: string; title: string } | null> {
  fl.busy = what
  try {
    const r = await api.post<{ file: string; title: string }>('/api/filing/file', body)
    toast(`Filed in “${r.title}”`, '', { label: 'Open', run: () => openNote(r.file) })
    return r
  } catch (e) { toast((e as Error).message, 'w'); return null }
  finally { fl.busy = '' }
}

export async function fileAs(a: Att, o: FileOpt) {
  let title = o.title
  if (o.action === 'new') {
    const v = await promptWin({ title: 'New note', code: 'JVF-01', label: 'Note title', value: o.title, hint: 'It goes to My Notes > Inbox.', ok: 'Create' })
    if (!v) return
    title = v
  }
  const r = await file({ id: a.id, action: o.action, file: o.file, title }, o.action === 'extend' ? `Wiskit is writing what ${a.name} adds…` : `Filing ${a.name}…`)
  if (r) { a.filed = r.title; closeFiling() }
}

export async function fileInto(a: Att, note: string) {
  if (!note) return
  const r = await file({ id: a.id, action: 'append', file: note }, `Filing ${a.name}…`)
  if (r) { a.filed = r.title; closeFiling() }
}

export async function digestAtts() {
  const pics = ask.atts.filter(a => a.kind === 'image')
  if (!pics.length) { toast('Attach a screenshot first', 'w'); return }
  fl.busy = `Transcribing ${pics.length} screenshot(s)…`
  try {
    const [d] = await Promise.all([api.post<{ text: string; failed: number }>('/api/filing/digest', { ids: pics.map(a => a.id) }), noteList()])
    fl.digest = { text: d.text, from: pics.length === 1 ? pics[0].name : `${pics.length} screenshots` }
    if (d.failed) toast(`${d.failed} screenshot(s) could not be read; the rest is below`, 'w')
  } catch (e) { toast((e as Error).message, 'w') }
  finally { fl.busy = '' }
}

export async function placeDigest(how: 'append' | 'new', note = '') {
  const d = fl.digest
  if (!d || (how === 'append' && !note)) return
  let title = ''
  if (how === 'new') {
    const v = await promptWin({ title: 'New note', code: 'JVF-02', label: 'Note title', value: `Screenshot digest ${new Date().toISOString().slice(0, 10)}`, ok: 'Create' })
    if (!v) return
    title = v
  }
  const r = await file({ text: d.text, name: 'Screenshot digest', action: how, file: note, title }, 'Saving the digest…')
  if (r) fl.digest = null
}

export async function copyDigest() {
  if (!fl.digest) return
  try { await navigator.clipboard.writeText(fl.digest.text); toast('Copied the digest') }
  catch { toast('The clipboard is not available here', 'w') }
}
