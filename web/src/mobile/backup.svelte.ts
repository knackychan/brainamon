import { t } from '../lib/i18n/index.ts'
import { phoneWords, nativeError } from './settings-words'
import { backupTask, beginBackupTask, pauseBackupTask, runBackupTask, type BackupTask } from './mirror/phone-backup'
import type { Changes } from './mirror/changes'
import { pairing } from './mirror/pairing'
import { beginLanguageWork } from './language-switch.ts'

export const backup = $state({ task: backupTask(), busy: false, step: '', error: '', deleted: undefined as number | undefined })
export async function runBackup(changes: Changes, kind?: BackupTask['kind'], prefix = '') {
  if (backup.busy) return
  const done = beginLanguageWork()
  backup.busy = true; backup.deleted = undefined; backup.error = ''; backup.step = t('backup.task.stoppingCloud')
  const key = pairing()?.k
  try {
    if (kind) await beginBackupTask(kind, prefix)
    else await pauseBackupTask(false)
    backup.task = backupTask()
    await runBackupTask(changes, (text, deleted) => { backup.step = text; backup.deleted = deleted; backup.task = backupTask() }, phoneWords)
    location.replace(location.pathname + '#/backup'); location.reload()
  } catch (e) {
    backup.error = backupTask()?.paused ? '' : nativeError('backup', e)
    if (pairing()?.k !== key) {
      sessionStorage.setItem('bp-note', backup.error || t('backup.task.replacementPaused'))
      location.replace(location.pathname + '#/backup'); location.reload()
    }
  }
  finally { backup.task = backupTask(); backup.busy = false; backup.step = ''; done() }
}
export async function pauseBackup() {
  const done = beginLanguageWork()
  try { await pauseBackupTask(true); backup.task = backupTask() }
  finally { done() }
}
