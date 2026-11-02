<script lang="ts">
  // Settings > AI models: the Wiskit provider and model, as two cells of a .fg row; `children` (a hint)
  // goes under the two selects.
  import type { Snippet } from 'svelte'
  import type { ModelChoice, ModelView } from '../lib/setup'
  import Label from './ui/Label.svelte'
  let { catalog, choice = $bindable(), children }: { catalog: ModelView; choice: ModelChoice; children?: Snippet } = $props()
  const id = $props.id()
  function changeProvider() {
    choice = { provider: choice.provider, model: catalog.models[choice.provider]?.[0]?.id ?? '' }
  }
</script>

<Label for={id}>Wiskit model</Label>
<div>
  <div class="frow">
    <select class="inp" id={id} bind:value={choice.provider} onchange={changeProvider} aria-label="Wiskit provider">
      {#each catalog.providers as p (p.id)}
        <option value={p.id} disabled={!p.has_key && p.id !== choice.provider}>{p.label}{p.has_key ? '' : ' (no key)'}</option>
      {/each}
    </select>
    <select class="inp" bind:value={choice.model} aria-label="Wiskit model">
      {#each catalog.models[choice.provider] ?? [] as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
    </select>
  </div>
  {@render children?.()}
</div>
