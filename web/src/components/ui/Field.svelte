<script lang="ts">
  // One row of a form grid (.fg): the label and its control as two grid cells, no wrapper element.
  import type { Snippet } from 'svelte'
  import Label from './Label.svelte'

  let { label, for: htmlFor, as = 'label', children }: { label: string | number | Snippet; for?: string; as?: 'label' | 'span'; children?: Snippet } = $props()
</script>

<Label {as} for={htmlFor}>{#if typeof label === 'function'}{@render label()}{:else}{label}{/if}</Label> {@render children?.()}
