<script lang="ts">
  // AI-01 Turn on Wiskit (spec D5): one provider, its key page, one field. The key goes to .env through
  // PUT /api/settings (core/config.py) and nowhere else. When the Wiskit provider has no key yet, the same
  // call moves Wiskit to the chosen provider's default model (the one a new Ask chat starts on, e.g.
  // Sonnet 4.6, else its first listed), so the new key works at once; a key already saved for the chosen
  // provider is enough for that move.
  import { onMount } from 'svelte'
  import WiskitSprite from '../components/WiskitSprite.svelte'
  import { api } from '../lib/api'
  import { refreshAskOptions } from '../lib/ask.svelte'
  import { openSettings } from '../lib/io-commands.svelte'
  import { loadOnboarding } from '../lib/onboarding.svelte'
  import { ui } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import WinBody from '../components/ui/WinBody.svelte'

  let { close, want = '' }: { close: () => void; want?: string } = $props()
  type Pid = 'openai' | 'anthropic'
  const PROVIDERS: [Pid, string][] = [['openai', 'OpenAI'], ['anthropic', 'Anthropic']]
  interface Models { jarvis: { provider: string; model: string }; providers: { id: string; label: string; has_key: boolean }[]; models: Record<string, { id: string; label: string }[]> }
  let models = $state<Models | null>(null)
  let provider = $state<Pid>('openai')
  let key = $state(''), busy = $state(false), error = $state(''), done = $state(false)
  let doneKey = $state<HTMLButtonElement>()
  const name = $derived(PROVIDERS.find(([id]) => id === provider)?.[1] ?? provider)
  const hasKey = (m: Models, id: string) => !!m.providers.find(p => p.id === id)?.has_key
  // Wiskit moves only while its own provider has no key
  const moves = (m: Models, id: string) => m.jarvis.provider !== id && !hasKey(m, m.jarvis.provider)
  const saved = $derived(!!models && hasKey(models, provider))
  const ready = $derived(!!models && (!!key.trim() || (saved && moves(models, provider))))

  onMount(() => {
    api.get<{ models: Models }>('/api/settings').then(v => {
      models = v.models
      const has = (id: string) => hasKey(v.models, id)
      provider = want === 'openai' || want === 'anthropic' ? want
        : has('openai') ? 'openai' : has('anthropic') ? 'anthropic' : v.models.jarvis.provider === 'anthropic' ? 'anthropic' : 'openai'
    }).catch(e => { error = (e as Error).message })
  })
  $effect(() => { if (done) doneKey?.focus() })

  async function openKeyPage() {
    error = ''
    try { await api.post('/api/app/setup/link', { name: provider }) } catch (e) { error = (e as Error).message }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault()
    if (busy || !ready) return
    busy = true; error = ''
    try {
      const m = (await api.get<{ models: Models }>('/api/settings')).models     // fresh: Settings may have changed Wiskit
      const body: Record<string, unknown> = {}
      if (key.trim()) body.keys = { [provider]: key.trim() }
      if (moves(m, provider)) {
        const def = (await api.get<{ default_models: Record<string, string> }>('/api/ask/options')).default_models[provider]
        const list = m.models[provider] ?? []
        const model = list.some(x => x.id === def) ? def : list[0]?.id
        if (model) body.models = { jarvis: { provider, model } }
      }
      if (body.keys || body.models) await api.put('/api/settings', body)
      key = ''
      done = true
      await Promise.all([refreshAskOptions(), loadOnboarding()])
    } catch (e) { error = (e as Error).message }
    finally { busy = false }
  }
</script>

<form class="ob-key" onsubmit={save}>
  <WinBody>
    {#if done}
      <div class="ob-key-head" role="status">
        <div class="ob-pet"><WiskitSprite pose="happy" motionOff={ui.motionOff} /></div>
        <div><h2>Wiskit is on</h2><Hint>Ask it about your saves in the Wiskit panel. Change the model in Settings &gt; Wiskit &amp; AI.</Hint></div>
      </div>
    {:else}
      <div class="ob-key-head">
        <div class="ob-pet"><WiskitSprite pose="idle" motionOff={ui.motionOff} /></div>
        <div><h2>Turn on Wiskit</h2><Hint>Wiskit describes, sorts and answers questions about your saves. It runs on your own AI account.</Hint></div>
      </div>
      <div class="ob-key-rows">
        <Label as="span" id="ob-prov">Provider</Label>
        <div class="seg" role="group" aria-labelledby="ob-prov">
          {#each PROVIDERS as [id, label] (id)}<button type="button" aria-pressed={provider === id} onclick={() => { provider = id; error = '' }}>{label}</button>{/each}
        </div>
        <Label as="span">1. Get a key</Label>
        <div><Button size="sm" onclick={openKeyPage}>Open {name}</Button></div>
        <Label for="ob-key-in">2. Paste it here</Label>
        <input class="inp" id="ob-key-in" type="password" autocomplete="off" spellcheck="false" data-autofocus bind:value={key} placeholder={saved ? 'Saved on this PC. Paste a new one to replace it' : `${name} API key`} />
      </div>
      <Hint class="ob-key-note">AI requests send your prompt and relevant library text, notes and chat context to {name}. Image features also send selected pictures or frames; audio transcription uses OpenAI. A configured endpoint or proxy receives the request. Provider charges apply separately. Keys are protected on this PC; provider retention and terms apply.</Hint>
      {#if error}<p class="err ob-key-err" role="alert">{error}</p>{/if}
    {/if}
  </WinBody>
  <div class="cw-foot">
    {#if done}
      <span class="sp"></span><Button variant="pri" bind:ref={doneKey} onclick={close}>Done</Button>
    {:else}
      <button class="linkk" type="button" onclick={() => openSettings('models')}>More AI options</button>
      <span class="sp"></span>
      <Button variant="pri" type="submit" disabled={busy || !ready}>{busy ? 'Saving…' : 'Turn on Wiskit'}</Button>
    {/if}
  </div>
</form>

<style>
  .ob-key { display: contents }
  .ob-key-head { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 16px; align-items: center; margin-bottom: 18px }
  .ob-pet { width: 96px; height: 56px }
  .ob-key-head h2 { margin: 0 0 6px; font: var(--type-heading); letter-spacing: -.02em }
  .ob-key-rows { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 12px 14px; align-items: center }
  .ob-key-rows .seg { justify-self: start }
  .ob-key :global(.ob-key-note) { margin-top: 14px }
  .ob-key-err { margin-top: 10px }
</style>
