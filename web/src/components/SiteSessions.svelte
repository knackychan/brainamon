<script lang="ts">
  // Site logins (core/site_sessions.py): cookie files saved with Windows protection for downloads, and the
  // logins the browser scrapers remember. One group: the saved ones as a list, Add a login… opens the flow
  // (site, cookies.txt, review, Save protected copy), Test a link reveals the test row. Forget and Use this
  // login for downloads ask first. Settings > Imports & downloads, Setup step 3 and Help show it.
  import { onMount, tick } from 'svelte'
  import { api } from '../lib/api'
  import { isDesktop, pickPath, pickFileObj } from '../lib/pick'
  import { confirmWin } from '../lib/windows.svelte'
  import Button from './ui/Button.svelte'
  import Disclosure from './ui/Disclosure.svelte'
  import InfoTip from './ui/InfoTip.svelte'
  import GroupBox from './ui/GroupBox.svelte'
  import Hint from './ui/Hint.svelte'
  import ItemList from './ui/ItemList.svelte'
  import Label from './ui/Label.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import TextButton from './ui/TextButton.svelte'
  // onadding: the add flow opened or closed (Settings lets it lead while it is open)
  let { titleId = '', oncount, onadding }: { titleId?: string; oncount?: (saved: number) => void; onadding?: (on: boolean) => void } = $props()
  interface Session { slot: string; mode: string; status: string; domains: string[]; usable: number; expired: number }
  interface Review { domains: string[]; usable: number; expired: number; digest: string; status: string }
  let sessions = $state<Session[]>([]), supported = $state(false), busy = $state(false), error = $state('')
  let loaded = $state(false)
  let site = $state('facebook'), slot = $state('general'), preview = $state<Review | null>(null)
  let chosen = $state<File | string | null>(null)
  let adding = $state(false), testing = $state(false)
  let testUrl = $state(''), testResult = $state(''), testOk = $state(false)
  // the request in flight (its progress line) and where an error belongs
  let doing = $state(''), errorAt = $state(''), done = $state('')
  const id = $props.id()
  const SLOT_NAME: Record<string, string> = {
    general: 'Downloads', instagram: 'Instagram downloads',
    'browser-facebook': 'Facebook browser login', 'browser-instagram': 'Instagram browser login', 'browser-reddit': 'Reddit browser login', 'browser-threads': 'Threads browser login',
  }
  const SITE_NAME: Record<string, string> = { facebook: 'Facebook', instagram: 'Instagram', reddit: 'Reddit', threads: 'Threads', youtube: 'YouTube' }
  const STATUS: Record<string, string> = {
    'Saved; not tested': 'Saved, not tested yet',
    'Sign-in may need refreshing': 'Saved, but the sign-in may need refreshing',
    'Cannot unlock on this PC': 'Saved, but it cannot be unlocked on this PC: save it again',
  }
  function statusOf(s: Session): string {
    if (s.mode === 'legacy') return s.status.startsWith('Legacy') ? 'Uses a cookie file from an earlier version: save a protected copy, or Forget it' : 'Not saved. Cookie files from an earlier version are still allowed: Forget turns that off'
    return STATUS[s.status] ?? s.status
  }
  // the slots Forget can act on: the ones the old list gave a Forget button
  const saved = $derived(sessions.filter(s => s.mode !== 'none' && s.mode !== 'disabled'))
  $effect(() => { if (loaded) oncount?.(saved.length) })
  $effect(() => { onadding?.(adding) })
  const PROGRESS: Record<string, string> = {
    choose: 'Reading the cookie file', save: 'Saving a protected copy', forget: 'Forgetting the saved access',
    reuse: 'Copying the login for downloads', test: 'Testing the link',
  }
  async function load() {
    const r = await api.get<{ supported: boolean; sessions: Session[] }>('/api/settings/site-sessions')
    supported = r.supported; sessions = r.sessions; loaded = true
  }
  async function act(what: string, fn: () => Promise<unknown>) {
    if (busy) return
    busy = true; error = ''; errorAt = ''; doing = what
    try { await fn() } catch (e) { error = (e as Error).message; errorAt = what } finally { busy = false; doing = '' }
  }
  function reset() { preview = null; chosen = null; slot = site === 'instagram' ? 'instagram' : 'general' }
  async function send(save: boolean) {
    if (!chosen) return
    const q = new URLSearchParams({ site: site === 'general' ? '' : site, slot, save: String(save), digest: preview?.digest ?? '' })
    const r = await fetch(`/api/settings/site-sessions/import?${q}`, { method: 'POST', headers: { 'X-CM': '1', ...(typeof chosen === 'string' ? { 'Content-Type': 'application/json' } : {}) }, body: typeof chosen === 'string' ? JSON.stringify({ path: chosen }) : chosen })
    const value = await r.json()
    if (!r.ok) throw new Error(value.detail || 'Cookie import failed')
    preview = value
    if (save) { chosen = null; adding = false; await load() }
  }
  async function choose() {
    await act('choose', async () => {
      preview = null; done = ''
      doing = ''                                // the file dialog is open: nothing is working yet
      chosen = isDesktop() ? await pickPath('cookies') : await pickFileObj('.txt')
      doing = 'choose'
      if (chosen instanceof File && chosen.size > 1048576) { chosen = null; throw new Error('Choose a cookie file up to 1 MiB.') }
      await send(false)
    })
  }
  async function openAdd() {
    adding = true; testing = false; preview = null; done = ''; error = ''; reset()
    await tick(); document.getElementById(id + '-site')?.focus()       // the clicked key is gone: focus the flow's first field
  }
  function cancelAdd() { reset(); adding = false; error = '' }
  async function forget(slot: string) {
    const name = SLOT_NAME[slot] ?? slot
    const also = slot === 'general' ? 'This also forgets the Facebook, Reddit and Threads browser logins. ' : slot === 'instagram' ? 'This also forgets the Instagram browser login. ' : ''
    const ok = await confirmWin({
      title: 'Forget saved access', msg: `Forget ${name}?`, ok: 'Forget', danger: true,
      detail: `${also}Brainamon stops using it, and stops using cookie files from an earlier version. A running download, link info, analysis or scrape job stops. Your own browser and your account on the site stay signed in.`,
    })
    if (!ok) return
    await act('forget', async () => { await api.post('/api/settings/site-sessions/forget', { slot }); await load(); testResult = ''; done = `${name}: forgotten.` })
  }
  async function test() {
    await act('test', async () => {
      const r = await api.post<{ status: string; at: string; action: string; code: string }>('/api/settings/site-sessions/test', { url: testUrl.trim() })
      const at = new Date(r.at)
      testOk = !r.code
      testResult = `${r.status}${isNaN(at.getTime()) ? '' : ` (${at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })})`}`
    })
  }
  async function reuse(site: string) {
    await act('reuse', async () => {
      done = ''
      const review = await api.post<Review & { target: string }>('/api/settings/site-sessions/reuse', { site })
      doing = ''                                // waiting for the answer
      const ok = await confirmWin({
        title: 'Use this login for downloads', msg: `Use your ${SITE_NAME[site] ?? site} browser login for video downloads?`, ok: 'Use it',
        detail: `Copies ${review.usable} cookies for ${review.domains.join(', ')} (${review.expired} expired ones are dropped). It replaces what ${SLOT_NAME[review.target] ?? review.target} uses now. The login is not tested yet.`,
      })
      if (!ok) return
      doing = 'reuse'
      await api.post('/api/settings/site-sessions/reuse', { site, save: true, digest: review.digest })
      await load()
      done = `Downloads now use your ${SITE_NAME[site] ?? site} browser login. Not tested yet.`
    })
  }
  onMount(() => { act('load', load) })
</script>

<GroupBox active={adding || testing} aria-label="Site logins">
  <Label as="span" id={titleId || undefined} tabindex={titleId ? -1 : undefined}>Site logins<InfoTip label="Which features use logins, and how they are protected"><span><b>Download videos:</b> yt-dlp can use your saved login to retrieve the video or its thumbnail. <b>Fetch link info:</b> the yt-dlp part can use it for thumbnails, titles, creators and captions. <b>Analyze videos:</b> only if yt-dlp must download a missing video first. <b>Automatic scrapers:</b> Facebook, Instagram, Reddit and Threads can sign in to their browser with a matching imported login. <b>Test link access:</b> checks link details with yt-dlp and the saved cookies, without downloading.</span><span>Once saved, cookies are supplied to yt-dlp for download and link-info requests, including public links; yt-dlp uses the ones that match the requested site. The public preview in Add, CSV/JSON imports, AI work on existing content and Google Drive sync never use them. Cookies do not grant access beyond your account or guarantee that a site allows a download; expired ones may need replacing.</span><span>On Windows, saved logins are encrypted for your Windows account and kept out of library and Drive copies, so a new PC needs them saved again. This does not protect against programs running as you; old exports and browser profiles stay separate and unencrypted. Saved does not mean signed in: only a test shows whether the site accepts a login. Browser scrapers remember a login only when you tick Remember; Use this login for downloads copies only that site's cookies into downloads.</span></InfoTip></Label>
  <div>
    <Hint>Only for posts that need you signed in. Many public videos, Facebook reels included, download without a login.</Hint>
    {#if saved.length}
      <ItemList items={saved} key={s => s.slot} label="Saved logins">
        {#snippet item(s)}<Status as="span" on={s.mode === 'protected' && s.status === 'Saved; not tested'} role="status">{SLOT_NAME[s.slot] ?? s.slot} · {statusOf(s)}{s.domains.length ? ` · ${s.domains.join(', ')} · ${s.usable} usable` : ''}</Status>{/snippet}
        {#snippet actions(s)}
          {#if s.slot.startsWith('browser-') && s.mode === 'protected'}<TextButton disabled={busy} aria-label={`Use the ${SITE_NAME[s.slot.slice(8)] ?? s.slot.slice(8)} login for downloads`} onclick={() => reuse(s.slot.slice(8))}>Use this login for downloads</TextButton>{/if}
          <TextButton disabled={busy} aria-label={`Forget ${SLOT_NAME[s.slot] ?? s.slot}…`} onclick={() => forget(s.slot)}>Forget saved access…</TextButton>
        {/snippet}
      </ItemList>
    {:else}
      <Hint role="status">{loaded ? 'None saved yet.' : error && errorAt === 'load' ? 'Could not check the saved logins.' : 'Checking saved logins…'}</Hint>
    {/if}
    {#if loaded && !supported}<Hint>Protected storage is not available on this system, so logins cannot be saved here. Nothing is saved as plain text.</Hint>{/if}
  </div>
  {#if adding}
    <Label for={id + '-site'}>Site</Label>
    <div>
      <select class="inp" id={id + '-site'} bind:value={site} onchange={reset} disabled={busy}>
        <option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="reddit">Reddit</option><option value="threads">Threads</option><option value="youtube">YouTube</option><option value="general">Several sites (keeps every site in the file)</option>
      </select>
    </div>
    <Label as="span">Cookie file</Label>
    <div>
      {#if preview && chosen}
        <Status on role="status">{preview.domains.join(', ')} · {preview.usable} usable · {preview.expired} expired, dropped. {site === 'general' ? 'Every listed site is kept.' : 'Other sites in the file are dropped.'}</Status>
        <Hint>Brainamon keeps a protected copy. Your exported file stays where it is: delete it yourself when you are done.</Hint>
      {:else}
        <Hint>Export the site's cookies.txt from Chrome, then choose it here. It holds your login session: keep it private like a password.<InfoTip label="How to export cookies.txt"><span>1. Install <a href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank" rel="noopener noreferrer">Get cookies.txt LOCALLY</a> in Chrome, then sign in to the site in that browser.</span><span>2. On the site's tab, open the extension and export only that site's cookies in Netscape cookies.txt format.{#if site === 'youtube'} Follow the extra <a href="https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies" target="_blank" rel="noopener noreferrer">YouTube export steps</a> for this site.{/if}</span><span>3. Save the file in a private local folder, outside shared or cloud-synced folders.</span><span>4. Choose the file here, check its sites, then save a protected copy.</span></InfoTip></Hint>
      {/if}
    </div>
  {/if}
  {#if testing}
    <Label for={id + '-test'}>Test a link</Label>
    <div>
      <div class="frow">
        <input class="inp" id={id + '-test'} bind:value={testUrl} placeholder="https://…" type="url" autocomplete="off" spellcheck="false" aria-describedby={id + '-test-h'} />
        <Button size="sm" disabled={busy || !testUrl.trim()} onclick={test}>{doing === 'test' ? 'Testing…' : 'Test link access'}</Button>
      </div>
      {#if doing === 'test'}<Progress label={PROGRESS.test} />{/if}
      {#if testResult}<Status on={testOk} role="status">{testResult}</Status>{/if}
      {#if error && errorAt === 'test'}<Hint tone="error" role="alert">{error}</Hint>{/if}
      <Hint id={id + '-test-h'}>Paste one Facebook, Instagram, Reddit or YouTube link. Brainamon reads its details with the saved login, without downloading. This can take up to a minute.</Hint>
    </div>
  {/if}
  <span></span>
  <div>
    {#if doing && doing !== 'test' && doing !== 'load'}<Progress label={PROGRESS[doing]} />{/if}
    {#if done}<Hint role="status">{done}</Hint>{/if}
    {#if preview && !chosen && !adding}<Status on role="status">Saved a protected copy: {preview.domains.join(', ')}, {preview.usable} usable. Not tested yet.</Status>{/if}
    {#if error && errorAt !== 'test'}<Hint tone="error" role="alert">{error}</Hint>{/if}
    <div class="frow">
      {#if adding}
        {#if preview && chosen}
          <Button variant="pri" size="sm" disabled={busy} onclick={() => act('save', () => send(true))}>Save protected copy</Button>
          <TextButton disabled={busy} onclick={choose}>Choose another file</TextButton>
        {:else}
          <Button variant="pri" size="sm" disabled={busy || !supported} onclick={choose}>Choose cookies.txt</Button>
        {/if}
        <TextButton disabled={busy} onclick={cancelAdd}>Cancel</TextButton>
      {:else}
        <Button size="sm" disabled={busy || (loaded && !supported)} onclick={openAdd}>Add a login…</Button>
        {#if error && errorAt === 'load'}<TextButton disabled={busy} onclick={() => act('load', load)}>Check again</TextButton>{/if}
        {#if testing}<TextButton onclick={() => { testing = false; testResult = '' }}>Hide the test</TextButton>
        {:else}<TextButton onclick={() => { testing = true }}>Test a link</TextButton>{/if}
      {/if}
    </div>
  </div>
</GroupBox>
