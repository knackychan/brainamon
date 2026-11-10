<script lang="ts">
  // The Tools key's ring (projects/phone-processing-flow, decision 3): while a run started from this phone's panel
  // goes on with the panel closed, an orange ring fills round the key and a badge counts the items left; once it
  // ended with failures, a red badge counts them. Nothing is drawn while the panel is open. Inside the key's MKey
  // it draws (aria-hidden); the same component with `status` after the key is the spoken version (a polite status
  // the key is described by), so a screen reader hears the progress without leaving the key.
  import { current } from './tools-run.svelte'
  import { toolText } from './tools-words.ts'
  import { progress, ringText } from './tools'

  let { open, status = false }: { open: boolean; status?: boolean } = $props()
  const run = $derived(current())
  const p = $derived(run ? progress(run) : null)
</script>

{#if status}
  <span id="m-tools-status" class="m-sr" role="status">{#if !open && run && p}{ringText(p, run.ended, toolText)}{/if}</span>
{:else if !open && run && p}
  {#if !run.ended}
    <span class="m-tools-ring" style:--p="{Math.round(100 * (p.n - p.left) / Math.max(1, p.n))}%" aria-hidden="true"></span>
    <span class="m-tools-n" aria-hidden="true">{p.left}</span>
  {:else if p.err}
    <span class="m-tools-n m-tools-err" aria-hidden="true">{p.err}</span>
  {/if}
{/if}
