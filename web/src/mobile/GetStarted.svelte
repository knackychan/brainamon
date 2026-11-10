<script lang="ts">
  // The phone's Get started (spec P2), top of the Library while the welcome has an answer and Hide was not
  // tapped: three tasks, the first always ticked; a todo row opens Add or the More box that does it.
  import { phoneTasks, progressOf, type Task } from '../lib/onboarding'
  import { t, type Key } from '../lib/i18n/index.ts'
  import { onb, openMoreBox, openPairing, saveOnb } from './onboard.svelte'
  import { mirrorSource, phone, solo } from './state.svelte'
  import MButton from './ui/MButton.svelte'

  const tasks = $derived.by(() => {
    void phone.synced; void phone.tokenAt; void phone.route     // keys saved in More, a pairing, a sync: read again
    return phoneTasks(onb.answer, { pc: mirrorSource ? !solo : phone.reachable, items: phone.rows.length, ai: !!mirrorSource?.ai() }, key => t(key as Key))
  })
  const p = $derived(progressOf(tasks))
  function start(t: Task) {
    if (t.id === 'saves') location.hash = '#/cap'
    else if (t.id === 'pc') openPairing()
    else if (t.id === 'wiskit') openMoreBox('m-ai')
  }
</script>

{#if onb.loaded && onb.answer && !onb.hidden}
  <div class="m-box m-gs" role="region" aria-labelledby="m-gs-h">
    <h3 id="m-gs-h">{t('onboarding.task.title')}<span class="m-sp"></span><span class="m-lbl" role="status">{p.all ? t('onboarding.task.done') : t('onboarding.task.count', { done: p.done, total: p.total })}</span><MButton size="sm" onclick={() => saveOnb({ hidden: true }).catch(() => {})}>{t('onboarding.task.hide')}</MButton></h3>
    <div class="m-gs-bar" aria-hidden="true">{#each tasks as t (t.id)}<i class:on={t.done}></i>{/each}</div>
    <div class="m-gs-list">
      {#each tasks as task (task.id)}
        {#if task.done}
          <div class="m-gs-row done"><i class="m-gs-dot on" aria-hidden="true"><svg viewBox="0 0 12 12"><path d="M2.5 6.5 5 9l4.5-5.5" /></svg></i><span>{task.label}</span><span class="sr">{t('onboarding.task.doneSuffix')}</span></div>
        {:else}
          <button type="button" class="m-gs-row" onclick={() => start(task)}><i class="m-gs-dot" aria-hidden="true"></i><span>{task.label}</span><b aria-hidden="true">›</b></button>
        {/if}
      {/each}
    </div>
    {#if p.all}<span class="m-hint">{t('onboarding.task.ready')}</span>{/if}
  </div>
{/if}

<style>
  .m-gs { margin: 0 14px 12px; gap: 8px }
  .m-gs-bar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px }
  .m-gs-bar i { height: 6px; border-radius: 2px; background: var(--seg-off) }
  .m-gs-bar i.on { background: var(--m-ok) }
  .m-gs-list { display: grid }
  .m-gs-row { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 44px; padding: 6px 2px; border: 0; border-top: 1px solid var(--wg-line); background: none; color: var(--wg-ink); font: 600 13px/1.25 var(--mono); text-align: left }
  .m-gs-row span { flex: 1; min-width: 0 }
  .m-gs-row.done { color: var(--wg-dim); font-weight: 500 }
  .m-gs-row b { color: var(--accent); font: 700 18px/1 var(--mono) }
  .m-gs-dot { flex: none; display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; border: 2px solid var(--wg-edge) }
  .m-gs-dot.on { border-color: var(--m-ok); background: var(--m-ok); color: #fff }
  .m-gs-dot svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 2.2 }
</style>
