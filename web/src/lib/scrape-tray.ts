import type { JobSnap } from './events.svelte'

export interface ImportResult { added: number; duplicates: number; invalid: number; ids: number[] }
export interface Tray {
  site: string
  phase: 'ready' | 'scan' | 'wait' | 'play' | 'done' | 'off'
  read: number | null
  result: ImportResult | null
  ended: '' | 'stopped' | 'failed'
}

export const PLAY_MAX = 12
export const idleTray = (site: string): Tray => ({ site, phase: 'ready', read: null, result: null, ended: '' })
export const startScan = (site: string): Tray => ({ ...idleTray(site), phase: 'scan' })

export function readCount(tray: Tray, n: number): Tray {
  return tray.phase === 'scan' && Number.isSafeInteger(n) && n >= 0 && n <= 9999999 && (tray.read === null || n > tray.read)
    ? { ...tray, read: n } : tray
}

export function scanEnded(tray: Tray, last: Pick<JobSnap, 'state' | 'err'> | null): Tray {
  if (tray.phase !== 'scan') return tray
  if (last?.state === 'stopped') return { ...tray, phase: 'off', ended: 'stopped' }
  if (last?.err) return { ...tray, phase: 'off', ended: 'failed' }
  return { ...tray, phase: 'wait' }
}

export const imported = (tray: Tray, result: ImportResult): Tray => ({ ...tray, phase: 'play', result, ended: '' })
export const played = (tray: Tray): Tray => tray.phase === 'play' ? { ...tray, phase: 'done' } : tray
export const playRows = (result: ImportResult): number => Math.min(PLAY_MAX, result.ids.length)
export function playedCount(result: ImportResult, shown: number): number {
  const k = playRows(result)
  return k ? Math.round(result.added * Math.min(Math.max(0, shown), k) / k) : result.added
}
