<script lang="ts">
  import { tick } from 'svelte'
  import { api } from '../lib/api'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  import TextButton from './ui/TextButton.svelte'

  let { account, ondone, onform, onbusy, onerror, replaceReason = '' }: { account: string; ondone: () => void; onform?: (open: boolean) => void; onbusy?: (busy: boolean) => void; onerror?: (error: unknown) => void; replaceReason?: string } = $props()
  const uid = $props.id()
  const waitId = `${uid}-wait`
  const reasonId = `${uid}-reason`
  let choice = $state<'' | 'replace' | 'delete'>(''), busy = $state(false), error = $state('')
  let choiceAccount = $state('')
  let cancel: HTMLButtonElement | undefined = $state(), replace: HTMLButtonElement | undefined = $state(), disconnect: HTMLButtonElement | undefined = $state()
  function choose(next: 'replace' | 'delete') { choiceAccount = account; choice = next; error = ''; void tick().then(() => cancel?.focus()) }
  function cancelChoice() { const old = choice; choice = ''; error = ''; void tick().then(() => (old === 'replace' ? replace : disconnect)?.focus()) }
  $effect(() => { onform?.(!!choice) })
  $effect(() => {
    if (choice && !busy && account !== choiceAccount) {
      cancelChoice()
      error = 'The Google account changed. Review this action again for the current account.'
    }
  })
  async function confirm() {
    if (busy || !choice || !choiceAccount || choiceAccount !== account) return
    busy = true; onbusy?.(true); error = ''
    try {
      await api.post(choice === 'replace' ? '/api/cloud/reset' : '/api/cloud/sign-out',
        choice === 'replace' ? { replace_existing: true, expected_account: choiceAccount } : { delete_mirror: true, delete_existing: true, expected_account: choiceAccount })
      choice = ''; ondone()
    } catch (e) { error = (e as Error).message; onerror?.(e) }
    finally { busy = false; onbusy?.(false) }
  }
</script>

<div>
  {#if choice}
    <Hint role="alert">{choice === 'replace'
      ? `Replace the desktop backup in ${choiceAccount || 'this Google account'} with this PC’s library? Existing desktop backups are deleted only after the new backup finishes. Content that exists only in those old backups will be lost. Close Brainamon on other PCs first.`
      : `Delete all Brainamon desktop backup data in ${choiceAccount || 'this Google account'} and disconnect? Content that exists only in those backups will be lost.`}</Hint>
    <Hint>Your library on this PC and standalone phone backups stay intact. Current sync work stops automatically. Old recovery material and paired phones will no longer open the deleted backups.</Hint>
    {#if choice === 'replace'}<Hint>After the replacement, choose a new recovery passphrase and pair your phones again.</Hint>{/if}
    {#if choice === 'replace' && replaceReason}<Hint id={reasonId}>{replaceReason}</Hint>{/if}
    {#if busy}<Hint id={waitId} role="status">Waiting for this action to finish.</Hint>{/if}
    {#if !choiceAccount}<Hint id={waitId}>Connect Google Drive and check the account before continuing.</Hint>{/if}
    <div class="frow">
      <Button size="sm" variant="danger" disabled={busy || !choiceAccount || (choice === 'replace' && !!replaceReason)} aria-describedby={busy || !choiceAccount ? waitId : choice === 'replace' && replaceReason ? reasonId : undefined} onclick={confirm}>{busy ? 'Starting…' : choice === 'replace' ? 'Replace with this PC’s library' : 'Delete and disconnect'}</Button>
      <TextButton bind:ref={cancel} disabled={busy} aria-describedby={busy ? waitId : undefined} onclick={cancelChoice}>Cancel</TextButton>
    </div>
  {:else}
    <Hint>Without a passphrase, recovery file or working device holding its key, the encrypted backup cannot be opened. You can keep this PC’s library and start a new backup.</Hint>
    <div class="frow">
      <TextButton bind:ref={replace} onclick={() => choose('replace')}>Replace cloud backup with this PC’s library…</TextButton>
      <TextButton bind:ref={disconnect} onclick={() => choose('delete')}>Delete cloud backup and disconnect…</TextButton>
    </div>
  {/if}
  {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
</div>
