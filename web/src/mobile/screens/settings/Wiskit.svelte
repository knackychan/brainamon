<script lang="ts">
  let { active = true }: { active?: boolean } = $props()
  import { onMount, onDestroy } from 'svelte'
  import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from '../../language-switch.ts'
  import { t } from '../../../lib/i18n/index.ts'
  import { phoneWords } from '../../settings-words'
  import { devSolo, mirrorSource, phone, refresh, solo } from '../../state.svelte'
  import { isApp, secretsSaved } from '../../native'
  import { setAiKey } from '../../mirror/pairing'
  import PageKeys from '../../PageKeys.svelte'
  import { aiLine } from '../../settings-lines'
  import MButton from '../../ui/MButton.svelte'
  import MHint from '../../ui/MHint.svelte'
  import MRow from '../../ui/MRow.svelte'
  import MStatus from '../../ui/MStatus.svelte'
  import MSeg from '../../ui/MSeg.svelte'
  import MDisclosure from '../../ui/MDisclosure.svelte'
  import MTextButton from '../../ui/MTextButton.svelte'
  import MCard from '../../ui/MCard.svelte'
  import MPicker from '../../ui/MPicker.svelte'
  const m = mirrorSource!
  let aiTick = $state(0)
  const ai = $derived((phone.synced, aiTick, m?.ai() ?? null))
  let confirmForgetAi = $state(false)
  let forgetting = $state(false), forgetFailed = $state(false)
  async function forgetAi() {
    if (forgetting || savingKey) return
    modelRead?.abort()
    if (!confirmForgetAi && !forgetFailed) { confirmForgetAi = true; return }
    const done = beginLanguageWork()
    forgetting = true; keysNote = ''
    try {
      await m?.forgetKeys()
      savedKeys = { openai: false, anthropic: false }
      editingKeys = { openai: true, anthropic: true }
      keyIn = { openai: '', anthropic: '' }
      confirmForgetAi = false; forgetFailed = false
    } catch { forgetFailed = true; keysNote = t('settings.keys.forgetFailed') }
    finally { forgetting = false; aiTick++; done() }
  }
  function pickAi(provider: string, model: string) {
    const p = ai?.providers.find(x => x.id === provider)
    m?.setAi(provider, p?.models.some(x => x.id === model) ? model : p?.models[0]?.id ?? '')
    aiTick++
  }
  // Refresh: ask the providers which models the phone's keys can use (desktop: Settings > AI models)
  let listing = $state(false), listNote = $state('')
  let modelRead: AbortController | undefined
  $effect(() => { if (!active) modelRead?.abort() })
  onDestroy(() => modelRead?.abort())
  async function refreshModels() {
    if (!m || listing) return
    const done = beginLanguageWork()
    listing = true; listNote = ''
    const read = modelRead = new AbortController()
    const timeout = setTimeout(() => read.abort(new Error(t('settings.keys.modelTimeout'))), 30_000)
    try { listNote = await m.refreshModels(phoneWords, read.signal) }
    catch (e) { if (active) listNote = read.signal.reason instanceof Error && read.signal.reason.name !== 'AbortError' ? read.signal.reason.message : t('settings.keys.modelCancelled') }
    finally { clearTimeout(timeout); listing = false; aiTick++; done() }
  }
  const aiProvider = $derived(ai ? ai.providers.find(p => p.id === ai.provider)?.label ?? ai.provider : '')
  let keyIn = $state({ anthropic: '', openai: '' }), keysNote = $state('')
  let savedKeys = $state({ openai: !!m?.pair.ai?.openai, anthropic: !!m?.pair.ai?.anthropic })
  let editingKeys = $state({ openai: !m?.pair.ai?.openai, anthropic: !m?.pair.ai?.anthropic })
  const canSolo = isApp || devSolo                      // keys only in the app's encrypted storage
  let savingKey = $state('')
  async function saveKey(provider: 'openai' | 'anthropic') {
    if (!m || savingKey || forgetting || forgetFailed) return
    savingKey = provider
    try {
      const previous = m.ai()
      if (previous) m.setAi(previous.provider, previous.model)
      setAiKey(m.pair, provider, keyIn[provider])
      await secretsSaved()
      keyIn[provider] = ''
      savedKeys[provider] = true
      editingKeys[provider] = false
      keysNote = t('settings.keys.saved', { provider: provider === 'openai' ? 'OpenAI' : 'Anthropic' })
      aiTick++
    } catch { keysNote = t('settings.keys.failed') }
    finally { savingKey = '' }
  }
  onMount(() => registerLanguageCheck(() => keyIn.openai || keyIn.anthropic ? 'settings.language.unsavedKeys' : null))
</script>

{#if active}<PageKeys infoTitle={t('settings.group.ai')}>{#snippet info()}
        <p>{solo ? t('settings.keys.soloStorage') : t('settings.keys.pairedStorage')}</p>
        <p>{t('settings.keys.help')}</p>
        {#if ai}
          {#if solo}<p>{t('settings.keys.soloHelp')}</p>
          {:else}<p>{t('settings.keys.capabilities', { smart: t(ai.smart ? 'settings.keys.smartAvailable' : 'settings.keys.smartNeedsKey'), model: ai.synth || t('settings.keys.thePc'), n: m.synthMax })}</p>{/if}
        {:else if !solo}
          <p>{t('settings.keys.pairHelp')}</p>
          {#if m.pair.t}<p>{t('settings.keys.transferHelp')}</p>{/if}
        {/if}
        <p>{t('settings.keys.disclosure', { provider: ai?.providers.find(p => p.id === ai.provider)?.label ?? t('settings.keys.chosenProvider') })}</p>
        <p>{t('settings.keys.charges')}</p>
      {/snippet}</PageKeys>{/if}
<div class={active ? 'm-pad m-calm m-page' : 'm-settings-parked'}>
  <h1 class="m-page-title">{t('settings.group.ai')}</h1>
  <MStatus look="page" tone={ai ? 'done' : 'todo'} kind={ai ? 'done' : 'empty'} text={aiLine(aiProvider, solo, phoneWords)} />
  {#if ai || !solo}<MCard id={solo ? undefined : 'm-ai'}>
      {#if ai}
        <!-- one key: the provider is a fact, not a choice -->
        <MRow wrap title={t('settings.keys.provider')}>{#if ai.providers.length > 1}<MSeg label={t('settings.keys.provider')} size="sm" options={ai.providers.map(p => [p.id, p.label] as [string, string])} value={ai.provider} onchange={id => pickAi(id, ai.model)} />{:else}<span class="m-val">{ai.providers[0]?.label ?? ai.provider}</span>{/if}</MRow>
        <MRow wrap title={t('settings.keys.model')}>{#if active}<MPicker label={t('settings.keys.model')} options={(ai.providers.find(p => p.id === ai.provider)?.models ?? []).map(md => [md.id, md.label])} value={ai.model} onchange={value => pickAi(ai.provider, value)} />{/if}
        </MRow>
        <MRow wrap title={t('settings.keys.lists')} desc={listNote || undefined}><MButton size="sm" onclick={refreshModels} disabled={listing || forgetting || forgetFailed}>{listing ? t('settings.keys.checking') : t('settings.keys.refresh')}</MButton></MRow>
        <!-- ai.smart is "an OpenAI key is on this phone" (mirror.ts ai()): voice notes and search by meaning need it -->
        {#if !ai.smart}<MHint>{solo ? t('settings.keys.addOpenai') : t('settings.keys.pairOpenai')}</MHint>{/if}
      {:else if !solo && m.pair.t}
        <MHint>{t('settings.keys.waiting')}</MHint>
      {:else if !solo}
        <MHint>{t('settings.keys.pairAgain')}</MHint>
      {/if}
</MCard>{/if}
  {#if solo}<MCard id="m-ai">
        <!-- OpenAI first and marked recommended (decision 8); the aria-labels stay the accessible names -->
        <MRow wrap title={t('settings.keys.openai')} desc={t('settings.keys.recommended')} />
        <div class:saved={savedKeys.openai && !editingKeys.openai} class="m-keyrow"><label class="m-fld"><input type="password" bind:value={keyIn.openai} oninput={languageWorkChanged} placeholder={savedKeys.openai && !editingKeys.openai ? t('settings.keys.savedPlaceholder') : 'sk-…'} disabled={!editingKeys.openai || !!savingKey || forgetting || forgetFailed} aria-label={t('settings.keys.openaiLabel')} autocomplete="off" spellcheck="false" /></label>
          {#if savedKeys.openai && !editingKeys.openai}<MButton size="sm" aria-label={t('settings.keys.changeOpenai')} disabled={!!savingKey || forgetting || forgetFailed} onclick={() => { editingKeys.openai = true; keysNote = '' }}>{t('settings.keys.change')}</MButton>
          {:else}<MButton size="sm" aria-label={t('settings.keys.saveOpenai')} onclick={() => saveKey('openai')} disabled={!!savingKey || forgetting || forgetFailed || !keyIn.openai.trim()}>{savingKey === 'openai' ? t('settings.keys.saving') : t('common.save')}</MButton>{/if}</div>
        <MRow wrap title={t('settings.keys.anthropic')} desc={t('settings.keys.optional')} />
        <div class:saved={savedKeys.anthropic && !editingKeys.anthropic} class="m-keyrow"><label class="m-fld"><input type="password" bind:value={keyIn.anthropic} oninput={languageWorkChanged} placeholder={savedKeys.anthropic && !editingKeys.anthropic ? t('settings.keys.savedPlaceholder') : 'sk-ant-…'} disabled={!editingKeys.anthropic || !!savingKey || forgetting || forgetFailed} aria-label={t('settings.keys.anthropicLabel')} autocomplete="off" spellcheck="false" /></label>
          {#if savedKeys.anthropic && !editingKeys.anthropic}<MButton size="sm" aria-label={t('settings.keys.changeAnthropic')} disabled={!!savingKey || forgetting || forgetFailed} onclick={() => { editingKeys.anthropic = true; keysNote = '' }}>{t('settings.keys.change')}</MButton>
          {:else}<MButton size="sm" aria-label={t('settings.keys.saveAnthropic')} onclick={() => saveKey('anthropic')} disabled={!!savingKey || forgetting || forgetFailed || !keyIn.anthropic.trim()}>{savingKey === 'anthropic' ? t('settings.keys.saving') : t('common.save')}</MButton>{/if}</div>

      </MCard>{/if}
  {#if ai || forgetFailed}<MCard><MDisclosure foot summary={t('common.showMore')} less={t('common.showLess')}>      {#if ai || forgetFailed}
        <MRow wrap title={t('settings.keys.onPhone')} desc={t('settings.keys.remainPaired', { providers: ai?.providers.map(p => p.label).join(', ') ?? '' })}><MTextButton tone="danger" onclick={forgetAi} disabled={forgetting || !!savingKey}>{forgetting ? t('settings.keys.forgetting') : forgetFailed ? t('common.retry') : confirmForgetAi ? t('settings.keys.confirmForget') : t('settings.keys.forget')}</MTextButton></MRow>
      {/if}
    </MDisclosure></MCard>{/if}
  <div role="status">{#if keysNote}<MHint>{keysNote}</MHint>{/if}</div>
</div>
