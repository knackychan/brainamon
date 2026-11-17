<script lang="ts">
  import { flip } from 'svelte/animate'
  import { cubicOut } from 'svelte/easing'
  import { lib, thumbSrc } from '../../lib/library.svelte'
  import { arrive } from '../../lib/motion/arrive.ts'
  import { ARRIVE_MS, motionOn } from '../../lib/motion/motion.ts'

  let { ids }: { ids: number[] } = $props()
</script>

<div class="mo-tray-list">
  <ul class="ilist" aria-label="Imported saved posts">
    {#each ids as id (id)}
      {@const row = lib.byId.get(id)}
      <li class="mo-tray-row" data-id={id} in:arrive={{ x: -28 }} animate:flip={{ duration: motionOn() ? ARRIVE_MS : 0, easing: cubicOut }}>
        <div class="mo-tray-item">
          <span class="mo-tray-picture">{#if row?.thumb}<img src={thumbSrc(id, 64)} alt="" />{/if}</span>
          <span class="mo-tray-text"><strong>{row?.title || `Item ${id}`}</strong><small>{row?.creator || `id ${id}`}</small></span>
        </div>
        <span class="acts"><span class="mo-pop mo-tray-tick" aria-label="Imported" style:animation-delay=".14s">✓</span></span>
      </li>
    {/each}
  </ul>
</div>

<style>
  .mo-tray-list { height: 176px; overflow: hidden }
  .mo-tray-row { height: 44px; min-height: 44px; box-sizing: border-box; padding: 0; flex-wrap: nowrap }
  .mo-tray-item { display: flex; align-items: center; gap: 9px; overflow: hidden }
  .mo-tray-picture { display: block; width: 32px; height: 32px; flex: none; overflow: hidden; border-radius: 4px; background: var(--rw-2) }
  .mo-tray-picture img { width: 100%; height: 100%; object-fit: cover }
  .mo-tray-text { display: grid; min-width: 0 }
  .mo-tray-text strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: var(--type-mo-tray-title) }
  .mo-tray-text small { color: var(--rw-dim); font: var(--type-mo-tray-detail) }
  .mo-tray-tick { display: inline-block; color: var(--mo-ok-ink); font: var(--type-mo-tray-tick) }
  :global(.motion-off) .mo-tray-row, :global(.cm-rest) .mo-tray-row { transform: none !important; opacity: 1 !important }
  :global(.cm-rest) .mo-tray-tick { animation: none }
  @media (prefers-reduced-motion: reduce) { .mo-tray-row { transform: none !important; opacity: 1 !important } }
</style>
