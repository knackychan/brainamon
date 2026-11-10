<script lang="ts">
  // The Library gallery: cards or compact rows, windowed like the desktop's VirtualGrid (only the
  // rows on screen plus one above and below are mounted, spacers keep the scroll height) so 3,000+
  // cards scroll at the phone's frame rate. Grid cards do not tilt (scrolling stays native); the
  // Item screen's card does. A tap opens the Item screen.
  import { onMount, tick, untrack } from 'svelte'
  import { cardMarkup, ghostText, isBare, themeCard, tintOf, tintText } from './cards'
  import type { Row } from './source/types'
  import { phone, source } from './state.svelte'
  import { t } from '../lib/i18n/index.ts'
  import { srcMark } from './outbox.svelte'
  import { work, workLabel, type WorkMark } from './work.svelte'

  let { rows, scroller }: { rows: Row[]; scroller: HTMLElement | undefined } = $props()

  const PAD_X = 14, GAP_X = 12
  const list = $derived(phone.gallery === 'rows')
  const cols = $derived(list ? 1 : Number(phone.gallery))
  const gap = $derived(list ? 8 : 14)
  let el: HTMLDivElement | undefined = $state()
  let width = $state(360)
  let scrollTop = $state(0)
  let viewH = $state(700)
  let top0 = $state(0)

  const cellW = $derived((width - PAD_X * 2 - GAP_X * (cols - 1)) / cols)
  // under a card narrower than 240 px a caption in UI type repeats its title, creator and collection
  // (lib/cards/small.css, audit 2026-10-15 #1); CAP_H is that caption's height
  const CAP_H = 44
  const capped = $derived(cellW < 240)
  const rowH = $derived(list ? 88 : cellW * 88 / 63 + (capped ? CAP_H : 0) + gap)
  const nRows = $derived(Math.ceil(rows.length / cols))
  const first = $derived(Math.max(0, Math.floor((scrollTop - top0) / rowH) - 1))
  const last = $derived(Math.min(nRows, Math.ceil((scrollTop - top0 + viewH) / rowH) + 1))
  const topH = $derived(first * rowH)
  const botH = $derived(Math.max(0, (nRows - last) * rowH - gap))
  const slice = $derived(rows.slice(first * cols, last * cols))

  // Keep the first visible item in view when the layout or viewport changes.
  let previousCols = 2, previousH = 1
  $effect.pre(() => {
    const nextCols = cols, nextH = rowH
    untrack(() => {
      const index = Math.max(0, Math.floor((scrollTop - top0) / previousH)) * previousCols
      const y = top0 + Math.floor(index / previousCols) * previousH - scrollTop
      if (scrollTop > top0 && scroller) {
        scrollTop = Math.max(0, top0 + Math.floor(index / nextCols) * nextH - y * nextH / previousH)
        phone.scroll.lib = scrollTop
        tick().then(() => { if (scroller) { scroller.scrollTop = scrollTop; measure() } })
      }
      previousCols = nextCols; previousH = nextH
    })
  })

  function measure() {
    if (!el || !scroller) return
    width = el.clientWidth
    viewH = scroller.clientHeight
    // the grid's top inside the scrolled content: offsetTop counts from the page, so it would include the
    // shell's top bar above the scroller (projects/phone-dock-shell/plans/06, Troubleshooting)
    top0 = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop + 12
    scrollTop = scroller.scrollTop
  }
  onMount(() => {
    measure()
    const ro = new ResizeObserver(measure)
    if (el) ro.observe(el)
    // content above the grid (the Tools panel) opening or closing moves the grid without resizing it:
    // watch the scroller's content too, and re-measure the grid's top on every scroll
    if (scroller?.firstElementChild) ro.observe(scroller.firstElementChild)
    const onScroll = () => { if (scroller) { measure(); phone.scroll.lib = scrollTop } }
    scroller?.addEventListener('scroll', onScroll, { passive: true })
    const offHold = el ? holdGuard(el) : () => {}
    // Restore first; a strip visit may have ended on an item outside that viewport.
    const saved = phone.scroll.lib || 0, opened = phone.lastItem
    phone.lastItem = null
    tick().then(() => {
      if (!el?.isConnected || !scroller) return
      scroller.scrollTop = saved
      measure()
      const i = rows.findIndex(r => r.id === opened)
      if (i >= 0) {
        const y = top0 + Math.floor(i / cols) * rowH, h = rowH - gap
        if (y + h <= scrollTop || y >= scrollTop + viewH) scroller.scrollTop = Math.max(0, y + h / 2 - viewH / 2)
      }
      measure()
      phone.scroll.lib = scrollTop
    })
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
    let distance = 0, pinchCols = 2, pinching = false
    const span = (e: TouchEvent) => Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY)
    const touchStart = (e: TouchEvent) => {
      if (e.touches.length < 2) { if (!pinching) start(e); return }
      held = pinching = true; touching = false
      distance = span(e); pinchCols = list ? 2 : cols
      e.preventDefault()
    }
    const touchMove = (e: TouchEvent) => {
      if (!pinching) { move(e); return }
      e.preventDefault()
      if (e.touches.length !== 2 || !distance) return
      const ratio = span(e) / distance
      if (ratio < .8 || ratio > 1.25) {
        phone.gallery = String(Math.max(2, Math.min(4, Math.round(pinchCols / ratio))))
      }
    }
    const touchEnd = (e: TouchEvent) => {
      if (pinching) { held = true; if (!e.touches.length) pinching = false }
      else end()
    }
    grid.addEventListener('touchstart', touchStart, { passive: false })
    grid.addEventListener('touchmove', touchMove, { passive: false })
    grid.addEventListener('touchend', touchEnd)
    grid.addEventListener('touchcancel', touchEnd)
    grid.addEventListener('click', click, true)
    grid.addEventListener('contextmenu', menu)
    return () => {
      grid.removeEventListener('touchstart', touchStart)
      grid.removeEventListener('touchmove', touchMove)
      grid.removeEventListener('touchend', touchEnd)
      grid.removeEventListener('touchcancel', touchEnd)
      grid.removeEventListener('click', click, true)
      grid.removeEventListener('contextmenu', menu)
    }
  }
  // the card's category colour, the creator in the stub (src/lib/cards/theme.ts, then the phone's words: cards.ts themeCard);
  // a decoded image shows at once
  function theme(node: HTMLElement, r: Row) {
    const apply = (row: Row) => {
      const s = node.querySelector<HTMLElement>('.slot')
      if (s) themeCard(s, row)
    }
    apply(r)
    return { update: apply }
  }
  const cellLabel = (r: Row, w: WorkMark | undefined) => {
    const title = r.title || 'No.' + r.id
    if (!w) return t('library.cell.open', { title })
    return t(w.st === 'wait' ? 'library.cell.openWaiting' : w.st === 'run' ? 'library.cell.openRunning' : w.st === 'done' ? 'library.cell.openDone' : 'library.cell.openFailed', { title })
  }
</script>

<div class="m-grid" class:m-gallery-dense={cols > 2} bind:this={el} style:--m-gap="{gap}px" style:--m-cols={cols} style:--m-card-height="{cellW * 88 / 63}px">
  <div style:height="{topH}px"></div>
  <div class="m-grid-rows">
    {#each slice as r (r.id)}
      {@const w = work.get(r.id)}
      <!-- processing marks (work.svelte.ts): waiting, worked on, then done or failed for a moment; a Tools run's
           skipped and failed cards keep theirs until the panel closes (projects/phone-processing-flow) -->
      <div class="m-cell" class:m-w-wait={w?.st === 'wait'} class:m-w-run={w?.st === 'run'} class:m-w-done={w?.st === 'done'} class:m-w-err={w?.st === 'err'} class:m-w-skip={w?.st === 'skip'} style:height="{rowH - gap}px">
        {#if w}<span class="m-w-tag" aria-hidden="true">{workLabel(w)}</span>{#if w.st === 'run'}<span class="m-w-scan" aria-hidden="true"></span>{/if}{/if}
        <a class="m-cell-a" href={`#/item/${r.id}`} aria-label={cellLabel(r, w)}>
        {#if list}
          <div class="m-gallery-row">
            {#if r.thumb}<img src={source.thumbUrl(r)} alt="" loading="lazy" decoding="async" />{:else}<span class="m-gallery-cover" aria-hidden="true">{srcMark(r.url)}</span>{/if}
            <span class="m-gallery-copy"><b>{r.title || r.url}</b><small>{[r.creator || r.src, r.cat].filter(Boolean).join(' · ')}</small></span>
          </div>
        {:else if isBare(r)}
          <div class="m-ghost"><span class="m-src">{srcMark(r.url)}</span><span class="m-u">{r.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)}</span><span class="m-badge">{ghostText(r)}</span></div>
        {:else if !r.thumb}
          <div class="m-tint" style:background="linear-gradient(160deg,{tintOf(r)},color-mix(in srgb,{tintOf(r)} 55%,#000))"><b>{r.title || 'No.' + r.id}</b><small>{tintText(r)}</small></div>
        {:else}
          {#key r.fav + ':' + r.tv + ':' + phone.cardStyle}<div use:theme={r}>{@html cardMarkup(r)}</div>{/key}
        {/if}
        {#if !list && capped}<div class="card-cap" style:height="{CAP_H}px"><b>{r.title || r.url || 'No.' + r.id}</b><small>{[r.creator || t('item.creatorUnknown'), r.cat].filter(Boolean).join(' · ')}</small></div>{/if}
        </a>
      </div>
    {/each}
  </div>
  <div style:height="{botH}px"></div>
</div>
