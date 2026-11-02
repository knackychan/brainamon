<script lang="ts">
  // 07 Type: All + each item type with its share bar.
  import Tr from './Tr.svelte'
  import Wg from './Wg.svelte'
  import { lib, setFilter } from '../../../lib/library.svelte'

  const BASE = ['Reel', 'Video', 'Post', 'Link', 'Recipe', 'Tutorial', 'Other']
  const counts = $derived.by(() => { const m = new Map<string, number>(); for (const r of lib.pool) if (r.type) m.set(r.type, (m.get(r.type) ?? 0) + 1); return m })
  const types = $derived([...BASE, ...[...counts.keys()].filter(t => !BASE.includes(t)).sort()])
  const max = $derived(Math.max(1, ...counts.values()))
</script>

<Wg cls="s3" id="type" title="Type" jp="種類" n={types.length}>
  <div class="rove" role="radiogroup" aria-label="Type" data-rove id="type-g">
    <Tr label="All" checked={lib.type === 'all'} meter={1} k="var(--wg-ink)" onpick={() => setFilter('type', 'all')} />
    {#each types as t (t)}
      {@const n = counts.get(t) ?? 0}
      <Tr label={t} count={n} checked={lib.type === t} meter={n / max} k="var(--wg-ink)" off={!n} onpick={() => setFilter('type', t)} />
    {/each}
  </div>
</Wg>
