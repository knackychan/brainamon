<script lang="ts">
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  import WinBody from './ui/WinBody.svelte'
  import WinFoot from './ui/WinFoot.svelte'
  // confirmWin(): message, optional detail, Cancel + OK (danger styles OK red).
  let { msg, detail, ok, danger, cancel = 'Cancel', answer, close }: {
    msg: string; detail?: string; ok: string; danger: boolean; cancel?: string; answer: (v: boolean) => void; close: () => void
  } = $props()
</script>

<WinBody><div class="about"><p>{msg}</p>{#if detail}<Hint>{detail}</Hint>{/if}</div></WinBody>
<WinFoot>
  <Button data-autofocus={danger ? true : undefined} onclick={() => answer(false)}>{cancel}</Button>
  <Button variant="pri" class={{ danger }} data-autofocus={!danger ? true : undefined} onclick={() => answer(true)}>{ok}</Button>
</WinFoot>
