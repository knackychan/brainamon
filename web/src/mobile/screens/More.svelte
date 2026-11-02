<script lang="ts">
  // 07 More, calm (docs/superpowers/plans/2026-10-29-phone-settings-calm.md): a phone paired with a PC or used without
  // one starts with its status card (StatusCard.svelte; its Google Drive, pairing and recovery boxes are on More >
  // Backup & phones, screens/Backup.svelte), then the Setup summary, Sync (what runs now and what waits, lanes.ts), the
  // connection (the pairing, else the PC over USB), Obsidian (the vault folder, then Open in Obsidian), No PC? (with
  // Recover a library…, #/recover), Import, the desktop
  // app, Wiskit on this phone, what is on this phone, Keep automatically, Saved for offline, Opened recently, the
  // cache limit, Look, then App info
  // and the legal documents. Long explanations sit behind MDisclosure; quiet and destructive actions are MTextButtons.
  import { onMount } from 'svelte'
  import { items as idb, storageUse, wipe } from '../store'
  import { devSolo, driveStatus, fmtAgo, fmtMB, isDark, measurePend, mirrorSource, pairFrom, phone, refresh, setCap, setCardStyle, setMotionOff, syncNow, CARD_STYLES, solo, source, toggleTheme, useWithoutPc, type CardStyle } from '../state.svelte'
  import { syncLanes } from '../lanes'
  import { pickVaultFolder, runVault, setVaultOn, vault as vaultRun } from '../vault/auto.svelte'
  import { appInfo, isApp, secretsSaved } from '../native'
  import { setVaultName, vaultName } from '../obsidian'
  import { setAiKeys } from '../mirror/pairing'
  import { freeSpace, keepCanvasesNeed, keepVideosNeed, offline, removeCanvas, removeItem, setKeep, setKeepVideos, type KeepVideos } from '../offline.svelte'
  import type { StoredItem } from '../store'
  import Vault from '../Vault.svelte'
  import SetupList from '../SetupList.svelte'
  import LegalDocuments from '../../components/LegalDocuments.svelte'
  import { network, setWifiOnly, syncPaused } from '../network.svelte'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'
  import MToggle from '../ui/MToggle.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import StatusCard from '../StatusCard.svelte'
  import { DOWNLOAD_URL } from '../../lib/product-links'

  let use = $state<Awaited<ReturnType<typeof storageUse>> | null>(null)
  let info = $state<Awaited<ReturnType<typeof appInfo>> | null>(null)
  let infoError = $state('')
  async function readAppInfo() {
    infoError = ''
    try { info = await appInfo() }
    catch { infoError = 'Could not read app info.' }
  }
  onMount(() => { if (isApp) void readAppInfo() })
  let kept = $state<StoredItem[]>([])
  let health = $state<{ ok: boolean; items: number; licensed?: boolean } | null>(null)
  let dark = $state(isDark())
  let free = $state(0)
  let ask = $state<{ kind: 'videos'; v: KeepVideos; count: number; bytes: number } | { kind: 'canvases'; bytes: number } | null>(null)
  const m = mirrorSource

  async function measure() {
    use = await storageUse(phone.rows)
    kept = (await idb.all()).filter(s => !s.saved).sort((a, b) => b.at - a.at)
    free = await freeSpace()
    await offline.load()
    if (m) await measurePend()
    else { try { health = await source.health() } catch { health = null } }
  }
  $effect(() => { void phone.synced; if (!phone.refreshing) void measure() })
  const savedBytes = $derived(offline.saved.reduce((a, s) => a + (s.size ?? 0), 0) + offline.canvases.reduce((a, c) => a + c.size, 0))
  const total = $derived(use ? use.light + use.thumbBytes + use.fullBytes + savedBytes : 0)
  const parts = $derived(use ? [['Light copy', use.light, 'var(--m-teal)', 'always'], ['Thumbnails', use.thumbBytes, 'var(--lcd-dim)', `of ${phone.capMB} MB`], ['Opened items', use.fullBytes, 'var(--accent)', `${use.fullItems} kept`], ['Saved for offline', savedBytes, 'var(--m-warn)', `${offline.saved.length + offline.canvases.length} saved`]] as [string, number, string, string][] : [])
  async function forget(id: number) { await idb.del(id); measure() }
  // the stores and the mirror's in-memory copy both go, then the list loads again from the source
  let clearNote = $state('')
  async function clearAll() {
    clearNote = 'Clearing…'
    await wipe()
    m?.forgetCopy()
    phone.rows = []
    navigator.serviceWorker?.controller?.postMessage({ type: 'clear' })
    const why = await refresh()
    clearNote = why ? `Cleared. Not reloaded yet: ${why}` : `Cleared, reloaded ${phone.rows.length.toLocaleString('en')} items.`
    measure()
  }

  // turning a keep setting on: show what it downloads first
  function wantVideos(v: KeepVideos) {
    if (v === 'off') { setKeepVideos('off'); ask = null; return }
    ask = { kind: 'videos', v, ...keepVideosNeed(v) }
  }
  function wantCanvases(on: boolean) {
    if (!on) { setKeep('canvases', false); ask = null; return }
    ask = { kind: 'canvases', bytes: keepCanvasesNeed() }
  }
  function confirm() {
    if (!ask) return
    if (ask.kind === 'videos') setKeepVideos(ask.v); else setKeep('canvases', true)
    ask = null
  }
  let pasted = $state('')
  let vault = $state(vaultName(source.obsidianVault?.() ?? ''))
  let aiTick = $state(0)
  const ai = $derived((phone.synced, aiTick, m?.ai() ?? null))
  let confirmForgetAi = $state(false)
  function forgetAi() {
    if (!confirmForgetAi) { confirmForgetAi = true; return }
    confirmForgetAi = false
    m?.forgetKeys()
    aiTick++
  }
  function pickAi(provider: string, model: string) {
    const p = ai?.providers.find(x => x.id === provider)
    m?.setAi(provider, p?.models.some(x => x.id === model) ? model : p?.models[0]?.id ?? '')
    aiTick++
  }
  // Refresh: ask the providers which models the phone's keys can use (desktop: Settings > AI models)
  let listing = $state(false), listNote = $state('')
  async function refreshModels() {
    if (!m || listing) return
    listing = true; listNote = ''
    try { listNote = await m.refreshModels() } finally { listing = false; aiTick++ }
  }
  const drive = $derived(driveStatus())
  const driveBusy = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing)
  // Sync now (send this phone's changes, then read Drive) and the vault's, with every lane's line and bar
  const lanes = $derived(syncLanes())
  const running = $derived(lanes.filter(l => l.tag === 'running' || l.tag === 'stopping').length)
  const queued = $derived(lanes.filter(l => l.tag === 'queued').length)
  function driveSync() { syncNow().then(measure) }

  // without a PC (plans/08-phone-solo.md): the AI keys typed on the phone; its backup, pairing and recovery are on Backup &
  // phones (screens/Backup.svelte)
  let keyIn = $state({ anthropic: '', openai: '' }), keysNote = $state('')
  const canSolo = isApp || devSolo                      // keys only in the app's encrypted storage
  async function saveKeys() {
    if (!m) return
    try {
      setAiKeys(m.pair, { ...(m.pair.ai || {}), ...Object.fromEntries(Object.entries(keyIn).filter(([, v]) => v.trim())) })
      await secretsSaved()
      keyIn = { anthropic: '', openai: '' }
      keysNote = Object.keys(m.pair.ai).length ? 'Saved in this phone\'s encrypted storage.' : 'No key saved.'
      aiTick++
    } catch { keysNote = 'Keys could not be saved securely. Retry before leaving this page.' }
  }
</script>

<!-- the pairing-link paste field, under a disclosure in the box that pairs -->
{#snippet pasteLink()}
  <MDisclosure summary="Paste the pairing link instead">
    <MRow title="Pairing link" desc="Copy link, under the code on the PC"><MButton size="sm" onclick={() => pairFrom(pasted)} disabled={!pasted.includes('#pair=')}>Pair</MButton></MRow>
    <label class="m-fld"><input bind:value={pasted} placeholder="https://…#pair=…" aria-label="Pairing link" autocomplete="off" /></label>
  </MDisclosure>
{/snippet}

<div class="m-pad m-calm">
  <StatusCard />
  <SetupList />

  <!-- Sync: one row per lane (lanes.ts) with its state, its line, Sync now and its bar while it runs; the
       setup stays in the connection box below -->
  {#if m}
    <MBox>
      <h3>Sync<span class="m-sp"></span><span class="m-lamp" class:amber={syncPaused() || (!running && !queued && !drive.ok)} class:busy={running > 0}>{syncPaused() ? 'paused' : running ? `${running} running${queued ? ` · ${queued} queued` : ''}` : queued ? `${queued} queued` : drive.ok ? 'idle' : drive.lamp}</span></h3>
      <MHint>{solo ? 'Backs this phone up to Google Drive, without a PC or license.' : 'Pairing and sync are free. The paired PC renews signed access while online; it expires after one hour without renewal.'}</MHint>
      <MRow title="Wi-Fi only" desc={network.wifiOnly ? 'Uploads, sync and downloads wait for Wi-Fi. Edits stay on this phone.' : 'Uploads, sync and downloads can use mobile data.'}><MToggle label="Wi-Fi only" on={network.wifiOnly} onchange={on => setWifiOnly(on)} /></MRow>
      {#if network.wifiOnly && network.ready && network.type === 'unknown'}<MHint>Wi-Fi could not be confirmed. Use the Android app for network detection, or turn off Wi-Fi only to allow this connection.</MHint>{/if}
      {#each lanes as l (l.key)}
        <MRow desc="{l.text}{l.tag === 'running' && l.pct !== null ? ` · ${l.pct}%` : ''}">{#snippet title()}{l.name}{#if l.key !== 'network'} <span class="m-lbl">{l.tag}</span>{/if}{/snippet}{#if l.key === 'drive'}<MButton size="sm" onclick={driveSync} disabled={driveBusy || syncPaused()}>{driveBusy ? 'Syncing…' : 'Sync now'}</MButton>
          {:else if l.key === 'vault'}
            {#if vaultRun.opts.on}
              <span class="m-row" style="grid-row:1 / span 2;grid-column:2">
                <MButton size="sm" onclick={() => runVault()} disabled={vaultRun.busy || vaultRun.queued || !drive.ok || syncPaused()}>{vaultRun.stopping ? 'Stopping…' : vaultRun.busy ? 'Syncing…' : vaultRun.queued ? 'Queued' : 'Sync now'}</MButton>
                <MTextButton onclick={() => setVaultOn(false)} disabled={vaultRun.stopping}>Stop</MTextButton>
              </span>
            {:else if vaultRun.opts.uri}<MButton variant="pri" size="sm" onclick={() => setVaultOn(true)} disabled={vaultRun.busy}>Start</MButton>
            {:else}<MButton variant="pri" size="sm" onclick={pickVaultFolder}>Choose folder</MButton>{/if}
          {/if}
        </MRow>
        {#if l.active && l.pct !== null}<span class="m-pb" role="progressbar" aria-label={`${l.name} progress`} aria-valuenow={l.pct} aria-valuemin={0} aria-valuemax={100}><i style:width={`${l.pct}%`}></i></span>{/if}
      {/each}
      <MDisclosure summary="About sync">
        <MHint>{solo ? 'Your phone backup stays separate from any desktop library in the same account.' : 'While access is locked, saved content and queued edits stay on this phone.'}</MHint>
        {#if lanes.some(l => l.key === 'vault')}<MHint>The library read from Google Drive goes first: a vault round asked for while it runs waits in the queue, then starts on its own.</MHint>{/if}
      </MDisclosure>
    </MBox>
  {/if}

  {#if !m && isApp}
    <MBox id="m-conn">
      <h3>Pair with your PC<span class="m-sp"></span><span class="m-lamp amber">not paired</span></h3>
      {#if phone.note}<MHint>{phone.note}</MHint>{/if}
      <MRow title="Scan the pairing code" desc="On the PC: Settings > Backup & phones > Add a phone"><MButton variant="pri" size="sm" onclick={() => pairFrom()}>Scan</MButton></MRow>
      {@render pasteLink()}
      <MDisclosure summary="What the code carries">
        <MHint>The code carries the key to your encrypted library. AI keys you tick on the PC wait in your Google Drive, sealed with a one-time key, until this phone collects them; the code itself never holds them. The phone keeps both in its own encrypted storage; nothing goes through Brainamon.</MHint>
      </MDisclosure>
    </MBox>
  {:else if !m}
    <MBox id="m-conn">
      <h3>Your PC<span class="m-sp"></span><span class="m-lamp" class:amber={!phone.reachable}>{phone.reachable ? 'reachable' : 'off'}</span></h3>
      {#if phone.note}<MHint>{phone.note}</MHint>{/if}
      <MRow title={location.host} desc="{health?.licensed === false ? 'Update Brainamon on the PC for payment-free sync. Saved content stays here.' : health ? `${health.items.toLocaleString('en')} items on the PC` : 'Not reachable now'} · copy from {fmtAgo(phone.synced)}"><MButton size="sm" onclick={() => refresh().then(measure)} disabled={phone.refreshing}>{phone.refreshing ? 'Syncing…' : 'Refresh'}</MButton></MRow>
      <MDisclosure summary="Development mode">
        <MHint>This page reads the PC app directly (USB: adb reverse tcp:18765 tcp:18765). To use the phone with the PC off, pair it: on the PC, Settings > Backup & phones > Add a phone.</MHint>
      </MDisclosure>
    </MBox>
  {/if}

  <!-- Obsidian, together and right under Sync: the vault folder kept in step with the PC (Vault.svelte), then the
       name Open in Obsidian uses. Choose / Start / Stop also sit in the vault's row of the Sync box above. -->
  <Vault />
  <MBox>
    <h3>Open in Obsidian</h3>
    <MRow title="Vault name" desc="Open in Obsidian puts a note in Content Manager/notes there{source.obsidianVault?.() ? ` · the PC's is ${source.obsidianVault()}` : ''}" />
    <label class="m-fld"><input bind:value={vault} onchange={() => setVaultName(vault)} placeholder="The vault's name in Obsidian" aria-label="Obsidian vault name" autocomplete="off" /></label>
    <MHint>The PC's Export to Obsidian replaces these copies; edits made in Obsidian do not come back to Brainamon.</MHint>
  </MBox>

  {#if !m && canSolo}
    <MBox>
      <h3>No PC?<span class="m-sp"></span><span class="m-lbl">{devSolo ? 'development Drive' : 'this phone only'}</span></h3>
      <MRow title="Use Brainamon without a PC" desc="Save links, notes and chats locally, with optional encrypted Google Drive backup."><MButton variant="pri" size="sm" onclick={() => useWithoutPc()}>Start</MButton></MRow>
      <MRow title="Restore from Google Drive" desc="A phone backup, unlocked with its original recovery code"><MButton as="a" size="sm" href="#/recover">Recover a library…</MButton></MRow>
    </MBox>
  {/if}

  <!-- no Canvas box: Canvas is a tab (audit 2026-10-15 #12) -->

  {#if m}
    <MBox>
      <h3>Import</h3>
      <MRow title="Saved posts from Instagram" desc="Read Instagram Saved ZIP/JSON on this phone, without your login; some pictures may be unavailable"><MButton as="a" size="sm" href="#/import">Open</MButton></MRow>
    </MBox>
  {/if}

  {#if !m || solo}
  <MBox id="m-desktop">
    <h3>Your desktop library, anywhere</h3>
    <MHint>This app is a companion to Brainamon on your PC: browse your library on the go. The desktop app adds video analysis and Claude Code integration.</MHint>
    <MButton as="a" variant="pri" href={DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">Get the desktop app</MButton>
    <MDisclosure summary="What needs a PC">
      <MHint>Video downloads, browser scraping, video analysis, Smart search and exports. Some pictures may not load on the phone; the saved links still work.</MHint>
      <MHint>No social login is needed on the phone, and Drive sign-in does not connect social accounts.</MHint>
    </MDisclosure>
    <MDisclosure summary="Already have the desktop app?">
      <MHint>Update Brainamon on your PC and phone, then open Settings &gt; Backup &amp; phones on the PC to pair. No purchase or activation is needed.</MHint>
    </MDisclosure>
  </MBox>
  {/if}

  {#if m}
    <MBox id="m-ai">
      <h3>Wiskit on this phone<span class="m-sp"></span><span class="m-lamp" class:amber={!ai}>{ai ? 'ready' : 'no key'}</span></h3>
      {#if ai}
        <MRow title="Provider" desc={solo ? 'Your keys, in this phone\'s encrypted storage' : 'The AI keys the PC sent with the pairing'}><MSeg label="Provider" size="sm" options={ai.providers.map(p => [p.id, p.label] as [string, string])} value={ai.provider} onchange={id => pickAi(id, ai.model)} /></MRow>
        <MRow title="Model" desc="Wiskit answers with it, on your key"><label class="m-fld" style="padding:5px 8px;grid-row:1 / span 2;grid-column:2"><select value={ai.model} onchange={e => pickAi(ai.provider, (e.currentTarget as HTMLSelectElement).value)} aria-label="Model">{#each ai.providers.find(p => p.id === ai.provider)?.models ?? [] as md (md.id)}<option value={md.id}>{md.label}</option>{/each}</select><span>▾</span></label>
        </MRow>
        <MRow title="Model lists" desc={listNote || 'Ask the providers which models your keys can use'}><MButton size="sm" onclick={refreshModels} disabled={listing}>{listing ? 'Checking…' : 'Refresh'}</MButton></MRow>
        {#if solo}
          <MHint>Wiskit reads your notes and chats here; saved links have no text until a PC describes them. Smart search needs the PC.</MHint>
        {:else}
          <MHint>Smart search {ai.smart ? 'ranks by meaning with your OpenAI key' : 'needs an OpenAI key (keyword search still works)'}. Synthesize uses {ai.synth || 'the PC'}, up to {m.synthMax} sources; bigger notes wait for the PC.</MHint>
        {/if}
        <!-- ai.smart is "an OpenAI key is on this phone" (mirror.ts ai()): voice notes and search by meaning need it -->
        {#if !ai.smart}<MHint>{solo ? 'Add an OpenAI key for voice notes and search by meaning.' : 'Voice notes and search by meaning need an OpenAI key: pair again from the PC with it ticked.'}</MHint>{/if}
      {:else if solo}
        <MHint>Recommended: an OpenAI key. With it Wiskit answers on this phone, and it also turns on voice notes and finds items by meaning. An Anthropic key only answers; you can add both. Keys stay in the phone's encrypted storage and never go to Google Drive or Brainamon.</MHint>
      {:else if m.pair.t}
        <MHint>Waiting for the AI keys you ticked on the PC: they come through Google Drive once it is connected, for 30 minutes after the code was made. If none arrive, pair again from the PC.</MHint>
      {:else}
        <MHint>To use Wiskit, Smart search and Synthesize with the PC off, pair the phone again with an AI key ticked (PC: Settings > Backup & phones > Add a phone). Recommended: tick the OpenAI key; it also turns on voice notes and search by meaning. The phone then calls the AI itself with your key; nothing goes through Brainamon.</MHint>
      {/if}
      {#if solo}
        <!-- OpenAI first and marked recommended (decision 8); the aria-labels stay the accessible names -->
        <label class="m-fld"><span>OpenAI · recommended</span><input type="password" bind:value={keyIn.openai} placeholder={m.pair.ai?.openai ? 'saved · retype to replace' : 'sk-…'} aria-label="OpenAI API key" autocomplete="off" spellcheck="false" /></label>
        <label class="m-fld"><span>Anthropic · optional</span><input type="password" bind:value={keyIn.anthropic} placeholder={m.pair.ai?.anthropic ? 'saved · retype to replace' : 'sk-ant-…'} aria-label="Anthropic API key" autocomplete="off" spellcheck="false" /></label>
        <div class="m-acts"><span class="m-sp"></span><MButton variant="dk" onclick={saveKeys} disabled={!keyIn.anthropic.trim() && !keyIn.openai.trim()}>Save keys</MButton></div>
        {#if keysNote}<MHint>{keysNote}</MHint>{/if}
      {/if}
      <MDisclosure summary="What is sent to the provider">
        <MHint>AI sends prompts and relevant library text, notes and chat context to {ai?.providers.find(p => p.id === ai.provider)?.label ?? 'your chosen Anthropic or OpenAI provider'}. Configured endpoints or proxies can also receive these requests. Picture/PDF features send selected files; transcription sends audio to OpenAI. Search and Deep can send query/library text to OpenAI for embeddings. Provider charges apply separately; recipient terms and retention apply.</MHint>
      </MDisclosure>
      {#if ai}
        <MRow title="AI keys on this phone" desc="{ai.providers.map(p => p.label).join(', ')} · forgetting them keeps the phone paired"><MTextButton tone="danger" onclick={forgetAi}>{confirmForgetAi ? 'Sure? Forget' : 'Forget'}</MTextButton></MRow>
      {/if}
    </MBox>
  {/if}

  <MBox class="lcd">
    <h3>On this phone<span class="m-sp"></span><span class="m-lbl">{fmtMB(total)}</span></h3>
    <div class="m-stack">{#each parts as p (p[0])}<i style:width="{Math.max(2, total ? p[1] / total * 100 : 0)}%" style:background={p[2]}></i>{/each}</div>
    <div class="m-keys3">{#each parts as p (p[0])}<i style:background={p[2]}></i><span><b>{p[0]}</b><em style="font-style:normal">{fmtMB(p[1])} · {p[3]}</em></span>{/each}</div>
    {#if use?.quota}<span class="m-lbl">Browser storage: {fmtMB(use.usage)} used of {fmtMB(use.quota)}{offline.persisted ? ' · kept by the phone' : ''}</span>{/if}
  </MBox>

  <MBox>
    <h3>Keep automatically</h3>
    <MRow title="Favourites" desc="Thumbnails and opened text kept on this phone for offline use"><MToggle label="Keep favourites" on={true} disabled /></MRow>
    <MRow title="Keep all canvases" desc={m ? 'With their images, for viewing with no signal' : 'With the Google Drive mirror'}><MToggle label="Keep all canvases" on={offline.keepCanvases} disabled={!m} onchange={on => wantCanvases(on)} /></MRow>
    <MRow title="Keep videos" desc={m ? 'The videos your PC put in Google Drive' : 'With the Google Drive mirror'}><MSeg label="Keep videos" size="sm" options={[['off', 'Off'], ['fav', 'Favs'], ['all', 'All']]} value={offline.keepVideos} disabled={!m} onchange={v => wantVideos(v as KeepVideos)} /></MRow>
    {#if ask}
      <div class="m-ask">
        <b>{ask.kind === 'videos' ? `Keep videos (${ask.v === 'fav' ? 'favourites' : 'all'}): ${ask.count} video${ask.count === 1 ? '' : 's'}, ${fmtMB(ask.bytes)}` : `Keep all canvases: ${fmtMB(ask.bytes)}`}</b>
        <small>{free ? `This phone has about ${fmtMB(free)} free for Brainamon.` : ''}{free && ask.bytes > free * 0.8 ? ' That is most of it: some may not fit.' : ''} {offline.wifiOnly ? 'Downloads wait for Wi-Fi.' : 'Downloads use mobile data too.'}</small>
        <div class="m-acts"><MButton onclick={() => (ask = null)}>Cancel</MButton><MButton variant="dk" onclick={confirm}>Turn on</MButton></div>
      </div>
    {/if}
    {#if offline.busy}<MHint>Downloading: {offline.busy}</MHint>{/if}
  </MBox>

  {#if m}
    <MBox>
      <h3>Saved for offline<span class="m-sp"></span><span class="m-lbl">{fmtMB(savedBytes)}</span></h3>
      <MHint>Items and canvases you saved from their screens stay until you remove them.</MHint>
      <MDisclosure summary={`${offline.saved.length + offline.canvases.length} saved`}>
        <div class="m-olist">
          {#each offline.saved as s (s.id)}
            {@const r = phone.byId.get(s.id)}
            <div class="m-oit">
              {#if r?.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span></span>{/if}
              <div><b>{r?.title || s.item.short_desc || 'No.' + s.id}</b><small>{fmtMB(s.size ?? 0)} · {s.report ? 'report' : 'description'}{s.transcript ? ' + transcript' : ''}{s.item.files?.video ? ' + video' : ''} · saved {fmtAgo(s.at)}</small></div>
              <button type="button" onclick={() => removeItem(s.id).then(measure)}>Remove</button>
            </div>
          {/each}
          {#each offline.canvases as c (c.id)}
            <div class="m-oit">
              <span class="m-cvi">▦</span>
              <div><b>{c.name}</b><small>Canvas · {fmtMB(c.size)} · {c.images.length} image{c.images.length === 1 ? '' : 's'} · saved {fmtAgo(c.at)}</small></div>
              <button type="button" onclick={() => removeCanvas(c.id).then(measure)}>Remove</button>
            </div>
          {/each}
          {#if !offline.saved.length && !offline.canvases.length}
            <div class="m-empty" style="padding:12px">Save an item (with its video) or a canvas for offline from its screen: it stays until you remove it.</div>
          {/if}
        </div>
      </MDisclosure>
    </MBox>
  {/if}

  <MBox>
    <h3>Opened recently<span class="m-sp"></span><span class="m-lbl">{kept.length} items</span></h3>
    <MHint>Items you open stay here for reading with no signal.</MHint>
    <MDisclosure summary={`${Math.min(kept.length, 30)} shown`}>
      <div class="m-olist">
        {#each kept.slice(0, 30) as s (s.id)}
          {@const r = phone.byId.get(s.id)}
          <div class="m-oit">
            {#if r?.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span></span>{/if}
            <div><b>{r?.title || s.item.short_desc || 'No.' + s.id}</b><small>{s.report ? 'report' : 'description'}{s.transcript ? ' + transcript' : ''} · opened {fmtAgo(s.at)}{r?.fav ? ' · favourite' : ''}</small></div>
            <button type="button" onclick={() => forget(s.id)}>Remove</button>
          </div>
        {:else}
          <div class="m-empty" style="padding:12px">Nothing opened yet.</div>
        {/each}
      </div>
    </MDisclosure>
  </MBox>

  <MBox>
    <h3>Cache limit<span class="m-sp"></span><span class="m-lbl">{phone.capMB} MB</span></h3>
    <input type="range" class="m-range" min="50" max="1000" step="50" value={phone.capMB} oninput={e => setCap(+(e.currentTarget as HTMLInputElement).value)} aria-label="Cache limit" />
    <MHint>Thumbnails you scrolled past. Oldest go first; favourites and saved items never do.</MHint>
  </MBox>

  <MBox>
    <h3>Look</h3>
    <MRow title="Night" desc="Follows the phone unless you switch it"><MToggle label="Night" on={dark} onchange={() => { toggleTheme(); dark = isDark() }} /></MRow>
    <MRow title="Card style" desc="Auto: Cover, Holo for favourites"><MSeg label="Card style" size="sm" options={CARD_STYLES} value={phone.cardStyle} onchange={v => setCardStyle(v as CardStyle)} /></MRow>
    <MRow title="Card motion" desc="Tilt and shine on the Item card"><MToggle label="Card motion" on={!phone.motionOff} onchange={on => setMotionOff(!on)} /></MRow>
    <MRow title="Clear the phone's copy" desc="Rows, thumbnails and opened items; saved ones and unsent changes stay"><MTextButton tone="danger" onclick={clearAll} disabled={clearNote === 'Clearing…'}>Clear</MTextButton></MRow>
    {#if clearNote}<MHint>{clearNote}</MHint>{/if}
    <MDisclosure summary="About clearing">
      <MHint>Clear reloads from the source. Unpair also keeps some saved data. For complete local removal, review pending edits first, then clear Brainamon's storage in Android Settings or clear this browser's site data. Other devices, Drive and backups keep their copies.</MHint>
    </MDisclosure>
  </MBox>

  {#if isApp}
    <MBox id="m-app-info">
      <h3>App info</h3>
      {#if info}
        <MRow title="Version" desc={info.version} />
        <MRow title="Build" desc={info.build} />
      {:else if infoError}
        <MHint tone="error" role="alert">{infoError}</MHint>
        <MButton size="sm" onclick={readAppInfo}>Retry</MButton>
      {:else}
        <MHint role="status">Loading app info…</MHint>
      {/if}
    </MBox>
  {/if}
  <MBox>
    <h3>Privacy and licenses</h3>
    <MHint>Bundled with the app. Read offline, without a PC or Google sign-in.</MHint>
    <LegalDocuments />
  </MBox>
</div>
