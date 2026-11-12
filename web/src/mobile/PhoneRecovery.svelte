<script lang="ts">
  import { phoneWords, phoneLocale } from './settings-words'
  import { t } from '../lib/i18n/index.ts'
  // The Recovery group of Settings > Backup & phones for the phone without a PC (docs/superpowers/plans/
  // 2026-10-31-phone-backup-phones.md, sub-plan 05; a group row since projects/phone-settings, ui/MGroup.svelte):
  // the row says what protects this phone's key (settings-lines.ts recoveryLine), the open group the one next step,
  // the passphrase form, the original recovery code and the way to Recover a library… (screens/Recover.svelte,
  // #/recover). The state it shares with the status keys is in recovery.svelte.ts; a key is left out while the Status
  // above offers the same one, and a key here is orange only while the Status offers none.
  import ForgotPassphrase from '../components/ForgotPassphrase.svelte'
  import { onMount, tick } from 'svelte'
  import MButton from './ui/MButton.svelte'
  import MDisclosure from './ui/MDisclosure.svelte'
  import MCard from './ui/MCard.svelte'
  import MSteps from './ui/MSteps.svelte'
  import MRunBar from './ui/MRunBar.svelte'
  import { backup } from './backup.svelte'
  import { recoverySteps, toneKind } from './settings-steps'
  import './tools.css'
  import MHint from './ui/MHint.svelte'
  import MInfo from './ui/MInfo.svelte'
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
  import { recoveryLine, recoveryTone } from './settings-lines'
  import { languageWorkChanged, registerLanguageCheck } from './language-switch.ts'

  let { working }: { working: boolean } = $props()
  const m = mirrorSource
  const st = $derived(phoneStatus())
  const above = (id: ActionId) => st?.action?.id === id
  const lead = $derived(!st?.action)
  // token() and the pairing are not reactive: read them again when a token comes or goes (phone.tokenAt), Google
  // refuses it, or a recovery action ends (phone.recoveryAt)
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  const fact = $derived((phone.recoveryAt, phone.tokenAt, m ? recoveryFact(m.pair) : 'none'))
  const setup = $derived((phone.recoveryAt, m?.pair.recovery))
  const set = $derived(fact !== 'none' && setup ? day(setup.kit.record.header.created * 1000, phoneLocale()) : '')
  const savedAt = $derived(setup?.saved ? ` ${day(setup.saved, phoneLocale())}` : '')
  const gated = $derived(!!backup.task || backup.busy)
  const available = $derived(signedIn && !!m && !rec.busy && !working && !gated)
  const waitReason = $derived(gated ? t('shared.native.backup.saved-task') : rec.busy ? rec.activity : phone.connecting
    ? t('recovery.warning.connecting')
    : working ? t('recovery.warning.syncing')
    : !signedIn ? t('recovery.warning.connectSetup') : '')

  let password = $state(''), confirmation = $state(''), showPassword = $state(false)
  function clearSecrets() { password = ''; confirmation = ''; showPassword = false }
  function open(mode: '' | 'setup') { rec.mode = mode; rec.error = ''; rec.message = ''; clearSecrets() }
  async function guidePassphrase() { open('setup'); await tick(); document.getElementById('phone-recovery-password')?.focus() }
  async function guideCode() { open(''); showCode = true; await tick(); document.getElementById('phone-original-code')?.focus() }
  // leaving the screen closes the form and forgets what it said; the passphrase never outlives it
  onMount(() => {
    const release = registerLanguageCheck(() => password || confirmation ? 'settings.language.unsavedRecovery' : null)
    return () => { rec.mode = ''; rec.message = ''; rec.error = ''; clearSecrets(); release() }
  })
  async function prepare() {
    try {
      await preparePhoneRecovery(m!.pair, m!.drive, password, confirmation)
      rec.mode = ''; rec.message = t('recovery.state.prepared')
    } finally { clearSecrets() }
  }
  // the original recovery code (the 43-character library key)
  let showCode = $state(false), codeNote = $state('')
  async function copyCode() {
    try { await navigator.clipboard.writeText(m?.pair.k ?? ''); codeNote = t('recovery.state.copied') } catch { codeNote = t('recovery.state.copyManually') }
  }
</script>

<MCard title={t('recovery.group.title')} id="m-recovery" line={recoveryLine(true, fact, phoneWords)} kind={toneKind(recoveryTone(st, true, fact, signedIn))} infoTitle={t('recovery.help.title')}>
  {#snippet info()}
    <p>{t('recovery.help.soloMaterial')}</p>
    <p>{t('recovery.help.check')}</p>
    <p>{t('recovery.help.restore')}</p>
  {/snippet}

  <MSteps steps={recoverySteps(fact, set, phoneWords, savedAt)} />
  {#if rec.busy}<MRunBar lead={rec.activity} right="" total={1} done={0} run label={t('recovery.group.title')} />{/if}
  {#if !rec.mode && (fact !== 'none' || (signedIn && !above('set-up-recovery')))}
    <div class="m-row" style="flex-wrap:wrap">
      {#if fact === 'none'}
        <MButton variant={lead ? 'pri' : 'default'} size="sm" disabled={!available} aria-describedby={waitReason ? 'phone-recovery-wait' : undefined} onclick={() => open('setup')}>{t('backup.action.recovery')}</MButton>
      {:else if fact === 'prepared'}
        <MButton variant={lead ? 'pri' : 'default'} size="sm" disabled={gated || rec.busy} onclick={() => saveFile()}>{t('recovery.action.saveFile')}</MButton>
        <MTextButton disabled={!available} aria-describedby={waitReason ? 'phone-recovery-wait' : undefined} onclick={() => open('setup')}>{t('recovery.action.anotherPassphrase')}</MTextButton>
      {:else if fact === 'saved'}
        {#if !above('check-file')}<MButton variant={lead ? 'pri' : 'default'} size="sm" disabled={!available} aria-describedby={waitReason ? 'phone-recovery-wait' : undefined} onclick={() => checkFile()}>{t('backup.action.checkFile')}</MButton>{/if}
        <MTextButton disabled={gated || rec.busy} onclick={() => saveFile()}>{t('recovery.action.saveCopy')}</MTextButton>
      {:else}
        <MTextButton disabled={gated || rec.busy} onclick={() => saveFile()}>{t('recovery.action.saveCopy')}</MTextButton>
        <MTextButton disabled={!available} aria-describedby={waitReason ? 'phone-recovery-wait' : undefined} onclick={() => open('setup')}>{t('recovery.action.anotherPassphrase')}</MTextButton>
      {/if}
    </div>
  {/if}
  {#if rec.mode === 'setup'}
    <label class="m-fld"><span>{t('recovery.method.passphraseLabel')}</span><input id="phone-recovery-password" type={showPassword ? 'text' : 'password'} bind:value={password} oninput={languageWorkChanged} minlength="12" maxlength="1024" autocomplete="new-password" spellcheck="false" disabled={!available} aria-describedby="phone-recovery-help" /></label>
    <div class="m-row" style="flex-wrap:wrap">
      <MButton size="sm" disabled={!available} onclick={() => { password = generateRecoveryPassphrase(); confirmation = password; showPassword = true; languageWorkChanged() }}>{t('recovery.action.generate')}</MButton>
      <MButton size="sm" disabled={!available || !password} aria-controls="phone-recovery-password" aria-pressed={showPassword} onclick={() => showPassword = !showPassword}>{showPassword ? t('recovery.action.hidePassphrase') : t('recovery.action.showPassphrase')}</MButton>
    </div>
    <div class="m-row"><MHint id="phone-recovery-help">{t('recovery.warning.length')}</MHint><MInfo title={t('recovery.method.passphraseLabel')}><p>{t('recovery.help.generate')}</p></MInfo></div>
    <label class="m-fld"><span>{t('recovery.method.confirm')}</span><input type="password" bind:value={confirmation} oninput={languageWorkChanged} maxlength="1024" autocomplete="new-password" disabled={!available} /></label>
    <div class="m-row" style="flex-wrap:wrap">
      <MButton variant="pri" size="sm" disabled={!available || password.length < 12 || password !== confirmation} aria-describedby={waitReason ? 'phone-recovery-wait' : 'phone-recovery-help'} onclick={() => recoveryRun(prepare, t('recovery.state.savingChecking'))}>{t('recovery.action.savePassphrase')}</MButton>
      <MTextButton disabled={rec.busy} onclick={() => open('')}>{t('common.cancel')}</MTextButton>
    </div>
  {/if}
  {#if waitReason}<MHint id="phone-recovery-wait" role="status">{waitReason}</MHint>{/if}
  {#if rec.message && !(fact === 'checked' && rec.message === t('recovery.state.fileChecked'))}<MHint role="status">{rec.message}</MHint>{/if}
  {#if rec.error}<MHint tone="error" role="alert">{rec.error}</MHint>{/if}
  {#if m && !rec.mode}
    <MRow wrap title={t('recovery.action.restoreDrive')}><MButton as="a" size="sm" href="#/recover">{t('recovery.action.recoverEllipsis')}</MButton></MRow>
  {/if}
  <MDisclosure foot summary={t('common.showMore')} less={t('common.showLess')}>
  <ForgotPassphrase mobile words={phoneWords} workingLabel={t('recovery.action.anotherPassphrase')} workingReason={waitReason}
    methodReason={gated ? waitReason : rec.busy ? rec.activity : ''}
    onworking={guidePassphrase} onfile={() => { location.hash = '#/recover/file' }} oncode={guideCode}
    onnone={() => { location.hash = '#/backup/manage' }} />
  {#if m && !rec.mode}
    <MDisclosure summary={t('recovery.method.original')} open={showCode} id="phone-original-code" tabindex={-1}>
      <MRow wrap title={t('recovery.method.original')} desc={t('recovery.warning.originalKey', { fingerprint: m.pair.f, development: m.pair.d ? t('backup.pair.development') : '' })}><MTextButton onclick={() => (showCode = !showCode)}>{showCode ? t('recovery.action.hide') : t('recovery.action.show')}</MTextButton></MRow>
      {#if showCode}
        <MRow wrap desc={codeNote || t('recovery.warning.original')}>{#snippet title()}<span style="font-family:var(--mono, monospace);word-break:break-all;font-size:12px">{m.pair.k}</span>{/snippet}<MButton size="sm" onclick={copyCode}>{t('recovery.action.copy')}</MButton></MRow>
      {/if}
    </MDisclosure>
  {/if}
  </MDisclosure>
</MCard>
