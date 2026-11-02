<script lang="ts">
  // One rail tile (V6 wg()): numbered by the dock's CSS, a header with title, a count and the
  // Japanese label, then the body.
  import type { Snippet } from 'svelte'
  let { cls = '', id, title, jp, n = '', children }: { cls?: string; id: string; title: string; jp: string; n?: string | number; children: Snippet } = $props()
</script>

<section class={'wg' + (cls ? ' ' + cls : '')} aria-labelledby={'h-' + id}>
  <header class="wg-hd"><h2 id={'h-' + id}>{title}</h2><span class="n" id={'n-' + id}>{n}</span><span class="jp" aria-hidden="true">{jp}</span></header>
  {@render children()}
</section>
