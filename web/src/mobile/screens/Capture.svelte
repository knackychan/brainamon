<script lang="ts">
  // Add to Brainamon on the phone (projects/note-organic-ui/plans/09-add-to-brainamon.md): one capture
  // flow. What is shared to the app or typed here is a DRAFT (IndexedDB, capture.svelte.ts): closing,
  // reloading or being offline loses nothing, and nothing is created until Save. A Library save goes
  // through the outbox (stored first, sent when the PC or the mirror is reachable); a note goes through
  // source.createMyNote / saveMyNote / appendMyNote (the PC over REST, or a note change file on the Google
  // Drive mirror). A failed save keeps the draft exactly as it was.
  // The draft is one mixed capture (projects/phone-add-confirm): the title, the text, the link's page and one
  // picture or document, with Photo, File, Paste and Save in the composer at the bottom (projects/phone-add-sheet).
  // Save opens the recap, #/cap/save on this same screen: a preview of the note or the Library item as it will
  // be saved, the attachment's line, where it goes (Note: a new one or an existing one, its category; Library:
  // its collection and tags), the comment, then the final Save. The top-right Import & drafts key is drawn by
  // Mobile.svelte (CaptureKey.svelte) and talks to this screen through capture-ui.svelte.ts.
  import '../note.css'
  import { onMount, tick, untrack } from 'svelte'
  import { Outbox, OutboxStorageError } from '../outbox.svelte'
  import { fillLinks, go, patchRows, phone, solo, source } from '../state.svelte'
  import { back as stepBack, go as goTo } from '../shell.svelte'
  import { cap, captureRevision, clearFile, clearRead, clearSuggestion, draftEdited, dropDraft, dropDraftIfUnchanged, keepDraft, loadDrafts, retainFile, retainRead, retainSuggestion } from '../capture.svelte'
  import { t } from '../../lib/i18n/index.ts'
  import { captureError, captureText, captureType, draftAgo, saveStateLabel } from '../capture-words.ts'
  import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from '../language-switch.ts'
  import { capUi } from '../capture-ui.svelte'
  import { ACCEPT, fileName, stamp, toPicked } from '../files'
  import { cleanLink } from '../links'
  import { watchKeyboard } from '../keyboard'
  import { readClipboard } from '../native'
  import { attachDrop, decodes } from '../../lib/dropzone'
  import { plain } from '../../lib/note-format'
  import {
    checkFiles, isEmpty, joinText, label, LIBRARY_TYPES, libraryNote, linkOf, lone, newBody, newDraft, noteText, pageOf, pickNotes, picKind,
    section, siteOf, sourceHelp, suggestNote, titleFor, verdict, type Draft, type NoteRef, type Preview, type Saved,
  } from '../../lib/capture'
  import {
    attLine, categoriesFor, collectionsFor, draftHelp, GENERAL, KIND_TAG, libraryBlock, libraryHint, noteHint, phoneDest, pickedLine,
    startCollection, suggestFailed, tailOf,
  } from '../recap'
  import { mergeTags } from '../ai/describe'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'
  import MInfo from '../ui/MInfo.svelte'
  import MKey from '../ui/MKey.svelte'
  import MPicker from '../ui/MPicker.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import ShellIcon from '../ShellIcon.svelte'

  // with no PC the link goes into the phone's own journal, so a save needs no signal
  const box = new Outbox(source, solo)
  let d = $state<Draft>(newDraft())
  let ready = $state(false)
  let alive = true
  let applyingFile = $state('')
  let pickOpen = $state(false)                       // the recap's "which note" list is open
  let newMode = $state(false)                        // Library: the collection is a name typed here
  let q = $state('')                                 // the note search
  let notes = $state.raw<NoteRef[]>([])
  let noteCats = $state<string[]>([])                // the categories the source lists (the ones notes use)
  let busy = $state(''), err = $state(''), picNote = $state(''), over = $state(false), sharedNote = $state('')
  let saved = $state<Saved | null>(null)
  let picUrl = $state('')
  let head: HTMLElement | undefined = $state()
  let pvHead: HTMLElement | undefined = $state()
  let area: HTMLTextAreaElement | undefined = $state()
  let input: HTMLInputElement | undefined = $state()
  let photos: HTMLInputElement | undefined = $state()
  let pop: HTMLDialogElement | undefined = $state()
  let menu: HTMLElement | undefined = $state()
  let pvBody: HTMLElement | undefined = $state()
  let timer = 0
  let page = $state.raw<Preview | null>(null)        // what the lone link's page says (source.linkPreview)
  let tail = $state.raw<{ file: string; text: string } | null>(null)   // the end of the note an addition goes to
  let pvLong = $state(false), pvAll = $state(false)  // the preview is taller than its frame; it is shown whole

  const NEW = '+'
  // the recap is #/cap/save: the same screen, so the draft and its state stay as they are under it
  const recap = $derived(!!phone.route.save)
  const link = $derived(linkOf(d.text))
  const known = $derived(link ? phone.rows.find(r => r.url === link)?.id : undefined)
  // why the Library cannot take this draft ('' when it can), and where the recap stands: Note whenever it cannot
  const block = $derived(libraryBlock(d, known, captureText))
  const dest = $derived(phoneDest(d, known))
  const category = $derived(d.category || GENERAL)
  const v = $derived(verdict({ ...d, dest, category }, { thumb: false, known }, captureText))
  const canGo = $derived(!!d.text.trim() || !!d.pic)
  const suggested = $derived(suggestNote(d.text, notes))
  const shown = $derived(pickNotes(notes, q, suggested))
  const target = $derived(notes.find(n => n.file === d.target))
  const categoryOptions = $derived(categoriesFor(noteCats, d.category).map(c => [c, c] as [string, string]))
  // Library: the phone decides the collection, never the PC later. It starts on the one used last on this phone, else
  // INTERESTING; a new collection needs its name before Save
  const LAST = 'bp-cap-collection'
  let last = $state((() => { try { return localStorage.getItem(LAST) ?? '' } catch { return '' } })())
  const names = $derived(phone.cats.map(c => c.name))
  const start = $derived(startCollection(last))
  const collection = $derived(d.collection || start)
  const collectionOptions = $derived<[string, string][]>([
    ...collectionsFor(names, newMode ? '' : collection).map(c => [c, c] as [string, string]), [NEW, t('capture.destination.newCollectionOption')],
  ])
  const collectionName = $derived(newMode ? t('capture.destination.newCollectionOption') : collection)
  function keepCollection(name: string) {
    last = name
    try { localStorage.setItem(LAST, name) } catch { /* remembered for this session only */ }
  }
  const typeOptions = $derived<[string, string][]>([['', t('capture.destination.automatic')], ...LIBRARY_TYPES.map(type => [type, captureType(type)] as [string, string])])
  const origin = $derived(d.origin === 'typed' ? t('capture.draft.typedHelp') : t('capture.draft.sharedHelp'))
  // reading a picture or PDF needs the PC (over REST) or an AI key on this phone (the mirror); a text file needs neither
  const needsAi = $derived(!!d.pic && picKind(d.pic) !== 'text')
  const canRead = $derived(!needsAi || (source.kind === 'desktop' ? phone.reachable : !!source.ai?.()))
  const readHelp = $derived(source.kind === 'desktop' ? t('capture.attachment.pcNeeded') : t('capture.attachment.keyNeeded'))
  // Wiskit answers through the PC (over REST) or with the AI key on this phone, as the Wiskit screen says
  const canAsk = $derived(source.kind === 'desktop' ? phone.reachable : !!source.ai?.())
  let big = $state(false)                            // the attachment's picture shown large
  const others = $derived(cap.list.filter(x => x.id !== d.id))
  const alone = $derived(lone(d.text))
  const info = $derived(pageOf(d, page))
  // the empty draft's one hint (Import saved posts) shows until something is typed, shared or attached
  const empty = $derived(isEmpty(d) && !d.title.trim() && !saved)
  // the recap's preview: the new note as it will read, or the note's last lines and the section an addition makes,
  // or the Library item's fields (no card: the Library numbers and draws it when it is saved)
  const when = $derived(recap ? stamp() : '')
  const pvText = $derived(d.target ? section(d, when, info) : newBody(d, info).trimEnd())
  const pvTail = $derived(d.target && tail?.file === d.target && tail.text ? `…\n${tail.text}` : '')
  const libNote = $derived(libraryNote(d))
  const byline = $derived([info?.creator, siteOf(link)].filter(Boolean).join(' · '))
  const collectionShown = $derived(newMode ? d.collection.trim() || t('capture.destination.unnamedCollection') : collection)
  const unnamed = $derived(dest === 'library' && newMode && !d.collection.trim())

  // Suggest: with an AI key on this phone, Wiskit picks the collection and a few tags from the link and what its page
  // says (the PC's Categorize prompt, MirrorSource.suggestCategory). It asks first, like Read text; nothing is written.
  const canSuggest = $derived(!!source.suggestCategory && !!source.ai?.())
  let sureCat = $state(false), asking = $state(false), picked = $state('')
  let suggestKey: HTMLButtonElement | HTMLAnchorElement | undefined = $state()
  let catGo: HTMLButtonElement | HTMLAnchorElement | undefined = $state()
  $effect(() => { if (sureCat) tick().then(() => catGo?.focus()) })
  function cancelSuggest() { sureCat = false; suggestKey?.focus() }
  async function suggest() {
    const done = beginLanguageWork()
    const draftId = d.id
    sureCat = false
    asking = true
    err = ''
    picked = ''
    try {
      const got = await source.suggestCategory!({ url: link, description: [info?.title, info?.desc, libNote].filter(Boolean).join('\n'), creator: info?.creator ?? '', type: '' }, collectionsFor(names))
      if (!alive || d.id !== draftId) { retainSuggestion(got.category, got.tags); return }
      newMode = false
      d.collection = got.category
      if (got.tags) d.tags = mergeTags(d.tags, got.tags)
      picked = pickedLine(got.category, got.tags, captureText)
    } catch (e) { err = suggestFailed(captureError(e), captureText) } finally { asking = false; done() }
  }
  // the recap's Save: the verdict, a named collection, and no suggestion on its way
  const ok = $derived(v.ok && !unnamed && !asking)
  const help = $derived(unnamed ? t('capture.destination.nameIt') : v.help)

  // The three actions on an attachment ask first, inside the picture's card (no browser pop-up): the first tap opens
  // this line, Continue runs the action, Cancel closes the line.
  type Act = 'digest' | 'describe' | 'ask'
  const ASKS: Record<Act, { name: string; says: string }> = {
    digest: { name: t('capture.attachment.read'), says: t('capture.attachment.readSays') },
    describe: { name: t('processing.action.describe.label'), says: t('capture.attachment.describeSays') },
    ask: { name: t('shell.askWiskitLabel'), says: t('capture.attachment.askSays') },
  }
  let sure = $state<Act | ''>('')
  let quick: HTMLElement | undefined = $state()
  let goBtn: HTMLButtonElement | HTMLAnchorElement | undefined = $state()
  function cancelAsk() {
    const pill = quick?.querySelector<HTMLElement>('[aria-expanded="true"]')
    sure = ''
    pill?.focus()
  }
  $effect(() => { if (busy) { sure = ''; sureCat = false } })
  $effect(() => { if (sure) tick().then(() => goBtn?.focus()) })
  // moving between the draft and the recap closes the confirm lines and the note list
  $effect(() => { void recap; sure = ''; sureCat = false; pickOpen = false })
  $effect(() => { if (pickOpen) tick().then(() => menu?.scrollIntoView({ block: 'nearest' })) })

  // the Import & drafts key (CaptureKey.svelte) shows how many other drafts wait and opens the panel below
  let seenTray = capUi.tray
  $effect(() => { capUi.drafts = others.length })
  $effect(() => {
    const n = capUi.tray
    if (n !== seenTray) { seenTray = n; if (pop && !pop.open) { pop.showModal(); capUi.open = true } }
  })
  // a tap outside the panel closes it (MDialog.svelte's rule: the backdrop's default would move focus to BODY)
  function outside(e: PointerEvent) {
    if (!pop || e.target !== pop) return
    const r = pop.getBoundingClientRect()
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { e.preventDefault(); pop.close() }
  }

  // the page is asked for 400 ms after the box becomes one link (through the PC, or the app's own reader)
  $effect(() => {
    const u = alone
    if (!u || saved || !source.linkPreview || page?.asked === u) return
    const t = setTimeout(() => { source.linkPreview?.(u).then(p => { if (lone(d.text) === u) page = p }).catch(() => {}) }, 400)
    return () => clearTimeout(t)
  })

  let draftVersion = 0, flushedVersion = -1
  let lastDraftSignature = '', lastDraftBlob: Blob | null = null
  function flush() { clearTimeout(timer); if (ready && !saved) keepDraft(d) }
  // every change is kept 300 ms later, and at once when the page is hidden or the screen is left
  $effect(() => {
    const s = $state.snapshot(d) as Draft
    if (!ready || saved) return
    const { made: _made, ...content } = s
    const signature = JSON.stringify({ ...content, pic: s.pic ? { name: s.pic.name, type: s.pic.type } : null })
    const blob = s.pic?.blob ?? null
    if (signature !== lastDraftSignature || blob !== lastDraftBlob) {
      lastDraftSignature = signature; lastDraftBlob = blob; draftEdited(s.id)
    }
    languageWorkChanged()
    const version = ++draftVersion
    clearTimeout(timer)
    timer = window.setTimeout(() => { void keepDraft(s).then(() => { if (draftVersion === version) flushedVersion = version }) }, 300)
  })
  $effect(() => {
    const b = d.pic && picKind(d.pic) === 'image' ? d.pic.blob : null
    if (!b) { picUrl = ''; return }
    const u = URL.createObjectURL(b)
    picUrl = u
    return () => URL.revokeObjectURL(u)
  })

  // each list loads on its own: one that fails leaves the other as it is (projects/phone-notes-manager)
  async function loadNotes() {
    const [rows, cats] = await Promise.allSettled([source.myNotes(), source.myNoteCategories()])
    if (rows.status === 'fulfilled') notes = rows.value
    if (cats.status === 'fulfilled') noteCats = cats.value
  }

  // an addition shows the end of its note above the new section; nothing when the note cannot be read. The read is
  // untracked: the PC's API counts each request in a state (lib/api.ts net.n) that this effect would read and write
  $effect(() => {
    const file = recap ? d.target : ''
    if (!file || tail?.file === file) return
    let live = true
    untrack(() => source.myNote(file)).then(m => { if (live) tail = { file, text: tailOf(plain(m.body ?? '')) } }).catch(() => { if (live) tail = { file, text: '' } })
    return () => { live = false }
  })
  // the preview shows about ten lines; Show all opens it whole
  $effect(() => {
    if (!recap) return
    void pvText; void pvTail; void pvAll; void dest
    const el = pvBody
    tick().then(() => { pvLong = pvAll || (!!el && el.scrollHeight > el.clientHeight + 1) })
  })
  // the recap opens on its first heading
  $effect(() => { if (recap && !saved) tick().then(() => pvHead?.focus({ preventScroll: true })) })

  function show(next: Draft) {
    pop?.close()
    flush()
    d = { ...next }
    pickOpen = false
    newMode = !!next.collection && !phone.cats.some(c => c.name === next.collection)
    q = ''; err = ''; busy = ''; saved = null; picNote = ''; big = false; sure = ''
    if (phone.route.save) stepBack()                         // a share that arrives on the recap opens on the draft
    if (d.pic && picKind(d.pic) !== 'image' && !d.read && !d.text.trim() && !cap.recoveredReads.some(result => result.draftId === d.id)) read('digest')   // a PDF or text file reads at once
  }

  onMount(() => {
    const releaseDraftCheck = registerLanguageCheck(async () => {
      if (ready && !saved && draftVersion !== flushedVersion) {
        const version = draftVersion
        clearTimeout(timer); await keepDraft(d)
        if (draftVersion === version) flushedVersion = version
      }
      return null
    })
    if (phone.route.save) goTo('#/cap', true)                // a reload on the recap starts on the draft
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
        if (f && f.origin !== 'typed' && Date.now() - f.at < 120_000) sharedNote = t('capture.draft.sharedNotice')
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
    // the keyboard is up when the page lost a fifth of its tallest height at this width (keyboard.ts: html.kb);
    // mobile.css then folds the screen around the text
    const stopKeyboard = watchKeyboard()
    return () => {
      alive = false
      flush()
      releaseDraftCheck()
      off()
      stopKeyboard()
      capUi.drafts = 0
      capUi.open = false
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
  async function takeFiles(files: File[]): Promise<boolean> {
    if (!files.length || saved) return false
    const c = checkFiles(files, captureText)
    if (!c.ok) { err = c.msg; return false }
    const f = files[0], draftId = d.id, previous = d.pic, done = beginLanguageWork()
    try {
      if (c.kind === 'image' && !(await decodes(f))) { err = t('capture.attachment.imageFailed'); return false }
      if (!alive || saved || d.id !== draftId || d.pic !== previous) { retainFile(f); return true }
      err = ''
      d.pic = { name: fileName(f.name, f.type), type: f.type, blob: f }
      d.read = ''
      picNote = t('capture.attachment.added', { name: d.pic.name })
      if (c.kind !== 'image') await read('digest')
      return true
    } finally { done() }
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
  // the Paste key: the clipboard's text goes at the end of the draft (a lone link then shows its preview)
  async function pasteClip() {
    const draftId = d.id, done = beginLanguageWork()
    try {
      const text = (await readClipboard()).trim()
      if (!text) { err = t('capture.draft.clipboardEmpty'); return }
      if (!alive || d.id !== draftId) { retainRead('', t('capture.clipboard'), text, 'digest'); return }
      err = ''
      d.text = d.text.trim() ? `${d.text.trimEnd()}\n${text}` : text
    } catch { err = t('capture.draft.clipboardDenied') }
    finally { done() }
    area?.focus()
  }
  function removePic() { d.pic = null; d.read = ''; picNote = ''; err = ''; big = false; sure = '' }

  // the attachment goes to Wiskit as text: a picture is described first when nothing was read from it yet.
  // The draft stays as it is; the Wiskit screen shows the context and asks with it.
  async function askWiskit() {
    const p = d.pic, draftId = d.id
    if (!p || busy) return
    if (!d.read && canRead) { await read(picKind(p) === 'image' ? 'describe' : 'digest'); if (err) return }
    if (!alive || d.id !== draftId) return
    const text = d.text.trim()
    if (!text) { err = t('capture.attachment.askText'); return }
    cap.ask = { label: p.name, text: text.slice(0, 8000) }
    languageWorkChanged()
    flush()
    go('#/jv')
  }

  async function read(how: 'digest' | 'describe') {
    const p = d.pic, id = d.id
    if (!p || busy) return
    const done = beginLanguageWork()
    busy = picKind(p) !== 'image' ? t('capture.attachment.readingFile', { name: p.name }) : how === 'digest' ? t('capture.attachment.readingImage') : t('capture.attachment.describing')
    err = ''
    try {
      const text = await source.readFile(await toPicked(p.blob, p.name, p.type), how)
      if (!alive || d.id !== id || d.pic !== p) { retainRead(id, p.name, text, how); return }
      d.text = joinText(d.text, text)
      d.read = how
      picNote = t('capture.attachment.textAdded')
    } catch (e) { err = t('capture.attachment.failed', { message: captureError(e) }) } finally { busy = ''; done() }
  }
  function useRecoveredRead(result: typeof cap.recoveredReads[number]) {
    d.text = joinText(d.text, result.text)
    if (d.id === result.draftId && d.pic?.name === result.name) d.read = result.how
    void keepDraft(d)
    clearRead(result.id)
  }
  function useRecoveredSuggestion(result: typeof cap.recoveredSuggestions[number]) {
    newMode = false
    d.collection = result.category
    if (result.tags) d.tags = mergeTags(d.tags, result.tags)
    void keepDraft(d)
    clearSuggestion(result.id)
  }
  async function useRecoveredFile(result: typeof cap.recoveredFiles[number]) {
    if (d.pic || applyingFile) return
    applyingFile = result.id
    try { if (await takeFiles([result.file])) clearFile(result.id) }
    finally { applyingFile = '' }
  }

  // ── Save ────────────────────────────────────────────────────────────────────
  // Save on the draft only opens the recap: nothing is created there either
  function toRecap() {
    if (!canGo || busy || saved) return
    flush()
    err = ''
    pvAll = false
    goTo('#/cap/save')
  }

  // where a note lives decides what "saved" means: the PC has it, or this phone holds it until it syncs
  const where = () => (source.kind === 'desktop' ? { state: 'synced' as const, detail: t('capture.outbox.pcSaved') }
    : solo ? { state: 'synced' as const, detail: t('capture.outbox.phoneSaved') }
      : { state: 'pending' as const, detail: t('capture.outbox.phonePending') })

  async function saveNote(s: Draft): Promise<Saved> {
    const p = pageOf(s, page)                               // the card the user saw, for this exact link
    const category = s.category || GENERAL
    if (s.target) {                                         // only the new section travels: the note's text stays as it is
      const m = await source.appendMyNote(s.target, notes.find(n => n.file === s.target)?.title ?? '', label(s), noteText(s, p))
      return { ...where(), title: t('capture.outbox.appendedTitle'), meta: t('capture.outbox.appendedMeta', { title: m.title }), page: section(s, undefined, p), file: m.file }
    }
    let m = s.made ? await source.myNote(s.made).catch(() => null) : null
    if (!m) {
      m = await source.createMyNote(titleFor(s, p), category)
      d.made = m.file                                       // a failure below keeps the draft, and the retry reuses this note
      await keepDraft(d)
    }
    const out = await source.saveMyNote(m.file, titleFor(s, p), category, newBody(s, p))
    return { ...where(), title: t('capture.outbox.newNoteTitle'), meta: t('capture.outbox.noteMeta', { category }), page: `${out.title}\n\n${newBody(s, p).trimEnd()}`, file: out.file }
  }

  async function saveLibrary(s: Draft): Promise<Saved> {
    // the collection the recap shows: the new name typed, the one picked, else where it started (never empty)
    const name = (newMode ? s.collection : s.collection || start).trim().slice(0, 80)
    const note = libraryNote(s)                             // the text around the link, then the comment
    const e = await box.save(linkOf(s.text), note, name, s.tags.trim(), source.kind === 'desktop' ? s.type : '')
    if (e.state === 'error') { if (e.id) await box.remove(e.id); throw new Error(e.error || t('capture.outbox.refused')) }
    // the PC already had it (this phone's rows were out of date): nothing was added, so the draft stays
    if (e.state === 'dup') throw new Error(t((e.itemId ?? 0) > 0 ? 'capture.outbox.duplicateId' : 'capture.outbox.duplicate', { id: e.itemId }))
    keepCollection(name)
    if (e.itemId && e.itemId > 0) patchRows([e.itemId])
    if ((e.itemId ?? 0) < 0 && e.state === 'sent') fillLinks([e.itemId!])
    const meta = t('capture.outbox.libraryMeta', { collection: name ? ' / ' + name : '', type: s.type && source.kind === 'desktop' ? ' · ' + captureType(s.type) : '', tags: s.tags.trim() ? ' · ' + s.tags.trim() : '' })
    const page = `${e.url}${note ? '\n\n' + note : ''}`
    if (e.state === 'waiting') return { state: 'pending', title: t('capture.outbox.libraryTitle'), detail: t('capture.outbox.waitingDetail'), meta, page }
    const where = (e.itemId ?? 0) > 0 ? t('capture.outbox.pcThumbnail') : solo ? t('capture.outbox.phoneSaved') : t('capture.outbox.pcLater')
    return { state: (e.itemId ?? 0) > 0 || solo ? 'synced' : 'pending', title: t('capture.outbox.libraryTitle'), detail: where, meta, page, itemId: e.itemId ?? undefined }
  }

  async function save() {
    if (!ok || busy || saved) return
    const done = beginLanguageWork()
    busy = 'Saving…'
    err = ''
    const s = { ...($state.snapshot(d) as Draft), dest }    // where the recap stands (a Library it cannot take is Note)
    const revision = captureRevision(s.id)
    try {
      const r = s.dest === 'library' ? await saveLibrary(s) : await saveNote(s)
      clearTimeout(timer)
      saved = r
      tail = null
      await dropDraftIfUnchanged(s.id, revision)
      loadNotes()
      if (phone.route.save) stepBack()                       // the result shows on the draft's page
      await tick()
      head?.focus()
    } catch (e) { err = e instanceof OutboxStorageError ? t('capture.linkStorageFailure') : t('capture.outbox.failed', { message: captureError(e) }) } finally { busy = ''; done() }
  }

  function discard() { clearTimeout(timer); dropDraft(d.id); fresh() }
  function fresh() {
    pop?.close()
    d = newDraft()
    pickOpen = false; newMode = false; q = ''; err = ''; picNote = ''; saved = null; sharedNote = ''; big = false; sure = ''; tail = null
    sureCat = false; picked = ''
    tick().then(() => area?.focus())
  }
  const ago = draftAgo
  const short = (u: string) => u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40) + (u.length > 48 ? '…' : '')
  const peek = (x: Draft) => (x.text.trim() || x.pic?.name || x.comment.trim() || t('capture.draft.empty')).replace(/\s+/g, ' ').slice(0, 34)
</script>

<!-- an attachment's actions and their confirm line: all of them on the draft, Read text and Describe on the recap -->
{#snippet acts(onRecap: boolean)}
  {@const img = picKind(d.pic) === 'image'}
  <div class="m-cap-quick" role="group" aria-label={t('capture.attachment.actions')} bind:this={quick}>
    {#if img || !d.read}<MButton class="m-cap-pill" aria-expanded={sure === 'digest'} disabled={!canRead || !!busy} onclick={() => (sure = sure === 'digest' ? '' : 'digest')}>{t('capture.attachment.read')}</MButton>{/if}
    {#if img}<MButton class="m-cap-pill" aria-expanded={sure === 'describe'} disabled={!canRead || !!busy} onclick={() => (sure = sure === 'describe' ? '' : 'describe')}>{t('processing.action.describe.label')}</MButton>{/if}
    {#if !onRecap}
      <MButton class="m-cap-pill" aria-expanded={sure === 'ask'} disabled={!canAsk || !!busy} onclick={() => (sure = sure === 'ask' ? '' : 'ask')}>{t('shell.askWiskitLabel')}</MButton>
      <MKey aria-label={t('capture.attachment.remove')} title={t('capture.attachment.remove')} disabled={!!busy} onclick={removePic}><ShellIcon name="bin" /></MKey>
    {/if}
  </div>
  {#if sure}
    <div class="m-cap-ask" role="group" aria-label={t('capture.attachment.confirm', { name: ASKS[sure].name })}>
      <p><b>{ASKS[sure].name}.</b> {ASKS[sure].says}</p>
      <div class="m-cap-ask-go">
        <MButton variant="pri" size="sm" bind:ref={goBtn} onclick={() => { const a = sure; sure = ''; if (a === 'ask') askWiskit(); else if (a) read(a) }}>{t('capture.attachment.continue')}</MButton>
        <MTextButton onclick={cancelAsk}>{t('common.cancel')}</MTextButton>
      </div>
    </div>
  {/if}
{/snippet}

<div class="m-cap-screen">
  {#if saved}
    {@const s = saved}
    <section class="m-cap-done" aria-labelledby="cap-done">
      <span class="m-cap-mark" aria-hidden="true">✓</span>
      <h2 id="cap-done" tabindex="-1" bind:this={head}>{s.title}</h2>
      <div class="m-row"><span class="m-badge" class:ok={s.state === 'synced'} class:wait={s.state === 'pending'} class:bad={s.state === 'failed'}>{saveStateLabel(s.state)}</span></div>
      <MHint as="p">{s.detail}</MHint>
      <div class="m-cap-page"><b>{s.meta}</b><pre>{s.page}</pre></div>
    </section>
    <footer class="m-cap-dock done">
      {#if s.file}<MButton class="m-cap-open" onclick={() => go(`#/mynotes/${encodeURIComponent(s.file ?? '')}`)}>{t('capture.outbox.openNote')}</MButton>{/if}
      {#if s.itemId && s.itemId > 0}<MButton class="m-cap-open" onclick={() => go(`#/item/${s.itemId}`)}>{t('capture.outbox.openCard')}</MButton>{/if}
      <MKey size="mid" tone="add" aria-label={t('capture.outbox.addAnother')} title={t('capture.outbox.addAnother')} onclick={fresh}><ShellIcon name="plus" /></MKey>
    </footer>
  {:else if recap}
    <form class="m-cap-form" onsubmit={e => { e.preventDefault(); save() }}>
      <section class="m-cap-recap" aria-labelledby="cap-pv">
        <h2 class="m-lbl m-cap-kick" id="cap-pv" tabindex="-1" bind:this={pvHead}>{t('capture.recap.preview')}</h2>
        {#if dest === 'library'}
          <div class="m-cap-pv m-cap-pv-lib" role="group" aria-label={t('capture.recap.libraryItem')}>
            {#if info?.image}<img src={info.image} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={e => ((e.currentTarget as HTMLImageElement).hidden = true)} />{/if}
            <div>
              <div class="m-cap-flags"><span class="m-badge ok">{t('capture.recap.newLibrary')}</span>{#if !phone.reachable && !solo}<span class="m-badge wait">{t('capture.recap.waitsPc')}</span>{/if}</div>
              <b class="m-cap-pv-title">{info?.title || short(link)}</b>
              {#if byline}<small>{byline}</small>{/if}
              <dl class="m-cap-kv">
                <dt>{t('item.collection')}</dt><dd>{collectionShown}</dd>
                {#if source.kind === 'desktop' && d.type}<dt>{t('capture.destination.type')}</dt><dd>{captureType(d.type)}</dd>{/if}
                {#if d.tags.trim()}<dt>{t('item.info.tags')}</dt><dd>{d.tags.trim()}</dd>{/if}
                {#if libNote}<dt>{t('notes.editor.note')}</dt><dd>{libNote}</dd>{/if}
              </dl>
            </div>
          </div>
          <MHint as="p" class="m-cap-says">{t(info ? 'capture.recap.pageLibraryHelp' : 'capture.recap.libraryHelp')}</MHint>
        {:else}
          <div class="m-cap-pv" role="group" aria-label={t(d.target ? 'capture.recap.noteAddition' : 'capture.recap.newNoteAria')}>
            <div class="m-cap-pv-head"><span class="m-cap-cat">{d.target ? target?.category || GENERAL : category}</span><span class="m-sp"></span><span class="m-cap-pv-kind">{t(d.target ? 'capture.recap.addsToNote' : 'notes.new')}</span></div>
            <b class="m-cap-pv-title">{d.target ? target?.title ?? t('capture.recap.yourNote') : titleFor(d, info)}</b>
            <div class="m-cap-pv-body" class:m-cap-all={pvAll} class:m-cap-cut={pvLong && !pvAll} bind:this={pvBody}>{#if pvTail}<span class="m-cap-pv-old">{pvTail}</span>{/if}{#if d.target}<span class="m-cap-pv-new">{pvText}</span>{:else if pvText}{pvText}{:else}<span class="m-cap-pv-wait">{t(picKind(d.pic) === 'image' ? 'capture.recap.pictureText' : 'capture.recap.documentText')}</span>{/if}</div>
            {#if pvLong}<MTextButton aria-expanded={pvAll} onclick={() => (pvAll = !pvAll)}>{t(pvAll ? 'capture.recap.less' : 'capture.recap.all')}</MTextButton>{/if}
          </div>
          {#if d.target}<MHint as="p" class="m-cap-says">{t('capture.recap.appendHelp')}</MHint>{/if}
        {/if}

        {#if d.pic}
          <!-- a picture: its thumbnail with its name, its line and its buttons over it; a document: its kind, then its line -->
          <div class="m-cap-att" class:m-cap-shot={!!picUrl} role="presentation" onkeydown={e => { if (e.key === 'Escape' && sure) { e.stopPropagation(); cancelAsk() } }}>
            {#if picUrl}<img src={picUrl} alt="" />{:else}<span class="m-cap-kind" aria-hidden="true">{KIND_TAG[picKind(d.pic)] ?? 'FILE'}</span>{/if}
            <div>
              <div><b>{d.pic.name}</b><MHint as="p" role="status">{busy && busy !== 'Saving…' ? busy : !d.read && !canRead ? readHelp : attLine(d, captureText)}</MHint></div>
              {#if !d.read}{@render acts(true)}{/if}
            </div>
          </div>
        {/if}

        <fieldset class="m-cap-where">
          <legend class="m-lbl m-cap-kick">{t('capture.destination.where')}</legend>
          <div class="m-cap-dest" class:m-cap-on={dest === 'note'} role="presentation" onkeydown={e => { if (e.key === 'Escape' && pickOpen) pickOpen = false }}>
            <label class="m-cap-choice"><input type="radio" name="cap-dest" value="note" checked={dest === 'note'} aria-describedby={dest === 'note' ? undefined : 'cap-note-hint'} onchange={() => (d.dest = 'note')} /><b>{t('notes.editor.note')}</b></label>
            {#if dest === 'note'}
              <div class="m-cap-commit">
                <div class="m-cap-chip m-cap-destination" class:fresh={!d.target}>
                  <i>{t('capture.destination.addTo')}</i>
                  <button type="button" aria-haspopup="listbox" aria-expanded={pickOpen} aria-label={t('capture.destination.noteToAdd')} onclick={() => (pickOpen = !pickOpen)}><span>{d.target ? target?.title ?? t('capture.recap.yourNote') : t('notes.new')}</span><ShellIcon name="down" /></button>
                </div>
                {#if d.target}
                  <div class="m-cap-chip fixed m-cap-category"><i>{t('notes.category')}</i><b><span>{target?.category || GENERAL}</span></b></div>
                {:else}
                  <div class="m-cap-chip m-cap-category"><i>{t('notes.category')}</i>
                    <MPicker label={t('notes.category')} value={category} options={categoryOptions} onchange={value => (d.category = value)}><span>{category}</span><ShellIcon name="down" /></MPicker>
                  </div>
                {/if}
              </div>
              {#if pickOpen}
                <div class="m-cap-menu" bind:this={menu}>
                  <button type="button" class="m-cap-new" aria-pressed={!d.target} onclick={() => { d.target = ''; pickOpen = false }}>{t('capture.destination.newNoteOption')}</button>
                  <label class="m-fld"><span class="m-pr">?</span><input type="search" bind:value={q} aria-label={t('capture.destination.searchNotes')} placeholder={t('capture.destination.searchNotes')} /></label>
                  <div class="m-cap-notes" role="listbox" aria-label={t('shell.route.notes')}>
                    {#each shown as n (n.file)}
                      <button type="button" class="m-cap-note" role="option" aria-selected={d.target === n.file} onclick={() => { d.target = n.file; pickOpen = false }}><span><b>{n.title}</b><small>{n.category}{n.file === suggested ? t('capture.destination.suggested') : ''}</small></span></button>
                    {:else}
                      <div class="m-empty">{t(q ? 'capture.destination.noMatch' : 'capture.destination.noNotes')}</div>
                    {/each}
                  </div>
                </div>
              {/if}
            {:else}
              <small class="m-cap-why" id="cap-note-hint">{noteHint(d, info, captureText)}</small>
            {/if}
          </div>
          <div class="m-cap-dest" class:m-cap-on={dest === 'library'} class:m-cap-blocked={!!block} role="presentation" onkeydown={e => { if (e.key === 'Escape' && sureCat) { e.stopPropagation(); cancelSuggest() } }}>
            <label class="m-cap-choice"><input type="radio" name="cap-dest" value="library" checked={dest === 'library'} disabled={!!block} aria-describedby={dest === 'library' ? undefined : 'cap-lib-hint'} onchange={() => (d.dest = 'library')} /><b>{t('shell.route.library')} <span class="sr">{t('capture.destination.item')}</span></b></label>
            {#if dest === 'library'}
              <div class="m-cap-commit">
                <div class="m-cap-chip m-cap-category"><i>{t('item.collection')}</i>
                  <MPicker label={t('item.collection')} value={newMode ? NEW : collection} options={collectionOptions}
                    onchange={value => { newMode = value === NEW; d.collection = newMode ? '' : value; picked = '' }}><span>{collectionName}</span><ShellIcon name="down" /></MPicker>
                </div>
                {#if canSuggest}<MButton class="m-cap-suggest" aria-expanded={sureCat} disabled={asking || !!busy} bind:ref={suggestKey} onclick={() => (sureCat = !sureCat)}>{t(asking ? 'capture.suggest.asking' : 'capture.suggest.name')}</MButton>{/if}
              </div>
              {#if sureCat}
                <div class="m-cap-ask" role="group" aria-label={t('capture.attachment.confirm', { name: t('capture.suggest.name') })}>
                  <p><b>{t('capture.suggest.name')}.</b> {t('capture.suggest.says')}</p>
                  <div class="m-cap-ask-go">
                    <MButton variant="pri" size="sm" bind:ref={catGo} onclick={suggest}>{t('capture.attachment.continue')}</MButton>
                    <MTextButton onclick={cancelSuggest}>{t('common.cancel')}</MTextButton>
                  </div>
                </div>
              {/if}
              {#if picked}<MHint as="p" role="status">{picked}</MHint>{/if}
              {#if newMode}<label class="m-cap-chip m-cap-field"><i>{t('capture.destination.newCollection')}</i><input bind:value={d.collection} maxlength="80" aria-label={t('capture.destination.collectionName')} placeholder={t('capture.destination.nameCollection')} /></label>{/if}
              {#if source.kind === 'desktop'}
                <div class="m-cap-chip"><i>{t('capture.destination.type')}</i>
                  <MPicker label={t('capture.destination.type')} value={captureType(d.type)} options={typeOptions} onchange={value => (d.type = value)}><span>{d.type ? captureType(d.type) : t('capture.destination.automatic')}</span><ShellIcon name="down" /></MPicker>
                </div>
              {/if}
              <label class="m-cap-chip m-cap-field"><i>{t('item.info.tags')}</i><input bind:value={d.tags} aria-label={t('item.info.tags')} placeholder={t('capture.destination.tagsPlaceholder')} /></label>
            {:else}
              <small class="m-cap-why" id="cap-lib-hint">{block || libraryHint(d, captureText)}</small>
            {/if}
          </div>
        </fieldset>
      </section>

      <div class="m-cap-say">
        {#if err}<p class="m-err" role="alert">{err}</p>{/if}
        <MHint as="small" id="cap-help">{help}</MHint>
      </div>

      <footer class="m-cap-dock">
        <label class="m-cap-chip m-cap-field m-cap-comment"><i>{t('capture.destination.comment')}</i><input id="cap-comment" bind:value={d.comment} aria-label={t('capture.destination.comment')} placeholder={t('capture.destination.commentPlaceholder')} /></label>
        <MKey size="mid" tone="add" type="submit" class="m-cap-save" aria-label={t(dest === 'library' ? 'capture.destination.saveLibrary' : d.target ? 'capture.destination.saveAddition' : 'capture.destination.saveNote')} aria-describedby="cap-help" aria-busy={busy === 'Saving…'} disabled={!ok || !!busy}><ShellIcon name="check" /></MKey>
      </footer>
    </form>
  {:else}
    <form class="m-cap-form" onsubmit={e => { e.preventDefault(); toRecap() }}>
      <input type="file" accept={ACCEPT} hidden bind:this={input} onchange={chosen} />
      <input type="file" accept="image/*" hidden bind:this={photos} onchange={chosen} />
      <section class="m-cap-editor" aria-label={t('capture.draft.yourCapture')}>
        <div class="m-cap-heading">
          <label class="sr" for="cap-title">{t('capture.draft.title')}</label><input id="cap-title" class="m-cap-title" bind:value={d.title} maxlength="80" aria-label={t('capture.draft.title')} placeholder={titleFor({ ...d, title: '' }, info)} />
          <MInfo title={t('capture.draft.addingContent')}>
            <p>{origin} {sourceHelp(d, info, captureText)}</p>
            <p>{t('capture.attachment.pdfPrivacy')}</p>
            <p>{t('capture.attachment.imagePrivacy')}</p>
          </MInfo>
        </div>
        {#if sharedNote}<span class="m-badge ok" role="status">{sharedNote}</span>{/if}
        {#each cap.recoveredReads as result (result.id)}
          <MHint role="status">{t('capture.recoveredRead', { name: result.name })}</MHint>
          <div class="m-row"><MButton size="sm" onclick={() => useRecoveredRead(result)}>{t('capture.useRecoveredRead')}</MButton><MButton size="sm" onclick={() => clearRead(result.id)}>{t('capture.discardRecoveredRead')}</MButton></div>
        {/each}
        {#each cap.recoveredSuggestions as result (result.id)}
          <MHint role="status">{t('capture.recoveredSuggestion', { category: result.category })}</MHint>
          <div class="m-row"><MButton size="sm" onclick={() => useRecoveredSuggestion(result)}>{t('capture.useRecoveredSuggestion')}</MButton><MButton size="sm" onclick={() => clearSuggestion(result.id)}>{t('capture.discardRecoveredSuggestion')}</MButton></div>
        {/each}
        {#each cap.recoveredFiles as result (result.id)}
          <MHint role="status">{t('capture.recoveredFile', { name: result.file.name })}</MHint>
          {#if d.pic}<MHint>{t('capture.removeAttachmentFirst')}</MHint>{/if}
          <div class="m-row"><MButton size="sm" disabled={!!d.pic || !!busy || !!applyingFile} onclick={() => useRecoveredFile(result)}>{t('capture.useRecoveredFile')}</MButton><MButton size="sm" disabled={!!applyingFile} onclick={() => clearFile(result.id)}>{t('capture.discardRecoveredFile')}</MButton></div>
        {/each}
        <label class="sr" for="cap-text">{t('capture.draft.yourContent')}</label>
        <div class="m-fld ta m-cap-paper">
          <textarea id="cap-text" bind:this={area} bind:value={d.text} onpaste={pasted} placeholder={t('capture.draft.placeholder')} rows="12"></textarea>
          {#if empty && !cap.recoveredReads.length && !cap.recoveredSuggestions.length && !cap.recoveredFiles.length}
            <div class="m-cap-hello">
              <b>{t('capture.draft.addBrainamon')}</b>
              <small>{t('capture.draft.hello')}</small>
              <a class="m-cap-try" href="#/import" aria-label={t('imports.title')} title={t('capture.draft.importTitle')}><i>{t('capture.draft.try')}</i><span>{t('capture.draft.importSites')}</span></a>
            </div>
          {/if}
        </div>
        {#if info}
          <div class="m-cap-link" role="group" aria-label={t('capture.draft.pageSays')}>
            {#if info.image}<img src={info.image} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={e => ((e.currentTarget as HTMLImageElement).hidden = true)} />{/if}
            <div><b>{info.title || info.creator || siteOf(info.url)}</b>{#if info.desc}<p>{info.desc}</p>{/if}</div>
          </div>
        {/if}

        {#if d.pic}
          <div class="m-cap-pic" class:big role="presentation" onkeydown={e => { if (e.key === 'Escape' && sure) { e.stopPropagation(); cancelAsk() } }}>
            {#if picUrl}<button type="button" class="m-cap-thumb" aria-expanded={big} aria-label={t(big ? 'capture.attachment.small' : 'capture.attachment.large')} onclick={() => (big = !big)}><img src={picUrl} alt={t('capture.attachment.preview')} /></button>{/if}
            <div><b>{d.pic.name}</b><MHint as="p" role="status">{busy && busy !== 'Saving…' ? busy : !canRead ? readHelp : picNote}</MHint></div>
            {@render acts(false)}
          </div>
        {/if}
      </section>

      <div class="m-cap-say">
        {#if err}<p class="m-err" role="alert">{err}</p>{/if}
        <MHint as="small" id="cap-help">{draftHelp(d, captureText)}</MHint>
      </div>

      <footer class="m-cap-dock">
        <div class="m-cap-actions">
          <MKey aria-label={t('capture.attachment.photo')} title={t('capture.attachment.photo')} disabled={!!busy} onclick={() => photos?.click()}><ShellIcon name="photo" /></MKey>
          <MKey aria-label={t('imports.file.label')} title={t('imports.file.label')} disabled={!!busy} onclick={() => input?.click()}><ShellIcon name="file" /></MKey>
          <MKey aria-label={t('capture.draft.paste')} title={t('capture.draft.paste')} disabled={!!busy} onclick={pasteClip}><ShellIcon name="paste" /></MKey>
        </div>
        <span class="m-sp"></span>
        <MKey size="mid" tone="add" type="submit" class="m-cap-save" aria-label={t('common.save')} title={t('common.save')} aria-describedby="cap-help" disabled={!canGo || !!busy}><ShellIcon name="check" /></MKey>
      </footer>
    </form>
  {/if}

  <dialog class="m-cap-pop" bind:this={pop} aria-labelledby="cap-pop-title" onpointerdown={outside} onclose={() => (capUi.open = false)}>
    <div class="m-cap-pop-body">
      <h2 id="cap-pop-title">{t('shell.captureTray')}</h2>
      <a class="m-cap-imp" href="#/import" aria-label={t('imports.title')} title={t('capture.draft.importTitle')} onclick={() => pop?.close()}><i aria-hidden="true"><ShellIcon name="import" /></i><span><b>{t('imports.title')}</b><small>{t('capture.draft.fromSites')}</small></span><span class="m-cap-go" aria-hidden="true"><ShellIcon name="back" /></span></a>
      {#if others.length}
        <div class="m-cap-drafts" role="group" aria-labelledby="cap-drafts-title">
          <span class="m-lbl" id="cap-drafts-title">{t('capture.draft.others', { n: others.length })}</span>
          {#each others as x (x.id)}<button type="button" class="m-cap-draft" onclick={() => show(x)}><b>{peek(x)}</b><small>{t(x.origin === 'typed' ? 'capture.draft.typed' : 'capture.draft.shared')} · {ago(x.at)}</small></button>{/each}
        </div>
      {/if}
      {#if !saved && (d.text || d.comment || d.pic)}<MTextButton tone="danger" onclick={discard}>{t('capture.draft.discard')}</MTextButton>{/if}
    </div>
  </dialog>
</div>

{#if over}
  <div class="m-cap-over" aria-hidden="true"><div><b>{t('capture.attachment.drop')}</b><p>{t('capture.attachment.release')}</p><small>{t('capture.attachment.oneAtTime')}</small></div></div>
{/if}
