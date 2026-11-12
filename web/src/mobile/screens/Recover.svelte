<script lang="ts">
  import { phoneWords, phoneLocale, nativeError } from '../settings-words'
  import { t } from '../../lib/i18n/index.ts'
  // Recover a library… (#/recover, docs/superpowers/plans/2026-10-31-phone-backup-phones.md sub-plan 05): a phone backup
  // in Google Drive, unlocked with a recovery passphrase (the setups found in Drive, newest first), a recovery file or
  // the original code. Then Keep this phone's content (Reconnect, when this phone's latest backup is in Drive under
  // that key) or Restore on an empty phone. Nothing here writes Drive; what was typed or unlocked is forgotten when the
  // screen closes. A phone paired with a PC recovers its library on the PC. The page (projects/phone-settings, spec
  // section 4): the top keys with How recovery works, the kicker and title, the word tabs, the method, Forgot passphrase?
  import ForgotPassphrase from '../../components/ForgotPassphrase.svelte'
  import { onMount, tick } from 'svelte'
  import MBox from '../ui/MBox.svelte'
  import MCard from '../ui/MCard.svelte'
  import MRunBar from '../ui/MRunBar.svelte'
  import MPicker from '../ui/MPicker.svelte'
  import { backup } from '../backup.svelte'
  import '../tools.css'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'
  import PageKeys from '../PageKeys.svelte'
  import MRow from '../ui/MRow.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import { MirrorKey } from '../mirror/crypto'
  import { token } from '../mirror/pairing'
  import { clock } from '../mirror/phone-state'
  import { readPhoneKit, type PhoneKit } from '../mirror/recovery-envelope'
  import { discoverPhoneRecovery, recoveryAccount, restorePhoneKit, restorePhonePassphrase } from '../mirror/phone-recovery'
  import { eligibilityText, keyFromMaterial, KIT_IN_CODE, reconnectCheck, reconnectPhone, REFUSALS, type Eligibility } from '../mirror/phone-reconnect'
  import { recoveryFileText } from '../recovery.svelte'
  import { mirrorSource, phone, useWithoutPc } from '../state.svelte'
  import { cloudCheckpoint, cloudRevision } from '../mirror/gate'
  import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from '../language-switch.ts'
  import PhoneBackupChoices from '../PhoneBackupChoices.svelte'

  let { scroller }: { scroller?: HTMLElement } = $props()
  const m = mirrorSource
  // token() is not reactive: read it again when a token comes or goes (phone.tokenAt) or Google refuses it
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  const working = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing || phone.connecting)
  type Method = 'password' | 'kit' | 'code'
  let checking = $state(false)
  let busy = $state(false), error = $state(''), errorDisplay = $state(''), message = $state('')
  let password = $state(''), code = $state('')
  let method = $state<Method>(location.hash.endsWith('/file') ? 'kit' : m ? 'password' : 'code')
  let setups = $state<Awaited<ReturnType<typeof discoverPhoneRecovery>>>([]), selected = $state('')
  // the key a method unlocked, held in memory until Reconnect, Restore on an empty phone or Cancel; never stored
  let found = $state<{ key: string; account: string; kit?: PhoneKit; check: Eligibility } | null>(null)
  let sure = $state(false)      // Reconnect asks twice (the phone's two-tap confirmation, as Remove and Unpair)
  let alive = true, revision = cloudRevision()
  let choices = $state(false)
  function current() { cloudCheckpoint(revision); if (!alive) throw new Error('Recovery screen closed.') }
  const gated = $derived(!!backup.task || backup.busy)
  const available = $derived(signedIn && !!m && !busy && !working && !gated)
  $effect(() => { void signedIn; found = null; sure = false })     // a sign-in change makes a found key stale

  function clearSecrets() { password = ''; code = '' }
  function forget() { found = null; sure = false }
  function choose(next: string) { if (busy) return; method = next as Method; error = ''; message = ''; clearSecrets(); forget() }
  async function guideMethod(next: Method) {
    choose(next)
    await tick()
    document.getElementById('phone-unlock-method')?.focus()
  }
  // the screen opens at its top; leaving it forgets what was typed, unlocked or found
  onMount(() => {
    const release = registerLanguageCheck(() => password || code || found ? 'settings.language.unsavedRecovery' : null)
    scroller?.scrollTo(0, 0)
    return () => { alive = false; clearSecrets(); forget(); setups = []; release() }
  })
  async function run(action: () => Promise<void>) {
    if (busy) return
    const done = beginLanguageWork()
    revision = cloudRevision(); busy = true; error = ''; message = ''
    try { await action() }
    catch (e) { if (alive) { error = (e as Error).message; errorDisplay = nativeError('recovery', e) } }
    finally { busy = false; checking = false; done() }
  }
  async function discover() {
    await recoveryAccount(m!.pair, m!.drive)
    const found = await discoverPhoneRecovery(m!.drive)
    current(); setups = found
    selected = setups[0]?.id ?? ''
    if (!selected) message = t('recovery.state.noSetups')
  }
  // the method unlocks the key; nothing is restored yet. Then the read-only check says whether this phone can keep its content.
  async function find() {
    try {
      let key: string, account: string, kit: PhoneKit | undefined
      if (method === 'kit') {
        const text = await recoveryFileText()
        current()
        if (text === null) return
        kit = readPhoneKit(text)
        ;({ key, account } = await restorePhoneKit(m!.pair, m!.drive, text))
      } else if (method === 'password') {
        ;({ key, account } = await restorePhonePassphrase(m!.pair, m!.drive, selected, password))
      } else {
        key = await keyFromMaterial(code)
        account = signedIn && m ? await recoveryAccount(m.pair, m.drive) : ''
      }
      current(); checking = true
      const check: Eligibility = signedIn && m
        ? await reconnectCheck(await MirrorKey.fromText(key), m.drive, m.changes)
        : { ok: false, reason: 'not_connected', message: REFUSALS.not_connected }
      current(); found = { key, account, kit, check }; sure = false
    } finally { clearSecrets() }
  }
  async function reconnect() {
    if (!found || !m) return
    if (!sure) { sure = true; return }
    const f = found
    await reconnectPhone(m.pair, m.drive, m.changes, f.key, f.account, f.kit)
    forget()
    // a recovery file keeps recovery set up; otherwise Backup & phones offers Set up recovery right away (its Status key)
    try { sessionStorage.setItem('bp-note', f.kit ? t('recovery.state.reconnected') : t('recovery.state.reconnectedSetup')) } catch { /* the note is only a courtesy */ }
    location.replace(location.pathname + '#/backup'); location.reload()
  }
  async function restoreEmpty() {
    if (!found) return
    sure = false
    // keeps `found` on refusal: Reconnect stays one tap away
    if (!await useWithoutPc(found.key, found.account)) throw new Error(phone.note)
  }
</script>

<PageKeys infoTitle={t('recovery.help.title')}>
  {#snippet info()}
    <p>{t('recovery.help.find')}</p>
    <p>{t('recovery.help.material')}</p>
    <p>{t('recovery.help.readOnly')}</p>
    <p>{t('recovery.help.originalCode')}</p>
    <p>{t('recovery.help.methods')}</p>
    {#if !m}<p>{t('recovery.help.noPhone')}</p>
    {:else if !signedIn}<p>{t('recovery.help.noDrive')}</p>{/if}
  {/snippet}
</PageKeys>
<div class="m-pad m-calm m-page">
  <h1 class="m-page-title">{t('recovery.action.recover')}</h1>
  <MRunBar lead={t(found ? 'recovery.step.keep' : checking ? 'recovery.step.checkPhone' : 'recovery.step.unlock')} right={t('common.step', { n: found ? 3 : checking ? 2 : 1, total: 3 })} total={3} done={found ? 2 : checking ? 1 : 0} run={busy} label={t('recovery.action.recover')} />
  <MCard id="m-recover">
    <span class="m-recover-k">{t('recovery.method.backupTitle')}</span>
    <div id="phone-unlock-method" tabindex="-1" class="m-recover-tabs"><MSeg look="tabs" label={t('recovery.method.unlock')} options={[['password', t('recovery.method.passphrase')], ['kit', t('recovery.method.file')], ['code', t('recovery.method.code')]]} value={method} disabled={busy} onchange={choose} /></div>
    {#if !m}
      <MHint>{t('recovery.warning.start')}</MHint>
    {:else if !signedIn}
      <MHint>{t('recovery.warning.connect')}</MHint>
    {/if}
    {#if gated}<MHint>{t('recovery.warning.finishBeforeRestore')}</MHint>{/if}
    {#if working}<MHint>{t('recovery.warning.waitRestore')}</MHint>{/if}
    {#if !found}
      {#if method === 'password'}
        <MButton size="sm" disabled={!available} onclick={() => run(discover)}>{t('recovery.action.findSetups')}</MButton>
        {#if setups.length > 1}
          <MPicker label={t('recovery.method.setup')} bind:value={selected} disabled={!available} options={setups.map(setup => [setup.id, t('recovery.state.setupAt', { when: clock(setup.record.header.created * 1000, Date.now(), phoneLocale()) })])} />
        {:else if setups.length === 1}
          <MRow wrap title={t('recovery.method.setup')} desc={t('recovery.state.setupAt', { when: clock(setups[0].record.header.created * 1000, Date.now(), phoneLocale()) })} />
        {/if}
        {#if setups.length}
          <label class="m-fld"><span>{t('recovery.method.passphraseLabel')}</span><input type="password" bind:value={password} oninput={languageWorkChanged} maxlength="1024" autocomplete="off" disabled={!available} /></label>
          <div class="m-hero-key"><MButton shape="pill" variant="pri" disabled={!available || !selected || !password} onclick={() => run(find)}>{t('recovery.action.findBackup')}</MButton></div>
        {/if}
      {:else if method === 'kit'}
        <div class="m-hero-key"><MButton shape="pill" variant="pri" disabled={!available} onclick={() => run(find)}>{t('recovery.action.openFile')}</MButton></div>
      {:else}
        <label class="m-fld"><span>{t('recovery.method.original')}</span><input type="password" bind:value={code} oninput={languageWorkChanged} maxlength="32768" autocomplete="off" spellcheck="false" disabled={gated || busy || working} /></label>
        <div class="m-hero-key"><MButton shape="pill" variant="pri" disabled={gated || busy || working || !code.trim()} onclick={() => run(find)}>{t('recovery.action.findBackup')}</MButton></div>
      {/if}
    {:else}
      <MRow wrap id="phone-recovery-keep" title={t('recovery.action.keep')} desc={eligibilityText(found.check, phoneWords)} />
      {#if found.check.ok}
        <MHint>{sure ? t('recovery.warning.confirmReconnect') : t('recovery.warning.keep')}</MHint>
      {/if}
      <div class="m-hero-key">
        {#if found.check.ok}<MButton shape="pill" variant="pri" disabled={!available} onclick={() => run(reconnect)}>{sure ? t('recovery.action.confirmReconnect') : t('recovery.action.reconnect')}</MButton>{/if}
        <MButton shape="pill" variant={found.check.ok ? 'default' : 'pri'} disabled={gated || busy || working} onclick={() => run(restoreEmpty)}>{t('recovery.action.empty')}</MButton>
        <MTextButton disabled={busy} onclick={() => { forget(); error = ''; message = '' }}>{t('common.cancel')}</MTextButton>
      </div>
    {/if}
    {#if error === KIT_IN_CODE}<MButton size="sm" onclick={() => choose('kit')}>{t('recovery.action.useFile')}</MButton>{/if}
    {#if busy}<MHint role="status">{t('recovery.state.checking')}</MHint>{/if}
    {#if message}<MHint role="status">{message}</MHint>{/if}
    {#if error}<MHint tone="error" role="alert">{errorDisplay || error}</MHint>{/if}
    <!-- Forgot passphrase? under the form, the quiet disclosure it is (spec section 4.4) -->
    <ForgotPassphrase mobile words={phoneWords} workingLabel={t('recovery.action.settings')}
      workingReason={busy ? t('recovery.warning.waitCheck') : working ? t('recovery.warning.waitSync') : !m ? t('recovery.warning.workingDevice') : ''}
      methodReason={gated ? t('recovery.warning.finishBeforeRestore') : busy ? t('recovery.warning.waitCheck') : ''}
      onworking={() => { location.hash = '#/backup' }}
      onfile={() => guideMethod('kit')} oncode={() => guideMethod('code')}
      onnone={() => { forget(); clearSecrets(); choices = true }} />
  </MCard>
  {#if choices && m}<PhoneBackupChoices onclose={() => choices = false} />
  {:else if choices}<MBox><MHint>{t('recovery.warning.startConnect')}</MHint><MButton as="a" href="#/more">{t('recovery.action.openSettings')}</MButton></MBox>{/if}
</div>
