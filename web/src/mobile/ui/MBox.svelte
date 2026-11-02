<script lang="ts">
  // A framed group on a phone screen (.m-box in mobile.css).
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLElement> & { as?: 'div' | 'section'; ref?: HTMLElement; children?: Snippet }
  let { as = 'div', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<svelte:element this={as} bind:this={ref} {...rest} class={['m-box', cls]}>{@render children?.()}</svelte:element>
