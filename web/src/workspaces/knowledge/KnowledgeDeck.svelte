<script lang="ts">
  import Px from '../../lib/Px.svelte'
  import { runCmd } from '../../lib/commands'
  import { augment, clearSources, cxScanning, ks, picked, scanConnections, searchSources, synthesize } from '../../lib/knowledge.svelte'

  let input: HTMLInputElement | undefined = $state()
  function search() { ks.topicId = null; void searchSources(ks.sourceQuery) }
  function clear() { clearSources(); input?.focus() }
</script>

<div class="deck workspace-deck" aria-label="Knowledge search and actions">
  <form class="dq" class:ranking={ks.loading} aria-busy={ks.loading} onsubmit={e => { e.preventDefault(); search() }}>
    <span class="ps" aria-hidden="true">~/knowledge <b>$</b></span>
    <label class="sr" for="knowledge-q">Search knowledge sources</label>
    <input id="knowledge-q" type="search" bind:this={input} bind:value={ks.sourceQuery} autocomplete="off" spellcheck="false"
      placeholder="search sources and saved notes" enterkeyhint="search"
      onkeydown={e => { if (e.key === 'Escape' && (ks.sourceQuery || ks.q || ks.cat)) { e.preventDefault(); e.stopPropagation(); clear() } }} />
    <span class="cnt" aria-live="polite">{ks.loading ? 'Searching…' : `${ks.items.length} sources`}</span>
    <button class="dq-x" type="button" aria-label="Clear knowledge search" hidden={!ks.sourceQuery && !ks.q && !ks.cat} onclick={clear}><Px name="clear" /></button>
    <button class="smart" type="submit" disabled={!ks.sourceQuery.trim()}>Search</button>
    <span class="dq-scan" aria-hidden="true"></span>
  </form>
  <div class="keys">
    <button class="mk pri" type="button" aria-label="Synthesize sources" title="Write a note from selected sources, or all loaded sources" disabled={!ks.items.length} onclick={synthesize}><Px name="core" /><b>SYNTHESIZE</b><small>sources to note</small></button>
    <button class="mk" type="button" aria-label="Augment note" title="Add new sources to the open note" disabled={!ks.note || !picked().some(id => !ks.note!.row.sources.includes(id))} onclick={augment}><Px name="plus" /><b>AUGMENT</b><small>extend this note</small></button>
    <button class="mk" type="button" aria-label="Find connections" title="Find connections between indexed sources" disabled={cxScanning()} onclick={scanConnections}><Px name="link" /><b>CONNECTIONS</b><small>find insights</small></button>
    <button class="mk" type="button" aria-label="Knowledge graph" title="Open the knowledge graph in Obsidian" onclick={() => runCmd('obs-graph')}><Px name="grid" /><b>GRAPH</b><small>knowledge map</small></button>
  </div>
</div>
