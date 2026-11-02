<script lang="ts">
  import { openKeys } from '../lib/command-table'
  import { ui } from '../lib/ui.svelte'
  import { DONATE_URL, GOOGLE_PLAY_URL } from '../lib/product-links'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  import WinBody from './ui/WinBody.svelte'
  import WinFoot from './ui/WinFoot.svelte'
  import LegalDocuments from './LegalDocuments.svelte'
  let { close }: { close: () => void } = $props()
</script>

<WinBody>
  <div class="about">
    <img class="about-mark" src="/brand/icon-hero.svg" alt="" width="64" height="64" />
    <p><b>Brainamon</b> · Wiskit · CM-OS V6. Your library is stored on this computer. Optional AI sends content to your selected provider or configured server and is billed by that provider. Optional Google Drive sync stores an encrypted copy in your account. Link previews, downloads and updates also use the network.</p>
    <Hint>Library {ui.libCount.toLocaleString('en-US')} items. The server listens on 127.0.0.1 only.</Hint>
    <p>Take your library anywhere with the Brainamon mobile companion. The desktop app provides the full experience, including video analysis and Claude Code integration.</p>
    <Hint><a href={GOOGLE_PLAY_URL} target="_blank" rel="noopener noreferrer">Get the Android app on Google Play</a>. Pair it with this PC to browse your library on your phone.</Hint>
    <Hint>Brainamon is free software under GPL-3.0-only, copyright 2026 Frederic TOMAS. Support is optional. <a href={DONATE_URL} target="_blank" rel="noopener noreferrer">Support it on Ko-fi</a>.</Hint>
  </div>
  <LegalDocuments />
</WinBody>
<WinFoot>
  {#snippet start()}
  <Button onclick={openKeys}>Keyboard shortcuts</Button>
  {/snippet}
  <Button variant="pri" onclick={close}>Close</Button>
</WinFoot>
