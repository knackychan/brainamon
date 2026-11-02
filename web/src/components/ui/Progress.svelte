<script lang="ts">
  // A job's 12-segment bar (V6 .prog, as in the rail's Jobs): `pct` lights the segments done and sweeps the
  // next one; without `pct` one sweep crosses the whole bar (.prog.busy), for work that cannot be counted.
  let { label, pct }: { label: string; pct?: number } = $props()
  const lit = $derived(pct === undefined ? 0 : Math.min(12, Math.floor(12 * pct / 100)))
</script>

{#if pct === undefined}
  <div class="prog busy" role="progressbar" aria-label={label}><i class="lead"></i></div>
{:else}
  <div class="prog" role="progressbar" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
    {#each { length: 12 } as _, i (i)}<i class:lit={i < lit} class:lead={i === lit}></i>{/each}
  </div>
{/if}

<style>
  :global(.prog.busy) { grid-template-columns: minmax(0, 1fr); }
  :global(.prog i.lead) { background: linear-gradient(90deg, transparent, var(--accent), transparent) 0 0 / 40% 100% no-repeat; background-color: var(--seg-off); animation: progress-sweep 1s linear infinite; }
  @keyframes progress-sweep { to { background-position: 170% 0; } }
  :global(.motion-off .prog i.lead) { animation: none; background-size: 100% 100%; }
  @media (prefers-reduced-motion: reduce) { :global(.prog i.lead) { animation: none; background-size: 100% 100%; } }
</style>
