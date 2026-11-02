<script lang="ts">
  import { PX, IC, pxPath } from './px'
  // name looks in IC first, then PX. Renders the V6 `svg.px` glyph.
  let { name }: { name: string } = $props()
  const d = $derived(pxPath(IC[name] ?? PX[name] ?? []))
</script>

<svg class="px" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" {d} /></svg>
