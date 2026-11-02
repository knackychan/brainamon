// What the phone says about its backup and its PC, decided in one place (docs/superpowers/plans/2026-10-31-phone-backup-phones.md).
// The status card at the top of More, the Status group of More > Backup & phones, the line under the app bar and the
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
const held = (k: number) => k ? `${count(k, 'edit waits', 'edits wait')} on this phone.` : ''
const join = (...parts: string[]) => parts.filter(Boolean).join(' ')
const say = (id: StateId, tone: Tone, text: string, detail = '', action: PhoneAction | null = null, lamp = ''): PhoneState =>
  ({ id, tone, text, detail, action, strip: STRIP.includes(id), lamp })
const key = (id: ActionId, label: string, primary: boolean): PhoneAction => ({ id, label, primary })

export function phoneState(f: PhoneFacts): PhoneState {
  if (f.backupTask) return say('backup-task', f.backupTask.busy ? 'busy' : 'next', f.backupTask.text, f.backupTask.detail, key('manage-backup', 'View backup task', false))
  if (f.pause) return say('paused', 'todo', f.pause, 'Local edits stay on this phone.', key('resume-sync', 'Resume sync', false))
  const pending = f.unsent + f.waiting
  if (!f.online) return say('offline', 'todo', 'Offline.', pending
    ? `${count(pending, 'edit waits', 'edits wait')} on this phone and go${pending === 1 ? 'es' : ''} out when you're back online.`
    : f.checked ? `Showing the copy checked ${f.checked}.` : '')
  if (f.wifiWait) return say('wifi', 'todo', 'Waiting for Wi-Fi.', join(held(pending), 'Wi-Fi only is on (More > Sync).'))
  if (!f.signedIn && f.account && !f.mismatch) return say('sign-in-again', 'next', 'Google asks you to sign in again.', held(pending), key('sign-in-again', 'Sign in again', true))
  return f.mode === 'solo' ? solo(f, pending) : pc(f, pending)
}

function pc(f: PhoneFacts, pending: number): PhoneState {
  const scan = (primary: boolean) => f.app ? key('scan', 'Scan new code', primary) : null
  if (f.tooOld) return say('update-app', 'next', 'Update Brainamon on this phone.', 'Your PC backs up in a newer format. The copy already here still works.', null, 'update app')
  if (f.mismatch) return say('account-mismatch', 'next', `Signed in as ${f.mismatch}, but your PC backs up to ${f.pcAccount}.`, '', key('change-account', 'Change account', true))
  if (!f.signedIn) return say('connect', 'next', 'Connect Google Drive.', f.pcAccount ? `Choose ${f.pcAccount}, the account your PC backs up to.` : 'Choose the account your PC backs up to.', key('connect', 'Connect', true))
  switch (f.access) {
    case 'replaced':
      return say('replaced', 'next', 'Your PC changed (restored or reinstalled).', join(held(pending), f.app
        ? 'Scan the new code on it: Settings > Backup & phones > Add a phone.'
        : 'Open the new pairing link from it: Settings > Backup & phones > Add a phone.'), scan(true), 'PC changed')
    case 'missing':
      if (!f.hadAccess) return say('confirming', 'todo', 'Waiting for your PC to confirm this phone.', 'Keep Brainamon open on your PC with Google Drive connected.', key('retry', 'Retry', false), 'access pending')
      return say('removed', 'next', "This phone's access was removed on your PC.", join(f.since ? `Last access ${f.since}.` : '', held(pending),
        f.app ? 'Still your phone? Scan the new code on your PC.' : 'Still your phone? Open the new pairing link from your PC.'), scan(true), 'access removed')
    case 'expired':
      return say('waiting-pc', 'todo', f.since ? `Your PC hasn't renewed sync access since ${f.since}.` : "Your PC hasn't renewed sync access.",
        join("It's off, offline, signed out of Google, or backs up to another account.", held(pending),
          f.app ? 'Restored or reinstalled it? Scan its new code.' : 'Restored or reinstalled it? Open its new pairing link.'), scan(false), 'waiting for PC')
    case 'inactive':
      return say('license', 'next', 'Your PC needs an update.', 'Update Brainamon on the PC for payment-free sync, then retry. Saved content and queued edits stay here.', null, 'PC update needed')
    case 'webview':
      return say('webview', 'next', f.app ? 'Update Android System WebView.' : 'Update this browser.',
        join(f.app ? "Brainamon needs a newer one to check this phone's access (Play Store)." : "Brainamon needs a newer one to check this phone's access.", held(pending)), null, 'update needed')
    case 'invalid':
      return say('access-invalid', 'next', 'This phone could not check its access.', f.app
        ? 'Update Brainamon on this phone and on your PC. If it stays, scan the new code on your PC.'
        : 'Update Brainamon on your PC and reload this page. If it stays, open the new pairing link from your PC.', scan(false), 'check failed')
  }
  switch (f.noLibrary) {
    case '': break
    case 'uploading': return say('first-backup', 'busy', 'Your PC is still backing up.', 'The library appears when it finishes.', null, 'waiting')
    case 'key': return say('key', 'next', "This phone's pairing is out of date.", f.app
      ? 'Scan the new code on your PC: Settings > Backup & phones > Add a phone.'
      : 'Open the new pairing link from your PC: Settings > Backup & phones > Add a phone.', scan(true))
    case 'mirror-off': return say('backup-off', 'next', "Your PC isn't backing up the library.", 'On the PC: Settings > Backup & phones > Turn on backup.')
    default: return say('no-library', 'next', 'No library in Google Drive yet.', f.noLibraryText,
      f.noLibrary === 'account' ? key('change-account', 'Change account', false) : f.noLibrary === 'unknown' ? key('retry', 'Retry', false) : null)
  }
  if (!f.tried) return say('connecting', 'busy', 'Connecting to Google Drive…')
  if (f.refreshing && !f.reachable) return say('connecting', 'busy', 'Checking Google Drive…', 'Checking PC access and loading your library.')
  if (!f.reachable) return say('unreachable', 'next', 'Google Drive could not be reached.', held(pending) || 'Saved content stays on this phone.', key('retry', 'Retry', true))
  if (f.resending) return say('resending', 'busy', 'Paired again.', `Sending ${count(f.resending, 'edit', 'edits')} made while access was removed.`)
  return say('in-sync', f.refreshing ? 'busy' : 'done', f.refreshing ? 'Syncing…' : f.checked ? `In sync · checked ${f.checked}.` : 'In sync.',
    `Changes from this phone: ${f.unsent ? `${f.unsent} not sent yet` : 'All sent'}${f.waiting ? ` · ${f.waiting} waiting for your PC` : ''}.`,
    f.unsent ? key('send', 'Send now', false) : null)
}

function solo(f: PhoneFacts, pending: number): PhoneState {
  if (!f.signedIn) return say('solo-local', 'next', 'Your library is only on this phone.', 'Back it up to your own Google Drive, encrypted: Google cannot read it.', key('back-up', 'Back up to Google Drive', true))
  if (!f.tried) return say('connecting', 'busy', 'Connecting to Google Drive…')
  if (f.refreshing && !f.reachable) return say('connecting', 'busy', 'Checking Google Drive…', 'Reading your backup and saving changes.')
  if (!f.reachable) return say('unreachable', 'next', 'Google Drive could not be reached.', held(pending) || 'Saved content stays on this phone.', key('retry', 'Retry', true))
  if (f.recovery === 'none') return say('solo-recovery', 'next', 'Backed up, but if this phone is lost nothing can unlock the backup.', 'A recovery passphrase or recovery file unlocks it on a new phone.', key('set-up-recovery', 'Set up recovery', true))
  if (f.recovery === 'saved') return say('solo-check-file', 'next', 'Recovery file saved, not checked yet.', 'Check it so you know it opens your backup.', key('check-file', 'Check recovery file…', true))
  return say('solo-ok', f.refreshing ? 'busy' : 'done', f.refreshing ? 'Backing up…' : f.checked ? `Backed up · checked ${f.checked}.` : 'Backed up.',
    `Changes from this phone: ${f.unsent ? `${f.unsent} not backed up yet` : 'All backed up'}.`, f.unsent ? key('send', 'Send now', false) : null)
}

// a moment as the PC page writes one (lib/backup.ts hm and day): "15:05" today, "30 Oct 15:05" before, '' unknown;
// day alone ("30 Oct") is when a recovery setup was made (PhoneRecovery.svelte)
const hm = (t: number) => new Date(t).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
export const day = (t: number) => new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
export const clock = (t: number, now = Date.now()) => !t ? '' : new Date(t).toDateString() === new Date(now).toDateString() ? hm(t) : `${day(t)} ${hm(t)}`
