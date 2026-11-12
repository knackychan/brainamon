<script lang="ts">
  // Video tools (FFmpeg, ffprobe, yt-dlp, Deno, YouTube EJS) as one group: chips for the state, Check and set
  // up through winget (server/routes/settings.py), the per-tool rows under Advanced details. Shown in
  // Settings > Imports & downloads, Setup step 2 and Help.
  import { onMount, untrack } from 'svelte'
  import { api } from '../lib/api'
  import { on } from '../lib/events.svelte'
  import { isDesktop, pickPath } from '../lib/pick'
  import { toast } from '../lib/ui.svelte'
  import type { ToolsView, InstallView } from '../lib/setup'
  import type { Line } from '../lib/backup-state'
  import { videoLine } from '../lib/settings-lines'
  import { toolsReady, toolState } from '../lib/onboarding'
  import Button from './ui/Button.svelte'
  import Disclosure from './ui/Disclosure.svelte'
  import GroupBox from './ui/GroupBox.svelte'
  import Hint from './ui/Hint.svelte'
  import Label from './ui/Label.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import TextButton from './ui/TextButton.svelte'
  import ToolStatus from './ui/ToolStatus.svelte'
  // lead: Check and set up may be the state's primary (Settings gives the lead to one unfinished group at a time)
  let { initial, initialInstall, titleId = '', lead = true, onready = (_ready: boolean) => {}, onstatus = (_line: Line) => {} }: { initial?: ToolsView; initialInstall?: InstallView; titleId?: string; lead?: boolean; onready?: (ready: boolean) => void; onstatus?: (line: Line) => void } = $props()
  let tools = $state<ToolsView | null>(untrack(() => initial ?? null))
  let install = $state<InstallView | null>(untrack(() => initialInstall ?? null))
  let toolsDir = $state(untrack(() => initial?.tools_dir ?? ''))
  let toolsBusy = $state(false)
  let toolsError = $state('')
  let checking = $state(false)
  let editing = $state(''), folder = $state('')
  const names = ['ffmpeg', 'ffprobe', 'yt-dlp', 'deno']
  const CHIP: Record<string, string> = { ffmpeg: 'FFmpeg', ffprobe: 'ffprobe', 'yt-dlp': 'yt-dlp', deno: 'Deno' }
  async function chooseFolder(name: string) {
    editing = name; folder = tools?.tool_folders?.[name] ?? ''
    if (isDesktop()) { const picked = await pickPath('folder'); if (picked) { folder = picked; await saveFolder() } }
  }
  async function saveFolder() {
    toolsBusy = true; dirError = ''
    try { tools = await api.put<ToolsView>('/api/settings/tools', { tool: editing, folder: folder.trim() }); editing = ''; onready(toolsReady(tools)) }
    catch (e) { dirError = (e as Error).message } finally { toolsBusy = false }
  }
  let starting = $state(false)
  let startError = $state('')
  let dirError = $state('')
  let terminalBusy = $state(false), terminalOpened = $state(false)
  const installRunning = $derived(install?.state === 'running')
  const ready = $derived(!!tools && toolsReady(tools))
  const pending = $derived(checking || toolsBusy || !tools && !toolsError)
  const summary = $derived(videoLine({ tools, install, checking, starting, error: toolsError || startError || (terminalOpened ? 'Finish setup in the terminal, then check again.' : '') }))
  $effect(() => { onstatus(summary) })
  $effect(() => { if (tools) onready(toolsReady(tools)) })
  // Advanced details: what each tool is for, under its state
  const TOOL_HINT: Record<string, string> = {
    ffmpeg: 'Video analysis: extracts images for AI analysis and audio for transcription. Skip it if you only save links or notes.',
    ffprobe: 'Transcription: measures audio length so recordings can be split into upload-sized parts. Included with FFmpeg.',
    'yt-dlp': 'Video downloads: saves videos, thumbnails and captions from supported links. Saving a link itself does not need it.',
    deno: 'YouTube downloads: runs the JavaScript checks included with the official yt-dlp executable. Needs Deno 2.3 or newer.',
  }
  const youtubeLine = $derived.by(() => {
    const y = tools?.youtube
    if (!y) return 'Could not verify: Check again.'
    if (y.functional && y.deno && y.ejs === 'detected') return 'Ready: yt-dlp, Deno and the EJS scripts passed a local check'
    const missing = [!y.functional && 'yt-dlp did not pass its local check', !y.deno && 'Deno 2.3 or newer is missing', y.ejs === 'not detected' ? 'the EJS scripts are missing' : y.ejs !== 'detected' && 'the EJS scripts could not be verified'].filter(Boolean)
    return `Not ready: ${missing.join(', ')}`
  })
  const ejsState = $derived(pending ? 'checking' : tools?.youtube?.ejs === 'detected' ? 'ready' : tools?.youtube?.ejs === 'not detected' ? 'missing' : 'failed')
  function chipState(name: string): string {
    const t = tools?.tools.find(t => t.name === name)
    return pending ? 'checking' : t && toolState(t, install) === 'Installing' ? 'installing' : t?.state ?? 'failed'
  }
  // the group's one status line for screen readers (the chips are not live regions)
  const needs = $derived(!tools || pending ? [] : [...names.filter(n => chipState(n) !== 'ready').map(n => CHIP[n]), ...(ejsState === 'ready' ? [] : ['YouTube EJS'])])
  async function loadTools() {
    toolsError = ''
    try {
      const [t, i] = await Promise.all([api.get<ToolsView>('/api/settings/tools'), api.get<InstallView>('/api/settings/tools/install')])
      tools = t; install = i; toolsDir = t.tools_dir
      if (i.state === 'running') pollInstall()
    } catch (e) { toolsError = (e as Error).message; tools = null; install = null; toast(toolsError, 'w') }
  }
  async function checkAgain() {
    if (checking) return
    checking = true
    try { await loadTools() } finally { checking = false }
  }
  let polling = $state(false)
  let disposed = false
  async function pollInstall() {
    if (polling) return
    polling = true
    try {
    while (!disposed && install?.state === 'running') {
      await new Promise(r => setTimeout(r, 1500))
      if (disposed) return
      try { install = await api.get<InstallView>('/api/settings/tools/install') } catch (e) { toolsError = (e as Error).message; tools = null; install = null; return }
    }
    if (disposed) return
    tools = await api.get<ToolsView>('/api/settings/tools')
    if (install?.state === 'done') toast(toolsReady(tools) ? 'Video tools are ready' : 'Some tools still need attention. Open Advanced details.', toolsReady(tools) ? undefined : 'w')
    } catch (e) { toolsError = (e as Error).message; tools = null; toast(toolsError, 'w') } finally { polling = false }
  }
  // `starting` covers the request itself, so a second click cannot start a second install
  async function runInstall() {
    if (starting || installRunning || polling) return
    starting = true; startError = ''; terminalOpened = false
    try { install = await api.post<InstallView>('/api/settings/tools/install'); pollInstall() }
    catch (e) { startError = (e as Error).message }
    finally { starting = false }
  }
  async function copyInstall() {
    try { await navigator.clipboard.writeText(install?.command ?? ''); toast('Command copied') } catch { toast('Select the command and copy it by hand', 'w') }
  }
  async function openTerminal() {
    terminalBusy = true; startError = ''
    try { await api.post('/api/settings/tools/install/terminal'); terminalOpened = true }
    catch (e) { startError = (e as Error).message }
    finally { terminalBusy = false }
  }
  async function browseTools() {
    const p = await pickPath('folder')
    if (p) toolsDir = p
  }
  async function saveToolsDir() {
    toolsBusy = true; dirError = ''
    try {
      tools = await api.put<ToolsView>('/api/settings/tools', { tools_dir: toolsDir.trim() })
      toolsDir = tools.tools_dir
      toast(tools.all_found ? 'Tools folder saved: all tools found' : 'Tools folder saved')
    } catch (e) { dirError = (e as Error).message } finally { toolsBusy = false }
  }
  const blocked = $derived(!installRunning && (install?.state === 'error' || !!startError || terminalOpened))

  onMount(() => {
    if (!tools) checkAgain()
    else if (installRunning) pollInstall()
    const offs = [on('settings_changed', checkAgain), on('hello', checkAgain)]
    return () => { disposed = true; offs.forEach(off => off()) }
  })
</script>

<GroupBox active={starting || installRunning} aria-label="Video tools" aria-busy={checking || toolsBusy || starting || installRunning || polling}>
  <Label as="span" id={titleId || undefined} tabindex={titleId ? -1 : undefined}>Video tools</Label>
  <div>
    <Status state={summary.tone} role="status">{summary.text}</Status>
    {#if !ready}<Hint>For video downloads, analysis and transcription; links and notes need none. Check and set up downloads what is missing with Windows Package Manager; Windows may ask for permission.</Hint>
      {#if needs.length}<p class="sr" role="status">Video tools need attention: {needs.join(', ')}.</p>{/if}{/if}
    <div class="chips">
      {#each names as name (name)}<ToolStatus name={CHIP[name]} state={chipState(name)} />{/each}
      <ToolStatus name="YouTube EJS" state={ejsState} />
    </div>
    <Disclosure id={titleId ? 'set-s-tools-more' : undefined} tabindex={titleId ? -1 : undefined} summary="More: tool folders, install by hand">
      <div class="tool-checklist">
        {#each names as name (name)}
          {@const t = tools?.tools.find(t => t.name === name)}
          <div class="tool-row">
            <div class="tool-info">
              <div class="tool-title"><b>{name}</b><ToolStatus state={chipState(name)} /></div>
              <Hint>{TOOL_HINT[name]}</Hint>
              {#if t?.version}<Hint>Version {t.version}</Hint>{/if}
              {#if t?.path}<Hint class="tool-path">{t.path}</Hint>{/if}
              {#if t?.state === 'failed' || t?.state === 'older'}<Hint>{toolState(t, install)}</Hint>{/if}
            </div>
            <Button size="sm" disabled={checking || toolsBusy || installRunning} onclick={() => chooseFolder(name)} aria-label={`Browse for ${name}`}>Browse…</Button>
            {#if editing === name}
              <div class="tool-wide">
                <label class="fl" for={`folder-${name}`}>Folder containing {name}</label>
                <div class="frow"><input class="inp" id={`folder-${name}`} bind:value={folder} placeholder="Full folder path" /><Button size="sm" disabled={toolsBusy} onclick={saveFolder}>Use folder</Button><Button size="sm" onclick={() => editing = ''}>Cancel</Button></div>
                <Hint>Clear this path to use automatic detection again after restarting Brainamon.</Hint>
              </div>
            {/if}
          </div>
        {/each}
        <div class="tool-row">
          <div class="tool-info">
            <div class="tool-title"><b>YouTube EJS scripts</b><ToolStatus state={ejsState} /></div>
            <Hint>YouTube downloads: these challenge-solving scripts work with yt-dlp and Deno. Finding yt-dlp alone does not confirm they are installed.</Hint>
            {#if tools}<Hint>{youtubeLine}. This local check does not test access to a website.</Hint>{/if}
            <Hint>EJS is included in the official yt-dlp executable; there is no separate script folder to select. For a pip installation, update <code>yt-dlp[default]</code> in that same environment. <a href="https://github.com/yt-dlp/yt-dlp/wiki/EJS" target="_blank" rel="noopener noreferrer">Technical setup guide</a></Hint>
          </div>
        </div>
        <Disclosure summary="Install by hand"><Hint as="pre" class="set-cmd">{install?.command ?? 'Checking installation options…'}</Hint><Hint>Or download from <a href="https://ffmpeg.org/download.html" target="_blank" rel="noopener noreferrer">FFmpeg</a>, <a href="https://github.com/yt-dlp/yt-dlp/releases" target="_blank" rel="noopener noreferrer">yt-dlp</a> or <a href="https://deno.com/" target="_blank" rel="noopener noreferrer">Deno</a>, then browse to its folder.</Hint><div class="setup-actions"><Button size="sm" disabled={!install?.command} onclick={copyInstall}>Copy command</Button></div></Disclosure>
        <Disclosure summary="Shared tools folder">
          <Hint>Optional: use one folder for several tools. Individual tool folders take priority. Clearing a folder takes full effect after restarting Brainamon.</Hint>
          <div class="frow"><input class="inp" aria-label="Shared tools folder" bind:value={toolsDir} placeholder="Folder with your tools" />{#if isDesktop()}<Button size="sm" onclick={browseTools}>Browse…</Button>{/if}<Button size="sm" disabled={toolsBusy || toolsDir.trim() === tools?.tools_dir} onclick={saveToolsDir}>Use folder</Button></div>
        </Disclosure>
      </div>
    </Disclosure>
  </div>
  <span></span>
  <div>
    {#if toolsError || dirError || startError}<Hint tone="error" role="alert">{toolsError || dirError || startError}</Hint>{/if}
    {#if installRunning || starting}<Progress label={install?.step || 'Checking video tools'} />{/if}
    {#if install?.error && !installRunning}<Hint tone="error" role="alert">{install.error}</Hint>{/if}
    {#if blocked}
      {#if install?.winget}<Hint>Windows blocked setup or a tool still needs attention. If permission is needed, continue in an administrator terminal and approve the Windows prompt.</Hint>
      {:else}<Hint>Automatic setup needs <a href="https://apps.microsoft.com/detail/9nblggh4nns1" target="_blank" rel="noopener noreferrer">Microsoft App Installer</a>. Install or update it, then try again. Manual downloads are under More: tool folders, install by hand.</Hint>{/if}
      {#if terminalOpened}<Hint role="status">Terminal opened. Finish the commands there, then click Check and set up to verify the tools.</Hint>{/if}
    {/if}
    {#if checking || toolsBusy}<Progress label="Looking for tools and checking that they work…" />{/if}
    <div class="frow">
      <Button variant={ready || !lead ? 'default' : 'pri'} size="sm" disabled={starting || checking || toolsBusy || installRunning || polling || terminalBusy} onclick={runInstall}>{starting || installRunning || polling ? 'Setting up…' : 'Check and set up'}</Button>
      {#if blocked && install?.winget}<Button size="sm" disabled={terminalBusy || terminalOpened || starting || checking || polling} onclick={openTerminal}>{terminalBusy ? 'Opening…' : 'Open administrator terminal'}</Button>{/if}
      <TextButton disabled={checking || toolsBusy || installRunning} aria-label={checking ? undefined : 'Check video tools again'} onclick={checkAgain}>{checking ? 'Checking…' : 'Check again'}</TextButton>
    </div>
  </div>
</GroupBox>
