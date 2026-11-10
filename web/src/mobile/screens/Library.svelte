<script lang="ts">
  // 01 Library: collection chips and the card grid; in search (#/search, the top bar's field in TopBar.svelte:
  // keyword, Smart by meaning) the chips and Get started step aside, and a search can become a synthesized
  // note (Notes > Synthesize). Under the chips one toolbar (plans/06-library-toolbar.md): the title, three round
  // keys (Sort, the view switch, Tools) and one summary line (count, order, backup status).
  import Grid from '../Grid.svelte'
  import Processing from '../Processing.svelte'
  import ToolsRing from '../ToolsRing.svelte'
  import { hasRun } from '../tools-run.svelte'
  import GetStarted from '../GetStarted.svelte'
  import Sprite from '../Sprite.svelte'
  import { phoneEmpty } from '../../lib/onboarding'
  import { t, type Key } from '../../lib/i18n/index.ts'
  import { fmtNum } from '../../lib/i18n/format.ts'
  import { onb, openPairing } from '../onboard.svelte'
  import { driveLinked, mirrorSource, phone, phoneStatus, refresh, solo, sorts, type Sort } from '../state.svelte'
  import { ACCESS_STATES } from '../mirror/phone-state'
  import MButton from '../ui/MButton.svelte'
  import MInfo from '../ui/MInfo.svelte'
  import MKey from '../ui/MKey.svelte'
  import ShellIcon from '../ShellIcon.svelte'

  let { scroller }: { scroller: HTMLElement | undefined } = $props()
  const chips = $derived([{ key: 'all', label: t('library.all'), n: phone.rows.length }, ...phone.cats.filter(c => c.count).map(c => ({ key: c.name, label: c.name, n: c.count }))])
  const heading = $derived(phone.q.trim() ? t('library.heading.results') : phone.fav ? t('library.heading.favourites') : phone.cat === 'all' ? t('library.heading.all') : phone.cat)
  let processRows = $state<import('../source/types').Row[] | null>(null)
  let toolsKey: HTMLButtonElement | HTMLAnchorElement | HTMLLabelElement | undefined = $state()
  // the view key shows the layout it switches to; Grid is three columns (a pinch still picks 2, 3 or 4)
  const rowsView = $derived(phone.gallery === 'rows')
  // the summary line: how many cards, in which order, and whether the library lives only on this phone
  const ORDER: Record<Sort, Key> = { new: 'library.order.new', old: 'library.order.old', az: 'library.order.az', za: 'library.order.za' }
  const counted = $derived(phone.loaded && phone.rows.length > 0)
  const n = $derived(phone.visible.length)
  const order = $derived(phone.rank && phone.q.trim() ? t('library.order.meaning') : t(ORDER[phone.sort]))
  // Google Drive is an add-on: words on the summary line, never a block in the way of the cards
  const phoneOnly = $derived(solo && counted && !phone.signIn && (phone.synced, phone.tokenAt, !driveLinked()))
  function tools() { processRows = processRows ? null : [...phone.visible] }
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

{#if !phone.route.search}
<div class="m-chips" role="tablist" aria-label={t('library.collections')}>
  <button type="button" class="m-chip" class:on={phone.fav} onclick={() => { phone.fav = !phone.fav }}>{t('library.favs')}<small>{phone.favIds.size}</small></button>
  {#each chips as c (c.key)}
    <button type="button" class="m-chip" class:on={!phone.fav && phone.cat === c.key} onclick={() => { phone.cat = c.key; phone.fav = false }}>{c.label}<small>{c.n}</small></button>
  {/each}
</div>
{/if}
<div class="m-mathd">
  <h3>{heading}</h3>
  <span class="m-sp"></span>
  {#if phone.q.trim() && phone.visible.length}<MButton as="a" size="sm" href={`#/synth/${encodeURIComponent(phone.q.trim())}`}>{t('library.synthesize')}</MButton>{/if}
  <div class="m-lib-keys">
    {#if phoneOnly}<MInfo class="m-key m-lib-phone" title={t('library.phoneOnly.title')}>{#snippet icon()}<ShellIcon name="phone" /><span class="m-phone-badge"><ShellIcon name="check" /></span>{/snippet}<p>{t('library.phoneOnly.body')}</p></MInfo>{/if}
    <MKey as="label" class="m-lib-sort" title={t('library.sort.title')}><ShellIcon name="sort" /><select bind:value={phone.sort} aria-label={t('library.sort.title')}>{#each sorts() as [k, label] (k)}<option value={k as Sort}>{label}</option>{/each}</select></MKey>
    <MKey class="m-lib-view" aria-label={rowsView ? t('library.view.grid') : t('library.view.rows')} title={rowsView ? t('library.view.grid') : t('library.view.rows')} onclick={() => phone.gallery = rowsView ? '3' : 'rows'}><ShellIcon name={rowsView ? 'lib' : 'rows'} /></MKey>
    {#if phone.visible.length || processRows || hasRun()}<MKey bind:ref={toolsKey} class="m-lib-tools" aria-label={t('common.tools')} title={t('common.tools')} aria-haspopup="dialog" aria-describedby="m-tools-status" aria-expanded={!!processRows} tone={processRows ? 'dark' : 'plain'} onclick={tools}><ShellIcon name="tools" /><ToolsRing open={!!processRows} /></MKey><ToolsRing open={!!processRows} status />{/if}
  </div>
</div>
{#if counted || phone.signIn}
<!-- the status words and their (i) never break apart: with large phone text they move down together -->
<div class="m-lib-sum">
  {#if counted}{t('library.summary', { n, count: fmtNum(n, 'en'), order })}{' '}{/if}{#if phone.signIn}<span class="m-lib-tail">{counted ? '· ' : ''}{t('library.driveOff')}<MInfo title={t('library.driveSync.title')}><p>{t('library.driveSync.body')}</p></MInfo></span>{/if}
</div>
{/if}
{#if phone.smart && phone.smartNote && phone.q.trim()}<div class="m-lib-sum" role="status">{phone.smartNote}</div>{/if}
{#if processRows}<Processing rows={processRows} anchor={toolsKey} {heading} close={() => processRows = null} />{/if}
{#if phone.loaded && !phone.route.search}<GetStarted />{/if}
{#if phone.error && !phone.rows.length && !phone.signIn}
  <div class="m-err">{libraryError}<br /><MButton size="sm" style="margin-top:8px" onclick={() => refresh()}>{t('common.tryAgain')}</MButton></div>
{:else if !phone.loaded && !phone.signIn}
  <div class="m-empty m-load" role="status" aria-live="polite">
    {t('library.loading')}
    <div class="m-load-bar" role="progressbar" aria-label={t('library.loadingLabel')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(phone.load.frac * 100)}><b style:width={`${phone.load.frac * 100}%`}></b></div>
    <small>{phone.load.text || t('library.starting')}</small>
  </div>
{:else if !phone.rows.length && !phone.q.trim()}
  <div class="m-ob-empty">
    <Sprite pose="point" />
    <h3>{t('library.empty.title')}</h3>
    <!-- phoneEmpty() (lib/onboarding.ts, shared and pinned in English) decides which of the two; the phone reads catalog words -->
    <p>{empty.pc ? t('library.empty.connectLine') : t('library.empty.shareLine')}</p>
    <button type="button" class="m-btn dk m-ob-empty-go" onclick={emptyGo}>{empty.pc ? t('library.empty.connectKey') : t('library.empty.addKey')}</button>
  </div>
{:else if !phone.visible.length}
  <div class="m-empty">{phone.q.trim() ? t('library.noMatch') : t('library.noCards')}</div>
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
