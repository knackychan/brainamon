<script lang="ts">
  // A form label (.fl): a <label> for one control, or a <span> (as="span") for a group of them.
  import type { Snippet } from 'svelte'
  import type { HTMLLabelAttributes } from 'svelte/elements'

  type Props = HTMLLabelAttributes & { as?: 'label' | 'span'; ref?: HTMLElement; children?: Snippet }
  let { as = 'label', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<svelte:element this={as} bind:this={ref} {...rest} class={['fl', cls]}>{@render children?.()}</svelte:element>
