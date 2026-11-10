<script lang="ts">
  import { phoneWords, lampLabel } from './settings-words'
  import { t } from '../lib/i18n/index.ts'
  // Settings > Obsidian, one group (Fred 2026-11-04; projects/phone-settings, ui/MGroup.svelte): the vault sync with the
  // PC (Android app, paired phone only: the folder, Start / Stop), then the vault name Open in Obsidian uses (every
  // phone). The rounds run from vault/auto.svelte.ts (foreground, every 2 minutes, Sync now); where the phone's and
  // the PC's rounds are (the line, the bar, Sync now) is in Settings > Sync (lanes.ts).
  // The sync depends on Google Drive, so it reads the Drive box's own status (state.svelte.ts driveStatus): when Drive
  // is not usable the lamp says so instead of "in step". The row says the vault's name and, while it syncs, the lamp.
  import { isApp } from './native'
  import { driveStatus, phoneStatus, solo, source } from './state.svelte'
  import { pickVaultFolder as pick, removeOldPages, runVault, setVaultOn as setOn, vault, watchPc } from './vault/auto.svelte'
  import { deviceId } from './mirror/pairing'
  import { syncPaused } from './network.svelte'
  import { setVaultName, vaultName } from './obsidian'
  import { vaultLine, vaultTone } from './settings-lines'
  import MButton from './ui/MButton.svelte'
  import MGroup from './ui/MGroup.svelte'
  import MRow from './ui/MRow.svelte'

  const syncing = $derived(isApp && !solo && !!source.syncVault)
  const drive = $derived(driveStatus())
  // a group key is orange only while the status above offers no key (spec section 6.3)
  const lead = $derived(!phoneStatus()?.action)
  $effect(() => { if (isApp && !solo && vault.opts.on && drive.ok && source.vaultPc) return watchPc() })
  const lamp = $derived(
    vault.opts.on && syncPaused() ? 'paused' : vault.stopping ? 'stopping' : vault.busy ? 'syncing' : vault.queued ? 'queued' : !vault.opts.uri ? 'no folder' : !vault.opts.on ? 'off' : !drive.ok ? 'needs Drive'
    : vault.brake ? 'held' : vault.outcome === 'error' ? 'error' : vault.outcome === 'waiting' ? 'waiting for PC' : vault.outcome === 'ok' ? 'in step' : 'not run yet')
  let name = $state('')
  // reread when the folder changes (Choose here or in the Sync group saves the folder's name)
  $effect(() => { name = vaultName(source.obsidianVault?.() ?? '', vault.opts.name) })
</script>

<MGroup title="Obsidian" id={syncing ? 'm-vault' : undefined} line={vaultLine({ name: name.trim(), syncing, lamp: lampLabel(lamp) }, phoneWords)} tone={vaultTone(lamp, syncing)}>
  {#snippet info()}
    {#if syncing}
      <p>{t('settings.vault.folderHelp')}</p>
      <p>{t('settings.vault.conflictHelp')}</p>
      <p>{t('settings.vault.generatedHelp')}</p>
      <p>{t('settings.vault.plugins', { device: deviceId() })}</p>
    {/if}
    <p>{t('settings.vault.openHelp', { pc: source.obsidianVault?.() ? t('settings.vault.pcName', { name: source.obsidianVault() }) : '' })}</p>
    <p>{t('settings.vault.exportHelp')}</p>
  {/snippet}
  {#if syncing}
    <MRow title={t('settings.vault.folder')} desc={vault.opts.name || t('settings.vault.choose')}><MButton size="sm" onclick={pick} disabled={vault.busy}>{vault.opts.uri ? t('settings.vault.change') : t('settings.vault.chooseAction')}</MButton></MRow>
    {#if vault.opts.on}
      <MRow title={t('settings.vault.syncPc')} desc={vault.stopping ? t('settings.vault.stopping') : t('settings.vault.every')}><MButton size="sm" disabled={vault.stopping} onclick={() => setOn(false)}>{vault.stopping ? t('settings.vault.stoppingShort') : t('settings.vault.stop')}</MButton></MRow>
    {:else}
      <MRow title={t('settings.vault.syncPc')} desc={vault.busy ? t('settings.vault.stopping') : vault.outcome === 'stopped' ? vault.line : t('settings.vault.off')}><MButton variant={lead ? 'pri' : 'default'} size="sm" disabled={!vault.opts.uri || vault.busy} onclick={() => setOn(true)}>{t('settings.vault.start')}</MButton></MRow>
    {/if}
    {#if vault.brake}<div class="m-err" style="margin:0">{vault.brake}<MButton size="sm" onclick={() => runVault(true)}>{t('settings.vault.apply')}</MButton></div>{/if}
    {#if vault.legacy > 0}
      <MRow title={t('settings.vault.oldPages')} desc={t('settings.vault.legacy', { n: vault.legacy })}><MButton size="sm" aria-label={t('settings.vault.removeOldLabel')} disabled={vault.busy} onclick={removeOldPages}>{t('settings.storage.remove')}</MButton></MRow>
    {/if}
  {/if}
  <MRow title={t('settings.vault.name')} desc={t('settings.vault.nameHint')} />
  <label class="m-fld" style="min-height:44px"><input bind:value={name} onchange={() => setVaultName(name)} placeholder={t('settings.vault.namePlaceholder')} aria-label={t('settings.vault.nameLabel')} autocomplete="off" /></label>
</MGroup>
