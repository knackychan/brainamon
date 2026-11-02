<script lang="ts">
  // 06 Canvas, read-only: the list of canvases, then one canvas to pan (one finger) and zoom (pinch
  // or the buttons). Tapping a library card on it opens the item. Editing stays on the PC. On the
  // Google Drive mirror a canvas can be saved for offline, with its images.
  import { onMount, untrack } from 'svelte'
  import type { CanvasDoc, CanvasRow, CEl } from '../../lib/canvas.svelte'
  import { kv } from '../store'
  import { phone, source } from '../state.svelte'
  import { offline, removeCanvas, saveCanvas, savedCanvas } from '../offline.svelte'
  import MButton from '../ui/MButton.svelte'


  let { id }: { id: string | null } = $props()
  const onMirror = source.kind === 'mirror'
  let saving = $state(false)
  const isSaved = $derived(!!id && offline.canvases.some(c => c.id === id))
  async function toggleSave() {
    if (!id) return
    saving = true
    try { if (isSaved) await removeCanvas(id); else await saveCanvas(id) } catch (e) { err = (e as Error).message } finally { saving = false }
  }
  let list = $state<CanvasRow[]>([])
  let doc = $state<CanvasDoc | null>(null)
  let err = $state('')
  let view = $state({ x: 0, y: 0, s: 1 })
  let host: HTMLDivElement | undefined = $state()
  const ptrs = new Map<number, { x: number; y: number }>()
  let start: { x: number; y: number; s: number; d: number; cx: number; cy: number } | null = null
  let moved = false

  onMount(() => { void offline.load() })
  let generation = 0
  // untrack: the API client counts requests in a $state (src/lib/net.svelte.ts); read inside the
  // effect it would re-run it
  $effect(() => {
    const cid = id, revision = phone.canvasRevision, n = ++generation
    untrack(() => {
      void revision
      if (!cid) {
        doc = null
        void kv.get<CanvasRow[]>('canvases').then(cached => { if (n === generation) list = cached ?? [] })
        source.canvases().then(rows => { if (n === generation) { list = rows; void kv.set('canvases', rows) } })
          .catch(async e => { if (n === generation && !list.length) { list = offline.canvases.map(c => ({ id: c.id, name: c.name, count: c.doc.items.length, updated: c.at })); err = (e as Error).message } })
        return
      }
      err = ''
      source.canvas(cid).then(d => { if (n === generation) { doc = d; fit() } }).catch(async e => {
        const d = await savedCanvas(cid)
        if (n === generation) { if (d) { doc = d; fit() } else err = (e as Error).message }
      })
    })
  })

  const W = (e: CEl) => e.w ?? (e.type === 'note' ? 200 : 150)
  const H = (e: CEl) => e.h ?? (e.type === 'note' ? 120 : W(e) * 1.4)
  function fit() {
    if (!doc || !host) return
    const els = doc.items
    if (!els.length) { view = { x: 20, y: 20, s: 1 }; return }
    const x0 = Math.min(...els.map(e => e.x)), y0 = Math.min(...els.map(e => e.y))
    const x1 = Math.max(...els.map(e => e.x + W(e))), y1 = Math.max(...els.map(e => e.y + H(e)))
    const s = Math.min(2, Math.max(0.2, Math.min((host.clientWidth - 24) / (x1 - x0), (host.clientHeight - 80) / (y1 - y0))))
    view = { x: 12 - x0 * s + ((host.clientWidth - 24) - (x1 - x0) * s) / 2, y: 56 - y0 * s, s }
  }
  const dist = () => { const [a, b] = [...ptrs.values()]; return b ? Math.hypot(a.x - b.x, a.y - b.y) : 0 }
  const mid = () => { const [a, b] = [...ptrs.values()]; return b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : a }
  function down(e: PointerEvent) {
    if ((e.target as HTMLElement).closest('.m-zb, .m-cv-ui button')) return
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY })
    host?.setPointerCapture(e.pointerId)
    const m = mid()
    start = { x: view.x, y: view.y, s: view.s, d: dist(), cx: m.x, cy: m.y }
    moved = false
  }
  function move(e: PointerEvent) {
    if (!ptrs.has(e.pointerId) || !start) return
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY })
    const m = mid()
    if (Math.hypot(m.x - start.cx, m.y - start.cy) > 4) moved = true
    let s = start.s
    if (ptrs.size >= 2 && start.d) s = Math.min(3, Math.max(0.15, start.s * dist() / start.d))
    // keep the point under the fingers fixed while zooming
    const k = s / start.s
    view = { s, x: m.x - (start.cx - start.x) * k, y: m.y - (start.cy - start.y) * k }
  }
  function up(e: PointerEvent) {
    ptrs.delete(e.pointerId)
    if (ptrs.size) { const m = mid(); start = { x: view.x, y: view.y, s: view.s, d: dist(), cx: m.x, cy: m.y } } else start = null
  }
  function zoom(f: number) {
    if (!host) return
    const cx = host.clientWidth / 2, cy = host.clientHeight / 2, s = Math.min(3, Math.max(0.15, view.s * f)), k = s / view.s
    view = { s, x: cx - (cx - view.x) * k, y: cy - (cy - view.y) * k }
  }
  function tap(el: CEl) { if (!moved && el.item_id) location.hash = `#/item/${el.item_id}` }
  const rowOf = (el: CEl) => (el.item_id ? phone.byId.get(el.item_id) : undefined)
  // a picture that failed (Google busy, the phone offline for a moment) is tried twice more before it shows
  // as unavailable; the fragment makes a new load without changing the URL the service worker sees
  function failed(e: Event) {
    const img = e.currentTarget as HTMLImageElement, n = Number(img.dataset.tries || 0)
    if (n >= 2) { (img.parentElement as HTMLElement).dataset.missing = '1'; return }
    img.dataset.tries = String(n + 1)
    setTimeout(() => { img.src = img.src.split('#')[0] + '#r' + (n + 1) }, 3000 * (n + 1))
  }
  const when = (ms: number) => (ms ? new Date(ms > 1e12 ? ms : ms * 1000).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '')
</script>

{#if !id}
  <div class="m-pad">
    <div class="m-row"><span class="m-lbl">Canvases</span><span class="m-sp"></span><span class="m-lbl">{list.length} · view</span></div>
    {#if err}<div class="m-err" style="margin:0">{err}</div>{/if}
    <div class="m-notes m-cv-list">
      {#each list as c (c.id)}
        <button type="button" onclick={() => (location.hash = `#/canvas/${encodeURIComponent(c.id)}`)}><span class="m-cvi">▦</span><div><b>{c.name || c.id}</b><small>{c.count} elements · {when(c.updated)} · {source.canvasStatus?.(c.id) || (onMirror ? 'Drive' : 'PC')}</small></div>{#if offline.canvases.some(x => x.id === c.id)}<span class="m-badge ok">Saved</span>{:else}<span class="m-badge mute">{onMirror ? 'Phone' : 'PC'}</span>{/if}</button>
      {:else}
        <div class="m-empty">No canvases yet. Ask Wiskit to make one.</div>
      {/each}
    </div>
  </div>
{:else}
  <div class="m-cv" bind:this={host} role="img" aria-label={`Canvas ${doc?.name ?? ''}, drag to move, pinch to zoom`} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
    <div class="m-cv-ui"><span class="m-ro">{doc?.name ?? '…'} · view only</span><span class="m-sp"></span>{#if err}<span class="m-badge bad">{err}</span>{/if}{#if onMirror && doc}<MButton size="sm" class={{ dk: isSaved }} disabled={saving} onclick={toggleSave}>{saving ? 'Saving…' : isSaved ? '✓ Saved' : 'Save for offline'}</MButton>{/if}</div>
    <div class="m-cv-board" style:transform="translate({view.x}px,{view.y}px) scale({view.s})">
      {#if doc}
        {#each doc.items as el (el.id)}
          {#if el.type === 'note'}
            <div class="m-cv-txt" style:left="{el.x}px" style:top="{el.y}px" style:width="{W(el)}px" style:background={el.color || undefined}>{#if el.label}<b>{el.label}</b>{/if}{el.text ?? ''}</div>
          {:else}
            {@const r = rowOf(el)}
            <button type="button" class="m-cv-el" class:file={el.source === 'file'} style:left="{el.x}px" style:top="{el.y}px" style:width="{W(el)}px" style:height="{H(el)}px" onclick={() => tap(el)} aria-label={r?.title || el.label || 'image'}>
              {#if el.source === 'file' && el.file_path}<img src={source.canvasImageUrl(el.file_path.split(/[\\/]/).pop() || '')} alt="" loading="lazy" draggable="false" onerror={failed} />
              {:else if r}<img src={source.thumbUrl(r, 320)} alt="" loading="lazy" draggable="false" onerror={failed} />
              {:else}<span>{el.label ? `${el.label}: image` : 'Image'} unavailable</span>{/if}
            </button>
          {/if}
        {/each}
      {/if}
    </div>
    <div class="m-zb"><button type="button" onclick={() => zoom(1.25)} aria-label="Zoom in">+</button><button type="button" onclick={() => zoom(0.8)} aria-label="Zoom out">−</button><button type="button" onclick={fit} aria-label="Fit" style="font-size:10px">FIT</button></div>
  </div>
{/if}

<style>
  :global(.m-cv-el[data-missing='1'] img){display:none}
  :global(.m-cv-el[data-missing='1']::after){content:'Image unavailable';display:block;padding:8px;text-align:center}
</style>
