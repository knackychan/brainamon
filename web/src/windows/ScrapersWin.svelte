<script lang="ts">
  // Scrapers (Qt ui/scraper_dialog.py, V6 winScrapers): the manual DevTools scrapers (copy the
  // script, open the page, watch Downloads, import the CSV when it lands) and the Playwright
  // scrapers (Facebook, Instagram, Reddit, Threads). Closing the window stops the watcher and a running one.
  import { onMount, tick, untrack } from 'svelte'
  import { api } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { openImport } from '../lib/io-commands.svelte'
  import ImportSetup from '../components/ImportSetup.svelte'
  import { isSite, scrapeGuide, SITE_NAME, type Site } from '../lib/onboarding'
  import { SRC_MARK } from '../lib/cards/card'
  import { toast } from '../lib/ui.svelte'
  import { confirmWin } from '../lib/windows.svelte'
  import Field from '../components/ui/Field.svelte'
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
  const methodName: Record<Method, string> = { automatic: 'Scan saved posts', manual: 'Browser script', playlist: 'Playlist link', file: 'Import CSV' }
  function chooseSite(key: Site) {
    if (site === key) { site = ''; return }
    site = key; mode = key === 'youtube' ? 'playlist' : 'automatic'
    unsave = false; remember = false; stopAt = ''; copyMessage = ''; errorMessage = ''
  }
  function chooseMethod(key: Method) { mode = key; unsave = false; copyMessage = ''; errorMessage = '' }
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
                <Button role="tab" id={`scraper-method-${method}`} data-method={method} aria-controls="scraper-method-panel" aria-selected={mode === method} tabindex={mode === method ? 0 : -1} disabled={preparingAny} onclick={() => chooseMethod(method)} onkeydown={methodKey}>{methodName[method]}</Button>
              {/each}
            </div>
            {#key `${key}-${mode}`}
              <div id="scraper-method-panel" role="tabpanel" aria-labelledby={`scraper-method-${mode}`} class="scraper-work">
                {#if auto}
                  <h2>Scan your saved posts</h2>
                  <Hint>Sign in to {SITE_NAME[key]} in the browser that opens.</Hint>
                  <label class="chk scraper-remember"><input type="checkbox" bind:checked={remember} disabled={preparingAny} />Remember this login on this PC</label>
                {:else if mode === 'manual'}
                  <h2>Use your own browser</h2><Hint>Copy the script, then run it on your Saved {key === 'youtube' ? 'playlist' : 'page'}.</Hint>
                {:else if mode === 'playlist'}
                  <h2>Import a playlist</h2>
                  <form id="scraper-playlist" class="playlist-import" onsubmit={importPlaylist}>
                    <label class="scraper-field" for="youtube-playlist-url">Playlist link<input class="inp" id="youtube-playlist-url" type="url" required bind:value={playlistUrl} placeholder="https://www.youtube.com/playlist?list=…" autocomplete="off" disabled={preparingAny} /></label>
                  </form>
                  {#if playlistRunning}<Hint role="status">{playlistStep}</Hint>{/if}
                {:else}
                  <h2>Import a saved file</h2><Hint>Choose a scraper CSV from your computer.</Hint>
                {/if}

                {#if mode !== 'file'}
                  <Disclosure class="scraper-options" summary="Advanced options">
                    {#if mode === 'playlist'}
                      <Hint>Private playlists may need YouTube cookies in Settings > Imports & downloads. Browser script is another option.</Hint>
                    {:else}
                      <div class="fg">
                        <Field label="Stop at title" for="s-stop"><input class="inp" id="s-stop" bind:value={stopAt} placeholder="Optional: stop at an already imported post" autocomplete="off" disabled={preparingAny} /></Field>
                        {#if auto && key === 'instagram'}<Field label="Instagram username" for="s-iguser"><input class="inp" id="s-iguser" bind:value={igUser} placeholder="Optional: found from the page if empty" autocomplete="off" disabled={preparingAny} /></Field>{/if}
                      </div>
                      {#if key !== 'youtube'}
                        <label class="chk scraper-remove"><input type="checkbox" bind:checked={unsave} disabled={!canUnsave || preparingAny} aria-describedby="scraper-remove-help" />Remove from saved posts after export</label>
                        <Hint id="scraper-remove-help">{canUnsave ? `Changes your ${SITE_NAME[key]} saved list. Only collected posts are removed.` : key === 'threads' ? 'Removal is not available for Threads.' : 'Use Scan saved posts to remove originals.'}</Hint>
                      {/if}
                    {/if}
                  </Disclosure>
                {/if}

                <Disclosure class="scraper-help" summary="How it works">
                  {#if guide}
                    <ol>{#each guide.steps as step}<li>{step}</li>{/each}</ol>
                    {#if auto}
                      <Hint>Finish sign-in, 2FA or CAPTCHA in the separate browser. Your usual browser’s passwords are not available there. Scans stop after two hours; Stop keeps any exported files.</Hint>
                      <Hint>Remember login stores this site’s login in protected Windows storage on this PC. A site may ask you to sign in again.</Hint>
                    {:else}
                      <Hint>Use F12, then Console. Paste with Ctrl+V and press Enter. Only run scripts you trust. If pasting is blocked, use {key === 'youtube' ? 'Playlist link' : 'Scan saved posts'} or Import CSV.</Hint>
                      {#if key === 'facebook'}<Hint>If removal is enabled, verify each downloaded CSV when the script asks before confirming removal.</Hint>{/if}
                      <a href="/guides/manual-scraping.png" target="_blank" rel="noreferrer"><img src="/guides/manual-scraping.png" alt="Facebook Saved and Developer Tools with Console selected and the paste prompt highlighted." width="1536" height="1024" loading="lazy" /></a>
                    {/if}
                    <Hint>{watching ? `Watching for scraper CSVs in: ${dir}` : `CSV folder: ${dir || 'Downloads'}`}. Keep this window open until import finishes.</Hint>
                    {#if remove}<Hint>A CSV is exported before removal. Keep it until import succeeds. Interrupted Facebook scans keep recovery CSVs in the CSV folder’s pending subfolder.</Hint>{/if}
                  {:else if mode === 'playlist'}
                    <Hint>Imports video links and available titles, up to 10,000 entries per playlist. Existing links are skipped. Videos are not downloaded. Keep this window open until import finishes.</Hint>
                  {:else}
                    <Hint>Use a CSV exported by a Brainamon scraper. Existing links are skipped. File import does not change your original account.</Hint>
                  {/if}
                </Disclosure>

                {#if auto}
                  <Disclosure class="scraper-tools" summary={runtimeReady ? 'Browser tools' : 'Set up browser tools'}>
                    <ImportSetup section="browser" onready={ready => runtimeReady = ready} />
                  </Disclosure>
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
                {#if auto && !runtimeReady}<Hint>Set up browser tools above, or use Browser script.</Hint>{/if}
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
  .scraper-methods { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px }
  .scraper-methods :global([aria-selected="true"]) { background: var(--rw-ink); color: var(--rw); border-color: var(--rw-ink); box-shadow: none }
  .scraper-work { display: grid; gap: 10px; min-width: 0 }
  .scraper-work h2 { margin: 0; font: 700 16px/1.2 var(--display); letter-spacing: -.01em }
  .scraper-remember { margin: 2px 0 }
  .scraper-work :global(.set-more) { margin: 0; min-width: 0 }
  .scraper-work :global(.set-more>summary) { padding: 9px 0 }
  .scraper-work :global(.scraper-options) { margin-top: 6px; border-top: 1px solid var(--rw-dim) }
  .scraper-work :global(.scraper-options .fg) { margin: 8px 0 12px }
  .scraper-remove { margin: 10px 0 7px }
  .scraper-work :global(.scraper-help[open]), .scraper-work :global(.scraper-tools[open]) { padding-bottom: 8px }
  .scraper-work :global(.scraper-help>.hint) { margin: 10px 0 }
  .scraper-work :global(.scraper-help ol) { padding-left: 20px; margin: 8px 0 12px; display: grid; gap: 10px; font: var(--type-steps) }
  .scraper-work :global(.scraper-help img) { display: block; width: 100%; height: auto; margin: 12px 0; border: 1px solid var(--rw-ink) }
  .scraper-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 6px }
  .playlist-import { margin-top: 4px }
  .scraper-field { display: grid; gap: 8px; font: 500 12px/1.4 var(--mono) }
  .scraper-work :global(.scraper-account) { font: var(--type-aside) }
  .scraper-work :global(.scraper-account)::before { content: ''; display: inline-block; width: 5px; height: 5px; margin-right: 7px; background: var(--ok); border-radius: 50%; vertical-align: 2px }
  :global(.scraper-body>.scraper-activity) { margin-top: 16px }
  .scraper-footer-status { color: var(--rw-dim); font: var(--type-status) }
  @media(max-width:480px) { .scraper-content { margin: 0 12px }.scraper-content .fg { grid-template-columns: minmax(0,1fr); gap: 7px }.scraper-methods { gap: 8px }.scraper-actions { align-items: stretch }.scraper-work :global(.scraper-tools .gbox) { grid-template-columns: minmax(0,1fr) } }
  @media(pointer:coarse) { .scraper-toggle { min-height: 52px } }
</style>
