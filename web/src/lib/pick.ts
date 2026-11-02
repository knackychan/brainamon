// Picking files and folders (plan 12). In the desktop window (plan 13) the page asks the native
// dialog through window.pywebview.api.pick(kind) and gets local paths; in a browser tab there is
// no path, so callers upload the File itself or take a typed path.
declare global {
  interface Window { pywebview?: { api?: { pick?: (kind: string) => Promise<string[] | null>; close?: () => Promise<void> } } }
}
export type PickKind = 'import' | 'csv' | 'json' | 'image' | 'video' | 'cookies' | 'folder' | 'claude'

export const isDesktop = () => typeof window.pywebview?.api?.pick === 'function'

// A native dialog in the desktop window: the first picked path, or null (cancelled / browser tab).
export async function pickPath(kind: PickKind): Promise<string | null> {
  if (!isDesktop()) return null
  try { return (await window.pywebview!.api!.pick!(kind))?.[0] ?? null } catch { return null }
}

// A browser file chooser: the picked File, or null.
export function pickFileObj(accept: string): Promise<File | null> {
  return new Promise(res => {
    const f = document.createElement('input')
    f.type = 'file'
    f.accept = accept
    f.onchange = () => res(f.files?.[0] ?? null)
    f.oncancel = () => res(null)
    f.click()
  })
}
