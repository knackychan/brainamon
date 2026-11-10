<script lang="ts">
  // The phone's switch (.m-tg in mobile.css): a button with aria-pressed, `label` as its accessible name.
  // `on` is the state; onchange(on) gets the new value after a tap. Inside a MRow it sits in the control column.
  import type { HTMLButtonAttributes } from 'svelte/elements'
  import type { Snippet } from 'svelte'

  type Props = Omit<HTMLButtonAttributes, 'onchange'> & { label: string; on: boolean; onchange?: (on: boolean) => void; children?: Snippet }
  let { label, on, disabled = false, class: cls, onchange, children, ...rest }: Props = $props()
</script>

<button type="button" {...rest} class={['m-tg', cls]} aria-pressed={on} aria-label={label} {disabled} onclick={() => onchange?.(!on)}><i></i>{@render children?.()}</button>
