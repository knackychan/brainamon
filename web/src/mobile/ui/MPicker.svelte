<script lang="ts">
  import type { Snippet } from 'svelte'
  import { t } from '../../lib/i18n/index.ts'
  import MButton from './MButton.svelte'

  // footer: action rows under the list (the note page's New / Rename category); it gets a function that closes the sheet
  let { label, options, value = $bindable(''), onchange, children, footer, class: cls, disabled = false }: {
    label: string; options: [string, string][]; value?: string; onchange?: (value: string) => void
    children?: Snippet; footer?: Snippet<[() => void]>; class?: string; disabled?: boolean
  } = $props()
  const id = $props.id()
  let trigger: HTMLButtonElement
  let dialog: HTMLDialogElement
  let open = $state(false), query = $state('')
  const selected = $derived(options.find(([key]) => key === value)?.[1] ?? value)
  const matches = $derived(options.filter(([, name]) => name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())))
  // the caller's label reads lower-cased inside the sentences (as it always did)
  const word = $derived(label.toLowerCase())

  function toBody(node: HTMLDialogElement) { document.body.appendChild(node); return { destroy() { node.remove() } } }
  function show() {
    query = ''
    dialog.showModal()
    open = true
    dialog.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus()
  }
  function choose(next: string) { value = next; dialog.close(); onchange?.(next) }
  function outside(e: PointerEvent) {
    if (e.target !== dialog) return
    const r = dialog.getBoundingClientRect()
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close()
  }
</script>

<button type="button" class={[children ? 'm-picker-inline' : 'm-picker', cls]} bind:this={trigger} {disabled} aria-label={t('common.picker.choose', { label: word, selected })} aria-haspopup="dialog" aria-controls={id} aria-expanded={open} onclick={show}>
  {#if children}{@render children()}{:else}<span>{selected}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 8 4 4 4-4" /></svg>{/if}
</button>
<dialog class="m-cap-tools m-picker-sheet" {id} bind:this={dialog} use:toBody aria-labelledby={`${id}-title`} onpointerdown={outside} onkeydown={e => { if (e.key === 'Escape') { e.preventDefault(); dialog.close() } }} onclose={() => { open = false; if (!document.querySelector('dialog[open]')) trigger?.focus({ preventScroll: true }) }}>
  <div class="m-cap-tools-head"><h2 id={`${id}-title`}>{t('common.picker.title', { label: word })}</h2><MButton onclick={() => dialog.close()}>{t('common.close')}</MButton></div>
  <label class="m-fld m-picker-search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5" /><path d="m12.5 12.5 4 4" /></svg><input type="search" bind:value={query} aria-label={t('common.picker.searchLabel', { label: word })} placeholder={t('common.picker.placeholder')} /></label>
  <div class="m-picker-options" role="group" aria-label={t('common.picker.choices', { label })}>
    {#each matches as [key, name]}
      <button type="button" aria-pressed={key === value} onclick={() => choose(key)}><span>{name}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 10 3 3 7-7" /></svg></button>
    {:else}<p class="m-empty" role="status">{t('common.picker.none')}</p>{/each}
  </div>
  {#if footer}<div class="m-picker-foot">{@render footer(() => dialog.close())}</div>{/if}
</dialog>

<style>
  .m-picker { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; min-width: 0; min-height: 44px; padding: 8px 10px; border: 1px solid var(--np-edge); border-radius: 8px; background: var(--np-solid); color: var(--np-ink); font: 600 14px/1.3 var(--display); text-align: left }
  .m-picker>span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
  svg { flex: none; width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round }
  .m-picker-sheet { width: min(480px, calc(100vw - 32px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px))); max-height: min(560px, calc(100dvh - 32px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px))); bottom: max(16px, env(safe-area-inset-bottom, 0px)); background: var(--wg); color: var(--wg-ink); border-color: var(--wg-edge) }
  .m-picker-sheet :global(.m-cap-tools-head) { border-color: var(--wg-line) }
  .m-picker-search { flex: none; margin: 12px 16px 8px; min-height: 44px; box-sizing: border-box; color: var(--wg-dim); background: var(--wg-2); border-color: var(--wg-edge) }
  .m-picker-search input { font: 400 16px/1.3 var(--display); color: var(--wg-ink) }
  .m-picker-options { min-height: 0; overflow: auto; overscroll-behavior: contain; padding: 0 8px 8px }
  .m-picker-options button { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; min-height: 48px; padding: 12px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--wg-ink); font: 500 15px/1.4 var(--display); text-align: left }
  .m-picker-options button span { min-width: 0; overflow-wrap: anywhere }
  .m-picker-options button svg { visibility: hidden }
  .m-picker-options button[aria-pressed="true"] { background: var(--wg-2); font-weight: 700 }
  .m-picker-options button[aria-pressed="true"] svg { visibility: visible; color: var(--m-teal) }
  .m-picker-options button:active { background: var(--wg-2) }
  .m-picker-foot { flex: none; display: grid; gap: 2px; padding: 6px 8px 10px; border-top: 1px solid var(--wg-line) }
  .m-picker-foot :global(button) { display: flex; align-items: center; width: 100%; min-height: 48px; padding: 12px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--wg-ink); font: 600 15px/1.4 var(--display); text-align: left }
  .m-picker-foot :global(button:disabled) { color: var(--wg-dim) }
  .m-picker-foot :global(button:active) { background: var(--wg-2) }
  .m-picker-foot :global(.m-hint) { margin: 0 8px 4px }
</style>
