// What the phone says about its backup and its PC, decided in one place (docs/superpowers/plans/2026-10-31-phone-backup-phones.md).
// The status card at the top of More, the Status group of Settings > Backup & phones, the line under the app bar and the
// app bar lamp all show the one PhoneState phoneState() returns. The words follow the PC's (projects/backup-phones-mockup/
// README.md, phone pane PH1 to PH11), plus PH12: a PC that was restored or reinstalled. No runtime imports: Node runs
// this file (tests/test_phone_state.py; tests/fixtures/phone_states.json pins every state's words).
import type { NoLibraryCause } from './diagnose'
import type { AccessKind } from './license'

export interface PhoneFacts {
  pause?: string
  backupTask?: { busy: boolean; text: string; detail: string }
  mode: 'pc' | 'solo'          // paired with a PC, or a phone without one
  app: boolean                 // the Android app: Scan works (a phone browser pairs from the link instead)
  online: boolean
  wifiWait: boolean            // Wi-Fi only is on and this network is not Wi-Fi
  refreshing: boolean          // a library read runs now
  tried: boolean               // a library read has finished since the app started
  signedIn: boolean            // a Google token is held and Google has not refused it
  account: string              // the Google account confirmed on this phone (pairing `g`), '' none
  pcAccount: string            // the account the PC backs up to (pairing `e`), '' unknown
  mismatch: string             // signed in to another account than the PC's: that account, else ''
  access: '' | AccessKind      // why the last access check refused this phone (license.ts), '' when it did not
  hadAccess: boolean           // this pairing had access before (license.ts lastAccess)
  since: string                // when access was last confirmed or renewed (clock()), '' unknown
  noLibrary: '' | NoLibraryCause   // the last read found no library in Drive, and why (diagnose.ts)
  noLibraryText: string        // diagnose.ts words for that cause
  reachable: boolean           // the last library read worked
  tooOld: boolean              // the PC's copy needs a newer app
  checked: string              // when the library was last read ("2 min ago"), '' never
  unsent: number               // edits not sent yet
  waiting: number              // edits sent that the PC has not applied yet
  resending: number            // edits sent again after pairing again (S5)
  recovery: 'none' | 'prepared' | 'saved' | 'checked'   // without a PC: no recovery yet, a passphrase set (no recovery file
                                                         // yet), a recovery file not checked yet, checked
}

export type Tone = 'done' | 'todo' | 'next' | 'busy'
export type ActionId = 'scan' | 'connect' | 'sign-in-again' | 'change-account' | 'retry' | 'send' | 'back-up' | 'set-up-recovery' | 'check-file' | 'manage-backup' | 'resume-sync'
export interface PhoneAction { id: ActionId; label: string; primary: boolean }
export type StateId = 'paused' | 'backup-task' | 'offline' | 'wifi' | 'update-app' | 'account-mismatch' | 'sign-in-again' | 'connect' | 'replaced' | 'removed'
  | 'confirming' | 'waiting-pc' | 'license' | 'access-invalid' | 'webview' | 'first-backup' | 'key' | 'backup-off' | 'no-library'
  | 'connecting' | 'unreachable' | 'resending' | 'in-sync' | 'solo-local' | 'solo-recovery' | 'solo-check-file' | 'solo-ok'
export interface PhoneState {
  id: StateId
  tone: Tone                   // the dot: done (all well), todo (nothing to do here), next (needs you), busy (working)
  text: string                 // one sentence, what is true now: the status card shows it with the action
  detail: string               // what it means or what to do, '' none
  action: PhoneAction | null   // at most one key; primary only when the state needs you
  strip: boolean               // also the line under the app bar, on every screen
  lamp: string                 // the app bar lamp after "Drive · ", '' for the usual one
}

// the three states only this phone's owner can fix, shown under the app bar on every screen
const STRIP: StateId[] = ['removed', 'replaced', 'sign-in-again']
// the states of a refused access check: the guide on Backup & phones (step 3) and driveStatus (the Sync box, Setup,
// the vault and the Google account box) say these in the same words
export const ACCESS_STATES: StateId[] = ['replaced', 'removed', 'confirming', 'waiting-pc', 'license', 'access-invalid', 'webview']
const count = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`
const held = (k: number, words?: PhoneWords) => k ? (words?.('backup.state.held', { n: k }) ?? `${count(k, 'edit waits', 'edits wait')} on this phone.`) : ''
const join = (...parts: string[]) => parts.filter(Boolean).join(' ')
const say = (id: StateId, tone: Tone, text: string, detail = '', action: PhoneAction | null = null, lamp = ''): PhoneState =>
  ({ id, tone, text, detail, action, strip: STRIP.includes(id), lamp })
const key = (id: ActionId, label: string, primary: boolean): PhoneAction => ({ id, label, primary })

export type PhoneWords = (key: string, params?: Record<string, unknown>) => string

export function phoneState(f: PhoneFacts, words?: PhoneWords): PhoneState {
  if (f.backupTask) return say('backup-task', f.backupTask.busy ? 'busy' : 'next', f.backupTask.text, f.backupTask.detail, key('manage-backup', (words?.('backup.action.task') ?? 'View backup task'), false))
  if (f.pause) return say('paused', 'todo', f.pause, (words?.('backup.state.localEdits') ?? 'Local edits stay on this phone.'), key('resume-sync', (words?.('shell.sync.resume') ?? 'Resume sync'), false))
  const pending = f.unsent + f.waiting
  if (!f.online) return say('offline', 'todo', (words?.('backup.state.offline') ?? 'Offline.'), pending
    ? (words?.('backup.state.offlinePending', { n: pending }) ?? `${count(pending, 'edit waits', 'edits wait')} on this phone and go${pending === 1 ? 'es' : ''} out when you're back online.`)
    : f.checked ? (words?.('backup.state.copyChecked', { checked: f.checked }) ?? `Showing the copy checked ${f.checked}.`) : '')
  if (f.wifiWait) return say('wifi', 'todo', (words?.('backup.state.wifi') ?? 'Waiting for Wi-Fi.'), join(held(pending, words), (words?.('backup.state.wifiHelp') ?? 'Wi-Fi only is on (Settings > Sync).')))
  if (!f.signedIn && f.account && !f.mismatch) return say('sign-in-again', 'next', (words?.('backup.state.signIn') ?? 'Google asks you to sign in again.'), held(pending, words), key('sign-in-again', (words?.('backup.action.signIn') ?? 'Sign in again'), true))
  return f.mode === 'solo' ? solo(f, pending, words) : pc(f, pending, words)
}

function pc(f: PhoneFacts, pending: number, words?: PhoneWords): PhoneState {
  const scan = (primary: boolean) => f.app ? key('scan', (words?.('backup.action.scan') ?? 'Scan new code'), primary) : null
  if (f.tooOld) return say('update-app', 'next', (words?.('backup.state.update') ?? 'Update Brainamon on this phone.'), (words?.('backup.state.updateHelp') ?? 'Your PC backs up in a newer format. The copy already here still works.'), null, (words?.('backup.state.updateLamp') ?? 'update app'))
  if (f.mismatch) return say('account-mismatch', 'next', (words?.('backup.state.mismatch', { account: f.mismatch, pcAccount: f.pcAccount }) ?? `Signed in as ${f.mismatch}, but your PC backs up to ${f.pcAccount}.`), '', key('change-account', (words?.('backup.action.account') ?? 'Change account'), true))
  if (!f.signedIn) return say('connect', 'next', (words?.('backup.state.connect') ?? 'Connect Google Drive.'), f.pcAccount ? (words?.('backup.state.choosePc', { account: f.pcAccount }) ?? `Choose ${f.pcAccount}, the account your PC backs up to.`) : (words?.('backup.state.chooseAccount') ?? 'Choose the account your PC backs up to.'), key('connect', (words?.('backup.action.connect') ?? 'Connect'), true))
  switch (f.access) {
    case 'replaced':
      return say('replaced', 'next', (words?.('backup.state.replaced') ?? 'Your PC changed (restored or reinstalled).'), join(held(pending, words), f.app
        ? (words?.('backup.state.replacedScan') ?? 'Scan the new code on it: Settings > Backup & phones > Add a phone.')
        : (words?.('backup.state.replacedLink') ?? 'Open the new pairing link from it: Settings > Backup & phones > Add a phone.')), scan(true), (words?.('backup.state.replacedLamp') ?? 'PC changed'))
    case 'missing':
      if (!f.hadAccess) return say('confirming', 'todo', (words?.('backup.state.confirming') ?? 'Waiting for your PC to confirm this phone.'), (words?.('backup.state.confirmingHelp') ?? 'Keep Brainamon open on your PC with Google Drive connected.'), key('retry', (words?.('common.retry') ?? 'Retry'), false), (words?.('backup.state.pendingLamp') ?? 'access pending'))
      return say('removed', 'next', (words?.('backup.state.removed') ?? "This phone's access was removed on your PC."), join(f.since ? (words?.('backup.state.lastAccess', { since: f.since }) ?? `Last access ${f.since}.`) : '', held(pending, words),
        f.app ? (words?.('backup.state.removedScan') ?? 'Still your phone? Scan the new code on your PC.') : (words?.('backup.state.removedLink') ?? 'Still your phone? Open the new pairing link from your PC.')), scan(true), (words?.('backup.state.removedLamp') ?? 'access removed'))
    case 'expired':
      return say('waiting-pc', 'todo', f.since ? (words?.('backup.state.notRenewedSince', { since: f.since }) ?? `Your PC hasn't renewed sync access since ${f.since}.`) : (words?.('backup.state.notRenewed') ?? "Your PC hasn't renewed sync access."),
        join((words?.('backup.state.notRenewedHelp') ?? "It's off, offline, signed out of Google, or backs up to another account."), held(pending, words),
          f.app ? (words?.('backup.state.restoredScan') ?? 'Restored or reinstalled it? Scan its new code.') : (words?.('backup.state.restoredLink') ?? 'Restored or reinstalled it? Open its new pairing link.')), scan(false), (words?.('backup.state.waitingPcLamp') ?? 'waiting for PC'))
    case 'inactive':
      return say('license', 'next', (words?.('backup.state.pcUpdate') ?? 'Your PC needs an update.'), (words?.('backup.state.pcUpdateHelp') ?? 'Update Brainamon on the PC for payment-free sync, then retry. Saved content and queued edits stay here.'), null, (words?.('backup.state.pcUpdateLamp') ?? 'PC update needed'))
    case 'webview':
      return say('webview', 'next', f.app ? (words?.('backup.state.webview') ?? 'Update Android System WebView.') : (words?.('backup.state.browser') ?? 'Update this browser.'),
        join(f.app ? (words?.('backup.state.webviewHelp') ?? "Brainamon needs a newer one to check this phone's access (Play Store).") : (words?.('backup.state.browserHelp') ?? "Brainamon needs a newer one to check this phone's access."), held(pending, words)), null, (words?.('backup.state.updateNeededLamp') ?? 'update needed'))
    case 'invalid':
      return say('access-invalid', 'next', (words?.('backup.state.invalid') ?? 'This phone could not check its access.'), f.app
        ? (words?.('backup.state.invalidApp') ?? 'Update Brainamon on this phone and on your PC. If it stays, scan the new code on your PC.')
        : (words?.('backup.state.invalidWeb') ?? 'Update Brainamon on your PC and reload this page. If it stays, open the new pairing link from your PC.'), scan(false), (words?.('backup.state.failedLamp') ?? 'check failed'))
  }
  switch (f.noLibrary) {
    case '': break
    case 'uploading': return say('first-backup', 'busy', (words?.('backup.state.uploading') ?? 'Your PC is still backing up.'), (words?.('backup.state.uploadingHelp') ?? 'The library appears when it finishes.'), null, (words?.('backup.state.waitingLamp') ?? 'waiting'))
    case 'key': return say('key', 'next', (words?.('backup.state.key') ?? "This phone's pairing is out of date."), f.app
      ? (words?.('backup.state.keyScan') ?? 'Scan the new code on your PC: Settings > Backup & phones > Add a phone.')
      : (words?.('backup.state.keyLink') ?? 'Open the new pairing link from your PC: Settings > Backup & phones > Add a phone.'), scan(true))
    case 'mirror-off': return say('backup-off', 'next', (words?.('backup.state.backupOff') ?? "Your PC isn't backing up the library."), (words?.('backup.state.backupOffHelp') ?? 'On the PC: Settings > Backup & phones > Turn on backup or Resume backup.'))
    default: return say('no-library', 'next', (words?.('backup.state.noLibrary') ?? 'No library in Google Drive yet.'), f.noLibraryText,
      f.noLibrary === 'account' ? key('change-account', (words?.('backup.action.account') ?? 'Change account'), false) : f.noLibrary === 'unknown' ? key('retry', (words?.('common.retry') ?? 'Retry'), false) : null)
  }
  if (!f.tried) return say('connecting', 'busy', (words?.('backup.state.connecting') ?? 'Connecting to Google Drive…'))
  if (f.refreshing && !f.reachable) return say('connecting', 'busy', (words?.('backup.state.checking') ?? 'Checking Google Drive…'), (words?.('backup.state.checkingPc') ?? 'Checking PC access and loading your library.'))
  if (!f.reachable) return say('unreachable', 'next', (words?.('backup.state.unreachable') ?? 'Google Drive could not be reached.'), held(pending, words) || (words?.('backup.state.savedLocal') ?? 'Saved content stays on this phone.'), key('retry', (words?.('common.retry') ?? 'Retry'), true))
  if (f.resending) return say('resending', 'busy', (words?.('backup.state.pairedAgain') ?? 'Paired again.'), (words?.('backup.state.resending', { n: f.resending }) ?? `Sending ${count(f.resending, 'edit', 'edits')} made while access was removed.`))
  return say('in-sync', f.refreshing ? 'busy' : 'done', f.refreshing ? (words?.('backup.state.syncing') ?? 'Syncing…') : f.checked ? (words?.('backup.state.inSyncChecked', { checked: f.checked }) ?? `In sync · checked ${f.checked}.`) : (words?.('backup.state.inSync') ?? 'In sync.'),
    (words?.('backup.state.changes', { sent: f.unsent ? words('backup.state.unsent', { n: f.unsent }) : words('backup.state.allSent'), waiting: f.waiting ? words('backup.state.waitingPc', { n: f.waiting }) : '' }) ?? `Changes from this phone: ${f.unsent ? `${f.unsent} not sent yet` : 'All sent'}${f.waiting ? ` · ${f.waiting} waiting for your PC` : ''}.`),
    f.unsent ? key('send', (words?.('backup.action.send') ?? 'Send now'), false) : null)
}

function solo(f: PhoneFacts, pending: number, words?: PhoneWords): PhoneState {
  if (!f.signedIn) return say('solo-local', 'next', (words?.('backup.state.soloLocal') ?? 'Your library is only on this phone.'), (words?.('backup.state.soloLocalHelp') ?? 'Back it up to your own Google Drive, encrypted: Google cannot read it.'), key('back-up', (words?.('backup.action.backup') ?? 'Back up to Google Drive'), true))
  if (!f.tried) return say('connecting', 'busy', (words?.('backup.state.connecting') ?? 'Connecting to Google Drive…'))
  if (f.refreshing && !f.reachable) return say('connecting', 'busy', (words?.('backup.state.checking') ?? 'Checking Google Drive…'), (words?.('backup.state.readingSolo') ?? 'Reading your backup and saving changes.'))
  if (!f.reachable) return say('unreachable', 'next', (words?.('backup.state.unreachable') ?? 'Google Drive could not be reached.'), held(pending, words) || (words?.('backup.state.savedLocal') ?? 'Saved content stays on this phone.'), key('retry', (words?.('common.retry') ?? 'Retry'), true))
  if (f.recovery === 'none') return say('solo-recovery', 'next', (words?.('backup.state.soloRecovery') ?? 'Backed up, but if this phone is lost nothing can unlock the backup.'), (words?.('backup.state.soloRecoveryHelp') ?? 'A recovery passphrase or recovery file unlocks it on a new phone.'), key('set-up-recovery', (words?.('backup.action.recovery') ?? 'Set up recovery'), true))
  if (f.recovery === 'saved') return say('solo-check-file', 'next', (words?.('backup.state.fileSaved') ?? 'Recovery file saved, not checked yet.'), (words?.('backup.state.fileSavedHelp') ?? 'Check it so you know it opens your backup.'), key('check-file', (words?.('backup.action.checkFile') ?? 'Check recovery file…'), true))
  return say('solo-ok', f.refreshing ? 'busy' : 'done', f.refreshing ? (words?.('backup.state.backingUp') ?? 'Backing up…') : f.checked ? (words?.('backup.state.backedUpChecked', { checked: f.checked }) ?? `Backed up · checked ${f.checked}.`) : (words?.('backup.state.backedUp') ?? 'Backed up.'),
    (words?.('backup.state.soloChanges', { sent: f.unsent ? words('backup.state.unbacked', { n: f.unsent }) : words('backup.state.allBacked') }) ?? `Changes from this phone: ${f.unsent ? `${f.unsent} not backed up yet` : 'All backed up'}.`), f.unsent ? key('send', (words?.('backup.action.send') ?? 'Send now'), false) : null)
}

// a moment as the PC page writes one (lib/backup.ts hm and day): "15:05" today, "30 Oct 15:05" before, '' unknown;
// day alone ("30 Oct") is when a recovery setup was made (PhoneRecovery.svelte)
const hm = (t: number, locale = 'en-GB') => new Date(t).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
export const day = (t: number, locale = 'en-GB') => new Date(t).toLocaleDateString(locale, { day: 'numeric', month: 'short' })
export const clock = (t: number, now = Date.now(), locale = 'en-GB') => !t ? '' : new Date(t).toDateString() === new Date(now).toDateString() ? hm(t, locale) : `${day(t, locale)} ${hm(t, locale)}`
