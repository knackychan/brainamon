<script lang="ts">
  import { onMount, tick } from 'svelte'
  import { cleanStamps, INKS, MAX_STAMPS, SIZES, STAMPS, type Ink, type Stamp } from '../../lib/note-format'
  import { GRID, headingName, stampFromPoint, stampPosition, type Geometry } from '../../lib/note-editor'
  import { STAMP_DRAWINGS } from '../../lib/stamps'

  let { stamps, sheet, bodyRoot, readonly = false, open = $bindable(false), selected = $bindable<number | null>(null),
    ink = 'indigo', heading = 'top', oncommit, onclose }: {
    stamps: Stamp[]; sheet: HTMLElement; bodyRoot: HTMLElement; readonly?: boolean; open?: boolean; selected?: number | null;
    ink?: Ink; heading?: string; oncommit: (s: Stamp[]) => void; onclose: () => void
  } = $props()
  let size = $state(2)
  let geometry: Geometry = $state.raw({ width: 800, height: 600, textLeft: 72, textRight: 650, top: 48, end: 400, headings: [] })
  let drag = $state.raw<{ index: number; stamp: Stamp; start: { x: number; y: number }; left: number; top: number; moved: boolean; capture: HTMLElement; pointer: number } | null>(null)
  let target: Stamp | null = $state.raw(null)
  const limit = $derived(stamps.length >= MAX_STAMPS)

  // DRAWINGS: the shared static map (lib/stamps.ts); never supplied by note data.
  const drawings = STAMP_DRAWINGS

  function measure() {
    if (!sheet || !bodyRoot) return
    const page = sheet.getBoundingClientRect(), body = bodyRoot.getBoundingClientRect()
    const title = sheet.querySelector('#nt-title')?.getBoundingClientRect()
    geometry = { width: sheet.clientWidth, height: sheet.clientHeight, textLeft: body.left - page.left, textRight: body.right - page.left,
      top: title ? title.top - page.top : 48, end: body.bottom - page.top,
      headings: [...bodyRoot.querySelectorAll('h1,h2,h3')].map(h => ({ at: headingName(h.textContent || ''), row: h.getBoundingClientRect().top - page.top })) }
  }
  $effect(() => { stamps; sheet; bodyRoot; void tick().then(measure) })
  onMount(() => {
    const ro = new ResizeObserver(measure), mo = new MutationObserver(measure)
    ro.observe(sheet); ro.observe(bodyRoot); mo.observe(bodyRoot, { childList: true, subtree: true, characterData: true })
    let mounted = true
    void document.fonts.ready.then(() => { if (mounted) measure() })
    return () => { mounted = false; ro.disconnect(); mo.disconnect(); cancel() }
  })

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
  function cancel() {
    if (drag?.capture.hasPointerCapture(drag.pointer)) drag.capture.releasePointerCapture(drag.pointer)
    drag = null; target = null
  }
  function start(e: PointerEvent, index: number, k?: string) {
    if (readonly || (index < 0 && limit) || e.button !== 0) return
    e.preventDefault(); e.stopPropagation(); measure()
    const stamp: Stamp = index >= 0 ? stamps[index] : { k: k!, at: heading, x: -(size + 1), y: 0, s: size, c: ink, r: 0 }
    const pos = stampPosition(stamp, geometry)
    const capture = e.currentTarget as HTMLElement
    capture.focus(); capture.setPointerCapture(e.pointerId)
    selected = index >= 0 ? index : null
    drag = { index, stamp, start: { x: e.clientX, y: e.clientY }, ...pos, moved: false, capture, pointer: e.pointerId }
  }
  function move(e: PointerEvent) {
    if (!drag) return
    const dx = e.clientX - drag.start.x, dy = e.clientY - drag.start.y
    if (!drag.moved && Math.hypot(dx, dy) < 4) return
    const rect = sheet.getBoundingClientRect()
    const left = drag.index < 0 ? e.clientX - rect.left - drag.stamp.s * GRID / 2 : drag.left + dx
    const top = drag.index < 0 ? e.clientY - rect.top - drag.stamp.s * GRID / 2 : drag.top + dy
    target = cleanStamps([stampFromPoint(drag.stamp, left, top, geometry)])[0]
    drag = { ...drag, moved: true }
  }
  function finish(e: PointerEvent) {
    if (!drag) return
    const d = drag, next = target || d.stamp
    const rect = sheet.getBoundingClientRect()
    const inside = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom
    cancel()
    if (d.index < 0 && (!d.moved || inside)) {
      commit([...stamps, next], stamps.length)
      void tick().then(() => sheet.querySelector<HTMLButtonElement>(`[data-stamp="${stamps.length - 1}"]`)?.focus())
    } else if (d.index >= 0 && d.moved) commit(stamps.map((s, i) => i === d.index ? next : s), d.index)
  }
  function keys(e: KeyboardEvent, index?: number) {
    if (e.key === 'Escape') { e.preventDefault(); cancel(); selected = null; open = false; onclose(); return }
    if (readonly || index == null || e.target !== e.currentTarget) return
    selected = index
    const st = stamps[index]
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Delete', 'Backspace'].includes(e.key)) {
      e.preventDefault(); e.stopPropagation()
      if (e.key === 'Delete' || e.key === 'Backspace') remove()
      else change({ x: st.x + (e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0), y: st.y + (e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0) })
    }
  }
</script>

{#snippet drawing(k: string)}
  <svg viewBox="0 0 48 48" aria-hidden="true">{@html drawings[k] || ''}</svg>
{/snippet}

<div class="np-layer" aria-label="Stamps on this page">
  {#each stamps as st, i}
    {@const pos = stampPosition(drag?.index === i && target ? target : st, geometry)}
    {#if readonly}
      <span class="np-stamp fixed" role="img" aria-label={`${st.k} stamp at ${st.at}`} style={`left:${pos.left}px;top:${pos.top}px;width:${st.s * GRID}px;height:${st.s * GRID}px;color:var(--ink-${st.c});--tilt:${st.r}deg`}>{@render drawing(st.k)}</span>
    {:else}
      <button type="button" class="np-stamp" data-stamp={i} aria-pressed={selected === i}
        aria-label={`${st.k} stamp at ${st.at}. Arrow keys move; Delete removes. Size, tilt and ink in Stamps.`}
        style={`left:${pos.left}px;top:${pos.top}px;width:${st.s * GRID}px;height:${st.s * GRID}px;color:var(--ink-${st.c});--tilt:${st.r}deg`}
        onfocus={() => selected = i} onclick={() => selected = i} onkeydown={e => keys(e, i)}
        onpointerdown={e => start(e, i)} onpointermove={move} onpointerup={finish} onpointercancel={cancel}>
        {@render drawing(st.k)}
      </button>
    {/if}
  {/each}
  {#if target}
    {@const pos = stampPosition(target, geometry)}
    <span class="np-target" style={`left:${pos.left}px;top:${pos.top}px;width:${target.s * GRID}px;height:${target.s * GRID}px`}></span>
  {/if}
</div>

{#if open && !readonly}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <aside class="np-tray" id="np-tray" aria-label="Stamps" onkeydown={keys}>
    <header><h3>Stamps</h3><button type="button" aria-label="Close stamps" onclick={() => { open = false; onclose() }}>Close</button></header>
    <div class="stamp-options">
      <label>Size <select aria-label="Stamp size" value={selected == null ? size : stamps[selected]?.s} onchange={e => { size = +e.currentTarget.value; change({ s: size }) }}>{#each SIZES as s}<option value={s}>{s === 2 ? 'Small' : s === 3 ? 'Medium' : 'Large'}</option>{/each}</select></label>
      {#if selected != null}
        <label>Tilt <select aria-label="Stamp tilt" value={stamps[selected]?.r} onchange={e => change({ r: +e.currentTarget.value })}><option value="-8">Left</option><option value="0">Straight</option><option value="8">Right</option></select></label>
        <label>Ink <select aria-label="Stamp ink" value={stamps[selected]?.c} onchange={e => change({ c: e.currentTarget.value as Ink })}>{#each INKS as c}<option>{c}</option>{/each}</select></label>
        <button type="button" onclick={remove}>Remove stamp</button>
      {/if}
    </div>
    <div class="np-grid">
      {#each STAMPS as k}<button type="button" class="np-tstamp" aria-label={`Add ${k} stamp`} disabled={limit}
        onpointerdown={e => start(e, -1, k)} onpointermove={move} onpointerup={finish} onpointercancel={cancel}
        onclick={e => { if (e.detail === 0 && !limit) commit([...stamps, { k, at: heading, x: -(size + 1), y: 0, s: size, c: ink, r: 0 }], stamps.length) }}>
        {@render drawing(k)}<span>{k}</span>
      </button>{/each}
    </div>
    <p aria-live="polite">{limit ? `Limit of ${MAX_STAMPS} stamps reached. Remove one to add another.` : 'Click for the margin, or drag onto the page. Select a stamp to move it with arrow keys.'}</p>
  </aside>
{/if}

<style>
  .np-layer { position: absolute; inset: 0; pointer-events: none }
  .np-stamp { position: absolute; padding: 0; border: 1px solid transparent; border-radius: 8px; background: transparent; pointer-events: auto; touch-action: none; cursor: grab; z-index: 2 }
  .np-stamp.fixed { pointer-events: none }
  .np-stamp[aria-pressed=true] { border: 1px dashed var(--ink-indigo); background: var(--np-tint) }
  .np-stamp :global(svg) { transform: rotate(var(--tilt)) }
  :global(.np-stamp svg), :global(.np-tstamp svg) { display: block; width: 100%; height: 100%; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round }
  :global(.np-stamp svg *), :global(.np-tstamp svg *) { vector-effect: non-scaling-stroke }
  :global(.np-stamp .f), :global(.np-tstamp .f) { fill: currentColor; stroke: none }
  .np-target { position: absolute; border: 1px dashed var(--ink-indigo); background: var(--np-tint); pointer-events: none; z-index: 3 }
  .np-tray { position: sticky; bottom: 12px; margin: 12px 12px 0 auto; width: min(360px, calc(100% - 24px)); max-height: 65vh; overflow: auto; padding: 14px; border: 1px solid var(--np-edge); border-radius: 16px; background: var(--np-solid); color: var(--np-ink); box-shadow: 0 14px 30px -16px rgba(30,26,110,.5); z-index: 5; box-sizing: border-box; pointer-events: auto }
  header { display: flex; align-items: center; justify-content: space-between; gap: 8px }
  h3 { margin: 0; font-size: 16px }
  button, select { color: inherit; font: inherit }
  header button, .stamp-options button, select { border: 1px solid var(--np-edge); border-radius: 8px; padding: 5px; background: var(--np-paper); font-size: 12px }
  .stamp-options { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 12px 0; font-size: 12px }
  .np-grid { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 4px }
  .np-tstamp { min-width: 0; padding: 3px; border: 0; border-radius: 8px; background: transparent; color: var(--ink-indigo); touch-action: none; cursor: grab }
  .np-tstamp :global(svg) { height: 40px }
  .np-tstamp span { display: block; font-size: 9px; overflow-wrap: anywhere; color: var(--np-dim) }
  button:hover { background: var(--np-tint) }
  button:disabled { opacity: .4; cursor: default }
  p { font-size: 12px; line-height: 18px; color: var(--np-dim); margin: 12px 0 0 }
  :is(button,select):focus-visible { outline: 2px solid var(--ink-indigo); outline-offset: 2px }
</style>
