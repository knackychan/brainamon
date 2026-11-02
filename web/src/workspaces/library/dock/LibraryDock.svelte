<script lang="ts">
  // The Library rail (V6 buildLibDock order). Arrow keys move between the rows of one tile (V6
  // e-libui.js roving tabindex); leaving a tile hands its tab stop back to the checked row.
  import ClockTile from './ClockTile.svelte'
  import CollectionsTile from './CollectionsTile.svelte'
  import CreatorTile from './CreatorTile.svelte'
  import HoloTile from './HoloTile.svelte'
  import SavesTile from './SavesTile.svelte'
  import SortTile from './SortTile.svelte'
  import SourceTile from './SourceTile.svelte'
  import StatusTile from './StatusTile.svelte'
  import SystemTile from './SystemTile.svelte'
  import TagsTile from './TagsTile.svelte'
  import TypeTile from './TypeTile.svelte'
  import ViewTile from './ViewTile.svelte'
  import ViewingTile from './ViewingTile.svelte'
  import ZoomTile from './ZoomTile.svelte'

  function onKey(e: KeyboardEvent) {
    const r = (e.target as HTMLElement).closest<HTMLElement>('.tr'), box = r?.closest<HTMLElement>('[data-rove]')
    if (!r || !box) return
    const rows = [...box.querySelectorAll<HTMLElement>('.tr')].filter(x => !x.hidden && x.getAttribute('aria-disabled') !== 'true')
    const i = rows.indexOf(r)
    const go = ({ ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: rows.length - 1 } as Record<string, number>)[e.key]
    if (go === undefined) return
    e.preventDefault()
    const n = rows[(go + rows.length) % rows.length]
    box.querySelectorAll<HTMLElement>('.tr').forEach(x => (x.tabIndex = x === n ? 0 : -1))
    n.focus()
  }
  // the tiles must be direct children of .dock (.dock>.s6 spans), so listen on the dock itself
  $effect(() => {
    const dock = document.getElementById('mods')
    dock?.addEventListener('keydown', onKey)
    return () => dock?.removeEventListener('keydown', onKey)
  })
</script>

<ClockTile />
<HoloTile />
<!-- Status (the one tile with work to do) above Collections: audit 2026-10-15 #10 -->
<StatusTile />
<CollectionsTile />
<CreatorTile />
<TagsTile />
<TypeTile />
<SourceTile />
<SortTile />
<ViewTile />
<ZoomTile />
<SystemTile />
<ViewingTile />
<SavesTile />
