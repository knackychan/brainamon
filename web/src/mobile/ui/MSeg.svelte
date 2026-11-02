<script lang="ts">
  // A few equal choices on one line (.m-seg in mobile.css): one button per option with aria-pressed; `label`
  // names the group for assistive tech. onchange(value) gets the tapped option's value.
  type Props = { label: string; options: [string, string][]; value: string; size?: 'md' | 'sm'; disabled?: boolean; onchange?: (value: string) => void }
  let { label, options, value, size = 'md', disabled = false, onchange }: Props = $props()
</script>

<div class={['m-seg', size === 'sm' && 'sm']} role="group" aria-label={label}>{#each options as [v, text] (v)}<button type="button" aria-pressed={value === v} {disabled} onclick={() => onchange?.(v)}>{text}</button>{/each}</div>
