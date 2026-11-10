<script lang="ts">
  import { phoneWords, lampLabel, connectLabel, nativeError } from '../settings-words'
  import { fmtNum } from '../../lib/i18n/format.ts'
  import T from '../../lib/i18n/T.svelte'
  import { t } from '../../lib/i18n/index.ts'
  // Settings > Backup & phones (#/backup, docs/superpowers/plans/2026-10-31-phone-backup-phones.md P2; the hero and
  // the group rows since projects/phone-settings, spec section 3). A phone paired with a PC: the status (the
  // PhoneState with what it means and the library in Drive; the numbered guide under it while a new pairing is set
  // up), then the groups Google account, This phone and Recovery. The phone without a PC (sub-plan 05): the status
  // (with what is on this phone), Google account (its own backup), This phone (pairing with a PC, Remove) and Recovery
  // (PhoneRecovery.svelte, with Recover a library…, #/recover). One group opens at a time; a group's key is left out
  // while the status offers the same one, and is orange only while the status offers none.
  import ForgotPassphrase from '../../components/ForgotPassphrase.svelte'
  import { onMount } from 'svelte'
  import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from '../language-switch.ts'
  import { changes as changesDb, wipe } from '../store'
  import { changeAccount, connectDrive, driveStatus, fmtAgo, mirrorSource, pairFrom, parseRoute, phone, phoneStatus, refresh, solo, syncNow } from '../state.svelte'
  import { actionBusy, actionLabel, runPhoneAction } from '../actions'
  import { deviceName, isApp, secretsSaved } from '../native'
  import { forget as unpairPhone, token } from '../mirror/pairing'
  import { disconnectPhoneBackup, listPhoneBackups } from '../mirror/phone-backup'
  import { backup } from '../backup.svelte'
  import PhoneBackupChoices from '../PhoneBackupChoices.svelte'
  import { allowCloudWork, RECONNECT_BUSY, stopCloudWork } from '../mirror/gate'
  import { exportPhoneRecovery } from '../mirror/recovery'
  import { unpairEdits, unpairWarning } from '../mirror/phone-facts'
  import { ACCESS_STATES, type ActionId } from '../mirror/phone-state'
  import { network, setSyncPaused, syncPaused } from '../network.svelte'
  import { googleLine, googleTone, recoveryLine, recoveryTone, thisPhoneLine, thisPhoneTone } from '../settings-lines'
  import { setGroups } from '../ui/groups.svelte'
  import PageKeys from '../PageKeys.svelte'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MGroup from '../ui/MGroup.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'
  import MStatus from '../ui/MStatus.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import PhoneRecovery from '../PhoneRecovery.svelte'

  let { scroller }: { scroller?: HTMLElement } = $props()
  setGroups()
  const m = mirrorSource
  const st = $derived(phoneStatus())
  const above = (id: ActionId) => st?.action?.id === id
  const lead = $derived(!st?.action)
  // token() is not reactive: read it again when a token comes or goes (phone.tokenAt) or Google refuses it
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  const drive = $derived(driveStatus())
  const driveBusy = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing)
  // the source is not reactive: read its manifest again whenever a refresh lands
  const man = $derived((phone.synced, m?.manifest ?? null))
  let pairingGuide = $state(sessionStorage.getItem('bp-pair-setup') === '1')
  const pcAccess = $derived(phone.tried && signedIn && !network.licenseLocked && (phone.noLibrary || phone.reachable))
  function finishPairing() { sessionStorage.removeItem('bp-pair-setup'); pairingGuide = false; location.hash = '#/lib' }
  // the Google account row: the account in use (an account that is not the PC's is the one shown), else the lamp
  const account = $derived(phone.account?.check === 'mismatch' ? phone.account.got : m?.pair.g ?? '')
  const google = $derived(googleLine({ signedIn, account, driveOk: drive.ok, lamp: lampLabel(drive.lamp), solo }, phoneWords))

  let name = $state('')
  let backupFiles = $state<number | null>(null)
  onMount(() => { void deviceName().then(n => { name = n }) })
  onMount(() => {
    if (solo && signedIn && !backup.busy) void listPhoneBackups().then(backups => {
      backupFiles = backups.filter(b => b.current).reduce((n, b) => n + b.files, 0)
    }).catch(() => { /* keep the count unknown until Drive can be read */ })
  })
  // the screen opens at its top (the Library's line under the app bar comes from far down a list), and Back lands on
  // the top of Settings, where the status is, not where this screen was scrolled to. A teardown reads state as it
  // was (Svelte 5), so the next screen comes from the address.
  onMount(() => {
    scroller?.scrollTo(0, 0)
    return () => {
      const next = parseRoute(location.hash)
      if (next.tab === 'more' && !next.imp && !next.backup) scroller?.scrollTo(0, 0)
    }
  })

  let sending = $state(false), sendNote = $state('')
  async function sendNow() {
    if (!m) return
    sending = true; sendNote = ''
    try { await syncNow(); sendNote = phone.sync?.msg ?? '' } catch (e) { sendNote = nativeError('network', e) } finally { sending = false }
  }

  // Unpair (plan P10): the first tap says which edits never reach the PC; the journal stays on this phone
  let confirmUnpair = $state(false)
  const lost = $derived(unpairEdits(phone.pend, !!network.licenseKind))
  async function unpair() {
    if (!confirmUnpair) { confirmUnpair = true; return }
    const finishLanguageWork = beginLanguageWork()
    try {
      await stopCloudWork()
      await m?.dropPhoneRecord()                   // D13: off the PC's Phones list first (best effort, at most 3 s)
      allowCloudWork()
      unpairPhone()
      await secretsSaved()
      // Clear local copies only after protected storage confirmed removal of the connection.
      await wipe()
      navigator.serviceWorker?.controller?.postMessage({ type: 'clear' })
      location.replace(location.pathname + '#/more')
      location.reload()
    } catch (e) { phone.note = (e as Error).message === RECONNECT_BUSY ? RECONNECT_BUSY : t('backup.error.removeConnection') }
    finally { finishLanguageWork() }
  }

  let exportingRecovery = $state(false), recoveryNote = $state(''), showCode = $state(false)
  async function saveRecovery() {
    if (!m || exportingRecovery) return
    const finishLanguageWork = beginLanguageWork()
    exportingRecovery = true; recoveryNote = ''
    try { recoveryNote = await exportPhoneRecovery(m.pair, phoneWords) }
    catch (e) { recoveryNote = (e as Error).message === 'cancelled' ? '' : nativeError('recovery', e) }
    finally { exportingRecovery = false; finishLanguageWork() }
  }
  let pasted = $state('')
  onMount(() => registerLanguageCheck(() => pasted ? 'settings.language.unsavedPairing' : null))

  // without a PC (sub-plan 05): the source is not reactive, so read it again whenever a refresh lands
  const hasPcMirror = $derived((phone.synced, m?.pcMirror ?? false))
  async function disconnectBackup() {
    if (!m) return
    if (!confirmDisconnect) { confirmDisconnect = true; return }
    const finishLanguageWork = beginLanguageWork()
    disconnecting = true
    try { await disconnectPhoneBackup(); location.reload() }
    catch (e) { phone.note = nativeError('backup', e) }
    finally { disconnecting = false; finishLanguageWork() }
  }
  let confirmDisconnect = $state(false), disconnecting = $state(false)
  const manage = $derived((phone.route, location.hash.endsWith('/manage')))
  // Remove (two taps): the phone's library, its queued changes and its key leave this phone; independent copies stay
  let confirmRemove = $state(false)
  async function removeSolo() {
    if (backup.task || backup.busy) { phone.note = t('backup.warning.finishBeforeRemove'); return }
    if (!confirmRemove) { confirmRemove = true; return }
    const finishLanguageWork = beginLanguageWork()
    try {
      await stopCloudWork()
      allowCloudWork()
      unpairPhone()
      await secretsSaved()
      // Clear local copies only after protected storage confirmed removal of the connection.
      await Promise.all([wipe(), changesDb.clear()])
      navigator.serviceWorker?.controller?.postMessage({ type: 'clear' })
      location.replace(location.pathname + '#/more')
      location.reload()
    } catch (e) { phone.note = (e as Error).message === RECONNECT_BUSY ? RECONNECT_BUSY : t('backup.error.removeConnection') }
    finally { finishLanguageWork() }
  }
</script>

<!-- the Google account in use, and Change account (Google's account chooser; mirror/pairing.ts). An
     account that is not the PC's is not used: the row says so -->
{#snippet accountRow()}
  {#if m}
    {@const other = phone.account?.check === 'mismatch' ? phone.account.got : ''}
    <MRow title={t('backup.account.signedAs', { account: other || m.pair.g || t('backup.account.googleDefault') })} desc={other ? t('backup.account.pc', { account: m.pair.e }) : undefined}>{#if !above('change-account')}<MButton size="sm" onclick={changeAccount} disabled={phone.connecting}>{phone.connecting ? connectLabel(phone.connectStep) : t('backup.account.change')}</MButton>{/if}</MRow>
    {#if phone.connecting}<MHint>{phone.connectStep === 'Waiting for Google' ? t('backup.account.chooseSheet') : t('backup.account.checking')}</MHint>{/if}
  {/if}
{/snippet}

<!-- the pairing-link paste field, under a disclosure -->
{#snippet pasteLink()}
  <MDisclosure summary={t('settings.pair.paste')}>
    <MRow title={t('settings.pair.link')} desc={t('settings.pair.copyHint')}><MButton size="sm" onclick={() => pairFrom(pasted)} disabled={!pasted.includes('#pair=')}>{t('settings.pair.pair')}</MButton></MRow>
    <label class="m-fld"><input bind:value={pasted} oninput={languageWorkChanged} placeholder="https://…#pair=…" aria-label={t('settings.pair.link')} autocomplete="off" /></label>
  </MDisclosure>
{/snippet}

<!-- the PhoneState as the hero: its dot and "Status", the sentence, what it means and its one key, the pill (actions.ts) -->
{#snippet stateRow()}
  {#if st}
    <MStatus look="hero" kicker={t('backup.state.title')} tone={st.tone} text={st.text} detail={st.detail}>
      {#if st.action}{@const a = st.action}<MButton shape="pill" variant={a.primary ? 'pri' : 'default'} disabled={actionBusy(a.id)} onclick={() => runPhoneAction(a.id)}>{actionLabel(a)}</MButton>{/if}
    </MStatus>
  {/if}
{/snippet}

{#if m && !solo}
<PageKeys infoTitle={t('backup.group.sync')}>
  {#snippet info()}
    <p>{t('backup.help.sync')}</p>
    <p>{t('backup.help.metadata')}</p>
    <p>{t('backup.help.access')}</p>
  {/snippet}
</PageKeys>
<div class="m-pad m-calm m-page">
  <MBox id="m-backup-status">
    {@render stateRow()}
    {#if phone.note}<MHint role="status">{phone.note}</MHint>{/if}
    {#if st?.id === 'unreachable' && phone.error && !phone.refreshing}<MHint tone="error" role="alert">{phone.error}</MHint>{/if}
    <MRow id="m-library" title={t('backup.group.library')} desc={man ? t('backup.state.librarySummary', { items: fmtNum(man.items, 'en'), files: fmtNum(Object.keys(man.files).length, 'en'), ago: fmtAgo(man.published) }) : phone.refreshing ? t('backup.pair.loading') : t('backup.pair.nothingRead')} />
  </MBox>

  {#if pairingGuide || !phone.reachable}
    <MBox id="m-pair-setup">
      <h3>{t('backup.pair.finish')}</h3>
      <MRow title={t('backup.pair.step1')} desc={t('backup.pair.useAccount', { account: m.pair.e || t('backup.pair.pcAccount') })} />
      <MRow title={t('backup.pair.step2')} desc={signedIn ? t('backup.pair.connected', { account: m.pair.g || t('backup.pair.signedIn') }) : phone.connecting ? phone.connectStep : phone.account ? t('backup.pair.mismatch', { account: m.pair.e }) : t('backup.pair.connectAccount')} />
      <MRow role="status" title={t('backup.pair.step3')} desc={!signedIn ? t('backup.pair.afterConnect') : pcAccess ? t('backup.pair.confirmed') : phone.refreshing ? t('backup.pair.checking') : st && ACCESS_STATES.includes(st.id) ? st.text : t('backup.pair.waitConfirmation')} />
      <MRow title={t('backup.pair.step4')} desc={phone.reachable ? t('backup.pair.ready', { n: fmtNum(phone.rows.length, 'en') }) : phone.noLibraryWhy?.message || (pcAccess ? t('backup.pair.waitUpload') : t('backup.pair.waitLoad'))} />
      {#if signedIn && !phone.reachable && !above('retry') && !driveBusy}<MButton size="sm" disabled={phone.connecting || syncPaused()} onclick={() => refresh()}>{t('common.retry')}</MButton>{/if}
      {#if phone.reachable}<MButton variant={st?.action?.primary ? 'default' : 'pri'} onclick={finishPairing}>{t('backup.pair.done')}</MButton>{/if}
    </MBox>
  {/if}

  <MGroup title={t('backup.group.account')} id="m-conn" line={driveBusy && signedIn ? t('backup.account.syncing') : google} tone={googleTone(st, { signedIn, driveOk: drive.ok, busy: driveBusy })}>
    {#if phone.account || (signedIn && !phone.signIn)}{#if !m.pair.d}{@render accountRow()}{/if}{:else if !above('connect') && !above('sign-in-again')}
      <MRow title={t('backup.action.connectDrive')} desc={m.pair.c || isApp ? t('backup.account.choosePrompt', { choice: m.pair.e ? t('backup.account.choice', { account: m.pair.e }) : '' }) : t('backup.account.noApp')}><MButton variant={lead ? 'pri' : 'default'} size="sm" onclick={() => connectDrive()} disabled={phone.connecting || (!m.pair.c && !m.pair.d && !isApp)}>{phone.connecting ? connectLabel(phone.connectStep) : t('backup.account.connect')}</MButton></MRow>
    {/if}
  </MGroup>

  <MGroup title={t('backup.group.thisPhone')} id="m-phone" line={thisPhoneLine({ solo: false, name, unsent: phone.pend.unsent }, phoneWords)} tone={thisPhoneTone(st, phone.pend.unsent)} infoTitle={t('backup.help.connectionTitle')} onclose={() => { confirmUnpair = false }}>
    {#snippet info()}<p>{t('backup.help.device')}</p>{/snippet}
    <MRow title={name || t('backup.phone.thisPhone')} />
    <MRow title={t('backup.group.changes')} desc={t('backup.phone.changes', { unsent: phone.pend.unsent ? t('backup.state.unsent', { n: phone.pend.unsent }) : t('backup.state.allSent'), waiting: phone.pend.waiting ? t('backup.phone.waitingPc', { n: phone.pend.waiting }) : '', held: phone.pend.held ? t('backup.phone.heldCanvas', { n: phone.pend.held }) : '', error: m.lastError ? ` · ${m.lastError}` : '' })}>{#if !above('send')}<MButton size="sm" onclick={sendNow} disabled={sending || !phone.pend.unsent}>{sending ? t('backup.phone.sending') : t('backup.action.send')}</MButton>{/if}</MRow>
    {#if sendNote}<MHint>{sendNote}</MHint>{/if}
    <MRow id="m-pair" title={t('backup.pair.again')} desc={isApp ? t('backup.pair.scanAgain') : t('backup.pair.linkAgain')}>{#if isApp && !above('scan')}<MButton size="sm" onclick={() => pairFrom()}>{t('settings.pair.scan')}</MButton>{/if}</MRow>
    {@render pasteLink()}
    <MRow title={t('backup.pair.paired')} desc={t('backup.pair.keySummary', { fingerprint: m.pair.f, development: m.pair.d ? t('backup.pair.development') : '', keys: Object.keys(m.pair.ai || {}).length ? t('backup.pair.aiKeys', { providers: Object.keys(m.pair.ai).join(', ') }) : '' })}><MTextButton tone="danger" onclick={unpair}>{confirmUnpair ? t('backup.action.confirmUnpair') : t('backup.action.unpair')}</MTextButton></MRow>
    {#if confirmUnpair && lost}<MHint role="alert">{unpairWarning(lost, phoneWords)}</MHint>{/if}
  </MGroup>

  <MGroup title={t('recovery.group.title')} id="m-recovery" line={recoveryLine(false, '', phoneWords)} tone={recoveryTone(st, false, '')} infoTitle={t('recovery.help.pcTitle')}>
    {#snippet info()}
      <p>{t('recovery.help.pcStatus')}</p>
      <p>{t('recovery.help.pcWait')}</p>
      <p>{t('recovery.help.export')}</p>
      <p>{t('recovery.help.limit')}</p>
    {/snippet}
    <ForgotPassphrase mobile paired words={phoneWords} workingLabel="" oncode={() => { showCode = true }} />
    <MRow title={t('recovery.method.codeLabel')} desc={t('recovery.help.newPc')}><MTextButton onclick={() => { showCode = !showCode }} aria-expanded={showCode}>{showCode ? t('recovery.action.hide') : t('recovery.action.show')}</MTextButton></MRow>
    {#if showCode}
      <label class="m-fld"><input readonly value={m.pair.k} aria-label={t('recovery.method.codeLabel')} autocomplete="off" spellcheck="false" /></label>
      <MHint>{t('recovery.warning.code')}</MHint>
    {/if}
    <MRow title={t('recovery.action.newPc')}><MButton size="sm" disabled={exportingRecovery} onclick={saveRecovery}>{exportingRecovery ? t('recovery.action.saving') : t('recovery.action.export')}</MButton></MRow>
    {#if recoveryNote}<MHint role="status">{recoveryNote}</MHint>{/if}
  </MGroup>
</div>
{:else if m}
<PageKeys infoTitle={t('backup.group.drive')}>
  {#snippet info()}
    <p>{t('backup.help.solo')}</p>
    <p>{t('backup.help.separate')}</p>
    <p><T id="backup.help.soloContent" /></p>
  {/snippet}
</PageKeys>
<div class="m-pad m-calm m-page">
  <MBox id="m-backup-status">
    {@render stateRow()}
    {#if phone.note}<MHint role="status">{phone.note}</MHint>{/if}
    {#if st?.id === 'unreachable' && phone.round?.error && !phone.refreshing}<MHint tone="error" role="alert">{phone.round.error}</MHint>{/if}
    <MRow id="m-library" title={t('backup.state.localItems', { n: phone.rows.length, items: fmtNum(phone.rows.length, 'en') })} />
    {#if backupFiles !== null}<MRow title={t('backup.state.backupFiles', { n: backupFiles, files: fmtNum(backupFiles, 'en') })} />{/if}
  </MBox>

  <MGroup title={t('backup.group.account')} id="m-conn" line={driveBusy && signedIn ? t('backup.account.backingUp') : google} tone={googleTone(st, { signedIn, driveOk: drive.ok, busy: driveBusy })} onclose={() => { confirmDisconnect = false }}>
    {#if phone.account || signedIn}{#if !m.pair.d}{@render accountRow()}{/if}{:else if !above('back-up') && !above('sign-in-again')}
      <MRow title={t('backup.group.drive')}><MButton variant={lead ? 'pri' : 'default'} size="sm" onclick={() => connectDrive()} disabled={phone.connecting}>{phone.connecting ? connectLabel(phone.connectStep) : t('backup.action.backup')}</MButton></MRow>
    {/if}
    {#if signedIn || disconnecting}<MRow title={t('backup.action.disconnectBackup')} desc={t('backup.warning.disconnectHelp')}><MTextButton onclick={disconnectBackup} disabled={disconnecting}>{disconnecting ? t('backup.action.stopCloud') : confirmDisconnect ? t('backup.action.confirmDisconnect') : t('backup.action.disconnect')}</MTextButton></MRow>{/if}
    {#if confirmDisconnect && !disconnecting}{#if backup.task}<MHint>{t('backup.warning.disconnectTask')}</MHint>{/if}<MTextButton onclick={() => confirmDisconnect = false}>{t('common.cancel')}</MTextButton>{/if}
    <MRow title={t('shell.sync.title')} desc={network.manualPause ? t('backup.warning.pausePersisted') : t('backup.warning.pauseContent')}><MButton size="sm" onclick={() => setSyncPaused(!network.manualPause)}>{network.manualPause ? t('shell.sync.resume') : t('shell.sync.pause')}</MButton></MRow>
    <MTextButton onclick={() => { location.hash = '#/backup/manage' }}>{t('backup.action.manage')}</MTextButton>
  </MGroup>

  {#if manage || backup.task || backup.busy}<PhoneBackupChoices onclose={() => { location.hash = '#/backup' }} />{/if}

  <MGroup title={t('backup.group.thisPhone')} id="m-phone" line={thisPhoneLine({ solo: true, name, unsent: phone.pend.unsent }, phoneWords)} tone={thisPhoneTone(st, phone.pend.unsent)} onclose={() => { confirmRemove = false }}>
    <MRow title={t('backup.group.changes')} desc={t('backup.phone.soloChanges', { unsent: phone.pend.unsent ? t('backup.state.unbacked', { n: phone.pend.unsent }) : t('backup.state.allBacked'), error: m.lastError ? ` · ${m.lastError}` : '' })}>{#if !above('send')}<MButton size="sm" onclick={sendNow} disabled={sending || !phone.pend.unsent}>{sending ? t('backup.phone.sending') : t('backup.action.send')}</MButton>{/if}</MRow>
    {#if sendNote}<MHint>{sendNote}</MHint>{/if}
    <!-- "Connect your PC" (onboard.svelte.ts openPairing) opens this group and scrolls to m-pair, the first pairing line -->
    {#if hasPcMirror}<MHint id="m-pair">{t('backup.warning.desktop')}</MHint>{/if}
    <MRow title={t('backup.pair.withPc')} desc={t('backup.warning.pair')} id={hasPcMirror ? undefined : 'm-pair'}><MButton size="sm" onclick={() => pairFrom()} disabled={!isApp}>{t('settings.pair.scan')}</MButton></MRow>
    {@render pasteLink()}
    <MRow title={t('backup.action.removeLocal')} desc={t('backup.warning.removeLocal')}><MTextButton tone="danger" onclick={removeSolo}>{confirmRemove ? t('backup.action.confirmRemove') : t('settings.storage.remove')}</MTextButton></MRow>
  </MGroup>

  <PhoneRecovery working={driveBusy || phone.connecting || sending} />
</div>
{/if}
