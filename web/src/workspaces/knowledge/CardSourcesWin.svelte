<script lang="ts">
  // A connection card's sources (Qt ui/connections_sources_dialog.py): drop the irrelevant ones, add
  // the Library selection, then Save; Accept then synthesizes exactly these.
  import { untrack } from 'svelte'
  import { titleOf } from '../../lib/cards/card'
  import { act } from '../../lib/cardmenu'
  import { ks, setCardSources } from '../../lib/knowledge.svelte'
  import { lib, thumbSrc } from '../../lib/library.svelte'
  import { toast } from '../../lib/ui.svelte'
  import Button from '../../components/ui/Button.svelte'
  import Hint from '../../components/ui/Hint.svelte'
  import WinBody from '../../components/ui/WinBody.svelte'
  import WinFoot from '../../components/ui/WinFoot.svelte'

  let { cardKey, close }: { cardKey: string; close: () => void } = $props()
  const card = untrack(() => ks.cards.find(c => c.key === cardKey))
  let ids = $state<number[]>(card ? [...card.item_ids] : [])
  const rows = $derived(ids.map(id => lib.byId.get(id)).filter(r => !!r))

  function addSelection() {
    const add = [...lib.sel].filter(id => !ids.includes(id))
    if (!add.length) { toast('Select items in the Library first (they are added here)', 'w'); return }
    ids = [...ids, ...add]
  }
  async function save() {
    if (!ids.length) { toast('Keep at least one source', 'w'); return }
    try { await setCardSources(cardKey, ids); close() } catch (e) { toast((e as Error).message, 'w') }
  }
</script>

<WinBody>
  {#if card}<Hint style="margin-bottom:10px">{card.text}</Hint>{/if}
  <div class="blist">
    {#each rows as r (r!.id)}
      <div class="brow">
        {#if r!.thumb}<img src={thumbSrc(r!.id)} alt="" />{:else}<span></span>{/if}
        <span>{titleOf(r!)}</span>
        <small><Button size="sm" onclick={() => act('open', r!.id)}>Open</Button> <Button size="sm" onclick={() => (ids = ids.filter(x => x !== r!.id))}>Remove</Button></small>
      </div>
    {:else}
      <p class="pal-empty">No sources left.</p>
    {/each}
  </div>
</WinBody>
<WinFoot>
  {#snippet start()}
  <Button onclick={addSelection}>Add the Library selection ({lib.sel.size})</Button>
  {/snippet}
  <Button onclick={close}>Cancel</Button>
  <Button variant="pri" onclick={save}>Save</Button>
</WinFoot>
