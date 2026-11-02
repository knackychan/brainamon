<script lang="ts">
  // The phone's quiet action (.m-link in mobile.css): a text key beside real keys, for Cancel, Hide, Show and the
  // quieter destructive actions; tone="danger" draws it in the danger colour. Keeps its two-tap confirmation words.
  import type { Snippet } from 'svelte'
  import type { HTMLButtonAttributes } from 'svelte/elements'

  type Props = HTMLButtonAttributes & { tone?: 'default' | 'danger'; children?: Snippet }
  let { tone = 'default', type = 'button', class: cls, children, ...rest }: Props = $props()
</script>

<button {...rest} {type} class={['m-link', tone === 'danger' && 'danger', cls]}>{@render children?.()}</button>
