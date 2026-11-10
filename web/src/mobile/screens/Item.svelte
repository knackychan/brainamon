<script lang="ts">
  import { captureError } from '../capture-words.ts'
  // The approved item screen (phone-dock-shell plan 07); the locked card/finger engine stays unchanged.
  import { onDestroy, tick, untrack } from 'svelte'
  import { mdHTML } from '../../lib/md'
  import { cardMarkup, displayDate, themeCard, tintOf, variantOf } from '../cards'
  import { sourceName, typeName } from '../card-words.ts'
  import { t } from '../../lib/i18n/index.ts'
  import { fmtMegabytes } from '../../lib/i18n/format.ts'
  import type { FullItem, Row } from '../source/types'
  import { items as idb, type StoredItem } from '../store'
  import { deleteItem, openLibrarySearch, parseRoute, phone, replaceRow, solo, source, toggleFav } from '../state.svelte'
  import { back, go } from '../shell.svelte'
  import { esc, srcLabel } from '../../lib/cards/card'
  import { fingerTilt } from '../finger'
  import Processing from '../Processing.svelte'
  import ToolsRing from '../ToolsRing.svelte'
  import { onToolsDone } from '../tools-run.svelte'
  import { NO_CONTENT } from '../ai/describe'
  import { removeItem, saveItem, videoUrl } from '../offline.svelte'
  import ShellIcon from '../ShellIcon.svelte'
  import MButton from '../ui/MButton.svelte'
  import MDialog from '../ui/MDialog.svelte'
  import MInfo from '../ui/MInfo.svelte'
  import MKey from '../ui/MKey.svelte'
  import MPicker from '../ui/MPicker.svelte'
  import MSeg from '../ui/MSeg.svelte'
  import MTextButton from '../ui/MTextButton.svelte'

  let { id, scroller }: { id: number; scroller: HTMLElement | undefined } = $props()
  const row = $derived(phone.byId.get(id))
  const onMirror = source.kind === 'mirror'
  const twoScopes = onMirror && !solo
  let full = $state<FullItem | null>(null)
  const aiDescription = $derived(full?.ai_desc?.trim() === NO_CONTENT ? '' : full?.ai_desc || '')
  let report = $state(''), transcript = $state(''), err = $state('')
  let tab = $state<'rep' | 'tr' | 'info'>('rep')
  let related = $state<Row[]>([])
  let onPhone = $state(false), saved = $state(false), saving = $state(''), saveFrac = $state(0), keeping = $state(false)
  // an Error's own text is shown as the detail of a sentence in the page language (English: the detail alone, as today);
  // a throw with no message shows nothing, as before
  const errorText = (e: unknown): string => { const detail = (e as Error | null)?.message; return detail ? t('item.error.detail', { detail: captureError(e) }) : '' }
  let editing = $state(false), tags = $state(''), savingTags = $state(false)
  let collection = $state(''), moving = $state(false), processing = $state(false), askDel = $state(false)
  let toolsKey: HTMLButtonElement | HTMLAnchorElement | HTMLLabelElement | undefined = $state()
  let stage: HTMLDivElement | undefined = $state()
  let openLink: HTMLAnchorElement | undefined = $state()
  let tagsField: HTMLInputElement | undefined = $state()
  let hand: HandCard | null = null
  let live = true, loadSeq = 0, firstLoad = true
  // left for another section: a later Library return keeps its saved scroll (decision 12)
  onDestroy(() => { live = false; loadSeq++; if (phone.route.tab !== 'lib') phone.lastItem = null })
  $effect(() => { collection = row?.cat ?? '' })
  // a Tools run that ends, or an Undo, refreshes this screen; the registration goes with the screen (tools-run.svelte.ts)
  $effect(() => onToolsDone(() => load()))
  const creator = $derived(row?.creator.trim() && row.creator.trim().toLowerCase() !== 'unknown' ? row.creator : '')
  const madeHere = $derived(id < 0)
  const kept = $derived(onMirror ? saved : onPhone)
  const phoneName = $derived(madeHere ? (solo ? t('item.phone.saved') : t('item.phone.waiting')) : saving || t('item.phone.keep'))
  const infoTitle = $derived(madeHere ? phoneName : t('item.phone.title'))
  const infoText = $derived(madeHere
    ? solo ? t('item.phone.infoSolo') : t('item.phone.infoPaired')
    : onMirror ? t('item.phone.infoMirror') : t('item.phone.infoDirect'))
  const tabs = $derived<[string, string][]>([['rep', report ? t('item.tab.report') : t('item.tab.description')], ...(transcript ? [['tr', t('item.tab.transcript')] as [string, string]] : []), ['info', t('item.tab.info')]])
  $effect(() => { if (tab === 'tr' && !transcript) tab = 'rep' })

  // Video playback is the existing block and the existing source/cache path.
  const vbytes = $derived(source.videoSize?.(id) ?? 0)
  let vsrc = $state(''), vprog = $state(''), vbusy = $state(false)
  $effect(() => () => { if (vsrc) URL.revokeObjectURL(vsrc) })
  const pct = (g: number, total: number) => (total ? t('item.progress.percent', { n: Math.round(g / total * 100) }) : fmtMegabytes(g))
  // vbusy, not the words of vprog, tells that a download is in flight: Play stays disabled for it in every language and
  // is enabled again after a failure, whose detail then shows in vprog
  async function play() {
    vbusy = true; vprog = t('item.video.downloading')
    try { vsrc = await videoUrl(id, (g, total) => { vprog = t('item.video.downloadingProgress', { progress: pct(g, total) }) }); vprog = '' } catch (e) { vprog = errorText(e) } finally { vbusy = false }
  }
  // Saving shows the progress words and ring; removing/forgetting keeps the name and face, disabled.
  async function toggleKeep() {
    if (keeping) return
    err = ''; keeping = true; saveFrac = 0; loadSeq++
    if (!kept) saving = t('item.phone.saving')
    try {
      if (onMirror) {
        if (saved) { await removeItem(id); saved = false }
        else {
          await saveItem(id, true, (g, total) => { saving = t('item.phone.savingVideo', { progress: pct(g, total) }); saveFrac = total ? Math.max(0, Math.min(1, g / total)) : 0 })
          saved = true; onPhone = true
        }
      } else if (onPhone) await forget()
      else await load(false, true)
    } catch (e) { err = errorText(e) }
    finally { saving = ''; keeping = false }
  }

  // The same card as the Library, still rasterised at 3x and tilted by HandCard/fingerTilt.
  $effect(() => {
    if (!stage || !row) return
    const html = cardMarkup(row, variantOf(row), 0)
    stage.innerHTML = html
    const slot = stage.querySelector<HTMLElement>('.slot')
    if (slot) {
      slot.style.setProperty('--t', TYPE[row.cat] || '#9cc4e2')
      themeCard(slot, row)
      hand = new HandCard(slot, { idle: !phone.motionOff, onTap: () => {
        if (row.url) openLink?.click()
        else err = t('item.error.noUrl')
      } })
    }
    return () => { if (hand) { ALL.delete(hand); ACTIVE.delete(hand); hand = null } }
  })
  $effect(() => { if (stage) return fingerTilt(stage, () => hand) })
  // The idle float rewrites the card's light layers (blend modes, masks, the blurred shadow) every
  // frame on a card laid out at 3x; while the page scrolls that competes with the scroll for each
  // frame. Hold the float during a scroll and resume it once the page has been still for 200 ms.
  $effect(() => {
    const el = scroller
    if (!el) return
    let timer = 0
    const onScroll = () => {
      if (hand && hand.idle) hand.idle = false
      clearTimeout(timer)
      timer = window.setTimeout(() => { if (hand && !phone.motionOff) { hand.idle = true; wake(hand) } }, 200)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => { clearTimeout(timer); el.removeEventListener('scroll', onScroll) }
  })

  async function load(resetScroll = false, keep = false) {
    if (keeping && !keep) return
    const seq = ++loadSeq
    if (resetScroll) scroller?.scrollTo({ top: 0 })
    try {
      const stored = await idb.get(id)
      if (!live || seq !== loadSeq) return
      if (stored) { full = stored.item; report = stored.report ?? ''; transcript = stored.transcript ?? ''; onPhone = true; saved = !!stored.saved }
      try {
        const it = await source.item(id)
        const [rep, tr] = await Promise.all([
          it.files.report ? source.itemText(id, 'report').catch(() => '') : Promise.resolve(''),
          it.files.transcript ? source.itemText(id, 'transcript').catch(() => it.transcript || '') : Promise.resolve(it.transcript || ''),
        ])
        if (!live || seq !== loadSeq) return
        const latest = await idb.get(id)
        if (!live || seq !== loadSeq) return
        const s: StoredItem = { ...latest, id, at: Date.now(), item: it, report: rep, transcript: tr }
        const keepCopy = onMirror || resetScroll || keep || onPhone
        if (keepCopy) await idb.put(s)
        if (!live || seq !== loadSeq) return
        full = it; report = rep; transcript = tr; onPhone = keepCopy || !!latest; saved = !!s.saved
      } catch (e) {
        if (live && seq === loadSeq && !full) err = t('item.error.unreachable', { detail: captureError(e) })
      }
      source.related(id).then(r => { if (live && seq === loadSeq) related = r }).catch(() => { /* needs the PC */ })
    } catch (e) { if (live && seq === loadSeq) err = errorText(e) }
  }
  // Reload after jobs/row changes. Keep/Forget itself reloads nothing; a row change during it reloads once
  // it ends. load() does not recache a direct-PC copy after Forget.
  let seenRow: Row | undefined, missed = false
  $effect(() => {
    const current = row, busy = keeping
    if (current) untrack(() => {
      phone.lastItem = id
      const changed = current !== seenRow
      seenRow = current
      if (busy) { missed ||= changed; return }
      if (changed || missed) { missed = false; void load(firstLoad); firstLoad = false }
    })
  })
  const body = $derived.by(() => {
    if (!full) return ''
    if (tab === 'rep') return report ? mdHTML(report) : mdHTML(aiDescription || full.description || '') || (source.describe ? `<p>${esc(t('item.empty.withTools'))}</p>` : `<p>${esc(t('item.empty.pcDescribes'))}</p>`)
    if (tab === 'tr') return `<pre>${transcript.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]!)}</pre>`
    return ''
  })
  async function editTags() { if (!row) return; tags = row.tags; editing = true; tab = 'info'; await tick(); tagsField?.focus() }
  async function saveTags() {
    if (savingTags) return
    savingTags = true; err = ''
    try { replaceRow(await source.edit(id, { tags })); editing = false } catch (e) { err = errorText(e) }
    finally { savingTags = false }
  }
  async function moveCollection(category: string) {
    moving = true; err = ''
    try { replaceRow(await source.edit(id, { category })) }
    catch (e) { collection = row?.cat ?? ''; err = errorText(e) }
    finally { moving = false }
  }
  async function forget() { await idb.del(id); onPhone = false }
  // After a delete (decision 11): back to the Library entry behind this item, so no duplicate Library entry
  // remains; else (Related, a cited item, a deep link, no Navigation API) the Library in this item's place.
  function leave() {
    const nav = (globalThis as { navigation?: { currentEntry?: { index: number } | null; entries?: () => { url: string | null }[] } }).navigation
    const now = nav?.currentEntry?.index ?? -1
    const url = now > 0 ? nav?.entries?.()[now - 1]?.url ?? '' : ''
    const prev = url ? parseRoute(new URL(url).hash) : null
    if (prev?.tab === 'lib' && !prev.item) back()
    else go('#/lib', true)
  }
  async function del(pc: boolean) {
    askDel = false; err = ''; loadSeq++
    try { await deleteItem(id, pc); leave() } catch (e) { err = errorText(e) }
  }
  function onChip(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest<HTMLElement>('.cite[data-cid]')
    if (b) location.hash = `#/item/${b.dataset.cid}`
  }
</script>

<div class="m-it-felt" class:m-it-missing={!row}>
  <div class="m-it-over"><MKey aria-label={t('common.back')} title={t('common.back')} onclick={() => history.back()}><ShellIcon name="back" /></MKey><span class="m-ws">{t('shell.route.item')}</span></div>
  {#if row}
    <MKey class="m-it-delete" tone="danger" aria-label={t('common.delete')} title={t('common.delete')} onclick={() => askDel = true}><ShellIcon name="bin" /></MKey>
    <div class="m-it-stage" bind:this={stage}></div>
    {#if row.url}<MKey as="a" tone="add" class="m-it-open-corner" href={row.url} target="_blank" rel="noopener noreferrer" aria-label={t('item.openIn', { source: sourceName(srcLabel(row.src)) })}><ShellIcon name="open" /></MKey>{/if}
  {/if}
</div>
{#if !row}
  <div class="m-empty">{t('item.missing', { id })}</div>
{:else}
  <div class="m-sheet m-it-sheet">
    <div class="m-it-head">
      <div class="m-it-kline">
        <div class="m-it-kicker">
          <MPicker label={t('item.collection')} class="m-it-collection" options={phone.cats.map(c => [c.name, c.name])} bind:value={collection} disabled={moving} onchange={moveCollection}>
            <span class="m-it-catpart"><i class="m-it-cdot" style:background={TYPE[collection] || 'var(--wg-dim)'}></i><span class="m-it-catname">{collection}</span><ShellIcon name="down" /></span>
          </MPicker>
          {#if row.type}<span class="m-it-format">· {typeName(row.type)}</span>{/if}
        </div>
        <div class="m-it-phone">
          {#snippet phoneFace()}
            <span class={['m-phone-face', madeHere ? (solo ? 'flat' : 'wait') : saving ? 'busy' : kept ? 'on' : 'off']} style:--m-save={`${saveFrac * 100}%`}>
              <ShellIcon name="phone" />
              {#if madeHere || kept}<span class="m-phone-badge">{#if madeHere && !solo}<i></i>{:else}<ShellIcon name="check" />{/if}</span>{/if}
            </span>
          {/snippet}
          {#if madeHere}<span class="m-phone-state" role="img" aria-label={phoneName}>{@render phoneFace()}</span>
          {:else}<MKey class="m-phone-key" aria-label={phoneName} title={phoneName} aria-pressed={kept} disabled={keeping} onclick={toggleKeep}>{@render phoneFace()}</MKey>{/if}
          <MInfo title={infoTitle}><p>{infoText}</p></MInfo>
        </div>
      </div>
      <h3 class="m-it-tt">{row.title || (row.id > 0 ? 'No.' + row.id : row.url)}</h3>
      {#if creator}<div class="m-it-by">{t('item.by')} <button type="button" onclick={() => openLibrarySearch(row.creator)}><span>{creator}</span></button></div>{/if}
    </div>
    <div class="m-it-keyrow">
      <div class="m-lib-keys m-it-keys">
        <MKey class="m-it-fav" tone={row.fav ? 'dark' : 'plain'} aria-label={t('item.favourite')} title={t('item.favourite')} aria-pressed={row.fav} onclick={() => toggleFav(row.id)}><ShellIcon name="star" /></MKey>
        <MKey aria-label={t('item.editTags')} title={t('item.editTags')} onclick={editTags}><ShellIcon name="tag" /></MKey>
        <MKey bind:ref={toolsKey} class="m-it-tools" tone={processing ? 'dark' : 'plain'} aria-label={t('common.tools')} title={t('common.tools')} aria-haspopup="dialog" aria-describedby="m-tools-status" aria-expanded={processing} onclick={() => processing = !processing}><ShellIcon name="tools" /><ToolsRing open={processing} /></MKey><ToolsRing open={processing} status />
      </div>
      <span class="m-sp"></span>
      {#if row.url}<MButton as="a" variant="pri" class="m-it-open" bind:ref={openLink} href={row.url} target="_blank" rel="noopener noreferrer"><ShellIcon name="open" />{t('item.openIn', { source: sourceName(srcLabel(row.src)) })}</MButton>{/if}
    </div>
    {#if processing}<Processing rows={[row]} item anchor={toolsKey} close={() => processing = false} />{/if}
    {#if vsrc}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video class="m-video" src={vsrc} controls playsinline autoplay></video>
    {:else if onMirror && vbytes}
      <div class="m-vid"><div><b>{t('item.video.fromPc')}</b><small>{vprog ? t('item.video.progressLine', { progress: vprog }) : t(saved ? 'item.video.sizeSaved' : 'item.video.sizeDrive', { size: fmtMegabytes(vbytes) })}</small></div><MButton variant="dk" size="sm" onclick={play} disabled={vbusy}>{t('item.video.play')}</MButton></div>
    {:else if full?.files.video}
      <div class="m-vid"><div><b>{t('item.video.onPc')}</b><small>{onMirror ? t('item.video.notInDrive') : t('item.video.directPc')}</small></div><span class="m-badge mute">{t('shell.where.pc')}</span></div>
    {/if}
    <MSeg look="tabs" label={t('item.tabs')} options={tabs} value={tab} onchange={v => tab = v as typeof tab} />
    {#if err}<div class="m-err" role="alert" style="margin:0">{err}</div>{/if}
    {#if tab === 'info'}
      <dl class="m-it-info">
        {#if row.id > 0}<dt>No.</dt><dd>{row.id}</dd>{/if}
        <dt>{t('item.info.saved')}</dt><dd>{displayDate(row.created)}</dd>
        {#if row.url}<dt>{t('item.info.link')}</dt><dd><a href={row.url} target="_blank" rel="noopener noreferrer">{row.url}</a></dd>{/if}
        <dt>{t('item.info.tags')}</dt><dd class="m-it-tags">
          {#if editing}
            <label class="m-fld"><span class="m-pr">#</span><input bind:this={tagsField} bind:value={tags} aria-label={t('item.info.tags')} placeholder={t('item.tags.placeholder')} /></label>
            <div class="m-acts" style="margin-top:8px"><MButton disabled={savingTags} onclick={() => (editing = false)}>{t('common.cancel')}</MButton><MButton variant="dk" disabled={savingTags} onclick={saveTags}>{t('common.save')}</MButton></div>
          {:else}<span>{row.tags || t('item.info.none')}</span><MTextButton onclick={editTags}>{t('common.edit')}</MTextButton>{/if}
        </dd>
        {#if full?.notes}<dt>{t('item.info.notes')}</dt><dd class="m-it-notes">{full.notes}</dd>{/if}
        {#if full}<dt>{t('item.info.ai')}</dt><dd>{[aiDescription ? t('item.info.aiDescribed') : t('item.info.aiNone'), full.analysis_done && t('item.info.analysed'), full.files.frames && t('item.info.frames', { n: full.files.frames })].filter(Boolean).join(' · ')}</dd>{/if}
      </dl>
    {:else}
      <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
      <div class="m-rep" onclick={onChip}>{@html body}</div>
    {/if}
    {#if related.length}
      <span class="m-lbl">{t('item.related')}</span>
      <div class="m-rel">
        {#each related as r (r.id)}
          <button type="button" onclick={() => (location.hash = `#/item/${r.id}`)}>
            {#if r.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<div class="m-tint" style:background={tintOf(r)}></div>{/if}
            <span>{r.title || 'No.' + r.id}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>
  <MDialog bind:open={askDel} title={t('item.delete.title', { title: row.title || 'No.' + row.id })}>
    <p>{twoScopes ? t('item.delete.bodyTwo') : t('item.delete.bodyOne')}</p>
    {#snippet actions()}
      <MButton onclick={() => askDel = false}>{t('common.cancel')}</MButton>
      {#if twoScopes}<MButton onclick={() => del(false)}>{t('item.delete.thisPhone')}</MButton><MButton variant="danger" onclick={() => del(true)}>{t('item.delete.phoneAndPc')}</MButton>
      {:else}<MButton variant="danger" onclick={() => del(true)}>{t('common.delete')}</MButton>{/if}
    {/snippet}
  </MDialog>
{/if}
