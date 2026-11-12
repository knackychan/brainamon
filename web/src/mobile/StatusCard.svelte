<script lang="ts">
  import { t } from '../lib/i18n/index.ts'
  // The top of Settings for a phone paired with a PC or used without one (projects/phone-settings, spec section 2.1;
  // first in docs/superpowers/plans/2026-10-31-phone-backup-phones.md P2): the one PhoneState as the hero, its kicker
  // the link to Settings > Backup & phones, which says the rest, its sentence as the title and at most one key, the
  // pill. The kicker and the key are separate targets; the detail never shows here.
  import { actionBusy, actionLabel, runPhoneAction } from './actions'
  import { kindOf } from './settings-steps'
  import { backup } from './backup.svelte'
  import SettingsProgress from './SettingsProgress.svelte'
  import { phoneStatus } from './state.svelte'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MStatus from './ui/MStatus.svelte'

  const st = $derived(phoneStatus())
</script>

{#if st}
  <MBox id="m-status" class={['m-status-hero', 'm-wash', `k-${kindOf(st, backup.error)}`]}>
    <MStatus look="hero" kicker={t('backup.state.title')} kind={kindOf(st, backup.error)} tone={st.tone} text={st.text}>
      {#if st.action}{@const a = st.action}<MButton shape="pill" variant={a.primary ? 'pri' : 'default'} disabled={actionBusy(a.id)} onclick={() => runPhoneAction(a.id)}>{actionLabel(a)}</MButton>{/if}
    </MStatus>
    <SettingsProgress />
  </MBox>
{/if}
