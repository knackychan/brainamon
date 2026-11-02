<script lang="ts">
  // A window's scrolling body (.cw-body), inside WinFrame; the footer below it is WinFoot.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLDivElement> & { ref?: HTMLDivElement; children?: Snippet }
  let { class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<div bind:this={ref} {...rest} class={['cw-body', cls]}>{@render children?.()}</div>
