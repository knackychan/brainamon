import { backupTask, beginBackupTask, pauseBackupTask, runBackupTask, type BackupTask } from './mirror/phone-backup'
import type { Changes } from './mirror/changes'
import { pairing } from './mirror/pairing'

export const backup = $state({ task: backupTask(), busy: false, step: '', error: '' })
export async function runBackup(changes: Changes, kind?: BackupTask['kind'], prefix = '') {
  if (backup.busy) return
  backup.busy = true; backup.error = ''; backup.step = 'Stopping previous cloud work…'
  const key = pairing()?.k
  try {
    if (kind) await beginBackupTask(kind, prefix)
    else await pauseBackupTask(false)
    backup.task = backupTask()
    await runBackupTask(changes, text => { backup.step = text; backup.task = backupTask() })
    location.replace(location.pathname + '#/backup'); location.reload()
  } catch (e) {
    backup.error = backupTask()?.paused ? '' : (e as Error).message
    if (pairing()?.k !== key) {
      sessionStorage.setItem('bp-note', backup.error || 'Replacement saved. The remaining backup task is paused.')
      location.replace(location.pathname + '#/backup'); location.reload()
    }
  }
  finally { backup.task = backupTask(); backup.busy = false; backup.step = '' }
}
export async function pauseBackup() {
  await pauseBackupTask(true)
  backup.task = backupTask()
}
