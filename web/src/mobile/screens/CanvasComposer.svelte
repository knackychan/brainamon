<script lang="ts">
  import { toolText } from '../tools-words.ts'
  import { t } from '../../lib/i18n/index.ts'
  import { onMount, untrack } from 'svelte'
  import { phone, refresh, source } from '../state.svelte'
  import { up, shell, go } from '../shell.svelte'
  import { Composer } from '../canvas/compose.svelte'
  import { CHANGED, preview, stops, type Stop } from '../canvas/compose'
  import { composerSuccess, registerGuard, unguarded } from '../canvas/navigation'
  import { beginLanguageWork, registerLanguageCheck } from '../language-switch.ts'
  import { strip } from '../ai/quick'
  import CanvasBoard from '../canvas/CanvasBoard.svelte'
  import ComposeDrawer from '../canvas/ComposeDrawer.svelte'
  import ShellIcon from '../ShellIcon.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MDialog from '../ui/MDialog.svelte'
  import MButton from '../ui/MButton.svelte'

  let { id }: { id: string | null } = $props()
  let c = $state.raw(new Composer(source, phone.smart, toolText)), active: string | null | undefined
  let header: HTMLElement | undefined = $state(), nameInput: HTMLInputElement | undefined = $state()
  let height = $state(0), stop = $state<Stop>('half'), bottom = $state(0)
  let heights = $state(stops(0, 0, 0, 0)), open = $state(false), shaking = $state(false)
  let leave: (() => void) | null = null, shakeTimer: ReturnType<typeof setTimeout> | undefined
  const doc = $derived(preview(c.base, c.picks.map(p => p.row.id), c.note, c.color, c.layout,
    new Map(c.picks.filter(p => p.size).map(p => [p.row.id, p.size!]))))
  const staged = $derived.by(() => {
    const entries = new Map<string, { key: string; url?: string; unavailable?: boolean }>()
    c.picks.forEach((p, i) => entries.set(`draft_${i}`, { key: p.key, url: p.url, unavailable: p.state === 'unavailable' }))
    if (strip(c.note)) entries.set(`draft_${c.picks.length}`, { key: 'note' })
    return entries
  })
  $effect(() => { const target = id; untrack(() => {
    if (active === target) return
    if (active !== undefined && c.id !== target) { c.destroy(); c = new Composer(source, phone.smart, toolText); stop = 'half' }
    active = target; shell.base = 'cv'; void c.target(target)
  }) })
  $effect(() => { const rows = phone.rows, locked = c.locked; if (!locked) untrack(() => c.reconcile(rows)) })
  $effect(() => { const rev = phone.canvasRevision, target = id, locked = c.locked; untrack(() => { if (rev && target && !locked) void c.target(target) }) })
  $effect(() => { if (!open) leave = null })
  onMount(() => {
    const releaseLanguageCheck = registerLanguageCheck(() => c.busy || c.uncertain || c.n || (!c.id && c.name.trim()) ? 'settings.language.unsavedCanvas' : null)
    const shared = () => c.tell(t('canvas.composer.shared'))
    window.addEventListener('brainamon-compose-share', shared)
    const cleanup = registerGuard(next => {
      if (c.busy) return true
      if (open) return true
      if (c.n) { leave = next; open = true; return true }
      return false
    })
    const measure = () => {
      if (!header) return
      const app = document.getElementById('m-app')!, viewport = window.visualViewport
      const V = (viewport?.offsetTop || 0) + (viewport?.height || innerHeight)
      const style = getComputedStyle(app), T = app.getBoundingClientRect().top + parseFloat(style.paddingTop || '0')
      const drawer = document.querySelector('.m-cp-drawer')
      const B = drawer ? parseFloat(getComputedStyle(drawer).paddingBottom) || 0 : 0
      bottom = Math.max(0, innerHeight - V)
      heights = stops(V, T, header.getBoundingClientRect().bottom, B)
    }
    const observer = new ResizeObserver(measure)
    if (header) observer.observe(header)
    if (header?.parentElement) observer.observe(header.parentElement)
    const app = document.getElementById('m-app'); if (app) observer.observe(app)
    visualViewport?.addEventListener('resize', measure); visualViewport?.addEventListener('scroll', measure); window.addEventListener('resize', measure)
    measure()
    return () => { cleanup(); c.destroy(); releaseLanguageCheck(); leave = null; clearTimeout(shakeTimer); observer.disconnect(); visualViewport?.removeEventListener('resize', measure); visualViewport?.removeEventListener('scroll', measure); window.removeEventListener('resize', measure); window.removeEventListener('brainamon-compose-share', shared) }
  })
  function back() {
    if (c.busy) return
    const dialog = document.querySelector<HTMLDialogElement>('dialog[open]')
    if (dialog) { dialog.close(); return }
    if (shell.panel) { shell.panel = false; return }
    up(false)
  }
  async function add() {
    const done = beginLanguageWork()
    try {
      const result = await c.add(() => phone.rows)
      if (result) {
        shell.canvasNotice = { canvasId: result.id, text: result.text, until: 0 }
        c.destroy(); c.note = ''; leave = null; open = false
        composerSuccess(`#/canvas/${encodeURIComponent(result.id)}`, result.add)
      } else if (c.error === CHANGED) {
        c.busy = true
        try { await refresh() } finally { c.busy = false; c.reconcile(phone.rows, true) }
      } else if (c.nameError) {
        nameInput?.focus(); shaking = true; clearTimeout(shakeTimer); shakeTimer = setTimeout(() => { shaking = false }, 300)
      } else if (c.error) stop = c.noteMode ? 'note' : 'half'
    } finally { done() }
  }
  async function retarget() {
    const target = c.clashId
    if (!target || c.locked) return
    if (await c.target(target, true)) {
      active = target; c.nameError = false; c.selected = null; c.clashId = null; c.error = ''
      // The one transition that retains the staging session.
      unguarded(() => go(`#/canvas/${encodeURIComponent(target)}/add`, true))
    }
  }
</script>

<div class="m-cp-page" class:m-cp-still={phone.motionOff}>
  <header class="m-cp-header" bind:this={header}>
    <button type="button" class="m-back" aria-label={t('common.back')} disabled={c.busy} onclick={back}>‹</button>
    {#if id}<span class="m-ws">{c.base?.name || '…'}</span>
    {:else}<input bind:this={nameInput} class="m-cp-name" class:m-cp-invalid={c.nameError} class:m-cp-shake={shaking} aria-label={t('canvas.composer.name')} aria-invalid={c.nameError} placeholder={t('canvas.composer.namePlaceholder')} value={c.name} disabled={c.locked} oninput={e => { c.name = e.currentTarget.value; c.edited() }} onfocus={() => { stop = 'closed' }} onkeydown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />{/if}
    <div class="m-cp-layout"><MSeg label={t('canvas.composer.layout')} options={[["rows", t('canvas.composer.rows')], ["columns", t('canvas.composer.columns')]]} value={c.layout} disabled={c.locked} onchange={v => { c.layout = v; c.edited() }}>
      {#snippet icon(value: string)}<ShellIcon name={value === 'rows' ? 'rows' : 'columns'} />{/snippet}
    </MSeg></div>
  </header>
  <div class="m-cp-board-wrap"><CanvasBoard {doc} compose {staged} selected={c.selected} onselect={key => { if (!c.locked) c.selected = key }} onremove={key => c.remove(key)} covered={height + bottom} full={height === heights.full} busy={c.locked} /></div>
  <ComposeDrawer {c} {heights} bind:height bind:stop {bottom} onadd={add} />
  {#if c.notice}<div class="m-cp-notice" role="status" style:bottom="{height + bottom + 12}px"><span>{c.notice}</span>{#if c.clashId}<button type="button" disabled={c.locked} onclick={retarget}>{t('canvas.composer.addTo')}</button>{/if}</div>{/if}
</div>
<MDialog bind:open title={t('canvas.composer.discardTitle')}>
  <p>{c.uncertain ? t('canvas.composer.uncertainLeave') : t('canvas.composer.notAdded', { n: c.n })}</p>
  {#snippet actions()}
    <MButton onclick={() => { leave = null; open = false }}>{t('canvas.composer.keep')}</MButton>
    <MButton variant="danger" onclick={() => { const next = leave; leave = null; c.destroy(); c.note = ''; open = false; next?.() }}>{t('canvas.composer.discard')}</MButton>
  {/snippet}
</MDialog>
