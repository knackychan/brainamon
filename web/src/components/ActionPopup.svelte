<script lang="ts">
  // Short actions stay beside their source; full editors keep the regular window frame.
  import { onMount } from 'svelte'
  import { closeWin, type Win } from '../lib/windows.svelte'

  let { w, z, under }: { w: Win; z: number; under: boolean } = $props()
  let el: HTMLElement
  const Body = $derived(w.body)
  const close = () => closeWin(w)

  onMount(() => {
    function place() {
      const r = w.anchor
      if (!r) return
      const width = el.offsetWidth, height = el.offsetHeight
      let left = r.right - width, top = r.top - height - 8
      if (top < 8) {
        top = r.bottom - height
        if (r.left - width - 8 >= 8) left = r.left - width - 8
        else if (r.right + width + 8 <= innerWidth - 8) left = r.right + 8
        else top = r.bottom + 8
      }
      el.style.left = Math.max(8, Math.min(innerWidth - width - 8, left)) + 'px'
      el.style.top = Math.max(8, Math.min(innerHeight - height - 8, top)) + 'px'
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(el)
    addEventListener('resize', place)
    const frame = requestAnimationFrame(() => {
      el.querySelector<HTMLElement>('[data-autofocus], input, button')?.focus({ preventScroll: true })
    })
    return () => { observer.disconnect(); removeEventListener('resize', place); cancelAnimationFrame(frame) }
  })
</script>

<section bind:this={el} class="cw action-popup" class:under class:anchored={!!w.anchor} data-n={w.n}
  role={w.alert ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby={'cw-t' + w.n}
  style:--w={(w.w ?? 340) + 'px'} style:z-index={z}>
  <div class="action-popup-head"><h2 id={'cw-t' + w.n}>{w.title}</h2></div>
  <Body {...w.props ?? {}} {close} />
</section>
