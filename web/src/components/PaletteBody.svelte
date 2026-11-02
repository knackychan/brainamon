<script lang="ts">
  // Ctrl+K command palette (V6 openPalette): every command by menu, then the provider groups
  // (items, notes, canvases) once the query has 2+ characters. Arrows move, Enter runs.
  import { CMD, labelOf, MENU_NAMES, runCmd, type MenuKey } from '../lib/commands'
  import { providers, type PaletteGroup, type PaletteRow } from '../lib/palette'
  import Px from '../lib/Px.svelte'
  import WinBody from './ui/WinBody.svelte'

  let { close }: { close: () => void } = $props()
  let q = $state('')
  let sel = $state(0)
  let box: HTMLDivElement | undefined = $state()

  const groups: PaletteGroup[] = $derived.by(() => {
    const s = q.trim().toLowerCase()
    const m = (t: string) => !s || t.toLowerCase().includes(s)
    const out: PaletteGroup[] = []
    for (const k of Object.keys(MENU_NAMES) as MenuKey[]) {
      const rows: PaletteRow[] = [...CMD.values()]
        .filter(c => c.menu === k && !c.hide && m(MENU_NAMES[k] + ' ' + labelOf(c)))
        .map(c => ({ label: labelOf(c), key: c.key, icon: c.icon ?? 'grid', off: !!c.off?.(), run: () => runCmd(c.id) }))
      if (rows.length) out.push({ name: MENU_NAMES[k], rows })
    }
    if (s.length > 1) for (const p of providers) { const g = p(s); if (g && g.rows.length) out.push(g) }
    return out
  })
  const rows = $derived(groups.flatMap(g => g.rows))
  // the groups again, each row carrying its index in `rows` (the selection and aria ids use it)
  const view = $derived.by(() => {
    let k = 0
    return groups.map(g => ({ name: g.name, rows: g.rows.map(r => ({ r, k: k++ })) }))
  })

  $effect(() => { q; sel = 0 })
  $effect(() => {
    const b = box?.querySelector<HTMLElement>(`[data-r="${sel}"]`)
    b?.scrollIntoView({ block: 'nearest' })
  })

  function go(k: number) {
    const r = rows[k]
    if (!r) return
    close()
    r.run()             // a disabled command explains itself with a toast
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (rows.length) sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length
    } else if (e.key === 'Enter') { e.preventDefault(); go(sel) }
  }
</script>

<WinBody>
  <div class="pal-q">
    <b aria-hidden="true">&gt;</b>
    <label class="sr" for="pal-in">Type a command</label>
    <input id="pal-in" placeholder="Type a command, an item, a note or a canvas" autocomplete="off" role="combobox"
      aria-expanded="true" aria-controls="pal-list" aria-autocomplete="list" aria-activedescendant={rows.length ? 'pal-o' + sel : undefined}
      bind:value={q} onkeydown={key} data-autofocus />
  </div>
  <div class="pal-list" id="pal-list" role="listbox" aria-label="Commands" bind:this={box}>
    {#if !rows.length}
      <p class="pal-empty">No command matches that.</p>
    {:else}
      {#each view as g (g.name)}
        <p class="pal-g">{g.name}</p>
        {#each g.rows as { r, k } (k)}
          <button type="button" class="pal-i" role="option" id={'pal-o' + k} data-r={k} aria-selected={k === sel}
            aria-disabled={r.off ? 'true' : undefined} onclick={() => go(k)} onpointermove={() => { if (sel !== k) sel = k }}>
            {#if r.img}<img src={r.img} alt="" />{:else}<Px name={r.icon ?? 'grid'} />{/if}<span>{r.label}</span><kbd>{r.key ?? ''}</kbd>
          </button>
        {/each}
      {/each}
    {/if}
  </div>
</WinBody>
