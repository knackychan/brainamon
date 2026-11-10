<script lang="ts">
  import { untrack } from 'svelte'
  import type { Snippet } from 'svelte'

  let { open = $bindable(false), title, children, actions }: {
    open?: boolean; title: string; children: Snippet; actions: Snippet
  } = $props()
  const id = $props.id()
  let dialog: HTMLDialogElement | undefined = $state()
  let trigger: HTMLElement | null = null
  function toBody(node: HTMLDialogElement) { document.body.appendChild(node); return { destroy() { node.close(); node.remove() } } }
  $effect(() => {
    if (!dialog) return
    if (open && !dialog.open) {
      trigger = untrack(() => document.activeElement instanceof HTMLElement ? document.activeElement : null)
      dialog.showModal()
    } else if (!open && dialog.open) dialog.close()
  })
  // the backdrop's default pointerdown would move focus to BODY after close restored it to the trigger
  function outside(e: PointerEvent) {
    if (e.target !== dialog || !dialog) return
    const r = dialog.getBoundingClientRect()
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { e.preventDefault(); dialog.close() }
  }
  // Edge's native modal lets Tab leave the last key for BODY: wrap Tab and Shift+Tab inside the dialog
  function wrap(e: KeyboardEvent) {
    if (e.key !== 'Tab' || !dialog) return
    const keys = [...dialog.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')]
    if (!keys.length) return
    const first = keys[0], last = keys[keys.length - 1], at = document.activeElement
    if (e.shiftKey ? at === first || !dialog.contains(at) : at === last || !dialog.contains(at)) {
      e.preventDefault(); (e.shiftKey ? last : first).focus()
    }
  }
</script>

<dialog class="m-dialog" bind:this={dialog} use:toBody aria-labelledby={`${id}-title`} aria-describedby={`${id}-body`} onpointerdown={outside} onkeydown={wrap} onclose={() => { open = false; if (trigger?.isConnected) trigger.focus({ preventScroll: true }) }}>
  <h2 id={`${id}-title`}>{title}</h2>
  <div class="m-dialog-body" id={`${id}-body`}>{@render children()}</div>
  <div class="m-dialog-actions">{@render actions()}</div>
</dialog>
