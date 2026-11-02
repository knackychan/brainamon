<script lang="ts">
  // The map strip beside the mat (V6 #mmap): click or drag to scroll the board, hover for a label,
  // wheel and keys scroll. Drawing is lib/map.ts (once per frame at most).
  import { lib } from '../../lib/library.svelte'
  import { bindMap, mapHit, mapTo, scheduleMap } from '../../lib/map'
  import { titleOf } from '../../lib/cards/card'
  import { ui } from '../../lib/ui.svelte'

  let mm: HTMLDivElement | undefined = $state()
  let cv: HTMLCanvasElement | undefined = $state()
  let tip = $state<{ text: string; id: number; y: number } | null>(null)
  let drag = false

  $effect(() => {
    if (!mm || !cv) return
    bindMap(mm, cv)
    const ro = new ResizeObserver(scheduleMap)
    ro.observe(mm)
    return () => { ro.disconnect(); bindMap(null, null) }
  })
  // redraw when what the dots show changes
  $effect(() => { lib.visible; lib.sel.size; lib.tints; lib.cellState.size; ui.dark; ui.ws; scheduleMap() })

  const board = () => document.getElementById('board')
  function down(e: PointerEvent) { drag = true; try { mm?.setPointerCapture(e.pointerId) } catch { /* not capturable */ } mapTo(e); tip = null }
  function move(e: PointerEvent) {
    if (drag) { mapTo(e); return }
    if (e.pointerType !== 'mouse') return
    const w = mapHit(e)
    const r = w ? lib.byId.get(w.id) : null
    tip = w && r ? { text: titleOf(r), id: r.id, y: w.y - 10 } : null
  }
  function key(e: KeyboardEvent) {
    const b = board()
    if (!b) return
    const k = ({ ArrowDown: 80, ArrowUp: -80, PageDown: b.clientHeight * 0.9, PageUp: -b.clientHeight * 0.9 } as Record<string, number>)[e.key]
    if (k) { e.preventDefault(); b.scrollTop += k }
    else if (e.key === 'Home') { e.preventDefault(); b.scrollTop = 0 }
    else if (e.key === 'End') { e.preventDefault(); b.scrollTop = b.scrollHeight }
  }
  function wheel(e: WheelEvent) { e.preventDefault(); const b = board(); if (b) b.scrollTop += e.deltaY }
</script>

<div class="mmap" id="mmap" role="scrollbar" aria-controls="board" aria-orientation="vertical" aria-label="Library map: one dot per card"
  aria-valuemin={0} aria-valuemax={100} aria-valuenow={0} tabindex="0" bind:this={mm}
  onpointerdown={down} onpointermove={move} onpointerup={() => (drag = false)} onpointercancel={() => (drag = false)}
  onpointerleave={() => (tip = null)} onwheel={wheel} onkeydown={key}>
  <canvas id="mm-cv" bind:this={cv}></canvas><span class="mm-hd" aria-hidden="true">MAP</span><span class="mm-ft" id="mm-pct" aria-hidden="true">0</span>
  <span class="mm-tip" id="mm-tip" hidden={!tip} style:top={tip ? tip.y + 'px' : undefined}>{#if tip}<b>No.{tip.id}</b> {tip.text}{/if}</span>
</div>
