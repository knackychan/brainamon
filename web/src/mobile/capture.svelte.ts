// The phone's capture drafts (plans/09-add-to-brainamon.md): what was shared to Brainamon or typed on the
// Add tab waits here, in IndexedDB (kv 'drafts', src/mobile/store.ts), until the user picks Note or
// Library and presses Save. Nothing is created before that. `cap` mirrors the stored list for the screen;
// with no IndexedDB (a private window) the list lives in memory only.
import { drafts } from './store'
import { isEmpty, newDraft, shareParts, type Draft, type Pic } from '../lib/capture'
import { languageWorkChanged, registerLanguageCheck } from './language-switch.ts'

export const cap = $state({
  list: [] as Draft[],        // every draft kept, oldest first
  ready: false,
  focus: '',                  // a draft that just arrived: the Add screen shows it
  notice: '',                 // why a share could not become a draft (the Android share sheet)
  ask: null as { label: string; text: string } | null,   // Ask Wiskit on an attachment: the Wiskit screen takes it as context
  recoveredReads: [] as { id: string; draftId: string; name: string; text: string; how: 'digest' | 'describe' }[],
  recoveredSuggestions: [] as { id: string; category: string; tags: string }[],
  recoveredFiles: [] as { id: string; file: File }[],
})

const put = (list: Draft[], d: Draft) => (list.some(x => x.id === d.id) ? list.map(x => (x.id === d.id ? d : x)) : [...list, d])
const memoryOnly = new Set<string>(), newOnly = new Set<string>(), failedDrops = new Set<string>(), pending = new Set<Promise<unknown>>()
const versions = new Map<string, number>()
export const captureRevision = (id: string): number => versions.get(id) ?? 0
export function draftEdited(id: string): void { versions.set(id, captureRevision(id) + 1); languageWorkChanged() }

function track<T>(work: Promise<T>): Promise<T> {
  pending.add(work); languageWorkChanged()
  void work.finally(() => { pending.delete(work); languageWorkChanged() }).catch(() => {})
  return work
}

function retainMemory(stored: Draft[]): Draft[] {
  const drafts = new Map(cap.list.filter(d => memoryOnly.has(d.id)).map(d => [d.id, d]))
  return [...stored.filter(d => !failedDrops.has(d.id)).map(d => drafts.get(d.id) ?? d),
    ...[...drafts.values()].filter(d => !stored.some(s => s.id === d.id))]
}

registerLanguageCheck(async () => {
  await Promise.allSettled([...pending])
  for (const id of [...failedDrops]) if (failedDrops.has(id)) await dropDraft(id)
  return memoryOnly.size || failedDrops.size || cap.ask || cap.recoveredReads.length || cap.recoveredSuggestions.length || cap.recoveredFiles.length ? 'settings.language.unsavedDraft' : null
})

export function retainRead(draftId: string, name: string, text: string, how: 'digest' | 'describe'): void {
  cap.recoveredReads = [...cap.recoveredReads, { id: crypto.randomUUID(), draftId, name, text, how }]
  languageWorkChanged()
}

export function clearRead(id: string): void {
  cap.recoveredReads = cap.recoveredReads.filter(result => result.id !== id)
  languageWorkChanged()
}

export function retainSuggestion(category: string, tags: string): void {
  cap.recoveredSuggestions = [...cap.recoveredSuggestions, { id: crypto.randomUUID(), category, tags }]
  languageWorkChanged()
}

export function clearSuggestion(id: string): void {
  cap.recoveredSuggestions = cap.recoveredSuggestions.filter(result => result.id !== id)
  languageWorkChanged()
}

export function retainFile(file: File): void {
  cap.recoveredFiles = [...cap.recoveredFiles, { id: crypto.randomUUID(), file }]
  languageWorkChanged()
}

export function clearFile(id: string): void {
  cap.recoveredFiles = cap.recoveredFiles.filter(result => result.id !== id)
  languageWorkChanged()
}

export async function loadDrafts() {
  const stored = await drafts.all()
  cap.list = retainMemory([...stored, ...cap.list.filter(x => !stored.some(y => y.id === x.id))])   // a share that arrived while booting stays
  cap.ready = true
}

async function saveDraft(copy: Draft) {
  const saved = await track(drafts.edit(l => put(l, copy)))
  if (saved) { memoryOnly.delete(copy.id); newOnly.delete(copy.id); failedDrops.delete(copy.id); cap.list = retainMemory(saved) }
  else { memoryOnly.add(copy.id); cap.list = put(cap.list, copy) }
  languageWorkChanged()
}

// store this draft as it is now; an empty one is dropped
export async function keepDraft(d: Draft) {
  const copy = $state.snapshot(d) as Draft
  if (isEmpty(copy)) return dropDraft(copy.id)
  const wasPendingDrop = failedDrops.delete(copy.id)
  if (wasPendingDrop) languageWorkChanged()
  if (cap.ready && !cap.list.some(item => item.id === copy.id) && !wasPendingDrop) newOnly.add(copy.id)
  await saveDraft(copy)
}

export async function dropDraft(id: string) {
  const version = captureRevision(id)
  const out = (l: Draft[]) => captureRevision(id) === version ? l.filter(x => x.id !== id) : l
  const saved = await track(drafts.edit(out))
  // A late empty-draft deletion must not discard newer typing, even when storage failed.
  if (captureRevision(id) !== version) return
  if (saved) { memoryOnly.delete(id); newOnly.delete(id); failedDrops.delete(id); cap.list = retainMemory(saved) }
  else { memoryOnly.delete(id); if (!newOnly.delete(id)) failedDrops.add(id); cap.list = out(cap.list) }
  languageWorkChanged()
}

export async function dropDraftIfUnchanged(id: string, version: number): Promise<void> {
  let removed = false
  const saved = await track(drafts.edit(list => {
    if (captureRevision(id) !== version) return list
    removed = true
    return list.filter(draft => draft.id !== id)
  }))
  if (!removed || !saved) return
  memoryOnly.delete(id); newOnly.delete(id); failedDrops.delete(id); cap.list = retainMemory(saved)
  languageWorkChanged()
}

// something arrived from outside (the Android share sheet, a share the service worker could not store).
// A lone link (alone or with only its page title) is kept as the cleaned link and the title, as public/sw.js does.
export async function shareIn(text: string, pic: Pic | null = null): Promise<Draft> {
  const p = pic ? { text, title: '' } : shareParts(text)
  const d: Draft = { ...newDraft(pic ? 'file' : 'share', p.text, pic), title: p.title }
  newOnly.add(d.id)
  await saveDraft(d)
  cap.focus = d.id
  return d
}
