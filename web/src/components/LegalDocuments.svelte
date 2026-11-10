<script lang="ts">
  import privacy from '../../../mobile-shell/store/privacy-policy.md?raw'
  import license from '../../../LICENSE?raw'
  import notices from '../../../THIRD_PARTY_NOTICES.md?raw'
  import { t } from '../lib/i18n/index.ts'

  let { policy = privacy, policyLang = 'en' }: { policy?: string; policyLang?: 'en' | 'fr' | 'zh-Hant-TW' } = $props()
</script>

<div class="legal-documents">
  <p>{t('legal.label.contact')} <a href="mailto:me@fredtomas.com">me@fredtomas.com</a></p>
  <details>
    <summary>{t('legal.label.privacy')}</summary>
    <pre lang={policyLang}>{policy}</pre>
    {#if policyLang !== 'en'}
      <details>
        <summary>{t('legal.label.original')}</summary>
        <pre lang="en">{privacy}</pre>
      </details>
    {/if}
  </details>
  <details>
    <summary>{t('legal.label.license')}</summary>
    <pre lang="en">{license}</pre>
  </details>
  <details>
    <summary>{t('legal.label.notices')}</summary>
    <pre lang="en">{notices}</pre>
  </details>
</div>

<style>
  .legal-documents { min-width: 0; font: var(--type-paper); color: inherit }
  details { min-width: 0; margin-top: 12px }
  summary { min-height: 44px; padding: 10px 0; cursor: pointer; font-weight: 600 }
  summary:focus-visible { outline: 2px solid currentColor; outline-offset: 2px }
  pre { max-width: 75ch; margin: 0 0 16px; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit }
</style>
