<script lang="ts">
  // The command deck (V6 .deck): the terminal search with the SMART switch, and ADD / IMPORT / SCRAPE.
  // Typing searches after 150 ms (the app's debounce); Enter with SMART on re-ranks by meaning.
  import Px from '../../lib/Px.svelte'
  import { runCmd } from '../../lib/commands'
  import { clearFilters, lib, setQuery, setSmart, smartRank } from '../../lib/library.svelte'

  let input: HTMLInputElement | undefined = $state()
  const pad3 = (n: number) => String(n).padStart(3, '0')
  const n = $derived(lib.visible.length)
  const tot = $derived(lib.rows.length)

  function onKey(e: KeyboardEvent) {
    if (!input) return
    if (e.key === 'Enter') {
      e.preventDefault()
      setQuery(input.value, true)
      if (lib.smart && input.value.trim()) smartRank()
    } else if (e.key === 'Escape' && input.value) {
      e.preventDefault(); e.stopPropagation()
      clearFilters('q')
    }
  }
  function toggleSmart() { setSmart(!lib.smart); input?.focus() }
</script>

<div class="deck">
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="dq" class:ranking={lib.ranking} id="dq" onclick={e => { if (!(e.target as HTMLElement).closest('button')) input?.focus() }}>
    <span class="ps" aria-hidden="true">~/library <b>$</b></span>
    <label class="sr" for="q">Search the library</label>
    <input id="q" type="search" bind:this={input} autocomplete="off" spellcheck="false" enterkeyhint="search"
      placeholder={lib.smart ? 'search by meaning, press Enter to re-rank' : 'search titles, creators, tags'}
      oninput={() => setQuery(input!.value)} onkeydown={onKey} />
    <span class="cnt" class:all={n === tot} aria-live="polite"><b id="q-n">{pad3(n)}</b> / <span id="q-t">{pad3(tot)}</span></span>
    <button class="dq-x" type="button" id="q-x" aria-label="Clear the search" hidden={!lib.q} onclick={() => { clearFilters('q'); input?.focus() }}><Px name="clear" /></button>
    <button class="smart" type="button" id="smart" aria-pressed={lib.smart} title="Smart search: Enter re-ranks the results by meaning" onclick={toggleSmart}><Px name="core" />Smart<i aria-hidden="true"></i></button>
    <span class="dq-scan" aria-hidden="true"></span>
  </div>
  <div class="keys">
    <button class="mk pri" type="button" onclick={() => runCmd('add')}><Px name="plus" /><b>ADD</b><small>new item</small></button>
    <button class="mk" type="button" onclick={() => runCmd('import')}><Px name="up" /><b>IMPORT</b><small>CSV · JSON</small></button>
    <button class="mk" type="button" onclick={() => runCmd('scrape')}><Px name="magnet" /><b>SCRAPE</b><small>FB · IG · YT · RD</small></button>
  </div>
</div>
