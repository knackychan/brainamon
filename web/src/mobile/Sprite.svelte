<script lang="ts">
  import WiskitSprite from '../components/WiskitSprite.svelte'
  import { phone } from './state.svelte'
  let { pose = 'idle' }: { pose?: string } = $props()
</script>

<div class="m-sprite"><WiskitSprite {pose} motionOff={phone.motionOff} /></div>
