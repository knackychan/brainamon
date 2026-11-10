<script lang="ts">
  // A job's live panel inside the page that starts it (Settings > Knowledge map): the rail's 12-segment bar,
  // the count, the time so far and left, the current step line, Pause / Resume / Stop, and the activity log
  // (one line per step: what it was, its result or error, how long it took). Shown while a job of `kind`
  // runs; after one of that kind was stopped it says what was kept and what is left. Everything comes from
  // live (the SSE `job` / `job_item` events) and GET /api/jobs/progress, as in the progress window.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { live, on, type JobSnap } from '../lib/events.svelte'
  import { jobControl } from '../lib/jobs'
  import { progress } from '../lib/progress'
  import { openProgress } from '../lib/job-commands'
  import Button from './ui/Button.svelte'
  import Disclosure from './ui/Disclosure.svelte'
  import Hint from './ui/Hint.svelte'
  import Progress from './ui/Progress.svelte'

  let { kind }: { kind: string } = $props()
  interface Line { id: number; state: string; title: string; step?: string; error?: string; t?: number; ms?: number }
  let lines = $state<Line[]>([])
  let jobId = $state(0)
  let now = $state(Date.now())

  const job = $derived(live.jobs.current?.kind === kind ? live.jobs.current : null)
  const stopped = $derived(!job && live.jobs.last?.kind === kind && live.jobs.last.state === 'stopped' ? live.jobs.last : null)
  const n = $derived(job ? job.done + (job.skipped ?? 0) + job.err : 0)
  const paused = $derived(job?.state === 'paused')
  const p = $derived(job ? progress(n, job.total, job.t0 * 1000, now) : { pct: 0, left: '' })
  const log = $derived(lines.filter(l => l.state !== 'queued'))

  async function load() {
    try {
      const r = await api.get<{ job: JobSnap | null; items: Line[] }>('/api/jobs/progress')
      if (r.job?.kind === kind) { jobId = r.job.id; lines = r.items } else { jobId = 0; lines = [] }
    } catch { /* the next job event loads it again */ }
  }
  onMount(() => {
    load()
    const tick = setInterval(() => { if (job && !paused) now = Date.now() }, 1000)
    const offs = [
      on('job_item', (d: Line & { job: number }) => {
        if (d.job !== jobId) { if (job) load(); return }
        const l = lines.find(x => x.id === d.id)
        if (!l) { load(); return }
        l.state = d.state
        for (const k of ['step', 'error', 't', 'ms'] as const) if (d[k] !== undefined) (l as any)[k] = d[k]
      }),
      on('job', () => { if (live.jobs.current?.kind === kind && live.jobs.current.id !== jobId) load() }),
    ]
    return () => { clearInterval(tick); offs.forEach(f => f()) }
  })

  // the log follows its last line, as a terminal does, unless the reader scrolled up
  function follow(el: HTMLElement) {
    let stick = true
    el.addEventListener('scroll', () => { stick = el.scrollHeight - el.scrollTop - el.clientHeight < 40 })
    $effect(() => {
      void log.length; void live.step
      if (stick) el.scrollTop = el.scrollHeight
    })
  }

  const clock = (t?: number) => t ? new Date(t * 1000).toTimeString().slice(0, 8) : ''
  const took = (l: Line) => l.state === 'working' ? 'working…' : l.ms ? `${(l.ms / 1000).toFixed(1)} s` : ''
  function elapsed(ms: number) {
    const s = Math.max(0, Math.round(ms / 1000))
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
  }
</script>

{#if job}
  <div class="job-live">
    <p class="job-live-hd"><span>{job.label}</span><b class:held={paused}>{paused ? 'PAUSED' : 'RUNNING'}</b></p>
    <Progress label={`${job.label} progress`} pct={job.total ? Math.floor(100 * n / job.total) : 0} />
    <Hint>{n} of {job.total} steps{job.skipped ? ` · ${job.skipped} skipped` : ''}{job.err ? ` · ${job.err} failed` : ''} · {elapsed(now - job.t0 * 1000)} so far{p.left ? ` · ${p.left}` : ''}</Hint>
    {#if live.step}<Hint role="status">{live.step}</Hint>{/if}
    <div class="frow">
      <Button size="sm" onclick={() => jobControl(paused ? 'resume' : 'pause')}>{paused ? 'Resume' : 'Pause'}</Button>
      <Button size="sm" variant="danger" onclick={() => jobControl('stop')}>Stop</Button>
      <Button size="sm" onclick={openProgress}>Progress window</Button>
    </div>
  </div>
{:else if stopped}
  <Hint role="status">Stopped after {stopped.done + (stopped.skipped ?? 0) + stopped.err} of {stopped.total} steps. Everything finished is saved; {stopped.total - stopped.done} left{stopped.err ? ` (${stopped.err} failed)` : ''}. The next run does only what is left.</Hint>
{/if}
{#if (job || stopped) && log.length}
  <Disclosure summary={`Activity · ${log.length} step${log.length === 1 ? '' : 's'}`} open={!!job}>
    <div class="job-log" role="log" aria-label="Activity" use:follow>
      {#each log as l (l.id)}
        <p class:bad={l.state === 'error'}><time>{clock(l.t)}</time><span>{l.title}</span><span title={l.error ?? l.step ?? ''}>{l.error ?? l.step ?? ''}</span><em>{took(l)}</em></p>
      {/each}
    </div>
  </Disclosure>
{/if}
