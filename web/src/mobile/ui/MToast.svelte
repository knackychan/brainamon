<script lang="ts">
  // A short pill above the dock (projects/motion-language plan 08): the text for `ms` (3.6 s), then `onclose`. It pops in
  // (motion.css .mo-pop; nothing moves with motion off) and is announced as a status, never a button or a trap.
  import { onMount } from 'svelte'

  let { text, ms = 3600, onclose }: { text: string; ms?: number; onclose: () => void } = $props()
  onMount(() => {
    const timer = setTimeout(onclose, ms)
    return () => clearTimeout(timer)
  })
</script>

<div class="m-toast" role="status"><span class="mo-pop">{text}</span></div>
