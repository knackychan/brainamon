<script lang="ts">
  // 05 Creator: a terminal list, the top 4 creators then "+N more" (the rest render only when opened).
  import Tr from './Tr.svelte'
  import Wg from './Wg.svelte'
  import { lib, setFilter } from '../../../lib/library.svelte'

  const SHOW = 4
  let open = $state(false)
  const list = $derived.by(() => {
    const m = new Map<string, number>()
    for (const r of lib.pool) if (r.creator) m.set(r.creator, (m.get(r.creator) ?? 0) + 1)
    return [...m].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  })
  const shown = $derived(open ? list : list.slice(0, SHOW))
</script>

<Wg cls="s6 term" id="creator" title="Creator" jp="作者" n={list.length}>
  <div class="rove" role="radiogroup" aria-label="Creator" data-rove>
    <Tr label="All creators" checked={lib.creator === 'all'} onpick={() => setFilter('creator', 'all')} />
    {#each shown as [c, n] (c)}<Tr label={c} count={n} checked={lib.creator === c} onpick={() => setFilter('creator', c)} />{/each}
    {#if list.length > SHOW}
      <button type="button" class="tr tr-more" tabindex="-1" aria-expanded={open} onclick={() => (open = !open)}><span class="l">{open ? '- show fewer' : `+${list.length - SHOW} more`}</span><span class="c"></span></button>
    {/if}
  </div>
</Wg>
