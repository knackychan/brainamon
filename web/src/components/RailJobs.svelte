<script lang="ts">
  // The rail's Jobs module: the running job without opening the progress window (kind, label, state,
  // done + failed of total, a 12-segment bar, the current step line) with Pause / Resume / Stop
  // (jobControl, as the progress window). Pinned above the rail's scroll area, so it stays in view on
  // every workspace. All of it comes from live (the SSE `job` / `job_item` events). While a job runs
  // (not paused) one thing moves: the dscan sweep in the bar's front segment, or across the whole bar
  // for a one-item job (a connections scan). Idle and paused draw nothing that moves.
  // The Google Drive backup has a DRIVE row only while it is something to watch (D14): the first backup, removing
  // phones, another long task, or a pause that waits for Resume. A small change upload stays out of it.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { hm, long, num } from '../lib/backup'
  import { runCmd } from '../lib/commands'
  import { JOB_SHORT, live } from '../lib/events.svelte'
  import { openSettings } from '../lib/io-commands.svelte'
  import { jobControl } from '../lib/jobs'
  import { requestLabel, reviewRequest } from '../lib/job-requests'
  import { progress } from '../lib/progress'
  import { toast } from '../lib/ui.svelte'
  import Button from './ui/Button.svelte'
  import KeyIcon from './ui/KeyIcon.svelte'

  const job = $derived(live.jobs.current)
  const last = $derived(live.jobs.last)
  const request = $derived(live.jobs.request?.state === 'pending' ? live.jobs.request : null)
  const n = $derived(job ? job.done + job.err : 0)
  const lit = $derived(job && job.total ? Math.min(12, Math.floor(12 * n / job.total)) : 0)
  const paused = $derived(job?.state === 'paused')
  // the segment being filled: the one after the lit run (none when paused or full)
  const lead = $derived(paused ? -1 : lit)
  const short = (k: string) => JOB_SHORT[k] ?? k.toUpperCase()
  // the Google Drive backup (server/sync.py), shown under the jobs, and the Obsidian vault sync
  const cl = $derived(live.cloud)
  let now = $state(Date.now())
  onMount(() => { const t = setInterval(() => { now = Date.now() }, 15000); return () => clearInterval(t) })
  const drive = $derived.by((): { row: string; step: string; pct: number | null; kind: 'paused' | 'pausing' | 'busy' | 'error' } | null => {
    if (!cl?.signed_in) return null
    const task = cl.task ?? null
    if (task?.kind === 'disconnect' && task.error) return { row: `${task.title} stopped`, step: task.error, pct: null, kind: 'error' }
    if (task?.kind === 'disconnect' || cl.state === 'disconnecting') return null
    if ((cl.paused_since ?? 0) > 0 && !cl.running) return { row: `Backup paused · ${long(Math.max(0, now - cl.paused_since!))}`, step: `Changes since ${hm(cl.last_publish || cl.paused_since!)} are only on this PC.`, pct: null, kind: 'paused' }
    if (cl.state === 'stopping') return { row: 'Pausing after the current upload request', step: '', pct: null, kind: 'pausing' }
    if (task?.error || (task && task.kind !== 'update_folder' && cl.state === 'error')) return { row: `${task.title} stopped`, step: task.error || cl.error, pct: null, kind: 'error' }
    if (task && task.kind !== 'enroll') {
      const frac = task.total ? task.done / task.total : 0
      if (task.kind === 'remove_phones') return task.step >= 3 ? { row: `Removing phones · step ${task.step} of 5`, step: '', pct: task.step === 3 ? 70 * frac : task.step === 4 ? 70 + 30 * frac : 100, kind: 'busy' } : null
      // Update this folder: a row while it downloads; Downloaded waits for Restart now in Backup & phones
      if (task.kind === 'update_folder') return ['queued', 'downloading'].includes(task.stage) && !task.error ? { row: 'Updating this folder', step: '', pct: task.bytes_total ? 100 * task.bytes_done / task.bytes_total : null, kind: 'busy' } : null
      return { row: `${task.title} · step ${task.step} of ${task.of}`, step: '', pct: task.bytes_total ? 100 * (task.bytes_done / task.bytes_total) : 100 * frac, kind: 'busy' }
    }
    if (!cl.last_publish && ['starting', 'publishing'].includes(cl.state)) {
      const pct = cl.bytes_total ? 100 * (cl.bytes_done ?? 0) / cl.bytes_total : cl.total ? 100 * cl.done / cl.total : null
      return { row: cl.total ? `First backup · ${num(cl.done)}/${num(cl.total)}` : 'First backup · checking what to send', step: '', pct, kind: 'busy' }
    }
    return null
  })
  // Disconnect waits for the upload threads to end: said at once, no bar
  const mirrorMove = $derived(cl?.state === 'disconnecting' || (cl?.task?.kind === 'disconnect' && !cl.task.error) ? 'Disconnecting from Google Drive' : '')
  // the vault sync has its own On / Off (vault_running), not the mirror's
  const vaultBusy = $derived(!!cl?.vault_running && (cl.vault_state === 'syncing' || cl.vault_state === 'starting'))
  const vaultMove = $derived(cl?.vault_state === 'stopping' ? 'Stopping the vault sync' : '')
  const vp = $derived(cl && vaultBusy ? progress(cl.vault_done, cl.vault_total, cl.vault_since) : { pct: 0, left: '' })
  const seg = (pct: number) => Math.min(12, Math.floor(12 * pct / 100))
  const uploading = $derived(!!drive || vaultBusy || !!mirrorMove || !!vaultMove)

  async function call(path: 'pause' | 'resume') {
    try { await api.post(`/api/cloud/${path}`) } catch (e) { toast((e as Error).message, 'w') }
  }
</script>

{#snippet segBar(label: string, pct: number)}
  <div class="prog" role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(pct)}>
    {#each { length: 12 } as _, i (i)}<i class:lit={i < seg(pct)} class:lead={i === seg(pct)}></i>{/each}
  </div>
{/snippet}

<section class="wg rjobs" class:on={!!job || uploading || !!request} aria-labelledby="h-rjobs">
  <header class="wg-hd"><h2 id="h-rjobs">Jobs</h2><span class="n" role="status">{job ? (paused ? 'Paused' : 'Running') : request ? 'Pending approval' : drive?.kind === 'paused' ? 'Paused' : drive?.kind === 'busy' || vaultBusy ? 'Uploading' : drive || mirrorMove || vaultMove ? 'Drive' : 'Idle'}</span></header>
  {#if request}
    <p class="rj-row"><b class="rj-k">PENDING</b><span class="l" title={`${request.source}: ${requestLabel(request)}`}>{requestLabel(request)}</span></p>
    <p class="rj-step">{request.source} · awaiting your approval</p>
    <div class="rj-keys"><Button onclick={reviewRequest}>Review request</Button></div>
  {/if}
  {#if job}
    <p class="rj-row"><b class="rj-k">{short(job.kind)}</b><span class="l">{job.label}{job.auto ? ' · auto' : ''}</span><span class="c">{n}/{job.total}</span></p>
    {#if job.total > 1}
      <div class="prog" role="progressbar" aria-label={`${job.label} progress`} aria-valuemin="0" aria-valuemax={job.total} aria-valuenow={n}>
        {#each { length: 12 } as _, i (i)}<i class:lit={i < lit} class:lead={i === lead}></i>{/each}
      </div>
    {:else}
      <!-- one long step (a connections scan, one note): no count to fill, so the scan bar runs -->
      <div class="rj-run" class:held={paused} role="progressbar" aria-label={`${job.label} running`}></div>
    {/if}
    {#if live.step}<p class="rj-step" title={live.step}>{live.step}</p>{/if}
    <div class="rj-keys">
      <Button onclick={() => jobControl(paused ? 'resume' : 'pause')}>{paused ? 'Resume' : 'Pause'}</Button>
      <Button variant="danger" onclick={() => jobControl('stop')}>Stop</Button>
      <Button onclick={() => runCmd('progress')}>Progress</Button>
    </div>
    {#if job.err}<p class="rj-err">{job.err} failed</p>{/if}
  {:else if !request}
    <p class="rj-row rj-idle"><span class="l">idle{last ? ` · last: ${short(last.kind)} ${last.done}/${last.total}${last.err ? `, ${last.err} failed` : ''}${last.state === 'stopped' ? ', stopped' : ''}` : ''}</span>
      {#if last}<Button onclick={() => runCmd('progress')}>Progress</Button>{/if}</p>
  {/if}
  {#if drive}
    <p class="rj-row"><b class="rj-k">DRIVE</b><span class="l">{drive.row}</span>{#if drive.pct !== null}<span class="c">{Math.round(drive.pct)}%</span>{/if}</p>
    {#if drive.pct !== null}{@render segBar(drive.row, drive.pct)}{/if}
    {#if drive.step}<p class="rj-step">{drive.step}</p>{/if}
    {#if drive.kind !== 'pausing'}
      <div class="rj-keys">
        {#if drive.kind === 'paused'}<Button onclick={() => call('resume')}><KeyIcon name="play" />Resume backup</Button>
        {:else if drive.kind === 'busy'}<Button onclick={() => call('pause')}><KeyIcon name="pause" />Pause backup</Button>{/if}
        <Button onclick={() => openSettings('backup', 'set-s-sync-uploads')}>Progress</Button>
      </div>
    {/if}
  {/if}
  {#if mirrorMove}
    <p class="rj-row"><b class="rj-k">DRIVE</b><span class="l">{mirrorMove}</span>{#if cl?.state === 'disconnecting' && cl.total}<span class="c">{cl.done}/{cl.total}</span>{/if}</p>
  {/if}
  {#if vaultBusy && cl}
    <p class="rj-row"><b class="rj-k">VAULT</b><span class="l">{cl.vault_state === 'starting' ? 'Obsidian vault · starting' : `${cl.vault_step} · ${cl.vault_done}/${cl.vault_total}${vp.left ? ` · ${vp.left}` : ''}`}</span><span class="c">{vp.pct}%</span></p>
    {@render segBar('Obsidian vault sync', vp.pct)}
  {/if}
  {#if vaultMove}
    <p class="rj-row"><b class="rj-k">VAULT</b><span class="l">{vaultMove}</span></p>
  {/if}
  {#if (vaultBusy || mirrorMove || vaultMove) && !drive}
    <div class="rj-keys"><Button onclick={() => openSettings('backup', 'set-s-sync-uploads')}>Progress</Button></div>
  {/if}
</section>
