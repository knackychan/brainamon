<script lang="ts">
  // Bulk edit (V6 winBulk; Qt ui/bulk_edit_dialog.py): the items it was opened with (the selection,
  // else the visible items), a filter, Select all, Invert, then one action on the ticked ones.
  import { SvelteSet } from 'svelte/reactivity'
  import { api } from '../lib/api'
  import { titleOf } from '../lib/cards/card'
  import { deleteItems } from '../lib/edit-commands'
  import { plural } from '../lib/jobs'
  import { lib, type Row, thumbSrc } from '../lib/library.svelte'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Field from '../components/ui/Field.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { close }: { close: () => void } = $props()
  const fromSel = lib.sel.size > 0
  const pool: Row[] = (fromSel ? [...lib.sel] : lib.visIds).map(id => lib.byId.get(id)).filter((r): r is Row => !!r)
  const on = new SvelteSet(pool.map(r => r.id))
  const ticked = $derived(on.size)
  let q = $state('')
  const TYPES = ['Reel', 'Video', 'Post', 'Link', 'Recipe', 'Tutorial', 'Other']
  const ACTS: [string, string][] = [['set_category', 'Set category'], ['set_type', 'Set type'], ['set_creator', 'Set creator'],
    ['add_tags', 'Add tags'], ['remove_tags', 'Remove tags'], ['delete', 'Delete items']]
  let action = $state('set_category')
  let value = $state(lib.cats[0]?.name ?? '')
  let busy = $state(false)
  const shown = $derived.by(() => {
    const s = q.trim().toLowerCase()
    return (s ? pool.filter(r => `${r.id} ${r.title} ${r.creator} ${r.tags} ${r.cat} ${r.type}`.toLowerCase().includes(s)) : pool).slice(0, 400)
  })
  // the value control follows the action
  $effect(() => {
    if (action === 'set_category') value = lib.cats[0]?.name ?? ''
    else if (action === 'set_type') value = 'Reel'
    else value = ''
  })

  const tick = (id: number, v: boolean) => { if (v) on.add(id); else on.delete(id) }
  function all() { pool.forEach(r => on.add(r.id)) }
  function invert() { pool.forEach(r => (on.has(r.id) ? on.delete(r.id) : on.add(r.id))) }

  async function apply() {
    const ids = [...on]
    if (!ids.length) { toast('Tick at least one item', 'w'); return }
    if (action === 'delete') { close(); await deleteItems(ids); return }
    const v = value.trim()
    if (!v) { toast('Enter a value', 'w'); return }
    busy = true
    try {
      const r = await api.post<{ changed: number }>('/api/items/bulk', { ids, action, value: v })
      toast(`${ACTS.find(a => a[0] === action)![1]}: ${plural(r.changed, 'item')} updated`)
    } catch (e) { toast((e as Error).message, 'w') } finally { busy = false }
  }
</script>

<WinBody>
  <div class="frow" style="margin-bottom:10px">
    <label class="sr" for="b-f">Filter</label><input class="inp" id="b-f" placeholder="Filter this list" autocomplete="off" bind:value={q} data-autofocus />
    <Button size="sm" onclick={all}>Select all</Button>
    <Button size="sm" onclick={invert}>Invert</Button>
  </div>
  <div class="blist" id="b-list">
    {#each shown as r (r.id)}
      <label class="brow"><input type="checkbox" checked={on.has(r.id)} onchange={e => tick(r.id, e.currentTarget.checked)} />
        {#if r.thumb}<img src={thumbSrc(r.id)} alt="" loading="lazy" />{:else}<span></span>{/if}<span>{titleOf(r)}</span><small>{r.cat} · {r.type}</small></label>
    {:else}
      <p class="pal-empty">Nothing matches.</p>
    {/each}
  </div>
  <Hint style="margin:8px 0 14px">{ticked} of {pool.length} items ticked{shown.length < pool.length && !q ? ` (first ${shown.length} shown; filter to find the rest)` : ''}</Hint>
  <div class="fg">
    <Field label="Action" for="b-act"><select class="inp" id="b-act" bind:value={action}>{#each ACTS as [k, l] (k)}<option value={k}>{l}</option>{/each}</select></Field>
    <Label for="b-val">Value</Label>
    {#if action === 'set_category'}
      <select class="inp" id="b-val" bind:value={value}>{#each lib.cats as c (c.name)}<option>{c.name}</option>{/each}</select>
    {:else if action === 'set_type'}
      <select class="inp" id="b-val" bind:value={value}>{#each TYPES as t (t)}<option>{t}</option>{/each}</select>
    {:else if action === 'delete'}
      <Hint id="b-val">No value. The ticked items are deleted.</Hint>
    {:else}
      <input class="inp" id="b-val" bind:value={value} autocomplete="off" placeholder={action === 'set_creator' ? 'Creator name' : 'tag, another tag'} />
    {/if}
  </div>
</WinBody>
<WinFoot>
  {#snippet start()}
  <small>{fromSel ? 'Started from your selection' : 'Started from the visible items'}</small>
  {/snippet}
  <Button onclick={close}>Close</Button>
  <Button variant="pri" disabled={busy} onclick={apply}>Apply</Button>
</WinFoot>
