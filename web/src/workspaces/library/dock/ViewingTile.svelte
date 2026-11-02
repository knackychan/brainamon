<script lang="ts">
  // 13 Viewing: the card you hover (or the first visible one), its position, and prev / tour / next.
  // The tour steps every 2.6 s and scrolls the board to the card (V6 paintNV / nvStep / nvTour).
  import Wg from './Wg.svelte'
  import { pxPath } from '../../../lib/px'
  import { titleOf } from '../../../lib/cards/card'
  import { lib, thumbSrc } from '../../../lib/library.svelte'
  import { locate } from '../../../lib/map'

  const PREV = ['#.....#.', '#....##.', '#...###.', '#..####.', '#...###.', '#....##.', '#.....#.', '........']
  const NEXT = PREV.map(r => [...r.slice(0, 7)].reverse().join('') + '.')
  const PLAY = ['.#......', '.##.....', '.###....', '.####...', '.###....', '.##.....', '.#......', '........']
  const PAUSE = ['.##.##..', '.##.##..', '.##.##..', '.##.##..', '.##.##..', '.##.##..', '.##.##..', '........']

  let tour = $state(0)
  const ids = $derived(lib.visIds)
  const id = $derived(lib.nvId !== null && lib.byId.has(lib.nvId) && ids.includes(lib.nvId) ? lib.nvId : ids[0] ?? null)
  const it = $derived(id === null ? null : lib.byId.get(id) ?? null)
  const k = $derived(id === null ? -1 : ids.indexOf(id))
  const lit = $derived(it ? Math.max(1, Math.round((k + 1) / ids.length * 12)) : 0)
  const p2 = (n: number) => String(n).padStart(2, '0')

  function step(d: number) {
    if (!ids.length) return
    let i = id === null ? -1 : ids.indexOf(id)
    i = i < 0 ? 0 : (i + d + ids.length) % ids.length
    lib.nvId = ids[i]
    locate(ids[i])
  }
  function setTour(on: boolean) {
    clearInterval(tour); tour = 0
    if (on) { step(1); tour = window.setInterval(() => step(1), 2600) }
  }
  $effect(() => () => clearInterval(tour))
</script>

<Wg cls="s s3" id="nv" title="Viewing" jp="再生中" n={it ? `${p2(k + 1)} / ${p2(ids.length)}` : '00 / 00'}>
  <div class="nv">
    <div class="nv-art">{#if it?.thumb}<img id="nv-img" alt="" src={thumbSrc(it.id)} style:object-position="50% 42%" />{/if}</div>
    <div class="nv-t"><b id="nv-title">{it ? titleOf(it) : 'No cards shown'}</b><span id="nv-sub">{it ? `${it.creator || 'unknown'} · ${it.fav ? '★ Favourite' : it.cat}` : 'Clear a filter to see cards'}</span></div>
  </div>
  <div class="prog" id="nv-prog" aria-hidden="true">{#each { length: 12 } as _, j (j)}<i class:lit={j < lit}></i>{/each}</div>
  <div class="xport">
    <button type="button" class="xk" aria-label="Previous card" onclick={() => { setTour(false); step(-1) }}><svg class="px" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d={pxPath(PREV)} /></svg></button>
    <button type="button" class="xk" aria-pressed={!!tour} aria-label={tour ? 'Stop the tour' : 'Tour the cards'} onclick={() => setTour(!tour)}><svg class="px" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d={pxPath(tour ? PAUSE : PLAY)} /></svg></button>
    <button type="button" class="xk" aria-label="Next card" onclick={() => { setTour(false); step(1) }}><svg class="px" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d={pxPath(NEXT)} /></svg></button>
  </div>
</Wg>
