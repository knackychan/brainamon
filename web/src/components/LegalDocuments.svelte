<script lang="ts">
  import privacy from '../../../mobile-shell/store/privacy-policy.md?raw'
  import license from '../../../LICENSE?raw'
  import notices from '../../../THIRD_PARTY_NOTICES.md?raw'
</script>

<div class="legal-documents">
  <p>Contact Frederic TOMAS: <a href="mailto:me@fredtomas.com">me@fredtomas.com</a></p>
  <details>
    <summary>Privacy policy</summary>
    <pre>{privacy}</pre>
  </details>
  <details>
    <summary>Software license</summary>
    <pre>{license}</pre>
  </details>
  <details>
    <summary>Third-party notices</summary>
    <pre>{notices}</pre>
  </details>
</div>

<style>
  .legal-documents { min-width: 0; font: var(--type-paper); color: inherit }
  details { min-width: 0; margin-top: 12px }
  summary { min-height: 44px; padding: 10px 0; cursor: pointer; font-weight: 600 }
  summary:focus-visible { outline: 2px solid currentColor; outline-offset: 2px }
  pre { max-width: 75ch; margin: 0 0 16px; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit }
</style>
