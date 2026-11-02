<script lang="ts" generics="T extends string">
  // A few equal choices (the V6 .seg): one pressed button per option, switching what the section below shows.
  // tone="yes": the chosen option draws in the accent when it is not the first ("None" stays ink), for choices that mean
  // "included" (Backup > Canvases, Videos).
  let { options, value = $bindable(), label, disabled = false, tone = 'default', onchange }: {
    options: { value: T; label: string }[]; value: T; label: string; disabled?: boolean; tone?: 'default' | 'yes'; onchange?: (value: T) => void
  } = $props()
</script>

<div class={['seg', tone === 'yes' && 'yes']} role="group" aria-label={label}>{#each options as option (option.value)}<button type="button" aria-pressed={value === option.value} {disabled} onclick={() => { value = option.value; onchange?.(option.value) }}>{option.label}</button>{/each}</div>

<style>
  .seg.yes button[aria-pressed="true"]:not(:first-child) { background: var(--accent); color: #1f1f22 }
</style>
