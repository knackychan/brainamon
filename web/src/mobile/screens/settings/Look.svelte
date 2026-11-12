<script lang="ts">
  import { switchLanguage } from '../../language-switch.ts'
  import { LANGS, lang, t, type Choice, type Key } from '../../../lib/i18n/index.ts'
  import { phoneWords } from '../../settings-words'
  import { isDark, phone, setCardStyle, setMotionOff, cardStyles, toggleTheme, type CardStyle } from '../../state.svelte'
  import { secretsHaveFailures, secretsSaved } from '../../native'
  import PageKeys from '../../PageKeys.svelte'
  import { lookLine } from '../../settings-lines'
  import MHint from '../../ui/MHint.svelte'
  import MRow from '../../ui/MRow.svelte'
  import MToggle from '../../ui/MToggle.svelte'
  import MSeg from '../../ui/MSeg.svelte'
  import MCard from '../../ui/MCard.svelte'
  let dark = $state(isDark())
  let languageChoice = $state<Choice>((() => {
    try {
      const value = localStorage.getItem('bp-lang')
      return value === 'en' || value === 'fr' || value === 'zh-Hant' ? value : 'auto'
    } catch { return 'auto' }
  })())
  let changingLanguage = $state(false), languageError = $state('')
  const selectedLanguage = $derived(LANGS.find(entry => entry.id === lang())!)
  const languageDetail = $derived(languageChoice === 'auto' ? t('settings.language.resolved', { language: selectedLanguage.name })
    : !selectedLanguage.ready ? t('settings.language.preview', { language: selectedLanguage.name }) : '')
  async function changeLanguage(value: string) {
    if (value !== 'auto' && value !== 'en' && value !== 'fr' && value !== 'zh-Hant') return
    if (value === languageChoice || changingLanguage) return
    changingLanguage = true; languageError = ''
    const root = document.getElementById('m-app') as HTMLElement | null
    const wasInert = root?.inert ?? false
    if (root) root.inert = true
    let reloading = false
    try {
      const result = await switchLanguage(value, languageChoice, async () => {
        await secretsSaved()
        if (secretsHaveFailures()) throw new Error('Secure write failed')
      }, localStorage, () => location.reload())
      if (result.status === 'reloaded') { reloading = true; return }
      if (result.status === 'blocked') languageError = t(result.reason as Key)
      else if (result.status === 'storage-error') languageError = t('settings.language.storageError')
    } catch {
      languageError = t('settings.language.storageError')
    } finally {
      if (!reloading) { if (root) root.inert = wasInert; changingLanguage = false }
    }
  }

  const styleName = $derived(cardStyles().find(([v]) => v === phone.cardStyle)?.[1] ?? t('item.cardStyle.auto'))

</script>

<PageKeys infoTitle={t('settings.look.appearance')}>{#snippet info()}<p>{t('settings.look.nightHelp')}</p><p>{t('settings.look.cardHelp')}</p>{/snippet}</PageKeys>
<div class="m-pad m-calm m-page"><h1 class="m-page-title">{t('settings.group.look')}</h1><p class="m-page-sub">{lookLine(styleName, dark, phoneWords)}</p><MCard>
    <MRow wrap title={t('settings.language.title')} desc={languageDetail}>
      <MSeg label={t('settings.language.title')} size="sm" options={[["auto", t('settings.language.auto')], ["en", "EN"], ["fr", "FR"], ["zh-Hant", "繁中"]]} value={languageChoice} disabled={changingLanguage} onchange={changeLanguage} />
    </MRow>
    {#if languageError}<MHint tone="error" role="alert">{languageError}</MHint>{/if}
    <MRow wrap title={t('settings.look.night')}><MToggle label={t('settings.look.night')} on={dark} onchange={() => { toggleTheme(); dark = isDark() }} /></MRow>
    <MRow wrap title={t('settings.look.cardStyle')}><MSeg label={t('settings.look.cardStyle')} size="sm" options={cardStyles()} value={phone.cardStyle} onchange={v => setCardStyle(v as CardStyle)} /></MRow>
    <MRow wrap title={t('settings.look.motion')}><MToggle label={t('settings.look.motion')} on={!phone.motionOff} onchange={on => setMotionOff(!on)} /></MRow>
  </MCard></div>
