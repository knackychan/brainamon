<script lang="ts">
  // More > Setup: one row per thing to set up, a neutral dot (filled when ready, a ring when not, never a
  // cross), and Set up / Change, which scrolls to the matching box (ids m-conn, m-ai, m-vault below; a phone paired
  // with a PC or used without one finds its m-phone, m-conn and m-recovery on More > Backup & phones). The Library
  // shows Get started instead (GetStarted.svelte).
  import { isApp } from './native'
  import { openBackupBox, openMoreBox } from './onboard.svelte'
  import { driveStatus, mirrorSource, phone, solo, source } from './state.svelte'
  import { token } from './mirror/pairing'
  import { recoveryFact } from './mirror/recovery-fact'
  import { vault } from './vault/auto.svelte'
  import MBox from './ui/MBox.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'

  const m = mirrorSource
  interface Row { id: string; label: string; ok: boolean; note: string; backup?: boolean }   // backup: the box is on Backup & phones
  const rows = $derived.by((): Row[] => {
    void phone.synced; void phone.tokenAt; void phone.signIn; void phone.recoveryAt
    const drive = driveStatus()
    const signedIn = m ? !!token(m.pair) : false
    const ai = m?.ai() ?? null
    const out: Row[] = []
    if (m && solo) out.push({ id: 'm-phone', label: 'Your phone', ok: true, note: 'Saving here. A PC is optional.', backup: true })
    else if (m) out.push({ id: 'm-phone', label: 'Your PC', ok: true, note: `Paired · key ${m.pair.f}`, backup: true })
    else out.push({ id: 'm-conn', label: 'Your PC', ok: phone.reachable, note: phone.reachable ? `${location.host} over USB` : isApp ? 'Not paired: scan the code on the PC' : 'Not reachable' })
    if (m) out.push({ id: 'm-conn', label: 'Google Drive', ok: signedIn && drive.ok, note: signedIn ? (drive.ok ? (solo ? 'Drive connected' : 'Syncing with the PC') : drive.why) : solo ? 'Not backed up yet' : 'Not connected', backup: true })
    if (m && solo) {
      const r = recoveryFact(m.pair)
      out.push({ id: 'm-recovery', label: 'Recovery', ok: r === 'prepared' || r === 'checked', note: r === 'none' ? 'Not set up' : r === 'prepared' ? 'Passphrase set' : r === 'saved' ? 'Recovery file saved, not checked' : 'Passphrase set · recovery file checked', backup: true })
    }
    if (m) out.push({ id: 'm-ai', label: 'Wiskit on this phone', ok: !!ai, note: ai ? `${ai.providers.find(p => p.id === ai.provider)?.label ?? ai.provider} on your key` : solo ? 'Add your own AI key' : 'Pair again with an AI key ticked on the PC' })
    if (isApp && !solo && source.syncVault) out.push({ id: 'm-vault', label: 'Obsidian vault', ok: vault.opts.on && !!vault.opts.uri, note: vault.opts.on && vault.opts.uri ? vault.opts.name || 'Syncing with the PC' : 'Keep a vault on this phone' })
    return out
  })
  const missing = $derived(rows.filter(r => !r.ok).length)
</script>

<MBox class="m-setup">
  <h3>Setup<span class="m-sp"></span><span class="m-lbl">{missing ? `${missing} optional` : 'all set'}</span></h3>
  {#each rows as r, i (r.id + i)}
    <div class="m-srow m-setup-row">
      <i class="m-setup-dot" class:on={r.ok} aria-hidden="true"></i>
      <b>{r.label}</b><span class="sr">{r.ok ? ', ready' : ', optional'}</span><small>{r.note}</small>
      <MButton size="sm" onclick={() => (r.backup ? openBackupBox : openMoreBox)(r.id)}>{r.ok ? 'Change' : 'Set up'}</MButton>
    </div>
  {/each}
  {#if !isApp}<MHint>Link previews work best in the Android app.</MHint>{/if}
</MBox>

<style>
  .m-setup-row { grid-template-columns: 22px minmax(0, 1fr) auto }
  .m-setup-row small { grid-column: 2 }
  .m-setup-row :global(.m-btn) { grid-column: 3; grid-row: 1 / span 2 }
  .m-setup-dot { grid-row: 1 / span 2; width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--wg-edge) }
  .m-setup-dot.on { border-color: var(--m-ok); background: var(--m-ok) }
</style>
