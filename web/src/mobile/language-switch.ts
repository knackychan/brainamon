import type { Choice } from '../lib/i18n/index.ts'

export type SwitchCheck = () => string | null | Promise<string | null>
export type SwitchResult = { status: 'same' | 'busy' | 'reloaded' | 'storage-error' } | { status: 'blocked'; reason: string }

const checks = new Set<SwitchCheck>()
let revision = 0
let inFlight = false
let secretFailure = false

export function registerLanguageCheck(check: SwitchCheck): () => void {
  checks.add(check)
  revision++
  return () => { if (checks.delete(check)) revision++ }
}

export function beginLanguageWork(reason = 'settings.language.unsavedWork'): () => void {
  return registerLanguageCheck(() => reason)
}

export function languageWorkChanged(): void { revision++ }
export function languageSwitching(): boolean { return inFlight }
export function languageSecretsSaved(): void { secretFailure = false; revision++ }

export async function switchLanguage(
  next: Choice,
  current: Choice,
  saveSecrets: () => Promise<void>,
  storage: Pick<Storage, 'setItem'>,
  reload: () => void,
): Promise<SwitchResult> {
  if (next === current) return { status: 'same' }
  if (inFlight) return { status: 'busy' }
  inFlight = true
  try {
    if (secretFailure) return { status: 'blocked', reason: 'settings.language.unsavedSecrets' }
    for (;;) {
      const started = revision
      for (const check of checks) {
        let reason: string | null
        try { reason = await check() } catch { return { status: 'blocked', reason: 'settings.language.unsavedWork' } }
        if (reason) return { status: 'blocked', reason }
        if (revision !== started) break
      }
      if (revision !== started) continue
      try { await saveSecrets() } catch { secretFailure = true; return { status: 'blocked', reason: 'settings.language.unsavedSecrets' } }
      if (revision !== started) continue
      try { storage.setItem('bp-lang', next) } catch { return { status: 'storage-error' } }
      reload()
      return { status: 'reloaded' }
    }
  } finally { inFlight = false }
}
