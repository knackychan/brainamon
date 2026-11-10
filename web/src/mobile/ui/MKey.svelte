<script lang="ts">
  // The phone shell's round key (.m-key in mobile.css, projects/phone-dock-shell): the top bar's 36 px
  // circles and pills (size "top"), the Wiskit composer's 44 px Send / Stop (size "mid",
  // projects/phone-wiskit-chat), the dock's 46 px circles (size "dock"). tone: plain (the case's key),
  // dark (the open section, the sync key with its panel open), add (the orange Add key). wide: a pill with
  // words after its glyph. as="a" draws a link with the same look; as="label" wraps a control that must take
  // the tap itself (the Library's sort <select>, invisible over the key, plans/06).
  import type { Snippet } from 'svelte'
  import type { HTMLAnchorAttributes, HTMLButtonAttributes, HTMLLabelAttributes } from 'svelte/elements'

  type Props = HTMLButtonAttributes & HTMLAnchorAttributes & {
    as?: 'button' | 'a' | 'label'
    size?: 'top' | 'mid' | 'dock'
    tone?: 'plain' | 'dark' | 'add' | 'danger'
    wide?: boolean
    ref?: HTMLButtonElement | HTMLAnchorElement | HTMLLabelElement
    children?: Snippet
  }
  let { as = 'button', size = 'top', tone = 'plain', wide = false, type = 'button', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
  const classes = $derived(['m-key', size !== 'top' && size, tone !== 'plain' && tone, wide && 'wide', cls])
</script>

{#if as === 'a'}
  <a bind:this={ref} {...rest} class={classes}>{@render children?.()}</a>
{:else if as === 'label'}
  <label bind:this={ref} {...rest as HTMLLabelAttributes} class={classes}>{@render children?.()}</label>
{:else}
  <button bind:this={ref} {...rest} {type} class={classes}>{@render children?.()}</button>
{/if}
