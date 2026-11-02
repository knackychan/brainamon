<script lang="ts">
  // The rail's Get started module (spec D2), pinned under Jobs while the welcome has an answer and Hide was
  // not pressed: six steps, with optional capabilities kept separate; a todo row opens its setup step. A library from before
  // the welcome never answered it, so it never shows this.
  import { untrack } from 'svelte'
  import { openSetup } from '../lib/command-table'
  import Hint from './ui/Hint.svelte'
  import { lib } from '../lib/library.svelte'
  import { desktopTasks, progressOf, SETUP_STEPS, type Task } from '../lib/onboarding'
  import { guiding, loadInstallChecks, onb, saveOnboarding, watchOnboarding } from '../lib/onboarding.svelte'
  import { toast } from '../lib/ui.svelte'

  watchOnboarding()
  $effect(() => { if (guiding()) untrack(() => { void loadInstallChecks() }) })
  // the library store follows new cards live; the server's counts cover a note and the first load
  const tasks = $derived(desktopTasks(onb.answer, { items: Math.max(onb.items, lib.rows.length), notes: onb.notes, wiskit: onb.wiskit, tools: onb.tools && onb.browser, drive: onb.drive, recovery: onb.recovery, phone: onb.phone }))
  const p = $derived(progressOf(tasks, true))

  function start(t: Task) {
    const step = SETUP_STEPS[['install', 'tools', 'saves', 'wiskit', 'drive', 'phone'].indexOf(t.id)]
    void saveOnboarding({ step }).catch(e => toast(`Could not save setup position: ${(e as Error).message}`, 'w'))
    openSetup()
  }
  function hide() {
    onb.hidden = true
    saveOnboarding({ hidden: true }).catch(e => { onb.hidden = false; toast(`Could not hide Get started: ${(e as Error).message}`, 'w') })
  }
</script>

{#if guiding()}
  <section class="wg gs" aria-labelledby="h-gs">
    <header class="wg-hd gs-hd"><h2 id="h-gs">Get started</h2><span class="n" role="status">{p.all ? 'Done' : `${p.done} of ${p.total}`}</span><button class="gs-x" type="button" onclick={hide}>Hide</button></header>
    <div class="prog gs-prog" aria-hidden="true">{#each tasks as t (t.id)}<i class:lit={t.done}></i>{/each}</div>
    <ol class="gs-list">
      {#each tasks as t (t.id)}
        <li>
          {#if t.done}
            <span class="gs-row done"><i class="gs-dot on" aria-hidden="true"><svg viewBox="0 0 12 12"><path d="M2.5 6.5 5 9l4.5-5.5" /></svg></i><span class="l">{t.label}</span><span class="sr">, done</span></span>
          {:else}
            <button class="gs-row" type="button" onclick={() => start(t)}><i class="gs-dot" aria-hidden="true"></i><span class="l">{t.label}</span><span class="gs-go" aria-hidden="true">›</span></button>
          {/if}
        </li>
      {/each}
    </ol>
    <Hint>Optional steps can wait. Hide keeps unfinished tasks available from App menu &gt; Setup.</Hint>
    {#if p.all}<p class="gs-end">Brainamon is ready.</p>{/if}
  </section>
{/if}

<style>
  .gs { flex: none; margin: 0 3px; gap: 8px }
  .gs-hd { grid-template-columns: minmax(0, 1fr) auto auto }
  .gs-x { border: 0; background: none; padding: 0 0 0 6px; font: var(--type-tag); letter-spacing: .08em; text-transform: uppercase; color: var(--wg-dim); cursor: pointer }
  .gs-x:hover { color: var(--wg-ink) }
  .gs-prog { grid-template-columns: repeat(6, minmax(0, 1fr)) }
  .gs-prog i.lit { background: var(--ok) }
  .gs-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px }
  .gs-row { display: flex; align-items: center; gap: 9px; width: 100%; min-height: 30px; padding: 4px 5px; border: 0; border-radius: 7px; background: none; color: var(--wg-ink); font: 500 12px/1.25 var(--mono); text-align: left }
  button.gs-row { cursor: pointer }
  button.gs-row:hover { background: var(--wg-2) }
  .gs-row .l { flex: 1; min-width: 0 }
  .gs-row.done { color: var(--wg-dim) }
  .gs-dot { flex: none; display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--wg-edge) }
  .gs-dot.on { border-color: var(--ok); background: var(--ok); color: #0b2a19 }
  .gs-dot svg { width: 10px; height: 10px; fill: none; stroke: currentColor; stroke-width: 2.2 }
  .gs-go { flex: none; font: 600 15px/1 var(--mono); color: var(--accent) }
  .gs-end { margin: 0; font: var(--type-small); color: var(--wg-dim) }
</style>
