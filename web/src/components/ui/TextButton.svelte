<script lang="ts">
  // A quiet underlined action (.text-btn, app.css) beside a row's keys: Cancel, Close, Hide. Never the primary action.
  import type { Snippet } from 'svelte'
  import type { HTMLButtonAttributes } from 'svelte/elements'

  type Props = HTMLButtonAttributes & { ref?: HTMLButtonElement; children?: Snippet }
  let { type = 'button', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<button bind:this={ref} {...rest} {type} class={['text-btn', cls]}>{@render children?.()}</button>
