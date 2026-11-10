// The Recovery group of Settings > Backup & phones (PhoneRecovery.svelte) and the status keys (actions.ts) share one state
// for the phone without a PC (docs/superpowers/plans/2026-10-31-phone-backup-phones.md, sub-plan 05): the setup form
// open or not, the action running, its message and its error. Check recovery file… and Save recovery file… open their
// chooser or download inside the tap (a browser keeps user activation only until the first wait).
import { t } from '../lib/i18n/index.ts'
import { nativeError } from './settings-words'
import { pickFileObj } from '../lib/pick'
import { RECOVERY_LIMIT } from './mirror/recovery-envelope'
import { savePhoneKit, verifyPhoneRecovery } from './mirror/phone-recovery'
import { mirrorSource, phone } from './state.svelte'
import { beginLanguageWork } from './language-switch.ts'

export const rec = $state({ mode: '' as '' | 'setup', busy: false, activity: '', message: '', error: '' })

// one recovery action at a time; Setup's Recovery row and the status follow at once (phone.recoveryAt)
export async function recoveryRun(action: () => Promise<void>, activity?: string): Promise<void> {
  if (rec.busy) return
  const done = beginLanguageWork()
  rec.busy = true; rec.activity = activity ?? t('recovery.state.checkingShort'); rec.error = ''; rec.message = ''
  try { await action() } catch (e) { rec.error = nativeError('recovery', e) }
  finally { rec.busy = false; rec.activity = ''; phone.recoveryAt = Date.now(); done() }
}

// a recovery file the person picks, as text; null when the chooser was cancelled
export async function recoveryFileText(): Promise<string | null> {
  const file = await pickFileObj('.json,application/json')
  if (!file) return null
  if (file.size > RECOVERY_LIMIT) throw Object.assign(new Error('Recovery files must be smaller than 32 KiB.'), { code: 'file-limit' })
  return file.text()
}

// Check recovery file…: the file saved for this setup, checked against the setup in Google Drive (nothing is uploaded)
export function checkFile(): Promise<void> {
  return recoveryRun(async () => {
    const m = mirrorSource
    if (!m) return
    const text = await recoveryFileText()
    if (text === null) return
    await verifyPhoneRecovery(m.pair, m.drive, text)
    rec.message = t('recovery.state.fileChecked')
  })
}

// Save recovery file…: the app writes it to a folder the person picks (and remembers it did); a browser downloads it
export function saveFile(): Promise<void> {
  return recoveryRun(async () => {
    const m = mirrorSource
    if (!m) return
    const saved = await savePhoneKit(m.pair)
    rec.message = saved === 'saved' ? t('recovery.state.fileSaved')
      : saved === 'downloaded' ? t('recovery.state.downloadRequested') : ''
  }, t('recovery.state.savingFile'))
}
