<script lang="ts">
  // 12 System: Motion, Night, Sound (after parity, plan 15), Console.
  import Wg from './Wg.svelte'
  import { runCmd } from '../../../lib/commands'
  import { ui } from '../../../lib/ui.svelte'
  const keys: [string, string, () => boolean][] = [
    ['motion', 'Motion', () => !ui.motionOff], ['night', 'Night', () => ui.dark],
    ['sound', 'Sound', () => false], ['console', 'Console', () => ui.consoleOpen],
  ]
</script>

<Wg cls="s6" id="sys" title="System" jp="設定" n="4">
  <div class="sw" role="group" aria-label="System">
    {#each keys as [a, l, on] (a)}<button type="button" class="swk" aria-pressed={on()} onclick={() => runCmd(a)}><span>{l}</span><i aria-hidden="true"></i></button>{/each}
  </div>
</Wg>
