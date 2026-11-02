<script lang="ts">
  // 10 View: Grid / List, and the card style Full / Cover.
  import Wg from './Wg.svelte'
  import { lib, setFilter } from '../../../lib/library.svelte'
</script>

<Wg cls="v s2" id="view" title="View" jp="表示" n="2">
  <p class="wg-l">Layout</p>
  <div class="wseg" role="group" aria-label="Layout">
    <button type="button" aria-pressed={lib.view === 'grid'} onclick={() => setFilter('view', 'grid')}>Grid</button>
    <button type="button" aria-pressed={lib.view === 'list'} onclick={() => setFilter('view', 'list')}>List</button>
  </div>
  <p class="wg-l">Card</p>
  <div class="wseg" role="group" aria-label="Card style">
    <button type="button" aria-pressed={lib.variant === 'fa2'} title="Full art: the art fills the card, text on the art" onclick={() => setFilter('variant', 'fa2')}>Full</button>
    <button type="button" aria-pressed={lib.variant === 'full'} title="Cover: the art on top, the description on a ticket body below" onclick={() => setFilter('variant', 'full')}>Cover</button>
  </div>
</Wg>
