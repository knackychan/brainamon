<script lang="ts">
  // A help line (.hint) or, with tone="error", an error line (.err), from the V6 page CSS.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLElement> & {
    as?: 'p' | 'small' | 'span' | 'div' | 'ol' | 'pre'
    tone?: 'hint' | 'error' | 'positive'
    ref?: HTMLElement
    children?: Snippet
  }
  let { as = 'p', tone = 'hint', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<svelte:element this={as} bind:this={ref} {...rest} class={[tone === 'error' ? 'err' : tone === 'positive' ? 'positive' : 'hint', cls]}>{@render children?.()}</svelte:element>

<style>
  .positive { color: color-mix(in srgb, var(--ok) 55%, var(--rw-ink)); font: inherit }
</style>
