<svelte:options runes />

<script lang="ts">
  // Setup step 2's tools: the browser tools and the video tools, the same groups Settings > Imports & downloads shows.
  // runes: with no rune left, Svelte would compile this in legacy mode, where the onb import is reactive and loops.
  import { onb } from '../lib/onboarding.svelte'
  import ToolsSettings from './ToolsSettings.svelte'
  import ImportSetup from './ImportSetup.svelte'
</script>

<ImportSetup section="browser" onready={ready => { onb.browser = ready }} />
<ToolsSettings onready={ready => { onb.tools = ready }} />
