<script lang="ts">
  // The dock (projects/phone-dock-shell, mockups/layout-v3.html): Notes at left, Ask Wiskit in the middle (the
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

  let { away = false }: { away?: boolean } = $props()
</script>

<nav class="m-dock" class:away aria-label={t('shell.dock.label')} inert={away}>
  <MKey size="dock" class="m-vt-notes" aria-label={t('shell.route.notes')} title={t('shell.route.notes')} onclick={() => go('#/notes')}><ShellIcon name="notes" /></MKey>
  <button type="button" class="m-askbox m-vt-jv" aria-label={t('shell.askWiskitLabel')} onclick={() => go('#/jv')}>
    <span class="m-ask-cat" aria-hidden="true"><WiskitSprite pose="happy" crop motionOff={phone.motionOff} /></span>
    <span><T id="shell.askWiskit" /></span>
  </button>
  <MKey size="dock" tone="add" class="m-vt-cap" aria-label={t('common.add')} title={t('common.add')} onclick={() => go('#/cap')}><ShellIcon name="plus" /></MKey>
</nav>
