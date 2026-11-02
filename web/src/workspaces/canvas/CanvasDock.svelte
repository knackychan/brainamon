<script lang="ts">
  // The Canvas rail (V6 buildCanvasDock): 01 time, 02 target, 03 canvases (New, Rename, Delete),
  // 04 your items (search; double-click, Enter or drag onto the board), 05 tools, 06 arrange, 07 zoom.
  import ClockTile from '../library/dock/ClockTile.svelte'
  import Wg from '../library/dock/Wg.svelte'
  import Px from '../../lib/Px.svelte'
  import { attachAt, dragArm } from '../../lib/attach'
  import { activeCount, cv, openCanvas } from '../../lib/canvas.svelte'
  import { center, cvAction, offWhy, type CvAct } from '../../lib/canvas-board'
  import { titleOf } from '../../lib/cards/card'
  import { soonText } from '../../lib/commands'
  import { lib, thumbSrc } from '../../lib/library.svelte'
  import { setWS, toast, ui } from '../../lib/ui.svelte'
  import Button from '../../components/ui/Button.svelte'

  let q = $state('')
  const items = $derived.by(() => {
    const s = q.trim().toLowerCase()
    return lib.rows.filter(r => !s || `${r.title} ${r.creator} ${r.desc} ${r.tags} No.${r.id}`.toLowerCase().includes(s))
      .sort((a, b) => b.id - a.id).slice(0, 40)
  })
  const pct = $derived(Math.round(cv.s * 100) + '%')

  function tool(a: CvAct) {
    const why = offWhy(a)
    if (why) { toast(why, 'w'); return }
    cvAction(a)
  }
  const dis = (a: CvAct) => (offWhy(a) ? 'true' : undefined)
  function pick(id: string) {
    openCanvas(id)
    if (ui.ws !== 'canvas') setWS('canvas')
  }
  function addHere(id: number) {
    if (!cv.doc) { toast('Create a canvas first', 'w'); return }
    const p = center()
    attachAt([id], { x: p.x - 110, y: p.y - 160 })
  }
</script>

<ClockTile />
<Wg cls="y s3" id="ctgt" title="Target" jp="送り先">
  <p class="wg-sub">Add to canvas lands in</p>
  <label class="sr" for="ct-sel">Active canvas</label>
  <select class="tsel" id="ct-sel" value={cv.active ?? ''} onchange={e => openCanvas(e.currentTarget.value)}>
    {#each cv.list as c (c.id)}<option value={c.id}>{c.name} · {c.id === cv.active ? activeCount() : c.count}</option>{:else}<option value="">No canvas</option>{/each}
  </select>
  <div class="tkeys"><Button kind="tool" wide aria-pressed="false" onclick={() => toast(soonText('15 (after parity)'), 'w')}>Pop-out</Button></div>
</Wg>
<Wg cls="s6" id="cvl" title="Canvases" jp="キャンバス" n={cv.list.length}>
  <div class="tlist" role="list">
    {#each cv.list as c (c.id)}
      <button type="button" class="trow" aria-current={c.id === cv.active} onclick={() => pick(c.id)}><span class="l">{c.name}</span><span class="c">{c.id === cv.active ? activeCount() : c.count} elements</span></button>
    {:else}
      <p class="wg-sub">No canvases yet.</p>
    {/each}
  </div>
  <div class="tkeys">
    <Button kind="tool" variant="pri" onclick={() => cvAction('new')}><Px name="plus" />New</Button>
    <Button kind="tool" aria-disabled={cv.doc ? undefined : 'true'} onclick={() => tool('rename')}><Px name="edit" />Rename</Button>
    <span class="sp"></span>
    <Button kind="tool" aria-disabled={cv.doc ? undefined : 'true'} onclick={() => tool('del')}><Px name="trash" />Delete</Button>
  </div>
</Wg>
<Wg cls="s6" id="yi" title="Your items" jp="アイテム" n={items.length}>
  <label class="sr" for="yi-q">Search your items</label>
  <input class="tin" id="yi-q" type="search" placeholder="search, then double-click or drag onto the board" autocomplete="off" bind:value={q} />
  <div class="tlist" role="list">
    {#each items as r (r.id)}
      <button type="button" class="trow it" title="Double-click or Enter adds it; drag it onto the board"
        ondblclick={() => addHere(r.id)} onkeydown={e => { if (e.key === 'Enter') { e.preventDefault(); addHere(r.id) } }}
        onpointerdown={e => dragArm(e, r.id, [r.id])}>
        {#if r.thumb}<img src={thumbSrc(r.id)} alt="" loading="lazy" style:object-position="50% 42%" />{:else}<span></span>{/if}<span class="l">{titleOf(r)}</span><span class="c">No.{r.id}</span>
      </button>
    {:else}
      <p class="wg-sub">Nothing matches.</p>
    {/each}
  </div>
</Wg>
<Wg cls="s2" id="cvtools" title="Tools" jp="道具">
  <div class="tcol">
    <Button kind="tool" aria-disabled={dis('note')} onclick={() => tool('note')}><Px name="note" />Note</Button>
    <Button kind="tool" aria-disabled={dis('image')} onclick={() => tool('image')}><Px name="img" />Image</Button>
    <Button kind="tool" aria-disabled={dis('label')} onclick={() => tool('label')}><Px name="tag" />Label</Button>
    <Button kind="tool" aria-disabled={dis('delete')} onclick={() => tool('delete')}><Px name="trash" />Delete</Button>
  </div>
</Wg>
<Wg cls="s s2" id="cvarr" title="Arrange" jp="整列">
  <div class="tcol">
    <Button kind="tool" aria-disabled={dis('row')} onclick={() => tool('row')}>Row</Button>
    <Button kind="tool" aria-disabled={dis('grid')} onclick={() => tool('grid')}>Grid</Button>
    <Button kind="tool" aria-disabled={dis('all')} onclick={() => tool('all')}>Select all</Button>
  </div>
</Wg>
<section class="wg k s2" aria-labelledby="h-cvz">
  <header class="wg-hd"><h2 id="h-cvz">Zoom</h2><span class="n"></span><span class="jp" aria-hidden="true">拡大</span></header>
  <p class="dotn sm" id="cvz-n">{pct}</p>
  <div class="zk">
    <button type="button" aria-label="Zoom out" onclick={() => tool('zout')}>−</button>
    <button type="button" onclick={() => tool('fit')}>Fit</button>
    <button type="button" aria-label="Zoom in" onclick={() => tool('zin')}>+</button>
  </div>
</section>
