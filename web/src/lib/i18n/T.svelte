<script lang="ts">
  import { template, type Key, type Params } from './index.ts'
  import { parseRich, safeHref, type RichNode } from './rich.ts'

  type Binding = { href?: string; action?: () => void }
  let { id, params = {}, links = {} }: { id: Key; params?: Params; links?: Record<string, Binding> } = $props()
  const nodes = $derived(parseRich(template(id, params), params))
  const binding = (name: string | undefined) => name && Object.hasOwn(links, name) ? links[name] : undefined
</script>

{#snippet render(items: RichNode[])}
  {#each items as item}
    {#if item.type === 'text'}{item.value}
    {:else if item.type === 'b'}<b>{@render render(item.children)}</b>
    {:else if item.type === 'i'}<i>{@render render(item.children)}</i>
    {:else if item.type === 'code'}<code>{@render render(item.children)}</code>
    {:else if binding(item.name)?.href && !binding(item.name)?.action && safeHref(binding(item.name)?.href)}
      <a href={safeHref(binding(item.name)?.href) ?? undefined} target="_blank" rel="noopener noreferrer">{@render render(item.children)}</a>
    {:else if binding(item.name)?.action && !binding(item.name)?.href}
      <button type="button" class="i18n-link" onclick={binding(item.name)?.action}>{@render render(item.children)}</button>
    {:else}{@render render(item.children)}{/if}
  {/each}
{/snippet}

{@render render(nodes)}

<style>
  .i18n-link { border: 0; padding: 0; background: none; color: inherit; font: inherit; text-decoration: underline; cursor: pointer }
</style>
