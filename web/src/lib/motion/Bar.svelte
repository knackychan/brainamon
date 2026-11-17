<script lang="ts">
  // BAR (motion language, motion.css .mo-bar): `busy` sweeps while the amount of work is unknown, `fill` follows
  // `value` (0 to 1), `ok` is the full green bar of a finished run. Motion off: busy is a still, faint bar.
  let { mode = 'fill', value = 0, label }: { mode?: 'busy' | 'fill' | 'ok'; value?: number; label: string } = $props()
  const pct = $derived(mode === 'ok' ? 100 : Math.round(Math.min(1, Math.max(0, value)) * 100))
</script>

{#if mode === 'busy'}
  <div class="mo-bar mo-busy" role="progressbar" aria-label={label}><i></i></div>
{:else}
  <div class="mo-bar" class:mo-ok={mode === 'ok'} role="progressbar" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><i style:width="{pct}%"></i></div>
{/if}
