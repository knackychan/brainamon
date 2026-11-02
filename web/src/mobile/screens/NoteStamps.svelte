<script lang="ts">
  // The phone's stamp layer + tray (projects/note-organic-ui/plans/07-phone-editor.md): the plan 01
  // stamp shape ({k, at, x, y, s, c, r}) on the dot paper, reusing the 20 drawings and the geometry of
  // the desktop NoteStamps.svelte and note-editor.ts. Phone rules: the sheet is full-bleed with a
  // 3-cell right margin; margin stamps (x < 0) show at S there while the file keeps their size, and a
  // display clamp is never written back on its own (only a user move writes new at / x / y).
  import { onMount, tick } from 'svelte'
  import { cleanStamps, MAX_STAMPS, STAMPS, type Ink, type Stamp } from '../../lib/note-format'
  import { GRID, headingName } from '../../lib/note-editor'
  import { STAMP_DRAWINGS } from '../../lib/stamps'
  import MHint from '../ui/MHint.svelte'

  let { stamps, sheet, bodyRoot, titleEl, ink = 'indigo', heading = 'top',
    open = $bindable(false), selected = $bindable<number | null>(null), oncommit, onink, onclose }: {
    stamps: Stamp[]; sheet: HTMLElement; bodyRoot: HTMLElement; titleEl?: HTMLElement | null;
    ink?: Ink; heading?: string; open?: boolean; selected?: number | null;
    oncommit: (s: Stamp[]) => void; onink: () => void; onclose: () => void
  } = $props()
  let size = $state(2)
  let dragging = $state(false)
  const G = GRID, GUT = 3
  let cols = $state(16)
  let geom = $state.raw({ top: 1, end: 12, headings: [] as { at: string; row: number }[] })
  let drag = $state.raw<{ index: number; stamp: Stamp; x0: number; y0: number; col: number; row: number; ds: number; moved: boolean; capture: HTMLElement; pointer: number } | null>(null)
  let target = $state.raw<Stamp | null>(null)
  let ghostEl: HTMLElement | null = null
  const limit = $derived(stamps.length >= MAX_STAMPS)

  function measure() {
    if (!sheet) return
    const pr = sheet.getBoundingClientRect()
    cols = Math.max(12, Math.floor(sheet.clientWidth / G))
    const rowOf = (el: Element) => Math.round((el.getBoundingClientRect().top - pr.top) / G)
    const title = titleEl ?? sheet.querySelector('#nt-title')
    const last = bodyRoot.lastElementChild
    const end = last ? rowOf(last) + Math.round(last.getBoundingClientRect().height / G) + 1 : rowOf(bodyRoot)
    geom = {
      top: title ? rowOf(title) : 1,
      end,
      headings: [...bodyRoot.querySelectorAll('h1,h2,h3')].filter(h => h.textContent!.trim())
        .map(h => ({ at: headingName(h.textContent || ''), row: rowOf(h) })),
    }
  }
  $effect(() => { stamps; sheet; bodyRoot; void tick().then(measure) })
  onMount(() => {
    const ro = new ResizeObserver(measure), mo = new MutationObserver(measure)
    if (sheet) { ro.observe(sheet); ro.observe(bodyRoot) }
    mo.observe(bodyRoot, { childList: true, subtree: true, characterData: true })
    let mounted = true
    void document.fonts.ready.then(() => { if (mounted) measure() })
    return () => { mounted = false; ro.disconnect(); mo.disconnect(); cancel() }
  })

  function anchorRow(at: string): number | null {
    if (at === 'top') return geom.top
    if (at === 'end') return geom.end
    return geom.headings.find(x => x.at === at)?.row ?? null
  }
  // where a stamp shows: margin stamps (x < 0) at S within the 3-cell margin; text stamps keep their column, clamped
  function display(st: Stamp) {
    const r = anchorRow(st.at) ?? anchorRow('end')!
    let ds = st.s, col: number
    if (st.x < 0) { ds = Math.min(st.s, GUT - 1); col = Math.min(Math.max(cols + st.x, cols - GUT), cols - ds - 1) }
    else col = Math.min(1 + st.x, cols - GUT - ds)
    return { col, row: Math.max(0, r + st.y), ds }
  }
  // a drop back into the file's shape: nearest heading above (or top / end), margin when it lands in the margin
  function toModel(col: number, row: number, s: number) {
    let at = 'top', ar = geom.top
    for (const h of geom.headings) if (h.row <= row) { at = h.at; ar = h.row }
    if (row >= geom.end) { at = 'end'; ar = geom.end }
    const x = col >= cols - GUT ? Math.min(col - cols, -(s + 1)) : Math.max(0, col - 1)
    return { at, x, y: row - ar }
  }
  function commit(next: Stamp[], index = selected) {
    const cleaned = cleanStamps(next)
    selected = index != null && index < cleaned.length ? index : null
    if (JSON.stringify(cleaned) !== JSON.stringify(stamps)) oncommit(cleaned)
  }
  export function change(patch: Partial<Stamp>) {
    if (selected == null || !stamps[selected]) return
    commit(stamps.map((s, i) => i === selected ? { ...s, ...patch } : s))
  }
  function remove() { if (selected != null) commit(stamps.filter((_, i) => i !== selected), null) }
  function add(k: string, at?: { at: string; x: number; y: number }) {
    const s = size
    let pos = at ?? { at: heading, x: -(s + 1), y: 0 }
    if (!at) while (stamps.some(o => o.at === pos.at && o.x < 0 && Math.abs(o.y - pos.y) < 2)) pos = { ...pos, y: pos.y + 2 }
    commit([...stamps, { k, at: pos.at, x: pos.x, y: pos.y, s, c: ink, r: 0 }], stamps.length)
    open = false
    void tick().then(() => sheet.querySelector<HTMLButtonElement>(`[data-stamp="${stamps.length - 1}"]`)?.focus())
  }
  function cancel() {
    if (drag?.capture.hasPointerCapture(drag.pointer)) drag.capture.releasePointerCapture(drag.pointer)
    drag = null; target = null; dragging = false
    ghostEl?.remove(); ghostEl = null
  }
  function snap(px: number, py: number, ds: number) {
    return { col: Math.max(1, Math.min(cols - ds - 1, Math.round(px / G - ds / 2))), row: Math.max(0, Math.round(py / G - ds / 2)) }
  }
  function start(e: PointerEvent, index: number, k?: string) {
    if ((index < 0 && limit) || e.button !== 0) return
    e.preventDefault(); e.stopPropagation(); measure()
    const stamp: Stamp = index >= 0 ? stamps[index] : { k: k!, at: heading, x: -(size + 1), y: 0, s: size, c: ink, r: 0 }
    const d = index >= 0 ? display(stamp) : { col: 1, row: geom.top, ds: size }
    const capture = e.currentTarget as HTMLElement
    capture.focus(); capture.setPointerCapture(e.pointerId)
    selected = index >= 0 ? index : null
    drag = { index, stamp, x0: e.clientX, y0: e.clientY, ...d, moved: false, capture, pointer: e.pointerId }
  }
  function move(e: PointerEvent) {
    if (!drag) return
    const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0
    if (!drag.moved && Math.hypot(dx, dy) < 4) return
    const rect = sheet.getBoundingClientRect()
    const s = drag.stamp.s
    const at = drag.index < 0
      ? snap(e.clientX - rect.left - s * G / 2, e.clientY - rect.top - s * G / 2, s)
      : snap(drag.col * G + dx, drag.row * G + dy, drag.ds)
    target = { ...drag.stamp, ...toModel(at.col, at.row, s) }
    drag = { ...drag, moved: true }
    if (drag.index < 0) {
      if (!ghostEl) {
        ghostEl = document.createElement('div')
        ghostEl.className = 'np-ghost'
        ghostEl.innerHTML = `<svg viewBox="0 0 48 48">${STAMP_DRAWINGS[drag.stamp.k] || ''}</svg>`
        ghostEl.style.width = ghostEl.style.height = s * G + 'px'; ghostEl.style.color = `var(--ink-${drag.stamp.c})`
        document.body.append(ghostEl)
        dragging = true
      }
      ghostEl.style.left = `${e.clientX - s * G / 2}px`; ghostEl.style.top = `${e.clientY - s * G / 2}px`
    }
  }
  function finish(e: PointerEvent) {
    if (!drag) return
    const d = drag
    const rect = sheet.getBoundingClientRect()
    const inside = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom
    const next = target
    cancel()
    if (d.index < 0) {
      if (!d.moved) { add(d.stamp.k); return }              // a tap in the tray
      if (inside && next) { add(d.stamp.k, { at: next.at, x: next.x, y: next.y }); return }  // a drop on the page
    } else if (d.moved && next) {
      commit(stamps.map((s, i) => i === d.index ? { ...s, at: next.at, x: next.x, y: next.y } : s), d.index)
    }
  }
  function keys(e: KeyboardEvent, index?: number) {
    if (e.key === 'Escape') { e.preventDefault(); cancel(); selected = null; open = false; onclose(); return }
    if (index == null || e.target !== e.currentTarget) return
    selected = index
    const st = stamps[index]
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Delete', 'Backspace'].includes(e.key)) {
      e.preventDefault(); e.stopPropagation()
      if (e.key === 'Delete' || e.key === 'Backspace') remove()
      else change({ x: st.x + (e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0), y: st.y + (e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0) })
    }
  }
</script>

{#snippet svg(k: string)}
  <svg viewBox="0 0 48 48" aria-hidden="true">{@html STAMP_DRAWINGS[k] || ''}</svg>
{/snippet}

<div class="np-layer" aria-label="Stamps on this page">
  {#each stamps as st, i}
    {@const d = display(st)}
    <button type="button" class="np-stamp" data-stamp={i} aria-pressed={selected === i}
      aria-label={`${st.k} stamp at ${st.at}. Arrow keys move; Delete removes.`}
      style={`left:${d.col * G}px;top:${d.row * G}px;--s:${d.ds};--c:var(--ink-${st.c});--r:${st.r}deg`}
      onfocus={() => selected = i} onclick={() => selected = i} onkeydown={e => keys(e, i)}
      onpointerdown={e => start(e, i)} onpointermove={move} onpointerup={finish} onpointercancel={cancel}>
      {@render svg(st.k)}
    </button>
  {/each}
  {#if selected != null && stamps[selected]}
    {@const st = stamps[selected]}
    {@const d = display(st)}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="np-chip" style={`left:${Math.max(4, Math.min(cols * G - 124, (d.col + d.ds) * G - 120))}px;top:${(d.row > 1 ? d.row * G - 48 : (d.row + d.ds) * G + 8)}px`}>
      <button type="button" data-chip="rot" aria-label="Tilt stamp" onclick={() => change({ r: st.r >= 8 ? -8 : st.r + 8 })}><svg viewBox="0 0 16 16"><path d="M13 8a5 5 0 1 1-1.6-3.7"/><path d="M13 2.5v3h-3"/></svg></button>
      <button type="button" data-chip="ink" aria-label="Stamp colour" onclick={onink}><i class="np-dot" style={`--c:var(--ink-${st.c})`}></i></button>
      <button type="button" data-chip="del" aria-label="Remove stamp" onclick={remove}><svg viewBox="0 0 16 16"><path d="m4 4 8 8M12 4l-8 8"/></svg></button>
    </div>
  {/if}
  {#if target}
    {@const d = display(target)}
    <span class="np-target" style={`left:${d.col * G}px;top:${d.row * G}px;width:${d.ds * G}px;height:${d.ds * G}px`}></span>
  {/if}
</div>

{#if open}
  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <section class="m-sheet np-sheet np-tray" class:dragging id="np-tray" role="dialog" aria-label="Stamps">
    <i class="np-grab" aria-hidden="true"></i>
    <div class="np-sh-hd"><h3>Stamps</h3>
      <div class="m-seg sm np-size" role="group" aria-label="Stamp size">
        {#each [2, 3, 4] as s}<button type="button" aria-pressed={size === s} onclick={() => size = s}>{s === 2 ? 'S' : s === 3 ? 'M' : 'L'}</button>{/each}
      </div>
      <button type="button" class="np-x" aria-label="Close stamps" onclick={() => { open = false; onclose() }}><svg viewBox="0 0 14 14"><path d="m3 3 8 8M11 3l-8 8"/></svg></button>
    </div>
    <div class="np-grid">
      {#each STAMPS as k}
        <button type="button" class="np-tstamp" style={`--c:var(--ink-${ink})`} aria-label={`Add ${k} stamp`} disabled={limit}
          onpointerdown={e => start(e, -1, k)} onpointermove={move} onpointerup={finish} onpointercancel={cancel}
          onclick={e => { if (e.detail === 0 && !limit) add(k) }}>{@render svg(k)}</button>
      {/each}
    </div>
    <MHint as="p">{limit ? `Limit of ${MAX_STAMPS} stamps reached. Remove one to add another.` : 'Tap one to put it beside this section, or drag it onto the page. It snaps to the dots and takes the current ink.'}</MHint>
  </section>
{/if}
