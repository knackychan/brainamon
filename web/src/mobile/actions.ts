// The one key a PhoneState offers (mirror/phone-state.ts ActionId), run with the flows the phone already has: the
// status card on More and the Status group of Settings > Backup & phones press it. Without a PC, Back up to Google Drive is
// Connect, Set up recovery opens the Recovery group's form, and Check recovery file… opens the file chooser at once (inside
// the tap) and shows its outcome in that group (recovery.svelte.ts).
import { connectLabel, phoneWords } from './settings-words'
import type { ActionId, PhoneAction } from './mirror/phone-state'
import { openBackupBox } from './onboard.svelte'
import { checkFile, rec } from './recovery.svelte'
import { changeAccount, connectDrive, pairFrom, phone, refresh, syncNow } from './state.svelte'
import { network, setSyncPaused } from './network.svelte'

const GOOGLE: ActionId[] = ['connect', 'sign-in-again', 'change-account', 'back-up']
const RECOVERY: ActionId[] = ['set-up-recovery', 'check-file']

export async function runPhoneAction(id: ActionId): Promise<void> {
  switch (id) {
    case 'manage-backup': location.hash = '#/backup/manage'; return
    case 'resume-sync': await setSyncPaused(network.pauseFailed); return
    case 'scan': return pairFrom()
    case 'connect': case 'sign-in-again': case 'back-up': return connectDrive()
    case 'change-account': return changeAccount()
    case 'retry': await refresh(); return
    case 'send': return syncNow()
    case 'set-up-recovery': rec.mode = 'setup'; rec.error = ''; rec.message = ''; return openBackupBox('m-recovery')
    case 'check-file': { const run = checkFile(); void openBackupBox('m-recovery'); return run }
  }
}

// while its flow runs the key waits, and a Google key says which step it is in (as More's own keys do)
export const actionBusy = (id: ActionId) => GOOGLE.includes(id) ? phone.connecting : (id === 'resume-sync' && network.pausePending) || (RECOVERY.includes(id) && (rec.busy || phone.connecting)) || phone.refreshing || (!!phone.sync && !phone.sync.end)
export const actionLabel = (a: PhoneAction) => a.id === 'resume-sync' && (network.pausePending || network.pauseFailed) ? phoneWords(network.pausePending ? 'settings.sync.savingPolicy' : 'common.retry') : GOOGLE.includes(a.id) && phone.connecting ? connectLabel(phone.connectStep) : a.label
