import { enqueue } from './voice'
import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from './language-switch.ts'

export const unsavedVoice = $state({ items: [] as { id: string; file: string; blob: Blob }[] })
const retrying = new Set<string>()

registerLanguageCheck(() => unsavedVoice.items.length ? 'settings.language.unsavedRecording' : null)

export function retainVoice(file: string, blob: Blob): void {
  unsavedVoice.items = [...unsavedVoice.items, { id: crypto.randomUUID(), file, blob }]
  languageWorkChanged()
}

export function discardVoice(id: string): void {
  if (retrying.has(id)) return
  unsavedVoice.items = unsavedVoice.items.filter(item => item.id !== id)
  languageWorkChanged()
}

export async function retryVoice(id: string): Promise<boolean> {
  const item = unsavedVoice.items.find(entry => entry.id === id)
  if (!item || retrying.has(id)) return false
  retrying.add(id)
  const done = beginLanguageWork()
  try { await enqueue(item.file, item.blob); retrying.delete(id); discardVoice(id); return true }
  catch { return false }
  finally { retrying.delete(id); done() }
}
