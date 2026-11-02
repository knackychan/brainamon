<script lang="ts">
  // 03 Wiskit: Ask Quick, streamed, and Deep (the librarian researches with tools, plans/07): on the
  // paired phone it answers itself with the user's own key (source/mirror.ts), over USB the desktop
  // answers (POST /api/ask). The saved chats, citations open the card or note, Save as note.
  import { ASK_EXAMPLES } from '../../lib/ask-examples'
  import { onMount, tick, untrack } from 'svelte'
  import { fmtAnswer } from '../../lib/md'
  import type { AskEvent, CategoryProposal, PhoneCanvasProposal, Chat, ChatRow, Row } from '../source/types'
  import type { CanvasPreviewEl } from '../../lib/job-requests'
  import { kv } from '../store'
  import Sprite from '../Sprite.svelte'
  import CanvasProposal from '../CanvasProposal.svelte'
  import { phone, refresh, solo, source } from '../state.svelte'
  import { cap } from '../capture.svelte'
  import MButton from '../ui/MButton.svelte'
  const onMirror = source.kind === 'mirror'
  // the phone's own AI (null: no key in the pairing); read again when a refresh brings the PC's settings
  const ai = $derived((phone.synced, source.ai?.() ?? null))

  let { chats: showChats }: { chats: boolean } = $props()
  interface Msg { role: 'user' | 'jarvis'; text: string; ctx?: string; cited?: number[]; sources?: Row[]; streaming?: boolean; error?: string; saved?: string; steps?: string[]; deep?: boolean }
  let msgs = $state<Msg[]>([])
  let chats = $state<ChatRow[]>([])
  let slug = $state(''), name = $state('')
  let q = $state(''), busy = $state(false), run = ''
  // an attachment sent from the Add screen (Ask Wiskit): its text goes with the next question
  let ctx = $state<{ label: string; text: string } | null>(null)
  let qEl: HTMLInputElement | undefined = $state()
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
    reviewBusy = true; reviewError = ''; reviewDone = ''
    try {
      if (apply) {
        openCanvasId = await source.applyCanvasProposal?.(canvasProposal) ?? ''
        reviewDone = onMirror ? 'Canvas saved on this phone.' : 'Canvas saved on the PC.'
        phone.canvasRevision++
      } else { await source.declineCanvasProposal?.(canvasProposal); reviewDone = 'Canvas proposal declined.' }
      canvasProposal = null
    } catch (e) { reviewError = (e as Error).message; await loadProposal() }
    finally { reviewBusy = false }
  }
  async function answerProposal(apply: boolean) {
    if (!proposal || reviewBusy) return
    reviewBusy = true; reviewError = ''; reviewDone = ''
    try {
      if (apply) await source.applyCategoryProposal?.(proposal)
      else await source.declineCategoryProposal?.()
      reviewDone = apply ? `${proposal.entries.length} category changes approved.` : 'Category proposal declined.'
      proposal = null
      if (apply) await refresh().catch(() => {})
    } catch (e) { reviewError = (e as Error).message }
    finally { reviewBusy = false }
  }
  const DEEP_KEY = 'bp-deep'
  let deep = $state((() => { try { return localStorage.getItem(DEEP_KEY) === '1' } catch { return false } })())
  function setDeep(on: boolean) {
    deep = on
    try { localStorage.setItem(DEEP_KEY, on ? '1' : '0') } catch { /* private window */ }
    location.hash = '#/jv'
  }
  let ctl: AbortController | null = null
  let chatEl: HTMLDivElement | undefined = $state()
  const pet = $derived(busy ? 'work' : msgs.at(-1)?.cited?.length ? 'done' : 'idle')

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
    try { const c = await source.newChat(); slug = c.slug; name = c.name; msgs = []; await loadChats() } catch (e) { msgs = [...msgs, { role: 'jarvis', text: '', error: (e as Error).message }] }
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
    } catch (e) { msgs = [...msgs, { role: 'jarvis', text: '', error: (e as Error).message }] }
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
  onMount(() => {
    if (cap.ask) { ctx = cap.ask; cap.ask = null; q = 'What in my library relates to this?'; tick().then(() => qEl?.select()) }
    void loadChats(); void loadProposal(); const timer = window.setInterval(() => { if (onMirror || busy) void loadProposal() }, onMirror ? 10000 : 1000)
    // on the PC: polled only while an ask runs; a request made elsewhere arrives over SSE
    const stop = onMirror ? undefined : source.watchRequests?.(() => void loadProposal())
    return () => { clearInterval(timer); stop?.() }
  })

  async function scrollEnd() { await tick(); chatEl?.closest('.m-main')?.scrollTo({ top: 1e9 }) }

  async function send() {
    const text = q.trim()
    if (!text || busy) return
    q = ''
    const c = ctx
    ctx = null
    const asked = c ? `${c.text}

(Above: what I am adding to Brainamon, from ${c.label}.)

${text}` : text
    const isDeep = deep
    msgs = [...msgs, { role: 'user', text: c ? `${text}
(with ${c.label})` : text }, { role: 'jarvis', text: '', ctx: 'Reading the library…', streaming: true, deep: isDeep, steps: [] }]
    const m = msgs[msgs.length - 1]
    busy = true
    ctl = new AbortController()
    const active = ctl
    let terminal = false
    scrollEnd()
    try {
      await source.ask(asked, slug, (e: AskEvent) => {
        if (ctl !== active || terminal) return
        if (e.ev === 'done' || e.ev === 'error' || e.ev === 'stopped') terminal = true
        if (e.ev === 'start') run = e.run
        else if (e.ev === 'context') m.ctx = e.line
        else if (e.ev === 'progress') { if (m.ctx && m.ctx !== 'Reading the library…') m.steps = [...(m.steps ?? []), m.ctx]; m.ctx = e.line; scrollEnd() }
        else if (e.ev === 'reset') { m.text = ''; m.cited = []; m.sources = [] }
        else if (e.ev === 'chunk') { m.text += e.text; scrollEnd() }
        else if (e.ev === 'done') { if (m.ctx) m.steps = [...(m.steps ?? []), m.ctx]; m.text = e.text; m.cited = e.cited; m.sources = e.sources; m.ctx = ''; slug = e.chat.slug; name = e.chat.name; loadChats(false) }
        else if (e.ev === 'stopped') m.ctx = 'Stopped.'
        else if (e.ev === 'error') { m.error = e.message; m.ctx = '' }
        else if (e.ev === 'category_proposal') { proposal = e.proposal; reviewDone = ''; scrollEnd() }
        else if (e.ev === 'canvas_proposal') { canvasProposal = e.proposal; reviewDone = ''; scrollEnd() }
      }, ctl.signal, isDeep ? 'deep' : 'quick')
    } catch (e) {
      if (ctl !== active || terminal) return
      m.error = (e as Error).name === 'AbortError' ? 'Stopped.' : (e as Error).message
      m.ctx = ''
    } finally {
      m.streaming = false; busy = false; ctl = null; run = ''
      void loadProposal()
      scrollEnd()
    }
  }
  function stop() { if (run) source.stopAsk(run).catch(() => {}); ctl?.abort() }
  async function save(m: Msg) {
    try { m.saved = (await source.saveAnswer(m.text, m.cited ?? [])).file } catch (e) { m.error = (e as Error).message }
  }
  function onChip(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest<HTMLElement>('.cite')
    if (b?.dataset.cid) location.hash = `#/item/${b.dataset.cid}`
    else if (b?.dataset.note) location.hash = `#/notes/${encodeURIComponent(b.dataset.note)}`
  }
  const when = (s: string) => (s ? new Date(s).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '')
</script>

<div class="m-jv-win">
  <div class="m-jv-modes">
    <button type="button" aria-pressed={!showChats && !deep} onclick={() => setDeep(false)}>Quick</button>
    <button type="button" aria-pressed={!showChats && deep} onclick={() => setDeep(true)} title="Wiskit researches the library step by step: slower, more thorough">Deep</button>
    <button type="button" aria-pressed={showChats} onclick={() => (location.hash = '#/jv/chats')}>Chats</button>
    {#if (proposal || canvasProposal) && showChats}<button type="button" onclick={() => (location.hash = '#/jv')}>Review request</button>{/if}
    <span class="m-sp"></span><span class="m-lbl m-jv-name">{name || 'new chat'}</span>
  </div>
  {#if showChats}
    <div class="m-chats">
      <button type="button" onclick={newChat}><b>+ New chat</b><small>Start a fresh conversation</small></button>
      {#each chats as c (c.slug)}
        <div class="m-chat-row">
          <button type="button" class:on={c.slug === slug} onclick={() => { sure = ''; openChat(c.slug) }}><b>{c.name}</b><small>{c.message_count} messages · {when(c.updated)}</small></button>
          <button type="button" class="m-chat-del" class:sure={sure === c.slug} disabled={busy && c.slug === slug} aria-label={sure === c.slug ? `Tap again to delete “${c.name}”` : `Delete “${c.name}”`} onclick={() => delChat(c)}>{sure === c.slug ? 'Delete' : '×'}</button>
        </div>
      {:else}
        <div class="m-empty">No chats yet.</div>
      {/each}
    </div>
  {:else}
    <div class="m-jv-card"><Sprite pose={pet} /><div><b>WISKIT</b><small>{onMirror ? (ai ? `${deep ? 'Deep: researches your library step by step' : 'Answers'} on this phone with your ${ai.providers.find(p => p.id === ai.provider)?.label} key (${ai.label}), even with the PC off. Cites the cards it used.` : solo ? 'Add your Anthropic or OpenAI key under More > Wiskit on this phone, then ask here.' : 'Your chats, read from Google Drive. To ask from the phone, pair it again with an AI key ticked (PC: Settings > Backup & phones > Add a phone, under Also send).') : phone.reachable ? 'Answers through your PC with its keys. Cites the cards it used.' : 'Needs the PC: answers run there.'}</small></div></div>
    <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
    <div class="m-chat" bind:this={chatEl} onclick={onChip}>
      {#each msgs as m, i (i)}
        {#if m.role === 'user'}
          <div class="m-q">{m.text}</div>
        {:else}
          <div class="m-a" class:err={!!m.error}>
            {#if m.steps?.length}
              {#if m.streaming}<ol class="m-steps">{#each m.steps as st, k (k)}<li>{st}</li>{/each}</ol>
              {:else}<details class="m-steps"><summary>{m.steps.length} research step{m.steps.length > 1 ? 's' : ''}</summary><ol>{#each m.steps as st, k (k)}<li>{st}</li>{/each}</ol></details>{/if}
            {/if}
            {#if m.ctx}<div class="m-ctx">{m.ctx}</div>{/if}
            {@html fmtAnswer(m.text)}
            {#if m.error}<p>{m.error}</p>{/if}
            {#if m.sources?.length}
              <div class="m-src">{#each m.sources.filter(s => !m.cited?.length || m.cited.includes(s.id)).slice(0, 8) as s (s.id)}<button type="button" onclick={() => (location.hash = `#/item/${s.id}`)} aria-label={`Open No.${s.id}`}>{#if s.thumb}<img src={source.thumbUrl(s, 160)} alt="" />{/if}</button>{/each}</div>
            {/if}
            {#if !m.streaming && m.text && !m.error && m.ctx !== 'Stopped.'}
              <div class="m-foot"><span>{onMirror ? `Answered on this phone${m.deep ? ' · Deep' : ''}${ai ? ' · ' + ai.label : ''}` : `Answered on the PC${m.deep ? ' · Deep' : ''}`}{m.cited?.length ? ` · ${m.cited.length} card${m.cited.length > 1 ? 's' : ''}` : ''}</span>{#if m.saved}<span>Saved as {m.saved}</span>{:else}<button type="button" onclick={() => save(m)}>Save as note</button>{/if}</div>
            {/if}
          </div>
        {/if}
      {:else}
        <div class="m-jv-empty">
          <p>Ask anything about your library. Wiskit cites the cards it used.</p>
          <div class="m-jv-sugs">{#each ASK_EXAMPLES as s (s)}<button type="button" class="m-chip" disabled={busy || (onMirror && !ai)} onclick={() => { q = s; send() }}>{s}</button>{/each}</div>
        </div>
      {/each}
    </div>
    {#if canvasProposal}
      <CanvasProposal preview={canvasProposal.preview} imageUrl={canvasImage} busy={reviewBusy} error={reviewError}
        onApply={() => answerCanvas(true)} onDecline={() => answerCanvas(false)} />
    {:else if proposal}
      <section class="m-box m-jv-proposal" aria-label="Wiskit category proposal">
        <h3>Review category changes</h3>
        <p class="m-hint">Wiskit proposes {proposal.entries.length} item{proposal.entries.length === 1 ? '' : 's'}. Categories change only when you tap Apply batch.</p>
        <div class="m-jv-proposal-list">{#each proposal.entries as e (e.id)}<div><b>{e.title || `No. ${e.id}`}</b><small>No. {e.id} · {e.from || 'Uncategorized'} → {e.category}</small></div>{/each}</div>
        {#if reviewError}<p class="m-hint err" role="alert">{reviewError}</p>{/if}
        <div class="m-acts"><MButton disabled={reviewBusy} onclick={() => answerProposal(false)}>Decline</MButton><MButton variant="dk" disabled={reviewBusy} onclick={() => answerProposal(true)}>{reviewBusy ? 'Applying…' : 'Apply batch'}</MButton></div>
      </section>
    {:else if reviewDone}<p class="m-hint m-pad-x" role="status">{reviewDone}{#if openCanvasId} <button type="button" onclick={() => (location.hash = `#/canvas/${encodeURIComponent(openCanvasId)}`)}>Open canvas</button>{/if}</p>{/if}
    {#if canvasRefusal && !canvasProposal}<p class="m-hint m-pad-x" role="status">Not synced: {canvasRefusal.reason} Your phone copy is kept. <button type="button" onclick={() => (location.hash = `#/canvas/${encodeURIComponent(canvasRefusal!.id)}`)}>Open canvas</button></p>{/if}
    {#if ctx}<div class="m-row m-pad-x"><span class="m-badge ok">With {ctx.label}</span><button type="button" class="m-link" onclick={() => (ctx = null)}>Leave it out</button></div>{/if}
    <form class="m-jv-in" onsubmit={e => { e.preventDefault(); send() }}>
      <label class="m-fld"><span class="m-pr">&gt;</span><input bind:this={qEl} bind:value={q} placeholder={deep ? 'Ask Wiskit to research…' : 'Ask your library…'} enterkeyhint="send" autocomplete="off" disabled={busy || (onMirror && !ai)} /></label>
      {#if busy}<MButton onclick={stop}>Stop</MButton>{:else}<MButton variant="dk" type="submit" disabled={!q.trim()}>Send</MButton>{/if}
    </form>
  {/if}
</div>

<style>
  .m-jv-proposal { margin: 10px 12px; gap: 10px }
  .m-jv-proposal p { margin: 0 }
  .m-jv-proposal-list { max-height: 220px; overflow: auto; border: 1px solid var(--wg-edge); border-radius: 8px }
  .m-jv-proposal-list > div { display: grid; gap: 3px; padding: 8px 10px; border-bottom: 1px solid var(--wg-edge) }
  .m-jv-proposal-list > div:last-child { border-bottom: 0 }
  .m-jv-proposal-list b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px }
  .m-jv-proposal-list small { color: var(--wg-dim); font: 500 11px/1.3 var(--display) }
</style>
