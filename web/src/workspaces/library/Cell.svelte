<script lang="ts">
  // One grid cell (V6 cellHTML): select key, favourite star, the locked card, the key strip.
  // The card markup comes from the engine (cardFA2 / cardHTML) with escaped text; its HandCard is
  // created when the markup is in the DOM and detached when it changes or the cell unmounts.
  import CardKeys from './CardKeys.svelte'
  import Px from '../../lib/Px.svelte'
  import { attachHand } from '../../lib/cards/hand'
  import { cardMarkup, GRID_THUMB_W, titleOf } from '../../lib/cards/card'
  import { themeSlot } from '../../lib/cards/theme'
  import { lib, rangeSel, toggleFav, toggleSel, Z, type Row } from '../../lib/library.svelte'
  import { cardTap } from './tap'
  import { JOB_SHORT, live } from '../../lib/events.svelte'

  // first load (VirtualGrid): i, the cell's place in the mounted slice, staggers the fade; sk puts a
  // skeleton card under the card that fades out as the card fades in
  let { row, i = 0, sk = false }: { row: Row; i?: number; sk?: boolean } = $props()
  let el: HTMLDivElement | undefined = $state()

  const html = $derived(cardMarkup(row, lib.variant, lib.rankOf.get(row.id) ?? row.id, GRID_THUMB_W, lib.rows.length))
  const on = $derived(lib.sel.has(row.id))
  const st = $derived(lib.cellState.get(row.id))
  // a running job's item: its short name on the drone tag, a scan bar on the card (capped, lib.scanIds)
  const kind = $derived(st === 'worked' && live.jobs.current ? live.jobs.current.kind : '')
  const scan = $derived(st === 'worked' && lib.scanIds.has(row.id))
  // the same tag then says how the item ended, so a finished card stays visible for a moment
  const tag = $derived(st === 'done' ? 'DONE' : st === 'err' ? 'FAILED' : kind ? JOB_SHORT[kind] ?? kind.toUpperCase() : '')

  $effect(() => {
    html
    const s = el?.querySelector<HTMLElement>('.slot')
    if (!s) return
    // a thumbnail already decoded (from cache) fired its load before it could be seen: show it now
    s.querySelectorAll<HTMLImageElement>('img.art').forEach(m => { if (m.complete) m.classList.add('ld') })
    s.tabIndex = 0
    s.style.cursor = 'pointer'
    themeSlot(s, row)
    const id = row.id
    return attachHand(s, () => cardTap(id))
  })

  function selKey(e: MouseEvent) { if (e.shiftKey) rangeSel(row.id); else toggleSel(row.id) }
</script>

<div class="cell" class:sel={on} class:worked={st === 'worked'} class:done={st === 'done'} class:err={st === 'err'} class:cited={lib.cited.has(row.id)} class:hl={lib.hlId === row.id} data-id={row.id} style:--i={i} bind:this={el}>
  <span class="sel-mat" aria-hidden="true"></span>
  {#if sk}<span class="cell-sk" aria-hidden="true"></span>{/if}
  <button type="button" class="sel-key" aria-pressed={on} aria-label={`Select No.${row.id}`} title="Select (Shift for a range)" onclick={selKey}><Px name="check" /></button>
  <span class="drn-tag">{tag}</span><span class="cite-tag">{lib.cited.has(row.id) ? `cited ${lib.cited.get(row.id)}` : ''}</span>
  <button type="button" class="fav-key" aria-pressed={row.fav} aria-label={`Favourite No.${row.id}`} title="Favourite: a holo card" onclick={() => toggleFav(row.id)}><Px name="star" /></button>
  {@html html}
  {#if Z[lib.zi] < 240}<div class="card-cap" style:width="var(--card)"><b>{titleOf(row)}</b><small>{[row.creator || 'unknown', row.cat].filter(Boolean).join(' · ')}</small></div>{/if}
  {#if scan}<span class="job-scan" aria-hidden="true"></span>{/if}
  <!-- the key strip is hidden at the two smallest zoom steps (.board.zs .ck-row): not mounted there -->
  {#if Z[lib.zi] > 116}<CardKeys id={row.id} />{/if}
</div>
