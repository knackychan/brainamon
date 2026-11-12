<script lang="ts">
  import { captureError } from './capture-words.ts'
  import { t } from '../lib/i18n/index.ts'
  import { toolText, keyMessage, replaceText } from './tools-words.ts'
  // The Tools panel (projects/phone-processing-flow, option C): one row per step, a tap on a row starts it; a
  // confirm line grows inside the row only for big batches, Run again and Analyze (tools.ts needsConfirm). The run
  // (tools-run.svelte.ts) outlives the panel: its heading row, a ledger of items and the run bar replace the rows
  // while it goes on; finished, the ledger lists Failed and Skipped first with their reasons. The finished bar's key
  // (Retry, Continue, Next) goes through the same preview and confirm line as a first start. Direct PC jobs show here
  // from their events (pc-jobs.svelte.ts). The words are tools.ts; lib/processing.ts keeps the PC's targets.
  // A run keeps the scope it started on, whichever screen reopens the panel; every way out of the panel (Escape, a
  // tap outside, Back, the Tools key, a route change) ends here in leave(): a finished run goes, a running one stays.
  // Escape asks first (cancel) and the browser may send the close event late, so the decision is made at the request.
  import { onMount, tick, untrack } from 'svelte'
  import { api } from '../lib/api'
  import type { Row } from '../lib/library.svelte'
  import { processingTargets, recommendedProcessing } from '../lib/processing'
  import type { AO } from '../windows/AnalyzeOptionsForm.svelte'
  import { setMoreFrom } from './back'
  import { openMoreBox } from './onboard.svelte'
  import { phone, solo, source } from './state.svelte'
  import { beginLanguageWork } from './language-switch.ts'
  import ShellIcon from './ShellIcon.svelte'
  import { chargeLine, confirmGo, confirmText, ledgerWindow, MAIN_STEPS, needsConfirm, nextKey, PC_STEPS, pcBusy, PHONE_LIMIT,
    phoneTargets, PROVIDER, progress, stepWords, runNote, savedLine, scopeText, STEPS, stopLabel, summary, whereLine, type Act, type StepKind, type ToolsSrc } from './tools'
  import { current, dismiss, followPlan, runPc, runPhone, startFollow, stopRun, undo, type Plan } from './tools-run.svelte'
  import MButton from './ui/MButton.svelte'
  import MDisclosure from './ui/MDisclosure.svelte'
  import MInfo from './ui/MInfo.svelte'
  import MKey from './ui/MKey.svelte'
  import MRow from './ui/MRow.svelte'
  import MRunBar from './ui/MRunBar.svelte'
  import MStepRow from './ui/MStepRow.svelte'
  import MTextButton from './ui/MTextButton.svelte'
  import MToggle from './ui/MToggle.svelte'
  import { pcResult, runs, type RunItem } from './work.svelte'
  import './tools.css'

  let { rows, close, anchor, item = false, heading = 'Items' }: { rows: Row[]; close: () => void; anchor?: HTMLElement; item?: boolean; heading?: string } = $props()
  let dialog: HTMLDialogElement
  function position() {
    if (!anchor || !dialog) return
    const r = anchor.getBoundingClientRect()
    const above = !!anchor.closest('.m-dock')
    const top = above ? 12 : Math.min(r.bottom + 8, window.innerHeight - 180)
    dialog.style.setProperty('--process-top', `${Math.max(12, top)}px`)
    dialog.style.setProperty('--process-bottom', above ? `${window.innerHeight - r.top + 8}px` : 'auto')
    const box = dialog.getBoundingClientRect()
    dialog.style.setProperty('--process-notch', `${Math.max(18, Math.min(box.width - 18, r.left + r.width / 2 - box.left))}px`)
    if (dialog.contains(document.activeElement) && document.activeElement instanceof HTMLInputElement && document.activeElement.type === 'text') document.activeElement.scrollIntoView({ block: 'nearest' })
  }
  // a tap outside closes the panel; a run goes on (decision 3)
  function outside(e: MouseEvent) {
    if (e.target !== dialog) return
    const r = dialog.getBoundingClientRect()
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { e.preventDefault(); dialog.close() }
  }

  const pc = source.kind === 'desktop'
  const src: ToolsSrc = pc ? 'pc' : solo ? 'solo' : 'phone'
  const steps: StepKind[] = pc ? [...MAIN_STEPS, ...PC_STEPS] : ['thumb', ...MAIN_STEPS]
  const limit = pc ? Infinity : PHONE_LIMIT
  const ai = untrack(() => (pc ? null : source.ai?.() ?? null))
  const byId = $derived(new Map(phone.rows.map(r => [r.id, r])))
  const live = $derived(rows.map(r => byId.get(r.id) ?? r))         // the panel's rows as the run changes them
  let rerun = $state(false), err = $state(''), open = $state(false)
  // one preview or one start at a time ('starting' = submitted: closing the panel does not take it back)
  let work = $state<'idle' | 'checking' | 'starting'>('idle')
  let ask = $state<StepKind | 'follow' | null>(null)
  interface Pre { kind: StepKind; ids: number[]; rest: number[]; n: number; all: number; provider: string; rerun: boolean; act: Act | null; plan: Plan | null }
  let pre = $state<Pre | null>(null)
  let gen = 0                                       // a preview or a confirm line belongs to one generation: leaving or cancelling ends it
  let settleUntil = 0                               // the run view replaces the confirm line under the finger: a second tap right after a start lands on nothing
  let pcAi = $state<{ provider: string; model: string } | null>(null)
  let analysis = $state<AO | null>(null), joining = $state(false)
  let topic = $state(''), synthBusy = $state(false), synthLine = $state(''), synthFile = $state('')
  let pcSetup = $state(t('processing.setup.checking'))

  const eff = (k: StepKind) => rerun && k !== 'index'           // Index looks for changed text itself; Run again would embed everything
  const targetsOf = (k: StepKind) => (pc ? processingTargets(live, k, eff(k)) : phoneTargets(live, k, eff(k)))
  const counts = $derived(Object.fromEntries(steps.map(k => [k, targetsOf(k).length])) as Record<StepKind, number>)
  const rec = $derived(pc ? recommendedProcessing(live) : MAIN_STEPS.find(k => counts[k] > 0) ?? (counts.thumb ? 'thumb' : null))
  const provider = pc ? '' : PROVIDER[ai?.provider ?? ''] ?? ai?.provider ?? ''
  // the phone's own key serves both its steps; the PC's keys are checked per step by that step's own preview
  const noKey = $derived(pc ? '' : ai ? '' : source.noKeyText?.(toolText) ?? t('processing.noKey'))
  const where = $derived(pc ? whereLine('pc', PROVIDER[pcAi?.provider ?? ''] ?? pcAi?.provider ?? '', pcAi?.model ?? '', toolText) : whereLine(src, provider, ai?.label || ai?.model || '', toolText))
  const run = $derived(current())
  const busyJob = $derived(!run && pc ? runs.pcJob : null)
  const scopeLine = $derived.by(() => {
    if (!run) return scopeText(item, heading, rows.length, toolText)
    if (run.scope.item) return rows.length === 1 && rows[0].id === run.items[0]?.id ? t('processing.scope.item') : run.scope.heading
    return scopeText(false, run.scope.heading, run.scope.count, toolText)
  })
  const scopeNow = () => (item ? { item: true, heading: rows[0]?.title || rows[0]?.url || t('processing.scope.item'), count: 1 } : { item: false, heading, count: rows.length })

  // every way out: a finished run is reviewed and goes, a running one stays; a preview in flight is called off
  function invalidate() { gen++; ask = null; pre = null; if (work === 'checking') work = 'idle' }
  function leave() {
    invalidate()
    const r = current()
    if (r?.ended) dismiss(r.lane)
  }

  onMount(() => {
    const scroller = anchor?.closest<HTMLElement>('.m-main')
    const oldPadding = scroller?.style.paddingBottom ?? '', oldScroll = scroller?.scrollTop ?? 0
    if (anchor && scroller) {
      scroller.style.paddingBottom = '100dvh'
      scroller.scrollTop += Math.max(0, anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 20)
    }
    dialog.showModal()
    position()
    window.addEventListener('resize', position)
    if (pc) {
      api.get<{ tools: Record<string, boolean>; cookies: boolean }>('/api/app/setup')
        .then(s => { pcSetup = t('processing.setup.line', { tools: Object.entries(s.tools).filter(([, found]) => found).map(([name]) => name).join(', ') || t('processing.setup.none'), access: t(s.cookies ? 'processing.setup.provided' : 'processing.setup.optional') }) })
        .catch(() => { pcSetup = t('processing.setup.unavailable') })
      // the line under the rows: the PC's provider and model (informational: each step checks its own key when tapped)
      const ids = untrack(() => (processingTargets(live, 'describe').slice(0, 1).length ? processingTargets(live, 'describe').slice(0, 1) : live.slice(0, 1).map(r => r.id)))
      if (ids.length) api.post<{ provider?: string; model?: string }>('/api/jobs/preview', { kind: 'describe', ids, force: true })
        .then(p => { pcAi = { provider: p.provider ?? '', model: p.model ?? '' } })
        .catch(() => { /* the line says only where it runs */ })
    }
    return () => {
      window.removeEventListener('resize', position)
      if (scroller) { scroller.style.paddingBottom = oldPadding; scroller.scrollTop = oldScroll }
      leave()
    }
  })

  // keyboard focus follows the panel: a started run puts it on its Stop key, a finished one on the key to press next
  let focusRun = false
  $effect(() => {
    const r = run, ended = r?.ended
    if (!r) return
    if (focusRun || (ended && dialog && (dialog.contains(document.activeElement) || document.activeElement === document.body))) {
      focusRun = false
      void tick().then(() => dialog?.querySelector<HTMLElement>('[data-tl-focus]:not(:disabled)')?.focus())
    }
  })

  interface Preview { count: number; provider?: string; model?: string; key?: boolean }
  const named = (p: string | undefined) => PROVIDER[p ?? ''] ?? p ?? ''

  // The one path every start takes, a first tap and a follow-up key alike: targets, then the PC's preview of this step,
  // then the confirm line when the rule asks (tools.ts needsConfirm), else the start.
  async function prepare(k: StepKind, f: Plan | null = null) {
    err = ''
    if (work !== 'idle' || (!f && ask === k)) return
    ask = null; pre = null
    const ids = f ? f.ids : targetsOf(k)
    const re = f ? f.rerun : eff(k)
    if (!ids.length) { if (f && !pc) await startFollow(f); return }
    const my = ++gen
    if (!pc) {
      const chosen = f ? ids : ids.slice(0, limit)
      pre = { kind: k, ids: chosen, rest: f ? [] : ids.slice(limit), n: chosen.length, all: f ? chosen.length : ids.length, provider, rerun: re, act: f?.act ?? null, plan: f }
      if (needsConfirm(k, chosen.length, re) || (!f && ids.length > limit)) { ask = f ? 'follow' : k; return }
      await start()
      return
    }
    work = 'checking'
    let confirm = false
    try {
      if (k === 'analyze' && !f) {
        // the options open first: a saved option or a missing key is fixed here, and the chosen options are what the PC previews
        const [settings, jobs] = await Promise.all([api.get<{ options: AO }>('/api/settings/analyze'), api.get<{ current?: { kind: string } | null }>('/api/jobs')])
        if (my !== gen) return
        analysis = settings.options; joining = jobs.current?.kind === 'analyze'
        pre = { kind: k, ids, rest: [], n: ids.length, all: ids.length, provider: '', rerun: re, act: null, plan: null }
        ask = k
        return
      }
      const p = await api.post<Preview>('/api/jobs/preview', { kind: k, ids, force: re, opts: f?.opts ?? {} })
      if (my !== gen) return                       // closed or cancelled meanwhile: nothing starts
      if (!p.count) { err = t('processing.emptyStep'); return }
      if (STEPS[k].charge !== 'none' && p.key === false) { err = keyMessage(k); return }
      pre = { kind: k, ids, rest: [], n: p.count, all: p.count, provider: named(p.provider), rerun: re, act: f?.act ?? null, plan: f }
      confirm = needsConfirm(k, p.count, re)
      if (confirm) ask = f ? 'follow' : k
    } catch (e) {
      if (my === gen) err = captureError(e)
      return
    } finally { if (my === gen) work = 'idle' }
    if (!confirm) await start()
  }

  async function start() {
    const p = pre
    if (!p || work === 'starting') return
    const my = gen
    const finishLanguageWork = beginLanguageWork()
    err = ''
    work = 'starting'
    focusRun = true
    settleUntil = Date.now() + 600
    try {
      const scope = p.plan?.scope ?? scopeNow()
      if (!pc) {
        // the phone's loop runs on after this returns: the confirm line is done with at once
        ask = null; pre = null
        void Promise.resolve(p.plan ? startFollow(p.plan) : runPhone(p.kind as 'thumb' | 'describe' | 'categorize', p.ids, { rest: p.rest, rerun: p.rerun, scope })).catch(e => { err = captureError(e) })
      } else if (p.plan) await startFollow(p.plan)
      else if (p.kind === 'analyze' && joining) await runPc('analyze', p.ids, { rerun: p.rerun, scope, joined: true })
      else if (p.kind === 'analyze') {
        if (!analysis || !(+analysis.frame_interval > 0 || analysis.transcribe)) throw new Error(t('processing.framesRequired'))
        const opts = { ...analysis }
        // the options chosen here are previewed before anything starts: an invalid one or a missing key is answered by the PC
        const v = await api.post<Preview>('/api/jobs/preview', { kind: 'analyze', ids: p.ids, force: p.rerun, opts })
        if (my !== gen) return
        if (!v.count) throw new Error(t('processing.emptyStep'))
        if (v.key === false) throw new Error(keyMessage('analyze'))
        await api.put('/api/settings/analyze', opts)
        if (my !== gen) return
        await runPc('analyze', p.ids, { rerun: p.rerun, opts, scope })
      } else await runPc(p.kind, p.ids, { rerun: p.rerun, scope })
      if (my === gen) { ask = null; pre = null }
    } catch (e) {
      focusRun = false
      err = captureError(e)
    } finally { work = 'idle'; finishLanguageWork() }
  }
  function cancelAsk() { gen++; ask = null; pre = null }
  function follow(act: Act) {
    err = ''
    const f = followPlan(act)
    if (!f) { err = t('processing.emptyRun'); return }
    void prepare(f.kind, f)
  }
  async function act(fn: () => Promise<unknown> | unknown) {
    err = ''
    try { await fn() } catch (e) { err = captureError(e) }
  }
  async function done() {
    invalidate()
    const r = current()
    if (r) dismiss(r.lane)
    await tick()
    dialog?.querySelector<HTMLElement>('.m-step-rw:not(:disabled)')?.focus()
  }
  function addKey() {
    dialog.close()
    if (solo) { setMoreFrom(location.hash); void openMoreBox('m-ai') } else location.hash = '#/backup'
  }
  async function synthesize() {
    if (!topic.trim() || !source.synthesize || synthBusy) return
    const finishLanguageWork = beginLanguageWork()
    synthBusy = true; err = ''; synthLine = ''; synthFile = ''
    try {
      const result = await source.synthesize(topic.trim(), rows.slice(0, rows.length === 1 ? 1 : 30).map(r => r.id), line => synthLine = line, new AbortController().signal, toolText)
      synthFile = result.file
    } catch (e) { err = captureError(e) }
    finally { synthBusy = false; finishLanguageWork() }
  }
  const thumbOf = (id: number) => { const r = byId.get(id); return r?.thumb ? source.thumbUrl(r, 80) : '' }
</script>

{#snippet line(it: RunItem, ended: boolean, ing: string)}
  {@const th = thumbOf(it.id)}
  <a class="m-tl-li" class:m-tl-cur={it.st === 'run'} class:m-tl-wait={it.st === 'wait'} href="#/item/{it.id}" onclick={(e) => { if (Date.now() < settleUntil) e.preventDefault(); else dialog.close() }}>
    {#if th}<img class="m-tl-th" src={th} alt="" loading="lazy" />{:else}<i class="m-tl-th"></i>{/if}
    <span><b>{it.title}</b>{#if (it.st === 'skip' || it.st === 'err') && it.why}<small>{t('processing.error.detail', { detail: it.why })}</small>{/if}</span>
    <span class="m-tl-st m-tl-st-{it.st}">
      {#if it.st === 'run'}<i class="m-tl-spin" aria-hidden="true"></i>{ing}
      {:else if it.st === 'done'}<ShellIcon name="check" />{t('processing.work.done')}
      {:else if it.st === 'skip'}<ShellIcon name="dash" />{t('processing.work.skipped')}
      {:else if it.st === 'err'}<ShellIcon name="x" />{t('processing.work.failed')}
      {:else}{ended ? t('processing.work.notStarted') : t('processing.work.waiting')}{/if}
    </span>
  </a>
{/snippet}

<!-- the confirm line: inside the tapped step's row, or inside the finished run's heading row for Retry, Continue and Next -->
{#snippet confirm(k: StepKind)}
  {#if pre}
    {@const c = confirmText({ kind: k, n: pre.n, all: pre.all, rerun: pre.rerun, src, provider: pre.provider, replace: replaceText(k), join: joining && !pre.act, act: pre.act, retained: !!pre.act }, toolText)}
    <div class="m-tl-ask">
      <span><b>{c.lead}</b> {c.rest}</span>
      {#if k === 'analyze' && !pre.act && analysis && !joining}
        <fieldset class="m-tl-opts">
          <label>{t('processing.review.interval')}<input type="number" min="0" max="60" step="0.5" bind:value={analysis.frame_interval} /></label>
          <label><input type="checkbox" bind:checked={analysis.transcribe} /> {t('processing.review.transcribe')}</label>
          <label>{t('processing.review.report')}<select bind:value={analysis.analysis_provider}><option value="none">{t('processing.review.none')}</option><option value="claude">Claude</option><option value="openai">OpenAI</option><option value="freellmapi">FreeLLMAPI</option></select></label>
          <MDisclosure summary={t('processing.review.options')}>
            <label>{t('processing.review.frames')}<select bind:value={analysis.ai_frame_budget}><option value="auto">{t('processing.review.auto')}</option><option value="0">{t('processing.review.off')}</option><option value="8">{t('processing.review.upTo8')}</option><option value="15">{t('processing.review.upTo15')}</option><option value="24">{t('processing.review.upTo24')}</option></select></label>
            <label><input type="checkbox" bind:checked={analysis.keep_frames} /> {t('processing.review.keep')}</label>
            <label><input type="checkbox" bind:checked={analysis.show_frames_in_canvas} disabled={!analysis.keep_frames} /> {t('processing.review.show')}</label>
            <label><input type="checkbox" bind:checked={analysis.delete_video} /> {t('processing.review.deleteVideo')}</label>
            <label><input type="checkbox" bind:checked={analysis.delete_audio} /> {t('processing.review.deleteAudio')}</label>
          </MDisclosure>
        </fieldset>
      {/if}
      <div class="m-tl-ask-keys"><MButton shape="pill" variant="pri" disabled={work === 'starting'} onclick={start}>{confirmGo({ kind: k, n: pre.n, all: pre.all, src }, toolText)}</MButton><MTextButton disabled={work === 'starting'} onclick={cancelAsk}>{t('common.cancel')}</MTextButton></div>
    </div>
  {/if}
{/snippet}

{#snippet step(k: StepKind)}
  {@const S = stepWords(k, toolText)}
  {@const n = counts[k]}
  {@const suggested = k === rec && !noKey && !busyJob}
  {@const join = !!busyJob && k === 'analyze' && busyJob.kind === 'analyze'}
  <MStepRow label={eff(k) ? t('processing.again', { label: S.label }) : S.label} glyph={S.glyph}
    sub={[item ? (n ? S.one : t('processing.doneItem')) : S.line(n), chargeLine(k, Math.min(n, limit), toolText)].filter(Boolean).join(' · ')}
    rec={suggested} tag={suggested ? t('processing.suggested') : ''} expanded={ask === k}
    disabled={!n || work !== 'idle' || (S.charge === 'model' && !!noKey) || (!!busyJob && !join)} onclick={() => prepare(k)}>
    {#if ask === k}{@render confirm(k)}{/if}
  </MStepRow>
{/snippet}

<dialog class="m-cap-pop m-process-pop" class:m-process-dock={!!anchor?.closest('.m-dock')} bind:this={dialog} aria-label={t('common.tools')} onclick={outside} oncancel={leave} onclose={() => { leave(); close() }}>
 <div class="m-cap-pop-body m-process m-tl">
  <div class="m-tl-head"><h2>{t('common.tools')}</h2><MInfo title={t('processing.helpTitle')}>
    <p>{t('processing.help')}</p>
    {#if source.kind === 'mirror'}<p>{t('processing.helpPhone')}</p><p>{t('processing.helpOpen')}</p>{:else}<p>{t('processing.helpPc', { setup: pcSetup })}</p><p>{t('processing.helpReconnect')}</p>{/if}
  </MInfo><span class="m-sp"></span><span class="m-tl-scope">{scopeLine}</span></div>

  {#if run}
    {@const S = stepWords((run.kind as StepKind) in STEPS ? run.kind as StepKind : 'describe', toolText)}
    {@const k = (run.kind as StepKind) in STEPS ? (run.kind as StepKind) : 'describe'}
    {@const p = progress(run)}
    {@const n = p.n}
    {@const cur = run.items.find(i => i.st === 'run')}
    {@const one = run.scope.item && run.items.length === 1}
    {@const first = run.items[0]}
    {@const next = run.unavailable ? null : nextKey({ done: p.done, skip: p.skip, err: p.err, left: p.left }, run.stopped, run.rest.length, toolText)}
    {@const at = run.lane === 'phone' ? run.attempt : { total: n, done: p.done + p.skip + p.err }}
    <MStepRow label={S.label} glyph={S.glyph} state={run.ended && !(one && first && first.st !== 'done') ? 'fin' : 'on'}
      sub={run.ended ? (run.unavailable ? t('processing.error.unavailable') : one && first && first.st !== 'done' ? first.why || t('processing.notDone') : savedLine(src, toolText)) : one && run.kind === 'describe' ? t('processing.reading') : cur ? t('processing.current', { ing: S.ing, title: cur.title }) : t('processing.busyIng', { ing: S.ing })}>
      {#if ask === 'follow'}{@render confirm(k)}{/if}
    </MStepRow>
    {#if one}
      {#if run.ended && first.st === 'done' && run.text}
        <div class="m-tl-pv"><span class="m-tl-kick">{run.undone ? (run.kind === 'describe' ? t('processing.restoredDescription') : t('processing.restoredCollection')) : run.kind === 'describe' ? t('processing.newDescription') : t('processing.newCollection')}</span><p>{#if run.undone}<s>{run.text}</s>{:else}{run.text}{/if}</p></div>
        {#if run.lane === 'phone' && run.undo && !run.undone}<div><MTextButton disabled={run.undoing} onclick={() => act(undo)}>{t('notes.editor.undo')}</MTextButton></div>{/if}
      {/if}
    {:else if run.ended}
      {@const failed = run.items.filter(i => i.st === 'err')}
      {@const skipped = run.items.filter(i => i.st === 'skip')}
      {@const done = run.items.filter(i => i.st === 'done')}
      <div class="m-tl-groups">
        {#if failed.length}<p class="m-tl-group m-tl-gh">{t('processing.work.failed')} · {failed.length}</p><div class="m-tl-led">{#each failed as it (it.id)}{@render line(it, true, S.ing)}{/each}</div>{/if}
        {#if skipped.length}<p class="m-tl-group m-tl-gh">{t('processing.work.skipped')} · {skipped.length}</p><div class="m-tl-led">{#each skipped as it (it.id)}{@render line(it, true, S.ing)}{/each}</div>{/if}
        {#if p.left && !run.unavailable}<p class="m-tl-group m-tl-gh">{t('processing.work.notStarted')} · {p.left}</p>{/if}
        {#if done.length}
          <button type="button" class="m-tl-fold" aria-expanded={open} onclick={() => open = !open}>{stepWords(k, toolText, done.length).verb[0].toUpperCase() + stepWords(k, toolText, done.length).verb.slice(1)} · {done.length}</button>
          {#if open}<div class="m-tl-led">{#each done as it (it.id)}{@render line(it, true, S.ing)}{/each}</div>{/if}
        {/if}
      </div>
    {:else}
      <div class="m-tl-led" class:m-tl-cap={run.items.length > 6}>{#each ledgerWindow(run.items) as it (it.id)}{@render line(it, false, S.ing)}{/each}</div>
    {/if}
    {#if !run.ended}<p class="m-tl-line">{runNote(src, run.stopping, run.joined, toolText)}</p>{/if}
    {#if run.why}<p class="m-tl-line" role="status">{t('processing.error.detail', { detail: run.why })}</p>{/if}
    {#if err}<p class="m-tl-line m-tl-err" role="alert">{t('processing.error.detail', { detail: err })}</p>{/if}
    {#if run.ended}
      <MRunBar label={t('processing.progress', { label: S.label })} strong="{run.stopped ? t('processing.stopped') : ''}{summary({ done: p.done, skip: p.skip, err: p.err, left: p.left }, k, toolText)}" lead="" right={pc ? t('processing.onPc') : t('processing.saved')} total={n} done={p.done} skip={p.skip} err={p.err}>
        {#if next}<MButton shape="pill" variant="pri" data-tl-focus disabled={work !== 'idle' || ask === 'follow'} onclick={() => follow(next.act)}>{#if next.act === 'retry'}<ShellIcon name="retry" />{/if}{next.text}</MButton>{/if}
        <MButton shape="pill" class="m-runbar-done" data-tl-focus={next ? undefined : ''} disabled={work === 'starting'} onclick={done}>{t('processing.work.done')}</MButton>
      </MRunBar>
    {:else}
      <MRunBar label={t('processing.progress', { label: S.label })} strong={t('processing.position', { n: Math.min(at.total, at.done + 1), total: at.total })} lead={t('processing.items', { n: at.total })} right="{pc ? t('processing.onYourPc') : ''}{chargeLine(k, at.total, toolText) || t('processing.noAi')}" total={n} done={p.done} skip={p.skip} err={p.err} run>
        <MKey size="mid" tone="dark" data-tl-focus aria-label={stopLabel(run.joined, toolText)} title={stopLabel(run.joined, toolText)} disabled={run.stopping} onclick={() => { if (Date.now() >= settleUntil) void act(stopRun) }}><ShellIcon name="stop" /></MKey>
        <MButton shape="pill" disabled>{run.stopping ? t('processing.stopping') : t('processing.busyIng', { ing: S.ing })}</MButton>
      </MRunBar>
    {/if}
  {:else}
    {#if busyJob}
      {@const b = pcBusy(busyJob.label || busyJob.kind, busyJob.done, busyJob.total, stepWords(rec && rec !== busyJob.kind ? rec : 'describe', toolText).label, toolText)}
      <div class="m-tl-ask" role="status"><span><b>{b.lead}</b> {b.rest}</span><div class="m-meter"><i style:width="{Math.round(100 * Math.min(busyJob.total, busyJob.done) / Math.max(1, busyJob.total))}%"></i></div></div>
    {/if}
    {#if noKey}
      <div class="m-tl-ask m-tl-warn" role="alert"><span><b>{t('processing.noKeyTitle')}</b> {noKey}</span>{#if !pc}<div class="m-tl-ask-keys"><MTextButton onclick={addKey}>{solo ? t('processing.openSettings') : t('processing.openBackup')}</MTextButton></div>{/if}</div>
    {/if}
    <div class="m-tl-steps">
      {#if !pc}{@render step('thumb')}{/if}
      {#each MAIN_STEPS as k (k)}{@render step(k)}{/each}
      {#if pc}<MDisclosure summary={t('processing.other', { n: PC_STEPS.length })} open={!!rec && PC_STEPS.includes(rec)}><div class="m-tl-steps">{#each PC_STEPS as k (k)}{@render step(k)}{/each}</div></MDisclosure>{/if}
    </div>
    {#if !noKey}<p class="m-tl-line">{where}</p>{/if}
    {#if err}<p class="m-tl-line m-tl-err" role="alert">{t('processing.error.detail', { detail: err })}</p>{/if}
    {#if pc && pcResult.job}
      <p class="m-tl-line" role="status">{t('processing.last', { done: pcResult.done, skip: pcResult.skipped, err: pcResult.err, stopped: pcResult.state === 'stopped' ? t('processing.lastStopped') : '', detail: pcResult.skipped ? t('processing.lastNoText') : '' })}</p>
      {#if pcResult.detail}<p class="m-tl-line m-tl-err" role="alert">{t('processing.error.detail', { detail: pcResult.detail })}</p>{/if}
    {/if}
    <MDisclosure summary={t('processing.more')}>
      <MRow title={t('processing.rerun')} desc={t('processing.rerunHelp')}><MToggle label={t('processing.rerun')} on={rerun} disabled={work !== 'idle'} onchange={value => { rerun = value; invalidate() }} /></MRow>
      <div class="m-process-use">
        <h3>{t('processing.use')} <MInfo title={t('processing.useTitle')}><p>{t('processing.askHelp')}</p>{#if source.synthesize}<p>{t('processing.synthHelp', { scope: t(rows.length > 1 ? 'processing.first30' : 'processing.thisItem') })}</p>{/if}</MInfo></h3>
        <MButton as="a" size="sm" href="#/jv">{t('shell.askWiskitLabel')}</MButton>
        {#if source.synthesize}
          <label class="m-lbl">{t('processing.topic')}<input type="text" bind:value={topic} placeholder={t('notes.synthesize.topic')} onfocus={(e) => e.currentTarget.scrollIntoView({ block: 'nearest' })} /></label>
          <MButton disabled={synthBusy || !topic.trim()} onclick={synthesize}>{synthBusy ? t('notes.synthesize.writing') : t('notes.synthesize.title')}</MButton>
          {#if synthLine}<p class="m-hint" role="status">{synthLine}</p>{/if}
          {#if synthFile}<MButton as="a" href={`#/notes/${encodeURIComponent(synthFile)}`}>{t('processing.openNote')}</MButton>{/if}
        {/if}
      </div>
      <MInfo title={t('processing.privacyTitle')} label={t('processing.privacyLabel')}><p>{t('processing.privacyText')}</p><p>{t('processing.privacyAudio')}</p><p>{t('processing.privacyCharges')}</p></MInfo>
    </MDisclosure>
  {/if}
 </div>
</dialog>

<style>
  .m-process-pop { top: var(--process-top); right: max(12px, env(safe-area-inset-right, 0px)); width: min(420px, calc(100vw - 24px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px))) }
  .m-process-dock { top: auto; bottom: var(--process-bottom) }
  .m-process-dock::before { top: auto; bottom: -7px; transform: rotate(225deg) }
  .m-process-dock .m-process { max-height: calc(100dvh - var(--process-bottom) - 12px - env(safe-area-inset-top, 0px)) }
  .m-process-pop::before { left: var(--process-notch); right: auto; margin-left: -6px }
  .m-process { max-height: calc(100dvh - var(--process-top) - 12px - env(safe-area-inset-bottom, 0px)) }
  .m-tl-groups { display: flex; flex-direction: column; gap: 4px }
  .m-process-use { display: grid; gap: 8px; padding-top: 10px; border-top: 1px solid var(--wg-edge) }
  .m-process-use h3 { margin: 0 }
  .m-process-use label { display: grid; gap: 5px }
  .m-process-use input { min-height: 40px; border: 1px solid var(--wg-edge); border-radius: 6px; padding: 6px; background: var(--wg); color: var(--wg-ink) }
</style>
