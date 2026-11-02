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
