<script lang="ts">
  // What syncs right now, under the app bar on every screen: one line and one bar per running, queued or
  // paused lane (lanes.ts: the Google Drive read, the Obsidian vault round, the picture queue). Hidden when
  // nothing runs, on More and on Backup & phones (the Sync box and the status say the same, with the buttons), and
  // while the pull-to-sync widget lists its own steps. A tap opens More.
  // The three states only this phone's owner can fix (access removed, PC changed, Google asks to sign in again:
  // mirror/phone-state.ts `strip`) take the line's place instead, and a tap opens Backup & phones (plan P3).
  import { syncLanes } from './lanes'
  import { phone, phoneStatus } from './state.svelte'
  import { syncPaused } from './network.svelte'

  const here = $derived(phone.route.tab === 'more' && !phone.route.imp)
  const st = $derived(phoneStatus())
  const owner = $derived(!here && st?.strip ? st : null)
  const shown = $derived(here || owner || (phone.sync && !syncPaused()) ? [] : syncLanes().filter(l => l.active))
</script>

{#if owner}
  <div class="m-strip m-strip-owner" role="status" aria-live="polite">
    <a class="m-strip-lane" href="#/backup"><span class="m-strip-text m-strip-paused"><b>Backup &amp; phones</b> · {owner.text}</span></a>
  </div>
{:else if shown.length}
  <div class="m-strip" class:m-strip-network={shown.some(l => l.key === 'network')} role="status" aria-live="polite">
    {#each shown as l (l.key)}
      <a class="m-strip-lane" class:m-strip-idle={l.tag !== 'running'} href="#/more">
        {#if l.key !== 'network'}<span class="m-strip-track"><b style:width={`${l.pct ?? 0}%`}></b></span>{/if}
        <span class="m-strip-text" class:m-strip-paused={l.key === 'network'}><b>{l.name}</b> · {l.tag === 'running' || l.key === 'network' ? '' : `${l.tag} · `}{l.text}{l.pct !== null && l.tag === 'running' ? ` · ${l.pct}%` : ''}</span>
      </a>
    {/each}
  </div>
{/if}
