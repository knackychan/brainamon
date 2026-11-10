// A vault round's progress bar (Settings > Backup & phones on the PC, Settings > Obsidian on the phone): the percent done
// and, after 30 files and 10 seconds, the time left at the pace so far.
// Wait past the first parallel batch so startup overhead does not dominate the estimate.
// `since` is when the step began and `now` the moment `done` was counted, both ms since the epoch.
export interface Progress { pct: number; left: string }

export function progress(done: number, total: number, since: number, now = Date.now(), words?: (key: string, params?: Record<string, unknown>) => string): Progress {
  const pct = total > 0 ? Math.min(100, Math.floor(100 * done / total)) : 0
  const elapsed = now - since
  if (!since || done < 30 || done >= total || elapsed < 10000) return { pct, left: '' }
  return { pct, left: timeLeft(elapsed / done * (total - done), words) }
}

function timeLeft(ms: number, words?: (key: string, params?: Record<string, unknown>) => string): string {
  const m = Math.round(ms / 60000)
  if (m < 1) return (words?.('backup.progress.underMinute', {}) ?? 'under a minute left')
  if (m < 60) return (words?.('backup.progress.minutes', { n: m }) ?? `about ${m} min left`)
  const h = Math.floor(m / 60), r = m % 60
  return (words?.('backup.progress.hours', { h, minutes: r ? words!('backup.progress.minuteSuffix', { n: r }) : '' }) ?? `about ${h} h${r ? ` ${r} min` : ''} left`)
}
