<script lang="ts">
  // A window's footer (.cw-foot): `start` sits before the spacer (a note, a secondary key),
  // the children after it (the window's actions, right-aligned).
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLDivElement> & { start?: Snippet; children?: Snippet }
  let { class: cls, start, children, ...rest }: Props = $props()
</script>

<div {...rest} class={['cw-foot', cls]}>{@render start?.()}<span class="sp"></span>{@render children?.()}</div>
