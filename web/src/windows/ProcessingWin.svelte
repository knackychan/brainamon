<script lang="ts">
  import { untrack } from 'svelte'
  import { askAbout } from '../lib/ask.svelte'
  import { live } from '../lib/events.svelte'
  import { lib, type NeedKey } from '../lib/library.svelte'
  import { jobBusy, jobBusyMsg, jobHooks, startJob, plural } from '../lib/jobs'
  import Hint from '../components/ui/Hint.svelte'
  import TextButton from '../components/ui/TextButton.svelte'
  import { PROCESS_ACTIONS, processingEligible, processingTargets, recommendedProcessing } from '../lib/processing'

  let { ids, scope, initial, close }: { ids: number[]; scope: string; initial?: NeedKey; close: () => void } = $props()
  const rows = $derived(ids.flatMap(id => { const row = lib.byId.get(id); return row ? [row] : [] }))
  const recommendation = $derived(recommendedProcessing(rows))
  let chosen = $state<NeedKey>(untrack(() => initial ?? recommendedProcessing(rows) ?? 'index'))
  let rerun = $state(false)
  let starting = $state(false)
  const action = $derived(PROCESS_ACTIONS.find(a => a.kind === chosen)!)
  const targets = $derived(processingTargets(rows, chosen, rerun))
  // every eligible item already has the step: the Review key stays off until the user chooses to run it again
  const allDone = $derived(chosen === 'index' || rerun || targets.length ? 0 : rows.filter(r => processingEligible(r, chosen)).length)
  const blocked = $derived(jobBusy() && !(chosen === 'analyze' && live.jobs.current?.kind === 'analyze'))
  const visibleIds = $derived(new Set(lib.visIds))
  const hidden = $derived(rows.filter(r => !visibleIds.has(r.id)).length)
  // same rule as Process > Synthesize with no selection: the first 30 visible items
  const visibleScope = $derived(scope === 'Visible items')
  const noteIds = $derived(rows.map(r => r.id).slice(0, visibleScope ? 30 : undefined))

  async function go() {
    starting = true
    try {
      if (await startJob(chosen, { ids: targets, force: chosen !== 'index' && rerun, from: visibleScope ? 'visible' : 'selection' })) close()
    } finally { starting = false }
  }
  async function synthesize() {
    starting = true
    try { if (await startJob('note', { ids: noteIds, from: visibleScope ? 'visible' : 'selection' })) close() }
    finally { starting = false }
  }
</script>

<div class="cw-body processing-body">
  <p class="scope"><b>{scope} · {plural(rows.length, 'item')}</b>{#if hidden}<span>{hidden} outside the current filters</span>{/if}</p>
  <p class="hint">Choose what you want to add. Only the step you choose will run. You’ll review its cost and options before it starts.</p>
  {#if !rows.length}
    <p class="hint" role="status">No items in this scope. Close this window and select items or change the Library filters.</p>
  {:else}
    <fieldset disabled={starting}>
      <legend>Enrich and organize</legend>
      {#each PROCESS_ACTIONS as a (a.kind)}
        {@const eligible = rows.filter(r => processingEligible(r, a.kind)).length}
        {@const count = processingTargets(rows, a.kind).length}
        <label class="processing-choice" class:chosen={chosen === a.kind}>
          <input type="radio" name="processing-action" value={a.kind} bind:group={chosen} disabled={!eligible} onchange={() => rerun = false} />
          <span>
            <span class="choice-heading"><b>{a.label}</b>{#if recommendation === a.kind}<em>Suggested next</em>{/if}</span>
            {#if chosen === a.kind}<span class="choice-description">{a.description}</span>{/if}
            <span class="choice-count">{!eligible ? (a.kind === 'thumb' ? 'No web links in this scope' : 'No videos in this scope') : a.kind === 'index' ? `${plural(count, 'item')} to check for changed text` : `${count} missing this step · ${eligible} eligible`}</span>
          </span>
        </label>
      {/each}
    </fieldset>
    {#if !recommendation}<p class="hint">No routine steps are missing. Video analysis is optional; you can also check the search index for changed text.</p>{/if}
    <div class="processing-review" aria-live="polite">
      <b>{action.label} · {plural(targets.length, 'item')}</b>
      <p>{action.cost}</p>
      {#if chosen !== 'index'}
        <label class="rerun"><input type="checkbox" bind:checked={rerun} disabled={starting} /> Include completed items (run again)</label>
        {#if rerun}<p>{action.replace}</p>{:else if allDone}<p>{allDone === 1 ? 'This item already has' : `All ${allDone} items already have`} this step, so nothing will run. Tick the box above to run it again.</p>{:else}<p>Completed items are skipped.</p>{/if}
      {/if}
      {#if !targets.length && !allDone}<p>Nothing needs this step. Choose another action.</p>{/if}
      <p>Text changes also refresh the search index; embeddings charges may apply.</p>
    </div>
    <section class="processing-use" aria-labelledby="processing-use-title">
      <h3 id="processing-use-title">Use your saved content</h3>
      <div><button class="wkey" type="button" disabled={starting} onclick={() => { close(); askAbout(rows.map(r => r.id)) }}>Ask Wiskit</button><p>Start a chat answer about these items, with sources. Uses your Wiskit model; charges may apply.{rows.length > 8 ? ' The opening question names the first 8 items.' : ''}</p></div>
      <div><button class="wkey" type="button" disabled={starting || jobBusy()} onclick={synthesize}>Synthesize a note…</button><p>Combine the available text into one saved note in Knowledge. You’ll choose a topic and review an AI cost estimate. Items without usable text are skipped.{visibleScope && rows.length > 30 ? ' Uses the first 30 visible items; select items to choose others.' : ''}</p></div>
    </section>
  {/if}
  {#if jobBusy()}<p class="hint" role="status">{blocked ? jobBusyMsg() : 'These videos will join the running analysis and use its options.'}. <button class="linkk" type="button" onclick={() => jobHooks.openProgress?.()}>Show progress</button></p>{/if}
</div>
<div class="cw-foot">
  {#if allDone && !blocked}<Hint as="span" role="status">Already done.</Hint>{/if}
  <span class="sp"></span>
  <button class="wkey" type="button" onclick={close}>Close</button>
  {#if allDone && !blocked}<TextButton disabled={starting} onclick={() => rerun = true}>Run again</TextButton>{/if}
  <button class="wkey pri" type="button" disabled={starting || blocked || !targets.length} onclick={go}>{starting ? 'Reviewing…' : `Review ${action.label.toLowerCase()}…`}</button>
</div>

<style>
  .processing-body { display: grid; gap: 14px }
  .processing-body p { margin: 0; line-height: 1.5 }
  .scope { display: flex; flex-wrap: wrap; gap: 4px 12px }
  .scope span { font-size: 12px }
  fieldset { min-width: 0; margin: 0; padding: 0; border: 0 }
  legend, h3 { margin: 0 0 8px; font: 700 14px/1.4 var(--display) }
  .processing-choice { display: flex; align-items: start; gap: 10px; padding: 11px 4px; border-bottom: 1px solid var(--line); cursor: pointer }
  .processing-choice input { margin-top: 3px; flex: 0 0 auto; accent-color: var(--accent) }
  .processing-choice:focus-within { outline: 2px solid var(--accent); outline-offset: 2px }
  .processing-choice.chosen b { text-decoration: underline; text-underline-offset: 3px }
  .choice-heading { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 13px }
  .choice-heading em { font-size: 11px; font-style: normal }
  .choice-description, .choice-count { display: block; margin-top: 4px; font-size: 12px; line-height: 1.5 }
  .choice-count { font-weight: 600 }
  .processing-review { padding: 12px; border: 1px solid var(--line); border-radius: 6px; font-size: 12px; display: grid; gap: 6px }
  .rerun { display: flex; align-items: center; gap: 8px; padding: 4px 0 }
  .processing-use > div { display: grid; grid-template-columns: 175px minmax(0, 1fr); align-items: start; gap: 10px; margin-top: 10px }
  .processing-use p { font-size: 12px }
  @media (max-width: 540px) { .processing-use > div { grid-template-columns: 1fr } .processing-use button { justify-self: start } }
</style>
