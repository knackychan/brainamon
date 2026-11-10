<script lang="ts">
  // Equal choices, the item's word tabs, or a small pill (the Wiskit composer's Quick / Deep,
  // projects/phone-wiskit-chat); all retain the existing aria-pressed group interface.
  import type { Snippet } from 'svelte'
  type Props = { label: string; options: [string, string][]; value: string; size?: 'md' | 'sm'; look?: 'seg' | 'tabs' | 'pill'; disabled?: boolean; onchange?: (value: string) => void; icon?: Snippet<[string]> }
  let { label, options, value, size = 'md', look = 'seg', disabled = false, onchange, icon }: Props = $props()
</script>

<div class={[look === 'tabs' ? 'm-tabline' : look === 'pill' ? 'm-segpill' : 'm-seg', size === 'sm' && 'sm']} role="group" aria-label={label}>{#each options as [v, text] (v)}<button type="button" aria-label={icon ? text : undefined} aria-pressed={value === v} {disabled} onclick={() => onchange?.(v)}>{#if icon}{@render icon(v)}{:else}{text}{/if}</button>{/each}</div>
