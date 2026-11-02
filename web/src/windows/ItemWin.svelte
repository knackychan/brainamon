<script lang="ts">
  // The item window (V6 openItem; Qt ui/item_detail_window.py), one scrolling page: header (title,
  // No., type, source, saved date, section jumps); a sticky left side with the big card and the grouped
  // actions; the main column with the metadata, Description beside the AI description, My notes, then
  // the folding Report, Frames and Related sections.
  // Save = PATCH plus the pending thumbnail upload; Delete asks first. The report and the related items
  // load when their section comes near (or is jumped to). tab 1 / 2 opens on Report / Related.
  import { onMount, tick, untrack } from 'svelte'
  import Px from '../lib/Px.svelte'
  import { api, ApiError } from '../lib/api'
  import { act, type CardAct } from '../lib/cardmenu'
  import { attachFree } from '../lib/cards/hand'
  import { cardMarkup, dateOf, srcLabel, titleOf } from '../lib/cards/card'
  import { themeSlot } from '../lib/cards/theme'
  import { deleteItems, openItem, pickFile } from '../lib/edit-commands'
  import { jobBusy, jobBusyMsg, startJob } from '../lib/jobs'
  import { isVid, lib, replaceRow, toggleFav, type Row, thumbSrc } from '../lib/library.svelte'
  import { attachItems } from '../lib/attach'
  import { mdHTML } from '../lib/md'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { id, tab = 0, close }: { id: number; tab?: number; close: () => void } = $props()

  const TYPES = ['Reel', 'Video', 'Post', 'Link', 'Recipe', 'Tutorial', 'Other']
  interface Full {
    id: number; url: string; description: string; short_desc: string; creator: string; type: string; category: string
    tags: string; notes: string; ai_desc: string; created: number
    files: { thumb: boolean; report: boolean; transcript: boolean; frames: number; frame_names: string[]; video: boolean }
  }
  let it = $state<Full | null>(null)
  let f = $state({ description: '', short_desc: '', creator: '', type: 'Reel', category: '', url: '', tags: '', notes: '' })
  let err = $state<{ field: string; msg: string } | null>(null)
  let saving = $state(false)
  let pendingThumb: File | null = null
  let thumbPreview = $state('')
  let report = $state<string | null>(null)
  let related = $state<(Row & { score: number })[] | 'needs' | null>(null)
  let cardBox: HTMLDivElement | undefined = $state()
  let body: HTMLDivElement | undefined = $state()
  let secReport: HTMLDetailsElement | undefined = $state()
  let secFrames: HTMLDetailsElement | undefined = $state()
  let secRel: HTMLDetailsElement | undefined = $state()
  let wantReport = $state(false), wantRel = $state(false)
  let pending: HTMLDetailsElement | undefined

  const row = $derived(lib.byId.get(id))
  const cats = $derived(lib.cats.map(c => c.name))

  async function load() {
    try {
      const r = await api.get<Full>(`/api/items/${id}`)
      it = r
      f = { description: r.description || '', short_desc: r.short_desc || '', creator: r.creator || '', type: r.type || 'Reel',
        category: r.category || 'INTERESTING', url: r.url || '', tags: r.tags || '', notes: r.notes || '' }
      await tick()
      // opened on a section (View analysis report): land there, and again as the report and related items
      // arrive and grow the page (before they do, the page can be too short to scroll that far)
      pending = tab === 1 ? secReport : tab === 2 ? secRel : undefined
      jump(pending, false)
      setTimeout(() => (pending = undefined), 2000)
    } catch (e) { toast(`Could not open No.${id}: ${(e as Error).message}`, 'w'); close() }
  }
  onMount(load)

  // the card with its own HandCard (normal idle sway); redrawn when the row changes
  $effect(() => {
    const r = row
    if (!r || !cardBox) return
    cardBox.innerHTML = cardMarkup(r, lib.variant, lib.rankOf.get(r.id) ?? r.id, 0, lib.rows.length)
    const s = cardBox.querySelector<HTMLElement>('.slot')
    if (!s) return
    themeSlot(s, r)
    if (thumbPreview) s.querySelector<HTMLImageElement>('img.art')?.setAttribute('src', thumbPreview)
    s.style.cursor = 'pointer'
    return attachFree(s, tapCard)
  })

  // a click on the card opens the item's URL by the same path as the Open URL button
  function tapCard() {
    if (!lib.byId.get(id)?.url?.trim()) { toast('No URL for this item', 'w'); return }
    open('url')
  }

  // lazy sections: the report and the related items load once their section is within 300 px of view
  $effect(() => {
    if (!body) return
    const io = new IntersectionObserver(es => {
      for (const e of es) {
        if (!e.isIntersecting) continue
        if (e.target === secReport) wantReport = true
        if (e.target === secRel) wantRel = true
        io.unobserve(e.target)
      }
    }, { root: body, rootMargin: '300px 0px' })
    for (const s of [secReport, secRel]) if (s) io.observe(s)
    return () => io.disconnect()
  })

  // each loads once; untracked, since api.get counts requests in state (net.n) and would loop the effect
  let askedReport = false, askedRel = false
  const settle = () => tick().then(() => pending?.scrollIntoView({ block: 'start', behavior: 'instant' }))
  $effect(() => {
    const r = wantReport && !!it?.files.report, rel = wantRel
    untrack(() => {
      if (r && !askedReport) {
        askedReport = true
        fetch(`/files/items/${id}/report.md`).then(r => (r.ok ? r.text() : '')).then(t => (report = t)).catch(() => (report = '')).finally(settle)
      }
      if (rel && !askedRel) {
        askedRel = true
        api.get<any>(`/api/items/${id}/related`).then(r => (related = Array.isArray(r) ? r : 'needs')).catch(() => (related = [])).finally(settle)
      }
    })
  })

  // a section jump: unfold it, load it, scroll it to the top of the page
  function jump(sec: HTMLDetailsElement | undefined, smooth = true) {
    if (!sec) return
    sec.open = true
    if (sec === secReport) wantReport = true
    if (sec === secRel) wantRel = true
    sec.scrollIntoView({ block: 'start', behavior: smooth ? 'smooth' : 'instant' })
  }

  async function save() {
    err = null
    const desc = f.description.trim(), url = f.url.trim()
    if (!desc) return fail('description', 'Description is required.')
    if (!url) return fail('url', 'Enter the URL.')
    saving = true
    try {
      let r = await api.patch<Row>(`/api/items/${id}`, { ...f, description: desc, url })
      if (pendingThumb) r = await putThumb(pendingThumb)
      replaceRow(r)
      toast(`Saved No.${id}`)
      close()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) fail('url', 'This URL is already in the library.')
      else err = { field: '', msg: (e as Error).message }
    } finally { saving = false }
  }

  // a field error: show it and focus the field (focus scrolls it into view)
  function fail(field: 'description' | 'url', msg: string) {
    err = { field, msg }
    tick().then(() => document.getElementById(field === 'url' ? 'f-url' : 'f-desc')?.focus())
  }

  async function putThumb(file: File): Promise<Row> {
    const r = await fetch(`/api/items/${id}/thumb`, { method: 'PUT', headers: { 'X-CM': '1' }, body: file })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new ApiError(r.status, j.detail || r.statusText)
    return j as Row
  }

  async function upload() {
    const file = await pickFile('image/*')
    if (!file) return
    pendingThumb = file
    thumbPreview = URL.createObjectURL(file)
    cardBox?.querySelector<HTMLImageElement>('img.art')?.setAttribute('src', thumbPreview)
    toast(`Thumbnail ${file.name} is set when you Save`)
  }

  async function linkVideo() {
    const file = await pickFile('video/*,.mkv,.avi,.m4v')
    if (!file) return
    toast(`Copying ${file.name} into the item folder…`)
    try {
      const r = await fetch(`/api/items/${id}/video?name=${encodeURIComponent(file.name)}`, { method: 'PUT', headers: { 'X-CM': '1' }, body: file })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.detail || r.statusText)
      if (it) it.files.video = true
      toast(`Linked ${file.name} (data/items/${id}/${j.path})`)
    } catch (e) { toast(`Failed to copy the video: ${(e as Error).message}`, 'w') }
  }

  async function open(what: 'url' | 'folder' | 'video' | 'report') {
    try { await api.post('/api/open', { what, id }) } catch (e) { toast((e as Error).message, 'w') }
  }
  const doAct = (a: CardAct) => act(a, id)

  // the copy icon sits in the Report summary: preventDefault keeps the click from folding the section
  let copied = $state(false)
  async function copyReport(e: MouseEvent) {
    e.preventDefault()
    try {
      const t = report ?? await fetch(`/files/items/${id}/report.md`).then(r => (r.ok ? r.text() : ''))
      if (!t) { toast('The report is empty', 'w'); return }
      await navigator.clipboard.writeText(t)
      copied = true
      setTimeout(() => (copied = false), 1500)
      toast('Report copied to the clipboard')
    } catch { toast('Copy is blocked on this page', 'w') }
  }
  async function del() { if (await deleteItems([id])) close() }
  function openRel(rid: number) { close(); openItem(rid) }
  const bad = (k: string) => err?.field === k
  const groups = [{ t: 'Open', s: actOpen }, { t: 'Process', s: actProcess }, { t: 'Media', s: actMedia }, { t: 'To canvas', s: actCanvas }, { t: 'Wiskit', s: actWiskit }]
</script>

<!-- building blocks, placed by the page below -->
{#snippet fDesc()}
  <div class="itf"><Label for="f-desc">Description <b>*</b></Label>
    <textarea class="inp grow" class:bad={bad('description')} id="f-desc" rows="8" bind:value={f.description} data-autofocus></textarea></div>
{/snippet}
{#snippet fNote()}
  <div class="itf"><Label for="f-note">Short note</Label><input class="inp" id="f-note" bind:value={f.short_desc} autocomplete="off" /></div>
{/snippet}
{#snippet fCreator()}
  <div class="itf"><Label for="f-cr">Creator</Label><input class="inp" id="f-cr" bind:value={f.creator} autocomplete="off" /></div>
{/snippet}
{#snippet fType()}
  <div class="itf"><Label for="f-type">Type</Label>
    <select class="inp" id="f-type" bind:value={f.type}>{#each TYPES.includes(f.type) ? TYPES : [...TYPES, f.type] as t (t)}<option>{t}</option>{/each}</select></div>
{/snippet}
{#snippet fCat()}
  <div class="itf"><Label for="f-cat">Category</Label>
    <select class="inp" id="f-cat" bind:value={f.category}>{#each cats.includes(f.category) ? cats : [...cats, f.category] as c (c)}<option>{c}</option>{/each}</select></div>
{/snippet}
{#snippet fUrl()}
  <div class="itf itf-wide"><Label for="f-url">URL <b>*</b></Label><input class="inp" class:bad={bad('url')} id="f-url" bind:value={f.url} autocomplete="off" spellcheck="false" /></div>
{/snippet}
{#snippet fTags()}
  <div class="itf itf-wide"><Label for="f-tags">Tags</Label><input class="inp" id="f-tags" bind:value={f.tags} placeholder="comma, separated" autocomplete="off" /></div>
{/snippet}
{#snippet fMine()}
  <div class="itf"><Label for="f-mine">My notes</Label><textarea class="inp mine" id="f-mine" rows="3" bind:value={f.notes}></textarea></div>
{/snippet}
{#snippet fAi()}
  <div class="itf"><Label as="span">AI description <i class="itv-ro">read only</i></Label>
    <p class="aibox">{it?.ai_desc || 'Not described yet. Run Describe (Process, on the left), or from the Process menu.'}</p></div>
{/snippet}
{#snippet actOpen()}
  <Button variant="pri" onclick={() => open('url')}><Px name="link" />Open URL</Button>
  <Button disabled={!it?.files.video} onclick={() => open('video')}><Px name="film" />Open video</Button>
  <Button disabled={!it?.files.report} onclick={() => open('report')}><Px name="note" />Open report.md</Button>
{/snippet}
{#snippet actProcess()}
  <Button disabled={!row || !isVid(row)} onclick={() => doAct('analyze')}><Px name="film" />Analyze video</Button>
  <Button onclick={() => (jobBusy() ? toast(jobBusyMsg(), 'w') : startJob('describe', { ids: [id], force: true }))}><Px name="core" />Describe</Button>
{/snippet}
{#snippet actMedia()}
  <Button onclick={upload}><Px name="up" />Upload image</Button>
  <Button onclick={() => doAct('thumbOnly')}><Px name="img" />Download thumbnail</Button>
  <Button onclick={() => doAct('download')}><Px name="down" />Download video</Button>
  <Button onclick={linkVideo}><Px name="link" />Link local video</Button>
{/snippet}
{#snippet actCanvas()}
  <Button onclick={() => doAct('canvasThumb')}><Px name="canvas" />Add thumbnail</Button>
  <Button onclick={() => doAct('canvasDesc')}><Px name="note" />Add description</Button>
  <Button disabled={!it?.files.report} onclick={() => doAct('canvasReport')}><Px name="note" />Add report</Button>
{/snippet}
{#snippet actWiskit()}
  <Button onclick={() => { close(); doAct('ask') }}><Px name="core" />Ask about this</Button>
{/snippet}

<WinBody bind:ref={body}>
  <div class="itv">
    <header class="itw-head">
      <div>
        <h2>{row ? titleOf(row) : `No.${id}`}</h2>
        {#if row}<Hint><b>No.{id}</b> · {row.type} · from {srcLabel(row.src)} · saved {dateOf(row.created)}</Hint>{/if}
      </div>
      <nav class="itw-nav" aria-label="Sections">
        <Button size="sm" onclick={() => body?.scrollTo({ top: 0, behavior: 'smooth' })}>Details</Button>
        <Button size="sm" onclick={() => jump(secReport)}>Report</Button>
        {#if it?.files.frames}<Button size="sm" onclick={() => jump(secFrames)}>Frames</Button>{/if}
        <Button size="sm" onclick={() => jump(secRel)}>Related</Button>
      </nav>
    </header>

    <p class="err itv-err" role="alert" hidden={!err}>{err?.msg}</p>
    <form class="itl" novalidate onsubmit={e => { e.preventDefault(); save() }}>
      <aside class="itv-side" aria-label="Item and actions">
        <section class="itv-card c-item" aria-label="Item">
          <div class="itw-card">
            <div bind:this={cardBox}></div>
            <div class="frow">
              <Button size="sm" aria-pressed={!!row?.fav} onclick={() => toggleFav(id)}><Px name="star" />{row?.fav ? 'Favourite' : 'Make favourite'}</Button>
            </div>
          </div>
        </section>
        <div class="itv-acts" role="toolbar" aria-label="Item actions">
          {#each groups as g (g.t)}<div class="ag"><h4>{g.t}</h4><div>{@render g.s()}</div></div>{/each}
        </div>
      </aside>
      <div class="itv-main">
        <section class="itv-card" aria-label="Metadata">
          <div class="itv-grid4">{@render fNote()}{@render fCreator()}{@render fType()}{@render fCat()}{@render fUrl()}{@render fTags()}</div>
        </section>
        <section class="itv-card itx" aria-label="Description">{@render fDesc()}{@render fAi()}</section>
        <section class="itv-card" aria-label="My notes">{@render fMine()}</section>
        {#if it}
          <details class="itv-det itv-sec" open bind:this={secReport} ontoggle={() => secReport?.open && (wantReport = true)}>
            <summary>Report <small>{it.files.report ? 'report.md' : 'not analyzed'}</small>
              {#if it.files.report}<Button size="sm" class="itv-copy" title="Copy the report" aria-label="Copy the report to the clipboard" onclick={copyReport}><Px name={copied ? 'check' : 'copy'} /></Button>{/if}</summary>
            {#if it.files.report}
              <div class="md">{@html report === null ? '<p>Loading…</p>' : mdHTML(report)}</div>
            {:else if it.files.frames}
              <Hint>No report.md yet. The frames are below.</Hint>
            {:else if row}
              <div class="emp"><h3>Not analyzed yet</h3>
                <p>{isVid(row) ? 'Analyze extracts frames with ffmpeg, transcribes the audio and writes report.md.' : 'Only reels and videos can be analyzed.'}</p>
                {#if isVid(row)}<Button variant="pri" onclick={() => doAct('analyze')}>Analyze video</Button>{/if}
              </div>
            {/if}
          </details>

          {#if it.files.frames}
            <details class="itv-det itv-sec" open bind:this={secFrames}>
              <summary>Frames <small>{it.files.frames} · data/items/{id}/frames</small></summary>
              <div class="frames strip">
                {#each it.files.frame_names as name, k (name)}
                  <figure class="frm"><img src={`/files/items/${id}/frames/${name}`} alt={`Frame ${k + 1}`} loading="lazy" /><time>{name.replace(/\.jpg$/, '')}</time>
                    <Button size="sm" aria-label={`Add frame ${k + 1} to the canvas`} onclick={e => attachItems([id], 'frame', e.currentTarget.closest('figure'), name)}>+ canvas</Button></figure>
                {/each}
              </div>
            </details>
          {/if}

          <details class="itv-det itv-sec" open bind:this={secRel} ontoggle={() => secRel?.open && (wantRel = true)}>
            <summary>Related <small>by meaning, click to open</small></summary>
            {#if related === 'needs'}
              <div class="emp"><h3>Not in the search index</h3><p>Related items come from the embedding index. Run Index for search (Process menu) first.</p></div>
            {:else if related === null}
              <Hint>Loading…</Hint>
            {:else}
              <div class="rel">
                {#each related as r (r.id)}
                  <button type="button" class="rel-r" onclick={() => openRel(r.id)}>
                    {#if r.thumb}<img src={thumbSrc(r.id)} alt="" />{:else}<span></span>{/if}
                    <span><b>{titleOf(r)}</b><small>No.{r.id} · {r.creator || 'unknown'} · {r.cat}</small></span>
                    <span class="score" title="Similarity"><i style:--v={r.score.toFixed(2)}></i>{r.score.toFixed(2)}</span>
                  </button>
                {:else}
                  <Hint>Nothing close enough yet.</Hint>
                {/each}
              </div>
            {/if}
          </details>
        {/if}
      </div>
    </form>
  </div>
</WinBody>
<WinFoot>
  {#snippet start()}
  <Button variant="danger" onclick={del}><Px name="trash" />Delete</Button>
  <Button onclick={() => open('folder')}><Px name="folder" />Open item folder</Button>
  {/snippet}<small>Edits save to the library and re-index this item.</small>
  <Button onclick={close}>Close</Button>
  <Button variant="pri" disabled={saving} onclick={save}>Save</Button>
</WinFoot>
