<script lang="ts">
  // The reformat proposal's preview: title, category, topic chips, the new body. Apply writes
  // through the notes autosave (the user's click); Discard drops the proposal.
  import { applyReformat, discardReformat, nt, rf } from '../../lib/notes.svelte'
  import Button from '../../components/ui/Button.svelte'
  let cat = $state('')
  $effect(() => { if (rf.proposal) cat = rf.proposal.category })
  const cats = $derived(rf.proposal && !nt.categories.includes(rf.proposal.category)
    ? [...nt.categories, rf.proposal.category] : nt.categories)
</script>

{#if rf.proposal}
  <div class="rf-back" role="dialog" aria-label="Reformat preview">
    <div class="rf-win panel">
      <h3>Reformat “{rf.proposal.old_title}”?</h3>
      <p class="rf-meta">Title: <b>{rf.proposal.title}</b> · Category:
        <select class="inp" bind:value={cat}>{#each cats as c (c)}<option value={c}>{c}</option>{/each}</select>
        {#if rf.proposal.category !== rf.proposal.old_category}(was {rf.proposal.old_category}){/if}</p>
      {#if rf.proposal.instruction}<p class="rf-meta">Asked for: {rf.proposal.instruction}</p>{/if}
      {#if rf.proposal.topics.length}<p class="rf-topics">{#each rf.proposal.topics as t (t)}<span class="rf-chip">{t}</span>{/each}</p>{/if}
      <pre class="rf-body">{rf.proposal.body}</pre>
      <p class="rf-warn">Apply replaces the note's current text with this{rf.proposal.stamps ? `, and its stamps with ${rf.proposal.stamps.length}` : ''}. There is no undo.</p>
      <div class="rf-btns">
        <Button kind="tool" variant="pri" onclick={() => applyReformat(cat)}>Apply</Button>
        <Button kind="tool" onclick={discardReformat}>Discard</Button>
      </div>
    </div>
  </div>
{/if}

<style>
  .rf-back { position: fixed; inset: 0; background: rgba(0,0,0,.45); display: flex; align-items: center; justify-content: center; z-index: 60 }
  .rf-win { width: min(680px, 92vw); max-height: 84vh; display: flex; flex-direction: column; gap: 8px; padding: 14px }
  .rf-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap }
  .rf-topics { display: flex; gap: 6px; flex-wrap: wrap }
  .rf-chip { border: 1px solid currentColor; border-radius: 10px; padding: 0 8px; font-size: 12px; opacity: .8 }
  .rf-body { overflow: auto; flex: 1; min-height: 160px; white-space: pre-wrap; font: inherit; margin: 0; padding: 8px; border: 1px solid currentColor; border-radius: 6px }
  .rf-warn { font-size: 12px; opacity: .75 }
  .rf-btns { display: flex; gap: 8px; justify-content: flex-end }
</style>
