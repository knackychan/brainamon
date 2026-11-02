<script lang="ts">
  // 03 Collections: All items + every collection with its share bar and count; the pencil edits a
  // collection, New / Edit open the Collection window (plan 06 installs it in hooks.editCollection).
  import Px from '../../../lib/Px.svelte'
  import Tr from './Tr.svelte'
  import Wg from './Wg.svelte'
  import { runCmd, soonText } from '../../../lib/commands'
  import { hooks, lib, setFilter } from '../../../lib/library.svelte'
  import { toast } from '../../../lib/ui.svelte'
  import Button from '../../../components/ui/Button.svelte'

  const counts = $derived.by(() => { const m = new Map<string, number>(); for (const r of lib.rows) m.set(r.cat, (m.get(r.cat) ?? 0) + 1); return m })
  const max = $derived(Math.max(1, ...lib.cats.map(c => counts.get(c.name) ?? 0)))
  const edit = (name: string) => (hooks.editCollection ? hooks.editCollection(name) : toast(soonText('06'), 'w'))
</script>

<Wg cls="s6" id="cols" title="Collections" jp="コレクション" n={lib.cats.length}>
  <div class="rove" role="radiogroup" aria-label="Collection" data-rove id="cols-g">
    <div class="trw"><Tr label="All items" checked={lib.cat === 'all'} meter={1} k="var(--accent)" onpick={() => setFilter('cat', 'all')} /><span></span></div>
    {#each lib.cats as c (c.name)}
      {@const n = counts.get(c.name) ?? 0}
      <div class="trw">
        <Tr label={c.name} count={n} checked={lib.cat === c.name} meter={n / max} k={c.color} onpick={() => setFilter('cat', c.name)} />
        <button type="button" class="pen" aria-label={`Edit the ${c.name} collection`} title="Edit collection" onclick={() => edit(c.name)}><Px name="edit" /></button>
      </div>
    {/each}
  </div>
  <div class="tkeys">
    <Button kind="tool" variant="pri" onclick={() => runCmd('new-col')}><Px name="plus" />New</Button>
    <Button kind="tool" id="edit-col" aria-disabled={lib.cat === 'all' ? 'true' : 'false'} onclick={() => runCmd('edit-col')}><Px name="edit" />Edit</Button>
    <span class="sp"></span>
    {#if lib.hiddenCats.size}<Button kind="tool" aria-pressed={lib.showHidden} title="Show items from hidden collections in All items" onclick={() => (lib.showHidden = !lib.showHidden)}>{lib.showHidden ? 'Hide hidden' : 'Show hidden'}</Button>{/if}
  </div>
</Wg>
