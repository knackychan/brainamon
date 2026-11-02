<script lang="ts">
  // Wiskit, the right rail on every workspace (V6 aside.jv; Qt ui/ask_panel.py): Quick / Deep,
  // saved chats and the SET pop-overs, Wiskit's animated display,
  // the transcript with streamed answers and citation chips, the composer with Send / Stop.
  import { onMount, tick } from 'svelte'
  import WiskitFiling from './WiskitFiling.svelte'
  import WiskitMsg from './WiskitMsg.svelte'
  import {
    ask, askWiskit, blankChat, loadAsk, newChat, openChat, openNote, refreshChats, reviewThisWeek, saveOptions, setCited, setMode, stopAsk,
  } from '../lib/ask.svelte'
  import { api } from '../lib/api'
  import { openSettings } from '../lib/io-commands.svelte'
  import { guiding, openWiskitKey } from '../lib/onboarding.svelte'
  import { act } from '../lib/cardmenu'
  import { lib } from '../lib/library.svelte'
  import { ACCEPT, attachFiles } from '../lib/filing.svelte'
  import WiskitSprite from './WiskitSprite.svelte'
  import { drawTether, hl, locateCard, unhl } from '../lib/tether'
  import { toast, ui } from '../lib/ui.svelte'
  import { confirmWin, promptWin } from '../lib/windows.svelte'
  import { ASK_EXAMPLES } from '../lib/ask-examples'
  import Button from './ui/Button.svelte'
  import Field from './ui/Field.svelte'
  import Hint from './ui/Hint.svelte'

  const SUGS = ASK_EXAMPLES

  let input = $state('')
  let ta: HTMLTextAreaElement | undefined = $state()
  let log: HTMLDivElement | undefined = $state()
  let pop = $state<null | 'chats' | 'set'>(null)
  let dragging = $state(false)               // files over the rail (projects/wiskit-files)
  let picker: HTMLInputElement | undefined = $state()
  // SET pop-over draft
  let dProvider = $state(''), dModel = $state(''), dDepth = $state(25), dScope = $state('')

  onMount(() => {
    loadAsk()
    const away = (e: PointerEvent) => { if (pop && !(e.target as HTMLElement).closest('.jpop,#chats-k,#set-k,.action-popup,.action-scrim')) pop = null }
    document.addEventListener('pointerdown', away, true)
    const board = () => document.getElementById('board')
    const redraw = () => { if (lib.hlId !== null) drawTether() }
    board()?.addEventListener('scroll', redraw, { passive: true })
    addEventListener('resize', redraw)
    return () => { document.removeEventListener('pointerdown', away, true); removeEventListener('resize', redraw) }
  })

  // keep the newest message in view while it streams
  $effect(() => {
    const last = ask.msgs[ask.msgs.length - 1]
    last && (last.role === 'jarvis' ? last.text.length + last.trace.length : 0)
    if (!log) return
    const near = log.scrollHeight - log.scrollTop - log.clientHeight < 120
    if (near || ask.busy) tick().then(() => { if (log) log.scrollTop = log.scrollHeight })
  })

  const conn = $derived(!ask.opts ? 'pending' : 'live')
  const reviewReason = $derived(
    !ask.opts ? 'Wiskit is loading…'
    : ask.busy ? 'Wait for this answer, or press Stop.'
    : ask.mode === 'claude_code' ? 'Choose an API model to review this week.'
    : ask.atts.length ? 'Send or remove attached files first.'
    : input.trim() ? 'Send or clear your draft first.'
    : (!ask.provider || !ask.model) ? 'Choose a model in SET first.'
    : '')

  function send(e?: Event) {
    e?.preventDefault()
    const q = input.trim()
    if (!q || ask.busy) return
    input = ''
    grow()
    pop = null
    askWiskit(q)
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send() }
  }
  function grow() { if (!ta) return; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 132) + 'px' }

  // files: drop them anywhere on the rail, paste them into the box, or press Attach (lib/filing.svelte.ts)
  function dragOver(e: DragEvent) {
    if (!e.dataTransfer?.types.includes('Files')) return
    e.preventDefault()
    dragging = true
  }
  function dragLeave(e: DragEvent) {
    if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) dragging = false
  }
  function dropFiles(e: DragEvent) {
    dragging = false
    const files = [...(e.dataTransfer?.files ?? [])]
    if (!files.length) return
    e.preventDefault()
    attachFiles(files)
  }
  function pasteFiles(e: ClipboardEvent) {
    const files = [...(e.clipboardData?.files ?? [])]
    if (!files.length) return                // text pastes go into the box as usual
    e.preventDefault()
    attachFiles(files)
  }
  function picked() {
    if (picker?.files?.length) attachFiles([...picker.files])
    if (picker) picker.value = ''
  }

  function reviewWeek() {
    if (reviewReason) return
    pop = null
    reviewThisWeek()
  }

  // citations: hover finds the card, click opens it; the stepper walks the last answer's citations
  function over(e: Event) {
    const c = (e.target as HTMLElement).closest<HTMLElement>('[data-cid]')
    if (c) { hl(+c.dataset.cid!, c); ask.pet = 'point' }
  }
  function out(e: PointerEvent | FocusEvent) {
    const c = (e.target as HTMLElement).closest<HTMLElement>('[data-cid]')
    if (c && !c.contains(e.relatedTarget as Node)) { unhl(); if (ask.pet === 'point') ask.pet = 'idle' }
  }
  function click(e: MouseEvent) {
    const t = e.target as HTMLElement
    const loc = t.closest<HTMLElement>('[data-loc]')
    if (loc) { unhl(); locateCard(+loc.dataset.loc!); return }
    const n = t.closest<HTMLElement>('[data-note]')
    if (n) { unhl(); openNote(n.dataset.note!); return }
    const c = t.closest<HTMLElement>('[data-cid]')
    if (c) { unhl(); act('open', +c.dataset.cid!); return }
    const s = t.closest<HTMLElement>('[data-sug]')
    if (s) askWiskit(s.dataset.sug!)
  }
  function step(d: number) {
    const ids = [...lib.cited.keys()]
    if (!ids.length) { toast('No citations in the last answer', 'w'); return }
    let k = ask.navId === null ? -1 : ids.indexOf(ask.navId)
    k = (k + d + ids.length) % ids.length
    ask.navId = ids[k]
    locateCard(ids[k])
    const chip = log?.querySelector<HTMLElement>(`.m-j:last-of-type .ans [data-cid="${ids[k]}"]`)
    if (chip) setTimeout(() => hl(ids[k], chip), 350)
  }

  // the pop-overs
  function openPop(which: 'chats' | 'set') {
    if (pop === which) { pop = null; return }
    if (which === 'set') { dProvider = ask.provider; dModel = ask.model; dDepth = ask.depth; dScope = ask.scope }
    else refreshChats()
    pop = which
  }
  function pickProvider(p: string) {
    dProvider = p
    const models = ask.opts?.models[p] ?? []
    dModel = ask.opts?.default_models[p] || models[0]?.id || ''
  }
  async function saveSet() {
    Object.assign(ask, { provider: dProvider, model: dModel, depth: +dDepth, scope: dScope })
    if (ask.mode === 'deep' && !ask.canDeep) setMode('quick')
    await saveOptions()
    pop = null
    toast(`Wiskit: ${ask.provider} · ${ask.modelLabel}${ask.scope ? ` · ${ask.scope} only` : ''}`)
  }
  async function chatAct(a: 'new' | 'rename' | 'clear' | 'delete') {
    if (a === 'new') { pop = null; newChat(); return }
    if (!ask.slug && a !== 'clear') return
    try {
      if (a === 'clear') {
        // a first question can still be streaming before the server names the chat: no slug yet, clear locally
        if (!ask.msgs.length) return
        const ok = await confirmWin({ title: 'Clear this chat?', code: 'ASK-04', danger: true, ok: 'Clear chat', msg: `The messages in “${ask.name}” are removed; the chat stays in Saved chats. This cannot be undone.` })
        if (!ok) return
        if (ask.busy) stopAsk()
        if (ask.slug) await api.post(`/api/chats/${encodeURIComponent(ask.slug)}/clear`)
        ask.msgs = []; setCited([])
        toast('Cleared the chat')
      } else if (a === 'rename') {
        const v = await promptWin({ title: 'Rename the chat', code: 'ASK-02', label: 'Title', value: ask.name, ok: 'Rename' })
        if (!v) return
        const r = await api.post<{ slug: string; name: string }>(`/api/chats/${encodeURIComponent(ask.slug)}/rename`, { name: v })
        ask.slug = r.slug; ask.name = r.name
      } else {
        await delChat(ask.slug, ask.name)
        return
      }
      refreshChats()
    } catch (e) { toast((e as Error).message, 'w') }
  }
  // the open chat (Delete) or any saved one (its row's ×); the phone loses it at the next upload
  async function delChat(slug: string, name: string) {
    const from = document.activeElement as HTMLElement | null
    const row = from?.closest('.chr-w')
    const next = (row?.nextElementSibling ?? row?.previousElementSibling)?.querySelector<HTMLButtonElement>('.chr-x')
    try {
      const ok = await confirmWin({ title: 'Delete this chat?', code: 'ASK-03', danger: true, ok: 'Delete chat', msg: `“${name}” and its answers are removed, here and on the phone. This cannot be undone.` })
      if (!ok) return
      const open = slug === ask.slug
      if (open && ask.busy) stopAsk()
      const r = await api.del<{ chats: { slug: string }[] }>(`/api/chats/${encodeURIComponent(slug)}`)
      ask.chats = r.chats as any
      if (open) { if (r.chats.length) await openChat(r.chats[0].slug); else blankChat() }
      await tick()
      if (pop === 'chats' && (!from?.isConnected || from.matches(':disabled'))) (next?.isConnected ? next : document.getElementById('chats-k'))?.focus({ preventScroll: true })
      toast('Deleted the chat')
    } catch (e) { toast((e as Error).message, 'w') }
  }
</script>

<aside class="jv" class:open={ui.drawer === 'jv'} class:drag={dragging} id="jv" aria-label="Wiskit, chat with your library">
  <div class="wbar">
    <span class="wdots" aria-hidden="true"><i></i><i></i></span>
    <div class="wid">
      <p class="wtitle">~/wiskit - librarian</p>
      <p class="jv-st" id="jv-st" data-s={conn} aria-live="polite"><span id="jv-st-t">{#if ask.opts}{ask.mode === 'claude_code' ? 'Claude Code' : `${ask.provider} · ${ask.modelLabel}`}{:else}Connecting…{/if}</span></p>
    </div>
    <div class="scene"><WiskitSprite id="pet" pose={ask.pet} motionOff={ui.motionOff} /></div>
    <span class="wled" title="Wiskit connection"><i id="led" data-s={conn}></i></span>
    <Button class="jv-x" id="close-jv" onclick={() => (ui.drawer = null)}>Close</Button>
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="wtools" id="jv-tools" onkeydown={e => { if (e.key === 'Escape' && pop) { e.preventDefault(); e.stopPropagation(); pop = null } }}>
    <span class="seg" role="group" aria-label="Answer depth">
      <button type="button" aria-pressed={ask.mode === 'quick'} onclick={() => setMode('quick')}>Quick</button>
      <button type="button" aria-pressed={ask.mode === 'deep'} title={ask.canDeep ? 'Deep: the librarian searches with tools' : 'Deep needs Anthropic or OpenAI (SET)'} onclick={() => setMode('deep')}>Deep</button>
      {#if ask.canClaude}<button type="button" aria-pressed={ask.mode === 'claude_code'} title="Claude Code: your Claude Code login reads the library through the Brainamon tools" onclick={() => setMode('claude_code')}>Claude Code</button>{/if}
    </span>
    <Button class="chats" id="chats-k" aria-haspopup="dialog" aria-expanded={pop === 'chats'} aria-controls="chats-pop" title={`Saved chat: ${ask.name}`} onclick={() => openPop('chats')}><span id="chat-t">{ask.name}</span></Button>
    <Button id="newchat" aria-label="New chat" title="New chat" onclick={() => newChat()}>+</Button>
    <Button id="clearchat" title="Clear this chat's messages (the chat stays saved)" disabled={!ask.msgs.length} onclick={() => chatAct('clear')}>Clear</Button>
    <Button id="set-k" aria-haspopup="dialog" aria-expanded={pop === 'set'} aria-controls="set-pop" title={`Ask settings: ${ask.provider} · ${ask.modelLabel} · depth ${ask.depth} · scope ${ask.scope || 'Auto'}`} onclick={() => openPop('set')}>SET</Button>
    <div class="jpop" id="chats-pop" role="dialog" aria-label="Saved chats" hidden={pop !== 'chats'}>
      <h4><span>Saved chats</span><span>{ask.chats.length}</span></h4>
      <div class="chl">
        {#each ask.chats as c (c.slug)}
          <div class="chr-w">
            <button type="button" class="chr" aria-current={c.slug === ask.slug} onclick={() => { pop = null; openChat(c.slug) }}><span>{c.name}</span><small>{(c.updated || '').slice(0, 10)}</small></button>
            <button type="button" class="chr-x" aria-label={`Delete “${c.name}”`} title="Delete this chat" onclick={() => delChat(c.slug, c.name)}>×</button>
          </div>
        {:else}
          <Hint>No saved chats yet. Your first question starts one.</Hint>
        {/each}
      </div>
      <div class="frow">
        <Button size="sm" onclick={() => chatAct('new')}>+ New</Button><span class="sp"></span>
        <Button size="sm" disabled={!ask.slug} onclick={() => chatAct('rename')}>Rename</Button>
        <Button size="sm" disabled={!ask.msgs.length} onclick={() => chatAct('clear')}>Clear</Button>
        <Button variant="danger" size="sm" disabled={!ask.slug} onclick={() => chatAct('delete')}>Delete</Button>
      </div>
    </div>
    <div class="jpop" id="set-pop" role="dialog" aria-label="Ask settings" hidden={pop !== 'set'}>
      <h4><span>Ask settings</span><span>{dProvider}</span></h4>
      {#if ask.opts}
        <div class="fg">
          <Field label="Provider" for="as-pr"><select class="inp" id="as-pr" value={dProvider} onchange={e => pickProvider(e.currentTarget.value)}>
            {#each ask.opts.providers as p (p.id)}<option value={p.id} disabled={!p.enabled} title={p.note}>{p.label}</option>{/each}
          </select></Field>
          <Field label="Model" for="as-mo"><select class="inp" id="as-mo" bind:value={dModel}>{#each ask.opts.models[dProvider] ?? [] as m (m.id)}<option value={m.id}>{m.label}</option>{/each}</select></Field>
          <Field label="Depth" for="as-de"><select class="inp" id="as-de" bind:value={dDepth}>{#each ask.opts.depths as d (d)}<option value={d}>{d}</option>{/each}</select></Field>
          <Field label="Scope" for="as-sc"><select class="inp" id="as-sc" bind:value={dScope}><option value="">Auto</option>{#each ask.opts.scopes as s (s)}<option value={s}>{s}</option>{/each}</select></Field>
        </div>
        <Hint>Model changes apply to this chat. New chats start with the Wiskit model from Settings. Depth is how many items a Quick answer reads; Scope keeps it to one collection. Deep mode needs Anthropic or OpenAI.</Hint>
      {/if}
      <div class="frow"><span class="sp"></span><Button variant="pri" size="sm" onclick={saveSet}>Save</Button></div>
    </div>
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="wbody" ondragover={dragOver} ondragleave={dragLeave} ondrop={dropFiles}>
    <div class="lcd panel">
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="jv-log" id="log" aria-live="polite" aria-busy={ask.busy} bind:this={log}
        onpointerover={over} onpointerout={out} onfocusin={over} onfocusout={out} onclick={click}>
        {#if !ask.msgs.length}
          <div class="jv-empty dlg" id="empty">
            <h3>Ask your library.</h3>
            <p>I cite every card I use and flag general knowledge. Hover a citation to find its card; click to open it.</p>
            <ul class="sugs" id="sugs">{#each SUGS as s (s)}<li><button type="button" data-sug={s}>{s}</button></li>{/each}</ul>
            <div class="jv-recent" id="jv-recent">
              {#if ask.chats.length}
                <h4><span>Recent chats</span><span>{ask.chats.length}</span></h4>
                {#each ask.chats.slice(0, 4) as c (c.slug)}<button type="button" onclick={() => openChat(c.slug)}><span>{c.name}</span><small>{(c.updated || '').slice(0, 10)}</small></button>{/each}
              {/if}
            </div>
            <small>Save any answer as a note. It shows up in Knowledge.</small>
          </div>
        {/if}
        {#each ask.msgs as m, i (i)}
          {#if m.role === 'user'}<div class="m-u"><small>You{m.t ? ` · ${m.t}` : ''}</small><p>{m.text}</p>{#if m.files?.length}<small class="jv-ufiles">with {m.files.join(', ')}</small>{/if}</div>
          {:else}<WiskitMsg {m} />{/if}
        {/each}
      </div>
    </div>
    <form class="jv-cmp" id="cmp" onsubmit={send}>
      {#if ask.problem}
        {@const own = ask.provider === 'anthropic' || ask.provider === 'openai'}
        {@const calm = own && guiding()}
        <p class="jv-nokey" class:calm role={calm ? 'status' : 'alert'}>{calm ? 'Wiskit is off until you add an AI key.' : ask.problem} <Button size="sm" onclick={() => (own ? openWiskitKey(ask.provider) : openSettings('keys'))}>{own ? 'Turn on Wiskit' : 'API keys…'}</Button></p>
      {/if}
      <WiskitFiling />
      <div class="jv-review-row">
        <Button size="sm" id="review-week"
          aria-disabled={!!reviewReason} aria-describedby="review-week-hint"
          onclick={reviewWeek}>Review this week</Button>
        <small id="review-week-hint">{reviewReason || 'Last 7 dates · all collections'}</small>
      </div>
      <label class="sr" for="ask">Ask Wiskit</label>
      <div class="cmp-box panel"><b aria-hidden="true">&gt;</b>
        <textarea id="ask" rows="1" placeholder={ask.problem ? 'Wiskit needs an API key first…' : ask.atts.length ? 'Ask about the attached files…' : 'Ask your library…'} autocomplete="off" bind:this={ta} bind:value={input} oninput={grow} onkeydown={key} onpaste={pasteFiles}></textarea>
        <input type="file" multiple accept={ACCEPT} hidden bind:this={picker} onchange={picked} />
        <button class="lkey" type="button" id="attach" title="Attach a PDF, a .md or .txt file, or a picture" onclick={() => picker?.click()}>Attach</button>
        <button class="lkey" type="submit" id="send" hidden={ask.busy}>Send</button>
        <button class="lkey" type="button" id="stop" hidden={!ask.busy} onclick={stopAsk}>Stop</button>
      </div>
      <p class="cmp-hint"><span id="jv-note">{ask.mode === 'deep' ? 'Deep: the librarian researches with tools' : ask.mode === 'claude_code' ? 'Claude Code: researches with the Brainamon tools, asks before saving' : 'Quick: the best-ranked items and notes'}</span><span class="cnav" role="group" aria-label="Step through citations"><Button aria-label="Previous citation" title="Previous citation" onclick={() => step(-1)}>◀</Button>cite<Button aria-label="Next citation" title="Next citation" onclick={() => step(1)}>▶</Button></span></p>
    </form>
  </div>
</aside>

<style>
  /* Wiskit's screen lives in the title bar, so the chat gets the whole body */
  .wbar { height: 68px }
  /* no screen frame: the cat stands on the bar's line; the cell's empty top is clipped by the bar */
  .wid { flex: 0 1 auto; min-width: 0; max-width: 185px; display: grid; gap: 5px }
  .wid > * { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
  .wbar .wtitle { position: static; transform: none; max-width: none }
  .wbar .jv-st { margin: 0 }
  .wbar .scene {
    /* the cell's empty sides slide under the title block and the LED / Close, so the cat can be big */
    flex: none; width: 240px; margin: 0 -50px 0 auto; align-self: stretch; height: auto;
    border: 0; border-radius: 0; background: none; overflow: hidden;
  }
  .wbar .scene::after { display: none }
  .wbar .wled, .wbar :global(.jv-x) { position: relative; z-index: 1 }
  .wbar .scene :global(canvas) { inset: auto; left: 0; bottom: 0; width: 100%; height: auto; aspect-ratio: 96 / 56 }
</style>
