// The phone's capture drafts (plans/09-add-to-brainamon.md): what was shared to Brainamon or typed on the
// Add tab waits here, in IndexedDB (kv 'drafts', src/mobile/store.ts), until the user picks Note or
// Library and presses Save. Nothing is created before that. `cap` mirrors the stored list for the screen;
// with no IndexedDB (a private window) the list lives in memory only.
import { drafts } from './store'
import { isEmpty, newDraft, shareParts, type Draft, type Pic } from '../lib/capture'

export const cap = $state({
  list: [] as Draft[],        // every draft kept, oldest first
  ready: false,
  focus: '',                  // a draft that just arrived: the Add screen shows it
  notice: '',                 // why a share could not become a draft (the Android share sheet)
  ask: null as { label: string; text: string } | null,   // Ask Wiskit on an attachment: the Wiskit screen takes it as context
})

const put = (list: Draft[], d: Draft) => (list.some(x => x.id === d.id) ? list.map(x => (x.id === d.id ? d : x)) : [...list, d])

export async function loadDrafts() {
  const stored = await drafts.all()
  cap.list = [...stored, ...cap.list.filter(x => !stored.some(y => y.id === x.id))]   // a share that arrived while booting stays
  cap.ready = true
}

// store this draft as it is now; an empty one is dropped
export async function keepDraft(d: Draft) {
  const copy = $state.snapshot(d) as Draft
  if (isEmpty(copy)) return dropDraft(copy.id)
  cap.list = (await drafts.edit(l => put(l, copy))) ?? put(cap.list, copy)
}

export async function dropDraft(id: string) {
  const out = (l: Draft[]) => l.filter(x => x.id !== id)
  cap.list = (await drafts.edit(out)) ?? out(cap.list)
}

// something arrived from outside (the Android share sheet, a share the service worker could not store).
// A lone link (alone or with only its page title) is kept as the cleaned link and the title, as public/sw.js does.
export async function shareIn(text: string, pic: Pic | null = null): Promise<Draft> {
  const p = pic ? { text, title: '' } : shareParts(text)
  const d: Draft = { ...newDraft(pic ? 'file' : 'share', p.text, pic), title: p.title }
  cap.list = (await drafts.edit(l => put(l, d))) ?? put(cap.list, d)
  cap.focus = d.id
  return d
}
