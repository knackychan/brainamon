// Shared desktop backup facts and actions, derived only from server snapshots and local dismissals.
import { amount, DAY, day, dur, gb, hm, long, num, sameAccount, W, type CloudTask, type CloudSnapshot, type RecoveryView } from './backup'
import type { RecoveryActivity } from './recovery'

export interface QueuedTask { id: string; kind: string; title: string; stage: string; error: string; code: string }
type ModelCloud = CloudSnapshot & { tasks?: QueuedTask[] }
type ModelTask = CloudTask & { paused_snapshot?: boolean }

export type Tone = 'done' | 'todo' | 'next' | 'optional' | 'busy'
// the six states every section follows: nothing set up, status unknown, running by itself, all well, stopped and
// needs you (a reason and one key), stopped until you say go
export type Kind = 'empty' | 'loading' | 'working' | 'done' | 'failed' | 'paused'
export type GroupId = 'account' | 'backup' | 'recovery' | 'phones'
export type ActId = 'connect' | 'turn-on' | 'cancel-sign-in' | 'sign-in-again' | 'switch-to' | 'resume' | 'pause' | 'keep-going' | 'try-again'
  | 'recover' | 'unlock' | 'reset-instead' | 'update' | 'retry-update' | 'stop-update' | 'restart' | 'takeover' | 'create-pass' | 'check-recovery' | 'save-file'
  | 'check-file' | 'add-phone' | 'keep-local' | 'recheck' | 'other-account' | 'hide' | 'open-recover' | 'retry-status' | 'stop-copy'
export interface Act { id: ActId; label: string; icon?: 'pause' | 'play'; why?: string }
export interface Line { kind: Kind; tone: Tone; text: string; detail?: string }
export interface Step { label: string; state: 'done' | 'active' | 'waiting' }
export interface TaskView {
  id: string; title: string; kind: Kind; saved: boolean      // saved: a task in cloud/intents.json, continues after a restart
  step: number; of: number; steps: Step[]; running: boolean
  progress: 'determinate' | 'steps' | 'indeterminate'; pct?: number; bar: string
  line: string; notes: string[]; error?: string; leave: boolean
  primary?: Act; quiet: Act[]; also: QueuedTask[]
}
export interface BackupState {
  id: string; kind: Kind
  hero: Line & { primary?: Act; quiet: Act[]; alert?: string; choices?: boolean }
  task: TaskView | null
  rows: Record<GroupId, Line> & { vault: Line }
  open: '' | GroupId              // the group the hero's key belongs to: it opens by itself
  nav: { tone: Tone | null; line: string }
  blocked: string                 // why changes wait right now ('' when they do not): a recovery step holds the gate
}
export interface Local { dismissedOther?: boolean; dismissedNotice?: boolean; dismissedRemoval?: boolean; dismissedUpdate?: boolean }

export function pairingReason(c: CloudSnapshot | null): string {
  if (!c) return 'Checking phone pairing…'
  if (!c.licensed) return 'Update Brainamon on this PC for payment-free phone pairing, then retry.'
  if (!c.signed_in) return 'Connect Google Drive before adding a phone.'
  if (c.key_missing) return 'Unlock this backup before adding a phone.'
  if (c.recovery_gate_active || c.recovery_activity?.state === 'running')
    return c.recovery_activity?.step ? `${c.recovery_activity.step} Wait for this step to finish.` : 'Wait for the current recovery step to finish.'
  if (c.pair_ready !== true) return 'Wait until this library has a usable pairing key, then try again.'
  return ''
}

const LEAVE = 'You can close Settings. Quitting Brainamon pauses this; it continues at the next start.'
const act = (id: ActId, label: string, extra: Partial<Act> = {}): Act => ({ id, label, ...extra })
const line = (kind: Kind, tone: Tone, text: string, detail?: string): Line => ({ kind, tone, text, detail })
const plural = (n: number, one: string, many = one + 's') => `${num(n)} ${n === 1 ? one : many}`
const when = (t: number) => `${day(t)}, ${hm(t)}`
const ACTIVITY: Record<string, string> = { reconnect: 'Keeping this folder', enroll: 'Saving the recovery passphrase', verify: 'Checking the recovery file', unpair: 'Locking phones out' }
// the steps server/recovery.py reports for Keep this folder, in order (RecoveryService.reconnect, _reconnect)
const RECONNECT_STEPS = ['Checking this library against Google Drive', 'Checking the Google account and that this folder matches the latest upload',
  'Saving the new recovery setup and uploader record in Google Drive', 'Keeping this folder with the recovered key']

export function reconnectSteps(activity: RecoveryActivity): Step[] {
  const at = activity.step_count === RECONNECT_STEPS.length ? (activity.step_index ?? 0) - 1 : -1
  return at >= 0 && at < RECONNECT_STEPS.length
    ? RECONNECT_STEPS.map((label, i) => ({ label: i === at ? activity.step.replace(/…$/, '') : label, state: i < at ? 'done' : i === at ? 'active' : 'waiting' }))
    : [{ label: activity.step.replace(/…$/, ''), state: 'active' }]
}

function loading(): BackupState {
  const wait = line('loading', 'todo', 'Checking…')
  return { id: 'loading', kind: 'loading', hero: { ...line('loading', 'todo', 'Checking your backup…'), quiet: [] }, task: null,
    rows: { account: wait, backup: wait, recovery: wait, phones: wait, vault: wait }, open: '', nav: { tone: null, line: 'Checking…' }, blocked: '' }
}

export function backupState(c: ModelCloud | null, rec: RecoveryView | null | 'error', now: number, local: Local = {}): BackupState {
  if (!c) return loading()
  const r = rec && rec !== 'error' ? rec : null
  const recUnread = rec === 'error', recLoading = rec === null
  const task = c.task ?? null
  const online = c.error_code !== 'offline'
  const paused = (c.paused_since ?? 0) > 0
  const pausing = c.state === 'stopping'
  const backedUp = c.last_publish > 0
  const since = backedUp ? hm(c.last_publish) : ''
  const removal = task?.kind === 'remove_phones'
  const rotating = removal || c.rotation === 'pending' || !!r?.rotation_pending
  const enrollFailed = task?.kind === 'enroll' && !!task.error
  const enrolling = task?.kind === 'enroll' && !enrollFailed
  const sameAcc = !!r && sameAccount(r.account, c.account)
  const enrolled = !!r && r.enrolled && sameAcc
  const fileOutdated = !!r?.file_outdated && enrolled
  const phones = c.phones ?? []
  const phoneSummary = `${plural(phones.length, 'phone')} ${phones.length === 1 ? 'has' : 'have'} reported a sync.`
  const phoneRead = !online ? 'This PC will read newer reports when its connection returns.' : !c.running ? 'This PC will read newer reports when it resumes syncing.' : 'This PC checks Google Drive for new reports during sync.'
  const phoneHelp = `${phoneRead} Phones send a report after syncing, no more than once every 30 minutes. An older report does not mean a phone is disconnected. Open Brainamon on your phone to see its current sync status.`
  const activity = c.recovery_activity ?? null
  const blocked = activity?.state === 'running' ? `${activity.step} Changes here wait until this step finishes.` : ''
  const backUp = act('connect', W.backUp, c.configured ? {} : { why: 'Google sign-in is not set up in this build.' })
  const resumeAct = act('resume', W.resume, { icon: 'play' }), pauseAct = act('pause', W.pause, { icon: 'pause' })
  const tryAgain = act('try-again', 'Try again')
  // the server classifies every failure and names the next action (server/cloud_errors.py): 'wait' means it retries by itself
  const waits = c.error_action === 'wait'

  // ── the task panel: a saved task, a recovery step that holds the gate, or a copy into a new folder ──
  const taskView = buildTask(c, r, now, { online, paused, removal }, local)

  // ── the group rows ──
  const account: Line = !c.signed_in
    ? c.state === 'signing-in' ? line('working', 'busy', 'Waiting for the Google sign-in')
      : !c.configured ? line('empty', 'optional', 'Not connected', 'Google sign-in is not set up in this build.')
      : c.account ? line('empty', 'optional', `Disconnected · the copy in ${c.account} stays`) : line('empty', 'optional', 'Not connected')
    : c.state === 'disconnecting' || task?.kind === 'disconnect' ? line(task?.error ? 'failed' : 'working', task?.error ? 'next' : 'busy', task?.error ? `Still connected · ${c.account}` : 'Disconnecting…')
    : c.token_expired ? line('failed', 'next', `Sign-in expired · ${c.account}`)
    : c.error_code === 'wrong_account' ? line('failed', 'next', `Signed in as another account · this library uses ${c.account}`)
    : task?.kind === 'switch_account' ? line('working', 'busy', `Switching account · ${task.steps[task.step - 1]?.label ?? ''}`)
    : line('done', 'done', c.account || 'Connected', c.limit ? `${gb(c.used)} of ${gb(c.limit)} GB of Google storage used.` : undefined)

  const backup: Line = !c.signed_in ? line('empty', 'optional', 'Off', 'Starts when you back up to Google Drive.')
    : pausing ? line('working', 'busy', 'Pausing after the current upload request')
    : paused ? line('paused', 'next', `Paused ${long(Math.max(0, now - (c.paused_since ?? now)))} ago`)
    : c.error_code === 'foreign_backup' ? line('failed', 'next', 'Waiting: choose what to do with the existing backup')
    : c.key_missing ? line('failed', 'next', 'Waiting: this PC has no key for the backup')
    : c.error_code === 'other_copy' ? line('failed', 'next', 'Stopped: another Brainamon on this PC made this backup')
    : c.token_expired ? line('failed', 'next', 'Waiting: sign-in expired')
    : c.error_code === 'not_owner' ? line('failed', 'next', 'Stopped: another PC backs up')
    : task?.kind === 'reset_backup' || task?.kind === 'switch_account' || task?.kind === 'update_folder' || task?.kind === 'one_shot_publish'
      ? line(task.error ? 'failed' : 'working', task.error ? 'next' : 'busy', `${task.title} · step ${task.step} of ${task.of}`)
    : removal ? line('working', 'busy', 'Re-encrypting with the new key')
    : rotating ? line('failed', 'next', c.rotation_lock || 'A phone removal in another library must finish first.')
    : !online ? line('working', 'busy', 'Waiting for the connection')
    : c.error_code === 'drive_full' ? line('failed', 'next', 'Waiting: Google Drive is full')
    : c.state === 'error' ? line('failed', 'next', 'Stopped: backup needs attention')
    : !c.on ? line('empty', backedUp ? 'next' : 'optional', backedUp ? `Off · last backup ${when(c.last_publish)}` : 'Off')
    : !backedUp ? line('working', 'busy', c.total ? `First backup · ${num(c.done)} of ${num(c.total)} files` : 'First backup · checking what to send')
    : ['starting', 'publishing'].includes(c.state) ? line('working', 'busy', `Backing up ${c.total ? plural(c.total, 'change') : 'recent changes'}`)
    : line('done', 'done', `Up to date · ${since}`, 'Changes back up about a minute after you make them.')

  const recovery: Line = recUnread ? line('failed', 'next', 'Recovery status could not be read')
    : recLoading ? line('loading', 'todo', 'Checking recovery…')
    : r!.restart_required ? line('paused', 'next', 'Restored library ready · restart to open it')
    : r!.restored ? line('empty', 'next', 'Restored library · not the backup PC yet')
    : (enrolling || enrollFailed) && task ? line(enrollFailed ? 'failed' : 'working', enrollFailed ? 'next' : 'busy', enrollFailed ? 'Saving your passphrase stopped' : `Saving your passphrase · step ${task.step} of ${task.of}`)
    : !c.signed_in || c.key_missing ? line('empty', 'optional', 'Not set up', 'Available once the backup has started.')
    : fileOutdated ? line('done', 'done', 'Passphrase set · old recovery file outdated', 'Your passphrase still unlocks the backup. Saving a replacement file is optional.')
    : rotating ? line(paused && removal ? 'paused' : 'working', paused && removal ? 'next' : 'busy', r!.configured ? `Passphrase set${r!.setup_at ? ` ${day(r!.setup_at * 1000)}` : ''} · waits for the key update` : 'Waits for the key update')
    : r!.configured && !sameAcc ? line('empty', 'next', `Set up for ${r!.account}, not for this account`)
    : r!.configured && !enrolled ? line('failed', 'next', 'Passphrase created · not confirmed in Google Drive yet')
    : !enrolled ? line('empty', 'next', 'Not set up', `If this PC is lost, a passphrase or a ${W.file} unlocks the backup on another PC.`)
    : r!.verified_at ? line('done', 'done', `Passphrase set${r!.setup_at ? ` ${day(r!.setup_at * 1000)}` : ''} · ${W.file} checked ${day(r!.verified_at * 1000)}`)
    : r!.saved_at ? line('done', 'done', `Passphrase set${r!.setup_at ? ` ${day(r!.setup_at * 1000)}` : ''} · ${W.file} saved, not checked`, 'Open the file once so you know it unlocks your backup.')
    : line('done', 'done', `Passphrase set${r!.setup_at ? ` ${day(r!.setup_at * 1000)}` : ''}`, `Optional: also save a ${W.file}, in case you forget the passphrase.`)

  const phonesRow: Line = !c.licensed ? line('failed', 'next', 'Update Brainamon on this PC', 'Phone sync needs the current version. Backup and recovery stay available.')
    : !c.signed_in || c.key_missing ? line('empty', 'optional', 'No phones', 'Phones read your backup in Google Drive, so back up first.')
    : removal ? line(paused ? 'paused' : 'working', paused ? 'next' : 'busy', c.rotation_locked_at ? `All phones locked out at ${hm(c.rotation_locked_at)}` : c.rotation_locked_by ? `Locked out by ${hm(c.rotation_locked_by)} at the latest` : 'Locking phones out')
    : !phones.length ? line('empty', 'optional', 'No phone sync report received yet', `A paired phone appears after it syncs and this PC reads its report from Google Drive. ${phoneRead} Open Brainamon on the phone to check its progress.`)
    : line('done', 'done', phoneSummary, phoneHelp)

  const vault: Line = !c.licensed ? line('empty', 'optional', 'Needs a PC update')
    : c.vault_state === 'starting' ? line('working', 'busy', c.state === 'signing-in' ? 'Waiting for the Google sign-in' : 'Starting: comparing the vault with the phone')
    : c.vault_state === 'stopping' ? line('working', 'busy', 'Stopping')
    : c.vault_state === 'syncing' ? line('working', 'busy', `${c.vault_step || 'Syncing'}${c.vault_total ? ` · ${num(c.vault_done)} of ${num(c.vault_total)} files` : c.vault_done ? ` · ${num(c.vault_done)} files` : ''}`)
    : c.vault_state === 'brake' ? line('paused', 'next', 'Held: this round would delete many files')
    : c.vault_state === 'error' ? line('failed', 'next', 'Stopped on an error')
    : c.vault_running ? line('done', 'done', `On${c.vault_last ? ` · last round ${hm(c.vault_last)}` : ''}`, c.vault_skipped_note || undefined)
    : paused && c.vault.folder ? line('paused', 'optional', 'Off · Pause backup also stops vault sync')
    : line('empty', 'optional', 'Off')
  const rows = { account, backup, recovery, phones: phonesRow, vault }

  // ── the status sentence and its one key: first match wins ──
  type Hero = BackupState['hero']
  // a recovery step that did not finish keeps its reason in the status (it survives closing Settings): say it once, here
  const lastStep = activity?.state === 'error' ? `${ACTIVITY[activity.action] ?? 'The last recovery step'} did not finish. ${activity.step}` : undefined
  // one key per state: while the task panel holds a key (Resume, Try again, Restart now), the status offers none. The nav
  // marks only what stopped (failed, paused): a section that was never set up is not a reason to call you
  const hero = (id: string, kind: Kind, tone: Tone, text: string, more: Partial<Hero> = {}, open: '' | GroupId = ''): BackupState => {
    const gateFirst = ['restart-restored', 'copied', 'copy-failed', 'copy-stopped', 'restored', 'foreign-backup', 'key-missing', 'wrong-account', 'sign-in-expired', 'not-owner', 'not-owner-update'].includes(id)
      || ((id === 'paused' || id === 'paused-task') && more.primary?.id !== 'resume')
    const task = taskView && gateFirst ? { ...taskView, primary: undefined } : taskView
    return { id, kind, hero: { kind, tone, text, quiet: [], alert: lastStep, ...more, ...(task?.primary ? { primary: undefined } : {}) }, task, rows, open, blocked,
      nav: { tone: kind === 'failed' || kind === 'paused' ? 'next' : null, line: navLine(id, kind, rows) } }
  }
  // a task waits by itself while offline (the sync thread retries); it has stopped only with its own error, or a backup error
  const taskStopped = !!task && task.kind !== 'enroll' && online && !['wait', 'none'].includes(c.error_action ?? '') && (!!task.error || (task.kind !== 'update_folder' && c.state === 'error' && !!c.error))
  const copy = r?.job
  if (r?.restart_required) return hero('restart-restored', 'paused', 'next', 'The restored library is ready. Restart Brainamon to open it.', { detail: 'Your current library stays in its folder.', primary: act('restart', 'Restart now') })
  if (copy?.state === 'restoring') return hero('copying', 'working', 'busy', `Copying your backup into a new folder: ${num(copy.done)} of ${num(copy.total)} files.`, { detail: 'Backup of this library is paused meanwhile. Nothing in Drive changes.' })
  if (copy?.state === 'complete' || copy?.state === 'activated') return hero('copied', 'paused', 'next', `Copied to ${copy.destination}. Drive was not changed.`, { detail: 'Restart to open it. Your current library stays in its folder.', primary: act('restart', 'Restart now') })
  if (copy?.state === 'error' || copy?.state === 'cancelled') return hero(copy.state === 'error' ? 'copy-failed' : 'copy-stopped', 'failed', 'next', copy.state === 'error' ? 'Copying your backup stopped.' : 'Copying was stopped. Your library and Drive are unchanged.', { alert: copy.error || undefined, primary: act('open-recover', W.recover) })
  if (r?.restored) return hero('restored', 'empty', 'next', 'This restored library is not backed up yet.', { detail: 'Make this PC the backup PC once the old PC is off or closed.', primary: act('takeover', W.takeOver) })
  if (activity?.state === 'running' && activity.action !== 'enroll') return hero('activity', 'working', 'busy', `${ACTIVITY[activity.action] ?? 'Working'}…`)
  if (c.error_code === 'other_copy') return hero('other-copy', 'failed', 'next', c.error, { detail: 'Nothing was uploaded from this copy. Quit the other Brainamon, or keep using it for this library.', quiet: [act('recheck', 'Check again')] })
  if (c.state === 'signing-in') return hero('signing-in', 'working', 'busy', 'Finish signing in in the browser window that opened.', { detail: "Choose the Google account for this library's backup.", quiet: [act('cancel-sign-in', 'Cancel sign-in')] })
  if (task?.kind === 'disconnect' && task.error) return hero('disconnect-failed', 'failed', 'next', 'Disconnecting stopped. Your Google account is still connected.', { alert: task.error })
  if (c.state === 'disconnecting' || task?.kind === 'disconnect') return hero('disconnecting', 'working', 'busy', 'Disconnecting from Google Drive…')
  if (!c.signed_in) {
    if (c.state === 'signed-out' && c.on) return hero('signed-out', 'failed', 'next', `This PC is signed out of Google Drive${c.account ? ` (${c.account})` : ''}. Backup was on and is waiting.`, { detail: 'Connect again to keep backing up. Nothing was deleted.', primary: backUp })
    return c.account
      ? hero('disconnected', 'empty', 'next', `Google Drive disconnected. Backup is off. The copy in ${c.account}${backedUp ? ` from ${day(c.last_publish)}` : ''} stays in Drive.`, { primary: backUp, quiet: [act('open-recover', W.recover)] })
      : hero(c.configured ? 'not-connected' : 'not-configured', 'empty', 'next', 'Your library is only on this PC.', { detail: 'Back it up to your own Google Drive, encrypted: Google cannot read it. Already backed up from another PC? Recover a library gets it back.', primary: backUp, quiet: [act('open-recover', W.recover)] })
  }
  if (pausing) return hero('pausing', 'working', 'busy', 'Pausing after the current upload request (up to a minute).', { detail: 'Resume is available when the current requests finish.' })
  if (paused) return hero(task ? 'paused-task' : 'paused', 'paused', 'next', backedUp ? `Backup paused. Changes since ${since} are only on this PC.` : 'Backup paused. The first backup is not finished.',
    { detail: [task ? `${task.title} is paused too. Resume continues from its saved step.` : '', c.vault.folder ? 'Resume restores vault sync if it was on when Pause was requested.' : '', c.token_expired || c.error_code === 'wrong_account' ? 'Sign in again before resuming.' : c.key_missing ? 'Unlock the backup before resuming.' : ['not_owner', 'foreign_backup'].includes(c.error_code ?? '') ? 'Recover or update this library before resuming.' : c.error_code === 'other_copy' ? c.error : ''].filter(Boolean).join(' ') || undefined,
      primary: c.token_expired || c.error_code === 'wrong_account' ? act('sign-in-again', W.signInAgain) : c.key_missing ? act('unlock', 'Unlock backup…') : ['not_owner', 'foreign_backup'].includes(c.error_code ?? '') ? act('recover', 'Get the newer library…') : c.error_code === 'other_copy' ? act('recheck', 'Check again') : resumeAct })
  if (c.error_code === 'foreign_backup') return hero('foreign-backup', 'failed', 'next', `${c.account} already holds a Brainamon backup from another PC${c.error_at ? ` (last backup ${when(c.error_at)})` : ''}.`,
    { detail: 'Recover it, replace it with this PC’s library, or use another Google account.', primary: act('recover', 'Recover this backup…'), quiet: [act('recheck', 'Check and back up again'), act('other-account', 'Use another account…')], choices: true })
  if (c.key_missing) return hero('key-missing', 'failed', 'next', `${c.account} already holds this library's backup${backedUp ? ` (last backup ${when(c.last_publish)})` : ''}, but this PC no longer has the key that opens it.`,
    { detail: "Unlock it with your passphrase, recovery file or a phone code: nothing uploads again and backup continues from where it stopped. Each phone then scans this PC's new code once (Add a phone).", primary: act('unlock', 'Unlock backup…'), quiet: [act('reset-instead', 'Reset backup instead…')], choices: true }, 'recovery')
  if (c.error_code === 'wrong_account') return hero('wrong-account', 'failed', 'next', c.error, { primary: act('sign-in-again', W.signInAgain), quiet: [act('switch-to', `Switch this library to ${c.error_account || 'the other account'}…`)] })
  if (c.token_expired) return hero('sign-in-expired', 'failed', 'next', `Google stopped accepting this PC's sign-in for ${c.account}. Nothing was deleted.`, { detail: 'Backup waits, and phones pause within an hour, until you sign in again.', primary: act('sign-in-again', W.signInAgain) })
  if (task?.kind === 'update_folder') {
    if (task.error) return hero(task.stage === 'claim' ? 'update-claim-failed' : 'update-failed', 'failed', 'next', task.stage === 'claim' ? 'Updated, but this PC is not the backup PC yet.' : 'Updating this folder stopped.', { alert: task.error })
    if (['downloaded', 'swap'].includes(task.stage)) return hero(task.stage === 'swap' ? 'update-swap' : 'update-downloaded', 'paused', 'next', 'Downloaded. Restart Brainamon to switch to the newer library; this PC then backs up again.')
    return hero(task.stage === 'claim' ? 'update-claim' : 'updating', 'working', 'busy', task.stage === 'claim' ? 'Switched to the newer library. Becoming the backup PC again…' : `Updating this folder: ${amount(task.bytes_done)} of ${amount(task.bytes_total)}${online ? '' : ' · waiting for the connection'}.`,
      { detail: task.stage === 'claim' ? undefined : 'Only what the other PC changed is downloaded. Your library stays usable meanwhile; edits you make now are kept with the earlier ones.' })
  }
  if (c.error_code === 'not_owner') {
    const u = r?.update?.eligible ? r.update : null
    if (local.dismissedOther) return hero('not-owner-local', 'failed', 'next', 'Not backed up: another PC is the backup PC.', { quiet: [u ? act('update', 'Update this folder…') : act('recover', 'Get the newer library…')] })
    return u
      ? hero('not-owner-update', 'failed', 'next', `Another PC became the backup PC on ${when(u.owner_at || c.error_at || now)}. Google Drive has a newer version of this library (backup from ${when(u.published ?? now)}).`,
        { detail: u.nothing ? "Nothing changed there since this PC's last backup: updating only makes this PC the backup PC again." : `Update this folder downloads only what changed: ${amount(u.bytes ?? 0)}, ${plural(u.files ?? 0, 'file')}. Then this PC backs up again. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).`,
          primary: act('update', 'Update this folder…'), quiet: [act('recover', 'Copy into a new folder…'), act('keep-local', 'Keep working on this PC only')] })
      : hero('not-owner', 'failed', 'next', `Another PC became the backup PC${c.error_at ? ` on ${when(c.error_at)}` : ''}. This PC stopped backing up so it does not overwrite newer changes.`,
        { primary: act('recover', 'Get the newer library…'), quiet: [act('keep-local', 'Keep working on this PC only')] })
  }
  if (task && task.kind !== 'enroll') {
    if (taskStopped) return hero('task-failed', 'failed', 'next', `${task.title} stopped.`, { alert: task.error || c.error })
    return hero(`task-${task.kind}`, 'working', 'busy', `${task.title} · step ${task.step} of ${task.of}.`, { detail: !online ? 'Waiting for the connection.' : undefined })
  }
  if (rotating && !removal) return hero('foreign-rotation', 'failed', 'next', c.rotation_lock || 'A phone removal in another library must finish first.')
  if (!backedUp) {
    if (!c.on) return hero('backup-off-first', 'empty', 'next', `Google Drive connected (${c.account}). Backup is off.`, { primary: act('turn-on', W.turnOn) })
    if (!online) return hero('first-offline', 'working', 'busy', "Can't reach Google Drive. The first backup continues when the connection returns.", { detail: 'Your library stays on this PC meanwhile.' })
    if (c.error_code === 'drive_full') return hero('first-drive-full', 'failed', 'next', `Google Drive is full${c.limit ? ` (${gb(c.used)} of ${gb(c.limit)} GB)` : ''}.${c.total ? ` ${plural(Math.max(0, c.total - c.done), 'file')} are not backed up yet.` : ''}`,
      { detail: 'Free space in Google Drive, or back up fewer videos in Backup below. Brainamon tries again every 5 minutes.', primary: waits || c.error_action === 'none' ? undefined : tryAgain }, 'backup')
    if (c.state === 'error' && c.error) return waits || c.error_action === 'none' ? hero('waiting', 'working', 'busy', c.error) : hero('first-error', 'failed', 'next', c.error, { primary: tryAgain })
    return hero(c.total ? 'first-backup' : 'first-backup-starting', 'working', 'busy', c.total ? `Backing up for the first time: ${num(c.done)} of ${num(c.total)} files${c.bytes_total ? ` (${gb(c.bytes_done ?? 0)} of ${gb(c.bytes_total)} GB)` : ''}.` : 'Backing up for the first time.',
      { detail: [c.total ? `${dur(now - (c.upload_since || now))} so far.` : c.upload_step || 'Checking the Google account and what to send…', !enrolled && !recLoading && !recUnread && !enrolling ? 'You can create your recovery passphrase while it runs (Recovery below).' : ''].filter(Boolean).join(' '), quiet: c.running ? [pauseAct] : [] })
  }
  if (!c.on) return hero('backup-off', 'empty', 'next', `Backup is off. Last backup: ${when(c.last_publish)}.`, { primary: act('turn-on', W.turnOn) })
  if (!online) return hero('offline', 'working', 'busy', "Can't reach Google Drive. Changes stay on this PC and back up when the connection returns.", { detail: 'Phones keep syncing for up to an hour; after that their edits wait on the phone.' })
  if (c.error_code === 'drive_full') return hero('drive-full', 'failed', 'next', 'Google Drive is full. Recent changes are not backed up yet.', { detail: 'Free space in Google Drive, or back up fewer videos in Backup below.', primary: waits || c.error_action === 'none' ? undefined : tryAgain }, 'backup')
  if (c.state === 'error' && c.error) return waits || c.error_action === 'none' ? hero('waiting', 'working', 'busy', c.error) : hero('error', 'failed', 'next', c.error, { primary: tryAgain })
  if (c.rotation === 'complete' && c.rotation_locked_at && !(local.dismissedRemoval ?? local.dismissedNotice) && !phones.length)
    return hero('phones-removed', 'done', 'done', `All phones removed at ${hm(c.rotation_locked_at)}.`, { detail: 'Add each phone you keep again: its unsent edits arrive then.', primary: act('add-phone', W.addPhone), quiet: [act('hide', 'Hide')] })
  if (fileOutdated) return hero('file-outdated', 'done', 'done', `Your library is safe: backed up at ${since}, unlocked by your passphrase.`, { detail: 'Your old recovery file stopped working when phones were removed. Saving a replacement is optional, in case you forget your passphrase.', quiet: [act('save-file', W.saveNewFile)] })
  if (recUnread) return hero('recovery-unread', 'failed', 'next', `Backed up at ${since}. The recovery status could not be read on this PC.`, { detail: 'Brainamon cannot say whether a passphrase protects this backup. Keep the files and check again.', primary: act('retry-status', 'Check again') })
  if (recLoading) return hero('recovery-loading', 'loading', 'todo', `Backed up at ${since}. Checking recovery…`)
  if (enrolling) return hero('enrolling', 'working', 'busy', `Backed up at ${since}. Saving your recovery passphrase…`)
  if (enrollFailed) return hero('enroll-failed', 'failed', 'next', `Backed up at ${since}. Saving your recovery passphrase stopped.`, { alert: task!.error, primary: act('create-pass', W.createPass) })
  if (!enrolled) {
    if (r!.configured && sameAcc) return hero('recovery-unconfirmed', 'failed', 'next', `Backed up at ${since}. Your recovery passphrase is not confirmed in Google Drive yet.`,
      { detail: r!.check?.state === 'queued' ? 'Waiting for the current upload request, then checking recovery. Backup carries on.' : 'Check it, or create the passphrase again. Until then nothing can unlock the backup if this PC is lost.', primary: act('check-recovery', 'Check recovery') })
    return hero('no-recovery', 'empty', 'next', `Backed up at ${since}, but if this PC is lost nothing can unlock the backup.`, { detail: r!.configured ? `The recovery passphrase on this PC was made for ${r!.account}. Create one for ${c.account}.` : 'A recovery passphrase unlocks it on another PC. Backup carries on without one.', primary: act('create-pass', W.createPass) })
  }
  if (r?.updated && !(local.dismissedUpdate ?? local.dismissedNotice) && now - r.updated.at < 7 * DAY)
    return hero('updated', 'done', 'done', `Updated to the backup from ${when(r.updated.published)}. This PC is the backup PC again.`, { detail: r.updated.kept ? `Kept this PC's ${plural(r.updated.kept, 'earlier change')} in a copy of its library database (before update, ${day(r.updated.at)}); not in the newer library.` : undefined, quiet: [act('hide', 'Hide')] })
  if (['starting', 'publishing'].includes(c.state)) return hero('backing-up', 'working', 'busy', `Backing up ${c.total ? plural(c.total, 'change') : 'recent changes'}. Last complete backup ${since}.`, { detail: c.total ? `${num(c.done)} of ${num(c.total)} files.` : c.upload_step || undefined, quiet: c.running ? [pauseAct] : [] })
  return hero('safe', 'done', 'done', `Your library is safe: backed up at ${since}, unlocked by your passphrase${r!.verified_at ? ` or ${W.file}` : ''}.`, { detail: phones.length ? `${phoneSummary} These are periodic reports, not a live connection status.` : undefined })
}

// the one line the nav row's tooltip, the narrow picker and the Overview give for the whole page
function navLine(id: string, kind: Kind, rows: BackupState['rows']): string {
  if (kind === 'loading') return 'Checking…'
  if (kind === 'done') return rows.backup.text
  if (id.startsWith('task-') || id === 'updating' || id === 'activity') return 'Working'
  return ({ empty: rows.account.kind === 'empty' ? 'Not connected' : 'Needs a step', working: 'Working', failed: 'Needs you', paused: 'Paused' } as Record<string, string>)[kind] ?? ''
}

function buildTask(c: ModelCloud, r: RecoveryView | null, now: number, f: { online: boolean; paused: boolean; removal: boolean }, local: Local): TaskView | null {
  const queue = (c.tasks ?? []).map(({ id, kind, title, stage, error, code }) => ({ id, kind, title, stage, error, code }))
  const activity = c.recovery_activity as (NonNullable<CloudSnapshot['recovery_activity']> & { step_index?: number; step_count?: number }) | null | undefined
  if (activity?.state === 'running' && activity.action !== 'enroll') {
    const steps: Step[] = activity.action === 'reconnect' ? reconnectSteps(activity) : [{ label: activity.step.replace(/…$/, ''), state: 'active' }]
    const at = steps.findIndex(step => step.state === 'active')
    return { id: 'activity-' + activity.action, title: ACTIVITY[activity.action] ?? 'Working', kind: 'working', saved: false, step: Math.max(1, at + 1), of: steps.length, steps, running: true,
      progress: steps.length > 1 ? 'steps' : 'indeterminate', bar: ACTIVITY[activity.action] ?? 'Working', line: `Started ${hm(activity.started)}.`, notes: ['This step is not a saved task: if Brainamon quits now, start it again.'], leave: false, quiet: [], also: queue }
  }
  const job = r?.job
  if (job?.state === 'restoring') {
    return { id: 'copy', title: 'Copying the backup into a new folder', kind: 'working', saved: false, step: 1, of: 1, steps: [{ label: `Copying ${num(job.done)} of ${num(job.total)} files`, state: 'active' }], running: true,
      progress: 'determinate', pct: job.total ? 100 * job.done / job.total : 0, bar: 'Copying the backup', line: `Into ${job.destination}.`,
      notes: ['You can close Settings. Quitting Brainamon stops the copy; find your backup again to start over.'], leave: false, quiet: [act('stop-copy', 'Stop copying'), act('open-recover', W.recover)], also: queue }
  }
  const current = c.task as ModelTask | null | undefined
  if (!current) return null
  const t = f.paused && !current.paused_snapshot
    ? { ...current, done: 0, total: 0, bytes_done: 0, bytes_total: 0, items_done: 0, items_total: 0 }
    : current
  const autoWait = !f.online || c.error_action === 'wait' || c.error_action === 'none'
  const failed = !autoWait && (!!t.error || (t.kind !== 'enroll' && t.kind !== 'update_folder' && c.state === 'error' && !!c.error))
  const waiting = t.kind === 'update_folder' && ['downloaded', 'swap'].includes(t.stage)
  const kind: Kind = failed ? 'failed' : f.paused || waiting ? 'paused' : 'working'
  const frac = t.total ? t.done / t.total : 0
  const usesBytes = !(t.stage === 'cleanup' || (t.kind === 'remove_phones' && t.step >= 4))
  const counted = (usesBytes && t.bytes_total > 0) || t.total > 0
  const locked = c.rotation_locked_at ? `Phones locked out at ${hm(c.rotation_locked_at)}` : c.rotation_locked_by ? `Phones locked out by ${hm(c.rotation_locked_by)} at the latest (this PC stopped renewing their access)` : 'Locking phones out'
  const steps = t.steps.map((s, i) => ({ ...s, label: i === t.step - 1 ? activeLabel(t, c, s.label) : t.kind === 'remove_phones' && i === 1 ? locked : s.label }))
  if (t.kind === 'reset_backup' && t.stage === 'cleanup' && steps[1] && t.uploaded_items != null && t.uploaded_files != null) {
    steps[1].label += ` · ${num(t.uploaded_items)} / ${num(t.uploaded_items_total ?? t.uploaded_items)} item records · ${num(t.uploaded_files)} / ${num(t.uploaded_files)} files`
  }
  const notes: string[] = []
  if (t.kind === 'remove_phones') {
    notes.push('Phones you keep: add them again now. They load the library when re-encrypting finishes.')
    if (t.step === 3 && !t.done && !t.total && ['starting', 'publishing'].includes(c.state)) notes.push('Starts after the current upload request (up to a minute).')
    if (c.error_code === 'drive_full') notes.push('Google Drive is full: it needs room for both copies until the old one is deleted.')
    if (t.step === 4 && c.upload_step) notes.push(c.upload_step)
  }
  if (t.kind === 'reset_backup' && t.stage === 'backing-up') notes.push('Drive temporarily holds both copies. The old backup is deleted only after the replacement is complete.')
  if (t.kind === 'switch_account' && t.stage === 'signing-in' && !c.signed_in) notes.push('Finish signing in to the other Google account in the browser window that opened.')
  if (t.kind === 'update_folder' && t.stage === 'swap') notes.push('The switch is prepared and runs when Brainamon starts. It cannot be stopped now.')
  if (t.kind === 'disconnect' && t.step === 1) notes.push('Waiting for the current request or recovery write to end, then completing your request by itself.')
  if (!f.online && !failed) notes.push('Waiting for the connection.')
  if (f.paused) notes.push(c.state === 'stopping' || c.vault_state === 'stopping' ? 'Resume is available when the current requests finish.' : 'Paused: Resume backup continues from this step.')
  if (f.paused && t.paused_snapshot) notes.push('Last reported when Pause was requested.')
  const blocker = c.token_expired || c.key_missing || ['wrong_account', 'other_copy', 'foreign_backup'].includes(c.error_code ?? '') || (c.error_code === 'not_owner' && t.kind !== 'update_folder')
  const primary = blocker ? undefined : waiting ? act('restart', 'Restart now')
    : f.paused ? (c.state !== 'stopping' && c.vault_state !== 'stopping' ? act('resume', W.resume, { icon: 'play' }) : undefined)
    : failed ? (autoWait ? undefined : t.kind === 'enroll' ? act('create-pass', W.createPass) : t.kind === 'update_folder' ? act('retry-update', 'Try again') : act('try-again', 'Try again')) : undefined
  const quiet: Act[] = []
  if (kind === 'working' && !['disconnect', 'enroll'].includes(t.kind)) quiet.push(act('pause', W.pause, { icon: 'pause' }))
  if (t.kind === 'update_folder' && t.stage !== 'claim' && t.stage !== 'swap') quiet.push(act('stop-update', 'Stop updating'))
  const pct = usesBytes && t.bytes_total ? 100 * t.bytes_done / t.bytes_total : t.total ? 100 * frac : undefined
  return { id: t.id, title: t.title, kind, saved: true, step: t.step, of: t.of, steps, running: kind === 'working', progress: counted && !waiting ? 'determinate' : kind !== 'working' || t.of > 1 ? 'steps' : 'indeterminate',
    pct: waiting ? undefined : pct, bar: t.title, line: `Step ${t.step} of ${t.of} · started ${when(t.since)}.`, notes, error: failed ? (t.error || c.error) : undefined,
    leave: kind === 'working', primary, quiet, also: queue.filter(item => item.id !== current.id) }
}

// the step in progress says what it counts, from the same counters the server sends (done, total, bytes, items)
function activeLabel(t: CloudTask, c: ModelCloud, label: string): string {
  const bytes = t.bytes_total ? ` (${amount(t.bytes_done)} of ${amount(t.bytes_total)})` : ''
  if (t.kind === 'remove_phones') {
    if (t.step === 3) return t.total ? `Re-encrypting: ${num(t.done)} of ${num(t.total)} files${bytes}` : 'Re-encrypting the backup…'
    if (t.step === 4) return t.total ? `Checking the new copy: ${num(t.done)} of ${num(t.total)} files.` : 'Checking the new copy, including your Obsidian vault if you sync one…'
    if (t.step === 5) return t.total ? `Deleting the old copy: ${num(t.done)} of ${num(t.total)} files confirmed.` : 'Deleting the old copy'
  }
  if (t.kind === 'reset_backup' || t.kind === 'switch_account' || t.kind === 'one_shot_publish') {
    if (['backing-up', 'signing-in', 'running', 'queued'].includes(t.stage) && t.total) return `${label}: ${num(t.done)} of ${num(t.total)} files${bytes}${t.items_total ? ` · ${num(t.items_done ?? 0)} / ${num(t.items_total)} item records backed up.` : ''}`
    if (t.stage === 'backing-up' && c.upload_step) return c.upload_step
    if (t.stage === 'cleanup' && t.total) return `${label}: ${num(t.done)} of ${num(t.total)} files confirmed.`
  }
  if (t.kind === 'update_folder' && ['queued', 'downloading'].includes(t.stage) && t.bytes_total) return `${label}: ${amount(t.bytes_done)} of ${amount(t.bytes_total)}`
  if (t.kind === 'disconnect' && t.stage === 'deleting' && c.total) return `Deleting the backup: ${num(c.done)} of ${num(c.total)} files`
  return c.upload_step && t.step === 1 && t.kind === 'disconnect' ? 'Stopping current work' : label
}

export const LEAVE_NOTE = LEAVE
