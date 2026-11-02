<script lang="ts">
  // A calm group in a Settings section (.group-box, app.css): its own label column, the group's title in the first
  // cell and its action row last. tone="summary" is the filled at-a-glance panel; active outlines the open task.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLElement> & { tone?: 'group' | 'summary'; active?: boolean; ref?: HTMLElement; children?: Snippet }
  let { tone = 'group', active = false, class: cls, ref = $bindable(), children, ...rest }: Props = $props()
</script>

<section bind:this={ref} {...rest} class={['group-box', tone === 'summary' && 'summary', active && 'on', cls]}>{@render children?.()}</section>
