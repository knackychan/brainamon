<script lang="ts">
  // The board: every visible item, windowed by rows. Keeps the V6 CSS grid (auto-fill columns of
  // --card + --gap); only the rows on screen plus one above and one below are mounted, with a top
  // and a bottom spacer row (grid-column 1 / -1) standing in for the rest. Geometry is measured
  // from the live grid: columns = the computed grid-template-columns tracks, row height = the first
  // cell's height + row gap. Re-measured on zoom, view, card style and resize.
  import { tick } from 'svelte'
  import Cell from './Cell.svelte'
  import ListRow from './ListRow.svelte'
  import { lib, Z } from '../../lib/library.svelte'
  import { readyAfterPaint, ui } from '../../lib/ui.svelte'
  import { anchor, bindBoard, geo, scheduleMap, setZoom } from '../../lib/map'
  import { openCardMenu } from '../../lib/cardmenu'
  import { tapMod } from './tap'
  import EmptyLibrary from './EmptyLibrary.svelte'

  let board: HTMLDivElement | undefined = $state()
  let grid: HTMLDivElement | undefined = $state()
  let scrollTop = $state(0)
  let viewH = $state(800)
  let cols = $state(1)
  let rowH = $state(300)
  let gap = $state(22)
  let top0 = $state(0)

  const items = $derived(lib.visible)
  const nRows = $derived(Math.ceil(items.length / cols))
  // clamped: after a filter shrinks the list the old scrollTop can lie past the end; the board
  // then shrinks, the browser clamps scrollTop and the scroll event re-windows
  const inView = $derived(Math.ceil(viewH / rowH))
  const first = $derived(Math.max(0, Math.min(Math.floor((scrollTop - top0) / rowH) - 1, nRows - inView - 1)))
  const last = $derived(Math.min(nRows, Math.max(Math.ceil((scrollTop - top0 + viewH) / rowH) + 1, first + inView + 2)))
  const slice = $derived(items.slice(first * cols, last * cols))
  const topH = $derived(first > 0 ? first * rowH - gap : 0)
  const botH = $derived(last < nRows ? (nRows - last) * rowH - gap : 0)

  // a first guess before the grid exists: the V6 card proportions
  function estimate() {
    if (!board) return
    const card = Z[lib.zi], g = lib.view === 'list' ? 6 : card * 0.14
    cols = lib.view === 'list' ? 1 : Math.max(1, Math.floor((board.clientWidth - 20) / (card + g)))
    rowH = lib.view === 'list' ? 70 : card * 88 / 63 + 18 + g
    gap = g
  }

  function measure() {
    if (!board || !grid) return
    viewH = board.clientHeight
    scrollTop = board.scrollTop
    const cs = getComputedStyle(grid)
    cols = Math.max(1, cs.gridTemplateColumns.split(' ').filter(Boolean).length)
    gap = parseFloat(cs.rowGap) || 0
    top0 = grid.offsetTop
    const cell = grid.querySelector<HTMLElement>('.cell')
    if (cell) rowH = cell.offsetHeight + gap
    Object.assign(geo, { cols, rowH, top0, cellH: cell ? cell.offsetHeight : rowH - gap })
    const a = anchor[0]
    if (a) {
      anchor[0] = null
      const i = lib.visIds.indexOf(a.id)
      if (i >= 0) { board.scrollTop = top0 + Math.floor(i / cols) * rowH - a.dy; scrollTop = board.scrollTop }
    }
    scheduleMap()
  }

  // re-measure when the card size, the layout or the card style changes, or the list fills
  let marked = false
  $effect(() => {
    lib.zi; lib.view; lib.variant
    const n = items.length > 0
    const ready = lib.loaded && ui.ws === 'lib'
    board?.style.setProperty('--card', Z[lib.zi] + 'px')
    estimate()
    tick().then(() => requestAnimationFrame(() => {
      measure()
      if (ready && !marked && (!n || grid?.querySelector('.cell'))) {
        marked = true
        if (n) performance.mark('cm-first-cards')
        readyAfterPaint('lib')                    // includes an empty library and list view
      }
    }))
  })
  // a filter change starts at the top; redraw the map
  $effect(() => { items; scheduleMap() })

  $effect(() => {
    if (!board) return
    bindBoard(board)
    const ro = new ResizeObserver(() => measure())
    ro.observe(board)
    return () => { ro.disconnect(); bindBoard(null) }
  })

  function onScroll() {
    if (!board) return
    scrollTop = board.scrollTop
    scheduleMap(false)
  }

  // Ctrl + wheel and pinch step the zoom (V6)
  let wacc = 0
  function onWheel(e: WheelEvent) {
    if (!(e.ctrlKey || e.metaKey)) return
    e.preventDefault()
    wacc += e.deltaY
    if (Math.abs(wacc) > 36) { setZoom(lib.zi + (wacc > 0 ? -1 : 1), { x: e.clientX, y: e.clientY }); wacc = 0 }
  }
  let pinch: { d: number } | null = null
  const dist = (t: TouchList) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
  function touchStart(e: TouchEvent) { if (e.touches.length === 2) pinch = { d: dist(e.touches) } }
  function touchMove(e: TouchEvent) {
    if (!pinch || e.touches.length !== 2) return
    e.preventDefault()
    const d = dist(e.touches), mid = { x: (e.touches[0].clientX + e.touches[1].clientX) / 2, y: (e.touches[0].clientY + e.touches[1].clientY) / 2 }
    if (d / pinch.d > 1.22) { setZoom(lib.zi + 1, mid); pinch.d = d } else if (d / pinch.d < 0.82) { setZoom(lib.zi - 1, mid); pinch.d = d }
  }

  function onContext(e: MouseEvent) {
    const c = (e.target as HTMLElement).closest<HTMLElement>('.cell[data-id]')
    if (!c) return
    e.preventDefault()
    const from = (e.target as HTMLElement).closest<HTMLElement>('.slot,.lr-open,button') ?? c
    const r = from.getBoundingClientRect()
    openCardMenu(+c.dataset.id!, e.clientX || e.clientY ? { x: e.clientX, y: e.clientY } : { x: r.left + 20, y: r.top + 20 }, from)
  }

  // remember Ctrl / Shift at pointerdown: the card engine's tap callback has no event (V6 tapMod)
  function down(e: PointerEvent) { tapMod.shift = e.shiftKey; tapMod.ctrl = e.ctrlKey || e.metaKey }
  function keydown() { tapMod.shift = false; tapMod.ctrl = false }
  // the Viewing tile follows the card under the pointer
  function over(e: PointerEvent) {
    const c = (e.target as HTMLElement).closest<HTMLElement>('.cell[data-id]')
    if (c && +c.dataset.id! !== lib.nvId) lib.nvId = +c.dataset.id!
  }

  const q = $derived(lib.q.trim())

  // First load: skeleton cards fill the first screen until the rows arrive; then the cards fade in,
  // in reading order (app.css #grid.fade, Cell --i), and the class goes so scrolling never replays it.
  const skN = $derived(Math.min(60, cols * (Math.ceil(viewH / rowH) + 1)))
  let fade = $state(false), faded = false
  $effect(() => {
    if (faded || !lib.loaded || !items.length) return
    faded = true
    fade = true
    setTimeout(() => (fade = false), 1300)
  })
  // a card thumbnail fades in once it has loaded (or failed), never half-drawn (app.css img.art)
  function artIn(e: Event) { const t = e.target as HTMLElement; if (t.tagName === 'IMG') t.classList.add('ld') }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="board" class:lv={lib.view === 'list'} class:zs={Z[lib.zi] <= 116} class:selecting={lib.sel.size > 0}
  id="board" tabindex="-1" bind:this={board} onscroll={onScroll} onwheel={onWheel}
  ontouchstart={touchStart} ontouchmove={touchMove} ontouchend={() => (pinch = null)}>
  <div class="grid" class:fade id="grid" bind:this={grid} aria-busy={!lib.loaded} onloadcapture={artIn} onerrorcapture={artIn} onpointerdowncapture={down} onkeydowncapture={keydown} oncontextmenu={onContext} onpointerover={over}>
    {#if !lib.loaded}
      <p class="sk-sr" role="status">Loading the library</p>
      {#each { length: skN } as _, i (i)}<div class="sk-cell" aria-hidden="true"><div class="sk-card"><i class="sk-art"></i><i class="sk-l"></i><i class="sk-l"></i></div></div>{/each}
    {/if}
    {#if lib.loaded && !items.length}
      {#if !lib.rows.length}
        <EmptyLibrary />
      {:else}
        <p class="empty">No items match{q ? ` “${q}”` : ' these filters'}.{q && !lib.rank ? ' Switch on SMART and press Enter to search by meaning, or' : ''}
          <button type="button" class="linkk" data-cmd="clear-filters">Clear filters</button></p>
      {/if}
    {/if}
    {#if topH > 0}<div class="vsp" style:grid-column="1 / -1" style:height="{topH}px"></div>{/if}
    {#each slice as r, i (r.id)}
      {#if lib.view === 'list'}<ListRow row={r} />{:else}<Cell row={r} {i} sk={fade} />{/if}
    {/each}
    {#if botH > 0}<div class="vsp" style:grid-column="1 / -1" style:height="{botH}px"></div>{/if}
  </div>
</div>
