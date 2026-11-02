<script lang="ts">
  // The loading bar under the menubar: shown while any API request is in flight (a workspace
  // loading its data, a refetch, a save), after 150 ms so quick requests never flash it.
  import { net } from '../lib/net.svelte'
</script>

<div class="loadbar" class:on={net.n > 0} role="progressbar" aria-label="Loading" aria-hidden={net.n === 0}><i></i></div>

<style>
  .loadbar{position:fixed;left:0;right:0;top:38px;height:3px;z-index:31;overflow:hidden;pointer-events:none;opacity:0;transition:opacity .2s}
  .loadbar.on{opacity:1;transition:opacity .12s .15s}
  .loadbar i{position:absolute;top:0;bottom:0;left:0;width:32%;background:var(--accent);box-shadow:0 0 8px var(--accent);transform:translateX(-100%)}
  .loadbar.on i{animation:lb 1.1s cubic-bezier(.4,0,.2,1) infinite}
  @keyframes lb{to{transform:translateX(320%)}}
</style>
