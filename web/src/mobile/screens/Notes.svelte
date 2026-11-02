<script module lang="ts">
  import type { Stamp } from '../../lib/note-format'
  import type { MyNote, NoteRow, OpenNote, Row } from '../source/types'
  // a note the screen closed on (another tab) while its save was still going or had failed: the next
  // Notes screen takes it back with its edits instead of the stored copy (plans/07-phone-editor-review.md #1)
  type Left = { my: MyNote; title: string; body: string; category: string; stamps: Stamp[]; stampTouched: boolean; done: Promise<boolean> }
  let left: Left | null = null
</script>

<script lang="ts">
  import ObsidianIcon from '../../components/ui/ObsidianIcon.svelte'
  // 05 Notes: Knowledge notes (read; their sources open the cards), Synthesize a note (PLAN.md
  // Phase 5: on the phone up to source.synthMax sources, more are queued for the PC; on the desktop
  // source it is the PC's job) and My Notes (the round 2 dot-paper editor, plans/07-phone-editor.md).
  // Lists are kept in the phone's copy.
  import { onDestroy, onMount, untrack } from 'svelte'
  import { mdHTML } from '../../lib/md'
  import { kv } from '../store'
  import { phone, solo, source } from '../state.svelte'
  import { graphUrl, noteText, obsidianUrl, vaultName } from '../obsidian'
  import { openObsidian } from '../native'
  import { appendVoice, flush as flushVoice, queued } from '../voice'
  import NoteEditor from './NoteEditor.svelte'
  import NoteCard from '../NoteCard.svelte'
  import '../note.css'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'

  let { file, myFile, synth }: { file?: string; myFile?: string; synth?: string } = $props()
  let seg = $state<'know' | 'mine'>('mine')     // My notes first, then Knowledge
  let notes = $state<NoteRow[]>([]), mine = $state<MyNote[]>([])
  let cats = $state<string[]>([])
  let cat = $state('All')
  let open = $state<OpenNote | null>(null), my = $state<MyNote | null>(null)
  let title = $state(''), body = $state(''), myCat = $state(''), stamps = $state<Stamp[]>([])
  let status = $state<'saved' | 'pending' | 'saving' | 'error'>('saved'), savedAt = $state('')
  let revision = $state(0), focusTitle = $state(false)
  let showSrc = $state(false)
  let err = $state('')

  // Open in Obsidian: the note goes into the phone's vault where the PC's export puts it. The app
  // knows when Obsidian is missing; a browser opens nothing, so say what to expect
  let obsNote = $state('')
  const NO_OBS = 'Obsidian is not installed on this phone. Get it from the Play Store, then open your vault in it once.'
  async function toObsidian(file: string, text: string) {
    const ok = await openObsidian(obsidianUrl(vaultName(source.obsidianVault?.() ?? ''), file, text, source.obsidianNotes?.() ?? ''))
    obsNote = ok === false ? NO_OBS : 'Sent to Obsidian. Nothing opened? Install Obsidian, or set the vault name under More.'
  }
  // See my knowledge graph: Obsidian on the vault; its graph view is in Obsidian's own menu
  let graphNote = $state('')
  async function seeGraph() {
    const ok = await openObsidian(graphUrl(vaultName(source.obsidianVault?.() ?? '')))
    graphNote = ok === false ? NO_OBS
      : 'In Obsidian, open the graph view from the menu (or the command palette: "Open graph view"). Nothing opened? Install Obsidian, or set the vault name under More.'
  }

  async function loadLists() {
    notes = (await kv.get<NoteRow[]>('notes')) ?? []
    mine = (await kv.get<MyNote[]>('mynotes')) ?? []
    try {
      const [n, m, c] = await Promise.all([source.notes(), source.myNotes(), source.myNoteCategories()])
      notes = n.filter(x => x.kind.toLowerCase() !== 'personal'); mine = m; cats = c      // personal notes are the My notes list
      kv.set('notes', notes); kv.set('mynotes', m)
    } catch { /* the copy stays */ }
  }
  onMount(loadLists)

  // ── autosave (desktop notes.svelte.ts, on the phone's source) ──
  let timer = 0, dirty = false, stampTouched = false, version = 0, stampVersion = 0
  let saving: Promise<boolean> | null = null
  function edited() {
    if (!my) return
    dirty = true; version++
    status = 'pending'
    clearTimeout(timer)
    timer = window.setTimeout(() => { void flush() }, 800)
  }
  function setStamps(s: Stamp[]) { stamps = s; stampTouched = true; stampVersion++; edited() }
  async function flush(): Promise<boolean> {
    clearTimeout(timer)
    while (my && (dirty || saving)) {
      if (!saving) saving = save().finally(() => { saving = null })
      if (!await saving) return false
    }
    return true
  }
  async function save(): Promise<boolean> {
    if (!my || !dirty) return true
    const file = my.file
    const sendStamps = stampTouched
    const sentVersion = version, sentStampVersion = stampVersion
    status = 'saving'
    try {
      const n = await source.saveMyNote(file, title, myCat, body, sendStamps ? stamps : undefined)
      if (my?.file === file) {
        if (version === sentVersion) { dirty = false; status = 'saved'; savedAt = (n.updated || '').slice(11, 19) }
        else status = 'pending'
        if (stampVersion === sentStampVersion) stampTouched = false
        my = n
      }
      loadLists()
      return true
    } catch (e) {
      if (my?.file === file) { err = (e as Error).message; status = 'error'; dirty = true; if (sendStamps) stampTouched = true }
      return false
    }
  }
  onMount(() => {
    const onHide = () => { void flush() }
    addEventListener('pagehide', onHide)
    return () => removeEventListener('pagehide', onHide)
  })
  // leaving the Notes screen saves the open note; until that save lands its edits are kept in `left`
  onDestroy(() => {
    if (!my || !(dirty || saving)) return
    const kept: Left = { my: $state.snapshot(my), title, body, category: myCat, stamps: $state.snapshot(stamps), stampTouched, done: flush() }
    left = kept
    void kept.done.then(ok => { if (ok && left === kept) left = null })
  })
  if (left) {
    // after the last screen's save is done (landed or failed), this one saves the edits again
    const k = left; left = null
    my = k.my; title = k.title; body = k.body; myCat = k.category; stamps = k.stamps; stampTouched = k.stampTouched
    dirty = true; version++
    saving = k.done.then(() => true).finally(() => { saving = null })
    edited()
  }

  // untrack: the API client counts requests in a $state (src/lib/net.svelte.ts); read inside the
  // effect it would re-run it
  $effect(() => {
    const f = file
    untrack(() => {
      if (f) { seg = 'know'; open = null; err = ''; source.note(f).then(n => (open = n)).catch(e => (err = (e as Error).message)) }
      else open = null
    })
  })
  let opening = 0
  $effect(() => {
    const f = myFile
    untrack(() => { void show(f) })
  })
  // open a note, or the list (f undefined). The note being edited is saved first; one whose save
  // fails stays, with its edits, and nothing loads over it. The latest open wins.
  async function show(f: string | undefined) {
    const request = ++opening
    err = ''
    if (f) seg = 'mine'
    if (f && my?.file === f) { if (dirty) edited(); return }        // back to the note being edited
    if (!await flush()) {
      if (request === opening && my) err = `"${title || 'Untitled'}" is not saved (${err || 'save failed'}). Open it again to keep its changes.`
      return
    }
    if (request !== opening) return
    if (!f) { my = null; return }
    try {
      const n = await source.myNote(f)
      if (request !== opening) return
      my = n; title = n.title; body = n.body ?? ''; myCat = n.category; stamps = n.stamps ?? []
      dirty = false; stampTouched = false; status = 'saved'; savedAt = (n.updated || '').slice(11, 19); revision++
    } catch (e) { if (request === opening) err = (e as Error).message }
  }

  async function create(record = false) {
    try {
      const d = new Date(), p = (v: number) => String(v).padStart(2, '0')
      const title = record ? `Note ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}` : ''
      const n = await source.createMyNote(title, cat === 'All' ? '' : cat)
      await loadLists()
      focusTitle = !record
      if (record) sessionStorage.setItem('bp-record-note', n.file)
      location.hash = `#/mynotes/${encodeURIComponent(n.file)}`
    } catch (e) { err = (e as Error).message }
  }
  async function del() {
    if (!my) return
    if (!await flush()) return
    const file = my.file
    try {
      if (source.deleteMyNote) { await source.deleteMyNote(file); my = null }
      else err = 'Deleting a note runs on the PC.'
      loadLists()
      location.hash = '#/mynotes'
    } catch (e) { err = (e as Error).message }
  }
  function obsidianNote() {
    if (!my) return
    toObsidian(my.file, noteText({ topic: title, created: my.created, updated: my.updated, kind: 'personal', category: myCat }, body))
  }
  // ── voice notes: text from a recording goes into the editor; waiting recordings are saved when online ──
  let waiting = $state(0)
  function addVoice(text: string) { body = appendVoice(body, text); revision++; edited() }
  async function countWaiting() { waiting = (await queued().catch(() => [])).length }
  async function flushWaiting() {
    if (!source.transcribe || navigator.onLine === false) return
    await flushVoice(
      b => source.transcribe!(b),
      async (file, text) => { const n = await source.myNote(file); await source.saveMyNote(n.file, n.title, n.category, appendVoice(n.body ?? '', text)) },
      file => my?.file === file,
    )
    countWaiting(); loadLists()
  }
  onMount(() => { countWaiting(); flushWaiting(); addEventListener('online', flushWaiting); return () => removeEventListener('online', flushWaiting) })
  function onChip(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest<HTMLElement>('.cite[data-cid]')
    if (b) location.hash = `#/item/${b.dataset.cid}`
  }
  // frontmatter sources, else the [id N] citations in the body (notes saved from Ask carry none)
  const srcIds = $derived.by(() => {
    if (!open) return []
    if (open.row.sources.length) return open.row.sources
    const ids = new Set<number>()
    for (const m of open.body.matchAll(/\[\s*ids?\s*:?\s*(\d{1,6}(?:\s*[,;&]\s*(?:ids?\s*:?\s*)?\d{1,6})*)\s*\]/gi)) for (const d of m[1].match(/\d{1,6}/g) ?? []) ids.add(+d)
    return [...ids].sort((a, b) => a - b)
  })
  const when = (s: string) => (s ? new Date(s).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '')
  const shown = $derived(cat === 'All' ? mine : mine.filter(n => n.category === cat))
  // a note card's colour: its shelf's place in the category list, five colours round (note.css --np-cd-0..4)
  const tintOf = (c: string) => Math.max(0, cats.filter(x => x !== 'All').indexOf(c)) % 5

  // ── Synthesize a note ──
  const FOUND = 60, FIRST = 12                    // matches listed; ticked at first (one AI call)
  const max = source.synthMax ?? Infinity
  let topic = $state(''), found = $state<Row[]>([]), picked = $state(new Set<number>())
  let finding = $state(false), running = $state(false), synLine = $state(''), synErr = $state('')
  let ctl: AbortController | null = null
  $effect(() => {
    const t = synth
    untrack(() => { if (t !== undefined && t !== topic) { topic = t; seg = 'know'; if (t) find() } })
  })
  async function find() {
    const t = topic.trim()
    if (!t || finding) return
    finding = true; synErr = ''; synLine = ''
    let ids: number[] = []
    try { ids = await source.smart(t) } catch { try { ids = await source.search(t) } catch (e) { synErr = (e as Error).message } }
    found = ids.map(i => phone.byId.get(i)).filter((r): r is Row => !!r && r.id > 0).slice(0, FOUND)
    picked = new Set(found.slice(0, FIRST).map(r => r.id))
    if (!found.length && !synErr) synErr = 'Nothing in the library matches that topic.'
    finding = false
  }
  function tick(id: number, on: boolean) { const p = new Set(picked); if (on) p.add(id); else p.delete(id); picked = p }
  const n = $derived(picked.size)
  const over = $derived(n > max)
  async function runSynth() {
    if (!source.synthesize || !n || running) return
    running = true; synErr = ''; synLine = ''
    ctl = new AbortController()
    try {
      const r = await source.synthesize(topic, found.filter(x => picked.has(x.id)).map(x => x.id), l => (synLine = l), ctl.signal)
      await loadLists()
      if (r.file) location.hash = `#/notes/${encodeURIComponent(r.file)}`
      else found = []
    } catch (e) { synErr = (e as Error).name === 'AbortError' ? 'Stopped.' : (e as Error).message } finally { running = false; ctl = null }
  }
</script>

<div class="m-pad">
  {#if open}
    <h3 class="m-note-ttl">{open.row.title}</h3>
    <div class="m-it-meta"><span>{open.row.kind}</span><span>{srcIds.length} sources</span><span>{when(open.row.updated)}</span></div>
    <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
    <MBox><div class="m-rep" onclick={onChip}>{@html mdHTML(open.body)}</div></MBox>
    {#if srcIds.length}
      <div class="m-acts"><MButton aria-expanded={showSrc} onclick={() => (showSrc = !showSrc)}>{showSrc ? 'Hide' : 'Show'} cited sources</MButton></div>
      {#if showSrc}
        <div class="m-rel">
          {#each srcIds.map(id => phone.byId.get(id)).filter(r => !!r) as r (r.id)}
            <button type="button" onclick={() => (location.hash = `#/item/${r.id}`)}>{#if r.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{/if}<span>{r.title || 'No.' + r.id}</span></button>
          {/each}
        </div>
      {/if}
    {/if}
    <div class="m-acts"><MButton onclick={() => open && toObsidian(open.file, noteText(open.meta, open.body))}>Open in Obsidian</MButton></div>
    {#if obsNote}<MHint>{obsNote}</MHint>{/if}
  {:else if myFile}
    {#if my && my.file === myFile}
      <NoteEditor file={my.file} bind:title bind:category={myCat} categories={cats} {body} {stamps} {revision} updated={my.updated}
        {status} {savedAt} bind:focusTitle onbody={b => { body = b; edited() }} onstamps={setStamps} onedit={edited}
        onvoice={addVoice} onqueued={countWaiting} onobsidian={obsidianNote} ondelete={del} />
      {#if obsNote}<MHint>{obsNote}</MHint>{/if}
      {#if waiting}<MHint>{waiting} recording{waiting > 1 ? 's' : ''} waiting for a signal.</MHint>{/if}
    {:else if err}
      <div class="m-err" style="margin:0">{err}</div>
    {:else}
      <div class="m-empty">Loading…</div>
    {/if}
  {:else}
    <div class="m-segrow">
      <div class="m-seg" role="group" aria-label="Notes sections">
        <button type="button" aria-pressed={seg === 'mine'} onclick={() => (seg = 'mine')}>My notes</button>
        <button type="button" aria-pressed={seg === 'know'} onclick={() => (seg = 'know')}>Knowledge</button>
      </div>
      <!-- See my knowledge graph: an Obsidian gem beside the two tabs -->
      <button type="button" class="m-obs" aria-label="See my knowledge graph in Obsidian" title="See my knowledge graph in Obsidian" onclick={seeGraph}>
        <ObsidianIcon />
      </button>
    </div>
    {#if err}<div class="m-err" style="margin:0">{err}</div>{/if}
    {#if graphNote}<MHint>{graphNote}</MHint>{/if}
    {#if seg === 'know'}
      {#if source.synthesize}
        <MBox class="m-syn">
          <span class="m-lbl">Synthesize a note</span>
          <form class="m-row" onsubmit={e => { e.preventDefault(); find() }}><label class="m-fld" style="flex:1"><span class="m-pr">T</span><input bind:value={topic} placeholder="Topic, e.g. knee prehab" enterkeyhint="search" /></label><MButton size="sm" type="submit" disabled={!topic.trim() || finding || running}>{finding ? '…' : 'Find'}</MButton></form>
          {#if found.length}
            <div class="m-syn-srcs">
              {#each found as r (r.id)}
                <label><input type="checkbox" checked={picked.has(r.id)} onchange={e => tick(r.id, (e.currentTarget as HTMLInputElement).checked)} disabled={running} />{#if r.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span></span>{/if}<span>{r.title || 'No.' + r.id}</span></label>
              {/each}
            </div>
            {#if max !== Infinity}<div class="m-meter" class:over><i style:width="{Math.min(100, (n / max) * 100)}%"></i></div>{/if}
            <div class="m-est"><span>{n} {max !== Infinity ? `of ${max} ` : ''}source{n === 1 ? '' : 's'}</span><span>{over ? (solo ? 'Over the phone limit: waits for a PC' : 'Over the phone limit: the PC writes it') : n ? `${Math.ceil(n / 12)} AI call${Math.ceil(n / 12) > 1 ? 's' : ''}` : ''}</span></div>
            <div class="m-acts">
              {#if running}<MButton onclick={() => ctl?.abort()}>Stop</MButton>{/if}
              <MButton variant="dk" disabled={!n || running} onclick={runSynth}>{running ? 'Writing…' : over ? (solo ? 'Keep for a PC' : 'Queue for the PC') : 'Synthesize'}</MButton>
            </div>
          {/if}
          {#if synLine}<MHint>{synLine}</MHint>{/if}
          {#if synErr}<MHint tone="error">{synErr}</MHint>{/if}
        </MBox>
      {/if}
      <div class="m-row"><span class="m-lbl">Saved notes</span><span class="m-sp"></span><span class="m-lbl">{notes.length}</span></div>
      <div class="m-notes">
        {#each notes as n (n.file)}
          <button type="button" class="m-note" onclick={() => (location.hash = `#/notes/${encodeURIComponent(n.file)}`)}><b>{n.title}</b><small>{n.kind} · {n.sources.length} sources · {when(n.updated)}</small></button>
        {:else}
          <div class="m-empty">No notes yet. Synthesize one above or on the PC.</div>
        {/each}
      </div>
    {:else}
      <div class="m-chips m-wg" style="padding:0">
        {#each ['All', ...cats.filter(c => c !== 'All')] as c (c)}<button type="button" class="m-chip" class:on={cat === c} onclick={() => (cat = c)}>{c}</button>{/each}
      </div>
      <div class="m-row"><span class="m-lbl">My notes</span><span class="m-sp"></span>{#if source.canTranscribe?.()}<MButton size="sm" onclick={() => create(true)}>Record</MButton>{/if}<MButton variant="pri" size="sm" onclick={() => create()}>+ New</MButton></div>
      <div class="np-cards">
        {#each shown as n (n.file)}
          <NoteCard {n} tint={tintOf(n.category)} onopen={() => (location.hash = `#/mynotes/${encodeURIComponent(n.file)}`)} />
        {:else}
          <div class="m-empty">No personal notes here yet.</div>
        {/each}
      </div>
    {/if}
  {/if}
</div>
