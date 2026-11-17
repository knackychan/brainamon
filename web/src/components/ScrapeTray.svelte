<script lang="ts">
  import { lib } from '../lib/library.svelte'
  import { motionOn } from '../lib/motion/motion.ts'
  import Count from '../lib/motion/Count.svelte'
  import Bar from '../lib/motion/Bar.svelte'
  import { playRows, playedCount, type Tray } from '../lib/scrape-tray'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  import ScrapeRows from './ui/ScrapeRows.svelte'

  let { tray, onplayed, onshow }: { tray: Tray; onplayed: () => void; onshow: () => void } = $props()
  let shown = $state(0)
  const result = $derived(tray.result)
  const done = $derived(tray.phase === 'done')
  const count = $derived(done ? result?.added ?? 0 : tray.phase === 'play' && result ? playedCount(result, shown) : tray.read ?? 0)
  const rows = $derived(result ? result.ids.slice(0, done ? playRows(result) : shown).slice(-5).reverse() : [])
  const title = $derived(tray.phase === 'ready' ? 'Ready' : tray.phase === 'scan' ? 'Scanning in the browser window'
    : tray.phase === 'wait' ? "Reading the scan's file" : tray.phase === 'play' ? 'Importing into your library'
    : done ? 'Saved posts imported' : tray.ended === 'stopped' ? 'Scan stopped' : 'Scan ended with an error')

  $effect(() => {
    const current = tray
    if (current.phase !== 'play' || !current.result) return
    const r = current.result, k = playRows(r), started = performance.now()
    shown = 0
    let timer: ReturnType<typeof setTimeout>
    function step() {
      if (!motionOn()) shown = k
      else shown += 1
      if (shown >= k) onplayed()
      else timer = setTimeout(step, 100)
    }
    function wait() {
      if (r.ids.slice(0, k).every(id => lib.byId.has(id)) || performance.now() - started >= 1500) {
        if (k) step()
        else onplayed()
      } else timer = setTimeout(wait, 50)
    }
    timer = setTimeout(wait, 0)
    return () => clearTimeout(timer)
  })
</script>

<section class="mo-scrape-tray" class:mo-tray-done={done} data-phase={tray.phase} aria-label="Saved posts import">
  <p class="mo-tray-state" role="status">{#if done}<span class="mo-pop mo-tray-ok" aria-hidden="true">✓</span>{/if}{title}</p>
  {#if tray.phase === 'ready'}
    <Hint>Open the browser to scan your saved posts.</Hint>
  {:else}
    <p class="mo-tray-total"><Count class="mo-tray-count" value={count} jump={tray.phase === 'scan' || tray.phase === 'wait' || tray.phase === 'off' ? 'read' : 'new'} /> <span>{done ? 'new items' : tray.phase === 'play' ? 'new' : 'read'}</span></p>
    <Bar mode={done ? 'ok' : tray.phase === 'scan' || tray.phase === 'wait' ? 'busy' : 'fill'} value={tray.phase === 'play' && result?.added ? count / result.added : 0} label={title} />
    <ScrapeRows ids={rows} />
    {#if tray.phase === 'play' && result}
      <Hint>{count} of {result.added} new · {result.duplicates} already in library</Hint>
    {:else if done && result}
      <Hint>{result.duplicates ? `${result.duplicates} ${result.duplicates === 1 ? 'was' : 'were'} already in your library.` : 'None were already in your library.'}{result.invalid ? ` ${result.invalid === 1 ? '1 row had' : `${result.invalid} rows had`} no link.` : ''}</Hint>
      {#if result.added > 0}<div class="mo-tray-actions"><Button variant="pri" class="mo-nudge" onclick={onshow}>Show in Library</Button></div>{/if}
    {/if}
  {/if}
</section>

<style>
  .mo-scrape-tray { display: grid; gap: 10px; padding: 14px; border: 1px solid var(--rw-dim); border-radius: 8px; background: var(--rw) }
  .mo-tray-state { display: flex; align-items: center; gap: 8px; margin: 0; font: var(--type-mo-tray-state) }
  .mo-tray-total { margin: 0; font: var(--type-mo-tray-total); font-variant-numeric: tabular-nums }
  .mo-tray-total :global(.mo-tray-count) { font: var(--type-mo-tray-count); font-variant-numeric: tabular-nums }
  .mo-tray-done .mo-tray-state, .mo-tray-done .mo-tray-total { color: var(--mo-ok-ink) }
  .mo-tray-ok { display: inline-block }
  .mo-tray-actions { display: flex; justify-content: flex-start }
  :global(.cm-rest .mo-scrape-tray .mo-bar>i) { transition: none }
  :global(.cm-rest .mo-scrape-tray .mo-pop), :global(.cm-rest .mo-scrape-tray .mo-nudge) { animation: none }
</style>
