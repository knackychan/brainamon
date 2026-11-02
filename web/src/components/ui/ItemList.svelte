<script lang="ts" generics="T">
  // Rows of one thing each (.ilist, app.css): what the row says first, its quiet actions after, hairlines
  // between. At narrow widths the actions wrap under the words. `key` must be unique per item.
  import type { Snippet } from 'svelte'

  let { items, key, item, actions, label }: { items: T[]; key: (x: T) => string; item: Snippet<[T]>; actions?: Snippet<[T]>; label?: string } = $props()
</script>

<ul class="ilist" aria-label={label}>{#each items as x (key(x))}<li><div>{@render item(x)}</div>{#if actions}<span class="acts">{@render actions(x)}</span>{/if}</li>{/each}</ul>
