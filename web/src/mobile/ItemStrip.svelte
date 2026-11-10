<script lang="ts">
  import { onDestroy, untrack } from 'svelte'
  import { cardMarkup, ghostText, isBare, themeCard, tintOf, tintText } from './cards'
  import { t } from '../lib/i18n/index.ts'
  import { srcMark } from './outbox.svelte'
  import { phone, source } from './state.svelte'
  import type { Row } from './source/types'
  import { go } from './shell.svelte'
  import { stripIndex, stripList, stripPosition, stripTap, stripThumb, stripWindow } from './strip'

  let ids = $state.raw<number[]>([]), position = $state(0), dragging = $state(false), settling = $state(false)
  let lastId: number | undefined, timer = 0, pending: (() => void) | null = null
  const index = $derived(stripIndex(position, ids.length))
  const preview = $derived(phone.byId.get(ids[index]))
  const range = $derived(stripWindow(position, ids.length))
  const pictures = $derived(ids.slice(range[0], range[1]).flatMap((id, i) => {
    const row = phone.byId.get(id)
    return row ? [{ row, i: i + range[0] }] : []
  }))
  $effect(() => {
    const id = phone.route.item, all = phone.rows
    untrack(() => {
      const next = stripList(id ?? 0, phone.visible.map(r => r.id), all.map(r => r.id), ids)
      if (id !== lastId || next.length !== ids.length || next.some((n, i) => n !== ids[i])) {
        clearTimeout(timer); pending = null; dragging = settling = false
        ids = next; lastId = id; position = Math.max(0, next.indexOf(id ?? 0))
      }
    })
  })
  onDestroy(() => { clearTimeout(timer); pending = null })
  const still = () => phone.motionOff || matchMedia('(prefers-reduced-motion: reduce)').matches
  function open(id: number) {
    if (id === phone.route.item || !phone.byId.has(id)) return
    go(`#/item/${id}`, true)
  }
  function theme(node: HTMLElement, r: Row) {
    const apply = (row: Row) => { const slot = node.querySelector<HTMLElement>('.slot'); if (slot) themeCard(slot, row) }
    apply(r)
    return { update: apply }
  }
  function gesture(node: HTMLElement) {
    let pointer: number | null = null, x = 0, y = 0, started = 0, start = 0, distance = 0, tapped = 0
    const cancel = () => {
      const captured = pointer
      clearTimeout(timer); pending = null
      pointer = null; dragging = settling = false
      if (captured !== null && node.hasPointerCapture(captured)) node.releasePointerCapture(captured)
      position = Math.max(0, ids.indexOf(phone.route.item ?? 0))
    }
    const down = (e: PointerEvent) => {
      if (!e.isPrimary) { cancel(); return }
      if (e.button !== 0) return
      e.preventDefault(); clearTimeout(timer)
      // a touch during the 150 ms snap completes it first, so the ring and the page agree
      const done = pending; pending = null; done?.()
      settling = false
      pointer = e.pointerId; x = e.clientX; y = e.clientY; start = position; started = performance.now(); distance = 0
      tapped = Number((e.target as Element).closest<HTMLElement>('[data-item]')?.dataset.item || 0)
      node.setPointerCapture(e.pointerId)
    }
    const move = (e: PointerEvent) => {
      if (pointer !== e.pointerId) return
      distance = Math.max(distance, Math.hypot(e.clientX - x, e.clientY - y))
      if (distance >= 6) dragging = true
      if (dragging) position = stripPosition(start, e.clientX - x, ids.length)
    }
    const up = (e: PointerEvent) => {
      if (pointer !== e.pointerId) return
      move(e)
      pointer = null
      if (node.hasPointerCapture(e.pointerId)) node.releasePointerCapture(e.pointerId)
      if (stripTap(performance.now() - started, distance)) { dragging = false; if (tapped) open(tapped); return }
      if (!dragging) return
      const target = ids[stripIndex(position, ids.length)], from = phone.route.item
      dragging = false; settling = !still(); position = stripIndex(position, ids.length)
      const finish = () => { pending = null; settling = false; if (phone.route.item === from) open(target) }
      if (still()) finish()
      else { pending = finish; timer = window.setTimeout(finish, 150) }
    }
    const lost = (e: PointerEvent) => { if (pointer === e.pointerId) cancel() }
    const menu = (e: Event) => e.preventDefault()
    node.addEventListener('pointerdown', down)
    node.addEventListener('pointermove', move)
    node.addEventListener('pointerup', up)
    node.addEventListener('pointercancel', lost)
    node.addEventListener('lostpointercapture', lost)
    node.addEventListener('contextmenu', menu)
    return { destroy() {
      cancel(); clearTimeout(timer)
      node.removeEventListener('pointerdown', down)
      node.removeEventListener('pointermove', move)
      node.removeEventListener('pointerup', up)
      node.removeEventListener('pointercancel', lost)
      node.removeEventListener('lostpointercapture', lost)
      node.removeEventListener('contextmenu', menu)
    } }
  }
</script>

{#if ids.length >= 2 && phone.byId.has(phone.route.item ?? 0)}
  <nav class="m-item-strip" class:m-item-sliding={dragging} class:m-item-settling={settling} aria-label={t('item.strip.label')} use:gesture>
    {#if dragging && preview}
      <div class="m-item-preview" aria-hidden="true" inert>
        {#key preview.id + ':' + preview.fav + ':' + preview.tv + ':' + phone.cardStyle}
          <div class="m-item-preview-card" use:theme={preview}>
            {#if isBare(preview)}
              <div class="m-ghost"><span class="m-src">{srcMark(preview.url)}</span><span class="m-u">{preview.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)}</span><span class="m-badge">{ghostText(preview)}</span></div>
            {:else if !preview.thumb}
              <div class="m-tint" style:background="linear-gradient(160deg,{tintOf(preview)},color-mix(in srgb,{tintOf(preview)} 55%,#000))"><b>{preview.title || 'No.' + preview.id}</b><small>{tintText(preview)}</small></div>
            {:else}{@html cardMarkup(preview)}{/if}
          </div>
        {/key}
        <span class="m-ws">{t('item.strip.position', { n: index + 1, total: ids.length })}</span>
      </div>
    {/if}
    <div class="m-item-reel">
      {#each pictures as p (p.row.id)}
        {@const r = p.row}
        {@const size = stripThumb(p.i - position, dragging)}
        <button type="button" class="m-item-thumb" data-item={r.id} aria-label={r.title || r.url || 'No.' + r.id} aria-current={r.id === phone.route.item ? 'page' : undefined}
          style:width={`${size.w}px`} style:height={`${size.h}px`} style:transform={`translate(calc(-50% + ${size.x}px), -50%)`}
          style:background="linear-gradient(160deg,{tintOf(r)},color-mix(in srgb,{tintOf(r)} 55%,#000))"
          onclick={e => { e.preventDefault(); if (e.detail === 0) open(r.id) }}>
          {#if r.thumb}<img src={source.thumbUrl(r, 80)} alt="" draggable="false" />{/if}
        </button>
      {/each}
    </div>
    <span class="m-item-ring" aria-hidden="true"></span>
  </nav>
{/if}
