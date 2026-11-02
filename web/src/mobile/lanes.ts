// What syncs on this phone, one lane per kind, for More > Sync (at the top of More) and the strip under the
// app bar on the other screens (SyncStrip.svelte): the read of Google Drive (with the changes sent first on
// Sync now), this phone's Obsidian vault round, the PC's vault round (from the status file it writes to
// Drive; read while More is open) and the slow picture queue. Call it inside $derived: every value comes from
// reactive state. `active`: running, queued or paused, so the strip shows it.
import { isApp } from './native'
import { driveStatus, driveWork, fmtAgo, mirrorSource, phone, pics, solo, source } from './state.svelte'
import { PC_FIRST, pcLine, pcProgress, vault } from './vault/auto.svelte'
import { syncPaused, syncPauseReason } from './network.svelte'
import { backup } from './backup.svelte'

export type LaneKey = 'network' | 'drive' | 'vault' | 'pc' | 'pics'
export interface Lane { key: LaneKey; name: string; tag: string; active: boolean; text: string; pct: number | null }

export function syncLanes(): Lane[] {
  const out: Lane[] = []
  const drive = driveStatus()
  const work = driveWork()
  const dname = mirrorSource ? 'Google Drive' : 'Your PC'
  const paused = !!mirrorSource && syncPaused()
  if (paused) out.push({ key: 'network', name: 'Sync paused', tag: 'paused', active: true, pct: null,
                         text: syncPauseReason().split(' · ')[1] + ' · changes stay on this phone' })
  if (backup.task && !backup.busy) out.push({ key: 'drive', name: dname, tag: backup.task.paused ? 'paused' : 'waiting', active: true, text: backup.error || 'Backup task saved. Open Backup & phones to continue.', pct: null })
  else if (paused) out.push({ key: 'drive', name: dname, tag: 'paused', active: false, text: 'Resume sync when ready; network restrictions still apply', pct: null })
  else if (work) out.push({ key: 'drive', name: dname, tag: 'running', active: true, text: work.text, pct: work.pct })
  else out.push({ key: 'drive', name: dname, tag: drive.ok ? 'idle' : drive.lamp, active: false, pct: null,
                  text: drive.why || (phone.sync?.end ? phone.sync.msg : `Copy from ${fmtAgo(phone.synced)}`) })

  if (isApp && !solo && source.syncVault) {
    const v = vault
    if (paused && v.opts.on) out.push({ key: 'vault', name: 'Obsidian vault', tag: 'paused', active: false, text: 'Resumes automatically when the connection allows', pct: null })
    else if (v.busy) out.push({ key: 'vault', name: 'Obsidian vault', tag: v.stopping ? 'stopping' : 'running', active: true, text: v.step || 'Syncing…', pct: v.prog?.pct ?? null })
    else if (v.queued) out.push({ key: 'vault', name: 'Obsidian vault', tag: 'queued', active: true, text: `Starts when the ${dname} read ends`, pct: null })
    else if (!v.opts.on) out.push({ key: 'vault', name: 'Obsidian vault', tag: 'off', active: false, text: v.opts.uri ? `Folder: ${v.opts.name || 'chosen'} · press Start to keep it in step with the PC` : 'Choose the folder your Obsidian app uses to keep it in step with the PC', pct: null })
    else if (!drive.ok) out.push({ key: 'vault', name: 'Obsidian vault', tag: 'needs Drive', active: false, text: drive.why, pct: null })
    else out.push({ key: 'vault', name: 'Obsidian vault', tag: v.brake ? 'held' : v.outcome === 'error' ? 'error' : v.outcome === 'waiting' ? 'waiting for PC' : 'idle', active: false, text: v.brake || v.line || 'Not run yet · it runs when the app opens and every 2 minutes', pct: null })

    if (v.opts.on && drive.ok && !paused) {
      const pr = v.pc ? pcProgress(v.pc) : null
      out.push({ key: 'pc', name: 'Vault on the PC', tag: pr ? 'running' : 'idle', active: !!pr, pct: pr?.pct ?? null,
                 text: v.pc ? pcLine(v.pc) : v.pcRead ? PC_FIRST : 'Checking…' })
    }
  }

  if (!paused && pics.state !== 'idle' && pics.total > 0) {
    const wait = pics.state === 'wait'
    out.push({ key: 'pics', name: 'Pictures', tag: wait ? 'paused' : 'running', active: true, pct: Math.min(100, Math.round(pics.done / pics.total * 100)),
               text: wait ? `${pics.done} / ${pics.total} · waiting a few minutes, the site asked to slow down` : `Fetching ${pics.done} / ${pics.total}` })
  }
  return out
}
