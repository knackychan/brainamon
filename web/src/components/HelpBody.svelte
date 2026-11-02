<script lang="ts">
  // Help (Brainamon menu > Help): the getting-started checklist from GET /api/app/setup, then plain-
  // language help for buyers. App.svelte opens the welcome (WelcomeWin) at first start; Help reuses ImportSetup.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { runCmd } from '../lib/commands'
  import { openAdd } from '../lib/edit-commands'
  import { openImport, openScrapers, openSettings } from '../lib/io-commands.svelte'
  import { toast } from '../lib/ui.svelte'
  import ImportSetup from './ImportSetup.svelte'
  import { PROCESS_ACTIONS } from '../lib/processing'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  import Label from './ui/Label.svelte'
  import WinBody from './ui/WinBody.svelte'
  import WinFoot from './ui/WinFoot.svelte'

  let { close }: { close: () => void } = $props()
  interface Setup {
    frozen: boolean; data_dir: string; has_key: boolean; items: number; dismissed: boolean; cookies: boolean
    tools: { ffmpeg: boolean; yt_dlp: boolean }
  }
  let s = $state<Setup | null>(null)
  onMount(() => { api.get<Setup>('/api/app/setup').then(x => { s = x }).catch(e => toast((e as Error).message, 'w')) })

  async function dismiss() {
    try { await api.post('/api/app/setup/dismiss'); toast('Help stays in the Brainamon menu') } catch (e) { toast((e as Error).message, 'w') }
    close()
  }
  const mark = (ok: boolean) => (ok ? 'Done' : 'To do')

  const HELP: [string, string][] = [
    ['Save your first link', 'Open File > Add to Brainamon, paste a link, choose Library, then Save. Find it in the Library. No AI key or extra tool is needed.'],
    ['Write a note', 'Open File > Add to Brainamon, type your text, choose Note, then Save. Notes live in My Notes; choose Library when you want a link in your saved-item library.'],
    ['Import many saves (optional)', 'File > Import accepts scraper CSV or Brainamon JSON exports. Import Instagram Saved ZIP/JSON on the phone through More > Import. File > Scrapers is an advanced bulk-import tool: it copies a script for the browser console on Facebook, Instagram or YouTube, then watches Downloads for the resulting CSV.'],
    ['Choose a processing step', 'Select items and choose Process items in the selection tray, or open Process > Process items. With no selection, it uses the visible items. The chooser suggests a next step and shows how many items need each action. Completed items are skipped unless you explicitly include them. Review one step at a time; video analysis is optional. Click an item’s processing status in List view to review just that item.'],
    ...PROCESS_ACTIONS.map(a => [a.label, `${a.description} ${a.cost}`] as [string, string]),
    ['Link previews', 'New links fetch their preview automatically. Some Fetch link info and video requests need optional saved login access. The public Capture preview does not use those cookies; blocked previews do not remove saved links. Fetch link info uses a missing thumbnail as its signal; to refresh the caption of a link that already has a thumbnail, choose Include completed items.'],
    ['When cookies help', 'Many public videos, including Facebook reels, download without cookies. Settings > Imports & downloads > Site logins supplies optional signed-in access to Download videos, the yt-dlp part of Fetch link info, and Analyze videos when it must download a missing video. Once saved, cookies are supplied on these requests, including public links; the app does not wait for a login error. Automatic scrapers can also use matching imported cookies, or you can sign in in their browser. The public Add/Capture preview, manual scraping in your own browser, CSV/JSON imports, AI work on existing content and Google Drive sync do not use this cookie option.'],
    ['Set up video tools', 'Open Settings > Imports & downloads and press Check and set up. Brainamon checks FFmpeg, ffprobe, yt-dlp and Deno, installs or updates tools that need attention with Windows Package Manager, then checks them again. The official yt-dlp executable includes the YouTube EJS scripts. Working tools are kept. If automatic setup fails, use Open administrator terminal and approve the Windows permission prompt, finish there, then press Check and set up again. Advanced details contains existing-tool folder choices, check results and manual downloads. Saving links and notes needs none of these tools.'],
    ['Ask Wiskit', 'Start a conversation about saved content and get an answer with sources. The selection shortcut sends an opening question about the chosen items (the first 8 for a large selection). Quick mode searches; Deep mode reads further. This uses your configured Wiskit model and may incur charges. You can save a good answer as a note in Knowledge.'],
    ['Synthesize a note', 'Combine available descriptions, transcripts and reports into one saved note in Knowledge. Choose a topic and review the estimated AI cost before starting. Unlike Ask Wiskit, this creates a note directly. Uses your selection, or up to the first 30 visible items without a selection; items without usable text are skipped.'],
    ['Processing status', 'Missing steps are options, not a checklist you must finish. Describe makes a static summary from available post text, title and thumbnail; it can reuse a saved transcript. Analyze videos downloads the video if needed and examines sampled frames and/or its audio transcript. Text changes automatically refresh the search index, which may add embeddings charges. Index for search also checks for stale text even when an item already shows as indexed. Track running work in Jobs or Process > Show progress.'],
    ['API keys and costs', 'Brainamon has no account and no subscription: AI features use your own keys (Settings > Wiskit & AI), billed by the provider. Keys are stored in a file on this PC and never shown again in the app.'],
    ['Your phone', 'Settings > Backup & phones keeps an encrypted copy of the library in a hidden folder of your own Google Drive, for recovery and for the Brainamon phone app. It is off until you turn it on.'],
    ['Back up your library', 'Quit Brainamon from Settings > General or the tray menu (closing the window may only hide it). Copy the whole data folder shown in Settings > General. Item CSV export is not a full backup: it omits files, chats, Knowledge notes, settings and cloud keys. For full PC recovery, also protect the Brainamon settings folder in your Windows local app data; it contains sensitive API and cloud credentials.'],
    ['Uninstall', 'Uninstalling removes the app, never the data folder or your keys. Reinstall and point Settings > General at the same data folder to pick up where you left off.'],
    ['Something went wrong', 'Settings > General > Updates > Export diagnostics saves a zip on this PC. Review the zip before sharing: logs can contain item text. Nothing is sent automatically.'],
  ]
</script>

<WinBody>
  <Hint style="margin-bottom:12px">Getting started</Hint>
  {#if s}
    <div class="blist">
      <div class="brow" style="grid-template-columns:70px minmax(0,1fr) auto;cursor:default">
        <b>Done</b><span>Data folder: <span style="overflow-wrap:anywhere">{s.data_dir}</span></span>
        {#if s.frozen}<Button size="sm" onclick={() => openSettings('app')}>Change…</Button>{:else}<span></span>{/if}
      </div>
      <div class="brow" style="grid-template-columns:70px minmax(0,1fr) auto;cursor:default">
        <b>{mark(s.items > 0)}</b><span>{s.items ? `Your library holds ${s.items.toLocaleString('en-US')} items.` : 'Save your first link or write a note.'}</span>
        <span class="frow"><Button size="sm" onclick={() => openAdd()}>Add to Brainamon…</Button><Button size="sm" onclick={openImport}>Import…</Button><Button size="sm" onclick={openScrapers}>Scrapers…</Button></span>
      </div>
      <div class="brow" style="grid-template-columns:70px minmax(0,1fr) auto;cursor:default">
        <b>Optional</b><span>{s.has_key ? 'An AI key is set.' : 'Add a provider key only when you want AI features. Wiskit and Describe use the model you choose; transcription may need OpenAI or local Whisper.'}</span>
        <Button size="sm" onclick={() => openSettings('keys')}>API keys…</Button>
      </div>
    </div>
  {:else}
    <Hint>Loading…</Hint>
  {/if}
  <ImportSetup lead={false} />
  <div class="fg" style="margin-top:16px">
    {#each HELP as [h, t] (h)}<Label as="span">{h}</Label><Hint>{t}</Hint>{/each}
  </div>
</WinBody>
<WinFoot>
  {#snippet start()}
  <Button onclick={() => { close(); runCmd('setup') }}>Resume setup</Button>
  {#if s && !s.dismissed}<Button onclick={dismiss}>Don't show at start</Button>{/if}
  {/snippet}
  <Button variant="pri" onclick={close}>Close</Button>
</WinFoot>
