// The rules of the phone's import run (projects/motion-language plan 07, ImportRun.svelte): the line under "N posts
// ready to import", which squares of the picture grid wait, are scanned or have landed, and when the pictures are
// finished. Pure: the component hands in what it reads (the rows, the work marks, the picture queue's state).
import type { Key } from '../lib/i18n/index.ts'

export const GRID_MAX = 24, GRID_COLS = 6, GRID_STEP_MS = 65
export type Square = 'wait' | 'run' | 'done'
export type Say = (key: Key, params?: Record<string, unknown>) => string

// a scan's end, in words (SiteRead's REASONS, translated); an unknown reason reads as a stop
function reasonKey(reason: string): Key {
  switch (reason) {
    case 'end': return 'importrun.reason.end'
    case 'known': return 'importrun.reason.known'
    case 'cap': return 'importrun.reason.cap'
    case 'empty': return 'importrun.reason.empty'
    case 'failure': return 'importrun.reason.failure'
    case 'unsave-failed': return 'importrun.reason.unsaveFailed'
    default: return 'importrun.reason.stop'
  }
}

export function reasonText(res: { reason: string; unsaveFailed?: boolean } | null, say: Say): string {
  const text = res ? say(reasonKey(res.reason)) : say('importrun.reason.cut')
  return res?.unsaveFailed ? `${text} · ${say('imports.unsave.failed')}` : text
}

export const capitalise = (text: string): string => text ? text.charAt(0).toUpperCase() + text.slice(1) : text

// under the title: the reason (capitalised), then how many were already there and how many were refused (zero parts left out)
export function readySub(reason: string, known: number, refused: number, say: Say): string {
  const parts = reason ? [capitalise(reason)] : []
  if (known > 0) parts.push(say('importrun.known', { n: known }))
  if (refused > 0) parts.push(say('importrun.refused', { n: refused }))
  return parts.join(' · ')
}

// the grid follows the first GRID_MAX added posts: a square waits (skeleton), is scanned while its picture is
// fetched (the picture lane's work mark `run`) and has landed once the row has a thumbnail
export function squares(ids: readonly number[], has: (id: number) => boolean, running: (id: number) => boolean): Square[] {
  return ids.slice(0, GRID_MAX).map(id => has(id) ? 'done' : running(id) ? 'run' : 'wait')
}

export const gotCount = (ids: readonly number[], has: (id: number) => boolean): number => ids.filter(has).length

// the pictures are finished once the queue was started for this import and either every post has its picture or
// the queue is no longer working (idle, or waiting out the site's slow-down)
export function picsFinished(ids: readonly number[], has: (id: number) => boolean, started: boolean, state: 'idle' | 'run' | 'wait'): boolean {
  return started && (ids.length === 0 || ids.every(has) || state !== 'run')
}
