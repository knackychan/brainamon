<script lang="ts">
  // The first box of More for a phone paired with a PC or used without one (docs/superpowers/plans/
  // 2026-10-31-phone-backup-phones.md P2): the one PhoneState as its dot, its sentence and at most one key. The heading
  // opens More > Backup & phones, which says the rest; the heading and the key are separate targets.
  import { actionBusy, actionLabel, runPhoneAction } from './actions'
  import { phoneStatus } from './state.svelte'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MStatus from './ui/MStatus.svelte'

  const st = $derived(phoneStatus())
</script>

{#if st}
  <MBox id="m-status">
    <h3><a class="m-status-head" href="#/backup">Backup &amp; phones<span class="m-sp"></span><span aria-hidden="true">›</span></a></h3>
    <MStatus tone={st.tone} text={st.text}>
      {#if st.action}{@const a = st.action}<MButton size="sm" variant={a.primary ? 'pri' : 'default'} disabled={actionBusy(a.id)} onclick={() => runPhoneAction(a.id)}>{actionLabel(a)}</MButton>{/if}
    </MStatus>
  </MBox>
{/if}
