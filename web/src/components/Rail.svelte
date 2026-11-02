<script lang="ts">
  // The MP-06 rail (V6 aside.pad): one dock of numbered tiles per workspace. The docks are filled
  // by the workspace sub-plans: LibraryDock (05), KnowledgeDock (08), CanvasDock (09), NotesDock (10).
  // The Jobs module (RailJobs) sits above them on every workspace, Get started (a new library) under it.
  import LibraryDock from '../workspaces/library/dock/LibraryDock.svelte'
  import KnowledgeDock from '../workspaces/knowledge/KnowledgeDock.svelte'
  import CanvasDock from '../workspaces/canvas/CanvasDock.svelte'
  import NotesDock from '../workspaces/notes/NotesDock.svelte'
  import RailJobs from './RailJobs.svelte'
  import GetStarted from './GetStarted.svelte'
  import { ghosts, saveGhosts } from '../lib/dock-ghost'
  import { ui, WS_NAME, type Ws } from '../lib/ui.svelte'

  let { visited }: { visited: Record<Ws, boolean> } = $props()

  // Start-up: skeleton tiles (a title bar, then text lines) hold each dock's tiles until the docks
  // mount, then the real content fades in on the same surfaces (app.css .dock-sk, html.cm-boot).
  const SK_W = ['88%', '62%', '94%', '48%', '76%']
  const skLines = (h: number) => Math.max(0, Math.min(14, Math.floor((h - 44) / 21)))
  // a moment after a dock settles, its tile heights become the next start's placeholders
  $effect(() => {
    if (!ui.ready) return
    const ws = ui.ws
    const t = setTimeout(() => { const d = document.querySelector<HTMLElement>(`.dock[data-dock="${ws}"]`); if (d) saveGhosts(ws, d) }, 3000)
    return () => clearTimeout(t)
  })
</script>

{#snippet hollow(ws: Ws)}
  {#each ghosts(ws) as [cls, h], i (i)}
    <div class={'wg dock-sk ' + cls} style:height={h + 'px'} aria-hidden="true"><i class="sk-h"></i>{#each { length: skLines(h) } as _, j (j)}<i class="sk-l" style:width={SK_W[j % SK_W.length]}></i>{/each}</div>
  {/each}
{/snippet}

<aside class="pad" class:open={ui.drawer === 'pad'} id="pad" aria-label="Dashboard">
  <div class="padtop">
    <b>MP-06</b><span class="ws-n" id="pad-ws">{WS_NAME[ui.ws]}</span><span class="jp" aria-hidden="true">ダッシュボード</span>
    <span class="pwr"><i></i>All systems go</span>
    <button class="tkey pad-x" type="button" id="close-pad" onclick={() => (ui.drawer = null)}>Close</button>
  </div>
  <!-- pinned: outside the scroll area, the same on every workspace -->
  <RailJobs />
  <GetStarted />
  <div class="pad-scroll">
    <div class="dock" id="mods" data-dock="lib" hidden={ui.ws !== 'lib'}>{#if ui.ready}<LibraryDock />{:else}{@render hollow('lib')}{/if}</div>
    <div class="dock" id="mods-know" data-dock="know" hidden={ui.ws !== 'know'}>{#if ui.ready && visited.know}<KnowledgeDock />{:else}{@render hollow('know')}{/if}</div>
    <div class="dock" id="mods-canvas" data-dock="canvas" hidden={ui.ws !== 'canvas'}>{#if ui.ready && visited.canvas}<CanvasDock />{:else}{@render hollow('canvas')}{/if}</div>
    <div class="dock" id="mods-notes" data-dock="notes" hidden={ui.ws !== 'notes'}>{#if ui.ready && visited.notes}<NotesDock />{:else}{@render hollow('notes')}{/if}</div>
  </div>
</aside>
