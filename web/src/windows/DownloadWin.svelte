<script lang="ts">
  // The yt-dlp run window (Qt DownloadProgressDialog, V6 downloadVideo): the streamed lines of one
  // download job, the percentage and ETA, Cancel = stop the job.
  import { onMount, tick, untrack } from 'svelte'
  import { api } from '../lib/api'
  import { live, on } from '../lib/events.svelte'
  import { toast } from '../lib/ui.svelte'
  import DownloadRecovery from '../components/DownloadRecovery.svelte'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { jobId, itemId, thumbnailOnly, close }: { jobId: number; itemId: number; thumbnailOnly: boolean; close: () => void } = $props()
  let lines = $state<{ t: string; c: string }[]>([])
  let pct = $state(0)
  let status = $state(untrack(() => thumbnailOnly) ? 'Fetching the thumbnail…' : 'Downloading…')
  let done = $state(false)
  let action = $state('')
  let box: HTMLPreElement | undefined = $state()

  function push(t: string, c = '') {
    lines.push({ t, c })
    if (lines.length > 600) lines.splice(0, lines.length - 600)
    const m = t.match(/\[download\]\s+([0-9]{1,3}(?:\.[0-9]+)?)%/)
    if (m) { pct = Math.min(100, +m[1]); status = `Running yt-dlp… ${(+m[1]).toFixed(1)}%` }
    tick().then(() => { if (box) box.scrollTop = box.scrollHeight })
  }

  onMount(() => {
    const offs = [
      on('ytdlp', (d: { job: number; line: string }) => { if (d.job === jobId) push(d.line) }),
      on('job_item', (d: { job: number; state: string; error?: string; action?: string }) => {
        if (d.job !== jobId || d.state === 'working') return
        done = true
        action = d.action ?? ''
        if (d.state === 'done') { pct = 100; push(`✓ Completed: files in data/items/${itemId}/video/`, 'g'); status = thumbnailOnly ? 'Thumbnail saved.' : 'Done.' }
        else { push(`✗ ${d.error ?? 'yt-dlp failed'}`, 'r'); status = 'Failed.' }
      }),
      on('job', () => { if (!live.jobs.current && !done) { done = true; status = 'Stopped.' } }),
    ]
    return () => offs.forEach(f => f())
  })

  async function cancel() {
    if (done) { close(); return }
    push('Cancel requested: terminating yt-dlp…', 'a')
    try { await api.post('/api/jobs/stop') } catch (e) { toast((e as Error).message, 'w') }
  }
</script>

<WinBody>
  <pre class="tlog" bind:this={box} aria-live="polite">{#each lines as l, i (i)}<span class={l.c}>{l.t}</span>{'\n'}{/each}</pre>
  <div class="frow" style="margin-top:10px;align-items:center"><progress max="100" value={pct} style="flex:1"></progress><Hint>{status}</Hint></div>
  {#if done && action}<DownloadRecovery {action} {itemId} {thumbnailOnly} kind="download" />{/if}
</WinBody>
<WinFoot>
  <Button class={{ pri: done }} onclick={cancel}>{done ? 'Close' : 'Cancel'}</Button>
</WinFoot>
