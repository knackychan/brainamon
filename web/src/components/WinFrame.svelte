<script lang="ts">
  // One CM-OS window (V6 c-shell.js openWin): cream frame, title bar with grip (drag to move,
  // not below 640 px), Close key, the body component. Focus goes to the body's first control.
  import { closeWin, type Win } from '../lib/windows.svelte'
  import Button from './ui/Button.svelte'

  let { w, z, under }: { w: Win; z: number; under: boolean } = $props()
  let el: HTMLElement | undefined = $state()
  let drag: { x: number; y: number; W: number } | null = null

  const FOCUSABLE = 'button:not([disabled]):not([hidden]),[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

  $effect(() => {
    if (!el) return
    const box = el
    requestAnimationFrame(() => {
      const f = box.querySelector<HTMLElement>('[data-autofocus]') ?? box.querySelector<HTMLElement>('.cw-body ' + FOCUSABLE) ?? box.querySelector<HTMLElement>('[data-wclose]')
      f?.focus({ preventScroll: true })
    })
  })

  function down(e: PointerEvent) {
    if (!el || (e.target as HTMLElement).closest('button') || innerWidth <= 640) return
    const r = el.getBoundingClientRect()
    drag = { x: e.clientX - r.left, y: e.clientY - r.top, W: el.offsetWidth }
    el.classList.add('moved')
    el.style.left = r.left + 'px'
    el.style.top = r.top + 'px'
    try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId) } catch { /* not capturable */ }
  }
  function move(e: PointerEvent) {
    if (!drag || !el) return
    el.style.left = Math.max(-drag.W + 90, Math.min(innerWidth - 90, e.clientX - drag.x)) + 'px'
    el.style.top = Math.max(0, Math.min(innerHeight - 40, e.clientY - drag.y)) + 'px'
  }
  const end = () => { drag = null }
  const close = () => closeWin(w)
  const Body = $derived(w.body)
</script>

<section bind:this={el} class={'cw' + (w.cls ? ' ' + w.cls : '')} class:under data-n={w.n}
  role={w.alert ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby={'cw-t' + w.n}
  style:--w={(w.w ?? 640) + 'px'} style:z-index={z}>
  <div class="wbar" role="presentation" onpointerdown={down} onpointermove={move} onpointerup={end} onpointercancel={end}>
    <span class="wdots" aria-hidden="true"><i></i><i></i></span>
    <p class="wtitle" id={'cw-t' + w.n}>{w.title}</p>
    {#if w.code}<span class="wcode">{w.code}</span>{/if}
    <Button size="sm" class="x" data-wclose onclick={close}>{w.closeLabel ?? 'Close'}</Button>
  </div>
  <Body {...w.props ?? {}} {close} />
</section>
