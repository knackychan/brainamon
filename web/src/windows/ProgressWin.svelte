<script lang="ts">
  // The progress window (Qt ui/analysis_progress_window.py, V6 openProgress): every item of the
  // running (or last) job with its step and state. GET /api/jobs/progress, then live job_item events.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { titleOf } from '../lib/cards/card'
  import { JOB_SHORT, live, on, type JobSnap } from '../lib/events.svelte'
  import { jobControl } from '../lib/jobs'
  import { lib, thumbSrc } from '../lib/library.svelte'
  import { toast } from '../lib/ui.svelte'
  import DownloadRecovery from '../components/DownloadRecovery.svelte'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import SectionTitle from '../components/ui/SectionTitle.svelte'
  import Progress from '../components/ui/Progress.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { close }: { close: () => void } = $props()
  interface PItem { id: number; state: string; title: string; step?: string; error?: string; code?: string; action?: string }
  let job = $state<JobSnap | null>(null)
  let items = $state<PItem[]>([])

  async function load() {
    try {
      const p = await api.get<{ job: JobSnap | null; items: PItem[] }>('/api/jobs/progress')
      job = p.job
      items = p.items
    } catch (e) { toast((e as Error).message, 'w') }
  }
  onMount(() => {
    load()
    const offs = [
      on('hello', load),
      on('job_item', (d: { job: number; id: number; state: string; step?: string; error?: string; code?: string; action?: string }) => {
        if (!job || d.job !== job.id) { load(); return }
        const it = items.find(x => x.id === d.id)
        if (!it) { load(); return }
        it.state = d.state
        if (d.step) it.step = d.step
        if (d.error) it.error = d.error
        if (d.action) it.action = d.action
      }),
      on('job', () => { const j = live.jobs.current ?? live.jobs.last; if (j && (!job || j.id !== job.id || j.total !== items.length)) load(); else if (j) job = j }),
    ]
    return () => offs.forEach(f => f())
  })

  const running = $derived(job?.state === 'running' || job?.state === 'paused')
  const paused = $derived(job?.state === 'paused')
  const S: Record<string, [string, string]> = { queued: ['', 'Queued'], working: ['run', 'Processing'], done: ['ok', 'Done'], skipped: ['', 'Skipped'], error: ['bad', 'Failed'] }
  const ordered = $derived([...items.filter(it => it.state === 'working'), ...items.filter(it => it.state === 'queued'), ...items.filter(it => it.state !== 'working' && it.state !== 'queued')])
  const waiting = $derived(items.filter(it => it.state === 'queued').length)
  const name = (it: PItem) => { const r = lib.byId.get(it.id); return r ? titleOf(r) : it.title }
</script>

<WinBody>
  {#if !job}
    <div class="emp"><h3>No job yet</h3><p>Start one from the Process menu, the command palette (Ctrl+K) or a card's right-click menu. Each item shows its status here while the job runs.</p></div>
  {:else}
    {@const j = live.jobs.current?.id === job.id ? live.jobs.current : job}
    <SectionTitle as="p">{j.label}{j.auto ? ' · automatic' : ''} · {j.done} done{j.skipped ? `, ${j.skipped} skipped` : ''}{j.err ? `, ${j.err} failed` : ''} of {j.total}</SectionTitle>
    <Progress label={`${j.label} progress`} pct={j.total ? 100 * (j.done + (j.skipped ?? 0) + j.err) / j.total : 0} paused={paused || !running} />
    <Hint role="status">{waiting} {j.state === 'stopped' ? 'not processed' : 'queued'}{paused ? ' · Paused' : ''}.{#if running}{' '}You can close this window; the job stays {paused ? 'paused' : 'running'}.{/if}</Hint>
    {#if !live.connected}<Hint role="status">Reconnecting to live progress…</Hint>{/if}
    <div class="queue-head" aria-hidden="true"><span>Item</span><span>Activity</span><span>Status</span></div>
    {#each ordered as it (it.id)}
      {@const [c, l] = S[it.state] ?? S.queued}
      <div class="prow" class:active={it.state === 'working'} data-item-id={it.id} title={it.error ?? ''}>
        {#if lib.byId.get(it.id)?.thumb}<img src={thumbSrc(it.id)} alt="" />{:else}<span></span>{/if}
        <span title={name(it)}>{it.id > 0 ? `No.${it.id} · ` : ''}{name(it)}</span>
        <em>{it.state === 'error' ? (it.error ?? '').slice(0, 60) : it.state === 'queued' ? (j.state === 'stopped' ? 'Stopped before this item' : 'Waiting to start') : it.state === 'working' ? it.step ?? (JOB_SHORT[job.kind] ?? job.kind).toLowerCase() : it.state === 'skipped' ? it.step ?? '' : 'Saved'}</em>
        <b class={c}>{it.state === 'queued' && j.state === 'stopped' ? 'Not processed' : it.state === 'working' && paused ? 'Paused' : l}</b>
      </div>
      {#if it.state === 'error' && it.action}<Hint role="status">{it.error}</Hint><DownloadRecovery action={it.action} itemId={it.id} kind={job.kind} />{/if}
    {/each}
  {/if}
</WinBody>
<WinFoot>
  {#snippet start()}
  <small>{running ? (paused ? 'Paused' : 'Running') : job ? `${job.state === 'stopped' ? 'Stopped' : 'Finished'} ${new Date((job.t1 || Date.now() / 1000) * 1000).toTimeString().slice(0, 5)}` : ''}</small>
  {/snippet}
  <Button disabled={!running} onclick={() => jobControl(paused ? 'resume' : 'pause')}>{paused ? 'Resume' : 'Pause'}</Button>
  <Button variant="danger" disabled={!running} onclick={() => jobControl('stop')}>Stop</Button>
  <Button variant="pri" onclick={close}>Close</Button>
</WinFoot>

<style>
  .queue-head, .prow { grid-template-columns: 30px minmax(0, 1fr) 150px 100px; }
  .queue-head { display: grid; gap: 12px; padding: 12px 4px 6px; font: 500 12px var(--mono); color: var(--rw-dim); }
  .queue-head span:first-child { grid-column: span 2; }
  .prow.active { background: var(--seg-off); }
  .prow.active > span { font-weight: 700; }
  @media (max-width: 540px) {
    .queue-head { display: none; }
    .prow { grid-template-columns: 30px minmax(0, 1fr) 100px; }
    .prow em { grid-column: 2; grid-row: 2; }
    .prow b { grid-column: 3; grid-row: 1 / span 2; }
  }
</style>
