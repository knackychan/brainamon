<script lang="ts">
  // The library with no card at all (spec D3): Wiskit, one line and ONE key, picked by the welcome's answer
  // (onboarding.ts startFor): a site's saves open Scrapers on that site, anything else opens Add.
  import WiskitSprite from '../../components/WiskitSprite.svelte'
  import { startFor } from '../../lib/onboarding'
  import { onb, runStart } from '../../lib/onboarding.svelte'
  import { ui } from '../../lib/ui.svelte'

  const s = $derived(startFor(onb.answer))
</script>

<div class="ob-empty" role="region" aria-labelledby="ob-empty-h">
  <div class="ob-empty-pet"><WiskitSprite pose="point" motionOff={ui.motionOff} /></div>
  <h2 id="ob-empty-h">Your library is empty</h2>
  <p>{s.line}</p>
  <button type="button" class="wkey pri ob-empty-go" onclick={() => runStart()}>{s.key}</button>
</div>

<style>
  .ob-empty { grid-column: 1 / -1; justify-self: center; display: grid; justify-items: center; gap: 10px; max-width: 440px; margin: 48px 16px; text-align: center; color: var(--felt-ink) }
  /* the empty mat keeps its dashes: the ring, centre line and corner marks (LibraryWs .mat-art) would run through
     the text, and the footer's card tips have no card to point at */
  :global(.zone-lib:has(.ob-empty) .ma-ring), :global(.zone-lib:has(.ob-empty) .ma-ln), :global(.zone-lib:has(.ob-empty) .ma-br) { display: none }
  :global(.mat:has(.ob-empty) .mat-ft span:first-child) { visibility: hidden }
  .ob-empty-pet { width: 192px; height: 112px }
  .ob-empty h2 { margin: 4px 0 0; font: 700 22px/1.2 var(--display); letter-spacing: -.01em }
  .ob-empty p { margin: 0; font: 500 12.5px/1.5 var(--mono); text-wrap: pretty }
  .ob-empty-go { height: 34px; margin-top: 6px; padding: 0 16px; font-size: 12px }
</style>
