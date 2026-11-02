<script lang="ts">
  // A row of lit segments (V6 segs()).
  let { n = 10, lit, k }: { n?: number; lit: number; k?: string } = $props()
</script>

<span class="segs" aria-hidden="true" style:--k={k}>{#each { length: n } as _, i (i)}<i class:lit={i < lit}></i>{/each}</span>
