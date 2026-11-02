<script lang="ts">
  // A phone help line (.m-hint in mobile.css), a <span> unless `as` says otherwise; tone="error" adds .err.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLElement> & {
    as?: 'span' | 'p' | 'small' | 'div'
    tone?: 'hint' | 'error'
    ref?: HTMLElement
    children?: Snippet
  }
  let { as = 'span', tone = 'hint', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<svelte:element this={as} bind:this={ref} {...rest} class={['m-hint', tone === 'error' && 'err', cls]}>{@render children?.()}</svelte:element>
