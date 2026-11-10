<script module lang="ts">
  import { registerLanguageCheck } from '../language-switch.ts'
  let heldDraft: { question: string; context: { label: string; text: string } | null } | null = null
  registerLanguageCheck(() => heldDraft ? 'settings.language.unsentQuestion' : null)
</script>

<script lang="ts">
  import { captureError } from '../capture-words.ts'
  // 03 Wiskit (projects/phone-wiskit-chat, version C "thumb composer"): Ask Quick, streamed, and Deep (the
  // librarian researches with tools, plans/07). On the paired phone it answers itself with the user's own key
  // (source/mirror.ts), over USB the desktop answers (POST /api/ask). The sheet's floating keys (Sheet.svelte,
  // bare mode: Close, the tag, the chat's name, Chats) are the sheet's; here: the conversation anchored to the
  // end (a Latest key when the reader scrolled up), the "needs a key / needs the PC" screen, one random example
  // on an empty chat, and the raised composer at the bottom (the cat, the status line, Quick / Deep, a text
  // area that grows to four lines, a round Send key that becomes Stop). Saved chats, citations open the card or
  // note, Save as note.
  import { t } from '../../lib/i18n/index.ts'
  import { fmtDate } from '../../lib/i18n/format.ts'
  import { toolText } from '../tools-words.ts'
  import { askExamples } from '../wiskit-words.ts'
  import { onMount, tick, untrack } from 'svelte'
  import { fmtAnswer } from '../../lib/md'
  import type { AskEvent, CategoryProposal, PhoneCanvasProposal, Chat, ChatRow, Row } from '../source/types'
  import type { CanvasPreviewEl } from '../../lib/job-requests'
  import { kv } from '../store'
  import WiskitSprite from '../../components/WiskitSprite.svelte'
  import CanvasProposal from '../CanvasProposal.svelte'
  import { phone, refresh, solo, source } from '../state.svelte'
  import { cap } from '../capture.svelte'
  import { beginLanguageWork, languageWorkChanged } from '../language-switch.ts'
  import { openMoreBox } from '../onboard.svelte'
  import { setMoreFrom } from '../back'
  import { watchKeyboard } from '../keyboard'
  import ShellIcon from '../ShellIcon.svelte'
  import MButton from '../ui/MButton.svelte'
  import MInfo from '../ui/MInfo.svelte'
  import MKey from '../ui/MKey.svelte'
  import MSeg from '../ui/MSeg.svelte'
  const onMirror = source.kind === 'mirror'
  // the phone's own AI (null: no key in the pairing); read again when a refresh brings the PC's settings
  const ai = $derived((phone.synced, source.ai?.() ?? null))

  // `name`: the open chat's name, shown by the sheet after its tag (Mobile.svelte binds it)
  let { chats: showChats, name = $bindable('') }: { chats: boolean; name?: string } = $props()
  interface Msg { role: 'user' | 'jarvis'; text: string; ctx?: string; cited?: number[]; sources?: Row[]; streaming?: boolean; error?: string; saved?: string; steps?: string[]; deep?: boolean; ctxLabel?: string; stopped?: boolean }
  let msgs = $state<Msg[]>([])
  let chats = $state<ChatRow[]>([])
  let slug = $state('')
  let q = $state(heldDraft?.question ?? ''), busy = $state(false), run = ''
  // an attachment sent from the Add screen (Ask Wiskit): its text goes with the next question
  let ctx = $state<{ label: string; text: string } | null>(heldDraft?.context ?? null)
  if (heldDraft) { heldDraft = null; languageWorkChanged() }
  let qEl: HTMLTextAreaElement | undefined = $state()
  let proposal = $state<CategoryProposal | null>(null), reviewBusy = $state(false), reviewError = $state(''), reviewDone = $state('')
  let canvasProposal = $state<PhoneCanvasProposal | null>(null), openCanvasId = $state('')
  let canvasRefusal = $state<{ id: string; reason: string } | null>(null)
  async function loadProposal() {
    try { proposal = await source.categoryProposal?.() ?? null; canvasProposal = await source.canvasProposal?.() ?? null; canvasRefusal = source.lastCanvasRefusal?.() ?? null }
    catch { /* the local copy stays */ }
  }
  const canvasImage = (e: CanvasPreviewEl) => {
    if (e.file_path) return source.canvasImageUrl(e.file_path.split(/[\\/]/).pop() || '')
    if (e.kind === 'frame' && e.item_id && e.frame && !onMirror) return `/files/items/${e.item_id}/frames/${encodeURIComponent(e.frame)}`
    const r = e.item_id ? phone.byId.get(e.item_id) : null
    return r ? source.thumbUrl(r, 240) : ''
  }
  async function answerCanvas(apply: boolean) {
    if (!canvasProposal || reviewBusy) return
    const done = beginLanguageWork()
    reviewBusy = true; reviewError = ''; reviewDone = ''
    try {
      if (apply) {
        openCanvasId = await source.applyCanvasProposal?.(canvasProposal) ?? ''
        reviewDone = onMirror ? t('wiskit.canvas.phone') : t('wiskit.canvas.pc')
        phone.canvasRevision++
      } else { await source.declineCanvasProposal?.(canvasProposal); reviewDone = t('wiskit.canvas.declined') }
      canvasProposal = null
    } catch (e) { reviewError = captureError(e); await loadProposal() }
    finally { reviewBusy = false; done() }
  }
  async function answerProposal(apply: boolean) {
    if (!proposal || reviewBusy) return
    const done = beginLanguageWork()
    reviewBusy = true; reviewError = ''; reviewDone = ''
    try {
      if (apply) await source.applyCategoryProposal?.(proposal)
      else await source.declineCategoryProposal?.()
      reviewDone = apply ? t('wiskit.category.approved', { n: proposal.entries.length }) : t('wiskit.category.declined')
      proposal = null
      if (apply) await refresh().catch(() => {})
    } catch (e) { reviewError = captureError(e) }
    finally { reviewBusy = false; done() }
  }
  const DEEP_KEY = 'bp-deep'
  let deep = $state((() => { try { return localStorage.getItem(DEEP_KEY) === '1' } catch { return false } })())
  function setDeep(on: boolean) {
    deep = on
    try { localStorage.setItem(DEEP_KEY, on ? '1' : '0') } catch { /* private window */ }
  }
  let ctl: AbortController | null = null
  let root: HTMLDivElement | undefined = $state()
  const pet = $derived(busy ? 'work' : msgs.at(-1)?.cited?.length ? 'done' : 'idle')
  // the cat's cropped size per pose (web/public/wiskit/sheet.json bounds), so it draws at its own pixels
  const CAT: Record<string, [number, number]> = { idle: [52, 30], work: [84, 37], done: [55, 30] }

  // Wiskit can answer: a key on the mirror (solo or paired), a reachable PC in direct mode
  const canAsk = $derived(onMirror ? !!ai : phone.reachable)
  // C1 (spec section 3): why it cannot, in the middle of the screen; the composer stays, greyed
  const need = $derived.by(() => {
    if (canAsk) return null
    if (!onMirror) return { title: t('wiskit.need.pcTitle'), text: t('wiskit.need.pc'), key: '', hint: t('wiskit.need.pcHint') }
    if (solo) return { title: t('wiskit.need.keyTitle'), text: t('wiskit.need.solo'), key: t('wiskit.need.add'), hint: t('wiskit.need.keyHint') }
    return { title: t('wiskit.need.keyTitle'), text: t('wiskit.need.paired'), key: t('wiskit.need.how'), hint: t('wiskit.need.keyHint') }
  })
  const status = $derived(onMirror ? (ai ? t('wiskit.status.phone', { model: ai.label }) : '') : t('wiskit.status.pc'))
  $effect(() => {
    if (cap.ask && !q.trim() && !ctx && !busy) {
      ctx = cap.ask; cap.ask = null; q = t('wiskit.context.question'); languageWorkChanged()
      tick().then(() => qEl?.select())
    }
  })

  // C2: one example, picked again each time the empty chat shows
  let example = $state(askExamples()[0])
  const pickExample = () => { const examples = askExamples(); example = examples[Math.floor(Math.random() * examples.length)] }
  $effect(() => { if (!msgs.length) untrack(pickExample) })

  const hist = (c: Chat): Msg[] => (c.history || []).map(t => (t.role === 'user' ? { role: 'user', text: t.content } : { role: 'jarvis', text: t.content, cited: citedIds(t.content), sources: c.sources }))
  const citedIds = (t: string) => [...new Set([...t.matchAll(/\[\s*(?:ids?|no\.?)\s*:?\s*([\d,\s]+)\]/gi)].flatMap(m => m[1].match(/\d+/g) ?? []).map(Number))]

  // reopen: false after an answer, so the turn on screen keeps its research steps
  async function loadChats(reopen = true) {
    try {
      const r = await source.chats()
      chats = r.chats
      kv.set('chats', chats)
      // a chat deleted (here or on the PC) is not reopened
      const known = (s?: string) => (s && chats.some(c => c.slug === s) ? s : '')
      if (!known(slug)) slug = known(await kv.get<string>('bp-chat')) || known(r.active) || chats[0]?.slug || ''
      if (slug && reopen) await openChat(slug)
      else if (slug) kv.set('bp-chat', slug)
    } catch { chats = (await kv.get<ChatRow[]>('chats')) ?? [] }
  }
  async function openChat(s: string) {
    try {
      const c = await source.chat(s)
      slug = c.slug; name = c.name; msgs = hist(c)
      kv.set('bp-chat', slug)
      scrollEnd()
    } catch { /* keep what is on screen */ }
    if (showChats) location.hash = '#/jv'
  }
  async function newChat() {
    try { const c = await source.newChat(); slug = c.slug; name = c.name; msgs = []; await loadChats() } catch (e) { msgs = [...msgs, { role: 'jarvis', text: '', error: captureError(e) }] }
  }
  // two taps: the first arms the row's delete key, the second deletes (on the PC too)
  let sure = $state('')
  async function delChat(c: ChatRow) {
    if (sure !== c.slug) { sure = c.slug; return }
    sure = ''
    try {
      await source.deleteChat(c.slug)
      if (c.slug === slug) { slug = ''; name = ''; msgs = []; await kv.del('bp-chat') }
      await listChats()
    } catch (e) { msgs = [...msgs, { role: 'jarvis', text: '', error: captureError(e) }] }
  }
  // the list again; the open chat goes when it is no longer there (deleted on the PC)
  async function listChats() {
    try {
      chats = (await source.chats()).chats
      kv.set('chats', chats)
      if (slug && !busy && !chats.some(c => c.slug === slug)) { slug = ''; name = ''; msgs = []; kv.del('bp-chat') }
    } catch { /* keep the list on screen */ }
  }
  // a refresh (the lamp, Refresh in More, the app back in front) can bring chats the PC deleted
  let seen = phone.synced
  $effect(() => { const s = phone.synced; if (s !== seen) { seen = s; untrack(() => listChats()) } })

  // following the answer (spec section 5.3): the sheet body scrolls; the screen follows only while the reader is
  // within 80 px of the end; a Latest key brings them back
  let body: HTMLElement | null = null
  let follow = $state(true)
  const atEnd = () => !body || body.scrollHeight - body.scrollTop - body.clientHeight <= 80
  const onScroll = () => { follow = atEnd() }
  async function scrollEnd(force = true) {
    if (!force && !follow) return
    await tick()
    root?.closest('.m-sheet-body')?.scrollTo({ top: 1e9 })
    follow = true
  }
  onMount(() => {
    const releaseDraftCheck = registerLanguageCheck(() => q.trim() || ctx ? 'settings.language.unsentQuestion' : null)
    body = root?.closest<HTMLElement>('.m-sheet-body') ?? null
    body?.addEventListener('scroll', onScroll, { passive: true })
    // the keyboard (html.kb): the composer rises with it; the end stays in view when it was in view
    const offKb = watchKeyboard(() => { void scrollEnd(false) })
    void loadChats(); void loadProposal(); const timer = window.setInterval(() => { if (onMirror || busy) void loadProposal() }, onMirror ? 10000 : 1000)
    // on the PC: polled only while an ask runs; a request made elsewhere arrives over SSE
    const stop = onMirror ? undefined : source.watchRequests?.(() => void loadProposal())
    return () => {
      if (q.trim() || ctx) { heldDraft = { question: q, context: ctx }; languageWorkChanged() }
      releaseDraftCheck(); clearInterval(timer); stop?.(); offKb(); body?.removeEventListener('scroll', onScroll)
    }
  })

  async function send() {
    const text = q.trim()
    if (!text || busy) return
    const done = beginLanguageWork()
    q = ''
    const c = ctx
    ctx = null
    const asked = c ? `${c.text}

(Above: what I am adding to Brainamon, from ${c.label}.)

${text}` : text
    const isDeep = deep
    msgs = [...msgs, { role: 'user', text: c ? `${text}
(with ${c.label})` : text }, { role: 'jarvis', text: '', ctx: 'Reading the library…', ctxLabel: t('wiskit.reading'), streaming: true, deep: isDeep, steps: [] }]
    const m = msgs[msgs.length - 1]
    busy = true
    ctl = new AbortController()
    const active = ctl
    let terminal = false
    scrollEnd()
    try {
      await source.ask(asked, slug, (e: AskEvent, display?: string) => {
        if (ctl !== active || terminal) return
        if (e.ev === 'done' || e.ev === 'error' || e.ev === 'stopped') terminal = true
        if (e.ev === 'start') run = e.run
        else if (e.ev === 'context') { m.ctx = e.line; m.ctxLabel = display ?? t('wiskit.progress.external', { detail: e.line }) }
        else if (e.ev === 'progress') { if (m.ctx && m.ctx !== 'Reading the library…') m.steps = [...(m.steps ?? []), m.ctxLabel || m.ctx]; m.ctx = e.line; m.ctxLabel = display ?? t('wiskit.progress.external', { detail: e.line }); scrollEnd(false) }
        else if (e.ev === 'reset') { m.text = ''; m.cited = []; m.sources = [] }
        else if (e.ev === 'chunk') { m.text += e.text; scrollEnd(false) }
        else if (e.ev === 'done') { if (m.ctx) m.steps = [...(m.steps ?? []), m.ctxLabel || m.ctx]; m.text = e.text; m.cited = e.cited; m.sources = e.sources; m.ctx = ''; slug = e.chat.slug; name = e.chat.name; loadChats(false) }
        else if (e.ev === 'stopped') { m.ctx = 'Stopped.'; m.ctxLabel = t('wiskit.stopped'); m.stopped = true }
        else if (e.ev === 'error') { m.error = e.message; m.ctx = '' }
        else if (e.ev === 'category_proposal') { proposal = e.proposal; reviewDone = ''; scrollEnd() }
        else if (e.ev === 'canvas_proposal') { canvasProposal = e.proposal; reviewDone = ''; scrollEnd() }
      }, ctl.signal, isDeep ? 'deep' : 'quick', toolText)
    } catch (e) {
      if (ctl !== active || terminal) return
      m.stopped = (e as Error).name === 'AbortError'
      m.error = m.stopped ? t('wiskit.stopped') : captureError(e)
      m.ctx = ''
    } finally {
      m.streaming = false; busy = false; ctl = null; run = ''
      void loadProposal().finally(done)
      scrollEnd(false)
    }
  }
  // Enter sends; Shift+Enter, Enter during IME composition (Android keyboards: isComposing or keyCode 229) and
  // Enter while Wiskit answers leave the text where it is (send() refuses while busy)
  function onKey(e: KeyboardEvent) {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing || e.keyCode === 229) return
    e.preventDefault()
    void send()
  }
  function stop() { if (run) source.stopAsk(run).catch(() => {}); ctl?.abort() }
  async function save(m: Msg) {
    const done = beginLanguageWork()
    try { m.saved = (await source.saveAnswer(m.text, m.cited ?? [])).file } catch (e) { m.error = captureError(e) }
    finally { done() }
  }
  function onChip(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest<HTMLElement>('.cite')
    if (b?.dataset.cid) location.hash = `#/item/${b.dataset.cid}`
    else if (b?.dataset.note) location.hash = `#/notes/${encodeURIComponent(b.dataset.note)}`
  }
  const when = (s: string) => (s ? fmtDate(s, { day: '2-digit', month: 'short' }, 'en-GB') : '')
</script>

<div class="m-jv" bind:this={root}>
  {#if showChats}
    <div class="m-chats">
      {#if proposal || canvasProposal}<button type="button" class="m-jv-review" onclick={() => (location.hash = '#/jv')}><b>{t('wiskit.chat.review')}</b><small>{t('wiskit.chat.waiting')}</small></button>{/if}
      <button type="button" onclick={newChat}><b>{t('wiskit.chat.new')}</b></button>
      {#each chats as c (c.slug)}
        <div class="m-chat-row">
          <button type="button" class:on={c.slug === slug} onclick={() => { sure = ''; openChat(c.slug) }}><b>{c.name}</b><small>{t('wiskit.chat.messages', { n: c.message_count })} · {when(c.updated)}</small></button>
          <button type="button" class="m-chat-del" class:sure={sure === c.slug} disabled={busy && c.slug === slug} aria-label={sure === c.slug ? t('wiskit.chat.deleteAgain', { name: c.name }) : t('wiskit.chat.delete', { name: c.name })} onclick={() => delChat(c)}>{sure === c.slug ? t('common.delete') : '×'}</button>
        </div>
      {:else}
        <div class="m-empty">{t('wiskit.chat.empty')}</div>
      {/each}
    </div>
  {:else}
    <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
    <div class="m-jv-feed" onclick={onChip}>
      {#if need}
        <div class="m-jv-need">
          <div class="m-jv-rug" aria-hidden="true"><span class="m-jv-cat" style:width="104px" style:height="60px"><WiskitSprite pose="idle" crop motionOff={phone.motionOff} /></span></div>
          <h4>{need.title}</h4>
          <p>{need.text}</p>
          {#if need.key}<MButton variant="pri" class="m-jv-go" onclick={() => { setMoreFrom('#/jv'); openMoreBox('m-ai') }}>{need.key}</MButton>{/if}
        </div>
      {:else if !msgs.length}
        <div class="m-jv-hello">
          <b>{t('wiskit.hello')}</b>
          <small>{t('wiskit.citations')}</small>
          <button type="button" class="m-jv-try" disabled={busy} onclick={() => { q = example; send() }}><i>{t('wiskit.try')}</i><span>{example}</span></button>
        </div>
      {/if}
      {#each msgs as m, i (i)}
        {#if m.role === 'user'}
          <div class="m-q">{m.text}</div>
        {:else}
          <div class="m-a" class:err={!!m.error}>
            {#if m.steps?.length}
              {#if m.streaming}<ol class="m-steps">{#each m.steps as st, k (k)}<li>{st}</li>{/each}</ol>
              {:else}<details class="m-steps"><summary>{t('wiskit.steps', { n: m.steps.length })}</summary><ol>{#each m.steps as st, k (k)}<li>{st}</li>{/each}</ol></details>{/if}
            {/if}
            {#if m.ctx}<div class="m-ctx">{m.ctxLabel || m.ctx}</div>{/if}
            {@html fmtAnswer(m.text)}
            {#if m.error}<p>{t('wiskit.error.detail', { detail: m.error })}</p>{/if}
            {#if m.sources?.length}
              <div class="m-src">{#each m.sources.filter(s => !m.cited?.length || m.cited.includes(s.id)).slice(0, 8) as s (s.id)}<button type="button" onclick={() => (location.hash = `#/item/${s.id}`)} aria-label={t('wiskit.openItem', { id: s.id })}>{#if s.thumb}<img src={source.thumbUrl(s, 160)} alt="" />{/if}</button>{/each}</div>
            {/if}
            {#if !m.streaming && m.text && !m.error && !m.stopped}
              <div class="m-foot"><span>{t(onMirror ? 'wiskit.answeredPhone' : 'wiskit.answeredPc')}{m.deep ? ' · ' + t('wiskit.mode.deep') : ''}{onMirror && ai ? ' · ' + ai.label : ''}{m.cited?.length ? ' · ' + t('wiskit.cards', { n: m.cited.length }) : ''}</span>{#if m.saved}<span>{t('wiskit.saved', { file: m.saved })}</span>{:else}<button type="button" onclick={() => save(m)}>{t('wiskit.save')}</button>{/if}</div>
            {/if}
          </div>
        {/if}
      {/each}
      {#if canvasProposal}
        <CanvasProposal preview={canvasProposal.preview} imageUrl={canvasImage} busy={reviewBusy} error={reviewError}
          onApply={() => answerCanvas(true)} onDecline={() => answerCanvas(false)} />
      {:else if proposal}
        <section class="m-box m-jv-proposal" aria-label={t('wiskit.category.label')}>
          <h3>{t('wiskit.category.review')} <MInfo title={t('wiskit.category.title')}><p>{t('wiskit.category.help')}</p></MInfo></h3>
          <p class="m-hint">{t('wiskit.category.count', { n: proposal.entries.length })}</p>
          <div class="m-jv-proposal-list">{#each proposal.entries as e (e.id)}<div><b>{e.title || `No. ${e.id}`}</b><small>No. {e.id} · {e.from || t('wiskit.category.uncategorized')} → {e.category}</small></div>{/each}</div>
          {#if reviewError}<p class="m-hint err" role="alert">{t('wiskit.error.detail', { detail: reviewError })}</p>{/if}
          <div class="m-acts"><MButton disabled={reviewBusy} onclick={() => answerProposal(false)}>{t('canvas.proposal.decline')}</MButton><MButton variant="dk" disabled={reviewBusy} onclick={() => answerProposal(true)}>{reviewBusy ? t('canvas.proposal.applying') : t('wiskit.category.apply')}</MButton></div>
        </section>
      {:else if reviewDone}<p class="m-hint" role="status">{reviewDone}{#if openCanvasId} <button type="button" onclick={() => (location.hash = `#/canvas/${encodeURIComponent(openCanvasId)}`)}>{t('wiskit.canvas.open')}</button>{/if}</p>{/if}
      {#if canvasRefusal && !canvasProposal}<p class="m-hint" role="status">{t('wiskit.canvas.refused', { reason: canvasRefusal.reason })} <button type="button" onclick={() => (location.hash = `#/canvas/${encodeURIComponent(canvasRefusal!.id)}`)}>{t('wiskit.canvas.open')}</button></p>{/if}
    </div>
    <div class="m-jv-foot">
      {#if !follow && msgs.length}<MKey class="m-jv-latest" aria-label={t('wiskit.latest')} title={t('wiskit.latest')} onclick={() => scrollEnd()}><ShellIcon name="down" /></MKey>{/if}
      <div class="m-jv-comp" class:off={!!need}>
        <div class="m-jv-row">
          {#if !need}
            <span class="m-jv-cat" aria-hidden="true" style:width={`${CAT[pet][0]}px`} style:height={`${CAT[pet][1]}px`}><WiskitSprite pose={pet} crop motionOff={phone.motionOff} /></span>
            <span class="m-sp"></span>
            <span class="m-jv-stat">{status}</span>
            <MInfo title={t('wiskit.about')}>
              <p>{onMirror ? (ai ? t('wiskit.about.phone', { provider: ai.providers.find(p => p.id === ai.provider)?.label, model: ai.label }) : solo ? t('wiskit.about.solo') : t('wiskit.about.paired')) : phone.reachable ? t('wiskit.about.pc') : t('wiskit.about.needsPc')}</p>
              <p>{t('wiskit.mode.help')}</p>
            </MInfo>
          {:else}<span class="m-sp"></span>{/if}
          <MSeg label={t('wiskit.mode.label')} look="pill" options={[['quick', t('wiskit.mode.quick')], ['deep', t('wiskit.mode.deep')]]} value={deep ? 'deep' : 'quick'} disabled={!!need} onchange={v => setDeep(v === 'deep')} />
        </div>
        {#if ctx}<div class="m-jv-with"><span class="m-badge ok">{t('wiskit.with', { label: ctx.label })}</span><button type="button" class="m-link" onclick={() => { ctx = null; languageWorkChanged() }}>{t('wiskit.leaveOut')}</button></div>{/if}
        <form class="m-jv-ask" onsubmit={e => { e.preventDefault(); send() }}>
          <label class="m-jv-field"><span class="m-pr">&gt;</span><textarea bind:this={qEl} bind:value={q} rows="1" aria-label={t('wiskit.question')} placeholder={need ? need.hint : deep ? t('wiskit.deepPlaceholder') : t('wiskit.placeholder')} enterkeyhint="send" autocomplete="off" disabled={!!need} oninput={languageWorkChanged} onkeydown={onKey}></textarea></label>
          {#if busy}<MKey size="mid" tone="dark" aria-label={t('notes.synthesize.stop')} title={t('notes.synthesize.stop')} onclick={stop}><ShellIcon name="stop" /></MKey>
          {:else}<MKey size="mid" tone="add" type="submit" aria-label={t('wiskit.send')} title={t('wiskit.send')} disabled={!!need || !q.trim()}><ShellIcon name="send" /></MKey>{/if}
        </form>
      </div>
    </div>
  {/if}
</div>

<style>
  .m-jv-proposal { margin: 0; gap: 10px }
  .m-jv-proposal p { margin: 0 }
  .m-jv-proposal-list { max-height: 220px; overflow: auto; border: 1px solid var(--wg-edge); border-radius: 8px }
  .m-jv-proposal-list > div { display: grid; gap: 3px; padding: 8px 10px; border-bottom: 1px solid var(--wg-edge) }
  .m-jv-proposal-list > div:last-child { border-bottom: 0 }
  .m-jv-proposal-list b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px }
  .m-jv-proposal-list small { color: var(--wg-dim); font: 500 11px/1.3 var(--display) }
</style>
