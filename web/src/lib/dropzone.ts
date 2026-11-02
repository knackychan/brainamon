// Drop a picture or file anywhere in the window (Add to Brainamon, desktop and the phone page in a
// browser). While files are dragged over the window `over(true)` shows the mint overlay; it clears on
// leaving the window, on drop, on Escape and when the window loses focus. Only drags that carry files
// count: dragging text into the content box behaves as it always did. A drop that an element under the
// pointer already handled (it called preventDefault) is left to it.
export interface DropHooks {
  files: (files: File[]) => void
  over: (on: boolean) => void
}

export function attachDrop(h: DropHooks): () => void {
  let depth = 0, shown = false
  const has = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files')
  const show = (on: boolean) => { shown = on; h.over(on) }
  const end = () => { depth = 0; show(false) }
  const enter = (e: DragEvent) => { if (!has(e)) return; e.preventDefault(); depth++; show(true) }
  const over = (e: DragEvent) => { if (!has(e)) return; e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; show(true) }
  const leave = (e: DragEvent) => { if (!has(e)) return; depth = Math.max(0, depth - 1); if (!depth || !e.relatedTarget) end() }
  const drop = (e: DragEvent) => {
    if (e.defaultPrevented) { end(); return }          // a part of the page took it (Wiskit's desk, Import): theirs
    const files = [...(e.dataTransfer?.files ?? [])]
    if (has(e) || files.length) e.preventDefault()
    end()
    if (files.length) h.files(files)
  }
  // Escape closes the overlay first; the window behind it stays open
  const key = (e: KeyboardEvent) => { if (e.key === 'Escape' && shown) { e.stopPropagation(); end() } }
  window.addEventListener('dragenter', enter)
  window.addEventListener('dragover', over)
  window.addEventListener('dragleave', leave)
  window.addEventListener('drop', drop)
  window.addEventListener('dragend', end)
  window.addEventListener('blur', end)
  window.addEventListener('keydown', key, true)
  return () => {
    window.removeEventListener('dragenter', enter)
    window.removeEventListener('dragover', over)
    window.removeEventListener('dragleave', leave)
    window.removeEventListener('drop', drop)
    window.removeEventListener('dragend', end)
    window.removeEventListener('blur', end)
    window.removeEventListener('keydown', key, true)
    end()
  }
}

// an image the browser can open: a damaged or renamed file is refused before it replaces anything
export async function decodes(file: Blob): Promise<boolean> {
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    img.src = url
    await img.decode()
    return true
  } catch { return false } finally { URL.revokeObjectURL(url) }
}
