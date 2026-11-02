<script lang="ts">
  // A section title inside a window (.fsec: small caps line with a dashed rule after it).
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLElement> & { as?: 'h3' | 'p'; ref?: HTMLElement; children?: Snippet }
  let { as = 'h3', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<svelte:element this={as} bind:this={ref} {...rest} class={['fsec', cls]}>{@render children?.()}</svelte:element>
