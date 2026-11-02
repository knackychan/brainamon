<script lang="ts">
  import { untrack } from 'svelte'
  import { num } from '../../lib/backup'

  let { done, total }: { done: number; total: number } = $props()
  let estimated = $state(0)
  let counter: HTMLSpanElement

  $effect(() => {
    const confirmed = done
    // Stay within the current 4 × 100 group and never estimate completion.
    const ceiling = Math.min(total - 1, (Math.floor(confirmed / 400) + 1) * 400 - 1)
    let count = Math.max(confirmed, Math.min(untrack(() => estimated), ceiling))
    estimated = count
    if (confirmed >= total) return
    const timer = setInterval(() => {
      if (matchMedia('(prefers-reduced-motion: reduce)').matches || counter?.closest('.motion-off')) return
      if (count < ceiling) estimated = ++count
    }, 80)
    return () => clearInterval(timer)
  })
</script>

<span bind:this={counter} class="deletion-estimate" aria-live="off">Estimated deletion: {num(Math.max(done, estimated))} / {num(total)} files.</span>

<style>
  .deletion-estimate { font-variant-numeric: tabular-nums; }
  :global(.motion-off) .deletion-estimate { display: none; }
  @media (prefers-reduced-motion: reduce) { .deletion-estimate { display: none; } }
</style>
