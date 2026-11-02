<script lang="ts">
  // A state with SetupHub's step marker (.status-dot, app.css): a green check when on or ready, a ring when
  // still to do, an orange ring for the next step, a dashed ring when optional; never red (an error is a
  // Hint tone="error"). `state` overrides `on`; `n` puts a step number in a marker that is not done.
  // Alone it is the marker; with children, the marker and its words.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type State = 'done' | 'todo' | 'next' | 'optional'
  type Props = HTMLAttributes<HTMLElement> & { on?: boolean; state?: State; n?: number; as?: 'p' | 'span'; ref?: HTMLElement; children?: Snippet }
  let { on = false, state, n, as = 'p', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
  const s = $derived(state ?? (on ? 'done' : 'todo'))
  const dot = $derived(['status-dot', s === 'done' && 'on', s === 'next' && 'next', s === 'optional' && 'opt'])
</script>

{#if children}
  <svelte:element this={as} bind:this={ref} {...rest} class={['status-line', cls]}><i class={dot} aria-hidden="true">{#if n && s !== 'done'}{n}{/if}</i><span>{@render children()}</span></svelte:element>
{:else}
  <i bind:this={ref} {...rest} class={[...dot, cls]} aria-hidden="true">{#if n && s !== 'done'}{n}{/if}</i>
{/if}
