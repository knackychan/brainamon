<script lang="ts">
  // Settings (V6 winSettings), in the first-run tour's order and words (SetupHub, OptionalSetup and
  // WiskitKeyWin: Wiskit, API keys, Sync; Turn on, Install, Check again, Save, Done; the neutral dot).
  // Wiskit: AI models (one Wiskit model, the search provider), API keys (.env through config.py: the page
  // only sees "set" or "not set" and can replace or remove a key), Local model, Claude Code
  // (Wiskit's third Ask mode, knowledge/claude_code.py; find, install link, sign in). Sync: Cloud (Google Drive, server/sync.py;
  // projects/mobile-app/PLAN.md). Library: Tools (FFmpeg, ffprobe, yt-dlp, Deno, browser tools), Downloads
  // (site logins, the scraper watch folder). Application: App (projects/desktop-app), License.
  // Keys, models, the local server and the watch folder wait for Save, and the footer names the sections
  // with edits not saved yet; everything else applies at once. Find a setting searches SECTIONS.
  import { onMount, setContext, tick, untrack } from 'svelte'
  import { api } from '../lib/api'
  import type { CloudView, Sizes } from '../lib/backup'
  import { refreshAskOptions } from '../lib/ask.svelte'
  import { confirmWin, topWin, wins } from '../lib/windows.svelte'
  import { runCmd } from '../lib/commands'
  import { on } from '../lib/events.svelte'
  import { loadInstallChecks, onb, openWiskitKey } from '../lib/onboarding.svelte'
  import { isDesktop, pickPath, type PickKind } from '../lib/pick'
  import { progress } from '../lib/progress'
  import { toast } from '../lib/ui.svelte'
  import { restartApp } from '../lib/restart'
  import WiskitModelPicker from '../components/WiskitModelPicker.svelte'
  import ToolsSettings from '../components/ToolsSettings.svelte'
  import ImportSetup from '../components/ImportSetup.svelte'
  import SiteSessions from '../components/SiteSessions.svelte'
  import LicenseSettings from '../components/LicenseSettings.svelte'
  import BackupPhonesPage from './BackupPhonesPage.svelte'
  import { openRecover } from '../lib/recover'
  import ObsidianSettings from '../components/ObsidianSettings.svelte'
  import type { ModelView, ModelChoice, SetupView, ToolsView } from '../lib/setup'
  import type { SettingsTab } from '../lib/io-commands.svelte'
  import Button, { QUIET_PRIMARY } from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import Status from '../components/ui/Status.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'
  import Disclosure from '../components/ui/Disclosure.svelte'
  import GroupBox from '../components/ui/GroupBox.svelte'
  import ItemList from '../components/ui/ItemList.svelte'
  import Segmented from '../components/ui/Segmented.svelte'
  import TextButton from '../components/ui/TextButton.svelte'
  import InfoTip from '../components/ui/InfoTip.svelte'
  import ToggleRow from '../components/ui/ToggleRow.svelte'

  let { close, tab = 'overview', section = '', navigation = 0 }: { close: () => void; tab?: SettingsTab; section?: string; navigation?: number } = $props()
  type Page = 'overview' | 'general' | 'ai' | 'imports' | 'obsidian' | 'backup'
  let cur = $state<Page>('overview')
  let visited = $state<Partial<Record<Page, boolean>>>({ overview: true })
  let navigated = -1
  let pendingSection = ''
  function focusSection() {
    void tick().then(() => requestAnimationFrame(() => {
      const el = pendingSection && document.getElementById(pendingSection)
      if (!el || !body?.contains(el)) return
      pendingSection = ''
      if (el instanceof HTMLDetailsElement) el.open = true
      for (let parent = el.parentElement; parent && parent !== body; parent = parent.parentElement) {
        if (parent instanceof HTMLDetailsElement) parent.open = true
      }
      el.scrollIntoView({ block: 'start' })
      el.focus({ preventScroll: true })
      // a newly opened window focuses its heading in the same frame: take focus back once
      requestAnimationFrame(() => { if (document.activeElement === heading || document.activeElement === document.body) el.focus({ preventScroll: true }) })
    }))
  }
  $effect(() => {
    const targetTab = tab, targetSection = section, request = navigation
    untrack(() => {
      if (navigated === request) return
      navigated = request
      const defaults: Partial<Record<SettingsTab, string>> = {
        keys: 'set-s-keys-main', models: 'set-s-models-wiskit', local: 'set-s-local',
        'claude-code': 'set-s-cc-program', tools: 'set-s-tools-video', downloads: 'set-s-dl-logins',
        sync: 'set-s-sync-account', app: 'set-s-app-folder', license: 'set-s-license',
      }
      const target = targetSection || defaults[targetTab] || ''
      // the Phone sync tab joined Backup & recovery as one page (Backup & phones)
      const page = SECTIONS.find(s => s.id === target)?.tab ?? (targetTab === 'phone' ? 'backup' : TABS.some(t => t.id === targetTab) ? targetTab as Page : 'overview')
      selectTab(page)
      pendingSection = target
      focusSection()
    })
  })
  interface Opt { id: string; label: string }
  // ── Claude Code: Wiskit's third Ask mode (server/routes/claude_code.py); installed builds bundle its MCP server ──
  interface CcTest { ok: boolean; state: string; version: string; message: string }
  interface CcView { available: boolean; path: string; detected: string; enabled: boolean; model: string; models: Opt[]; auto_approve: boolean; winget: boolean }
  let cc = $state<CcView | null>(null)
  let ccPath = $state('')
  let ccTest = $state<CcTest | null>(null)
  let ccBusy = $state(false)
  let ccTesting = $state(false)
  let ccError = $state('')
  let ccErrorAt = $state<'test' | 'set'>('test')      // shown under Test, or under the switches
  // the tabs in the tour's order of concepts; `apply` says when an edit takes effect
  interface TabDef { id: Page; label: string; group: string; help: string }
  const TABS: TabDef[] = [
    { id: 'overview', label: 'Overview', group: 'Your app', help: 'Everything here is optional.' },
    { id: 'general', label: 'General', group: 'Your app', help: 'How Brainamon starts, updates and is licensed.' },
    { id: 'ai', label: 'Wiskit & AI', group: 'Your app', help: 'One OpenAI key turns on Wiskit, search by meaning and voice transcription.' },
    { id: 'imports', label: 'Imports & downloads', group: 'Your library', help: 'Tools for downloading videos and importing saved posts. Links and notes need none.' },
    { id: 'obsidian', label: 'Obsidian & map', group: 'Your library', help: 'A vault Brainamon writes for you, and the topic map Wiskit uses.' },
    { id: 'backup', label: 'Backup & phones', group: 'Backup & devices', help: 'An encrypted copy of your library in your Google Drive, and the phones that read it.' },
  ]
  const GROUPS = $derived([...new Set(TABS.map(t => t.group))])
  const current = $derived(TABS.find(t => t.id === cur) ?? TABS[0])
  let body: HTMLDivElement | undefined = $state()
  // One primary per state (master rule 1): the footer's Done steps back while the visible tab shows a primary.
  let bodyPrimary = $state(false)
  function syncPrimary() { bodyPrimary = !!body?.querySelector('#set-panel > div:not([hidden]) .wkey.pri:not(:disabled)') }
  function selectTab(id: Page) {
    pendingSection = ''
    cur = id
    visited[id] = true
    body?.scrollTo(0, 0)
    void tick().then(syncPrimary)
    if (id === 'ai') void loadAudioTools()
    if (id === 'backup') void loadRecoveryStatus()
  }
  // Overview's Open links: the clicked link is now hidden, so focus moves to the tab's heading
  let heading: HTMLHeadingElement | undefined = $state()
  function openTab(id: Page) {
    selectTab(id)
    void tick().then(() => heading?.focus({ preventScroll: true }))
  }

  // ── Find a setting: every section, with the words someone might type for what is in it ──
  interface Sec { tab: Page; id: string; title: string; words: string }
  const SECTIONS: Sec[] = [
    { tab: 'ai', id: 'set-s-models-wiskit', title: 'Wiskit', words: 'wiskit model provider anthropic claude openai gpt freellmapi turn on describe sort summaries video analysis refresh model lists' },
    { tab: 'ai', id: 'set-s-models-search', title: 'Search', words: 'search embeddings meaning semantic index provider' },
    { tab: 'ai', id: 'set-s-keys-main', title: 'API keys', words: 'api key anthropic claude openai gpt get a key paste remove replace' },
    { tab: 'ai', id: 'set-s-ai-advanced', title: 'Other ways to use AI', words: 'advanced alternatives local freellmapi' },
    { tab: 'ai', id: 'set-s-keys-free', title: 'FreeLLMAPI', words: 'freellmapi free pool docker server address url api key' },
    { tab: 'ai', id: 'set-s-local', title: 'Local server', words: 'ollama lm studio local server address url api key model offline' },
    { tab: 'ai', id: 'set-s-cc-program', title: 'Claude Code program', words: 'claude code cli program path test login' },
    { tab: 'ai', id: 'set-s-cc-wiskit', title: 'Wiskit mode', words: 'use in wiskit claude code model' },
    { tab: 'ai', id: 'set-s-cc-approvals', title: 'Approvals', words: 'run requests without asking approve approval mcp tools' },
    { tab: 'backup', id: 'set-s-sync-account', title: 'Google account', words: 'google drive account sign in again connect disconnect switch account change account storage back up' },
    { tab: 'backup', id: 'set-s-sync-uploads', title: 'Backup', words: 'backup upload status files videos canvases favourites pause resume reset turn on turn off' },
    { tab: 'backup', id: 'set-s-sync-recovery', title: 'Recovery', words: 'recovery passphrase recovery file kit restore recover a library backup lost stolen formatted replacement pc keep this folder missing key wrong key lost key same folder' },
    { tab: 'obsidian', id: 'set-s-sync-vault', title: 'Vault sync with phone', words: 'obsidian vault notes sync phone conflicts deletions folder drop' },
    { tab: 'backup', id: 'set-s-sync-pair', title: 'Phones', words: 'phones add a phone pair qr code encryption key phone page remove all phones unpair lost stolen new key rotate license phone sync' },
    { tab: 'imports', id: 'set-s-tools-video', title: 'Video tools', words: 'ffmpeg ffprobe yt-dlp deno youtube ejs install winget video download analysis tools folder' },
    { tab: 'imports', id: 'set-s-tools-browser', title: 'Browser tools', words: 'browser tools playwright python scrapers saved posts facebook instagram reddit import' },
    { tab: 'obsidian', id: 'set-s-obsidian-vault', title: 'Obsidian vault', words: 'obsidian vault create new vault existing vault knowledge graph open in obsidian move fredorama adopted reset reclaim take over pictures' },
    { tab: 'obsidian', id: 'set-s-obsidian-map', title: 'Knowledge map', words: 'knowledge map topics refresh map rebuild stale summaries index coverage wiskit' },
    { tab: 'imports', id: 'set-s-dl-logins', title: 'Site logins', words: 'site logins cookies cookies.txt sign in private posts facebook instagram reddit youtube forget test link' },
    { tab: 'imports', id: 'set-s-dl-watch', title: 'Scraper imports', words: 'watch folder scraper csv downloads import' },
    { tab: 'general', id: 'set-s-app-folder', title: 'Library folder', words: 'version library folder data folder location move restart' },
    { tab: 'general', id: 'set-s-app-startup', title: 'Startup', words: 'start with windows startup wiskit desktop widget tray minimize reopen notice' },
    { tab: 'general', id: 'set-s-app-notify', title: 'Notifications', words: 'windows notifications toasts test alerts' },
    { tab: 'general', id: 'set-s-app-updates', title: 'Updates', words: 'updates update download install diagnostics support logs zip automatic' },
    { tab: 'general', id: 'set-s-app-about', title: 'About', words: 'about version privacy legal software license eula notices support contact quit stop exit background server' },
    { tab: 'general', id: 'set-s-license', title: 'Support & older receipts', words: 'support donate free license key activate remove replace sync gumroad receipt ko-fi' },
  ]
  let find = $state('')
  const found = $derived.by(() => {
    const q = find.trim().toLowerCase()
    if (!q) return []
    const words = q.split(/\s+/)
    const hits: { s: Sec; t: TabDef; rank: number }[] = []
    for (const s of SECTIONS) {
      if (s.id.startsWith('set-s-cc-') && !cc?.available) continue
      const t = TABS.find(x => x.id === s.tab)
      if (!t) continue
      const hay = `${s.title} ${t.label} ${t.group} ${s.words}`.toLowerCase()
      if (!words.every(w => hay.includes(w))) continue
      hits.push({ s, t, rank: s.title.toLowerCase().includes(q) ? 0 : t.label.toLowerCase().includes(q) ? 1 : 2 })
    }
    return hits.sort((a, b) => a.rank - b.rank)
  })
  async function jump(s: Sec) {
    find = ''
    selectTab(s.tab)
    pendingSection = s.id
    focusSection()
  }
  const jumpTo = (id: string) => { const s = SECTIONS.find(x => x.id === id); if (s) jump(s) }
  function findKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && found.length) { e.preventDefault(); jump(found[0].s) }
    else if (e.key === 'Escape' && find) { e.preventDefault(); e.stopPropagation(); find = '' }     // Escape again closes the window
  }

  async function loadCc() {
    try {
      const result = await api.get<CcView>('/api/claude-code')
      cc = result; ccPath = cc.path || cc.detected
    } catch { cc = null }
  }
  async function browseCc() {
    const p = await pickPath('claude')
    if (p) { ccPath = p; ccTest = null }
  }
  async function findCc() {
    ccError = ''
    await loadCc()
    if (cc && !cc.path && !cc.detected) { ccError = 'Claude Code was not found on this PC. Install it, or browse to claude.exe.'; ccErrorAt = 'test' }
    if (cc?.detected) { ccPath = cc.detected; ccTest = null }
  }
  async function loginCc() {
    ccBusy = true; ccError = ''
    try { await api.post('/api/claude-code/login', { path: ccPath.trim() }); toast('Finish signing in to Claude Code in the terminal window, then press Test') }
    catch (e) { ccError = (e as Error).message; ccErrorAt = 'test' } finally { ccBusy = false }
  }
  async function testCc() {
    ccBusy = true; ccTesting = true; ccError = ''
    try {
      const r = await api.post<CcView & { test: CcTest }>('/api/claude-code/test', { path: ccPath.trim() })
      ccTest = r.test
      cc = r
    } catch (e) { ccError = (e as Error).message; ccErrorAt = 'test' } finally { ccBusy = false; ccTesting = false }
  }
  async function setCc(o: { enabled?: boolean; model?: string; auto_approve?: boolean }) {
    ccBusy = true; ccError = ''
    try {
      cc = await api.put<CcView>('/api/claude-code', o)
      refreshAskOptions()                       // Wiskit shows or hides its Claude Code button
      if (o.enabled !== undefined) toast(o.enabled ? 'Claude Code mode is on in Wiskit' : 'Claude Code mode is off', o.enabled ? '' : 'off')
      if (o.auto_approve !== undefined) toast(o.auto_approve ? 'Claude Code requests now run without asking' : 'Claude Code requests wait for your click', o.auto_approve ? '' : 'off')
    } catch (e) { ccError = (e as Error).message; ccErrorAt = 'set'; loadCc() } finally { ccBusy = false }
  }
  const ccPassed = $derived(!!(ccTest?.ok && cc && ccPath.trim() === cc.path))
  const ccState = $derived.by((): { on: boolean; line: string } => {
    const c = cc, t = ccTest
    if (!c) return { on: false, line: '' }
    if (t) return { on: t.ok, line: `${t.ok ? 'Ready' : t.state === 'logged_out' ? 'Not logged in' : t.state === 'missing' ? 'Not found' : 'Error'}${t.version ? ` (${t.version})` : ''}: ${t.message}` }
    if (c.enabled && c.path) return { on: true, line: 'On in Wiskit. Press Test to check it again.' }
    if (!c.path && c.detected) return { on: false, line: 'Found on this PC. Press Test to use it.' }   // the field above shows where
    if (!c.path) return { on: false, line: 'Not found on this PC. Install Claude Code and log in, or choose claude.exe or claude.cmd.' }
    return { on: false, line: 'Not tested yet. Press Test to check the program and its login.' }
  })

  interface View {
    keys: Record<string, boolean>; plain: Record<string, string>; freellmapi_default_base: string
    downloads: Record<string, string>; default_watch_dir: string
    models: ModelView
  }
  let v = $state<View | null>(null)
  const NO_KEYS = { anthropic: '', openai: '', freellmapi: '', local: '' }
  let keyIn = $state<Record<string, string>>({ ...NO_KEYS })
  let clear = $state<Record<string, boolean>>({})
  let plain = $state<Record<string, string>>({})
  let dl = $state<Record<string, string>>({})
  let wiskit = $state<ModelChoice>({ provider: '', model: '' })
  let embed = $state('')
  let busy = $state(false)
  let saveError = $state('')
  let keySaving = $state('')
  let keyResult = $state<Record<string, { error?: string; saved?: boolean }>>({})
  let refreshing = $state(false)
  let refreshed = $state('')
  let refreshError = $state('')
  let linkError = $state('')
  let loadError = $state('')
  let appError = $state('')
  let cloudError = $state('')
  // Wiskit is on when its provider has a key: the same test as the tour (onboarding view, provider_problem)
  const wiskitOn = $derived(!!v && !!v.models.providers.find(p => p.id === wiskit.provider)?.has_key)
  let audioTools = $state<ToolsView | null>(null)
  let audioToolsError = $state('')
  async function loadAudioTools() {
    try { audioTools = await api.get<ToolsView>('/api/settings/tools'); audioToolsError = '' }
    catch (e) { audioTools = null; audioToolsError = (e as Error).message }
  }
  const audioReady = $derived(!!audioTools && ['ffmpeg', 'ffprobe'].every(name => audioTools?.tools.some(t => t.name === name && t.state === 'ready')))
  // the tabs with edits that wait for Save
  const same = (a?: string | null, b?: string | null) => (a ?? '') === (b ?? '')
  const keyEdited = (k: string) => !!keyIn[k]?.trim() || (!!clear[k] && !!v?.keys[k])
  const dirty = $derived.by((): Page[] => {
    const x = v
    if (!x) return []
    const out: Page[] = []
    if (wiskit.provider !== x.models.jarvis.provider || wiskit.model !== x.models.jarvis.model || embed !== x.models.embed_provider) out.push('ai')
    if (['anthropic', 'openai', 'freellmapi'].some(keyEdited) || !same(plain.freellmapi_base, x.plain.freellmapi_base)) out.push('ai')
    if (keyEdited('local') || !same(plain.local_base, x.plain.local_base) || !same(plain.local_model, x.plain.local_model)) out.push('ai')
    if (Object.keys(x.downloads).some(k => !same(dl[k], x.downloads[k]))) out.push('imports')
    return out
  })
  const dirtyNames = $derived(TABS.filter(t => dirty.includes(t.id)).map(t => t.label))
  // master rule 1: while edits wait for Save, Save leads and every other primary steps back (`keep` opts out)
  setContext(QUIET_PRIMARY, () => dirty.length > 0)
  // OpenAI drafts take precedence; otherwise the footer owns non-key edits and one visible key can lead.
  const settingsEdited = $derived(!!v && (wiskit.provider !== v.models.jarvis.provider || wiskit.model !== v.models.jarvis.model || embed !== v.models.embed_provider
    || !same(plain.freellmapi_base, v.plain.freellmapi_base) || !same(plain.local_base, v.plain.local_base) || !same(plain.local_model, v.plain.local_model)))
  const keyTyped = $derived(Object.values(keyIn).some(x => !!x?.trim()))
  let advancedOpen = $state(false)
  const primaryKey = $derived(keyIn.openai?.trim() ? 'openai' : !settingsEdited && !dirty.includes('imports')
    ? ['anthropic', ...(advancedOpen ? ['freellmapi', 'local'] : [])].find(k => keyIn[k]?.trim()) ?? '' : '')

  interface AppView { version: string; frozen: boolean; automatic_updates: boolean; data_dir: string; data_dir_next: string; autostart: boolean; widget: boolean; tray: boolean; warm: boolean; notice: boolean; toasts: Toasts; can_quit: boolean }
  interface Toasts { on: boolean; jobs: boolean; approval: boolean; claude: boolean; capture: boolean }
  const TOAST_KINDS: [keyof Omit<Toasts, 'on'>, string][] = [
    ['jobs', 'A job finishes or fails'], ['approval', 'Claude Code is waiting for your OK'],
    ['claude', 'Claude Code did something'], ['capture', 'Something arrives through Wiskit or the scraper'],
  ]
  let appv = $state<AppView | null>(null)
  let appBusy = $state(false)
  let quitting = $state(false)
  let newData = $state('')
  let diag = $state('')
  let diagBusy = $state(false)
  let diagError = $state('')
  let testing = $state(false)
  let testLine = $state('')
  let testFailed = $state(false)
  let changingFolder = $state(false)                  // Library folder: Use another folder… opened the field
  let logins = $state<number | null>(null)             // saved site logins, from SiteSessions' oncount
  let addingLogin = $state(false)                      // SiteSessions' add flow is open: it leads Imports

  // Overview: the Obsidian vault and whether a phone has synced, from the setup view; tools from the install checks
  type SetupFacts = Omit<SetupView, 'tools' | 'tool_status' | 'tool_install'>
  let setupv = $state<SetupFacts | null>(null)
  function loadSetup() {
    api.get<SetupFacts>('/api/app/setup?include_tools=false').then(s => { setupv = s }).catch(() => {})
    void loadInstallChecks().catch(() => {})
  }
  interface NextStep { line: string; key: string; run: () => void }
  // each key lands on the group that does the step; a build without Google sign-in skips the Drive steps
  const nextStep = $derived.by((): NextStep | null => {
    if (v && !wiskitOn) return { line: 'Add an AI key so Wiskit can answer, describe and summarize.', key: 'Turn on Wiskit', run: () => openWiskitKey(v?.models.jarvis.provider) }
    if (!onb.tools) return { line: 'Set up the video tools for downloads, analysis and transcription.', key: 'Set up video tools…', run: () => jumpTo('set-s-tools-video') }
    if (cloud && !cloud.signed_in && cloud.configured) return { line: 'Back up your library to your own Google Drive, encrypted.', key: 'Back up to Google Drive…', run: () => jumpTo('set-s-sync-account') }
    if (cloud?.signed_in && !cloud.running && recoveryReady && !recoveryRestored) return { line: 'Turn on backup so each change backs up to Google Drive.', key: 'Turn on backup…', run: () => jumpTo('set-s-sync-uploads') }
    if (cloud?.running && recoveryReady && !onb.recovery && !recoveryRestored) return { line: 'Create a recovery passphrase to get this library back if the PC is lost.', key: 'Create recovery passphrase…', run: () => jumpTo('set-s-sync-recovery') }
    if (cloud?.licensed && cloud.signed_in && setupv && !setupv.phone_seen) return { line: 'Add your phone to read your library anywhere.', key: 'Add a phone…', run: () => jumpTo('set-s-sync-pair') }
    return null
  })

  async function exportDiagnostics() {
    diagBusy = true; diagError = ''
    try { diag = (await api.post<{ path: string }>('/api/app/diagnostics')).path } catch (e) { diagError = (e as Error).message } finally { diagBusy = false }
  }
  function revealDiag() {
    diagError = ''
    api.post('/api/reveal', { path: diag }).catch(e => { diagError = (e as Error).message })
  }

  // Installed app only: point location.json at another data folder (nothing is moved; next start).
  async function setDataDir() {
    if (!newData.trim()) return
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/data-dir', { path: newData.trim() }); newData = ''; toast(appv.can_quit ? 'Restart Brainamon to open that library folder' : 'Brainamon uses that data folder from the next start') }
    catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }
  async function browseData() {
    const p = await pickPath('folder')
    if (p) newData = p
  }

  async function setAutostart(on: boolean) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/autostart', { on }); toast(on ? 'Brainamon will start with Windows' : 'Start with Windows is off', on ? '' : 'off') }
    catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }
  interface Upd { current: string; latest?: string; newer?: boolean; notes?: string; size?: number; error?: string }
  let upd = $state<Upd | null>(null)
  let updState = $state<'' | 'checking' | 'downloading' | 'ready' | 'installing'>('')
  let updName = ''
  let updPct = $state(0)
  let updError = $state('')
  let updLater = $state(false)                        // Later: the ready update stops asking until the window reopens
  interface DlStatus { state: string; done: number; total: number; name: string; error: string }
  async function checkUpdate() {
    updState = 'checking'; updError = ''
    try { upd = await api.get<Upd>('/api/app/update') }
    catch (e) { updError = (e as Error).message; updState = ''; return }
    await loadUpdate()
  }
  type UpdateStatus = DlStatus & Upd & { version: string; automatic: boolean }
  function takeUpdate(st: UpdateStatus) {
    if (updState === 'installing') return
    if (st.latest || st.current) upd = { ...st, error: undefined }
    updName = st.name
    updState = ['checking', 'downloading', 'ready'].includes(st.state) ? st.state as typeof updState : ''
    updPct = st.total ? Math.floor(st.done / st.total * 100) : 0
    updError = st.error || ''
  }
  async function loadUpdate() {
    try { takeUpdate(await api.get<UpdateStatus>('/api/app/update/status')) } catch { /* retry on the next event */ }
  }
  async function downloadUpdate() {
    updError = ''
    try { takeUpdate(await api.post<UpdateStatus>('/api/app/update/download')) }
    catch (e) { updError = (e as Error).message }
  }
  async function setAutomatic(on: boolean) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/update/automatic', { on }) }
    catch (e) { updError = (e as Error).message } finally { appBusy = false }
  }
  async function installUpdate() {
    updState = 'installing'; updError = ''
    try {
      await api.post('/api/app/update/install', { name: updName })
      toast('Installing the update: Brainamon restarts when it is done')
      setTimeout(() => window.pywebview?.api?.close?.(), 800)
    } catch (e) { updError = (e as Error).message; updState = 'ready' }
  }
  async function setWidget(on: boolean) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/widget', { on }); toast(on ? 'Wiskit is on your desktop' : 'Wiskit left the desktop', on ? '' : 'off') }
    catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }
  async function setTray(on: boolean) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/tray', { on }); toast(on ? 'Minimizing now goes to the tray' : 'Minimizing stays on the taskbar', on ? '' : 'off') }
    catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }
  async function setWarm(on: boolean) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/warm', { on }); toast(on ? 'The window stays warm in the tray' : 'The window closes when it goes to the tray', on ? '' : 'off') }
    catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }

  async function setNotice(on: boolean) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/notice', { on }); toast(on ? 'You will get a notice when Brainamon goes to the tray' : 'No notice when Brainamon goes to the tray', on ? '' : 'off') }
    catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }
  async function setToasts(o: Partial<Toasts>) {
    appBusy = true
    try { appv = await api.put<AppView>('/api/app/toasts', o) } catch (e) { toast((e as Error).message, 'w') } finally { appBusy = false }
  }
  async function testToast() {
    testing = true; testLine = ''
    try { await api.post('/api/app/toasts/test'); testFailed = false; testLine = 'Sent. If nothing appears, check the notification settings of Windows.' }
    catch (e) { testFailed = true; testLine = (e as Error).message } finally { testing = false }
  }
  let restarting = $state(false)
  async function restart() {
    appBusy = true; restarting = true
    try { await restartApp() } catch (e) { toast((e as Error).message, 'w'); appBusy = false; restarting = false }
  }
  async function quitApp() {
    const ok = await confirmWin({ title: 'Quit completely', msg: 'Stop Brainamon, including its background server?', detail: 'Jobs, uploads, vault sync and Wiskit on the desktop stop until you start Brainamon again. Closing the window alone keeps the background server running.', ok: 'Quit completely', danger: true })
    if (!ok) return
    appBusy = true; quitting = true
    try {
      await api.post('/api/app/quit')
      toast('Brainamon stopped')
      window.pywebview?.api?.close?.()
    } catch (e) { toast((e as Error).message, 'w'); appBusy = false; quitting = false }
  }

  // ── Cloud: Google Drive. The Backup & phones page (BackupPhonesPage.svelte) shows and drives it; this window keeps the status
  // for it, for the Obsidian tab's vault sync and for the Overview, and the recovery facts the Overview needs. ──
  let recoveryConfigured = $state(false)
  let recoveryReady = $state(false)
  let recoveryRestored = $state(false)
  async function loadRecoveryStatus() {
    try {
      const r = await api.get<{ configured: boolean; restored: boolean; enrolled: boolean }>('/api/cloud/recovery')
      recoveryConfigured = r.configured; recoveryRestored = r.restored; onb.recovery = r.enrolled; recoveryReady = true
    } catch { recoveryReady = false }
  }
  let cloud = $state<CloudView | null>(null)
  let backupForm = $state(false)               // a form of the page is open (a danger key is its submit): Done steps back
  let recoverPrimary = $state(false)           // the page's summary already offers Recover this backup / Unlock backup: the footer's link steps back
  let sizes = $state<Sizes | null>(null)
  let cloudBusy = $state(false)
  let cloudNow = $state(Date.now())
  let cloudErr = $state<{ where: string; msg: string } | null>(null)
  const mb = (b: number) => b >= 1e9 ? `${(b / 1073741824).toFixed(1)} GB` : `${Math.max(b ? 0.1 : 0, b / 1048576).toFixed(1)} MB`
  const when = (ms: number) => ms ? new Date(ms).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'never'
  // the last `cloud` event: an answer read before it (a lower seq) keeps its state fields
  let cloudSnap: Partial<CloudView> | null = null
  function takeView(v: CloudView) {
    cloud = cloudSnap && v.seq < (cloudSnap.seq ?? 0) ? { ...v, ...cloudSnap } : v
  }
  // `pending` shows at once; the answer or a `cloud` event replaces it. A failure rolls it back unless the
  // server has moved on since (a newer seq), and shows where it happened (`where`: the section's actions)
  async function cloudDo(path: string, body?: unknown, pending?: Partial<CloudView>, where = 'phone'): Promise<boolean> {
    cloudBusy = true; cloudErr = null
    const before = cloud
    if (cloud && pending) cloud = { ...cloud, ...pending }
    try { takeView(await api.post<CloudView>(path, body)); return true } catch (e) {
      if (before && cloud?.seq === before.seq) cloud = before
      cloudErr = { where, msg: (e as Error).message }; return false
    } finally { cloudBusy = false }
  }
  // Drop a phone from vault sync (spec 1b decision 5): asks beside the button, then its file list leaves Drive
  async function dropDevice(device: string) {
    const ok = await confirmWin({ title: 'Drop this phone from vault sync?', msg: `${device} is forgotten: its file list leaves Drive and vault sync stops waiting for it.`,
                                  detail: 'Nothing on the phone is deleted. The PC forgets this phone; it can rejoin by syncing again.', ok: 'Drop', danger: true })
    if (ok) await cloudDo('/api/cloud/vault/drop', { device }, undefined, 'vault')
  }

  // the Obsidian vault sync: its own On / Off beside the phone mirror, on the same Google sign-in
  const vaultLine = $derived.by(() => {
    const c = cloud
    if (!c) return ''
    if (!c.licensed) return 'Update Brainamon on this PC for payment-free vault sync.'
    if (c.vault_state === 'starting') return c.state === 'signing-in' ? 'Waiting for the Google sign-in.' : 'Starting: comparing the vault with the phone.'
    if (c.vault_state === 'stopping') return 'Stopping vault sync. Finishing requests already in progress.'
    if (c.vault_state === 'syncing') { const pr = progress(c.vault_done, c.vault_total, c.vault_since); return `${c.vault_step}: ${c.vault_done} of ${c.vault_total} files${pr.left ? `, ${pr.left}` : ''}.` }
    if (c.vault_state === 'brake') return 'Held: this round would delete many files.'
    if (c.vault_state === 'error') return 'Stopped on an error. The reason is below.'
    if (c.vault_running) return c.vault_skipped_note ? `Vault sync is on. ${c.vault_skipped_note}` : 'Vault sync is on. Up to date.'
    return c.vault.on ? 'Vault sync is on but not running.' : 'Vault sync is off.'
  })
  const vaultMoving = $derived(!!cloud && (cloud.vault_state === 'starting' || cloud.vault_state === 'stopping'))
  const vaultPct = $derived(cloud?.vault_state === 'syncing' && cloud.vault_total ? progress(cloud.vault_done, cloud.vault_total, cloud.vault_since).pct : undefined)
  // the summary line of Obsidian & map's Phone sync row
  const vaultSummary = $derived.by((): { on: boolean; text: string } => {
    const c = cloud
    if (!c) return { on: false, text: 'Checking…' }
    if (!c.licensed) return { on: false, text: 'PC update needed' }
    const on = c.vault_running && !['stopping', 'brake', 'error'].includes(c.vault_state)
    return { on, text: c.vault_running ? `On${c.vault_last ? ` · last ${when(c.vault_last)}` : ''}` : 'Off' }
  })
  async function cloudOpt(o: Partial<CloudView['options']> | { phone_url: string }, where = 'phone') {
    cloudErr = null
    try { takeView(await api.put<CloudView>('/api/cloud/options', o)) } catch (e) { cloudErr = { where, msg: (e as Error).message } }
  }
  // a transition the server is still in: account and sync actions wait for it
  const cloudMoving = $derived(!!cloud && ['signing-in', 'starting', 'stopping', 'disconnecting'].includes(cloud.state))

  function load(x: View) {
    v = x
    plain = { ...x.plain }
    dl = { ...x.downloads }
    wiskit = { ...x.models.jarvis }
    embed = x.models.embed_provider
    focusSection()
  }
  function resetKeys() {
    keyIn = { ...NO_KEYS }
    clear = {}
    keyResult = {}
  }
  function discard() {
    if (v) load(v)
    resetKeys()
    saveError = ''
  }
  function loadSettings() {
    loadError = ''
    api.get<View>('/api/settings').then(load).catch(e => { loadError = (e as Error).message })
  }
  // another window saved settings (Turn on Wiskit, a site login): show it, and keep edits that wait for Save
  async function refreshView() {
    if (busy) return
    try {
      const x = await api.get<View>('/api/settings')
      if (dirty.length) v = x
      else load(x)
    } catch { /* the window keeps what it shows */ }
  }
  function loadApp() {
    appError = ''
    api.get<AppView>('/api/app').then(a => { appv = a; focusSection() }).catch(e => { appError = (e as Error).message })
  }
  // Also used after a reconnect: a restarted server counts seq from 0 again.
  function loadCloud() {
    cloudError = ''
    api.get<CloudView>('/api/cloud').then(c => { cloud = c; cloudSnap = null; focusSection() }).catch(e => { cloudError = (e as Error).message })
  }
  onMount(() => {
    const observer = new MutationObserver(() => { syncPrimary(); if (pendingSection) focusSection() })
    if (body) observer.observe(body, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'class', 'disabled'] })
    syncPrimary()
    loadApp()
    loadSettings()
    loadRecoveryStatus()
    loadCloud()
    loadUpdate()
    const updateTimer = setInterval(() => { cloudNow = Date.now(); loadUpdate() }, 2000)
    api.get<Sizes>('/api/cloud/sizes').then(z => { sizes = z }).catch(() => {})
    loadCc()
    loadSetup()
    const offs = [
      on('hello', () => { loadCloud(); loadUpdate() }),
      on('update', takeUpdate),
      on('cloud', (d: Partial<CloudView>) => {
        if (!cloud || (d.seq ?? 0) < cloud.seq) return       // older than what the window shows
        cloudSnap = d
        cloud = { ...cloud, ...d }
      }),
      on('settings_changed', () => { refreshView(); if (visited.ai) void loadAudioTools(); loadSetup() }),
    ]
    return () => { observer.disconnect(); clearInterval(updateTimer); offs.forEach(off => off()) }
  })

  const KEYS: [string, string][] = [['openai', 'OpenAI'], ['anthropic', 'Anthropic'], ['freellmapi', 'FreeLLMAPI key']]
  const KEY_NAMES: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI', freellmapi: 'FreeLLMAPI', local: 'Local server' }
  function keyState(k: string): string {
    const typed = !!keyIn[k]?.trim(), saved = !!v?.keys[k]
    if (keySaving === k) return 'Saving on this PC…'
    if (typed) return saved ? 'New key: press Save key to replace the saved one' : 'New key: press Save key to store it on this PC'
    if (clear[k] && saved) return 'Removal pending: press Confirm removal'
    return saved ? 'Saved on this PC' : 'Not set'
  }
  async function saveKey(k: string) {
    if (busy || !v || !keyEdited(k)) return
    busy = true; keySaving = k; keyResult[k] = {}
    try {
      const value = keyIn[k].trim()
      const r = await api.put<View>('/api/settings', value ? { keys: { [k]: value } } : { clear_keys: [k] })
      // Only availability changed; the other saved baselines and drafts still belong to this form.
      v = { ...v, keys: r.keys, models: { ...v.models, providers: r.models.providers } }
      keyIn[k] = ''; clear[k] = false; keyResult[k] = { saved: true }
      refreshAskOptions()
    } catch (e) { keyResult[k] = { error: (e as Error).message } }
    finally { busy = false; keySaving = '' }
  }
  // 1. Get a key, as in Turn on Wiskit: the provider's key page in the browser (POST /api/app/setup/link)
  async function openKeyPage(k: string) {
    linkError = ''
    try { await api.post('/api/app/setup/link', { name: k }); toast(`Opening the ${KEY_NAMES[k]} key page in your browser`) }
    catch (e) { linkError = (e as Error).message }
  }
  async function browse(k: string, kind: PickKind) {
    const p = await pickPath(kind)
    if (p) dl[k] = p
  }
  // Save keeps the window open; Done closes it. The payload is the one Settings always sent.
  async function save() {
    if (busy || !v) return
    busy = true; saveError = ''
    try {
      const keys = Object.fromEntries(Object.entries(keyIn).filter(([, val]) => val.trim()))
      const r = await api.put<View>('/api/settings', {
        keys, clear_keys: Object.keys(clear).filter(k => clear[k] && !keyIn[k]?.trim()), plain, downloads: dl,
        models: { jarvis: wiskit, embed_provider: embed },
      })
      load(r)
      resetKeys()
      refreshAskOptions()                       // a key may have been added: Wiskit's missing-key line follows
      toast('Settings saved')
    } catch (e) { saveError = (e as Error).message } finally { busy = false }
  }
  const fromSetup = $derived(wins.some(w => w.id === 'setup' || w.id === 'welcome'))
  function backToSetup() {
    if (!dirty.length) close()
    const setup = wins.find(w => w.id === 'setup' || w.id === 'welcome')
    if (setup) { wins.splice(wins.indexOf(setup), 1); wins.push(setup) }
    else runCmd('setup')
    void tick().then(() => requestAnimationFrame(() => document.getElementById('setup-stage')?.focus()))
  }
  // Settings > AI models > Refresh model lists (projects/model-lists/PLAN.md): only the lists change,
  // never the Wiskit choice on screen, which may not be saved yet.
  const PROVIDER_NAMES: [string, string][] = [['anthropic', 'Anthropic'], ['openai', 'OpenAI']]
  interface RefreshResult { results: Record<string, { ok: boolean; count: number; error: string }>; models: ModelView }
  async function refreshModels() {
    if (refreshing || !v) return
    refreshing = true; refreshed = ''; refreshError = ''
    try {
      const r = await api.post<RefreshResult>('/api/settings/models/refresh', {})
      if (v) v = { ...v, models: { ...v.models, models: r.models.models, found_at: r.models.found_at } }
      refreshAskOptions()
      refreshed = PROVIDER_NAMES.map(([p, n]) => { const x = r.results[p]; return `${n}: ${x?.ok ? `${x.count} models found.` : x?.error || 'Skipped.'}` }).join(' ')
    } catch (e) { refreshError = (e as Error).message } finally { refreshing = false }
  }
  const foundLine = $derived.by(() => {
    const at = v?.models.found_at ?? {}
    const parts = PROVIDER_NAMES.filter(([p]) => at[p]).map(([p, n]) => `${n} ${at[p].slice(0, 10)}`)
    return parts.length ? `Last checked: ${parts.join(', ')}.` : 'Not checked yet: the lists show the built-in models.'
  })
  // Escape answers an open question first, and asks before unsaved edits are dropped; otherwise the window's
  // usual Escape closes it. Find's own Escape (clear the field) runs while it has text.
  function escKey(e: KeyboardEvent) {
    if (e.key !== 'Escape' || topWin()?.id !== 'settings') return
    if (find && (e.target as HTMLElement | null)?.closest?.('.set-find, .set-picker')) return
    const stop = () => { e.preventDefault(); e.stopPropagation() }
    if (!dirty.length) return
    stop()
    void confirmWin({ title: 'Close Settings', msg: `Not saved yet: ${dirtyNames.join(', ')}. Close without saving?`, detail: 'Cancel keeps your edits so you can Save them.', ok: 'Discard and close', danger: true })
      .then(ok => { if (ok) close() })
  }
  function tabKey(e: KeyboardEvent) {
    const i = TABS.findIndex(t => t.id === cur)
    let next: number
    if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = TABS.length - 1
    else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = (i + 1) % TABS.length
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') next = (i + TABS.length - 1) % TABS.length
    else return
    e.preventDefault()
    selectTab(TABS[next].id)
    document.getElementById(`set-t${cur}`)?.focus()
  }
</script>

<!-- the sections that match Find a setting: each opens its tab at that section -->
{#snippet results(id: string)}
  <ul class="set-found" id={id} aria-label="Matching settings">
    {#each found as f (f.s.id)}
      <li><button class="set-tab set-hit" type="button" onclick={() => jump(f.s)}>{f.s.title}<small>{f.t.label}</small></button></li>
    {:else}
      <li><Hint>No setting matches. Try a word such as key, phone or update.</Hint></li>
    {/each}
  </ul>
  <p class="sr" role="status">{found.length ? `${found.length} matching ${found.length === 1 ? 'section' : 'sections'}` : 'No setting matches'}</p>
{/snippet}

<!-- one API key row of a group: the field, Save key, Get an API key, Remove key, then its state -->
{#snippet keyField(k: string, label: string)}
  <Label for={`k-${k}`}>{label}{#if k === 'openai'}{' '}<Hint as="span" tone="positive">(Recommended)</Hint>{/if}</Label>
  <div>
    <div class="frow">
      <input class="inp" id={`k-${k}`} type="password" bind:value={keyIn[k]} disabled={busy && (!keySaving || keySaving === k)} oninput={() => { keyResult[k] = {} }} placeholder={v?.keys[k] ? 'Saved on this PC. Paste a new one to replace it' : k === 'local' ? 'Optional' : `${KEY_NAMES[k]} API key`} autocomplete="off" spellcheck="false" aria-describedby={`k-${k}-st`} />
      <Button variant={primaryKey === k ? 'pri' : 'default'} keep size="sm" disabled={busy || !keyEdited(k)} onclick={() => saveKey(k)}>{keySaving === k ? 'Saving…' : clear[k] && !keyIn[k]?.trim() ? 'Confirm removal' : `Save ${KEY_NAMES[k]} key`}</Button>
      {#if k === 'anthropic' || k === 'openai'}<Button size="sm" aria-label={`Get an ${KEY_NAMES[k]} API key`} onclick={() => openKeyPage(k)}>Get an API key</Button>{/if}
      {#if v?.keys[k]}<TextButton disabled={busy && (!keySaving || keySaving === k)} aria-pressed={!!clear[k]} onclick={() => { clear[k] = !clear[k]; keyResult[k] = {} }}>{clear[k] ? 'Keep key' : 'Remove key'}</TextButton>{/if}
    </div>
    <Status id={`k-${k}-st`} on={!!v?.keys[k] && !(clear[k] && !keyIn[k]?.trim())} aria-live="polite">{keyState(k)}</Status>
    {#if k === 'local'}<Hint>Optional. Ollama accepts any word here, such as local.</Hint>{/if}
    {#if keyResult[k]?.error}<Hint tone="error" role="alert">{keyResult[k].error}</Hint>
    {:else if keyResult[k]?.saved}<Hint role="status">{v?.keys[k] ? 'Saved on this PC. Provider access has not been tested.' : 'Key removed from this PC.'}</Hint>{/if}
  </div>
{/snippet}

{#snippet settingsLoading()}
  {#if loadError}<Hint tone="error" role="alert">Could not load these settings: {loadError}</Hint><div class="frow"><Button size="sm" onclick={loadSettings}>Retry</Button></div>
  {:else}<Hint role="status">Loading settings…</Hint>{/if}
{/snippet}

<svelte:window onkeydowncapture={escKey} />
<div class="set-layout">
  <div class="set-nav">
    <div class="set-find">
      <Label for="set-find">Find a setting</Label>
      <input class="inp" id="set-find" type="search" bind:value={find} onkeydown={findKey} placeholder="cookies, update…" autocomplete="off" spellcheck="false" aria-controls="set-found" />
    </div>
    {#if find.trim()}{@render results('set-found')}{/if}
    <div role="tablist" aria-label="Settings sections" aria-orientation="vertical" hidden={!!find.trim()}>
      {#each TABS as t, i (t.id)}
        {#if i === 0 || TABS[i - 1].group !== t.group}<span class="set-group" aria-hidden="true">{t.group}</span>{/if}
        <button class="set-tab" class:dirty={dirty.includes(t.id)} type="button" role="tab" id={`set-t${t.id}`} aria-controls="set-panel" aria-selected={cur === t.id}
          tabindex={cur === t.id ? 0 : -1} onclick={() => selectTab(t.id)} onkeydown={tabKey}>{t.label}{#if dirty.includes(t.id)}<span class="sr">, not saved yet</span>{/if}</button>
      {/each}
    </div>
  </div>
  <div class="set-content">
    <div class="set-picker">
      <div>
        <Label for="set-find-m">Find a setting</Label>
        <input class="inp" id="set-find-m" type="search" bind:value={find} onkeydown={findKey} placeholder="cookies, update…" autocomplete="off" spellcheck="false" aria-controls="set-found-m" />
      </div>
      <div>
        <Label for="set-section">Section</Label>
        <select class="inp" id="set-section" bind:value={cur} onchange={() => selectTab(cur)}>
          {#each GROUPS as g (g)}
            <optgroup label={g}>{#each TABS.filter(t => t.group === g) as t (t.id)}<option value={t.id}>{t.label}{dirty.includes(t.id) ? ' (not saved)' : ''}</option>{/each}</optgroup>
          {/each}
        </select>
      </div>
      {#if find.trim()}{@render results('set-found-m')}{/if}
    </div>
<WinBody bind:ref={body}>
  <header class="set-heading">
    <h2 tabindex="-1" data-autofocus bind:this={heading}>{current.label}</h2>
    <Hint>{current.help}</Hint>
    {#if cur === 'ai'}<small class="set-save-note">Key edits save with their own key; the rest with Save.</small>{/if}
  </header>

  <div role="tabpanel" id="set-panel" aria-labelledby={`set-t${cur}`} tabindex="0">
    <!-- tab:overview -->
    <div hidden={cur !== 'overview'}><div class="set-calm">
      <GroupBox tone="summary" aria-label="Your setup at a glance">
        <Label as="span">Wiskit & AI</Label>
        <div><Status state={wiskitOn ? 'done' : 'optional'}>{!v ? 'Checking…' : wiskitOn ? `${v.models.providers.find(p => p.id === wiskit.provider)?.label ?? wiskit.provider} key saved` : 'Needs a key'}</Status><TextButton aria-label="Open Wiskit & AI" onclick={() => openTab('ai')}>Open</TextButton></div>
        <Label as="span">Imports & downloads</Label>
        <div><Status on={onb.tools && onb.browser}>{onb.tools ? 'Video tools ready' : 'Video tools not set up'} · {onb.browser ? 'browser tools ready' : 'browser tools off'}</Status><TextButton aria-label="Open Imports & downloads" onclick={() => openTab('imports')}>Open</TextButton></div>
        <Label as="span">Obsidian & map</Label>
        <div><Status state={setupv?.obsidian.mode === 'owner' ? 'done' : 'optional'}>{!setupv ? 'Checking…' : setupv.obsidian.mode === 'owner' ? 'Vault set up' : 'No vault yet'}</Status><TextButton aria-label="Open Obsidian & map" onclick={() => openTab('obsidian')}>Open</TextButton></div>
        <Label as="span">Backup & phones</Label>
        <div><Status state={cloud?.running ? 'done' : 'optional'}>{!cloud ? 'Checking…' : `${cloud.running ? 'Backup on' : cloud.signed_in ? 'Backup off' : 'Not connected'} · ${!recoveryReady ? 'recovery unchecked' : onb.recovery ? 'recovery set up' : 'recovery not set up'} · ${!cloud.licensed ? 'phone sync needs a PC update' : setupv?.phone_seen ? 'a phone has synced' : 'no phone yet'}`}</Status><TextButton aria-label="Open Backup & phones" onclick={() => openTab('backup')}>Open</TextButton></div>
      </GroupBox>
      <GroupBox active={!!nextStep} aria-label="Next step">
        <Label as="span">Next step</Label>
        <div><Hint>{nextStep ? nextStep.line : 'Everything you use is set up. AI, video tools and cloud connections stay optional.'}</Hint></div>
        {#if nextStep}
          <span></span>
          <div><div class="frow"><Button variant="pri" size="sm" onclick={nextStep.run}>{nextStep.key}</Button></div></div>
        {/if}
      </GroupBox>
    </div></div>
    <!-- /tab:overview -->
    <!-- tab:general -->
    <div hidden={cur !== 'general'}>{#if visited.general}<div class="set-calm">
      {#if appv}
        <GroupBox tone="summary" aria-label="General status">
          <Label as="span">Version</Label>
          <div>{#if upd && !upd.error}<Status on={!upd.newer}>{upd.newer ? `${upd.latest} available` : `${upd.current} · up to date`}{appv.frozen ? '' : ' · from source'}</Status>{:else}<span>{appv.version}{appv.frozen ? '' : ' · from source'}</span>{/if}</div>
          <Label as="span">Library</Label>
          <div><span>{appv.data_dir}{appv.data_dir_next !== appv.data_dir ? ` · from the next start: ${appv.data_dir_next}` : ''}</span></div>
          <Label as="span">Features</Label>
          <div><Status on>All features available · support is optional</Status></div>
        </GroupBox>

        <GroupBox aria-label="Startup">
          <Label as="span" id="set-s-app-startup" tabindex={-1}>Startup</Label>
          <div>
            <ToggleRow id="a-auto" info="Starts Brainamon in the background when you sign in to Windows." label="Start with Windows" checked={appv.autostart} disabled={appBusy} onchange={setAutostart} />
            <ToggleRow id="a-widget" info="Keeps Wiskit on top of your desktop to capture something or ask a question. With Start with Windows on, he appears at sign-in." label="Wiskit on desktop" checked={appv.widget} disabled={appBusy} onchange={setWidget} />
            <ToggleRow id="a-tray" info="Closing or minimizing keeps Brainamon in the notification area, with Wiskit if he is on the desktop. Click either to reopen; quit from their menus." label="Minimize to tray" checked={appv.tray} disabled={appBusy} onchange={setTray} />
            <ToggleRow id="a-warm" info="Keeps about 400 MB in memory so the window comes back at once. Off, reopening takes 2 to 3 seconds and restores your workspace." label="Reopen instantly" note={appv.tray ? 'uses about 400 MB' : 'needs Minimize to tray'} checked={appv.warm} disabled={appBusy || !appv.tray} onchange={setWarm} />
            <ToggleRow id="a-notice" info="Says where Brainamon went each time it goes to the tray. The first time always says it; the tray menu has the same switch." label="Tray notice" note={appv.tray ? '' : 'needs Minimize to tray'} checked={appv.notice} disabled={appBusy || !appv.tray} onchange={setNotice} />
          </div>
        </GroupBox>

        <GroupBox aria-label="Notifications">
          <Label as="span" id="set-s-app-notify" tabindex={-1}>Notifications</Label>
          <div>
            <ToggleRow id="a-toasts" label="Windows notifications" note="while Brainamon is in the background" checked={appv.toasts.on} disabled={appBusy} onchange={on => setToasts({ on })} />
            {#if appv.toasts.on}
              <div role="group" aria-label="Notify me when">
                {#each TOAST_KINDS as [key, label] (key)}<ToggleRow id={`a-toast-${key}`} {label} checked={appv.toasts[key]} disabled={appBusy} onchange={on => setToasts({ [key]: on })} />{/each}
              </div>
            {:else}<Hint>Off by default. Turn on to choose which events notify you.</Hint>{/if}
          </div>
          <span></span>
          <div>
            {#if testLine}<Hint tone={testFailed ? 'error' : 'hint'} role={testFailed ? 'alert' : 'status'}>{testLine}</Hint>{/if}
            <div class="frow"><TextButton disabled={testing} onclick={testToast}>{testing ? 'Sending…' : 'Send a test'}</TextButton></div>
          </div>
        </GroupBox>

        <GroupBox active={!!upd?.newer && appv.frozen && !updLater} aria-label="Updates">
          <Label as="span" id="set-s-app-updates" tabindex={-1}>Updates</Label>
          <div>
            {#if upd && !updError}
              {#if upd.error}<Hint tone="error" role="alert">{upd.error}</Hint>
              {:else}<Status on={!upd.newer} role="status">{upd.newer ? `Version ${upd.latest} is available${upd.size ? ` (${Math.round(upd.size / 1048576)} MB)` : ''}.${appv.frozen ? updState === 'ready' ? ' Downloaded and checked: ready to install.' : '' : ' Running from source: update with git.'}` : `Up to date (${upd.current}).`}</Status>{/if}
              {#if upd.newer && upd.notes}<Disclosure summary={`What is new in ${upd.latest}`}><Hint as="pre" class="set-notes">{upd.notes}</Hint></Disclosure>{/if}
            {/if}
            {#if appv.frozen}<ToggleRow id="set-auto-update" info={"Updates come from Brainamon's releases on GitHub. A download is checked against its SHA-256 before it can install. Automatic updates check daily and download in the background; installation waits for Install and restart."} label="Automatic updates" note="installs only when you choose Install and restart" checked={appv.automatic_updates} disabled={appBusy} onchange={setAutomatic} />{/if}
          </div>
          <span></span>
          <div>
            {#if updState === 'checking'}<Progress label="Checking for updates" />
            {:else if updState === 'downloading'}<Progress label="Downloading the update" pct={updPct} />
            {:else if updState === 'installing'}<Progress label="Starting the installer" />{/if}
            {#if diagBusy}<Progress label="Exporting diagnostics" />{/if}
            {#if diag}<Status on role="status">Saved: {diag}</Status>{/if}
            {#if updError}<Hint tone="error" role="alert">{updError}</Hint>{/if}
            {#if diagError}<Hint tone="error" role="alert">{diagError}</Hint>{/if}
            <div class="frow">
              {#if upd?.newer && appv.frozen}
                {#if updState === 'ready' || updState === 'installing'}
                  <Button variant={updLater ? 'default' : 'pri'} size="sm" disabled={updState === 'installing'} onclick={installUpdate}>{updState === 'installing' ? 'Installing…' : 'Install and restart'}</Button>
                  {#if !updLater}<Button size="sm" disabled={updState === 'installing'} onclick={() => (updLater = true)}>Later</Button>{/if}
                {:else}
                  <Button variant="pri" size="sm" disabled={updState !== ''} onclick={downloadUpdate}>{updState === 'downloading' ? `Downloading… ${updPct}%` : `Download ${upd.latest}`}</Button>
                {/if}
                <TextButton disabled={['checking', 'downloading', 'installing'].includes(updState)} onclick={checkUpdate}>{updState === 'checking' ? 'Checking…' : 'Check again'}</TextButton>
              {:else}
                <Button size="sm" disabled={['checking', 'downloading', 'installing'].includes(updState)} onclick={checkUpdate}>{updState === 'checking' ? 'Checking…' : 'Check for updates'}</Button>
              {/if}
              <TextButton disabled={diagBusy} onclick={exportDiagnostics}>{diagBusy ? 'Exporting…' : 'Export diagnostics'}</TextButton><InfoTip label="What Export diagnostics does" text={'Export diagnostics writes a support zip with logs, the version and a settings summary. API keys, email addresses and your user folder are removed. The zip stays on this PC; nothing is sent.'} />
              {#if diag}<TextButton onclick={revealDiag}>Open folder</TextButton>{/if}
            </div>
          </div>
        </GroupBox>

        <GroupBox active={changingFolder} aria-label="Library folder">
          <Label as="span" id="set-s-app-folder" tabindex={-1}>Library folder<InfoTip label="How to move a library" text="Nothing is moved or copied. Quit Brainamon, copy the folder, start Brainamon, choose the copy here, then restart." /></Label>
          <div>
            <Hint>{appv.data_dir}</Hint>
            {#if appv.data_dir_next !== appv.data_dir}<Status role="status">Opens after a restart: {appv.data_dir_next}</Status>{/if}
            {#if !appv.frozen}<Hint>Running from source: the folder comes from CM_DATA_DIR.</Hint>{/if}
            {#if changingFolder && appv.frozen}
              <div class="frow">
                <input class="inp" bind:value={newData} placeholder="Another library folder: empty, or one with content_manager.db" aria-label="New library folder" autocomplete="off" spellcheck="false" />
                {#if isDesktop()}<Button size="sm" onclick={browseData}>Browse</Button>{/if}
              </div>
            {/if}
          </div>
          <span></span>
          <div>
            <div class="frow">
              {#if appv.data_dir_next !== appv.data_dir && appv.can_quit}<Button variant={changingFolder ? 'default' : 'pri'} size="sm" disabled={appBusy} onclick={restart}>{restarting ? 'Restarting…' : 'Restart now to open it'}</Button>{/if}
              {#if appv.frozen && changingFolder}
                <Button variant="pri" size="sm" disabled={appBusy || !newData.trim()} onclick={async () => { await setDataDir(); if (!newData) changingFolder = false }}>Use it</Button>
                <TextButton disabled={appBusy} onclick={() => { changingFolder = false; newData = '' }}>Cancel</TextButton>
              {:else if appv.frozen}
                <Button size="sm" onclick={() => (changingFolder = true)}>Use another folder…</Button>
              {/if}
            </div>
          </div>
        </GroupBox>

        <LicenseSettings />

        <GroupBox aria-label="About">
          <Label as="span" id="set-s-app-about" tabindex={-1}>About</Label>
          <div>
            <Hint>Brainamon {appv.version} · {appv.frozen ? 'installed' : 'running from source'} · <a href="mailto:me@fredtomas.com">me@fredtomas.com</a></Hint>
            {#if !appv.can_quit}<Hint>Quit is not available here: this server was not started by the Brainamon app.</Hint>{/if}
          </div>
          <span></span>
          <div>
            <div class="frow">
              <Button variant="danger" size="sm" disabled={appBusy || !appv.can_quit} onclick={quitApp}>{quitting ? 'Quitting…' : 'Quit completely'}</Button>
              <TextButton onclick={() => runCmd('about')}>Privacy and licenses…</TextButton>
            </div>
          </div>
        </GroupBox>
      {:else if appError}
        <Hint tone="error" role="alert">Could not load the app settings: {appError}</Hint><div class="frow"><Button size="sm" onclick={loadApp}>Retry</Button></div>
      {:else}
        <Hint role="status">Loading the app settings…</Hint>
      {/if}
    </div>{/if}</div>
    <!-- /tab:general -->
    <!-- tab:ai -->
    <div hidden={cur !== 'ai'}>{#if visited.ai}<div class="set-calm">
      {#if v}
        {@const wiskitLabel = v.models.providers.find(p => p.id === wiskit.provider)?.label ?? wiskit.provider}
        {@const wiskitModel = v.models.models[wiskit.provider]?.find(m => m.id === wiskit.model)?.label ?? wiskit.model}
        {@const embedLabel = v.models.embed_providers.find(p => p.id === embed)?.label ?? embed}
        <GroupBox tone="summary" aria-label="AI status">
          <Label as="span">Wiskit</Label>
          <div><Status on={wiskitOn}>{wiskitOn ? `${wiskitLabel} · ${wiskitModel}` : `Needs a ${wiskitLabel} key`}</Status></div>
          <Label as="span">Search</Label>
          <div><Status on={!!v.keys[embed]}>{v.keys[embed] ? embedLabel : `Needs ${embed === 'openai' ? 'an OpenAI' : 'a FreeLLMAPI'} key`}</Status></div>
          <Label as="span">Transcription</Label>
          <div><Status on={!!v.keys.openai && audioReady}>{v.keys.openai ? 'OpenAI Whisper' : 'Needs an OpenAI key'} · {audioToolsError ? 'audio tools not checked' : !audioTools ? 'checking audio tools…' : audioReady ? 'FFmpeg ready' : 'FFmpeg missing'}</Status></div>
        </GroupBox>

        <GroupBox active={!v.keys.openai && !v.keys.anthropic} aria-label="API keys">
          <Label as="span" id="set-s-keys-main" tabindex={-1}>API keys</Label>
          <div><Hint>{v.keys.openai || v.keys.anthropic ? 'Saved on this PC. Paste a new key to replace one.' : 'Paste a key. OpenAI covers Wiskit, search and transcription; Anthropic is optional, for Wiskit only.'}</Hint></div>
          {@render keyField('openai', 'OpenAI')}
          {@render keyField('anthropic', 'Anthropic')}
          {#if linkError}<span></span><Hint tone="error" role="alert">Could not open the key page: {linkError}</Hint>{/if}
        </GroupBox>

        <GroupBox aria-label="Wiskit">
          <Label as="span" id="set-s-models-wiskit" tabindex={-1}>Wiskit<InfoTip label="What AI sends, and to whom"><span>Wiskit sends prompts, relevant library text, notes, chat context and, for image features, pictures or video frames to the provider you choose. Search sends library and query text for embeddings; transcription sends audio to OpenAI. A provider marked "no key" needs one in <a href="#set-s-keys-main" onclick={e => { e.preventDefault(); jumpTo('set-s-keys-main') }}>API keys</a>.</span><span>Configured endpoints or proxies receive these requests too and may forward them. Provider charges apply separately; the provider's terms and retention apply. Saving a key does not test it.</span></InfoTip></Label>
          <div>
            <Hint>{wiskitOn ? `Answers, descriptions and summaries run on ${wiskitLabel}.` : `Add a ${wiskitLabel} key above, or Turn on Wiskit.`}</Hint>
          </div>
          <WiskitModelPicker catalog={v.models} bind:choice={wiskit} />
          <span></span>
          <div>
            {#if refreshing}<Progress label="Asking the providers for their model lists" />{/if}
            {#if refreshed}<Hint role="status">{refreshed}</Hint>{/if}
            {#if refreshError}<Hint tone="error" role="alert">{refreshError}</Hint>{/if}
            <div class="frow">
              {#if !wiskitOn}<Button variant={keyTyped || dirty.length ? 'default' : 'pri'} size="sm" onclick={() => openWiskitKey(v?.models.jarvis.provider)}>Turn on Wiskit</Button>{/if}
              <TextButton disabled={refreshing} onclick={refreshModels}>{refreshing ? 'Checking…' : 'Refresh model lists'}</TextButton>
            </div>
            <Hint>{foundLine}</Hint>
          </div>
          {#if cc?.available}
            <Label as="span" id="set-s-cc-program" tabindex={-1}>Claude Code</Label>
            <div>
              <Status on={ccState.on} role="status">{ccState.line}</Status>
              <Hint>Wiskit's third mode: your Claude plan instead of an API key. {ccPath.trim() ? 'Install Claude Code and log in first; Test checks the program and its login.' : 'Type or browse to claude.exe or claude.cmd, or press Find.'}</Hint>
              {#if !ccPath.trim()}<Hint>Claude Code is a separate program from Anthropic and needs a Claude plan. <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener noreferrer">Install Claude Code</a>{cc.winget ? ', or run winget install Anthropic.ClaudeCode in a terminal' : ''}, then press Find.</Hint>{/if}
              {#if ccPath.trim() && !ccPassed}<Hint>Sign in opens a terminal window for Claude Code's own sign-in. Finish it there, then press Test.</Hint>{/if}
            </div>
            <Label for="cc-path">Program</Label>
            <div>
              <div class="frow">
                <input class="inp" id="cc-path" bind:value={ccPath} oninput={() => (ccTest = null)} placeholder={cc.detected || 'claude.exe or claude.cmd'} autocomplete="off" spellcheck="false" />
                {#if isDesktop()}<Button size="sm" onclick={browseCc}>Browse</Button>{/if}
              </div>
            </div>
            <span></span>
            <div>
              {#if ccTesting}<Progress label="Testing Claude Code" />{/if}
              {#if ccError && ccErrorAt === 'test'}<Hint tone="error" role="alert">{ccError}</Hint>{/if}
              <div class="frow">
                <Button size="sm" disabled={ccBusy || !ccPath.trim()} onclick={testCc}>{ccTesting ? 'Testing…' : 'Test'}</Button>
                {#if !ccPassed}<TextButton disabled={ccBusy} onclick={findCc}>Find</TextButton>{/if}
                {#if ccPath.trim() && !ccPassed}<TextButton disabled={ccBusy} onclick={loginCc}>Sign in…</TextButton>{/if}
              </div>
            </div>
            <Label as="span" id="set-s-cc-wiskit" tabindex={-1}>Wiskit mode<InfoTip label="What Claude Code can do here"><span>Adds Claude Code beside Quick and Deep, on your Claude plan instead of an API key. Prompts and library context it reads go through your Claude Code provider configuration, under that service's terms and charges. It cannot edit files or run commands.</span></InfoTip></Label>
            <div>
              <ToggleRow id="cc-on" label="Use in Wiskit" note={!cc.enabled && !ccPassed ? 'turns on after a passing Test' : ''} checked={cc.enabled} disabled={ccBusy || (!cc.enabled && !ccPassed)} onchange={enabled => setCc({ enabled })} />
            </div>
            <Label for="cc-model">Claude Code model</Label>
            <div>
              <select class="inp" id="cc-model" value={cc.model} disabled={ccBusy} onchange={e => setCc({ model: (e.currentTarget as HTMLSelectElement).value })}>
                {#each cc.models as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
              </select>
            </div>
            <Label as="span" id="set-s-cc-approvals" tabindex={-1}>Approvals<InfoTip label="What runs without asking"><span>Off, a note or a job waits for your click. On, they go ahead at once, including replacing a personal note with no undo and running paid AI jobs; a job still waits while another runs. To follow what Claude Code does, turn on its <a href="#set-s-app-notify" onclick={e => { e.preventDefault(); jumpTo('set-s-app-notify') }}>notification</a>.</span></InfoTip></Label>
            <div>
              <ToggleRow id="cc-auto" label="Run requests without asking" note="off by default" checked={cc.auto_approve} disabled={ccBusy} onchange={auto_approve => setCc({ auto_approve })} />
              {#if ccError && ccErrorAt === 'set'}<Hint tone="error" role="alert">{ccError}</Hint>{/if}
              {#if appv && !appv.frozen}<Disclosure summary="Use Brainamon from Claude Code (MCP)"><Hint>Configure your MCP client to run <code>python -m mcp_local</code> from your Brainamon checkout. Read tools work with Brainamon closed. Job tools (describe, categorize, thumbnails) need Brainamon running, and a job or a note starts only after your click here, unless Run requests without asking is on. The server is local only, has no delete tool, and every write happens inside the app. Full steps: <code>docs/development/MCP.md</code>.</Hint></Disclosure>{/if}
            </div>
          {/if}
        </GroupBox>

        <GroupBox aria-label="Search">
          <Label for="m-emb" id="set-s-models-search" tabindex={-1}>Search</Label>
          <div>
            <select class="inp" id="m-emb" bind:value={embed}>{#each v.models.embed_providers.filter(p => p.id === 'openai' || p.id === 'freellmapi') as p (p.id)}<option value={p.id}>{p.label}</option>{/each}</select>
            <Hint>Search by meaning sends library and query text to {embedLabel} for embeddings. Switching keeps your search index.</Hint>
          </div>
        </GroupBox>

        <Disclosure id="set-s-ai-advanced" tabindex={-1} summary="Other ways to use AI" ontoggle={e => { advancedOpen = e.currentTarget.open }}>
          <div class="set-calm">
            <GroupBox aria-label="FreeLLMAPI">
              <Label as="span" id="set-s-keys-free" tabindex={-1}>FreeLLMAPI</Label>
              <div><Hint>A shared free pool. Its server and upstream providers can receive your content; their own terms and charges apply.</Hint></div>
              {@render keyField('freellmapi', 'FreeLLMAPI key')}
              <Label for="k-fu">Server address</Label>
              <div>
                <input class="inp" id="k-fu" aria-label="FreeLLMAPI server address" bind:value={plain.freellmapi_base} placeholder={v.freellmapi_default_base} autocomplete="off" spellcheck="false" />
                <Hint>Requests go to {plain.freellmapi_base || v.freellmapi_default_base}.</Hint>
              </div>
            </GroupBox>
            <GroupBox aria-label="Local server">
              <Label as="span" id="set-s-local" tabindex={-1}>Local server</Label>
              <div><Hint>Start Ollama, LM Studio or another OpenAI-compatible server first; Brainamon does not install or start it. Then choose Local (OpenAI-compatible) under SET in the Wiskit panel.</Hint></div>
              <Label for="l-url">Server address</Label>
              <div>
                <input class="inp" id="l-url" aria-label="Local server address" bind:value={plain.local_base} placeholder="http://localhost:11434/v1" autocomplete="off" spellcheck="false" />
                <Hint>Prompts and context go to {plain.local_base || 'http://localhost:11434/v1'}. A remote address or forwarding server can send them off this PC; its terms and charges apply.</Hint>
              </div>
              {@render keyField('local', 'API key')}
              <Label for="l-mod">Default model</Label>
              <div><input class="inp" id="l-mod" bind:value={plain.local_model} placeholder="Optional model id" autocomplete="off" spellcheck="false" /></div>
            </GroupBox>
          </div>
        </Disclosure>
      {:else}{@render settingsLoading()}{/if}
    </div>{/if}</div>
    <!-- /tab:ai -->
    <!-- tab:imports -->
    <div hidden={cur !== 'imports'}>{#if visited.imports}<div class="set-calm">
      <GroupBox tone="summary" aria-label="Imports status">
        <Label as="span">Video tools</Label>
        <div><Status on={onb.tools}>{onb.tools ? 'Ready' : 'Not set up'}</Status></div>
        <Label as="span">Browser tools</Label>
        <div><Status on={onb.browser}>{onb.browser ? 'Ready' : 'Not set up'}</Status></div>
        <Label as="span">Site logins</Label>
        <div><span>{logins === null ? 'Checking…' : logins ? `${logins} saved` : 'None'}</span></div>
        <Label as="span">Watch folder</Label>
        <div><span>{dl.scrape_watch_dir || 'Downloads'}</span></div>
      </GroupBox>
      <ToolsSettings titleId="set-s-tools-video" lead={!addingLogin} onready={ready => { onb.tools = ready }} />
      <div class="set-anchor" id="set-s-tools-browser" tabindex="-1"><ImportSetup section="browser" lead={onb.tools && !addingLogin} onready={ready => { onb.browser = ready }} /></div>
      <SiteSessions titleId="set-s-dl-logins" oncount={n => { logins = n }} onadding={on => { addingLogin = on }} />
      {#if v && (dl.yt_dlp_cookies || dl.instagram_cookies)}
        <Hint>This library still points at cookie files from an earlier version. Save a protected copy above, or press Forget saved access to stop using them. The files themselves are not deleted.</Hint>
      {/if}
      {#if v}
        <GroupBox aria-label="Scraper imports">
          <Label as="span" id="set-s-dl-watch" tabindex={-1}>Scraper imports</Label>
          <div><Hint>New scraper files saved here are imported while the Scrapers window watches. Empty means your Downloads folder.</Hint></div>
          <Label for="d-sc">Watch folder</Label>
          <div><div class="frow"><input class="inp" id="d-sc" bind:value={dl.scrape_watch_dir} placeholder={v.default_watch_dir} autocomplete="off" spellcheck="false" />{#if isDesktop()}<Button size="sm" onclick={() => browse('scrape_watch_dir', 'folder')}>Browse</Button>{/if}</div></div>
        </GroupBox>
      {:else}{@render settingsLoading()}{/if}
    </div>{/if}</div>
    <!-- /tab:imports -->
    <!-- tab:obsidian -->
    <div hidden={cur !== 'obsidian'}>{#if visited.obsidian}
      <ObsidianSettings sync={vaultSummary}>
        {#snippet phoneSync()}
          <GroupBox active={!!cloud && (cloud.vault_state === 'starting' || cloud.vault_state === 'syncing' || cloud.vault_state === 'brake')} aria-label="Vault sync with phone">
            <Label as="span" id="set-s-sync-vault" tabindex={-1}>Vault sync with phone<InfoTip label="Conflicts, deletions and skipped files"><span>In a Brainamon vault, the pages Brainamon generates go from PC to phone only; your own files, and anything you add inside the Brainamon folder, go both ways. A classic export's Content Manager folder only goes from PC to phone. If both sides change a file, the PC copy stays and a separate "phone conflict" copy is added. Deleted files go to .trash. Files over 50 MB, plugins, themes and workspace files are skipped.</span><span>A Brainamon vault syncs only while every phone runs the current app; the phone's More &gt; Obsidian vault shows its name. Drop forgets a phone you no longer use. Vault sync can stay off.</span></InfoTip></Label>
            {#if cloud}
              <div>
                <Status on={cloud.vault_running && !['stopping', 'brake', 'error'].includes(cloud.vault_state)} aria-live="polite">{vaultLine}</Status>
                {#if cloud.vault_state === 'starting' || cloud.vault_state === 'syncing'}<Progress label={cloud.vault_step || 'Obsidian vault sync'} pct={vaultPct} />{/if}
                {#if cloud.vault_state === 'brake'}
                  <div role="alert"><Hint tone="error">{cloud.vault_reason}</Hint><Hint>Sync is paused to prevent a large deletion. Read the reason before you continue.</Hint></div>
                {:else if cloud.vault_state === 'error' && cloud.vault_reason}<Hint tone="error" role="alert">{cloud.vault_reason}</Hint>{/if}
                {#if !cloud.vault.folder}<Hint>Syncs the vault with the Android app on the Google account in Backup & phones. Choose a vault above first.</Hint>
                {:else}<Hint>Syncs {cloud.vault.folder} with the Android app on the Google account in Backup & phones.{cloud.vault_last ? ` Last round ${when(cloud.vault_last)}${cloud.vault_summary ? ` · ${cloud.vault_summary}` : ''}.` : ''}</Hint>{/if}
                {#if !cloud.configured && !cloud.signed_in}<Hint>Needs Google sign-in, which is not set up in this build.</Hint>{/if}
                {#if !cloud.vault_devices}<Hint>The phone check is incomplete. Remembered phones can still be dropped.</Hint>{/if}
                {#if cloud.vault_devices?.length || cloud.vault_members.length}
                  <ItemList items={cloud.vault_devices ?? cloud.vault_members.map(device => ({ device, ok: false }))} key={d => d.device} label="Phones">
                    {#snippet item(d)}<Status as="span" on={d.ok}>{d.device} · {!cloud?.vault_devices ? 'not checked' : d.ok ? 'current app' : 'needs the current Brainamon app'}</Status>{/snippet}
                    {#snippet actions(d)}<TextButton disabled={!cloud?.licensed || cloudBusy} aria-label={`Drop ${d.device}…`} onclick={() => dropDevice(d.device)}>Drop…</TextButton>{/snippet}
                  </ItemList>
                {:else if cloud.vault_devices}<Hint>No phone has synced this vault yet.</Hint>{/if}
              </div>
              <span></span>
              <div>
                {#if cloudErr?.where === 'vault'}<Hint tone="error" role="alert">{cloudErr.msg}</Hint>{/if}
                <div class="frow">
                  {#if cloud.vault_state === 'brake'}
                    <Button variant="danger" size="sm" disabled={!cloud.licensed || cloudBusy} onclick={() => cloudDo('/api/cloud/vault/confirm', undefined, { vault_state: 'starting', vault_reason: '' }, 'vault')}>Apply deletions anyway</Button>
                  {/if}
                  {#if cloud.vault_running}
                    <Button size="sm" disabled={!cloud.licensed || cloudBusy || vaultMoving || cloud.vault_state === 'syncing'} onclick={() => cloudDo('/api/cloud/vault/now', undefined, { vault_state: 'starting', vault_reason: '' }, 'vault')}>Sync now</Button>
                    <TextButton disabled={cloudBusy || cloud.vault_state === 'stopping' || cloud.state === 'disconnecting'} onclick={() => cloudDo('/api/cloud/vault/stop', undefined, { vault_state: 'stopping' }, 'vault')}>Turn off vault sync</TextButton>
                  {:else}
                    {#if cloud.state === 'signing-in' && cloud.vault_state === 'starting'}
                      <Button size="sm" disabled={cloudBusy} onclick={() => cloudDo('/api/cloud/cancel-sign-in', undefined, { state: 'off', vault_state: 'off', error: '' }, 'vault')}>Cancel sign-in</Button>
                    {/if}
                    <Button size="sm" disabled={!cloud.licensed || cloudBusy || vaultMoving || cloudMoving || (!cloud.configured && !cloud.signed_in)} onclick={() => cloudDo('/api/cloud/vault/connect', undefined, { vault_state: 'starting', vault_reason: '', ...(cloud?.signed_in ? {} : { state: 'signing-in' as const, error: '' }) }, 'vault')}>Sync my Obsidian vault</Button>
                  {/if}
                </div>
              </div>
            {:else if cloudError}
              <div><Hint tone="error" role="alert">Could not load the cloud settings: {cloudError}</Hint><div class="frow"><Button size="sm" onclick={loadCloud}>Retry</Button></div></div>
            {:else}
              <div><Hint role="status">Loading the cloud settings…</Hint></div>
            {/if}
          </GroupBox>
        {/snippet}
      </ObsidianSettings>
    {/if}</div>
    <!-- /tab:obsidian -->
    <!-- tab:backup -->
    <div hidden={cur !== 'backup'}>{#if visited.backup}
      {#if cloud}
        <BackupPhonesPage {cloud} {sizes} err={cloudErr} run={cloudDo} setOption={cloudOpt} reload={loadCloud} onrecover={openRecover} onrecoverprimary={primary => { recoverPrimary = primary }} onform={open => { backupForm = open }} />
        <div class="set-calm">
          <Disclosure summary="Phone page address">
            <div class="fg">
              <Label for="c-purl">Phone page</Label>
              <div>
                <input class="inp" id="c-purl" name="phone_url" type="url" autocomplete="off" spellcheck="false" value={cloud.phone_url} onchange={e => cloudOpt({ phone_url: (e.currentTarget as HTMLInputElement).value }, 'page')} />
                {#if cloudErr?.where === 'page'}<Hint tone="error" role="alert">{cloudErr.msg}</Hint>{/if}
                <Hint>Where the phone opens Brainamon. During development, reach this PC over USB with adb reverse tcp:18765 tcp:18765.</Hint>
              </div>
            </div>
          </Disclosure>
        </div>
      {:else if cloudError}
        <div class="set-calm"><Hint tone="error" role="alert">Could not load the cloud settings: {cloudError}</Hint><div class="frow"><Button size="sm" onclick={loadCloud}>Retry</Button></div></div>
      {:else}
        <div class="set-calm"><Hint role="status">Loading the cloud settings…</Hint></div>
      {/if}
    {/if}</div>
    <!-- /tab:backup -->
  </div>
</WinBody>
  </div>
</div>
<WinFoot>
  {#snippet start()}
    {#if cur === 'backup' && !recoverPrimary}<TextButton onclick={openRecover}>Recover a library…</TextButton>{/if}
    {#if dirty.length}<small class="set-foot-note" role="status">Not saved yet: {dirtyNames.join(', ')}.</small>
    {/if}
    {#if fromSetup}<Button disabled={busy} onclick={backToSetup}>Back to Setup</Button>{/if}
    {#if saveError}<Hint class="set-foot-err" tone="error" role="alert">Could not save: {saveError}</Hint>{/if}
  {/snippet}
  {#if dirty.length}
    <Button disabled={busy} onclick={discard}>Discard</Button>
    <Button variant={cur === 'ai' && primaryKey ? 'default' : 'pri'} keep disabled={busy} onclick={save}>{busy ? 'Saving…' : 'Save'}</Button>
  {:else}
    <Button variant={bodyPrimary || (cur === 'backup' && backupForm) ? 'default' : 'pri'} onclick={close}>Done</Button>
  {/if}
</WinFoot>
