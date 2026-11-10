<script lang="ts">
  // The phone's first start (spec P1): one question over the app while the phone is not paired to a PC,
  // the library is empty and nothing was answered (Mobile.svelte decides). Skip, top right, answers 'skip';
  // 'pc' opens More at the pairing rows (scan the PC's code); 'phone' closes: the phone's own library
  // already runs.
  import { onMount } from 'svelte'
  import Wordmark from '../components/Wordmark.svelte'
  import Sprite from './Sprite.svelte'
  import { openPairing, saveOnb } from './onboard.svelte'
  import { DOWNLOAD_URL } from '../lib/product-links'
  import { t } from '../lib/i18n/index.ts'
  import MButton from './ui/MButton.svelte'
  import MInfo from './ui/MInfo.svelte'

  let box: HTMLDivElement | undefined = $state()
  onMount(() => box?.focus())         // a screen reader starts on the question, not on the page behind
  function answer(a: 'pc' | 'phone' | 'skip') {
    saveOnb({ answer: a }).catch(() => {})
    if (a === 'pc') openPairing()
  }
</script>

<div class="m-ob" role="dialog" aria-modal="true" aria-labelledby="m-ob-q" tabindex="-1" bind:this={box}>
  <div class="m-ob-top"><span class="m-ob-wm"><Wordmark label="Brainamon" /></span><span class="m-sp"></span><MButton size="sm" onclick={() => answer('skip')}>{t('onboarding.answer.skip')}</MButton></div>
  <div class="m-ob-mid"><Sprite pose="hover" /></div>
  <div class="m-ob-low">
    <h2 id="m-ob-q">{t('onboarding.answer.question')}</h2>
    <MInfo title={t('onboarding.answer.helpTitle')} label={t('onboarding.answer.helpLabel')}><p>{t('onboarding.answer.help')}</p></MInfo>
    <button type="button" class="m-ob-opt dk" onclick={() => answer('pc')}><b>{t('onboarding.answer.pc')}</b><small>{t('onboarding.answer.pcHelp')}</small></button>
    <button type="button" class="m-ob-opt" onclick={() => answer('phone')}><b>{t('onboarding.answer.phone')}</b><small>{t('onboarding.answer.phoneHelp')}</small></button>
    <MButton as="a" href={DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">{t('onboarding.answer.desktop')}</MButton>
  </div>
</div>

<style>
  .m-ob { position: fixed; inset: 0; z-index: 60; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; padding: calc(12px + env(safe-area-inset-top, 0px)) 16px calc(20px + env(safe-area-inset-bottom, 0px)); background: var(--case); color: var(--case-ink); outline: none }
  .m-ob-top { display: flex; align-items: center; gap: 8px }
  .m-ob-wm { display: inline-flex; font-size: 20px }
  .m-ob-mid { display: grid; place-items: center }
  .m-ob-mid :global(.m-sprite) { width: 192px; height: 112px }
  .m-ob-low { display: grid; gap: 10px }
  .m-ob-low h2 { margin: 0; font: 800 26px/1.15 var(--display); font-stretch: 85%; letter-spacing: -.01em; text-wrap: balance }
  .m-ob-low p { margin: 0 0 6px; font: var(--type-steps) }
  .m-ob-opt { display: grid; gap: 4px; justify-items: start; width: 100%; min-height: 64px; padding: 12px 16px; border: 1px solid var(--wg-edge); border-radius: 12px; background: var(--wg); color: var(--wg-ink); box-shadow: 0 2px 0 var(--wg-edge); font: inherit; text-align: left }
  .m-ob-opt b { font: 800 16px/1.2 var(--display); font-stretch: 85% }
  .m-ob-opt small { font: var(--type-option); opacity: .78 }
  .m-ob-opt.dk { background: var(--ink); border-color: var(--ink); color: var(--wg) }
  .m-ob-opt:active { transform: translateY(1px); box-shadow: none }
</style>
