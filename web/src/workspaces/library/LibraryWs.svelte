<script lang="ts">
  // 01 LIBRARY (V6 main.ws-lib): the command deck, the mat (header, the virtualized board, the
  // selection tray) and the map strip. Data and filters live in lib/library.svelte.ts.
  import { onMount } from 'svelte'
  import Deck from './Deck.svelte'
  import MapStrip from './MapStrip.svelte'
  import MatHeader from './MatHeader.svelte'
  import Tray from './Tray.svelte'
  import VirtualGrid from './VirtualGrid.svelte'
  import { installEdits } from '../../lib/edit-commands'
  import { installJobs } from '../../lib/job-commands'
  import { installAsk } from '../../lib/ask-commands'
  import { installKnowledgeCommands } from '../../lib/knowledge-commands'
  import { installAttach } from '../../lib/attach'
  import { installIo } from '../../lib/io-commands.svelte'
  import { installLibrary } from '../../lib/library-commands'
  import { lib } from '../../lib/library.svelte'
  import { ui } from '../../lib/ui.svelte'

  onMount(() => { installLibrary(); installEdits(); installJobs(); installAsk(); installKnowledgeCommands(); installAttach(); installIo() })
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
<main class="ws ws-lib" id="ws-lib" role="tabpanel" aria-labelledby="tab-lib" data-ws="lib" hidden={ui.ws !== 'lib'}>
  <Deck />
  <section class="mat" class:selecting={lib.sel.size > 0} id="mat" aria-label="Library">
    <MatHeader />
    <div class="zone-wrap">
      <p class="zlbl">Library<span class="jp" aria-hidden="true">ライブラリ</span></p>
      <div class="zone-lib">
        <div class="mat-art" aria-hidden="true"><i class="ma-dash t"></i><i class="ma-ln l"></i><i class="ma-ring"></i><i class="ma-ln r"></i><i class="ma-br b1"></i><i class="ma-br b2"></i><i class="ma-br b3"></i><i class="ma-br b4"></i><i class="ma-dash b"></i></div>
        <VirtualGrid />
      </div>
    </div>
    <p class="mat-ft"><span>Star a card to make it holo. Right-click a card for its menu.</span><span><kbd>Ctrl</kbd>+<kbd>K</kbd> commands · <kbd>/</kbd> search · <kbd>1</kbd>-<kbd>4</kbd> workspaces</span></p>
    <Tray />
  </section>
  <MapStrip />
</main>
