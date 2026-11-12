<script lang="ts">
  import { phoneWords, phoneLocale, nativeError } from './settings-words'
  import { fmtNum } from '../lib/i18n/format.ts'
  import { t } from '../lib/i18n/index.ts'
  import { onMount } from 'svelte'
  import { backup, pauseBackup, runBackup } from './backup.svelte'
  import { listPhoneBackups, type PhoneBackup } from './mirror/phone-backup'
  import { mirrorSource, phone, connectDrive } from './state.svelte'
  import { token } from './mirror/pairing'
  import { cloudStopped } from './mirror/gate'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'
  import MInfo from './ui/MInfo.svelte'
  import MTextButton from './ui/MTextButton.svelte'
  import MSteps from './ui/MSteps.svelte'
  import MCard from './ui/MCard.svelte'
  import MStatus from './ui/MStatus.svelte'
  import MRunBar from './ui/MRunBar.svelte'
  import MPicker from './ui/MPicker.svelte'
  import { taskSteps as stepsForTask } from './settings-steps'
  import './tools.css'
  import { amount } from '../lib/backup'

  let { onclose, page = false }: { onclose?: () => void; page?: boolean } = $props()
  let choices = $state<PhoneBackup[]>([]), selected = $state(''), busy = $state(false), error = $state(''), listed = $state(false)
  let action = $state<'' | 'replace' | 'delete'>('')
  let alive = true
  const m = mirrorSource
  const connected = $derived((phone.tokenAt, phone.signIn, error, backup.error, m && token(m.pair)))
  const taskSteps = $derived(backup.task ? stepsForTask(backup.task, backup.busy, backup.error, phoneWords) : [])
  const done = $derived(taskSteps.filter(s => s.kind === 'done').length)
  const deleted = $derived(backup.deleted ?? backup.task?.removed ?? 0)
  const label = (b: PhoneBackup) => t('backup.task.choice', { n: b.files, name: t(b.current ? 'backup.task.thisBackup' : 'backup.task.phoneBackup'), id: b.prefix.slice(5, 13), files: fmtNum(b.files, 'en') })
  async function list() {
    busy = true; error = ''; action = ''; selected = ''; choices = []
    try { const found = await listPhoneBackups(); if (alive) { choices = found; listed = true; if (found.length === 1) selected = found[0].prefix } }
    catch (e) { if (alive) error = nativeError('backup', e) }
    finally { if (alive) busy = false }
  }
  onMount(() => {
    if (!backup.task && connected) void list()
    return () => {
      alive = false
      if (page && cloudStopped() && !backup.task && !backup.busy) location.reload()
    }
  })
</script>

<div id="phone-backup-choices" class="m-backup-manager">
  {#if page}<h1 class="m-page-title">{backup.task ? t('backup.task.savedTitle') : t('backup.task.chooseTitle')}</h1>
  {:else}<h2 class="m-page-title">{backup.task ? t('backup.task.savedTitle') : t('backup.task.chooseTitle')}</h2>{/if}
  {#if backup.task}
    <MStatus look="page" tone={backup.busy ? 'busy' : 'next'} kind={backup.error ? 'failed' : backup.task.paused ? 'paused' : backup.busy ? 'working' : 'attention'} text={backup.busy ? backup.task.paused ? t('backup.task.pausingRequest') : backup.step : backup.task.paused ? t('backup.task.pausedSaved') : t('backup.task.retrySaved')} detail={`${backup.task.kind === 'replace' ? t('backup.task.replaceTitle') : t('backup.task.deleteTitle')} · ${backup.task.account}`} />
    <MCard><MSteps steps={taskSteps} /></MCard>
    {#if backup.task.kind === 'replace' && backup.task.phase !== 'prepare'}<MHint>{t('backup.task.contents', { items: backup.task.items === undefined ? t('backup.task.theLibrary') : t('backup.task.items', { n: backup.task.items, items: fmtNum(backup.task.items, 'en') }), size: backup.task.bytes ? ` (${amount(backup.task.bytes, phoneWords)})` : '' })}</MHint>{/if}
    <MRunBar lead={backup.step || taskSteps[done]?.label || ''} strong={t('common.step', { n: Math.min(done + 1, taskSteps.length), total: taskSteps.length })} right={backup.task.phase === 'delete' ? t('backup.task.deleted', { done: fmtNum(deleted, 'en'), total: fmtNum(backup.task.files.length, 'en') }) : ''} total={backup.task.phase === 'delete' ? backup.task.files.length : taskSteps.length} done={backup.task.phase === 'delete' ? deleted : done} run={backup.busy && !backup.task.paused && !backup.error} label={t('backup.task.stepsLabel')}>
    {#if backup.error}<MHint tone="error" role="alert">{backup.error}</MHint>{/if}
    <div class="m-row" style="flex-wrap:wrap">
      {#if backup.busy}<MButton size="sm" disabled={backup.task.paused} onclick={pauseBackup}>{t('backup.action.pause')}</MButton>
      {:else}<MButton variant="pri" size="sm" onclick={() => m && runBackup(m.changes)}>{backup.task.paused ? t('backup.action.resumeTask') : t('backup.action.retryTask')}</MButton>{/if}
      {#if !connected}<MButton size="sm" onclick={() => connectDrive()}>{t('backup.action.signIn')}</MButton>{/if}
    </div>
    </MRunBar>
    <MHint>{t('backup.warning.localTask')}</MHint>
  {:else}
    <MCard>
    {#if !connected}<MButton size="sm" onclick={() => connectDrive()}>{t('backup.action.connectDrive')}</MButton>{/if}
    <MButton size="sm" disabled={busy || !connected} onclick={list}>{busy ? t('backup.task.finding') : t('backup.action.refreshList')}</MButton>
    {#if choices.length}
      <MPicker label={t('backup.task.selectedLabel')} options={[['', t('backup.task.choose')], ...choices.map(b => [b.prefix, label(b)] as [string, string])]} bind:value={selected} disabled={backup.busy} onchange={() => action = ''} />
      {#if selected}<MHint>{t('backup.task.selected', { backup: label(choices.find(b => b.prefix === selected)!), account: m?.pair.g })}</MHint>{/if}
      {#if !action}
        <div class="m-row" style="flex-wrap:wrap">
          <MButton size="sm" disabled={!selected || backup.busy} onclick={() => action = 'replace'}>{t('backup.action.replace')}</MButton>
          <MTextButton tone="danger" disabled={!selected || backup.busy} onclick={() => action = 'delete'}>{t('backup.action.deleteDisconnect')}</MTextButton>
        </div>
      {:else}
        <MHint role="alert">{action === 'replace' ? t('backup.warning.replace') : t('backup.warning.delete')}</MHint>
        <div class="m-row" style="flex-wrap:wrap">
          <MButton variant="pri" size="sm" disabled={backup.busy} onclick={() => m && runBackup(m.changes, action || undefined, selected)}>{backup.busy ? t('backup.task.stoppingPrevious') : action === 'replace' ? t('backup.action.confirmReplacement') : t('backup.action.confirmDeleteDisconnect')}</MButton>
          <MTextButton disabled={backup.busy} onclick={() => action = ''}>{t('common.cancel')}</MTextButton>
        </div>
      {/if}
    {:else if listed && !busy}<MHint>{t('backup.warning.noBackups')}</MHint>{/if}
    {#if error || backup.error}<MHint tone="error" role="alert">{error || backup.error}</MHint>{/if}
    </MCard>
  {/if}
  {#if onclose && !page}<MTextButton onclick={() => { onclose?.(); if (cloudStopped() && !backup.task && !backup.busy) location.reload() }}>{t('common.close')}</MTextButton>{/if}
</div>
