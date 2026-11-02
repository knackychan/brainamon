<script lang="ts">
  // 06 Tags: the 14 most used tags as chips (click toggles the tag filter), and clear.
  import Wg from './Wg.svelte'
  import { lib, setFilter, tagsOf } from '../../../lib/library.svelte'

  const top = $derived.by(() => {
    const m = new Map<string, number>()
    for (const r of lib.pool) for (const t of tagsOf(r)) m.set(t, (m.get(t) ?? 0) + 1)
    return [...m].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 14)
  })
</script>

<Wg cls="s6" id="tags" title="Tags" jp="タグ" n={top.length}>
  <div class="tchips" id="tags-g" role="group" aria-label="Tags">
    {#each top as [t, n] (t)}<button type="button" class="tchip" aria-pressed={lib.tag === t} onclick={() => setFilter('tag', t)}>{t}<span>{n}</span></button>{/each}
    <button type="button" class="tchip" aria-pressed="false" title="Clear the tag filter" onclick={() => (lib.tag = 'all')}>✕ clear</button>
  </div>
</Wg>
