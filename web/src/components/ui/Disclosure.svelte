<script lang="ts">
  // The quiet underlined disclosure (.set-more, app.css): one summary line, the long explanation under it,
  // closed by default. Every paragraph inside is a Hint. `open` is a plain prop; Settings' focusSection
  // opens the element itself when a found section sits inside.
  import type { Snippet } from 'svelte'
  import type { HTMLDetailsAttributes } from 'svelte/elements'

  type Props = HTMLDetailsAttributes & { summary: string; open?: boolean; ref?: HTMLDetailsElement; children?: Snippet }
  let { summary, open = false, class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<details bind:this={ref} {...rest} {open} class={['set-more', cls]}><summary>{summary}</summary>{@render children?.()}</details>
