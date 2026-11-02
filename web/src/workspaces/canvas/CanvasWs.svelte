<script lang="ts">
  // 03 CANVAS (V6 main.ws-c, i-canvas.js): the active canvas on a board. Ctrl-drag pans, wheel
  // zooms, click / Shift-click selects, drag moves the selection, double-click edits a note or
  // opens an item (on empty board: a new note), arrows nudge, Delete removes, right-click for more.
  import { onMount, tick } from 'svelte'
  import { confirmWin } from '../../lib/windows.svelte'
  import { cv, imgSrc, markDirty, renameTo, save, selEls, type CEl } from '../../lib/canvas.svelte'
  import { cvAction, fit, offWhy, toWorld, zoom, type CvAct } from '../../lib/canvas-board'
  import { act } from '../../lib/cardmenu'
  import { titleOf } from '../../lib/cards/card'
  import type { Cmd, MenuEntry } from '../../lib/commands'
  import { lib } from '../../lib/library.svelte'
  import { openMenu } from '../../lib/menu.svelte'
  import { readyAfterPaint, toast, ui } from '../../lib/ui.svelte'
  import Button from '../../components/ui/Button.svelte'

  onMount(() => readyAfterPaint('canvas'))

  let board: HTMLDivElement | undefined = $state()
  let nameEl: HTMLInputElement | undefined = $state()
  const d = $derived(cv.doc)
  const nSel = $derived(cv.sel.size)
  const count = $derived(d ? `${d.items.length} element${d.items.length === 1 ? '' : 's'}${nSel ? ` · ${nSel} selected` : ''}` : '')
  const st = $derived(!d ? 'No canvas yet. Press New on the rail.'
    : d.items.length ? 'Drag to select · Ctrl + drag to pan · Shift-click to add · Wheel zooms · double-click a note to edit'
    : 'Empty canvas. Add a note, an image, or drag items from the rail.')

  // fit when a canvas opens (fitTick) and when the workspace shows
  let shownFit = 0
  $effect(() => {
    const t = cv.fitTick, on = ui.ws === 'canvas'
    if (on && t !== shownFit) { shownFit = t; tick().then(fitTwice) }
  })
  // fit now, then again once the images have their real size (unless the view moved meanwhile)
  let needFit = false
  $effect(() => {   // the board had no size yet (window hidden or minimised): fit when it gets one
    const b = board
    if (!b) return
    const ro = new ResizeObserver(() => { if (needFit && b.clientWidth) fitTwice() })
    ro.observe(b)
    return () => ro.disconnect()
  })
  async function fitTwice() {
    needFit = !board?.clientWidth || !cv.doc
    if (needFit) return
    fit()
    const view = `${cv.s},${cv.x},${cv.y}`, t = cv.fitTick
    const imgs = [...(board?.querySelectorAll('img') ?? [])].filter(i => !i.complete)
    if (!imgs.length) return
    await Promise.race([Promise.allSettled(imgs.map(i => i.decode())), new Promise(r => setTimeout(r, 2500))])
    if (t === cv.fitTick && view === `${cv.s},${cv.x},${cv.y}`) fit()
  }
  // leaving the workspace saves at once
  $effect(() => { if (ui.ws !== 'canvas' && cv.dirty) save(true) })
  // the name box follows the canvas unless it is being typed in
  $effect(() => { const n = d?.name ?? ''; if (nameEl && document.activeElement !== nameEl) nameEl.value = n })

  const caption = (e: CEl) => {
    if (e.source === 'file' || !e.item_id) return 'image'
    const r = lib.byId.get(e.item_id)
    return r ? `No.${r.id} · ${titleOf(r)}` : `No.${e.item_id}`
  }

  // ── pointer: pan, select, move ─────────────────────────────────────────────
  type Drag = { mode: 'pan'; x: number; y: number; ox: number; oy: number; moved: boolean; pid: number }
    | { mode: 'move'; x: number; y: number; start: { e: CEl; x: number; y: number }[]; moved: boolean; pid: number }
    | { mode: 'select'; x: number; y: number; base: string[]; bounds: { id: string; rect: DOMRect }[]; moved: boolean; pid: number }
  let drag: Drag | null = null
  let ctrlHeld = $state(false)
  let marquee: { x: number; y: number; w: number; h: number } | null = $state(null)
  function controlKey(e: KeyboardEvent) { ctrlHeld = e.ctrlKey }
  function down(e: PointerEvent) {
    if (e.button !== 0 || !d) return
    const target = e.target as HTMLElement
    if (!e.ctrlKey && (target.closest('.lbl') || (e.pointerType === 'touch' && target.closest('.ce-text')))) return
    const ce = (e.target as HTMLElement).closest<HTMLElement>('.ce')
    if (ce && ce.dataset.eid === cv.editing) return
    e.preventDefault()
    if (cv.editing) cv.editing = null
    ctrlHeld = e.ctrlKey
    board!.focus({ preventScroll: true })
    if (e.ctrlKey) drag = { mode: 'pan', x: e.clientX, y: e.clientY, ox: cv.x, oy: cv.y, moved: false, pid: e.pointerId }
    else if (ce) {
      const id = ce.dataset.eid!
      if (e.shiftKey || e.metaKey) { if (cv.sel.has(id)) cv.sel.delete(id); else cv.sel.add(id) }
      else if (!cv.sel.has(id)) { cv.sel.clear(); cv.sel.add(id) }
      drag = { mode: 'move', x: e.clientX, y: e.clientY, start: selEls().map(el => ({ e: el, x: el.x, y: el.y })), moved: false, pid: e.pointerId }
    } else {
      if (!e.shiftKey && !e.metaKey) cv.sel.clear()
      drag = { mode: 'select', x: e.clientX, y: e.clientY, base: [...cv.sel],
        bounds: [...board!.querySelectorAll<HTMLElement>('.ce')].map(el => ({ id: el.dataset.eid!, rect: el.getBoundingClientRect() })),
        moved: false, pid: e.pointerId }
    }
  }
  function move(e: PointerEvent) {
    if (!drag) return
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < 4) return
      drag.moved = true
      try { board!.setPointerCapture(drag.pid) } catch { /* gone */ }
      if (drag.mode === 'pan') board!.classList.add('pan')
    }
    if (drag.mode === 'pan') { cv.x = drag.ox + dx; cv.y = drag.oy + dy }
    else if (drag.mode === 'move') for (const s of drag.start) { s.e.x = Math.round(s.x + dx / cv.s); s.e.y = Math.round(s.y + dy / cv.s) }
    else {
      const left = Math.min(drag.x, e.clientX), top = Math.min(drag.y, e.clientY)
      const right = Math.max(drag.x, e.clientX), bottom = Math.max(drag.y, e.clientY)
      const r = board!.getBoundingClientRect()
      marquee = { x: left - r.left, y: top - r.top, w: right - left, h: bottom - top }
      cv.sel.clear()
      for (const id of drag.base) cv.sel.add(id)
      for (const { id, rect } of drag.bounds) {
        if (rect.left < right && rect.right > left && rect.top < bottom && rect.bottom > top) cv.sel.add(id)
      }
    }
  }
  function up() {
    if (!drag) return
    board?.classList.remove('pan')
    if (drag.mode === 'move' && drag.moved) markDirty()
    const pid = drag.pid
    drag = null
    marquee = null
    if (board?.hasPointerCapture(pid)) board.releasePointerCapture(pid)
  }
  function dbl(e: MouseEvent) {
    if (!d || e.ctrlKey || (e.target as HTMLElement).closest('.lbl')) return
    const ce = (e.target as HTMLElement).closest<HTMLElement>('.ce')
    if (!ce) { cvAction('note', toWorld(e.clientX, e.clientY)); return }
    const el = d.items.find(x => x.id === ce.dataset.eid)
    if (!el) return
    if (el.type === 'note') cv.editing = el.id
    else if (el.item_id) act('open', el.item_id)
  }

  // ── wheel (not passive: it zooms and pans instead of scrolling) ─────────────
  $effect(() => {
    const b = board
    if (!b) return
    const wheel = (e: WheelEvent) => {
      if (!cv.doc) return
      if (!(e.ctrlKey || e.metaKey) && (e.target as HTMLElement).closest('.ce-text, .ce-ed')) return
      e.preventDefault()
      zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, { x: e.clientX, y: e.clientY })
    }
    b.addEventListener('wheel', wheel, { passive: false })
    return () => b.removeEventListener('wheel', wheel)
  })

  function key(e: KeyboardEvent) {
    if (e.target !== board || !d) return
    const s = selEls()
    const stop = () => { e.preventDefault(); e.stopPropagation() }
    if ((e.key === 'Delete' || e.key === 'Backspace') && s.length) { stop(); cvAction('delete') }
    else if (e.key.startsWith('Arrow') && s.length) {
      stop()
      const k = e.shiftKey ? 40 : 8
      const [dx, dy] = ({ ArrowLeft: [-k, 0], ArrowRight: [k, 0], ArrowUp: [0, -k], ArrowDown: [0, k] } as Record<string, number[]>)[e.key] ?? [0, 0]
      s.forEach(x => { x.x += dx; x.y += dy })
      markDirty()
    } else if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) { stop(); cvAction('all') }
    else if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) { stop(); save() }
    else if (e.key === 'Enter' && s.length === 1) {
      stop()
      if (s[0].type === 'note') cv.editing = s[0].id; else if (s[0].item_id) act('open', s[0].item_id)
    } else if (e.key === 'Escape' && cv.sel.size) { stop(); cv.sel.clear() }
  }

  function menu(e: MouseEvent) {
    if (!d) return
    e.preventDefault()
    const ce = (e.target as HTMLElement).closest<HTMLElement>('.ce'), p = toWorld(e.clientX, e.clientY)
    if (ce && !cv.sel.has(ce.dataset.eid!)) { cv.sel.clear(); cv.sel.add(ce.dataset.eid!) }
    const s = selEls(), one = s.length === 1 ? s[0] : null
    let n = 0
    const m = (label: string, run: () => void, o: Partial<Cmd> = {}): Cmd => ({ id: `cvm-${n++}`, menu: 'edit', label, run, ...o })
    const list: MenuEntry[] = [
      { head: d.name },
      m('Add note here', () => cvAction('note', p), { icon: 'note' }),
      m('Add image from file…', () => cvAction('image', p), { icon: 'img' }),
      { sep: true },
      m('Open item', () => act('open', one!.item_id!), { icon: 'link', off: () => !one?.item_id, offMsg: () => 'Select one item image' }),
      m('Edit note', () => (cv.editing = one!.id), { icon: 'edit', off: () => one?.type !== 'note', offMsg: () => 'Select one note' }),
      m('Set label…', () => cvAction('label'), { icon: 'tag', off: () => offWhy('label') !== null, offMsg: () => offWhy('label')! }),
      m('Arrange selected in a row', () => cvAction('row'), { off: () => s.length < 2, offMsg: () => offWhy('row')! }),
      m('Arrange selected in a grid', () => cvAction('grid'), { off: () => s.length < 2, offMsg: () => offWhy('grid')! }),
      m('Delete selected', () => cvAction('delete'), { icon: 'trash', danger: true, off: () => !s.length, offMsg: () => offWhy('delete')! }),
      { sep: true },
      m('Fit', fit),
      m('Save', () => save()),
    ]
    openMenu(list, board!, { x: e.clientX, y: e.clientY })
  }

  function tool(a: CvAct) {
    const why = offWhy(a)
    if (why) { toast(why, 'w'); return }
    cvAction(a)
  }

  // the note editor: a textarea in place of the note text; blur or Esc ends it
  function edDone(el: CEl, ta: HTMLTextAreaElement) {
    const t = ta.value.replace(/\n+$/, '').trim() || 'Note'
    if (t !== el.text) { el.text = t; markDirty() }
    if (cv.editing === el.id) cv.editing = null
  }
  function edMount(ta: HTMLTextAreaElement) { ta.focus(); ta.select() }
  function edKey(e: KeyboardEvent) {
    e.stopPropagation()
    if (e.key === 'Escape') { e.preventDefault(); (e.currentTarget as HTMLTextAreaElement).blur(); board?.focus({ preventScroll: true }) }
  }

  function nameChange() {
    const v = nameEl!.value.trim()
    if (!d) return
    if (!v) { toast('Enter a name', 'w'); nameEl!.value = d.name; return }
    renameTo(v)
  }
  function nameKey(e: KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); nameEl!.blur() }
    else if (e.key === 'Escape') { e.stopPropagation(); nameEl!.value = d?.name ?? ''; nameEl!.blur() }
  }
</script>

<svelte:window onkeydown={controlKey} onkeyup={controlKey} onblur={() => { ctrlHeld = false; up() }} />

<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
<main class="ws ws-c" id="ws-canvas" role="tabpanel" aria-labelledby="tab-canvas" data-ws="canvas" hidden={ui.ws !== 'canvas'}>
  <section class="rwin cv-win" aria-labelledby="cv-h">
    <div class="wbar"><span class="wdots" aria-hidden="true"><i></i><i></i></span><p class="wtitle" id="cv-h">Canvas · <span id="cv-file">{d ? d.name : 'no canvas'}</span></p><span class="wcode">CNV-31</span></div>
    <div class="wtools">
      <label class="sr" for="cv-name">Canvas name</label><input class="inp cv-name" id="cv-name" autocomplete="off" disabled={!d} bind:this={nameEl} onchange={nameChange} onkeydown={nameKey} />
      <span class="cv-dirty" id="cv-dirty" title="Unsaved changes" hidden={!cv.dirty}></span>
      <Button size="sm" aria-disabled={offWhy('note') ? 'true' : undefined} onclick={() => tool('note')}>Add note</Button>
      <Button size="sm" aria-disabled={offWhy('image') ? 'true' : undefined} onclick={() => tool('image')}>Add image</Button>
      <Button size="sm" aria-disabled={offWhy('label') ? 'true' : undefined} onclick={() => tool('label')}>Set label</Button>
      <Button variant="danger" size="sm" aria-disabled={offWhy('delete') ? 'true' : undefined} onclick={() => tool('delete')}>Delete</Button>
      <span class="sp"></span>
      <small id="cv-count">{count}</small>
      <Button variant="pri" size="sm" aria-disabled={d ? undefined : 'true'} onclick={() => tool('save')}>Save</Button>
    </div>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_static_element_interactions -->
    <div class="cv-board" id="cv-board" class:pan-ready={ctrlHeld} tabindex="0" aria-label="Canvas board. Drag empty space to select elements, Ctrl-drag to pan, Shift-click to add to the selection, wheel to zoom, Delete removes the selection."
      bind:this={board} style:--bx={cv.x + 'px'} style:--by={cv.y + 'px'} style:--s={cv.s}
      onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onlostpointercapture={up} ondblclick={dbl} onkeydown={key} oncontextmenu={menu}>
      <div class="cv-world" id="cv-world" style:transform={`translate(${cv.x}px,${cv.y}px) scale(${cv.s})`}>
        {#if d}
          {#each d.items as el (el.id)}
            {#if el.type === 'note'}
              <div class="ce note" class:fresh={cv.fresh.has(el.id)} class:sel={cv.sel.has(el.id)} class:editing={cv.editing === el.id} data-eid={el.id}
                style:left={el.x + 'px'} style:top={el.y + 'px'} style:width={(el.w ?? 240) + 'px'} style:height={(el.h ?? 160) + 'px'}>
                {#if cv.editing === el.id}
                  <textarea class="ce-ed" aria-label="Note text" value={el.text ?? ''} use:edMount onblur={e => edDone(el, e.currentTarget)} onkeydown={edKey}></textarea>
                {:else}
                  <!-- Focusable scroll region also supports Enter to edit. -->
                  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
                  <div class="ce-text" role="region" tabindex="0" aria-label="Note text. Scroll to read; double-click to edit." onkeydown={e => { if (e.key === 'Enter') { e.preventDefault(); cv.editing = el.id } }}>{el.text}</div>{/if}
              </div>
            {:else}
              <figure class="ce img" class:fresh={cv.fresh.has(el.id)} class:sel={cv.sel.has(el.id)} data-eid={el.id}
                style:left={el.x + 'px'} style:top={el.y + 'px'} style:width={(el.w ?? 200) + 'px'}>
                {#if el.label}<button type="button" class="lbl" aria-label={`Read label: ${el.label}`} onclick={() => confirmWin({ title: 'Image label', msg: el.label!, ok: 'Close' })}>{el.label}</button>{/if}
                <img style:height={Math.max(40, el.h ?? 150) + 'px'} src={imgSrc(el)} alt="" draggable="false" decoding="async" />
                <figcaption>{caption(el)}</figcaption>
              </figure>
            {/if}
          {/each}
        {/if}
      </div>
      {#if marquee}<div class="cv-marquee" aria-hidden="true" style:left={marquee.x + 'px'} style:top={marquee.y + 'px'} style:width={marquee.w + 'px'} style:height={marquee.h + 'px'}></div>{/if}
      <p class="cv-st" id="cv-st">{st}</p>
    </div>
  </section>
</main>
