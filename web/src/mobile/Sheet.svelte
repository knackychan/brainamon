<script lang="ts">
  // A full-screen sheet over the last section page (projects/phone-dock-shell, spec section 4): Notes, Wiskit or
  // Add. The head holds the grip (drag it down past 80 px to close), Back while a page inside the sheet is open,
  // the title and the close key; the owner line follows (OwnerLine.svelte), then the screen in .m-sheet-body,
  // which scrolls. The class m-vt-<kind> gives the sheet its dock key's view-transition-name (Dock.svelte), so
  // opening and closing grow it out of the key and back (shell.svelte.ts).
  // keys (projects/phone-wiskit-chat, Wiskit only): no head and no drag; floating keys overlay the top of the
  // layer (.m-sheet-keys: Close or Back, the tag, the open chat's `name`, a `corner` key the caller renders);
  // the owner line keeps its place under their band; the layer pads its bottom by Android's inset (mobile.css,
  // class m-bare).
  import type { Snippet } from 'svelte'
  import type { SheetKind } from './shell'
  import { t } from '../lib/i18n/index.ts'
  import OwnerLine from './OwnerLine.svelte'
  import MKey from './ui/MKey.svelte'
  import ShellIcon from './ShellIcon.svelte'

  // bare: no head (an open My Note draws its own keys, NoteEditor.svelte)
  let { kind, title, sub = false, capturing = false, bare = false, keys = false, name = '', onback, onclose, corner, children }: {
    kind: SheetKind; title: string; sub?: boolean; capturing?: boolean; bare?: boolean; keys?: boolean; name?: string
    onback: () => void; onclose: () => void; corner?: Snippet; children: Snippet
  } = $props()
  const CLOSE_AT = 80
  let drag = $state(0), dragging = $state(false), y0 = 0, id = -1

  function down(e: PointerEvent) {
    if (e.target instanceof Element && e.target.closest('button, a')) return
    dragging = true; id = e.pointerId; y0 = e.clientY
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  function move(e: PointerEvent) { if (dragging && e.pointerId === id) drag = Math.max(0, e.clientY - y0) }
  function release(e: PointerEvent, cancel = false) {
    if (!dragging || e.pointerId !== id) return
    dragging = false
    if (!cancel && drag > CLOSE_AT) onclose()
    else drag = 0
  }
</script>

<section class={['m-sheet-layer', `m-vt-${kind}`]} class:m-capturing={capturing} class:m-bare={keys} class:m-dragging={dragging}
  aria-label={title} style:transform={drag ? `translateY(${drag}px)` : undefined}>
  {#if keys}
    <div class="m-sheet-keys">
      {#if sub}<MKey aria-label={t('common.back')} title={t('common.back')} onclick={onback}><ShellIcon name="back" /></MKey>
      {:else}<MKey aria-label={t('shell.sheet.close', { title })} title={t('shell.sheet.close', { title })} onclick={onclose}><ShellIcon name="back" /></MKey>{/if}
      <span class="m-ws">{title}</span>
      {#if name && !sub}<span class="m-sheet-name">{name}</span>{/if}
      <span class="m-sp"></span>
      {@render corner?.()}
    </div>
  {:else if !bare}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <header class="m-sheet-head" onpointerdown={down} onpointermove={move} onpointerup={e => release(e)} onpointercancel={e => release(e, true)}>
      <span class="m-sheet-grip" aria-hidden="true"></span>
      {#if sub}<button type="button" class="m-back" onclick={onback} aria-label={t('common.back')}>‹</button>{/if}
      <span class="m-ws">{title}</span>
      <span class="m-sp"></span>
      <button type="button" class="m-back" onclick={onclose} aria-label={t('shell.sheet.close', { title })}>✕</button>
    </header>
  {/if}
  <OwnerLine />
  <div class="m-sheet-body">{@render children()}</div>
</section>
