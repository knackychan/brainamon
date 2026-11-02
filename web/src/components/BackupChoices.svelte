<script lang="ts">
  import { api } from '../lib/api'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  import TextButton from './ui/TextButton.svelte'

  let { account, ondone, onform }: { account: string; ondone: () => void; onform?: (open: boolean) => void } = $props()
  let choice = $state<'' | 'replace' | 'delete'>(''), busy = $state(false), error = $state('')
  $effect(() => { onform?.(!!choice) })
  async function confirm() {
    if (busy || !choice) return
    busy = true; error = ''
    try {
      await api.post(choice === 'replace' ? '/api/cloud/reset' : '/api/cloud/sign-out',
        choice === 'replace' ? { replace_existing: true } : { delete_mirror: true, delete_existing: true })
      choice = ''; ondone()
    } catch (e) { error = (e as Error).message }
    finally { busy = false }
  }
</script>

<div>
  {#if choice}
    <Hint role="alert">{choice === 'replace'
      ? `Replace the desktop backup in ${account || 'this Google account'} with this PC’s library? Existing desktop backups are deleted only after the new backup finishes. Content that exists only in those old backups will be lost. Close Brainamon on other PCs first.`
      : `Delete all Brainamon desktop backup data in ${account || 'this Google account'} and disconnect? Content that exists only in those backups will be lost.`}</Hint>
    <Hint>Your library on this PC and standalone phone backups stay intact. Current sync work stops automatically. Old recovery material and paired phones will no longer open the deleted backups.</Hint>
    {#if choice === 'replace'}<Hint>After the replacement, choose a new recovery passphrase and pair your phones again.</Hint>{/if}
    <div class="frow">
      <Button size="sm" variant="danger" disabled={busy} onclick={confirm}>{busy ? 'Starting…' : choice === 'replace' ? 'Replace with this PC’s library' : 'Delete and disconnect'}</Button>
      <TextButton disabled={busy} onclick={() => { choice = ''; error = '' }}>Cancel</TextButton>
    </div>
  {:else}
    <Hint>Without a passphrase, recovery file or working device holding its key, the encrypted backup cannot be opened. You can keep this PC’s library and start a new backup.</Hint>
    <div class="frow">
      <TextButton onclick={() => choice = 'replace'}>Replace cloud backup with this PC’s library…</TextButton>
      <TextButton onclick={() => choice = 'delete'}>Delete cloud backup and disconnect…</TextButton>
    </div>
  {/if}
  {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
</div>
