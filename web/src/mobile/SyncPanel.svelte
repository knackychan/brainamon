<script lang="ts">
  // The sync panel (projects/phone-dock-shell, mockups/sync-v4.html, the layout of state 4): opened by the sync
  // key, a card under the top bar with a notch at the key. An owner-fixable state first (its sentence, Backup &
  // phones as the main key); else the steps of a Sync now run (state.svelte.ts syncNow), or the state in words at
  // rest; then the lanes of lanes.ts; then the keys.
  import { backup } from './backup.svelte'
  import { onMount } from 'svelte'
  import { scale } from 'svelte/transition'
  import { lampLabel } from './settings-words'
  import { t } from '../lib/i18n/index.ts'
  import { fmtNum } from '../lib/i18n/format.ts'
  import { backupHere, fmtAgo, mirrorSource, phone, phoneStatus, solo, source, syncNow } from './state.svelte'
  import { network, setSyncPaused, syncPaused } from './network.svelte'
  import { syncLanes } from './lanes'
  import { shell } from './shell.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'

  let { label }: { label: string } = $props()
  const MARK = { wait: '·', run: '…', ok: '✓', err: '!' }
  const run = $derived(phone.sync)
  const total = $derived(run?.steps.length ?? 0)
  const done = $derived(run ? run.steps.filter(s => s.state === 'ok' || s.state === 'err').length : 0)
  // the header names where the sync goes, with the step count while a run is open (whole clauses, not a glued suffix)
  const running = $derived(!!run && !run.end)
  const head = $derived(source.kind === 'mirror'
    ? (running ? t('shell.sync.headDriveRun', { done, total }) : t('shell.sync.headDrive'))
    : (running ? t('shell.sync.headPcRun', { done, total }) : t('shell.sync.headPc')))
  const st = $derived(phoneStatus())
  const owner = $derived(st?.strip ? st : null)
  const lanes = $derived(syncLanes().filter(l => l.key !== 'drive'))
  const busy = $derived(phone.refreshing || (!!run && !run.end))
  const paused = $derived(!!mirrorSource && syncPaused())
  const items = $derived(fmtNum(phone.rows.length, 'en'))
  // when the PC last uploaded the mirror (a paired phone; the solo phone has no PC)
  const uploaded = mirrorSource && !solo ? mirrorSource.manifest?.published ?? 0 : 0
  const still = phone.motionOff || matchMedia('(prefers-reduced-motion: reduce)').matches
  let el: HTMLElement | undefined = $state()

  function close() { shell.panel = false }
  onMount(() => {
    // a pointer down anywhere else closes it (the sync key toggles it itself); Escape too, back to the key
    const outside = (e: PointerEvent) => {
      const t = e.target instanceof Element ? e.target : null
      if (t && !el?.contains(t) && !t.closest('.m-sync-key')) close()
    }
    const key = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      close()
      document.querySelector<HTMLElement>('.m-sync-key')?.focus()
    }
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', key) }
  })
</script>

<section class="m-syncp" id="m-sync-panel" aria-label={t('shell.sync.title')} bind:this={el} transition:scale={{ start: 0.92, opacity: 0, duration: still ? 0 : 180 }}>
  <header class="m-syncp-head"><span>{head}</span><button type="button" class="m-syncp-fold" aria-label={t('shell.sync.close')} onclick={close}>▴</button></header>
  {#if owner}
    <p class="m-syncp-why"><b>{owner.text}</b><small>{t('shell.sync.keepsCopy', { n: phone.rows.length, items, ago: fmtAgo(phone.synced) })}</small></p>
  {:else if run}
    <ol class="m-syncp-steps">
      {#each run.steps as s (s.key)}
        <li class={`m-syncp-${s.state}`}><i aria-hidden="true">{MARK[s.state]}</i><span>{s.label}{#if s.note}<small>{s.note}</small>{/if}</span></li>
      {/each}
    </ol>
    {#if run.end}<p class="m-syncp-end" class:err={run.end === 'error'}>{run.msg}</p>{/if}
  {:else}
    <p class="m-syncp-why">{t('shell.sync.labelItems', { n: phone.rows.length, label, items })}<small>{uploaded ? t('shell.sync.readUploaded', { ago: fmtAgo(phone.synced), uploaded: fmtAgo(uploaded) }) : t('shell.sync.read', { ago: fmtAgo(phone.synced) })}</small></p>
  {/if}
  {#each lanes as l (l.key)}
    <div class="m-syncp-lane"><b>{l.name}</b> · {l.tag === 'running' || l.key === 'network' ? '' : `${lampLabel(l.tag)} · `}{l.text}{#if l.files}<MHint>{t('backup.vault.verified', l.files)}</MHint>{/if}{#if l.active && l.pct !== null}<span class="m-syncp-bar"><b style:width={`${l.pct}%`}></b></span>{/if}</div>
  {/each}
  <div class="m-syncp-btns">
    {#if owner}
      <MButton as="a" size="sm" variant="dk" href="#/backup">{t('shell.sync.backupLink')}</MButton>
      <MButton size="sm" disabled>{t('shell.sync.now')}</MButton>
    {:else}
      <MButton size="sm" variant="dk" disabled={busy || paused || !!backup.task || backup.busy} onclick={() => syncNow()}>{t('shell.sync.now')}</MButton>
      {#if mirrorSource}<MButton size="sm" disabled={network.pausePending} onclick={() => setSyncPaused(network.pauseFailed || !network.manualPause)}>{network.pausePending ? t('settings.sync.savingPolicy') : network.pauseFailed ? t('common.retry') : t(network.manualPause ? 'shell.sync.resume' : 'shell.sync.pause')}</MButton>{/if}
      <MButton as="a" size="sm" href={backupHere ? '#/backup' : '#/more'}>{backupHere ? t('shell.sync.backupLink') : t('shell.sync.settingsLink')}</MButton>
    {/if}
  </div>
</section>
