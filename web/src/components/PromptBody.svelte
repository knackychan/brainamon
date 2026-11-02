<script lang="ts">
  import { untrack } from 'svelte'
  import Button from './ui/Button.svelte'
  import Field from './ui/Field.svelte'
  import Hint from './ui/Hint.svelte'
  import WinBody from './ui/WinBody.svelte'
  import WinFoot from './ui/WinFoot.svelte'
  // promptWin(): one text field, an optional hint, a check(v) that returns an error message or null.
  let { label, value, hint, ok, check, answer, close }: {
    label: string; value: string; hint?: string; ok: string
    check?: (v: string) => string | null; answer: (v: string) => void; close: () => void
  } = $props()
  let text = $state(untrack(() => value))   // the field starts from value, then is the user's
  let err = $state('')

  function go(e?: Event) {
    e?.preventDefault()
    const v = text.trim()
    const bad = check ? check(v) : (!v ? 'Enter a name.' : null)
    if (bad) { err = bad; return }
    answer(v)
  }
</script>

<WinBody>
  <form class="fg" onsubmit={go}>
    <Field {label} for="pw-in"><input class="inp" class:bad={!!err} id="pw-in" bind:value={text} autocomplete="off" data-autofocus /></Field>
    {#if hint}<span></span><Hint>{hint}</Hint>{/if}
    <span></span><Hint tone="error" hidden={!err}>{err}</Hint>
  </form>
</WinBody>
<WinFoot>
  <Button onclick={close}>Cancel</Button>
  <Button variant="pri" onclick={() => go()}>{ok}</Button>
</WinFoot>
