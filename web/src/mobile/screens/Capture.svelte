<script lang="ts">
  // Add to Brainamon on the phone (projects/note-organic-ui/plans/09-add-to-brainamon.md): one capture
  // flow. Incoming content -> destination (Note or Library) -> that destination's fields -> an optional
  // comment -> Save. What is shared to the app or typed here is a DRAFT (IndexedDB, capture.svelte.ts):
  // closing, reloading or being offline loses nothing, and nothing is created until Save. A Library
  // save goes through the outbox (stored first, sent when the PC or the mirror is reachable); a note
  // goes through source.createMyNote / saveMyNote (the PC over REST, or an op: note change file on the
  // Google Drive mirror). A failed save keeps the draft exactly as it was.
  import '../note.css'
  import { onMount, tick } from 'svelte'
  import { Outbox, SRC_COLOR, srcMark } from '../outbox.svelte'
  import { back, fillLinks, go, patchRows, phone, solo, source } from '../state.svelte'
  import { cap, dropDraft, keepDraft, loadDrafts } from '../capture.svelte'
  import { ACCEPT, fileName, toPicked } from '../files'
  import { cleanLink } from '../links'
  import { readClipboard } from '../native'
  import { attachDrop, decodes } from '../../lib/dropzone'
  import {
    checkFiles, destOf, INBOX, joinText, KEPT, label, libraryNote, linkOf, lone, newBody, newDraft, noteText, pageOf, pickNotes, picKind, section,
    siteOf, sourceHelp, STATE_LABEL, suggestNote, titleFor, verdict, type Draft, type NoteRef, type Preview, type Saved,
  } from '../../lib/capture'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'

  // with no PC the link goes into the phone's own journal, so a save needs no signal
  const box = new Outbox(source, solo)
  let d = $state<Draft>(newDraft())
  let ready = $state(false)
  let pickOpen = $state(false)                       // Note: the "which note" dropdown is open
  let newMode = $state(false)                        // Library: the collection is a name typed here
  let q = $state('')                                 // the note search
  let notes = $state.raw<NoteRef[]>([])
  let noteCats = $state<string[]>([INBOX])
  let busy = $state(''), err = $state(''), picNote = $state(''), over = $state(false), sharedNote = $state('')
  let saved = $state<Saved | null>(null)
  let picUrl = $state('')
  let head: HTMLElement | undefined = $state()
  let area: HTMLTextAreaElement | undefined = $state()
  let input: HTMLInputElement | undefined = $state()
  let photos: HTMLInputElement | undefined = $state()
  let tools: HTMLDialogElement | undefined = $state()
  let timer = 0
  let page = $state.raw<Preview | null>(null)        // what the lone link's page says (source.linkPreview)

  const NEW = '+'
  const dest = $derived(destOf(d))
  const link = $derived(linkOf(d.text))
  const known = $derived(link ? phone.rows.find(r => r.url === link)?.id : undefined)
  const v = $derived(verdict(d, { thumb: false, known }))
  const suggested = $derived(suggestNote(d.text, notes))
  const shown = $derived(pickNotes(notes, q, suggested))
  const target = $derived(notes.find(n => n.file === d.target))
  const noteCategories = $derived([...new Set([INBOX, ...noteCats, ...(d.category ? [d.category] : [])])])
  const kind = $derived(d.pic ? (picKind(d.pic) === 'image' ? 'Picture' : 'File') : lone(d.text) ? 'Link' : 'Text')
  const origin = $derived(d.origin === 'typed' ? 'Paste, type, or add a picture.' : 'Shared with Brainamon. Nothing is saved yet.')
  // reading a picture or PDF needs the PC (over REST) or an AI key on this phone (the mirror); a text file needs neither
  const needsAi = $derived(!!d.pic && picKind(d.pic) !== 'text')
  const canRead = $derived(!needsAi || (source.kind === 'desktop' ? phone.reachable : !!source.ai?.()))
  const readHelp = $derived(source.kind === 'desktop' ? 'The PC is not reachable. Reading a picture needs it. Type the text instead, or try again when it is on.' : 'Reading a picture needs an AI key on this phone (More > Wiskit on this phone). Type the text instead.')
  // Wiskit answers through the PC (over REST) or with the AI key on this phone, as the Wiskit screen says
  const canAsk = $derived(source.kind === 'desktop' ? phone.reachable : !!source.ai?.())
  let big = $state(false)                            // the attachment's picture shown large
  const others = $derived(cap.list.filter(x => x.id !== d.id))
  const alone = $derived(lone(d.text))
  const info = $derived(pageOf(d, page))
  // the page is asked for 400 ms after the box becomes one link (through the PC, or the app's own reader)
  $effect(() => {
    const u = alone
    if (!u || saved || !source.linkPreview || page?.asked === u) return
    const t = setTimeout(() => { source.linkPreview?.(u).then(p => { if (lone(d.text) === u) page = p }).catch(() => {}) }, 400)
    return () => clearTimeout(t)
  })

  function flush() { clearTimeout(timer); if (ready && !saved) keepDraft(d) }
  // every change is kept 300 ms later, and at once when the page is hidden or the screen is left
  $effect(() => {
    const s = $state.snapshot(d) as Draft
    if (!ready || saved) return
    clearTimeout(timer)
    timer = window.setTimeout(() => keepDraft(s), 300)
  })
  $effect(() => {
    const b = d.pic && picKind(d.pic) === 'image' ? d.pic.blob : null
    if (!b) { picUrl = ''; return }
    const u = URL.createObjectURL(b)
    picUrl = u
    return () => URL.revokeObjectURL(u)
  })

  async function loadNotes() {
    const [rows, cats] = await Promise.all([source.myNotes().catch(() => []), source.myNoteCategories().catch(() => [INBOX])])
    notes = rows; noteCats = cats
  }

  function show(next: Draft) {
    tools?.close()
    flush()
    d = { ...next }
    pickOpen = false
    newMode = !!next.collection && !phone.cats.some(c => c.name === next.collection)
    q = ''; err = ''; busy = ''; saved = null; picNote = ''; big = false
    if (d.pic && picKind(d.pic) !== 'image' && !d.read && !d.text.trim()) read('digest')   // a PDF or text file reads at once
  }

  onMount(() => {
    loadNotes()
    box.load().then(() => box.flush())
    loadDrafts().then(() => {
      const f = cap.list.find(x => x.id === cap.focus) ?? cap.list[cap.list.length - 1]
      cap.focus = ''
      if (f) show(f)
      else navigator.clipboard?.readText().then(t => { if (!d.text && cleanLink(t)) d.text = t }).catch(() => {})   // like the desktop widget: best effort, often refused
      if (sessionStorage.getItem('bp-shared')) {             // the service worker kept it as a draft (public/sw.js)
        sessionStorage.removeItem('bp-shared')
        // a service worker from before this build saved the link itself and made no draft: say nothing then
        if (f && f.origin !== 'typed' && Date.now() - f.at < 120_000) sharedNote = 'Kept as a draft. Choose where it goes, then Save.'
      }
      if (cap.notice) { err = cap.notice; cap.notice = '' }
      ready = true
    })
    const on = () => box.flush()
    const hide = () => { if (document.visibilityState === 'hidden') flush() }
    window.addEventListener('online', on)
    document.addEventListener('visibilitychange', hide)
    window.addEventListener('pagehide', flush)
    const off = attachDrop({ files: takeFiles, over: o => (over = o && !saved) })   // no overlay over the result view
    // the keyboard is up when the page lost a fifth of its tallest height at this width (the viewport resizes
    // with it: interactive-widget=resizes-content, the app's insets); mobile.css then folds the screen around the text
    let width = 0, tallest = 0
    const fit = () => {
      if (innerWidth !== width) { width = innerWidth; tallest = 0 }
      tallest = Math.max(tallest, innerHeight)
      document.documentElement.classList.toggle('kb', innerHeight < tallest * 0.8)
    }
    fit()
    window.addEventListener('resize', fit)
    return () => {
      flush()
      off()
      window.removeEventListener('resize', fit)
      document.documentElement.classList.remove('kb')
      window.removeEventListener('online', on)
      document.removeEventListener('visibilitychange', hide)
      window.removeEventListener('pagehide', flush)
    }
  })
  // something shared while this screen is open (Android share sheet, native.ts) shows at once
  $effect(() => {
    const id = cap.focus
    if (!ready || !id) return
    const f = cap.list.find(x => x.id === id)
    cap.focus = ''
    if (f && f.id !== d.id) show(f)
  })
  $effect(() => { if (ready && cap.notice) { err = cap.notice; cap.notice = '' } })

  // ── a picture or file ─────────────────────────────────────────────────────
  async function takeFiles(files: File[]) {
    if (!files.length || saved) return
    const c = checkFiles(files)
    if (!c.ok) { err = c.msg; return }
    const f = files[0]
    if (c.kind === 'image' && !(await decodes(f))) { err = 'This image could not be opened. Try a PNG, JPEG, WebP or GIF image.' + KEPT; return }
    err = ''
    d.pic = { name: fileName(f.name, f.type), type: f.type, blob: f }
    d.read = ''
    picNote = `${d.pic.name} added to this capture.`
    if (c.kind !== 'image') await read('digest')
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
  // the Paste button: the clipboard's text goes at the end of the draft (a lone link then shows its preview)
  async function pasteClip() {
    try {
      const t = (await readClipboard()).trim()
      if (!t) { err = 'The clipboard is empty.'; return }
      err = ''
      d.text = d.text.trim() ? `${d.text.trimEnd()}\n${t}` : t
    } catch { err = 'This phone did not allow reading the clipboard. Long-press the box and choose Paste.' }
    area?.focus()
  }
  function removePic() { d.pic = null; d.read = ''; picNote = ''; err = ''; big = false }

  // the attachment goes to Wiskit as text: a picture is described first when nothing was read from it yet.
  // The draft stays as it is; the Wiskit screen shows the context and asks with it.
  async function askWiskit() {
    const p = d.pic
    if (!p || busy) return
    if (!d.read && canRead) { await read(picKind(p) === 'image' ? 'describe' : 'digest'); if (err) return }
    const text = d.text.trim()
    if (!text) { err = 'Wiskit reads text: use Read text or Describe first, or type what it shows.'; return }
    cap.ask = { label: p.name, text: text.slice(0, 8000) }
    flush()
    go('#/jv')
  }

  async function read(how: 'digest' | 'describe') {
    const p = d.pic, id = d.id
    if (!p || busy) return
    busy = picKind(p) !== 'image' ? `Reading ${p.name}…` : how === 'digest' ? 'Reading the text in the picture…' : 'Describing the picture…'
    err = ''
    try {
      const text = await source.readFile(await toPicked(p.blob, p.name, p.type), how)
      if (d.id !== id || d.pic !== p) return                // the capture changed while it was reading
      d.text = joinText(d.text, text)
      d.read = how
      picNote = 'Text added to the box. Review it before saving.'
    } catch (e) { err = (e as Error).message + KEPT } finally { busy = '' }
  }

  // ── Save ────────────────────────────────────────────────────────────────────
  // where a note lives decides what "saved" means: the PC has it, or this phone holds it until it syncs
  const where = () => (source.kind === 'desktop' ? { state: 'synced' as const, detail: 'Saved on the PC.' }
    : solo ? { state: 'synced' as const, detail: 'Saved on this phone.' }
      : { state: 'pending' as const, detail: 'Saved on this phone. It reaches the PC when it syncs.' })

  async function saveNote(s: Draft): Promise<Saved> {
    const p = pageOf(s, page)                               // the card the user saw, for this exact link
    const category = s.category || INBOX
    if (s.target) {                                         // only the new section travels: the note's text stays as it is
      const m = await source.appendMyNote(s.target, notes.find(n => n.file === s.target)?.title ?? '', label(s), noteText(s, p))
      return { ...where(), title: 'Added to your note', meta: `${m.title} · appended`, page: section(s, undefined, p), file: m.file }
    }
    let m = s.made ? await source.myNote(s.made).catch(() => null) : null
    if (!m) {
      m = await source.createMyNote(titleFor(s, p), category)
      d.made = m.file                                       // a failure below keeps the draft, and the retry reuses this note
      await keepDraft(d)
    }
    const out = await source.saveMyNote(m.file, titleFor(s, p), category, newBody(s, p))
    return { ...where(), title: 'Saved to a new note', meta: `My Notes / ${category}`, page: `${out.title}\n\n${newBody(s, p).trimEnd()}`, file: out.file }
  }

  async function saveLibrary(s: Draft): Promise<Saved> {
    const name = (s.collection === NEW ? '' : s.collection).trim().slice(0, 80)
    const note = libraryNote(s)                             // the text around the link, then the comment
    const e = await box.save(linkOf(s.text), note, name, s.tags.trim(), source.kind === 'desktop' ? s.type : '')
    if (e.state === 'error') { if (e.id) await box.remove(e.id); throw new Error(e.error || 'The link was refused.') }
    // the PC already had it (this phone's rows were out of date): nothing was added, so the draft stays
    if (e.state === 'dup') throw new Error(`Already in your library${(e.itemId ?? 0) > 0 ? ` as No. ${e.itemId}` : ''}. Nothing was added to it`)
    if (e.itemId && e.itemId > 0) patchRows([e.itemId])
    if ((e.itemId ?? 0) < 0 && e.state === 'sent') fillLinks([e.itemId!])
    const meta = `Library${name ? ' / ' + name : ''}${s.type && source.kind === 'desktop' ? ' · ' + s.type : ''}${s.tags.trim() ? ' · ' + s.tags.trim() : ''}`
    const page = `${e.url}${note ? '\n\n' + note : ''}`
    if (e.state === 'waiting') return { state: 'pending', title: 'Saved as a Library item', detail: 'Stored on this phone. It goes to the PC when it is reachable.', meta, page }
    const where = (e.itemId ?? 0) > 0 ? 'Saved. The PC fetches the thumbnail.' : solo ? 'Saved on this phone.' : 'Saved. The PC adds it, with its thumbnail, when it runs.'
    return { state: (e.itemId ?? 0) > 0 || solo ? 'synced' : 'pending', title: 'Saved as a Library item', detail: where, meta, page, itemId: e.itemId ?? undefined }
  }

  async function save() {
    if (!v.ok || busy || saved) return
    busy = 'Saving…'
    err = ''
    const s = $state.snapshot(d) as Draft
    try {
      const r = destOf(s) === 'library' ? await saveLibrary(s) : await saveNote(s)
      clearTimeout(timer)
      saved = r
      await dropDraft(s.id)
      loadNotes()
      await tick()
      head?.focus()
    } catch (e) { err = `Not saved: ${(e as Error).message}.${KEPT}` } finally { busy = '' }
  }

  function discard() { clearTimeout(timer); dropDraft(d.id); fresh() }
  function fresh() {
    tools?.close()
    d = newDraft()
    pickOpen = false; newMode = false; q = ''; err = ''; picNote = ''; saved = null; sharedNote = ''; big = false
    tick().then(() => area?.focus())
  }
  const ago = (ms: number) => { const m = Math.round((Date.now() - ms) / 60000); return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago` }
  const short = (u: string) => u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40) + (u.length > 48 ? '…' : '')
  const peek = (x: Draft) => (x.text.trim() || x.pic?.name || x.comment.trim() || 'Empty draft').replace(/\s+/g, ' ').slice(0, 34)
</script>

<div class="m-cap-screen" class:m-cap-result={!!saved}>
  {#if saved}
    {@const s = saved}
    <section class="m-share m-cap-done" aria-labelledby="cap-done">
      <div class="m-share-bd">
        <span class="m-cap-mark" aria-hidden="true">✓</span>
        <h2 id="cap-done" tabindex="-1" bind:this={head}>{s.title}</h2>
        <div class="m-row"><span class="m-badge" class:ok={s.state === 'synced'} class:wait={s.state === 'pending'} class:bad={s.state === 'failed'}>{STATE_LABEL[s.state]}</span></div>
        <MHint as="p">{s.detail}</MHint>
        <div class="m-cap-page"><b>{s.meta}</b><pre>{s.page}</pre></div>
        <div class="m-row m-cap-acts">
          <MButton variant="pri" onclick={fresh}>Add another</MButton>
          <MButton onclick={back}>Back</MButton>
          {#if s.file}<MButton onclick={() => go(`#/mynotes/${encodeURIComponent(s.file ?? '')}`)}>Open the note</MButton>{/if}
          {#if s.itemId && s.itemId > 0}<MButton onclick={() => go(`#/item/${s.itemId}`)}>Open the card</MButton>{/if}
        </div>
      </div>
    </section>
    <MButton onclick={() => tools?.showModal()}>Outbox ({box.entries.length})</MButton>
  {:else}
    <form class="m-cap-form" onsubmit={e => { e.preventDefault(); save() }}>
      <input type="file" accept={ACCEPT} hidden bind:this={input} onchange={chosen} />
      <input type="file" accept="image/*" hidden bind:this={photos} onchange={chosen} />
      <div class="m-cap-meta">
        {#if dest === 'note'}
          <div class="m-cap-category"><span class="m-lbl">Category</span>{#if target}<b>{target.category || INBOX}</b>{:else}<select aria-label="Note category" value={d.category || INBOX} onchange={e => (d.category = e.currentTarget.value)}>{#each noteCategories as c (c)}<option>{c}</option>{/each}</select>{/if}</div>
          <div class="m-cap-destination"><span class="m-lbl">Add to</span>
            <div class="m-cap-which" role="presentation" onkeydown={e => { if (e.key === 'Escape') pickOpen = false }}>
              <button type="button" class="m-cap-pick" class:fresh={!target} aria-haspopup="listbox" aria-expanded={pickOpen} aria-label="Note to add to" onclick={() => (pickOpen = !pickOpen)}>
                <span>{target ? target.title : 'New note'}</span><span aria-hidden="true">▾</span>
              </button>
              {#if pickOpen}
                <div class="m-cap-menu">
                  <button type="button" class="m-cap-new" aria-pressed={!target} onclick={() => { d.target = ''; pickOpen = false }}>+ New note</button>
                  <label class="m-fld"><span class="m-pr">?</span><input type="search" bind:value={q} aria-label="Search your notes" placeholder="Search your notes" /></label>
                  <div class="m-cap-notes" role="listbox" aria-label="Notes">
                    {#each shown as n (n.file)}
                      <button type="button" class="m-cap-note" role="option" aria-selected={d.target === n.file} onclick={() => { d.target = n.file; pickOpen = false }}><span><b>{n.title}</b><small>{n.category}{n.file === suggested ? ' · suggested: shares the most words' : ''}</small></span></button>
                    {:else}
                      <div class="m-empty">{q ? 'No note matches that.' : 'No notes yet.'}</div>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          </div>
        {:else}
          <div class="m-row"><span class="m-lbl">Collection</span><span class="m-sp"></span>
            <label class="m-fld" style="padding:5px 8px"><select aria-label="Collection" value={newMode ? NEW : d.collection} onchange={e => { const x = e.currentTarget.value; newMode = x === NEW; d.collection = newMode ? '' : x; if (newMode) tools?.showModal() }}><option value="">{solo ? 'Default' : 'PC decides'}</option>{#each phone.cats as c (c.name)}<option value={c.name}>{c.name}</option>{/each}{#if d.collection && !newMode && !phone.cats.some(c => c.name === d.collection)}<option value={d.collection}>{d.collection}</option>{/if}<option value={NEW}>+ New collection</option></select><span>▾</span></label>
          </div>
        {/if}
      </div>
      <section class="m-cap-editor" aria-label="Your capture">
        {#if dest === 'note' && !target}
          <label class="sr" for="cap-title">Note title</label><input id="cap-title" class="m-cap-title" bind:value={d.title} maxlength="80" aria-label="Note title" placeholder={titleFor({ ...d, title: '' }, info)} />
        {:else}<h2 class="m-cap-title">{dest === 'note' && target ? target.title : 'Library item'}</h2>{/if}
        <MHint as="p" class="m-cap-origin">{origin}</MHint>
        {#if sharedNote}<span class="m-badge ok" role="status">{sharedNote}</span>{/if}
        <label class="sr" for="cap-text">Your content</label>
        <div class="m-fld ta m-cap-paper"><textarea id="cap-text" bind:this={area} bind:value={d.text} onpaste={pasted} placeholder="Paste a link or write something to keep." rows="12"></textarea></div>
        {#if info}
          <div class="m-cap-link" role="group" aria-label="What the page says about itself">
            {#if info.image}<img src={info.image} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={e => ((e.currentTarget as HTMLImageElement).hidden = true)} />{/if}
            <div><b>{info.title || info.creator || siteOf(info.url)}</b>{#if info.desc}<p>{info.desc}</p>{/if}</div>
          </div>
        {/if}

        {#if d.pic}
          {@const img = picKind(d.pic) === 'image'}
          <div class="m-cap-pic" class:big>
            {#if picUrl}<button type="button" class="m-cap-thumb" aria-expanded={big} aria-label={big ? 'Show the picture small' : 'Show the picture large'} onclick={() => (big = !big)}><img src={picUrl} alt="Preview of the added file" /></button>{/if}
            <div><b>{d.pic.name}</b><MHint as="p" role="status">{busy && busy !== 'Saving…' ? busy : !canRead ? readHelp : picNote}</MHint></div>
            <div class="m-cap-quick" role="group" aria-label="Attachment actions">
              {#if img || !d.read}<MButton size="sm" class="m-cap-lbl" disabled={!canRead || !!busy} onclick={() => { if (window.confirm('Read text\n\nCopy the text in this attachment into your draft for you to review before saving.')) read('digest') }}>Read text</MButton>{/if}
              {#if img}<MButton size="sm" class="m-cap-lbl" disabled={!canRead || !!busy} onclick={() => { if (window.confirm('Describe\n\nAI describes what the photo shows and copies its visible text into your draft. Review the result before saving.')) read('describe') }}>Describe</MButton>{/if}
              <MButton size="sm" class="m-cap-lbl" disabled={!canAsk || !!busy} onclick={() => { if (window.confirm('Ask Wiskit\n\nOpen chat with your draft text as context so you can ask questions about it. If the attachment has not been read yet, it is read or described first and added to your draft.')) askWiskit() }}>Ask Wiskit</MButton>
              <MButton size="sm" class="m-cap-icon" aria-label="Remove the attachment" title="Remove the attachment" disabled={!!busy} onclick={removePic}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" /></svg></MButton>
            </div>
          </div>
        {/if}
        <MHint as="p" class="m-cap-source-help">{sourceHelp(d, info)}</MHint>
      </section>
      <footer class="m-cap-dock">
        <MHint as="p">PDFs are read as soon as you add them: own-key phone mode sends the complete PDF to your AI provider; direct-PC mode reads it on the PC. Reading or describing pictures sends the image to your selected provider or configured endpoint. AI provider charges apply separately; recipient terms and retention apply.</MHint>
        {#if err}<p class="m-err" role="alert">{err}</p>{/if}
        <div class="m-cap-actions">
          <MButton class="m-cap-drop" disabled={!!busy} onclick={() => photos?.click()}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v14H4zM4 16l5-5 4 4 2-2 5 5" /><circle cx="15.5" cy="9" r="1.5" /></svg>Photo</MButton>
          <MButton disabled={!!busy} onclick={() => input?.click()}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8" /></svg>File</MButton>
          <MButton disabled={!!busy} onclick={pasteClip}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4h6v3H9zM9 5.5H6v15h12v-15h-3M9 12h6M9 16h4" /></svg>Paste</MButton>
          <MButton aria-haspopup="dialog" onclick={() => tools?.showModal()}>More</MButton>
        </div>
        <div class="m-cap-commit">
          <fieldset class="m-cap-set">
            <legend class="m-lbl sr">Save to</legend>
            <div class="m-cap-choices" role="radiogroup" aria-label="Save to">
              <label class="m-cap-choice"><input type="radio" name="cap-dest" value="note" checked={dest === 'note'} onchange={() => (d.dest = 'note')} /><span>Note</span></label>
              <label class="m-cap-choice"><input type="radio" name="cap-dest" value="library" checked={dest === 'library'} onchange={() => (d.dest = 'library')} /><span>Library item</span></label>
            </div>
          </fieldset>

          <MButton variant="pri" type="submit" class="m-cap-save" aria-label={dest === 'library' ? 'Save to Library' : target ? 'Add to note' : 'Save to note'} aria-describedby="cap-help" disabled={!v.ok || !!busy}>{busy === 'Saving…' ? 'Saving…' : 'Save'}</MButton>
        </div>
        <MHint as="small" id="cap-help">{v.help}</MHint>
      </footer>
    </form>
  {/if}

  <dialog class="m-cap-tools" bind:this={tools} aria-labelledby="cap-tools-title">
    <div class="m-cap-tools-head"><h2 id="cap-tools-title">More</h2><MButton onclick={() => tools?.close()}>Done</MButton></div>
    <div class="m-cap-tools-body">
      {#if !saved}
        {#if others.length}
          <div class="m-cap-drafts" role="group" aria-label="Other drafts">
            <span class="m-lbl">Other drafts ({others.length})</span>
            {#each others as x (x.id)}<button type="button" class="m-chip" onclick={() => show(x)}>{peek(x)}</button>{/each}
          </div>
        {/if}

        {#if dest === 'library'}
          {#if newMode}<label class="m-fld"><span class="m-pr">#</span><input bind:value={d.collection} maxlength="80" aria-label="New collection name" placeholder="Name the new collection" /></label>{/if}
          <details class="m-cap-more">
            <summary>More details</summary>
            <div class="m-cap-fields">
              {#if source.kind === 'desktop'}
                <label class="m-fld"><span class="m-lbl">Type</span><select aria-label="Type" bind:value={d.type}><option value="">Automatic</option>{#each ['Reel', 'Video', 'Post', 'Link', 'Recipe', 'Tutorial', 'Other'] as t (t)}<option>{t}</option>{/each}</select><span>▾</span></label>
              {/if}
              <label class="m-fld"><span class="m-pr">#</span><input bind:value={d.tags} aria-label="Tags" placeholder="Tags, comma-separated (optional)" /></label>
            </div>
          </details>
          {#if known}<span class="m-badge mute">Already card No. {known}</span>{:else if link}<span class="m-badge ok">New to your library</span>{/if}
          {#if !phone.reachable && !solo}<span class="m-badge wait">Waits for the PC</span>{/if}
        {:else if target}
          <div class="m-cap-page" aria-label="What will be added"><b>Adds this at the end of {target.title}</b><pre>{section(d, undefined, info)}</pre><MHint as="small">Existing text stays untouched.</MHint></div>
        {/if}
        <label class="m-lbl" for="cap-comment">Comment <i>(optional)</i></label>
        <label class="m-fld"><span class="m-pr">#</span><input id="cap-comment" bind:value={d.comment} placeholder="Why do you want to keep this?" /></label>

        {#if d.text || d.comment || d.pic}<button type="button" class="m-link" onclick={discard}>Discard this draft</button>{/if}
      {/if}
      <div class="m-row"><span class="m-lbl">Outbox <span class="m-jp" aria-hidden="true">送信待ち</span></span><span class="m-sp"></span><span class="m-lbl">{box.entries.some(e => e.state === 'waiting') ? 'sends when the PC runs' : `${box.entries.length} saved`}</span></div>
      <div class="m-q-list">
        {#each box.entries as e (e.id)}
          <button type="button" class="m-q-it" onclick={() => { const id = phone.rows.find(r => r.url === e.url)?.id ?? e.itemId; if (id) location.hash = `#/item/${id}` }}>
            <span class="m-qico" style:background={SRC_COLOR[e.src]}>{e.src}</span>
            <div><b>{short(e.url)}</b><small>Saved {ago(e.added)}{e.state === 'dup' ? ' · already a card' : e.state === 'sent' ? ((e.itemId ?? 0) > 0 || phone.rows.some(r => r.url === e.url && r.id > 0) ? ' · the PC has it' : solo ? ' · on this phone' : ' · waiting for the PC') : e.state === 'error' ? ` · ${e.error}` : ''}</small></div>
            {#if e.state === 'waiting'}<span class="m-badge wait">Waiting</span>{:else if e.state === 'sent'}<span class="m-badge ok">In library</span>{:else if e.state === 'dup'}<span class="m-badge mute">Duplicate</span>{:else}<span class="m-badge bad">Failed</span>{/if}
          </button>
        {:else}
          <div class="m-empty">Links you save here show up in this list, then as cards in the Library.</div>
        {/each}
      </div>
      {#if box.entries.length}<button type="button" class="m-link" style="align-self:flex-end" onclick={() => box.entries.filter(e => e.state !== 'waiting').forEach(e => e.id && box.remove(e.id))}>Clear the done ones</button>{/if}
    </div>
  </dialog>
</div>

{#if over}
  <div class="m-cap-over" aria-hidden="true"><div><b>Drop to add a picture</b><p>Release anywhere to add it to your capture.</p><small>One at a time · choose where to save next</small></div></div>
{/if}
