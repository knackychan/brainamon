<script lang="ts">
  // The phone's quiet disclosure (.m-more in mobile.css): one summary line, the long explanation under it, closed
  // by default. Every line inside is an MHint or an MRow. `open` is a plain prop; rest props (an id) land on details.
  import type { Snippet } from 'svelte'
  import type { HTMLDetailsAttributes } from 'svelte/elements'

  type Props = HTMLDetailsAttributes & { summary: string; open?: boolean; children?: Snippet }
  let { summary, open = false, class: cls, children, ...rest }: Props = $props()
</script>

<details {...rest} {open} class={['m-more', cls]}><summary>{summary}</summary><div class="m-more-body">{@render children?.()}</div></details>
