// What syncs on this phone, one lane per kind, for Settings > Sync (at the top of More) and the sync panel of the
// section pages (SyncPanel.svelte): the read of Google Drive (with the changes sent first on
// Sync now), this phone's Obsidian vault round, the PC's vault round (from the status file it writes to
// Drive; read while More is open) and the slow picture queue. Call it inside $derived: every value comes from
// reactive state. `active`: running, queued or paused, so the sync panel draws its bar.
import { t } from '../lib/i18n/index.ts'
import { phoneWords } from './settings-words'
import { isApp } from './native'
import { driveStatus, driveWork, fmtAgo, mirrorSource, phone, pics, solo, source } from './state.svelte'
import { pcLine, pcProgress, vault } from './vault/auto.svelte'
import { network, syncPaused, syncPauseReason } from './network.svelte'
import { backup } from './backup.svelte'
import { token } from './mirror/pairing'
import { lampLabel } from './settings-words'
import { syncLine } from './settings-lines'
import { vaultLamp } from './settings-facts.svelte'
import { nativeSync, nativeSyncText, nativePhasePct } from './sync/native.svelte'

export type LaneKey = 'network' | 'drive' | 'vault' | 'pc' | 'pics'
export interface Lane { key: LaneKey; name: string; tag: string; active: boolean; text: string; pct: number | null; files?: { done: number; total: number } }

export function syncLanes(): Lane[] {
  const out: Lane[] = []
  const drive = driveStatus()
  const work = driveWork()
  const dname = mirrorSource ? t('shell.sync.whereDrive') : t('backup.lane.pc')
  const paused = !!mirrorSource && syncPaused()
  if (paused) out.push({ key: 'network', name: t('backup.lane.paused'), tag: 'paused', active: true, pct: null,
                         text: t('backup.lane.pauseDetail', { reason: syncPauseReason(phoneWords, true) }) })
  if (backup.task && !backup.busy) out.push({ key: 'drive', name: dname, tag: backup.task.paused ? 'paused' : 'waiting', active: true, text: backup.error || t('backup.lane.savedTask'), pct: null })
  else if (paused) out.push({ key: 'drive', name: dname, tag: 'paused', active: false, text: t('backup.lane.resume'), pct: null })
  else if (work) out.push({ key: 'drive', name: dname, tag: 'running', active: true, text: work.text, pct: work.pct })
  else if (nativeSync.supported && nativeSync.state && !['idle', 'syncing'].includes(nativeSync.state)) out.push({ key: 'drive', name: dname, tag: ['queued', 'retry', 'offline', 'wifi'].includes(nativeSync.state) ? 'waiting' : 'error', active: false, text: nativeSyncText(), pct: null })
  else out.push({ key: 'drive', name: dname, tag: drive.ok ? 'idle' : drive.lamp, active: false, pct: null,
                  text: drive.why || (phone.sync?.end ? phone.sync.msg : t('backup.lane.copy', { ago: fmtAgo(phone.synced) })) })

  if (isApp && !solo && source.syncVault) {
    const v = vault, lamp = vaultLamp()
    if (lamp === 'paused') out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'paused', active: false, text: t('backup.lane.resumes'), pct: null })
    else if (v.opts.on && nativeSync.supported && ['queued', 'retry', 'wifi', 'offline'].includes(nativeSync.state)) out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'waiting', active: false, text: nativeSyncText(), pct: null })
    else if (v.opts.on && nativeSync.supported && nativeSync.state === 'syncing' && nativeSync.phase !== 'vault') out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'waiting', active: false, text: t('backup.lane.queued', { where: dname }), pct: null })
    else if (nativeSync.supported && nativeSync.state === 'syncing' && nativeSync.phase === 'vault') {
      const step = nativeSync.vaultStep
      const text = step?.key ? t(step.key) : nativeSyncText()
      out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'running', active: true, text: `${text}${step && step.total > 0 ? ` · ${step.done}/${step.total}` : ''}`, pct: nativePhasePct() })
    }
    else if (lamp === 'syncing' || lamp === 'stopping') out.push({ key: 'vault', name: t('backup.lane.vault'), tag: v.stopping ? 'stopping' : 'running', active: true, text: v.step || t('backup.lane.syncing'), pct: v.pct })
    else if (lamp === 'queued') out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'queued', active: true, text: t('backup.lane.queued', { where: dname }), pct: null })
    else if (lamp === 'off' || lamp === 'no folder') out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'off', active: false, text: v.opts.uri ? t('backup.lane.folder', { name: v.opts.name || t('backup.lane.chosen') }) : t('backup.lane.chooseFolder'), pct: null })
    else if (lamp === 'needs Drive') out.push({ key: 'vault', name: t('backup.lane.vault'), tag: 'needs Drive', active: false, text: drive.why, pct: null })
    else out.push({ key: 'vault', name: t('backup.lane.vault'), tag: ['in step', 'not run yet'].includes(lamp) ? 'idle' : lamp, active: false, text: v.brake || v.line || t('backup.lane.notRun'), pct: null })

    const files = nativeSync.supported ? nativeSync.vaultFiles : v.files
    if (v.opts.on && files) out[out.length - 1].files = files

    if (v.opts.on && drive.ok && !paused) {
      const pr = v.pc ? pcProgress(v.pc, phoneWords) : null
      out.push({ key: 'pc', name: t('backup.lane.pcVault'), tag: pr ? 'running' : 'idle', active: !!pr, pct: pr?.pct ?? null,
                 text: v.pc ? pcLine(v.pc, phoneWords) : v.pcRead ? t('backup.vault.pcFirst') : t('backup.lane.checking') })
    }
  }

  if (!paused && pics.state !== 'idle' && pics.total > 0) {
    const wait = pics.state === 'wait'
    out.push({ key: 'pics', name: t('backup.lane.pictures'), tag: wait ? 'paused' : 'running', active: true, pct: Math.min(100, Math.round(pics.done / pics.total * 100)),
               text: wait ? t('backup.lane.picsWait', { done: pics.done, total: pics.total }) : t('backup.lane.picsFetch', { done: pics.done, total: pics.total }) })
  }
  return out
}

export function syncSummary(): string {
  void phone.tokenAt; void phone.signIn
  if (network.pausePending || network.pauseFailed) return syncPauseReason(phoneWords)
  const lanes = syncLanes(), drive = lanes.find(l => l.key === 'drive')
  const running = lanes.filter(l => l.tag === 'running' || l.tag === 'stopping').length
  const queued = lanes.filter(l => l.tag === 'queued').length
  if (nativeSync.supported && nativeSync.state && !['syncing', 'idle'].includes(nativeSync.state) && !syncPaused()) return nativeSyncText()
  const lamp = backup.task ? lampLabel(drive?.tag ?? 'waiting') : syncPaused() ? network.manualPause ? lampLabel('paused') : syncPauseReason(phoneWords, true)
    : running ? t('settings.sync.runningCount', { running, queued: queued ? t('settings.sync.queuedSuffix', { n: queued }) : '' })
    : queued ? t('settings.sync.queuedCount', { n: queued }) : driveStatus().ok ? 'idle' : lampLabel(driveStatus().lamp)
  return syncLine({ signedIn: !!mirrorSource && !!token(mirrorSource.pair), lamp, wifiOnly: network.wifiOnly }, phoneWords)
}
