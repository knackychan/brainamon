<script lang="ts">
  // One state on a phone screen (.m-status in mobile.css): a dot for its tone (done: all well, todo: nothing to do
  // here, next: needs you, busy: working), the sentence, an optional detail under it, then at most one key (the
  // children). The status card on More and the Status group of More > Backup & phones draw the PhoneState with it.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'

  type Props = HTMLAttributes<HTMLDivElement> & { tone: 'done' | 'todo' | 'next' | 'busy'; text: string; detail?: string; children?: Snippet }
  let { tone, text, detail = '', class: cls, children, ...rest }: Props = $props()
</script>

<div {...rest} class={['m-status', cls]}><p><b><i class={['m-status-dot', tone]} aria-hidden="true"></i>{text}</b>{#if detail}<small>{detail}</small>{/if}</p>{@render children?.()}</div>
