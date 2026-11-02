<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte'
  import { api } from '../lib/api'
  import { NEED, type NeedKey, type Row } from '../lib/library.svelte'
  import { PROCESS_ACTIONS, processingEligible, processingTargets, recommendedProcessing } from '../lib/processing'
  import type { AO } from '../windows/AnalyzeOptionsForm.svelte'
  import { phone, refresh, replaceRow, source } from './state.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'

  let { rows, close }: { rows: Row[]; close: () => void } = $props()
  const actions = $derived(PROCESS_ACTIONS.filter(a => source.kind === 'desktop' || a.kind === 'describe' || a.kind === 'categorize'))
  let kind = $state<NeedKey>(untrack(() => source.kind === 'mirror' ? (['describe', 'categorize'] as NeedKey[]).find(k => rows.some(r => r.nd & NEED[k])) ?? 'describe' : recommendedProcessing(rows) ?? 'index'))
  let rerun = $state(false), busy = $state(false), stopping = false
  let progress = $state(''), error = $state(''), preview = $state<{ count: number; provider?: string; model?: string } | null>(null)
  let topic = $state(''), synthBusy = $state(false), synthLine = $state(''), synthFile = $state('')
  let analysis = $state<AO | null>(null), runningAnalyze = $state(false)
  let pcSetup = $state('Checking PC setup…')
  onMount(() => {
    if (source.kind === 'desktop') api.get<{ tools: Record<string, boolean>; cookies: boolean }>('/api/app/setup')
      .then(s => { pcSetup = `PC tools detected: ${Object.entries(s.tools).filter(([, found]) => found).map(([name]) => name).join(', ') || 'none'}. Saved access: ${s.cookies ? 'provided, not tested' : 'optional, not provided'}. Manage tools and site access on the PC.` })
      .catch(() => { pcSetup = 'PC setup is unavailable. Check that the PC is running and reachable.' })
  })
  const action = $derived(PROCESS_ACTIONS.find(a => a.kind === kind)!)
  const targets = $derived(source.kind === 'mirror' ? rows.filter(r => rerun || (kind === 'describe' ? !r.ai : kind === 'categorize' ? (r.cat === 'INTERESTING' || !r.cat) && !r.tags : false)).map(r => r.id) : processingTargets(rows, kind, rerun))
  const limit = source.kind === 'mirror' ? 25 : Infinity
  const chosen = $derived(targets.slice(0, limit))
  onDestroy(() => { stopping = true })

  function choose(k: NeedKey) { kind = k; rerun = false; preview = null; error = ''; progress = '' }
  async function review() {
    error = ''; progress = ''
    if (!chosen.length) return
    busy = true
    try {
      if (source.kind === 'mirror' && !source.ai?.()) throw new Error('Add an AI key under More > Wiskit on this phone, or pair this phone again with a key.')
      const result = source.kind === 'desktop'
        ? await api.post<{ count: number; provider?: string; model?: string }>('/api/jobs/preview', { kind, ids: chosen, force: rerun })
        : { count: chosen.length, provider: 'Phone', model: source.ai?.()?.label }
      preview = result
      if (!result.count) error = 'Nothing needs this step.'
      if (source.kind === 'desktop' && kind === 'analyze' && result.count) {
        const [settings, jobs] = await Promise.all([
          api.get<{ options: AO }>('/api/settings/analyze'), api.get<{ current?: { kind: string } }>('/api/jobs'),
        ])
        analysis = settings.options; runningAnalyze = jobs.current?.kind === 'analyze'
      }
    } catch (e) { error = (e as Error).message }
    finally { busy = false }
  }
  async function run() {
    if (!preview?.count || busy) return
    busy = true; error = ''; stopping = false
    try {
      if (source.kind === 'desktop') {
        const opts = kind === 'analyze' && !runningAnalyze ? analysis : {}
        if (kind === 'analyze' && !runningAnalyze) {
          if (!analysis || !(+analysis.frame_interval > 0 || analysis.transcribe)) throw new Error('Turn on frames or transcription before starting video analysis.')
          await api.put('/api/settings/analyze', analysis)
        }
        await api.post('/api/jobs', { kind, ids: chosen, force: rerun, opts })
        progress = `${action.label} started on the PC. Progress appears there.`
      } else {
        let done = 0
        for (const id of chosen) {
          if (stopping) break
          progress = `${action.label} ${done + 1} of ${chosen.length}…`
          if (kind === 'describe') {
            await source.describe!(id)
            const updated = await source.rowsByIds([id]); if (updated[0]) replaceRow(updated[0])
          } else if (kind === 'categorize') replaceRow(await source.categorize!(id, phone.cats.map(c => c.name)))
          done++
        }
        progress = `${done} item${done === 1 ? '' : 's'} processed${stopping ? ' before stopping' : ''}. Changes are saved on this phone and sync when connected.`
      }
      await refresh().catch(() => {})
      preview = null
    } catch (e) { error = (e as Error).message }
    finally { busy = false }
  }
  async function synthesize() {
    if (!topic.trim() || !source.synthesize || synthBusy) return
    synthBusy = true; error = ''; synthLine = ''; synthFile = ''
    try {
      const result = await source.synthesize(topic.trim(), rows.slice(0, rows.length === 1 ? 1 : 30).map(r => r.id), line => synthLine = line, new AbortController().signal)
      synthFile = result.file
    } catch (e) { error = (e as Error).message }
    finally { synthBusy = false }
  }
</script>

<section class="m-box m-process" aria-label="Process items">
  <div class="m-row"><h3>Process items</h3><span class="m-sp"></span><MButton size="sm" onclick={close} disabled={busy && source.kind === 'mirror'}>Close</MButton></div>
  <p class="m-hint">{rows.length} item{rows.length === 1 ? '' : 's'} in this scope. Choose one step; nothing runs until you review it.</p>
  <fieldset disabled={busy}>
    <legend class="m-lbl">Enrich and organize</legend>
    {#each actions as a (a.kind)}
      {@const eligible = rows.filter(r => processingEligible(r, a.kind)).length}
      {@const missing = source.kind === 'mirror' ? rows.filter(r => a.kind === 'describe' ? !r.ai : a.kind === 'categorize' ? (r.cat === 'INTERESTING' || !r.cat) && !r.tags : false).length : processingTargets(rows, a.kind).length}
      <label class="m-process-choice" class:on={kind === a.kind}>
        <input type="radio" name="m-process-kind" checked={kind === a.kind} disabled={!eligible} onchange={() => choose(a.kind)} />
        <span><b>{a.label}</b>{#if kind === a.kind}<small>{a.description}</small>{/if}<small>{a.kind === 'index' ? `${eligible} to check for changed text` : `${missing} missing this step · ${eligible} eligible`}</small></span>
      </label>
    {/each}
  </fieldset>
  {#if source.kind === 'mirror'}<p class="m-hint">Public previews and own-key Describe/Categorize can run on this phone. Video downloads, browser scraping, video analysis and search indexing run on a PC. A Drive mirror does not submit live PC jobs.</p>{:else}<p class="m-hint">Runs on your PC, which must be running and reachable. {pcSetup}</p>{/if}
  {#if kind !== 'index'}<label class="m-process-rerun"><input type="checkbox" bind:checked={rerun} onchange={() => preview = null} disabled={busy} /> Include completed items (run again)</label>{/if}
  {#if rerun}<p class="m-hint">{action.replace}</p>{:else}<p class="m-hint">Completed items are skipped.</p>{/if}
  {#if targets.length > limit}<p class="m-hint">This phone processes the first {limit} items at a time. Reopen to continue.</p>{/if}
  <div class="m-process-review" aria-live="polite"><b>{action.label} · {chosen.length} item{chosen.length === 1 ? '' : 's'}</b><small>{action.cost}</small>
    {#if preview}<small>Ready: {preview.count} · {preview.model ? `${preview.provider} · ${preview.model}` : 'Current settings'}. Text changing steps may also refresh the search index on the PC.</small>{/if}
  </div>
  <MHint>AI steps send relevant library text and selected images to the chosen provider or configured server; indexing sends text for embeddings. Video transcription sends audio to OpenAI even when the AI report is set to None. Direct-PC mode uses the PC's provider configuration. Provider charges apply separately; recipient terms and retention apply.</MHint>
  {#if kind === 'analyze' && preview && analysis}
    {#if runningAnalyze}<p class="m-hint">These videos join the running analysis and use its existing options.</p>{:else}
      <fieldset class="m-process-options" disabled={busy}>
        <legend class="m-lbl">Video options</legend>
        <label>Frame interval (seconds; 0 turns frames off)<input type="number" min="0" max="60" step="0.5" bind:value={analysis.frame_interval} /></label>
        <label><input type="checkbox" bind:checked={analysis.transcribe} /> Transcribe audio</label>
        <label>AI report<select bind:value={analysis.analysis_provider}><option value="none">None</option><option value="claude">Claude</option><option value="openai">OpenAI</option><option value="freellmapi">FreeLLMAPI</option></select></label>
        <label>Frames sent to AI<select bind:value={analysis.ai_frame_budget}><option value="auto">Auto</option><option value="0">Off</option><option value="8">Up to 8</option><option value="15">Up to 15</option><option value="24">Up to 24</option></select></label>
        <label><input type="checkbox" bind:checked={analysis.keep_frames} /> Keep extracted frames</label>
        <label><input type="checkbox" bind:checked={analysis.show_frames_in_canvas} disabled={!analysis.keep_frames} /> Show frames in item canvas</label>
        <label><input type="checkbox" bind:checked={analysis.delete_video} /> Delete downloaded video after analysis</label>
        <label><input type="checkbox" bind:checked={analysis.delete_audio} /> Delete extracted audio after analysis</label>
      </fieldset>
    {/if}
  {/if}
  {#if progress}<p class="m-hint" role="status">{progress}</p>{/if}
  {#if error}<p class="m-hint err" role="alert">{error}</p>{/if}
  <div class="m-acts">
    {#if busy && source.kind === 'mirror'}<MButton onclick={() => stopping = true}>Stop after item</MButton>{:else}<MButton disabled={busy || !chosen.length} onclick={review}>Review {chosen.length}</MButton>{/if}
    <MButton variant="dk" disabled={busy || !preview?.count} onclick={run}>Start {preview?.count ?? chosen.length}</MButton>
  </div>
  <div class="m-process-use">
    <h3>Use saved content</h3>
    <p class="m-hint"><a href="#/jv">Ask Wiskit</a> for an answer with citations. It does not change your items.</p>
    {#if source.synthesize}
      <p class="m-hint">Synthesize writes a note from available item text. {rows.length > 1 ? 'Uses up to the first 30 items in this scope.' : 'Uses this item.'}</p>
      <label class="m-lbl">Note topic<input type="text" bind:value={topic} placeholder="Topic" /></label>
      <MButton disabled={synthBusy || !topic.trim()} onclick={synthesize}>{synthBusy ? 'Writing…' : 'Synthesize a note'}</MButton>
      {#if synthLine}<p class="m-hint" role="status">{synthLine}</p>{/if}
      {#if synthFile}<MButton as="a" href={`#/notes/${encodeURIComponent(synthFile)}`}>Open note</MButton>{/if}
    {/if}
  </div>
</section>

<style>
  .m-process { margin: 12px; gap: 10px }
  .m-process p { margin: 0 }
  .m-process fieldset { margin: 0; padding: 0; border: 0; min-width: 0 }
  .m-process legend { padding: 0 0 5px }
  .m-process-choice { display: flex; gap: 10px; padding: 10px; border: 1px solid var(--wg-edge); border-radius: 8px; margin: 6px 0; color: var(--wg-ink) }
  .m-process-choice.on { border-color: var(--accent) }
  .m-process-choice input { flex: none; accent-color: var(--accent) }
  .m-process-choice span { display: grid; gap: 3px; min-width: 0 }
  .m-process-choice small, .m-process-review small { font: 500 11px/1.4 var(--display); color: var(--wg-dim) }
  .m-process-rerun { display: flex; align-items: center; gap: 8px; min-height: 40px; font-size: 12px }
  .m-process-rerun input { accent-color: var(--accent) }
  .m-process-review { display: grid; gap: 4px; padding: 10px; border: 1px dashed var(--wg-edge); border-radius: 8px }
  .m-process > .m-acts { position: sticky; bottom: 0; z-index: 2; padding: 8px 0; background: var(--wg) }
  .m-process-options { display: grid; gap: 8px; border: 1px solid var(--wg-edge) !important; border-radius: 8px !important; padding: 10px !important }
  .m-process-options label { display: grid; gap: 4px; font: 500 12px/1.4 var(--display) }
  .m-process-options label:has(input[type=checkbox]) { display: flex; align-items: center }
  .m-process-options input:not([type=checkbox]), .m-process-options select { min-height: 38px; border: 1px solid var(--wg-edge); border-radius: 6px; padding: 6px; background: var(--wg); color: var(--wg-ink) }
  .m-process-use { display: grid; gap: 8px; padding-top: 10px; border-top: 1px solid var(--wg-edge) }
  .m-process-use h3 { margin: 0 }
  .m-process-use label { display: grid; gap: 5px }
  .m-process-use input { min-height: 40px; border: 1px solid var(--wg-edge); border-radius: 6px; padding: 6px; background: var(--wg); color: var(--wg-ink) }
</style>
