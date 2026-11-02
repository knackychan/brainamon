<script lang="ts">
  // Optional support, with an explicit legacy receipt exchange for older phone apps.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { confirmWin } from '../lib/windows.svelte'
  import { DONATE_URL } from '../lib/product-links'
  import Button from './ui/Button.svelte'
  import Disclosure from './ui/Disclosure.svelte'
  import InfoTip from './ui/InfoTip.svelte'
  import GroupBox from './ui/GroupBox.svelte'
  import Hint from './ui/Hint.svelte'
  import Label from './ui/Label.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import TextButton from './ui/TextButton.svelte'

  interface License { status: 'none' | 'valid' | 'invalid'; licensee: string; email: string; key_id: string; issued: string; error: string }
  let { idPrefix = '', onstatus }: { idPrefix?: string; onstatus?: (license: License) => void } = $props()
  let license = $state<License | null>(null)
  let key = $state('')
  let busy = $state(false)
  let doing = $state<'' | 'activate' | 'remove'>('')
  let error = $state('')
  let message = $state('')
  let replacing = $state(false)
  const valid = $derived(license?.status === 'valid')
  const editing = $derived(!!license && (license.status !== 'valid' || replacing))

  function take(l: License) { license = l; onstatus?.(l) }
  async function load() {
    error = ''
    try { take(await api.get<License>('/api/license')) }
    catch (e) { error = (e as Error).message }
  }
  onMount(load)

  async function activate() {
    if (busy || !key.trim()) return
    busy = true; doing = 'activate'; error = ''; message = ''
    try {
      take(await api.put<License>('/api/license', { key }))
      key = ''; replacing = false
      message = 'Legacy receipt saved for compatibility with older phone apps.'
    } catch (e) { error = (e as Error).message } finally { busy = false; doing = '' }
  }
  async function remove() {
    if (busy) return
    const ok = await confirmWin({ title: 'Remove legacy receipt', msg: 'Remove the saved legacy receipt?', detail: 'Current phone and vault sync keep working. Older phone apps that still use this receipt need an upgrade. Your library, pairing and queued edits stay. Keep the key if you need it again.', ok: 'Remove receipt', danger: true })
    if (!ok) return
    busy = true; doing = 'remove'; error = ''; message = ''
    try {
      take(await api.del<License>('/api/license'))
      replacing = false
      message = 'Legacy receipt removed. Current sync, pairing and saved content are unchanged.'
    } catch (e) { error = (e as Error).message } finally { busy = false; doing = '' }
  }
</script>

<GroupBox aria-label="Support">
  <Label as="span" id={idPrefix + 'set-s-license'} tabindex={-1}>Support<InfoTip label="Support and older receipts"><span>Brainamon's current features are free to use. Support is optional and does not unlock features. AI providers may charge for requests made with your own keys.</span><span>An older phone app can still use a valid legacy receipt. Current phones use the paired PC's signed access confirmation, which expires after one hour without renewal. Removing a receipt does not unpair current phones.</span></InfoTip></Label>
  <div>
    <Hint>All features are available without payment or activation. <a href={DONATE_URL} target="_blank" rel="noopener noreferrer">Support Brainamon on Ko-fi</a> if you would like to.</Hint>
    <Disclosure summary="Legacy receipt for an older phone app">
    <Hint>Optional compatibility only. Saving an old Gumroad receipt key explicitly contacts the activation service and Gumroad once; a Brainamon key is then stored locally. Current apps do not need it.</Hint>
    {#if license}
      <Status on={valid} role="status">{valid ? 'Legacy receipt stored' : license.status === 'invalid' ? 'Saved legacy receipt could not be verified' : 'No legacy receipt stored'}</Status>
      {#if valid}<Hint>Issued to {license.licensee}{license.email ? ` (${license.email})` : ''} · {license.key_id} · no expiry.</Hint>{/if}
      {#if license.error}<Hint tone="error" role="alert">{license.error}</Hint>{/if}
    {:else if error}
      <Hint tone="error" role="alert">Could not load the optional legacy receipt: {error}</Hint>
    {:else}
      <Hint role="status">Loading legacy receipt…</Hint>
    {/if}
  {#if editing}
    <Label for={idPrefix + 'license-key'}>Legacy receipt key</Label>
    <div>
      <textarea class="inp" id={idPrefix + 'license-key'} rows="3" bind:value={key} disabled={busy} placeholder="Existing Gumroad or Brainamon key" autocomplete="off" spellcheck="false" maxlength="8192"></textarea>
    </div>
  {/if}
    {#if doing === 'activate'}<Progress label="Checking the license key" />{/if}
    {#if message}<Status on={valid} role="status">{message}</Status>{/if}
    {#if error && license}<Hint tone="error" role="alert">{error}</Hint>{/if}
    <div class="frow">
      {#if !license}
        {#if error}<Button size="sm" onclick={load}>Retry</Button>{/if}
      {:else if editing}
        <Button size="sm" disabled={busy || !key.trim()} onclick={activate}>{doing === 'activate' ? 'Saving…' : 'Save legacy receipt'}</Button>
        {#if replacing}<TextButton disabled={busy} onclick={() => { replacing = false; key = '' }}>Cancel</TextButton>{/if}
      {:else}
        <Button size="sm" disabled={busy} onclick={() => { replacing = true; message = '' }}>Replace receipt…</Button>
      {/if}
      {#if license && license.status !== 'none'}<TextButton disabled={busy} onclick={remove}>{doing === 'remove' ? 'Removing…' : 'Remove legacy receipt…'}</TextButton>{/if}
    </div>
    </Disclosure>
  </div>
</GroupBox>
