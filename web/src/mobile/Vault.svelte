<script lang="ts">
  // More > Obsidian vault: pick the phone's Obsidian vault folder and keep it in step with the PC (Android app only).
  // The rounds run from vault/auto.svelte.ts (foreground, every 2 minutes, Sync now). Laid out like the
  // Google Drive box (More.svelte): a lamp, the folder, then Start / Stop. Where the phone's and the PC's
  // rounds are (the line, the bar, Sync now) is in More's Sync box at the top (lanes.ts).
  // It depends on Google Drive, so it reads the Drive box's own status (state.svelte.ts driveStatus): when Drive
  // is not usable the lamp says so instead of "in step".
  import { isApp } from './native'
  import { driveStatus, solo, source } from './state.svelte'
  import { pickVaultFolder as pick, removeOldPages, runVault, setVaultOn as setOn, vault, watchPc } from './vault/auto.svelte'
  import { deviceId } from './mirror/pairing'
  import { syncPaused } from './network.svelte'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'
  import MRow from './ui/MRow.svelte'

  const drive = $derived(driveStatus())
  $effect(() => { if (isApp && !solo && vault.opts.on && drive.ok && source.vaultPc) return watchPc() })
  const lamp = $derived(
    vault.opts.on && syncPaused() ? 'paused' : vault.stopping ? 'stopping' : vault.busy ? 'syncing' : vault.queued ? 'queued' : !vault.opts.uri ? 'no folder' : !vault.opts.on ? 'off' : !drive.ok ? 'needs Drive'
    : vault.brake ? 'held' : vault.outcome === 'error' ? 'error' : vault.outcome === 'waiting' ? 'waiting for PC' : vault.outcome === 'ok' ? 'in step' : 'not run yet')
</script>

{#if isApp && !solo && source.syncVault}
  <MBox id="m-vault">
    <h3>Obsidian vault<span class="m-sp"></span><span class="m-lamp" class:amber={lamp !== 'syncing' && lamp !== 'in step'} class:busy={vault.busy}>{lamp}</span></h3>
    <MRow title="Folder" desc={vault.opts.name || 'None picked: choose the folder your Obsidian app uses'}><MButton size="sm" onclick={pick} disabled={vault.busy}>{vault.opts.uri ? 'Change' : 'Choose'}</MButton></MRow>
    {#if vault.opts.on}
      <MRow title="Keep in step with the PC" desc={vault.stopping ? 'Stopping after this file' : 'When the app opens and every 2 minutes'}><MButton size="sm" disabled={vault.stopping} onclick={() => setOn(false)}>{vault.stopping ? 'Stopping…' : 'Stop syncing'}</MButton></MRow>
    {:else}
      <MRow title="Keep in step with the PC" desc={vault.busy ? 'Stopping after this file' : vault.outcome === 'stopped' ? vault.line : 'Two ways. The PC needs Sync my Obsidian vault on too (Settings > Obsidian & map)'}><MButton variant="pri" size="sm" disabled={!vault.opts.uri || vault.busy} onclick={() => setOn(true)}>Start syncing</MButton></MRow>
    {/if}
    {#if vault.brake}<div class="m-err" style="margin:0">{vault.brake}<MButton size="sm" onclick={() => runVault(true)}>Apply anyway</MButton></div>{/if}
    {#if vault.legacy > 0}
      <MRow title="Old Brainamon pages" desc={`${vault.legacy} page${vault.legacy === 1 ? '' : 's'} of the old Content Manager folder ${vault.legacy === 1 ? 'is' : 'are'} still on this phone. Never sent to the PC.`}><MButton size="sm" disabled={vault.busy} onclick={removeOldPages}>Remove old Brainamon pages</MButton></MRow>
    {/if}
    <MHint>Files changed on both sides keep the PC's copy and add a "phone conflict" copy. Deleted files go to .trash. In a Brainamon vault, the pages Brainamon generates come from the PC only; your own files, and anything you add inside the Brainamon folder, go both ways. A classic export's Content Manager folder only comes from the PC. Plugins, themes and workspace files are not synced. This phone's name in vault sync: {deviceId()}.</MHint>
  </MBox>
{/if}
