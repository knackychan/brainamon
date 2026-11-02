<script lang="ts">
  // 11 Zoom: percentage, the ruler (click a step), - Fit +.
  import { lib, Z } from '../../../lib/library.svelte'
  import { fitAll, setZoom } from '../../../lib/map'
  const pct = $derived(Math.round(Z[lib.zi] / 196 * 100) + '%')
</script>

<section class="wg k s2" aria-labelledby="h-zoom">
  <header class="wg-hd"><h2 id="h-zoom">Zoom</h2><span class="n"></span><span class="jp" aria-hidden="true">拡大</span></header>
  <p class="dotn sm" id="n-zoom">{pct}</p>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="ruler" id="ruler" aria-hidden="true">
    {#each Z as _, i (i)}<i class:lit={i === lib.zi} class:below={i < lib.zi} onclick={() => setZoom(i)}></i>{/each}
  </div>
  <div class="zk">
    <button type="button" aria-label="Zoom out" onclick={() => setZoom(lib.zi - 1)}>−</button>
    <button type="button" aria-label="Fit all cards" onclick={fitAll}>Fit</button>
    <button type="button" aria-label="Zoom in" onclick={() => setZoom(lib.zi + 1)}>+</button>
  </div>
</section>
