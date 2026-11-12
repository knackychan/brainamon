<script lang="ts">
  import type { Kind } from '../settings-steps'
  import { KIND_PATH } from './kinds.ts'
  let { kind, small = false }: { kind: Kind; small?: boolean } = $props()
</script>
<span class={['m-badge', `k-${kind}`, small && 'sm']} aria-hidden="true">{#if KIND_PATH[kind]}<svg viewBox="0 0 12 12"><path d={KIND_PATH[kind]} /></svg>{/if}</span>
