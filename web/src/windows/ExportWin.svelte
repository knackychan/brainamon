<script lang="ts">
  // Export (Qt _export_csv / _export_obsidian, V6 winExport): two tabs, each one a background job.
  // Export for phone retired with the Google Drive mirror (Settings > Backup & phones, plan Phase 3). The
  // log shows the job's steps; when it ends the result text and Open folder. Exports never write inside data/ (the Obsidian vault is the exception: it is
  // data/Fredorama by default and the exporter owns its Content Manager subfolder).
  import { onMount, tick, untrack } from 'svelte'
  import { api } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { jobBusy, jobBusyMsg, startJob } from '../lib/jobs'
  import { openSettings } from '../lib/io-commands.svelte'
  import { isDesktop, pickPath } from '../lib/pick'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Field from '../components/ui/Field.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { close, tab = 0 }: { close: () => void; tab?: number } = $props()
  let cur = $state(untrack(() => tab))
  const TABS = ['Item CSV', 'Obsidian']
  let csvPath = $state(''), vault = $state('')
  let isVault = $state(true), owner = $state(false)
  let cov = $state<{ indexed: number; total: number; low: boolean } | null>(null)
  let lines = $state<{ t: string; c: string }[]>([])
  let result = $state<{ path: string; text: string } | null>(null)
  let jobId = $state<number | null>(null)
  let pendingKind = ''      // events can arrive before the start reply: match the running job's kind
  let box: HTMLPreElement | undefined = $state()
  const running = $derived(jobId !== null && live.jobs.current?.id === jobId)

  function out(t: string, c = '') {
    if (lines.at(-1)?.t === t) return
    lines.push({ t, c })
    if (lines.length > 400) lines.splice(0, lines.length - 400)
    tick().then(() => { if (box) box.scrollTop = box.scrollHeight })
  }

  onMount(() => {
    api.get<{ home: string; csv_path: string; vault: string; is_vault: boolean; owner: boolean }>('/api/export/defaults')
      .then(d => { csvPath = d.csv_path; vault = d.vault; isVault = d.is_vault; owner = d.owner })
    api.get<typeof cov>('/api/export/obsidian/coverage').then(c => { cov = c })
    const offs = [
      on('job_item', (d: { job: number; step?: string; state: string; error?: string }) => {
        const mine = d.job === jobId || (pendingKind && live.jobs.current?.id === d.job && live.jobs.current.kind === pendingKind)
        if (!mine) return
        if (d.step) out(d.step)
        if (d.state === 'error') out(d.error ?? 'Failed', 'r')
      }),
      on('export_done', (d: { path: string; text: string }) => {
        if (jobId === null && !pendingKind) return
        result = d
        d.text.split('\n').forEach((t, i) => out(t, i ? '' : 'g'))
      }),
    ]
    return () => offs.forEach(f => f())
  })

  async function browse() {
    const p = await pickPath('folder')
    if (p) vault = p
  }

  async function go(kind: 'csv' | 'obsidian') {
    if (jobBusy()) { toast(jobBusyMsg(), 'w'); return }
    lines = []; result = null; pendingKind = 'export_' + kind
    const body = kind === 'csv' ? { path: csvPath } : { vault }
    out(kind === 'csv' ? `Item CSV export to ${csvPath}` : `Export to Obsidian: ${vault}`, 'a')
    try {
      const snap = await api.post<{ current: { id: number } | null }>(`/api/export/${kind}`, body)
      jobId = snap.current?.id ?? live.jobs.current?.id ?? null
    } catch (e) { out((e as Error).message, 'r') }
  }
  async function indexNow() {
    close()
    await startJob('index', {})
  }
  async function reveal() {
    if (result) { try { await api.post('/api/reveal', { path: result.path }) } catch (e) { toast((e as Error).message, 'w') } }
  }

  function tabKey(e: KeyboardEvent) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    cur = (cur + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length
    document.getElementById(`exp-t${cur}`)?.focus()
  }
</script>

<div class="ctabs" role="tablist">
  {#each TABS as label, i (i)}
    <button class="ctab" type="button" role="tab" id={`exp-t${i}`} aria-controls={`exp-p${i}`} aria-selected={cur === i}
      tabindex={cur === i ? 0 : -1} onclick={() => (cur = i)} onkeydown={tabKey}>{label}</button>
  {/each}
</div>
<WinBody>
  <div role="tabpanel" id="exp-p0" aria-labelledby="exp-t0" hidden={cur !== 0}>
    <p class="about">Item metadata as CSV: links, descriptions, item notes, categories, tags and dates. Re-import with File &gt; Import. This is not a full backup: it excludes images, videos, processing files and status, chats, Knowledge notes, settings and cloud keys. Quit Brainamon and copy the whole data folder for library recovery.</p>
    <div class="fg" style="margin-top:12px"><Field label="File" for="x-csv"><input class="inp" id="x-csv" bind:value={csvPath} autocomplete="off" spellcheck="false" /></Field></div>
    <div class="frow" style="margin-top:12px"><Button variant="pri" disabled={running} onclick={() => go('csv')}>Export item CSV</Button></div>
  </div>
  <div role="tabpanel" id="exp-p1" aria-labelledby="exp-t1" hidden={cur !== 1}>
    {#if owner}
      <p class="about">Your Obsidian vault is a Brainamon vault: Settings &gt; Obsidian &amp; map keeps it up to date and refreshes the AI topics. The classic export is not needed.</p>
      <div class="frow" style="margin-top:12px"><Button variant="pri" onclick={() => { close(); openSettings('obsidian') }}>Open Settings &gt; Obsidian &amp; map</Button></div>
    {:else}
      <p class="about">The classic export: one page per item, your notes from data/notes/, the tag topics, the AI topics of the knowledge map and the map page, into a Content Manager subfolder of a vault you already use. For a vault of Brainamon's own, use Settings &gt; Obsidian &amp; map instead.</p>
      <div class="fg" style="margin-top:12px">
        <Field label="Vault folder" for="x-vault"><div class="frow"><input class="inp" id="x-vault" bind:value={vault} autocomplete="off" spellcheck="false" />{#if isDesktop()}<Button size="sm" onclick={browse}>Browse</Button>{/if}</div></Field>
        <span></span><Hint>AI topics come from Settings &gt; Obsidian &amp; map &gt; Refresh map; the export writes the ones already built.</Hint>
        {#if !isVault}<span></span><Hint>This folder has no .obsidian subfolder, so it may not be an Obsidian vault. The export still goes into its Content Manager subfolder.</Hint>{/if}
      </div>
      {#if cov?.low}
        <Hint tone="error" style="margin-top:12px">Only {cov.indexed} of {cov.total} items are indexed for semantic search, so the Related links and AI topics will be sparse.</Hint>
        <div class="frow" style="margin-top:8px"><Button onclick={indexNow}>Index now</Button><Button variant="pri" disabled={running} onclick={() => go('obsidian')}>Export anyway</Button></div>
      {:else}
        <div class="frow" style="margin-top:12px"><Button variant="pri" disabled={running} onclick={() => go('obsidian')}>Export to Obsidian</Button></div>
      {/if}
    {/if}
  </div>
  {#if lines.length}<pre class="tlog" bind:this={box} style="margin-top:12px" aria-live="polite">{#each lines as l, i (i)}<span class={l.c}>{l.t}</span>{'\n'}{/each}</pre>{/if}
</WinBody>
<WinFoot>
  {#snippet start()}
  <small>Obsidian: the generated subfolders are wiped and rebuilt on every export; data/notes/ is the source.</small>
  {/snippet}
  {#if result}<Button onclick={reveal}>Open folder</Button>{/if}
  <Button onclick={close}>Close</Button>
</WinFoot>
