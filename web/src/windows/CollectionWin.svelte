<script lang="ts">
  // Collection (V6 winCollection; Qt ui/category_dialog.py): name (saved upper-case), colour from the
  // 14 colour swatches, Delete moves the items to INTERESTING. INTERESTING can be
  // recoloured only.
  import { untrack } from 'svelte'
  import Px from '../lib/Px.svelte'
  import { api } from '../lib/api'
  import { plural } from '../lib/jobs'
  import { lib, loadCats, type Category } from '../lib/library.svelte'
  import { toast } from '../lib/ui.svelte'
  import { confirmWin } from '../lib/windows.svelte'
  import Button from '../components/ui/Button.svelte'
  import Field from '../components/ui/Field.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { name = null, close }: { name?: string | null; close: () => void } = $props()
  const SWATCH = ['#2E75B6', '#7030A0', '#E46C0A', '#375623', '#C00000', '#538135', '#1F3864',
    '#F4B942', '#4472C4', '#70AD47', '#404040', '#C55A11', '#7F6000', '#000000']
  const orig = untrack(() => name)          // the collection this window edits (null = new)
  const is = orig !== null
  const fixed = orig === 'INTERESTING'
  const n = is ? lib.rows.filter(r => r.cat === orig).length : 0
  let nm = $state(orig ?? '')
  let col = $state(is ? (lib.cats.find(c => c.name === orig)?.color ?? SWATCH[0]) : SWATCH[8])
  let hid = $state(is ? !!lib.cats.find(c => c.name === orig)?.hidden : false)
  let err = $state('')

  async function save() {
    err = ''
    const v = nm.trim().toUpperCase()
    if (!v) { err = 'Enter a name.'; return }
    try {
      if (!is) await api.post<Category[]>('/api/categories', { name: v, color: col, hidden: hid })
      else await api.patch<Category[]>(`/api/categories/${encodeURIComponent(orig!)}`, { name: v, color: col, hidden: hid })
      await loadCats()
      if (is && v !== orig && lib.cat === orig) lib.cat = v
      close()
      toast(is ? `Saved ${v}` : `Added the ${v} collection`)
    } catch (e) { err = (e as Error).message }
  }

  async function del() {
    const ok = await confirmWin({ title: `Delete ${orig}?`, code: 'COL-05', danger: true, ok: 'Delete collection',
      msg: `The ${plural(n, 'item')} in ${orig} move to INTERESTING. The items are kept.` })
    if (!ok) return
    try {
      await api.del(`/api/categories/${encodeURIComponent(orig!)}`)
      await loadCats()
      if (lib.cat === orig) lib.cat = 'all'
      close()
      toast(`Deleted ${orig}; ${plural(n, 'item')} moved to INTERESTING`)
    } catch (e) { err = (e as Error).message }
  }
</script>

<WinBody>
  <form class="fg" novalidate onsubmit={e => { e.preventDefault(); save() }}>
    <Field label="Name" for="c-name"><input class="inp" class:bad={!!err} id="c-name" bind:value={nm} autocomplete="off" readonly={fixed} data-autofocus={!fixed ? true : undefined} /></Field>
    <Label as="span" class="top">Colour</Label>
    <div class="swatches" role="group" aria-label="Colour">
      {#each SWATCH as c (c)}<button type="button" style:--k={c} aria-pressed={c.toLowerCase() === col.toLowerCase()} aria-label={`Colour ${c}`} onclick={() => (col = c)}></button>{/each}
    </div>
    <span></span><label class="hint"><input type="checkbox" bind:checked={hid} /> Hide from the main feed (shown only when this collection is open or Show hidden is on)</label>
    <span></span><Hint tone="error" hidden={!err}>{err}</Hint>
    {#if fixed}<span></span><Hint>INTERESTING is the default collection for new items. It can be recoloured, not renamed or deleted.</Hint>{/if}
  </form>
</WinBody>
<WinFoot>
  {#snippet start()}
  {#if is && !fixed}<Button variant="danger" onclick={del}><Px name="trash" />Delete ({plural(n, 'item')})</Button>{/if}
  {/snippet}
  <Button onclick={close}>Cancel</Button>
  <Button variant="pri" data-autofocus={fixed ? true : undefined} onclick={save}>Save</Button>
</WinFoot>
