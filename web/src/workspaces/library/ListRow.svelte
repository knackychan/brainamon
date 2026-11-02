<script lang="ts">
  // One list row (V6 rowHTML): select key, thumbnail + title + meta, collection, the five status
  // pips (T D C A I), favourite, the key strip.
  import CardKeys from './CardKeys.svelte'
  import Px from '../../lib/Px.svelte'
  import { act } from '../../lib/cardmenu'
  import { dateOf, titleOf } from '../../lib/cards/card'
  import { JOB_SHORT, live } from '../../lib/events.svelte'
  import { lib, NEED, rangeSel, toggleFav, toggleSel, type Row, thumbSrc } from '../../lib/library.svelte'
  import { openProcessing } from '../../lib/job-commands'
  import { PROCESS_ACTIONS, processingEligible, processingStatus } from '../../lib/processing'

  let { row }: { row: Row } = $props()
  const on = $derived(lib.sel.has(row.id))
  const st = $derived(lib.cellState.get(row.id))
  const status = $derived(processingStatus(row))
  const statusDetail = $derived(PROCESS_ACTIONS.map(a => `${a.label}: ${!processingEligible(row, a.kind) ? 'not applicable' : row.nd & NEED[a.kind] ? 'not done' : a.kind === 'index' ? 'indexed; may need a refresh' : 'done'}`).join('. '))
  function open(e: MouseEvent) {
    if (e.ctrlKey || e.metaKey) toggleSel(row.id)
    else if (e.shiftKey) rangeSel(row.id)
    else act('open', row.id)
  }
  function selKey(e: MouseEvent) { if (e.shiftKey) rangeSel(row.id); else toggleSel(row.id) }
</script>

<div class="cell lr" class:sel={on} class:worked={st === 'worked'} class:done={st === 'done'} class:err={st === 'err'} class:cited={lib.cited.has(row.id)} class:hl={lib.hlId === row.id} data-id={row.id} style:--k={TYPE[row.cat]}>
  <button type="button" class="sel-key" aria-pressed={on} aria-label={`Select No.${row.id}`} title="Select (Shift for a range)" onclick={selKey}><Px name="check" /></button>
  <div class="lr-main">
    <button type="button" class="lr-open" aria-label={`Open No.${row.id}, ${titleOf(row)}`} onclick={open}>
    {#if row.thumb}<img class="lr-th" src={thumbSrc(row.id)} alt="" loading="lazy" style:object-position="50% 42%" />{:else}<span class="lr-th" style:opacity=".25"></span>{/if}
    <span class="lr-t"><b>{titleOf(row)}</b><span>No.{row.id} · {row.creator || 'unknown'} · {row.type} · {dateOf(row.created)}</span></span>
    </button>
    <button class="processing-status" type="button" title={statusDetail} aria-label={`${status} for No.${row.id}. ${statusDetail}. Review processing`} onclick={() => openProcessing(undefined, [row.id])}>{status}…</button>
  </div>
  <span class="tyb">{row.cat}</span>
  <button type="button" class="fav-key" aria-pressed={row.fav} aria-label={`Favourite No.${row.id}`} title="Favourite: a holo card" onclick={() => toggleFav(row.id)}><Px name="star" /></button>
  <CardKeys id={row.id} />
  <span class="drn-tag">{st === 'done' ? 'DONE' : st === 'err' ? 'FAILED' : st === 'worked' && live.jobs.current ? JOB_SHORT[live.jobs.current.kind] ?? live.jobs.current.kind.toUpperCase() : ''}</span><span class="cite-tag">{lib.cited.has(row.id) ? `cited ${lib.cited.get(row.id)}` : ''}</span>
</div>

<style>
  .cell.lr { grid-template-columns: 24px minmax(0, 1fr) auto auto auto }
  .lr-main { min-width: 0; justify-self: stretch; display: grid; gap: 4px }
  .processing-status { justify-self: start; margin-left: 74px; padding: 3px 0; border: 0; background: transparent; color: var(--felt-ink); font: var(--type-aside); white-space: nowrap; text-decoration: underline; text-underline-offset: 3px; cursor: pointer }
  .processing-status:hover, .processing-status:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px }
  @media (max-width: 860px) {
    .cell.lr { grid-template-columns: 24px minmax(0, 1fr) auto }
    .processing-status { margin-left: 64px }
    .cell.lr :global(.ck-row) { grid-column: 2 / -1; justify-self: start }
  }
</style>
