<script lang="ts">
  // 02 KNOWLEDGE (V6 main.ws-k): the Sources window (tick list, "in note" / "new" marks, the bench),
  // the Synthesis window (the open note with citation chips, Attach / Save / Rename / Delete / Close,
  // the step log) and the Connections window (insight cards with Sources / Accept / Dismiss).
  import { onMount } from 'svelte'
  import Px from '../../lib/Px.svelte'
  import CardSourcesWin from './CardSourcesWin.svelte'
  import { api } from '../../lib/api'
  import { act } from '../../lib/cardmenu'
  import { soonText } from '../../lib/commands'
  import { titleOf } from '../../lib/cards/card'
  import { startJob } from '../../lib/jobs'
  import { live } from '../../lib/events.svelte'
  import {
    acceptCards, augment, closeNote, cxScanning, deleteNote, dismissCard, installKnowledge, ks, openNote, renameNote,
    resetConnections, scanConnections, synthesize,
  } from '../../lib/knowledge.svelte'
  import { attachItems } from '../../lib/attach'
  import { cardChip, mdHTML } from '../../lib/md'
  import { askHooks } from '../../lib/ask.svelte'
  import { isVid, lib, thumbSrc } from '../../lib/library.svelte'
  import { readyAfterPaint, toast, ui } from '../../lib/ui.svelte'
  import { confirmWin, openWin, promptWin } from '../../lib/windows.svelte'
  import Button from '../../components/ui/Button.svelte'
  import SectionTitle from '../../components/ui/SectionTitle.svelte'

  onMount(installKnowledge)
  onMount(() => readyAfterPaint('know'))

  const inNote = $derived(new Set(ks.note?.row.sources ?? []))
  const topic = $derived(ks.topics.find(t => t.id === ks.topicId))
  const lbl = $derived(ks.items.length ? (ks.tick.size ? `${ks.tick.size} of ${ks.items.length} ticked` : `all ${ks.items.length} (none ticked = all)`) : '')
  const noteHtml = $derived(ks.note ? mdHTML(ks.note.body) : '')
  const last = $derived(ks.lastScan ? new Date(ks.lastScan).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'never')

  function tick(id: number, on: boolean) { if (on) ks.tick.add(id); else ks.tick.delete(id) }
  function rowClick(e: MouseEvent, id: number) {
    if ((e.target as HTMLElement).closest('input,button')) return
    tick(id, !ks.tick.has(id))
  }
  async function bench(k: 'describe' | 'analyze' | 'frames') {
    const ids = (ks.tick.size ? ks.items.filter(r => ks.tick.has(r.id)) : ks.items)
    if (!ids.length) { toast('No sources loaded. Search on the rail first.', 'w'); return }
    if (k === 'describe') startJob('describe', { ids: ids.map(r => r.id), force: true })
    else if (k === 'analyze') {
      const v = ids.filter(isVid).map(r => r.id)
      if (!v.length) { toast('None of these sources is a reel or a video', 'w'); return }
      startJob('analyze', { ids: v, force: true })
    } else {
      const v = ids.filter(r => r.an).map(r => r.id)
      if (!v.length) { toast('None of these sources has frames yet. Analyze them first.', 'w'); return }
      attachItems(v, 'frames')
    }
  }
  async function syn(a: 'attach' | 'copy' | 'folder' | 'save' | 'rename' | 'delete') {
    const n = ks.note
    if (!n) return
    try {
      if (a === 'attach') {
        if (askHooks.attachText) askHooks.attachText(`${n.row.title}\n${n.body}`); else toast(soonText('09'), 'w')
      } else if (a === 'copy') {
        const md = /^\s*#/.test(n.body) ? n.body : `# ${n.row.title}\n\n${n.body}`
        try { await navigator.clipboard.writeText(md); toast('Note copied to the clipboard') } catch { toast('Copy is blocked on this page', 'w') }
      } else if (a === 'folder') {
        await api.post(`/api/notes/${encodeURIComponent(n.file)}/reveal`)
      } else if (a === 'save') {
        await api.put(`/api/notes/${encodeURIComponent(n.file)}`, { body: n.body })
        toast(`Saved data/notes/${n.file}`)
      } else if (a === 'rename') {
        const v = await promptWin({ title: 'Rename note', code: 'WIK-23', label: 'New note name', value: n.meta.topic || n.row.title, ok: 'Rename' })
        if (v && v !== (n.meta.topic || n.row.title)) await renameNote(v)
      } else {
        const ok = await confirmWin({ title: `Delete ${n.file}?`, code: 'WIK-24', danger: true, ok: 'Delete note', msg: `Permanently delete data/notes/${n.file}?`, detail: 'This cannot be undone.' })
        if (ok) await deleteNote()
      }
    } catch (e) { toast((e as Error).message, 'w') }
  }
  function body(e: MouseEvent) {
    const c = (e.target as HTMLElement).closest<HTMLElement>('[data-cid]')
    if (c) act('open', +c.dataset.cid!)
  }
  function sources(key: string) {
    openWin({ id: 'cx-src', title: 'Card sources', code: 'CNX-24', w: 620, body: CardSourcesWin, props: { cardKey: key } })
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
<main class="ws ws-k" id="ws-know" role="tabpanel" aria-labelledby="tab-know" data-ws="know" hidden={ui.ws !== 'know'}>
  <section class="rwin k-src" aria-labelledby="ksrc-h">
    <div class="wbar"><span class="wdots" aria-hidden="true"><i></i><i></i></span><p class="wtitle" id="ksrc-h">Sources · <span id="ksrc-q">{ks.cat ? `collection ${ks.cat}` : ks.q ? `“${ks.q}”` : 'none yet'}</span></p><span class="wcode">SRC-21</span></div>
    <div class="wtools">
      <Button size="sm" onclick={() => ks.items.forEach(r => ks.tick.add(r.id))}>All</Button>
      <Button size="sm" onclick={() => ks.tick.clear()}>None</Button>
      <span class="sp"></span><small aria-live="polite">{ks.loading ? 'Searching…' : lbl}{ks.mode === 'hybrid' ? ' · by meaning' : ''}</small>
    </div>
    <div class="rwin-body" role="list">
      {#if ks.items.length}
        {#each ks.items as r (r.id)}
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions, a11y_no_noninteractive_element_interactions -->
          <div class="srow" class:in={inNote.has(r.id)} role="listitem" onclick={e => rowClick(e, r.id)} ondblclick={() => act('open', r.id)}>
            <input type="checkbox" aria-label={`Include No.${r.id}, ${titleOf(r)}`} checked={ks.tick.has(r.id)} onchange={e => tick(r.id, e.currentTarget.checked)} />
            {#if r.thumb}<img src={thumbSrc(r.id)} alt="" loading="lazy" />{:else}<span></span>{/if}
            <span><b>{titleOf(r)}</b><small>No.{r.id} · {r.creator || 'unknown'} · {r.cat} · {r.type}{r.an ? ' · report' : ''}</small></span>
            <span class="sbx">{#if inNote.has(r.id)}<span class="bdg in">in note</span>{/if}<Button size="sm" aria-label={`Open No.${r.id}`} onclick={() => act('open', r.id)}>Open</Button></span>
          </div>
        {/each}
      {:else}
        <div class="emp"><h3>No sources</h3><p>{ks.q || ks.cat ? (ks.cat ? 'That collection is empty.' : `Nothing matches every word of “${ks.q}”. Try fewer words, or load a whole collection from the rail.`) : 'Search a topic on the rail, or load a collection. Tick sources, then Synthesize: the AI reads them and writes one note to data/notes/.'}</p></div>
      {/if}
    </div>
    <div class="rwin-foot">
      <Button size="sm" title="Rerun AI Describe on the ticked sources (runs as a background job)" onclick={() => bench('describe')}>Describe</Button>
      <Button size="sm" title="Analyze the ticked reels and videos (runs as a background job)" onclick={() => bench('analyze')}>Analyze</Button>
      <Button size="sm" title="Drop the ticked sources' extracted frames onto the active canvas" onclick={() => bench('frames')}>Frames to canvas</Button>
      <span class="sp"></span>
      <label class="sr" for="ks-merge">Merge mode</label>
      <select class="wsel" id="ks-merge" bind:value={ks.merge}><option value="integrate">Integrate &amp; reorganize</option><option value="append">Append &amp; merge</option></select>
      <Button size="sm" aria-disabled={ks.note ? undefined : 'true'} title={ks.note ? `Merge the ticked sources into ${ks.note.file}` : 'Open a note first (Saved notes on the rail)'} onclick={augment}>Augment note</Button>
      <Button variant="pri" onclick={synthesize}>Synthesize</Button>
    </div>
  </section>

  <section class="rwin k-syn" aria-labelledby="ksyn-h">
    <div class="wbar"><span class="wdots" aria-hidden="true"><i></i><i></i></span><p class="wtitle" id="ksyn-h">Synthesis{ks.note ? ` · ${ks.note.file}` : ''}</p><span class="wcode">WIK-22</span></div>
    <div class="wtools">
      <Button size="sm" aria-disabled={ks.note ? undefined : 'true'} onclick={() => syn('attach')}>Attach to canvas</Button>
      <Button size="sm" aria-disabled={ks.note ? undefined : 'true'} title="Copy the note text (markdown) to the clipboard" onclick={() => syn('copy')}>Copy</Button>
      <Button size="sm" aria-disabled={ks.note ? undefined : 'true'} title="Show the note file in its folder" onclick={() => syn('folder')}>Open folder</Button>
      <Button size="sm" aria-disabled={ks.note ? undefined : 'true'} onclick={() => syn('save')}>Save</Button>
      <Button size="sm" aria-disabled={ks.note ? undefined : 'true'} onclick={() => syn('rename')}>Rename</Button>
      <Button variant="danger" size="sm" aria-disabled={ks.note ? undefined : 'true'} onclick={() => syn('delete')}>Delete</Button>
      <span class="sp"></span>
      <Button size="sm" onclick={closeNote}>Close note</Button>
    </div>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="rwin-body" id="ksyn-body" onclick={body}>
      {#if ks.note}
        <div class="md">
          <p class="nmeta"><span class="bdg">{ks.note.row.kind}</span><span>data/notes/{ks.note.file}</span><span>updated {ks.note.row.updated.slice(0, 10)}</span></p>
          <h1 class="ntt">{ks.note.row.title}</h1>
          {@html noteHtml}
          {#if ks.note.row.sources.length}
            <SectionTitle as="p">Sources · {ks.note.row.sources.length}</SectionTitle>
            <p class="nsrc">{@html ks.note.row.sources.slice(0, 24).map(cardChip).join('')}{#if ks.note.row.sources.length > 24}<small>+{ks.note.row.sources.length - 24} more</small>{/if}</p>
          {/if}
        </div>
      {:else}
        <div class="emp"><h3>No note open</h3><p>Tick sources and press Synthesize: the AI reads them and writes one note to data/notes/. Or open a saved note from the rail.</p></div>
      {/if}
    </div>
    <details class="k-log"><summary>Steps {ks.log.length ? `· ${ks.log.length}` : ''}<span class="sp"></span></summary><pre class="tlog">{ks.log.join('\n') || 'No steps yet. Synthesize or augment a note to see what the AI reads.'}</pre></details>
  </section>

  <section class="rwin k-cx" aria-labelledby="kcx-h">
    <div class="wbar"><span class="wdots" aria-hidden="true"><i></i><i></i></span><p class="wtitle" id="kcx-h">Connections</p><span class="wcode">CNX-23</span></div>
    <div class="wtools">
      <Button size="sm" disabled={cxScanning()} onclick={scanConnections}>{cxScanning() ? 'Scanning…' : 'Find connections'}</Button>
      <Button size="sm" onclick={resetConnections}>Reset</Button>
      <Button size="sm" onclick={() => ks.cards.forEach(c => ks.cxSel.add(c.key))}>All</Button>
      <Button size="sm" onclick={() => ks.cxSel.clear()}>None</Button>
      <Button size="sm" disabled={!ks.cxSel.size} onclick={() => acceptCards([...ks.cxSel])}>Synthesize selected</Button>
      <span class="sp"></span><small aria-live="polite">Last scan {last} · {ks.cards.length} insight{ks.cards.length === 1 ? '' : 's'}{ks.cxSel.size ? ` · ${ks.cxSel.size} selected` : ''}{ks.cxQueue.length ? ` · ${ks.cxQueue.length} queued` : ''}</small>
    </div>
    {#if cxScanning() || ks.cxActive}
      <!-- the running scan or card synthesis, with its live step (the job's step / the synth log). No Stop:
           a scan is one job item and the server only stops between items -->
      <div class="cx-run" class:held={live.jobs.current?.state === 'paused'} role="status">
        <b>{cxScanning() ? 'Scanning' : 'Synthesizing'}</b>
        <span>{live.jobs.current?.state === 'paused' ? 'Paused' : cxScanning() ? live.step || 'Reading the search index…' : ks.log.at(-1) || 'Writing the note…'}</span>
      </div>
    {/if}
    <div class="rwin-body"><div class="cx-cards">
      {#each ks.cards as c (c.key)}
        <article class="cx" class:busy={ks.cxActive === c.key}>
          <div class="cx-hd">
            <input type="checkbox" aria-label={`Select: ${c.text}`} checked={ks.cxSel.has(c.key)} onchange={e => (e.currentTarget.checked ? ks.cxSel.add(c.key) : ks.cxSel.delete(c.key))} />
            <span class={'cxk ' + c.kind}>{c.kind}</span>
            <small>{c.item_ids.length} item{c.item_ids.length === 1 ? '' : 's'}</small>
          </div>
          <p>{c.text}</p>
          <div class="cx-its">
            {#each c.items as it (it.id)}<button type="button" title={it.title} onclick={() => act('open', it.id)}>{#if lib.byId.get(it.id)?.thumb}<img src={thumbSrc(it.id)} alt="" />{/if}No.{it.id}</button>{/each}
          </div>
          <div class="cx-act">
            <Button size="sm" onclick={() => sources(c.key)}>Sources</Button>
            <Button size="sm" aria-disabled={ks.cxQueue.includes(c.key) || ks.cxActive === c.key ? 'true' : undefined} onclick={() => acceptCards([c.key])}>{ks.cxActive === c.key ? 'Writing…' : ks.cxQueue.includes(c.key) ? 'Queued' : 'Accept'}</Button>
            <Button size="sm" onclick={() => dismissCard(c.key)}>Dismiss</Button>
          </div>
        </article>
      {:else}
        <div class="emp"><h3>No insights</h3><p>Find connections reads your indexed saves and proposes bridges between topics and shifts in what you save. Every card is checked by the AI first.</p></div>
      {/each}
    </div></div>
  </section>
</main>
