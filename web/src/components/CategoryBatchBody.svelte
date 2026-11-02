<script lang="ts">
  import WinBody from './ui/WinBody.svelte'
  let { entries, source, answer }: {
    entries: { id: number; title: string; from: string; category: string }[]
    source: string
    answer: (ok: boolean) => void
  } = $props()
  const categories = $derived(new Set(entries.map(e => e.category)).size)
</script>

<WinBody>
  <p>{source} proposes {entries.length} category changes across {categories} {categories === 1 ? 'category' : 'categories'}.</p>
  <p class="hint">Nothing changes until you apply this batch. Close keeps it pending in Jobs.</p>
  <div class="review">
    <table>
      <caption class="hint">Current and proposed categories for every item in this batch</caption>
      <thead><tr><th scope="col">Item</th><th scope="col">Current category</th><th scope="col">Proposed category</th></tr></thead>
      <tbody>
        {#each entries as entry (entry.id)}
          <tr><th scope="row"><span class="number">No.{entry.id}</span> {entry.title}</th>
            <td>{entry.from || 'Uncategorized'}</td><td><strong>{entry.category}</strong></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</WinBody>
<div class="cw-foot">
  <small>One approval applies the whole batch</small>
  <span class="sp"></span>
  <button class="wkey" type="button" onclick={() => answer(false)}>Decline</button>
  <button class="wkey pri" type="button" onclick={() => answer(true)}>Apply batch ({entries.length})</button>
</div>

<style>
  p { margin: 0 0 10px; }
  .review { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; text-align: left; }
  caption { text-align: left; padding-bottom: 12px; }
  th, td { padding: 10px 8px; vertical-align: top; overflow-wrap: anywhere; border-bottom: 1px solid var(--hair); }
  thead th { font-size: 12px; color: var(--muted); }
  tbody th { font-weight: 400; width: 44%; }
  .number { white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--muted); }
  .cw-foot { flex-wrap: wrap; }
  .cw-foot button { min-height: 40px; }
  @media (max-width: 540px) {
    .cw-foot small { flex-basis: 100%; }
    .cw-foot .sp { display: none; }
    .cw-foot button { flex: 1; min-height: 44px; }
  }
</style>
