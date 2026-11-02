<script lang="ts">
  import { onMount } from 'svelte'
  import { backup, pauseBackup, runBackup } from './backup.svelte'
  import { listPhoneBackups, type PhoneBackup } from './mirror/phone-backup'
  import { mirrorSource, phone, connectDrive } from './state.svelte'
  import { token } from './mirror/pairing'
  import { cloudStopped } from './mirror/gate'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'
  import MTextButton from './ui/MTextButton.svelte'
  import TaskSteps from '../components/ui/TaskSteps.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import DeletionEstimate from '../components/ui/DeletionEstimate.svelte'
  import { amount, num } from '../lib/backup'

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
    const labels = task.kind === 'delete' ? ['Delete selected backup files', 'Disconnect backup']
      : ['Prepare replacement backup', `Back up again${task.items !== undefined ? ` · ${num(task.uploaded ? task.items : 0)} / ${num(task.items)} item${task.items === 1 ? '' : 's'}` : ''} · ${task.uploaded ? '1 / 1' : '0 / 1'} file`, 'Check replacement backup', 'Delete old backup files']
    return labels.map((label, i) => ({ label, state: phase === 'done' || i < active ? 'done' as const : i === active ? 'active' as const : 'waiting' as const }))
  })
  const deleted = $derived(backup.deleted ?? backup.task?.removed ?? 0)
  const label = (b: PhoneBackup) => `${b.current ? 'This phone’s backup' : 'Phone backup'} · ${b.prefix.slice(5, 13)} · ${b.files} file${b.files === 1 ? '' : 's'}`
  async function list() {
    busy = true; error = ''; action = ''; selected = ''; choices = []
    try { const found = await listPhoneBackups(); if (alive) { choices = found; listed = true; if (found.length === 1) selected = found[0].prefix } }
    catch (e) { if (alive) error = (e as Error).message }
    finally { if (alive) busy = false }
  }
  onMount(() => { if (!backup.task && connected) void list(); return () => { alive = false } })
</script>

<MBox id="phone-backup-choices">
  <h3>{backup.task ? 'Saved backup task' : 'Choose a phone backup'}</h3>
  {#if backup.task}
    <MHint>{backup.task.kind === 'replace' ? 'Replace selected phone backup' : 'Delete selected phone backup and disconnect'} · {backup.task.account}</MHint>
    <MHint role="status">{backup.busy ? backup.task.paused ? 'Pausing after the current request…' : backup.step : backup.task.paused ? 'Paused. This task stays saved when you leave or restart.' : 'Task saved. Retry to continue from the last completed step.'}</MHint>
    <TaskSteps steps={taskSteps} running={backup.busy && !backup.task.paused} />
    {#if backup.task.phase === 'delete'}
      <Progress label="Deleting old backup files" pct={backup.task.files.length ? 100 * deleted / backup.task.files.length : undefined} />
      {#if backup.busy && !backup.task.paused && !backup.error && deleted < backup.task.files.length}
        <MHint><DeletionEstimate done={deleted} total={backup.task.files.length} /></MHint>
      {/if}
      <MHint>{num(deleted)} / {num(backup.task.files.length)} files deleted.{#if backup.busy && !backup.task.paused && deleted < backup.task.files.length}{' '}Waiting for Google Drive to confirm the next files…{/if}</MHint>
    {:else if backup.task.kind === 'replace' && backup.task.phase !== 'prepare'}
      <Progress label="Replacement backup upload" pct={backup.task.uploaded ? 100 : undefined} />
      <MHint>This backup contains {backup.task.items === undefined ? 'the library' : `${num(backup.task.items)} item${backup.task.items === 1 ? '' : 's'}`} and queued edits in one encrypted file{backup.task.bytes ? ` (${backup.task.bytes < 1048576 ? `${num(Math.ceil(backup.task.bytes / 1024))} KB` : amount(backup.task.bytes)})` : ''}. The file is counted after Google confirms the upload.</MHint>
    {/if}
    {#if backup.error}<MHint tone="error" role="alert">{backup.error}</MHint>{/if}
    <div class="m-row" style="flex-wrap:wrap">
      {#if backup.busy}<MButton size="sm" disabled={backup.task.paused} onclick={pauseBackup}>Pause</MButton>
      {:else}<MButton variant="pri" size="sm" onclick={() => m && runBackup(m.changes)}>{backup.task.paused ? 'Resume task' : 'Retry task'}</MButton>{/if}
      {#if !connected}<MButton size="sm" onclick={() => connectDrive()}>Sign in again</MButton>{/if}
    </div>
    <MHint>Local content and queued edits stay here. Other backups stay in Drive. Normal sync waits until this task finishes.</MHint>
  {:else}
    <MHint>A lost key cannot decrypt old content. Keep this phone’s local library and replace one selected backup, or delete that backup and disconnect.</MHint>
    <MHint>Only standalone phone backups appear here. The short ID distinguishes backups; encrypted names cannot tell us which phone made them. Recovery files and independent copies stay where they were saved.</MHint>
    {#if !connected}<MButton size="sm" onclick={() => connectDrive()}>Connect Google Drive</MButton>{/if}
    <MButton size="sm" disabled={busy || !connected} onclick={list}>{busy ? 'Finding backups…' : 'Refresh backup list'}</MButton>
    {#if choices.length}
      <label class="m-fld"><span>Selected phone backup</span><select bind:value={selected} disabled={backup.busy} onchange={() => action = ''}><option value="">Choose a backup…</option>{#each choices as b (b.prefix)}<option value={b.prefix}>{label(b)}</option>{/each}</select></label>
      {#if selected}<MHint>Selected: {label(choices.find(b => b.prefix === selected)!)}. Account: {m?.pair.g}.</MHint>{/if}
      {#if !action}
        <div class="m-row" style="flex-wrap:wrap">
          <MButton size="sm" disabled={!selected || backup.busy} onclick={() => action = 'replace'}>Replace with this phone’s content…</MButton>
          <MTextButton tone="danger" disabled={!selected || backup.busy} onclick={() => action = 'delete'}>Delete backup and disconnect…</MTextButton>
        </div>
      {:else}
        <MHint role="alert">{action === 'replace' ? 'This phone’s local content and queued edits stay. A complete replacement is uploaded and checked before the selected old files are deleted. Content found only in that old backup will be lost. Other phones using its old key must reconnect using the new code. Set up recovery again after replacement.' : 'The selected backup files will be deleted from Google Drive, then this phone will disconnect. Content found only in those files will be lost. This phone’s local library and queued edits stay.'}</MHint>
        <div class="m-row" style="flex-wrap:wrap">
          <MButton variant="pri" size="sm" disabled={backup.busy} onclick={() => m && runBackup(m.changes, action || undefined, selected)}>{backup.busy ? 'Stopping previous work…' : action === 'replace' ? 'Confirm replacement' : 'Confirm delete and disconnect'}</MButton>
          <MTextButton disabled={backup.busy} onclick={() => action = ''}>Cancel</MTextButton>
        </div>
      {/if}
    {:else if listed && !busy}<MHint>No standalone phone backup remains in this account. Local content stays here; return to Backup &amp; phones to back it up.</MHint>{/if}
    {#if error || backup.error}<MHint tone="error" role="alert">{error || backup.error}</MHint>{/if}
  {/if}
  {#if onclose}<MTextButton onclick={() => { onclose?.(); if (cloudStopped() && !backup.task && !backup.busy) location.reload() }}>Close</MTextButton>{/if}
</MBox>
