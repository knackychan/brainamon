<script lang="ts">
  // The review window of a Wiskit canvas proposal (CANVAS-02, projects/wiskit-canvas/PLAN.md).
  import type { CanvasPreview, CanvasPreviewEl } from '../lib/job-requests'
  import WinBody from './ui/WinBody.svelte'

  let { preview, source, answer, setActivate }: {
    preview: CanvasPreview
    source: string
    answer: (ok: boolean) => void
    setActivate: (on: boolean) => void
  } = $props()
  let activate = $state(false)
  const c = $derived(preview.counts)
  const added = $derived(c.thumbnail + c.frame + c.text)
  const groups = $derived([
    ...(preview.explicit.length ? [{ title: 'Placed by position', elements: preview.explicit }] : []),
    ...preview.sections,
  ])

  function src(e: CanvasPreviewEl): string | null {
    if (e.kind === 'frame' && e.item_id != null) return `/files/items/${e.item_id}/frames/${encodeURIComponent(e.frame ?? '')}`
    if (e.kind === 'thumbnail' && e.item_id != null) return `/thumb/${e.item_id}?w=240`
    if (e.kind === 'existing' && e.type === 'image') return e.item_id != null ? `/thumb/${e.item_id}?w=240` : `/files/canvas-uploads/${e.file_path}`
    return null
  }
  const what = (e: CanvasPreviewEl) =>
    e.kind === 'frame' ? `No.${e.item_id} · ${e.frame}` : e.kind === 'thumbnail' ? `No.${e.item_id}` : e.kind === 'existing' ? 'moved' : 'note'
</script>

<WinBody>
  <p>{source} proposes {preview.target.new ? 'a new canvas' : 'additions to the canvas'} <strong>{preview.target.name}</strong>:
    {c.thumbnail} {c.thumbnail === 1 ? 'thumbnail' : 'thumbnails'}, {c.frame} {c.frame === 1 ? 'frame' : 'frames'},
    {c.text} {c.text === 1 ? 'note' : 'notes'}{c.sections ? ` in ${c.sections} ${c.sections === 1 ? 'section' : 'sections'}` : ''}.</p>
  <p class="hint">
    {#if preview.target.new}A new canvas is created; no other canvas changes.{:else}Its {preview.target.count} current elements stay as they are{c.moves ? `, except ${c.moves} moved into the sections below (content unchanged)` : ''}. Nothing is removed.{/if}
    Laid out in {preview.layout === 'columns' ? 'columns, left to right' : 'rows, top to bottom'}. Nothing is written until you apply. Close keeps it pending in Jobs.
  </p>
  <!-- Scroll region is focusable for keyboard reading. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="review" role="region" tabindex="0" aria-label="Proposed canvas contents">
    {#each groups as g, gi (gi)}
      <section>
        <h3>{g.title ?? 'Without a section'}</h3>
        <ul>
          {#each g.elements as e, i (i)}
            {@const img = src(e)}
            <li class:note={!img}>
              {#if img}<img src={img} alt="" loading="lazy" />{/if}
              {#if e.text}<span class="txt">{e.text}</span>{/if}
              {#if e.title && e.kind !== 'existing'}<span class="txt">{e.title}</span>{/if}
              <small>{what(e)}{e.label ? ` · ${e.label}` : ''}</small>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  </div>
</WinBody>
<div class="cw-foot">
  <label class="chk"><input type="checkbox" bind:checked={activate} onchange={() => setActivate(activate)} />Make it the active canvas</label>
  <span class="sp"></span>
  <button class="wkey" type="button" onclick={() => answer(false)}>Decline</button>
  <button class="wkey pri" type="button" onclick={() => answer(true)}>Apply ({added + c.sections}{c.moves ? `, move ${c.moves}` : ''})</button>
</div>

<style>
  p { margin: 0 0 10px; }
  .review { display: grid; gap: 14px; max-height: 52vh; overflow: auto; }
  h3 { margin: 0 0 8px; font: 600 12px/1.4 var(--mono); color: var(--muted); }
  ul { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; }
  li { display: grid; gap: 4px; align-content: start; min-width: 0; padding: 6px; border: 1px solid var(--hair); border-radius: 6px; }
  li.note { background: var(--rw-2); }
  img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 4px; }
  .txt { font-size: 12px; overflow-wrap: anywhere; white-space: pre-wrap; }
  small { color: var(--muted); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  .cw-foot { flex-wrap: wrap; align-items: center; }
  .cw-foot button { min-height: 40px; }
  @media (max-width: 540px) {
    .cw-foot .chk { flex-basis: 100%; }
    .cw-foot .sp { display: none; }
    .cw-foot button { flex: 1; min-height: 44px; }
  }
</style>
