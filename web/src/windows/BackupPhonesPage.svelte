<script lang="ts">
  // Settings > Backup & phones: the encrypted copy of the library in the user's Google Drive, how to get it back and the phones that
  // read it, on one page. The summary answers "is my library safe?" and holds the page's one primary key; four cards follow (Google
  // account, Backup, Recovery, Phones). Layout, words and the order of the states come from the approved mockup
  // (projects/backup-phones-mockup, web/src/previews/backup/BackupPage.svelte); this page reads the real status of /api/cloud and
  // /api/cloud/recovery. Restoring is the Recover a library window (RecoverWin.svelte), never a control here.
  import { onMount, tick, untrack } from 'svelte'
  import ForgotPassphrase from '../components/ForgotPassphrase.svelte'
  import BackupChoices from '../components/BackupChoices.svelte'
  import { openRecoveryMethod } from '../lib/recover'
  import { api } from '../lib/api'
  import { addSample, amount, day, dur, gb, hm, HOUR, num, sameAccount, timeLeft, W, DAY, type CloudView, type RecoveryView, type Sample, type Sizes } from '../lib/backup'
  import { GOOGLE_SIGN_OUT_URL, GOOGLE_SIGNIN_IN_TESTING } from '../lib/product-links'
  import { downloadRecovery, generateRecoveryPassphrase } from '../lib/recovery'
  import { isDesktop, pickFileObj, pickPath } from '../lib/pick'
  import { restartApp } from '../lib/restart'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Field from '../components/ui/Field.svelte'
  import GroupBox from '../components/ui/GroupBox.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import ItemList from '../components/ui/ItemList.svelte'
  import KeyIcon from '../components/ui/KeyIcon.svelte'
  import Label from '../components/ui/Label.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import DeletionEstimate from '../components/ui/DeletionEstimate.svelte'
  import TaskSteps from '../components/ui/TaskSteps.svelte'
  import Segmented from '../components/ui/Segmented.svelte'
  import Status from '../components/ui/Status.svelte'
  import TextButton from '../components/ui/TextButton.svelte'
  import ToggleRow from '../components/ui/ToggleRow.svelte'

  interface Pairing { url: string; svg: string; fingerprint: string; keys: string[] }
  let { cloud, sizes, err, run, setOption, reload, onrecover, onrecoverprimary, onform }: {
    cloud: CloudView; sizes: Sizes | null; err: { where: string; msg: string } | null
    run: (path: string, body?: unknown, pending?: Partial<CloudView>, where?: string) => Promise<boolean>
    setOption: (o: Partial<CloudView['options']>, where?: string) => Promise<void>
    reload: () => void; onrecover: () => void; onrecoverprimary?: (primary: boolean) => void; onform?: (open: boolean) => void
  } = $props()

  type Dot = 'done' | 'todo' | 'next'
  type Form = '' | 'pass' | 'change' | 'remove' | 'switch' | 'stop' | 'takeover' | 'fresh' | 'erase' | 'update'
  interface Act { id: string; label: string; run: () => void; icon?: 'pause' | 'play'; why?: string }
  interface Sum { dot: Dot; text: string; detail?: string; steps?: string[]; pct?: number; bar?: string; leave?: boolean; primary?: Act; quiet?: Act[]; alert?: string }

  const VIDEO_OPTIONS: { value: 'off' | 'fav' | 'all'; label: string }[] = [{ value: 'off', label: 'None' }, { value: 'fav', label: 'Favourites' }, { value: 'all', label: 'All' }]
  const CANVAS_OPTIONS: { value: 'on' | 'off'; label: string }[] = [{ value: 'off', label: 'None' }, { value: 'on', label: 'All' }]
  const KEY_NAME: Record<string, string> = { openai: 'OpenAI', anthropic: 'Anthropic' }
  const LEAVE = 'You can close Settings. Quitting Brainamon pauses this; it continues at the next start.'

  let rec = $state<RecoveryView | null>(null)
  let recError = $state('')
  let now = $state(Date.now())
  let form = $state<Form>('')
  let noKey = $state(false), choicesOpen = $state(false)
  let pass = $state(''), pass2 = $state(''), show = $state(false), current = $state(''), removeMode = $state<'keep' | 'new'>('keep')
  let del = $state(false), formError = $state(''), cardError = $state(''), note = $state('')
  let dismissedOther = $state(false)
  let dismissedDone = $state(readDone())
  let dismissedUpdated = $state(readUpdated())
  let updateAsked = false
  let pairing = $state<Pairing | null>(null), making = $state(false), pairError = $state('')
  let pairKeys = $state<string[]>(['anthropic', 'openai'])
  let kitSaved = $state(false)
  let samples = $state<Sample[]>([])
  let waitingCheck = $state(false), checkNote = $state('')
  let qr = $state<HTMLDivElement>()
  let autoOpened = false

  // the "all phones removed" line is dismissed per removal (the time it finished), kept in this browser only
  function readDone(): string { try { return localStorage.getItem('bp-done') ?? '' } catch { return '' } }
  function hideDone(at: number) { dismissedDone = String(at); try { localStorage.setItem('bp-done', dismissedDone) } catch { /* private window */ } }
  // the same for the line after Update this folder (the time it finished)
  function readUpdated(): string { try { return localStorage.getItem('bp-updated') ?? '' } catch { return '' } }
  function hideUpdated(at: number) { dismissedUpdated = String(at); try { localStorage.setItem('bp-updated', dismissedUpdated) } catch { /* private window */ } }

  async function loadRec() {
    try { rec = await api.get<RecoveryView>('/api/cloud/recovery'); recError = '' } catch (e) { recError = (e as Error).message }
  }
  onMount(() => {
    void loadRec()
    const clock = setInterval(() => { now = Date.now() }, 1000)
    const status = setInterval(() => { void loadRec() }, 2000)
    return () => { clearInterval(clock); clearInterval(status) }
  })

  function openForm(f: Form) { form = f; pass = ''; pass2 = ''; current = ''; show = false; del = false; formError = ''; removeMode = 'keep' }
  function closeForm() { form = ''; formError = ''; pass = ''; pass2 = ''; current = '' }
  async function guidePassphrase() { openForm(rec?.configured ? 'change' : 'pass'); await tick(); document.getElementById('bp-pass')?.focus() }
  function passError(): string {
    if (pass.length < 12) return 'Use at least 12 characters.'
    if (pass !== pass2) return 'The two passphrases are different.'
    return ''
  }
  const message = (e: unknown) => (e as Error).message

  // ── what the page asks of the PC ──
  const connect = () => run('/api/cloud/connect', undefined, { state: cloud.signed_in ? 'starting' : 'signing-in', error: '', error_code: '' }, 'backup')
  const cancelSignIn = () => run('/api/cloud/cancel-sign-in', undefined, { state: 'off', error: '' }, 'backup')
  const signInAgain = () => run('/api/cloud/reauth', undefined, { state: 'signing-in', error: '', error_code: '' }, 'backup')
  const pause = () => run('/api/cloud/pause', undefined, { state: 'stopping', done: 0, total: 0, error: '' }, 'backup')
  const resume = () => run('/api/cloud/resume', undefined, { state: 'starting', error: '' }, 'backup')
  const tryAgain = () => run('/api/cloud/publish', undefined, { state: 'publishing', error: '', error_code: '' }, 'backup')

  // a failure shows in the open form, or (card) in the Recovery card
  async function recCall<T = RecoveryView>(action: string, body: unknown = {}, card = false): Promise<T | null> {
    formError = cardError = ''
    try { const r = await api.post<T>('/api/cloud/recovery/' + action, body); void loadRec(); return r } catch (e) { if (card) cardError = message(e); else formError = message(e); return null }
  }
  async function savePass() {
    if (passWait) { formError = passWait; return }
    if (form !== 'pass' && form !== 'change') return
    const e = passError()
    if (e) { formError = e; return }
    if (await recCall('enroll', { password: pass, confirmation: pass2 })) { closeForm(); reload() }
  }
  async function confirmRemove() {
    formError = ''
    const body = { recovery_passphrase: '', new_passphrase: '' }
    if (rec?.configured) {
      if (removeMode === 'keep') {
        if (!current) { formError = 'Type your current recovery passphrase, or choose a new one.'; return }
        body.recovery_passphrase = current
      } else {
        const e = passError()
        if (e) { formError = e; return }
        body.new_passphrase = pass
      }
    }
    if (await run('/api/cloud/unpair', body, undefined, 'unpair')) { closeForm(); pairing = null; dismissedDone = ''; reload(); void loadRec() }
  }
  async function takeOver() {
    const ready = !!rec?.takeover_ready
    if (!ready) { const e = passError(); if (e) { formError = e; return } }
    if (await recCall('take-over', ready ? { password: '', confirmation: '', confirm: true } : { password: pass, confirmation: pass2, confirm: true })) { closeForm(); reload() }
  }
  // Update this folder (S9): Drive is only read until this PC is the backup PC again
  async function startUpdate() {
    const nothing = !!rec?.update?.nothing
    if (await recCall('update-start', { confirm: true }, true)) { closeForm(); reload(); if (nothing) toast('Nothing needed downloading. This PC is the backup PC again.') }
  }
  async function stopUpdate() { if (await recCall('update-cancel', {}, true)) reload() }
  async function restartUpdate() {
    if (m.task?.stage === 'downloaded' && !(await recCall('update-activate', {}, true))) { reload(); return }
    await restartApp().catch(e => toast(message(e), 'w'))
  }
  async function saveKit() {
    note = ''
    if (isDesktop()) {
      const folder = await pickPath('folder')
      if (!folder) return
      const r = await recCall<{ path: string; saved: boolean; verified: boolean; message?: string }>('save-kit', { path: folder.replace(/[\\/]$/, '') + '/Brainamon-recovery-' + Date.now() + '.json' }, true)
      if (r) note = r.verified ? 'Recovery file saved and checked against your backup.' : `Recovery file saved. ${r.message || 'Check it once so you know it opens your backup.'}`
    } else {
      const kit = await recCall<unknown>('kit', {}, true)
      if (kit) { kitSaved = true; downloadRecovery(kit, 'Brainamon-recovery-' + Date.now() + '.json'); note = 'Download requested. A browser download is not confirmed until you open the file.' }
    }
  }
  async function checkFile() {
    note = ''
    const file = await pickFileObj('.json,application/json')
    if (!file) return
    if (file.size > 32768) { cardError = 'Recovery files must be smaller than 32 KiB.'; return }
    if (await recCall('verify', { material: await file.text() }, true)) note = 'Recovery file checked against your backup.'
  }
  async function checkRecovery() {
    checkNote = ''; waitingCheck = true
    const r = await recCall<{ state: string; message: string }>('preflight', {}, true)
    if (r && r.state !== 'queued') await settleCheck(r as { state: string; message: string; enrolled?: boolean })
  }
  async function settleCheck(r: { state: string; message: string; enrolled?: boolean }) {
    waitingCheck = false
    if (r.state === 'ready' && r.enrolled && rec && !rec.enrolled) { await recCall('reconcile', {}, true); reload(); return }
    checkNote = r.state === 'ready' ? 'Brainamon could not confirm your recovery passphrase in Google Drive yet. Create it again below.' : r.message
  }
  // the check that met an upload runs between two upload requests; its answer arrives with the recovery status
  $effect(() => {
    const check = rec?.check
    if (waitingCheck && check && check.state !== 'queued') untrack(() => { void settleCheck(check) })
  })
  async function showPair() {
    making = true; pairError = ''
    try { pairing = await api.post<Pairing>('/api/cloud/pair', { keys: pairKeys }) } catch (e) { pairError = message(e); pairing = null } finally { making = false }
    if (pairing) { await tick(); qr?.focus() }
  }
  const openSignOutHelp = () => { window.open(GOOGLE_SIGN_OUT_URL, '_blank', 'noopener,noreferrer') }

  // ── the view model ──
  const c = $derived(cloud)
  const m = $derived.by(() => {
    const task = c.task ?? null
    const online = c.error_code !== 'offline'
    const paused = c.signed_in && !c.on && (c.paused_since ?? 0) > 0
    const pausing = c.state === 'stopping'
    const done = c.last_publish > 0
    const since = c.last_publish ? hm(c.last_publish) : hm(now)
    const removal = task?.kind === 'remove_phones' || c.rotation === 'pending'
    const rotating = removal || !!rec?.rotation_pending
    // a passphrase save that stopped has no retry of its own (its task keeps the reason): the passphrase is typed again
    const enrollFailed = task?.kind === 'enroll' && !!task.error
    const enrolling = task?.kind === 'enroll' && !enrollFailed
    const recOk = !rec || (rec.enrolled && (!rec.account || !c.account || sameAccount(rec.account, c.account)))       // not read yet: nothing to warn about
    const fileOutdated = !!rec?.file_outdated && recOk
    const file = W.file
    const phones = c.phones ?? []
    const inSync = phones.filter(p => now - p.seen < HOUR).length
    const phonesLine = phones.length ? `${inSync} of ${phones.length} phone${phones.length === 1 ? '' : 's'} in sync.` : ''
    const left = timeLeft(samples, c.bytes_done ?? 0, c.bytes_total ?? 0)
    const elapsed = now - (c.upload_since || now)
    const pausedLine = 'Backup paused.'
    const reason = err && (err.where === 'account' || err.where === 'backup') ? err.msg : ''
    const asked = (id: string, label: string, fn: () => unknown, extra: Partial<Act> = {}): Act => ({ id, label, run: () => { void fn() }, ...extra })
    const pauseAct = asked('pause', W.pause, pause, { icon: 'pause' })
    const resumeAct = asked('resume', W.resume, resume, { icon: 'play' })
    const backUp = asked('connect', W.backUp, connect, c.configured ? {} : { why: 'Google sign-in is not set up in this build.' })
    let s: Sum

    if (rec?.restart_required) s = { dot: 'next', text: 'The restored library is ready. Restart Brainamon to open it.', detail: 'Your current library stays in its folder.', primary: asked('restart', 'Restart now', () => restartApp().catch(e => toast(message(e), 'w'))) }
    else if (rec?.restored) s = { dot: 'next', text: 'This restored library is not backed up yet.', detail: 'Make this PC the backup PC once the old PC is off or closed.', primary: asked('takeover', W.takeOver, () => openForm('takeover')) }
    else if (c.error_code === 'other_copy') s = { dot: 'todo', text: c.error }
    else if (c.state === 'signing-in') s = { dot: 'todo', text: 'Finish signing in in the browser window that opened.', detail: "Choose the Google account for this library's backup.", quiet: [asked('cancel-sign-in', 'Cancel sign-in', cancelSignIn)] }
    else if (task?.kind === 'disconnect' && task.error) s = { dot: 'next', text: 'Disconnecting stopped. Your Google account is still connected.', alert: task.error, primary: c.token_expired ? asked('again', W.signInAgain, signInAgain) : asked('try-again', 'Try again', tryAgain) }
    else if (c.state === 'disconnecting' || task?.kind === 'disconnect') s = { dot: 'todo', text: 'Disconnecting from Google Drive…', detail: c.total ? `Deleting the copy: ${num(c.done)} of ${num(c.total)} files.` : 'Stopping current work automatically, then completing your request.', pct: c.total ? 100 * c.done / c.total : undefined, bar: 'Disconnecting' }
    else if (!c.signed_in) s = c.account
      ? { dot: 'next', text: `Google Drive disconnected. Backup is off. The copy in ${c.account}${c.last_publish ? ` from ${day(c.last_publish)}` : ''} stays in Drive.`, primary: backUp }
      : { dot: 'next', text: 'Your library is only on this PC.', detail: 'Back it up to your own Google Drive, encrypted: Google cannot read it.', primary: backUp }
    else if (pausing) s = { dot: 'todo', text: 'Pausing after the current upload request (up to a minute).', quiet: [asked('keep-going', 'Keep backing up', resume, { icon: 'play' })] }
    else if (paused) s = { dot: 'next', text: done ? `${pausedLine} Changes since ${since} are only on this PC.` : `${pausedLine} The first backup is not finished.`, detail: task ? `${task.title} is paused too. Resume continues from its saved step.` : undefined, primary: resumeAct }
    else if (c.error_code === 'foreign_backup') s = { dot: 'next', text: `${c.account} already holds a Brainamon backup from another PC${c.error_at ? ` (last backup ${day(c.error_at)}, ${hm(c.error_at)})` : ''}.`, detail: 'Recover it, replace it with this PC’s library, or use another Google account.', primary: asked('recover', 'Recover this backup…', onrecover), quiet: [asked('recheck', 'Check and back up again', tryAgain), asked('other-account', 'Use another account…', () => openForm('switch'))] }
    else if (c.key_missing) s = { dot: 'next', text: `${c.account} already holds this library's backup${c.last_publish ? ` (last backup ${day(c.last_publish)}, ${hm(c.last_publish)})` : ''}, but this PC no longer has the key that opens it.`, detail: "Unlock it with your passphrase, recovery file or a phone code: nothing uploads again and backup continues from where it stopped. Each phone then scans this PC's new code once (Add a phone).", primary: asked('recover', 'Unlock backup…', onrecover), quiet: [asked('fresh', 'Reset backup instead…', () => openForm('fresh'))] }
    else if (c.error_code === 'wrong_account') {
      const got = c.error_account || 'the other account'      // from the status (server/sync.py), never parsed out of the sentence
      s = { dot: 'next', text: c.error, primary: asked('again', W.signInAgain, signInAgain), quiet: [asked('switch-to', `Switch this library to ${got}…`, () => openForm('switch'))] }
    }
    else if (c.token_expired) s = { dot: 'next', text: `Google stopped accepting this PC's sign-in for ${c.account}. Nothing was deleted.`, detail: `Backup waits, and phones pause within an hour, until you sign in again.${GOOGLE_SIGNIN_IN_TESTING ? " Google asks again every 7 days while Brainamon's Google sign-in is in testing." : ''}`, primary: asked('again', W.signInAgain, signInAgain) }
    else if (task?.kind === 'update_folder' && task.error) s = { dot: 'next', text: task.stage === 'claim' ? 'Updated, but this PC is not the backup PC yet.' : 'Updating this folder stopped.', alert: task.error, primary: asked('update-again', 'Try again', startUpdate), quiet: task.stage === 'claim' ? [] : [asked('stop-update', 'Stop updating', stopUpdate)] }
    else if (task?.kind === 'update_folder' && ['queued', 'downloading'].includes(task.stage)) s = { dot: 'todo', text: `Updating this folder: ${amount(task.bytes_done)} of ${amount(task.bytes_total)}${online ? '' : ' · waiting for the connection'}.`, detail: 'Only what the other PC changed is downloaded. Your library stays usable meanwhile; edits you make now are kept with the earlier ones.', pct: task.bytes_total ? 100 * task.bytes_done / task.bytes_total : undefined, bar: 'Updating this folder', leave: true, quiet: [asked('stop-update', 'Stop updating', stopUpdate)] }
    else if (task?.kind === 'update_folder' && ['downloaded', 'swap'].includes(task.stage)) s = { dot: 'next', text: 'Downloaded. Restart Brainamon to switch to the newer library; this PC then backs up again.', primary: asked('restart', 'Restart now', restartUpdate) }
    else if (c.error_code === 'not_owner' && rec?.update?.eligible) {
      const u = rec.update
      s = dismissedOther
        ? { dot: 'todo', text: 'Not backed up: another PC is the backup PC.', quiet: [asked('update', 'Update this folder…', () => openForm('update'))] }
        : { dot: 'next', text: `Another PC became the backup PC on ${day(u.owner_at || c.error_at || now)}, ${hm(u.owner_at || c.error_at || now)}. Google Drive has a newer version of this library (backup from ${day(u.published ?? now)}, ${hm(u.published ?? now)}).`, detail: !u.nothing ? `Update this folder downloads only what changed: ${amount(u.bytes ?? 0)}, ${num(u.files ?? 0)} files. Then this PC backs up again. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).` : "Nothing changed there since this PC's last backup: updating only makes this PC the backup PC again.", primary: asked('update', 'Update this folder…', () => openForm('update')), quiet: [asked('recover', 'Copy into a new folder…', onrecover), asked('keep-local', 'Keep working on this PC only', () => { dismissedOther = true })] }
    }
    else if (c.error_code === 'not_owner') s = dismissedOther
      ? { dot: 'todo', text: 'Not backed up: another PC is the backup PC.', quiet: [asked('recover', 'Get the newer library…', onrecover)] }
      : { dot: 'next', text: `Another PC became the backup PC${c.error_at ? ` on ${day(c.error_at)}, ${hm(c.error_at)}` : ''}. This PC stopped backing up so it does not overwrite newer changes.`, primary: asked('recover', 'Get the newer library…', onrecover), quiet: [asked('keep-local', 'Keep working on this PC only', () => { dismissedOther = true })] }
    else if (task && task.kind !== 'enroll' && (task.error || (c.state === 'error' && c.error))) s = { dot: 'next', text: `${task.title} stopped.`, alert: task.error || c.error, primary: asked('try-again', 'Try again', tryAgain), quiet: [pauseAct] }
    else if (task && task.kind !== 'enroll') {
      const frac = task.total ? task.done / task.total : 0
      if (task.kind === 'remove_phones') {
        const step = task.step
        const stepNames = ['New key ready.', c.rotation_locked_at ? `Phones locked out at ${hm(c.rotation_locked_at)}.` : 'Lock phones out.',
          step === 3 ? `Re-encrypting: ${num(task.done)} of ${num(task.total)} files (${gb(task.bytes_done)} of ${gb(task.bytes_total)} GB).` : 'Re-encrypt the backup.',
          step === 4 ? `Checking the new copy: ${num(task.done)} of ${num(task.total)} files.` : 'Check the new copy.',
          step === 5 ? `Deleting the old copy${task.total ? `: ${num(task.done)} of ${num(task.total)}` : ''}.` : 'Delete the old copy.']
        const why = !online ? ' Waiting for the connection.' : paused ? ` ${pausedLine}` : c.error_code === 'drive_full' ? ' Google Drive is full: it needs room for both copies until the old one is deleted.'
          : step === 3 && !task.done && ['starting', 'publishing'].includes(c.state) ? ' Starts after the current upload request (up to a minute).' : ''
        s = { dot: 'todo', text: `Removing all phones · step ${step} of 5.${why}`, steps: stepNames, pct: step === 3 ? 70 * frac : step === 4 ? 70 + 30 * frac : step === 5 ? 100 : 0, bar: 'Removing all phones', leave: true, quiet: [paused ? resumeAct : pauseAct] }
      } else {
        s = { dot: 'todo', text: `${task.title} · step ${task.step} of ${task.of}.`, steps: task.steps.map(x => x.label + (x.state === 'active' ? '…' : '')),
          pct: task.bytes_total ? 100 * task.bytes_done / task.bytes_total : task.total ? 100 * frac : undefined, bar: task.title, leave: true, quiet: paused ? [resumeAct] : [pauseAct] }
        if (task.kind === 'reset_backup') {
          s.steps = task.steps.map(x => x.label)
          if (task.uploaded_items != null && task.uploaded_files != null && task.stage === 'cleanup') {
            s.steps[1] += ` · ${num(task.uploaded_items)} / ${num(task.uploaded_items_total ?? task.uploaded_items)} item records · ${num(task.uploaded_files)} / ${num(task.uploaded_files)} files`
          }
          if (task.stage === 'backing-up') {
            if (task.items_total !== undefined && task.items_total > 0) s.steps[1] += ` · ${num(task.items_done ?? 0)} / ${num(task.items_total)} item records backed up.`
            const pct = s.pct === undefined ? '' : `${s.pct > 0 && s.pct < 1 ? '<1' : Math.floor(s.pct)}% · `
            const bytes = task.bytes_total ? ` (${task.bytes_done ? amount(task.bytes_done) : '0 MB'} of ${amount(task.bytes_total)})` : ''
            s.detail = task.total
              ? `Uploading replacement backup: ${pct}${num(task.done)} of ${num(task.total)} files${bytes}.`
              : c.upload_step || 'Preparing the replacement backup…'
            s.detail += ' Drive temporarily holds both copies. The old backup is deleted only after the replacement is complete.'
          } else if (task.stage === 'cleanup') {
            s.detail = task.total ? `Deleting the old backup: ${num(task.done)} of ${num(task.total)} files confirmed.${task.done < task.total ? " Waiting for Google Drive to confirm the next files…" : ""}` : c.upload_step || 'Checking the old backup files to delete…'
          } else s.detail = 'Preparing a new backup key…'
        }
      }
      if (task.error || (c.state === 'error' && c.error)) s.alert = task.error || c.error
    }
    else if (!done) {
      const n = c.total, upBytes = c.bytes_done ?? 0, whole = c.bytes_total ?? 0
      if (!c.on && !paused) s = { dot: 'next', text: `Google Drive connected (${c.account}). Backup is off.`, primary: asked('turn-on', W.turnOn, connect) }
      else if (!online) s = { dot: 'todo', text: "Can't reach Google Drive. The first backup continues when the connection returns.", detail: 'Your library stays on this PC meanwhile.' }
      else if (c.error_code === 'drive_full') s = { dot: 'next', text: `Google Drive is full${c.limit ? ` (${gb(c.used)} of ${gb(c.limit)} GB)` : ''}.${n ? ` ${num(Math.max(0, n - c.done))} files are not backed up yet.` : ''}`, detail: 'Free space in Google Drive, or back up fewer videos in Backup below. Brainamon tries again every 5 minutes.', primary: asked('try-again', 'Try again', tryAgain) }
      else if (c.state === 'error' && c.error) s = { dot: 'next', text: c.error, primary: asked('try-again', 'Try again', tryAgain) }
      else if (n) s = { dot: 'todo', text: `Backing up for the first time: ${num(c.done)} of ${num(n)} files${whole ? ` (${gb(upBytes)} of ${gb(whole)} GB)` : ''}.`, detail: `${c.items_total ? `${num(c.items_done ?? 0)} / ${num(c.items_total)} item records backed up. ` : ''}${left !== null ? `About ${dur(left)} left · ` : ''}${dur(elapsed)} so far.`, pct: whole ? 100 * upBytes / whole : 100 * c.done / n, bar: 'First backup', leave: true, quiet: [pauseAct] }
      else s = { dot: 'todo', text: 'Backing up for the first time.', detail: c.upload_step || 'Checking the Google account and what to send…', leave: true, quiet: [pauseAct] }
    }
    else if (!c.on) s = { dot: 'next', text: `Backup is off. Last backup: ${day(c.last_publish)}, ${hm(c.last_publish)}.`, primary: asked('turn-on', W.turnOn, connect) }
    else if (!online) s = { dot: 'todo', text: "Can't reach Google Drive. Changes stay on this PC and back up when the connection returns.", detail: 'Phones keep syncing for up to an hour; after that their edits wait on the phone.' }
    else if (c.error_code === 'drive_full') s = { dot: 'next', text: 'Google Drive is full. Recent changes are not backed up yet.', detail: 'Free space in Google Drive, or back up fewer videos in Backup below.', primary: asked('try-again', 'Try again', tryAgain) }
    else if (c.state === 'error' && c.error) s = { dot: 'next', text: c.error, primary: asked('try-again', 'Try again', tryAgain) }
    else if (c.rotation === 'complete' && c.rotation_locked_at && dismissedDone !== String(c.rotation_locked_at) && !phones.length) s = { dot: 'done', text: `All phones removed at ${hm(c.rotation_locked_at)}.`, detail: 'Add each phone you keep again: its unsent edits arrive then.', primary: asked('add-phone', W.addPhone, showPair), quiet: [asked('dismiss', 'Hide', () => hideDone(c.rotation_locked_at!))] }
    else if (fileOutdated) s = { dot: 'next', text: `Your library is safe, but your old ${file} stopped working when phones were removed.`, detail: 'Your passphrase still unlocks the backup.', primary: asked('save-file', W.saveNewFile, saveKit) }
    else if (!recOk) s = enrolling
      ? { dot: 'todo', text: `Backed up at ${since}. Saving your recovery passphrase…` }
      : { dot: 'next', text: `Backed up at ${since}, but if this PC is lost nothing can unlock the backup.`, detail: 'A recovery passphrase unlocks it on another PC.', primary: asked('create-pass', W.createPass, () => openForm('pass')) }
    else if (rec?.updated && dismissedUpdated !== String(rec.updated.at) && now - rec.updated.at < 7 * DAY) {
      const u = rec.updated
      s = { dot: 'done', text: `Updated to the backup from ${day(u.published)}, ${hm(u.published)}. This PC is the backup PC again.`, detail: u.kept ? `Kept this PC's ${u.kept} earlier change${u.kept === 1 ? '' : 's'} in a copy of its library database (before update, ${day(u.at)}); not in the newer library.` : phonesLine || undefined, quiet: [asked('dismiss-updated', 'Hide', () => hideUpdated(u.at))] }
    }
    else if (['starting', 'publishing'].includes(c.state)) s = { dot: 'todo', text: `Backing up ${c.total || 'recent'} change${c.total === 1 ? '' : 's'}. Last complete backup ${since}.`, detail: c.total ? `${num(c.done)} / ${num(c.total)} files${c.items_total ? ` · ${num(c.items_done ?? 0)} / ${num(c.items_total)} item records backed up` : ''}.` : c.upload_step || phonesLine || undefined,
      pct: c.bytes_total ? 100 * (c.bytes_done ?? 0) / c.bytes_total : c.total ? 100 * c.done / c.total : undefined, bar: 'Backing up changes' }
    else s = { dot: 'done', text: `Your library is safe: backed up at ${since}, unlocked by your passphrase${rec?.verified ? ` or ${file}` : ''}.`, detail: phonesLine || undefined }

    // During a task the needed action can sit in a card (the replacement recovery file after a removal)
    const cardPrimary = !s.primary && removal && fileOutdated ? 'save-file' : ''
    const pri = form !== '' || choicesOpen ? 'form' : s.primary ? s.primary.id : cardPrimary
    const firstRunning = c.signed_in && c.on && !done && !c.key_missing && !c.token_expired && task?.stage !== 'queued' && !['foreign_backup', 'not_owner', 'other_copy', 'wrong_account'].includes(c.error_code ?? '')
    return { s, pri, task, online, paused, pausing, done, removal, rotating, enrolling, enrollFailed, recOk, fileOutdated, firstRunning, phones, reason, since }
  })
  const passWait = $derived(!rec ? 'Checking recovery status…' : m.rotating ? 'Passphrase changes wait until the security key update finishes uploading, verification and cleanup.' : m.enrolling ? 'Wait for the current passphrase save to finish.' : c.key_missing ? 'This PC no longer holds the backup key. Use a recovery file or code.' : !c.signed_in ? 'Connect Google Drive before changing the passphrase.' : '')
  const v = (id: string) => (m.pri === id ? 'pri' : 'default') as 'pri' | 'default'
  // A card repeats no action the summary already offers
  const shown = (id: string) => m.s.primary?.id !== id

  $effect(() => { onrecoverprimary?.(m.s.primary?.id === 'recover') })
  $effect(() => { onform?.(form !== '' || choicesOpen) })
  // another PC is the backup PC: ask once whether this folder can take its newer backup in place (T14b); reads only
  $effect(() => {
    if (c.error_code === 'not_owner' && rec && !rec.update && !c.task && !updateAsked) untrack(() => { updateAsked = true; void recCall('update-preview', {}, true) })
  })
  // A pairing code belongs to the account and phone-access capability it was made for.
  let pairedFor = ''
  $effect(() => {
    const key = `${c.account}|${c.licensed}`
    untrack(() => { if (key !== pairedFor) { pairedFor = key; pairing = null } })
  })
  // D10: the passphrase form opens by itself while the first backup runs (once per page, not a stored setting)
  $effect(() => {
    if (m.firstRunning && rec && !m.recOk && !m.enrolling && !m.rotating && !autoOpened && untrack(() => form) === '') { autoOpened = true; openForm('pass') }
  })
  // the pace of the last minute (T4)
  $effect(() => {
    const done = c.bytes_done ?? 0, whole = c.bytes_total ?? 0
    untrack(() => { samples = whole ? addSample(samples, Date.now(), done) : samples.length ? [] : samples })
  })

  // sizes for the Included list
  const SZ = $derived({ base: sizes?.base ?? 0, canvases: sizes?.canvases ?? 0, fav: sizes?.videos_fav ?? 0, all: sizes?.videos_all ?? 0 })
  const videoBytes = $derived(c.options.videos === 'all' ? SZ.all : c.options.videos === 'fav' ? SZ.fav : 0)
  const total = $derived(SZ.base + (c.options.canvases ? SZ.canvases : 0) + videoBytes)
  const g = (b: number) => (sizes ? gb(b) : '…')
  const phoneName = (p: { device: string; name: string }) => p.name || p.device
</script>

{#snippet passFields(label: string)}
  <Field label={label} for="bp-pass">
    <div>
      <div class="frow">
        <input class="inp" id="bp-pass" type={show ? 'text' : 'password'} bind:value={pass} autocomplete="new-password" spellcheck="false" oninput={() => (formError = '')} />
        <Button size="sm" onclick={() => { pass = generateRecoveryPassphrase(); pass2 = pass; show = true; formError = '' }}>Generate</Button>
        <Button size="sm" aria-pressed={show} onclick={() => (show = !show)}>{show ? 'Hide' : 'Show'}</Button>
      </div>
      <Hint>At least 12 characters. Write it down away from this PC.</Hint>
    </div>
  </Field>
  <Field label="Repeat it" for="bp-pass2"><div><input class="inp" id="bp-pass2" type="password" bind:value={pass2} autocomplete="new-password" oninput={() => (formError = '')} /></div></Field>
{/snippet}

{#snippet formErrorLine()}{#if formError}<Hint tone="error" role="alert">{formError}</Hint>{/if}{/snippet}

<div class="set-calm">
  <!-- Summary: is my library safe? -->
  <GroupBox tone="summary" aria-label="Is my library safe" active={choicesOpen || form === 'takeover' || form === 'fresh' || form === 'update'}>
    <Label as="span">Status</Label>
    <div><div>
      <Status state={m.s.dot} role="status" aria-live="polite">{m.s.text}</Status>
      {#if m.s.steps}<TaskSteps steps={m.s.steps.map((label, i) => ({ label, state: i < (m.task?.step ?? 1) - 1 ? 'done' : i === (m.task?.step ?? 1) - 1 ? 'active' : 'waiting' }))} />{/if}
      {#if m.s.bar}<Progress label={m.s.bar} pct={m.s.pct} />{/if}
      {#if m.s.bar && !m.s.alert && m.task && ['reset_backup', 'switch_account', 'disconnect'].includes(m.task.kind) && ['cleanup', 'deleting'].includes(m.task.stage) && m.task.total > m.task.done}
        {#key m.task.id}<Hint><DeletionEstimate done={m.task.done} total={m.task.total} /></Hint>{/key}
      {/if}
      {#if m.s.detail}<Hint>{m.s.detail}</Hint>{/if}
      {#if c.signed_in && (noKey || c.error_code === 'foreign_backup' || c.key_missing)}
        <div id="bp-backup-choices"><BackupChoices account={c.account} onform={open => choicesOpen = open} ondone={() => { noKey = choicesOpen = false; reload(); void loadRec() }} /></div>
      {/if}
      {#if m.s.leave}<Hint>{LEAVE}</Hint>{/if}
      {#if m.s.alert}<Hint tone="error" role="alert">{m.s.alert}</Hint>{/if}
      {#if m.reason && !m.s.alert}<Hint tone="error" role="alert">{m.reason}</Hint>{/if}
      {#if m.s.primary?.why}<Hint id="bp-why">{m.s.primary.why}</Hint>{/if}
      {#if form === 'fresh'}
        <Hint role="alert">Reset the backup in {c.account}? Brainamon backs up this PC’s library again with a new key. Existing desktop backups in this account are deleted only after the new backup is complete. Content that exists only in those backups will be lost. Your local library and standalone phone backups stay intact. Close Brainamon on other PCs first; then set a new passphrase and add your phones again.</Hint>
      {/if}
      {#if form === 'update' && rec?.update?.eligible}
        {@const u = rec.update}
        <Hint>Update this folder? Brainamon downloads {amount(u.bytes ?? 0)} of changes from {u.account || c.account}, switches to the newer library at the restart and becomes the backup PC again. The other PC stops backing up when it next starts. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).</Hint>
        {#if (u.local_changes ?? 0) > 0}<Hint role="alert">This PC has {u.local_changes} change{u.local_changes === 1 ? '' : 's'} made after its last backup ({day(u.last_backup || c.last_publish)}, {hm(u.last_backup || c.last_publish)}). They are not in the newer version and will not appear after the update. Brainamon keeps this PC's library database as a dated copy beside the library (before update, {day(now)}), so nothing is deleted, but you would redo those changes by hand.</Hint>{/if}
      {/if}
      {#if form === 'takeover'}
        <Hint>Other PCs stop backing up this library. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).{rec?.takeover_ready ? ' The passphrase you just used keeps protecting it.' : ' Type your recovery passphrase, or choose a new one.'}</Hint>
      {/if}
    </div></div>
    {#if form === 'takeover' && !rec?.takeover_ready}{@render passFields('Recovery passphrase')}{/if}
    {#if !choicesOpen && (m.s.primary || m.s.quiet?.length || form === 'takeover' || form === 'fresh' || form === 'update')}
      <span></span>
      <div>
        {#if form === 'takeover'}{@render formErrorLine()}{/if}
        {#if form === 'update' && cardError}<Hint tone="error" role="alert">{cardError}</Hint>{/if}
        <div class="frow">
          {#if form === 'takeover'}
            <Button variant="pri" size="sm" onclick={takeOver}>{W.takeOverGo}</Button>
            <TextButton onclick={closeForm}>Cancel</TextButton>
          {:else if form === 'update'}
            <Button variant="pri" size="sm" onclick={startUpdate}>Update this folder</Button>
            <TextButton onclick={closeForm}>Cancel</TextButton>
          {:else if form === 'fresh'}
            <Button variant="danger" size="sm" onclick={() => { closeForm(); void run('/api/cloud/reset', { replace_existing: true }, undefined, 'backup').then(() => reload()) }}>Reset backup</Button>
            <TextButton onclick={closeForm}>Cancel</TextButton>
          {:else}
            {#if m.s.primary}<Button variant={m.s.primary.why ? 'default' : v(m.s.primary.id)} size="sm" disabled={!!m.s.primary.why} aria-describedby={m.s.primary.why ? 'bp-why' : undefined} onclick={m.s.primary.run}>{#if m.s.primary.icon}<KeyIcon name={m.s.primary.icon} />{/if}{m.s.primary.label}</Button>{/if}
            {#each m.s.quiet ?? [] as q (q.id)}{#if q.icon}<Button size="sm" onclick={q.run}><KeyIcon name={q.icon} />{q.label}</Button>{:else}<TextButton onclick={q.run}>{q.label}</TextButton>{/if}{/each}
          {/if}
        </div>
      </div>
    {/if}
  </GroupBox>

  <!-- Google account -->
  <GroupBox aria-label={W.googleTitle} active={form === 'switch' || form === 'stop'}>
    <Label as="span" id="set-s-sync-account" tabindex={-1}>{W.googleTitle}</Label>
    <div>
      {#if !c.signed_in}<Status state="todo">Not connected</Status><Hint>Brainamon keeps an encrypted copy in a hidden folder of your Google Drive.</Hint>
      {:else if c.token_expired}<Status state="next">Sign-in expired · {c.account}</Status>
      {:else}<Status on>{c.account || 'Connected'}</Status>
        {#if GOOGLE_SIGNIN_IN_TESTING && c.token_issued}<Hint>Google asks you to sign in again every 7 days while Brainamon's sign-in is in testing. Next: {day(c.token_issued * 1000 + 7 * DAY)}.</Hint>{/if}
      {/if}
      {#if form === 'switch'}
        <Hint role="alert">Switch to another Google account? Brainamon backs up this library again in the new account{c.files ? ` (${num(c.files)} files, ${gb(c.size)} GB)` : ''}. Phones must be added again. The copy in {c.account} stays until you delete it.</Hint>
        <ToggleRow label={`Delete the copy in ${c.account} once the new backup is complete`} bind:checked={del} />
      {:else if form === 'stop'}
        <Hint role="alert">Disconnect Google Drive? Brainamon signs this PC out of Google and stops backing up. Your library stays on this PC. Phones stop syncing within an hour.</Hint>
        <ToggleRow label="Also delete the backup from Google Drive" bind:checked={del} />
        {#if del}<Hint tone="error">All Brainamon desktop backup data in {c.account} will be deleted, including inaccessible backups. Your passphrase, {W.file} and paired phones then have nothing to open. Your local library and standalone phone backups stay intact.</Hint>{/if}
      {/if}
      {#if (form === 'switch' || form === 'stop') && err?.where === 'account'}<Hint tone="error" role="alert">{err.msg}</Hint>{/if}
    </div>
    {#if c.signed_in}
      <span></span>
      <div>
        <div class="frow">
          {#if form === 'switch'}
            <Button variant="pri" size="sm" disabled={!c.configured} aria-describedby={c.configured ? undefined : 'bp-why-switch'} onclick={() => { const d = del; closeForm(); void run('/api/cloud/switch', { delete_old: d }, { state: 'disconnecting' }, 'account').then(() => reload()) }}>Switch account</Button>
            <TextButton onclick={closeForm}>Cancel</TextButton>
            {#if !c.configured}<Hint id="bp-why-switch">Google sign-in is not set up in this build.</Hint>{/if}
          {:else if form === 'stop'}
            <Button variant="danger" size="sm" onclick={() => { const d = del; closeForm(); void run('/api/cloud/sign-out', { delete_mirror: d, ...(d ? { delete_existing: true } : {}) }, { state: 'disconnecting' }, 'account').then(() => reload()) }}>{del ? 'Delete and disconnect' : W.stopGo}</Button>
            <TextButton onclick={closeForm}>Cancel</TextButton>
          {:else}
            {#if c.configured}<TextButton onclick={() => openForm('switch')}>{W.switchAccount}</TextButton>{/if}
            <TextButton onclick={() => openForm('stop')}>{W.stop}</TextButton>
          {/if}
        </div>
      </div>
    {/if}
  </GroupBox>

  <!-- Backup -->
  <GroupBox aria-label={W.backupTitle} active={form === 'erase'}>
    <Label as="span" id="set-s-sync-uploads" tabindex={-1}>{W.backupTitle}</Label>
    <div>
      {#if !c.signed_in}<Status state="todo">Off</Status><Hint>Starts when you back up to Google Drive.</Hint>
      {:else if m.paused}<Status state="next">Paused</Status>
      {:else if c.error_code === 'foreign_backup'}<Status state="next">Waiting: choose what to do with the existing backup</Status>
      {:else if c.key_missing}<Status state="next">Waiting: backup key missing</Status>
      {:else if m.removal}<Status state="todo">Re-encrypting with the new key (progress above)</Status>
      {:else if c.token_expired}<Status state="todo">Waiting: sign-in expired</Status>
      {:else if !m.online}<Status state="todo">Waiting: offline</Status>
      {:else if c.error_code === 'drive_full'}<Status state="todo">Waiting: Google Drive full</Status>
      {:else if c.error_code === 'not_owner'}<Status state="todo">Stopped: another PC backs up</Status>
      {:else if c.state === 'error'}<Status state="next">Stopped: backup needs attention</Status>
      {:else if !c.on}<Status state="todo">Off</Status>
      {:else if !m.done}<Status state="todo">First backup running (progress above)</Status>
      {:else if ['starting', 'publishing'].includes(c.state)}<Status on>Backing up {c.total || 'recent'} change{c.total === 1 ? '' : 's'}</Status>
      {:else}<Status on>Up to date · {hm(c.last_publish)}</Status><Hint>Changes back up about a minute after you make them.</Hint>{/if}
    </div>
    <Label as="span">Included</Label>
    <div>
      <ItemList items={['library', 'canvases', 'videos']} key={x => x} label="Included in the backup">
        {#snippet item(x)}
          {#if x === 'library'}Library{sizes?.items !== undefined ? ` · ${num(sizes.items)} items` : ''} · {g(SZ.base)} GB<Hint>Items, notes, reports, transcripts, chats, thumbnails.</Hint>
          {:else if x === 'canvases'}Canvases · {g(SZ.canvases)} GB
          {:else}Videos · {g(videoBytes)} GB<Hint>{c.options.videos === 'fav' ? `All videos: ${g(SZ.all)} GB.` : c.options.videos === 'off' ? `Favourites: ${g(SZ.fav)} GB.` : `Favourites only: ${g(SZ.fav)} GB.`}</Hint>{/if}
        {/snippet}
        {#snippet actions(x)}
          {#if x === 'library'}<Hint>Always</Hint>
          {:else if x === 'canvases'}<Segmented label="Canvases" tone="yes" options={CANVAS_OPTIONS} value={c.options.canvases ? 'on' : 'off'} onchange={o => setOption({ canvases: o === 'on' }, 'backup')} />
          {:else}<Segmented label="Videos" tone="yes" options={VIDEO_OPTIONS} value={c.options.videos} onchange={o => setOption({ videos: o }, 'backup')} />{/if}
        {/snippet}
      </ItemList>
      <Hint>{g(total)} GB in all, encrypted before upload.</Hint>
      {#if c.files || sizes?.files}<Hint>{num(c.files || sizes?.files || 0)} files in the backup. One item can include several files; thumbnail packs can contain several items.</Hint>{/if}
      {#if c.skipped_note}<Hint>{c.skipped_note}</Hint>{/if}
      {#if err?.where === 'backup' && !m.reason}<Hint tone="error" role="alert">{err.msg}</Hint>{/if}
    </div>
    {#if form === 'erase'}
      <span></span>
      <div>
        <Status state="next">Reset the backup?</Status>
        <Hint role="alert">Brainamon backs up this library again from scratch with a new key{c.files ? ` (${num(c.files)} files, ${gb(c.size)} GB)` : ''}, then deletes the current backup in {c.account}. There is always one to restore until the new one is complete. Your library on this PC is not touched.</Hint>
        <Hint role="alert">This replaces all Brainamon desktop backups in {c.account}, including inaccessible ones. Content found only in those backups will be lost. Your local library and standalone phone backups stay intact. Close Brainamon on other PCs first.</Hint>
        <Hint>Afterwards your passphrase, {W.file} and phone codes no longer open the old backup: choose a new passphrase and add your phones again. To remove it from Google Drive without a new one: {W.stop} above, then Delete and disconnect.</Hint>
      </div>
    {/if}
    {#if c.signed_in && !c.key_missing && !m.removal && !rec?.restored}
      <span></span>
      <div>
        <div class="frow">
          {#if form === 'erase'}
            <Button variant="danger" size="sm" onclick={() => { closeForm(); void run('/api/cloud/reset', { replace_existing: true }, undefined, 'backup').then(() => reload()) }}>Reset backup</Button>
            <TextButton onclick={closeForm}>Cancel</TextButton>
          {:else}
            {#if c.on && m.done && !m.paused && !m.pausing && !c.token_expired && !c.error_code}
              <Button size="sm" onclick={() => void pause()}><KeyIcon name="pause" />{W.pause}</Button>
            {/if}
            {#if !c.token_expired && m.online}<TextButton onclick={() => openForm('erase')}>Reset backup…</TextButton>{/if}
          {/if}
        </div>
      </div>
    {/if}
  </GroupBox>

  <!-- Recovery -->
  <GroupBox aria-label="Recovery" active={form === 'pass' || form === 'change'}>
    <Label as="span" id="set-s-sync-recovery" tabindex={-1}>Recovery</Label>
    {#if form === 'pass' || form === 'change'}
      <div>
        <Status state="next">{form === 'pass' ? 'Choose a recovery passphrase' : 'Change your recovery passphrase'}</Status>
        <Hint>{form === 'pass' ? `If this PC is lost, it unlocks your backup on another PC.${m.firstRunning ? ' You can do this while the first backup runs.' : ''}` : "You don't need the old one. The old passphrase stops working once this one is saved."}</Hint>
      </div>
      {@render passFields('Recovery passphrase')}
      <span></span>
      <div>
        {@render formErrorLine()}
        {#if passWait}<Hint id="bp-pass-wait" role="status">{passWait}</Hint>{/if}
        <div class="frow"><Button variant="pri" size="sm" disabled={!!passWait} aria-describedby={passWait ? "bp-pass-wait" : undefined} onclick={savePass}>Save passphrase</Button><TextButton onclick={closeForm}>{m.firstRunning ? 'Later' : 'Cancel'}</TextButton></div>
      </div>
    {:else}
      <div>
        {#if (m.enrolling || m.enrollFailed) && m.task}
          {@const at = m.task.step - 1}
          <Status state="todo" role="status">{!m.online ? 'Saving your passphrase · waiting for the connection' : c.token_expired ? 'Saving your passphrase · waiting until you sign in again' : `Saving your passphrase · step ${at + 1} of 3`}</Status>
          <Hint as="ol">
            <li>{at > 0 ? 'Upload request finished.' : 'Waiting for the current upload request: about 2 s, up to a minute on a slow connection.'}</li>
            <li>{at > 1 ? 'Sealed key uploaded.' : `Upload your library key, locked with the passphrase (4 KB), to Brainamon's hidden folder in ${c.account}.`}</li>
            <li>Read it back to check that it opens your backup.</li>
          </Hint>
          <Hint>The passphrase itself never leaves this PC. Backup pauses for these few seconds, then continues.</Hint>
          {#if m.task.error}<Hint tone="error" role="alert">{m.task.error}</Hint>{/if}
        {:else if !c.signed_in || c.key_missing}<Status state="todo">Not set up</Status><Hint>Available once the backup has started.</Hint>
        {:else if m.fileOutdated}<Status state="next">Recovery file outdated since {day(rec!.replaced_at ? rec!.replaced_at * 1000 : now)}</Status><Hint>Passphrase set{rec?.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''}. Removing phones made a new key. The old {W.file} no longer opens your backup; your passphrase still does.</Hint>
        {:else if m.rotating}<Status state="todo">{rec?.configured ? `Passphrase created${rec.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''}` : 'Recovery setup waits for the backup update'}</Status><Hint>The backup is being updated with a new security key. Recovery checks and passphrase changes are available after upload, verification and cleanup finish.</Hint>
        {:else if rec?.configured && !m.recOk}<Status state="next">Recovery setup not finished</Status><Hint>Passphrase created{rec.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''}. Brainamon could not confirm it in Google Drive yet. Check it, or create the passphrase again.</Hint>
          {#if waitingCheck}<Hint role="status">Waiting for the current upload request, then checking recovery. Backup carries on.</Hint>{/if}
          {#if checkNote}<Hint role="status">{checkNote}</Hint>{/if}
        {:else if !m.recOk}<Status state="next">Not set up</Status><Hint>If this PC is lost, your passphrase or a {W.file} unlocks the backup on another PC.</Hint>
        {:else if !rec?.saved_at && !kitSaved && !rec?.verified_at}<Status on>Passphrase set {day((rec?.setup_at ?? 0) * 1000 || now)}</Status><Hint>Recommended: also save a {W.file}, in case you forget the passphrase.</Hint>
        {:else if !rec?.verified_at}<Status state="next">Recovery file saved{rec?.saved_at ? ` ${day(rec.saved_at * 1000)}` : ''}, not checked</Status><Hint>{rec?.setup_at ? `Passphrase set ${day(rec.setup_at * 1000)}. ` : ''}Open it once so you know it unlocks your backup.</Hint>
        {:else}<Status on>Passphrase set {day((rec.setup_at ?? 0) * 1000 || now)} · {W.file} checked {day(rec.verified_at * 1000)}</Status><Hint>Keep the file outside this PC.</Hint>{/if}
        {#if note}<Hint role="status">{note}</Hint>{/if}
        {#if cardError}<Hint tone="error" role="alert">{cardError}</Hint>{/if}
        {#if recError}<Hint tone="error" role="alert">Could not check recovery: {recError}</Hint>{/if}
      </div>
      {#if c.signed_in && !c.key_missing && !m.enrolling}
        <span></span>
        <div>
          <div class="frow">
            {#if m.rotating && !m.fileOutdated}<Button size="sm" disabled aria-describedby="bp-why-rotation">{rec?.configured ? W.changePass : W.createPass}</Button><Hint id="bp-why-rotation">Available after the backup update finishes. Progress is shown above.</Hint>
            {:else if m.fileOutdated}{#if shown('save-file')}<Button variant={v('save-file')} size="sm" onclick={saveKit}>{W.saveNewFile}</Button>{/if}
            {:else if rec?.configured && !m.recOk}<Button size="sm" disabled={waitingCheck} aria-describedby={waitingCheck ? 'bp-why-check' : undefined} onclick={checkRecovery}>Check recovery</Button><TextButton onclick={() => openForm('pass')}>{W.createPass}</TextButton>
              {#if waitingCheck}<Hint id="bp-why-check">Checking between two upload requests.</Hint>{/if}
            {:else if !m.recOk}{#if shown('create-pass')}<Button size="sm" onclick={() => openForm('pass')}>{W.createPass}</Button>{/if}
            {:else if !rec?.saved_at && !kitSaved && !rec?.verified_at}<Button size="sm" onclick={saveKit}>{W.saveFile}</Button><TextButton onclick={() => openForm('change')}>{W.changePass}</TextButton>
            {:else if !rec?.verified_at}<Button size="sm" onclick={checkFile}>{W.checkFile}</Button><TextButton onclick={saveKit}>Save another copy…</TextButton>
            {:else}<TextButton onclick={() => openForm('change')}>{W.changePass}</TextButton><TextButton onclick={saveKit}>Save another copy…</TextButton>{/if}
          </div>
        </div>
      {/if}
    {/if}
    <span></span>
    <div>
      {#if (form === 'pass' || form === 'change') && rec?.setup_at}<Hint>Passphrase set {day(rec.setup_at * 1000)}. Recovery file {rec.file_outdated ? 'outdated' : rec.verified_at ? 'checked' : rec.saved_at ? 'saved, not checked' : 'not saved'}.</Hint>{/if}
      <ForgotPassphrase workingLabel="Change passphrase…" workingReason={passWait}
        onnone={async () => { noKey = true; await tick(); document.getElementById('bp-backup-choices')?.scrollIntoView({ block: 'nearest' }) }}
        onworking={guidePassphrase}
        onfile={() => openRecoveryMethod('file')} oncode={() => openRecoveryMethod('code')} />
    </div>
  </GroupBox>

  <!-- Phones -->
  <GroupBox aria-label={W.phonesTitle} active={!!pairing || form === 'remove'}>
    <Label as="span" id="set-s-sync-pair" tabindex={-1}>{W.phonesTitle}</Label>
    {#if !c.licensed}
      <div><Status state="todo">Update this PC</Status><Hint>Update Brainamon on this PC for payment-free phone sync. Your backup and recovery stay available.</Hint></div>
    {:else if !c.signed_in || c.key_missing}
      <div><Status state="todo">No phones</Status><Hint>Phones read your backup in Google Drive, so back up first.</Hint></div>
    {:else if pairing}
      <div>
        <div class="set-pair">
          <div class="set-qr" role="img" aria-label="Phone pairing QR code" tabindex="-1" bind:this={qr}>{@html pairing.svg}</div>
          <div>
            <Hint>Open Brainamon on the phone, then More &gt; Pair with your PC &gt; Scan (a phone already set up: More &gt; Backup &amp; phones &gt; This phone). Show this code only to your own phone: it carries your library key. Code check: {pairing.fingerprint}.</Hint>
            {#if m.removal || m.firstRunning}<Hint>The phone loads the library when the {m.removal ? 're-encrypted copy' : 'first backup'} is ready.</Hint>{/if}
            {#if c.phone_keys.length}
              <Label as="span" id="bp-pair-keys">Also send</Label>
              <div role="group" aria-labelledby="bp-pair-keys">
                {#each c.phone_keys as k (k)}<ToggleRow label={`My ${KEY_NAME[k] ?? k} key`} checked={pairKeys.includes(k)} onchange={on => { pairKeys = on ? [...new Set([...pairKeys, k])] : pairKeys.filter(x => x !== k); void showPair() }} />{/each}
                <Hint>Sent encrypted through Drive for the phone to collect, never in the code.</Hint>
              </div>
            {/if}
          </div>
        </div>
      </div>
      <span></span>
      <div><div class="frow"><Button size="sm" onclick={() => navigator.clipboard?.writeText(pairing!.url).then(() => toast('Pairing link copied. It opens your library copy: paste it only on your phone.'))}>Copy pairing link</Button><TextButton onclick={() => (pairing = null)}>Hide code</TextButton></div></div>
    {:else if form === 'remove'}
      <div>
        <Status state="next">Remove all phones?</Status>
        <Hint>Use this if a phone was lost, stolen or given away. All phones share one library key, so Brainamon cannot remove just one. It locks every phone out now, makes a new key, re-encrypts the backup{c.files ? ` (${num(c.files)} files, ${gb(c.size)} GB)` : ''}, then deletes the old copy. Add each phone you keep again: its unsent edits arrive then.</Hint>
        {#if ['starting', 'publishing'].includes(c.state)}<Hint>Phones are locked out at once; re-encrypting starts after the current upload request (up to a minute).</Hint>{/if}
      </div>
      {#if rec?.configured}
        <Label as="span">Passphrase</Label>
        <div><Segmented label="Passphrase" options={[{ value: 'keep', label: 'Keep my passphrase' }, { value: 'new', label: 'Choose a new one' }]} bind:value={removeMode} onchange={() => (formError = '')} /></div>
        {#if removeMode === 'keep'}
          <Field label="Current passphrase" for="bp-current"><div><input class="inp" id="bp-current" type="password" bind:value={current} autocomplete="current-password" oninput={() => (formError = '')} /><Hint>It protects the new key. The PC never stores it.</Hint></div></Field>
        {:else}{@render passFields('New passphrase')}{/if}
      {/if}
      <span></span>
      <div>
        {@render formErrorLine()}
        {#if err?.where === 'unpair' && !formError}<Hint tone="error" role="alert">{err.msg}</Hint>{/if}
        <div class="frow">
          <Button variant="danger" size="sm" onclick={confirmRemove}>{W.removeAllGo}</Button>
          <TextButton onclick={closeForm}>Cancel</TextButton>
        </div>
      </div>
    {:else}
      <div>
        {#if m.removal}
          <Status state="todo">{c.rotation_locked_at ? `Locked out at ${hm(c.rotation_locked_at)}` : c.rotation_locked_by ? `Locked out by ${hm(c.rotation_locked_by)} at the latest: this PC stopped renewing their access` : 'Locking phones out'}</Status>
          <Hint>Phones you keep: add them again now. They load the library when re-encrypting finishes.</Hint>
          {#if c.ignored_changes}<Hint>{c.ignored_changes} change{c.ignored_changes === 1 ? '' : 's'} from removed phones {c.ignored_changes === 1 ? 'was' : 'were'} ignored.</Hint>{/if}
        {:else if !m.phones.length}<Status state="optional">Phones read your backup</Status><Hint>This PC cannot tell which phones are paired.</Hint>
          {#if c.ignored_changes}<Hint>{c.ignored_changes} change{c.ignored_changes === 1 ? '' : 's'} from removed phones {c.ignored_changes === 1 ? 'was' : 'were'} ignored.</Hint>{/if}
        {:else}
          <Status on>{m.phones.length} phone{m.phones.length === 1 ? '' : 's'}</Status>
          <ItemList items={m.phones} key={x => x.device} label="Phones">
            {#snippet item(ph)}{phoneName(ph)} · synced {dur(Math.max(0, now - ph.seen))} ago{/snippet}
          </ItemList>
          {#if c.ignored_changes}<Hint>{c.ignored_changes} change{c.ignored_changes === 1 ? '' : 's'} from removed phones {c.ignored_changes === 1 ? 'was' : 'were'} ignored.</Hint>{/if}
        {/if}
        {#if m.removal || c.rotation === 'complete'}
          {#if m.removal}<Hint role="alert">Lost or stolen? Also sign that phone out of your Google account. Until then it can still delete Brainamon's files in your Drive, and download the old encrypted copy until step 5 deletes it.</Hint>{/if}
        {/if}
        {#if pairError}<Hint tone="error" role="alert">{pairError}</Hint>{/if}
        {#if err?.where === 'pair'}<Hint tone="error" role="alert">{err.msg}</Hint>{/if}
      </div>
      <span></span>
      <div>
        <div class="frow">
          {#if shown('add-phone')}<Button size="sm" onclick={showPair}>{making ? 'Making the code…' : W.addPhone}</Button>{/if}
          {#if !m.removal}<Button variant="danger" size="sm" onclick={() => openForm('remove')}>{W.removeAll}</Button>{/if}
          {#if m.removal}<TextButton onclick={openSignOutHelp}>How to sign a phone out</TextButton>{/if}
        </div>
      </div>
    {/if}
  </GroupBox>
</div>
