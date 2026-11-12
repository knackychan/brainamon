<script lang="ts">
  import { t } from '../lib/i18n/index.ts'
  import { phoneWords } from './settings-words'
  import { backup } from './backup.svelte'
  import { syncLanes } from './lanes'
  import { taskSteps } from './settings-steps'
  import MRunBar from './ui/MRunBar.svelte'
  import './tools.css'
  const steps = $derived(backup.task ? taskSteps(backup.task, backup.busy, backup.error, phoneWords) : [])
  const done = $derived(steps.filter(s => s.kind === 'done').length)
  const lanes = $derived(syncLanes().filter(l => l.active && l.tag === 'running' && ['drive', 'vault'].includes(l.key)))
</script>
{#if backup.task}
  <MRunBar lead={backup.step || steps[done]?.label || ''} right={t('common.step', { n: Math.min(done + 1, steps.length), total: steps.length })} total={steps.length} {done} run={backup.busy && !backup.task.paused} label={t('backup.task.stepsLabel')} />
{:else}
  {#each lanes as l (l.key)}
    <MRunBar lead={l.text} right={l.pct === null ? '…' : `${l.pct}%`} total={100} done={l.pct ?? 0} indeterminate={l.pct === null} run label={t('settings.sync.progress', { name: l.name })} />
  {/each}
{/if}
