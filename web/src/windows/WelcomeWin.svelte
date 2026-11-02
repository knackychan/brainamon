<script lang="ts">
  import SetupHub from './SetupHub.svelte'
  let { close }: { close: () => void } = $props()
</script>

<SetupHub {close} />
