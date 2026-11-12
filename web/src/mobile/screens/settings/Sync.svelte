<script lang="ts">
  import { t } from '../../../lib/i18n/index.ts'
  import { phoneWords, lampLabel } from '../../settings-words'
  import { driveStatus, phone, phoneStatus, solo, syncNow } from '../../state.svelte'
  import { network, setSyncPaused, setWifiOnly, syncPaused } from '../../network.svelte'
  import { backup } from '../../backup.svelte'
  import { syncLanes, syncSummary } from '../../lanes'
  import { SYNC_IDS } from '../../settings-lines'
  import { kindOf } from '../../settings-steps'
  import { runPhoneAction, actionBusy, actionLabel } from '../../actions'
  import { runVault, setVaultOn, vault } from '../../vault/auto.svelte'
  import { nativeSync } from '../../sync/native.svelte'
  import PageKeys from '../../PageKeys.svelte'
  import SettingsProgress from '../../SettingsProgress.svelte'
  import ShellIcon from '../../ShellIcon.svelte'
  import MCard from '../../ui/MCard.svelte'
  import MRow from '../../ui/MRow.svelte'
  import MButton from '../../ui/MButton.svelte'
  import MKey from '../../ui/MKey.svelte'
  import MTextButton from '../../ui/MTextButton.svelte'
  import MToggle from '../../ui/MToggle.svelte'
  import MStatus from '../../ui/MStatus.svelte'
  import MHint from '../../ui/MHint.svelte'
  import MRunBar from '../../ui/MRunBar.svelte'
  const st = $derived(phoneStatus())
  const own = $derived(!!st && SYNC_IDS.includes(st.id))
  const action = $derived(own && st?.action && ['retry', 'send'].includes(st.action.id) ? st.action : null)
  const lanes = $derived(syncLanes())
  const busy = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing)
  const gated = $derived(!!backup.task || backup.busy)
  const drive = $derived(driveStatus())
</script>

<PageKeys infoTitle={t('shell.sync.title')}>
  {#snippet info()}
    <p>{solo ? t('settings.sync.soloHelp') : t('settings.sync.pairedHelp')}</p>
    <p>{t('settings.sync.wifiHelp')}</p><p>{t('settings.sync.pauseHelp')}</p>
    {#if nativeSync.supported}<p>{t('settings.sync.native.schedule')}</p>{/if}
    {#if lanes.some(l => l.key === 'vault')}<p>{t('settings.sync.queueHelp')}</p>{/if}
  {/snippet}
</PageKeys>
<div class={['m-pad', 'm-calm', 'm-page', `k-${kindOf(st, backup.error)}`, 'm-wash-page']}>
  <h1 class="m-page-title">{t('shell.sync.title')}</h1>
  <MStatus look="page" tone={own && st ? st.tone : 'todo'} kind={own ? kindOf(st, backup.error) : 'empty'} text={own && st ? st.text : syncSummary()} detail={own && st ? st.detail : gated ? t('backup.warning.localTask') : ''}>
    {#if action}<MButton shape="pill" variant={action.primary ? 'pri' : 'default'} disabled={gated || actionBusy(action.id)} onclick={() => runPhoneAction(action.id)}>{actionLabel(action)}</MButton>
    {:else if gated || (st && ['attention', 'failed'].includes(kindOf(st, backup.error)))}<MButton as="a" shape="pill" href="#/backup">{t('backup.group.title')}<ShellIcon name="down" /></MButton>{/if}
  </MStatus>
  <div class="m-settings-chips">
    <MKey size="mid" wide disabled={gated || busy || syncPaused()} onclick={() => syncNow()}><ShellIcon name="sync" />{t('shell.sync.now')}</MKey>
    <MKey size="mid" wide disabled={network.pausePending} onclick={() => setSyncPaused(network.pauseFailed || !network.manualPause)}><ShellIcon name={network.manualPause ? 'play' : 'pause'} />{network.pausePending ? t('settings.sync.savingPolicy') : network.pauseFailed ? t('common.retry') : t(network.manualPause ? 'shell.sync.resume' : 'shell.sync.pause')}</MKey>
  </div>
  {#if gated}<MHint>{t('backup.warning.localTask')}</MHint>{/if}
  <SettingsProgress />
  {#if phone.sync?.end}<MHint role="status">{phone.sync.msg}</MHint>{/if}
  <MCard title={t('settings.sync.activity')}>
    {#each lanes as l (l.key)}
      <div class="m-lane">
        <MRow wrap title={l.name} desc={l.text}>
          <span class="m-step-tag">{lampLabel(l.tag)}</span>
          {#if l.key === 'vault'}
            {#if vault.opts.on && (vault.busy || vault.stopping)}<MTextButton onclick={() => setVaultOn(false)} disabled={vault.stopping}>{vault.stopping ? t('settings.sync.stopping') : t('settings.sync.stop')}</MTextButton>
            {:else if vault.opts.on}<MButton size="sm" onclick={() => runVault()} disabled={gated || vault.queued || !drive.ok || syncPaused()}>{vault.queued ? t('settings.sync.queued') : t('shell.sync.now')}</MButton>
            {:else}<MButton as="a" size="sm" href="#/more/obsidian">{vault.opts.uri ? t('settings.sync.start') : t('settings.sync.folder')}</MButton>{/if}
          {/if}
        </MRow>
        {#if l.files}
          <MHint>{t('backup.vault.verified', l.files)}</MHint>
        {/if}
        {#if l.active && (l.pct !== null || l.tag === 'running')}<MRunBar lead={l.text} right={l.pct === null ? '…' : `${l.pct}%`} total={100} done={l.pct ?? 0} indeterminate={l.pct === null} run={l.tag === 'running'} label={t('settings.sync.progress', { name: l.name })} />{/if}
      </div>
    {/each}
  </MCard>
  <MCard title={t('settings.sync.network')}>
    {#if nativeSync.supported}<MHint>{t('settings.sync.native.schedule')}</MHint>{/if}
    <MRow wrap title={t('settings.sync.wifi')} desc={network.wifiOnly ? t('settings.sync.waitWifi') : t('settings.sync.mobile')}><MToggle label={t('settings.sync.wifi')} on={network.wifiOnly} onchange={on => setWifiOnly(on)} /></MRow>
    {#if network.wifiOnly && network.ready && network.type === 'unknown'}<MHint>{t('settings.sync.unknownWifi')}</MHint>{/if}
  </MCard>
</div>
