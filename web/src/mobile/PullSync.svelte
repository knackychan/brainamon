<script lang="ts">
  // The pull-to-refresh widget: Mobile.svelte drives the gesture and passes how far the finger
  // pulled (1 = far enough). While pulling it says what letting go does; during a sync it lists the
  // phone's own steps (state.svelte.ts syncNow) and ends on done or the reason it stopped. A running
  // sync is a row of the app bar (mobile.css .m-pull-live), so it pushes the screen down rather than
  // covering it; the fold button keeps only the bar (remembered until the page reloads).
  import { closeSync, mirrorSource, phone, source, syncFill } from './state.svelte'
  import { syncPaused } from './network.svelte'

  let { pull = 0 }: { pull?: number } = $props()
  const run = $derived(phone.sync)
  const MARK = { wait: '·', run: '…', ok: '✓', err: '!' }
  const where = source.kind === 'mirror' ? 'Google Drive' : 'the PC'
  // the progress bar: steps finished out of all, the running one counts half
  const total = $derived(run?.steps.length ?? 0)
  const done = $derived(run ? run.steps.filter(s => s.state === 'ok' || s.state === 'err').length : 0)
  const fill = $derived(run ? syncFill(run) : 0)
  let folded = $state(false)
</script>

{#if (run || pull > 0) && !(mirrorSource && syncPaused())}
  <div class="m-pull" class:m-pull-live={!!run} class:m-pull-armed={!run && pull >= 1} class:m-pull-failed={run?.end === 'error'}
    style:--m-pull={run ? 1 : Math.min(1, pull)} role="status" aria-live="polite">
    {#if run}
      {#if !folded}
        <ol class="m-pull-steps">
          {#each run.steps as s (s.key)}
            <li class={`m-pull-${s.state}`}><i aria-hidden="true">{MARK[s.state]}</i><span>{s.label}{#if s.note}<small>{s.note}</small>{/if}</span></li>
          {/each}
        </ol>
      {/if}
      <div class="m-pull-bar">
        <span class="m-pull-track" role="progressbar" aria-label="Sync progress" aria-valuemin={0} aria-valuemax={total} aria-valuenow={run.end ? total : done}><b style:width={`${fill * 100}%`}></b></span><span>{run.end ? total : done}/{total}</span>
        <button type="button" class="m-pull-btn" onclick={() => (folded = !folded)} aria-expanded={!folded} aria-label={folded ? 'Show the sync steps' : 'Hide the sync steps'}>{folded ? '▾' : '▴'}</button>
        {#if run.end}<button type="button" class="m-pull-btn" onclick={closeSync} aria-label="Close">×</button>{/if}
      </div>
      {#if run.end}<p class="m-pull-end">{run.msg}</p>{/if}
    {:else}
      <span class="m-pull-hint"><i aria-hidden="true">↓</i>{pull >= 1 ? 'Release' : 'Pull'} to sync with {where}</span>
      <!-- how far to the mark: full means letting go syncs -->
      <div class="m-pull-bar" aria-hidden="true"><span class="m-pull-track"><b style:width={`${Math.min(1, pull) * 100}%`}></b></span></div>
    {/if}
  </div>
{/if}
