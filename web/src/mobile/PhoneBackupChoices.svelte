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
  import TaskSteps from '../components/ui/TaskSteps.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import DeletionEstimate from '../components/ui/DeletionEstimate.svelte'
  import { amount } from '../lib/backup'

  let { onclose }: { onclose?: () => void } = $props()
  let choices = $state<PhoneBackup[]>([]), selected = $state(''), busy = $state(false), error = $state(''), listed = $state(false)
  let action = $state<'' | 'replace' | 'delete'>('')
  let alive = true
  const m = mirrorSource
  const connected = $derived((phone.tokenAt, phone.signIn, error, backup.error, m && token(m.pair)))
  const taskSteps = $derived.by(() => {
    const task = backup.task
    if (!task) return []
    const phase = task.phase
    const active = task.kind === 'delete' ? (phase === 'disconnect' || phase === 'done' ? 1 : 0)
      : phase === 'prepare' ? 0 : phase === 'upload' ? task.uploaded ? 2 : 1 : phase === 'install' ? 2 : 3
    const labels = task.kind === 'delete' ? [t('backup.task.deleteSelected'), t('backup.task.disconnect')]
      : [t('backup.task.prepare'), t('backup.task.backupAgain', { items: task.items !== undefined ? t('backup.task.itemProgress', { n: task.items, done: fmtNum(task.uploaded ? task.items : 0, 'en'), total: fmtNum(task.items, 'en') }) : '', files: task.uploaded ? '1 / 1' : '0 / 1' }), t('backup.task.checkReplacement'), t('backup.task.deleteOld')]
    return labels.map((label, i) => ({ label, state: phase === 'done' || i < active ? 'done' as const : i === active ? 'active' as const : 'waiting' as const }))
  })
  const deleted = $derived(backup.deleted ?? backup.task?.removed ?? 0)
  const label = (b: PhoneBackup) => t('backup.task.choice', { n: b.files, name: t(b.current ? 'backup.task.thisBackup' : 'backup.task.phoneBackup'), id: b.prefix.slice(5, 13), files: fmtNum(b.files, 'en') })
  async function list() {
    busy = true; error = ''; action = ''; selected = ''; choices = []
    try { const found = await listPhoneBackups(); if (alive) { choices = found; listed = true; if (found.length === 1) selected = found[0].prefix } }
    catch (e) { if (alive) error = nativeError('backup', e) }
    finally { if (alive) busy = false }
  }
  onMount(() => { if (!backup.task && connected) void list(); return () => { alive = false } })
</script>

<MBox id="phone-backup-choices">
  <h3>{backup.task ? t('backup.task.savedTitle') : t('backup.task.chooseTitle')}<MInfo title={t('backup.help.manageTitle')}>
    <p>{t('backup.warning.lostKey')}</p>
    <p>{t('backup.help.choices')}</p>
    <p>{t('backup.warning.taskSync')}</p>
  </MInfo></h3>
  {#if backup.task}
    <MHint>{backup.task.kind === 'replace' ? t('backup.task.replaceTitle') : t('backup.task.deleteTitle')} · {backup.task.account}</MHint>
    <MHint role="status">{backup.busy ? backup.task.paused ? t('backup.task.pausingRequest') : backup.step : backup.task.paused ? t('backup.task.pausedSaved') : t('backup.task.retrySaved')}</MHint>
    <TaskSteps words={phoneWords} steps={taskSteps} running={backup.busy && !backup.task.paused} />
    {#if backup.task.phase === 'delete'}
      <Progress label={t('backup.task.deleting')} pct={backup.task.files.length ? 100 * deleted / backup.task.files.length : undefined} />
      {#if backup.busy && !backup.task.paused && !backup.error && deleted < backup.task.files.length}
        <MHint><DeletionEstimate words={phoneWords} locale={phoneLocale()} done={deleted} total={backup.task.files.length} /></MHint>
      {/if}
      <MHint>{t('backup.task.deleted', { done: fmtNum(deleted, 'en'), total: fmtNum(backup.task.files.length, 'en') })}{#if backup.busy && !backup.task.paused && deleted < backup.task.files.length}{' '}{t('backup.task.waitGoogle')}{/if}</MHint>
    {:else if backup.task.kind === 'replace' && backup.task.phase !== 'prepare'}
      <Progress label={t('backup.task.upload')} pct={backup.task.uploaded ? 100 : undefined} />
      <MHint>{t('backup.task.contents', { items: backup.task.items === undefined ? t('backup.task.theLibrary') : t('backup.task.items', { n: backup.task.items, items: fmtNum(backup.task.items, 'en') }), size: backup.task.bytes ? ` (${backup.task.bytes < 1048576 ? `${fmtNum(Math.ceil(backup.task.bytes / 1024), 'en')} ${t('common.size.kb')}` : amount(backup.task.bytes, phoneWords)})` : '' })}</MHint>
    {/if}
    {#if backup.error}<MHint tone="error" role="alert">{backup.error}</MHint>{/if}
    <div class="m-row" style="flex-wrap:wrap">
      {#if backup.busy}<MButton size="sm" disabled={backup.task.paused} onclick={pauseBackup}>{t('backup.action.pause')}</MButton>
      {:else}<MButton variant="pri" size="sm" onclick={() => m && runBackup(m.changes)}>{backup.task.paused ? t('backup.action.resumeTask') : t('backup.action.retryTask')}</MButton>{/if}
      {#if !connected}<MButton size="sm" onclick={() => connectDrive()}>{t('backup.action.signIn')}</MButton>{/if}
    </div>
    <MHint>{t('backup.warning.localTask')}</MHint>
  {:else}
    {#if !connected}<MButton size="sm" onclick={() => connectDrive()}>{t('backup.action.connectDrive')}</MButton>{/if}
    <MButton size="sm" disabled={busy || !connected} onclick={list}>{busy ? t('backup.task.finding') : t('backup.action.refreshList')}</MButton>
    {#if choices.length}
      <label class="m-fld"><span>{t('backup.task.selectedLabel')}</span><select bind:value={selected} disabled={backup.busy} onchange={() => action = ''}><option value="">{t('backup.task.choose')}</option>{#each choices as b (b.prefix)}<option value={b.prefix}>{label(b)}</option>{/each}</select></label>
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
  {/if}
  {#if onclose}<MTextButton onclick={() => { onclose?.(); if (cloudStopped() && !backup.task && !backup.busy) location.reload() }}>{t('common.close')}</MTextButton>{/if}
</MBox>
