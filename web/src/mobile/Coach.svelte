<script lang="ts">
  // The phone's one coach mark (spec P4): once, over the + tab (in the thumb's reach), while the Library is
  // empty: posts shared from other apps land in Add. Got it, or opening Add, puts it away for good
  // (kv 'onboard' coach). `hold` keeps it back while the welcome is up.
  import { onb, saveOnb } from './onboard.svelte'
  import { phone } from './state.svelte'

  let { hold = false }: { hold?: boolean } = $props()
  const show = $derived(onb.loaded && !!onb.answer && !onb.coach && !hold && phone.loaded && !phone.rows.length && phone.route.tab === 'lib' && !phone.route.item)
  $effect(() => { if (onb.loaded && onb.answer && !onb.coach && phone.route.tab === 'cap') saveOnb({ coach: true }).catch(() => {}) })
</script>

{#if show}
  <div class="m-coach" role="note">
    <p>Share a post from any app to Brainamon. It lands here, in Add.</p>
    <button type="button" class="m-btn sm" onclick={() => saveOnb({ coach: true }).catch(() => {})}>Got it</button>
  </div>
{/if}

<style>
  .m-coach { position: fixed; z-index: 30; left: 12px; right: 12px; bottom: calc(62px + env(safe-area-inset-bottom, 0px)); display: flex; align-items: center; gap: 10px; padding: 10px 10px 10px 14px; border-radius: 12px; background: var(--ink); color: var(--wg); box-shadow: 0 6px 18px rgba(0, 0, 0, .25) }
  /* the arrow over the + tab: the third of six tabs, centred at 41.67% of the bubble (12px gutters, 6px bar padding) */
  .m-coach::after { content: ''; position: absolute; top: 100%; left: calc(41.667% - 8px); border: 7px solid transparent; border-top-color: var(--ink) }
  .m-coach p { flex: 1; margin: 0; font: 600 12px/1.4 var(--mono) }
  .m-coach .m-btn { flex: none }
  @media (prefers-reduced-motion: no-preference) { .m-coach { animation: m-coach-in .24s ease-out } }
  :global(.motion-off) .m-coach { animation: none }
  @keyframes m-coach-in { from { opacity: 0; transform: translateY(6px) } }
</style>
