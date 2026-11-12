<script lang="ts">
  import { t } from '../lib/i18n/index.ts'
  import { phoneWords } from './settings-words'
  import { backup } from './backup.svelte'
  import { phone } from './state.svelte'
  import { taskSteps } from './settings-steps'
  import MRunBar from './ui/MRunBar.svelte'
  import './tools.css'
  const steps = $derived(backup.task ? taskSteps(backup.task, backup.busy, backup.error, phoneWords) : [])
  const sync = $derived(phone.sync && !phone.sync.end ? phone.sync : null)
  const done = $derived(steps.length ? steps.filter(s => s.kind === 'done').length : sync?.steps.filter(s => ['ok', 'err'].includes(s.state)).length ?? 0)
  const current = $derived(sync?.steps.find(s => s.state === 'run'))
</script>
{#if backup.task}
  <MRunBar lead={backup.step || steps[done]?.label || ''} right={t('common.step', { n: Math.min(done + 1, steps.length), total: steps.length })} total={steps.length} {done} run={backup.busy && !backup.task.paused} label={t('backup.task.stepsLabel')} />
{:else if sync}
  <MRunBar lead={current ? `${current.label}${current.note ? ` · ${current.note}` : ''}` : t('shell.sync.starting')} right={t('common.step', { n: Math.min(done + 1, sync.steps.length), total: sync.steps.length })} total={sync.steps.length} {done} run label={t('shell.sync.title')} />
{:else if phone.read}
  <MRunBar lead={phone.read.text} right={`${Math.round(phone.read.frac * 100)}%`} total={100} done={Math.round(phone.read.frac * 100)} run label={t('shell.sync.title')} />
{/if}
