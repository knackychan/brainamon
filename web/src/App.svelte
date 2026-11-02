<script lang="ts">
  // The CM-OS shell (V6 body.html): field canvas, menubar, the shell row (rail, workspace,
  // Wiskit), console drawer, menu panel, toasts, windows, the drawer scrim and the Ask button.
  import { onMount } from 'svelte'
  import ConsoleDrawer from './components/ConsoleDrawer.svelte'
  import WiskitDesk from './components/WiskitDesk.svelte'
  import LoadBar from './components/LoadBar.svelte'
  import Menubar from './components/Menubar.svelte'
  import MenuPanel from './components/MenuPanel.svelte'
  import Rail from './components/Rail.svelte'
  import Toasts from './components/Toasts.svelte'
  import WindowLayer from './components/WindowLayer.svelte'
  import LibraryWs from './workspaces/library/LibraryWs.svelte'
  import { api } from './lib/api'
  import { registerCommands } from './lib/command-table'
  import { startField } from './lib/desk'
  import { connect } from './lib/events.svelte'
  import { installJobRequests } from './lib/job-requests'
  import { installKeys } from './lib/keys'
  import { installRest } from './lib/rest'
  import { loadOnboarding, openWelcome } from './lib/onboarding.svelte'
  import { initMotion, initTheme, initWS, readyAfterPaint, ui } from './lib/ui.svelte'
  import { wins } from './lib/windows.svelte'

  registerCommands()
  initTheme()
  initMotion()
  initWS()
  installKeys()
  installRest()

  // Keep visited workspaces mounted (drafts and handlers), but never preload unused UI.
  const loadKnow = () => import('./workspaces/knowledge/KnowledgeWs.svelte')
  const loadCanvas = () => import('./workspaces/canvas/CanvasWs.svelte')
  const loadNotes = () => import('./workspaces/notes/NotesWs.svelte')
  let visited = $state({ lib: true, know: false, canvas: false, notes: false })
  $effect(() => { visited[ui.ws] = true })

  // Start-up: from the moment the rail docks and Wiskit mount, html.cm-boot fades their content in
  // once (app.css); the class goes after, so a dock or drawer shown later never replays it.
  $effect(() => {
    if (!ui.ready) return
    const h = document.documentElement
    h.classList.add('cm-boot')
    const t = setTimeout(() => h.classList.remove('cm-boot'), 900)
    return () => { clearTimeout(t); h.classList.remove('cm-boot') }
  })

  onMount(() => {
    if (ui.ws !== 'lib') readyAfterPaint(ui.ws)  // no grid to wait for (marks cm-first-screen)
    setTimeout(() => (ui.ready = true), 3000)    // the library failed to load: show the rest anyway
    startField()
    installJobRequests()          // before connect(): the first hello can already carry a waiting request
    connect()
    api.get<{ items: number }>('/api/health').then(h => { ui.libCount = h.items }).catch(() => {})
    // First run (server/routes/onboarding.py): one welcome question, only for a new library
    loadOnboarding().then(o => { if (o.welcome) openWelcome() }).catch(() => {})
  })
</script>

<canvas id="field" aria-hidden="true"></canvas>
<Menubar />
<LoadBar />
<div class="shell" id="shell" inert={wins.length > 0}>
  <Rail {visited} />
  <LibraryWs />
  {#if visited.know}{#await loadKnow() then M}<M.default />{/await}{/if}
  {#if visited.canvas}{#await loadCanvas() then M}<M.default />{/await}{/if}
  {#if visited.notes}{#await loadNotes() then M}<M.default />{/await}{/if}
  {#if ui.ready}<WiskitDesk />{:else}
    <!-- the Wiskit skeleton: title bar, toolbar, the pet and its readout, a few lines, the input -->
    <aside class="jv" id="jv" aria-label="Wiskit, chat with your library" aria-busy="true">
      <div class="jv-sk" aria-hidden="true">
        <i class="sk-h"></i><i class="sk-l jv-sk-tools"></i>
        <div class="jv-sk-pet"><i class="sk-art"></i><div><i class="sk-h"></i><i class="sk-l"></i><i class="sk-l"></i><i class="sk-l"></i></div></div>
        <div class="jv-sk-msg"><i class="sk-l"></i><i class="sk-l"></i><i class="sk-l"></i><i class="sk-l"></i><i class="sk-l"></i></div>
        <i class="sk-l jv-sk-in"></i>
      </div>
    </aside>
  {/if}
</div>
<ConsoleDrawer />
<MenuPanel />
<Toasts />
<WindowLayer />
<svg class="tether" id="tether" aria-hidden="true"></svg>
<div class="tether-tag" id="tether-tag" hidden></div>
<button class="ask-fab" type="button" id="ask-fab" aria-controls="jv" aria-expanded={ui.drawer === 'jv'} inert={wins.length > 0} onclick={() => (ui.drawer = ui.drawer === 'jv' ? null : 'jv')}><canvas id="fab-pet" aria-hidden="true"></canvas>Ask Wiskit</button>
<div class="scrim" id="scrim" hidden={!ui.drawer} role="presentation" onclick={() => (ui.drawer = null)}></div>
