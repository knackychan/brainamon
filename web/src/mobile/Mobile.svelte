<script lang="ts">
  // The phone shell (projects/phone-dock-shell): on the section pages (the Library grid, the Canvas list) the top
  // bar (TopBar.svelte: settings, the two sections, the sync key, search) and the dock (Dock.svelte: Notes, Ask
  // Wiskit, Add); Notes, Wiskit and Add open as full-screen sheets (Sheet.svelte) over the last section, which
  // stays mounted under them (shell.base); every other page keeps the app bar with its back arrow and title.
  // Screens are hash routes (src/mobile/state.svelte.ts parseRoute) so the Android back button works.
  import type { Snippet } from 'svelte'
  import { onMount, untrack } from 'svelte'
  import { boot, fmtAgo, mirrorSource, phone, phoneStatus, solo, source, syncNow, tabName } from './state.svelte'
  import { t } from '../lib/i18n/index.ts'
  import { autoKeep } from './offline.svelte'
  import { exitApp, isApp, onBackButton, onShared, onSharedFile } from './native'
  import { parentHash } from './back'
  import { isCompose, isSection, sheetOf, sheetSub } from './shell'
  import { installTraversalGuard } from './canvas/navigation'
  import { back, closeSheet, go, shell, up } from './shell.svelte'
  import { fileName, kindOf } from './files'
  import { cap, shareIn } from './capture.svelte'
  import { kv } from './store'
  import { UPDATE_APP } from './source/mirror'
  import Library from './screens/Library.svelte'
  import Item from './screens/Item.svelte'
  import ItemStrip from './ItemStrip.svelte'
  import Canvas from './screens/Canvas.svelte'
  import CanvasComposer from './screens/CanvasComposer.svelte'
  import Capture from './screens/Capture.svelte'
  import Wiskit from './screens/Wiskit.svelte'
  import Notes from './screens/Notes.svelte'
  import More from './screens/More.svelte'
  import Import from './screens/Import.svelte'
  import Backup from './screens/Backup.svelte'
  import Recover from './screens/Recover.svelte'
  import TopBar from './TopBar.svelte'
  import Dock from './Dock.svelte'
  import Sheet from './Sheet.svelte'
  import OwnerLine from './OwnerLine.svelte'
  import MBox from './ui/MBox.svelte'
  import MHint from './ui/MHint.svelte'
  import MKey from './ui/MKey.svelte'
  import ShellIcon from './ShellIcon.svelte'
  import CaptureKey from './CaptureKey.svelte'
  import { runVault, startVault } from './vault/auto.svelte'
  import { syncPaused } from './network.svelte'
  import Welcome from './Welcome.svelte'
  import Coach from './Coach.svelte'
  import { loadOnb, onb } from './onboard.svelte'

  const r = $derived(phone.route)
  const title = $derived(r.item ? t('shell.route.item') : r.imp ? t('shell.route.import') : r.save ? t('shell.route.save') : tabName(r.tab))
  // a section page (top bar and dock), or a sheet over the last one (shell.base); `under` is the screen in .m-main
  const section = $derived(isSection(r))
  const compose = $derived(isCompose(r))
  const sheet = $derived(sheetOf(r))
  const under = $derived(sheet ? shell.base : r.tab)
  $effect(() => { if (section) shell.base = r.tab === 'cv' ? 'cv' : 'lib' })
  // PC (development, over USB) or Drive (the mirror); with no answer, the age of the phone's copy. The words follow
  // the source kind; `source.label` stays the English name the source classes carry.
  const L = source.kind === 'mirror' ? t('shell.where.drive') : t('shell.where.pc')
  // "off" only when a call got no reply: a Drive that answers (a refusal, no library yet) is not offline. A paired
  // phone's state names the reason when it has one (mirror/phone-state.ts `lamp`: access removed, PC changed, ...).
  // The sentence is the sync key's name (SyncKey.svelte); `amber` is its "needs you" ring.
  const st = $derived(phoneStatus())
  const lamp = $derived.by(() => {
    if (mirrorSource && syncPaused()) return t('shell.lamp.paused')
    if (phone.refreshing) return phone.online ? t('shell.lamp.syncing', { where: L }) : t('shell.lamp.offlineSyncing')
    if (!phone.online) return phone.synced ? t('shell.lamp.offlineCopy', { ago: fmtAgo(phone.synced) }) : t('shell.lamp.offline')
    if (st?.lamp) return t('shell.lamp.joined', { where: L, text: st.lamp })
    if (phone.signIn) return t('shell.lamp.signIn', { where: L })
    if (phone.noLibrary) return t('shell.lamp.noLibrary', { where: L })
    if (!phone.tried) return t('shell.lamp.connecting', { where: L })
    if (phone.answered) return phone.synced ? t('shell.lamp.joined', { where: L, text: fmtAgo(phone.synced) }) : L
    return phone.synced ? t('shell.lamp.offCopy', { where: L, ago: fmtAgo(phone.synced) }) : t('shell.lamp.off', { where: L })
  })
  const amber = $derived(!phone.online || !phone.answered || phone.noLibrary || !!st?.lamp)

  // a vault round once Google Drive has been read: the one at start may have found it not signed in yet (at most once a minute)
  $effect(() => { if (phone.synced && phone.reachable && mirrorSource && isApp) untrack(() => { runVault(false, true) }) })
  // the auto-keep settings (Settings > Keep automatically) run after each refresh from the mirror
  $effect(() => { if (phone.synced && phone.reachable && mirrorSource) untrack(() => { autoKeep() }) })

  // the first start (Welcome.svelte): not paired to a PC, an empty library on screen, no answer yet; a share
  // that opened the app on Add waits until the Library
  const welcome = $derived(onb.loaded && !onb.answer && (solo || !mirrorSource) && phone.loaded && !phone.rows.length && r.tab === 'lib' && !r.item)

  let main: HTMLElement | undefined = $state()
  // the open Wiskit chat's name, shown after the bare sheet's tag (Sheet.svelte; plan 02 binds it from Wiskit.svelte)
  let jvName = $state('')
  // the Notes sheet's corner key: Notes.svelte hands its snippet up (the search on the root, the gem on a Knowledge
  // note; projects/phone-notes-manager)
  let notesCorner = $state<Snippet | undefined>()

  // pull to refresh: a drag down that starts with a section page at its top fills the sync key's ring
  // (SyncKey.svelte) and letting go past the mark runs syncNow; the page follows the finger a little (up to
  // 26 px) and springs back. Only on a section page, not in search, not while sync is paused or running; never
  // from a text field, or inside a box that is itself scrolled down.
  const PULL_ARM = 64, PULL_SLOP = 10
  let pull = $state(0), pulling = false, x0 = 0, y0 = 0
  $effect(() => { if (compose) { pulling = false; pull = 0; shell.base = 'cv' } })
  function canPull(target: EventTarget | null): boolean {
    if (!main || !section || r.search || main.scrollTop > 0 || (phone.sync && !phone.sync.end) || phone.refreshing) return false
    if (mirrorSource && syncPaused()) return false
    const el = target instanceof Element ? target : null
    if (el?.closest('input, textarea, select, [contenteditable]')) return false
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
  onMount(installTraversalGuard)
  onMount(() => { loadOnb() })
  onMount(startVault)              // vault sync rounds (Android app): foreground and every 2 minutes
  // Android's back button: a help dialog or the sync panel closes first; the app leaves only from the Library
  // root; a sheet's root closes the sheet; else one page back when the WebView has one, else up to the parent
  // (a screen opened cold, or after a reload, has nothing behind it)
  onMount(() => {
    onBackButton(canGoBack => {
      const help = [...document.querySelectorAll<HTMLDialogElement>('dialog.m-info-dialog[open], dialog.m-picker-sheet[open], dialog.m-dialog[open], dialog.m-cap-pop[open]')].at(-1)
      if (help) { if (help.dispatchEvent(new Event('cancel', { cancelable: true }))) help.close(); return }
      if (shell.panel) { shell.panel = false; return }
      if (!parentHash(phone.route, shell.base)) exitApp()
      else up(canGoBack)
    })
  })

  // What is shared to Brainamon becomes a DRAFT on the Add tab; nothing is created until Save
  // (projects/note-organic-ui/plans/09-add-to-brainamon.md). The service worker stores the draft itself
  // (manifest share_target, POST, then ?shared=1); the rest arrives here: the Android share sheet
  // (native.ts), or text the service worker could not store (?share_text=).
  const sharedToAdd = () => window.dispatchEvent(new Event('brainamon-compose-share'))
  const toAdd = () => {
    if (isCompose(phone.route)) { sharedToAdd(); return }
    if (phone.route.tab !== 'cap' || phone.route.imp) location.hash = '#/cap'
  }
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
      const stay = isCompose(phone.route)
      const name = fileName(s.name, s.type)
      if (s.error) cap.notice = t('capture.attachment.nativeError', { message: s.error })
      else if (!kindOf(name, s.type)) cap.notice = t('capture.attachment.unreadable')
      else await shareIn('', { name, type: s.type, blob: new Blob([Uint8Array.from(atob(s.data), c => c.charCodeAt(0))], { type: s.type }) })
      if (stay) sharedToAdd(); else toAdd()
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
    onShared(text => { const stay = isCompose(phone.route); shareIn(text).then(() => { if (stay) sharedToAdd(); else toAdd() }) })
  })
</script>

<div id="m-app" class:m-item={!!r.item}>
  {#if section || sheet}
    <TopBar label={lamp} {amber} {pull} />
  {:else if !r.item && !compose && r.tab !== 'more'}
    <!-- the canvas detail (#/canvas/<id>); Settings, Backup & phones and Recover draw their own keys (PageKeys.svelte) -->
    <header class="m-abar">
      <button type="button" class="m-back" onclick={() => history.back()} aria-label={t('common.back')}>‹</button>
      <span class="m-ws">{title}</span>
    </header>
  {/if}
  {#if !sheet}<OwnerLine />{/if}

  <main class="m-main" class:m-cp-main={compose} class:m-felt={under === 'lib'} class:m-docked={section || !!r.item} class:m-pulling={pull > 0} style:transform={pull > 0 ? `translateY(${Math.min(1, pull) * 26}px)` : undefined} bind:this={main} ontouchstart={pullStart} ontouchmove={pullMove} ontouchend={pullEnd} ontouchcancel={() => { pulling = false; pull = 0 }}>
    {#if phone.tooOld && phone.rows.length}<MBox role="alert"><MHint as="p" tone="error">{UPDATE_APP}</MHint></MBox>{/if}
    {#if r.item}
      {#key r.item}<Item id={r.item} scroller={main} />{/key}
    {:else if compose}
      <CanvasComposer id={r.add ? r.canvas! : null} />
    {:else if r.canvas}
      <Canvas id={r.canvas ?? null} />
    {:else if under === 'lib'}
      <Library scroller={main} />
    {:else if under === 'cv'}
      <Canvas id={null} />
    {:else if r.backup}
      <Backup scroller={main} />
    {:else if r.recover}
      <Recover scroller={main} />
    {:else}
      <More />
    {/if}
  </main>

  {#if section}<Dock away={!!r.search} />{/if}
  {#if r.item}<ItemStrip />{/if}
  {#if sheet}
    <Sheet kind={sheet} {title} sub={sheetSub(r)} capturing={sheet === 'cap' && !r.imp} bare={!!r.mynote} keys={sheet === 'jv' || sheet === 'cap' || (sheet === 'notes' && !r.mynote)} name={sheet === 'jv' ? jvName : ''}
      onback={() => { if (r.imp) go(parentHash(r, shell.base)); else back() }} onclose={closeSheet}>
      {#snippet corner()}
        {#if sheet === 'jv'}<MKey aria-label={t('shell.chats')} title={t('shell.chats')} tone={r.chats ? 'dark' : 'plain'} aria-pressed={!!r.chats} onclick={() => { if (r.chats) back(); else go('#/jv/chats') }}><ShellIcon name="rows" /></MKey>{:else if sheet === 'cap' && !r.imp && !r.save}<CaptureKey />{/if}{#if sheet === 'notes'}{@render notesCorner?.()}{/if}
      {/snippet}
      {#if sheet === 'cap'}
        {#if r.imp}
          <Import />
        {:else}
          <Capture />
        {/if}
      {:else if sheet === 'jv'}
        <Wiskit chats={!!r.chats} bind:name={jvName} />
      {:else}
        <Notes file={r.note} myFile={r.mynote} synth={r.synth} search={!!r.find} bind:corner={notesCorner} />
      {/if}
    </Sheet>
  {/if}
  {#if welcome}<Welcome />{/if}
  <Coach hold={welcome} />
</div>
