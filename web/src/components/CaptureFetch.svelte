<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { live, on, type JobSnap, type JobsState } from '../lib/events.svelte'
  import Progress from './ui/Progress.svelte'

  let { itemId }: { itemId: number } = $props()
  interface ItemProgress { id: number; state: string; step?: string; error?: string }
  let status = $state('working'), step = $state(''), error = $state('')
  let jobId: number | null = null
  let revision = 0, disposed = false
  const running = $derived(status === 'working' || status === 'queued')
  const message = $derived(status === 'done' ? 'Link info fetched.'
    : status === 'error' ? 'Could not fetch link info. Your item is saved; you can try again from its card.'
    : status === 'stopped' ? 'Fetching stopped. Your item is saved; you can try again from its card.'
    : status === 'paused' ? 'Fetching paused. Your item is saved.'
    : status === 'unknown' ? 'Fetching status is unavailable. Open the card to check its details.'
    : 'Fetching thumbnail and description…')

  function update(item: ItemProgress, job?: JobSnap | null) {
    status = item.state
    step = item.step ?? ''
    error = item.error ?? ''
    if (!['done', 'error'].includes(status) && job && ['paused', 'stopped'].includes(job.state)) status = job.state
  }

  async function load() {
    if (['done', 'error', 'stopped'].includes(status)) return
    const version = revision
    try {
      const p = await api.get<{ job: JobSnap | null; items: ItemProgress[] }>('/api/jobs/progress')
      if (disposed || revision !== version) return
      const item = p.items.find(i => i.id === itemId)
      if (p.job?.kind === 'thumb' && item && (jobId === null || p.job.id === jobId)) {
        jobId = p.job.id
        update(item, p.job)
      } else if (!['done', 'error', 'stopped'].includes(status)) {
        // A fast fetch can finish before this window mounts and the automatic index takes over.
        const row = await api.get<{ thumb_path?: string; short_desc?: string; description?: string; url: string }>(`/api/items/${itemId}`)
        if (disposed || revision !== version) return
        status = row.thumb_path || row.short_desc || (row.description && row.description !== row.url) ? 'done' : 'unknown'
      }
    } catch {
      if (!disposed && revision === version && !['done', 'error', 'stopped'].includes(status)) status = 'unknown'
    }
  }

  onMount(() => {
    const offs = [
      on('job_item', (item: ItemProgress & { job: number }) => {
        const job = [live.jobs.current, live.jobs.last].find(j => j?.id === item.job)
        if (item.id !== itemId || (jobId !== null ? item.job !== jobId : job?.kind !== 'thumb')) return
        jobId = item.job
        revision++
        update(item, job)
      }),
      on('job', (jobs: JobsState) => {
        const job = [jobs.current, jobs.last].find(j => j?.id === jobId)
        if (job && !['done', 'error'].includes(status)) {
          if (job.state === 'stopped' || job.state === 'paused') { revision++; status = job.state }
          else if (job.state === 'running' && status === 'paused') { revision++; status = 'working' }
        }
        load()
      }),
      on('hello', load),
    ]
    load()
    return () => { disposed = true; offs.forEach(off => off()) }
  })
</script>

<div class="capture-fetch">
  <div role="status" aria-live="polite">
    <p>{message}</p>
    {#if running && step}<p class="cap-dim">{step}</p>{/if}
    {#if status === 'error' && error}<p class="cap-dim">{error}</p>{/if}
  </div>
  {#if running}
    <Progress label="Fetching thumbnail and description" />
    <p class="cap-dim">You can close this window. Fetching continues in the background.</p>
  {/if}
</div>

<style>
  .capture-fetch { margin-bottom:14px; max-width:65ch; font:400 11px/1.6 var(--mono); overflow-wrap:anywhere }
  p { margin:0 0 8px }
</style>
