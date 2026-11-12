<script lang="ts">
  // Settings > Backup & phones: the encrypted copy of the library in the user's Google Drive, how to get it back and the phones that
  // read it, on one page. The summary answers "is my library safe?" and holds the page's one primary key; four cards follow (Google
  // account, Backup, Recovery, Phones). Layout, words and the order of the states come from the approved mockup
  // (projects/backup-phones-mockup, web/src/previews/backup/BackupPage.svelte); this page reads the real status of /api/cloud and
  // /api/cloud/recovery. Restoring is the Recover a library window (RecoverWin.svelte), never a control here.
  import { onMount, tick, untrack } from 'svelte'
  import ForgotPassphrase from '../components/ForgotPassphrase.svelte'
  import BackupChoices from '../components/BackupChoices.svelte'
  import BackupTaskPanel from '../components/BackupTaskPanel.svelte'
  import { openRecoveryMethod } from '../lib/recover'
  import { openSettings } from '../lib/io-commands.svelte'
  import { api } from '../lib/api'
  import { backupState, pairingReason, type ActId, type BackupState, type GroupId } from '../lib/backup-state'
  import { amount, day, dur, gb, hm, long, num, sameAccount, W, DAY, type CloudView, type RecoveryView, type Sizes } from '../lib/backup'
  import { GOOGLE_SIGN_OUT_URL, GOOGLE_SIGNIN_IN_TESTING } from '../lib/product-links'
  import { downloadRecovery, generateRecoveryPassphrase } from '../lib/recovery'
  import { isDesktop, pickFileObj, pickPath } from '../lib/pick'
  import { restartApp } from '../lib/restart'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Disclosure from '../components/ui/Disclosure.svelte'
  import Field from '../components/ui/Field.svelte'
  import GroupBox from '../components/ui/GroupBox.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import ItemList from '../components/ui/ItemList.svelte'
  import KeyIcon from '../components/ui/KeyIcon.svelte'
  import Label from '../components/ui/Label.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import Segmented from '../components/ui/Segmented.svelte'
  import Status from '../components/ui/Status.svelte'
  import TextButton from '../components/ui/TextButton.svelte'
  import ToggleRow from '../components/ui/ToggleRow.svelte'

  interface Pairing { url: string; svg: string; fingerprint: string; keys: string[] }
  let { cloud, sizes, err, run, setOption, reload, onrecover, onrecoverprimary, onform, rec, recError, recPending, loadRec, sectionRequest, actionRequest, cancelRequest, onmodel }: {
    cloud: CloudView; sizes: Sizes | null; err: { where: string; msg: string } | null
    run: (path: string, body?: unknown, pending?: Partial<CloudView>, where?: string) => Promise<boolean>
    setOption: (o: Partial<CloudView['options']> | { phone_url: string }, where?: string) => Promise<void>
    reload: () => void; onrecover: () => void; onrecoverprimary?: (primary: boolean) => void; onform?: (open: boolean) => void
    rec: RecoveryView | null; recError: string; recPending: boolean; loadRec: () => Promise<void>
    sectionRequest?: { id: string; serial: number }
    actionRequest?: { id: ActId; serial: number }; onmodel?: (state: BackupState) => void
    cancelRequest?: { serial: number }
  } = $props()

  type Form = '' | 'pass' | 'change' | 'remove' | 'switch' | 'stop' | 'takeover' | 'fresh' | 'erase' | 'update'

  const VIDEO_OPTIONS: { value: 'off' | 'fav' | 'all'; label: string }[] = [{ value: 'off', label: 'None' }, { value: 'fav', label: 'Favourites' }, { value: 'all', label: 'All' }]
  const CANVAS_OPTIONS: { value: 'on' | 'off'; label: string }[] = [{ value: 'off', label: 'None' }, { value: 'on', label: 'All' }]
  const KEY_NAME: Record<string, string> = { openai: 'OpenAI', anthropic: 'Anthropic' }

  let now = $state(Date.now())
  let form = $state<Form>('')
  let noKey = $state(false), choicesOpen = $state(false), choicesBusy = $state(false)
  let choicesReset = $state(0)
  let accountNotice = $state('')
  let pass = $state(''), pass2 = $state(''), show = $state(false), current = $state(''), removeMode = $state<'keep' | 'new'>('keep')
  let del = $state(false), formError = $state(''), cardError = $state(''), note = $state('')
  let dismissedOther = $state(false)
  let dismissedDone = $state(readDone())
  let dismissedUpdated = $state(readUpdated())
  let updateAsked = false
  let pairing = $state<Pairing | null>(null), making = $state(false), pairError = $state('')
  let pairKeys = $state<string[]>(['anthropic', 'openai'])
  let waitingCheck = $state(false), checkNote = $state('')
  let savingKit = $state<'' | 'choosing' | 'saving' | 'preparing'>('')
  let qr = $state<HTMLDivElement>()
  let openGroup = $state<'' | GroupId>('')
  let handledSection = 0
  $effect(() => {
    const request = sectionRequest
    if (!request?.serial || request.serial === handledSection || form || choicesOpen) return
    handledSection = request.serial
    const group: Record<string, GroupId> = { 'set-s-sync-account': 'account', 'set-s-sync-uploads': 'backup', 'set-s-sync-recovery': 'recovery', 'set-s-sync-pair': 'phones',
      'set-s-sync-account-more': 'account', 'set-s-sync-backup-more': 'backup', 'set-s-sync-recovery-more': 'recovery', 'set-s-sync-phones-more': 'phones' }
    if (group[request.id]) openGroup = group[request.id]
  })
  let confirming = $state(false)
  let confirmAccount = '', restarting = $state(false)

  // the "all phones removed" line is dismissed per removal (the time it finished), kept in this browser only
  function readDone(): string { try { return localStorage.getItem('bp-done') ?? '' } catch { return '' } }
  function hideDone(at: number) { dismissedDone = String(at); try { localStorage.setItem('bp-done', dismissedDone) } catch { /* private window */ } }
  // the same for the line after Update this folder (the time it finished)
  function readUpdated(): string { try { return localStorage.getItem('bp-updated') ?? '' } catch { return '' } }
  function hideUpdated(at: number) { dismissedUpdated = String(at); try { localStorage.setItem('bp-updated', dismissedUpdated) } catch { /* private window */ } }

  onMount(() => {
    const clock = setInterval(() => { now = Date.now() }, 1000)
    const status = setInterval(() => { if (!recPending && (waitingCheck || cloud.task?.kind === 'enroll')) void loadRec() }, 2000)
    return () => { clearInterval(clock); clearInterval(status) }
  })

  function openForm(f: Form) {
    confirmAccount = cloud.account
    if (f === 'switch' || f === 'stop') openGroup = 'account'
    else if (f === 'erase' || f === 'fresh' || f === 'takeover' || f === 'update') openGroup = 'backup'
    else if (f === 'pass' || f === 'change') openGroup = 'recovery'
    else if (f === 'remove') openGroup = 'phones'
    form = f; pass = ''; pass2 = ''; current = ''; show = false; del = false; formError = ''; removeMode = 'keep'
    void tick().then(() => document.getElementById(f === 'pass' || f === 'change' || (f === 'takeover' && !rec?.takeover_ready) ? 'bp-pass' : 'bp-form-cancel')?.focus())
  }
  function closeForm() { form = ''; formError = ''; pass = ''; pass2 = ''; current = '' }
  function cancelForm() {
    const old = form
    closeForm()
    const group = old === 'switch' || old === 'stop' ? 'account' : ['erase', 'fresh', 'takeover', 'update'].includes(old) ? 'uploads' : old === 'remove' ? 'pair' : 'recovery'
    void tick().then(() => document.getElementById(`set-s-sync-${group}`)?.focus())
  }
  async function confirmCloud(path: string, body: Record<string, unknown>, pending: Partial<CloudView> | undefined, where: string) {
    if (confirming || !confirmAccount || confirmAccount !== cloud.account) return
    confirming = true
    try { if (await run(path, { ...body, expected_account: confirmAccount }, pending, where)) { closeForm(); reload() } }
    finally { confirming = false }
  }
  $effect(() => {
    const request = cancelRequest
    if (!request?.serial) return
    untrack(() => {
      if (confirming || removing || choicesBusy) return
      const old = form
      if (choicesOpen) choicesReset++
      closeForm(); noKey = choicesOpen = false
      const group = old === 'switch' || old === 'stop' ? 'account' : ['erase', 'fresh', 'takeover', 'update'].includes(old) ? 'backup' : old === 'remove' ? 'phones' : 'recovery'
      if (old) openGroup = group
      void tick().then(() => document.getElementById(`set-s-sync-${group === 'account' ? 'account' : group === 'backup' ? 'uploads' : group === 'phones' ? 'pair' : 'recovery'}`)?.focus())
    })
  })
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
  const pause = () => run('/api/cloud/pause', undefined, { state: 'stopping', error: '' }, 'backup')
  const resume = () => run('/api/cloud/resume', undefined, { state: 'starting', error: '' }, 'backup')
  const tryAgain = () => run('/api/cloud/publish', undefined, { state: 'publishing', error: '', error_code: '' }, 'backup')

  // a failure shows in the open form, or (card) in the Recovery card
  async function recCall<T = RecoveryView>(action: string, body: unknown = {}, card = false): Promise<T | null> {
    formError = cardError = ''
    try { const r = await api.post<T>('/api/cloud/recovery/' + action, body); void loadRec(); return r } catch (e) { if (card) cardError = message(e); else formError = message(e); return null }
  }
  async function savePass() {
    if (confirming) return
    if (passWait) { formError = passWait; return }
    if (form !== 'pass' && form !== 'change') return
    const e = passError()
    if (e) { formError = e; return }
    confirming = true
    try { if (await recCall('enroll', { password: pass, confirmation: pass2 })) { closeForm(); reload() } }
    finally { confirming = false }
  }
  let removing = $state(false)           // the unpair request is in flight: the key shows it and cannot be pressed twice
  async function confirmRemove() {
    if (removing || !confirmAccount || confirmAccount !== cloud.account) return
    formError = ''
    if (!rec) { formError = recError ? 'Check recovery again before removing phones.' : 'Checking recovery status…'; return }
    const body = { recovery_passphrase: '', new_passphrase: '', expected_account: confirmAccount }
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
    removing = true
    try {
      if (await run('/api/cloud/unpair', body, undefined, 'unpair')) { closeForm(); pairing = null; dismissedDone = ''; reload(); void loadRec() }
    } finally { removing = false }
  }
  async function takeOver() {
    if (confirming) return
    const ready = !!rec?.takeover_ready
    if (!ready) { const e = passError(); if (e) { formError = e; return } }
    confirming = true
    try { if (await recCall('take-over', ready ? { password: '', confirmation: '', confirm: true } : { password: pass, confirmation: pass2, confirm: true })) { closeForm(); reload() } }
    finally { confirming = false }
  }
  // Update this folder (S9): Drive is only read until this PC is the backup PC again
  async function startUpdate() {
    if (confirming) return
    const nothing = !!rec?.update?.nothing
    confirming = true
    try { if (await recCall('update-start', { confirm: true }, true)) { closeForm(); reload(); if (nothing) toast('Nothing needed downloading. This PC is the backup PC again.') } }
    finally { confirming = false }
  }
  async function stopUpdate() { if (await recCall('update-cancel', {}, true)) reload() }
  async function restartBackup() {
    if (restarting) return
    restarting = true
    let accepted = false
    try {
      if (m.task?.kind === 'update_folder') {
        if (!['downloaded', 'swap'].includes(m.task.stage)) return
        if (m.task.stage === 'downloaded' && !(await recCall('update-activate', {}, true))) { reload(); return }
      } else {
        if (!rec || !(rec.restart_required || ['complete', 'activated'].includes(rec.job.state))) {
          cardError = 'Check recovery again before restarting into the restored library.'
          void loadRec()
          return
        }
        if (rec.job.state === 'complete' && !rec.restart_required && !(await recCall('activate', { confirm: true }, true))) return
      }
      await restartApp()
      accepted = true
    } catch (e) { cardError = message(e) }
    finally { if (!accepted) restarting = false }
  }
  async function saveKit() {
    if (savingKit) return
    if (gateWait) { cardError = gateWait; return }
    if (!rec) { cardError = recPending ? 'Checking recovery status…' : 'Check recovery again before saving a file.'; return }
    note = cardError = ''
    savingKit = isDesktop() ? 'choosing' : 'preparing'
    try {
      if (isDesktop()) {
        const path = await pickPath('recovery-save')
        if (!path) return
        savingKit = 'saving'
        const r = await recCall<{ path: string; saved: boolean; verified: boolean; message?: string }>('save-kit', { path }, true)
        if (r) note = r.verified ? `Recovery file saved and checked against your backup. Saved to ${r.path}` : `Recovery file saved to ${r.path}. ${r.message || 'Check it once so you know it opens your backup.'}`
      } else {
        const kit = await recCall<unknown>('kit', {}, true)
        if (kit) { downloadRecovery(kit, 'Brainamon-recovery-' + Date.now() + '.json'); note = 'Download requested. A browser download is not confirmed until you open the file.' }
      }
      await loadRec()
    } catch (e) { cardError = message(e) }
    finally { savingKit = '' }
  }
  async function checkFile() {
    if (gateWait) { cardError = gateWait; return }
    if (!rec) { cardError = recPending ? 'Checking recovery status…' : 'Check recovery again before checking a file.'; return }
    note = ''
    const file = await pickFileObj('.json,application/json')
    if (!file) return
    if (file.size > 32768) { cardError = 'Recovery files must be smaller than 32 KiB.'; return }
    if (await recCall('verify', { material: await file.text() }, true)) note = 'Recovery file checked against your backup.'
  }
  async function checkRecovery() {
    if (waitingCheck) return
    if (gateWait) { cardError = gateWait; return }
    checkNote = ''; waitingCheck = true
    const r = await recCall<{ state: string; message: string }>('preflight', {}, true)
    if (!r) { waitingCheck = false; return }
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
    if (pairingReason(cloud)) return
    const account = cloud.account
    making = true; pairError = ''
    try { const result = await api.post<Pairing>('/api/cloud/pair', { keys: pairKeys }); pairing = account === cloud.account && !pairingReason(cloud) ? result : null } catch (e) { pairError = message(e); pairing = null } finally { making = false }
    if (pairing) { await tick(); qr?.focus() }
  }
  const openSignOutHelp = () => { window.open(GOOGLE_SIGN_OUT_URL, '_blank', 'noopener,noreferrer') }

  // ── the view model ──
  const c = $derived(cloud)
  const m = $derived.by(() => {
    const task = c.task ?? null
    const online = c.error_code !== 'offline'
    const paused = (c.paused_since ?? 0) > 0
    const pausing = c.state === 'stopping', done = c.last_publish > 0
    const removal = task?.kind === 'remove_phones'
    const rotating = removal || c.rotation === 'pending' || !!rec?.rotation_pending
    const enrollFailed = task?.kind === 'enroll' && !!task.error
    const enrolling = task?.kind === 'enroll' && !enrollFailed
    const recOk = !!rec && rec.enrolled && sameAccount(rec.account, c.account)
    const fileOutdated = !!rec?.file_outdated && recOk
    const firstRunning = c.signed_in && c.on && !done && !c.key_missing && !c.token_expired && task?.stage !== 'queued' && !['foreign_backup', 'not_owner', 'other_copy', 'wrong_account'].includes(c.error_code ?? '')
    const reason = err && (err.where === 'account' || err.where === 'backup') ? err.msg : ''
    return { task, online, paused, pausing, done, removal, rotating, enrolling, enrollFailed, recOk, fileOutdated, firstRunning, phones: c.phones ?? [], reason }
  })
  const gateWait = $derived(c.recovery_gate_active ? `${c.recovery_activity?.step || 'A recovery change is in progress.'} Wait for it to finish.` : '')
  const accountWait = $derived(!c.account ? 'Check the connected Google account before continuing.' : '')
  const resetWait = $derived(gateWait || accountWait || (!rec ? (recPending ? 'Checking recovery status…' : 'Check recovery again before resetting the backup.') : !c.signed_in ? 'Connect Google Drive before resetting the backup.' : c.key_missing ? 'Unlock the backup before resetting it.' : m.rotating ? 'Wait for phone removal to finish.' : rec.restored ? 'Complete restored-library ownership first.' : c.token_expired ? 'Sign in again before resetting the backup.' : !m.online ? 'Connect to Google Drive before resetting the backup.' : ''))
  const freshResetWait = $derived(gateWait || accountWait || (!rec ? (recPending ? 'Checking recovery status…' : 'Check recovery again before resetting the backup.') : !c.signed_in ? 'Connect Google Drive before resetting the backup.' : m.rotating ? 'Wait for phone removal to finish.' : c.token_expired ? 'Sign in again before resetting the backup.' : !m.online ? 'Connect to Google Drive before resetting the backup.' : ''))
  const updateWait = $derived(gateWait || (!rec?.update?.eligible ? 'Check that this folder can still be updated before continuing.' : ''))
  const takeoverWait = $derived(gateWait || (!rec ? (recPending ? 'Checking recovery status…' : 'Check recovery again before continuing.') : !rec.restored ? 'This library is no longer awaiting takeover.' : ''))
  const removeWait = $derived(gateWait || accountWait || (!rec ? (recPending ? 'Checking recovery status…' : 'Check recovery again before removing phones.') : !c.licensed || !c.signed_in || c.key_missing ? 'Reconnect this library before removing phones.' : m.rotating ? (c.rotation_lock || 'Phones are already being removed.') : ''))
  const passWait = $derived(gateWait || (!rec ? (recPending ? 'Checking recovery status…' : 'Check recovery again before changing the passphrase.') : m.rotating ? 'Passphrase changes wait until the security key update finishes uploading, verification and cleanup.' : m.enrolling ? 'Wait for the current passphrase save to finish.' : c.key_missing ? 'This PC no longer holds the backup key. Use a recovery file or code.' : !c.signed_in ? 'Connect Google Drive before changing the passphrase.' : ''))
  const st = $derived(backupState(c, recPending ? null : recError ? 'error' : rec, now, { dismissedOther,
    dismissedRemoval: !!c.rotation_locked_at && dismissedDone === String(c.rotation_locked_at),
    dismissedUpdate: !!rec?.updated?.at && dismissedUpdated === String(rec.updated.at) }))
  const heroWhy = $derived(restarting ? 'Preparing the library and restarting Brainamon…' : st.hero.primary?.why || (st.hero.primary?.id === 'add-phone' ? pairingReason(c) : '') || (st.hero.primary?.id === 'check-recovery' && waitingCheck ? 'Checking recovery between upload requests.' : ''))
  let taskWrap: HTMLDivElement | undefined = $state()
  $effect.pre(() => {
    if (!st.task && taskWrap?.contains(document.activeElement)) void tick().then(() => document.getElementById('set-s-sync-status')?.focus())
  })
  $effect(() => { onmodel?.(st) })
  const primary = $derived(st.task?.primary ?? st.hero.primary)
  const v = (id: string) => (!form && !choicesOpen && primary?.id === id ? 'pri' : 'default') as 'pri' | 'default'
  // A card repeats no action the summary already offers
  const shown = (id: string) => primary?.id !== id && !st.hero.quiet.some(a => a.id === id)

  $effect(() => { onrecoverprimary?.(primary?.id === 'recover' || primary?.id === 'unlock') })
  $effect(() => { onform?.(form !== '' || choicesOpen) })
  // another PC is the backup PC: ask once whether this folder can take its newer backup in place (T14b); reads only
  $effect(() => {
    if (c.error_code === 'not_owner' && rec && !rec.update && !c.task && !updateAsked) untrack(() => { updateAsked = true; void recCall('update-preview', {}, true) })
  })
  // A pairing code belongs to the account and phone-access capability it was made for.
  let pairedFor = ''
  $effect(() => {
    const key = `${c.account}|${c.licensed}`
    const reason = pairingReason(c)
    untrack(() => { if (key !== pairedFor || reason) { pairedFor = key; pairing = null } })
  })
  let formAccount = ''
  $effect(() => {
    const account = c.account
    const pending = confirming || removing || choicesBusy
    untrack(() => {
      if (pending && account !== formAccount) return
      if (formAccount && account !== formAccount && (form || choicesOpen)) {
        closeForm(); noKey = choicesOpen = false
        accountNotice = 'The Google account changed. Review the action again before continuing.'
        toast(accountNotice, 'w')
      }
      formAccount = account
    })
  })
  let autoOpen = ''
  $effect(() => {
    const target = c.error_code === 'drive_full' ? 'backup' : c.key_missing ? 'recovery' : ''
    if (target && target !== autoOpen && !untrack(() => form || openGroup)) openGroup = target
    autoOpen = target
  })
  function action(id: ActId) {
    switch (id) {
      case 'connect': case 'turn-on': void connect(); break
      case 'cancel-sign-in': void cancelSignIn(); break
      case 'sign-in-again': void signInAgain(); break
      case 'switch-to': case 'other-account': openForm('switch'); break
      case 'resume': case 'keep-going': void resume(); break
      case 'pause': void pause(); break
      case 'try-again': case 'recheck': void tryAgain(); break
      case 'recover': case 'unlock': case 'open-recover': onrecover(); break
      case 'reset-instead': openForm('fresh'); break
      case 'update': openForm('update'); break
      case 'retry-update': void startUpdate(); break
      case 'stop-update': void stopUpdate(); break
      case 'restart': void restartBackup(); break
      case 'takeover': openForm('takeover'); break
      case 'create-pass': openForm('pass'); break
      case 'check-recovery': void checkRecovery(); break
      case 'save-file': void saveKit(); break
      case 'check-file': void checkFile(); break
      case 'add-phone': openGroup = 'phones'; void showPair(); break
      case 'keep-local': dismissedOther = true; break
      case 'hide': if (st.id === 'phones-removed' && c.rotation_locked_at) hideDone(c.rotation_locked_at); else if (st.id === 'updated' && rec?.updated?.at) hideUpdated(rec.updated.at); break
      case 'retry-status': void loadRec(); break
      case 'stop-copy': void recCall('cancel', {}, true); break
    }
  }
  $effect(() => {
    const request = actionRequest
    if (request?.serial) untrack(() => action(request.id))
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

{#snippet saveFileButton(label: string)}
  <TextButton disabled={!!savingKit || !!gateWait} aria-busy={!!savingKit} aria-describedby={savingKit ? 'bp-file-status' : gateWait ? 'bp-gate-wait' : undefined} onclick={saveKit}>{savingKit === 'choosing' ? 'Choose where to save…' : savingKit === 'preparing' ? 'Preparing download…' : savingKit ? 'Saving and checking…' : label}</TextButton>
{/snippet}

{#snippet backupSpecialForm()}
  {#if form === 'fresh' || form === 'update' || form === 'takeover'}
    <Label as="span">Confirm</Label><div>
      {#if form === 'fresh'}
        <Hint role="alert">Reset the backup in {c.account}? Brainamon backs up this PC’s library again with a new key. Existing desktop backups in this account are deleted only after the new backup is complete. Content that exists only in those backups will be lost. Your local library and standalone phone backups stay intact. Close Brainamon on other PCs first; then set a new passphrase and add your phones again.</Hint>
      {:else if form === 'update' && rec?.update?.eligible}
        {@const u = rec.update}
        <Hint>Update this folder? Brainamon downloads {amount(u.bytes ?? 0)} of changes from {u.account || c.account}, switches to the newer library at the restart and becomes the backup PC again. The other PC stops backing up when it next starts. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).</Hint>
        {#if (u.local_changes ?? 0) > 0}<Hint role="alert">This PC has {u.local_changes} change{u.local_changes === 1 ? '' : 's'} made after its last backup ({day(u.last_backup || c.last_publish)}, {hm(u.last_backup || c.last_publish)}). They are not in the newer version and will not appear after the update. Brainamon keeps this PC's library database as a dated copy beside the library (before update, {day(now)}), so nothing is deleted, but you would redo those changes by hand.</Hint>{/if}
      {:else if form === 'takeover'}
        <Hint>Other PCs stop backing up this library. Phones paired with this PC keep working; phones paired with another PC scan this PC's code once (Add a phone).{rec?.takeover_ready ? ' The passphrase you just used keeps protecting it.' : ' Type your recovery passphrase, or choose a new one.'}</Hint>
      {/if}
    </div>
    {#if form === 'takeover' && !rec?.takeover_ready}{@render passFields('Recovery passphrase')}{/if}
    <span></span><div>
      {#if form === 'takeover'}{@render formErrorLine()}{/if}
      {#if form === 'update' && cardError}<Hint tone="error" role="alert">{cardError}</Hint>{/if}
      <div class="frow">
        {#if form === 'takeover'}
          {#if takeoverWait}<Hint id="bp-takeover-wait">{takeoverWait}</Hint>{/if}
          <Button variant="pri" size="sm" disabled={!!takeoverWait || confirming} aria-describedby={takeoverWait ? 'bp-takeover-wait' : confirming ? 'bp-confirming' : undefined} onclick={takeOver}>{W.takeOverGo}</Button>
          <TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>Cancel</TextButton>
        {:else if form === 'update'}
          {#if updateWait}<Hint id="bp-update-wait">{updateWait}</Hint>{/if}
          <Button variant="pri" size="sm" disabled={!!updateWait || confirming} aria-describedby={updateWait ? 'bp-update-wait' : confirming ? 'bp-confirming' : undefined} onclick={startUpdate}>Update this folder</Button>
          <TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>Cancel</TextButton>
        {:else}
          {#if freshResetWait}<Hint id="bp-reset-wait">{freshResetWait}</Hint>{/if}
          <Button variant="danger" size="sm" disabled={!!freshResetWait || confirming} aria-describedby={freshResetWait ? 'bp-reset-wait' : confirming ? 'bp-confirming' : undefined} onclick={() => confirmCloud('/api/cloud/reset', { replace_existing: true }, undefined, 'backup')}>Reset backup</Button>
          <TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>Cancel</TextButton>
        {/if}
      </div>
    </div>
  {/if}
{/snippet}

<div class="set-calm">
  <!-- Summary: is my library safe? -->
  <GroupBox id="set-s-sync-status" tabindex={-1} tone="summary" aria-label="Is my library safe" active={choicesOpen || form === 'takeover' || form === 'fresh' || form === 'update'}>
    <Label as="span" id="set-s-sync-board" tabindex={-1}>Status</Label>
    <div><div>
      <Status state={st.hero.tone} role="status" aria-live="polite">{st.hero.text}</Status>
      {#if st.hero.detail}<Hint>{st.hero.detail}</Hint>{/if}
      {#if savingKit}
        <Hint id="bp-file-status" role="status">{savingKit === 'choosing' ? 'Choose a filename and location in the Save dialog. You can cancel; your passphrase still works.' : savingKit === 'preparing' ? 'Preparing your download. After saving it, open the file to check it against your backup.' : 'Saving your recovery file, then checking it against Google Drive. This can take a minute. Your passphrase still works.'}</Hint>
        {#if savingKit !== 'choosing'}<Progress label={savingKit === 'preparing' ? 'Preparing recovery file download' : 'Saving and checking recovery file'} />{/if}
      {/if}
      {#if note}<Hint role="status">{note}</Hint>{/if}
      {#if accountNotice}<Hint role="status">{accountNotice}</Hint>{/if}
      {#if cardError}<Hint tone="error" role="alert">{cardError}</Hint>{/if}
      {#if st.hero.alert}<Hint tone="error" role="alert">{st.hero.alert}</Hint>{/if}
      {#if recError}<Hint tone="error" role="alert">Could not check recovery: {recError}</Hint>{/if}
      {#if m.reason && !st.hero.alert}<Hint tone="error" role="alert">{m.reason}</Hint>{/if}
      {#if heroWhy}<Hint id="bp-hero-why">{heroWhy}</Hint>{/if}
      {#if st.blocked}<Hint role="status">{st.blocked}</Hint>{/if}
      {#if gateWait}<Hint id="bp-gate-wait" role="status">{gateWait}</Hint>{/if}
      {#if form || choicesOpen}<Hint id="bp-form-wait">Finish or cancel the open form before changing sections.</Hint>{/if}
      {#if confirming}<Hint id="bp-confirming" role="status">Waiting for this action to finish.</Hint>{/if}
    </div></div>
    {#if !form && !choicesOpen && (st.hero.primary || st.hero.quiet.length)}
      <span></span><div><div class="frow">
        {#if st.hero.primary && !st.task?.primary}<Button variant={heroWhy ? 'default' : v(st.hero.primary.id)} size="sm" disabled={!!heroWhy} aria-describedby={heroWhy ? 'bp-hero-why' : undefined} onclick={() => action(st.hero.primary!.id)}>{#if st.hero.primary.icon}<KeyIcon name={st.hero.primary.icon} />{/if}{st.hero.primary.label}</Button>{/if}
        {#each st.hero.quiet as q (q.id)}{#if q.id === 'save-file'}{@render saveFileButton(q.label)}{:else if q.icon}<Button size="sm" onclick={() => action(q.id)}><KeyIcon name={q.icon} />{q.label}</Button>{:else}<TextButton onclick={() => action(q.id)}>{q.label}</TextButton>{/if}{/each}
      </div></div>
    {/if}
    {#each [{ id: 'account' as const, name: W.googleTitle }, { id: 'backup' as const, name: W.backupTitle }, { id: 'recovery' as const, name: 'Recovery' }, { id: 'phones' as const, name: W.phonesTitle }] as group (group.id)}
      <Label as="span">{group.name}</Label>
      <div><Status as="span" state={st.rows[group.id].tone}>{st.rows[group.id].text}</Status>
        <TextButton aria-label={`${openGroup === group.id ? 'Hide' : 'Show'} ${group.name}`} aria-expanded={openGroup === group.id} aria-controls={`bp-group-${group.id}`} disabled={!!form || choicesOpen} aria-describedby={form || choicesOpen ? 'bp-form-wait' : undefined} onclick={() => { openGroup = openGroup === group.id ? '' : group.id }}>{openGroup === group.id ? 'Hide' : 'Show'}</TextButton></div>
    {/each}
    <Label as="span">Obsidian vault</Label><div><Status as="span" state={st.rows.vault.tone}>{st.rows.vault.text}</Status><TextButton aria-label="Open Obsidian vault sync" onclick={() => openSettings('obsidian', 'set-s-sync-vault')}>Open</TextButton></div>
  </GroupBox>

  {#if st.task}<div bind:this={taskWrap}><BackupTaskPanel task={st.task} source={c.task} onaction={action} allowPrimary={!form && !choicesOpen} anchor /></div>{/if}

  {#if (c.signed_in && (noKey || c.error_code === 'foreign_backup' || c.key_missing)) || choicesOpen}
    <GroupBox aria-label="No recovery key">
      <Label as="span">Other choices</Label><div id="bp-backup-choices">
        <Disclosure summary="No passphrase, recovery file or phone code?" open={noKey || choicesOpen}>
          {#key `${c.account}:${choicesReset}`}<BackupChoices account={c.account} replaceReason={freshResetWait} onform={open => choicesOpen = open} onbusy={busy => choicesBusy = busy} ondone={() => { noKey = choicesOpen = choicesBusy = false; reload(); void loadRec() }} />{/key}
        </Disclosure>
      </div>
    </GroupBox>
  {/if}


  <!-- Google account -->
  <div id="bp-group-account" hidden={openGroup !== 'account'}>
  <GroupBox aria-label={W.googleTitle} active={form === 'switch' || form === 'stop'}>
    <Label as="span" id="set-s-sync-account" tabindex={-1}>{W.googleTitle}</Label>
    <div>
      <Status state={st.rows.account.tone}>{st.rows.account.text}</Status>
      {#if !c.signed_in}<Hint>Brainamon keeps an encrypted copy in a hidden folder of your Google Drive.</Hint>
      {:else if !c.token_expired}
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
      {#if accountWait}<Hint id="bp-account-wait">{accountWait}</Hint>{/if}
      {#if (form === 'switch' || form === 'stop') && err?.where === 'account'}<Hint tone="error" role="alert">{err.msg}</Hint>{/if}
    </div>
    {#if c.signed_in || form === 'switch' || form === 'stop'}
      <span></span>
      <div>
        <div class="frow">
          {#if form === 'switch'}
            <Button variant="pri" size="sm" disabled={!c.configured || !c.signed_in || !!gateWait || !!accountWait || confirming} aria-describedby={accountWait ? 'bp-account-wait' : gateWait ? 'bp-gate-wait' : confirming ? 'bp-confirming' : !c.configured || !c.signed_in ? 'bp-why-switch' : undefined} onclick={() => confirmCloud('/api/cloud/switch', { delete_old: del }, { state: 'disconnecting' }, 'account')}>Switch account</Button>
            <TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>Cancel</TextButton>
            {#if !c.configured || !c.signed_in}<Hint id="bp-why-switch">Connect Google Drive before switching accounts.</Hint>{/if}
          {:else if form === 'stop'}
            <Button variant="danger" size="sm" disabled={confirming || !!accountWait} aria-describedby={accountWait ? 'bp-account-wait' : confirming ? 'bp-confirming' : undefined} onclick={() => confirmCloud('/api/cloud/sign-out', { delete_mirror: del, ...(del ? { delete_existing: true } : {}) }, { state: 'disconnecting' }, 'account')}>{del ? 'Delete and disconnect' : W.stopGo}</Button>
            <TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>Cancel</TextButton>
          {:else}
            <Disclosure id="set-s-sync-account-more" tabindex={-1} summary="More: switch account, disconnect">
              <div class="frow">{#if c.configured}<TextButton onclick={() => openForm('switch')}>{W.switchAccount}</TextButton>{/if}
                <TextButton onclick={() => openForm('stop')}>{W.stop}</TextButton></div>
            </Disclosure>
          {/if}
        </div>
      </div>
    {/if}
  </GroupBox>
  </div>

  <!-- Backup -->
  <div id="bp-group-backup" hidden={openGroup !== 'backup'}>
  <GroupBox aria-label={W.backupTitle} active={['erase', 'fresh', 'takeover', 'update'].includes(form)}>
    <Label as="span" id="set-s-sync-uploads" tabindex={-1}>{W.backupTitle}</Label>
    <div>
      <Status state={st.rows.backup.tone}>{st.rows.backup.text}</Status>
      {#if st.rows.backup.detail}<Hint>{st.rows.backup.detail}</Hint>{/if}
    </div>
    {@render backupSpecialForm()}
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
    {#if form === 'erase' || (!form && c.signed_in && !c.key_missing && !m.rotating && !rec?.restored)}
      <span></span>
      <div>
        <div class="frow">
          {#if form === 'erase'}
            {#if resetWait}<Hint id="bp-reset-wait">{resetWait}</Hint>{/if}
            <Button variant="danger" size="sm" disabled={!!resetWait || confirming} aria-describedby={resetWait ? 'bp-reset-wait' : confirming ? 'bp-confirming' : undefined} onclick={() => confirmCloud('/api/cloud/reset', { replace_existing: true }, undefined, 'backup')}>Reset backup</Button>
            <TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>Cancel</TextButton>
          {:else}
            {#if c.on && m.done && !m.paused && !m.pausing && !c.token_expired && !c.error_code}
              <Button size="sm" onclick={() => void pause()}><KeyIcon name="pause" />{W.pause}</Button>
            {/if}
            {#if !c.token_expired && m.online}<Disclosure id="set-s-sync-backup-more" tabindex={-1} summary="More: reset the backup"><TextButton onclick={() => openForm('erase')}>Reset backup…</TextButton></Disclosure>{/if}
          {/if}
        </div>
      </div>
    {/if}
  </GroupBox>
  </div>

  <!-- Recovery -->
  <div id="bp-group-recovery" hidden={openGroup !== 'recovery'}>
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
        {#if recError}<Hint tone="error" role="alert">Could not check recovery: {recError}</Hint><TextButton onclick={loadRec}>Check again</TextButton>{/if}
        <div class="frow"><Button variant="pri" size="sm" disabled={!!passWait || confirming} aria-describedby={passWait ? 'bp-pass-wait' : confirming ? 'bp-confirming' : undefined} onclick={savePass}>Save passphrase</Button><TextButton id="bp-form-cancel" disabled={confirming} aria-describedby={confirming ? 'bp-confirming' : undefined} onclick={cancelForm}>{m.firstRunning ? 'Later' : 'Cancel'}</TextButton></div>
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
        {:else if !rec}<Status state={recPending ? 'todo' : 'next'}>{recPending ? 'Checking recovery status…' : 'Could not check recovery.'}</Status>
        {:else if !c.signed_in || c.key_missing}<Status state="todo">Not set up</Status><Hint>Available once the backup has started.</Hint>
        {:else if m.fileOutdated}<Status on>Passphrase set · old recovery file outdated</Status><Hint>Removing phones made a new key. The old {W.file} no longer opens your backup; your passphrase still does. Saving a replacement file is optional.</Hint>
        {:else if m.rotating}<Status state="todo">{rec?.configured ? `Passphrase created${rec.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''}` : 'Recovery setup waits for the backup update'}</Status><Hint>The backup is being updated with a new security key. Recovery checks and passphrase changes are available after upload, verification and cleanup finish.</Hint>
        {:else if rec?.configured && !m.recOk}<Status state="next">Recovery setup not finished</Status><Hint>Passphrase created{rec.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''}. Brainamon could not confirm it in Google Drive yet. Check it, or create the passphrase again.</Hint>
          {#if waitingCheck}<Hint role="status">Waiting for the current upload request, then checking recovery. Backup carries on.</Hint>{/if}
          {#if checkNote}<Hint role="status">{checkNote}</Hint>{/if}
        {:else if !m.recOk}<Status state="next">Not set up</Status><Hint>If this PC is lost, your passphrase or a {W.file} unlocks the backup on another PC.</Hint>
        {:else if !rec?.saved_at && !rec?.verified_at}<Status on>Passphrase set{rec?.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''}</Status><Hint>Optional: also save a {W.file}, in case you forget the passphrase.</Hint>
        {:else if !rec?.verified_at}<Status state="next">Recovery file saved{rec?.saved_at ? ` ${day(rec.saved_at * 1000)}` : ''}, not checked</Status><Hint>{rec?.setup_at ? `Passphrase set ${day(rec.setup_at * 1000)}. ` : ''}Open it once so you know it unlocks your backup.</Hint>
        {:else}<Status on>Passphrase set{rec.setup_at ? ` ${day(rec.setup_at * 1000)}` : ''} · {W.file} checked {day(rec.verified_at * 1000)}</Status><Hint>Keep the file outside this PC.</Hint>{/if}
        {#if recError}<Hint tone="error" role="alert">Could not check recovery: {recError}</Hint>{/if}
      </div>
      {#if !rec && recError && shown('check-again')}
        <span></span><div><Button size="sm" onclick={loadRec}>Check again</Button></div>
      {:else if rec && c.signed_in && !c.key_missing && !m.enrolling}
        <span></span>
        <div>
          <div class="frow">
            {#if m.rotating && !m.fileOutdated}<Button size="sm" disabled aria-describedby="bp-why-rotation">{rec?.configured ? W.changePass : W.createPass}</Button><Hint id="bp-why-rotation">{m.removal ? 'Available after the backup update finishes. Progress is shown above.' : c.rotation_lock || 'Another library is updating its security key. Wait for it to finish.'}</Hint>
            {:else if m.fileOutdated}{#if shown('save-file')}{@render saveFileButton(W.saveNewFile)}{/if}
            {:else if rec?.configured && !m.recOk}{#if shown('check-recovery')}<Button size="sm" disabled={waitingCheck || !!gateWait} aria-describedby={gateWait ? 'bp-gate-wait' : waitingCheck ? 'bp-why-check' : undefined} onclick={checkRecovery}>Check recovery</Button>{/if}<TextButton onclick={() => openForm('pass')}>{W.createPass}</TextButton>
              {#if waitingCheck}<Hint id="bp-why-check">Checking between two upload requests.</Hint>{/if}
            {:else if !m.recOk}{#if shown('create-pass')}<Button size="sm" onclick={() => openForm('pass')}>{W.createPass}</Button>{/if}
            {:else if !rec?.saved_at && !rec?.verified_at}{@render saveFileButton(W.saveFile)}
            {:else if !rec?.verified_at}<Button size="sm" disabled={!!gateWait} aria-describedby={gateWait ? 'bp-gate-wait' : undefined} onclick={checkFile}>{W.checkFile}</Button>{/if}
          </div>
        </div>
      {/if}
    {/if}
    <span></span>
    <div>
      {#if (form === 'pass' || form === 'change') && rec?.setup_at}<Hint>Passphrase set {day(rec.setup_at * 1000)}. Recovery file {rec.file_outdated ? 'outdated' : rec.verified_at ? 'checked' : rec.saved_at ? 'saved, not checked' : 'not saved'}.</Hint>{/if}
      <TextButton onclick={onrecover}>{W.recover}</TextButton>
      <Disclosure id="set-s-sync-recovery-more" tabindex={-1} summary="More: change passphrase, another copy, forgot it">
        {#if rec && m.recOk}<div class="frow"><TextButton disabled={!!passWait} aria-describedby={passWait ? 'bp-more-pass-wait' : undefined} onclick={() => openForm('change')}>{W.changePass}</TextButton>{@render saveFileButton('Save another copy…')}</div>{#if passWait}<Hint id="bp-more-pass-wait">{passWait}</Hint>{/if}{/if}
        <ForgotPassphrase workingLabel="Change passphrase…" workingReason={passWait}
          onnone={async () => { noKey = true; await tick(); document.getElementById('bp-backup-choices')?.scrollIntoView({ block: 'nearest' }) }}
          onworking={guidePassphrase}
          onfile={() => openRecoveryMethod('file')} oncode={() => openRecoveryMethod('code')} />
      </Disclosure>
    </div>
  </GroupBox>
  </div>

  <!-- Phones -->
  <div id="bp-group-phones" hidden={openGroup !== 'phones'}>
  <GroupBox aria-label={W.phonesTitle} active={!!pairing || form === 'remove'}>
    <Label as="span" id="set-s-sync-pair" tabindex={-1}>{W.phonesTitle}</Label>
    {#if !c.licensed && form !== 'remove'}
      <div><Status state="todo">Update this PC</Status><Hint>Update Brainamon on this PC for payment-free phone sync. Your backup and recovery stay available.</Hint></div>
    {:else if (!c.signed_in || c.key_missing) && form !== 'remove'}
      <div><Status state="todo">No phones</Status><Hint>Phones read your backup in Google Drive, so back up first.</Hint></div>
    {:else if pairing}
      <div>
        <div class="set-pair">
          <div class="set-qr" role="img" aria-label="Phone pairing QR code" tabindex="-1" bind:this={qr}>{@html pairing.svg}</div>
          <div>
            <Hint>Open Brainamon on the phone, then Settings &gt; Pair with your PC &gt; Scan (a phone already set up: Settings &gt; Backup &amp; phones &gt; This phone). Show this code only to your own phone: it carries your library key. Code check: {pairing.fingerprint}.</Hint>
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
        {#if removing}
          <Progress label="Removing all phones" />
          <Hint id="bp-removing" role="status">Locking phones out and making a new key. This can take a moment; the steps appear here next.</Hint>
        {/if}
        <div class="frow">
          {#if removeWait}<Hint id="bp-remove-wait">{removeWait}</Hint>{/if}
          <Button variant="danger" size="sm" disabled={removing || !!removeWait} aria-busy={removing} aria-describedby={removing ? 'bp-removing' : removeWait ? 'bp-remove-wait' : undefined} onclick={confirmRemove}>{removing ? 'Removing all phones…' : W.removeAllGo}</Button>
          <TextButton id="bp-form-cancel" disabled={removing} aria-describedby={removing ? 'bp-removing' : undefined} onclick={cancelForm}>Cancel</TextButton>
        </div>
      </div>
    {:else}
      <div>
        {#if m.removal}
          <Status state="todo">{c.rotation_locked_at ? `Locked out at ${hm(c.rotation_locked_at)}` : c.rotation_locked_by ? `Locked out by ${hm(c.rotation_locked_by)} at the latest: this PC stopped renewing their access` : 'Locking phones out'}</Status>
          <Hint>Phones you keep: add them again now. They load the library when re-encrypting finishes.</Hint>
          {#if c.ignored_changes}<Hint>{c.ignored_changes} change{c.ignored_changes === 1 ? '' : 's'} from removed phones {c.ignored_changes === 1 ? 'was' : 'were'} ignored.</Hint>{/if}
        {:else if !m.phones.length}<Status state="optional">{st.rows.phones.text}</Status><Hint>{st.rows.phones.detail}</Hint>
          {#if c.ignored_changes}<Hint>{c.ignored_changes} change{c.ignored_changes === 1 ? '' : 's'} from removed phones {c.ignored_changes === 1 ? 'was' : 'were'} ignored.</Hint>{/if}
        {:else}
          <Status on>{st.rows.phones.text}</Status>
          <Hint>{st.rows.phones.detail}</Hint>
          <ItemList items={m.phones} key={x => x.device} label="Phones">
            {#snippet item(ph)}{phoneName(ph)} · last reported sync {long(Math.max(0, now - ph.seen))} ago{/snippet}
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
          {#if shown('add-phone')}<Button size="sm" disabled={!!pairingReason(c) || making} aria-describedby={pairingReason(c) ? 'bp-pair-why' : undefined} onclick={showPair}>{making ? 'Making the code…' : W.addPhone}</Button>{/if}
          {#if m.removal}<TextButton onclick={openSignOutHelp}>How to sign a phone out</TextButton>{/if}
        </div>
      </div>
    {/if}
    {#if pairingReason(c)}<span></span><div><Hint id="bp-pair-why">{pairingReason(c)}</Hint></div>{/if}
    <span></span><div><Disclosure id="set-s-sync-phones-more" tabindex={-1} summary="More: remove all phones, phone page address">
      {#if c.signed_in && c.licensed && !c.key_missing && !m.removal && form !== 'remove'}<Button variant="danger" size="sm" onclick={() => openForm('remove')}>{W.removeAll}</Button>{/if}
      <Field label="Phone page" for="c-purl"><div>
        <input class="inp" id="c-purl" name="phone_url" type="url" autocomplete="off" spellcheck="false" value={c.phone_url} onchange={e => setOption({ phone_url: (e.currentTarget as HTMLInputElement).value }, 'page')} />
        {#if err?.where === 'page'}<Hint tone="error" role="alert">{err.msg}</Hint>{/if}
        <Hint>Where the phone opens Brainamon. During development, reach this PC over USB with adb reverse tcp:18765 tcp:18765.</Hint>
      </div></Field>
    </Disclosure></div>
  </GroupBox>
  </div>
</div>
