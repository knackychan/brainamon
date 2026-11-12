<script lang="ts">
  import { onMount } from 'svelte'
  import { languageWorkChanged, registerLanguageCheck } from '../language-switch.ts'
  import { t } from '../../lib/i18n/index.ts'
  import { phoneWords, lampLabel } from '../settings-words'
  import { fmtNum } from '../../lib/i18n/format.ts'
  import T from '../../lib/i18n/T.svelte'
  import { devSolo, driveStatus, fmtAgo, fmtMB, isDark, mirrorSource, pairFrom, phone, phoneStatus, refresh, cardStyles, solo, source, useWithoutPc } from '../state.svelte'
  import { vault as vaultRun } from '../vault/auto.svelte'
  import { isApp } from '../native'
  import { offline } from '../offline.svelte'
  import PageKeys from '../PageKeys.svelte'
  import StatusCard from '../StatusCard.svelte'
  import { aboutLine, aiLine, lookLine, phoneLine, settingsTones, storageLine, vaultLine } from '../settings-lines'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MGroup from '../ui/MGroup.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'
  import MStatus from '../ui/MStatus.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MCard from '../ui/MCard.svelte'
  import { settings, measureSettings, storageTotal, readAppInfo, vaultLamp } from '../settings-facts.svelte'
  import { vaultName } from '../obsidian'
  import { rowKind } from '../settings-steps'
  import { SYNC_IDS } from '../settings-lines'
  import { syncSummary, syncLanes } from '../lanes'
  import { backup } from '../backup.svelte'
  const lanes = $derived(syncLanes())
  const m = mirrorSource
  const st = $derived(phoneStatus())
  const canSolo = isApp || devSolo
  const health = $derived(settings.health)
  let pasted = $state('')
  const ai = $derived((phone.synced, m?.ai() ?? null))
  const aiProvider = $derived(ai?.providers.find(p => p.id === ai.provider)?.label ?? ai?.provider ?? '')
  let dark = $state(isDark())
  const styleName = $derived(cardStyles().find(([v]) => v === phone.cardStyle)?.[1] ?? t('item.cardStyle.auto'))
  const total = $derived(storageTotal())
  const syncing = $derived(isApp && !solo && !!source.syncVault)
  const vaultTitle = $derived(vaultName(source.obsidianVault?.() ?? '', vaultRun.opts.name))
  const lamp = $derived(vaultLamp())
  const tones = $derived(settingsTones(st, { running: lanes.some(l => l.tag === 'running' || l.tag === 'stopping'), driveOk: driveStatus().ok, ai: !!ai }))
  $effect(() => { void phone.synced; if (!phone.refreshing) void measureSettings() })
  onMount(() => { if (isApp) void readAppInfo(); return registerLanguageCheck(() => pasted ? 'settings.language.unsavedPairing' : null) })

</script>

<!-- the pairing-link paste field, under a disclosure in the box that pairs -->
{#snippet pasteLink()}
  <MDisclosure summary={t('settings.pair.paste')}>
    <MRow wrap title={t('settings.pair.link')} desc={t('settings.pair.copyHint')}><MButton size="sm" onclick={() => pairFrom(pasted)} disabled={!pasted.includes('#pair=')}>{t('settings.pair.pair')}</MButton></MRow>
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
        <MButton shape="pill" onclick={() => refresh().then(measureSettings)} disabled={phone.refreshing}>{phone.refreshing ? t('settings.sync.syncing') : t('settings.keys.refresh')}</MButton>
      </MStatus>
      {#if phone.note}<MHint>{phone.note}</MHint>{/if}
    </MBox>
  {/if}


{#if m}<MCard>
<MGroup title={t('backup.group.title')} href="#/backup" glyph="cloud" line={phoneLine(solo, m.pair.f, phoneWords)} kind={rowKind(st && !SYNC_IDS.includes(st.id) ? st : null, tones.phone, backup.error)} />
<MGroup title={t('shell.sync.title')} href="#/more/sync" glyph="sync" line={syncSummary()} kind={rowKind(st && SYNC_IDS.includes(st.id) ? st : null, backup.task ? 'todo' : tones.sync, backup.error)} />
</MCard>{/if}
  {#if !m && canSolo}<MCard>
    <MGroup title={t('settings.group.solo')} line={devSolo ? 'Development Drive' : t('settings.pair.soloOnly')}>
      {#snippet action()}<MButton size="sm" onclick={() => useWithoutPc()}>{t('settings.sync.start')}</MButton>{/snippet}
    </MGroup>
    <MGroup title={t('recovery.action.recoverEllipsis')} href="#/recover" line={t('recovery.action.restoreDrive')} />
  </MCard>{/if}


{#if m}<MCard title={t('settings.section.assistant')}>
<MGroup title={t('settings.group.ai')} href="#/more/wiskit" glyph="cat" line={aiLine(aiProvider, solo, phoneWords)} />
<MGroup title="Obsidian" href="#/more/obsidian" glyph="gem" line={vaultLine({ name: vaultTitle, syncing, lamp: lampLabel(lamp) }, phoneWords)} />
</MCard>{/if}
<MCard title={t('settings.section.app')}>
{#if !m}<MGroup title="Obsidian" href="#/more/obsidian" glyph="gem" line={vaultLine({ name: vaultTitle, syncing, lamp: lampLabel(lamp) }, phoneWords)} />{/if}
<MGroup title={t('settings.group.storage')} href="#/more/storage" glyph="disk" line={storageLine(fmtMB(total), offline.keepCanvases, offline.keepVideos, phoneWords)} />
<MGroup title={t('settings.group.look')} href="#/more/look" glyph="look" line={lookLine(styleName, dark, phoneWords)} />
<MGroup title={t('settings.group.about')} href="#/more/about" glyph="info" line={aboutLine({ desktop: !m || solo, version: settings.app?.version ?? '' }, phoneWords)} />
</MCard></div>
