<script lang="ts">
  // The Recovery group of More > Backup & phones for the phone without a PC (docs/superpowers/plans/
  // 2026-10-31-phone-backup-phones.md, sub-plan 05): what protects this phone's key (a passphrase, a recovery file,
  // whether the file was checked), the one next step, the passphrase form, the original recovery code and the way to
  // Recover a library… (screens/Recover.svelte, #/recover). The state it shares with the status keys is in
  // recovery.svelte.ts; a key is left out while the Status above offers the same one.
  import { onMount } from 'svelte'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MDisclosure from './ui/MDisclosure.svelte'
  import MHint from './ui/MHint.svelte'
  import MRow from './ui/MRow.svelte'
  import MStatus from './ui/MStatus.svelte'
  import MTextButton from './ui/MTextButton.svelte'
  import { generateRecoveryPassphrase } from '../lib/recovery'
  import { token } from './mirror/pairing'
  import { day, type ActionId } from './mirror/phone-state'
  import { preparePhoneRecovery } from './mirror/phone-recovery'
  import { recoveryFact } from './mirror/recovery-fact'
  import { checkFile, rec, recoveryRun, saveFile } from './recovery.svelte'
  import { mirrorSource, phone, phoneStatus } from './state.svelte'

  let { working }: { working: boolean } = $props()
  const m = mirrorSource
  const st = $derived(phoneStatus())
  const above = (id: ActionId) => st?.action?.id === id
  // token() and the pairing are not reactive: read them again when a token comes or goes (phone.tokenAt), Google
  // refuses it, or a recovery action ends (phone.recoveryAt)
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  const fact = $derived((phone.recoveryAt, phone.tokenAt, m ? recoveryFact(m.pair) : 'none'))
  const setup = $derived((phone.recoveryAt, m?.pair.recovery))
  const set = $derived(fact !== 'none' && setup ? day(setup.kit.record.header.created * 1000) : '')
  const savedAt = $derived(setup?.saved ? ` ${day(setup.saved)}` : '')
  const available = $derived(signedIn && !!m && !rec.busy && !working)

  let password = $state(''), confirmation = $state(''), showPassword = $state(false)
  function clearSecrets() { password = ''; confirmation = ''; showPassword = false }
  function open(mode: '' | 'setup') { rec.mode = mode; rec.error = ''; rec.message = ''; clearSecrets() }
  // leaving the screen closes the form and forgets what it said; the passphrase never outlives it
  onMount(() => () => { rec.mode = ''; rec.message = ''; rec.error = ''; clearSecrets() })
  async function prepare() {
    try {
      await preparePhoneRecovery(m!.pair, m!.drive, password, confirmation)
      rec.mode = ''; rec.message = 'Passphrase set and checked against your backup. Now save the recovery file.'
    } finally { clearSecrets() }
  }
  // the original recovery code (the 43-character library key)
  let showCode = $state(false), codeNote = $state('')
  async function copyCode() {
    try { await navigator.clipboard.writeText(m?.pair.k ?? ''); codeNote = 'Copied. Keep it somewhere safe, not in Google Drive.' } catch { codeNote = 'Copy it by hand.' }
  }
</script>

<MBox id="m-recovery">
  <h3>Recovery</h3>
  {#if fact === 'prepared'}
    <MStatus tone="done" text="Passphrase set {set}" detail="Recommended: also save a recovery file, in case you forget the passphrase." />
  {:else if fact === 'saved'}
    <MStatus tone="next" text="Recovery file saved{savedAt}, not checked" detail="Open it once so you know it unlocks your backup." />
  {:else if fact === 'checked'}
    <MStatus tone="done" text="Passphrase set {set} · recovery file checked" detail="Keep the file outside this phone." />
  {:else}
    <MStatus tone={signedIn ? 'next' : 'todo'} text="Not set up" detail={signedIn ? 'If this phone is lost, your passphrase or a recovery file unlocks the backup on a new phone.' : 'Available once this phone backs up to Google Drive.'} />
  {/if}
  {#if !rec.mode && (fact !== 'none' || (signedIn && !above('set-up-recovery')))}
    <div class="m-row" style="flex-wrap:wrap">
      {#if fact === 'none'}
        <MButton variant="pri" size="sm" disabled={!available} onclick={() => open('setup')}>Set up recovery</MButton>
      {:else if fact === 'prepared'}
        <MButton variant="pri" size="sm" disabled={rec.busy} onclick={() => saveFile()}>Save recovery file…</MButton>
        <MTextButton disabled={!available} onclick={() => open('setup')}>Set up recovery again</MTextButton>
      {:else if fact === 'saved'}
        {#if !above('check-file')}<MButton variant="pri" size="sm" disabled={!available} onclick={() => checkFile()}>Check recovery file…</MButton>{/if}
        <MTextButton disabled={rec.busy} onclick={() => saveFile()}>Save another copy…</MTextButton>
      {:else}
        <MTextButton disabled={rec.busy} onclick={() => saveFile()}>Save another copy…</MTextButton>
        <MTextButton disabled={!available} onclick={() => open('setup')}>Set up recovery again</MTextButton>
      {/if}
    </div>
  {/if}
  {#if rec.mode === 'setup'}
    <label class="m-fld"><span>Recovery passphrase</span><input id="phone-recovery-password" type={showPassword ? 'text' : 'password'} bind:value={password} minlength="12" maxlength="1024" autocomplete="new-password" spellcheck="false" disabled={!available} aria-describedby="phone-recovery-help" /></label>
    <div class="m-row" style="flex-wrap:wrap">
      <MButton size="sm" disabled={!available} onclick={() => { password = generateRecoveryPassphrase(); confirmation = password; showPassword = true }}>Generate passphrase</MButton>
      <MButton size="sm" disabled={!available || !password} aria-controls="phone-recovery-password" aria-pressed={showPassword} onclick={() => showPassword = !showPassword}>{showPassword ? 'Hide passphrase' : 'Show passphrase'}</MButton>
    </div>
    <MHint id="phone-recovery-help">Generate a random passphrase, or enter at least 12 characters. Generation fills both fields. Write the passphrase down outside this phone, separately from your recovery file. It protects your existing key; it does not replace a lost key.</MHint>
    <label class="m-fld"><span>Confirm passphrase</span><input type="password" bind:value={confirmation} maxlength="1024" autocomplete="new-password" disabled={!available} /></label>
    <div class="m-row" style="flex-wrap:wrap">
      <MButton variant="pri" size="sm" disabled={!available || password.length < 12 || password !== confirmation} onclick={() => recoveryRun(prepare)}>Save passphrase</MButton>
      <MTextButton disabled={rec.busy} onclick={() => open('')}>Cancel</MTextButton>
    </div>
  {/if}
  {#if working}<MHint>Wait for the current sync or connection to finish before changing recovery.</MHint>{/if}
  {#if rec.busy}<MHint role="status">Checking recovery… This may take a few seconds.</MHint>{/if}
  {#if rec.message}<MHint role="status">{rec.message}</MHint>{/if}
  {#if rec.error}<MHint tone="error" role="alert">{rec.error}</MHint>{/if}
  {#if m && !rec.mode}
    <MRow title="Restore from Google Drive" desc="A phone backup, unlocked with its passphrase, recovery file or original code"><MButton as="a" size="sm" href="#/recover">Recover a library…</MButton></MRow>
    <MDisclosure summary="Original recovery code">
      <MRow title="Original recovery code" desc="Your 43-character library key still works, with or without a passphrase and recovery file. Key {m.pair.f}{m.pair.d ? ' · development Drive' : ''}"><MTextButton onclick={() => (showCode = !showCode)}>{showCode ? 'Hide' : 'Show'}</MTextButton></MRow>
      {#if showCode}
        <MRow desc={codeNote || 'Restore with this code and the same Google account. It still unlocks this backup after setting up a passphrase. Keep it private and outside this phone.'}>{#snippet title()}<span style="font-family:var(--mono, monospace);word-break:break-all;font-size:12px">{m.pair.k}</span>{/snippet}<MButton size="sm" onclick={copyCode}>Copy</MButton></MRow>
      {/if}
    </MDisclosure>
  {/if}
  <MDisclosure summary="How recovery works">
    <MHint>Recovery uses the same Google account as the backup. Your recovery file unlocks the backup; it does not contain the backup. Keep it outside this phone, separately from your passphrase. Earlier recovery files, passphrases and original codes still unlock this phone backup.</MHint>
    <MHint>Check recovery file… opens the file you saved and checks it against the setup in Google Drive; nothing is uploaded.</MHint>
  </MDisclosure>
</MBox>
