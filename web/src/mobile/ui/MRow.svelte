<script lang="ts">
  // A settings row on a phone screen (.m-srow in mobile.css): bold title, an optional small
  // description, then the row's control (the children).
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Text = string | number | Snippet
  type Props = Omit<HTMLAttributes<HTMLDivElement>, 'title'> & { wrap?: boolean; title: Text; desc?: Text; ref?: HTMLDivElement; children?: Snippet }
  let { wrap = false, title, desc, class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

{#if wrap}
<div bind:this={ref} {...rest} class={['m-srow', 'm-setting-row', cls]}><div class="m-row-words"><b>{#if typeof title === 'function'}{@render title()}{:else}{title}{/if}</b>{#if desc !== undefined}<small>{#if typeof desc === 'function'}{@render desc()}{:else}{desc}{/if}</small>{/if}</div>{@render children?.()}</div>
{:else}
<div bind:this={ref} {...rest} class={['m-srow', cls]}><b>{#if typeof title === 'function'}{@render title()}{:else}{title}{/if}</b>{#if desc !== undefined}<small>{#if typeof desc === 'function'}{@render desc()}{:else}{desc}{/if}</small>{/if}{@render children?.()}</div>
{/if}
