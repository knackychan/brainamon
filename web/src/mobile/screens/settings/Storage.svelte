<script lang="ts">
  import { beginLanguageWork } from '../../language-switch.ts'
  import { t } from '../../../lib/i18n/index.ts'
  import { phoneWords } from '../../settings-words'
  import { fmtNum } from '../../../lib/i18n/format.ts'
  import { items as idb, wipe } from '../../store'
  import { fmtAgo, fmtMB, mirrorSource, phone, refresh, setCap, source } from '../../state.svelte'
  import { keepCanvasesNeed, keepVideosNeed, offline, removeCanvas, removeItem, setKeep, setKeepVideos, type KeepVideos } from '../../offline.svelte'
  import PageKeys from '../../PageKeys.svelte'
  import { storageLine } from '../../settings-lines'
  import MBox from '../../ui/MBox.svelte'
  import MButton from '../../ui/MButton.svelte'
  import MHint from '../../ui/MHint.svelte'
  import MInfo from '../../ui/MInfo.svelte'
  import MRow from '../../ui/MRow.svelte'
  import MToggle from '../../ui/MToggle.svelte'
  import MSeg from '../../ui/MSeg.svelte'
  import MDisclosure from '../../ui/MDisclosure.svelte'
  import MTextButton from '../../ui/MTextButton.svelte'
  import MCard from '../../ui/MCard.svelte'
  import { settings, measureSettings, storageTotal, savedBytes } from '../../settings-facts.svelte'
  let ask = $state<{ kind: 'videos'; v: KeepVideos; count: number; bytes: number } | { kind: 'canvases'; bytes: number } | null>(null)
  const m = mirrorSource
  const measure = measureSettings
  const total = $derived(storageTotal())
  const use = $derived(settings.use)
  const kept = $derived(settings.kept)
  const free = $derived(settings.free)
  const parts = $derived(use ? [[t('settings.storage.light'), use.light, 'var(--m-teal)', t('settings.storage.always')], [t('settings.storage.thumbnails'), use.thumbBytes, 'var(--lcd-dim)', t('settings.storage.cap', { cap: phone.capMB })], [t('settings.storage.opened'), use.fullBytes, 'var(--accent)', t('settings.storage.kept', { n: use.fullItems })], [t('settings.storage.saved'), savedBytes(), 'var(--m-warn)', t('settings.storage.savedCount', { n: offline.saved.length + offline.canvases.length })]] as [string, number, string, string][] : [])
  async function forget(id: number) {
    const done = beginLanguageWork()
    try { await idb.delRequired(id); await measure() } catch { clearNote = t('settings.storage.failed') } finally { done() }
  }
  // Clear asks twice (Fred 2026-11-07): the stores and the mirror's in-memory copy both go, then the list loads again
  // from the source
  let clearNote = $state(''), confirmClear = $state(false), clearing = $state(false)
  async function clearAll() {
    if (clearing) return
    if (!confirmClear) { confirmClear = true; return }
    const done = beginLanguageWork()
    confirmClear = false
    clearing = true; clearNote = ''
    try {
      await wipe()
      m?.forgetCopy()
      phone.rows = []
      navigator.serviceWorker?.controller?.postMessage({ type: 'clear' })
      const why = await refresh()
      clearNote = why ? t('settings.storage.clearedWaiting', { detail: why }) : t('settings.storage.cleared', { n: fmtNum(phone.rows.length, 'en') })
      await measure()
    } catch { clearNote = t('settings.storage.failed') } finally { clearing = false; done() }
  }

  async function removeSaved(action: () => Promise<void>) {
    try { await action(); await measure() }
    catch { clearNote = t('settings.storage.failed') }
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

  $effect(() => { void phone.synced; if (!phone.refreshing) void measure() })
</script>

<PageKeys />
<div class="m-pad m-calm m-page"><h1 class="m-page-title">{t('settings.group.storage')}</h1><p class="m-page-sub">{storageLine(fmtMB(total), offline.keepCanvases, offline.keepVideos, phoneWords)}</p>
    <MBox class="lcd">
      <h3>{t('settings.storage.onPhone')}<span class="m-sp"></span><span class="m-lbl">{fmtMB(total)}</span></h3>
      <div class="m-stack">{#each parts as p (p[0])}<i style:width="{Math.max(2, total ? p[1] / total * 100 : 0)}%" style:background={p[2]}></i>{/each}</div>
      <div class="m-keys3">{#each parts as p (p[0])}<i style:background={p[2]}></i><span><b>{p[0]}</b><em style="font-style:normal">{fmtMB(p[1])} · {p[3]}</em></span>{/each}</div>
      {#if use?.quota}<span class="m-lbl">{t('settings.storage.browser', { used: fmtMB(use.usage), quota: fmtMB(use.quota), kept: offline.persisted ? t('settings.storage.persisted') : '' })}</span>{/if}
    </MBox><MCard>

    {#if m}
      <div class="m-row">
        <MDisclosure summary={t('settings.storage.savedSummary', { n: offline.saved.length + offline.canvases.length })}>
          <div class="m-olist">
            {#each offline.saved as s (s.id)}
              {@const r = phone.byId.get(s.id)}
              <div class="m-oit">
                {#if r?.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<span></span>{/if}
                <div><b>{r?.title || s.item.short_desc || 'No.' + s.id}</b><small>{t('settings.storage.savedItem', { size: fmtMB(s.size ?? 0), content: t(s.report ? 'settings.storage.report' : 'settings.storage.description'), transcript: s.transcript ? t('settings.storage.transcript') : '', video: s.item.files?.video ? t('settings.storage.video') : '', ago: fmtAgo(s.at) })}</small></div>
                <button type="button" onclick={() => removeSaved(() => removeItem(s.id))}>{t('settings.storage.remove')}</button>
              </div>
            {/each}
            {#each offline.canvases as c (c.id)}
              <div class="m-oit">
                <span class="m-cvi">▦</span>
                <div><b>{c.name}</b><small>{t('settings.storage.savedCanvas', { size: fmtMB(c.size), n: c.images.length, ago: fmtAgo(c.at) })}</small></div>
                <button type="button" onclick={() => removeSaved(() => removeCanvas(c.id))}>{t('settings.storage.remove')}</button>
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

<MDisclosure foot summary={t('common.showMore')} less={t('common.showLess')}>    <MRow wrap desc={`${phone.capMB} ${t('common.size.mb')}`}>{#snippet title()}{t('settings.storage.limit')}<MInfo title={t('settings.storage.limit')}><p>{t('settings.storage.limitHelp')}</p></MInfo>{/snippet}</MRow>
    <input type="range" class="m-range" min="50" max="1000" step="50" value={phone.capMB} oninput={e => setCap(+(e.currentTarget as HTMLInputElement).value)} aria-label={t('settings.storage.limit')} />

    <MRow wrap desc={t('settings.storage.retained')}>{#snippet title()}{t('settings.storage.clearCopy')}<MInfo title={t('settings.storage.clearCopy')}><p>{t('settings.storage.clearHelp')}</p><p>{t('settings.storage.removalHelp')}</p></MInfo>{/snippet}<MTextButton tone="danger" onclick={clearAll} disabled={clearing}>{confirmClear ? t('settings.storage.confirmClear') : t('settings.storage.clear')}</MTextButton></MRow>

  </MDisclosure></MCard>
<div role="status">{#if clearing || clearNote}<MHint>{clearing ? t('settings.storage.clearing') : clearNote}</MHint>{/if}</div>
<MCard title={t('settings.storage.automatic')} infoTitle={t('settings.storage.offlineHelpTitle')}>{#snippet info()}<p>{t('settings.storage.favouritesHelp')}</p><p>{t('settings.storage.keepHelp')}</p>{/snippet}

    <MRow wrap title={t('settings.storage.favourites')}><MToggle label={t('settings.storage.keepFavourites')} on={true} disabled /></MRow>
    <MRow wrap title={t('settings.storage.canvases')} desc={m ? undefined : t('settings.storage.needsDrive')}><MToggle label={t('settings.storage.canvases')} on={offline.keepCanvases} disabled={!m} onchange={on => wantCanvases(on)} /></MRow>
    <MRow wrap title={t('settings.storage.videos')} desc={m ? undefined : t('settings.storage.needsDrive')}><MSeg label={t('settings.storage.videos')} size="sm" options={[['off', t('settings.storage.off')], ['fav', t('settings.storage.favs')], ['all', t('settings.storage.all')]]} value={offline.keepVideos} disabled={!m} onchange={v => wantVideos(v as KeepVideos)} /></MRow>
    {#if ask}
      <div class="m-ask">
        <b>{ask.kind === 'videos' ? t('settings.storage.askVideos', { n: ask.count, size: fmtMB(ask.bytes), scope: t(ask.v === 'fav' ? 'settings.storage.favouritesScope' : 'settings.storage.allScope') }) : t('settings.storage.askCanvases', { size: fmtMB(ask.bytes) })}</b>
        <small>{free ? t('settings.storage.free', { size: fmtMB(free) }) : ''}{free && ask.bytes > free * 0.8 ? t('settings.storage.mostFree') : ''} {offline.wifiOnly ? t('settings.storage.downloadWifi') : t('settings.storage.downloadMobile')}</small>
        <div class="m-acts"><MButton onclick={() => (ask = null)}>{t('common.cancel')}</MButton><MButton variant="dk" onclick={confirm}>{t('settings.storage.turnOn')}</MButton></div>
      </div>
    {/if}
    {#if offline.busy}<MHint>{t('settings.storage.downloading', { name: offline.busy })}</MHint>{/if}

</MCard></div>
