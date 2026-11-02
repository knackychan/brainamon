// What the desktop Add to Brainamon window writes (plans/09-add-to-brainamon.md). Every call is a route
// that already exists: no new write path. A note is made with POST /api/my-notes then PUT (the phone's
// way), an addition to a note is POST /api/filing/file (one section on the Writer, the old text
// untouched), a Library item is POST /api/items (+ PUT /api/items/<id>/thumb for a picture), and a
// picture's text comes from POST /api/filing/read (the same digest Add a picture uses).
import { api, ApiError } from './api'
import { INBOX, libraryNote, linkOf, picKind, type Draft, type NoteRef, type Preview } from './capture'
import type { Row } from './library.svelte'

export interface NoteSaved { file: string; title: string }
export interface ItemSaved { row: Row & { fetching?: boolean }; thumb: boolean }

export const listNotes = () => api.get<NoteRef[]>('/api/my-notes')

// what a lone link's page says (POST /api/link/preview: a read on the PC, nothing saved)
export const linkPreview = (url: string) => api.post<Preview>('/api/link/preview', { url })

// the text of a picture (digest or describe), PDF or text file; nothing is kept
export async function readFileText(f: File, how: 'digest' | 'describe'): Promise<string> {
  if (picKind({ name: f.name, type: f.type, blob: f }) === 'text') return f.text()
  const r = await fetch(`/api/filing/read?name=${encodeURIComponent(f.name)}&how=${how}`, { method: 'POST', headers: { 'X-CM': '1' }, body: f })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(d.detail || r.statusText)
  return String(d.text || '')
}

// `made` is a note an earlier try created but did not fill: reused, never doubled
// (a `made` note deleted since is replaced by a new one)
export async function saveNewNote(title: string, body: string, made: string, onMade: (file: string) => void, category = INBOX): Promise<NoteSaved> {
  if (made) {
    try { return await api.put<NoteSaved>(`/api/my-notes/${encodeURIComponent(made)}`, { title, category, body }) }
    catch (e) { if (!(e instanceof ApiError && e.status === 404)) throw e }
  }
  const file = (await api.post<NoteSaved>('/api/my-notes', { title, category })).file
  onMade(file)
  return api.put<NoteSaved>(`/api/my-notes/${encodeURIComponent(file)}`, { title, category, body })
}

export const appendToNote = (file: string, name: string, text: string) =>
  api.post<NoteSaved>('/api/filing/file', { action: 'append', file, name, text })

// With a picture the picture becomes the thumbnail and the text the description: a description stops the
// caption fetch, which would replace the picture (the rule the old Add item window had). Without one the
// server stands the link in and fetches the thumbnail and caption; the text around the link goes into
// the card's note with the comment (libraryNote).
export async function saveItem(d: Draft): Promise<ItemSaved> {
  const img = picKind(d.pic) === 'image' ? d.pic : null
  const row = await api.post<ItemSaved['row']>('/api/items', {
    url: linkOf(d.text), notes: img ? d.comment.trim() : libraryNote(d), category: d.collection, type: d.type, tags: d.tags.trim(),
    ...(img ? { description: d.text.trim() } : {}),
  })
  let thumb = true
  if (img) {
    const r = await fetch(`/api/items/${row.id}/thumb`, { method: 'PUT', headers: { 'X-CM': '1' }, body: img.blob })
    thumb = r.ok
  }
  return { row, thumb }
}
