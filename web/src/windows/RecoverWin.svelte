<script lang="ts">
  // Recover a library: find the Brainamon backup in Google Drive with a passphrase, a recovery file or a phone code, then keep this
  // folder (put its key back) or copy the backup into a new folder. Drive is only read. The window pauses this PC's backup while it is
  // open and resumes it when it closes, unless a copy is on its way to becoming the library. Words and states W1 to W8 come from the
  // approved mockup (projects/backup-phones-mockup, web/src/previews/backup/RecoverWin.svelte).
  import { onMount, untrack, tick } from 'svelte'
  import ForgotPassphrase from '../components/ForgotPassphrase.svelte'
  import BackupChoices from '../components/BackupChoices.svelte'
  import { openSettings } from '../lib/io-commands.svelte'
  import { api, ApiError } from '../lib/api'
  import { addSample, amount, day, gb, hm, long, num, timeLeft, W, type CloudSnapshot, type CloudView, type RecoveryView, type Sample } from '../lib/backup'
  import { reconnectSteps } from '../lib/backup-state'
  import { on } from '../lib/events.svelte'
  import { isDesktop, pickFileObj, pickPath } from '../lib/pick'
  import { restartApp } from '../lib/restart'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Field from '../components/ui/Field.svelte'
  import GroupBox from '../components/ui/GroupBox.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import Segmented from '../components/ui/Segmented.svelte'
  import Status from '../components/ui/Status.svelte'
  import TaskSteps from '../components/ui/TaskSteps.svelte'
  import TextButton from '../components/ui/TextButton.svelte'
  import WinBody from '../components/ui/WinBody.svelte'

  let { close, initialMethod = 'pass' }: { close: () => void; initialMethod?: Method } = $props()
  type Method = 'pass' | 'file' | 'code'

  let cv = $state<CloudView | null>(null)
  let rec = $state<RecoveryView | null>(null)
  let method = $state<Method>(untrack(() => initialMethod)), pass = $state(''), code = $state(''), error = $state('')
  let another = $state(untrack(() => initialMethod !== 'pass')), wantCopy = $state(false), kept = $state(false), busy = $state(false)
  let folder = $state(''), newPass = $state(''), newPass2 = $state('')
  let finding = $state(false)          // Find backup is reading Drive: the newest recovery setup first (I5)
  let restarting = $state(false)
  let noKey = $state(false), foreign = $state(false)
  let pausing = $state(false)         // this window paused the backup and the last upload request is still finishing
  let samples = $state<Sample[]>([])
  let now = $state(Date.now())
  let pauseToken: string | null = null, pausePromise: Promise<void> | null = null
  let copyPromise: Promise<RecoveryView | null> | null = null, copyAccepted = false, copyUncertain = false, copyGeneration = 0
  let reconnectPromise: Promise<void> | null = null
  let choicePromise: Promise<void> | null = null, choiceFinished: (() => void) | null = null, choiceAccepted = false, choiceUncertain = false
  let recRequest = 0, cloudEpoch = 0, cloudSnap: CloudSnapshot | null = null
  let finished = false, finishPromise: Promise<void> | null = null

  const message = (e: unknown) => (e as Error).message
  async function readRec() {
    const request = ++recRequest
    const generation = copyGeneration, afterCopy = copyAccepted
    try {
      const result = await api.get<RecoveryView>('/api/cloud/recovery')
      if (request === recRequest) {
        rec = result
        if (afterCopy && generation === copyGeneration && ['error', 'cancelled'].includes(result.job.state)) copyAccepted = false
      }
    }
    catch (e) { if (request === recRequest) { rec = null; error = message(e) } }
  }
  function takeCloud(value: CloudView) {
    const next = cloudSnap && value.seq < cloudSnap.seq ? { ...value, ...cloudSnap } : value
    if (!cv || next.seq >= cv.seq) cv = next
  }
  async function readCloud() {
    const epoch = cloudEpoch
    try {
      const result = await api.get<CloudView>('/api/cloud')
      if (epoch === cloudEpoch) takeCloud(result)
      else if (!finished) await readCloud()
    } catch (e) { if (epoch === cloudEpoch) error = message(e); else if (!finished) await readCloud() }
  }

  // Backup is paused while this window is open; the pause is the window's own, so only the window undoes it.
  function pauseBackup() {
    if (finished || !cv || !(cv.running || cv.vault_running)) return
    pausing = true
    pausePromise = (async () => {
      try {
        const result = await api.post<CloudView & { pause_token: string | null }>('/api/cloud/pause', { source: 'recovery' })
        pauseToken = result.pause_token
      } catch (e) { error = message(e); pausing = false }
    })()
  }
  // A copy that is running or ready to open must not be disturbed by this library's uploads; a restored library stays off until it takes over.
  const keepsOff = () => choiceAccepted || copyAccepted || (!!rec && (['restoring', 'complete', 'activated'].includes(rec.job.state) || rec.restored || rec.restart_required))
  function choiceBusy(active: boolean) {
    if (active) choicePromise = new Promise(resolve => { choiceFinished = resolve })
    else { choiceFinished?.(); choiceFinished = null }
  }
  function finish() {
    if (finishPromise) return finishPromise
    finished = true
    finishPromise = (async () => {
      await pausePromise
      await copyPromise
      await reconnectPromise
      await choicePromise
      if (choiceUncertain) { toast('Backup remains paused because the backup change could not be confirmed. Check backup before resuming.', 'w'); return }
      if (copyUncertain) { toast('Backup remains paused because the copy request could not be confirmed. Check recovery before resuming.', 'w'); return }
      if (!pauseToken || keepsOff()) return
      for (let attempt = 0; attempt < 15; attempt++) {
        try {
          await api.post('/api/cloud/resume', { pause_token: pauseToken })
          return
        } catch (e) {
          if (!/still stopping/.test(message(e)) || attempt === 14) {
            toast(`Backup remains paused: ${message(e)}`, 'w')
            return
          }
          await new Promise(r => setTimeout(r, 1000))
        }
      }
    })()
    return finishPromise
  }

  onMount(() => {
    void (async () => { await Promise.all([readRec(), readCloud()]); foreign = cv?.error_code === 'foreign_backup'; await pauseBackup() })()
    const offs = [on('cloud', (d: CloudSnapshot) => {
      if (d.seq < Math.max(cloudSnap?.seq ?? 0, cv?.seq ?? 0)) return
      cloudSnap = d; if (cv) cv = { ...cv, ...d }
    }), on('hello', () => { cloudEpoch++; cloudSnap = null; cv = null; void readCloud() })]
    const status = setInterval(() => { now = Date.now(); void readRec(); if (pausing) void readCloud() }, 2000)     // the pause lands when the last upload request ends
    return () => { offs.forEach(off => off()); clearInterval(status); void finish() }
  })
  $effect(() => { if (pausing && cv && !cv.running && !cv.vault_running) pausing = false })

  const job = $derived(rec?.job)
  const found = $derived(rec?.preview && ['preview', 'error', 'cancelled'].includes(job?.state ?? '') && !another ? rec.preview : null)
  const retry = $derived(job?.state === 'error' || job?.state === 'cancelled')
  const signedIn = $derived(!!cv?.signed_in)
  const signing = $derived(cv?.state === 'signing-in')
  const wait = $derived(pausing ? 'Pausing your backup after the current upload request (up to a minute). Recovering starts right after.' : '')
  // W4b: the backup found has this folder's key and another PC moved it on: Update this folder comes first
  const update = $derived(found && rec?.update?.eligible && found.fingerprint === rec.fingerprint ? rec.update : null)
  const copied = $derived(!!rec && (job?.state === 'complete' || job?.state === 'activated' || rec.restart_required))
  $effect(() => {
    const d = job?.state === 'restoring' ? job.done : -1
    untrack(() => { samples = d >= 0 ? addSample(samples, Date.now(), d) : [] })
  })

  async function post<T = RecoveryView>(action: string, body: unknown = {}): Promise<T | null> {
    busy = true; error = ''
    try { const r = await api.post<T>('/api/cloud/recovery/' + action, body); await readRec(); return r } catch (e) { error = message(e); return null } finally { busy = false }
  }
  async function signIn() {
    error = ''
    const epoch = cloudEpoch
    try { const result = await api.post<CloudView>('/api/cloud/recovery/sign-in'); if (epoch === cloudEpoch) takeCloud(result) } catch (e) { error = message(e) }
  }
  async function cancelSignIn() {
    const epoch = cloudEpoch
    try { const result = await api.post<CloudView>('/api/cloud/cancel-sign-in'); if (epoch === cloudEpoch) takeCloud(result) } catch (e) { error = message(e) }
  }
  const methodWait = $derived(busy ? 'Wait for the current recovery check to finish.' : '')
  function chooseMethod(next: Method) {
    if (methodWait) return
    method = next; another = true; wantCopy = false; error = ''; pass = ''; code = ''; newPass = newPass2 = ''
  }
  async function guideMethod(next: Method) {
    chooseMethod(next)
    await tick()
    document.getElementById('rw-methods')?.focus()
  }
  async function find(body: { password: string } | { material: string }) {
    if (busy || pausing || methodWait) return
    another = false; wantCopy = false; finding = true
    try {
      if (await post('preview', body)) {
        pass = ''; code = ''
        if (rec?.preview?.fingerprint && rec.preview.fingerprint === rec.fingerprint) {
          await api.post('/api/cloud/recovery/update-preview').catch(() => null)       // this folder's key: can it update in place (W4b)? Reads only
          await readRec()
        }
      }
    } finally { finding = false }
  }
  async function openFile() {
    const file = await pickFileObj('.json,application/json')
    if (!file) return
    if (file.size > 32768) { error = 'Recovery files must be smaller than 32 KiB.'; return }
    await find({ material: await file.text() })
  }
  async function keep() {
    const ready = !!rec?.preview?.password_known
    if (!ready) {
      if (newPass.length < 12) { error = 'Use at least 12 characters.'; return }
      if (newPass !== newPass2) { error = 'The two passphrases are different.'; return }
    }
    reconnectPromise = (async () => {
      if (await post('reconnect', ready ? { password: '', confirmation: '', confirm: true } : { password: newPass, confirmation: newPass2, confirm: true })) { kept = true; newPass = newPass2 = ''; await readCloud() }
    })()
    await reconnectPromise
  }
  async function chooseFolder() {
    const picked = await pickPath('folder')
    if (picked) folder = picked.replace(/[\\/]$/, '') + '/Brainamon-restored-' + Date.now()
  }
  async function copy() {
    if (!folder.trim()) { error = 'Choose a new folder.'; return }
    recRequest++; copyGeneration++; copyAccepted = false
    copyPromise = (async () => {
      busy = true; error = ''; copyUncertain = true
      try {
        const result = await api.post<RecoveryView>('/api/cloud/recovery/restore', { destination: folder.trim() })
        copyAccepted = true; copyUncertain = false; await readRec(); return result
      } catch (e) {
        if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
          const request = ++recRequest
          try {
            const current = await api.get<RecoveryView>('/api/cloud/recovery')
            if (request === recRequest) {
              rec = current
              copyAccepted = ['restoring', 'complete', 'activated'].includes(current.job.state) || current.restored || current.restart_required
              copyUncertain = false
            }
          } catch { /* leave the pause in place if recovery status is unknown */ }
        }
        error = message(e); return null
      } finally { busy = false }
    })()
    await copyPromise
  }
  async function cancelCopy() { await post('cancel') }
  async function updateFolder() {
    if (await post('update-start', { confirm: true })) close()
  }
  async function restartNow() {
    if (restarting) return
    restarting = true
    let accepted = false
    try {
      if (!rec?.restart_required && !(await post('activate', { confirm: true }))) return
      await restartApp()
      accepted = true
    } catch (e) { error = message(e) }
    finally { if (!accepted) restarting = false }
  }
  const left = $derived(job?.state === 'restoring' ? timeLeft(samples, job.done, job.total) : null)
  const activity = $derived(cv?.recovery_activity?.action === 'reconnect' ? cv.recovery_activity : rec?.activity?.action === 'reconnect' ? rec.activity : null)
</script>

<WinBody>
  <div class="set-calm">
    {#if activity}
      <GroupBox aria-label="Recovery progress" active={activity.state === 'running'}>
        <Label as="span">Recovery progress</Label>
        <div><Status state={activity.state === 'running' ? 'busy' : 'next'} role="status">{activity.step}</Status>
          <TaskSteps steps={reconnectSteps(activity)} running={activity.state === 'running'} />
          {#if activity.state === 'error' && error}<Hint tone="error" role="alert">{error}</Hint>{/if}
        </div>
      </GroupBox>
    {/if}
    <GroupBox aria-label="Recover a library">
      <Label as="span">Recover</Label>
      {#if job?.state === 'restoring'}
        <div>
          <Status state="todo" role="status">Copying {num(job.done)} of {num(job.total)} files{left !== null ? ` · ${long(left)} left` : ''}</Status>
          <Progress label="Copying the backup" pct={job.total ? Math.round(100 * job.done / job.total) : 0} />
          <Hint>Into {job.destination}. You can close this window. Quitting Brainamon stops the copy; find your backup again to start over.</Hint>
          {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
        </div>
        <span></span>
        <div><div class="frow"><TextButton onclick={cancelCopy}>Stop copying</TextButton></div></div>
      {:else if copied}
        <div>
          <Status on role="status">{job?.destination ? `Copied to ${job.destination}. Drive was not changed.` : 'Restored library selected. Drive was not changed.'}</Status>
          <Hint>Restart to open it. Your current library stays in its folder.</Hint>
          {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
        </div>
        <span></span>
        <div><div class="frow"><Button variant="pri" size="sm" disabled={restarting} aria-describedby={restarting ? 'rw-restarting' : undefined} onclick={restartNow}>Restart now</Button>{#if restarting}<Hint id="rw-restarting" role="status">Preparing the library and restarting Brainamon…</Hint>{/if}</div></div>
      {:else if kept}
        <div><Status on role="status">This folder is unlocked again. Backup continues from where it stopped.</Status></div>
        <span></span>
        <div><div class="frow"><Button variant="pri" size="sm" onclick={close}>Done</Button></div></div>
      {:else if !signedIn}
        <div>
          {#if signing}<Status state="todo" role="status">Finish signing in in the browser window that opened.</Status>
          {:else}<Hint>Get a Brainamon backup from Google Drive onto this PC. Nothing in Drive changes. Sign in to the Google account that holds it.</Hint>{/if}
          {#if cv && !cv.configured && !signing}<Hint id="rw-why">Google sign-in is not set up in this build.</Hint>{/if}
          {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
        </div>
        <span></span>
        <div><div class="frow">
          {#if !signing}<Button variant="pri" size="sm" disabled={!cv || !cv.configured} aria-describedby={cv && !cv.configured ? 'rw-why' : undefined} onclick={signIn}>Sign in with Google</Button>
          {:else}<TextButton onclick={cancelSignIn}>Cancel sign-in</TextButton>{/if}
        </div></div>
      {:else if noKey}
        <div>
          <BackupChoices account={cv?.account || rec?.account || ''} replaceReason={cv?.recovery_gate_active ? 'Wait for the current recovery change to finish.' : ''} onbusy={choiceBusy} onerror={e => { choiceUncertain ||= !(e instanceof ApiError && e.status >= 400 && e.status < 500) }} ondone={() => { choiceAccepted = true; close(); openSettings('backup') }} />
          <TextButton onclick={() => noKey = false}>Back to recovery methods</TextButton>
        </div>
      {:else if found}
        <div>
          <Status on role="status">Found the backup from {day(found.published)}, {hm(found.published)}: {num(found.items)} items, {num(found.files)} files, {gb(found.bytes)} GB.</Status>
          {#if found.notice}<Hint>{found.notice}</Hint>{/if}
          {#each found.omissions as omission (omission)}<Hint>{omission}</Hint>{/each}
          {#if update && !wantCopy}<Hint>This folder already holds this backup's key: Update this folder downloads only what the other PC changed ({amount(update.bytes ?? 0)}) and makes this PC the backup PC again.</Hint>
            {#if (update.local_changes ?? 0) > 0}<Hint role="alert">This PC has {update.local_changes} change{update.local_changes === 1 ? '' : 's'} made after its last backup ({day(update.last_backup ?? now)}, {hm(update.last_backup ?? now)}). They are not in the newer version and will not appear after the update. Brainamon keeps this PC's library database as a dated copy beside the library (before update, {day(now)}), so nothing is deleted, but you would redo those changes by hand.</Hint>{/if}
          {:else if found.reconnect.ok && !wantCopy}<Hint>This folder matches it: keep it and put its key back, or copy the backup into a new folder.</Hint>
          {:else if found.reconnect.message && !wantCopy}<Hint>{found.reconnect.message}</Hint>{/if}
        </div>
        {#if found.reconnect.ok && !wantCopy && !update}
          {#if !found.password_known}
            <Field label="Recovery passphrase" for="rw-keep-pass"><div><input class="inp" id="rw-keep-pass" type="password" bind:value={newPass} autocomplete="new-password" /><Hint>Type your passphrase, or choose a new one. At least 12 characters.</Hint></div></Field>
            <Field label="Repeat it" for="rw-keep-pass2"><div><input class="inp" id="rw-keep-pass2" type="password" bind:value={newPass2} autocomplete="new-password" /></div></Field>
          {/if}
        {:else if !update || wantCopy}
          <Field label="New folder" for="rw-folder"><div>
            <div class="frow"><input class="inp" id="rw-folder" bind:value={folder} autocomplete="off" placeholder="Path to a new folder" />{#if isDesktop()}<Button size="sm" onclick={chooseFolder}>Choose…</Button>{/if}</div>
            <Hint>Needs about {gb(found.bytes * 3)} GB free while copying. Your current library stays as it is.</Hint>
            {#if !folder.trim()}<Hint id="rw-why-copy">Choose a new folder first.</Hint>{/if}
          </div></Field>
        {/if}
        <span></span>
        <div>
          {#if wait}<Hint role="status">{wait}</Hint>{/if}
          {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
          {#if job?.error}<Hint tone="error" role="alert">{job.error}</Hint>{/if}
          <div class="frow">
            {#if update && !wantCopy}
              <Button variant="pri" size="sm" disabled={busy} onclick={updateFolder}>Update this folder</Button>
              <TextButton onclick={() => (wantCopy = true)}>Copy into a new folder instead</TextButton>
            {:else if found.reconnect.ok && !wantCopy}
              <Button variant="pri" size="sm" disabled={busy || pausing || !!methodWait} aria-describedby={pausing ? 'rw-wait' : undefined} onclick={keep}>{W.keepFolder}</Button>
              <TextButton onclick={() => (wantCopy = true)}>Copy into a new folder instead</TextButton>
            {:else}
              <Button variant="pri" size="sm" disabled={busy || pausing || !folder.trim()} aria-describedby={pausing ? 'rw-wait' : !folder.trim() ? 'rw-why-copy' : undefined} onclick={copy}>{retry ? 'Retry copy' : W.copyNew}</Button>
            {/if}
            <TextButton onclick={() => { another = true; error = '' }}>Use another method</TextButton>
          </div>
        </div>
      {:else}
        <div>
          <Hint>Signed in as {cv?.account || rec?.account || 'your Google account'}. Use what you have; you see the backup before anything changes.</Hint>
          {#if wait}<Hint id="rw-wait" role="status">{wait}</Hint>{/if}
          {#if finding}<Status state="todo" role="status">Looking for your backup. Newest recovery setup first.</Status><Progress label="Finding your backup" />{/if}
        </div>
        <Label as="span">Unlock with</Label>
        <div id="rw-methods" tabindex="-1" role="group" aria-label="Recovery method">
          <Segmented disabled={!!methodWait} label="Unlock with" options={[{ value: 'pass', label: 'Passphrase' }, { value: 'file', label: 'Recovery file' }, { value: 'code', label: 'Phone code' }]} bind:value={method} onchange={chooseMethod} />
          {#if method === 'pass'}
            <input class="inp" aria-label="Recovery passphrase" type="password" bind:value={pass} autocomplete="off" onkeydown={e => { if (e.key === 'Enter' && pass && !pausing) void find({ password: pass }) }} />
            <Hint>The one you chose at setup. Forgot it? Use a {W.file} or a phone code instead.</Hint>
          {:else if method === 'file'}
            <Hint>A saved {W.file}, or one exported from a paired phone. It unlocks the backup; use the same Google account to retrieve it.</Hint>
          {:else}
            <input class="inp" aria-label="Phone code" type="password" bind:value={code} autocomplete="off" spellcheck="false" onkeydown={e => { if (e.key === 'Enter' && code && !pausing) void find({ material: code }) }} />
            <Hint>On a paired phone: Settings &gt; Backup &amp; phones &gt; Recovery code &gt; Show.</Hint>
          {/if}
        </div>
        <span></span>
        <div>
          {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
          <div class="frow">
            {#if method === 'file'}<Button variant="pri" size="sm" disabled={busy || pausing || !!methodWait} aria-describedby={pausing ? 'rw-wait' : undefined} onclick={openFile}>Open {W.file}…</Button>
            {:else if method === 'pass'}<Button variant="pri" size="sm" disabled={busy || pausing || !!methodWait || !pass} aria-describedby={pausing ? 'rw-wait' : !pass ? 'rw-why-find' : undefined} onclick={() => find({ password: pass })}>{W.findBackup}</Button>
            {:else}<Button variant="pri" size="sm" disabled={busy || pausing || !!methodWait || !code} aria-describedby={pausing ? 'rw-wait' : !code ? 'rw-why-find' : undefined} onclick={() => find({ material: code })}>{W.findBackup}</Button>{/if}
            <TextButton onclick={() => noKey = true}>I don’t have a key</TextButton>
            {#if !pass && method === 'pass' || !code && method === 'code'}<Hint id="rw-why-find">{method === 'pass' ? 'Type your passphrase first.' : 'Paste the phone code first.'}</Hint>{/if}
          </div>
        </div>
      {/if}
    </GroupBox>
    {#if !copied && !kept && job?.state !== 'restoring'}
      <GroupBox aria-label="Passphrase help">
        <Label as="span">Help</Label>
        <div>
          <ForgotPassphrase workingLabel="Open passphrase settings…"
            workingReason={methodWait || (cv?.key_missing || foreign ? 'This PC does not hold this backup’s key. Use the working PC, a recovery file or a code.' : '')}
            methodReason={methodWait}
            onworking={() => { close(); openSettings('backup', 'set-s-sync-recovery') }}
            onfile={() => guideMethod('file')} oncode={() => guideMethod('code')} onnone={() => noKey = true} />
          {#if methodWait}<Hint role="status">{methodWait}</Hint>{/if}
        </div>
      </GroupBox>
    {/if}
  </div>
</WinBody>
