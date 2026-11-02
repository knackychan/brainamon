<script lang="ts">
  // Toasts (at most 4) drop in at the top right of the open window, under its title bar, so they show
  // where the eyes are; with no window open, at the top middle of the screen.
  import { dropToast, toasts } from '../lib/ui.svelte'
  import { wins } from '../lib/windows.svelte'

  let at = $state<{ top: number; right: number } | null>(null)

  // follow the top full window while toasts show (it can be dragged or resized under them)
  $effect(() => {
    if (!toasts.length) { at = null; return }
    let raf = 0
    const place = () => {
      const w = wins.findLast(x => !x.popup)
      const r = w && document.querySelector(`.cw[data-n="${w.n}"]`)?.getBoundingClientRect()
      const next = r && r.width > 320 ? { top: Math.max(8, Math.round(r.top) + 46), right: Math.max(8, Math.round(innerWidth - r.right) + 12) } : null
      if (next?.top !== at?.top || next?.right !== at?.right) at = next
      raf = requestAnimationFrame(place)
    }
    place()
    return () => cancelAnimationFrame(raf)
  })
</script>

<div class="toasts" class:in-win={!!at} id="toasts" role="status" aria-live="polite" style:top={at ? `${at.top}px` : undefined} style:right={at ? `${at.right}px` : undefined}>
  {#each toasts as t (t.id)}
    <div class={'tst' + (t.level ? ' ' + t.level : '')}>
      <i aria-hidden="true"></i><span>{t.text}</span>
      {#if t.act}
        {@const act = t.act}
        <button type="button" onclick={() => { dropToast(t.id); act.run() }}>{act.label}</button>
      {:else}<span></span>{/if}
    </div>
  {/each}
</div>
