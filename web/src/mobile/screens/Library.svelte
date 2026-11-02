<script lang="ts">
  // 01 Library: search (keyword, Smart by meaning), collection chips, the card grid; a search can
  // become a synthesized note (Notes > Synthesize).
  import Grid from '../Grid.svelte'
  import Processing from '../Processing.svelte'
  import GetStarted from '../GetStarted.svelte'
  import Sprite from '../Sprite.svelte'
  import { phoneEmpty } from '../../lib/onboarding'
  import { onb, openPairing } from '../onboard.svelte'
  import { driveLinked, mirrorSource, phone, phoneStatus, refresh, setQuery, setSmart, solo, SORTS, type Sort } from '../state.svelte'
  import { ACCESS_STATES } from '../mirror/phone-state'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'

  let { scroller }: { scroller: HTMLElement | undefined } = $props()
  let text = $state(phone.q)
  const chips = $derived([{ key: 'all', label: 'All', n: phone.rows.length }, ...phone.cats.filter(c => c.count).map(c => ({ key: c.name, label: c.name, n: c.count }))])
  const heading = $derived(phone.q.trim() ? 'Results' : phone.fav ? 'Favourites' : phone.cat === 'all' ? 'All items' : phone.cat)
  let processRows = $state<import('../source/types').Row[] | null>(null)
  // the library with no card at all (spec P3): one line and one key
  const empty = $derived(phoneEmpty(onb.answer, !!mirrorSource && !solo))
  function emptyGo() {
    if (empty.pc) openPairing()
    else location.hash = '#/cap'
  }
  // a refused access check: the status model's sentence, as on the status card and the owner line (mirror/phone-state.ts)
  const status = $derived(phoneStatus())
  const libraryError = $derived(status && ACCESS_STATES.includes(status.id) ? status.text : phone.error)
</script>

<div class="m-lib-search">
  <label class="m-fld"><span class="m-pr">~/library $</span><input type="search" placeholder="search titles, creators, tags" bind:value={text} oninput={() => setQuery(text)} enterkeyhint="search" autocomplete="off" /></label>
  <button type="button" class="m-tg" aria-pressed={phone.smart} onclick={() => setSmart(!phone.smart)} title="Rank by meaning"><i></i>{phone.ranking ? '…' : 'Smart'}</button>
</div>
{#if phone.smart && phone.smartNote && phone.q.trim()}<MHint as="div" class="m-pad-x">{phone.smartNote}</MHint>{/if}
<div class="m-chips" role="tablist" aria-label="Collections">
  <button type="button" class="m-chip" class:on={phone.fav} onclick={() => { phone.fav = !phone.fav }}>★ Favs<small>{phone.favIds.size}</small></button>
  {#each chips as c (c.key)}
    <button type="button" class="m-chip" class:on={!phone.fav && phone.cat === c.key} onclick={() => { phone.cat = c.key; phone.fav = false }}>{c.label}<small>{c.n}</small></button>
  {/each}
</div>
<div class="m-mathd">
  <h3>{heading} <span class="m-jp" aria-hidden="true">ライブラリ</span></h3>
  <span class="m-sp"></span>
  <select class="m-sort" bind:value={phone.sort} aria-label="Sort">{#each SORTS as [k, label] (k)}<option value={k as Sort}>{label}</option>{/each}</select>
  {#if phone.q.trim() && phone.visible.length}<MButton as="a" size="sm" href={`#/synth/${encodeURIComponent(phone.q.trim())}`}>Synthesize</MButton>{/if}
  {#if phone.visible.length}<MButton size="sm" onclick={() => processRows = [...phone.visible]}>Process</MButton>{/if}
  <span class="m-cnt">{phone.visible.length.toLocaleString('en')}</span>
</div>
{#if processRows}<Processing rows={processRows} close={() => processRows = null} />{/if}
{#if phone.loaded}<GetStarted />{/if}
<!-- Google Drive is an add-on: a line of text, never a block in the way of the cards -->
{#if phone.signIn}
  <MHint as="div" class="m-pad-x">Google Drive is not connected, so this is the phone's last copy. Connect it on More > Backup & phones to sync.</MHint>
{:else if solo && phone.loaded && phone.rows.length > 0 && (phone.synced, phone.tokenAt, !driveLinked())}
  <MHint as="div" class="m-pad-x">Saved on this phone. Back up to Google Drive on More > Backup & phones, or pair a PC for thumbnails and AI.</MHint>
{/if}
{#if phone.error && !phone.rows.length && !phone.signIn}
  <div class="m-err">{libraryError}<br /><MButton size="sm" style="margin-top:8px" onclick={() => refresh()}>Try again</MButton></div>
{:else if !phone.loaded && !phone.signIn}
  <div class="m-empty m-load" role="status" aria-live="polite">
    Loading the library…
    <div class="m-load-bar" role="progressbar" aria-label="Loading the library" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(phone.load.frac * 100)}><b style:width={`${phone.load.frac * 100}%`}></b></div>
    <small>{phone.load.text || 'Starting'}</small>
  </div>
{:else if !phone.rows.length && !phone.q.trim()}
  <div class="m-ob-empty">
    <Sprite pose="point" />
    <h3>Your library is empty</h3>
    <p>{empty.line}</p>
    <button type="button" class="m-btn dk m-ob-empty-go" onclick={emptyGo}>{empty.key}</button>
  </div>
{:else if !phone.visible.length}
  <div class="m-empty">{phone.q.trim() ? 'Nothing matches.' : 'No cards here yet.'}</div>
{:else}
  <Grid rows={phone.visible} {scroller} />
{/if}

<style>
  .m-ob-empty { display: grid; justify-items: center; gap: 8px; padding: 36px 24px 24px; text-align: center }
  .m-ob-empty :global(.m-sprite) { width: 144px; height: 84px }
  .m-ob-empty h3 { margin: 6px 0 0; font: 800 20px/1.2 var(--display); font-stretch: 85% }
  .m-ob-empty p { margin: 0; max-width: 30ch; font: 500 12px/1.5 var(--mono); color: var(--felt-muted) }
  .m-ob-empty-go { min-height: 44px; margin-top: 8px; padding: 0 18px }
</style>
