<script lang="ts">
  // The mat header (V6 paintLibChrome): title, pills from the visible rows, filter chips (each one
  // removes its filter), Grid / List, the zoom pill.
  import { clearFilters, lib, NEED, NEED_LABEL, setFilter, Z, type NeedKey } from '../../lib/library.svelte'
  import { fitAll, setZoom } from '../../lib/map'

  const L = $derived(lib.visible)
  const pills = $derived.by(() => {
    let reels = 0, described = 0, thumbs = 0
    for (const r of L) { if (r.type === 'Reel') reels++; if (r.ai) described++; if (r.thumb) thumbs++ }
    return [['items', L.length, 'var(--felt-ink)', ''], ['reels', reels, '#9df6d2', ''],
      ['described', described, 'var(--gold)', ' hide-m'], ['thumbs', thumbs, '#8fe9ff', ' hide-m']] as [string, number, string, string][]
  })
  const chips = $derived.by(() => {
    const act: [string, string, string][] = []
    const q = lib.q.trim()
    if (q) act.push(['q', `“${q}”${lib.rank ? ' · by meaning' : ''}`, 'search'])
    if (lib.cat !== 'all') act.push(['cat', lib.cat, 'collection'])
    if (lib.tag !== 'all') act.push(['tag', '#' + lib.tag, 'tag'])
    if (lib.type !== 'all') act.push(['type', lib.type, 'type'])
    for (const [k, bit] of Object.entries(NEED) as [NeedKey, number][]) if (lib.status & bit) act.push(['st:' + bit, NEED_LABEL[k].toLowerCase(), 'status'])
    if (lib.creator !== 'all') act.push(['creator', lib.creator, 'creator'])
    if (lib.src !== 'all') act.push(['src', lib.src, 'source'])
    if (lib.fav !== 'all') act.push(['fav', '★ Favourites', 'favourites'])
    return act
  })
  const pct = $derived(Math.round(Z[lib.zi] / 196 * 100) + '%')
  const list = $derived(lib.view === 'list')
</script>

<div class="mat-hd">
  <p class="brand"><i></i><span class="lib-t" id="lib-t">{lib.cat === 'all' ? 'All items' : lib.cat}</span><span class="jp" aria-hidden="true">ライブラリ</span></p>
  <div class="spills" id="spills">
    {#each pills as [l, v, k, c] (l)}<span class={'spill' + c} style:--k={k}><i></i><b>{v}</b>{l}</span>{/each}
  </div>
  <div class="fchips" id="fchips">
    {#each chips as [k, l, w] (k)}<button type="button" class="fchip" aria-label={`Remove ${w} filter ${l}`} onclick={() => clearFilters(k)}>{l}<span aria-hidden="true">×</span></button>{/each}
  </div>
  <span class="msp"></span>
  <div class="vsw" role="group" aria-label="View">
    <button type="button" aria-pressed={!list} onclick={() => setFilter('view', 'grid')}>Grid</button>
    <button type="button" aria-pressed={list} onclick={() => setFilter('view', 'list')}>List</button>
  </div>
  <div class="zpill" role="group" aria-label="Zoom">
    <button type="button" id="zout" aria-label="Zoom out" disabled={lib.zi === 0 || list} onclick={() => setZoom(lib.zi - 1)}>−</button>
    <output id="zpct" aria-live="polite">{pct}</output>
    <button type="button" id="zin" aria-label="Zoom in" disabled={lib.zi === Z.length - 1 || list} onclick={() => setZoom(lib.zi + 1)}>+</button>
    <button type="button" id="zfit" disabled={list} onclick={fitAll}>Fit</button>
  </div>
</div>
