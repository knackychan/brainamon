<script lang="ts">
  // Settings > Obsidian & map (spec 2026-10-28 map engine and owner vault, decision 1), calm layout: a summary,
  // the Vault group (owner status, Vault not found, the legacy Move, or the setup steps: first, create, pick),
  // the Vault sync with phone group the window renders (`phoneSync` snippet), and the Knowledge map group, which works with
  // or without a vault. Every string comes from lib/obsidian.ts.
  import { onMount, type Snippet } from 'svelte'
  import { api, ApiError } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { jobBusy, jobBusyMsg, plural, startJob } from '../lib/jobs'
  import { COPY, firstOpenText, leftoversText, mapLine, newToObsidianText, removeText, statusLine, unlistedText, useAnyway, vaultIn, type MapStatus } from '../lib/obsidian'
  import { isDesktop, pickPath } from '../lib/pick'
  import { toast } from '../lib/ui.svelte'
  import { confirmWin } from '../lib/windows.svelte'
  import Button from './ui/Button.svelte'
  import Disclosure from './ui/Disclosure.svelte'
  import InfoTip from './ui/InfoTip.svelte'
  import GroupBox from './ui/GroupBox.svelte'
  import Hint from './ui/Hint.svelte'
  import ItemList from './ui/ItemList.svelte'
  import Label from './ui/Label.svelte'
  import JobLive from './JobLive.svelte'
  import Progress from './ui/Progress.svelte'
  import Status from './ui/Status.svelte'
  import TextButton from './ui/TextButton.svelte'
  import ToggleRow from './ui/ToggleRow.svelte'

  interface View {
    vault: string; mode: 'owner' | ''; exists: boolean; is_vault: boolean; legacy: boolean; default_location: string; earlier_vault: boolean
    pictures: boolean; first_open: 'pending' | ''; vault_sync_on: boolean; installed: boolean
    map: { topics: number; stale: number; pending: number; model_changed: boolean; coverage: { indexed: number; total: number; low: boolean } }
    status: MapStatus
  }
  interface KnownVault { path: string; open: boolean; ts: number }

  let { sync, phoneSync }: { sync: { on: boolean; text: string }; phoneSync?: Snippet } = $props()
  let v = $state<View | null>(null)
  let error = $state('')
  let busy = $state('')                                  // the request in flight: 'setup' | 'move' | 'reset' | ...
  let step = $state<'first' | 'create' | 'pick'>('first')
  let path = $state('')                                  // the create step's folder
  let movePath = $state('')
  let known = $state<KnownVault[]>([])
  let confirmFor = $state<{ path: string; count: number; message: string; create: boolean } | null>(null)
  let takeoverFor = $state<{ path: string; leftovers: number; message: string; create: boolean } | null>(null)
  let locating = $state(false)                           // Locate the folder: the picker after Vault not found
  let rebuild = $state(false)
  let changing = $state(false)                           // Use another folder: the setup screens over an owner vault
  const refreshing = $derived(live.jobs.current?.kind === 'refresh_map')
  const owner = $derived(!!v && v.mode === 'owner' && !changing)
  const flowOpen = $derived(changing || !!confirmFor || !!takeoverFor || busy === 'setup' || busy === 'move' || (!!v && v.mode !== 'owner' && !v.legacy && step !== 'first'))

  async function load() {
    try { v = await api.get<View>('/api/obsidian'); error = ''; if (!path) path = v.default_location; if (!movePath) movePath = v.default_location }
    catch (e) { error = (e as Error).message }
  }
  onMount(() => {
    load()
    const offs = [
      on('map', (d: MapStatus) => { if (v && (d.seq ?? 0) >= (v.status.seq ?? 0)) v.status = d }),
      on('settings_changed', load),
      on('job', (d: { current: { kind: string } | null; last: { kind: string } | null }) => { if (!d.current && d.last?.kind === 'refresh_map') load() }),
    ]
    return () => offs.forEach(f => f())
  })

  function fail(e: unknown) { error = e instanceof ApiError ? e.message : String(e) }

  // ── setup ──────────────────────────────────────────────────────────────────
  async function chooseFolder() {
    const p = await pickPath('folder')
    if (p) path = vaultIn(p)
  }
  async function setVault(folder: string, create: boolean, confirm = false, takeover = false, remove = false) {
    busy = 'setup'; error = ''; confirmFor = null; takeoverFor = null
    try {
      const r = await api.put<View & { needs_confirm?: boolean; needs_takeover?: boolean; count?: number; message?: string }>('/api/obsidian/vault', { path: folder, create, confirm, takeover, remove })
      if (r.needs_takeover) { takeoverFor = { path: folder, leftovers: r.count ?? 0, message: r.message ?? '', create }; return }
      if (r.needs_confirm) { confirmFor = { path: folder, count: r.count ?? 0, message: r.message ?? '', create }; return }
      v = r; changing = false; locating = false; step = 'first'
      toast(takeover ? 'Vault reconnected.' : create ? 'Vault created. Open it in Obsidian once.' : 'Vault set up.')
    } catch (e) { fail(e) } finally { busy = '' }
  }
  async function openPicker() {
    step = 'pick'
    try { known = (await api.get<{ vaults: KnownVault[] }>('/api/obsidian/vaults')).vaults } catch { known = [] }
  }
  async function pickExisting() {
    const p = await pickPath('folder')
    if (p) await setVault(p, false)
  }

  // ── owner actions ──────────────────────────────────────────────────────────
  async function act(what: string, url: string, body: unknown = {}) {
    busy = what; error = ''
    try { v = await api.post<View>(url, body); return true } catch (e) { fail(e); return false } finally { busy = '' }
  }
  async function cancel() { try { await api.post('/api/obsidian/cancel') } catch (e) { fail(e) } }
  async function copyPath() {
    try { await navigator.clipboard.writeText(v?.vault ?? ''); toast('Path copied') } catch { toast('Select the path and copy it by hand', 'w') }
  }
  async function openObsidian() {
    try {
      const r = await api.post<{ opened: boolean; vault: string }>('/api/obsidian/graph')
      toast(r.opened ? 'Opening Obsidian. Press Ctrl+G there for the graph view.' : newToObsidianText(r.vault))
    } catch (e) { toast((e as Error).message, 'w') }
  }
  async function firstOpenDone() {
    try { v = await api.post<View>('/api/obsidian/first-open/done') } catch (e) { fail(e) }
  }
  async function pictures(on: boolean) {
    try { v = await api.put<View>('/api/obsidian/options', { pictures: on }) } catch (e) { fail(e) }
  }
  async function reset(rel: string) {
    const ok = await confirmWin({ title: COPY.reset, msg: `Replace your edits in ${rel} with the generated page?`, detail: 'Your version is lost; the page is Brainamon’s again and follows the library.', ok: COPY.reset, danger: true })
    if (ok) await act('reset', '/api/obsidian/reset', { path: rel })
  }
  async function reclaim() {
    const ok = await confirmWin({ title: COPY.reclaim, msg: `${COPY.reclaim}?`, detail: COPY.reclaimDetail, ok: COPY.reclaim, danger: true })
    if (ok) await act('reclaim', '/api/obsidian/reclaim')
  }
  async function removeLeftovers() {
    const ok = await confirmWin({ title: COPY.removeLeftovers, msg: removeText(v?.status.leftovers ?? 0), detail: COPY.removeDetail, ok: COPY.removeLeftovers, danger: true })
    if (ok) await act('remove', '/api/obsidian/leftovers/remove')
  }
  async function takeOverRemove() {
    const t = takeoverFor
    if (!t) return
    const ok = await confirmWin({ title: COPY.takeOverRemove, msg: removeText(t.leftovers), detail: COPY.removeDetail, ok: COPY.takeOverRemove, danger: true })
    if (ok) await setVault(t.path, t.create, false, true, true)
  }
  async function locate() {
    changing = true; locating = true; step = 'first'
    if (!isDesktop()) { openPicker(); return }       // a browser tab has no native dialog: the typed-path page
    const p = await pickPath('folder')
    if (p) await setVault(p, false)
    else { changing = false; locating = false }
  }
  function createInstead() { changing = true; locating = false; step = 'create'; path = v?.default_location ?? path }
  async function move() {
    const ok = await confirmWin({ title: COPY.moveTitle, msg: `Copy your vault to ${movePath}?`, detail: COPY.moveHint, ok: COPY.moveButton })
    if (!ok) return
    if (await act('move', '/api/obsidian/move', { path: movePath })) toast(COPY.moveDone)
  }
  async function chooseMoveFolder() {
    const p = await pickPath('folder')
    if (p) movePath = vaultIn(p)
  }

  // ── the map ────────────────────────────────────────────────────────────────
  async function refresh() {
    if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
    error = ''
    try {
      const p = await api.post<{ count: number; provider?: string; model?: string; plan?: { tags: number; rebuild: number; summaries: number } }>(
        '/api/jobs/preview', { kind: 'refresh_map', ids: [], force: true, opts: { rebuild } })
      if (!p.count) { toast(COPY.upToDate); return }
      const plan = p.plan ?? { tags: 0, rebuild: 0, summaries: 0 }
      const parts = [plan.tags ? `clean up ${plural(plan.tags, 'tag')}` : '', plan.rebuild ? `rebuild ${plural(plan.rebuild, 'topic')}` : '', plan.summaries ? `write ${plural(plan.summaries, 'summary')}` : ''].filter(Boolean)
      const ok = await confirmWin({
        title: `${COPY.refresh}?`, code: 'JOB-01', ok: COPY.refresh,
        msg: `Brainamon will ${parts.join(', ')} with ${p.provider ?? 'your'} · ${p.model ?? 'Wiskit model'} (Settings > Wiskit & AI).`,
        detail: `Estimated cost: about $${Math.max(0.01, plan.summaries * 0.01 + Math.ceil(plan.tags / 300) * 0.02).toFixed(2)}; actual cost varies. Nothing paid runs on its own.`,
      })
      if (!ok) return
      await api.post('/api/jobs', { kind: 'refresh_map', ids: [], force: true, opts: { rebuild } })
      rebuild = false
      toast(`${COPY.refresh}: ${plural(p.count, 'step')} started`)
    } catch (e) { fail(e) }
  }
  async function indexNow() { await startJob('index', {}) }
</script>

{#snippet feedback()}
  {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
{/snippet}

{#if !v}
  {@render feedback()}
  <Hint role="status">Loading…</Hint>
{:else}
<div class="set-calm">
  <GroupBox tone="summary" aria-label="Obsidian status">
    <Label as="span">Vault</Label>
    <div><span>{v.mode === 'owner' ? v.vault : v.legacy ? `${v.vault} · legacy` : 'None yet'}</span></div>
    <Label as="span">Vault sync with phone</Label>
    <div><Status on={sync.on}>{sync.text}</Status></div>
    <Label as="span">{COPY.mapTitle}</Label>
    <div><Status on={v.map.topics > 0 && !v.map.stale && !v.map.pending}>{mapLine(v.map)}</Status></div>
  </GroupBox>

  <GroupBox active={flowOpen} aria-label="Vault">
    <Label as="span" id="set-s-obsidian-vault" tabindex={-1}>Vault</Label>
    {#if v.mode === 'owner' && !changing && !v.exists}
      <div>
        <Hint tone="error" role="alert">{COPY.missingTitle}</Hint>
        <Hint>{COPY.missingHint}</Hint>
        <Hint>{v.vault}</Hint>
      </div>
      <span></span>
      <div>
        {@render feedback()}
        <div class="frow"><Button variant="pri" size="sm" disabled={!!busy} onclick={locate}>{COPY.locate}</Button><TextButton disabled={!!busy} onclick={createInstead}>{COPY.create}</TextButton></div>
      </div>
    {:else if owner}
      <div>
        <Status on={!v.status.pending && !v.status.error && !v.status.other_library && v.status.last_render > 0} aria-live="polite">{statusLine(v.status)}</Status>
        {#if v.status.busy}<Progress label={v.status.busy} />{/if}
        <Hint>Edit items in Brainamon; write your own notes anywhere else in the vault.<InfoTip label="What Brainamon writes"><span>{COPY.viewHint}</span><span>{COPY.picturesHint}</span><span>{COPY.ownerSync}</span><span>Connecting your own notes vault comes in a later update.</span></InfoTip></Hint>
        <ToggleRow label={COPY.pictures} note="about 45 KB per item" checked={v.pictures} onchange={pictures} />
      </div>
      {#if v.first_open === 'pending'}
        <Label as="span">{COPY.firstOpenTitle}</Label>
        <div>
          <Hint>{firstOpenText(v.vault)}</Hint>
          {#if !v.installed}<Hint>Obsidian is not installed on this PC. Get it from obsidian.md, then open the folder above as a vault.</Hint>{/if}
          <div class="frow"><Button variant={v.status.other_library ? 'default' : 'pri'} size="sm" onclick={firstOpenDone}>{COPY.done}</Button><TextButton disabled={!v.installed} onclick={openObsidian}>{COPY.openObsidian}</TextButton></div>
        </div>
      {/if}
      {#if v.status.other_library}
        <Label as="span">Owner</Label>
        <div><Hint>{COPY.takeOverHint}</Hint><div class="frow"><Button variant="pri" size="sm" disabled={!!busy} onclick={() => act('takeover', '/api/obsidian/takeover')}>{COPY.takeOver}</Button></div></div>
      {/if}
      {#if v.status.unlisted}
        <Label as="span">Unlisted files</Label>
        <div><Hint>{unlistedText(v.status.unlisted)}</Hint><div class="frow"><Button size="sm" disabled={!!busy} onclick={reclaim}>{COPY.reclaim}</Button></div></div>
      {/if}
      {#if v.status.leftovers}
        <Label as="span">Leftovers</Label>
        <div><Hint>{leftoversText(v.status.leftovers)}</Hint><div class="frow"><Button size="sm" disabled={!!busy} onclick={removeLeftovers}>{COPY.removeLeftovers}</Button></div></div>
      {/if}
      {#if v.status.adopted.length}
        <Label as="span">Adopted pages</Label>
        <div>
          <Hint>You edited these generated pages. Brainamon keeps your version and never updates or removes them.</Hint>
          <ItemList items={v.status.adopted} key={rel => rel} label="Adopted pages">
            {#snippet item(rel)}<span>{rel}</span>{/snippet}
            {#snippet actions(rel)}<TextButton disabled={!!busy} onclick={() => reset(rel)}>{COPY.reset}</TextButton>{/snippet}
          </ItemList>
        </div>
      {/if}
      <span></span>
      <div>
        {@render feedback()}
        <div class="frow">
          {#if v.status.busy && v.status.waiting}<Button size="sm" onclick={cancel}>{COPY.cancel}</Button>{/if}
          <Button size="sm" disabled={!v.is_vault} onclick={openObsidian}>{COPY.openVault}</Button>
          <TextButton onclick={copyPath}>{COPY.copyPath}</TextButton>
          <TextButton onclick={() => { changing = true; step = 'first' }}>{COPY.changeVault}</TextButton>
        </div>
      </div>
    {:else if v.legacy && !changing}
      <div>
        <Status>Legacy vault inside the data folder<InfoTip label="What the move does"><span>{COPY.moveHint}</span></InfoTip></Status>
        <Hint>{v.vault}</Hint>
        {#if v.vault_sync_on}<Hint>{COPY.syncOnHint}</Hint>{/if}
      </div>
      <Label for="obs-move">New folder</Label>
      <div><div class="frow"><input class="inp" id="obs-move" bind:value={movePath} autocomplete="off" spellcheck="false" />{#if isDesktop()}<Button size="sm" onclick={chooseMoveFolder}>{COPY.changeFolder}</Button>{/if}</div></div>
      <span></span>
      <div>
        {@render feedback()}
        {#if busy === 'move'}<Progress label="Moving the vault" />{/if}
        <div class="frow"><Button variant="pri" size="sm" disabled={!!busy || !movePath.trim()} onclick={move}>{COPY.moveButton}</Button>{#if v.status.waiting}<TextButton onclick={cancel}>{COPY.cancel}</TextButton>{/if}</div>
      </div>
    {:else}
      {#if step === 'first'}
        <div>
          {#if v.vault && !v.legacy && v.mode !== 'owner'}<Hint>Export to Obsidian writes a Content Manager folder into {v.vault}. This tab sets up a vault of Brainamon’s own instead; the classic export stays in the Export window.</Hint>{/if}
          {#if v.earlier_vault}<Status role="status">{COPY.earlierHint} {v.default_location}.</Status>{/if}
          <Hint>Brainamon makes a vault of its own and keeps it in step with your library.<InfoTip label="What Brainamon writes"><span>{COPY.viewHint}</span><span>{COPY.existingHint}</span></InfoTip></Hint>
          {#if v.vault_sync_on}<Hint>{COPY.syncOnHint}</Hint>{/if}
        </div>
      {:else if step === 'create'}
        <div><Hint>Brainamon makes a vault of its own and keeps it in step with your library.</Hint></div>
        <Label for="obs-create">{COPY.willCreate}</Label>
        <div>
          <div class="frow"><input class="inp" id="obs-create" bind:value={path} autocomplete="off" spellcheck="false" />{#if isDesktop()}<Button size="sm" onclick={chooseFolder}>{COPY.changeFolder}</Button>{/if}</div>
          {#if isDesktop()}<Hint>{COPY.folderHint}</Hint>{/if}
        </div>
      {:else}
        <div><Hint><b>{locating ? COPY.locateTitle : COPY.pickTitle}</b></Hint><Hint>{locating ? COPY.locateHint : COPY.pickHint}</Hint></div>
        {#if known.length}
          <Label as="span">{COPY.knownVaults}</Label>
          <div>
            <ItemList items={known} key={k => k.path} label={COPY.knownVaults}>
              {#snippet item(k)}<span>{k.path}</span>{/snippet}
              {#snippet actions(k)}<TextButton disabled={!!busy} aria-label={`${COPY.use}: ${k.path}`} onclick={() => setVault(k.path, false)}>{COPY.use}</TextButton>{/snippet}
            </ItemList>
          </div>
        {/if}
        {#if !isDesktop()}
          <Label for="obs-pick">Folder</Label>
          <div><input class="inp" id="obs-pick" bind:value={path} autocomplete="off" spellcheck="false" /></div>
        {/if}
      {/if}
      {#if confirmFor}
        <Label as="span">Other files</Label>
        <div><Hint>{confirmFor.message}</Hint></div>
      {/if}
      {#if takeoverFor}
        <Label as="span">{COPY.earlierTitle}</Label>
        <div><Hint>{takeoverFor.message}</Hint></div>
      {/if}
      <span></span>
      <div>
        {@render feedback()}
        {#if busy === 'setup'}<Progress label="Setting up the vault" />{/if}
        <div class="frow">
          {#if confirmFor}
            <Button variant="pri" size="sm" disabled={!!busy} onclick={() => setVault(confirmFor!.path, confirmFor!.create, true)}>{useAnyway(confirmFor.count)}</Button>
            <TextButton onclick={() => (confirmFor = null)}>{COPY.cancel}</TextButton>
          {:else if takeoverFor}
            <Button variant="pri" size="sm" disabled={!!busy} onclick={() => setVault(takeoverFor!.path, takeoverFor!.create, false, true)}>{takeoverFor.leftovers ? COPY.takeOverKeep : COPY.takeOver}</Button>
            {#if takeoverFor.leftovers}<Button size="sm" disabled={!!busy} onclick={takeOverRemove}>{COPY.takeOverRemove}</Button>{/if}
            <TextButton onclick={() => (takeoverFor = null)}>{COPY.otherFolder}</TextButton>
          {:else if step === 'first'}
            {#if v.earlier_vault}<Button variant="pri" size="sm" disabled={!!busy} onclick={() => setVault(v!.default_location, true)}>{COPY.reconnect}</Button>{/if}
            <Button variant={v.earlier_vault ? 'default' : 'pri'} size="sm" disabled={!!busy} onclick={() => { step = 'create'; path = v?.default_location ?? path }}>{COPY.create}…</Button>
            <TextButton onclick={openPicker}>{COPY.emptyLink}</TextButton>
            {#if changing}<TextButton onclick={() => (changing = false)}>{COPY.cancel}</TextButton>{/if}
          {:else if step === 'create'}
            <Button variant="pri" size="sm" disabled={!!busy || !path.trim()} onclick={() => setVault(path.trim(), true)}>{COPY.createButton}</Button>
            <TextButton onclick={() => (step = 'first')}>{COPY.cancel}</TextButton>
          {:else}
            {#if isDesktop()}<Button variant="pri" size="sm" disabled={!!busy} onclick={pickExisting}>{COPY.browse}</Button>
            {:else}<Button variant="pri" size="sm" disabled={!!busy || !path.trim()} onclick={() => setVault(path.trim(), false)}>{COPY.use}</Button>{/if}
            <TextButton onclick={() => { step = 'first'; locating = false }}>{COPY.cancel}</TextButton>
          {/if}
        </div>
      </div>
    {/if}
  </GroupBox>

  {@render phoneSync?.()}

  <GroupBox aria-label={COPY.mapTitle}>
    <Label as="span" id="set-s-obsidian-map" tabindex={-1}>{COPY.mapTitle}<InfoTip label="What Refresh map does"><span>{COPY.mapHint}</span></InfoTip></Label>
    <div>
      <Status on={!v.map.coverage.low} role="status">{v.map.coverage.indexed} of {v.map.coverage.total} items indexed for search by meaning</Status>
      {#if v.map.coverage.low}<Hint>Topics and Related links are sparse until more items are indexed.</Hint>{/if}
      {#if v.map.model_changed}<Hint tone="error">The search embeddings model changed: the next Refresh map rebuilds the topics.</Hint>{/if}
      <ToggleRow label={COPY.rebuild} bind:checked={rebuild} />
    </div>
    <span></span>
    <div>
      <JobLive kind="refresh_map" />
      <div class="frow">
        <Button variant={owner && v.first_open !== 'pending' && !v.status.other_library ? 'pri' : 'default'} size="sm" disabled={refreshing} onclick={refresh}>{refreshing ? 'Refreshing…' : live.jobs.last?.kind === 'refresh_map' && live.jobs.last.state === 'stopped' ? COPY.finish : COPY.refresh}</Button>
        {#if v.map.coverage.low}<TextButton onclick={indexNow}>{COPY.indexNow}</TextButton>{/if}
      </div>
    </div>
  </GroupBox>
</div>
{/if}
