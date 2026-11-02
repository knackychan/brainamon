<script lang="ts">
  // More > Import (milestone-2026-10-14/mobile-import/PLAN.md): saved posts from a site's own data
  // export. The sources and their steps come from ../import-sources.json (Instagram only for now), so
  // the wording can follow Meta's menus without touching this screen. The file is read on the phone
  // (../imports.ts); new links go in as phone changes and the picture strip fetches their pictures.
  import { fmtAgo, mirrorSource, patchRows, runPictures } from '../state.svelte'
  import { MAX_IMPORT_BYTES, readExport, TOO_BIG } from '../imports'
  import SOURCES from '../import-sources.json'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MHint from '../ui/MHint.svelte'
  import MRow from '../ui/MRow.svelte'

  type Source = (typeof SOURCES)[number]
  const key = (s: Source) => `bp-import-${s.id}`
  const askedOn = (s: Source) => { try { return +(localStorage.getItem(key(s)) || 0) } catch { return 0 } }

  let open = $state(SOURCES.length === 1 ? SOURCES[0].id : '')
  let asked = $state<Record<string, number>>(Object.fromEntries(SOURCES.map(s => [s.id, askedOn(s)])))
  let busy = $state(false), error = $state(''), done = $state('')
  let input: HTMLInputElement | undefined = $state()

  function sent(s: Source) {
    const now = Date.now()
    try { localStorage.setItem(key(s), String(now)) } catch { /* private window: shown until the screen closes */ }
    asked = { ...asked, [s.id]: now }
  }

  async function picked() {
    const f = input?.files?.[0]
    if (input) input.value = ''
    if (!f || !mirrorSource) return
    error = ''; done = ''
    if (f.size > MAX_IMPORT_BYTES) { error = TOO_BIG; return }
    busy = true
    try {
      const { posts, skipped } = await readExport(new Uint8Array(await f.arrayBuffer()))
      const r = await mirrorSource.importLinks(posts)
      if (r.ids.length) { await patchRows(r.ids); runPictures() }
      const parts = [`Added ${r.ids.length} link${r.ids.length === 1 ? '' : 's'}`]
      if (r.dups) parts.push(`${r.dups} already in the library`)
      if (skipped) parts.push(`${skipped} without a link skipped`)
      done = parts.join(' · ') + (r.ids.length ? '. Links are saved. Public previews may arrive later; some pictures may be unavailable.' : '.')
    } catch (e) {
      error = (e as Error).message
    } finally {
      busy = false
    }
  }
</script>

<div class="m-pad">
  <MHint as="p">Import Instagram Saved ZIP/JSON, up to 60 MiB. You do not need to give Brainamon your Instagram login. Other sites’ account exports are not supported. Video downloads and browser scraping run on a PC.</MHint>
  {#each SOURCES as s (s.id)}
    <MBox>
      <h3>{s.name}<span class="m-sp"></span><span class="m-lbl">{s.what}</span></h3>
      {#if open !== s.id}
        <MRow title="Import from {s.name}" desc="From the file {s.name} gives you"><MButton size="sm" onclick={() => (open = s.id)}>Steps</MButton></MRow>
      {:else}
        <ol class="m-steps">{#each s.steps as step, i (i)}<li>{step}</li>{/each}</ol>
        <MRow title="Ask {s.name} for the file" desc="Opens in the browser"><MButton as="a" size="sm" href={s.page} target="_blank" rel="noopener noreferrer">{s.pageLabel}</MButton></MRow>
        <MRow title={asked[s.id] ? `Requested ${fmtAgo(asked[s.id])}` : 'Request sent?'} desc={asked[s.id] ? s.wait : 'Tap once you asked, so this screen remembers'}><MButton size="sm" onclick={() => sent(s)}>{asked[s.id] ? 'Again' : 'I sent it'}</MButton></MRow>
        <MRow title="Choose the file" desc="The zip, or saved_posts.json"><MButton variant="pri" size="sm" onclick={() => input?.click()} disabled={busy || !mirrorSource}>{busy ? 'Reading…' : 'Choose'}</MButton></MRow>
      {/if}
    </MBox>
  {/each}
  <input type="file" accept=".zip,.json,application/zip,application/json" hidden bind:this={input} onchange={picked} />
  {#if !mirrorSource}<MHint>Import needs the phone's own library: pair with a PC, or start without one (More).</MHint>{/if}
  {#if error}<div class="m-err" role="alert">{error}</div>{/if}
  {#if done}<MHint role="status">{done}</MHint>{/if}
  <MHint>The export is read on this phone. Only imported links, captions, creators and hashtags enter your library and its optional sync.</MHint>
</div>
