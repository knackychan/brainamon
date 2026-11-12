<script lang="ts">
  import type { Snippet } from 'svelte'
  import type { Kind } from '../settings-steps'
  import MInfo from './MInfo.svelte'
  import MBadge from './MBadge.svelte'
  let { title = '', line = '', kind, id, info, infoTitle = '', children }: {
    title?: string; line?: string; kind?: Kind; id?: string; info?: Snippet; infoTitle?: string; children?: Snippet
  } = $props()
</script>
<section class="m-card-section" {id} tabindex="-1">
  {#if title}<div class="m-card-head"><h3>{title}</h3>{#if kind}<MBadge {kind} small />{/if}{#if info}<MInfo title={infoTitle || title}>{@render info()}</MInfo>{/if}</div>{/if}
  {#if line}<p class="m-card-line">{line}</p>{/if}
  <div class="m-card">{@render children?.()}</div>
</section>
