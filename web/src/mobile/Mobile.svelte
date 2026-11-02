<script lang="ts">
  // The phone shell (PLAN.md "What the mobile app does"): app bar, one screen, the bottom tab bar.
  // Screens are hash routes (src/mobile/state.svelte.ts parseRoute) so the Android back button works.
  import { onMount, untrack } from 'svelte'
  import { boot, fmtAgo, mirrorSource, phone, phoneStatus, solo, source, syncNow, TAB_NAME, type Tab } from './state.svelte'
  import { autoKeep } from './offline.svelte'
  import { exitApp, isApp, onBackButton, onShared, onSharedFile } from './native'
  import { parentHash } from './back'
  import { fileName, kindOf, UNREADABLE } from './files'
  import { cap, shareIn } from './capture.svelte'
  import { kv } from './store'
  import { UPDATE_APP } from './source/mirror'
  import Library from './screens/Library.svelte'
  import Item from './screens/Item.svelte'
  import Canvas from './screens/Canvas.svelte'
  import Capture from './screens/Capture.svelte'
  import Wiskit from './screens/Wiskit.svelte'
  import Notes from './screens/Notes.svelte'
  import More from './screens/More.svelte'
  import Import from './screens/Import.svelte'
  import Backup from './screens/Backup.svelte'
  import Recover from './screens/Recover.svelte'
  import PullSync from './PullSync.svelte'
  import SyncStrip from './SyncStrip.svelte'
  import MBox from './ui/MBox.svelte'
  import MHint from './ui/MHint.svelte'
  import { runVault, startVault } from './vault/auto.svelte'
  import { tabIcon } from './tabicons'
  import Wordmark from '../components/Wordmark.svelte'
  import { syncPaused } from './network.svelte'
  import Welcome from './Welcome.svelte'
  import Coach from './Coach.svelte'
  import { loadOnb, onb } from './onboard.svelte'

  // the bottom bar: icon-only, Canvas between Library and Add (src/mobile/tabicons.ts draws them)
  const TABS: [Tab, string][] = [['lib', '#/lib'], ['cv', '#/canvas'], ['cap', '#/cap'], ['jv', '#/jv'], ['notes', '#/notes'], ['more', '#/more']]
  const r = $derived(phone.route)
  const title = $derived(r.item ? 'Item' : r.imp ? 'Import' : r.backup ? 'Backup & phones' : r.recover ? 'Recover a library' : TAB_NAME[r.tab])
  // PC (development, over USB) or Drive (the mirror); with no answer, the age of the phone's copy
  const L = source.label
  // "off" only when a call got no reply: a Drive that answers (a refusal, no library yet) is not offline. A paired
  // phone's state names the reason when it has one (mirror/phone-state.ts `lamp`: access removed, PC changed, ...)
  const st = $derived(phoneStatus())
  const lamp = $derived.by(() => {
    if (mirrorSource && syncPaused()) return 'Sync paused'
    if (phone.refreshing) return `${phone.online ? L : 'Offline'} · syncing`
    if (!phone.online) return phone.synced ? `Offline · copy ${fmtAgo(phone.synced)}` : 'Offline'
    if (st?.lamp) return `${L} · ${st.lamp}`
    if (phone.signIn) return `${L} · sign in`
    if (phone.noLibrary) return `${L} · no library yet`
    if (!phone.tried) return `${L} · connecting`
    if (phone.answered) return phone.synced ? `${L} · ${fmtAgo(phone.synced)}` : L
    return phone.synced ? `${L} off · copy ${fmtAgo(phone.synced)}` : `${L} off`
  })

  // a vault round once Google Drive has been read: the one at start may have found it not signed in yet (at most once a minute)
  $effect(() => { if (phone.synced && phone.reachable && mirrorSource && isApp) untrack(() => { runVault(false, true) }) })
  // the auto-keep settings (More > Keep automatically) run after each refresh from the mirror
  $effect(() => { if (phone.synced && phone.reachable && mirrorSource) untrack(() => { autoKeep() }) })

  // the first start (Welcome.svelte): not paired to a PC, an empty library on screen, no answer yet; a share
  // that opened the app on Add waits until the Library
  const welcome = $derived(onb.loaded && !onb.answer && (solo || !mirrorSource) && phone.loaded && !phone.rows.length && r.tab === 'lib' && !r.item)

  let main: HTMLElement | undefined = $state()

  // pull to refresh: a drag down that starts with the screen at its top shows the sync widget, and
  // letting go past the mark runs syncNow. Only the widget moves: the grid and its cards stay put.
  // Never on a canvas (one finger pans it), the Item card (the finger tilts it), a text field, or
  // inside a box that is itself scrolled down.
  const PULL_ARM = 64, PULL_SLOP = 10
  let pull = $state(0), pulling = false, x0 = 0, y0 = 0
  function canPull(target: EventTarget | null): boolean {
    if (!main || main.scrollTop > 0 || r.canvas || (phone.sync && !phone.sync.end) || phone.refreshing) return false
    const el = target instanceof Element ? target : null
    // only the Item card's slot: the Library grid is all cards (.m-cell .slot, pan-y), and a pull starts on one
    if (el?.closest('.m-it-stage .slot, input, textarea, select, [contenteditable]')) return false
    for (let n = el; n && n !== main; n = n.parentElement) if (n.scrollTop > 0) return false
    return true
  }
  function pullStart(e: TouchEvent) {
    pulling = e.touches.length === 1 && canPull(e.target)
    if (pulling) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY }
  }
  function pullMove(e: TouchEvent) {
    if (!pulling) return
    const t = e.touches[0], dx = t.clientX - x0, dy = t.clientY - y0
    // a scroll, a sideways swipe or a second finger: not a pull
    if (e.touches.length > 1 || main!.scrollTop > 0 || (!pull && (dy < -PULL_SLOP || Math.abs(dx) > Math.max(PULL_SLOP, dy)))) { pulling = false; pull = 0; return }
    pull = Math.max(0, dy - PULL_SLOP) / 2 / PULL_ARM
  }
  function pullEnd() {
    if (pulling && pull >= 1) syncNow()
    pulling = false; pull = 0
  }
  onMount(() => { boot() })
  onMount(() => { loadOnb() })
  onMount(startVault)              // vault sync rounds (Android app): foreground and every 2 minutes
  // Android's back button: leave only from the Library root; else one page back when the WebView has
  // one, else up to the screen's parent (a screen opened cold, or after a reload, has nothing behind it)
  onMount(() => {
    onBackButton(canGoBack => {
      const up = parentHash(phone.route)
      if (!up) exitApp()
      else if (canGoBack) history.back()
      else location.hash = up
    })
  })

  // What is shared to Brainamon becomes a DRAFT on the Add tab; nothing is created until Save
  // (projects/note-organic-ui/plans/09-add-to-brainamon.md). The service worker stores the draft itself
  // (manifest share_target, POST, then ?shared=1); the rest arrives here: the Android share sheet
  // (native.ts), or text the service worker could not store (?share_text=).
  const toAdd = () => { if (phone.route.tab !== 'cap') location.hash = '#/cap' }
  onMount(() => {
    const p = new URLSearchParams(location.search)
    // a service worker from before this build kept a shared file in kv 'shared-file': it becomes a draft too
    if (p.has('shared_file')) {
      history.replaceState(null, '', location.pathname + '#/cap')
      phone.route = { tab: 'cap' }
      kv.get<{ name: string; type: string; blob: Blob }>('shared-file').then(async s => {
        if (!s) return
        await kv.del('shared-file')
        await shareIn('', { name: s.name || 'shared', type: s.type, blob: s.blob })
      }).catch(() => {})
    }
    // the Android app: the share sheet hands a picture, PDF or text file over as base64 (BrainamonPlugin "sharedFile")
    onSharedFile(async s => {
      const name = fileName(s.name, s.type)
      if (s.error) cap.notice = s.error
      else if (!kindOf(name, s.type)) cap.notice = UNREADABLE
      else await shareIn('', { name, type: s.type, blob: new Blob([Uint8Array.from(atob(s.data), c => c.charCodeAt(0))], { type: s.type }) })
      toAdd()
    })
    if (p.has('shared')) {
      sessionStorage.setItem('bp-shared', '1')
      history.replaceState(null, '', location.pathname + '#/cap')
      phone.route = { tab: 'cap' }
    } else if (p.has('share_url') || p.has('share_text') || p.has('share_title')) {
      const text = [p.get('share_url'), p.get('share_text'), p.get('share_title')].filter(Boolean).join('\n')
      history.replaceState(null, '', location.pathname + '#/cap')
      phone.route = { tab: 'cap' }
      if (text) shareIn(text)
    }
    // the Android app: Android's share sheet hands the text over (native.ts)
    onShared(text => { shareIn(text).then(toAdd) })
  })
</script>

<div id="m-app" class:m-capturing={r.tab === 'cap'}>
  <header class="m-abar">
    {#if r.item || r.canvas || r.note || r.mynote || r.chats || r.imp || r.backup || r.recover}
      <button type="button" class="m-back" onclick={() => { if (r.backup || r.recover) location.hash = parentHash(r); else history.back() }} aria-label="Back">‹</button>
    {:else}
      <span class="m-logo"><Wordmark label="Brainamon" /></span>
    {/if}
    <span class="m-ws">{title}</span>
    <span class="m-sp"></span>
    <!-- a status, not a button (audit 2026-10-15 #17): pull down or More > Refresh syncs -->
    <span class="m-lamp" class:amber={!phone.online || !phone.answered || phone.noLibrary || !!st?.lamp} class:busy={phone.refreshing} role="status">{lamp}</span>
    <PullSync {pull} />
    <SyncStrip />
  </header>

  <main class="m-main" class:m-felt={r.tab === 'lib'} bind:this={main} ontouchstart={pullStart} ontouchmove={pullMove} ontouchend={pullEnd} ontouchcancel={() => { pulling = false; pull = 0 }}>
    {#if phone.tooOld && phone.rows.length}<MBox role="alert"><MHint as="p" tone="error">{UPDATE_APP}</MHint></MBox>{/if}
    {#if r.tab === 'lib'}
      {#if r.item}
        {#key r.item}<Item id={r.item} scroller={main} />{/key}
      {:else}
        <Library scroller={main} />
      {/if}
    {:else if r.tab === 'cv'}
      <Canvas id={r.canvas ?? null} />
    {:else if r.tab === 'cap'}
      <Capture />
    {:else if r.tab === 'jv'}
      <Wiskit chats={!!r.chats} />
    {:else if r.tab === 'notes'}
      <Notes file={r.note} myFile={r.mynote} synth={r.synth} />
    {:else if r.imp}
      <Import />
    {:else if r.backup}
      <Backup scroller={main} />
    {:else if r.recover}
      <Recover scroller={main} />
    {:else}
      <More />
    {/if}
  </main>

  <nav class="m-tabs" aria-label="Sections">
    {#each TABS as [tab, href] (tab)}
      <a class="m-tab" class:on={r.tab === tab} class:add={tab === 'cap'} {href} aria-label={TAB_NAME[tab]} title={TAB_NAME[tab]} aria-current={r.tab === tab ? 'page' : undefined}><svg class="px" viewBox="0 0 12 12" aria-hidden="true"><path fill="currentColor" d={tabIcon(tab, r.tab === tab)} /></svg></a>
    {/each}
  </nav>
  {#if welcome}<Welcome />{/if}
  <Coach hold={welcome} />
</div>
