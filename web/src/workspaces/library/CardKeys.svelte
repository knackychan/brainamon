<script lang="ts">
  // The key strip under a card (V6 keysHTML): Edit, Download video, Thumbnail only, grip (to a
  // canvas), Delete. Each goes through cardmenu.act so later plans fill them in.
  import Px from '../../lib/Px.svelte'
  import { act } from '../../lib/cardmenu'

  let { id }: { id: number } = $props()
</script>

<div class="ck-row" role="group" aria-label={`No.${id} actions`}>
  <button type="button" class="ck" title="Edit" aria-label={`Edit No.${id}`} onclick={() => act('open', id)}><Px name="edit" /></button>
  <button type="button" class="ck" title="Download video" aria-label={`Download the video of No.${id}`} onclick={() => act('download', id)}><Px name="down" /></button>
  <button type="button" class="ck" title="Thumbnail only" aria-label={`Fetch the thumbnail of No.${id}`} onclick={() => act('thumbOnly', id)}><Px name="img" /></button>
  <button type="button" class="ck grip" title="Drag onto a canvas, or press to add it to the active canvas" aria-label={`Add No.${id} to the active canvas`} onclick={e => act('grip', id, e.currentTarget)}><Px name="grip" /></button>
  <button type="button" class="ck del" title="Delete" aria-label={`Delete No.${id}`} onclick={() => act('del', id)}><Px name="trash" /></button>
</div>
