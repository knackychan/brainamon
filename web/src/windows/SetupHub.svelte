<script lang="ts">
  import { onMount, tick } from 'svelte'
  import { api } from '../lib/api'
  import { on } from '../lib/events.svelte'
  import { openImport, openSettings } from '../lib/io-commands.svelte'
  import { lib } from '../lib/library.svelte'
  import { IC, pxPath } from '../lib/px'
  import { SRC_COLOR, SRC_MARK } from '../lib/cards/card'
  import { ANSWERS, desktopTasks, startFor, SETUP_STEPS, type DriveState } from '../lib/onboarding'
  import { loadInstallChecks, loadOnboarding, onb, runStart, saveOnboarding } from '../lib/onboarding.svelte'
  import type { SetupView } from '../lib/setup'
  import { restartApp } from '../lib/restart'
  import { isDesktop, pickPath } from '../lib/pick'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import SectionTitle from '../components/ui/SectionTitle.svelte'
  import Status from '../components/ui/Status.svelte'
  import InfoTip from '../components/ui/InfoTip.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'
  import OptionalSetup from '../components/OptionalSetup.svelte'
  import ImportSetup from '../components/ImportSetup.svelte'
  import SetupAI from '../components/SetupAI.svelte'
  import LicenseSettings from '../components/LicenseSettings.svelte'

  let { close }: { close: () => void } = $props()
  type SetupFacts = Omit<SetupView, 'tools' | 'tool_status' | 'tool_install'>
  let v = $state<SetupFacts | null>(null), error = $state(''), checkError = $state('')
  let cloud = $state<(DriveState & { last_publish?: number; account?: string; configured: boolean; licensed: boolean; rotation?: string;
    running: boolean; vault_running: boolean; done: number; total: number; error: string; phone_keys: string[] }) | null>(null)
  let recovery = $state<{ enrolled: boolean; verified: boolean; restored: boolean } | null>(null)
  let cloudBusy = $state(false), cloudError = $state(''), pairMessage = $state('')
  let pairKeys = $state<string[]>(['anthropic', 'openai'])
  let pairing = $state<{ url: string; svg: string; fingerprint: string; keys: string[] } | null>(null)
  const keyName: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI' }
  const cloudMoving = $derived(['signing-in', 'starting', 'stopping', 'disconnecting'].includes(cloud?.state ?? ''))
  const titles = ['Your library', 'Tools & environment', 'Your first content', 'Wiskit AI', 'Drive & recovery', 'Connect your phone']
  const tasks = $derived(desktopTasks(onb.answer, { items: Math.max(v?.items ?? 0, v?.next_items ?? 0, onb.items, lib.rows.length), notes: Math.max(onb.notes, v?.next_notes ?? 0),
    wiskit: onb.wiskit, tools: onb.tools && onb.browser, drive: !!cloud?.signed_in && !!cloud.last_publish,
    recovery: !!recovery?.enrolled, phone: !!v?.phone_seen }))
  // A library folder chosen for the next start: its content counts before the restart loads it.
  const nextDir = $derived(v?.data_dir_next && v.data_dir_next !== v.data_dir ? v.data_dir_next : '')
  let restarting = $state(false)
  async function restart() {
    restarting = true; error = ''
    try { await restartApp() } catch (e) { error = (e as Error).message; restarting = false }
  }
  // Choosing another library folder stays in Setup: the native folder dialog in the desktop window, a typed path in a browser tab.
  let typing = $state(false), typed = $state(''), folderBusy = $state(false)
  async function chooseFolder() {
    error = ''
    if (!isDesktop()) { typing = true; return }
    const p = await pickPath('folder')
    if (p) await useFolder(p)
  }
  async function useFolder(path: string) {
    folderBusy = true; error = ''
    try { await api.put('/api/app/data-dir', { path }); typing = false; typed = ''; await load() }
    catch (e) { error = (e as Error).message } finally { folderBusy = false }
  }
  const ready = $derived(tasks.filter(t => t.done).length)
  const step = $derived(onb.step === 'summary' ? 6 : SETUP_STEPS.indexOf(onb.step))
  const source = $derived(startFor(onb.answer))
  const consequence = [
    'The current library stays active. Choosing a different folder takes effect after restarting.',
    'Links, notes, CSV and Brainamon JSON still work. Browser helpers and video features wait for their tools.',
    'Your library stays available; add links, notes or imports whenever you want.',
    'Saving and keyword search still work. AI answers, descriptions and semantic search wait for a provider key.',
    'Your local library stays usable. Content that has not been uploaded cannot be restored from Drive.',
    'Everything stays on this PC. You can pair your phone later, without payment.',
  ]
  function takeCloud(value: typeof cloud) {
    if (value && cloud && value.seq < cloud.seq) return
    if (cloud?.account !== value?.account || !value?.licensed || value.rotation === 'pending') pairing = null
    cloud = value
  }
  let loading = false
  async function load() {
    if (loading) return
    loading = true
    try {
      const [s, c, r] = await Promise.all([api.get<SetupFacts>('/api/app/setup?include_tools=false'), api.get<NonNullable<typeof cloud>>('/api/cloud').catch(() => null),
        api.get<NonNullable<typeof recovery>>('/api/cloud/recovery').catch(() => null), loadOnboarding()])
      v = s; takeCloud(c); recovery = r; if (r) onb.recovery = r.enrolled; onb.phone = !!s.phone_seen
      error = c && r ? '' : 'Some optional setup checks could not finish. Retry checks before relying on their readiness.'
    } catch (e) { error = (e as Error).message } finally { loading = false }
  }
  async function checkTools() {
    checkError = await loadInstallChecks() ? '' : 'Some optional tool checks could not finish. Retry checks before relying on their readiness.'
  }
  function refreshChecks() {
    void load(); void checkTools()
  }
  onMount(() => {
    refreshChecks()
    const offs = [on('settings_changed', refreshChecks), on('export_done', load), on('notes_changed', load), on('items_changed', load), on('cloud', load)]
    const refresh = () => { if (!document.hidden) void load() }
    window.addEventListener('focus', refresh)
    // Recovery and the library folder choice have no event of their own; refresh while their step is open.
    const timer = setInterval(() => { if (step === 0 || step === 4 || step === 5) void load() }, 4000)
    return () => { offs.forEach(f => f()); clearInterval(timer); window.removeEventListener('focus', refresh) }
  })
  $effect(() => { if (step !== 5) { pairing = null; pairMessage = '' } })
  async function cloudAction(path: string) {
    if (cloudBusy) return
    cloudBusy = true; cloudError = ''
    try { takeCloud(await api.post<NonNullable<typeof cloud>>(path)) }
    catch (e) { cloudError = (e as Error).message }
    finally { cloudBusy = false }
  }
  // Step 1 and 3 shortcut: sign in to Google here, then continue on the Drive step where restore lives.
  async function restoreFromDrive() {
    if (cloud && !cloud.signed_in && cloud.configured) {
      await cloudAction('/api/cloud/recovery/sign-in')
      if (cloudError) return
    }
    await visit(4)
  }
  async function showPair() {
    if (!cloud?.licensed || cloudBusy || cloud.rotation === 'pending') return
    const account = cloud.account
    cloudBusy = true; cloudError = ''; pairMessage = ''
    try {
      const result = await api.post<NonNullable<typeof pairing>>('/api/cloud/pair', { keys: pairKeys.filter(k => cloud!.phone_keys.includes(k)) })
      if (step === 5 && cloud?.account === account && cloud.licensed && cloud.rotation !== 'pending') pairing = result
    } catch (e) { cloudError = (e as Error).message }
    finally { cloudBusy = false }
  }
  async function copyPair() {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard is unavailable. Scan the QR instead.')
      await navigator.clipboard.writeText(pairing!.url)
      pairMessage = 'Pairing link copied. Paste it only on your own phone.'
    } catch { pairMessage = 'Could not copy the pairing link. Scan the QR instead.' }
  }
  async function visit(n: number, skipped = onb.skipped) {
    const saved = saveOnboarding({ step: n === 6 ? 'summary' : SETUP_STEPS[n], skipped })
    await tick(); document.getElementById('setup-stage')?.focus()
    try { await saved; await load() }
    catch (e) { error = `Could not save setup position: ${(e as Error).message}` }
  }
  function next(skip = false) {
    const skipped = skip && !tasks[step]?.done ? [...new Set([...onb.skipped, SETUP_STEPS[step]])] : onb.skipped
    void visit(Math.min(6, step + 1), skipped)
  }
  async function choose(answer: string) {
    try { await saveOnboarding({ answer }); error = '' }
    catch (e) { error = (e as Error).message }
  }
  async function finish() {
    try { if (!onb.answer) await saveOnboarding({ answer: 'skip' }); await loadOnboarding(); close() }
    catch (e) { error = (e as Error).message }
  }
</script>

<WinBody class="setup-surface">
  <div class="setup-layout">
    <aside>
      <h2>Let’s get you set up.</h2>
      <Hint>Six steps, one clear path. Check tools before your first import.</Hint>
      <Status role="status">{ready} of 6 ready</Status>
      <Progress label="Setup readiness" pct={ready * 100 / 6} />
      <nav aria-label="Setup checklist">
        {#each tasks as task, i (task.id)}
          <button type="button" class:current={step === i} aria-current={step === i ? 'step' : undefined} onclick={() => visit(i)}>
            <Status class="step-mark" state={task.done ? 'done' : step === i ? 'next' : i > 2 ? 'optional' : 'todo'} n={i + 1} />
            <span><b>{titles[i]}</b><small>{task.done ? i === 3 ? 'Key saved · not tested' : i === 5 ? 'Phone has synced' : 'Ready' : onb.skipped.includes(SETUP_STEPS[i]) ? 'Skipped · finish later' : i > 2 ? 'Optional · not finished' : 'Not finished'}</small></span>
          </button>
        {/each}
      </nav>
      <Hint>Skipped steps stay on your checklist. Reopen from App menu &gt; Setup.</Hint>
    </aside>
    <section aria-labelledby="setup-stage">
      <h2 id="setup-stage" tabindex="-1">{step < 6 ? `Step ${step + 1} of 6: ${titles[step]}` : 'Your setup, at a glance'}</h2>
      {#if onb.saving}<Hint role="status">Saving setup position…</Hint>{/if}
      {#if error || checkError}<Hint tone="error" role="alert">{error || checkError}</Hint><Button size="sm" onclick={refreshChecks}>Retry checks</Button>{/if}
      {#if step === 0}
        <SectionTitle>First, a home for your library.</SectionTitle>
        <Hint>Keep the current library, or choose the folder that already contains your items and notes after a reinstall.</Hint>
        {#if v}<Status on>Local library available</Status><Hint>{v.data_dir}</Hint>{:else}<Hint>Checking the current library…</Hint>{/if}
        {#if nextDir}
          <Status role="status">Opens after a restart: {nextDir}</Status>
          <Hint>{v?.next_items || v?.next_notes ? `It already holds ${(v?.next_items ?? 0).toLocaleString()} items and ${(v?.next_notes ?? 0).toLocaleString()} notes.` : 'No items or notes found in it yet.'}</Hint>
          {#if v?.can_quit}<div class="setup-actions"><Button variant="pri" disabled={restarting} onclick={restart}>{restarting ? 'Restarting…' : 'Restart now to open it'}</Button></div>{/if}
        {/if}
        {#if v && !v.frozen}<Hint>Running from source: the folder comes from CM_DATA_DIR.</Hint>{/if}
        {#if typing}<div class="setup-actions"><input class="inp" bind:value={typed} placeholder="A library folder: empty, or one with content_manager.db" aria-label="Library folder" autocomplete="off" spellcheck="false" /><Button variant="pri" size="sm" disabled={folderBusy || !typed.trim()} onclick={() => useFolder(typed.trim())}>Use it</Button><Button size="sm" disabled={folderBusy} onclick={() => { typing = false; typed = '' }}>Cancel</Button></div>{/if}
        {#if !tasks[2].done}
          <SectionTitle>Already backed up to Google Drive?</SectionTitle>
          <Hint>{cloud?.signed_in ? `Google Drive is connected${cloud.account ? ` as ${cloud.account}` : ''}. Restore your library from it before adding anything new.` : 'Connect the Google account you used before to find your library and restore it. Nothing is uploaded or changed until you choose.'}</Hint>
          <div class="setup-actions"><Button variant="pri" disabled={cloudBusy || cloudMoving || (!!cloud && !cloud.signed_in && !cloud.configured)} onclick={restoreFromDrive}>{cloud?.signed_in ? 'Restore from Google Drive' : cloudBusy ? 'Connecting…' : 'Connect Google Drive'}</Button></div>
          {#if cloudError}<Hint tone="error" role="alert">{cloudError}</Hint>{/if}
        {/if}
        <div class="setup-actions">{#if !typing && v?.frozen}<Button disabled={folderBusy} onclick={chooseFolder}>{folderBusy ? 'Checking the folder…' : 'Choose an existing folder…'}</Button>{/if}{#if tasks[2].done}<Button size="sm" onclick={() => visit(4)}>Restore a library from Drive…</Button>{/if}</div>
        <Hint>The active library stays in place unless you explicitly select a replacement. A selected folder loads after a full quit and restart.</Hint>
      {:else if step === 1}
        <Hint>Browser helpers import saved posts. Video tools add downloads, analysis and transcription. Install or update only the tools you need, then check local readiness below.</Hint>
        <OptionalSetup />
      {:else if step === 2}
        {#if !tasks[2].done}
          <Status role="status">Starting over on a new PC? Restore your library from Google Drive instead of importing again.</Status>
          <div class="setup-actions"><Button size="sm" onclick={restoreFromDrive}>{cloud?.signed_in ? 'Restore from Google Drive' : 'Connect Google Drive'}</Button></div>
          {#if cloudError}<Hint tone="error" role="alert">{cloudError}</Hint>{/if}
        {/if}
        <Hint>Choose a source, review what it needs, then bring in your first content.</Hint>
        <div class="source-options">
          {#each ANSWERS as answer (answer.id)}
            <Button class="source-button" data-source={answer.id} style={`--source-bg: ${SRC_COLOR[answer.id] ?? '#fff'}`} size="sm" aria-pressed={onb.answer === answer.id} onclick={() => choose(answer.id)}>
              {#if answer.id === 'links' || answer.id === 'files'}
                <svg class="source-icon" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d={pxPath(IC[answer.id === 'links' ? 'link' : 'folder'])} /></svg>
              {:else}<span class="source-logo" aria-hidden="true" style:background={SRC_MARK[answer.id][1]}>{@html SRC_MARK[answer.id][0]}</span>{/if}
              {answer.label}
              {#if onb.answer === answer.id}<span class="source-selected" aria-hidden="true"><svg viewBox="0 0 8 8"><path fill="currentColor" d={pxPath(IC.check)} /></svg></span>{/if}
            </Button>
          {/each}
        </div>
        <SectionTitle>{source.task}</SectionTitle>
        {#if source.site && source.site !== 'youtube'}
          <Hint>{onb.browser ? 'Browser helper ready. Sign in to the site in its separate browser window when asked.' : 'The browser helper is not ready. Review Tools first, or use the manual browser script in the import guide.'}</Hint>
          {#if !onb.browser}<Button size="sm" onclick={() => visit(1)}>Review browser requirements</Button>{/if}
        {:else if source.site === 'youtube'}<Hint>The playlist browser script does not require optional tools. Private playlists require signing in on the site. Video downloads need the tools in step 2.</Hint>
        {:else}<Hint>Links, notes and supported files work without tools, AI keys, Google or a license.</Hint>{/if}
        <div class="setup-actions"><Button variant="pri" onclick={() => runStart()}>{source.site && !onb.browser && source.site !== 'youtube' ? 'Open manual import guide' : source.key}</Button>{#if onb.answer !== 'files'}<Button onclick={openImport}>Import CSV or Brainamon JSON</Button>{/if}</div>
        <details><summary>Private posts and download access</summary><ImportSetup section="sessions" /></details>
        <Status on={tasks[2].done} role="status">{tasks[2].done ? (v?.items || onb.items || lib.rows.length || onb.notes ? 'First content saved' : 'Your selected library already has content. Restart to open it.') : 'Nothing saved yet. Return here after adding content.'}</Status>
      {:else if step === 3}
        <Hint>Use your own AI account for Wiskit answers, descriptions and summaries. Provider charges are separate from Brainamon.</Hint>
        <SetupAI />
        <details><summary>More AI options</summary><Hint>Manage other provider keys, embeddings and advanced model options.</Hint><Button size="sm" onclick={() => openSettings('keys')}>Advanced AI settings</Button></details>
      {:else if step === 4}
        <Hint>Connect Google, enable passphrase recovery if wanted, then choose whether to upload. Recovery protects the key; only successful uploads protect the latest content.</Hint>
        <Status on={!!cloud?.signed_in}>{cloud?.signed_in ? `Google Drive connected${cloud.account ? `: ${cloud.account}` : ''}` : 'Google Drive not connected'}</Status>
        {#if cloud}
          {#if !cloud.signed_in || cloud.state === 'signing-in'}<div class="setup-actions">
            {#if cloud.state === 'signing-in'}<Button disabled={cloudBusy} onclick={() => cloudAction('/api/cloud/cancel-sign-in')}>Cancel sign-in</Button>
            {:else if !cloud.signed_in}<Button variant="pri" disabled={cloudBusy || cloudMoving || !cloud.configured} onclick={() => cloudAction('/api/cloud/recovery/sign-in')}>Connect Google Drive</Button>{/if}
          </div>{/if}
          {#if !cloud.configured && !cloud.signed_in}<Hint>Google sign-in is not set up in this build.</Hint>{/if}
          <div id="setup-uploads" tabindex="-1" class="upload-controls">
            <SectionTitle>Library uploads</SectionTitle>
            <Status on={cloud.running}>{cloud.running ? 'Automatic uploads on' : 'Library uploads off'}</Status>
            <Hint>{cloud.last_publish ? `Last successful upload: ${new Date(cloud.last_publish).toLocaleString()}.` : 'No successful library upload yet.'}</Hint>
            <Hint>Encrypted library content uploads to your Google Drive account. Google can see account, connection and file size/timing metadata. Connecting alone leaves uploads off.</Hint>
            {#if cloud.state === 'publishing' || cloud.state === 'starting'}<Progress label="Google Drive upload" pct={cloud.total ? cloud.done * 100 / cloud.total : undefined} />{/if}
            <div class="setup-actions">
              {#if cloud.running}<Button disabled={cloudBusy || cloudMoving || cloud.state === 'publishing' || recovery?.restored} onclick={() => cloudAction('/api/cloud/publish')}>Upload now</Button>
              {:else}<Button variant="pri" disabled={cloudBusy || cloudMoving || !cloud.signed_in || recovery?.restored} onclick={() => cloudAction('/api/cloud/connect')}>Turn on uploads</Button>{/if}
              {#if cloud.running || cloud.vault_running}<Button disabled={cloudBusy || cloudMoving} onclick={() => cloudAction('/api/cloud/stop')}>Pause uploads and vault sync</Button>{/if}
            </div>
          </div>
          <div class="upload-controls" id="setup-recovery">
            <SectionTitle>Recovery</SectionTitle>
            <Status on={!!recovery?.enrolled}>{!recovery ? 'Checking recovery…' : recovery.enrolled ? 'Recovery passphrase set' : 'No recovery passphrase yet'}</Status>
            <Hint>Choose and check your recovery passphrase and file in Settings, on the Backup &amp; phones page. Recovery protects the key; only successful uploads protect the latest content.</Hint>
            <div class="setup-actions"><Button size="sm" disabled={!cloud.signed_in} aria-describedby={cloud.signed_in ? undefined : 'setup-recovery-why'} onclick={() => openSettings('backup', 'set-s-sync-recovery')}>Recovery in Backup &amp; phones</Button></div>
            {#if !cloud.signed_in}<Hint id="setup-recovery-why">Available once Google Drive is connected.</Hint>{/if}
          </div>
          {#if cloud.error}<Hint tone="error" role="alert">{cloud.error}</Hint>{/if}
        {/if}
        <Button size="sm" onclick={() => openSettings('backup', 'set-s-sync-account')}>Advanced cloud settings</Button>
      {:else if step === 5}
        <Hint>Scan the pairing code, connect the same Google account on the phone, then check PC access and load the library. Pairing and sync are free; the PC renews signed access while it is running.</Hint>
        <Status on={!!v?.phone_seen}>{v?.phone_seen ? 'A phone has synced changes with this library.' : 'Finish setup on your phone. Showing a QR does not confirm a connection.'}</Status>
        <Hint>After scanning, the phone guides each remaining step. Keep Google connection, PC access confirmation and library upload status separate.</Hint>
        {#if cloud}
          {#each cloud.phone_keys ?? [] as key (key)}<label class="phone-key"><input type="checkbox" bind:group={pairKeys} value={key} disabled={cloudBusy || !!pairing} />Give the phone my {keyName[key] ?? key} key</label>{/each}
          <Hint>Selected AI keys transfer encrypted through Drive for collection within 30 minutes. They are not in the QR. The QR itself unlocks your library; show it only to your own phone.</Hint>
          {#if pairing}
            <div class="pairing">
              <div class="pairing-qr" role="img" aria-label="Phone pairing QR code">{@html pairing.svg}</div>
              <div><Hint>Scan in Brainamon on your phone: More &gt; Pair with your PC &gt; Scan (a phone already set up: More &gt; Backup &amp; phones &gt; This phone). Code check: {pairing.fingerprint}.</Hint><div class="setup-actions"><Button size="sm" onclick={copyPair}>Copy pairing link</Button><Button size="sm" onclick={() => { pairing = null; pairMessage = '' }}>Hide the QR code</Button></div></div>
            </div>
          {:else}<Button variant="pri" disabled={cloudBusy || !cloud.licensed || cloud.rotation === 'pending'} onclick={showPair}>{cloudBusy ? 'Making the code…' : 'Show pairing QR'}</Button>{/if}
          {#if !cloud.licensed}<Hint>Update Brainamon on this PC for payment-free phone pairing, then retry.</Hint>{/if}
          {#if cloud.rotation === 'pending'}<Hint>Finish phone revocation in cloud settings before pairing again.</Hint>{/if}
        {/if}
        {#if pairMessage}<Hint role="status">{pairMessage}</Hint>{/if}
        <details><summary>Optional support and older receipts</summary><LicenseSettings idPrefix="setup-" /></details>
        <Button size="sm" onclick={() => openSettings('backup', 'set-s-sync-pair')}>Advanced phone settings</Button>
      {:else}
        <Hint>Your local library is available. Skipped and unfinished steps stay visible.</Hint>
        <ul class="setup-summary">{#each tasks as task, i (task.id)}<li><b>{i + 1}. {titles[i]}</b><span>{task.done ? 'Ready' : onb.skipped.includes(SETUP_STEPS[i]) ? 'Skipped' : 'Not finished'}</span><Button size="sm" onclick={() => visit(i)}>{task.done ? 'Review' : 'Resume'}</Button></li>{/each}</ul>
        <Button variant="pri" onclick={finish}>Open my library</Button>
      {/if}
      {#if (step === 4 || step === 5) && cloudError}<Hint tone="error" role="alert">{cloudError}</Hint>{/if}
    </section>
  </div>
</WinBody>
<WinFoot class="setup-surface">
  {#snippet start()}<small>Links and notes work right away.</small>{/snippet}
  {#if step > 0}<Button size="sm" onclick={() => visit(step - 1)}>Back</Button>{/if}
  {#if step < 6}<Button size="sm" onclick={() => next(true)}>Skip this step</Button><InfoTip label="If you skip this step" text={consequence[step]} /><Button variant="pri" onclick={() => next()}>{step === 5 ? 'Review setup' : 'Continue'}</Button>{/if}
  <Button size="sm" onclick={finish}>Do this later</Button>
</WinFoot>

<style>
  .setup-layout { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 28px; height: 100%; min-height: 0 }
  aside { display: grid; align-content: start; gap: 14px; padding-right: 22px; border-right: 1px solid var(--hair); overflow-y: auto }
  h2 { margin: 0; font: 700 22px/1.2 var(--display); text-wrap: balance }
  aside h2 { font-size: 24px }
  nav { display: grid; gap: 4px }
  nav button { display: flex; gap: 10px; align-items: center; padding: 12px 6px; border: 0; border-radius: 5px; background: none; color: var(--rw-ink); text-align: left; cursor: pointer }
  nav button:hover { background: var(--rw-2) }
  nav button.current { background: var(--rw-ink); color: var(--rw) }
  nav button.current small { color: inherit }
  nav button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
  nav b { display: block; font: 600 12px/1.3 var(--display) }
  nav small { display: block; margin-top: 4px; font: var(--type-small); color: var(--rw-dim) }
  nav :global(.step-mark) { width: 22px; height: 22px; font-size: 11px }
  nav :global(.step-mark.on::after) { width: 4px; height: 9px }
  section { min-width: 0; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; align-items: flex-start; gap: 16px; padding-right: 6px; scrollbar-gutter: stable }
  section > :global(*) { flex-shrink: 0 }
  section > h2 { width: 100%; padding-bottom: 16px; border-bottom: 1px solid var(--hair) }
  section :global(.setup-actions) { margin: 0; flex-wrap: wrap; justify-content: flex-start }
  section :global(.setup-actions > .inp) { flex: 1 1 240px; min-width: 0 }
  .upload-controls { display: grid; gap: 12px; width: 100% }
  .upload-controls :global(.fsec) { margin: 0 }
  .phone-key { display: flex; align-items: center; gap: 8px; font: var(--type-option) }
  .pairing { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; width: 100% }
  .pairing > div:last-child { flex: 1 1 180px }
  .pairing-qr { width: 200px; max-width: 100%; padding: 10px; background: white }
  .pairing-qr :global(svg) { display: block; width: 100%; height: auto }
  section > :global(.fsec) { margin: 8px 0 0 }
  .source-options { display: flex; gap: 12px; flex-wrap: wrap; padding: 4px }
  .source-options :global(.wkey.source-button) { position: relative; display: inline-flex; align-items: center; gap: 8px; min-height: 40px; max-width: 100%; padding: 7px 10px; background: var(--source-bg, #fff); color: var(--source-ink, #000) }
  .source-options :global(.source-button:hover:not(:disabled)) { filter: brightness(1.05) }
  .source-options :global(.source-button[aria-pressed=true]) { outline: 2px solid var(--rw-ink); outline-offset: 3px }
  .source-options :global(.source-button:focus-visible) { outline: 3px dashed var(--rw-ink); outline-offset: 3px }
  .source-icon, .source-logo { width: 18px; height: 18px; flex: none }
  .source-icon { shape-rendering: crispEdges }
  .source-logo { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 5px; color: #fff; font: 900 18px/1 Arial, sans-serif }
  .source-selected { position: absolute; top: -8px; right: -6px; display: grid; place-items: center; width: 18px; height: 18px; border: 2px solid var(--rw); border-radius: 50%; background: var(--rw-ink); color: var(--rw); pointer-events: none }
  .source-selected svg { width: 10px; height: 10px; shape-rendering: crispEdges }
  @media (pointer: coarse) { .source-options :global(.wkey.source-button) { min-height: 44px } }
  details { width: 100%; font: var(--type-option) }
  summary { cursor: pointer; margin-bottom: 10px }
  .setup-summary { width: 100%; list-style: none; padding: 0; margin: 0 }
  .setup-summary li { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--hair); font: var(--type-option) }
  .setup-summary li b { flex: 1 }
  @media (max-width: 700px) {
    .setup-layout { display: block; height: auto }
    aside { padding: 0 0 18px; margin-bottom: 22px; border-right: 0; border-bottom: 1px solid var(--hair) }
    aside h2, aside > :global(.hint) { display: none }
    nav { grid-template-columns: repeat(2, minmax(0, 1fr)) }
    nav button { min-width: 0 }
    nav small { overflow-wrap: anywhere }
    section { overflow: visible; padding-right: 0; scrollbar-gutter: auto }
    section h2 { font-size: 20px }
  }
</style>
