<script module lang="ts">
  import { registerLanguageCheck } from '../language-switch.ts'
  import type { Stamp } from '../../lib/note-format'
  import type { MyNote, NoteRow, OpenNote, Row } from '../source/types'
  // a note the screen closed on (another tab) while its save was still going or had failed: the next
  // Notes screen takes it back with its edits instead of the stored copy (plans/07-phone-editor-review.md #1)
  type Left = { my: MyNote; title: string; body: string; category: string; stamps: Stamp[]; stampTouched: boolean; done: Promise<boolean> }
  let left: Left | null = null
  registerLanguageCheck(async () => {
    const kept = left
    return kept && !await kept.done ? 'settings.language.unsavedNote' : null
  })
</script>

<script lang="ts">
  import { captureError } from '../capture-words.ts'
  import { t } from '../../lib/i18n/index.ts'
  import { fmtDate } from '../../lib/i18n/format.ts'
  import { toolText } from '../tools-words.ts'
  import { noteKind } from '../notes-words.ts'
  import ObsidianIcon from '../../components/ui/ObsidianIcon.svelte'
  // 05 Notes (projects/phone-notes-manager): the sheet's floating keys on every page but an open personal note,
  // with the search key (or the Obsidian gem on a Knowledge note) in the sheet's corner (`corner`, rendered by
  // Mobile.svelte). The root: My notes / Knowledge as word tabs, a kicker line (the category picker and the count,
  // or "Saved notes" and the graph gem), note card A or plain Knowledge rows, one raised bar (Synthesize, Record,
  // New note) and a search over both tabs (#/notes-search, notes-find.ts; the whole note on the Drive mirror).
  // Synthesize a note is a page with its own run bar (on the phone up to source.synthMax sources, more are queued
  // for the PC; on the desktop source it is the PC's job); a Knowledge note reads on the paper; My Notes open in
  // the dot-paper editor (plans/07-phone-editor.md). Lists are kept in the phone's copy.
  import type { Snippet } from 'svelte'
  import { onDestroy, onMount, untrack } from 'svelte'
  import { mdHTML } from '../../lib/md'
  import { kv } from '../store'
  import { phone, solo, source } from '../state.svelte'
  import { back, go } from '../shell.svelte'
  import { setMoreFrom } from '../back'
  import { openMoreBox } from '../onboard.svelte'
  import { graphUrl, noteText, obsidianUrl, vaultName } from '../obsidian'
  import { vault as vaultRun } from '../vault/auto.svelte'
  import { openObsidian } from '../native'
  import { appendVoice, flush as flushVoice, queued } from '../voice'
  import { beginLanguageWork, languageWorkChanged } from '../language-switch.ts'
  import { watchKeyboard } from '../keyboard'
  import { Synth } from '../ai/synth'
  import { SYNTH } from '../ai/prompts'
  import { findKnow, findMine, words } from '../notes-find'
  import NoteEditor from './NoteEditor.svelte'
  import NoteCard from '../NoteCard.svelte'
  import ShellIcon from '../ShellIcon.svelte'
  import '../note.css'
  import MHint from '../ui/MHint.svelte'
  import MKey from '../ui/MKey.svelte'
  import MPicker from '../ui/MPicker.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MTextButton from '../ui/MTextButton.svelte'

  let { file, myFile, synth, search = false, corner = $bindable() }: {
    file?: string; myFile?: string; synth?: string; search?: boolean; corner?: Snippet
  } = $props()
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
  const NO_OBS = t('notes.obsidian.missing')
  async function toObsidian(file: string, text: string) {
    const ok = await openObsidian(obsidianUrl(vaultName(source.obsidianVault?.() ?? '', vaultRun.opts.name), file, text, source.obsidianNotes?.() ?? ''))
    obsNote = ok === false ? NO_OBS : t('notes.obsidian.sent')
  }
  // See my knowledge graph: Obsidian on the vault; its graph view is in Obsidian's own menu
  let graphNote = $state('')
  async function seeGraph() {
    const ok = await openObsidian(graphUrl(vaultName(source.obsidianVault?.() ?? '', vaultRun.opts.name)))
    graphNote = ok === false ? NO_OBS
      : t('notes.obsidian.graphHelp')
  }

  async function loadLists() {
    notes = (await kv.get<NoteRow[]>('notes')) ?? []
    mine = (await kv.get<MyNote[]>('mynotes')) ?? []
    // each list on its own: a phone with no PC copy has no Knowledge notes (source.notes() rejects with
    // "library/meta.json is not in the mirror") but its own notes must still show; a failed list keeps its copy
    const [n, m, c] = await Promise.allSettled([source.notes(), source.myNotes(), source.myNoteCategories()])
    if (n.status === 'fulfilled') { notes = n.value.filter(x => x.kind.toLowerCase() !== 'personal'); kv.set('notes', notes) }      // personal notes are the My notes list
    if (m.status === 'fulfilled') { mine = m.value; kv.set('mynotes', m.value) }
    if (c.status === 'fulfilled') cats = c.value
    if (search) void loadTexts()
  }
  onMount(loadLists)

  // ── autosave (desktop notes.svelte.ts, on the phone's source) ──
  let timer = 0, dirty = false, stampTouched = false, version = 0, stampVersion = 0
  let saving: Promise<boolean> | null = null
  function edited() {
    if (!my) return
    dirty = true; version++; languageWorkChanged()
    status = 'pending'
    clearTimeout(timer)
    timer = window.setTimeout(() => { void flush() }, 800)
  }
  function setStamps(s: Stamp[]) { stamps = s; stampTouched = true; stampVersion++; edited() }
  // rename a category on every note in it (spec 2026-11-07 section 3): the open note's pending save goes first,
  // under the old name, and moves with the others
  let catErr = $state('')
  // why Rename is off ('' when on); reads phone.synced so it follows a manifest refresh
  // (plan 09's `(phone.synced, ...)` comma form is stripped of its parentheses by svelte2tsx)
  function renameOff(): string { void phone.synced; return source.renameBlocked?.(toolText) ?? '' }
  async function renameCategory(from: string, to: string) {
    catErr = ''
    if (!source.renameMyNoteCategory || !await flush()) return
    const done = beginLanguageWork()
    try {
      cats = await source.renameMyNoteCategory(from, to)
      if (myCat === from) myCat = to
      if (cat === from) cat = to
      await loadLists()
    } catch (e) { catErr = captureError(e) } finally { done() }
  }
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
      const n = await source.saveMyNote(file, title.trim() ? title : 'Untitled', myCat, body, sendStamps ? stamps : undefined)
      if (my?.file === file) {
        if (version === sentVersion) { dirty = false; status = 'saved'; savedAt = (n.updated || '').slice(11, 19) }
        else status = 'pending'
        if (stampVersion === sentStampVersion) stampTouched = false
        my = n
      }
      loadLists()
      return true
    } catch (e) {
      if (my?.file === file) { err = captureError(e); status = 'error'; dirty = true; if (sendStamps) stampTouched = true }
      return false
    }
  }
  onMount(() => {
    const onHide = () => { void flush() }
    addEventListener('pagehide', onHide)
    return () => removeEventListener('pagehide', onHide)
  })
  const releaseNoteCheck = registerLanguageCheck(async () => {
    if (!my || !(dirty || saving)) return null
    return await flush() ? null : 'settings.language.unsavedNote'
  })
  // leaving the Notes screen saves the open note; until that save lands its edits are kept in `left`
  onDestroy(() => {
    if (my && (dirty || saving)) {
      const kept: Left = { my: $state.snapshot(my), title, body, category: myCat, stamps: $state.snapshot(stamps), stampTouched, done: flush() }
      left = kept; languageWorkChanged()
      void kept.done.then(ok => { if (ok && left === kept) { left = null; languageWorkChanged() } })
    }
    releaseNoteCheck()
  })
  if (left) {
    // after the last screen's save is done (landed or failed), this one saves the edits again
    const k = left; left = null; languageWorkChanged()
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
      if (f) { seg = 'know'; open = null; err = ''; source.note(f).then(n => (open = n)).catch(e => (err = captureError(e))) }
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
      if (request === opening && my) err = t('notes.save.unsaved', { title: title || t('notes.editor.untitled'), detail: err || t('notes.save.failed') })
      return
    }
    if (request !== opening) return
    if (!f) { my = null; return }
    try {
      const n = await source.myNote(f)
      if (request !== opening) return
      // a brand-new note is stored as "Untitled" with no text: show the field empty (grey placeholder) instead
      my = n; title = n.title === 'Untitled' && !(n.body ?? '').trim() ? '' : n.title; body = n.body ?? ''; myCat = n.category; stamps = n.stamps ?? []
      dirty = false; stampTouched = false; status = 'saved'; savedAt = (n.updated || '').slice(11, 19); revision++
    } catch (e) { if (request === opening) err = captureError(e) }
  }

  async function create(record = false) {
    const done = beginLanguageWork()
    try {
      const d = new Date(), p = (v: number) => String(v).padStart(2, '0')
      const title = record ? `Note ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}` : ''
      const n = await source.createMyNote(title, cat === 'All' ? '' : cat)
      await loadLists()
      focusTitle = !record
      if (record) sessionStorage.setItem('bp-record-note', n.file)
      location.hash = `#/mynotes/${encodeURIComponent(n.file)}`
    } catch (e) { err = captureError(e) } finally { done() }
  }
  async function del() {
    if (!my) return
    if (!await flush()) return
    const file = my.file
    const done = beginLanguageWork()
    try {
      if (source.deleteMyNote) { await source.deleteMyNote(file); my = null }
      else err = t('notes.deletePc')
      loadLists()
      location.hash = '#/mynotes'
    } catch (e) { err = captureError(e) } finally { done() }
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
    const done = beginLanguageWork()
    try {
      await flushVoice(
        b => source.transcribe!(b),
        async (file, text) => { const n = await source.myNote(file); await source.saveMyNote(n.file, n.title, n.category, appendVoice(n.body ?? '', text)) },
        file => my?.file === file,
      )
      countWaiting(); loadLists()
    } finally { done() }
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
  const when = (s: string) => (s ? fmtDate(s, { day: '2-digit', month: 'short' }, 'en-GB') : '')
  // a note card's colour: its shelf's place in the category list, five colours round (note.css --np-cd-0..4)
  const tintOf = (c: string) => Math.max(0, cats.filter(x => x !== 'All').indexOf(c)) % 5

  // ── search (spec section 3): the words filter the open tab as they are typed, with the kicker's category;
  // #/notes-search is a page of the sheet, so the ✕, Escape, the sheet's Back and Android's Back close it; back on
  // the plain root the words clear, a note opened from the results keeps them ──
  const home = $derived(!file && !myFile && synth === undefined)
  let q = $state('')
  let field: HTMLInputElement | undefined = $state()
  let texts = $state<Record<string, string>>({})       // file to the whole note (the Drive mirror's noteBodies)
  async function loadTexts() {
    if (!source.noteBodies) return
    try { texts = await source.noteBodies() } catch { /* the lists' text stays */ }
  }
  function openSearch() {
    field?.focus({ preventScroll: true })
    go('#/notes-search')
  }
  function closeSearch() {
    if (history.length > 1) back()
    else go('#/notes', true)
  }
  $effect(() => {
    const on = search, root = home
    untrack(() => {
      if (on) void loadTexts()
      else { field?.blur(); if (root) q = '' }
    })
  })
  const terms = $derived(words(q))
  const shown = $derived(findMine(mine, terms, cat, texts))
  const known = $derived(findKnow(notes, terms, texts))
  const count = (k: number) => t('notes.count', { n: k })
  const catOptions: [string, string][] = $derived([['All', t('notes.all')], ...cats.filter(c => c !== 'All').map((c): [string, string] => [c, c])])
  // the sheet's corner key (spec section 1.3): the search on the root, the gem on a loaded Knowledge note
  $effect(() => { corner = keys; return () => { corner = undefined } })
  // the keyboard (keyboard.ts): html.kb drops the inset padding, hides the root's bar, lifts the run bar
  onMount(() => watchKeyboard())

  // ── Synthesize a note ──
  const FOUND = 60, FIRST = 12                    // matches listed; ticked at first (one AI call)
  const max = source.synthMax ?? Infinity
  let topic = $state(''), found = $state<Row[]>([]), picked = $state(new Set<number>())
  let finding = $state(false), running = $state(false), synLine = $state(''), synErr = $state('')
  let noText = $state(new Set<number>())           // found links saved on the phone with nothing to fold yet
  const synthText = new Synth(SYNTH)
  let ctl: AbortController | null = null
  // any synth route selects Knowledge (Back from the new note lands there); a new topic replaces the page's and
  // runs Find; #/synth/ with no topic (the bar's key) keeps the page's topic and found sources
  $effect(() => {
    const t = synth
    untrack(() => {
      if (t === undefined) return
      seg = 'know'
      if (t && t !== topic) { topic = t; find() }
    })
  })
  async function find() {
    const query = topic.trim()
    if (!query || finding) return
    finding = true; synErr = ''; synLine = ''
    let ids: number[] = []
    try { ids = await source.smart(query) } catch { try { ids = await source.search(query) } catch (e) { synErr = t('notes.error.detail', { detail: captureError(e) }) } }
    const hits = ids.map(i => phone.byId.get(i)).filter((r): r is Row => !!r)
    // links saved on the phone (id < 0): a phone with no PC folds them itself (projects/phone-solo-synthesize); a paired
    // phone's synthesis library holds only the PC's items, so there they wait for the PC
    found = (solo ? hits : hits.filter(r => r.id > 0)).slice(0, FOUND)
    noText = new Set(await textless(found))
    picked = new Set(found.filter(r => !noText.has(r.id)).slice(0, FIRST).map(r => r.id))
    const local = hits.length - found.length
    if (!found.length && !synErr) synErr = local
      ? t('notes.synthesize.local', { n: local })
      : t('notes.synthesize.none')
    finding = false
  }
  // a link saved on this phone with nothing to fold yet: no caption (its page not read: the description is still the
  // link), no AI description, no note. The mirror makes the same call when it folds (ai/synth.ts parts)
  async function textless(rows: Row[]): Promise<number[]> {
    const pc = rows.filter(r => r.id > 0).map(r => r.id)
    const out = pc.length && source.synthTextless ? await source.synthTextless(pc).catch(() => []) : []
    for (const r of rows.filter(x => x.id < 0)) {
      const f = await source.item(r.id).catch(() => null)
      if (!f || !synthText.hasText(f)) out.push(r.id)
    }
    return out
  }
  function tick(id: number, on: boolean) { const p = new Set(picked); if (on) p.add(id); else p.delete(id); picked = p }
  const n = $derived(picked.size)
  const over = $derived(n > max)
  // a phone with no PC writes the note with its own key: without one the run key opens More's key box (as the mic
  // does) and More's Back returns here. Read when the markup renders, so a key added under More counts on the next render
  const noKey = () => solo && !source.ai?.()
  function addKey() { setMoreFrom(location.hash); void openMoreBox('m-ai') }
  async function runSynth() {
    if (!source.synthesize || !n || running || (over && solo) || noKey()) return
    const done = beginLanguageWork()
    running = true; synErr = ''; synLine = ''
    ctl = new AbortController()
    try {
      const r = await source.synthesize(topic, found.filter(x => picked.has(x.id)).map(x => x.id), l => (synLine = l), ctl.signal, toolText)
      await loadLists()
      if (r.file) location.hash = `#/notes/${encodeURIComponent(r.file)}`
      else found = []
    } catch (e) { synErr = (e as Error).name === 'AbortError' ? t('notes.synthesize.stopped') : t('notes.error.detail', { detail: captureError(e) }) } finally { running = false; ctl = null; done() }
  }
</script>

{#snippet keys()}
  {#if file && open}
    <MKey aria-label={t('notes.openObsidian')} title={t('notes.openObsidian')} onclick={() => open && toObsidian(open.file, noteText(open.meta, open.body))}><ObsidianIcon /></MKey>
  {:else if home}
    <MKey class="m-nt-gem" aria-label={t('notes.graph')} title={t('notes.graph')} onclick={seeGraph}><ObsidianIcon /></MKey>
    <div class="m-find" class:open={search}>
      <button type="button" class="m-find-key" aria-label={t('notes.search')} title={t('notes.search')} onclick={() => (search ? field?.focus() : openSearch())}><ShellIcon name="search" /></button>
      <input bind:this={field} bind:value={q} class="m-find-in" type="search" placeholder={t('notes.searchPlaceholder')} aria-label={t('notes.search')}
        tabindex={search ? 0 : -1} onkeydown={e => { if (e.key === 'Escape') closeSearch(); else if (e.key === 'Enter') field?.blur() }}
        enterkeyhint="search" autocomplete="off" />
      {#if search}<button type="button" class="m-find-x" aria-label={t('notes.closeSearch')} onclick={closeSearch}>✕</button>{/if}
    </div>
  {/if}
{/snippet}

{#snippet empty(heading: string, text: string, other: number, to: 'mine' | 'know')}
  <div class="m-nt-empty">
    <div class="m-nt-rug" aria-hidden="true"><span class="m-nt-sheet"><u></u><i></i><i></i><i></i><i></i></span></div>
    <h4>{heading}</h4>
    <p>{text}</p>
    {#if other}<MKey size="mid" wide tone="add" onclick={() => (seg = to)}>{t('notes.otherTab', { n: other, tab: to === 'know' ? t('notes.knowledge') : t('notes.mine') })}</MKey>{/if}
  </div>
{/snippet}

{#if myFile}
  <div class="m-pad np-bleed">
    {#if my && my.file === myFile}
      <NoteEditor file={my.file} bind:title bind:category={myCat} categories={cats} {body} {stamps} {revision} updated={my.updated}
        {status} {savedAt} bind:focusTitle onbody={b => { body = b; edited() }} onstamps={setStamps} onedit={edited}
        onvoice={addVoice} onqueued={countWaiting} onobsidian={obsidianNote} ondelete={del} onback={() => back()}
        count={c => mine.filter(n => n.category === c).length} renameBlocked={renameOff()}
        onrename={renameCategory} />
      {#if catErr}<MHint tone="error">{t('notes.error.detail', { detail: catErr })}</MHint>{/if}
      {#if obsNote}<MHint>{obsNote}</MHint>{/if}
      {#if waiting}<MHint>{t('notes.waiting', { n: waiting })}</MHint>{/if}
    {:else if err}
      <div class="m-err" style="margin:0">{t('notes.error.detail', { detail: err })}</div>
    {:else}
      <div class="m-empty">{t('notes.loading')}</div>
    {/if}
  </div>
{:else if file}
  <div class="m-nt m-nt-read">
    {#if open}
      <div class="m-nt-kick"><i class="m-nt-dot"></i><span class="m-nt-meta">{noteKind(open.row.kind)} · {t('notes.sources', { n: srcIds.length })} · {when(open.row.updated)}</span></div>
      <h3 class="m-nt-title">{open.row.title}</h3>
      {#if obsNote}<MHint>{obsNote}</MHint>{/if}
      <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
      <div class="m-rep m-nt-text" onclick={onChip}>{@html mdHTML(open.body)}</div>
      {#if srcIds.length}
        <MTextButton class="m-nt-cited" aria-expanded={showSrc} onclick={() => (showSrc = !showSrc)}>{t(showSrc ? 'notes.hideCited' : 'notes.showCited')}</MTextButton>
        {#if showSrc}
          <div class="m-rel">
            {#each srcIds.map(id => phone.byId.get(id)).filter(r => !!r) as r (r.id)}
              <button type="button" onclick={() => (location.hash = `#/item/${r.id}`)}>{#if r.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{/if}<span>{r.title || 'No.' + r.id}</span></button>
            {/each}
          </div>
        {/if}
      {/if}
    {:else if err}
      <div class="m-err">{t('notes.error.detail', { detail: err })}</div>
    {:else}
      <div class="m-empty">{t('notes.loading')}</div>
    {/if}
  </div>
{:else if synth !== undefined}
  <div class="m-nt">
    <h3 class="m-nt-title">{t('notes.synthesize.title')}</h3>
    <form class="m-nt-topicrow" onsubmit={e => { e.preventDefault(); find() }}>
      <label class="m-nt-topic"><span class="m-pr">&gt;</span><input bind:value={topic} aria-label={t('notes.synthesize.topic')} placeholder={t('notes.synthesize.topicPlaceholder')} enterkeyhint="search" /></label>
      <MKey size="mid" wide type="submit" aria-label={t('notes.synthesize.find')} disabled={!topic.trim() || finding || running}>{finding ? '…' : t('notes.synthesize.find')}</MKey>
    </form>
    {#if synErr}<MHint tone="error">{synErr}</MHint>{/if}
    {#if synLine && !running}<MHint>{synLine}</MHint>{/if}
    {#if noKey()}<MHint>{t('notes.synthesize.noKey')}</MHint>{/if}
    {#if found.length}
      <div class="m-nt-kick">{t('notes.synthesize.found', { n: found.length })}{noText.size ? t('notes.synthesize.without', { n: noText.size }) : ''}</div>
      {#if noText.size}<MHint>{t('notes.synthesize.textless', { n: noText.size })}</MHint>{/if}
      <div class="m-nt-found">
        {#each found as r (r.id)}
          <label class="m-nt-src" class:m-nt-notext={noText.has(r.id)}><input type="checkbox" checked={picked.has(r.id)} onchange={e => tick(r.id, (e.currentTarget as HTMLInputElement).checked)} disabled={running || noText.has(r.id)} />{#if r.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span class="m-nt-tint"></span>{/if}<span>{r.title || (r.id < 0 ? r.url : 'No.' + r.id)}{#if noText.has(r.id)}<small>{t('notes.synthesize.noText')}</small>{/if}</span></label>
        {/each}
      </div>
      <div class="m-nt-foot m-nt-runfoot">
        <div class="m-nt-bar m-nt-run">
          <div class="m-nt-rtop">
            <span>{running && synLine ? synLine : t(max !== Infinity && n >= max * 0.75 ? 'notes.synthesize.ofSources' : 'notes.synthesize.sources', { n, max })}</span>
            {#if !running && !over && n && !noKey()}<span>{t('notes.synthesize.calls', { n: Math.ceil(n / 12) })}</span>{/if}
          </div>
          {#if max !== Infinity && n >= max * 0.75}<div class="m-meter" class:over><i style:width="{Math.min(100, (n / max) * 100)}%"></i></div>{/if}
          {#if over}<div class="m-nt-over">{solo ? t('notes.synthesize.limit', { max, n: n - max }) : t('notes.synthesize.pcLimit')}</div>{/if}
          <div class="m-nt-keys">
            {#if running}<MKey size="mid" tone="dark" aria-label={t('notes.synthesize.stop')} title={t('notes.synthesize.stop')} onclick={() => ctl?.abort()}><ShellIcon name="stop" /></MKey>{/if}
            {#if noKey()}
              <MKey size="mid" wide tone="add" aria-label={t('notes.synthesize.addKey')} title={t('notes.synthesize.addKey')} onclick={addKey}>{t('notes.synthesize.addKey')}</MKey>
            {:else}
              <MKey size="mid" wide tone="add" disabled={!n || running || (over && solo)} onclick={runSynth}>{running ? t('notes.synthesize.writing') : over && !solo ? t('notes.synthesize.queue') : t('notes.synthesize.go')}</MKey>
            {/if}
          </div>
        </div>
      </div>
    {/if}
  </div>
{:else}
  <div class="m-nt">
    <MSeg look="tabs" label={t('notes.sections')} options={[['mine', t('notes.mine')], ['know', t('notes.knowledge')]]} value={seg} onchange={v => (seg = v === 'know' ? 'know' : 'mine')} />
    {#if err}<div class="m-err">{t('notes.error.detail', { detail: err })}</div>{/if}
    {#if graphNote}<MHint>{graphNote}</MHint>{/if}
    {#if seg === 'mine'}
      {#if mine.length || cat !== 'All'}
        <div class="m-nt-kick">
          <MPicker label={t('notes.category')} class="m-nt-cat" options={catOptions} bind:value={cat}>
            <span class="m-nt-catpart"><i class="m-nt-dot" style:background={cat === 'All' ? 'var(--wg-dim)' : `var(--np-cd-${tintOf(cat)})`}></i><span class="m-nt-catname">{cat === 'All' ? t('notes.all') : cat}</span><ShellIcon name="down" /></span>
          </MPicker>
          <span class="m-sp"></span>
          <span>{count(shown.length)}</span>
        </div>
      {/if}
      {#if shown.length}
        <div class="np-cards">
          {#each shown as n (n.file)}
            <NoteCard {n} tint={tintOf(n.category)} onopen={() => (location.hash = `#/mynotes/${encodeURIComponent(n.file)}`)} />
          {/each}
        </div>
      {:else if terms.length}
        {@render empty(t('notes.noMatch'), t('notes.mineNoMatch', { query: q.trim() }), known.length, 'know')}
      {:else if cat !== 'All'}
        {@render empty(t('notes.categoryEmpty', { category: cat }), t('notes.pickCategory'), 0, 'mine')}
      {:else}
        {@render empty(t('notes.empty'), source.canTranscribe?.() ? t('notes.firstVoice') : t('notes.first'), 0, 'mine')}
      {/if}
    {:else}
      <div class="m-nt-kick">
        <span>{t('notes.savedCount', { n: known.length })}</span>
      </div>
      {#if known.length}
        <div class="m-nt-rows">
          {#each known as n (n.file)}
            <button type="button" class="m-nt-row" onclick={() => (location.hash = `#/notes/${encodeURIComponent(n.file)}`)}><b>{n.title}</b><small>{noteKind(n.kind)} · {t('notes.sources', { n: n.sources.length })} · {when(n.updated)}</small></button>
          {/each}
        </div>
      {:else if terms.length}
        {@render empty(t('notes.noMatch'), t('notes.knowledgeNoMatch', { query: q.trim() }), shown.length, 'mine')}
      {:else}
        {@render empty(t('notes.knowledgeEmpty'), t('notes.firstSynthesis'), 0, 'know')}
      {/if}
    {/if}
    <div class="m-nt-foot">
      <div class="m-nt-bar">
        {#if source.synthesize}<MKey size="mid" wide aria-label={t('notes.synthesize.title')} title={t('notes.synthesize.title')} onclick={() => go('#/synth/')}><ShellIcon name="tools" /><span>{t('notes.synthesize.go')}</span></MKey>{/if}
        <span class="m-sp"></span>
        {#if source.canTranscribe}
          <!-- without an OpenAI key the mic stays, as a reminder that voice notes exist: it opens the key box under More -->
          <MKey size="mid" aria-label={t('notes.record')} title={source.canTranscribe() ? t('notes.record') : t('notes.recordKey')}
            onclick={() => { if (source.canTranscribe?.()) void create(true); else { setMoreFrom('#/notes'); openMoreBox('m-ai') } }}><ShellIcon name="mic" /></MKey>
        {/if}
        <MKey size="mid" tone="add" aria-label={t('notes.new')} title={t('notes.new')} onclick={() => create()}><ShellIcon name="plus" /></MKey>
      </div>
    </div>
  </div>
{/if}
