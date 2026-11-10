<script lang="ts">
  import type { Snippet } from 'svelte'
  import { t } from '../../lib/i18n/index.ts'
  import MButton from './MButton.svelte'

  // icon replaces the (i) mark and class styles the button, for a key that opens help (Library: on this phone only)
  let { title, label, icon, class: cls = '', children }: { title: string; label?: string; icon?: Snippet; class?: string; children: Snippet } = $props()
  const id = $props.id()
  let trigger: HTMLButtonElement
  let dialog: HTMLDialogElement
  let open = $state(false)

  // Help can sit inside headings or scrolling panels; the overlay belongs to the viewport.
  function toBody(node: HTMLDialogElement) { document.body.appendChild(node); return { destroy() { node.remove() } } }
  function outside(e: PointerEvent) {
    if (e.target !== dialog) return
    const r = dialog.getBoundingClientRect()
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close()
  }
</script>

<button type="button" class={['m-info', cls]} bind:this={trigger} aria-label={t('common.info.label', { title })} aria-haspopup="dialog" aria-controls={id} aria-expanded={open} onclick={() => { dialog.showModal(); open = true }}>
  {#if icon}{@render icon()}{:else}<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7v1" /></svg>{/if}
  {#if label}<span>{label}</span>{/if}
</button>
<dialog class="m-info-dialog" {id} bind:this={dialog} use:toBody aria-labelledby={`${id}-title`} onclose={() => { open = false; trigger?.focus({ preventScroll: true }) }} onpointerdown={outside}>
  <div class="m-info-head"><h2 id={`${id}-title`}>{title}</h2><MButton onclick={() => dialog.close()}>{t('common.close')}</MButton></div>
  <div class="m-info-body">{@render children()}</div>
</dialog>

<style>
  .m-info { display: inline-flex; flex: none; align-items: center; justify-content: center; gap: 6px; align-self: flex-start; min-width: 44px; min-height: 44px; padding: 6px; border: 0; border-radius: 6px; background: transparent; color: var(--m-teal); font: 500 12px/1.3 var(--display); text-align: left; vertical-align: middle }
  .m-info svg { flex: none; width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round }
  .m-info:active { background: var(--wg-2) }
  .m-info-dialog { box-sizing: border-box; position: fixed; inset: 0; width: min(28rem, calc(100vw - 32px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px))); max-width: none; max-height: calc(100dvh - 32px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px)); margin: auto; padding: 0; border: 1px solid var(--wg-edge); border-radius: 12px; background: var(--wg); color: var(--wg-ink); box-shadow: 0 16px 40px -18px rgba(0, 0, 0, .5); overflow: hidden; font: 400 15px/1.5 var(--display); text-align: left; letter-spacing: normal; text-transform: none; font-stretch: normal }
  .m-info-dialog[open] { display: flex; flex-direction: column }
  .m-info-dialog::backdrop { background: rgba(0, 0, 0, .5) }
  .m-info-head { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--wg-line) }
  .m-info-head h2 { min-width: 0; margin: 0; font: 700 18px/1.3 var(--display); overflow-wrap: anywhere }
  .m-info-head :global(.m-btn) { flex: none; min-height: 44px }
  .m-info-body { min-height: 0; display: flex; flex-direction: column; gap: 12px; padding: 16px; overflow: auto; overscroll-behavior: contain; overflow-wrap: anywhere }
  .m-info-body :global(p) { margin: 0 }
  .m-info-body :global(.m-hint) { color: inherit; font: inherit }
</style>
