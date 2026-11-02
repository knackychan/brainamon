<script lang="ts">
  // The selection tray (V6 #tray): rises when something is selected. Every key runs a command.
  import { runCmd } from '../../lib/commands'
  import { lib } from '../../lib/library.svelte'
</script>

<div class="tray" class:up={lib.sel.size > 0} id="tray" role="toolbar" aria-label="Selection" inert={lib.sel.size === 0}>
  <b id="tray-n">{lib.sel.size} <small>selected</small></b>
  <button class="tk process" type="button" title="Choose a processing step, see what needs it, and review costs" onclick={() => runCmd('process-items')}>Process items…</button>
  <button class="tk" type="button" onclick={() => runCmd('select-all')}>Select all</button>
  <button class="tk" type="button" onclick={() => runCmd('bulk')}>Bulk edit</button>
  <button class="tk" type="button" onclick={() => runCmd('sel-canvas')}>Add to canvas</button>
  <button class="tk" type="button" title="Start a chat answer about the selection. AI charges may apply." onclick={() => runCmd('sel-ask')}>Ask Wiskit</button>
  <button class="tk" type="button" title="Combine available text into one saved note. Choose a topic and review the AI cost estimate." onclick={() => runCmd('sel-note')}>Synthesize a note…</button>
  <button class="tk del" type="button" onclick={() => runCmd('delete-sel')}>Delete</button>
  <button class="tk" type="button" aria-label="Clear the selection" onclick={() => runCmd('clear-sel')}>Clear</button>
</div>

<style>
  .tk.process { background: var(--term-ink); color: var(--term) }
  .tk.process:hover, .tk.process:focus-visible { background: var(--term-acc) }
</style>
