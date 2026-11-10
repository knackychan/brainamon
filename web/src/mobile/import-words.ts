import SOURCES from './import-sources.json' with { type: 'json' }
import { messages as english } from '../lib/i18n/en/imports.ts'
import type { CaptureWords } from '../lib/capture'
import type { SiteId } from './sites'
import { t } from '../lib/i18n/index.ts'
import { captureError } from './capture-words.ts'

// Default guide objects remain English for the prototype; the phone supplies its lazy formatter.
export function importGuides(words: CaptureWords = key => english[key as keyof typeof english] as string) {
  return SOURCES.map(source => ({ ...source, id: source.id as SiteId,
    ...(source.id === 'instagram' ? { what: words('imports.instagram.what'), pageLabel: words('imports.instagram.pageLabel'), wait: words('imports.instagram.wait') } : {}),
    steps: Array.from({ length: source.id === 'instagram' ? 6 : 3 }, (_, i) => words(`imports.${source.id}.step${i + 1}`)),
  }))
}

export function importResult(added: number, duplicates: number, skipped: number): string {
  const parts = [t('imports.result.added', { n: added })]
  if (duplicates) parts.push(t('imports.result.duplicates', { n: duplicates }))
  if (skipped) parts.push(t('imports.result.skipped', { n: skipped }))
  return parts.join(' · ') + t(added ? 'imports.result.saved' : 'imports.result.none')
}

export function importError(error: unknown): string {
  const e = error as { code?: string; message?: string }
  return e?.code === 'importNotSaved' ? t('imports.error.notSaved') : e?.code === 'importTooBig' ? t('imports.error.tooBig') : t('imports.error.detail', { message: captureError(error) })
}
