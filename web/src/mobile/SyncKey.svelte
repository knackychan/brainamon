<script lang="ts">
  // The sync key (projects/phone-dock-shell, mockups/sync-v4.html): a 36 px circle on the section pages, always
  // there. Its ring is the progress and its colour the state (sync-ring.ts); no words on it: the lamp sentence
  // (Mobile.svelte `lamp`) is its name, and a hidden status line announces it. A tap opens the sync panel.
  import { mirrorSource, phone, syncFill } from './state.svelte'
  import { network, syncPaused } from './network.svelte'
  import { syncLanes } from './lanes'
  import { GLYPH, RING_C, ringOf } from './sync-ring'
  import { shell } from './shell.svelte'
  import MKey from './ui/MKey.svelte'
  import SyncPanel from './SyncPanel.svelte'

  let { label, amber = false, pull = 0 }: { label: string; amber?: boolean; pull?: number } = $props()
  const run = $derived(phone.sync)
  // the vault rounds and the picture queue run on their own; the Drive read is `run` / phone.refreshing
  const lanes = $derived(syncLanes().filter(l => l.tag === 'running' && l.key !== 'drive' && l.key !== 'network'))
  const running = $derived((!!run && !run.end) || phone.refreshing || lanes.length > 0)
  const fill = $derived.by(() => {
    if (run && !run.end) return syncFill(run)
    if (phone.refreshing) return phone.read?.frac ?? null
    const pcts = lanes.map(l => l.pct).filter((p): p is number => p !== null)
    return pcts.length ? Math.max(...pcts) / 100 : null
  })
  const ring = $derived(ringOf({
    pull, running, fill,
    manualPause: !!mirrorSource && network.manualPause,
    waiting: !!mirrorSource && syncPaused() && network.online && !network.manualPause,
    problem: amber || run?.end === 'error',
  }))
  // a new page closes the panel
  $effect(() => { void phone.route; shell.panel = false })
</script>

<div class="m-sync">
  <span class="m-sr" role="status" aria-live="polite">{label}</span>
  <MKey class={['m-sync-key', ring.tone]} tone={shell.panel ? 'dark' : 'plain'} aria-label={label} title={label}
    aria-expanded={shell.panel} aria-controls="m-sync-panel" onclick={() => (shell.panel = !shell.panel)}>
    <svg class="m-ring" viewBox="0 0 28 28" aria-hidden="true">
      <circle class="t" cx="14" cy="14" r="11" />
      <circle class="f" cx="14" cy="14" r="11" stroke-dasharray={RING_C} stroke-dashoffset={RING_C * (1 - ring.frac)} />
    </svg>
    <span class="m-ring-g" class:spin={ring.spin} style:rotate={ring.turn ? `${ring.turn}deg` : undefined} aria-hidden="true">{GLYPH[ring.glyph]}</span>
  </MKey>
  {#if shell.panel}<SyncPanel {label} />{/if}
</div>
