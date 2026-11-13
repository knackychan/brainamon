<script lang="ts">
  // Scrapers (Qt ui/scraper_dialog.py, V6 winScrapers): the manual DevTools scrapers (copy the
  // script, open the page, watch Downloads, import the CSV when it lands) and the Playwright
  // scrapers (Facebook, Instagram, Reddit, Threads). Closing the window stops the watcher and a running one.
  import { onMount, tick, untrack } from 'svelte'
  import { api } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { jobBusyMsg, jobHooks } from '../lib/jobs'
  import { openImport } from '../lib/io-commands.svelte'
  import ImportSetup from '../components/ImportSetup.svelte'
  import { isSite, scrapeGuide, SITE_NAME, type Site } from '../lib/onboarding'
  import { SRC_MARK } from '../lib/cards/card'
  import { toast } from '../lib/ui.svelte'
  import { confirmWin } from '../lib/windows.svelte'
  import ToggleRow from '../components/ui/ToggleRow.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Disclosure from '../components/ui/Disclosure.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'
  import Button from '../components/ui/Button.svelte'

  let { close, focus = '' }: { close: () => void; focus?: string } = $props()
  interface P { key: string; label: string; target: string }
  const sources: Site[] = ['facebook', 'instagram', 'threads', 'youtube', 'reddit']
  type Method = 'automatic' | 'manual' | 'playlist' | 'file'
  let site = $state<Site | ''>(untrack(() => isSite(focus) ? focus : 'instagram'))
  let mode = $state<Method>(untrack(() => isSite(focus) ? 'manual' : 'automatic'))
  const methods = $derived<Method[]>(site === 'youtube' ? ['playlist', 'manual', 'file'] : ['automatic', 'manual', 'file'])
  const methodName: Record<Method, string> = { automatic: 'Automatic', manual: 'Manual Scraping', playlist: 'Playlist link', file: 'Import CSV' }
  const methodHint: Record<Method, string> = { automatic: 'Brainamon scans for you', manual: 'Run a script in your browser', playlist: 'Paste a YouTube link', file: 'Use an exported file' }
  function chooseSite(key: Site) {
    if (site === key) { site = ''; return }
    site = key; mode = key === 'youtube' ? 'playlist' : 'automatic'
    unsave = false; remember = false; stopAt = ''; copyMessage = ''; errorMessage = ''
  }
  function chooseMethod(key: Method) {
    if (mode === key) return
    mode = key; unsave = false; copyMessage = ''; errorMessage = ''
  }
  async function methodKey(event: KeyboardEvent) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const index = methods.indexOf(mode)
    chooseMethod(methods[event.key === 'Home' ? 0 : event.key === 'End' ? methods.length - 1 : (index + (event.key === 'ArrowLeft' ? -1 : 1) + methods.length) % methods.length])
    await tick()
    document.getElementById(`scraper-method-${mode}`)?.focus()
  }
  let platforms = $state<P[]>([])
  let preparing = $state(false), starting = $state(false)
  let copyMessage = $state('')
  const manualPlatform = $derived(platforms.find(p => p.key === site))
  let playwright = $state<{ key: string; label: string }[]>([])
  let watching = $state(false)
  let dir = $state('')
  let stopAt = $state('')
  let playlistUrl = $state(''), playlistStarting = $state(false), playlistStep = $state('')
  const playlistRunning = $derived(live.jobs.current?.kind === 'youtube_playlist')
  let unsave = $state(false), remember = $state(false), runtimeReady = $state(false)
  const canUnsave = $derived(mode === 'automatic' ? ['facebook', 'instagram', 'reddit'].includes(site) : mode === 'manual' && site === 'facebook')
  const remove = $derived(canUnsave && unsave)
  const confirmUnsave = (enabled: boolean, platform: string) => !enabled || confirmWin({ title: 'Unsave after export?', msg: `Remove collected posts from ${isSite(platform) ? SITE_NAME[platform] : platform} Saved after exporting a CSV? This changes your original account.`, detail: platform === 'facebook' && mode === 'manual' ? 'The browser script also asks you to verify each downloaded CSV before removal. Keep the exported files until import succeeds.' : 'Only collected posts are removed. Keep the exported CSV until import succeeds.', ok: 'Continue', danger: true })
  // the Instagram Saved page is per user (<username>/saved/all-posts/); remembered on this PC
  let igUser = $state(load('cm.scrapers.igUser'))
  $effect(() => { try { localStorage.setItem('cm.scrapers.igUser', igUser.trim()) } catch { /* private mode */ } })

  function load(k: string): string { try { return localStorage.getItem(k) ?? '' } catch { return '' } }
  let lines = $state<{ t: string; c: string }[]>([{ t: 'Ready.', c: 'd' }])
  let box: HTMLPreElement | undefined = $state()
  let errorMessage = $state('')
  const pwRunning = $derived(live.jobs.current?.kind === 'scrape')
  const auto = $derived(mode === 'automatic')
  const guide = $derived(site && ['manual', 'automatic'].includes(mode) ? scrapeGuide(site, auto) : null)
  const preparingAny = $derived(preparing || starting || playlistStarting)
  const occupied = $derived(preparingAny || !!live.jobs.current)
  let disposed = false

  function out(t: string, c = '') {
    if (c === 'r') errorMessage = t
    lines.push({ t, c })
    if (lines.length > 500) lines.splice(0, lines.length - 500)
    tick().then(() => { if (box) box.scrollTop = box.scrollHeight })
  }

  onMount(() => {
    api.get<{ platforms: P[]; playwright: { key: string; label: string }[]; watching: boolean; dir: string }>('/api/scrapers')
      .then(r => { platforms = r.platforms; playwright = r.playwright; watching = r.watching; dir = r.dir })
      .catch(e => out(String((e as Error).message), 'r'))
    const offs = [
      on('scrape', (d: { line: string; c?: string }) => out(d.line, d.c ?? '')),
      on('job_item', (d: { state: string; error?: string; step?: string }) => {
        if (playlistRunning && d.step) playlistStep = d.step
        if (['scrape', 'youtube_playlist'].includes(live.jobs.current?.kind ?? '') && d.state === 'error' && d.error && d.error !== 'Stopped.') out(d.error, 'r')
      }),
    ]
    return () => {
      disposed = true
      offs.forEach(f => f())
      api.post('/api/scrapers/watch', { on: false }).catch(() => {})
      if (['scrape', 'youtube_playlist'].includes(live.jobs.current?.kind ?? '')) api.post('/api/jobs/stop').catch(() => {})
    }
  })

  async function watch() {
    const r = await api.post<{ watching: boolean; dir: string }>('/api/scrapers/watch', { on: true })
    if (disposed) { await api.post('/api/scrapers/watch', { on: false }); return }
    watching = r.watching; dir = r.dir
  }

  async function launch(p: P, openPage = true) {
    if (occupied) return
    const removing = p.key === 'facebook' && remove, stop = stopAt.trim()
    preparing = true
    copyMessage = ''; errorMessage = ''
    try {
      if (!(await confirmUnsave(removing, p.key)) || disposed) return
      const q = new URLSearchParams({ stop_at: stop, unsave: String(removing) })
      const r = await fetch(`/api/scrapers/${p.key}.js?${q}`)
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
      const script = await r.text()
      if (disposed) return
      await navigator.clipboard.writeText(script)
      if (disposed) return
      await watch()
      if (disposed) return
      if (openPage) await api.post(`/api/scrapers/${p.key}/open`)
      copyMessage = `${isSite(p.key) ? SITE_NAME[p.key] : p.label} script copied to clipboard.`
      out(`${p.label}: ${openPage ? 'script copied and page opened.' : 'script copied to clipboard.'}`, 'a')
      out('In the page: F12, Console, paste (Ctrl+V), Enter, then wait.', 'd')
      if (p.key === 'youtube') out('(Choose View full playlist / Afficher la playlist complète first, then paste the script.)', 'd')
      if (p.key === 'instagram') out('(Open your profile, Saved, All posts first.)', 'd')
    } catch (e) {
      copyMessage = `Could not prepare the scraper: ${(e as Error).message}. Try Copy script again.`
      out(copyMessage, 'r')
    }
    finally { preparing = false }
  }

  async function startPw(platform: string) {
    if (occupied || !runtimeReady) return
    const removing = canUnsave && remove, stop = stopAt.trim(), username = igUser.trim(), keep = remember
    starting = true; errorMessage = ''
    try {
      if (!(await confirmUnsave(removing, platform)) || disposed) return
      await api.post('/api/scrapers/playwright', { platform, stop_at: stop, unsave: removing, remember: keep, unsave_confirmed: removing, username: platform === 'instagram' ? username : '' })
      if (disposed) { await api.post('/api/jobs/stop'); await api.post('/api/scrapers/watch', { on: false }); return }
      await watch()
    } catch (e) { out((e as Error).message, 'r'); toast((e as Error).message, 'w') }
    finally { starting = false }
  }
  async function stopPw() {
    if (!pwRunning) return
    try { await api.post('/api/jobs/stop') } catch (e) { out((e as Error).message, 'r') }
  }
  async function importPlaylist(event: SubmitEvent) {
    event.preventDefault()
    if (playlistStarting || live.jobs.current) return
    playlistStarting = true
    playlistStep = 'Reading playlist…'
    try {
      await api.post('/api/import/youtube-playlist', { url: playlistUrl.trim() })
      if (disposed) { await api.post('/api/jobs/stop'); return }
      out('YouTube playlist import started.', 'a')
    } catch (e) { out((e as Error).message, 'r') }
    finally { playlistStarting = false }
  }
  async function stopPlaylist() {
    try { await api.post('/api/jobs/stop') } catch (e) { out((e as Error).message, 'r') }
  }
</script>


<WinBody class="setup-surface scraper-body">
  <header class="scraper-intro"><h1>Import saved posts</h1><Hint>Choose a platform.</Hint></header>
  <div class="scraper-sources" aria-label="Platforms">
    {#each sources as key (key)}
      <section class="scraper-source" aria-label={SITE_NAME[key]}>
        <button class="scraper-toggle" type="button" data-site={key} aria-expanded={site === key} aria-controls={`scraper-source-${key}`} disabled={preparingAny} onclick={() => chooseSite(key)}>
          <span class="scraper-logo" aria-hidden="true" style:background={SRC_MARK[key][1]}>{@html SRC_MARK[key][0]}</span>
          <span>{SITE_NAME[key]}</span><span class="scraper-chevron" aria-hidden="true"></span>
        </button>
        <div class="scraper-content" id={`scraper-source-${key}`} hidden={site !== key}>
          {#if site === key}
            <div class="scraper-methods" role="tablist" aria-label={`${SITE_NAME[key]} import method`}>
              {#each methods as method}
                <button type="button" role="tab" id={`scraper-method-${method}`} data-method={method} aria-controls="scraper-method-panel" aria-selected={mode === method} tabindex={mode === method ? 0 : -1} disabled={preparingAny} onclick={() => chooseMethod(method)} onkeydown={methodKey}><strong>{methodName[method]}</strong><span>{methodHint[method]}</span></button>
              {/each}
            </div>
            {#key `${key}-${mode}`}
              <div id="scraper-method-panel" role="tabpanel" aria-labelledby={`scraper-method-${mode}`} class="scraper-work">
                {#if auto}
                  <Hint>Brainamon opens a separate browser, scans your saved posts and imports them. Sign in to {SITE_NAME[key]} there if asked.</Hint>
                {:else if mode === 'manual'}
                  <Hint>Use the browser where you’re already signed in. You run the script; Brainamon imports the CSV it downloads.</Hint>
                {:else if mode === 'playlist'}
                  <h2>Import a playlist</h2>
                  <form id="scraper-playlist" class="playlist-import" onsubmit={importPlaylist}>
                    <label class="scraper-field" for="youtube-playlist-url">Playlist link<input class="inp" id="youtube-playlist-url" type="url" required bind:value={playlistUrl} placeholder="https://www.youtube.com/playlist?list=…" autocomplete="off" disabled={preparingAny} /></label>
                  </form>
                  {#if playlistRunning}<Hint role="status">{playlistStep}</Hint>{/if}
                {:else}
                  <h2>Import a saved file</h2><Hint>Choose a scraper CSV from your computer.</Hint>
                {/if}

                {#if auto || mode === 'manual'}
                  <div class="scraper-preferences">
                    {#if key !== 'youtube'}
                      <div class="scraper-preference">
                        <ToggleRow label="Remove from saved posts after export" bind:checked={unsave} disabled={!canUnsave || preparingAny} describedby="scraper-remove-help" />
                        <Hint id="scraper-remove-help">{canUnsave ? `Only exported posts are removed from ${SITE_NAME[key]} Saved. Keep the CSV until import succeeds.` : key === 'threads' ? 'Removal is not available for Threads.' : 'Choose Automatic to remove exported posts from Saved.'}</Hint>
                      </div>
                    {/if}
                    {#if auto}
                      <div class="scraper-preference">
                        <ToggleRow label="Remember this login on this PC" bind:checked={remember} disabled={preparingAny} describedby="scraper-login-help" />
                        <Hint id="scraper-login-help">Stores this site’s login in protected Windows storage on this PC.</Hint>
                      </div>
                    {/if}
                  </div>
                  <div class="scraper-fields">
                    <label class="scraper-field" for="s-stop">Stop at title (optional)<input class="inp" id="s-stop" bind:value={stopAt} placeholder="Stop at an already imported post" autocomplete="off" disabled={preparingAny} /></label>
                    {#if auto && key === 'instagram'}<label class="scraper-field" for="s-iguser">Instagram username (optional)<input class="inp" id="s-iguser" bind:value={igUser} placeholder="Found from the page if empty" autocomplete="off" disabled={preparingAny} /></label>{/if}
                  </div>
                {/if}

                <div class="scraper-help">
                  {#if guide}
                    {#if auto}
                      <Hint>Finish sign-in, 2FA or CAPTCHA in the separate browser. Scans stop after two hours; Stop keeps any exported files.</Hint>
                    {:else}
                      <ol>{#each guide.steps as step}<li>{step}</li>{/each}</ol>
                      <Hint>Only run scripts you trust. If pasting is blocked, use {key === 'youtube' ? 'Playlist link' : 'Automatic'} or Import CSV.</Hint>
                      {#if key === 'facebook'}<Hint>If removal is enabled, verify each downloaded CSV when the script asks before confirming removal.</Hint>{/if}
                      <a class="scraper-tutorial" href="/guides/manual-scraping.png" target="_blank" rel="noreferrer">View the illustrated guide</a>
                    {/if}
                    <Hint>{watching ? `Watching for scraper CSVs in: ${dir}` : `CSV folder: ${dir || 'Downloads'}`}. Keep this window open until import finishes.</Hint>
                    {#if remove}<Hint>A CSV is exported before removal. Keep it until import succeeds. Interrupted Facebook scans keep recovery CSVs in the CSV folder’s pending subfolder.</Hint>{/if}
                  {:else if mode === 'playlist'}
                    <Hint>Imports video links and available titles, up to 10,000 entries per playlist. Existing links are skipped. Videos are not downloaded. Keep this window open until import finishes.</Hint>
                    <Hint>Private playlists may need YouTube cookies in Settings > Imports & downloads. Manual Scraping is another option.</Hint>
                  {:else}
                    <Hint>Use a CSV exported by a Brainamon scraper. Existing links are skipped. File import does not change your original account.</Hint>
                  {/if}
                </div>

                {#if auto}
                  <div class="scraper-tools" hidden={runtimeReady}>
                    <ImportSetup section="browser" onready={ready => runtimeReady = ready} />
                  </div>
                {/if}

                <div class="scraper-actions">
                  {#if auto}
                    <Button variant="pri" data-run disabled={occupied || !runtimeReady || !playwright.some(p => p.key === key)} onclick={() => startPw(key)}>{starting ? 'Starting…' : `Open ${SITE_NAME[key]} & scan`}</Button>
                  {:else if mode === 'manual'}
                    <Button variant="pri" data-run disabled={occupied || !manualPlatform} onclick={() => { if (manualPlatform) launch(manualPlatform) }}>{preparing ? 'Preparing…' : 'Copy script & open site'}</Button>
                    <Button disabled={occupied || !manualPlatform} onclick={() => { if (manualPlatform) launch(manualPlatform, false) }}>Copy script</Button>
                  {:else if mode === 'playlist'}
                    <Button variant="pri" type="submit" form="scraper-playlist" data-run disabled={!playlistUrl.trim() || occupied}>{playlistStarting || playlistRunning ? 'Importing…' : 'Import playlist'}</Button>
                  {:else}
                    <Button variant="pri" data-run onclick={() => openImport()}>Choose CSV file</Button>
                  {/if}
                </div>
                {#if mode !== 'file' && live.jobs.current && !pwRunning && !playlistRunning}
                  <Hint role="status">{jobBusyMsg()}. Wait for it to finish, or stop it in progress. <button class="linkk" type="button" onclick={() => jobHooks.openProgress?.()}>Show progress</button></Hint>
                {/if}
                {#if auto && !runtimeReady}<Hint>Set up browser tools above, or choose Manual Scraping.</Hint>{/if}
                {#if mode !== 'file' && mode !== 'playlist'}<Hint class="scraper-account">{remove ? `Removes collected posts from ${SITE_NAME[key]} Saved.` : 'Saves stay in your account.'}</Hint>{/if}
                {#if mode === 'manual' && copyMessage}<Hint role="status" class="scraper-copy">{copyMessage}</Hint>{/if}
              </div>
            {/key}
          {/if}
        </div>
      </section>
    {/each}
  </div>
  {#if errorMessage}<Hint tone="error" role="alert">{errorMessage}</Hint>{/if}
  <Disclosure class="scraper-activity" summary="Activity">
    <pre class="tlog" bind:this={box} aria-live="polite">{#each lines as l, i (i)}<span class={l.c}>{l.t}</span>{'\n'}{/each}</pre>
  </Disclosure>
</WinBody>
<WinFoot class="setup-surface">
  {#snippet start()}<span class="scraper-footer-status" role="status">{pwRunning ? 'Scanning…' : playlistRunning ? 'Importing playlist…' : preparingAny ? 'Preparing…' : watching ? 'Watching for CSV files' : 'Ready'}</span>{/snippet}
  {#if pwRunning}<Button onclick={stopPw}>Stop scan</Button>{/if}
  {#if playlistRunning}<Button onclick={stopPlaylist}>Stop playlist import</Button>{/if}
  <Button onclick={close}>Close</Button>
</WinFoot>

<style>
  .scraper-intro { margin-bottom: 18px }
  .scraper-intro h1 { margin: 0 0 6px; font: var(--type-heading); letter-spacing: -.02em }
  .scraper-sources { display: grid; gap: 9px }
  .scraper-source { border: 2px solid var(--rw-ink); border-radius: 10px; box-shadow: 2px 2px 0 var(--rw-sh); overflow: clip }
  .scraper-toggle { width: 100%; min-height: 49px; display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 0; background: transparent; color: var(--rw-ink); text-align: left; cursor: pointer; font: 700 15px/1.2 var(--display) }
  .scraper-toggle:hover { background: var(--rw-2) }
  .scraper-toggle:focus-visible { outline-offset: -4px }
  .scraper-toggle:disabled { cursor: default; opacity: .6 }
  .scraper-logo { width: 28px; height: 28px; flex: none; display: grid; place-items: center; border-radius: 7px; color: #fff; font: 800 22px/1 var(--display) }
  .scraper-chevron { margin-left: auto; width: 7px; height: 7px; border-top: 1.5px solid currentColor; border-right: 1.5px solid currentColor; transform: rotate(45deg) }
  .scraper-toggle[aria-expanded="true"] .scraper-chevron { transform: rotate(135deg) }
  .scraper-content { margin: 0 14px; padding: 13px 0 14px; border-top: 1px solid var(--rw-dim) }
  .scraper-methods { display: grid; grid-template-columns: 1fr 1fr .8fr; padding: 4px; gap: 4px; margin-bottom: 16px; border: 1px solid var(--rw-dim); border-radius: 8px; background: var(--rw-2) }
  .scraper-methods button { min-width: 0; display: grid; gap: 5px; padding: 10px 8px; border: 0; border-radius: 5px; background: transparent; color: var(--rw-ink); text-align: left; cursor: pointer; font: 500 11px/1.4 var(--mono) }
  .scraper-methods button strong { font: 700 14px/1.2 var(--display) }
  .scraper-methods button:hover { background: var(--rw) }
  .scraper-methods button[aria-selected="true"] { background: var(--rw-ink); color: var(--rw) }
  .scraper-methods button:disabled { cursor: default; opacity: .6 }
  .scraper-work { display: grid; gap: 10px; min-width: 0 }
  .scraper-work h2 { margin: 0; font: 700 16px/1.2 var(--display); letter-spacing: -.01em }
  .scraper-preferences { display: grid; gap: 12px; padding: 16px 0; border-block: 1px solid var(--rw-dim); margin: 4px 0 }
  .scraper-preference :global(.tgl) { flex-direction: row-reverse; justify-content: space-between; min-height: 28px; font: 600 13px/1.4 var(--display) }
  .scraper-preference :global(.hint) { margin: 3px 48px 0 0 }
  .scraper-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 12px; margin: 4px 0 }
  .scraper-help { display: grid; gap: 10px }
  .scraper-help ol { padding-left: 20px; margin: 6px 0; display: grid; gap: 10px; font: var(--type-steps) }
  .scraper-tutorial { color: var(--rw-ink); font: var(--type-aside); text-underline-offset: 3px }
  .scraper-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 6px }
  .playlist-import { margin-top: 4px }
  .scraper-field { display: grid; gap: 8px; font: 500 12px/1.4 var(--mono) }
  .scraper-work :global(.scraper-account) { font: var(--type-aside) }
  .scraper-work :global(.scraper-account)::before { content: ''; display: inline-block; width: 5px; height: 5px; margin-right: 7px; background: var(--ok); border-radius: 50%; vertical-align: 2px }
  :global(.scraper-body>.scraper-activity) { margin-top: 16px }
  .scraper-footer-status { color: var(--rw-dim); font: var(--type-status) }
  @media(max-width:480px) { .scraper-content { margin: 0 12px }.scraper-methods { grid-template-columns: 1fr 1fr }.scraper-methods button:last-child { grid-column: 1/-1; grid-template-columns: 1fr 1fr; align-items: center }.scraper-actions { align-items: stretch }.scraper-work :global(.scraper-tools .gbox) { grid-template-columns: minmax(0,1fr) } }
  @media(pointer:coarse) { .scraper-toggle { min-height: 52px } }
</style>
