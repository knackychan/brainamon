<script lang="ts">
  import Disclosure from './ui/Disclosure.svelte'
  import Hint from './ui/Hint.svelte'
  import TextButton from './ui/TextButton.svelte'
  import MDisclosure from '../mobile/ui/MDisclosure.svelte'
  import MHint from '../mobile/ui/MHint.svelte'
  import MTextButton from '../mobile/ui/MTextButton.svelte'

  let { mobile = false, paired = false, words, workingLabel, workingReason = '', methodReason = '', onworking, onfile, oncode, onnone }: {
    mobile?: boolean; paired?: boolean; words?: (key: string, params?: Record<string, unknown>) => string; workingLabel: string; workingReason?: string; methodReason?: string
    onworking?: () => void; onfile?: () => void; oncode: () => void; onnone?: () => void
  } = $props()
  const D = $derived(mobile ? MDisclosure : Disclosure)
  const H = $derived(mobile ? MHint : Hint)
  const T = $derived(mobile ? MTextButton : TextButton)
  const id = $props.id()
</script>

<D summary={words?.('recovery.forgot.forgot') ?? "Forgot passphrase?"}>
  <H>{words?.('recovery.forgot.choose') ?? "Choose what you still have. Opening this guide does not change your library, keys or backup."}</H>
  <D summary={words?.('recovery.forgot.working') ?? "I can still open my library"}>
    {#if paired}
      <H>{words?.('recovery.forgot.pc') ?? "The desktop passphrase is managed on the PC. On a PC that still holds the library key, open Settings > Backup & phones > Recovery > Change passphrase. The old passphrase is not required."}</H>
    {:else}
      <H>{mobile
        ? (words?.('recovery.forgot.solo') ?? 'This standalone phone can create another passphrase for the key it still holds. You do not need the old passphrase. Earlier phone passphrases remain valid.')
        : (words?.('recovery.forgot.desktop') ?? 'On the PC that still holds the library key, use Change passphrase. You do not need the old passphrase.')}</H>
      {#if onworking}<T disabled={!!workingReason} aria-describedby={workingReason ? `${id}-working` : undefined} onclick={onworking}>{workingLabel}</T>{/if}
      {#if workingReason}<H id={`${id}-working`}>{workingReason}</H>{/if}
    {/if}
  </D>
  <D summary={words?.('recovery.forgot.file') ?? "I have a recovery file"}>
    <H>{words?.('recovery.forgot.fileHelp') ?? "The recovery file unlocks the encrypted backup; it does not contain your library. Sign in to the same Google account that holds the backup to retrieve it."}</H>
    {#if paired}<H>{words?.('recovery.forgot.filePc') ?? "Use the file in Recover a library on the PC."}</H>{/if}
    {#if !paired}<T disabled={!!methodReason} aria-describedby={methodReason ? `${id}-methods` : undefined} onclick={onfile}>{words?.('recovery.forgot.useFile') ?? "Use recovery file"}</T>{/if}
  </D>
  <D summary={words?.('recovery.forgot.code') ?? "I have a recovery code or a paired phone"}>
    <H>{mobile && !paired
      ? (words?.('recovery.forgot.soloCode') ?? 'Use the standalone phone’s original 43-character recovery code. For a desktop library, use the surviving paired phone and recover on the PC.')
      : (words?.('recovery.forgot.pairedCode') ?? 'On the surviving paired phone, open Settings > Backup & phones > Recovery. Show its recovery code or export a recovery file, then use it in Recover a library on the PC. A phone removed by a later key rotation may no longer unlock the backup.')}</H>
    <T disabled={!!methodReason} aria-describedby={methodReason ? `${id}-methods` : undefined} onclick={oncode}>{paired ? (words?.('recovery.forgot.showCode') ?? 'Show recovery code') : (words?.('recovery.forgot.useCode') ?? 'Use recovery code')}</T>
  </D>
  <D summary={words?.('recovery.forgot.none') ?? "I have none of these"}>
    <H>{words?.('recovery.forgot.noneHelp') ?? "Google sign-in alone cannot unlock the encrypted backup. Without a working device holding the library key or valid recovery material, the backup cannot be unlocked."}</H>
    {#if onnone}<T onclick={onnone}>{mobile ? (words?.('recovery.forgot.phoneChoices') ?? 'Choose phone backup options…') : (words?.('recovery.forgot.pcChoices') ?? 'Use this PC’s library instead…')}</T>{/if}
    {#if mobile && paired}<H>{words?.('recovery.forgot.pcManage') ?? "Manage or replace the desktop backup on the PC. This phone cannot delete the PC’s backup."}</H>{/if}
  </D>
  {#if methodReason}<H id={`${id}-methods`} role="status">{methodReason}</H>{/if}
</D>
