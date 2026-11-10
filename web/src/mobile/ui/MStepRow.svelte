<script lang="ts">
  // One step of the Tools panel (projects/phone-processing-flow, option C; tools.css .m-step): Add's Import & drafts
  // row (a dark glyph square, the name, one line, a round key). Tapping the row is the action. Its classes are all
  // m-step-* (a bare .on or .cur is styled by the global sheets). `rec`: the suggested
  // step (outlined, orange key, `tag`). `state`: "on" while it is the run's heading (no key; its glyph turns orange),
  // "fin" once the run ended (green). The children grow inside the row under it (the confirm line).
  import type { Snippet } from 'svelte'
  import ShellIcon from '../ShellIcon.svelte'
  import type { ShellGlyph } from '../tabicons'

  type Props = { label: string; sub: string; glyph: ShellGlyph; rec?: boolean; tag?: string; state?: 'rest' | 'on' | 'fin'; disabled?: boolean; expanded?: boolean; onclick?: () => void; children?: Snippet }
  let { label, sub, glyph, rec = false, tag = '', state = 'rest', disabled = false, expanded, onclick, children }: Props = $props()
  const id = $props.id()
</script>

<div class={['m-step', rec && 'm-step-rec', state !== 'rest' && 'm-step-on', state === 'fin' && 'm-step-fin', disabled && 'm-step-off']}>
  {#if state === 'rest'}
    <button type="button" class="m-step-rw" aria-label={label} aria-describedby={tag ? `${id}-s ${id}-t` : `${id}-s`} aria-expanded={expanded} {disabled} {onclick}>
      <i class="m-step-gl"><ShellIcon name={glyph} /></i>
      <span class="m-step-nm"><b>{label}</b><small id="{id}-s">{sub}</small></span>
      {#if tag}<span class="m-step-tag" id="{id}-t">{tag}</span>{/if}
      <span class="m-step-go" aria-hidden="true"><ShellIcon name="play" /></span>
    </button>
  {:else}
    <div class="m-step-rw">
      <i class="m-step-gl"><ShellIcon name={state === 'fin' ? 'check' : glyph} /></i>
      <span class="m-step-nm"><b>{label}</b><small role="status">{sub}</small></span>
    </div>
  {/if}
  {@render children?.()}
</div>
