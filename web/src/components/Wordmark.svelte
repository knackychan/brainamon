<script lang="ts">
  // The Brainamon wordmark (design/logo Kit-1, the same paths as web/public/brand/wordmark.svg, built by
  // projects/brainamon-logo/build.py): "Braina" and the i's diamond in currentColor, "mon" in the accent,
  // so it follows the theme. Sized by its height (CSS on .wm); the width follows the viewBox.
  let { label = '' }: { label?: string } = $props()
</script>

<svg class="wm" viewBox="0 -2 486 82" role={label ? 'img' : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : 'true'} focusable="false">
  <g fill="none" stroke-width="16" stroke-linecap="butt" stroke-linejoin="miter">
    <path stroke="currentColor" d="M8 0V80 M8 8H26L36 18V30L26 40H8 M8 40H30L40 50V62L30 72H8 M64 24V80 M64 48L80 32H92 M118 32H132L142 42V62L132 72H118L108 62V42Z M142 24V80 M166 24V80 M190 24V80 M190 44L202 32H212L222 42V80 M256 32H270L280 42V62L270 72H256L246 62V42Z M280 24V80" />
    <path class="wm-a" d="M304 24V80 M304 44L316 32H324L334 42V80 M334 44L346 32H354L364 42V80 M398 32H412L422 42V62L412 72H398L388 62V42Z M446 24V80 M446 44L458 32H468L478 42V80" />
  </g>
  <path fill="currentColor" d="M166 -2L176 8L166 18L156 8Z" />
</svg>

<style>
  .wm { display: block; height: 1em; width: auto; overflow: visible; flex: none }
  .wm-a { stroke: var(--accent) }
</style>
