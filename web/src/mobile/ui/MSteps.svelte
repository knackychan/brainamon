<script lang="ts">
  import type { Step } from '../settings-steps'
  import { t } from '../../lib/i18n/index.ts'
  import MBadge from './MBadge.svelte'
  let { steps }: { steps: Step[] } = $props()
</script>
<ol class="m-steps" aria-label={t('backup.task.stepsLabel')}>
  {#each steps as step, i (i)}<li><MBadge kind={step.kind} small /><div><b>{step.label}</b>{#if step.tag}<span class="m-step-tag">{step.tag}</span>{/if}{#if step.line}<small>{step.line}</small>{:else}<span class="m-sr">{t(step.kind === 'done' ? 'backup.task.step.done' : step.kind === 'working' ? 'backup.task.step.active' : step.kind === 'paused' ? 'backup.task.step.paused' : 'backup.task.step.waiting')}</span>{/if}</div></li>{/each}
</ol>
