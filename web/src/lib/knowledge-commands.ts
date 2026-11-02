// Plan 08: the "Notes" group of the Ctrl+K palette, and Wiskit's note chips open in Knowledge;
// plan 10: personal notes open in the Notes editor, and File > New note.
import { askHooks } from './ask.svelte'
import { bind } from './commands'
import { installKnowledge, ks, openNoteInKnowledge } from './knowledge.svelte'
import { newNote, openMyNote } from './notes.svelte'
import { addPaletteProvider } from './palette'
import { setWS, toast } from './ui.svelte'
import { promptWin } from './windows.svelte'

export function openNoteAnywhere(file: string) {
  const row = ks.notes.find(n => n.file === file)
  if (row?.kind === 'Personal') { setWS('notes'); openMyNote(file) } else openNoteInKnowledge(file)
}

let installed = false
export function installKnowledgeCommands() {
  if (installed) return
  installed = true
  installKnowledge()
  askHooks.openNote = openNoteAnywhere
  bind('new-note', async () => {
    const v = await promptWin({ title: 'New note', code: 'NTE-43', label: 'Note title', ok: 'Create' })
    if (v) { try { await newNote(v) } catch (e) { toast((e as Error).message, 'w') } }
  })
  addPaletteProvider(q => {
    const rows = ks.notes.filter(n => n.title.toLowerCase().includes(q) || n.file.toLowerCase().includes(q)).slice(0, 4)
      .map(n => ({ label: n.title, key: n.file, icon: 'note', run: () => openNoteAnywhere(n.file) }))
    return { name: 'Notes', rows }
  })
}
