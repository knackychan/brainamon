<script lang="ts">
  // The window stack (V6 stackWins): z-index 70 + 2i, the scrim under the top window, older
  // windows marked .under. A scrim click closes the top window unless it is an alert.
  import { closeWin, topWin, wins } from '../lib/windows.svelte'
  import WinFrame from './WinFrame.svelte'
  import ActionPopup from './ActionPopup.svelte'

  function scrimClick() {
    const w = topWin()
    if (w && (w.popup || !w.alert)) closeWin(w)
  }
</script>

<div class="cw-scrim" class:action-scrim={topWin()?.popup} id="cw-scrim" hidden={!wins.length} style:z-index={69 + (wins.length - 1) * 2} role="presentation" onclick={scrimClick}></div>
{#each wins as w, i (w.n)}
  {#if w.popup}
    <ActionPopup {w} z={70 + i * 2} under={i < wins.length - 1} />
  {:else}
    <WinFrame {w} z={70 + i * 2} under={i < wins.length - 1} />
  {/if}
{/each}
