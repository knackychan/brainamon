<script lang="ts">
  import Hint from '../components/ui/Hint.svelte'
  // Add to Brainamon (projects/note-organic-ui/plans/09-add-to-brainamon.md; replaces the Add item form):
  // one capture flow, the same on the phone. Incoming content -> destination (Note or Library) -> that
  // destination's fields -> an optional comment -> Save. The destination can change without losing the
  // content or the comment. A picture is added with the button, a paste or a drop anywhere in the
  // window (mint overlay), one at a time; its text is read on request (the existing digest) and stays
  // editable. A failed save keeps everything as it was. The text fields survive closing the window
  // (localStorage), the picture does not. The writes are in lib/capture-api.ts, the rules in lib/capture.ts.
  import { onMount, tick } from 'svelte'
  import Px from '../lib/Px.svelte'
  import { api, ApiError } from '../lib/api'
  import { appendToNote, linkPreview, listNotes, readFileText, saveItem, saveNewNote } from '../lib/capture-api'
  import {
    checkFiles, destOf, INBOX, joinText, KEPT, label, libraryNote, LIBRARY_TYPES, linkOf, lone, newBody, newDraft, noteText, pageOf, pickNotes,
    picKind, section, siteOf, sourceHelp, STATE_LABEL, suggestNote, titleFor, verdict, type Draft, type NoteRef, type Preview, type Saved,
  } from '../lib/capture'
  import { attachDrop, decodes } from '../lib/dropzone'
  import { startJob } from '../lib/jobs'
  import { hooks, lib, refetch } from '../lib/library.svelte'
  import { openMyNote } from '../lib/notes.svelte'
  import { setWS, toast } from '../lib/ui.svelte'
  import { ACCEPT, fileName } from '../mobile/files'
  import { cleanLink } from '../mobile/links'
  import Button from '../components/ui/Button.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'
  import CaptureFetch from '../components/CaptureFetch.svelte'

  let { close, seed = {} }: { close: () => void; seed?: { text?: string } } = $props()

  const KEEP = 'bp-capture-draft'
  let d = $state<Draft>(newDraft())
  let pickOpen = $state(false)                       // Note: the "which note" dropdown is open
  let q = $state('')
  let notes = $state.raw<NoteRef[]>([])
  let noteCats = $state<string[]>([INBOX])
  let busy = $state(''), err = $state(''), picNote = $state(''), over = $state(false), restored = $state(false)
  let saved = $state<Saved | null>(null)
  let picUrl = $state('')
  let page = $state.raw<Preview | null>(null)        // what the lone link's page says (POST /api/link/preview)
  let head: HTMLElement | undefined = $state()
  let area: HTMLTextAreaElement | undefined = $state()
  let input: HTMLInputElement | undefined = $state()
  let photos: HTMLInputElement | undefined = $state()
  let ready = $state(false)

  const dest = $derived(destOf(d))
  const link = $derived(linkOf(d.text))
  const known = $derived(link ? lib.rows.find(r => r.url === link)?.id : undefined)
  const v = $derived(verdict(d, { thumb: true, known }))
  const suggested = $derived(suggestNote(d.text, notes))
  const shown = $derived(pickNotes(notes, q, suggested))
  const target = $derived(notes.find(n => n.file === d.target))
  const kind = $derived(d.pic ? (picKind(d.pic) === 'image' ? 'Picture' : 'File') : lone(d.text) ? 'Link' : 'Text')
  const cats = $derived(lib.cats.map(c => c.name))
  const noteCategories = $derived([...new Set([INBOX, ...noteCats, ...(d.category ? [d.category] : [])])])
  const alone = $derived(lone(d.text))
  const info = $derived(pageOf(d, page))
  // the page is asked for 400 ms after the box becomes one link; a failure or a slow page shows no card
  $effect(() => {
    const u = alone
    if (!u || saved || page?.asked === u) return
    const t = setTimeout(() => { linkPreview(u).then(p => { if (lone(d.text) === u) page = p }).catch(() => {}) }, 400)
    return () => clearTimeout(t)
  })

  // ── the text fields survive closing the window ────────────────────────────
  $effect(() => {
    const s = $state.snapshot(d) as Draft
    if (!ready || saved) return
    try {
      if (!s.text.trim() && !s.comment.trim()) localStorage.removeItem(KEEP)
      else localStorage.setItem(KEEP, JSON.stringify({ text: s.text, comment: s.comment, dest: s.dest, target: s.target, title: s.title, category: s.category, collection: s.collection, type: s.type, tags: s.tags, made: s.made }))
    } catch { /* private window or no storage: the draft just does not survive */ }
  })
  const forget = () => { try { localStorage.removeItem(KEEP) } catch { /* nothing kept */ } }

  $effect(() => {
    const b = d.pic && picKind(d.pic) === 'image' ? d.pic.blob : null
    if (!b) { picUrl = ''; return }
    const u = URL.createObjectURL(b)
    picUrl = u
    return () => URL.revokeObjectURL(u)
  })

  onMount(() => {
    listNotes().then(l => { notes = l }).catch(() => { /* the picker stays empty: New note still works */ })
    api.get<{ categories: string[] }>('/api/my-notes/categories').then(r => { noteCats = r.categories }).catch(() => {})
    try {
      const kept = JSON.parse(localStorage.getItem(KEEP) || 'null')
      if (kept && typeof kept.text === 'string') { Object.assign(d, kept); restored = true }
    } catch { /* unreadable: start empty */ }
    // what Wiskit's panel sent joins an unsaved draft after its text, never over it
    if (seed.text) d.text = joinText(d.text, seed.text)
    // best effort: the clipboard can be refused (no permission, not focused); then the box stays empty
    else if (!d.text) navigator.clipboard?.readText().then(t => { const u = cleanLink(t); if (u && !d.text) d.text = u }).catch(() => {})
    ready = true
    return attachDrop({ files: takeFiles, over: o => (over = o && !saved) })   // no overlay over the result view
  })

  // the overlay sits on the page, not inside the window (a transformed frame would clip a fixed child)
  function toBody(node: HTMLElement) { document.body.appendChild(node); return { destroy() { node.remove() } } }

  // ── a picture or file ─────────────────────────────────────────────────────
  async function takeFiles(files: File[]) {
    if (!files.length || saved) return
    const c = checkFiles(files)
    if (!c.ok) { err = c.msg; return }
    const f = files[0]
    if (c.kind === 'image' && !(await decodes(f))) { err = 'This image could not be opened. Try a PNG, JPEG, WebP or GIF image.' + KEPT; return }
    err = ''
    d.pic = { name: fileName(f.name, f.type), type: f.type, blob: new File([f], fileName(f.name, f.type), { type: f.type }) }
    d.read = ''
    picNote = `${d.pic.name} added to this capture.`
    if (c.kind !== 'image') await read('digest')             // a PDF or text file is read at once (no AI), as on the phone
  }
  function chosen(e: Event & { currentTarget: HTMLInputElement }) {
    const f = [...(e.currentTarget.files ?? [])]
    e.currentTarget.value = ''
    takeFiles(f)
  }
  function pasted(e: ClipboardEvent) {
    const f = [...(e.clipboardData?.files ?? [])]
    if (f.length) { e.preventDefault(); takeFiles(f) }
  }
  async function pasteClipboard() {
    try { const t = await navigator.clipboard.readText(); d.text = joinText(d.text, t); err = '' }
    catch { err = 'Clipboard access is unavailable. Click the content box and paste there.'; area?.focus() }
  }
  function removePic() { d.pic = null; d.read = ''; picNote = ''; err = '' }

  async function read(how: 'digest' | 'describe') {
    const p = d.pic
    if (!p || busy) return
    busy = picKind(p) !== 'image' ? `Reading ${p.name}…` : how === 'digest' ? 'Reading the text in the picture…' : 'Describing the picture…'
    err = ''
    try {
      const text = await readFileText(p.blob as File, how)
      if (d.pic !== p) return                               // the picture changed while it was reading
      d.text = joinText(d.text, text)
      d.read = how
      picNote = 'Text added to the box. Review it before saving.'
    } catch (e) { err = (e as Error).message + KEPT } finally { busy = '' }
  }

  // ── Save ────────────────────────────────────────────────────────────────────
  async function saveNote(s: Draft): Promise<Saved> {
    const p = pageOf(s, page)                               // the card the user saw, for this exact link
    if (s.target) {
      const m = await appendToNote(s.target, label(s), noteText(s, p))
      return { state: 'synced', title: 'Added to your note', detail: 'Saved. The note changed only at its end.', meta: `${m.title} · appended`, page: section(s, undefined, p), file: m.file }
    }
    const m = await saveNewNote(titleFor(s, p), newBody(s, p), s.made, file => { d.made = file }, s.category || INBOX)
    return { state: 'synced', title: 'Saved to a new note', detail: 'Saved.', meta: `My Notes / ${s.category || INBOX}`, page: `${m.title}\n\n${newBody(s, p).trimEnd()}`, file: m.file }
  }

  async function saveLibrary(s: Draft): Promise<Saved> {
    const { row, thumb } = await saveItem(s)
    await refetch([row.id])
    if (!thumb) toast('The item was added, but the thumbnail could not be saved', 'w')
    const detail = s.pic ? 'Saved with the picture as its thumbnail.' : row.fetching ? '' : 'Saved. Another job is running: fetch its thumbnail from the card later.'
    const meta = `Library${s.collection ? ' / ' + s.collection : ''}${s.type ? ' · ' + s.type : ''}${s.tags.trim() ? ' · ' + s.tags.trim() : ''} · No. ${row.id}`
    const note = picKind(s.pic) === 'image' ? s.comment.trim() : libraryNote(s)
    return { state: 'synced', title: 'Saved as a Library item', detail, meta, page: `${linkOf(s.text)}${note ? '\n\n' + note : ''}`, itemId: row.id, fetching: row.fetching }
  }

  async function save() {
    if (!v.ok || busy || saved) return
    busy = 'Saving…'
    err = ''
    const s = $state.snapshot(d) as Draft
    try {
      saved = destOf(s) === 'library' ? await saveLibrary(s) : await saveNote(s)
      forget()
      listNotes().then(l => { notes = l }).catch(() => {})
      await tick()
      head?.focus()
    } catch (e) { err = (e instanceof ApiError && e.status === 409 ? e.message : `Not saved: ${(e as Error).message}.`) + KEPT } finally { busy = '' }
  }

  function fresh() {
    d = newDraft()
    pickOpen = false; q = ''; err = ''; picNote = ''; saved = null; restored = false; page = null
    tick().then(() => area?.focus())
  }
  function discard() { forget(); fresh() }
  function openNote(file: string) { close(); setWS('notes'); openMyNote(file) }
  function openCard(id: number) { close(); hooks.openItem?.(id) }
</script>

<WinBody class={['cap', { 'cap-editing': !saved }]}>
  {#if saved}
    {@const s = saved}
    <section class="cap-done" aria-labelledby="cap-done">
      <span class="cap-mark" aria-hidden="true">✓</span>
      <h2 id="cap-done" tabindex="-1" bind:this={head}>{s.title}</h2>
      <p class="cap-state"><span class="cap-badge" data-s={s.state}>{STATE_LABEL[s.state]}</span> {s.detail}</p>
      {#if s.fetching && s.itemId}
        {#key s.itemId}<CaptureFetch itemId={s.itemId} />{/key}
      {/if}
      <div class="cap-page"><b>{s.meta}</b><pre>{s.page}</pre></div>
      <div class="cap-acts">
        {#if s.file}<Button onclick={() => openNote(s.file ?? '')}>Open the note</Button>{/if}
        {#if s.itemId}
          <Button onclick={() => openCard(s.itemId ?? 0)}>Open the card</Button>
          {#if !d.pic}<Button onclick={() => startJob('describe', { ids: [s.itemId ?? 0], force: true })}>Describe it</Button>{/if}
        {/if}
      </div>
    </section>
  {:else}
    <form id="cap-form" novalidate onsubmit={e => { e.preventDefault(); save() }}>
      <div class="cap-head">
        <div><h2>Add to Brainamon</h2><p class="cap-dim">{seed.text ? (restored ? 'Sent from Wiskit, added after your unsaved draft. Nothing is saved yet.' : 'Sent from Wiskit. Nothing is saved yet.') : restored ? 'Your unsaved draft is back.' : 'Paste, type, or add a picture.'}</p></div>
        <Button title="Start an empty capture" aria-label="Start an empty capture" onclick={discard}>+</Button>
      </div>

      <input type="file" accept={ACCEPT} hidden bind:this={input} onchange={chosen} />
      <input type="file" accept="image/*" hidden bind:this={photos} onchange={chosen} />
      <div class="cap-layout">
        <section class="cap-sheet" aria-label="Your capture">
          {#if dest === 'note' && !target}
            <label class="cap-title-label">Note title<input type="text" class="cap-title" bind:value={d.title} maxlength="80" placeholder={titleFor({ ...d, title: '' }, info)} /></label>
          {:else}<h3 class="cap-title">{target && dest === 'note' ? target.title : 'Library item'}</h3>{/if}
          <div class="cap-src"><label for="cap-text">Your content</label><span class="cap-kind">{kind}</span></div>
          <textarea id="cap-text" class="cap-paper" data-autofocus bind:this={area} bind:value={d.text} onpaste={pasted} rows="12" placeholder="Paste a link or write something to keep."></textarea>
          <p class="cap-dim">{sourceHelp(d, info)}</p>
          {#if info}
            <div class="cap-link" role="group" aria-label="What the page says about itself">
              {#if info.image}<img src={info.image} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={e => ((e.currentTarget as HTMLImageElement).hidden = true)} />{/if}
              <div><b>{info.title || info.creator || siteOf(info.url)}</b>{#if info.desc}<p>{info.desc}</p>{/if}<small>{info.creator || siteOf(info.url)}</small></div>
            </div>
          {/if}

        </section>
        <aside class="cap-tools" aria-label="Capture tools">
          <div class="cap-options">
            <h3>Note tools</h3>
            <div class="cap-add-grid">
              <Button disabled={!!busy} onclick={() => photos?.click()}><Px name="img" />Photo</Button>
              <Button disabled={!!busy} onclick={() => input?.click()}>File</Button>
              <Button onclick={() => area?.focus()}>Link</Button>
              <Button onclick={pasteClipboard}>Paste clipboard</Button>
            </div>
            <Hint>Reading a picture sends it to your selected AI provider or configured endpoint. PDF/text files are read on this PC. AI provider charges apply separately; recipient terms and retention apply.</Hint>
            {#if d.pic}
              <div class="cap-pic">
                <div class="cap-drop">{#if picUrl}<img src={picUrl} alt="Preview of the added file" />{:else}<Px name="img" />{/if}</div>
                <div class="cap-hint"><strong>{d.pic.name}</strong><p role="status">{busy && busy !== 'Saving…' ? busy : picNote}</p></div>
              </div>
              <div class="cap-acts">
                {#if picKind(d.pic) === 'image'}<Button disabled={!!busy} onclick={() => read('digest')}>Read screenshot text</Button><Button disabled={!!busy} onclick={() => read('describe')}>Describe it</Button>{/if}
                <Button disabled={!!busy} onclick={removePic}>Remove</Button>
              </div>
            {/if}
            {#if dest === 'note'}
              <div class="cap-fields"><div class="cap-category"><span>Category</span>{#if target}<b>{target.category || INBOX}</b>{:else}<select class="cap-in" aria-label="Note category" value={d.category || INBOX} onchange={e => (d.category = e.currentTarget.value)}>{#each noteCategories as c (c)}<option>{c}</option>{/each}</select>{/if}</div>
                <div class="cap-which" role="presentation" onkeydown={e => { if (e.key === 'Escape' && pickOpen) { e.stopPropagation(); pickOpen = false } }}>
                  <button type="button" class="cap-pick" class:fresh={!target} aria-haspopup="listbox" aria-expanded={pickOpen} aria-label="Note to add to" onclick={() => (pickOpen = !pickOpen)}>
                    <span>{target ? target.title : 'New note'}</span><span aria-hidden="true">▾</span>
                  </button>
                  {#if pickOpen}
                    <div class="cap-menu">
                      <button type="button" class="cap-new" aria-pressed={!target} onclick={() => { d.target = ''; pickOpen = false }}>+ New note</button>
                      <label class="cap-l">Search your notes<input type="search" class="cap-in" bind:value={q} placeholder="Recent notes show first" /></label>
                      <div class="cap-notes" role="listbox" aria-label="Notes">
                        {#each shown as n (n.file)}
                          <button type="button" class="cap-note" role="option" aria-selected={d.target === n.file} onclick={() => { d.target = n.file; pickOpen = false }}><span><b>{n.title}</b><small>{n.category}{n.file === suggested ? ' · suggested: shares the most words' : ''}</small></span></button>
                        {:else}
                          <p class="cap-dim">{q ? 'No note matches that.' : 'No notes yet.'}</p>
                        {/each}
                      </div>
                    </div>
                  {/if}
                </div>
                {#if target}
                  <div class="cap-page" aria-label="What will be added"><b>Adds this at the end of {target.title}</b><pre>{section(d, undefined, info)}</pre><small>Existing text stays untouched.</small></div>
                {/if}
              </div>
            {:else}
              <div class="cap-fields">
                <label class="cap-l">Collection<select class="cap-in" bind:value={d.collection}><option value="">Automatic (INTERESTING)</option>{#each cats as c (c)}<option>{c}</option>{/each}</select></label>
                <details class="cap-more">
                  <summary>More details</summary>
                  <div class="cap-row">
                    <label class="cap-l">Type<select class="cap-in" bind:value={d.type}><option value="">Automatic</option>{#each LIBRARY_TYPES as t (t)}<option>{t}</option>{/each}</select></label>
                    <label class="cap-l">Tags<input type="text" class="cap-in" bind:value={d.tags} placeholder="Optional, comma-separated" /></label>
                  </div>
                </details>
              </div>
            {/if}

            <label class="cap-l cap-comment">Comment <span class="cap-dim">(optional)</span><input type="text" class="cap-in" bind:value={d.comment} placeholder="Why do you want to keep this?" /></label>
          </div>
          <div class="cap-commit">
            <fieldset class="cap-set">
              <legend>Save to</legend>
              <div class="cap-choices" role="radiogroup" aria-label="Save to">
                <label class="cap-choice"><input type="radio" name="cap-dest" value="note" checked={dest === 'note'} onchange={() => (d.dest = 'note')} /><span>Note</span></label>
                <label class="cap-choice"><input type="radio" name="cap-dest" value="library" checked={dest === 'library'} onchange={() => (d.dest = 'library')} /><span>Library item</span></label>
              </div>
            </fieldset>

            <p class="cap-err" role="alert" hidden={!err}>{err}</p>
            <small id="cap-help">{v.help}</small>
            <Button variant="pri" type="submit" form="cap-form" aria-describedby="cap-help" disabled={!v.ok || !!busy}>{busy === 'Saving…' ? busy : dest === 'library' ? 'Save to Library' : target ? 'Add to note' : 'Save to note'}</Button>
            <Button onclick={close}>Cancel</Button>
          </div>
        </aside>
      </div>
    </form>
  {/if}
</WinBody>
{#if saved}
  <WinFoot>
    <Button onclick={close}>Close</Button>
    <Button onclick={() => { saved = null; tick().then(() => area?.focus()) }}>Back to capture</Button>
    <Button variant="pri" onclick={fresh}>Add another</Button>
  </WinFoot>
{/if}

{#if over}
  <div class="cap-over" use:toBody aria-hidden="true"><div><b>Drop to add a picture</b><p>Release anywhere to add it to your capture.</p><small>One at a time · choose where to save next</small></div></div>
{/if}
