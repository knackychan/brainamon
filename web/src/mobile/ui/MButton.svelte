<script lang="ts">
  // The phone's button (.m-btn in mobile.css); as="a" draws a link with the same look.
  import type { Snippet } from 'svelte'
  import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements'

  type Props = HTMLButtonAttributes & HTMLAnchorAttributes & {
    as?: 'button' | 'a'
    variant?: 'default' | 'pri' | 'dk'
    size?: 'md' | 'sm'
    ref?: HTMLButtonElement | HTMLAnchorElement
    children?: Snippet
  }
  let { as = 'button', variant = 'default', size = 'md', type = 'button', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
  const classes = $derived(['m-btn', size === 'sm' && 'sm', variant !== 'default' && variant, cls])
</script>

{#if as === 'a'}
  <a bind:this={ref} {...rest} class={classes}>{@render children?.()}</a>
{:else}
  <button bind:this={ref} {...rest} {type} class={classes}>{@render children?.()}</button>
{/if}
