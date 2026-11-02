<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { on } from '../lib/events.svelte'
  import { refreshAskOptions } from '../lib/ask.svelte'
  import { loadOnboarding } from '../lib/onboarding.svelte'
  import type { ModelView } from '../lib/setup'
  import Button from './ui/Button.svelte'
  import Field from './ui/Field.svelte'
  import Hint from './ui/Hint.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import ClaudeCodeSetup from './ClaudeCodeSetup.svelte'

  let view = $state<{ keys: Record<string, boolean>; models: ModelView } | null>(null)
  let provider = $state(''), model = $state(''), key = $state('')
  let busy = $state(false), error = $state(''), message = $state('')
  let refreshing = $state(false)
  let defaults: Record<string, string> = {}
  const id = $props.id()
  const saved = $derived(!!view?.keys[provider])
  const providerLabel = $derived(view?.models.providers.find(p => p.id === provider)?.label ?? provider)
  const modelChanged = $derived(provider !== view?.models.jarvis.provider || model !== view?.models.jarvis.model)
  async function load() {
    error = ''
    try {
      const [settings, options] = await Promise.all([api.get<NonNullable<typeof view>>('/api/settings'), api.get<{ default_models: Record<string, string> }>('/api/ask/options')])
      if (!view) { provider = settings.models.jarvis.provider; model = settings.models.jarvis.model }
      view = settings; defaults = options.default_models
    } catch (e) { error = (e as Error).message }
  }
  onMount(() => {
    void load()
    const off = on('settings_changed', load)
    return () => { off(); key = '' }
  })
  function changeProvider() {
    key = ''; message = ''; error = ''
    const models = view?.models.models[provider] ?? []
    model = models.find(m => m.id === defaults[provider])?.id ?? models[0]?.id ?? ''
  }
  async function save(kind: 'key' | 'model') {
    if (busy || !view) return
    busy = true; error = ''; message = ''
    try {
      const result = await api.put<NonNullable<typeof view>>('/api/settings', kind === 'key'
        ? { keys: { [provider]: key.trim() } } : { models: { jarvis: { provider, model } } })
      view = result
      if (kind === 'key') key = ''
      message = kind === 'key' ? 'Key saved on this PC. Provider access has not been tested.' : 'Wiskit model saved.'
      void refreshAskOptions()
      void loadOnboarding().catch(() => {})
    } catch (e) { error = (e as Error).message }
    finally { busy = false }
  }
  // Same call as Settings > Wiskit & AI > Refresh model lists: only the lists change, never the choice on screen.
  async function refreshModels() {
    if (busy || refreshing || !view) return
    refreshing = true; error = ''; message = ''
    try {
      const r = await api.post<{ results: Record<string, { ok: boolean; count: number; error: string }>; models: ModelView }>('/api/settings/models/refresh', {})
      view = { ...view, models: { ...view.models, models: r.models.models, found_at: r.models.found_at } }
      void refreshAskOptions()
      const x = r.results[provider]
      message = x?.ok ? `${x.count} ${providerLabel} models found.` : x?.error || 'Skipped: save a key for this provider first.'
    } catch (e) { error = (e as Error).message }
    finally { refreshing = false }
  }
  async function getKey() {
    try { await api.post('/api/app/setup/link', { name: provider }) }
    catch (e) { error = (e as Error).message }
  }
</script>

<div class="setup-ai-form">
  {#if view}
    <Hint><strong>OpenAI is recommended.</strong> One key covers Wiskit, Whisper transcription and the default search embeddings. Anthropic supports Wiskit, but does not provide transcription or embeddings.</Hint>
    <Field label="AI provider" for={`${id}-provider`}>
      <select class="inp" id={`${id}-provider`} bind:value={provider} onchange={changeProvider} disabled={busy}>
        {#each view.models.providers as item (item.id)}<option value={item.id}>{item.label}{item.id === 'openai' ? ' (recommended)' : ''}</option>{/each}
      </select>
    </Field>
    <Field label="API key" for={`${id}-key`}>
      <div class="frow">
        <input class="inp" id={`${id}-key`} type="password" bind:value={key} disabled={busy} autocomplete="off" spellcheck="false" placeholder={saved ? 'Saved on this PC. Paste a replacement if needed' : 'Paste your provider key'} />
        <div class="key-actions">
          <Button class="save-key" size="sm" disabled={busy || !key.trim()} onclick={() => save('key')}>{busy ? 'Saving…' : 'Save key'}</Button>
          {#if provider === 'anthropic' || provider === 'openai'}<Button size="sm" disabled={busy} onclick={getKey}>Get a provider key</Button>{/if}
        </div>
      </div>
    </Field>
    <Status on={saved}>{saved ? 'Key saved on this PC' : 'No key saved for this provider'}</Status>
    <Field label="Wiskit model" for={`${id}-model`}>
      <div class="frow">
        <select class="inp" id={`${id}-model`} bind:value={model} disabled={busy || refreshing || !view.models.models[provider]?.length}>
          {#each view.models.models[provider] ?? [] as item (item.id)}<option value={item.id}>{item.label}</option>{/each}
        </select>
        <div class="model-actions"><Button size="sm" disabled={busy || refreshing} onclick={refreshModels}>{refreshing ? 'Checking…' : 'Refresh models'}</Button></div>
      </div>
    </Field>
    {#if refreshing}<Progress label="Asking the providers for their model lists" />{/if}
    <div><Button variant="pri" disabled={busy || !model || !view.models.providers.find(p => p.id === provider)?.has_key || !modelChanged} onclick={() => save('model')}>Use this model</Button></div>
    <Hint>AI requests send prompts and relevant library content to the selected provider or configured endpoint. Save your key before leaving this step.</Hint>
  {:else if !error}<Hint role="status">Loading AI settings…</Hint>{/if}
  {#if message}<Hint role="status">{message}</Hint>{/if}
  {#if error}<Hint tone="error" role="alert">{error}</Hint>{#if !view}<Button size="sm" onclick={load}>Retry AI settings</Button>{/if}{/if}
  <ClaudeCodeSetup />
</div>

<style>
  .setup-ai-form { display: grid; gap: 12px; width: 100%; max-width: 580px }
  .frow { display: flex; flex-wrap: wrap; gap: 8px }
  .frow .inp { flex: 1 1 220px; min-width: 0 }
  .key-actions, .model-actions { display: flex; flex-wrap: wrap; gap: 8px }
  .setup-ai-form :global(.wkey.save-key) { background: var(--ok); color: #000 }
  .setup-ai-form :global(.wkey.save-key:hover:not(:disabled)) { filter: brightness(.94) }
  .setup-ai-form > :global(.wkey) { justify-self: start }
</style>
