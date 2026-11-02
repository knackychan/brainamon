<script lang="ts">
  // The Library grid: two columns of locked cards, windowed like the desktop's VirtualGrid (only the
  // rows on screen plus one above and below are mounted, spacers keep the scroll height) so 3,000+
  // cards scroll at the phone's frame rate. Grid cards do not tilt (scrolling stays native); the
  // Item screen's card does. A tap opens the Item screen.
  import { onMount, tick } from 'svelte'
  import { cardMarkup, isBare, tintOf } from './cards'
  import type { Row } from './source/types'
  import { phone, solo } from './state.svelte'
  import { themeSlot } from '../lib/cards/theme'
  import { srcMark } from './outbox.svelte'

  let { rows, scroller }: { rows: Row[]; scroller: HTMLElement | undefined } = $props()

  const COLS = 2, GAP = 14, PAD_X = 14
  let el: HTMLDivElement | undefined = $state()
  let width = $state(360)
  let scrollTop = $state(0)
  let viewH = $state(700)
  let top0 = $state(0)

  const cellW = $derived((width - PAD_X * 2 - 12) / COLS)
  // under a card narrower than 240 px a caption in UI type repeats its title, creator and collection
  // (lib/cards/small.css, audit 2026-10-15 #1); CAP_H is that caption's height
  const CAP_H = 44
  const capped = $derived(cellW < 240)
  const rowH = $derived(cellW * 88 / 63 + (capped ? CAP_H : 0) + GAP)
  const nRows = $derived(Math.ceil(rows.length / COLS))
  const first = $derived(Math.max(0, Math.floor((scrollTop - top0) / rowH) - 1))
  const last = $derived(Math.min(nRows, Math.ceil((scrollTop - top0 + viewH) / rowH) + 1))
  const topH = $derived(first * rowH)
  const botH = $derived(Math.max(0, (nRows - last) * rowH - GAP))
  const slice = $derived(rows.slice(first * COLS, last * COLS))

  function measure() {
    if (!el || !scroller) return
    width = el.clientWidth
    viewH = scroller.clientHeight
    top0 = el.offsetTop
    scrollTop = scroller.scrollTop
  }
  onMount(() => {
    measure()
    const ro = new ResizeObserver(measure)
    if (el) ro.observe(el)
    const onScroll = () => { if (scroller) phone.scroll.lib = scrollTop = scroller.scrollTop }
    scroller?.addEventListener('scroll', onScroll, { passive: true })
    const offHold = el ? holdGuard(el) : () => {}
    // back from an item: the same place in the list
    const saved = phone.scroll.lib
    if (saved && scroller) tick().then(() => { scroller!.scrollTop = saved; scrollTop = saved })
    return () => { offHold(); ro.disconnect(); scroller?.removeEventListener('scroll', onScroll) }
  })

  // a tap opens the Item screen, a hold does not: the engine's own numbers (design/card-designs/engine.js:
  // a tap is an up within 380 ms, a finger that travels past 6 px is a drag), so the click the
  // browser sends after a held or moved finger is dropped. No link menu on a long press either.
  const HOLD_MS = 380, SLOP = 6
  function holdGuard(grid: HTMLElement): () => void {
    let t0 = 0, x0 = 0, y0 = 0, touching = false, held = false
    const start = (e: TouchEvent) => { const t = e.touches[0]; if (!t) return; touching = true; held = false; t0 = performance.now(); x0 = t.clientX; y0 = t.clientY }
    const move = (e: TouchEvent) => { const t = e.touches[0]; if (t && Math.hypot(t.clientX - x0, t.clientY - y0) > SLOP) held = true }
    const end = () => { touching = false; if (performance.now() - t0 >= HOLD_MS) held = true }
    const click = (e: MouseEvent) => {
      if (!held || !(e.target as Element | null)?.closest?.('.m-cell-a')) return
      e.preventDefault(); e.stopPropagation(); held = false
    }
    const menu = (e: Event) => { if (touching && (e.target as Element | null)?.closest?.('.m-cell-a')) e.preventDefault() }
    grid.addEventListener('touchstart', start, { passive: true })
    grid.addEventListener('touchmove', move, { passive: true })
    grid.addEventListener('touchend', end)
    grid.addEventListener('touchcancel', end)
    grid.addEventListener('click', click, true)
    grid.addEventListener('contextmenu', menu)
    return () => {
      grid.removeEventListener('touchstart', start)
      grid.removeEventListener('touchmove', move)
      grid.removeEventListener('touchend', end)
      grid.removeEventListener('touchcancel', end)
      grid.removeEventListener('click', click, true)
      grid.removeEventListener('contextmenu', menu)
    }
  }
  // the card's category colour, the creator in the stub (src/lib/cards/theme.ts); a decoded image shows at once
  function theme(node: HTMLElement, r: Row) {
    const apply = (row: Row) => {
      const s = node.querySelector<HTMLElement>('.slot')
      if (s) themeSlot(s, row)
    }
    apply(r)
    return { update: apply }
  }
</script>

<div class="m-grid" bind:this={el} style:--m-gap="{GAP}px">
  <div style:height="{topH}px"></div>
  <div class="m-grid-rows">
    {#each slice as r (r.id)}
      <div class="m-cell" style:min-height={capped ? `${rowH - GAP}px` : undefined}>
        <a class="m-cell-a" href={`#/item/${r.id}`} aria-label={`Open the details of ${r.title || 'No.' + r.id}`}>
        {#if isBare(r)}
          <div class="m-ghost"><span class="m-src">{srcMark(r.url)}</span><span class="m-u">{r.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)}</span><span class="m-badge">{r.id < 0 ? (solo ? 'Link' : 'Waits for the PC') : 'No details yet'}</span></div>
        {:else if !r.thumb}
          <div class="m-tint" style:background="linear-gradient(160deg,{tintOf(r)},color-mix(in srgb,{tintOf(r)} 55%,#000))"><b>{r.title || 'No.' + r.id}</b><small>{r.creator || r.src} · no thumbnail yet</small></div>
        {:else}
          {#key r.fav + ':' + r.tv + ':' + phone.cardStyle}<div use:theme={r}>{@html cardMarkup(r)}</div>{/key}
          {#if capped}<div class="card-cap" style:height="{CAP_H}px"><b>{r.title || 'No.' + r.id}</b><small>{[r.creator || 'unknown', r.cat].filter(Boolean).join(' · ')}</small></div>{/if}
        {/if}
        </a>
      </div>
    {/each}
  </div>
  <div style:height="{botH}px"></div>
</div>
