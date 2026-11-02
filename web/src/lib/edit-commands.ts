// Plan 06: the item window, Add to Brainamon (was Add item), Collection, Bulk edit and Delete become live. Binds the
// commands (add, bulk, delete-sel, new-col, edit-col), installs the Library hooks (open an item,
// edit a collection) and the card actions (Delete, View analysis report).
import AddItemWin from '../windows/AddItemWin.svelte'
import BulkWin from '../windows/BulkWin.svelte'
import CollectionWin from '../windows/CollectionWin.svelte'
import ItemWin from '../windows/ItemWin.svelte'
import { api } from './api'
import { cardActs } from './cardmenu'
import { titleOf } from './cards/card'
import { bind } from './commands'
import { on } from './events.svelte'
import { plural } from './jobs'
import { hooks, lib, refetch } from './library.svelte'
import { quickNote } from './notes.svelte'
import { setWS, toast, ui } from './ui.svelte'
import { confirmWin, openWin } from './windows.svelte'

// A file chooser: resolves with the picked file, or null.
export function pickFile(accept: string): Promise<File | null> {
  return new Promise(res => {
    const f = document.createElement('input')
    f.type = 'file'
    f.accept = accept
    f.onchange = () => res(f.files?.[0] ?? null)
    f.oncancel = () => res(null)
    f.click()
  })
}

export function openItem(id: number, tab = 0) {
  const r = lib.byId.get(id)
  if (!r) { toast(`No.${id} is not in the library`, 'w'); return }
  lib.nvId = id
  openWin({ id: 'item', title: `No.${id} · ${titleOf(r)}`, code: 'ITM-' + String(id).slice(-2), w: 1560, cls: 'itw-win', body: ItemWin, props: { id, tab } })
}

// seed: what Wiskit's panel hands over (a link or text, POST /api/app/capture); it joins an unsaved draft
export function openAdd(seed: { text?: string } = {}) { openWin({ id: 'add', title: 'Add to Brainamon', code: 'ADD-01', w: 1120, cls: 'cap-window', body: AddItemWin, props: { seed } }) }

export function openCollection(name: string | null = null) {
  openWin({ id: 'col', title: name ? `Collection · ${name}` : 'New collection', code: 'COL-04', w: 520, body: CollectionWin, props: { name } })
}

export function openBulk() {
  if (!lib.sel.size && !lib.visIds.length) { toast('No items to edit: clear a filter first', 'w'); return }
  openWin({ id: 'bulk', title: 'Bulk edit', code: 'BLK-06', w: 720, body: BulkWin })
}

// V6 deleteItems: confirm, delete on the server (rows + data/items/<id>/), the SSE refetch drops them.
export async function deleteItems(ids: number[]): Promise<boolean> {
  ids = ids.filter(id => lib.byId.has(id))
  if (!ids.length) return false
  const one = ids.length === 1 ? lib.byId.get(ids[0])! : null
  const ok = await confirmWin({
    title: one ? `Delete No.${one.id}?` : `Delete ${ids.length} items?`, code: 'DEL-01', danger: true, ok: 'Delete',
    msg: one ? `“${titleOf(one)}” leaves the library, with its thumbnail, frames and report.`
      : `${ids.length} items leave the library, with their thumbnails, frames and reports.`,
    detail: 'The app removes data/items/<id>/ too. This cannot be undone.',
  })
  if (!ok) return false
  try {
    const r = await api.post<{ deleted: number }>('/api/items/delete', { ids })
    ids.forEach(id => lib.sel.delete(id))
    await refetch(ids)
    toast(one ? `Deleted No.${one.id}` : `Deleted ${plural(r.deleted, 'item')}`)
    return true
  } catch (e) {
    toast(`Delete failed: ${(e as Error).message}`, 'w')
    return false
  }
}

// Wiskit's panel left some text for the main window (POST /api/app/capture): open Add to Brainamon with it
async function takeCapture() {
  try {
    const r = await api.post<{ text: string }>('/api/app/capture/take')
    if (r.text) openAdd({ text: r.text })
  } catch { /* nothing waiting */ }
}

// Wiskit's wheel left a note request (POST /api/app/note): open Notes writing or recording
async function takeNote() {
  try {
    const r = await api.post<{ mode: string }>('/api/app/note/take')
    if (r.mode === 'write' || r.mode === 'record') await quickNote(r.mode)
  } catch { /* nothing waiting */ }
}

let installed = false
export function installEdits() {
  if (installed) return
  installed = true
  hooks.openItem = openItem
  hooks.editCollection = name => openCollection(name)
  cardActs.del = id => { deleteItems([id]) }
  cardActs.report = id => openItem(id, 1)

  const toLib = () => { if (ui.ws !== 'lib') setWS('lib') }
  bind('add', () => openAdd())
  on('capture_open', () => { takeCapture() })
  takeCapture()                       // the window the panel opened started after the event
  on('note_open', () => { takeNote() })
  takeNote()
  bind('bulk', () => { toLib(); openBulk() })
  bind('delete-sel', () => { deleteItems([...lib.sel]) }, { off: () => !lib.sel.size, offMsg: () => 'Select items in the Library first' })
  bind('new-col', () => openCollection())
  bind('edit-col', () => openCollection(lib.cat), { off: () => lib.cat === 'all', offMsg: () => 'Pick a collection on the rail first' })
}
