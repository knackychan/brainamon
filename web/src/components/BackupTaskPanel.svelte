<script lang="ts">
  import type { ActId, TaskView } from '../lib/backup-state'
  import type { CloudTask } from '../lib/backup'
  import Button from './ui/Button.svelte'
  import DeletionEstimate from './ui/DeletionEstimate.svelte'
  import GroupBox from './ui/GroupBox.svelte'
  import Hint from './ui/Hint.svelte'
  import KeyIcon from './ui/KeyIcon.svelte'
  import Label from './ui/Label.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import TaskSteps from './ui/TaskSteps.svelte'
  import TextButton from './ui/TextButton.svelte'

  let { task, onaction, anchor = false, source = null, allowPrimary = true }: { task: TaskView; onaction: (id: ActId) => void; anchor?: boolean; source?: CloudTask | null; allowPrimary?: boolean } = $props()
  const words = (key: string) => key === 'backup.task.step.paused'
    ? (task.kind === 'failed' ? 'stopped' : task.primary?.id === 'restart' ? 'waiting for you' : 'paused') : undefined as unknown as string
  const head = $derived(task.kind === 'failed' ? `${task.title} stopped` : task.kind === 'paused'
    ? (task.primary?.id === 'restart' ? `${task.title}: your turn` : `${task.title} is paused`) : task.title)
  const reasonId = (id: ActId) => `${anchor ? 'backup' : 'overview'}-task-why-${id}`
</script>

<GroupBox aria-label="Task" active>
  <Label as="span" id={anchor ? 'set-s-sync-task' : undefined} tabindex={anchor ? -1 : undefined}>Task</Label>
  <div>
    <Status state={task.kind === 'working' ? 'busy' : 'next'} role="status" aria-live="polite">{head}</Status>
    <Hint>{task.line}{task.saved ? (task.running ? ' Saved: it continues from this step after a restart.' : ' This step is saved; stopped work stays stopped until resumed or retried.') : ''}</Hint>
    <TaskSteps steps={task.steps} running={task.running} {words} />
    {#if task.progress !== 'steps'}<Progress label={task.bar} pct={task.pct} paused={!task.running} />{/if}
    {#if task.running && source && ['reset_backup', 'switch_account', 'disconnect'].includes(source.kind) && ['cleanup', 'deleting'].includes(source.stage) && source.total > source.done}
      {#key source.id}<Hint><DeletionEstimate done={source.done} total={source.total} /></Hint>{/key}
    {/if}
    {#if task.error}<Hint tone="error" role="alert">{task.error}</Hint>{/if}
    {#each task.notes as note (note)}<Hint>{note}</Hint>{/each}
    {#if task.leave}<Hint>You can close Settings. Quitting Brainamon pauses this; it continues at the next start.</Hint>{/if}
    {#if task.also.length}
      <Hint>Also saved, waiting for this task:</Hint>
      {#each task.also as waiting (waiting.id)}<Hint>{waiting.title} · {waiting.stage}{waiting.error ? ` · ${waiting.error}` : ''}</Hint>{/each}
    {/if}
  </div>
  {#if task.primary || task.quiet.length}
    <span></span>
    <div><div class="frow">
      {#if task.primary}<Button variant={allowPrimary ? 'pri' : 'default'} size="sm" disabled={!!task.primary.why} aria-describedby={task.primary.why ? reasonId(task.primary.id) : undefined} onclick={() => onaction(task.primary!.id)}>{#if task.primary.icon}<KeyIcon name={task.primary.icon} />{/if}{task.primary.label}</Button>{/if}
      {#each task.quiet as action (action.id)}
        {#if action.icon}<Button size="sm" disabled={!!action.why} aria-describedby={action.why ? reasonId(action.id) : undefined} onclick={() => onaction(action.id)}><KeyIcon name={action.icon} />{action.label}</Button>
        {:else}<TextButton disabled={!!action.why} aria-describedby={action.why ? reasonId(action.id) : undefined} onclick={() => onaction(action.id)}>{action.label}</TextButton>{/if}
      {/each}
    </div>{#if task.primary?.why}<Hint id={reasonId(task.primary.id)}>{task.primary.why}</Hint>{/if}
    {#each task.quiet as action (action.id)}{#if action.why}<Hint id={reasonId(action.id)}>{action.why}</Hint>{/if}{/each}</div>
  {/if}
</GroupBox>
