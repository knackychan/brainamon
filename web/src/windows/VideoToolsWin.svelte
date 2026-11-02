<script lang="ts">
  // Video Tools (Qt ui/video_analyzer_dialog.py, V6 winVideoTools): analyze a local video file with
  // the same options as the card Analyze (output in data/video_tools/items/<name>/), and the
  // thumbnail-downloader helper for a pasted URL. The log shows the analysis steps.
  import { onMount, tick } from 'svelte'
  import AnalyzeOptionsForm, { type AO } from './AnalyzeOptionsForm.svelte'
  import { api } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { jobBusy, jobBusyMsg } from '../lib/jobs'
  import { isDesktop, pickFileObj, pickPath } from '../lib/pick'
  import { toast } from '../lib/ui.svelte'
  import Button from '../components/ui/Button.svelte'
  import Field from '../components/ui/Field.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import SectionTitle from '../components/ui/SectionTitle.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { close }: { close: () => void } = $props()
  let cur = $state(0)
  const TABS = ['Video', 'Thumbnail']
  let path = $state('')
  let shown = $state('')
  let o = $state<AO | null>(null)
  let err = $state('')
  let url = $state('')
  let uploading = $state(false)
  let lines = $state<{ t: string; c: string }[]>([{ t: 'Ready.', c: 'd' }])
  let folder = $state('')
  let box: HTMLPreElement | undefined = $state()
  let mine = false
  const running = $derived(live.jobs.current?.kind === 'video_tools')

  function out(t: string, c = '') {
    if (lines.at(-1)?.t === t) return
    lines.push({ t, c })
    if (lines.length > 400) lines.splice(0, lines.length - 400)
    tick().then(() => { if (box) box.scrollTop = box.scrollHeight })
  }
  onMount(() => {
    api.get<{ options: AO }>('/api/settings/analyze').then(r => { o = r.options }).catch(e => { err = (e as Error).message })
    try { url = localStorage.getItem('cm-v6-vt-url') ?? '' } catch { /* private window */ }
    const offs = [
      on('job_item', (d: { step?: string; state: string; error?: string }) => {
        if (!mine || live.jobs.current?.kind !== 'video_tools') return
        if (d.step) out(`  ${d.step}`)
        if (d.state === 'error') out(`Error: ${d.error ?? 'failed'}`, 'r')
      }),
      on('video_tools', (d: { report: string; folder: string; transcript: boolean; analysis: string }) => {
        if (!mine) return
        mine = false
        folder = d.folder
        out(`Done. Report: ${d.report}`, 'g')
        if (d.transcript) out('Transcript captured.')
        if (d.analysis) { out('AI analysis:'); d.analysis.split('\n').forEach(l => out(l)) }
      }),
      on('job', () => { if (mine && !live.jobs.current) { mine = false; out('Finished.', 'd') } }),
    ]
    return () => offs.forEach(f => f())
  })

  async function browse() {
    if (isDesktop()) {
      const p = await pickPath('video')
      if (p) { path = p; shown = p }
      return
    }
    const f = await pickFileObj('video/*,.mkv,.m4v')
    if (!f) return
    uploading = true
    shown = `${f.name} (copying into data/video_tools/uploads/…)`
    try {
      const r = await fetch(`/api/video-tools/upload?name=${encodeURIComponent(f.name)}`, { method: 'PUT', headers: { 'X-CM': '1' }, body: f })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || r.statusText)
      path = j.path; shown = j.path
    } catch (e) { shown = ''; path = ''; toast(`Could not copy the video: ${(e as Error).message}`, 'w') } finally { uploading = false }
  }

  async function run() {
    if (!o) return
    err = ''
    if (!path) { out('No video selected.', 'r'); return }
    if (!(+o.frame_interval > 0) && !o.transcribe) { err = 'Nothing to analyze: set a frame interval or turn transcription on.'; return }
    if (jobBusy()) { toast(running ? 'A video is already being analyzed.' : jobBusyMsg(), 'w'); return }
    try { await api.put('/api/settings/analyze', o) } catch { /* the run still uses these options */ }
    folder = ''
    mine = true
    out(`Analyzing: ${path}`, 'a')
    try { await api.post('/api/video-tools/analyze', { path, opts: { ...o, frame_interval: +o.frame_interval } }) }
    catch (e) { mine = false; out((e as Error).message, 'r') }
  }

  async function thumb() {
    const u = url.trim()
    if (!u) { out('No URL entered for the thumbnail downloader.', 'r'); return }
    try { localStorage.setItem('cm-v6-vt-url', u) } catch { /* private window */ }
    try { await navigator.clipboard.writeText(u) } catch { /* not allowed: the site still opens */ }
    window.open('https://thumbnail-downloader.com/facebook/', '_blank', 'noopener')
    out('URL copied: paste it in thumbnail-downloader.com.', 'a')
  }
  async function reveal() { try { await api.post('/api/reveal', { path: folder }) } catch (e) { toast((e as Error).message, 'w') } }
  function tabKey(e: KeyboardEvent) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    cur = 1 - cur
    document.getElementById(`vt-t${cur}`)?.focus()
  }
</script>

<div class="ctabs" role="tablist">
  {#each TABS as label, i (i)}
    <button class="ctab" type="button" role="tab" id={`vt-t${i}`} aria-controls={`vt-p${i}`} aria-selected={cur === i}
      tabindex={cur === i ? 0 : -1} onclick={() => (cur = i)} onkeydown={tabKey}>{label}</button>
  {/each}
</div>
<WinBody>
  <div role="tabpanel" id="vt-p0" aria-labelledby="vt-t0" hidden={cur !== 0}>
    <div class="fg" style="margin-bottom:12px">
      <Field label="Video file" for="vt-f"><div class="frow">
        {#if isDesktop()}<input class="inp" id="vt-f" bind:value={path} placeholder="choose a local video, or paste its path" autocomplete="off" spellcheck="false" />
        {:else}<input class="inp" id="vt-f" value={shown} placeholder="choose a local video" readonly />{/if}
        <Button size="sm" disabled={uploading} onclick={browse}>Browse</Button>
      </div></Field>
    </div>
    <Hint>Choosing a file in a browser copies the video to this PC. Analyze sends audio and frames externally according to the options below.</Hint>
    {#if o}<AnalyzeOptionsForm bind:o {err} />{:else if err}<Hint tone="error">{err}</Hint>{/if}
    <div class="frow" style="margin-top:12px"><Button variant="pri" disabled={!o || running || uploading} onclick={run}>{running ? 'Analyzing…' : 'Analyze video'}</Button></div>
  </div>
  <div role="tabpanel" id="vt-p1" aria-labelledby="vt-t1" hidden={cur !== 1}>
    <div class="fg"><Field label="Video URL" for="vt-u"><input class="inp" id="vt-u" bind:value={url} placeholder="https://www.facebook.com/reel/…" autocomplete="off" spellcheck="false" /></Field></div>
    <Hint style="margin-top:8px">Copies the URL and opens thumbnail-downloader.com. To fetch a library item's thumbnail with yt-dlp, use Download thumbnail on its card.</Hint>
    <div class="frow" style="margin-top:12px"><Button variant="pri" onclick={thumb}>Open thumbnail downloader</Button></div>
  </div>
  <SectionTitle as="p" style="margin-top:16px">Log</SectionTitle>
  <pre class="tlog" bind:this={box} aria-live="polite">{#each lines as l, i (i)}<span class={l.c}>{l.t}</span>{'\n'}{/each}</pre>
</WinBody>
<WinFoot>
  {#snippet start()}
  <small>Output: data/video_tools/items/&lt;name&gt;/</small>
  {/snippet}
  {#if folder}<Button onclick={reveal}>Open folder</Button>{/if}
  <Button onclick={close}>Close</Button>
</WinFoot>
