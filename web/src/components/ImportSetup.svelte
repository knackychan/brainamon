<script lang="ts">
  // One browser-tool group for Setup, Settings, Scrapers and Help (library/scraper_runtime.py: Playwright in
  // its own Python 3.14 environment). `section` picks what shows: 'browser' the group, 'sessions' the site
  // logins, 'all' both with the video tools between. `lead`: Install browser tools may be the state's primary.
  import { onMount } from 'svelte'
  import { on } from '../lib/events.svelte'
  import { isDesktop, pickPath } from '../lib/pick'
  import { api } from '../lib/api'
  import { confirmWin } from '../lib/windows.svelte'
  import ToolsSettings from './ToolsSettings.svelte'
  import SiteSessions from './SiteSessions.svelte'
  import Button from './ui/Button.svelte'
  import Disclosure from './ui/Disclosure.svelte'
  import GroupBox from './ui/GroupBox.svelte'
  import Hint from './ui/Hint.svelte'
  import Label from './ui/Label.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import TextButton from './ui/TextButton.svelte'
  import ToolStatus from './ui/ToolStatus.svelte'
  let { section = 'all', lead = true, onready = (_ready: boolean) => {} }: { section?: 'all' | 'browser' | 'sessions'; lead?: boolean; onready?: (ready: boolean) => void } = $props()
  interface Runtime { path?: string; source?: string; managed?: boolean; environment?: string; python_path?: string; state: string; version?: string; step: string; error: string; supported: boolean; workers: boolean; python: boolean; winget: boolean }
  let runtime = $state<Runtime | null>(null), error = $state(''), busy = $state(false), skipped = $state(false)
  let checking = $state(false), doing = $state('')
  let editing = $state(''), folder = $state('')
  async function browse(kind: string) {
    editing = kind; folder = kind === 'environment' ? runtime?.environment ?? '' : ''
    if (isDesktop()) { const p = await pickPath('folder'); if (p) { folder = p; await selectFolder() } }
  }
  async function selectFolder() {
    busy = true; doing = 'select'; error = ''
    try { runtime = await api.post<Runtime>('/api/settings/scraper-runtime', { action: 'select', kind: editing, folder }); editing = ''; onready(runtime.state === 'ready') }
    catch (e) { error = (e as Error).message } finally { busy = false; doing = '' }
  }
  let disposed = false, polling = false
  async function check() {
    error = ''
    try { runtime = await api.get<Runtime>('/api/settings/scraper-runtime'); onready(runtime.state === 'ready'); if (runtime.state === 'installing') poll() }
    catch (e) { error = (e as Error).message; onready(false) }
  }
  async function poll() {
    if (polling) return
    polling = true
    try { while (!disposed && runtime?.state === 'installing') { await new Promise(r => setTimeout(r, 1500)); if (!disposed) await check() } }
    finally { polling = false }
  }
  // `doing` names the request in flight, for its progress line; a second click waits for it
  async function act(action: string) {
    if (busy) return
    busy = true; error = ''; doing = action
    try { runtime = await api.post<Runtime>('/api/settings/scraper-runtime', { action }); onready(runtime.state === 'ready'); if (runtime.state === 'installing') poll() }
    catch (e) { error = (e as Error).message }
    finally { busy = false; doing = '' }
  }
  async function recheck() {
    if (checking) return
    checking = true; onready(false)
    try { await check() } finally { checking = false }
  }
  async function removeTools() {
    const ok = await confirmWin({ title: 'Remove browser tools', msg: 'Remove the browser tools from this PC?', detail: 'Scrapers that use a browser stop working until you install the tools again (about 540 MiB). Your library, site logins and Python stay.', ok: 'Remove', danger: true })
    if (ok) act('remove')
  }
  const installing = $derived(runtime?.state === 'installing')
  const ready = $derived(runtime?.state === 'ready')
  const pending = $derived(checking || !runtime && !error)
  const playwrightState = $derived(pending || doing === 'select' ? 'checking' : runtime?.workers === false ? 'failed' : runtime?.state ?? 'failed')
  const line = $derived(!runtime ? 'Checking browser tools…' : runtime.workers === false ? 'This Brainamon installation is incomplete: reinstall the latest version to repair it.'
    : runtime.state === 'ready' ? `Ready: Playwright ${runtime.version} passed a browser check on this PC`
    : runtime.state === 'older' ? `Found an older Playwright ${runtime.version}: Install browser tools updates it to 1.61.0`
    : runtime.state === 'installing' ? `Installing: ${runtime.step}`
    : runtime.state === 'failed' ? 'Failed their check: retry, or keep working without them'
    : 'Missing: install them, or keep working without them')
  onMount(() => { if (section !== 'sessions') recheck(); const off = on('settings_changed', () => { if (section !== 'sessions') recheck() }); return () => { disposed = true; off() } })
</script>
{#if section !== 'sessions'}
  {#if !skipped}
    <GroupBox active={installing || busy} aria-label="Browser tools" aria-busy={checking || busy}>
      <Label as="span">Browser tools</Label>
      <div>
        {#if ready}<Status on role="status">Browser check passed. Automatic imports are available.</Status>
        {:else}<Hint>Optional: collects your saved Facebook, Instagram and Reddit posts in a separate browser window after you sign in. About 540 MiB; manual imports use your own browser and need none of it.</Hint>{/if}
        {#if runtime && !ready}<Hint role="status">{line}</Hint>{/if}
        <div class="chips">
          <ToolStatus name={runtime?.version && runtime.state !== 'missing' ? `Playwright ${runtime.version}` : 'Playwright'} state={playwrightState} />
          <ToolStatus name="Python 3.14" state={pending ? 'checking' : runtime?.python ? 'ready' : 'missing'} />
        </div>
        {#if runtime && !runtime.supported && !ready}<Hint>The installer supports Windows 10 (version 2004 or later) and Windows 11, x64 and ARM64.</Hint>{/if}
        {#if runtime && !runtime.python && !runtime.winget}<Hint><a href="https://www.python.org/downloads/windows/" target="_blank" rel="noopener noreferrer">Download Python</a>, then choose its folder under Your own environment.</Hint>{/if}
        <Disclosure summary="What gets installed, and your own environment">
          <Hint>Playwright 1.61.0 and Chromium in their own Python 3.14 environment, managed by Brainamon; allow 2 GiB free during installation. Python is a separate download. Project installs are separate: choose an existing environment containing Playwright 1.61.0 instead, and it is never installed over or removed. The browser check must pass before it is used.</Hint>
          {#if runtime?.path}<Hint class="tool-path">{runtime.source}: {runtime.path}</Hint>{/if}
          {#if runtime?.python_path}<Hint class="tool-path">{runtime.python_path}</Hint>{/if}
          <div class="frow">
            <Button size="sm" disabled={busy || checking || installing} onclick={() => browse('environment')} aria-label="Browse for Playwright environment">Browse for environment…</Button>
            <Button size="sm" disabled={busy || checking || installing} onclick={() => browse('python')} aria-label="Browse for Python 3.14">Browse for Python…</Button>
          </div>
          {#if editing}
            <label class="fl" for="browser-folder">{editing === 'environment' ? 'Python environment folder (contains Scripts/python.exe or bin/python)' : 'Folder containing Python 3.14'}</label>
            <div class="frow"><input class="inp" id="browser-folder" bind:value={folder} placeholder="Full folder path" /><Button size="sm" disabled={busy} onclick={selectFolder}>Use folder</Button><Button size="sm" onclick={() => editing = ''}>Cancel</Button></div>
            <Hint>Clear the path to return to automatic detection. Your existing environment is never installed over or removed.</Hint>
          {/if}
        </Disclosure>
      </div>
      <span></span>
      <div>
        {#if error || runtime?.error}<Hint tone="error" role="alert">{error || runtime?.error}</Hint>{/if}
        {#if checking}<Progress label="Looking for Python and checking Playwright with a local browser…" />{/if}
        {#if installing || busy}<Progress label={installing && runtime?.step ? runtime.step : doing === 'select' ? 'Checking the selected environment' : doing === 'python' ? 'Installing Python 3.14' : doing === 'remove' ? 'Removing browser tools' : 'Preparing browser tools'} />{/if}
        <div class="frow">
          {#if runtime && !ready}<Button variant={lead ? 'pri' : 'default'} size="sm" disabled={busy || checking || installing || !runtime.supported || !runtime.workers || !runtime.python} onclick={() => act('install')}>{runtime.state === 'failed' ? 'Retry browser tools' : 'Install browser tools'}</Button>{/if}
          {#if runtime && !runtime.python && runtime.winget && !ready}<Button size="sm" disabled={busy || checking || installing || !runtime.supported} onclick={() => act('python')}>Install Python 3.14</Button>{/if}
          {#if installing}<Button size="sm" disabled={busy} onclick={() => act('cancel')}>Cancel installation</Button>{/if}
          <TextButton disabled={busy || checking || installing} aria-label={checking ? undefined : 'Check browser tools again'} onclick={recheck}>{checking ? 'Checking…' : 'Check again'}</TextButton>
          {#if ready && runtime?.managed}<TextButton disabled={busy || checking} onclick={removeTools}>Remove browser tools…</TextButton>{/if}
          {#if section === 'all'}<TextButton onclick={() => skipped = true}>Skip for now</TextButton>{/if}
        </div>
      </div>
    </GroupBox>
  {:else}<Hint>Skipped. Links, notes and file imports work now.</Hint><div class="frow"><TextButton onclick={() => skipped = false}>Show browser setup</TextButton></div>{/if}
{/if}
{#if section === 'all'}<Disclosure summary="Download videos (optional, runs on this PC)"><ToolsSettings /></Disclosure>{/if}
{#if section === 'sessions'}<SiteSessions />
{:else if section !== 'browser'}<Disclosure summary="Connect a site only when needed"><SiteSessions /></Disclosure>{/if}
