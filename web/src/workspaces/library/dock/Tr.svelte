<script lang="ts">
  // One radio row of a rail tile (V6 rrow): label, count, an optional share bar (--m) in colour --k.
  let { label, count = '', checked, meter, k, off = false, hidden = false, onpick }: {
    label: string; count?: string | number; checked: boolean; meter?: number; k?: string; off?: boolean; hidden?: boolean; onpick: () => void
  } = $props()
</script>

<button type="button" class="tr" class:bar={meter !== undefined} role="radio" aria-checked={checked} tabindex={checked ? 0 : -1}
  aria-disabled={off ? 'true' : undefined} {hidden} style:--m={meter !== undefined ? meter.toFixed(3) : undefined} style:--k={k}
  onclick={() => { if (!off) onpick() }}><span class="l">{label}</span><span class="c">{count}</span></button>
