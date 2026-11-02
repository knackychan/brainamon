<script lang="ts">
  // Recover a library… (#/recover, docs/superpowers/plans/2026-10-31-phone-backup-phones.md sub-plan 05): a phone backup
  // in Google Drive, unlocked with a recovery passphrase (the setups found in Drive, newest first), a recovery file or
  // the original code. Then Keep this phone's content (Reconnect, when this phone's latest backup is in Drive under
  // that key) or Restore on an empty phone. Nothing here writes Drive; what was typed or unlocked is forgotten when the
  // screen closes. A phone paired with a PC recovers its library on the PC.
  import { onMount } from 'svelte'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import { MirrorKey } from '../mirror/crypto'
  import { token } from '../mirror/pairing'
  import { clock } from '../mirror/phone-state'
  import { readPhoneKit, type PhoneKit } from '../mirror/recovery-envelope'
  import { discoverPhoneRecovery, recoveryAccount, restorePhoneKit, restorePhonePassphrase } from '../mirror/phone-recovery'
  import { keyFromMaterial, KIT_IN_CODE, reconnectCheck, reconnectPhone, REFUSALS, type Eligibility } from '../mirror/phone-reconnect'
  import { recoveryFileText } from '../recovery.svelte'
  import { mirrorSource, phone, useWithoutPc } from '../state.svelte'

  let { scroller }: { scroller?: HTMLElement } = $props()
  const m = mirrorSource
  // token() is not reactive: read it again when a token comes or goes (phone.tokenAt) or Google refuses it
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  const working = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing || phone.connecting)
  type Method = 'password' | 'kit' | 'code'
  let busy = $state(false), error = $state(''), message = $state('')
  let password = $state(''), code = $state('')
  let method = $state<Method>(m ? 'password' : 'code')
  let setups = $state<Awaited<ReturnType<typeof discoverPhoneRecovery>>>([]), selected = $state('')
  // the key a method unlocked, held in memory until Reconnect, Restore on an empty phone or Cancel; never stored
  let found = $state<{ key: string; account: string; kit?: PhoneKit; check: Eligibility } | null>(null)
  let sure = $state(false)      // Reconnect asks twice (the phone's two-tap confirmation, as Remove and Unpair)
  const available = $derived(signedIn && !!m && !busy && !working)
  $effect(() => { void signedIn; found = null; sure = false })     // a sign-in change makes a found key stale

  function clearSecrets() { password = ''; code = '' }
  function forget() { found = null; sure = false }
  function choose(next: string) { method = next as Method; error = ''; message = ''; clearSecrets(); forget() }
  // the screen opens at its top; leaving it forgets what was typed, unlocked or found
  onMount(() => {
    scroller?.scrollTo(0, 0)
    return () => { clearSecrets(); forget(); setups = [] }
  })
  async function run(action: () => Promise<void>) {
    if (busy) return
    busy = true; error = ''; message = ''
    try { await action() }
    catch (e) { error = (e as Error).message }
    finally { busy = false }
  }
  async function discover() {
    await recoveryAccount(m!.pair, m!.drive)
    setups = await discoverPhoneRecovery(m!.drive)
    selected = setups[0]?.id ?? ''
    if (!selected) message = 'No phone passphrase setup was found. Use your recovery file or original recovery code. Desktop libraries are restored on a PC.'
  }
  // the method unlocks the key; nothing is restored yet. Then the read-only check says whether this phone can keep its content.
  async function find() {
    try {
      let key: string, account: string, kit: PhoneKit | undefined
      if (method === 'kit') {
        const text = await recoveryFileText()
        if (text === null) return
        kit = readPhoneKit(text)
        ;({ key, account } = await restorePhoneKit(m!.pair, m!.drive, text))
      } else if (method === 'password') {
        ;({ key, account } = await restorePhonePassphrase(m!.pair, m!.drive, selected, password))
      } else {
        key = await keyFromMaterial(code)
        account = signedIn && m ? await recoveryAccount(m.pair, m.drive) : ''
      }
      const check: Eligibility = signedIn && m
        ? await reconnectCheck(await MirrorKey.fromText(key), m.drive, m.changes)
        : { ok: false, reason: 'not_connected', message: REFUSALS.not_connected }
      found = { key, account, kit, check }; sure = false
    } finally { clearSecrets() }
  }
  async function reconnect() {
    if (!found || !m) return
    if (!sure) { sure = true; return }
    const f = found
    await reconnectPhone(m.pair, m.drive, m.changes, f.key, f.account, f.kit)
    forget()
    // a recovery file keeps recovery set up; otherwise Backup & phones offers Set up recovery right away (its Status key)
    try { sessionStorage.setItem('bp-note', f.kit ? 'This phone kept its content and reconnected to its Drive backup. Its queued changes go up at the next sync.' : 'This phone kept its content and reconnected to its Drive backup. Its queued changes go up at the next sync. Set up recovery to protect the key with a passphrase and a recovery file.') } catch { /* the note is only a courtesy */ }
    location.replace(location.pathname + '#/backup'); location.reload()
  }
  async function restoreEmpty() {
    if (!found) return
    sure = false
    // keeps `found` on refusal: Reconnect stays one tap away
    if (!await useWithoutPc(found.key, found.account)) throw new Error(phone.note)
  }
</script>

<div class="m-pad m-calm">
  <MBox id="m-recover">
    <h3>Phone backup in Google Drive</h3>
    <MHint>Find the backup first. If this phone matches it, you can keep everything here and reconnect; otherwise restore on an empty phone. Desktop libraries are restored on a PC.</MHint>
    {#if !m}
      <MHint>The original recovery code works right away. A passphrase or recovery file needs Google Drive: start Brainamon without a PC first (No PC? on More), then Back up to Google Drive with the account that holds the backup.</MHint>
    {:else if !signedIn}
      <MHint>A passphrase or recovery file needs Google Drive: Back up to Google Drive on Backup &amp; phones first, with the account that holds the backup. The original code works without it.</MHint>
    {/if}
    {#if working}<MHint>Wait for the current sync or connection to finish before restoring.</MHint>{/if}
    <MRow title="Unlock with" desc={method === 'password' ? 'A recovery setup in Google Drive, unlocked with its passphrase' : method === 'kit' ? 'The recovery file you saved' : 'The original code, a pairing link or an exported phone file'}><MSeg label="Unlock with" size="sm" options={[['password', 'Passphrase'], ['kit', 'File'], ['code', 'Code']]} value={method} disabled={busy} onchange={choose} /></MRow>
    {#if !found}
      {#if method === 'password'}
        <MButton size="sm" disabled={!available} onclick={() => run(discover)}>Find recovery setups</MButton>
        {#if setups.length > 1}
          <label class="m-fld"><span>Recovery setup</span><select bind:value={selected} disabled={!available}>{#each setups as setup (setup.id)}<option value={setup.id}>Set up {clock(setup.record.header.created * 1000)}</option>{/each}</select></label>
        {:else if setups.length === 1}
          <MRow title="Recovery setup" desc="Set up {clock(setups[0].record.header.created * 1000)}" />
        {/if}
        {#if setups.length}
          <label class="m-fld"><span>Recovery passphrase</span><input type="password" bind:value={password} maxlength="1024" autocomplete="off" disabled={!available} /></label>
          <MButton variant="pri" size="sm" disabled={!available || !selected || !password} onclick={() => run(find)}>Find backup</MButton>
        {/if}
      {:else if method === 'kit'}
        <MButton variant="pri" size="sm" disabled={!available} onclick={() => run(find)}>Open recovery file…</MButton>
      {:else}
        <label class="m-fld"><span>Original recovery code</span><input type="password" bind:value={code} maxlength="32768" autocomplete="off" spellcheck="false" disabled={busy || working} /></label>
        <MButton variant="pri" size="sm" disabled={busy || working || !code.trim()} onclick={() => run(find)}>Find backup</MButton>
      {/if}
    {:else}
      <MRow id="phone-recovery-keep" title="Keep this phone's content" desc={found.check.message} />
      {#if found.check.ok}
        <MHint>{sure ? "Your phone's content will be kept. Confirm to put the backup's key back; nothing is written to Drive." : "Your phone's content will be kept: everything on this phone and its queued changes stay, the backup's key comes back, nothing is written to Drive. Changes sent under the wrong key go up again at the next sync."}</MHint>
      {/if}
      <div class="m-row" style="flex-wrap:wrap">
        {#if found.check.ok}<MButton variant="pri" size="sm" disabled={!available} onclick={() => run(reconnect)}>{sure ? 'Confirm reconnect' : 'Reconnect this phone'}</MButton>{/if}
        <MButton variant={found.check.ok ? 'default' : 'pri'} size="sm" disabled={busy || working} onclick={() => run(restoreEmpty)}>Restore on an empty phone</MButton>
        <MTextButton disabled={busy} onclick={() => { forget(); error = ''; message = '' }}>Cancel</MTextButton>
      </div>
    {/if}
    {#if error === KIT_IN_CODE}<MButton size="sm" onclick={() => choose('kit')}>Use recovery file</MButton>{/if}
    {#if busy}<MHint role="status">Checking recovery… This may take a few seconds.</MHint>{/if}
    {#if message}<MHint role="status">{message}</MHint>{/if}
    {#if error}<MHint tone="error" role="alert">{error}</MHint>{/if}
    <MDisclosure summary="How recovery works">
      <MHint>Recovery uses the same Google account as the backup. Your recovery file unlocks the backup; it does not contain the backup. Keep it outside this phone, separately from your passphrase.</MHint>
      <MHint>Restore reads Drive without deleting or replacing its files. Reconnect keeps this phone's content when its latest backup is in Drive under the recovered key; Restore on an empty phone needs a phone with nothing on it.</MHint>
      <MHint>The original 43-character code is the library key, not a passphrase. The code field also takes a pairing link or the text of an exported phone recovery file.</MHint>
    </MDisclosure>
  </MBox>
</div>
