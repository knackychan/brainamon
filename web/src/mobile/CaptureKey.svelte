<script lang="ts">
  // Add's top-right key (projects/phone-add-confirm): opens the Import & drafts panel that Capture.svelte owns, which
  // drops from this key; dark while the panel is open; the orange badge counts the other drafts waiting. Mobile.svelte
  // draws it in the bare sheet's corner snippet, on the draft page of #/cap only.
  import { t } from '../lib/i18n/index.ts'
  import { capUi } from './capture-ui.svelte'
  import MKey from './ui/MKey.svelte'
  import ShellIcon from './ShellIcon.svelte'
</script>

<span class="m-cap-tray">
  <MKey aria-label={t('shell.captureTray')} title={t('shell.captureTray')} aria-haspopup="dialog" aria-expanded={capUi.open} tone={capUi.open ? 'dark' : 'plain'} onclick={() => capUi.tray++}><ShellIcon name="import" /></MKey>
  {#if capUi.drafts > 0}<span class="m-cap-badge" aria-hidden="true">{capUi.drafts > 99 ? '99+' : capUi.drafts}</span>{/if}
</span>
