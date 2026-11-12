<script lang="ts">
  import { onMount } from 'svelte'
  import { lang, t } from '../../../lib/i18n/index.ts'
  import { phoneWords } from '../../settings-words'
  import { mirrorSource, phoneStatus, solo } from '../../state.svelte'
  import { isApp } from '../../native'
  import PageKeys from '../../PageKeys.svelte'
  import LegalDocuments from '../../../components/LegalDocuments.svelte'
  import privacyFrench from '../../../../../mobile-shell/store/privacy-policy.fr.md?raw'
  import privacyTraditionalChinese from '../../../../../mobile-shell/store/privacy-policy.zh-Hant.md?raw'
  import { aboutLine } from '../../settings-lines'
  import MButton from '../../ui/MButton.svelte'
  import MHint from '../../ui/MHint.svelte'
  import MRow from '../../ui/MRow.svelte'
  import { DOWNLOAD_URL } from '../../../lib/product-links'
  import MCard from '../../ui/MCard.svelte'
  import { settings, readAppInfo } from '../../settings-facts.svelte'
  const m = mirrorSource
  const st = $derived(phoneStatus())
  const lead = $derived(!st?.action)
  const desktop = !m || solo
  onMount(() => { if (isApp) void readAppInfo() })
</script>

<PageKeys infoTitle={t('settings.about.desktop')}>{#snippet info()}
      <p>{t('settings.about.help')}</p>
      <p>{t('settings.about.pcHelp')}</p>
      <p>{t('settings.about.accountsHelp')}</p>
      <p>{t('settings.about.pairHelp')}</p>
    {/snippet}</PageKeys>
<div class="m-pad m-calm m-page"><h1 class="m-page-title">{t('settings.group.about')}</h1><p class="m-page-sub">{aboutLine({ desktop, version: settings.app?.version ?? '' }, phoneWords)}</p>
    {#if desktop}<MCard>
      <MRow wrap id="m-desktop" title={t('settings.about.windows')} desc={t('settings.about.features')}><MButton as="a" variant={lead ? 'pri' : 'default'} size="sm" href={DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">{t('settings.about.getApp')}</MButton></MRow>
    </MCard>{/if}
    <MCard>{#if isApp}
      <div id="m-app-info" class="m-stack-rows">
        {#if settings.app}
          <MRow wrap title={t('settings.about.version')} desc={settings.app.version} />
          <MRow wrap title={t('settings.about.build')} desc={settings.app.build} />
        {:else if settings.infoError}
          <MHint tone="error" role="alert">{settings.infoError}</MHint>
          <MButton size="sm" onclick={readAppInfo}>{t('common.retry')}</MButton>
        {:else}
          <MHint role="status">{t('settings.about.loading')}</MHint>
        {/if}
      </div>
    {:else}
      <MHint>{t('settings.about.previewHelp')}</MHint>
    {/if}
    </MCard>
    <MCard title={t('settings.about.privacy')}>
    <MHint>{t('settings.about.documentsHelp')}</MHint>
    <LegalDocuments policy={lang() === 'fr' ? privacyFrench : lang() === 'zh-Hant' ? privacyTraditionalChinese : undefined}
      policyLang={lang() === 'fr' ? 'fr' : lang() === 'zh-Hant' ? 'zh-Hant-TW' : 'en'} />
  </MCard></div>
