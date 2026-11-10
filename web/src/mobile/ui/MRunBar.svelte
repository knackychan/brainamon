<script lang="ts">
  // The run bar (projects/phone-processing-flow; tools.css .m-runbar), the Notes Synthesize bar's shape: a line over
  // a meter split by result (done teal, skipped amber, failed red, the current one striped orange), then the keys.
  // The meter's range is never zero and its count never passes it (a PC job whose rows are not loaded yet).
  import type { Snippet } from 'svelte'
  import { meter } from '../tools'

  type Props = { lead: string; strong?: string; right: string; total: number; done: number; skip?: number; err?: number; run?: boolean; label: string; children?: Snippet }
  let { lead, strong = '', right, total, done, skip = 0, err = 0, run = false, label, children }: Props = $props()
  const m = $derived(meter(total, done + skip + err))
  const w = (k: number) => `${(100 * Math.min(k, m.max) / m.max).toFixed(2)}%`
</script>

<div class="m-runbar">
  <div class="m-runbar-top"><span>{#if strong}<b>{strong}</b>{' '}{/if}{lead}</span><span>{right}</span></div>
  <div class="m-meter" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={m.max} aria-valuenow={m.now}>
    <i style:width={w(done)}></i><i class="m-meter-skip" style:width={w(skip)}></i><i class="m-meter-err" style:width={w(err)}></i>{#if run}<i class="m-meter-run" style:width={w(1)}></i>{/if}
  </div>
  <div class="m-runbar-keys">{@render children?.()}</div>
</div>
