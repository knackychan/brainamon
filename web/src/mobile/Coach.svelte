<script lang="ts">
  // The phone's one coach mark (spec P4): once, over the dock's Add key (in the thumb's reach), while the Library is
  // empty: posts shared from other apps land in Add. Got it, or opening Add, puts it away for good
  // (kv 'onboard' coach). `hold` keeps it back while the welcome is up.
  import { onb, saveOnb } from './onboard.svelte'
  import { phone } from './state.svelte'
  import { t } from '../lib/i18n/index.ts'

  let { hold = false }: { hold?: boolean } = $props()
  const show = $derived(onb.loaded && !!onb.answer && !onb.coach && !hold && phone.loaded && !phone.rows.length && phone.route.tab === 'lib' && !phone.route.item && !phone.route.search)
  $effect(() => { if (onb.loaded && onb.answer && !onb.coach && phone.route.tab === 'cap') saveOnb({ coach: true }).catch(() => {}) })
</script>

{#if show}
  <div class="m-coach" role="note">
    <p>{t('onboarding.coach.help')}</p>
    <button type="button" class="m-btn sm" onclick={() => saveOnb({ coach: true }).catch(() => {})}>{t('onboarding.coach.close')}</button>
  </div>
{/if}

<style>
  .m-coach { position: fixed; z-index: 30; left: 12px; right: 12px; bottom: calc(70px + env(safe-area-inset-bottom, 0px)); display: flex; align-items: center; gap: 10px; padding: 10px 10px 10px 14px; border-radius: 12px; background: var(--ink); color: var(--wg); box-shadow: 0 6px 18px rgba(0, 0, 0, .25) }
  /* the arrow over the dock's Add key: the key's centre is 33 px from the screen's right edge (10 px gutter +
     23), so 21 px from the bubble's (12 px gutter); the 14 px arrow starts 14 px from it. The bubble's bottom
     (70 px) clears the dock's top (14 + 46 + 3 px edge) by the arrow's 7 px. */
  .m-coach::after { content: ''; position: absolute; top: 100%; right: 14px; border: 7px solid transparent; border-top-color: var(--ink) }
  .m-coach p { flex: 1; margin: 0; font: 600 12px/1.4 var(--mono) }
  .m-coach .m-btn { flex: none }
  @media (prefers-reduced-motion: no-preference) { .m-coach { animation: m-coach-in .24s ease-out } }
  :global(.motion-off) .m-coach { animation: none }
  @keyframes m-coach-in { from { opacity: 0; transform: translateY(6px) } }
</style>
