<script lang="ts">
  let { active = true }: { active?: boolean } = $props()
  import { onMount, onDestroy } from 'svelte'
  import { beginLanguageWork, languageWorkChanged, registerLanguageCheck } from '../../language-switch.ts'
  import { t } from '../../../lib/i18n/index.ts'
  import { phoneWords } from '../../settings-words'
  import { mirrorSource, phone, solo } from '../../state.svelte'
  import { secretsSaved } from '../../native'
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
      keyIn = { openai: '', anthropic: '' }
      keyFailed = ''; confirmClear = ''
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
  const savedKeys = $derived((phone.synced, aiTick, { openai: !!m?.pair.ai?.openai, anthropic: !!m?.pair.ai?.anthropic }))
  const providers: ['openai' | 'anthropic', string][] = [['openai', 'OpenAI'], ['anthropic', 'Anthropic']]
  let confirmClear = $state('')
  let savingKey = $state(''), keyFailed = $state('')
  async function saveKey(provider: 'openai' | 'anthropic', clear = false) {
    if (!m || savingKey || forgetting || forgetFailed || (keyFailed && keyFailed !== provider)) return
    if (!clear && !keyIn[provider].trim()) return
    if (clear && confirmClear !== provider) { confirmClear = provider; return }
    modelRead?.abort()
    const done = beginLanguageWork()
    savingKey = provider
    try {
      const previous = m.ai()
      if (previous) m.setAi(previous.provider, previous.model)
      const next = { ...m.pair }
      setAiKey(next, provider, clear ? '' : keyIn[provider])
      await secretsSaved()
      m.pair.ai = next.ai
      delete m.pair.t; delete m.pair.tx
      keyIn[provider] = ''
      confirmClear = ''; keyFailed = ''
      keysNote = t(clear ? 'settings.keys.cleared' : 'settings.keys.saved', { provider: provider === 'openai' ? 'OpenAI' : 'Anthropic' })
      aiTick++
    } catch { keyFailed = provider; keysNote = t(clear ? 'settings.keys.clearFailed' : 'settings.keys.failed') }
    finally { savingKey = ''; done() }
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
  <MCard>
        <MRow wrap class="m-provider" title={t('settings.keys.provider')} desc={ai?.providers.length === 2 ? undefined : t('settings.keys.providerHelp')}><MSeg label={t('settings.keys.provider')} size="sm" options={providers} value={ai?.provider ?? ''} disabled={!!savingKey || forgetting || forgetFailed} disabledOptions={providers.filter(([id]) => !savedKeys[id]).map(([id]) => id)} onchange={id => pickAi(id, ai?.model ?? '')} /></MRow>
        <MRow wrap title={t('settings.keys.model')}>{#if active}<MPicker label={t('settings.keys.model')} options={(ai?.providers.find(p => p.id === ai.provider)?.models ?? []).map(md => [md.id, md.label])} value={ai?.model || t('settings.keys.modelNeedsKey')} disabled={!ai || !!savingKey || forgetting || forgetFailed} onchange={value => { if (ai) pickAi(ai.provider, value) }} />{/if}
        </MRow>
        <MRow wrap title={t('settings.keys.lists')} desc={listNote || undefined}><MButton size="sm" onclick={refreshModels} disabled={!ai || listing || !!savingKey || forgetting || forgetFailed}>{listing ? t('settings.keys.checking') : t('settings.keys.refresh')}</MButton></MRow>
        <!-- ai.smart is "an OpenAI key is on this phone" (mirror.ts ai()): voice notes and search by meaning need it -->
        {#if ai && !ai.smart}<MHint>{t('settings.keys.addOpenai')}</MHint>{/if}
      {#if !ai && !solo && m.pair.t}
        <MHint>{t('settings.keys.waiting')}</MHint>
      {/if}
</MCard>
  <MCard id="m-ai">
    <MHint>{t('settings.keys.replaceHelp')}</MHint>
    {#each providers as [provider, label]}
      <MRow wrap title={t(provider === 'openai' ? 'settings.keys.openai' : 'settings.keys.anthropic')} desc={t(provider === 'openai' ? 'settings.keys.recommended' : 'settings.keys.optional')}><MButton as="a" size="sm" href={provider === 'openai' ? 'https://platform.openai.com/api-keys' : 'https://console.anthropic.com/settings/keys'} target="_blank" rel="noopener noreferrer" aria-label={t('settings.keys.getLabel', { provider: label })}>{t('settings.keys.get')}</MButton></MRow>
      <div class:saved={savedKeys[provider] && !keyIn[provider]} class="m-keyrow"><label class="m-fld"><input type="password" bind:value={keyIn[provider]} oninput={() => { confirmClear = ''; keysNote = ''; languageWorkChanged() }} placeholder={savedKeys[provider] ? t('settings.keys.savedPlaceholder') : provider === 'openai' ? 'sk-…' : 'sk-ant-…'} disabled={!!savingKey || forgetting || forgetFailed || (!!keyFailed && keyFailed !== provider)} aria-label={t(provider === 'openai' ? 'settings.keys.openaiLabel' : 'settings.keys.anthropicLabel')} autocomplete="off" spellcheck="false" /></label>
        <MButton size="sm" aria-label={t(provider === 'openai' ? 'settings.keys.saveOpenai' : 'settings.keys.saveAnthropic')} onclick={() => saveKey(provider)} disabled={!!savingKey || forgetting || forgetFailed || (!!keyFailed && keyFailed !== provider) || !keyIn[provider].trim()}>{savingKey === provider ? t('settings.keys.saving') : t('common.save')}</MButton></div>
      <div class="m-key-actions"><MTextButton tone="danger" aria-label={t('settings.keys.clearLabel', { provider: label })} onclick={() => saveKey(provider, true)} disabled={!!savingKey || forgetting || forgetFailed || (!!keyFailed && keyFailed !== provider) || (!savedKeys[provider] && !keyIn[provider])}>{confirmClear === provider ? t('settings.keys.confirmClear') : t('settings.keys.clear')}</MTextButton>{#if confirmClear === provider}<MTextButton disabled={!!savingKey || forgetting} onclick={() => { confirmClear = '' }}>{t('common.cancel')}</MTextButton>{/if}</div>
    {/each}
  </MCard>
  {#if ai || forgetFailed}<MCard><MDisclosure foot summary={t('common.showMore')} less={t('common.showLess')}>      {#if ai || forgetFailed}
        <MRow wrap title={t('settings.keys.onPhone')} desc={t('settings.keys.remainPaired', { providers: ai?.providers.map(p => p.label).join(', ') ?? '' })}><MTextButton tone="danger" onclick={forgetAi} disabled={forgetting || !!savingKey}>{forgetting ? t('settings.keys.forgetting') : forgetFailed ? t('common.retry') : confirmForgetAi ? t('settings.keys.confirmForget') : t('settings.keys.forget')}</MTextButton></MRow>
      {/if}
    </MDisclosure></MCard>{/if}
  <div role="status">{#if keysNote}<MHint>{keysNote}</MHint>{/if}</div>
</div>

<style>
  :global(.m-page .m-provider>.m-seg) { flex-basis: 100%; width: 100% }
  .m-key-actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 12px 8px }
</style>
