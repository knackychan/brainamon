<script lang="ts">
  // The console drawer (Qt ui/console_panel.py): All / API / Errors / Logs, Follow, Clear, Copy.
  // Lines are app_console entries from the server (GET /api/console, then SSE 'log').
  import { cons, toast, toggleConsole, ui, type Tag } from '../lib/ui.svelte'
  import { wins } from '../lib/windows.svelte'

  let log: HTMLDivElement | undefined = $state()
  const FILTERS: [('all' | Tag), string][] = [['all', 'All'], ['API', 'API'], ['ERR', 'Errors'], ['LOG', 'Logs']]
  const shown = $derived(cons.lines.filter(l => cons.filter === 'all' || l.tag === cons.filter))

  $effect(() => {
    shown.length
    if (ui.consoleOpen && cons.follow && log) log.scrollTop = log.scrollHeight
  })

  function copy() {
    const t = cons.lines.map(l => `[${l.t}] ${l.tag} ${l.msg}`).join('\n')
    navigator.clipboard.writeText(t).then(() => toast('Console copied to the clipboard'), () => toast('Copy is blocked on this page', 'w'))
  }
  function closeIt() {
    toggleConsole(false)
    document.getElementById('cons-key')?.focus()
  }
</script>

<div class="cons" id="cons" role="region" aria-label="Console" hidden={!ui.consoleOpen} inert={wins.length > 0}>
  <div class="cons-hd">
    <span>Console</span><span class="jp" aria-hidden="true">コンソール</span>
    <span class="cseg" role="group" aria-label="Filter">
      {#each FILTERS as [k, label] (k)}
        <button type="button" aria-pressed={cons.filter === k} onclick={() => (cons.filter = k)}>{label}</button>
      {/each}
    </span>
    <span class="sp"></span>
    <label><input type="checkbox" bind:checked={cons.follow} />Follow</label>
    <button type="button" onclick={() => cons.lines.splice(0)}>Clear</button>
    <button type="button" onclick={copy}>Copy</button>
    <button type="button" aria-label="Close the console" onclick={closeIt}>✕</button>
  </div>
  <div class="cons-log" role="log" aria-live="off" bind:this={log}>
    {#each shown as l (l.id)}
      <div class="cl" class:e={l.tag === 'ERR'} class:l={l.tag === 'LOG'}><time>{l.t}</time><b>{l.tag}</b><span>{l.msg}</span></div>
    {:else}
      <div class="cl"><time></time><b></b><span>Nothing logged yet.</span></div>
    {/each}
  </div>
  <p class="cons-ft">{shown.length} of {cons.lines.length} lines · API calls and errors from every job</p>
</div>
