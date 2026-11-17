<script lang="ts">
  // 04 Status: show items that need any of the ticked steps (OR, as the app), with counts.
  import { untrack } from 'svelte'
  import { live } from '../../../lib/events.svelte'
  import Count from '../../../lib/motion/Count.svelte'
  import { DELTA_MS } from '../../../lib/motion/motion.ts'
  import Segs from './Segs.svelte'
  import Wg from './Wg.svelte'
  import { runCmd } from '../../../lib/commands'
  import { lib, NEED, NEED_LABEL, toggleStatus, type NeedKey } from '../../../lib/library.svelte'

  const keys = Object.keys(NEED) as NeedKey[]
  const counts = $derived.by(() => {
    const c: Record<string, number> = {}
    for (const k of keys) c[k] = 0
    for (const r of lib.pool) for (const k of keys) if (r.nd & NEED[k]) c[k]++
    return c
  })
  const total = $derived(Math.max(1, lib.pool.length))
  let base: { id: number; k: NeedKey; n: number } | null = null
  let ended = $state<{ id: number; k: NeedKey; n: number } | null>(null)
  const delta = $derived(ended ? ended.n - counts[ended.k] : 0)
  $effect(() => {
    const job = live.jobs.current, held = live.finished
    untrack(() => {
      if (base && held?.id === base.id) {
        const id = base.id
        ended = { ...base }
        base = null
        // No effect cleanup: later job snapshots must not cancel the delta's expiry.
        setTimeout(() => { if (ended?.id === id) ended = null }, DELTA_MS)
      }
      if (job && Object.hasOwn(NEED, job.kind) && base?.id !== job.id) {
        const k = job.kind as NeedKey
        base = { id: job.id, k, n: counts[k] }
      }
    })
  })
</script>

<Wg cls="s6" id="status" title="Status" jp="状態" n="OR">
  <div class="rove" role="group" aria-label="Status: show items that need any of these" data-rove id="status-g">
    {#each keys as k, i (k)}
      <button type="button" class="tr mt" role="checkbox" aria-checked={(lib.status & NEED[k]) !== 0} tabindex={i === 0 ? 0 : -1} onclick={() => toggleStatus(NEED[k])}>
        <span class="l">{NEED_LABEL[k]}{#if ended?.k === k && delta > 0}<em class="mo-delta">−{delta}</em>{/if}</span><Segs lit={Math.min(10, Math.ceil(counts[k] / total * 40))} k="var(--accent)" /><Count class={ended?.k === k ? 'c mo-okc' : 'c'} value={counts[k]} jump={`${lib.loaded}|${lib.showHidden}|${lib.cat}`} />
      </button>
    {/each}
  </div>
  <p class="wg-ln"><span>Show items missing any checked step. Video analysis is optional.</span><button type="button" class="linkk" onclick={() => runCmd('clear-status')}>Clear</button></p>
  <button type="button" class="linkk" onclick={() => runCmd('process-items')}>Choose a processing step…</button>
</Wg>

<style>
  .wg-ln { white-space: normal; line-height: 1.4 }
  .wg-ln button { flex: 0 0 auto }
</style>
