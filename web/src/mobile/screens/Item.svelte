<script lang="ts">
  // 02 Item: the Full card tilting under the finger (the locked engine's HandCard with touch-action
  // none), then the sheet: title, meta, Report / Transcript / Info, actions. The full item is read
  // from the phone's copy first (src/mobile/store.ts items) and refreshed from the source; what you
  // open stays on the phone (the pinned tier keeps favourites and the last 50 opened).
  import { onMount } from 'svelte'
  import { mdHTML } from '../../lib/md'
  import { cardMarkup, tintOf, variantOf } from '../cards'
  import { themeSlot } from '../../lib/cards/theme'
  import type { FullItem, Row } from '../source/types'
  import { items as idb, type StoredItem } from '../store'
  import { deleteItem, patchRows, phone, replaceRow, solo, source, toggleFav } from '../state.svelte'
  import { srcLabel } from '../../lib/cards/card'
  import { fingerTilt } from '../finger'
  import Processing from '../Processing.svelte'
  import { isSaved, removeItem, saveItem, videoUrl } from '../offline.svelte'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'

  let { id, scroller }: { id: number; scroller: HTMLElement | undefined } = $props()
  const row = $derived(phone.byId.get(id))
  let full = $state<FullItem | null>(null)
  let report = $state(''), transcript = $state('')
  let tab = $state<'rep' | 'tr' | 'info'>('rep')
  let related = $state<Row[]>([])
  let err = $state('')
  let onPhone = $state(false)
  let editing = $state(false), tags = $state('')
  let stage: HTMLDivElement | undefined = $state()
  let openLink: HTMLAnchorElement | undefined = $state()
  let hand: HandCard | null = null
  // the mirror: play the PC's downloaded video, Save for offline
  const onMirror = source.kind === 'mirror'
  const vbytes = $derived(source.videoSize?.(id) ?? 0)
  let vsrc = $state(''), vprog = $state(''), saved = $state(false), saving = $state('')
  $effect(() => () => { if (vsrc) URL.revokeObjectURL(vsrc) })
  const pct = (g: number, t: number) => (t ? `${Math.round(g / t * 100)}%` : `${(g / 1e6).toFixed(1)} MB`)
  async function play() {
    vprog = 'Downloading…'
    try { vsrc = await videoUrl(id, (g, t) => { vprog = `Downloading ${pct(g, t)}` }); vprog = '' } catch (e) { vprog = (e as Error).message }
  }
  async function toggleSave() {
    if (saved) { await removeItem(id); saved = false; return }
    saving = 'Saving…'
    try { await saveItem(id, true, (g, t) => { saving = `Saving video ${pct(g, t)}` }); saved = true; onPhone = true; saving = '' } catch (e) { saving = ''; err = (e as Error).message }
  }

  // the card: markup + a HandCard (the engine tilts it while the finger drags, then settles)
  $effect(() => {
    if (!stage || !row) return
    // the same card as the Library grid shows (variant, colour, creator in the stub): Fred, 2026-10-16
    const html = cardMarkup(row, variantOf(row), 0)
    stage.innerHTML = html
    const slot = stage.querySelector<HTMLElement>('.slot')
    if (slot) {
      slot.style.setProperty('--t', TYPE[row.cat] || '#9cc4e2')
      themeSlot(slot, row)
      hand = new HandCard(slot, { idle: !phone.motionOff, onTap: () => {
        if (row.url) openLink?.click()
        else err = 'No URL for this item'
      } })
    }
    return () => { if (hand) { ALL.delete(hand); ACTIVE.delete(hand); hand = null } }
  })
  // the finger reaches the card through touch events (src/mobile/finger.ts), not the pointer ones
  $effect(() => { if (stage) return fingerTilt(stage, () => hand) })

  async function load() {
    scroller?.scrollTo({ top: 0 })
    const stored = await idb.get(id)
    if (stored) { full = stored.item; report = stored.report ?? ''; transcript = stored.transcript ?? ''; onPhone = true }
    try {
      const it = await source.item(id)
      full = it
      const [rep, tr] = await Promise.all([
        it.files.report ? source.itemText(id, 'report').catch(() => '') : Promise.resolve(''),
        it.files.transcript ? source.itemText(id, 'transcript').catch(() => it.transcript || '') : Promise.resolve(it.transcript || ''),
      ])
      report = rep; transcript = tr
      const s: StoredItem = { ...stored, id, at: Date.now(), item: it, report: rep, transcript: tr }     // keeps `saved`
      await idb.put(s)
      onPhone = true
    } catch (e) {
      if (!full) err = `Not on this phone yet, and the PC is out of reach (${(e as Error).message}).`
    }
    source.related(id).then(r => { related = r }).catch(() => { /* needs the PC */ })
  }
  onMount(load)
  onMount(() => { isSaved(id).then(v => { saved = v }) })

  const body = $derived.by(() => {
    if (!full) return ''
    if (tab === 'rep') return report ? mdHTML(report) : mdHTML(full.ai_desc || full.description || '') || (source.describe ? '<p>No description yet. Tap Describe to write one with your AI key, or let the PC do it.</p>' : '<p>No description yet. The PC writes one with Describe.</p>')
    if (tab === 'tr') return transcript ? `<pre>${transcript.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]!)}</pre>` : '<p>No transcript. Video analysis runs on the PC.</p>'
    return ''
  })
  const date = (ms: number) => (ms ? new Date(ms).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '')

  async function saveTags() {
    try { replaceRow(await source.edit(id, { tags })); editing = false } catch (e) { err = (e as Error).message }
  }
  // Describe / Categorize with the phone's own key (plans/E-phone-fixes.md); the PC gets them as edits
  let working = $state<'' | 'describe' | 'categorize'>('')
  let processing = $state(false)
  async function describeIt() {
    working = 'describe'; err = ''
    try {
      const text = await source.describe!(id)
      await patchRows([id])
      if (full) {
        full = { ...full, ai_desc: text }
        const s = await idb.get(id)
        if (s) await idb.put({ ...s, item: full })
      }
      tab = 'rep'
    } catch (e) { err = (e as Error).message } finally { working = '' }
  }
  async function categorizeIt() {
    working = 'categorize'; err = ''
    try { replaceRow(await source.categorize!(id, phone.cats.map(c => c.name))) } catch (e) { err = (e as Error).message } finally { working = '' }
  }
  async function forget() { await idb.del(id); onPhone = false }
  // Delete asks where first: only this phone's copy, or the PC library too (the mirror sends it as a
  // change file); without a PC, or on the desktop source, there is one choice
  let askDel = $state(false)
  const twoScopes = onMirror && !solo
  async function del(pc: boolean) {
    askDel = false
    try { await deleteItem(id, pc); history.back() } catch (e) { err = (e as Error).message }
  }
  function onChip(e: MouseEvent) {
    const b = (e.target as HTMLElement).closest<HTMLElement>('.cite[data-cid]')
    if (b) location.hash = `#/item/${b.dataset.cid}`
  }
</script>

{#if !row}
  <div class="m-empty">No card No.{id} in the phone's copy.</div>
{:else}
  <div class="m-it-stage" bind:this={stage}></div>
  <div class="m-sheet m-it-sheet">
    <h3 class="m-it-tt">{row.title || (row.id > 0 ? 'No.' + row.id : row.url)}</h3>
    {#if row.url}
      <!-- the first action, under the title, never below the fold -->
      <MButton as="a" variant="pri" class="m-open" bind:ref={openLink} href={row.url} target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></svg>Open in {srcLabel(row.src)}</MButton>
    {/if}
    {#if row.id < 0}
      <span class="m-badge wait">{solo ? 'Saved on this phone' : 'Waiting for the PC'}</span>
      <MHint as="small">{solo ? 'Link saved on this phone. Public previews may be unavailable; add your own AI key for Describe or Categorize.' : 'Link saved. Public previews and phone AI can run here; PC processing happens after sync.'}</MHint>
    {/if}
    <div class="m-it-meta"><span>{row.creator || 'unknown'}</span><span>{srcLabel(row.src)}</span><span>{row.cat}</span>{#if row.id > 0}<span>No. {row.id}</span>{/if}{#if row.type}<span>{row.type}</span>{/if}</div>
    {#if vsrc}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video class="m-video" src={vsrc} controls playsinline autoplay></video>
    {:else if onMirror && vbytes}
      <div class="m-vid"><div><b>Video from your PC</b><small>{vprog || `${(vbytes / 1e6).toFixed(1)} MB${saved ? ' · saved on this phone' : ' · downloads from Google Drive'}`} · plays the PC’s copy, not the original site</small></div><MButton variant="dk" size="sm" onclick={play} disabled={!!vprog && vprog.startsWith('Downloading')}>▶ Play</MButton></div>
    {:else if full?.files.video}
      <div class="m-vid"><div><b>Video downloaded on the PC</b><small>{onMirror ? 'Not in Google Drive: the PC mirrors videos per Settings > Backup & phones (None / Favourites / All)' : 'Uses the directly connected PC; it must remain reachable'}</small></div><span class="m-badge mute">PC</span></div>
    {/if}
    <div class="m-seg" role="group" aria-label="Item tabs">
      <button type="button" aria-pressed={tab === 'rep'} onclick={() => (tab = 'rep')}>{report ? 'Report' : 'Description'}</button>
      <button type="button" aria-pressed={tab === 'tr'} onclick={() => (tab = 'tr')}>Transcript</button>
      <button type="button" aria-pressed={tab === 'info'} onclick={() => (tab = 'info')}>Info</button>
    </div>
    {#if err}<div class="m-err" style="margin:0">{err}</div>{/if}
    {#if tab === 'info'}
      <div class="m-rep">
        <p>No. {row.id} · {srcLabel(row.src)} · {row.type}<br />Creator: {row.creator || 'unknown'}<br />Saved {date(row.created)} · collection {row.cat}</p>
        {#if full}<p>{full.ai_desc ? 'Has an AI description' : 'Not described yet'}{full.analysis_done ? ' · video analysed' : ''}{full.files.frames ? ` · ${full.files.frames} frames` : ''}</p>{/if}
        <p><a href={row.url} target="_blank" rel="noopener noreferrer">{row.url}</a></p>
        {#if full?.notes}<h4>My notes</h4><p>{full.notes}</p>{/if}
        <h4>Tags</h4>
        {#if editing}
          <label class="m-fld"><span class="m-pr">#</span><input bind:value={tags} placeholder="comma, separated, tags" /></label>
          <div class="m-acts" style="margin-top:8px"><MButton onclick={() => (editing = false)}>Cancel</MButton><MButton variant="dk" onclick={saveTags}>Save</MButton></div>
        {:else}
          <p>{row.tags || 'none'}</p>
        {/if}
      </div>
    {:else}
      <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
      <div class="m-rep" onclick={onChip}>{@html body}</div>
    {/if}
    {#if related.length}
      <span class="m-lbl">Related by meaning</span>
      <div class="m-rel">
        {#each related as r (r.id)}
          <button type="button" onclick={() => (location.hash = `#/item/${r.id}`)}>
            {#if r.thumb}<img src={source.thumbUrl(r, 160)} alt="" loading="lazy" />{:else}<div class="m-tint" style:background={tintOf(r)}></div>{/if}
            <span>{r.title || 'No.' + r.id}</span>
          </button>
        {/each}
      </div>
    {/if}
    <div class="m-acts">
      <MButton onclick={() => toggleFav(row.id)}>{row.fav ? '★' : '☆'} Favourite</MButton>
      <MButton onclick={() => { tags = row.tags; editing = true; tab = 'info' }}>Edit tags</MButton>
      <MButton onclick={() => processing = true}>Process item</MButton>
      {#if source.describe && source.categorize}
        <MButton onclick={describeIt} disabled={!!working}>{working === 'describe' ? 'Describing…' : 'Describe'}</MButton>
        <MButton onclick={categorizeIt} disabled={!!working}>{working === 'categorize' ? 'Categorizing…' : 'Categorize'}</MButton>
      {/if}
    </div>
    {#if processing}<Processing rows={[row]} close={() => processing = false} />{/if}
    <!-- states are switches, not buttons; Delete comes last, apart (audit 2026-10-15 #11) -->
    {#if onMirror && id > 0}
      <MRow title="Save for offline" desc={saving || (saved ? 'Kept on this phone with its video' : 'Keep it, and its video, with no signal')}><button type="button" class="m-tg" aria-pressed={saved} aria-label="Save for offline" onclick={toggleSave} disabled={!!saving}><i></i></button></MRow>
    {:else}
      <MRow title="Keep on this phone" desc={onPhone ? 'Readable with the PC out of reach' : 'Only the card for now'}><button type="button" class="m-tg" aria-pressed={onPhone} aria-label="Keep on this phone" onclick={() => (onPhone ? forget() : load())}><i></i></button></MRow>
    {/if}
    {#if source.describe}
      <MHint as="small">Describe: a static AI summary of the available post description/caption, title and thumbnail; it can also use a saved transcript. It does not download or watch the video. Categorize: picks a collection and tags. Analyze videos on the PC downloads the video if needed and examines sampled frames and/or its audio transcript.</MHint>
    {/if}
    {#if !askDel}<MButton class="m-del" onclick={() => (askDel = true)}>Delete</MButton>{/if}
    {#if askDel}
      <div class="m-acts">
        <MButton onclick={() => (askDel = false)}>Cancel</MButton>
        {#if twoScopes}
          <MButton onclick={() => del(false)}>From this phone</MButton>
          <MButton variant="pri" onclick={() => del(true)}>From phone and PC</MButton>
        {:else}
          <MButton variant="pri" onclick={() => del(true)}>Sure? Delete</MButton>
        {/if}
      </div>
      <MHint as="small">{twoScopes ? 'From this phone hides it here only; the PC library keeps it. Phone and PC deletes it on the PC too, the next time the PC runs.' : 'It is deleted for good.'}</MHint>
    {/if}
  </div>
{/if}
