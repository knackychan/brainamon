import { t, type Key, type Params } from '../lib/i18n/index.ts'
import type { SaveState } from '../lib/capture'

// Pure/shared helpers keep their English defaults; only phone presentation supplies this formatter.
export const captureText = (key: string, params?: Params): string => t(key as Key, params)
export function captureError(error: unknown): string {
  const e = error as { message?: string; displayKey?: Key; displayParams?: Params }
  return e?.displayKey ? t(e.displayKey, e.displayParams) : e?.message ?? String(error)
}

const STATES: Record<SaveState, Key> = { synced: 'capture.outbox.synced', pending: 'capture.outbox.pending', failed: 'capture.outbox.notSaved' }
export const saveStateLabel = (state: SaveState): string => t(STATES[state])
const TYPES: Record<string, Key> = {
  Reel: 'item.type.reel', Video: 'item.type.video', Post: 'item.type.post', Link: 'capture.destination.typeLink',
  Recipe: 'capture.destination.typeRecipe', Tutorial: 'capture.destination.typeTutorial', Other: 'capture.destination.typeOther',
}
export const captureType = (type: string): string => Object.hasOwn(TYPES, type) ? t(TYPES[type]) : type
// Capture has no falsy "never" sentinel: timestamp 0 is still an elapsed date here.
export function draftAgo(ms: number, now = Date.now()): string {
  const m = Math.round((now - ms) / 60000)
  return m < 1 ? t('common.ago.now') : m < 60 ? t('common.ago.minutes', { n: m }) : m < 1440 ? t('common.ago.hours', { n: Math.round(m / 60) }) : t('common.ago.days', { n: Math.round(m / 1440) })
}
