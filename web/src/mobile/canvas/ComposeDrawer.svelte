<script lang="ts">
  import { t } from '../../lib/i18n/index.ts'
  import { onMount, tick, untrack } from 'svelte'
  import { phone, refresh } from '../state.svelte'
  import type { Composer } from './compose.svelte'
  import { COLOURS, filtered, identity, LIMIT, snap, type Stop } from './compose'
  import { strip } from '../ai/quick'
  import MKey from '../ui/MKey.svelte'
  import MButton from '../ui/MButton.svelte'
  import MToggle from '../ui/MToggle.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import ShellIcon from '../ShellIcon.svelte'
  let { c, heights, stop = $bindable('half'), height = $bindable(0), bottom = 0, onadd }: {
    c: Composer; heights: Record<Stop, number>; stop?: Stop; height?: number; bottom?: number; onadd: () => void
  } = $props()
  let grid: HTMLDivElement | undefined = $state(), textarea: HTMLTextAreaElement | undefined = $state()
  let windowSize = $state(120), dragging = $state(false)
  let drag: { id: number; y: number; h: number; prior: Stop; moved: boolean; ly: number; lt: number; v: number; grip: boolean } | null = null
  let focusTimer: ReturnType<typeof setTimeout> | undefined
  const rows = $derived(filtered(phone.rows, c.q, c.cat, c.fav, c.ids, c.rank))
  const logical = $derived(c.noteMode ? ['closed', 'note'] as Stop[] : ['closed', 'half', 'full'] as Stop[])
  const still = () => phone.motionOff || matchMedia('(prefers-reduced-motion: reduce)').matches
  $effect(() => { const q = c.q, smart = c.smart; return untrack(() => { void q; void smart; return c.search() }) })
  $effect(() => { void c.q; void c.cat; void c.fav; untrack(() => { windowSize = 120; if (grid) grid.scrollTop = 0 }) })
  $effect(() => { const h = heights[stop]; if (!dragging) height = h })
  onMount(() => () => clearTimeout(focusTimer))
  function selectStop(next: Stop) { if (c.locked) return; stop = next; height = heights[next] }
  function toggle() { selectStop(stop === 'closed' ? c.noteMode ? 'note' : 'half' : 'closed') }
  function begin(e: PointerEvent, grip = false) {
    if (c.locked || !grip && (e.target as HTMLElement).closest('input,button,textarea,a')) return
    drag = { id: e.pointerId, y: e.clientY, h: height, prior: stop, moved: false, ly: e.clientY, lt: performance.now(), v: 0, grip }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); dragging = true
  }
  function move(e: PointerEvent) {
    if (!drag || drag.id !== e.pointerId) return
    if (Math.abs(e.clientY - drag.y) > 4) drag.moved = true
    if (drag.moved) height = Math.min(Math.max(...logical.map(s => heights[s])), Math.max(heights.closed, drag.h - (e.clientY - drag.y)))
    const now = performance.now(); drag.v = (e.clientY - drag.ly) / Math.max(1, now - drag.lt); drag.ly = e.clientY; drag.lt = now
  }
  function end(e: PointerEvent) {
    if (!drag || drag.id !== e.pointerId) return
    const d = drag; drag = null; dragging = false
    if (e.type !== 'pointerup') { selectStop(d.prior); return }
    if (!d.moved) { if (d.grip) toggle(); else selectStop(d.prior); return }
    const value = snap(height, performance.now() - d.lt > 100 ? 0 : d.v, logical.map(s => heights[s]), heights[d.prior])
    selectStop(logical.find(s => heights[s] === value)!)
  }
  async function noteMode() {
    if (c.locked) return
    if (!c.noteMode && !strip(c.note) && c.picks.length === 60) { c.tell(t('canvas.composer.limit')); return }
    c.noteMode = !c.noteMode; selectStop(c.noteMode ? 'note' : 'half')
    clearTimeout(focusTimer)
    if (c.noteMode) { await tick(); focusTimer = setTimeout(() => { if (c.noteMode && stop === 'note') textarea?.focus() }, still() ? 0 : 300) }
  }
  function text(value: string) {
    if (c.locked) return
    if (c.picks.length === 60 && strip(value)) { c.tell(t('canvas.composer.limit')); if (textarea) textarea.value = c.note; return }
    c.note = value; c.edited()
  }
</script>

<section class="m-cp-drawer" class:m-cp-drag={dragging} style:height="{height}px" style:bottom="{bottom}px" aria-label={t('canvas.composer.picks')}>
  <button type="button" class="m-cp-grip" aria-label={t('canvas.composer.resize')} aria-expanded={stop !== 'closed'} disabled={c.locked}
    onpointerdown={e => begin(e, true)} onpointermove={move} onpointerup={end} onpointercancel={end} onlostpointercapture={end}
    onclick={e => { if (e.detail === 0) toggle() }} onkeydown={e => {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); const values = logical.filter((s, i, a) => a.findIndex(v => heights[v] === heights[s]) === i); const at = values.findIndex(s => heights[s] === height); selectStop(values[Math.max(0, Math.min(values.length - 1, at + (e.key === 'ArrowUp' ? 1 : -1)))]) }
    }}><i></i></button>
  <div class="m-cp-bar" role="group" aria-label={t('canvas.composer.controls')} onpointerdown={e => begin(e)} onpointermove={move} onpointerup={end} onpointercancel={end} onlostpointercapture={end}>
    <div class="m-cp-search"><ShellIcon name="search" />
      <input type="search" placeholder={t('common.search')} aria-label={t('canvas.composer.search')} value={c.q} disabled={c.locked} oninput={e => { c.q = e.currentTarget.value; c.edited() }} onfocus={() => { c.noteMode = false; selectStop('full') }} onkeydown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
      {#if c.q}<button type="button" class="m-cp-clear" aria-label={t('canvas.composer.clearSearch')} disabled={c.locked} onclick={() => { c.q = ''; c.edited() }}>✕</button>{/if}
      {#if c.q.trim()}<MToggle label={t('canvas.composer.smart')} on={c.smart} disabled={c.locked} onchange={on => { c.smart = on }}><span>{c.ranking ? '…' : t('canvas.composer.smart')}</span></MToggle>{/if}
    </div>
    <MKey aria-label={t('canvas.composer.write')} aria-pressed={c.noteMode} tone={c.noteMode ? 'dark' : 'plain'} disabled={c.locked} onclick={noteMode}><ShellIcon name="notes" /></MKey>
    <MButton class="m-cp-add" variant="pri" disabled={!c.canAdd} onclick={onadd}>{c.busy ? t('canvas.composer.adding') : t('common.add')}{#if c.n && !c.busy}<small>{c.n}</small>{/if}</MButton>
  </div>
  {#if c.error || c.invalid || c.problem || c.unavailable}<div class="m-cp-error" role="alert">{#if c.error || c.invalid || c.problem}<div>{c.errorLabel || c.error || c.invalid || c.problem}</div>{/if}{#if c.unavailable}<div>{t('canvas.composer.unavailable', { n: c.unavailable })}</div>{/if}</div>{/if}
  {#if c.noteMode}
    <div class="m-cp-note-pane"><textarea rows="3" bind:this={textarea} aria-label={t('notes.editor.body')} placeholder={t('canvas.composer.write')} value={c.note} disabled={c.locked} oninput={e => text(e.currentTarget.value)}></textarea>
      <div class="m-cp-swatches" role="group" aria-label={t('canvas.composer.colour')}>{#each COLOURS as color, i}<button type="button" style:background={color} aria-label={t('canvas.composer.colourNumber', { n: i + 1 })} aria-pressed={c.color === color} disabled={c.locked} onclick={() => { c.color = color; c.edited() }}></button>{/each}</div>
    </div>
  {:else}
    <div class="m-cp-chips" role="group" aria-label={t('canvas.composer.collections')}>
      <button type="button" aria-pressed={c.fav} disabled={c.locked} onclick={() => { c.fav = !c.fav; c.cat = 'all' }}><ShellIcon name="star" /> {t('canvas.composer.favs')}</button>
      <button type="button" aria-pressed={!c.fav && c.cat === 'all'} disabled={c.locked} onclick={() => { c.cat = 'all'; c.fav = false }}>{t('notes.all')}</button>
      {#each phone.cats.filter(cat => cat.count) as cat}<button type="button" aria-pressed={!c.fav && c.cat === cat.name} disabled={c.locked} onclick={() => { c.cat = cat.name; c.fav = false }}>{cat.name}</button>{/each}
    </div>
    <div class="m-cp-grid" bind:this={grid} onscroll={() => { if (grid && grid.scrollHeight - grid.scrollTop - grid.clientHeight < 200) windowSize += 120 }}>
      {#each rows.slice(0, windowSize) as row (identity(row))}
        {@const at = c.picks.findIndex(p => p.key === identity(row))}
        {@const pick = c.picks[at]}
        {@const used = c.used(row)}
        <button type="button" class="m-cp-tile" class:m-cp-picked={at >= 0} class:m-cp-used={used} class:m-cp-bad={pick?.state === 'unavailable'} disabled={c.locked}
          aria-label={(row.title || row.url || t('canvas.composer.item', { id: row.id })) + (used ? t('canvas.composer.used') : '')} aria-pressed={at >= 0} aria-disabled={used || c.locked} aria-busy={pick?.state === 'checking'} onclick={() => c.pick(row)}>
          <img src={c.source.thumbUrl(row, 160)} alt="" loading="lazy" draggable="false" />
          {#if used}<span><ShellIcon name="check" /></span>{:else if at >= 0}<span>{pick.state === 'unavailable' ? '!' : at + 1}</span>{/if}
        </button>
      {/each}
      {#if !phone.loaded && !phone.tried}<div class="m-cp-none">{t('canvas.composer.loading')}</div>
      {:else if !phone.loaded && phone.error}<div class="m-cp-none" role="alert">{phone.error}<MButton onclick={() => refresh()}>{t('common.tryAgain')}</MButton></div>
      {:else if !rows.length && !c.searching && !c.ranking}<div class="m-cp-none">{t('canvas.composer.none')}<MTextButton onclick={() => c.clear()}>{t('canvas.composer.clear')}</MTextButton></div>{/if}
    </div>
  {/if}
</section>
