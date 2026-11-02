<script lang="ts">
  // More > Backup & phones (#/backup, docs/superpowers/plans/2026-10-31-phone-backup-phones.md P2). A phone paired with
  // a PC: Status (the PhoneState with what it means and the library in Drive; the numbered guide under it while a new
  // pairing is set up), Google account, This phone and Recovery. The phone without a PC (sub-plan 05): Status (with
  // what is on this phone), Google account (its own backup), This phone (pairing with a PC, Remove) and Recovery
  // (PhoneRecovery.svelte, with Recover a library…, #/recover). Every row was More's before; a row's key is left out
  // while the Status offers the same one.
  import ForgotPassphrase from '../../components/ForgotPassphrase.svelte'
  import { onMount } from 'svelte'
  import { changes as changesDb, wipe } from '../store'
  import { changeAccount, connectDrive, driveStatus, fmtAgo, mirrorSource, pairFrom, parseRoute, phone, phoneStatus, refresh, solo, syncNow } from '../state.svelte'
  import { actionBusy, actionLabel, runPhoneAction } from '../actions'
  import { deviceName, isApp, secretsSaved } from '../native'
  import { forget as unpairPhone, token } from '../mirror/pairing'
  import { disconnectPhoneBackup } from '../mirror/phone-backup'
  import { backup } from '../backup.svelte'
  import PhoneBackupChoices from '../PhoneBackupChoices.svelte'
  import { allowCloudWork, RECONNECT_BUSY, stopCloudWork } from '../mirror/gate'
  import { exportPhoneRecovery } from '../mirror/recovery'
  import { unpairEdits, unpairWarning } from '../mirror/phone-facts'
  import { ACCESS_STATES, type ActionId } from '../mirror/phone-state'
  import { network, setSyncPaused, syncPaused } from '../network.svelte'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'
  import MStatus from '../ui/MStatus.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import PhoneRecovery from '../PhoneRecovery.svelte'

  let { scroller }: { scroller?: HTMLElement } = $props()
  const m = mirrorSource
  const st = $derived(phoneStatus())
  const above = (id: ActionId) => st?.action?.id === id
  // token() is not reactive: read it again when a token comes or goes (phone.tokenAt) or Google refuses it
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  const drive = $derived(driveStatus())
  const driveBusy = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing)
  // the source is not reactive: read its manifest again whenever a refresh lands
  const man = $derived((phone.synced, m?.manifest ?? null))
  let pairingGuide = $state(sessionStorage.getItem('bp-pair-setup') === '1')
  const pcAccess = $derived(phone.tried && signedIn && !network.licenseLocked && (phone.noLibrary || phone.reachable))
  function finishPairing() { sessionStorage.removeItem('bp-pair-setup'); pairingGuide = false; location.hash = '#/lib' }

  let name = $state('')
  onMount(() => { void deviceName().then(n => { name = n }) })
  // the screen opens at its top (the Library's line under the app bar comes from far down a list), and Back lands on
  // the top of More, where the status card is, not where this screen was scrolled to. A teardown reads state as it
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
    try { await syncNow(); sendNote = phone.sync?.msg ?? '' } catch (e) { sendNote = (e as Error).message } finally { sending = false }
  }

  // Unpair (plan P10): the first tap says which edits never reach the PC; the journal stays on this phone
  let confirmUnpair = $state(false)
  const lost = $derived(unpairEdits(phone.pend, !!network.licenseKind))
  async function unpair() {
    if (!confirmUnpair) { confirmUnpair = true; return }
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
    } catch (e) { phone.note = (e as Error).message === RECONNECT_BUSY ? RECONNECT_BUSY : 'Removing this phone connection could not finish. Keep the current files and retry.' }
  }

  let exportingRecovery = $state(false), recoveryNote = $state(''), showCode = $state(false)
  async function saveRecovery() {
    if (!m || exportingRecovery) return
    exportingRecovery = true; recoveryNote = ''
    try { recoveryNote = await exportPhoneRecovery(m.pair) }
    catch (e) { recoveryNote = (e as Error).message }
    finally { exportingRecovery = false }
  }
  let pasted = $state('')

  // without a PC (sub-plan 05): the source is not reactive, so read it again whenever a refresh lands
  const hasPcMirror = $derived((phone.synced, m?.pcMirror ?? false))
  async function disconnectBackup() {
    if (!m) return
    if (!confirmDisconnect) { confirmDisconnect = true; return }
    disconnecting = true
    try { await disconnectPhoneBackup(); location.reload() }
    catch (e) { phone.note = (e as Error).message }
    finally { disconnecting = false }
  }
  let confirmDisconnect = $state(false), disconnecting = $state(false)
  const manage = $derived((phone.route, location.hash.endsWith('/manage')))
  // Remove (two taps): the phone's library, its queued changes and its key leave this phone; independent copies stay
  let confirmRemove = $state(false)
  async function removeSolo() {
    if (backup.task || backup.busy) { phone.note = 'Finish the saved backup task, or disconnect backup before removing this phone’s content.'; return }
    if (!confirmRemove) { confirmRemove = true; return }
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
    } catch (e) { phone.note = (e as Error).message === RECONNECT_BUSY ? RECONNECT_BUSY : 'Removing this phone connection could not finish. Keep the current files and retry.' }
  }
</script>

<!-- the Google account in use, and Change account (Google's account chooser; mirror/pairing.ts). An
     account that is not the PC's is not used: the row says so -->
{#snippet accountRow()}
  {#if m}
    {@const other = phone.account?.check === 'mismatch' ? phone.account.got : ''}
    <MRow title="Signed in as {other || m.pair.g || 'your Google account'}" desc={other ? `Your PC uploads to ${m.pair.e}: change to that account to read your library` : 'Brainamon keeps its hidden folder in this Google account'}>{#if !above('change-account')}<MButton size="sm" onclick={changeAccount} disabled={phone.connecting}>{phone.connecting ? `${phone.connectStep || 'Connecting'}…` : 'Change account'}</MButton>{/if}</MRow>
    {#if phone.connecting}<MHint>{phone.connectStep === 'Waiting for Google' ? 'Choose the account in the sheet from Google. It gives up after 2 minutes.' : 'Asking Google which account this is. It gives up after 10 seconds.'}</MHint>{/if}
  {/if}
{/snippet}

<!-- the pairing-link paste field, under a disclosure -->
{#snippet pasteLink()}
  <MDisclosure summary="Paste the pairing link instead">
    <MRow title="Pairing link" desc="Copy link, under the code on the PC"><MButton size="sm" onclick={() => pairFrom(pasted)} disabled={!pasted.includes('#pair=')}>Pair</MButton></MRow>
    <label class="m-fld"><input bind:value={pasted} placeholder="https://…#pair=…" aria-label="Pairing link" autocomplete="off" /></label>
  </MDisclosure>
{/snippet}

<!-- the PhoneState: its dot, sentence, what it means and its one key (actions.ts) -->
{#snippet stateRow()}
  {#if st}
    <MStatus tone={st.tone} text={st.text} detail={st.detail}>
      {#if st.action}{@const a = st.action}<MButton size="sm" variant={a.primary ? 'pri' : 'default'} disabled={actionBusy(a.id)} onclick={() => runPhoneAction(a.id)}>{actionLabel(a)}</MButton>{/if}
    </MStatus>
  {/if}
{/snippet}

{#if m && !solo}
<div class="m-pad m-calm">
  <MBox id="m-backup-status">
    <h3>Status</h3>
    {@render stateRow()}
    {#if phone.note}<MHint role="status">{phone.note}</MHint>{/if}
    {#if st?.id === 'unreachable' && phone.error && !phone.refreshing}<MHint tone="error" role="alert">{phone.error}</MHint>{/if}
    <MRow id="m-library" title="Library in Google Drive" desc={man ? `${man.items.toLocaleString('en')} items · the PC uploaded ${fmtAgo(man.published)}` : phone.refreshing ? 'Loading your library…' : 'Nothing read from Drive yet'} />
  </MBox>

  {#if pairingGuide || !phone.reachable}
    <MBox id="m-pair-setup">
      <h3>Finish connecting your PC</h3>
      <MRow title="1. PC paired" desc={`Use the Google account ${m.pair.e || 'selected on the PC'}. A second phone license is not needed.`} />
      <MRow title="2. Connect Google Drive" desc={signedIn ? `Google Drive connected: ${m.pair.g || 'signed in'}.` : phone.connecting ? phone.connectStep : phone.account ? `Choose ${m.pair.e}; the selected account does not match.` : 'Connect this phone to the account your PC uses.'} />
      <MRow role="status" title="3. Check PC access" desc={!signedIn ? 'After connecting Google Drive.' : pcAccess ? 'PC access confirmed.' : phone.refreshing ? 'Checking the signed PC access confirmation…' : st && ACCESS_STATES.includes(st.id) ? st.text : 'Waiting to read PC access confirmation. Missing confirmation does not prove the PC is offline or unlicensed.'} />
      <MRow title="4. Load library" desc={phone.reachable ? `Ready: ${phone.rows.length.toLocaleString('en')} items loaded.` : phone.noLibraryWhy?.message || (pcAccess ? 'Waiting for the PC’s first library upload. Google Drive stays connected.' : 'Library loading follows PC access confirmation.')} />
      {#if signedIn && !phone.reachable && !above('retry') && !driveBusy}<MButton size="sm" disabled={phone.connecting || syncPaused()} onclick={() => refresh()}>Retry</MButton>{/if}
      {#if phone.reachable}<MButton variant={st?.action?.primary ? 'default' : 'pri'} onclick={finishPairing}>Done, open library</MButton>{/if}
    </MBox>
  {/if}

  <MBox id="m-conn">
    <h3>Google account<span class="m-sp"></span><span class="m-lamp" class:amber={drive.lamp !== 'connected' && drive.lamp !== 'syncing'} class:busy={driveBusy}>{driveBusy ? 'syncing' : drive.lamp}</span></h3>
    <MHint>Reads the PC's encrypted mirror and uploads encrypted phone edits, so the phone works with the PC off.</MHint>
    {#if phone.account || (signedIn && !phone.signIn)}{#if !m.pair.d}{@render accountRow()}{/if}{:else if !above('connect') && !above('sign-in-again')}
      <MRow title="Connect Google Drive" desc={m.pair.c || isApp ? `Google asks which account${m.pair.e ? `: choose ${m.pair.e}, the one your PC uploads to` : ''}` : 'The PC has no Google sign-in app for the phone yet (Settings > Backup & phones)'}><MButton variant="pri" size="sm" onclick={() => connectDrive()} disabled={phone.connecting || (!m.pair.c && !m.pair.d && !isApp)}>{phone.connecting ? `${phone.connectStep || 'Connecting'}…` : 'Connect'}</MButton></MRow>
    {/if}
    <MDisclosure summary="What Google sees">
      <MHint>Google sees account, connection and file size/timing metadata. This phone keeps decrypted copies; Google account/storage terms apply.</MHint>
      <MHint>Edits go back when the PC runs. PC unpairing blocks future reads after key rotation finishes; cached plaintext and independent Google sign-in remain.</MHint>
    </MDisclosure>
  </MBox>

  <MBox id="m-phone">
    <h3>This phone</h3>
    <MRow title={name || 'This phone'} desc={isApp ? 'How your PC lists this phone (Android Settings > About phone).' : 'How your PC lists this phone.'} />
    <MRow title="Changes from this phone" desc="{phone.pend.unsent ? `${phone.pend.unsent} not sent yet` : 'All sent'}{phone.pend.waiting ? ` · ${phone.pend.waiting} waiting for the PC` : ''}{phone.pend.held ? ` · ${phone.pend.held} canvas change${phone.pend.held > 1 ? 's' : ''} held until the PC is updated` : ''}{m.lastError ? ` · ${m.lastError}` : ''}">{#if !above('send')}<MButton size="sm" onclick={sendNow} disabled={sending || !phone.pend.unsent}>{sending ? 'Sending…' : 'Send now'}</MButton>{/if}</MRow>
    {#if sendNote}<MHint>{sendNote}</MHint>{/if}
    <MRow id="m-pair" title="Pair again" desc={isApp ? 'Scan the code on the PC (Settings > Backup & phones > Add a phone)' : 'Open the pairing link from the PC (Settings > Backup & phones > Add a phone)'}>{#if isApp && !above('scan')}<MButton size="sm" onclick={() => pairFrom()}>Scan</MButton>{/if}</MRow>
    {@render pasteLink()}
    <MRow title="Paired with your PC" desc="Key {m.pair.f}{m.pair.d ? ' · development Drive' : ''}{Object.keys(m.pair.ai || {}).length ? ` · AI keys: ${Object.keys(m.pair.ai).join(', ')}` : ''}"><MTextButton tone="danger" onclick={unpair}>{confirmUnpair ? 'Sure? Unpair' : 'Unpair this phone'}</MTextButton></MRow>
    {#if confirmUnpair && lost}<MHint role="alert">{unpairWarning(lost)}</MHint>{/if}
  </MBox>

  <MBox id="m-recovery">
    <h3>Recovery</h3>
    <ForgotPassphrase mobile paired workingLabel="" oncode={() => { showCode = true }} />
    <MStatus tone="todo" text="Recovery managed on your PC" detail="This phone does not receive the PC's passphrase status. Check it in the PC's Settings > Backup & phones > Recovery." />
    <MDisclosure summary="If the PC is updating its security key">
      <MHint>On the PC, recovery checks and passphrase changes wait for the replacement backup to finish uploading, verification and old-copy cleanup. An ordinary backup upload allows passphrase setup while it runs.</MHint>
    </MDisclosure>
    <MRow title="Recovery code" desc="For getting the library back on a new PC."><MTextButton onclick={() => { showCode = !showCode }} aria-expanded={showCode}>{showCode ? 'Hide' : 'Show'}</MTextButton></MRow>
    {#if showCode}
      <label class="m-fld"><input readonly value={m.pair.k} aria-label="Recovery code" autocomplete="off" spellcheck="false" /></label>
      <MHint>Anyone with this code can open your encrypted Drive mirror: keep it private. On the new PC: Settings &gt; Backup &amp; phones, Recover a library, Phone code.</MHint>
    {/if}
    <MRow title="Recover on a replacement PC" desc="Export this phone's library key, without AI keys or Google sign-in"><MButton size="sm" disabled={exportingRecovery} onclick={saveRecovery}>{exportingRecovery ? 'Saving…' : 'Export recovery file'}</MButton></MRow>
    {#if recoveryNote}<MHint role="status">{recoveryNote}</MHint>{/if}
    <MDisclosure summary="About the recovery file">
      <MHint>The file unlocks your encrypted Drive mirror. Save it outside this phone and keep it private. It cannot recover content that was never uploaded, or a mirror encrypted with a newer key. Use it in the PC's Settings &gt; Backup &amp; phones, then Recover a library.</MHint>
    </MDisclosure>
  </MBox>
</div>
{:else if m}
<div class="m-pad m-calm">
  <MBox id="m-backup-status">
    <h3>Status</h3>
    {@render stateRow()}
    {#if phone.note}<MHint role="status">{phone.note}</MHint>{/if}
    {#if st?.id === 'unreachable' && phone.round?.error && !phone.refreshing}<MHint tone="error" role="alert">{phone.round.error}</MHint>{/if}
    <MRow id="m-library" title="{phone.rows.length.toLocaleString('en')} item{phone.rows.length === 1 ? '' : 's'} on this phone" desc="Saved here; the backup in Google Drive is encrypted with this phone's own key" />
  </MBox>

  <MBox id="m-conn">
    <h3>Google account<span class="m-sp"></span><span class="m-lamp" class:amber={!signedIn} class:busy={driveBusy}>{driveBusy ? 'backing up' : signedIn ? 'Drive connected' : 'phone only'}</span></h3>
    <MHint>Optional: back up this phone's library encrypted in Google Drive, with its own key. No PC or license is needed.</MHint>
    {#if phone.account || signedIn}{#if !m.pair.d}{@render accountRow()}{/if}{:else if !above('back-up') && !above('sign-in-again')}
      <MRow title="Google Drive backup" desc="Google asks which account; Brainamon sees only its own hidden folder"><MButton variant="pri" size="sm" onclick={() => connectDrive()} disabled={phone.connecting}>{phone.connecting ? `${phone.connectStep || 'Connecting'}…` : 'Back up to Google Drive'}</MButton></MRow>
    {/if}
    <MDisclosure summary="What Google sees">
      <MHint>The backup does not sync with a desktop library in the same account. Google sees account, connection and file size/timing metadata. Google account/storage terms apply.</MHint>
    </MDisclosure>
    {#if signedIn || disconnecting}<MRow title="Disconnect backup" desc="Stops cloud work after the current request. Local content, queued edits and existing Drive backups stay."><MTextButton onclick={disconnectBackup} disabled={disconnecting}>{disconnecting ? 'Stopping cloud work…' : confirmDisconnect ? 'Confirm disconnect' : 'Disconnect'}</MTextButton></MRow>{/if}
    {#if confirmDisconnect && !disconnecting}{#if backup.task}<MHint>Disconnect stops the saved task and keeps remaining cloud copies. Files already deleted cannot be restored.</MHint>{/if}<MTextButton onclick={() => confirmDisconnect = false}>Cancel</MTextButton>{/if}
    <MRow title="Sync" desc={network.manualPause ? 'Paused until you resume, including after restart.' : 'Changes stay on this phone while sync is paused.'}><MButton size="sm" onclick={() => setSyncPaused(!network.manualPause)}>{network.manualPause ? 'Resume sync' : 'Pause sync'}</MButton></MRow>
    <MTextButton onclick={() => { location.hash = '#/backup/manage' }}>Manage phone backups…</MTextButton>
  </MBox>

  {#if manage || backup.task || backup.busy}<PhoneBackupChoices onclose={() => { location.hash = '#/backup' }} />{/if}

  <MBox id="m-phone">
    <h3>This phone</h3>
    <MRow title="Changes from this phone" desc="{phone.pend.unsent ? `${phone.pend.unsent} not backed up yet` : 'All backed up'}{m.lastError ? ` · ${m.lastError}` : ''}">{#if !above('send')}<MButton size="sm" onclick={sendNow} disabled={sending || !phone.pend.unsent}>{sending ? 'Sending…' : 'Send now'}</MButton>{/if}</MRow>
    {#if sendNote}<MHint>{sendNote}</MHint>{/if}
    <!-- "Connect your PC" (onboard.svelte.ts openPairing) scrolls to m-pair, the first pairing line -->
    {#if hasPcMirror}<MHint id="m-pair">This account also has a desktop library. Your phone backup stays separate. Pair with your trusted PC below only if you want to send this phone's library to it.</MHint>{/if}
    <MRow title="Pair with a PC" desc="Scan the code from the PC (Settings > Backup & phones > Add a phone). Everything saved here goes to the PC." id={hasPcMirror ? undefined : 'm-pair'}><MButton size="sm" onclick={() => pairFrom()} disabled={!isApp}>Scan</MButton></MRow>
    {@render pasteLink()}
    <MRow title="Remove from this phone" desc="Removes the local phone copy. Independent copies stay where you saved them."><MTextButton tone="danger" onclick={removeSolo}>{confirmRemove ? 'Sure? Remove' : 'Remove'}</MTextButton></MRow>
  </MBox>

  <PhoneRecovery working={driveBusy || phone.connecting || sending} />
</div>
{/if}
