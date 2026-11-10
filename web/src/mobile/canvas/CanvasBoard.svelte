<script lang="ts">
  import { t } from '../../lib/i18n/index.ts'
  import { onMount, untrack, type Snippet } from 'svelte'
  import type { CanvasDoc, CEl } from '../../lib/canvas.svelte'
  import { phone, source } from '../state.svelte'
  import { fit as composeFit, W, H } from './compose'
  import type { CanvasDocument } from '../ai/canvas'
  import ShellIcon from '../ShellIcon.svelte'

  let { doc, compose = false, staged = new Map(), selected = null, onselect, onremove, covered = 0, full = false,
    busy = false, children }: { doc: CanvasDoc | null; compose?: boolean;
    staged?: Map<string, { key: string; url?: string; unavailable?: boolean }>; selected?: string | null;
    onselect?: (key: string | null) => void; onremove?: (key: string) => void; covered?: number; full?: boolean; busy?: boolean; children?: Snippet } = $props()
  let host: HTMLDivElement | undefined = $state(), width = $state(0), height = $state(0)
  let view = $state({ x: 20, y: 20, s: 1 }), automatic = $state(true)
  const ptrs = new Map<number, { x: number; y: number }>()
  let start: { x: number; y: number; s: number; d: number; cx: number; cy: number } | null = null
  let moved = false, cancelled = false
  const timers = new Set<ReturnType<typeof setTimeout>>()
  const fitted = $derived(doc ? composeFit(doc as CanvasDocument, width, height - covered) : null)
  const minScale = $derived(compose ? Math.min(.15, fitted?.s ?? .15) : .15)
  const chosen = $derived(doc?.items.find(e => staged.get(e.id)?.key === selected))
  function fit() {
    if (!doc || !host) return
    if (compose) { if (full) return; if (fitted) view = fitted; return }
    const els = doc.items
    if (!els.length) { view = { x: 20, y: 20, s: 1 }; return }
    const x0 = Math.min(...els.map(e => e.x)), y0 = Math.min(...els.map(e => e.y))
    const x1 = Math.max(...els.map(e => e.x + W(e))), y1 = Math.max(...els.map(e => e.y + H(e)))
    const s = Math.min(2, Math.max(.2, Math.min((host.clientWidth - 24) / (x1 - x0), (host.clientHeight - 80) / (y1 - y0))))
    view = { x: 12 - x0 * s + ((host.clientWidth - 24) - (x1 - x0) * s) / 2, y: 56 - y0 * s, s }
  }
  $effect(() => { void doc; void width; void height; void covered; void full; if (!compose || automatic) untrack(fit) })
  onMount(() => {
    const observer = new ResizeObserver(() => { width = host?.clientWidth || 0; height = host?.clientHeight || 0 })
    if (host) observer.observe(host)
    return () => { observer.disconnect(); for (const t of timers) clearTimeout(t) }
  })
  const dist = () => { const [a, b] = [...ptrs.values()]; return b ? Math.hypot(a.x - b.x, a.y - b.y) : 0 }
  const mid = () => { const [a, b] = [...ptrs.values()]; return b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : a }
  const point = (e: PointerEvent) => { const r = host!.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top } }
  function down(e: PointerEvent) {
    if (busy || (e.target as HTMLElement).closest('.m-zb, .m-cv-ui, .m-cp-remove, .m-cp-fit, .m-cp-view-add')) return
    if (!ptrs.size) { moved = false; cancelled = false }
    else moved = true
    ptrs.set(e.pointerId, point(e)); host?.setPointerCapture(e.pointerId)
    const m = mid(); start = { x: view.x, y: view.y, s: view.s, d: dist(), cx: m.x, cy: m.y }
  }
  function move(e: PointerEvent) {
    if (!ptrs.has(e.pointerId) || !start) return
    ptrs.set(e.pointerId, point(e)); const m = mid()
    if (Math.hypot(m.x - start.cx, m.y - start.cy) > 4 || ptrs.size > 1) { moved = true; automatic = false; onselect?.(null) }
    if (!moved) return
    let s = start.s
    if (ptrs.size >= 2 && start.d) s = Math.min(3, Math.max(minScale, start.s * dist() / start.d))
    const k = s / start.s
    view = { s, x: m.x - (start.cx - start.x) * k, y: m.y - (start.cy - start.y) * k }
  }
  function up(e: PointerEvent) {
    if (!ptrs.has(e.pointerId)) return
    if (e.type === 'pointercancel' || e.type === 'lostpointercapture') cancelled = true
    if (compose && !moved && !cancelled && host) {
      const at = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>('[data-stage]')
      onselect?.(at?.dataset.stage || null)
    }
    // Pointer capture retargets click to the host, so viewer taps resolve at pointerup too.
    if (!compose && !moved && !cancelled) {
      const at = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>('[data-item]')
      if (at?.dataset.item) location.hash = `#/item/${at.dataset.item}`
    }
    ptrs.delete(e.pointerId)
    if (ptrs.size) { const m = mid(); start = { x: view.x, y: view.y, s: view.s, d: dist(), cx: m.x, cy: m.y } } else start = null
  }
  function zoom(f: number) {
    if (!host || busy) return
    automatic = false; onselect?.(null)
    const cx = host.clientWidth / 2, cy = host.clientHeight / 2, s = Math.min(3, Math.max(minScale, view.s * f)), k = s / view.s
    view = { s, x: cx - (cx - view.x) * k, y: cy - (cy - view.y) * k }
  }
  const rowOf = (el: CEl) => el.item_id ? phone.byId.get(el.item_id) : undefined
  function failed(e: Event) {
    const img = e.currentTarget as HTMLImageElement, n = Number(img.dataset.tries || 0)
    if (n >= 2) { img.parentElement!.dataset.missing = '1'; return }
    img.dataset.tries = String(n + 1)
    const timer = setTimeout(() => { timers.delete(timer); if (img.isConnected) img.src = img.src.split('#')[0] + '#r' + (n + 1) }, 3000 * (n + 1))
    timers.add(timer)
  }
</script>

<div class="m-cv" class:m-cp-board={compose} bind:this={host} role={compose ? 'group' : 'img'} aria-label={compose ? t('canvas.preview') : t('canvas.board', { name: doc?.name ?? '' })}
  onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onlostpointercapture={up}>
  {@render children?.()}
  {#if compose && !doc?.items.length}<div class="m-cp-empty"><ShellIcon name="cv" />{t('canvas.pickBelow')}</div>{/if}
  <div class="m-cv-board" style:transform="translate({view.x}px,{view.y}px) scale({view.s})" style:--m-cp-inverse={1 / view.s}>
    {#each doc?.items ?? [] as el (staged.get(el.id)?.key || el.id)}
      {@const stage = staged.get(el.id)}
      {@const r = rowOf(el)}
      {#if compose && stage}
        <button type="button" class="m-cp-staged" class:m-cp-selected={selected === stage.key} class:m-cp-missing={stage.unavailable}
          class:m-cv-txt={el.type === 'note'} class:m-cv-el={el.type !== 'note'} data-stage={stage.key}
          style:left="{el.x}px" style:top="{el.y}px" style:width="{W(el)}px" style:height="{H(el)}px" style:background={el.type === 'note' ? el.color : undefined}
          disabled={busy} aria-label={el.type === 'note' ? el.text : r?.title || el.label || t('canvas.pickedImage')} aria-pressed={selected === stage.key}
          onclick={e => { if (e.detail === 0 && !busy) onselect?.(stage.key) }}>
          {#if el.type === 'note'}{el.text ?? ''}{:else if stage.unavailable}<span>{t('canvas.notHere')}</span>{:else if stage.url}<img src={stage.url} alt="" draggable="false" />{/if}
        </button>
      {:else if el.type === 'note'}
        <div class="m-cv-txt" style:left="{el.x}px" style:top="{el.y}px" style:width="{W(el)}px" style:background={el.color || undefined}>{#if el.label}<b>{el.label}</b>{/if}{el.text ?? ''}</div>
      {:else}
        <button type="button" class="m-cv-el" data-missing-label={t('canvas.imageUnavailable')} class:file={el.source === 'file'} data-item={!compose ? el.item_id : undefined} tabindex={compose ? -1 : 0} inert={compose}
          style:left="{el.x}px" style:top="{el.y}px" style:width="{W(el)}px" style:height="{H(el)}px" aria-label={r?.title || el.label || t('canvas.image')}
          onclick={e => { if (!compose && e.detail === 0 && el.item_id) location.hash = `#/item/${el.item_id}` }}>
          {#if el.source === 'file' && el.file_path}<img src={source.canvasImageUrl(el.file_path.split(/[\\/]/).pop() || '')} alt="" loading="lazy" draggable="false" onerror={failed} />
          {:else if r}<img src={source.thumbUrl(r, 320)} alt="" loading="lazy" draggable="false" onerror={failed} />
          {:else}<span>{el.label ? t('canvas.namedUnavailable', { label: el.label }) : t('canvas.imageUnavailable')}</span>{/if}
        </button>
      {/if}
    {/each}
  </div>
  {#if compose}
    {#if chosen && selected}<button type="button" class="m-cp-remove" disabled={busy} style:left="{Math.max(56, Math.min(width - 56, view.x + (chosen.x + W(chosen) / 2) * view.s))}px" style:top="{Math.max(34, view.y + chosen.y * view.s - 8)}px" onpointerdown={e => e.stopPropagation()} onclick={() => onremove?.(selected!)}>{t('canvas.remove')}</button>{/if}
    {#if !full}<button type="button" class="m-cp-fit" style:bottom="{covered + 10}px" aria-label={t('canvas.fitBoard')} disabled={busy} onclick={() => { automatic = true; fit() }}>{t('canvas.fitKey')}</button>{/if}
  {:else}
    <div class="m-zb"><button type="button" onclick={() => zoom(1.25)} aria-label={t('canvas.zoomIn')}>+</button><button type="button" onclick={() => zoom(.8)} aria-label={t('canvas.zoomOut')}>−</button><button type="button" onclick={fit} aria-label={t('canvas.fit')} style="font-size:10px">{t('canvas.fitKey')}</button></div>
  {/if}
</div>

<style>
  :global(.m-cv-el[data-missing='1'] img){display:none}
  :global(.m-cv-el[data-missing='1']::after){content:attr(data-missing-label);display:block;padding:8px;text-align:center}
</style>
