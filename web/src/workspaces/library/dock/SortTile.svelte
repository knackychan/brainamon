<script lang="ts">
  // 09 Sort: Newest, Oldest, A to Z, Z to A, By type.
  import Tr from './Tr.svelte'
  import Wg from './Wg.svelte'
  import { lib, setFilter, SORTS } from '../../../lib/library.svelte'
</script>

<Wg cls="s2" id="sort" title="Sort" jp="並替" n={SORTS.length}>
  <div class="rove" role="radiogroup" aria-label="Sort" data-rove>
    {#each SORTS as [v, l] (v)}<Tr label={l} checked={lib.sort === v && !lib.rank} onpick={() => setFilter('sort', v)} />{/each}
  </div>
</Wg>
