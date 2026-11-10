<script lang="ts">
  // One 12 x 12 shell glyph (tabicons.ts), drawn at the size mobile.css gives .m-ico (20 px), in currentColor.
  import { shellIcon, type ShellGlyph } from './tabicons'
  let { name, on = false }: { name: ShellGlyph; on?: boolean } = $props()
</script>

<svg class="px m-ico" viewBox="0 0 12 12" aria-hidden="true"><path fill="currentColor" d={shellIcon(name, on)} /></svg>
