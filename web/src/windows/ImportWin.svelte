<script lang="ts">
  // Import CSV or JSON (Qt main_window._import_file, V6 winImport): drop or choose a file, or pick
  // one of the scrape files kept in data/scrapes/. Rows whose URL is already in the library are
  // skipped; embedded thumbnails become data/items/<id>/thumb.jpg; new rows are then indexed.
  import { onMount } from 'svelte'
  import Px from '../lib/Px.svelte'
  import { api } from '../lib/api'
  import { isDesktop, pickFileObj, pickPath } from '../lib/pick'
  import { setWS, toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import SectionTitle from '../components/ui/SectionTitle.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { close }: { close: () => void } = $props()
  interface F { name: string; size: number; mtime: number }
  let files = $state<F[]>([])
  let pick = $state<string | null>(null)
  let busy = $state(false)
  let over = $state(false)

  onMount(async () => {
    try { files = await api.get<F[]>('/api/import/files'); pick = files[0]?.name ?? null } catch { /* empty list */ }
  })
  const kb = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)
  const day = (ms: number) => new Date(ms).toISOString().slice(0, 10)

  interface R { added: number; skipped: number; duplicates: number; invalid: number; file: string }
  function done(r: R) {
    close()
    setWS('lib')
    toast(`${r.file}: ${r.added} added, ${r.duplicates} already present, ${r.invalid} without a link. Links are saved independently of previews or video files.`, r.added ? '' : 'w')
  }
  async function run(body: () => Promise<R>) {
    if (busy) return
    busy = true
    try { done(await body()) } catch (e) { toast((e as Error).message, 'w') } finally { busy = false }
  }
  async function upload(f: File) {
    await run(async () => {
      const r = await fetch(`/api/import?name=${encodeURIComponent(f.name)}`, { method: 'POST', headers: { 'X-CM': '1' }, body: f })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || r.statusText)
      return j
    })
  }
  async function choose() {
    if (isDesktop()) {
      const p = await pickPath('import')
      if (p) await run(() => api.post<R>('/api/import', { path: p }))
      return
    }
    const f = await pickFileObj('.csv,.json')
    if (f) await upload(f)
  }
  function drop(e: DragEvent) {
    e.preventDefault()
    over = false
    const f = e.dataTransfer?.files?.[0]
    if (f) upload(f)
  }
  const importPicked = () => (pick ? run(() => api.post<R>('/api/import', { scrape: pick })) : choose())
</script>

<WinBody>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <button type="button" class="dropz" class:drop={over} style="width:100%" onclick={choose}
    ondragover={e => { e.preventDefault(); over = true }} ondragleave={() => (over = false)} ondrop={drop}>
    <span><Px name="up" /></span><b>Drop a scraper CSV or Brainamon JSON export here</b><span>or click to choose a file{files.length ? ', or pick one from data/scrapes/' : ''}</span>
  </button>
  {#if files.length}
    <SectionTitle as="p">data/scrapes/</SectionTitle>
    <div class="files" role="group" aria-label="Files">
      {#each files as f (f.name)}
        <button type="button" class="file" aria-pressed={pick === f.name} onclick={() => (pick = f.name)}><Px name="note" /><span>{f.name}<br /><small>{f.name.endsWith('.json') ? 'JSON' : 'CSV'} · {kb(f.size)}</small></span><small>{day(f.mtime)}</small></button>
      {/each}
    </div>
  {/if}
  <Hint style="margin-top:12px">Already saved links are skipped. Instagram Saved ZIP/JSON imports run on the phone through More > Import. Saving links does not guarantee pictures or downloaded videos; missing previews do not remove imported links.</Hint>
</WinBody>
<WinFoot>
  <Button onclick={close}>Cancel</Button>
  <Button variant="pri" disabled={busy} onclick={importPicked}>{busy ? 'Importing…' : pick ? 'Import' : 'Choose a file…'}</Button>
</WinFoot>
