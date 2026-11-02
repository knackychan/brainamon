<script lang="ts" module>
  // The context key a host sets to a function: while it returns true, its primaries draw as default keys
  // (Settings while edits wait for Save, master rule 1 of the calm Settings plan). `keep` opts a key out.
  export const QUIET_PRIMARY = 'ui:quiet-primary'
</script>

<script lang="ts">
  // The V6 key (.wkey) or toolbar button (.tb); the look lives in the V6 page CSS
  // (projects/ui-building-blocks). type is "button" unless a form's submit key says "submit".
  import { getContext, type Snippet } from 'svelte'
  import type { HTMLButtonAttributes } from 'svelte/elements'

  type Props = HTMLButtonAttributes & {
    variant?: 'default' | 'pri' | 'danger'
    size?: 'md' | 'sm'
    kind?: 'key' | 'tool'
    wide?: boolean
    keep?: boolean
    ref?: HTMLButtonElement
    children?: Snippet
  }
  let { variant = 'default', size = 'md', kind = 'key', wide = false, keep = false, type = 'button', class: cls, ref = $bindable(), children, ...rest }: Props = $props()
  const quiet = getContext<(() => boolean) | undefined>(QUIET_PRIMARY)
  const shown = $derived(variant === 'pri' && !keep && quiet?.() ? 'default' : variant)
</script>

<button bind:this={ref} {...rest} {type} class={[kind === 'tool' ? 'tb' : 'wkey', size === 'sm' && 'sm', shown !== 'default' && shown, wide && 'w', cls]}>{@render children?.()}</button>
