<script lang="ts">
  // The dock: Tools at left, Ask Wiskit in the middle (the
  // cat's sparkle curl: the `happy` pose cropped to its bounds), Add at right, the one orange key. Each opens its
  // sheet through shell.svelte.ts `go`; the m-vt-* class is the view-transition-name the sheet takes over.
  // `away`: search is open, the dock slides down out of view.
  import WiskitSprite from '../components/WiskitSprite.svelte'
  import T from '../lib/i18n/T.svelte'
  import { t } from '../lib/i18n/index.ts'
  import { phone } from './state.svelte'
  import { go } from './shell.svelte'
  import MKey from './ui/MKey.svelte'
  import ShellIcon from './ShellIcon.svelte'
  import Processing from './Processing.svelte'
  import ToolsRing from './ToolsRing.svelte'
  import { hasRun } from './tools-run.svelte'
  import type { Row } from './source/types'

  let { away = false }: { away?: boolean } = $props()
  let processRows = $state<Row[] | null>(null)
  let heading = $state('')
  let toolsKey: HTMLButtonElement | HTMLAnchorElement | HTMLLabelElement | undefined = $state()
  function tools() {
    heading = phone.selection ? t('library.selected', { n: phone.selection.size }) : phone.q.trim() ? t('library.heading.results') : phone.fav ? t('library.heading.favourites') : phone.cat === 'all' ? t('library.heading.all') : phone.cat
    processRows = phone.selection ? phone.rows.filter(r => phone.selection!.has(r.id)) : [...phone.visible]
  }
  $effect(() => { phone.route; processRows = null })
</script>

<nav class="m-dock" class:away aria-label={t('shell.dock.label')} inert={away}>
  <MKey bind:ref={toolsKey} size="dock" class="m-lib-tools" aria-label={t('common.tools')} title={t('common.tools')} aria-haspopup="dialog" aria-describedby="m-tools-status" aria-expanded={!!processRows} tone={processRows ? 'dark' : 'plain'} disabled={phone.selection?.size === 0 && !hasRun()} onclick={tools}><ShellIcon name="tools" /><ToolsRing open={!!processRows} /></MKey>
  <ToolsRing open={!!processRows} status />
  <button type="button" class="m-askbox m-vt-jv" aria-label={t('shell.askWiskitLabel')} onclick={() => go('#/jv')}>
    <span class="m-ask-cat" aria-hidden="true"><WiskitSprite pose="happy" crop motionOff={phone.motionOff} /></span>
    <span><T id="shell.askWiskit" /></span>
  </button>
  <MKey size="dock" tone="add" class="m-vt-cap" aria-label={t('common.add')} title={t('common.add')} onclick={() => go('#/cap')}><ShellIcon name="plus" /></MKey>
</nav>
{#if processRows}<Processing rows={processRows} anchor={toolsKey} {heading} close={() => processRows = null} />{/if}
