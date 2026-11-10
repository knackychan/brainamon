<script lang="ts">
  // Scrapers (Qt ui/scraper_dialog.py, V6 winScrapers): the manual DevTools scrapers (copy the
  // script, open the page, watch Downloads, import the CSV when it lands) and the Playwright
  // scrapers (Facebook, Instagram, Reddit, Threads). Closing the window stops the watcher and a running one.
  import { onMount, tick } from 'svelte'
  import { api } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { openImport } from '../lib/io-commands.svelte'
  import ImportSetup from '../components/ImportSetup.svelte'
  import { isSite, scrapeGuide, SITE_NAME } from '../lib/onboarding'
  import { toast } from '../lib/ui.svelte'
  import { confirmWin } from '../lib/windows.svelte'
  import Field from '../components/ui/Field.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import SectionTitle from '../components/ui/SectionTitle.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'
  import Button from '../components/ui/Button.svelte'

  let { close, focus = '' }: { close: () => void; focus?: string } = $props()
  interface P { key: string; label: string; target: string }
  let mode = $state<'manual' | 'automatic'>('manual')
  async function tabKey(e: KeyboardEvent) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
    e.preventDefault()
    mode = e.key === 'Home' ? 'manual' : e.key === 'End' ? 'automatic' : mode === 'manual' ? 'automatic' : 'manual'
    await tick()
    document.getElementById(`scraper-tab-${mode}`)?.focus()
  }
  let platforms = $state<P[]>([])
  let manualSite = $state('facebook'), preparing = $state(false)
  let copyMessage = $state('')
  const manualPlatform = $derived(platforms.find(p => p.key === manualSite))
  let playwright = $state<{ key: string; label: string }[]>([])
  let watching = $state(false)
  let dir = $state('')
  let stopAt = $state('')
  let playlistUrl = $state(''), playlistStarting = $state(false), playlistStep = $state('')
  const playlistRunning = $derived(live.jobs.current?.kind === 'youtube_playlist')
  let unsave = $state(false), remember = $state(false), runtimeReady = $state(false)
  const confirmUnsave = () => !unsave || confirmWin({ title: 'Unsave after export?', msg: 'Unsave removes collected items from your account after CSV export. Continue?', ok: 'Continue', danger: true })
  // the Instagram Saved page is per user (<username>/saved/all-posts/); remembered on this PC
  let igUser = $state(load('cm.scrapers.igUser'))
  $effect(() => { try { localStorage.setItem('cm.scrapers.igUser', igUser.trim()) } catch { /* private mode */ } })

  function load(k: string): string { try { return localStorage.getItem(k) ?? '' } catch { return '' } }
  let lines = $state<{ t: string; c: string }[]>([{ t: 'Ready.', c: 'd' }])
  let box: HTMLPreElement | undefined = $state()
  const pwRunning = $derived(live.jobs.current?.kind === 'scrape')
  // A focused site's guide follows the explicitly selected import method.
  const site = $derived(isSite(focus) ? focus : null)
  const auto = $derived(mode === 'automatic')
  const guide = $derived(site && !(auto && site === 'youtube') ? scrapeGuide(site, auto) : null)
  function startGuide() {
    if (!site) return
    if (auto) { startPw(site); return }
    const p = platforms.find(x => x.key === site)
    if (p) launch(p)
    else out('This scraper is not available in this build.', 'r')
  }

  function out(t: string, c = '') {
    lines.push({ t, c })
    if (lines.length > 500) lines.splice(0, lines.length - 500)
    tick().then(() => { if (box) box.scrollTop = box.scrollHeight })
  }

  onMount(() => {
    api.get<{ platforms: P[]; playwright: { key: string; label: string }[]; watching: boolean; dir: string }>('/api/scrapers')
      .then(r => { platforms = r.platforms; manualSite = site ?? 'facebook'; playwright = r.playwright; watching = r.watching; dir = r.dir })
      .catch(e => out(String((e as Error).message), 'r'))
    const offs = [
      on('scrape', (d: { line: string; c?: string }) => out(d.line, d.c ?? '')),
      on('job_item', (d: { state: string; error?: string; step?: string }) => {
        if (playlistRunning && d.step) playlistStep = d.step
        if (['scrape', 'youtube_playlist'].includes(live.jobs.current?.kind ?? '') && d.state === 'error' && d.error && d.error !== 'Stopped.') out(d.error, 'r')
      }),
    ]
    return () => {
      offs.forEach(f => f())
      api.post('/api/scrapers/watch', { on: false }).catch(() => {})
      if (['scrape', 'youtube_playlist'].includes(live.jobs.current?.kind ?? '')) api.post('/api/jobs/stop').catch(() => {})
    }
  })

  async function watch() {
    const r = await api.post<{ watching: boolean; dir: string }>('/api/scrapers/watch', { on: true })
    watching = r.watching; dir = r.dir
  }

  async function launch(p: P, openPage = true) {
    if (preparing) return
    if (!(await confirmUnsave())) return
    preparing = true
    copyMessage = ''
    manualSite = p.key
    try {
      const q = new URLSearchParams({ stop_at: stopAt.trim(), unsave: String(unsave) })
      const r = await fetch(`/api/scrapers/${p.key}.js?${q}`)
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
      await navigator.clipboard.writeText(await r.text())
      if (openPage) await api.post(`/api/scrapers/${p.key}/open`)
      await watch()
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
    if (platform === 'threads' && unsave) { toast('Turn off Unsave before starting the Threads scraper.', 'w'); return }
    if (!(await confirmUnsave())) return
    if (pwRunning) { out('A Playwright scraper is already running.', 'a'); return }
    try {
      await api.post('/api/scrapers/playwright', { platform, stop_at: stopAt.trim(), unsave, remember, unsave_confirmed: unsave, username: igUser.trim() })
      await watch()
    } catch (e) { out((e as Error).message, 'r'); toast((e as Error).message, 'w') }
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
      out('YouTube playlist import started.', 'a')
    } catch (e) { out((e as Error).message, 'r') }
    finally { playlistStarting = false }
  }
  async function stopPlaylist() {
    try { await api.post('/api/jobs/stop') } catch (e) { out((e as Error).message, 'r') }
  }
</script>


<WinBody class="setup-surface">
  {#if !site || site === 'youtube'}
    <SectionTitle as="h3">Import a YouTube playlist</SectionTitle>
    <form class="playlist-import" onsubmit={importPlaylist}>
      <div class="fg"><Field label="Playlist link" for="youtube-playlist-url"><input class="inp" id="youtube-playlist-url" type="url" required bind:value={playlistUrl} placeholder="https://www.youtube.com/playlist?list=…" autocomplete="off" /></Field></div>
      <Hint>Import video links and available titles without downloading videos. Existing links are skipped. One playlist per import, up to 10,000 entries.</Hint>
      <Hint>Private playlists, Watch Later and Liked videos may need YouTube login cookies in Settings > Imports & downloads. If access fails, use the Manual browser script below. Keep this window open until finished.</Hint>
      <div class="setup-actions"><Button type="submit" variant="pri" disabled={!playlistUrl.trim() || playlistStarting || !!live.jobs.current}>{playlistStarting || playlistRunning ? 'Importing…' : 'Import playlist'}</Button>
        {#if playlistRunning}<Button onclick={stopPlaylist}>Stop playlist import</Button>{/if}</div>
      {#if playlistRunning}<Hint role="status">{playlistStep}</Hint>{/if}
    </form>
  {/if}
  <div class="scraper-tabs" role="tablist" aria-label="Import method">
    {#each ['manual', 'automatic'] as tab}
      <button class="wkey" type="button" role="tab" id={`scraper-tab-${tab}`} aria-controls={`scraper-panel-${tab}`} aria-selected={mode === tab} tabindex={mode === tab ? 0 : -1} onclick={() => mode = tab as 'manual' | 'automatic'} onkeydown={tabKey}>{tab === 'manual' ? 'Manual' : 'Automatic'}</button>
    {/each}
  </div>
  <div role="tabpanel" id={`scraper-panel-${mode}`} aria-labelledby={`scraper-tab-${mode}`} tabindex="0">
    {#if guide}
      <section class="sg-guide" aria-labelledby="sg-h">
        <h3 id="sg-h">{guide.title}</h3>
        <ol>{#each guide.steps as s, i (i)}<li>{s}</li>{/each}</ol>
        {#if !unsave}<Hint>Nothing is removed from your account.</Hint>{/if}
        <div class="sg-go"><button class="wkey pri" type="button" disabled={auto ? !runtimeReady || pwRunning : preparing || !platforms.some(p => p.key === site)} onclick={startGuide}>{guide.key}</button></div>
      </section>
    {/if}
    <SectionTitle as="p">{auto ? 'Automatic import options' : 'Manual import options'}</SectionTitle>
    <div class="fg">
      <Field label="Stop at title" for="s-stop"><input class="inp" id="s-stop" bind:value={stopAt} placeholder="First already-saved title; import only newer items" autocomplete="off" /></Field>
      {#if auto}<Field label="Instagram username" for="s-iguser"><input class="inp" id="s-iguser" bind:value={igUser} placeholder="Optional: found from the page if empty" autocomplete="off" /></Field>{/if}
      <span></span><label class="chk"><input type="checkbox" bind:checked={unsave} />Unsave each item after scraping ({auto ? 'Facebook, Instagram and Reddit; turn off for Threads' : 'Facebook only'}; modifies your account)</label>
    </div>
    {#if auto}
      <Hint>This separate browser does not have your usual browser’s saved passwords. Finish sign-in, 2FA or CAPTCHA in the browser. Follow Activity below if Saved does not open. Stop Playwright cancels; imports have a two-hour limit.</Hint>
      <label class="chk"><input type="checkbox" bind:checked={remember} />Remember this login on this PC (protected Windows storage)</label>
      <Hint>Check Remember before starting to reuse this site’s login on later imports. The site may ask you to sign in again when it expires. Manual scripts use your usual browser’s login and are available for Facebook, Instagram and Reddit. Unsave changes your account only after the CSV is written.</Hint>
      <ImportSetup section="browser" onready={ready => runtimeReady = ready} />
      {#if site === 'youtube'}<Hint>Use the playlist-link form above for YouTube, or the Manual tab for your signed-in browser. These browser helpers support Facebook, Instagram, Reddit and Threads.</Hint>{/if}
      <div class="setup-actions">{#each playwright as pw (pw.key)}<button class="wkey" type="button" disabled={!runtimeReady || pwRunning} onclick={() => startPw(pw.key)}>Start {pw.label} scraper</button>{/each}</div>
    {:else}
      <Hint>Copy a script, paste it in your browser’s developer console, and leave the page open. Brainamon watches Downloads and imports the CSV when it arrives. No Playwright installation is needed.</Hint>
      <div class="setup-actions">{#each platforms as p (p.key)}<button class="wkey" type="button" disabled={preparing} onclick={() => launch(p)}>{p.label}</button>{/each}<button class="wkey" type="button" onclick={() => openImport()}>Import a CSV manually</button></div>
      <section class="manual-tutorial" aria-labelledby="manual-tutorial-title">
        <h3 id="manual-tutorial-title">Browser walkthrough</h3>
        <p>Use your signed-in desktop browser. The screenshots show Facebook in Edge; Chrome uses the same Console shortcut.</p>
        <div class="manual-copy">
          <label for="manual-script-site">Script for</label>
          <select class="inp" id="manual-script-site" bind:value={manualSite} disabled={preparing}>
            {#each platforms as p (p.key)}<option value={p.key}>{isSite(p.key) ? SITE_NAME[p.key] : p.label}</option>{/each}
          </select>
          <Button disabled={preparing || !manualPlatform} onclick={() => { if (manualPlatform) launch(manualPlatform, false) }}>{preparing ? 'Preparing…' : 'Copy script'}</Button>
        </div>
        <p role="status">{copyMessage}</p>
        <ol>
          <li><strong>Open your saved items.</strong> Use the {site ? '“Copy script and open”' : 'site'} button above to copy the script and open the site. Sign in if needed. On Instagram, open your profile → Saved → All posts. On YouTube, choose View full playlist for one playlist. Facebook and Reddit open Saved directly.</li>
          <li><strong>Open Developer Tools.</strong> Press <kbd>F12</kbd> (or <kbd>Fn</kbd> + <kbd>F12</kbd>). In Chrome, you can also use the browser menu → More tools → Developer tools. In Edge, use More tools → Developer tools.</li>
          <li><strong>Choose Console.</strong> Click the Console tab at the top of Developer Tools. <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>J</kbd> opens Console directly in Chrome and Edge.</li>
          <li><strong>Paste and run.</strong> Click the empty line beside <code>&gt;</code> in Console, press <kbd>Ctrl</kbd> + <kbd>V</kbd>, then <kbd>Enter</kbd>. Use “Copy script” above to copy it again without opening another page. Copy again if you change the site or import options.</li>
          <li><strong>Wait for the CSV.</strong> Keep the site and this Scrapers window open. Allow the CSV to finish downloading into the watched folder below. Brainamon imports it automatically; if you saved it elsewhere, use “Import a CSV manually”.</li>
        </ol>
        <figure>
          <a href="/guides/manual-scraping.png" target="_blank" rel="noreferrer" aria-label="Open the browser walkthrough screenshot at full size"><img src="/guides/manual-scraping.png" alt="Redacted Facebook Saved page, followed by Developer Tools with Console selected and the empty paste prompt highlighted." width="1536" height="1024" loading="lazy" /></a>
          <figcaption>Edited Facebook example with personal content hidden and steps highlighted. <a href="/guides/manual-scraping.png" target="_blank" rel="noreferrer">View screenshot at full size</a>.</figcaption>
        </figure>
        <Hint>Read any Console warning. Only run a script you understand and trust. If your browser blocks pasting, use the Automatic tab or import a CSV manually.</Hint>
      </section>
    {/if}
    <Hint class="scraper-watch">{watching ? `Watching for scraper CSVs in: ${dir}` : `Watching: not started (folder: ${dir || 'Downloads'})`}</Hint>
  </div>
  <SectionTitle as="p">Activity</SectionTitle>
  {#if pwRunning}<div class="setup-actions"><button class="wkey" type="button" onclick={stopPw}>Stop Playwright</button></div>{/if}
  <pre class="tlog" bind:this={box} aria-live="polite">{#each lines as l, i (i)}<span class={l.c}>{l.t}</span>{'\n'}{/each}</pre>
</WinBody>
<WinFoot class="setup-surface">
  <button class="wkey" type="button" onclick={close}>Close</button>
</WinFoot>

<style>
  .playlist-import { display: grid; gap: 12px; margin-bottom: 24px }
  .manual-tutorial { margin-top: 24px; border-top: 1px solid var(--rw-ink); padding-top: 18px; overflow-wrap: anywhere }
  .manual-tutorial h3 { margin: 0 0 10px; font: 700 17px/1.2 var(--display) }
  .manual-tutorial p,.manual-tutorial ol { font: var(--type-steps); line-height: 1.6 }
  .manual-tutorial ol { display: grid; gap: 14px; padding-left: 22px; margin: 18px 0 }
  .manual-copy { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px }
  .manual-copy .inp { width: auto; max-width: 100% }
  .manual-tutorial figure { margin: 18px 0 12px }
  .manual-tutorial img { display: block; width: 100%; height: auto; border: 1px solid var(--rw-ink) }
  .manual-tutorial figcaption { margin-top: 8px; font: var(--type-steps) }
  .manual-tutorial a { color: inherit; text-decoration: underline; text-underline-offset: 3px }
  .manual-tutorial kbd { font: inherit; font-weight: 700 }
  .sg-guide { margin: 0 0 16px; padding: 14px 16px 12px; border: 2px solid var(--rw-ink); border-radius: 10px; background: var(--rw-2) }
  .sg-guide h3 { margin: 0 0 10px; font: 700 17px/1.2 var(--display); letter-spacing: -.01em }
  .sg-guide ol { margin: 0 0 14px; padding-left: 20px; display: grid; gap: 6px; font: var(--type-steps) }
  .sg-go { display: flex; align-items: center; gap: 14px; margin-top: 18px; justify-content: flex-end }
  .sg-go .wkey { height: 30px; padding: 0 14px; font-size: 12px }
  .scraper-tabs { display:flex; gap:12px; margin-bottom:20px }
  .scraper-tabs [aria-selected="true"] { border-bottom:4px solid var(--rw-ink); font-weight:700 }
  .scraper-watch { margin-top:18px; overflow-wrap:anywhere }
  [role="tabpanel"]>:global(.hint),[role="tabpanel"]>.chk { margin-top:16px }
</style>
