<script lang="ts">
  // The section pages' top bar (projects/phone-dock-shell, mockups/layout-v3.html): the settings key (More), the
  // Library and Canvas pills, the sync key, and the search circle that widens over the whole bar into the
  // Library's search field (#/search). The field is in the page all the time, folded inside the circle, so the
  // tap that opens search can focus it: that is what makes Android open the keyboard.
  import { untrack } from 'svelte'
  import { t } from '../lib/i18n/index.ts'
  import { phone, setQuery, setSmart } from './state.svelte'
  import { back, go, shell } from './shell.svelte'
  import MKey from './ui/MKey.svelte'
  import ShellIcon from './ShellIcon.svelte'
  import SyncKey from './SyncKey.svelte'

  let { label, amber, pull }: { label: string; amber: boolean; pull: number } = $props()
  const r = $derived(phone.route)
  const searching = $derived(!!r.search)
  let text = $state(phone.q)
  let field: HTMLInputElement | undefined = $state()

  function openSearch() {
    field?.focus({ preventScroll: true })
    go('#/search')
  }
  function closeSearch() {
    if (history.length > 1) back()
    else go('#/lib', true)
  }
  // search shows the whole Library: the collection filter waits in shell.keep while it is open; leaving search
  // clears the query
  $effect(() => {
    if (searching) untrack(() => {
      if (!shell.keep) { shell.keep = { cat: phone.cat, fav: phone.fav }; phone.cat = 'all'; phone.fav = false }
    })
    else untrack(() => {
      if (shell.keep) { phone.cat = shell.keep.cat; phone.fav = shell.keep.fav; shell.keep = null }
      if (phone.q) { text = ''; setQuery('') }
      field?.blur()
    })
  })
</script>

<header class="m-top" class:searching>
  <MKey as="a" href="#/more" aria-label={t('shell.settings')} title={t('shell.settings')}><img src="/brand/icon.svg" alt="" width="22" height="22" /></MKey>
  <MKey as="a" href="#/lib" tone={r.tab === 'lib' ? 'dark' : 'plain'} wide={r.tab === 'lib'} aria-label={t('shell.route.library')} title={t('shell.route.library')} aria-current={r.tab === 'lib' ? 'page' : undefined}><ShellIcon name="lib" on={r.tab === 'lib'} />{#if r.tab === 'lib'}<span>{t('shell.route.library')}</span>{/if}</MKey>
  <MKey as="a" href="#/canvas" tone={r.tab === 'cv' ? 'dark' : 'plain'} wide={r.tab === 'cv'} aria-label={t('shell.route.canvas')} title={t('shell.route.canvas')} aria-current={r.tab === 'cv' ? 'page' : undefined}><ShellIcon name="cv" on={r.tab === 'cv'} />{#if r.tab === 'cv'}<span>{t('shell.route.canvas')}</span>{/if}</MKey>
  <SyncKey {label} {amber} {pull} />
  <span class="m-top-slot" aria-hidden="true"></span>
  <div class="m-find" class:open={searching}>
    <button type="button" class="m-find-key" aria-label={t('common.search')} title={t('common.search')} onclick={() => (searching ? field?.focus() : openSearch())}><ShellIcon name="search" /></button>
    <input bind:this={field} bind:value={text} class="m-find-in" type="search" placeholder={t('shell.search.placeholder')} aria-label={t('shell.search.label')}
      tabindex={searching ? 0 : -1} oninput={() => setQuery(text)} onkeydown={e => { if (e.key === 'Escape') closeSearch(); else if (e.key === 'Enter') field?.blur() }}
      enterkeyhint="search" autocomplete="off" />
    {#if searching}
      <button type="button" class="m-tg" aria-pressed={phone.smart} onclick={() => setSmart(!phone.smart)} title={t('shell.search.rank')}><i></i>{phone.ranking ? '…' : t('shell.search.smart')}</button>
      <button type="button" class="m-find-x" aria-label={t('shell.search.close')} onclick={closeSearch}>✕</button>
    {/if}
  </div>
</header>
