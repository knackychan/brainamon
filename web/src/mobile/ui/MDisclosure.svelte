<script lang="ts">
  // The phone's quiet disclosure (.m-more in mobile.css): one summary line, the long explanation under it, closed
  // by default. Every line inside is an MHint or an MRow. `open` is a plain prop; rest props (an id) land on details.
  import type { Snippet } from 'svelte'
  import type { HTMLDetailsAttributes } from 'svelte/elements'

  type Props = HTMLDetailsAttributes & { summary: string; less?: string; open?: boolean; foot?: boolean; children?: Snippet }
  let expanded = $state(false)
  let { summary, less = '', foot = false, open = false, class: cls, children, ...rest }: Props = $props()
</script>

<details {...rest} {open} ontoggle={e => expanded = e.currentTarget.open} class={['m-more', foot && 'm-more-foot', cls]}><summary>{expanded && less ? less : summary}</summary><div class="m-more-body">{@render children?.()}</div></details>
