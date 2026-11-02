<script lang="ts">
  import { onMount, tick, type Snippet } from 'svelte'
  import { mdHTML } from '../../lib/md'
  import { INKS, MARKS, type Ink, type Stamp } from '../../lib/note-format'
  import { blockElements, mergeRuns, orderedSelection, parseMarkdown, readDOM, rememberSelection, restoreSelection,
    serializeMarkdown, sliceRuns, writeDOM, headingName, type Block, type Run, type Selection } from '../../lib/note-editor'
  import NoteStamps from './NoteStamps.svelte'

  let { body, stamps, revision, title, meta, onbody, onstamps }: {
    body: string; stamps: Stamp[]; revision: number; title: Snippet; meta: string;
    onbody: (body: string) => void; onstamps: (stamps: Stamp[]) => void
  } = $props()
  let editor = $state<HTMLDivElement>()!
  let page = $state<HTMLDivElement>()!
  let stampTools = $state<NoteStamps>()!
  let mode = $state<'write' | 'markdown' | 'preview'>('write')
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
  let pop = $state<'ink' | 'mark' | null>(null)
  let tray = $state(false)
  let selected = $state<number | null>(null)
  let inkButton = $state<HTMLButtonElement>()!, markButton = $state<HTMLButtonElement>()!, stampsButton = $state<HTMLButtonElement>()!
  type Snapshot = { body: string; stamps: Stamp[]; selection: Selection | null }
  let history: Snapshot[] = []
  let cursor = $state(0)
  let historyLength = $state(1)
  let lastKind = '', lastTime = 0, seenRevision = -1
  const preview = $derived(mdHTML(localBody))
  const parsed = $derived(parseMarkdown(localBody))

  const icons: Record<string, string> = {
    undo: 'M7.5 4.5 4 8l3.5 3.5M4 8h8.5a3.5 3.5 0 0 1 0 7H10',
    redo: 'M12.5 4.5 16 8l-3.5 3.5M16 8H7.5a3.5 3.5 0 0 0 0 7H10',
    bullet: 'M8 5h9M8 10h9M8 15h9M3 5h1M3 10h1M3 15h1',
    number: 'M9 6h8M9 14h8M3 4l2-1v5M3 12c1-2 4 0 1 2l-1 2h3',
    task: 'M11 6h6M11 14h6M3 3h5v5H3ZM3 12h5v5H3Zm1-6 1 1 2-3',
    divider: 'M3 10h1M7 10h1M11 10h1M15 10h1',
    clear: 'm11 3 6 6-7 7H6l-3-3 8-10M7 7l6 6M10 16h7',
    stamps: 'M9 2c1 5 3 6 7 7-4 1-6 3-7 7-1-4-3-6-7-7 4-1 6-2 7-7M16 14v5M14 16h5',
    marker: 'm12 3 5 5-7 7H5v-5Zm-3 3 5 5'
  }
  const tools = [['b', 'Bold', 'B'], ['i', 'Italic', 'I'], ['u', 'Underline', 'U'], ['s', 'Strikethrough', 'S']]

  function snapshot(): Snapshot { return { body: localBody, stamps: stamps.map(s => ({ ...s })), selection: saved ? structuredClone(saved) : null } }
  function reset() {
    const result = parseMarkdown(localBody)
    reason = result.ok ? '' : result.reason
    if (!result.ok) mode = 'markdown'
    if (result.ok && editor) writeDOM(editor, result.blocks)
    saved = null; pending = null; active = []; selected = null; pop = null; tray = false; error = ''
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
    return () => { document.removeEventListener('selectionchange', selectionChanged); saved = null; history = [] }
  })
  function selection(): Selection {
    return saved || { anchor: { block: 0, offset: 0 }, focus: { block: 0, offset: 0 } }
  }
  function mutate(blocks: Block[], sel: Selection, kind: string) {
    beforeMutation(); writeDOM(editor, blocks); saved = sel
    restoreSelection(editor, sel); collect(kind)
  }
  function format(mark: string) {
    if (mode !== 'write' || composing) return
    const sel = selection(), [start, end] = orderedSelection(sel)
    if (start.block === end.block && start.offset === end.offset) {
      const base = pending || active
      pending = mark === 'clear' ? [] : base.includes(mark) ? base.filter(m => m !== mark) : [...base.filter(m => !mark.includes(':') || !m.startsWith(mark.split(':')[0] + ':')), mark]
      active = pending; restoreSelection(editor, sel); return
    }
    const blocks = readDOM(editor)
    const selectedRuns = blocks.slice(start.block, end.block + 1).flatMap((b, i) => sliceRuns(b.runs, i === 0 ? start.offset : 0, start.block + i === end.block ? end.offset : Infinity))
    const remove = selectedRuns.length > 0 && selectedRuns.every(r => r.marks.includes(mark))
    for (let i = start.block; i <= end.block; i++) {
      const b = blocks[i], from = i === start.block ? start.offset : 0, to = i === end.block ? end.offset : Infinity
      b.runs = mergeRuns([...sliceRuns(b.runs, 0, from), ...sliceRuns(b.runs, from, to).map(r => ({ ...r, marks: mark === 'clear' ? [] : remove ? r.marks.filter(m => m !== mark) : [...r.marks.filter(m => !mark.includes(':') || !m.startsWith(mark.split(':')[0] + ':')), mark] })), ...sliceRuns(b.runs, to)])
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
    else mode = 'markdown'
    onbody(localBody); onstamps(state.stamps.map(s => ({ ...s })))
    if (mode === 'write') { restoreSelection(editor, saved); selectionChanged() }
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
    if (e.key === 'Escape') { pop = null; tray = false; selected = null }
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
    // Props update on the next Svelte turn; the history entry must include this gesture now.
    const state = snapshot(); state.stamps = next.map(s => ({ ...s }))
    history = history.slice(0, cursor + 1); history.push(state); cursor++; historyLength = history.length; lastKind = 'stamp'
  }
  function closePop() {
    const trigger = pop === 'ink' ? inkButton : markButton
    pop = null; trigger?.focus()
  }
  function swatch(c: string) {
    if (pop === 'ink') { ink = c as Ink; if (selected != null) stampTools.change({ c: ink }); else format(`ink:${c}`) }
    else if (c !== 'none') format(`mark:${c}`)
    if (c === 'none') {
      // Removing only the marker keeps ink, links and the other text styles.
      const sel = selection(), [start, end] = orderedSelection(sel), blocks = readDOM(editor)
      if (start.block === end.block && start.offset === end.offset) { pending = active.filter(m => !m.startsWith('mark:')); active = pending }
      else {
        for (let i = start.block; i <= end.block; i++) {
          const b = blocks[i], from = i === start.block ? start.offset : 0, to = i === end.block ? end.offset : Infinity
          b.runs = [...sliceRuns(b.runs, 0, from), ...sliceRuns(b.runs, from, to).map(r => ({ ...r, marks: r.marks.filter(m => !m.startsWith('mark:')) })), ...sliceRuns(b.runs, to)]
        }
        mutate(blocks, sel, 'format')
      }
    }
    pop = null
    if (selected != null) page.querySelector<HTMLButtonElement>(`[data-stamp="${selected}"]`)?.focus()
  }
  async function changeMode(next: typeof mode) {
    if (composing || (next === 'write' && !parsed.ok)) return
    pop = null; tray = false; selected = null; pending = null
    const previous = mode; mode = next
    if (next === 'write' && previous === 'markdown') {
      const result = parseMarkdown(localBody)
      if (result.ok) writeDOM(editor, result.blocks)
    }
    await tick()
  }
</script>

{#snippet icon(name: string)}<svg viewBox="0 0 20 20" aria-hidden="true"><path d={icons[name]} /></svg>{/snippet}

<div class="np-modes" role="group" aria-label="Editor mode">
  {#each ['write', 'markdown', 'preview'] as m}
    <button type="button" aria-pressed={mode === m} disabled={m === 'write' && !parsed.ok} onclick={() => changeMode(m as typeof mode)}>{m === 'write' ? 'Write' : m === 'markdown' ? 'Markdown' : 'Preview'}</button>
  {/each}
  {#if reason}<span class="np-explanation">{reason}</span>{/if}
</div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="np-editing" onkeydown={historyKey}>
  {#if mode === 'write'}
    <div class="np-bar" role="toolbar" aria-label="Formatting">
      <button type="button" aria-label="Undo" disabled={cursor === 0} onclick={() => undo(-1)}>{@render icon('undo')}</button>
      <button type="button" aria-label="Redo" disabled={cursor >= historyLength - 1} onclick={() => undo(1)}>{@render icon('redo')}</button>
      <select aria-label="Text style" value={['p','h1','h2','h3','quote'].includes(blockStyle) ? blockStyle : 'p'} onchange={e => block(e.currentTarget.value)}>
        <option value="p">Text</option><option value="h1">Title</option><option value="h2">Heading</option><option value="h3">Subheading</option><option value="quote">Quote</option>
      </select>
      {#each tools as [mark, label, letter]}<button type="button" class={`nb-${mark}`} aria-label={label} aria-pressed={active.includes(mark)} onclick={() => format(mark)}>{letter}</button>{/each}
      <button type="button" bind:this={inkButton} aria-label="Ink colour" aria-expanded={pop === 'ink'} aria-controls="np-swatches" onclick={() => pop = pop === 'ink' ? null : 'ink'}><span class="ink-letter" style={`border-color:var(--ink-${ink})`}>A</span></button>
      <button type="button" bind:this={markButton} aria-label="Highlighter" aria-expanded={pop === 'mark'} aria-controls="np-swatches" onclick={() => pop = pop === 'mark' ? null : 'mark'}>{@render icon('marker')}</button>
      {#each [['bullet','Bulleted list'],['number','Numbered list'],['task','Checklist']] as [kind, label]}<button type="button" aria-label={label} aria-pressed={blockStyle === kind} onclick={() => block(blockStyle === kind ? 'p' : kind)}>{@render icon(kind)}</button>{/each}
      <button type="button" aria-label="Dotted divider" onclick={divider}>{@render icon('divider')}</button>
      <button type="button" aria-label="Clear formatting" onclick={() => format('clear')}>{@render icon('clear')}</button>
      <button type="button" class="stamp-trigger" bind:this={stampsButton} aria-label="Stamps" aria-pressed={tray} aria-expanded={tray} aria-controls="np-tray" onclick={() => tray = !tray}>{@render icon('stamps')}<span>Stamps</span></button>
    </div>
  {/if}
  {#if pop && mode === 'write'}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div class="np-pop" id="np-swatches" role="group" aria-label={pop === 'ink' ? 'Ink colours' : 'Marker colours'} onkeydown={e => { if (e.key === 'Escape') { e.stopPropagation(); closePop() } }}>
      {#each pop === 'ink' ? INKS : [...MARKS, 'none'] as c}<button type="button" aria-label={c === 'none' ? 'No marker' : `${c} ${pop === 'ink' ? 'ink' : 'marker'}`} aria-pressed={active.includes(`${pop === 'ink' ? 'ink' : 'mark'}:${c}`)} onclick={() => swatch(c)}><i style={`background:${c === 'none' ? 'transparent' : `var(--${pop === 'ink' ? 'ink' : 'mk'}-${c})`}`}></i><span>{c}</span></button>{/each}
    </div>
  {/if}
  {#if error}<p class="np-error" role="alert">{error}</p>{/if}
  <div class="np-scroll">
    <div class="np-page" bind:this={page}>
      <div class="np-col">
        {@render title()}
        {#if meta}<p class="np-meta">{meta}</p>{/if}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div class="np-body" id="nt-write" bind:this={editor} hidden={mode !== 'write'} contenteditable="true" tabindex="0" role="textbox" aria-multiline="true" aria-label="Note text" spellcheck="true"
          onbeforeinput={beforeInput} oninput={e => { if (e instanceof InputEvent) input(e) }} onpaste={paste} onkeydown={keys} onclick={task}
          ondrop={e => e.preventDefault()} oncompositionstart={() => { composing = true; beforeMutation() }}
          oncompositionend={() => { composing = false; collect('composition') }}></div>
        {#if mode === 'markdown'}
          <label class="sr" for="nt-body">Note text (Markdown)</label>
          <textarea id="nt-body" class="np-source" spellcheck="true" value={localBody} oninput={e => { beforeMutation(); emit(e.currentTarget.value, 'typing') }}></textarea>
        {:else if mode === 'preview'}
          <div class="np-body md np-preview" id="nt-md" aria-label="Preview">{@html preview}</div>
        {/if}
      </div>
      {#if page && editor && mode !== 'markdown'}
        {#key mode}
          <NoteStamps bind:this={stampTools} {stamps} sheet={page} bodyRoot={mode === 'write' ? editor : page.querySelector('#nt-md') as HTMLElement}
            readonly={mode === 'preview'} bind:open={tray} bind:selected {ink} {heading} oncommit={stampChange} onclose={() => stampsButton?.focus()} />
        {/key}
      {/if}
    </div>
  </div>
</div>

<style>
  .np-modes { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 8px 20px }
  .np-modes button { border: 0; border-radius: 8px; background: transparent; color: var(--np-dim); padding: 6px 10px; font: var(--type-tool); cursor: pointer }
  .np-modes button[aria-pressed=true] { background: var(--np-tint); color: var(--ink-indigo) }
  .np-explanation { flex: 1 1 260px; font-size: 12px; line-height: 18px; color: var(--np-dim) }
  .np-editing { position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0; flex: 1 }
  .np-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; align-self: center; gap: 2px; max-width: calc(100% - 24px); margin: 0 12px 8px; padding: 4px; border: 1px solid var(--np-edge); border-radius: 14px; background: var(--np-solid); box-shadow: 0 10px 24px -16px rgba(30,26,110,.45) }
  .np-bar button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 32px; height: 32px; padding: 0 6px; border: 0; border-radius: 8px; color: var(--np-ink); background: transparent; font: 600 14px var(--display); cursor: pointer }
  .np-bar button:hover { background: var(--np-tint) }
  .np-bar button[aria-pressed=true] { color: var(--ink-indigo); background: var(--np-tint-2) }
  button:disabled { opacity: .4; cursor: default }
  .np-bar .nb-b { font-weight: 800 }.np-bar .nb-i { font-style: italic }.np-bar .nb-u { text-decoration: underline; text-underline-offset: 3px }.np-bar .nb-s { text-decoration: line-through }
  .np-bar select { min-width: 0; max-width: 120px; height: 32px; border: 0; background: var(--np-solid); color: var(--np-ink); font: var(--type-tool); border-radius: 8px }
  .ink-letter { line-height: 19px; border-bottom: 3px solid }
  .np-bar :global(svg) { width: 18px; height: 18px; stroke: currentColor; stroke-width: 1.6; fill: none; stroke-linecap: round; stroke-linejoin: round }
  .stamp-trigger span { font-size: 12px }
  .np-pop { display: flex; flex-wrap: wrap; gap: 3px; align-self: center; max-width: calc(100% - 24px); margin: 0 12px 8px; padding: 6px; background: var(--np-solid); border: 1px solid var(--np-edge); border-radius: 12px; z-index: 5 }
  .np-pop button { display: grid; justify-items: center; gap: 5px; min-width: 36px; border: 0; padding: 6px; background: transparent; color: var(--np-ink); font-size: 10px; border-radius: 6px; cursor: pointer }
  .np-pop button:hover, .np-pop button[aria-pressed=true] { background: var(--np-tint) }
  .np-pop i { width: 18px; height: 18px; border-radius: 50%; border: 1px solid var(--np-edge) }
  .np-scroll { min-height: 0; flex: 1; overflow: auto; scrollbar-width: thin; scrollbar-color: var(--np-edge) transparent }
  .np-page { position: relative; min-height: 100%; padding: 48px 72px 144px; box-sizing: border-box; background-image: radial-gradient(circle,var(--np-dot) 1.15px,transparent 1.7px); background-size: 24px 24px; background-position: -12px -12px }
  .np-col { position: relative; max-width: 696px; min-width: 0 }
  .np-meta { color: var(--np-dim); font: 11px/24px var(--mono); margin: 0 0 24px }
  .np-body { min-height: 240px; outline: 0; color: var(--np-ink); font: var(--type-paper); white-space: pre-wrap; overflow-wrap: anywhere; caret-color: var(--ink-indigo) }
  .np-body[hidden] { display: none }
  .np-body :global(:is(p,div,ul,ol,li,blockquote)) { margin: 0; font-size: 15px; line-height: 24px; min-height: 24px }
  .np-body :global(:is(h1,h2,h3)) { color: inherit; margin: 24px 0 0; padding: 0; font-family: var(--display); font-weight: 650 }
  .np-body :global(h1) { font-size: 26px; line-height: 48px }.np-body :global(h2) { font-size: 20px; line-height: 48px }.np-body :global(h3) { font-size: 16px; line-height: 24px }
  .np-body :global(:is(ul,ol)) { padding-left: 24px }
  .np-body :global(li[data-block=task]) { position: relative; list-style: none }
  .np-body :global([data-task]) { position: absolute; left: -23px; top: 4px; width: 16px; height: 16px; border: 1.5px solid var(--ink-indigo); border-radius: 3px 2px 4px 2px; background: var(--np-solid); color: var(--ink-indigo); padding: 0; line-height: 12px; font-size: 13px; cursor: pointer }
  .np-body :global(blockquote) { padding-left: 12px; border-left: 2px solid var(--ink-indigo); font-style: italic }
  .np-body :global(hr) { height: 24px; margin: 0; border: 0; background: radial-gradient(circle,var(--ink-indigo) 1.2px,transparent 1.7px) 0 50%/10px 10px repeat-x; opacity: .5 }
  .np-body :global(code) { font: var(--type-code); background: var(--np-tint); border-radius: 3px }
  .np-source { display: block; width: 100%; min-height: 48vh; resize: vertical; border: 0; padding: 0; background: transparent; color: var(--np-ink); font: var(--type-code); caret-color: var(--ink-indigo); overflow-wrap: anywhere; box-sizing: border-box }
  .np-error { margin: 0 20px 8px; color: var(--danger); font-size: 12px }
  :is(button,select,textarea):focus-visible, .np-body:focus-visible { outline: 2px solid var(--ink-indigo); outline-offset: 2px }
  @container (max-width: 620px) { .np-page { padding: 24px 24px 96px }.np-modes { padding-inline: 12px } }
  @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto } }
</style>
