<script lang="ts">
  // The top of Settings, Backup & phones and Recover a library (projects/phone-settings, spec section 1): the round
  // Back, the dark tag, and on Backup and Recover the page's (i) in a round key at the top right. The keys use the
  // Wiskit sheet's band (.m-sheet-keys in mobile.css, fixed here: settings.css) and stay put while the page scrolls.
  // Back goes one page back when the page behind belongs to this app session, else to the parent (back.ts pageBack).
  // Each page renders its keys before its .m-pad, so the page's own checks never count them.
  import type { Snippet } from 'svelte'
  import { t } from '../lib/i18n/index.ts'
  import { phone } from './state.svelte'
  import { pageBack } from './back'
  import { back, go, inAppBehind } from './shell.svelte'
  import MKey from './ui/MKey.svelte'
  import MInfo from './ui/MInfo.svelte'
  import ShellIcon from './ShellIcon.svelte'
  import './settings.css'

  let { infoTitle = '', info }: { infoTitle?: string; info?: Snippet } = $props()
  const r = $derived(phone.route)
  const tag = $derived(r.backup ? t('shell.pageTag.backup') : r.recover ? t('shell.pageTag.recover') : t('shell.settings'))
  function leave() { const to = pageBack(r, inAppBehind()); if (to) go(to, true); else back() }
</script>

<div class="m-sheet-keys m-page-keys">
  <MKey aria-label={t('common.back')} title={t('common.back')} onclick={leave}><ShellIcon name="back" /></MKey>
  <span class="m-ws">{tag}</span>
  <span class="m-sp"></span>
  {#if info}<MInfo class="m-key m-page-info" title={infoTitle}>{@render info()}</MInfo>{/if}
</div>
