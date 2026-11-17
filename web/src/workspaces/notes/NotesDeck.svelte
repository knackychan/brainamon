<script lang="ts">
  import { onDestroy } from 'svelte'
  import Px from '../../lib/Px.svelte'
  import { loadList, nt, pickDigestShots, promptNewNote, reformat, summarize } from '../../lib/notes.svelte'

  let input: HTMLInputElement | undefined = $state()
  let timer = 0
  function search() { clearTimeout(timer); void loadList() }
  function clear() { nt.q = ''; search(); input?.focus() }
  onDestroy(() => clearTimeout(timer))
</script>

<div class="deck workspace-deck" aria-label="Notes search and actions">
  <form class="dq" onsubmit={e => { e.preventDefault(); search() }}>
    <span class="ps" aria-hidden="true">~/notes <b>$</b></span>
    <label class="sr" for="notes-q">Search notes</label>
    <input id="notes-q" type="search" bind:this={input} bind:value={nt.q} autocomplete="off" spellcheck="false"
      placeholder="search titles, categories, note text" enterkeyhint="search"
      oninput={() => { clearTimeout(timer); timer = window.setTimeout(search, 150) }}
      onkeydown={e => { if (e.key === 'Escape' && nt.q) { e.preventDefault(); e.stopPropagation(); clear() } }} />
    <span class="cnt" aria-live="polite">{nt.list.length} notes</span>
    <button class="dq-x" type="button" aria-label="Clear notes search" hidden={!nt.q} onclick={clear}><Px name="clear" /></button>
  </form>
  <div class="keys">
    <button class="mk pri" type="button" aria-label="New note" title="Create a note" onclick={promptNewNote}><Px name="plus" /><b>NEW NOTE</b><small>start writing</small></button>
    <button class="mk" type="button" aria-label="Summarize note" title="Summarize the open note" disabled={!nt.file || !nt.body.trim()} onclick={summarize}><Px name="core" /><b>SUMMARIZE</b><small>AI summary</small></button>
    <button class="mk" type="button" aria-label="Reformat note" title="Reformat and classify the open note" disabled={!nt.file || !nt.body.trim()} onclick={reformat}><Px name="edit" /><b>REFORMAT</b><small>tidy &amp; classify</small></button>
    <button class="mk" type="button" aria-label="Digest screenshot" title="Transcribe screenshots into a note" onclick={pickDigestShots}><Px name="img" /><b>DIGEST</b><small>screenshots</small></button>
  </div>
</div>
