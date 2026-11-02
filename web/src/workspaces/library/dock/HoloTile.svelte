<script lang="ts">
  // 02 Holo: how many favourites (holo cards), and All / Favs.
  import Tr from './Tr.svelte'
  import Wg from './Wg.svelte'
  import { lib, setFilter } from '../../../lib/library.svelte'
  const n = $derived(lib.pool.reduce((s, r) => s + (r.fav ? 1 : 0), 0))
</script>

<Wg cls="y s3" id="holo" title="Holo" jp="お気に入り" n="★">
  <p class="dotn" id="n-fav">{String(n).padStart(2, '0')}</p><p class="wg-sub" id="holo-sub">favourites</p>
  <div class="rove h" role="radiogroup" aria-label="Show" data-rove>
    <Tr label="All" checked={lib.fav === 'all'} onpick={() => setFilter('fav', 'all')} />
    <Tr label="Favs" count={n} checked={lib.fav === 'fav'} onpick={() => setFilter('fav', 'fav')} />
  </div>
</Wg>
