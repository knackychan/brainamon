<script lang="ts">
  // The phone's My Notes editor (projects/note-organic-ui/plans/07-phone-editor.md): the round 2 dot
  // paper as a full-bleed sheet, reusing the desktop's Markdown adapter (note-editor.ts) and format
  // (note-format.ts) so there is no second serializer. Unsupported Markdown falls back to a raw
  // textarea, as the desktop's Markdown mode does. Autosave lives in Notes.svelte; this component
  // only emits body/stamp changes and title/category bindings.
  import { onMount } from 'svelte'
  import { INKS, MARKS, type Ink, type Stamp } from '../../lib/note-format'
  import { mergeRuns, orderedSelection, parseMarkdown, readDOM, rememberSelection, restoreSelection,
    serializeMarkdown, sliceRuns, writeDOM, headingName, type Block, type Selection } from '../../lib/note-editor'
  import Voice from '../Voice.svelte'
  import NoteStamps from './NoteStamps.svelte'
  import MButton from '../ui/MButton.svelte'

  let { file, title = $bindable(''), category = $bindable(''), categories, body, stamps, revision, updated,
    status, savedAt, focusTitle = $bindable(false), onbody, onstamps, onvoice, onqueued, onobsidian, ondelete, onedit }: {
    file: string; title?: string; category?: string; categories: string[]; body: string; stamps: Stamp[]; revision: number; updated: string
    status: 'saved' | 'pending' | 'saving' | 'error'; savedAt: string; focusTitle?: boolean
    onbody: (body: string) => void; onstamps: (stamps: Stamp[]) => void
    onvoice: (text: string) => void; onqueued: () => void
    onobsidian: () => void; ondelete: () => void; onedit: () => void
  } = $props()

  let editor = $state<HTMLDivElement>()!
  let page = $state<HTMLDivElement>()!
  let titleEl = $state<HTMLTextAreaElement>()!
  let stampTools = $state<NoteStamps>()!
  let localBody = $state('')
  let reason = $state('')
  let error = $state('')
  let composing = false
  let saved: Selection | null = null
  let pending: string[] | null = null
  let active = $state<string[]>([])
  let blockStyle = $state('p')
  let heading = $state('top')
  let ink: Ink = $state('indigo')
  let mark = $state('sun')
  let strip = $state<'style' | 'ink' | 'mark' | null>(null)
  let tray = $state(false)
  let menu = $state(false)
  let selected = $state<number | null>(null)
  type Snapshot = { body: string; stamps: Stamp[]; selection: Selection | null }
  let history: Snapshot[] = []
  let cursor = $state(0)
  let historyLength = $state(1)
  let lastKind = '', lastTime = 0, seenRevision = -1
  const parsed = $derived(parseMarkdown(localBody))

  const icons: Record<string, string> = {
    undo: 'M7.5 4.5 4 8l3.5 3.5M4 8h8.5a3.5 3.5 0 0 1 0 7H10',
    redo: 'M12.5 4.5 16 8l-3.5 3.5M16 8H7.5a3.5 3.5 0 0 0 0 7H10',
    marker: 'm12.4 2.8 4.3 4.3-6.8 6.8H5.6v-4.3zM9.6 5.6l4.3 4.3',
    check: 'M2.5 3.2h5.5v5.5H2.5ZM3.9 6l1.2 1.2 2.2-2.6M2.5 11.3h5.5v5.5H2.5ZM11 6h6.5M11 14h6.5',
    ul: 'M8 5.5h9M8 10h9M8 14.5h9',
    ol: 'M9 6h8M9 14h8M3.4 4.2 4.8 3.4v5M3.2 12.2c.3-.8 2.4-.9 2.4.4 0 1-2.4 1.9-2.4 3h2.6',
    stamps: 'M10 2.5c.6 4.2 2.4 6 6.5 6.5-4.1.6-5.9 2.4-6.5 6.5-.6-4.1-2.4-5.9-6.5-6.5 4.1-.5 5.9-2.3 6.5-6.5zM16 14v4M14 16h4',
    done: 'm5 8 5 5 5-5',
    divider: 'M3 10h.01M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01',
    clear: 'm11.2 3.6 5.2 5.2-7 7H5.6l-2-2a1.4 1.4 0 0 1 0-2zM7.8 7l5.2 5.2M10 15.8h7',
  }
  const BLOCKS: [string, string][] = [['h1', 'Title'], ['h2', 'Heading'], ['h3', 'Subheading'], ['p', 'Text'], ['quote', 'Quote']]

  const when = (s: string) => (s ? new Date(s).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) : '')
  const words = $derived(localBody.trim() ? localBody.trim().split(/\s+/).length : 0)
  const metaLine = $derived(`${when(updated)} · ${words} word${words === 1 ? '' : 's'} · ${stamps.length} stamp${stamps.length === 1 ? '' : 's'}`)
  const lamp = $derived({ saved: `Saved ${savedAt}`, pending: 'Editing…', saving: 'Saving…', error: 'Save failed' }[status])

  function snapshot(): Snapshot { return { body: localBody, stamps: stamps.map(s => ({ ...s })), selection: saved ? structuredClone(saved) : null } }
  function reset() {
    const result = parseMarkdown(localBody)
    reason = result.ok ? '' : result.reason
    if (result.ok && editor) writeDOM(editor, result.blocks)
    saved = null; pending = null; active = []; selected = null; strip = null; tray = false; menu = false; error = ''
    history = [snapshot()]; cursor = 0; historyLength = 1; lastKind = ''; lastTime = 0
  }
  $effect(() => {
    if (!editor) return
    if (seenRevision !== revision || body !== localBody) {
      seenRevision = revision; localBody = body; reset()
    }
  })
  function record(kind: string) {
    const next = snapshot(), prev = history[cursor]
    if (prev && prev.body === next.body && JSON.stringify(prev.stamps) === JSON.stringify(next.stamps)) return
    const now = performance.now()
    if (kind === 'typing' && lastKind === kind && now - lastTime < 750 && cursor > 0) history[cursor] = next
    else { history = history.slice(0, cursor + 1); history.push(next); cursor++ }
    historyLength = history.length; lastKind = kind; lastTime = now
  }
  function beforeMutation() { if (history[cursor]) history[cursor].selection = saved ? structuredClone(saved) : null }
  function emit(next: string, kind: string) {
    localBody = next
    const result = parseMarkdown(next); reason = result.ok ? '' : result.reason
    onbody(next); record(kind)
  }
  function collect(kind = 'typing') {
    if (composing) return
    try {
      saved = rememberSelection(editor) || saved
      const next = serializeMarkdown(readDOM(editor))
      error = ''; emit(next, kind); selectionChanged()
    } catch (e) {
      error = (e as Error).message
      const last = parseMarkdown(localBody)
      if (last.ok) { writeDOM(editor, last.blocks); restoreSelection(editor, saved) }
    }
  }
  function selectionChanged() {
    if (!editor || composing) return
    const current = rememberSelection(editor)
    if (!current) return
    if (saved && JSON.stringify(saved) !== JSON.stringify(current)) pending = null
    saved = current
    const blocks = readDOM(editor), p = current.focus, b = blocks[p.block]
    if (!b) return
    active = pending || sliceRuns(b.runs, Math.max(0, p.offset - 1), p.offset || 1)[0]?.marks || []
    blockStyle = b.kind
    heading = 'top'
    for (let i = 0; i <= p.block; i++) if (/^h[123]$/.test(blocks[i].kind)) heading = headingName(blocks[i].runs.map(r => r.text).join(''))
  }
  onMount(() => {
    document.addEventListener('selectionchange', selectionChanged)
    document.documentElement.classList.add('np-ed')
    if (focusTitle) { titleEl?.focus(); focusTitle = false }
    return () => { document.removeEventListener('selectionchange', selectionChanged); document.documentElement.classList.remove('np-ed'); saved = null; history = [] }
  })
  function selection(): Selection {
    return saved || { anchor: { block: 0, offset: 0 }, focus: { block: 0, offset: 0 } }
  }
  function mutate(blocks: Block[], sel: Selection, kind: string) {
    beforeMutation(); writeDOM(editor, blocks); saved = sel
    restoreSelection(editor, sel); collect(kind)
  }
  function format(markName: string) {
    if (!parsed.ok || composing) return
    const sel = selection(), [start, end] = orderedSelection(sel)
    if (start.block === end.block && start.offset === end.offset) {
      const base = pending || active
      pending = markName === 'clear' ? [] : base.includes(markName) ? base.filter(m => m !== markName) : [...base.filter(m => !markName.includes(':') || !m.startsWith(markName.split(':')[0] + ':')), markName]
      active = pending; restoreSelection(editor, sel); return
    }
    const blocks = readDOM(editor)
    const selectedRuns = blocks.slice(start.block, end.block + 1).flatMap((b, i) => sliceRuns(b.runs, i === 0 ? start.offset : 0, start.block + i === end.block ? end.offset : Infinity))
    const remove = selectedRuns.length > 0 && selectedRuns.every(r => r.marks.includes(markName))
    for (let i = start.block; i <= end.block; i++) {
      const b = blocks[i], from = i === start.block ? start.offset : 0, to = i === end.block ? end.offset : Infinity
      b.runs = mergeRuns([...sliceRuns(b.runs, 0, from), ...sliceRuns(b.runs, from, to).map(r => ({ ...r, marks: markName === 'clear' ? [] : remove ? r.marks.filter(m => m !== markName) : [...r.marks.filter(m => !markName.includes(':') || !m.startsWith(markName.split(':')[0] + ':')), markName] })), ...sliceRuns(b.runs, to)])
    }
    pending = null; mutate(blocks, sel, 'format')
  }
  function block(kind: string) {
    if (composing) return
    const sel = selection(), [start, end] = orderedSelection(sel), blocks = readDOM(editor)
    for (let i = start.block; i <= end.block; i++) blocks[i] = { ...blocks[i], kind, ...(kind === 'task' ? { checked: false } : {}), ...(kind === 'number' ? { number: i - start.block + 1 } : {}) }
    mutate(blocks, sel, 'format')
  }
  function divider() {
    const sel = selection(), blocks = readDOM(editor), index = sel.focus.block + 1
    blocks.splice(index, 0, { kind: 'hr', runs: [] }, { kind: 'p', runs: [] })
    const p = { block: index + 1, offset: 0 }; mutate(blocks, { anchor: p, focus: p }, 'format')
  }
  function insert(text: string, kind: string, marks = pending || active) {
    const blocks = readDOM(editor), [start, end] = orderedSelection(selection())
    const first = blocks[start.block] || { kind: 'p', runs: [] }, last = blocks[end.block] || first
    const before = sliceRuns(first.runs, 0, start.offset), after = sliceRuns(last.runs, end.offset)
    const lines = text.replace(/\r\n?/g, '\n').split('\n')
    const added = lines.map((line, i) => ({ ...first, checked: i ? false : first.checked,
      number: first.kind === 'number' ? (first.number || 1) + i : undefined,
      runs: mergeRuns([...(i === 0 ? before : []), { text: line, marks: [...marks] }, ...(i === lines.length - 1 ? after : [])]) }))
    blocks.splice(start.block, end.block - start.block + 1, ...added)
    const point = { block: start.block + lines.length - 1, offset: (lines.length === 1 ? start.offset : 0) + lines.at(-1)!.length }
    mutate(blocks, { anchor: point, focus: point }, kind)
  }
  function enter() {
    const blocks = readDOM(editor), sel = selection(), [start, end] = orderedSelection(sel), b = blocks[start.block]
    if (start.block === end.block && !b.runs.map(r => r.text).join('') && ['bullet', 'number', 'task', 'quote'].includes(b.kind)) { block('p'); return }
    insert('\n', 'enter', [])
    const next = readDOM(editor), current = next[start.block + 1]
    if (current && /^h[123]$/.test(current.kind)) { current.kind = 'p'; mutate(next, selection(), 'enter') }
    pending = null
  }
  function prefix() {
    const s = rememberSelection(editor)
    if (!s || s.anchor.block !== s.focus.block || s.anchor.offset !== s.focus.offset) return
    const blocks = readDOM(editor), b = blocks[s.focus.block]
    if (b?.kind !== 'p' || b.runs.some(r => r.marks.length)) return
    const text = b.runs.map(r => r.text).join('')
    const kind = ({ '- ': 'bullet', '1. ': 'number', '[] ': 'task', '# ': 'h1', '## ': 'h2', '> ': 'quote' } as Record<string, string>)[text]
    if (!kind || s.focus.offset !== text.length) return
    b.kind = kind; b.runs = []; b.checked = false; b.number = 1
    const point = { block: s.focus.block, offset: 0 }
    mutate(blocks, { anchor: point, focus: point }, 'prefix')
  }
  function input(e: InputEvent) {
    if (composing || e.isComposing) return
    if (e.inputType === 'insertText') prefix()
    collect(e.inputType === 'insertFromPaste' ? 'paste' : 'typing')
  }
  function beforeInput(e: InputEvent) {
    if (composing || e.isComposing) return
    saved = rememberSelection(editor) || saved; beforeMutation()
    if (e.inputType === 'historyUndo' || e.inputType === 'historyRedo') { e.preventDefault(); undo(e.inputType === 'historyRedo' ? 1 : -1) }
    else if (e.inputType === 'insertParagraph' || e.inputType === 'insertLineBreak') { e.preventDefault(); enter() }
    else if (e.inputType.startsWith('format')) e.preventDefault()
    else if (e.inputType === 'insertText' && pending && e.data) { e.preventDefault(); insert(e.data, 'typing'); prefix() }
  }
  function paste(e: ClipboardEvent) {
    e.preventDefault(); if (composing) return
    saved = rememberSelection(editor) || saved
    insert(e.clipboardData?.getData('text/plain') || '', 'paste', [])
  }
  function undo(direction: number) {
    if (composing) return
    const next = cursor + direction
    if (next < 0 || next >= history.length) return
    cursor = next
    const state = history[cursor]
    localBody = state.body; saved = state.selection; pending = null; selected = null; lastKind = ''
    const result = parseMarkdown(localBody); reason = result.ok ? '' : result.reason
    if (result.ok) writeDOM(editor, result.blocks)
    onbody(localBody)
    // only a step that changes the stamps sends them: a text-only undo keeps the stored stamps line
    if (JSON.stringify(state.stamps) !== JSON.stringify(stamps)) onstamps(state.stamps.map(s => ({ ...s })))
    if (result.ok) { restoreSelection(editor, saved); selectionChanged() }
  }
  function historyKey(e: KeyboardEvent) {
    if (e.isComposing || composing || (e.target as HTMLElement).closest('#nt-title')) return
    if ((e.ctrlKey || e.metaKey) && ['z', 'y'].includes(e.key.toLowerCase())) {
      e.preventDefault(); e.stopPropagation(); undo(e.key.toLowerCase() === 'y' || e.shiftKey ? 1 : -1)
    }
  }
  function keys(e: KeyboardEvent) {
    if (e.isComposing || composing) return
    if ((e.ctrlKey || e.metaKey) && ['b', 'i', 'u'].includes(e.key.toLowerCase())) { e.preventDefault(); format(e.key.toLowerCase()) }
    if (e.key === 'Escape') { strip = null; tray = false; menu = false; selected = null }
  }
  function task(e: MouseEvent) {
    selected = null
    const button = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-task]')
    if (button) {
      beforeMutation(); button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true')); collect('task')
    }
  }
  function stampChange(next: Stamp[]) {
    beforeMutation(); onstamps(next)
    const state = snapshot(); state.stamps = next.map(s => ({ ...s }))
    history = history.slice(0, cursor + 1); history.push(state); cursor++; historyLength = history.length; lastKind = 'stamp'
  }
  function setInk(c: string) {
    ink = c as Ink
    if (selected != null) stampTools.change({ c: ink })
    else format(`ink:${c}`)
  }
  function setMark(c: string) {
    if (c === 'none') {
      const sel = selection(), [start, end] = orderedSelection(sel), blocks = readDOM(editor)
      if (start.block === end.block && start.offset === end.offset) { pending = active.filter(m => !m.startsWith('mark:')); active = pending }
      else {
        for (let i = start.block; i <= end.block; i++) {
          const b = blocks[i], from = i === start.block ? start.offset : 0, to = i === end.block ? end.offset : Infinity
          b.runs = [...sliceRuns(b.runs, 0, from), ...sliceRuns(b.runs, from, to).map(r => ({ ...r, marks: r.marks.filter(m => !m.startsWith('mark:')) })), ...sliceRuns(b.runs, to)]
        }
        mutate(blocks, sel, 'format')
      }
    } else { mark = c; format(`mark:${c}`) }
  }
  function run(cmd: string) {
    if (cmd === 'check') { block(blockStyle === 'task' ? 'p' : 'task'); return }
    if (cmd === 'ul') { block(blockStyle === 'bullet' ? 'p' : 'bullet'); return }
    if (cmd === 'ol') { block(blockStyle === 'number' ? 'p' : 'number'); return }
    if (cmd === 'hr') { divider(); return }
    if (cmd === 'clear') { format('clear'); return }
    if (cmd === 'bold') format('b'); else if (cmd === 'italic') format('i')
    else if (cmd === 'underline') format('u'); else if (cmd === 'strikeThrough') format('s')
  }
  function toast(text: string) {
    const host = document.getElementById('np-toasts')
    if (!host) return
    const t = document.createElement('div'); t.className = 'np-toast'; t.textContent = text
    host.append(t); setTimeout(() => t.remove(), 3600)
  }
  function titled() {
    const stamp = new Date().toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
    const trimmed = localBody.replace(/\s+$/, '')
    const next = (trimmed ? trimmed + '\n\n' : '') + `## ${stamp}\n\n`
    const result = parseMarkdown(next)
    if (result.ok && editor) writeDOM(editor, result.blocks)
    emit(next, 'dated')
    if (result.ok) editor?.focus({ preventScroll: true })
  }
  function more(on: boolean) {
    menu = on
    if (on) { document.activeElement && (document.activeElement as HTMLElement).blur(); strip = null; tray = false }
  }
  const editing = () => document.activeElement === editor || document.activeElement === titleEl
  onMount(() => {
    if (sessionStorage.getItem('bp-record-note') === file) menu = true
    const on = () => document.documentElement.classList.toggle('typing', editing())
    const off = () => setTimeout(on, 0)
    document.addEventListener('focusin', on); document.addEventListener('focusout', off)
    return () => { document.removeEventListener('focusin', on); document.removeEventListener('focusout', off) }
  })
</script>

{#snippet icon(name: string)}<svg viewBox="0 0 20 20" aria-hidden="true"><path d={icons[name]} /></svg>{/snippet}

<section class="np" aria-label="Note">
  <div class="np-head">
    <label class="np-pill"><span class="sr">Category</span>
      <select bind:value={category} onchange={onedit}>{#each categories as c (c)}<option value={c}>{c}</option>{/each}</select>
    </label>
    <small class="np-led" data-s={status} aria-live="polite"><i></i><span>{lamp}</span></small>
    <span class="m-sp"></span>
    <button type="button" class="np-ic" aria-label="Undo" disabled={cursor === 0} onclick={() => undo(-1)}>{@render icon('undo')}</button>
    <button type="button" class="np-ic" aria-label="Redo" disabled={cursor >= historyLength - 1} onclick={() => undo(1)}>{@render icon('redo')}</button>
    <button type="button" class="np-ic" aria-label="Note actions" aria-haspopup="dialog" aria-expanded={menu} onclick={() => more(!menu)}>
      <svg viewBox="0 0 20 20"><circle cx="4.5" cy="10" r="1.4" fill="currentColor" stroke="none"/><circle cx="10" cy="10" r="1.4" fill="currentColor" stroke="none"/><circle cx="15.5" cy="10" r="1.4" fill="currentColor" stroke="none"/></svg>
    </button>
  </div>

  <div class="np-page" bind:this={page}>
    <div class="np-col">
      <label class="sr" for="nt-title">Title</label>
      <textarea class="np-title" id="nt-title" bind:this={titleEl} rows="1" autocomplete="off" enterkeyhint="next" placeholder="Untitled" bind:value={title} oninput={onedit} onkeydown={e => { if (e.key === 'Enter') { e.preventDefault(); editor?.focus() } }}></textarea>
      <p class="np-meta">{metaLine}</p>
      {#if parsed.ok}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div class="np-body" id="nt-body" bind:this={editor} contenteditable="true" tabindex="0" role="textbox" aria-multiline="true" aria-label="Note text" spellcheck="true"
          onbeforeinput={beforeInput} oninput={e => { if (e instanceof InputEvent) input(e) }} onpaste={paste} onkeydown={keys} onclick={task}
          ondrop={e => e.preventDefault()} oncompositionstart={() => { composing = true; beforeMutation() }}
          oncompositionend={() => { composing = false; collect('composition') }}></div>
      {:else}
        <label class="sr" for="nt-body">Note text (Markdown)</label>
        <textarea class="np-source" id="nt-body" spellcheck="true" value={localBody} oninput={e => { beforeMutation(); emit(e.currentTarget.value, 'typing') }}></textarea>
        {#if reason}<p class="np-hint">{reason}</p>{/if}
      {/if}
    </div>
    {#if page && editor && parsed.ok}
      <NoteStamps bind:this={stampTools} {stamps} sheet={page} bodyRoot={editor} titleEl={titleEl}
        bind:open={tray} bind:selected {ink} {heading} oncommit={stampChange} onink={() => strip = strip === 'ink' ? null : 'ink'} onclose={() => undefined} />
    {/if}
  </div>
</section>

{#if error}<p class="np-hint" role="alert" style="margin:0 24px">{error}</p>{/if}

<!-- the formatting dock: above the tab bar, on the keyboard while typing -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="np-dock" onmousedown={e => { if ((e.target as HTMLElement).closest('button')) e.preventDefault() }}>
  <div class="np-strip" role="group" hidden={!strip}>
    {#if strip === 'style'}
      {#each BLOCKS as [t, label]}<button type="button" class="np-chipb {t === 'quote' ? 'q' : t}" aria-pressed={blockStyle === t} onclick={() => block(t)}>{label}</button>{/each}
      <span class="np-sep"></span>
      <button type="button" class="np-chipb ic" aria-label="Dotted divider" onclick={() => run('hr')}>{@render icon('divider')}</button>
      <button type="button" class="np-chipb ic" aria-label="Clear formatting" onclick={() => run('clear')}>{@render icon('clear')}</button>
    {:else if strip === 'ink'}
      <span class="np-cap">{selected != null ? 'Stamp' : 'Ink'}</span>
      {#each INKS as c}<button type="button" class="np-sw" aria-label={`${c} ink`} aria-pressed={selected != null ? stamps[selected]?.c === c : ink === c} style={`--c:var(--ink-${c})`} onclick={() => setInk(c)}><i></i></button>{/each}
    {:else if strip === 'mark'}
      <span class="np-cap">Marker</span>
      {#each [...MARKS, 'none'] as c}<button type="button" class="np-sw mk{c === 'none' ? ' none' : ''}" aria-label={c === 'none' ? 'No marker' : `${c} marker`} aria-pressed={c !== 'none' && mark === c} style={`--c:var(--mk-${c})`} onclick={() => setMark(c)}><i></i></button>{/each}
    {/if}
  </div>
  <div class="np-bar" role="toolbar" aria-label="Formatting">
    <div class="np-bar-sc">
      <button type="button" class="nb aa" aria-label="Text style" aria-expanded={strip === 'style'} aria-controls="np-strip" onclick={() => strip = strip === 'style' ? null : 'style'}>Aa</button>
      <span class="np-sep"></span>
      <button type="button" class="nb b" aria-label="Bold" aria-pressed={active.includes('b')} onclick={() => run('bold')}>B</button>
      <button type="button" class="nb i" aria-label="Italic" aria-pressed={active.includes('i')} onclick={() => run('italic')}>I</button>
      <button type="button" class="nb u" aria-label="Underline" aria-pressed={active.includes('u')} onclick={() => run('underline')}>U</button>
      <button type="button" class="nb s" aria-label="Strikethrough" aria-pressed={active.includes('s')} onclick={() => run('strikeThrough')}>S</button>
      <span class="np-sep"></span>
      <button type="button" class="nb np-inkbtn" aria-label="Ink colour" aria-expanded={strip === 'ink'} aria-controls="np-strip" style={`--c:var(--ink-${ink})`} onclick={() => strip = strip === 'ink' ? null : 'ink'}><span class="np-a">A</span></button>
      <button type="button" class="nb np-mkbtn" aria-label="Highlighter" aria-expanded={strip === 'mark'} aria-controls="np-strip" style={`--c:var(--mk-${mark})`} onclick={() => strip = strip === 'mark' ? null : 'mark'}>{@render icon('marker')}<i></i></button>
      <span class="np-sep"></span>
      <button type="button" class="nb" aria-label="Checklist" aria-pressed={blockStyle === 'task'} onclick={() => run('check')}><svg viewBox="0 0 20 20" aria-hidden="true"><path d={icons.check} /></svg></button>
      <button type="button" class="nb" aria-label="Bulleted list" aria-pressed={blockStyle === 'bullet'} onclick={() => run('ul')}><svg viewBox="0 0 20 20" aria-hidden="true"><path d={icons.ul} /><circle cx="4" cy="5.5" r="1.1" fill="currentColor" stroke="none"/><circle cx="4" cy="10" r="1.1" fill="currentColor" stroke="none"/><circle cx="4" cy="14.5" r="1.1" fill="currentColor" stroke="none"/></svg></button>
      <button type="button" class="nb" aria-label="Numbered list" aria-pressed={blockStyle === 'number'} onclick={() => run('ol')}><svg viewBox="0 0 20 20" aria-hidden="true"><path d={icons.ol} /></svg></button>
    </div>
    <div class="np-bar-fix">
      <button type="button" class="nb st" aria-label="Stamps" aria-haspopup="dialog" aria-expanded={tray} onclick={() => { document.activeElement && (document.activeElement as HTMLElement).blur(); tray = true; strip = null }}>{@render icon('stamps')}</button>
      <button type="button" class="nb done" aria-label="Hide keyboard" onclick={() => { document.activeElement && (document.activeElement as HTMLElement).blur(); strip = null }}>{@render icon('done')}</button>
    </div>
  </div>
</div>

{#if tray || menu}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="np-scrim" onclick={() => { tray = false; menu = false }}></div>
{/if}

{#if menu}
  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <section class="m-sheet np-sheet np-more" role="dialog" aria-label="Note actions">
    <i class="np-grab" aria-hidden="true"></i>
    <div class="np-sh-hd"><h3>{title || 'Untitled'}</h3><button type="button" class="np-x" aria-label="Close" onclick={() => more(false)}><svg viewBox="0 0 14 14"><path d="m3 3 8 8M11 3l-8 8"/></svg></button></div>
    <div class="np-acts">
      <Voice file={file} onText={onvoice} onQueued={onqueued} />
      <MButton onclick={() => { menu = false; titled() }}>+ Dated section</MButton>
      <MButton onclick={() => { menu = false; toast('Summarize runs on the PC: open the note there.') }}>Summarize</MButton>
      <MButton onclick={() => { menu = false; toast('Reformat runs on the PC: open the note there.') }}>Reformat</MButton>
      <MButton onclick={() => { menu = false; onobsidian() }}>Obsidian</MButton>
      <MButton class="np-del" onclick={() => { menu = false; ondelete() }}>Delete</MButton>
    </div>
  </section>
{/if}

<div class="np-toasts" id="np-toasts" aria-live="polite"></div>
