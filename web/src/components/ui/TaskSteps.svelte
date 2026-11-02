<script lang="ts">
  export interface TaskStep { label: string; state: 'done' | 'active' | 'waiting' }
  let { steps, running = true }: { steps: TaskStep[]; running?: boolean } = $props()
</script>

<ul class="task-steps" aria-label="Backup steps">
  {#each steps as step, index (index)}
    <li aria-current={step.state === 'active' ? 'step' : undefined}>
      <svg class:cycle={step.state === 'active' && running} width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        {#if step.state === 'active' && running}
          <circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="24 11" />
        {:else}
          <rect x="1.5" y="1.5" width="13" height="13" rx="2" fill="none" stroke="currentColor" />
          {#if step.state === 'done'}<path d="m4 8 2.5 2.5L12 5" fill="none" stroke="currentColor" stroke-width="1.8" />{/if}
        {/if}
      </svg>
      <span>{step.label}{' '}<small> · {step.state === 'done' ? 'done' : step.state === 'waiting' ? 'waiting' : running ? 'in progress' : 'paused'}</small></span>
    </li>
  {/each}
</ul>

<style>
  .task-steps { list-style: none; padding: 0; margin: .4em 0; }
  li { display: flex; align-items: flex-start; gap: .6em; margin: .3em 0; }
  svg { flex: none; margin-top: .15em; }
  small { font: inherit; }
  .cycle { animation: task-cycle 1s linear infinite; }
  :global(.motion-off) .cycle { animation: none; }
  @keyframes task-cycle { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .cycle { animation: none; } }
</style>
