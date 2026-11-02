<script lang="ts">
  // A glyph inside a key (the app has no icon set yet): pause and play, currentColor, so it follows the key's variant.
  let { name }: { name: 'pause' | 'play' } = $props()
</script>

<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" focusable="false">
  {#if name === 'pause'}<rect x="1" y="0.5" width="3" height="9" rx="0.5" fill="currentColor" /><rect x="6" y="0.5" width="3" height="9" rx="0.5" fill="currentColor" />
  {:else}<path d="M2 0.8v8.4a.5.5 0 0 0 .76.43l6.6-4.2a.5.5 0 0 0 0-.86L2.76.37A.5.5 0 0 0 2 .8Z" fill="currentColor" />{/if}
</svg>
