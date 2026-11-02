<script lang="ts">
  // 08 Source: All + the platforms (the server's platform table, export._platform_of).
  import Tr from './Tr.svelte'
  import Wg from './Wg.svelte'
  import { srcLabel } from '../../../lib/cards/card'
  import { lib, setFilter } from '../../../lib/library.svelte'

  const BASE = ['facebook', 'instagram', 'reddit', 'youtube']
  const counts = $derived.by(() => { const m = new Map<string, number>(); for (const r of lib.pool) m.set(r.src, (m.get(r.src) ?? 0) + 1); return m })
  const srcs = $derived([...BASE, ...['threads', 'tiktok', 'web'].filter(s => counts.get(s))])
  const total = $derived(Math.max(1, lib.pool.length))
</script>

<Wg cls="s s3" id="src" title="Source" jp="出典" n={srcs.length}>
  <div class="rove" role="radiogroup" aria-label="Source" data-rove id="src-g">
    <Tr label="All" checked={lib.src === 'all'} meter={1} k="var(--wg-ink)" onpick={() => setFilter('src', 'all')} />
    {#each srcs as s (s)}
      {@const n = counts.get(s) ?? 0}
      <Tr label={srcLabel(s)} count={n} checked={lib.src === s} meter={n / total} k="var(--wg-ink)" off={!n} onpick={() => setFilter('src', s)} />
    {/each}
  </div>
</Wg>
