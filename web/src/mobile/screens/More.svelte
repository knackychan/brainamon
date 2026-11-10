<script lang="ts">
  // Settings (#/more, projects/phone-settings, spec docs/superpowers/specs/2026-11-07-phone-settings-design.md section 2;
  // before it 07 More, calm, docs/superpowers/plans/2026-10-29-phone-settings-calm.md): the round Back and the tag
  // (PageKeys.svelte), then the status: a phone paired with a PC or used without one shows its PhoneState
  // (StatusCard.svelte; its Google Drive, pairing and recovery are on Settings > Backup & phones, screens/Backup.svelte),
  // the fresh Android app shows Pair with your PC, a browser on the PC's address shows Your PC (both id m-conn). Then one
  // row per group (ui/MGroup.svelte, one open at a time; every state line from settings-lines.ts): Sync (what runs now
  // and what waits, lanes.ts), Your phone / Your PC (to Backup & phones), Wiskit on this phone, Obsidian (Vault.svelte),
  // Storage (keep automatically, the meter, the two lists, the cache limit, Clear), Look, About (the desktop app, App
  // info, the legal documents). The fresh app adds Use without a PC and Recover a library… (#/recover). Help sits
  // behind MInfo; quiet and destructive actions are MTextButtons.
  import { onMount } from 'svelte'
  import { beginLanguageWork, languageWorkChanged, registerLanguageCheck, switchLanguage } from '../language-switch.ts'
  import { LANGS, lang, t, type Choice, type Key } from '../../lib/i18n/index.ts'
  import { phoneWords, lampLabel } from '../settings-words'
  import { fmtNum } from '../../lib/i18n/format.ts'
  import T from '../../lib/i18n/T.svelte'
  import { items as idb, storageUse, wipe } from '../store'
  import { devSolo, driveStatus, fmtAgo, fmtMB, isDark, measurePend, mirrorSource, pairFrom, phone, phoneStatus, refresh, setCap, setCardStyle, setMotionOff, syncNow, cardStyles, solo, source, toggleTheme, useWithoutPc, type CardStyle } from '../state.svelte'
  import { syncLanes } from '../lanes'
  import { pickVaultFolder, runVault, setVaultOn, vault as vaultRun } from '../vault/auto.svelte'
  import { appInfo, isApp, secretsHaveFailures, secretsSaved } from '../native'
  import { setAiKey, token } from '../mirror/pairing'
  import { freeSpace, keepCanvasesNeed, keepVideosNeed, offline, removeCanvas, removeItem, setKeep, setKeepVideos, type KeepVideos } from '../offline.svelte'
  import type { StoredItem } from '../store'
  import Vault from '../Vault.svelte'
  import PageKeys from '../PageKeys.svelte'
  import StatusCard from '../StatusCard.svelte'
  import LegalDocuments from '../../components/LegalDocuments.svelte'
  import privacyFrench from '../../../../mobile-shell/store/privacy-policy.fr.md?raw'
  import privacyTraditionalChinese from '../../../../mobile-shell/store/privacy-policy.zh-Hant.md?raw'
  import { network, setSyncPaused, setWifiOnly, syncPaused } from '../network.svelte'
  import { aboutLine, aiLine, lookLine, phoneLine, settingsTones, storageLine, syncLine } from '../settings-lines'
  import { setGroups } from '../ui/groups.svelte'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MGroup from '../ui/MGroup.svelte'
  import MHint from '../ui/MHint.svelte'
  import MInfo from '../ui/MInfo.svelte'
  import MRow from '../ui/MRow.svelte'
  import MStatus from '../ui/MStatus.svelte'
  import MToggle from '../ui/MToggle.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import { DOWNLOAD_URL } from '../../lib/product-links'

  setGroups()
  let use = $state<Awaited<ReturnType<typeof storageUse>> | null>(null)
  let app = $state<Awaited<ReturnType<typeof appInfo>> | null>(null)
  let infoError = $state('')
  async function readAppInfo() {
    infoError = ''
    try { app = await appInfo() }
    catch { infoError = t('settings.about.infoFailed') }
  }
  onMount(() => {
    if (isApp) void readAppInfo()
    return registerLanguageCheck(() => keyIn.openai || keyIn.anthropic ? 'settings.language.unsavedKeys'
      : pasted ? 'settings.language.unsavedPairing' : null)
  })
  let kept = $state<StoredItem[]>([])
  let health = $state<{ ok: boolean; items: number; licensed?: boolean } | null>(null)
  let dark = $state(isDark())
  let free = $state(0)
  let ask = $state<{ kind: 'videos'; v: KeepVideos; count: number; bytes: number } | { kind: 'canvases'; bytes: number } | null>(null)
  const m = mirrorSource
  const st = $derived(phoneStatus())
  // a group key is orange only while the status above offers no key (spec section 6.3)
  const lead = $derived(!st?.action)

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
  const parts = $derived(use ? [[t('settings.storage.light'), use.light, 'var(--m-teal)', t('settings.storage.always')], [t('settings.storage.thumbnails'), use.thumbBytes, 'var(--lcd-dim)', t('settings.storage.cap', { cap: phone.capMB })], [t('settings.storage.opened'), use.fullBytes, 'var(--accent)', t('settings.storage.kept', { n: use.fullItems })], [t('settings.storage.saved'), savedBytes, 'var(--m-warn)', t('settings.storage.savedCount', { n: offline.saved.length + offline.canvases.length })]] as [string, number, string, string][] : [])
  async function forget(id: number) {
    const done = beginLanguageWork()
    try { await idb.del(id); await measure() } finally { done() }
  }
  // Clear asks twice (Fred 2026-11-07): the stores and the mirror's in-memory copy both go, then the list loads again
  // from the source
  let clearNote = $state(''), confirmClear = $state(false)
  async function clearAll() {
    if (clearNote === 'Clearing…') return
    if (!confirmClear) { confirmClear = true; return }
    const done = beginLanguageWork()
    confirmClear = false
    clearNote = 'Clearing…'
    try {
      await wipe()
      m?.forgetCopy()
      phone.rows = []
      navigator.serviceWorker?.controller?.postMessage({ type: 'clear' })
      const why = await refresh()
      clearNote = why ? t('settings.storage.clearedWaiting', { detail: why }) : t('settings.storage.cleared', { n: fmtNum(phone.rows.length, 'en') })
      await measure()
    } finally { done() }
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
  let aiTick = $state(0)
  const ai = $derived((phone.synced, aiTick, m?.ai() ?? null))
  let confirmForgetAi = $state(false)
  function forgetAi() {
    if (!confirmForgetAi) { confirmForgetAi = true; return }
    confirmForgetAi = false
    m?.forgetKeys()
    savedKeys = { openai: false, anthropic: false }
    editingKeys = { openai: true, anthropic: true }
    keysNote = ''
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
    const done = beginLanguageWork()
    listing = true; listNote = ''
    try { listNote = await m.refreshModels(phoneWords) } finally { listing = false; aiTick++; done() }
  }
  const drive = $derived(driveStatus())
  const driveBusy = $derived((!!phone.sync && !phone.sync.end) || phone.refreshing)
  // token() is not reactive: read it again when a token comes or goes (phone.tokenAt) or Google refuses it
  const signedIn = $derived((phone.tokenAt, phone.signIn, m ? !!token(m.pair) : false))
  // Sync now (send this phone's changes, then read Drive) and the vault's, with every lane's line and bar
  const lanes = $derived(syncLanes())
  const running = $derived(lanes.filter(l => l.tag === 'running' || l.tag === 'stopping').length)
  const queued = $derived(lanes.filter(l => l.tag === 'queued').length)
  const syncLamp = $derived(syncPaused() ? lampLabel('paused') : running ? t('settings.sync.runningCount', { running, queued: queued ? t('settings.sync.queuedSuffix', { n: queued }) : '' }) : queued ? t('settings.sync.queuedCount', { n: queued }) : drive.ok ? 'idle' : lampLabel(drive.lamp))
  function driveSync() { syncNow().then(measure) }
  const aiProvider = $derived(ai ? ai.providers.find(p => p.id === ai.provider)?.label ?? ai.provider : '')
  const tones = $derived(settingsTones(st, { running: running > 0, driveOk: drive.ok, ai: !!ai }))
  const styleName = $derived(cardStyles().find(([v]) => v === phone.cardStyle)?.[1] ?? 'Auto')
  const desktop = !m || solo                              // the Windows app shows while the phone is not paired

  // without a PC (plans/08-phone-solo.md): the AI keys typed on the phone; its backup, pairing and recovery are on Backup &
  // phones (screens/Backup.svelte)
  let keyIn = $state({ anthropic: '', openai: '' }), keysNote = $state('')
  let savedKeys = $state({ openai: !!m?.pair.ai?.openai, anthropic: !!m?.pair.ai?.anthropic })
  let editingKeys = $state({ openai: !m?.pair.ai?.openai, anthropic: !m?.pair.ai?.anthropic })
  const canSolo = isApp || devSolo                      // keys only in the app's encrypted storage
  let savingKey = $state('')
  let languageChoice = $state<Choice>((() => {
    try {
      const value = localStorage.getItem('bp-lang')
      return value === 'en' || value === 'fr' || value === 'zh-Hant' ? value : 'auto'
    } catch { return 'auto' }
  })())
  let changingLanguage = $state(false), languageError = $state('')
  const selectedLanguage = $derived(LANGS.find(entry => entry.id === lang())!)
  const languageDetail = $derived(languageChoice === 'auto' ? t('settings.language.resolved', { language: selectedLanguage.name })
    : !selectedLanguage.ready ? t('settings.language.preview', { language: selectedLanguage.name }) : '')
  async function changeLanguage(value: string) {
    if (value !== 'auto' && value !== 'en' && value !== 'fr' && value !== 'zh-Hant') return
    if (value === languageChoice || changingLanguage) return
    if (keyIn.openai || keyIn.anthropic) { languageError = t('settings.language.unsavedKeys'); return }
    if (pasted) { languageError = t('settings.language.unsavedPairing'); return }
    changingLanguage = true; languageError = ''
    const root = document.getElementById('m-app') as HTMLElement | null
    const wasInert = root?.inert ?? false
    if (root) root.inert = true
    let reloading = false
    try {
      const result = await switchLanguage(value, languageChoice, async () => {
        await secretsSaved()
        if (secretsHaveFailures()) throw new Error('Secure write failed')
      }, localStorage, () => location.reload())
      if (result.status === 'reloaded') { reloading = true; return }
      if (result.status === 'blocked') languageError = t(result.reason as Key)
      else if (result.status === 'storage-error') languageError = t('settings.language.storageError')
    } catch {
      languageError = t('settings.language.storageError')
    } finally {
      if (!reloading) { if (root) root.inert = wasInert; changingLanguage = false }
    }
  }
  async function saveKey(provider: 'openai' | 'anthropic') {
    if (!m) return
    savingKey = provider
    try {
      const previous = m.ai()
      if (previous) m.setAi(previous.provider, previous.model)
      setAiKey(m.pair, provider, keyIn[provider])
      await secretsSaved()
      keyIn[provider] = ''
      savedKeys[provider] = true
      editingKeys[provider] = false
      keysNote = t('settings.keys.saved', { provider: provider === 'openai' ? 'OpenAI' : 'Anthropic' })
      aiTick++
    } catch { keysNote = t('settings.keys.failed') }
    finally { savingKey = '' }
  }
</script>

<!-- the pairing-link paste field, under a disclosure in the box that pairs -->
{#snippet pasteLink()}
  <MDisclosure summary={t('settings.pair.paste')}>
    <MRow title={t('settings.pair.link')} desc={t('settings.pair.copyHint')}><MButton size="sm" onclick={() => pairFrom(pasted)} disabled={!pasted.includes('#pair=')}>{t('settings.pair.pair')}</MButton></MRow>
    <label class="m-fld"><input bind:value={pasted} oninput={languageWorkChanged} placeholder="https://…#pair=…" aria-label={t('settings.pair.link')} autocomplete="off" /></label>
  </MDisclosure>
{/snippet}

<PageKeys />
<div class="m-pad m-calm m-page">
  {#if m}
    <StatusCard />
  {:else if isApp}
    <MBox id="m-conn">
      <MStatus look="hero" kicker={t('settings.pair.pc')} tone="next" text={t('settings.pair.notPaired')} detail={t('settings.pair.scanHint')} infoTitle={t('settings.pair.codeTitle')}>
        {#snippet info()}
          <p>{t('settings.pair.codeHelp')}</p>
          <p>{t('settings.pair.storageHelp')}</p>
          <p><T id="settings.pair.soloHelp" /></p>
        {/snippet}
        <MButton shape="pill" variant="pri" onclick={() => pairFrom()}>{t('settings.pair.scan')}</MButton>
      </MStatus>
      {#if phone.note}<MHint>{phone.note}</MHint>{/if}
      {@render pasteLink()}
    </MBox>
  {:else}
    <MBox id="m-conn">
      <MStatus look="hero" kicker={t('settings.group.pc')} tone={phone.reachable ? 'done' : 'next'} text={phone.reachable ? t('settings.pair.connectedPc') : t('settings.pair.unreachablePc')}
        detail={t('settings.pair.directStatus', { host: location.host, status: health?.licensed === false ? t('settings.pair.pcUpdate') : health ? t('settings.pair.pcItems', { n: fmtNum(health.items, 'en') }) : t('settings.pair.pcOffline'), ago: fmtAgo(phone.synced) })} infoTitle={t('settings.pair.directTitle')}>
        {#snippet info()}<p>{t('settings.pair.directHelp')}</p>{/snippet}
        <MButton shape="pill" onclick={() => refresh().then(measure)} disabled={phone.refreshing}>{phone.refreshing ? t('settings.sync.syncing') : t('settings.keys.refresh')}</MButton>
      </MStatus>
      {#if phone.note}<MHint>{phone.note}</MHint>{/if}
    </MBox>
  {/if}

  <!-- Sync: one row per lane (lanes.ts) with its state, its line, Sync now and its bar while it runs -->
  {#if m}
    <MGroup title={t('shell.sync.title')} line={syncLine({ signedIn, lamp: syncLamp, wifiOnly: network.wifiOnly }, phoneWords)} tone={tones.sync}>
      {#snippet info()}
        <p>{solo ? t('settings.sync.soloHelp') : t('settings.sync.pairedHelp')}</p>
        <p>{t('settings.sync.wifiHelp')}</p>
        <p>{t('settings.sync.pauseHelp')}</p>
        {#if lanes.some(l => l.key === 'vault')}<p>{t('settings.sync.queueHelp')}</p>{/if}
      {/snippet}
      <MRow title={t('settings.sync.wifi')} desc={network.wifiOnly ? t('settings.sync.waitWifi') : t('settings.sync.mobile')}><MToggle label={t('settings.sync.wifi')} on={network.wifiOnly} onchange={on => setWifiOnly(on)} /></MRow>
      <MRow title={t('settings.sync.background')} desc={network.manualPause ? t('settings.sync.paused') : t('settings.sync.auto')}><MButton size="sm" onclick={() => setSyncPaused(!network.manualPause)}>{network.manualPause ? t('shell.sync.resume') : t('shell.sync.pause')}</MButton></MRow>
      {#if network.wifiOnly && network.ready && network.type === 'unknown'}<MHint>{t('settings.sync.unknownWifi')}</MHint>{/if}
      {#each lanes as l (l.key)}
        <MRow desc="{l.text}{l.tag === 'running' && l.pct !== null ? ` · ${l.pct}%` : ''}">{#snippet title()}{l.name}{#if l.key !== 'network'} <span class="m-lbl">{lampLabel(l.tag)}</span>{/if}{/snippet}{#if l.key === 'drive'}<MButton size="sm" onclick={driveSync} disabled={driveBusy || syncPaused()}>{driveBusy ? t('settings.sync.syncing') : t('shell.sync.now')}</MButton>
          {:else if l.key === 'vault'}
            <!-- one key at a time: Stop while a round runs, Sync now otherwise (Stop syncing also sits in the Obsidian group) -->
            {#if vaultRun.opts.on && (vaultRun.busy || vaultRun.stopping)}<MTextButton onclick={() => setVaultOn(false)} disabled={vaultRun.stopping}>{vaultRun.stopping ? t('settings.sync.stopping') : t('settings.sync.stop')}</MTextButton>
            {:else if vaultRun.opts.on}<MButton size="sm" onclick={() => runVault()} disabled={vaultRun.queued || !drive.ok || syncPaused()}>{vaultRun.queued ? t('settings.sync.queued') : t('shell.sync.now')}</MButton>
            {:else if vaultRun.opts.uri}<MButton variant={lead ? 'pri' : 'default'} size="sm" onclick={() => setVaultOn(true)} disabled={vaultRun.busy}>{t('settings.sync.start')}</MButton>
            {:else}<MButton variant={lead ? 'pri' : 'default'} size="sm" onclick={pickVaultFolder}>{t('settings.sync.folder')}</MButton>{/if}
          {/if}
        </MRow>
        {#if l.active && l.pct !== null}<span class="m-pb" role="progressbar" aria-label={t('settings.sync.progress', { name: l.name })} aria-valuenow={l.pct} aria-valuemin={0} aria-valuemax={100}><i style:width={`${l.pct}%`}></i></span>{/if}
      {/each}
    </MGroup>
    {#if solo}<MGroup title={t('settings.group.phone')} href="#/backup" line={phoneLine(true, m.pair.f, phoneWords)} tone={tones.phone} />
    {:else}<MGroup title={t('settings.group.pc')} href="#/backup" line={phoneLine(false, m.pair.f, phoneWords)} tone={tones.phone} />{/if}
  {/if}

  {#if !m && canSolo}
    <MGroup title={t('settings.group.solo')} line={devSolo ? 'Development Drive' : t('settings.pair.soloOnly')}>
      {#snippet action()}<MButton size="sm" onclick={() => useWithoutPc()}>{t('settings.sync.start')}</MButton>{/snippet}
    </MGroup>
    <MGroup title={t('recovery.action.recoverEllipsis')} href="#/recover" line={t('recovery.action.restoreDrive')} />
  {/if}

  {#if m}
    <MGroup title={t('settings.group.ai')} id="m-ai" line={aiLine(aiProvider, solo, phoneWords)} tone={tones.ai} onclose={() => { confirmForgetAi = false }}>
      {#snippet info()}
        <p>{solo ? t('settings.keys.soloStorage') : t('settings.keys.pairedStorage')}</p>
        <p>{t('settings.keys.help')}</p>
        {#if ai}
          {#if solo}<p>{t('settings.keys.soloHelp')}</p>
          {:else}<p>{t('settings.keys.capabilities', { smart: t(ai.smart ? 'settings.keys.smartAvailable' : 'settings.keys.smartNeedsKey'), model: ai.synth || t('settings.keys.thePc'), n: m.synthMax })}</p>{/if}
        {:else if !solo}
          <p>{t('settings.keys.pairHelp')}</p>
          {#if m.pair.t}<p>{t('settings.keys.transferHelp')}</p>{/if}
        {/if}
        <p>{t('settings.keys.disclosure', { provider: ai?.providers.find(p => p.id === ai.provider)?.label ?? t('settings.keys.chosenProvider') })}</p>
        <p>{t('settings.keys.charges')}</p>
      {/snippet}
      {#if ai}
        <!-- one key: the provider is a fact, not a choice -->
        <MRow title={t('settings.keys.provider')}>{#if ai.providers.length > 1}<MSeg label={t('settings.keys.provider')} size="sm" options={ai.providers.map(p => [p.id, p.label] as [string, string])} value={ai.provider} onchange={id => pickAi(id, ai.model)} />{:else}<span class="m-val">{ai.providers[0]?.label ?? ai.provider}</span>{/if}</MRow>
        <MRow title={t('settings.keys.model')}><label class="m-fld"><select value={ai.model} onchange={e => pickAi(ai.provider, (e.currentTarget as HTMLSelectElement).value)} aria-label={t('settings.keys.model')}>{#each ai.providers.find(p => p.id === ai.provider)?.models ?? [] as md (md.id)}<option value={md.id}>{md.label}</option>{/each}</select><span>▾</span></label>
        </MRow>
        <MRow title={t('settings.keys.lists')} desc={listNote || undefined}><MButton size="sm" onclick={refreshModels} disabled={listing}>{listing ? t('settings.keys.checking') : t('settings.keys.refresh')}</MButton></MRow>
        <!-- ai.smart is "an OpenAI key is on this phone" (mirror.ts ai()): voice notes and search by meaning need it -->
        {#if !ai.smart}<MHint>{solo ? t('settings.keys.addOpenai') : t('settings.keys.pairOpenai')}</MHint>{/if}
      {:else if !solo && m.pair.t}
        <MHint>{t('settings.keys.waiting')}</MHint>
      {:else if !solo}
        <MHint>{t('settings.keys.pairAgain')}</MHint>
      {/if}
      {#if solo}
        <!-- OpenAI first and marked recommended (decision 8); the aria-labels stay the accessible names -->
        <MRow title={t('settings.keys.openai')} desc={t('settings.keys.recommended')} />
        <div class:saved={savedKeys.openai && !editingKeys.openai} class="m-keyrow"><label class="m-fld"><input type="password" bind:value={keyIn.openai} oninput={languageWorkChanged} placeholder={savedKeys.openai && !editingKeys.openai ? t('settings.keys.savedPlaceholder') : 'sk-…'} disabled={!editingKeys.openai || !!savingKey} aria-label={t('settings.keys.openaiLabel')} autocomplete="off" spellcheck="false" /></label>
          {#if savedKeys.openai && !editingKeys.openai}<MButton size="sm" aria-label={t('settings.keys.changeOpenai')} disabled={!!savingKey} onclick={() => { editingKeys.openai = true; keysNote = '' }}>{t('settings.keys.change')}</MButton>
          {:else}<MButton size="sm" aria-label={t('settings.keys.saveOpenai')} onclick={() => saveKey('openai')} disabled={!!savingKey || !keyIn.openai.trim()}>{savingKey === 'openai' ? t('settings.keys.saving') : t('common.save')}</MButton>{/if}</div>
        <MRow title={t('settings.keys.anthropic')} desc={t('settings.keys.optional')} />
        <div class:saved={savedKeys.anthropic && !editingKeys.anthropic} class="m-keyrow"><label class="m-fld"><input type="password" bind:value={keyIn.anthropic} oninput={languageWorkChanged} placeholder={savedKeys.anthropic && !editingKeys.anthropic ? t('settings.keys.savedPlaceholder') : 'sk-ant-…'} disabled={!editingKeys.anthropic || !!savingKey} aria-label={t('settings.keys.anthropicLabel')} autocomplete="off" spellcheck="false" /></label>
          {#if savedKeys.anthropic && !editingKeys.anthropic}<MButton size="sm" aria-label={t('settings.keys.changeAnthropic')} disabled={!!savingKey} onclick={() => { editingKeys.anthropic = true; keysNote = '' }}>{t('settings.keys.change')}</MButton>
          {:else}<MButton size="sm" aria-label={t('settings.keys.saveAnthropic')} onclick={() => saveKey('anthropic')} disabled={!!savingKey || !keyIn.anthropic.trim()}>{savingKey === 'anthropic' ? t('settings.keys.saving') : t('common.save')}</MButton>{/if}</div>
        <div role="status">{#if keysNote}<MHint>{keysNote}</MHint>{/if}</div>
      {/if}
      {#if ai}
        <MRow title={t('settings.keys.onPhone')} desc={t('settings.keys.remainPaired', { providers: ai.providers.map(p => p.label).join(', ') })}><MTextButton tone="danger" onclick={forgetAi}>{confirmForgetAi ? t('settings.keys.confirmForget') : t('settings.keys.forget')}</MTextButton></MRow>
      {/if}
    </MGroup>
  {/if}

  <!-- Obsidian (Vault.svelte): the vault folder kept in step with the PC, then the name Open in Obsidian uses. Sync
       now / Stop also sit in the vault's row of the Sync group above. -->
  <Vault />

  <MGroup title={t('settings.group.storage')} line={storageLine(fmtMB(total), offline.keepCanvases, offline.keepVideos, phoneWords)} infoTitle={t('settings.storage.offlineHelpTitle')} onclose={() => { confirmClear = false }}>
    {#snippet info()}<p>{t('settings.storage.favouritesHelp')}</p><p>{t('settings.storage.keepHelp')}</p>{/snippet}
    <span class="m-lbl">{t('settings.storage.automatic')}</span>
    <MRow title={t('settings.storage.favourites')}><MToggle label={t('settings.storage.keepFavourites')} on={true} disabled /></MRow>
    <MRow title={t('settings.storage.canvases')} desc={m ? undefined : t('settings.storage.needsDrive')}><MToggle label={t('settings.storage.canvases')} on={offline.keepCanvases} disabled={!m} onchange={on => wantCanvases(on)} /></MRow>
    <MRow title={t('settings.storage.videos')} desc={m ? undefined : t('settings.storage.needsDrive')}><MSeg label={t('settings.storage.videos')} size="sm" options={[['off', t('settings.storage.off')], ['fav', t('settings.storage.favs')], ['all', t('settings.storage.all')]]} value={offline.keepVideos} disabled={!m} onchange={v => wantVideos(v as KeepVideos)} /></MRow>
    {#if ask}
      <div class="m-ask">
        <b>{ask.kind === 'videos' ? t('settings.storage.askVideos', { n: ask.count, size: fmtMB(ask.bytes), scope: t(ask.v === 'fav' ? 'settings.storage.favouritesScope' : 'settings.storage.allScope') }) : t('settings.storage.askCanvases', { size: fmtMB(ask.bytes) })}</b>
        <small>{free ? t('settings.storage.free', { size: fmtMB(free) }) : ''}{free && ask.bytes > free * 0.8 ? t('settings.storage.mostFree') : ''} {offline.wifiOnly ? t('settings.storage.downloadWifi') : t('settings.storage.downloadMobile')}</small>
        <div class="m-acts"><MButton onclick={() => (ask = null)}>{t('common.cancel')}</MButton><MButton variant="dk" onclick={confirm}>{t('settings.storage.turnOn')}</MButton></div>
      </div>
    {/if}
    {#if offline.busy}<MHint>{t('settings.storage.downloading', { name: offline.busy })}</MHint>{/if}

    <MBox class="lcd">
      <h3>{t('settings.storage.onPhone')}<span class="m-sp"></span><span class="m-lbl">{fmtMB(total)}</span></h3>
      <div class="m-stack">{#each parts as p (p[0])}<i style:width="{Math.max(2, total ? p[1] / total * 100 : 0)}%" style:background={p[2]}></i>{/each}</div>
      <div class="m-keys3">{#each parts as p (p[0])}<i style:background={p[2]}></i><span><b>{p[0]}</b><em style="font-style:normal">{fmtMB(p[1])} · {p[3]}</em></span>{/each}</div>
      {#if use?.quota}<span class="m-lbl">{t('settings.storage.browser', { used: fmtMB(use.usage), quota: fmtMB(use.quota), kept: offline.persisted ? t('settings.storage.persisted') : '' })}</span>{/if}
    </MBox>

    {#if m}
      <div class="m-row">
        <MDisclosure summary={t('settings.storage.savedSummary', { n: offline.saved.length + offline.canvases.length })}>
          <div class="m-olist">
            {#each offline.saved as s (s.id)}
              {@const r = phone.byId.get(s.id)}
              <div class="m-oit">
                {#if r?.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span></span>{/if}
                <div><b>{r?.title || s.item.short_desc || 'No.' + s.id}</b><small>{t('settings.storage.savedItem', { size: fmtMB(s.size ?? 0), content: t(s.report ? 'settings.storage.report' : 'settings.storage.description'), transcript: s.transcript ? t('settings.storage.transcript') : '', video: s.item.files?.video ? t('settings.storage.video') : '', ago: fmtAgo(s.at) })}</small></div>
                <button type="button" onclick={() => removeItem(s.id).then(measure)}>{t('settings.storage.remove')}</button>
              </div>
            {/each}
            {#each offline.canvases as c (c.id)}
              <div class="m-oit">
                <span class="m-cvi">▦</span>
                <div><b>{c.name}</b><small>{t('settings.storage.savedCanvas', { size: fmtMB(c.size), n: c.images.length, ago: fmtAgo(c.at) })}</small></div>
                <button type="button" onclick={() => removeCanvas(c.id).then(measure)}>{t('settings.storage.remove')}</button>
              </div>
            {/each}
            {#if !offline.saved.length && !offline.canvases.length}
              <div class="m-empty" style="padding:12px">{t('settings.storage.noSaves')}</div>
            {/if}
          </div>
        </MDisclosure>
        <MInfo title={t('settings.storage.saved')}><p>{t('settings.storage.savesHelp')}</p></MInfo>
      </div>
    {/if}
    <div class="m-row">
      <MDisclosure summary={t('settings.storage.openedSummary', { n: Math.min(kept.length, 30) })}>
        <div class="m-olist">
          {#each kept.slice(0, 30) as s (s.id)}
            {@const r = phone.byId.get(s.id)}
            <div class="m-oit">
              {#if r?.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span></span>{/if}
              <div><b>{r?.title || s.item.short_desc || 'No.' + s.id}</b><small>{t('settings.storage.openedItem', { content: t(s.report ? 'settings.storage.report' : 'settings.storage.description'), transcript: s.transcript ? t('settings.storage.transcript') : '', ago: fmtAgo(s.at), favourite: r?.fav ? t('settings.storage.favourite') : '' })}</small></div>
              <button type="button" onclick={() => forget(s.id)}>{t('settings.storage.remove')}</button>
            </div>
          {:else}
            <div class="m-empty" style="padding:12px">{t('settings.storage.noOpened')}</div>
          {/each}
        </div>
      </MDisclosure>
      <MInfo title={t('settings.storage.opened')}><p>{t('settings.storage.openedHelp')}</p></MInfo>
    </div>

    <MRow desc={`${phone.capMB} ${t('common.size.mb')}`}>{#snippet title()}{t('settings.storage.limit')}<MInfo title={t('settings.storage.limit')}><p>{t('settings.storage.limitHelp')}</p></MInfo>{/snippet}</MRow>
    <input type="range" class="m-range" min="50" max="1000" step="50" value={phone.capMB} oninput={e => setCap(+(e.currentTarget as HTMLInputElement).value)} aria-label={t('settings.storage.limit')} />

    <MRow desc={t('settings.storage.retained')}>{#snippet title()}{t('settings.storage.clearCopy')}<MInfo title={t('settings.storage.clearCopy')}><p>{t('settings.storage.clearHelp')}</p><p>{t('settings.storage.removalHelp')}</p></MInfo>{/snippet}<MTextButton tone="danger" onclick={clearAll} disabled={clearNote === 'Clearing…'}>{confirmClear ? t('settings.storage.confirmClear') : t('settings.storage.clear')}</MTextButton></MRow>
    {#if clearNote}<MHint>{clearNote === 'Clearing…' ? t('settings.storage.clearing') : clearNote}</MHint>{/if}
  </MGroup>

  <MGroup title={t('settings.group.look')} line={lookLine(styleName, dark, phoneWords)} infoTitle={t('settings.look.appearance')}>
    {#snippet info()}<p>{t('settings.look.nightHelp')}</p><p>{t('settings.look.cardHelp')}</p>{/snippet}
    <MRow title={t('settings.language.title')} desc={languageDetail}>
      <MSeg label={t('settings.language.title')} size="sm" options={[["auto", t('settings.language.auto')], ["en", "EN"], ["fr", "FR"], ["zh-Hant", "繁中"]]} value={languageChoice} disabled={changingLanguage} onchange={changeLanguage} />
    </MRow>
    {#if languageError}<MHint tone="error" role="alert">{languageError}</MHint>{/if}
    <MRow title={t('settings.look.night')}><MToggle label={t('settings.look.night')} on={dark} onchange={() => { toggleTheme(); dark = isDark() }} /></MRow>
    <MRow title={t('settings.look.cardStyle')}><MSeg label={t('settings.look.cardStyle')} size="sm" options={cardStyles()} value={phone.cardStyle} onchange={v => setCardStyle(v as CardStyle)} /></MRow>
    <MRow title={t('settings.look.motion')}><MToggle label={t('settings.look.motion')} on={!phone.motionOff} onchange={on => setMotionOff(!on)} /></MRow>
  </MGroup>

  <MGroup title={t('settings.group.about')} line={aboutLine({ desktop, version: app?.version ?? '' }, phoneWords)} infoTitle={t('settings.about.desktop')}>
    {#snippet info()}
      <p>{t('settings.about.help')}</p>
      <p>{t('settings.about.pcHelp')}</p>
      <p>{t('settings.about.accountsHelp')}</p>
      <p>{t('settings.about.pairHelp')}</p>
    {/snippet}
    {#if desktop}
      <MRow id="m-desktop" title={t('settings.about.windows')} desc={t('settings.about.features')}><MButton as="a" variant={lead ? 'pri' : 'default'} size="sm" href={DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">{t('settings.about.getApp')}</MButton></MRow>
    {/if}
    {#if isApp}
      <div id="m-app-info" class="m-stack-rows">
        {#if app}
          <MRow title={t('settings.about.version')} desc={app.version} />
          <MRow title={t('settings.about.build')} desc={app.build} />
        {:else if infoError}
          <MHint tone="error" role="alert">{infoError}</MHint>
          <MButton size="sm" onclick={readAppInfo}>{t('common.retry')}</MButton>
        {:else}
          <MHint role="status">{t('settings.about.loading')}</MHint>
        {/if}
      </div>
    {:else}
      <MHint>{t('settings.about.previewHelp')}</MHint>
    {/if}
    <h4 class="m-group-sub">{t('settings.about.privacy')}</h4>
    <MHint>{t('settings.about.documentsHelp')}</MHint>
    <LegalDocuments policy={lang() === 'fr' ? privacyFrench : lang() === 'zh-Hant' ? privacyTraditionalChinese : undefined}
      policyLang={lang() === 'fr' ? 'fr' : lang() === 'zh-Hant' ? 'zh-Hant-TW' : 'en'} />
  </MGroup>
</div>
