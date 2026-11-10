<script lang="ts">
  // The three states only this phone's owner can fix (access removed, PC changed, Google asks to sign in again:
  // mirror/phone-state.ts `strip`): one line under the top bar, a page's app bar or a sheet's head; a tap
  // opens Backup & phones (plan P3). Hidden on More and its pages, which show the same state with its keys.
  // It was SyncStrip.svelte's owner branch; the running lanes moved to the sync panel (SyncPanel.svelte).
  import T from '../lib/i18n/T.svelte'
  import { phone, phoneStatus } from './state.svelte'
  import { go } from './shell.svelte'

  const here = $derived(phone.route.tab === 'more')
  const st = $derived(phoneStatus())
  const owner = $derived(!here && st?.strip ? st : null)
</script>

{#if owner}
  <div class="m-strip m-strip-owner" role="status" aria-live="polite">
    <a class="m-strip-lane" href="#/backup" onclick={e => { e.preventDefault(); go('#/backup') }}><span class="m-strip-text"><T id="shell.ownerLine" params={{ text: owner.text }} /></span></a>
  </div>
{/if}
