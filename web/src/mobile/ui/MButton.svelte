<script lang="ts">
  // The phone's button (.m-btn in mobile.css); as="a" draws a link with the same look. shape="pill" (projects/
  // phone-settings, spec section 6; settings.css) is a page's answer: Archivo 14 px, 44 px high, round ends.
  import type { Snippet } from 'svelte'
  import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements'

  type Props = HTMLButtonAttributes & HTMLAnchorAttributes & {
    as?: 'button' | 'a'
    variant?: 'default' | 'pri' | 'dk' | 'danger'
    size?: 'md' | 'sm'
    shape?: 'rect' | 'pill'
    ref?: HTMLButtonElement | HTMLAnchorElement
    children?: Snippet
  }
  let { as = 'button', variant = 'default', size = 'md', shape = 'rect', type = 'button', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
  const classes = $derived(['m-btn', size === 'sm' && 'sm', shape === 'pill' && 'pill', variant !== 'default' && variant, cls])
</script>

{#if as === 'a'}
  <a bind:this={ref} {...rest} class={classes}>{@render children?.()}</a>
{:else}
  <button bind:this={ref} {...rest} {type} class={classes}>{@render children?.()}</button>
{/if}
